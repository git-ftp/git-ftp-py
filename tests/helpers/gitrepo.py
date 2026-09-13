"""A temporary git repository shaped like upstream's test fixture."""

from __future__ import annotations

import os
import stat
import subprocess
from pathlib import Path


class Repo:
    def __init__(self, path: Path) -> None:
        self.path = path

    # -- git ---------------------------------------------------------------
    def git(
        self, *args: str, check: bool = True, cwd: Path | None = None
    ) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            ["git", *args],
            cwd=cwd or self.path,
            check=check,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="surrogateescape",
        )

    def head(self) -> str:
        return self.git("rev-parse", "HEAD").stdout.strip()

    def commit(self, message: str = "commit", all: bool = True) -> str:
        if all:
            self.git("add", "--all")
        self.git("commit", "-q", "--allow-empty", "-m", message)
        return self.head()

    def config(self, key: str, value: str) -> None:
        self.git("config", "--", key, value)

    def checkout(self, branch: str, new: bool = False) -> None:
        if new:
            self.git("checkout", "-q", "-b", branch)
        else:
            self.git("checkout", "-q", branch)

    def status_sb(self) -> str:
        return self.git("status", "-sb").stdout.strip()

    # -- files -------------------------------------------------------------
    def write(self, rel: str, text: str = "") -> Path:
        p = self.path / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, encoding="utf-8")
        return p

    def append(self, rel: str, text: str) -> None:
        with open(self.path / rel, "a", encoding="utf-8") as fh:
            fh.write(text)

    def read(self, rel: str) -> str:
        return (self.path / rel).read_text(encoding="utf-8")

    def add(self, *rels: str) -> None:
        self.git("add", "--", *rels)

    def rm(self, *rels: str, recursive: bool = False) -> None:
        args = ["rm", "-q"]
        if recursive:
            args.append("-r")
        self.git(*args, "--", *rels)

    def exists(self, rel: str) -> bool:
        return (self.path / rel).exists()

    def hook(self, name: str, body: str) -> Path:
        hooks = Path(self.git("rev-parse", "--git-path", "hooks").stdout.strip())
        if not hooks.is_absolute():
            hooks = self.path / hooks
        hooks.mkdir(parents=True, exist_ok=True)
        p = hooks / name
        p.write_text(body if body.startswith("#!") else "#!/bin/sh\n" + body, encoding="utf-8")
        p.chmod(p.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
        return p

    def add_submodule(self, name: str, files: dict[str, str], at: str | None = None) -> Repo:
        """Create a sibling repository and add it as a submodule at ``at`` (default ``name``)."""
        sub_path = self.path.parent / f"{self.path.name}-{name}"
        sub_path.mkdir()
        sub = Repo(sub_path)
        sub.git("init", "-q")
        for rel, text in files.items():
            sub.write(rel, text)
        sub.commit("submodule init")
        target = at or name
        self.git(
            "-c",
            "protocol.file.allow=always",
            "submodule",
            "add",
            "-q",
            os.fspath(sub_path),
            target,
        )
        self.commit(f"add submodule {target}")
        return Repo(self.path / target)


def make_repo(path: Path) -> Repo:
    """Upstream's layout: 'test 1.txt'..'test 5.txt' and 'dir 1/test 1.txt'..'dir 5/test 5.txt'."""
    path.mkdir(parents=True, exist_ok=True)
    repo = Repo(path)
    for i in range(1, 6):
        repo.write(f"test {i}.txt", f"{i}\n")
        repo.write(f"dir {i}/test {i}.txt", f"{i}\n")
    repo.git("init", "-q")
    repo.commit("init")
    return repo
