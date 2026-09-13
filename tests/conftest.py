"""Shared fixtures: isolated HOME, git identity, a fixture repository, and a CLI runner."""

from __future__ import annotations

import os
import sys
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

import pytest
from click.testing import CliRunner

from gitftp.cli import main as cli_main
from tests.helpers.gitrepo import Repo, make_repo


@pytest.fixture
def home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("USERPROFILE", str(home))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(home / ".config"))
    monkeypatch.setenv("GIT_CONFIG_NOSYSTEM", "1")
    monkeypatch.setenv("GIT_TERMINAL_PROMPT", "0")
    monkeypatch.setenv("PYTHONUTF8", "1")
    monkeypatch.setenv("GIT_AUTHOR_NAME", "git-ftp test")
    monkeypatch.setenv("GIT_AUTHOR_EMAIL", "test@example.com")
    monkeypatch.setenv("GIT_COMMITTER_NAME", "git-ftp test")
    monkeypatch.setenv("GIT_COMMITTER_EMAIL", "test@example.com")
    for var in ("GIT_FTP_URL", "GIT_FTP_USER", "GIT_FTP_PASSWORD", "SSH_AUTH_SOCK", "NETRC"):
        monkeypatch.delenv(var, raising=False)
    (home / ".gitconfig").write_text(
        "[init]\n\tdefaultBranch = master\n"
        '[protocol "file"]\n\tallow = always\n'
        "[core]\n\tautocrlf = false\n"
        "[user]\n\tname = git-ftp test\n\temail = test@example.com\n",
        encoding="utf-8",
    )
    return home


@pytest.fixture
def repo(home: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Repo:
    r = make_repo(tmp_path / "project")
    monkeypatch.chdir(r.path)
    return r


@dataclass
class CliResult:
    code: int
    stdout: str
    stderr: str

    @property
    def output(self) -> str:
        return self.stdout + self.stderr

    def __repr__(self) -> str:
        return f"CliResult(code={self.code}, stdout={self.stdout!r}, stderr={self.stderr!r})"


RunCli = Callable[..., CliResult]


@pytest.fixture
def run_cli() -> RunCli:
    def run(*args: str, input: str | None = None) -> CliResult:
        runner = CliRunner()
        result = runner.invoke(
            _entry, list(args), input=input, catch_exceptions=False, standalone_mode=False
        )
        code = result.return_value if result.return_value is not None else result.exit_code
        return CliResult(code=int(code or 0), stdout=result.stdout, stderr=result.stderr)

    return run


import click  # noqa: E402


@click.command(context_settings={"ignore_unknown_options": True, "allow_extra_args": True})
@click.argument("args", nargs=-1, type=click.UNPROCESSED)
def _entry(args: tuple[str, ...]) -> int:
    """Run the real entry point (argv normalisation and exit-code mapping included)."""
    return cli_main(list(args))


@pytest.fixture
def cli_bin() -> list[str]:
    return [sys.executable, "-m", "gitftp"]


@pytest.fixture
def env_clean() -> dict[str, str]:
    return dict(os.environ)


@pytest.fixture
def run_bin(cli_bin: list[str]) -> RunCli:
    """Run the real entry point in a subprocess (hooks and git show/log need real stdio)."""
    import subprocess

    def run(*args: str, input: str | None = None, cwd: Path | None = None) -> CliResult:
        proc = subprocess.run(
            [*cli_bin, *args],
            input=input,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="surrogateescape",
            cwd=cwd,
        )
        return CliResult(code=proc.returncode, stdout=proc.stdout, stderr=proc.stderr)

    return run
