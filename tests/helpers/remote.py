"""Assertions on the server's directory on disk."""

from __future__ import annotations

from pathlib import Path

from tests.helpers.gitrepo import Repo


class Remote:
    def __init__(self, root: Path, deployed_file: str = ".git-ftp.log") -> None:
        self.root = root
        self.deployed_file = deployed_file

    def path(self, rel: str) -> Path:
        return self.root / rel

    def exists(self, rel: str) -> bool:
        return (self.root / rel).exists()

    def read(self, rel: str) -> str:
        return (self.root / rel).read_text(encoding="utf-8")

    def read_bytes(self, rel: str) -> bytes:
        return (self.root / rel).read_bytes()

    def write(self, rel: str, text: str) -> None:
        p = self.root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, encoding="utf-8")

    def delete(self, rel: str) -> None:
        (self.root / rel).unlink()

    def listdir(self, rel: str = "") -> list[str]:
        p = self.root / rel if rel else self.root
        return sorted(x.name for x in p.iterdir())

    def log(self) -> str | None:
        p = self.root / self.deployed_file
        return p.read_text(encoding="utf-8").strip() if p.is_file() else None

    def lock(self) -> str | None:
        p = self.root / "git-ftp.lck"
        return p.read_text(encoding="utf-8") if p.is_file() else None

    def assert_equals_local(self, rel: str, repo: Repo, local_rel: str | None = None) -> None:
        local = repo.path / (local_rel or rel)
        assert self.exists(rel), f"remote file missing: {rel}"
        assert self.read_bytes(rel) == local.read_bytes(), f"content differs: {rel}"
