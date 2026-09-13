from __future__ import annotations

import pytest

from tests.conftest import RunCli
from tests.helpers.ftpserver import FtpServer
from tests.helpers.gitrepo import Repo
from tests.integration.conftest import auth, cacert_args


def test_init_uploads_all_and_writes_log(
    run_cli: RunCli, repo: Repo, any_ftp_server: FtpServer
) -> None:
    s = any_ftp_server
    r = run_cli("init", *auth(s), *cacert_args(s), s.url())
    assert r.code == 0, r
    remote = s.remote()
    for i in range(1, 6):
        remote.assert_equals_local(f"test {i}.txt", repo)
        remote.assert_equals_local(f"dir {i}/test {i}.txt", repo)
    assert remote.log() == repo.head()
    assert "10 files to sync:" in r.stdout
    assert "[1 of 10] Buffered for upload 'dir 1/test 1.txt'." in r.stdout
    assert "Uploading ..." in r.stdout
    assert f"Last deployment changed from  to {repo.head()}." in r.stdout


def test_init_wrong_credentials_exit_4(run_cli: RunCli, repo: Repo, ftp_server: FtpServer) -> None:
    r = run_cli("init", "-u", "wrong", "-p", "wrong", ftp_server.url())
    assert r.code == 4


def test_init_invalid_password_message(run_cli: RunCli, repo: Repo, ftp_server: FtpServer) -> None:
    r = run_cli("init", "-u", ftp_server.USER, "-p", "wrong", ftp_server.url())
    assert r.code == 4
    assert (
        f"fatal: Can't access remote 'ftp://{ftp_server.USER}:***@{ftp_server.hostport}/site/'. "
        "Failed to log in. Correct user and password?" in r.stderr
    )
    assert "wrong" not in r.stderr


def test_init_invalid_user_message(run_cli: RunCli, repo: Repo, ftp_server: FtpServer) -> None:
    r = run_cli("init", "-u", "nobody", "-p", ftp_server.PASSWORD, ftp_server.url())
    assert r.code == 4
    assert "Failed to log in. Correct user and password?" in r.stderr


def test_init_twice_refused_then_push(run_cli: RunCli, repo: Repo, ftp_server: FtpServer) -> None:
    assert run_cli("init", *auth(ftp_server), ftp_server.url()).code == 0
    r = run_cli("init", *auth(ftp_server), ftp_server.url())
    assert r.code == 2
    assert "fatal: Commit found, use 'git ftp push' to sync. Exiting..." in r.stderr
    assert run_cli("push", *auth(ftp_server), ftp_server.url()).code == 0


def test_deployedsha1file_config(run_cli: RunCli, repo: Repo, ftp_server: FtpServer) -> None:
    repo.config("git-ftp.deployedsha1file", "git-ftp.txt")
    assert run_cli("init", *auth(ftp_server), ftp_server.url()).code == 0
    remote = ftp_server.remote()
    assert remote.exists("git-ftp.txt")
    assert not remote.exists(".git-ftp.log")
    assert remote.read("git-ftp.txt").strip() == repo.head()


def test_url_userinfo_used_as_credentials(
    run_cli: RunCli, repo: Repo, ftp_server: FtpServer
) -> None:
    r = run_cli("init", ftp_server.url(creds=True))
    assert r.code == 0, r
    assert ftp_server.remote().log() == repo.head()


def test_host_port_form_without_scheme(run_cli: RunCli, repo: Repo, ftp_server: FtpServer) -> None:
    r = run_cli("init", *auth(ftp_server), f"{ftp_server.hostport}/site")
    assert r.code == 0, r
    assert ftp_server.remote().log() == repo.head()


def test_remote_directory_is_created(run_cli: RunCli, repo: Repo, ftp_server: FtpServer) -> None:
    r = run_cli("init", *auth(ftp_server), ftp_server.url("deep/er/site"))
    assert r.code == 0, r
    assert ftp_server.remote("deep/er/site").log() == repo.head()


def test_dry_run_uploads_nothing(run_cli: RunCli, repo: Repo, ftp_server: FtpServer) -> None:
    r = run_cli("init", "-D", *auth(ftp_server), ftp_server.url())
    assert r.code == 0
    assert "10 files to sync:" in r.stdout
    assert "Uploading ..." not in r.stdout
    assert ftp_server.remote().listdir() == []


@pytest.mark.parametrize("jobs", ["1", "4"])
def test_init_jobs(run_cli: RunCli, repo: Repo, ftp_server: FtpServer, jobs: str) -> None:
    r = run_cli("init", "-j", jobs, *auth(ftp_server), ftp_server.url())
    assert r.code == 0, r
    assert ftp_server.remote().log() == repo.head()
    if jobs == "1":
        assert ftp_server.max_concurrent == 1
