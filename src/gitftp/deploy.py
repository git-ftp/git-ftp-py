"""The init / push / catchup engine, step for step as upstream's ``action_push``."""

from __future__ import annotations

import enum
from dataclasses import dataclass, field
from pathlib import Path

from gitftp import changeset as csmod
from gitftp.errors import (
    Aborted,
    DownloadError,
    GitError,
    GitFtpError,
    HookError,
    UploadError,
    UsageError,
)
from gitftp.gitrepo import UnknownCommit
from gitftp.hooks import POST_PUSH, PRE_PUSH, run_hook
from gitftp.lock import RemoteLock
from gitftp.options import CliOptions
from gitftp.progress import Progress
from gitftp.session import Session
from gitftp.transfer import DeleteTask, TransferError, TransferPool, UploadTask
from gitftp.transport import registry
from gitftp.transport.base import RemoteNotFound


class Action(enum.Enum):
    INIT = "init"
    PUSH = "push"
    CATCHUP = "catchup"


@dataclass
class DeployOptions:
    force: bool = False
    dry_run: bool = False
    all: bool = False
    auto_init: bool = False
    commit: str | None = None
    branch: str | None = None
    lock: bool = False
    no_verify: bool = False
    no_post_hooks: bool = False
    enable_post_errors: bool = False

    @classmethod
    def from_cli(cls, opts: CliOptions) -> DeployOptions:
        return cls(
            force=opts.force,
            dry_run=opts.dry_run,
            all=opts.all,
            auto_init=opts.auto_init,
            commit=opts.commit,
            branch=opts.branch,
            lock=opts.lock,
            no_verify=opts.no_verify,
            no_post_hooks=opts.no_post_hooks,
            enable_post_errors=opts.enable_post_errors,
        )

    def for_submodule(self) -> DeployOptions:
        """What upstream forwards to the recursive invocation (always ``--force``)."""
        return DeployOptions(force=True, dry_run=self.dry_run, all=self.all)


@dataclass
class DeployResult:
    local_sha: str
    deployed_sha: str | None
    uploaded: list[str] = field(default_factory=list)
    deleted: list[str] = field(default_factory=list)
    up_to_date: bool = False


def run(action: Action, session: Session, opts: DeployOptions) -> DeployResult:
    return _Run(action, session, opts).run()


class _Run:
    def __init__(self, action: Action, session: Session, opts: DeployOptions) -> None:
        self.action = action
        self.session = session
        self.opts = opts
        self.out = session.out
        self.repo = session.require_repo()
        self.url = session.url
        self._source_root: Path = self.repo.root

    # -- entry -------------------------------------------------------------
    def run(self) -> DeployResult:
        self.session.git.check_version()
        if self.repo.is_dirty():
            raise GitError("Dirty repository: Having uncommitted changes. Exiting...")
        original_branch: str | None = None
        branch = self.opts.branch or self.session.cfg.get("branch")
        if branch:
            original_branch = self.repo.current_branch()
            if not self.repo.checkout(branch):
                raise GitError(f"'{branch}' is not a valid branch! Exiting...")
        try:
            registry.check_available(self.url.scheme)
            if self.action is Action.CATCHUP:
                return self._catchup()
            return self._deploy()
        finally:
            if original_branch:
                self.repo.checkout(original_branch)

    # -- catchup -----------------------------------------------------------
    def _catchup(self) -> DeployResult:
        local = self.repo.head_sha()
        self._upload_log(local, None)
        for sub, initialised in self.repo.submodules(self.session.syncroot).items():
            if not initialised:
                continue
            self.out.info(f"Catching up submodule {sub}.")
            subsession = self.session.for_submodule(sub)
            try:
                run(Action.CATCHUP, subsession, self.opts.for_submodule())
            finally:
                subsession.close()
        return DeployResult(local_sha=local, deployed_sha=None)

    # -- init / push -------------------------------------------------------
    def _deploy(self) -> DeployResult:
        deployed, take_all = self._deployed_sha()
        local = self.repo.head_sha()
        cs = self._changeset(deployed, take_all, local)
        if cs is None:
            self.out.info(f"No changed files for {self.url.name()}. Everything up-to-date.")
            return DeployResult(local_sha=local, deployed_sha=deployed, up_to_date=True)

        scope_or_host = self.session.scope or self.url.host
        if not self.opts.no_verify:
            rc = run_hook(
                self.repo,
                PRE_PUSH,
                [scope_or_host, self.url.display(), local, deployed or ""],
                cs.hook_status(),
                self.out,
            )
            if rc:
                raise HookError(f"{PRE_PUSH} hook failed with exit code {rc}.")

        lock = RemoteLock(
            self.session.primary,
            local,
            enabled=self.opts.lock,
            force=self.opts.force,
            dry_run=self.opts.dry_run,
            out=self.out,
        )
        lock.acquire()
        try:
            self._run_sync(cs, local)
            self._upload_log(local, deployed)
        finally:
            lock.release()

        if not self.opts.no_post_hooks:
            rc = run_hook(
                self.repo,
                POST_PUSH,
                [scope_or_host, self.url.display(), local, deployed or ""],
                b"",
                self.out,
            )
            if rc:
                if self.opts.enable_post_errors:
                    raise HookError(f"{POST_PUSH} hook failed with exit code {rc}.")
                self.out.debug(f"{POST_PUSH} hook failed with exit code {rc}, ignoring.")
        return DeployResult(
            local_sha=local, deployed_sha=deployed, uploaded=cs.uploads, deleted=cs.deletes
        )

    def _deployed_sha(self) -> tuple[str | None, bool]:
        s = self.session
        log_file = s.deployed_sha1_file
        if self.action is Action.INIT:
            self.out.debug(f"Checking remote access to {self.url.display()}.")
            try:
                s.primary.mkdir_p("")
                data = s.primary.get(log_file)
            except RemoteNotFound:
                data = b""
            except DownloadError as e:
                raise UploadError(str(e)) from e
            if data.strip():
                raise UsageError("Commit found, use 'git ftp push' to sync. Exiting...")
            return None, True

        if self.opts.commit:
            self.out.debug(f"Using commit {self.opts.commit} as the last deployed commit.")
            return self.opts.commit, self.opts.all

        self.out.debug(f"Retrieving last commit from {self.url.display()}.")
        try:
            data = s.primary.get(log_file)
        except RemoteNotFound:
            data = b""
        except DownloadError as e:
            raise DownloadError(f"Could not get last commit from {self.url.display()}. {e}") from e
        deployed = data.decode("utf-8", "replace").strip().split("\n")[0].strip()
        if not deployed:
            if self.opts.auto_init:
                s.primary.mkdir_p("")
                self.out.debug(
                    f"Uploading all files since no commit was found at {self.url.display()}."
                )
                return None, True
            raise DownloadError(
                "Could not get last commit. Use 'git ftp init' for the initial push."
            )
        self.out.debug(f"Last deployed SHA1 for {self.url.name()} is {deployed}.")
        return deployed, self.opts.all

    def _changeset(
        self, deployed: str | None, take_all: bool, local: str
    ) -> csmod.ChangeSet | None:
        repo, syncroot, out = self.repo, self.session.syncroot, self.out
        if not take_all and deployed == local:
            return None
        try:
            return csmod.build(repo, syncroot, deployed, take_all, out)
        except UnknownCommit:
            pass
        if self.opts.force:
            out.info("Unknown SHA1 object, could not determine changed files, taking all files.")
            return csmod.build(repo, syncroot, deployed, True, out)
        out.info(
            "Unknown SHA1 object, make sure you are deploying the right branch "
            "and it is up-to-date."
        )
        answer = out.ask("Do you want to ignore and upload all files again? [y/N]: ")
        if answer == "":
            out.info("Aborting...")
            raise UsageError("")
        if answer.lower() != "y":
            out.info("Aborting...")
            raise Aborted()
        return csmod.build(repo, syncroot, deployed, True, out)

    def _run_sync(self, cs: csmod.ChangeSet, local: str) -> None:
        """Read the upload from a temporary worktree when ``--worktree`` is set."""
        if self.session.worktree and not self.opts.dry_run and cs.uploads:
            self.out.debug("Creating a temporary worktree for a consistent upload.")
            with self.repo.temporary_worktree(local) as tree:
                self._source_root = tree
                try:
                    self._sync(cs)
                finally:
                    self._source_root = self.repo.root
        else:
            self._sync(cs)

    def _source(self, path: str) -> Path:
        """Where to read the bytes of ``path`` from.

        Tracked files come from the worktree (``_source_root``); an untracked file
        added by ``.git-ftp-include`` is not in the commit, so it falls back to the
        live working tree.
        """
        candidate = self._source_root / path
        return candidate if candidate.exists() else self.repo.root / path

    def _sync(self, cs: csmod.ChangeSet) -> None:
        out, s = self.out, self.session
        total = cs.total()
        if total == 0:
            out.info("There are no files to sync.")
            return
        out.info(f"{total} file{'s' if total != 1 else ''} to sync:")
        done = 0
        uploads: list[UploadTask] = []
        for path in cs.uploads:
            done += 1
            out.info(f"[{done} of {total}] Buffered for upload '{path}'.")
            if path in cs.submodules:
                self._sync_submodule(path)
                continue
            local = self._source(path)
            if local.is_dir():
                out.debug(f"Skipping directory '{path}'.")
                continue
            uploads.append(
                UploadTask(
                    local=local,
                    remote=csmod.remote_path(path, s.syncroot),
                    size=local.stat().st_size,
                    label=path,
                )
            )
        deletes: list[DeleteTask] = []
        with TransferPool(s.connect, s.jobs, out, primary=s.primary) as pool:
            if uploads and not self.opts.dry_run:
                out.info("Uploading ...")
                try:
                    with Progress(out, "Uploading", len(uploads)) as p:
                        pool.upload(uploads, on_done=p.advance)
                except TransferError as e:
                    raise UploadError(f"Could not upload files. {e}") from e
            for path in cs.deletes:
                done += 1
                out.info(f"[{done} of {total}] Buffered for delete '{path}'.")
                deletes.append(DeleteTask(remote=csmod.remote_path(path, s.syncroot), label=path))
            if deletes and not self.opts.dry_run:
                out.info("Deleting ...")
                with Progress(out, "Deleting", len(deletes)) as p:
                    errors = pool.delete(deletes, on_done=p.advance)
                for err in errors:
                    out.debug(f"Could not delete {err.label}, continuing... ({err.cause})")
                if errors:
                    out.warn("Some files and/or directories could not be deleted.")

    def _sync_submodule(self, path: str) -> None:
        display = csmod.remote_path(path, self.session.syncroot)
        self.out.info(f"Handling submodule sync for {display}.")
        subsession = self.session.for_submodule(path)
        sub_opts = self.opts.for_submodule()
        try:
            try:
                run(self.action, subsession, sub_opts)
            except DownloadError:
                if self.action is not Action.PUSH:
                    raise
                self.out.info(f"Could not push {display}, trying to init...")
                run(Action.INIT, subsession, sub_opts)
        except GitFtpError as e:
            raise UploadError(f"Failed to sync submodules. ({e})") from e
        finally:
            subsession.close()

    def _upload_log(self, local: str, deployed: str | None) -> None:
        s, out = self.session, self.out
        out.debug(f"Uploading commit log to {self.url.display()}{s.deployed_sha1_file}.")
        if not self.opts.dry_run:
            try:
                s.primary.put_bytes(f"{local}\n".encode(), s.deployed_sha1_file)
            except (UploadError, DownloadError) as e:
                raise UploadError(f"Could not upload. {e}") from e
        out.info(f"Last deployment changed from {deployed or ''} to {local}.")
