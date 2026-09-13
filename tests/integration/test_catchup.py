from __future__ import annotations

from tests.conftest import RunCli
from tests.helpers.ftpserver import FtpServer
from tests.helpers.gitrepo import Repo
from tests.integration.conftest import auth


def test_catchup_writes_only_log(run_cli: RunCli, repo: Repo, ftp_server: FtpServer) -> None:
    s = ftp_server
    r = run_cli("catchup", *auth(s), s.url())
    assert r.code == 0, r
    assert s.remote().listdir() == [".git-ftp.log"]
    assert s.remote().log() == repo.head()
    assert f"Last deployment changed from  to {repo.head()}." in r.stdout


def test_catchup_invalid_credentials_exit_4(
    run_cli: RunCli, repo: Repo, ftp_server: FtpServer
) -> None:
    r = run_cli("catchup", "-u", ftp_server.USER, "-p", "wrong", ftp_server.url())
    assert r.code == 4
    assert "fatal: Could not upload. Can't access remote" in r.stderr
    assert "Failed to log in" in r.stderr


def test_show_and_log(run_bin: RunCli, run_cli: RunCli, repo: Repo, ftp_server: FtpServer) -> None:
    s = ftp_server
    assert run_cli("catchup", *auth(s), s.url()).code == 0
    r = run_bin("show", *auth(s), s.url())
    assert r.code == 0, r
    assert repo.head() in r.stdout
    r = run_bin("log", *auth(s), s.url())
    assert r.code == 0
    assert "init" in r.stdout


def test_show_without_log_exit_5(run_cli: RunCli, repo: Repo, ftp_server: FtpServer) -> None:
    r = run_cli("show", *auth(ftp_server), ftp_server.url())
    assert r.code == 5
    assert "Could not get uploaded log file" in r.stderr
