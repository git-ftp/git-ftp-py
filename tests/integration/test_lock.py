from __future__ import annotations

from tests.conftest import RunCli
from tests.helpers.ftpserver import FtpServer
from tests.helpers.gitrepo import Repo
from tests.integration.conftest import auth


def test_lock_written_with_real_newline_and_removed(
    run_cli: RunCli, repo: Repo, ftp_server: FtpServer
) -> None:
    s = ftp_server
    r = run_cli("init", "--lock", *auth(s), s.url())
    assert r.code == 0
    assert s.remote().lock() is None
    assert "site/git-ftp.lck" in s.received


def test_lock_blocks_foreign_commit_exit_7(
    run_cli: RunCli, repo: Repo, ftp_server: FtpServer
) -> None:
    s = ftp_server
    assert run_cli("init", *auth(s), s.url()).code == 0
    s.remote().write(
        "git-ftp.lck", "0000000000000000000000000000000000000000\nsomeone@host on Mon\n"
    )
    repo.write("x", "x")
    repo.commit("x")
    r = run_cli("push", "-l", *auth(s), s.url())
    assert r.code == 7
    assert "fatal: Remote locked by someone@host on Mon." in r.stderr
    assert (
        run_cli("push", *auth(s), s.url()).code == 0
    )  # without --lock the lock is not checked (upstream)


def test_lock_upstream_literal_backslash_n_parsed(
    run_cli: RunCli, repo: Repo, ftp_server: FtpServer
) -> None:
    s = ftp_server
    assert run_cli("init", *auth(s), s.url()).code == 0
    s.remote().write(
        "git-ftp.lck", "0000000000000000000000000000000000000000\\nsomeone@host on Mon"
    )
    r = run_cli("push", "-l", "-a", *auth(s), s.url())
    assert r.code == 7
    assert "Remote locked by someone@host on Mon." in r.stderr


def test_lock_own_commit_passes(run_cli: RunCli, repo: Repo, ftp_server: FtpServer) -> None:
    s = ftp_server
    assert run_cli("init", *auth(s), s.url()).code == 0
    s.remote().write("git-ftp.lck", f"{repo.head()}\nme@host on Mon\n")
    assert run_cli("push", "-l", "-a", *auth(s), s.url()).code == 0
    assert s.remote().lock() is None


def test_lock_force_ignores(run_cli: RunCli, repo: Repo, ftp_server: FtpServer) -> None:
    s = ftp_server
    assert run_cli("init", *auth(s), s.url()).code == 0
    s.remote().write(
        "git-ftp.lck", "0000000000000000000000000000000000000000\nsomeone@host on Mon\n"
    )
    assert run_cli("push", "-l", "-a", "-f", *auth(s), s.url()).code == 0


def test_lock_flag_twice_stays_on(run_cli: RunCli, repo: Repo, ftp_server: FtpServer) -> None:
    s = ftp_server
    r = run_cli("init", "-l", "-l", *auth(s), s.url())
    assert r.code == 0
    assert "site/git-ftp.lck" in s.received


def test_unlock(run_cli: RunCli, repo: Repo, ftp_server: FtpServer) -> None:
    s = ftp_server
    assert run_cli("init", *auth(s), s.url()).code == 0
    s.remote().write(
        "git-ftp.lck", "0000000000000000000000000000000000000000\nsomeone@host on Mon\n"
    )
    r = run_cli("unlock", *auth(s), s.url())
    assert r.code == 0
    assert "Remote lock removed." in r.stdout
    assert s.remote().lock() is None
    assert run_cli("unlock", *auth(s), s.url()).code == 0
