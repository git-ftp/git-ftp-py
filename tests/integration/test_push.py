from __future__ import annotations

import os
import sys

import pytest

from tests.conftest import RunCli
from tests.helpers.ftpserver import FtpServer
from tests.helpers.gitrepo import Repo
from tests.integration.conftest import auth


def init(run_cli: RunCli, s: FtpServer, *extra: str) -> None:
    assert run_cli("init", *auth(s), *extra, s.url()).code == 0


def test_push_auto_init_then_refuses_init(
    run_cli: RunCli, repo: Repo, ftp_server: FtpServer
) -> None:
    s = ftp_server
    r = run_cli("push", "--auto-init", *auth(s), s.url())
    assert r.code == 0, r
    assert s.remote().log() == repo.head()
    assert s.remote().exists("test 1.txt")
    assert run_cli("init", *auth(s), s.url()).code == 2
    repo.write("test 1.txt", "changed\n")
    repo.commit("change")
    assert run_cli("push", "--auto-init", *auth(s), s.url()).code == 0
    s.remote().assert_equals_local("test 1.txt", repo)


def test_push_without_init_exit_5(run_cli: RunCli, repo: Repo, ftp_server: FtpServer) -> None:
    r = run_cli("push", *auth(ftp_server), ftp_server.url())
    assert r.code == 5
    assert "fatal: Could not get last commit. Use 'git ftp init' for the initial push." in r.stderr


def test_push_invalid_password_exit_5(run_cli: RunCli, repo: Repo, ftp_server: FtpServer) -> None:
    init(run_cli, ftp_server)
    r = run_cli("push", "-u", ftp_server.USER, "-p", "wrong", ftp_server.url())
    assert r.code == 5
    assert "Could not get last commit" in r.stderr
    assert "Failed to log in" in r.stderr
    assert "git ftp init" not in r.stderr


def test_push_invalid_user_exit_5(run_cli: RunCli, repo: Repo, ftp_server: FtpServer) -> None:
    init(run_cli, ftp_server)
    r = run_cli("push", "-u", "nobody", "-p", ftp_server.PASSWORD, ftp_server.url())
    assert r.code == 5
    assert "Failed to log in" in r.stderr


def test_push_dry_run_counts_then_ignored_nothing_to_sync(
    run_cli: RunCli, repo: Repo, ftp_server: FtpServer
) -> None:
    s = ftp_server
    init(run_cli, s)
    repo.write("newfile.txt", "1\n")
    repo.commit("add")
    r = run_cli("push", "--dry-run", *auth(s), s.url())
    assert r.code == 0
    assert "1 file to sync:" in r.stdout
    assert not s.remote().exists("newfile.txt")
    repo.write(".git-ftp-ignore", "newfile.txt\n")
    r = run_cli("push", *auth(s), s.url())
    assert r.code == 0
    assert r.stdout.splitlines()[0] == "There are no files to sync."
    assert s.remote().log() == repo.head()


def test_push_added_file(run_cli: RunCli, repo: Repo, ftp_server: FtpServer) -> None:
    s = ftp_server
    init(run_cli, s)
    repo.write("newfile.txt", "1")
    repo.commit("add")
    assert run_cli("push", *auth(s), s.url()).code == 0
    assert s.remote().read("newfile.txt") == "1"


def test_push_twice_up_to_date(run_cli: RunCli, repo: Repo, ftp_server: FtpServer) -> None:
    s = ftp_server
    init(run_cli, s)
    repo.write("newfile.txt", "1")
    repo.commit("add")
    assert run_cli("push", *auth(s), s.url()).code == 0
    r = run_cli("push", *auth(s), s.url())
    assert r.code == 0
    assert "Everything up-to-date." in r.stdout


def test_push_from_two_branches_diffs_against_deployed(
    run_cli: RunCli, repo: Repo, ftp_server: FtpServer
) -> None:
    s = ftp_server
    init(run_cli, s)
    repo.checkout("branch1", new=True)
    repo.write("test 1.txt", "branch1\n")
    repo.commit("b1")
    assert run_cli("push", *auth(s), s.url()).code == 0
    repo.checkout("master")
    repo.checkout("branch2", new=True)
    repo.write("test 2.txt", "branch2\n")
    repo.commit("b2")
    r = run_cli("push", *auth(s), s.url())
    assert r.code == 0
    assert "2 files to sync:" in r.stdout
    s.remote().assert_equals_local("test 1.txt", repo)
    s.remote().assert_equals_local("test 2.txt", repo)


def _corrupt_log(s: FtpServer) -> None:
    s.remote().write(".git-ftp.log", "000000000\n")


def test_unknown_commit_eof_aborts_exit_2(
    run_cli: RunCli, repo: Repo, ftp_server: FtpServer
) -> None:
    s = ftp_server
    init(run_cli, s)
    _corrupt_log(s)
    repo.write("test 1.txt", "x\n")
    repo.commit("x")
    r = run_cli("push", *auth(s), s.url(), input="")
    assert r.code == 2, r
    assert "Unknown SHA1 object" in r.stdout
    assert "Do you want to ignore" in r.stdout
    assert s.remote().read("test 1.txt") == "1\n"


def test_unknown_commit_no_aborts_exit_0(
    run_cli: RunCli, repo: Repo, ftp_server: FtpServer
) -> None:
    s = ftp_server
    init(run_cli, s)
    _corrupt_log(s)
    repo.write("test 1.txt", "x\n")
    repo.commit("x")
    r = run_cli("push", *auth(s), s.url(), input="N\n")
    assert r.code == 0
    assert "Aborting..." in r.stdout
    assert s.remote().read("test 1.txt") == "1\n"


def test_unknown_commit_yes_uploads_all(run_cli: RunCli, repo: Repo, ftp_server: FtpServer) -> None:
    s = ftp_server
    init(run_cli, s)
    _corrupt_log(s)
    repo.write("test 1.txt", "x\n")
    repo.commit("x")
    r = run_cli("push", *auth(s), s.url(), input="Y\n")
    assert r.code == 0, r
    assert s.remote().read("test 1.txt") == "x\n"
    assert s.remote().log() == repo.head()


def test_unknown_commit_force_uploads_all(
    run_cli: RunCli, repo: Repo, ftp_server: FtpServer
) -> None:
    s = ftp_server
    init(run_cli, s)
    _corrupt_log(s)
    r = run_cli("push", "-f", *auth(s), s.url())
    assert r.code == 0
    assert "taking all files" in r.stdout
    assert s.remote().log() == repo.head()


def test_push_all_flag_uploads_everything(
    run_cli: RunCli, repo: Repo, ftp_server: FtpServer
) -> None:
    s = ftp_server
    init(run_cli, s)
    r = run_cli("push", "-a", *auth(s), s.url())
    assert r.code == 0
    assert "10 files to sync:" in r.stdout


def test_push_commit_option(run_cli: RunCli, repo: Repo, ftp_server: FtpServer) -> None:
    s = ftp_server
    first = repo.head()
    init(run_cli, s)
    repo.write("a.txt", "a\n")
    repo.commit("a")
    repo.write("b.txt", "b\n")
    repo.commit("b")
    r = run_cli("push", "-c", first, *auth(s), s.url())
    assert r.code == 0
    assert "2 files to sync:" in r.stdout


def test_push_branch_option_restores_branch(
    run_cli: RunCli, repo: Repo, ftp_server: FtpServer
) -> None:
    s = ftp_server
    init(run_cli, s)
    repo.checkout("deploy", new=True)
    repo.write("deploy.txt", "d\n")
    repo.commit("d")
    repo.checkout("master")
    for form in (["-b", "deploy"], ["--branch=deploy"]):
        r = run_cli("push", *form, *auth(s), s.url())
        assert r.code == 0, r
        assert repo.status_sb().startswith("## master")
    assert s.remote().exists("deploy.txt")
    r = run_cli("push", "-b", "nope", *auth(s), s.url())
    assert r.code == 8
    assert "'nope' is not a valid branch! Exiting..." in r.stderr


@pytest.mark.skipif(sys.platform == "win32", reason="symlinks")
def test_typechange_file_to_symlink_is_uploaded(
    run_cli: RunCli, repo: Repo, ftp_server: FtpServer
) -> None:
    s = ftp_server
    init(run_cli, s)
    (repo.path / "test 1.txt").unlink()
    os.symlink("test 2.txt", repo.path / "test 1.txt")
    repo.commit("typechange")
    r = run_cli("push", *auth(s), s.url())
    assert r.code == 0, r
    assert "1 file to sync:" in r.stdout
    assert s.remote().read("test 1.txt") == "2\n"


def test_running_from_subdirectory(
    run_cli: RunCli, repo: Repo, ftp_server: FtpServer, monkeypatch: pytest.MonkeyPatch
) -> None:
    s = ftp_server
    repo.write(".git-ftp-ignore", "test 5.txt\n")
    repo.commit("ignore")
    monkeypatch.chdir(repo.path / "dir 2")
    r = run_cli("init", *auth(s), s.url())
    assert r.code == 0, r
    assert s.remote().exists("dir 1/test 1.txt")
    assert not s.remote().exists("test 5.txt")
    r = run_cli("push", "--syncroot", "dir 3", "-a", *auth(s), s.url("sub"), "--auto-init")
    assert r.code == 0, r
    assert s.remote("sub").exists("test 3.txt")


def test_env_vars(
    run_cli: RunCli, repo: Repo, ftp_server: FtpServer, monkeypatch: pytest.MonkeyPatch
) -> None:
    s = ftp_server
    monkeypatch.setenv("GIT_FTP_URL", s.url())
    monkeypatch.setenv("GIT_FTP_USER", s.USER)
    monkeypatch.setenv("GIT_FTP_PASSWORD", s.PASSWORD)
    assert run_cli("init").code == 0
    assert s.remote().log() == repo.head()
