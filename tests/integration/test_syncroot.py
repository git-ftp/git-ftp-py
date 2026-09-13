from __future__ import annotations

from tests.conftest import RunCli
from tests.helpers.ftpserver import FtpServer
from tests.helpers.gitrepo import Repo
from tests.integration.conftest import auth


def test_syncroot_option(run_cli: RunCli, repo: Repo, ftp_server: FtpServer) -> None:
    s = ftp_server
    repo.write("foo bar/syncroot.txt", "s\n")
    repo.commit("syncroot")
    assert run_cli("init", "--syncroot", "foo bar", *auth(s), s.url()).code == 0
    assert s.remote().exists("syncroot.txt")
    assert not s.remote().exists("test 1.txt")
    assert not s.remote().exists("foo bar/syncroot.txt")


def test_syncroot_config(run_cli: RunCli, repo: Repo, ftp_server: FtpServer) -> None:
    s = ftp_server
    repo.write("foo bar/syncroot.txt", "s\n")
    repo.commit("syncroot")
    repo.config("git-ftp.syncroot", "foo bar/")
    assert run_cli("init", *auth(s), s.url()).code == 0
    assert s.remote().exists("syncroot.txt")


def test_syncroot_not_a_directory_exit_8(
    run_cli: RunCli, repo: Repo, ftp_server: FtpServer
) -> None:
    r = run_cli("init", "--syncroot", "nope", *auth(ftp_server), ftp_server.url())
    assert r.code == 8
    assert "'nope' is not a directory! Exiting..." in r.stderr


def test_syncroot_push_only_changes_below(
    run_cli: RunCli, repo: Repo, ftp_server: FtpServer
) -> None:
    s = ftp_server
    assert run_cli("init", "--syncroot", "dir 1", *auth(s), s.url()).code == 0
    repo.write("dir 1/new.txt", "n\n")
    repo.write("dir 2/other.txt", "o\n")
    repo.commit("both")
    r = run_cli("push", "--syncroot", "dir 1", *auth(s), s.url())
    assert r.code == 0
    assert "1 file to sync:" in r.stdout
    assert s.remote().exists("new.txt")
    assert not s.remote().exists("other.txt")
