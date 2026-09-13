from __future__ import annotations

from gitftp.version import __version__
from tests.conftest import RunCli
from tests.helpers.ftpserver import FtpServer
from tests.helpers.gitrepo import Repo
from tests.integration.conftest import auth


def test_no_arguments_prints_usage_exit_2(run_cli: RunCli) -> None:
    r = run_cli()
    assert r.code == 2
    assert r.stdout.splitlines()[0] == "git-ftp <action> [<options>] [<url>]"


def test_version_flag_and_action(run_cli: RunCli) -> None:
    assert run_cli("--version").stdout.strip() == f"git-ftp version {__version__}"
    assert run_cli("version").stdout.strip() == f"git-ftp version {__version__}"
    assert "libcurl" in run_cli("version", "-v").stdout


def test_help(run_cli: RunCli) -> None:
    r = run_cli("help")
    assert r.code == 0
    assert "push" in r.stdout and "--syncroot" in r.stdout
    assert run_cli("--help").code == 0


def test_unknown_protocol_exit_6(run_cli: RunCli, repo: Repo) -> None:
    r = run_cli("init", "badProtocol://localhost/")
    assert r.code == 6
    assert "fatal: Protocol unknown 'badprotocol://'." in r.stderr


def test_unknown_action_exit_3(run_cli: RunCli) -> None:
    r = run_cli("bogus")
    assert r.code == 3
    assert "fatal: Action unknown." in r.stderr


def test_ftp_and_ftpes_schemes_are_supported(run_cli: RunCli, repo: Repo) -> None:
    for scheme in ("ftp", "ftpes"):
        r = run_cli("init", "-u", "u", "-p", "p", f"{scheme}://127.0.0.1:1/")
        assert r.code == 4, r
        assert "not supported" not in r.stderr
        assert "Protocol unknown" not in r.stderr


def test_missing_url_exit_3(run_cli: RunCli, repo: Repo) -> None:
    r = run_cli("push")
    assert r.code == 3
    assert "fatal: Remote host not set." in r.stderr


def test_not_a_git_project_exit_8(run_cli: RunCli, home, tmp_path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.chdir(tmp_path)
    r = run_cli("push", "ftp://127.0.0.1:1/")
    assert r.code == 8
    assert "Not a Git project?" in r.stderr


def test_dirty_repository_exit_8(run_cli: RunCli, repo: Repo, ftp_server: FtpServer) -> None:
    repo.append("test 1.txt", "dirty")
    r = run_cli("init", *auth(ftp_server), ftp_server.url())
    assert r.code == 8
    assert "Dirty repository: Having uncommitted changes. Exiting..." in r.stderr


def test_silent_still_prints_fatal_to_stderr(
    run_cli: RunCli, repo: Repo, ftp_server: FtpServer
) -> None:
    r = run_cli("push", "-n", *auth(ftp_server), ftp_server.url())
    assert r.code == 5
    assert r.stdout == ""
    assert r.stderr.startswith("fatal: Could not get last commit.")


def test_unknown_option_exit_3(run_cli: RunCli, repo: Repo) -> None:
    r = run_cli("push", "--bogus")
    assert r.code == 3
    assert "fatal:" in r.stderr
