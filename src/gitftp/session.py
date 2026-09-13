"""Everything an action needs: repository, config, URL, credentials, connections."""

from __future__ import annotations

import os
from pathlib import Path

from gitftp import auth
from gitftp.changeset import remote_path
from gitftp.config import DEFAULT_DEPLOYED_SHA1_FILE, DEFAULT_JOBS, Config, validate_scope
from gitftp.errors import GitError, MissingArgumentError
from gitftp.gitrepo import GitRepo, GitRunner
from gitftp.options import CliOptions
from gitftp.output import Output
from gitftp.transport import registry
from gitftp.transport.base import Transport
from gitftp.url import RemoteURL, parse


class Session:
    def __init__(
        self,
        *,
        out: Output,
        git: GitRunner,
        repo: GitRepo | None,
        scope: str | None,
        cfg: Config,
        url: RemoteURL,
        creds: auth.Credentials,
        topts: registry.TransportOptions,
        jobs: int,
        deployed_sha1_file: str,
        syncroot: str,
        worktree: bool = False,
    ) -> None:
        self.out = out
        self.git = git
        self.repo = repo
        self.scope = scope
        self.cfg = cfg
        self.url = url
        self.creds = creds
        self.topts = topts
        self.jobs = jobs
        self.deployed_sha1_file = deployed_sha1_file
        self.syncroot = syncroot
        self.worktree = worktree
        self._connector = registry.connector(url, creds, topts, out)
        self._primary: Transport | None = None

    def log_settings(self) -> None:
        """Upstream's ``set_remotes`` diagnostics (printed with ``-v``)."""
        out = self.out
        out.debug(f"Host is '{self.url.host}'.")
        out.debug(f"User is '{self.creds.user}'.")
        out.debug("Password is set." if self.creds.password is not None else "No password is set.")
        if self.syncroot:
            out.debug(f"Syncroot is '{self.syncroot}'.")
        out.debug(f"Insecure is '{int(self.topts.insecure)}'.")
        if self.topts.disable_epsv:
            out.debug("Disable EPSV is '1'.")
        if self.jobs != DEFAULT_JOBS:
            out.debug(f"Jobs is '{self.jobs}'.")

    def connect(self) -> Transport:
        return self._connector()

    @property
    def primary(self) -> Transport:
        if self._primary is None:
            self._primary = self.connect()
        return self._primary

    def close(self) -> None:
        if self._primary is not None:
            try:
                self._primary.close()
            finally:
                self._primary = None

    def require_repo(self) -> GitRepo:
        if self.repo is None:
            raise GitError("Not a Git project? Exiting...")
        return self.repo

    def for_submodule(self, sub_path: str) -> Session:
        """A session for a submodule at git path ``sub_path`` (inside the syncroot)."""
        repo = self.require_repo()
        sub_root = repo.root / sub_path
        sub_repo = GitRepo(sub_root)
        cfg = Config.load(sub_repo, sub_root, self.scope)
        session = Session(
            out=self.out,
            git=sub_repo,
            repo=sub_repo,
            scope=self.scope,
            cfg=cfg,
            url=self.url.child(remote_path(sub_path, self.syncroot)),
            creds=self.creds,
            topts=self.topts,
            jobs=self.jobs,
            deployed_sha1_file=cfg.get("deployedsha1file", DEFAULT_DEPLOYED_SHA1_FILE),
            syncroot="",
            worktree=self.worktree,
        )
        session.log_settings()
        return session


def resolve_syncroot(repo: GitRepo | None, value: str) -> str:
    value = value.replace("\\", "/")
    while value.startswith("./"):
        value = value[2:]
    value = value.strip("/")
    if not value or value == ".":
        return ""
    if repo is not None and not (repo.root / value).is_dir():
        raise GitError(f"'{value}' is not a directory! Exiting...")
    return value + "/"


def open_session(
    opts: CliOptions,
    url_arg: str | None,
    out: Output,
    *,
    cwd: Path | None = None,
    need_repo: bool = True,
    need_url: bool = True,
) -> Session:
    cwd = cwd or Path.cwd()
    git = GitRunner(cwd)
    git.check_version()

    repo: GitRepo | None
    if need_repo:
        repo = GitRepo.discover(cwd)
    else:
        try:
            repo = GitRepo.discover(cwd)
        except GitError:
            repo = None

    scope: str | None = None
    if opts.scope is not None:
        if opts.scope:
            scope = opts.scope
        elif repo is not None:
            scope = repo.current_branch()
        else:
            raise MissingArgumentError("Missing scope argument.")
        validate_scope(scope, from_option=True)

    cfg = Config.load(git, repo.root if repo else None, scope)

    raw_url = url_arg or os.environ.get("GIT_FTP_URL") or cfg.get("url")
    if not raw_url:
        if need_url:
            raise MissingArgumentError("Remote host not set.")
        raw_url = "ftp://localhost"
    url = parse(raw_url)
    remote_root = opts.remote_root if opts.remote_root is not None else cfg.get("remote-root")
    if remote_root:
        url.set_path(remote_root)

    creds = auth.resolve(cfg, url, opts.auth_flags(), out)
    # Messages show the resolved login as upstream does (``user:***@host``); the
    # password itself is never placed in the URL.
    url.user = creds.user or None
    url.password = None

    insecure = opts.insecure or cfg.get_bool("insecure")
    cacert = None
    for candidate in (opts.cacert, cfg.get("cacert")):
        if candidate and os.access(candidate, os.R_OK):
            cacert = candidate
            break
    disable_epsv = (not opts.active) and (opts.disable_epsv or cfg.get_bool("disable-epsv"))
    proxy = opts.proxy or cfg.get("proxy") or cfg.git_option("http.proxy") or None
    topts = registry.TransportOptions(
        insecure=insecure,
        cacert=cacert,
        active=opts.active,
        disable_epsv=disable_epsv,
        proxy=proxy,
        trace=out.trace if out.tracing else None,
    )

    jobs = opts.jobs if opts.jobs is not None else cfg.get_int("jobs", DEFAULT_JOBS)
    syncroot = resolve_syncroot(
        repo, opts.syncroot if opts.syncroot is not None else cfg.get("syncroot")
    )
    deployed_sha1_file = cfg.get("deployedsha1file", DEFAULT_DEPLOYED_SHA1_FILE)
    worktree = opts.worktree or cfg.get_bool("worktree")

    session = Session(
        out=out,
        git=git,
        repo=repo,
        scope=scope,
        cfg=cfg,
        url=url,
        creds=creds,
        topts=topts,
        jobs=max(1, jobs),
        deployed_sha1_file=deployed_sha1_file,
        syncroot=syncroot,
        worktree=worktree,
    )
    session.log_settings()
    return session
