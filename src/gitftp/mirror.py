"""Native download / pull / snapshot (upstream used ``lftp mirror``)."""

from __future__ import annotations

import os
import shutil
from dataclasses import dataclass, field
from pathlib import Path

from gitftp import deploy
from gitftp.changeset import remote_path
from gitftp.errors import DownloadError, FilesystemError, GitError, UsageError
from gitftp.gitrepo import GitRepo
from gitftp.ignore import IgnoreRules
from gitftp.lock import LOCK_FILE, RemoteLock
from gitftp.options import CliOptions
from gitftp.output import Output
from gitftp.session import Session, open_session
from gitftp.transfer import DownloadTask, TransferError, TransferPool
from gitftp.transport import registry
from gitftp.transport.base import Entry, RemoteNotFound, Transport

PROTECTED = frozenset({".git", ".git-ftp-ignore", ".git-ftp-include", ".git-ftp-config", LOCK_FILE})
PART_SUFFIX = ".git-ftp-part"


@dataclass
class MirrorOptions:
    dry_run: bool = False
    changed_only: bool = False
    lock: bool = False
    force: bool = False
    no_commit: bool = False

    @classmethod
    def from_cli(cls, opts: CliOptions) -> MirrorOptions:
        return cls(
            dry_run=opts.dry_run,
            changed_only=opts.changed_only,
            lock=opts.lock,
            force=opts.force,
            no_commit=opts.no_commit,
        )


@dataclass
class MirrorPlan:
    downloads: list[DownloadTask] = field(default_factory=list)
    local_deletes: list[Path] = field(default_factory=list)
    mkdirs: list[Path] = field(default_factory=list)
    probes: list[str] = field(default_factory=list)


# -- scanning -----------------------------------------------------------------
def scan_remote(pool: TransferPool, out: Output) -> dict[str, Entry]:
    """Recursive listing: ``rel`` -> Entry, directories keyed with a trailing '/'."""
    result: dict[str, Entry] = {}
    level = [""]
    while level:

        def list_one(t: Transport, d: str) -> list[Entry]:
            return t.list_dir(d)

        listings = pool.map(list_one, level, fail_fast=True, label=lambda d: d or "/")
        next_level: list[str] = []
        for directory, entries in zip(level, listings, strict=True):
            if not isinstance(entries, list):
                continue
            for e in entries:
                rel = f"{directory}{e.name}"
                if e.is_dir:
                    result[rel + "/"] = e
                    next_level.append(rel + "/")
                else:
                    result[rel] = e
        level = next_level
        out.debug(f"Listed {len(result)} remote entries so far.")
    return result


def scan_local(base: Path) -> dict[str, os.stat_result]:
    result: dict[str, os.stat_result] = {}
    if not base.is_dir():
        return result
    for dirpath, dirnames, filenames in os.walk(base):
        dirnames[:] = [d for d in dirnames if d != ".git"]
        rel_dir = Path(dirpath).relative_to(base).as_posix()
        prefix = "" if rel_dir == "." else rel_dir + "/"
        for d in dirnames:
            result[f"{prefix}{d}/"] = os.lstat(Path(dirpath, d))
        for f in filenames:
            result[f"{prefix}{f}"] = os.lstat(Path(dirpath, f))
    return result


def _excluded(rel: str, syncroot: str, ignore: IgnoreRules, deployed_file: str) -> bool:
    parts = rel.strip("/").split("/")
    if any(p == ".git" for p in parts):
        return True
    if rel in (deployed_file, deployed_file + "/"):
        return True
    if parts[-1] in PROTECTED and len(parts) == 1:
        return True
    if parts[-1].endswith(PART_SUFFIX):
        return True
    candidate = rel.rstrip("/")
    return ignore.matches(syncroot + candidate) or ignore.matches(candidate)


def build_plan(
    remote: dict[str, Entry],
    local: dict[str, os.stat_result],
    *,
    base: Path,
    syncroot: str,
    ignore: IgnoreRules,
    deployed_file: str,
    only: set[str] | None,
    allow_delete: bool,
    protected: set[str] | None = None,
) -> MirrorPlan:
    plan = MirrorPlan()
    protected = protected or set()
    conflicts: list[Path] = []
    for rel, entry in remote.items():
        if _excluded(rel, syncroot, ignore, deployed_file):
            continue
        if entry.is_dir:
            if rel not in local:
                if rel.rstrip("/") in local:
                    conflicts.append(base / rel.rstrip("/"))
                plan.mkdirs.append(base / rel.rstrip("/"))
            continue
        if only is not None and rel not in only:
            continue
        st = local.get(rel)
        if rel + "/" in local:
            conflicts.append(base / rel)
            st = None
        task = DownloadTask(
            remote=rel, local=base / rel, size=entry.size, mtime=entry.mtime, label=rel
        )
        if st is None or (entry.size is not None and entry.size != st.st_size):
            plan.downloads.append(task)
        elif entry.mtime is not None and entry.mtime_exact:
            if entry.mtime > int(st.st_mtime) + 1:
                plan.downloads.append(task)
        else:
            plan.probes.append(rel)
    if allow_delete:
        for rel in local:
            if _excluded(rel, syncroot, ignore, deployed_file):
                continue
            if only is not None or rel.rstrip("/") in protected:
                continue
            if rel in remote:
                continue
            if rel.endswith("/"):
                # Only delete a directory when it does not exist remotely at all.
                plan.local_deletes.append(base / rel.rstrip("/"))
            elif rel + "/" in remote:
                continue  # handled as a conflict
            else:
                plan.local_deletes.append(base / rel)
    plan.local_deletes = conflicts + plan.local_deletes
    plan.downloads.sort(key=lambda t: t.remote)
    plan.mkdirs.sort()
    return plan


def _safe_remove(target: Path, base: Path) -> None:
    resolved = target.resolve()
    root = base.resolve()
    if resolved == root or root not in resolved.parents:
        raise FilesystemError(f"Refusing to delete '{target}' outside of '{base}'.")
    if ".git" in resolved.relative_to(root).parts:
        raise FilesystemError(f"Refusing to delete '{target}' inside .git.")
    if target.is_dir() and not target.is_symlink():
        shutil.rmtree(target)
    else:
        target.unlink()


def apply_plan(
    plan: MirrorPlan, pool: TransferPool, base: Path, out: Output, dry_run: bool
) -> None:
    if dry_run:
        for p in plan.local_deletes:
            out.info(f"Would delete local '{p.relative_to(base).as_posix()}'.")
        for p in plan.mkdirs:
            out.info(f"Would create directory '{p.relative_to(base).as_posix()}'.")
        for t in plan.downloads:
            out.info(f"Would download '{t.label}'.")
        return
    deleted = 0
    seen: set[Path] = set()
    for p in sorted(plan.local_deletes, key=lambda x: (-len(x.parts), str(x))):
        if p in seen or not (p.exists() or p.is_symlink()):
            continue
        seen.add(p)
        _safe_remove(p, base)
        deleted += 1
    for d in plan.mkdirs:
        d.mkdir(parents=True, exist_ok=True)
    if plan.downloads:
        try:
            pool.download(plan.downloads)
        except TransferError as e:
            raise DownloadError(f"Could not download files. {e}") from e
    out.info(f"Downloaded {len(plan.downloads)} file(s), deleted {deleted} local file(s).")


def download_remote_updates(session: Session, opts: MirrorOptions, only: set[str] | None) -> None:
    repo = session.require_repo()
    out = session.out
    base = repo.root / session.syncroot if session.syncroot else repo.root
    ignore = IgnoreRules.load(repo.root)
    with TransferPool(session.connect, session.jobs, out, primary=session.primary) as pool:
        out.debug(f"Mirroring {session.url.name()}")
        try:
            remote = scan_remote(pool, out)
        except TransferError as e:
            if isinstance(e.cause, RemoteNotFound):
                raise DownloadError(
                    f"Remote directory '{session.url.display()}' does not exist."
                ) from e
            raise DownloadError(f"Could not list '{session.url.display()}'. {e.cause}") from e
        local = scan_local(base)
        # Local files git ignores (build output, secrets) are never deleted by a mirror.
        git_ignored = repo.ignored([f"{session.syncroot}{rel.rstrip('/')}" for rel in local])
        plan = build_plan(
            remote,
            local,
            base=base,
            syncroot=session.syncroot,
            ignore=ignore,
            deployed_file=session.deployed_sha1_file,
            only=only,
            allow_delete=not opts.changed_only,
            protected={p[len(session.syncroot) :] for p in git_ignored},
        )
        if plan.probes:

            def probe(t: Transport, rel: str) -> Entry | None:
                return t.stat(rel)

            stats = pool.map(probe, plan.probes, fail_fast=True, label=str)
            for rel, st in zip(plan.probes, stats, strict=True):
                if not isinstance(st, Entry) or st.mtime is None:
                    continue
                lst = local[rel]
                if st.mtime > int(lst.st_mtime) + 1:
                    plan.downloads.append(
                        DownloadTask(
                            remote=rel, local=base / rel, size=st.size, mtime=st.mtime, label=rel
                        )
                    )
            plan.downloads.sort(key=lambda t: t.remote)
        apply_plan(plan, pool, base, out, opts.dry_run)


def _deployed_sha(session: Session) -> str:
    try:
        data = session.primary.get(session.deployed_sha1_file)
    except RemoteNotFound as e:
        raise DownloadError(
            "Could not get last commit. Use 'git ftp init' for the initial push."
        ) from e
    sha = data.decode("utf-8", "replace").strip()
    if not sha:
        raise DownloadError("Could not get last commit. Use 'git ftp init' for the initial push.")
    return sha


def _changed_only(repo: GitRepo, session: Session, a: str, b: str | None) -> set[str]:
    names = repo.diff_names_between(a, b)
    only = {remote_path(n, session.syncroot) for n in names}
    session.out.debug("Only pulling diff files:\n" + "\n".join(sorted(only)))
    return only


# -- actions ------------------------------------------------------------------
def run_download(session: Session, opts: MirrorOptions) -> None:
    repo = session.require_repo()
    registry.check_available(session.url.scheme)
    if repo.is_dirty():
        raise GitError("Dirty repository: Having uncommitted changes. Exiting...")
    if repo.has_any_changes():
        raise GitError("Dirty repository: Having untracked files. Exiting...")
    local = repo.head_sha()
    only = None
    if opts.changed_only:
        only = _changed_only(repo, session, _deployed_sha(session), None)
    lock = RemoteLock(
        session.primary,
        local,
        enabled=opts.lock,
        force=opts.force,
        dry_run=opts.dry_run,
        out=session.out,
    )
    lock.acquire()
    try:
        download_remote_updates(session, opts, only)
    finally:
        lock.release()


def run_pull(session: Session, opts: MirrorOptions) -> None:
    repo = session.require_repo()
    out = session.out
    registry.check_available(session.url.scheme)
    if repo.is_dirty():
        raise GitError("Dirty repository: Having uncommitted changes. Exiting...")
    current = repo.current_branch()
    deployed = _deployed_sha(session)
    out.debug(f"Last deployed SHA1 for {session.url.name()} is {deployed}.")
    only = _changed_only(repo, session, current, deployed) if opts.changed_only else None
    if not repo.checkout(deployed):
        raise GitError(f"Could not checkout {deployed}.")
    stashed = False
    new = deployed
    try:
        stashed = repo.stash_push_untracked()
        lock = RemoteLock(
            session.primary,
            deployed,
            enabled=opts.lock,
            force=opts.force,
            dry_run=opts.dry_run,
            out=out,
        )
        lock.acquire()
        try:
            download_remote_updates(session, opts, only)
        finally:
            lock.release()
        if not opts.dry_run:
            repo.add_all()
            if repo.has_any_changes():
                body = repo.diff_head_name_status()
                if repo.commit("[git-ftp] remotely untracked modifications", body):
                    new = repo.head_sha()
            out.debug(
                f"Uploading commit log to {session.url.display()}{session.deployed_sha1_file}."
            )
            session.primary.put_bytes(f"{new}\n".encode(), session.deployed_sha1_file)
            out.info(f"Last deployment changed from {deployed} to {new}.")
    finally:
        if stashed:
            proc = repo.run("stash", "pop", "-q", ok_codes=())
            if proc.returncode != 0:
                out.warn("Could not restore the stash; run 'git stash pop' yourself.")
        repo.checkout(current)
    if opts.dry_run:
        return
    out.info(f"From {session.url.name()}")
    out.info(f"   {deployed}..{new}")
    no_commit = opts.no_commit or session.cfg.get_bool("no-commit")
    if repo.merge(new, no_commit) != 0:
        raise GitError("Merge failed.")


def run_snapshot(cli: CliOptions, url_arg: str | None, directory: str | None, out: Output) -> None:
    session = open_session(cli, url_arg, out, need_repo=False, need_url=False)
    if not (url_arg or os.environ.get("GIT_FTP_URL") or session.cfg.get("url")):
        raise UsageError("Error: give a URL to snapshot.")
    registry.check_available(session.url.scheme)
    raw = url_arg or os.environ.get("GIT_FTP_URL") or session.cfg.get("url")
    target = directory or (raw.rstrip("/").rsplit("/", 1)[-1] if "/" in raw.rstrip("/") else "")
    if not target or "://" in target:
        target = session.url.hostname
    try:
        try:
            data = session.primary.get(session.deployed_sha1_file)
        except RemoteNotFound:
            data = b""
        if data.strip():
            raise UsageError(
                f"Commit found at {session.url.display()}{session.deployed_sha1_file}.\n"
                "The remote directory is managed by another Git repository already.\n"
                "Use 'git ftp pull' inside that repository to download the remote changes,\n"
                "or delete the file on the server to start a new snapshot."
            )
        dest = Path(target).absolute()
        try:
            dest.mkdir(parents=True, exist_ok=True)
        except OSError as e:
            raise FilesystemError(f"Error creating directory '{target}'. Aborting.") from e
        if any(dest.iterdir()):
            raise FilesystemError(
                f"Error: The destination directory '{target}' is not empty. Aborting."
            )
        repo = GitRepo.init(dest)
        session.repo = repo
        session.git = repo
        session.syncroot = ""
        download_remote_updates(session, MirrorOptions(), None)
        try:
            repo.add_dot()
        except GitError as e:
            raise GitError("Git: error adding changed files") from e
        if not repo.commit(f"Download {session.url.display()} with git-ftp", allow_empty=True):
            raise GitError("Git: error committing the changes")
        deploy.run(deploy.Action.CATCHUP, session, deploy.DeployOptions())
    finally:
        session.close()


def run_unlock(session: Session) -> None:
    registry.check_available(session.url.scheme)
    session.primary.delete(LOCK_FILE)
    session.out.info("Remote lock removed.")
