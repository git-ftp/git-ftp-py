"""Git access through the ``git`` binary.

Nothing here changes the working directory: every command receives ``cwd``.
Upstream ran ``set_syncroot`` before ``cd``-ing to the top level, which broke
invocations from a subdirectory; here paths are always resolved from
:attr:`GitRepo.root`.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import tempfile
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from pathlib import Path

from gitftp.errors import GitError

MIN_GIT_VERSION = (1, 7, 0)


class UnknownCommit(Exception):
    """A diff against a commit git does not know."""


class GitRunner:
    """Run git commands in a directory (which need not be a repository)."""

    def __init__(self, cwd: Path) -> None:
        self.cwd = Path(cwd)

    def run(
        self,
        *args: str,
        input: bytes | None = None,
        ok_codes: Sequence[int] = (0,),
        inherit_stdio: bool = False,
    ) -> subprocess.CompletedProcess[bytes]:
        env = dict(os.environ)
        env["LC_ALL"] = "C"
        try:
            proc = subprocess.run(
                ["git", *args],
                cwd=self.cwd,
                input=input,
                env=env,
                stdin=None if inherit_stdio or input is not None else subprocess.DEVNULL,
                stdout=None if inherit_stdio else subprocess.PIPE,
                stderr=None if inherit_stdio else subprocess.PIPE,
                check=False,
            )
        except FileNotFoundError as e:
            raise GitError("git is not installed or not on PATH.") from e
        if ok_codes and proc.returncode not in ok_codes:
            err = (proc.stderr or b"").decode("utf-8", "replace").strip()
            raise GitError(f"git {args[0]} failed: {err or proc.returncode}")
        return proc

    def out(self, *args: str, ok_codes: Sequence[int] = (0,)) -> str:
        return self.run(*args, ok_codes=ok_codes).stdout.decode("utf-8", "surrogateescape")

    def check_version(self) -> None:
        text = self.out("--version")
        m = re.search(r"(\d+)\.(\d+)(?:\.(\d+))?", text)
        if not m:
            return
        ver = (int(m.group(1)), int(m.group(2)), int(m.group(3) or 0))
        if ver < MIN_GIT_VERSION:
            wanted = ".".join(str(n) for n in MIN_GIT_VERSION)
            raise GitError(f"Git is too old, {wanted} or higher supported only.")

    # -- config ------------------------------------------------------------
    def config_list(self, file: Path | None = None) -> dict[str, str | None]:
        """``git config --list -z`` as a mapping; ``None`` marks a valueless key."""
        args = ["config"]
        if file is not None:
            args += ["-f", str(file)]
        args += ["--list", "-z"]
        proc = self.run(*args, ok_codes=(0, 128))
        result: dict[str, str | None] = {}
        for item in proc.stdout.split(b"\0"):
            if not item:
                continue
            text = item.decode("utf-8", "surrogateescape")
            key, has_value, value = text.partition("\n")
            result[_normalise_key(key)] = value if has_value else None
        return result

    def config_set(self, key: str, value: str, file: Path | None = None) -> None:
        args = ["config"]
        if file is not None:
            args += ["-f", str(file)]
        self.run(*args, "--", key, value)

    def config_remove_section(self, section: str) -> bool:
        proc = self.run("config", "--remove-section", section, ok_codes=())
        return proc.returncode == 0

    def config_get(self, key: str) -> str | None:
        proc = self.run("config", "--get", key, ok_codes=(0, 1))
        if proc.returncode != 0:
            return None
        return proc.stdout.decode("utf-8", "surrogateescape").rstrip("\n")


def _normalise_key(key: str) -> str:
    """Lower-case section and key, keep the subsection (scope) case."""
    parts = key.split(".")
    if len(parts) >= 3:
        return ".".join([parts[0].lower(), *parts[1:-1], parts[-1].lower()])
    return key.lower()


class GitRepo(GitRunner):
    """A git working tree."""

    def __init__(self, root: Path) -> None:
        super().__init__(Path(root).absolute())
        self.root = Path(root).absolute()

    @classmethod
    def discover(cls, cwd: Path) -> GitRepo:
        runner = GitRunner(cwd)
        proc = runner.run("rev-parse", "--show-toplevel", ok_codes=(0, 128))
        top = proc.stdout.decode("utf-8", "surrogateescape").strip()
        if proc.returncode != 0 or not top:
            raise GitError("Not a Git project? Exiting...")
        return cls(Path(top))

    @classmethod
    def init(cls, path: Path) -> GitRepo:
        proc = GitRunner(path).run("init", ok_codes=())
        if proc.returncode != 0:
            raise GitError("Error initialising Git repository.")
        return cls(path)

    # -- state -------------------------------------------------------------
    def head_sha(self) -> str:
        return self.out("log", "-n", "1", "--pretty=format:%H").strip()

    def current_branch(self) -> str:
        proc = self.run("symbolic-ref", "-q", "--short", "HEAD", ok_codes=(0, 1))
        if proc.returncode == 0:
            return proc.stdout.decode("utf-8", "surrogateescape").strip()
        return self.head_sha()

    def checkout(self, ref: str) -> bool:
        proc = self.run("checkout", "-q", ref, ok_codes=())
        return proc.returncode == 0

    def is_dirty(self) -> bool:
        return bool(self.out("status", "-uno", "--porcelain").strip())

    def has_any_changes(self) -> bool:
        return bool(self.out("status", "--porcelain").strip())

    def empty_tree(self) -> str:
        return self.out("hash-object", "-t", "tree", os.devnull).strip()

    # -- file lists (NUL separated, repo-relative, forward slashes) --------
    def _z(self, *args: str, ok_codes: Sequence[int] = (0,)) -> list[str]:
        data = self.run(*args, ok_codes=ok_codes).stdout
        return [p.decode("utf-8", "surrogateescape") for p in data.split(b"\0") if p]

    def ls_files(self, prefix: str = "") -> list[str]:
        return self._z("ls-files", "-z", "--", prefix or ".")

    def diff_names(self, base: str, diff_filter: str, prefix: str = "") -> list[str]:
        proc = self.run(
            "diff",
            "--name-only",
            "--no-renames",
            f"--diff-filter={diff_filter}",
            "-z",
            base,
            "--",
            prefix or ".",
            ok_codes=(),
        )
        if proc.returncode != 0:
            raise UnknownCommit(base)
        return [p.decode("utf-8", "surrogateescape") for p in proc.stdout.split(b"\0") if p]

    def diff_quiet_changed(self, base: str, path: str) -> bool:
        """``git diff --quiet base -- path``; any non-zero status counts as changed."""
        proc = self.run("diff", "--quiet", base, "--", path, ok_codes=())
        return proc.returncode != 0

    def diff_names_between(self, a: str, b: str | None = None) -> list[str]:
        args = ["diff", "--name-only", "-z", a]
        if b:
            args.append(b)
        return self._z(*args)

    def submodules(self, prefix: str = "") -> dict[str, bool]:
        """Submodule paths under ``prefix`` mapped to whether they are initialised."""
        if not (self.root / ".gitmodules").is_file():
            return {}
        args = ["submodule", "status"]
        if prefix:
            args += ["--", prefix]
        proc = self.run(*args, ok_codes=(0, 1, 128))
        result: dict[str, bool] = {}
        for line in proc.stdout.decode("utf-8", "surrogateescape").splitlines():
            if not line.strip():
                continue
            initialised = not line.startswith("-")
            parts = line.strip().lstrip("-+U").split()
            if parts and len(parts) >= 2:
                result[parts[1]] = initialised
        return result

    def ignored(self, paths: list[str]) -> set[str]:
        """The subset of ``paths`` (repo-relative) that git ignores."""
        if not paths:
            return set()
        data = b"".join(p.encode("utf-8", "surrogateescape") + b"\0" for p in paths)
        proc = self.run("check-ignore", "-z", "--stdin", input=data, ok_codes=(0, 1))
        return {p.decode("utf-8", "surrogateescape") for p in proc.stdout.split(b"\0") if p}

    def hooks_dir(self) -> Path:
        path = self.out("rev-parse", "--git-path", "hooks").strip()
        p = Path(path)
        return p if p.is_absolute() else self.root / p

    # -- mutations used by pull/snapshot -----------------------------------
    def stash_push_untracked(self) -> bool:
        """``git stash -u``; True when something was actually stashed."""
        proc = self.run("stash", "push", "-u", ok_codes=(0, 1))
        return proc.returncode == 0 and b"No local changes to save" not in proc.stdout

    def stash_pop(self) -> None:
        self.run("stash", "pop", "-q")

    @contextmanager
    def temporary_worktree(self, ref: str) -> Iterator[Path]:
        """Check ``ref`` out into a throwaway detached worktree, then remove it.

        The worktree shares the object store, so only the working copy is written
        to disk. Reading upload contents from it isolates a deploy from edits made
        to the live working tree while the transfer is running.
        """
        parent = Path(tempfile.mkdtemp(prefix="git-ftp-worktree-"))
        tree = parent / "tree"  # must not pre-exist: git worktree add creates it
        try:
            self.run("worktree", "add", "--detach", "--quiet", str(tree), ref)
        except GitError:
            shutil.rmtree(parent, ignore_errors=True)
            raise
        try:
            yield tree
        finally:
            self.run("worktree", "remove", "--force", str(tree), ok_codes=())
            self.run("worktree", "prune", ok_codes=())
            shutil.rmtree(parent, ignore_errors=True)

    def add_all(self) -> None:
        self.run("add", "--all")

    def add_dot(self) -> None:
        self.run("add", ".")

    def commit(
        self, subject: str, body: str | None = None, quiet: bool = True, allow_empty: bool = False
    ) -> bool:
        args = ["commit", "-m", subject]
        if allow_empty:
            args.append("--allow-empty")
        if body:
            args += ["-m", body]
        if quiet:
            args.append("-q")
        proc = self.run(*args, ok_codes=())
        return proc.returncode == 0

    def diff_head_name_status(self) -> str:
        return self.out("diff", "HEAD", "--name-status")

    def merge(self, sha: str, no_commit: bool) -> int:
        args = ["merge"]
        if no_commit:
            args += ["--no-commit", "--no-ff"]
        args.append(sha)
        return self.run(*args, ok_codes=(), inherit_stdio=True).returncode

    def show(self, sha: str) -> int:
        return self.run("show", sha, ok_codes=(), inherit_stdio=True).returncode

    def log(self, sha: str) -> int:
        return self.run("log", sha, ok_codes=(), inherit_stdio=True).returncode
