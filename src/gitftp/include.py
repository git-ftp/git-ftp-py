""".git-ftp-include: upload untracked files.

Formats:
    !target              always upload ``target``
    target:source        upload ``target`` when tracked ``source`` changed
    target:/source       ``source`` is relative to the repository root even with --syncroot

A ``target`` that is a directory expands to every file below it. A target that
no longer exists locally is deleted remotely (directories excepted).
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from gitftp.gitrepo import GitRepo
from gitftp.output import Output

INCLUDE_FILE = ".git-ftp-include"


@dataclass(frozen=True)
class IncludeRule:
    target: str
    source: str | None
    always: bool


def parse_rules(text: str) -> list[IncludeRule]:
    rules = []
    for raw in text.splitlines():
        line = raw.rstrip("\r")
        if not line.strip() or line.startswith("#"):
            continue
        if line.startswith("!"):
            rules.append(IncludeRule(target=line[1:], source=None, always=True))
        elif ":" in line:
            target, _, source = line.partition(":")
            rules.append(IncludeRule(target=target, source=source, always=False))
    return rules


def load_rules(root: Path) -> list[IncludeRule]:
    path = root / INCLUDE_FILE
    if not path.is_file():
        return []
    return parse_rules(path.read_text(encoding="utf-8", errors="surrogateescape"))


def resolve_source(source: str, syncroot: str) -> str:
    if source.startswith("/"):
        return source.lstrip("/")
    return f"{syncroot}{source}"


def _walk_files(root: Path, target: str) -> list[str]:
    base = root / target
    files = []
    for dirpath, _dirs, names in os.walk(base):
        for name in names:
            rel = Path(dirpath, name).relative_to(root).as_posix()
            files.append(rel)
    return sorted(files)


def expand(
    rules: list[IncludeRule],
    repo: GitRepo,
    syncroot: str,
    against: str,
    out: Output,
) -> tuple[list[str], list[str]]:
    """Return (uploads, deletes) contributed by the include rules."""
    uploads: list[str] = []
    deletes: list[str] = []
    for rule in rules:
        if not rule.always:
            assert rule.source is not None
            source = resolve_source(rule.source, syncroot)
            if not repo.diff_quiet_changed(against, source):
                continue
        target = rule.target
        local = repo.root / target
        if local.is_dir():
            uploads.extend(_walk_files(repo.root, target.rstrip("/")))
        elif local.is_file():
            uploads.append(target)
        elif target.endswith("/"):
            out.debug(f"Deletion of directory {target} is not supported.")
        else:
            deletes.append(target)
    return uploads, deletes
