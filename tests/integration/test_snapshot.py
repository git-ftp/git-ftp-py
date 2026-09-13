from __future__ import annotations

from pathlib import Path

import pytest

from tests.conftest import RunCli
from tests.helpers.ftpserver import FtpServer
from tests.helpers.gitrepo import Repo
from tests.integration.conftest import auth


def test_snapshot_refuses_managed_remote_exit_2(
    run_cli: RunCli,
    repo: Repo,
    ftp_server: FtpServer,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    s = ftp_server
    assert run_cli("init", *auth(s), s.url()).code == 0
    monkeypatch.chdir(tmp_path)
    r = run_cli("snapshot", *auth(s), s.url())
    assert r.code == 2
    assert "managed by another Git repository" in r.stderr


def test_snapshot_creates_repo_and_log(
    run_cli: RunCli,
    repo: Repo,
    ftp_server: FtpServer,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    s = ftp_server
    assert run_cli("init", *auth(s), s.url()).code == 0
    s.remote().delete(".git-ftp.log")
    monkeypatch.chdir(tmp_path)
    r = run_cli("snapshot", "-n", *auth(s), s.url())
    assert r.code == 0, r
    snap = Repo(tmp_path / "site")
    assert snap.exists(".git")
    assert snap.read("test 1.txt") == "1\n"
    assert snap.read("dir 3/test 3.txt") == "3\n"
    assert "Download" in snap.git("log", "-1", "--pretty=%s").stdout
    assert s.remote().log() == snap.head()
    assert not snap.exists(".git-ftp.log")


def test_snapshot_into_named_dir_refuses_non_empty_exit_10(
    run_cli: RunCli,
    repo: Repo,
    ftp_server: FtpServer,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    s = ftp_server
    assert run_cli("catchup", *auth(s), s.url()).code == 0
    s.remote().delete(".git-ftp.log")
    monkeypatch.chdir(tmp_path)
    (tmp_path / "dest" / "x").mkdir(parents=True)
    r = run_cli("snapshot", *auth(s), s.url(), "dest")
    assert r.code == 10
    assert "not empty" in r.stderr
    r = run_cli("snapshot", *auth(s), s.url(), "fresh")
    assert r.code == 0, r
    assert (tmp_path / "fresh" / ".git").is_dir()


def test_snapshot_without_url_exit_2(
    run_cli: RunCli, home: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    r = run_cli("snapshot")
    assert r.code == 2
    assert "give a URL to snapshot" in r.stderr
