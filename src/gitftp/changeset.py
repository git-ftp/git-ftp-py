"""Compute what to upload and delete, in upstream's order.

1. all tracked files (init, --all) or ``git diff`` against the deployed commit
2. ``.git-ftp-include`` rules (may add uploads and deletes)
3. ``.git-ftp-ignore`` patterns (remove from both lists)
4. sort, deduplicate
"""

from __future__ import annotations

from dataclasses import dataclass, field

from gitftp import ignore as ignoremod
from gitftp import include as includemod
from gitftp.gitrepo import GitRepo, UnknownCommit
from gitftp.output import Output

__all__ = ["ChangeSet", "UnknownCommit", "build"]


@dataclass
class ChangeSet:
    uploads: list[str] = field(default_factory=list)
    deletes: list[str] = field(default_factory=list)
    submodules: set[str] = field(default_factory=set)

    def is_empty(self) -> bool:
        return not self.uploads and not self.deletes

    def total(self) -> int:
        return len(self.uploads) + len(self.deletes)

    def hook_status(self) -> bytes:
        """NUL-separated ``A <path>`` / ``D <path>`` lines for the pre-push hook."""
        parts = [f"A {p}".encode("utf-8", "surrogateescape") for p in self.uploads]
        parts += [f"D {p}".encode("utf-8", "surrogateescape") for p in self.deletes]
        return b"".join(p + b"\0" for p in parts)


def remote_path(git_path: str, syncroot: str) -> str:
    """Strip the syncroot prefix (a plain prefix, not a glob as upstream did)."""
    if syncroot and git_path.startswith(syncroot):
        return git_path[len(syncroot) :]
    return git_path


def _sorted_unique(items: list[str]) -> list[str]:
    return sorted(set(items), key=lambda s: s.encode("utf-8", "surrogateescape"))


def build(
    repo: GitRepo,
    syncroot: str,
    deployed_sha: str | None,
    take_all: bool,
    out: Output,
) -> ChangeSet:
    """Raises :class:`UnknownCommit` when ``deployed_sha`` is unknown to git."""
    if take_all or not deployed_sha:
        uploads = repo.ls_files(syncroot)
        deletes: list[str] = []
        against = repo.empty_tree()
    else:
        uploads = repo.diff_names(deployed_sha, "AMT", syncroot)
        deletes = repo.diff_names(deployed_sha, "D", syncroot)
        against = deployed_sha

    rules = includemod.load_rules(repo.root)
    if rules:
        inc_up, inc_del = includemod.expand(rules, repo, syncroot, against, out)
        uploads += inc_up
        deletes += inc_del

    ignore = ignoremod.IgnoreRules.load(repo.root)
    if len(ignore):
        uploads = ignore.filter(uploads)
        deletes = ignore.filter(deletes)

    subs = repo.submodules(syncroot)
    # Uninitialised submodules are gitlinks without a working tree: nothing to upload.
    uninitialised = {p for p, ok in subs.items() if not ok}
    uploads = [p for p in uploads if p not in uninitialised]
    uploads = _sorted_unique(uploads)
    deletes = _sorted_unique(deletes)
    submodules = {p for p, ok in subs.items() if ok and p in set(uploads)}
    return ChangeSet(uploads=uploads, deletes=deletes, submodules=submodules)
