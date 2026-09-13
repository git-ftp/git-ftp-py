from __future__ import annotations

import sys

import pytest

from tests.conftest import RunCli
from tests.helpers.ftpserver import FtpServer
from tests.helpers.gitrepo import Repo
from tests.integration.conftest import auth


def test_config_defaults_url_user_password(
    run_cli: RunCli, repo: Repo, ftp_server: FtpServer
) -> None:
    s = ftp_server
    repo.config("git-ftp.user", s.USER)
    repo.config("git-ftp.password", s.PASSWORD)
    repo.config("git-ftp.url", s.url())
    assert run_cli("init").code == 0
    assert s.remote().log() == repo.head()


def test_cli_url_beats_config(run_cli: RunCli, repo: Repo, ftp_server: FtpServer) -> None:
    s = ftp_server
    repo.config("git-ftp.user", s.USER)
    repo.config("git-ftp.password", s.PASSWORD)
    repo.config("git-ftp.url", "ftp://127.0.0.1:1/bogus")
    assert run_cli("init", s.url()).code == 0


def test_cli_user_beats_config(run_cli: RunCli, repo: Repo, ftp_server: FtpServer) -> None:
    s = ftp_server
    repo.config("git-ftp.user", "johndoe")
    repo.config("git-ftp.password", s.PASSWORD)
    repo.config("git-ftp.url", s.url())
    assert run_cli("init", "-u", s.USER).code == 0


def test_cli_password_beats_config(run_cli: RunCli, repo: Repo, ftp_server: FtpServer) -> None:
    s = ftp_server
    repo.config("git-ftp.user", s.USER)
    repo.config("git-ftp.password", "wrong")
    repo.config("git-ftp.url", s.url())
    assert run_cli("init", "-p", s.PASSWORD).code == 0


def test_scope_password_overrides_default(
    run_cli: RunCli, repo: Repo, ftp_server: FtpServer
) -> None:
    s = ftp_server
    repo.config("git-ftp.user", s.USER)
    repo.config("git-ftp.password", "wrong")
    repo.config("git-ftp.url", s.url())
    repo.config("git-ftp.testing.password", s.PASSWORD)
    assert run_cli("init", "-s", "testing").code == 0


def test_invalid_scope_name_exit_2(run_cli: RunCli, repo: Repo) -> None:
    r = run_cli("init", "-s", "invalid:scope", "ftp://127.0.0.1:1/")
    assert r.code == 2
    assert "fatal: Invalid scope name 'invalid:scope'." in r.stderr
    r = run_cli("add-scope", "invalid:scope", "ftp://h/")
    assert r.code == 2
    assert (
        "fatal: Invalid scope name. Only these characters are allowed: 0-9 a-z A-Z - _ /"
        in r.stderr
    )


def test_bare_s_uses_branch_name(run_cli: RunCli, repo: Repo, ftp_server: FtpServer) -> None:
    s = ftp_server
    repo.checkout("production", new=True)
    repo.config("git-ftp.production.user", s.USER)
    repo.config("git-ftp.production.password", s.PASSWORD)
    repo.config("git-ftp.production.url", s.url())
    assert run_cli("init", "-s").code == 0
    assert s.remote().log() == repo.head()


def test_nested_branch_scope(run_cli: RunCli, repo: Repo, ftp_server: FtpServer) -> None:
    s = ftp_server
    repo.checkout("nested/branch", new=True)
    assert run_cli("add-scope", "nested/branch", s.url(creds=True)).code == 0
    assert run_cli("init", "-s").code == 0
    assert s.remote().log() == repo.head()


def test_scope_empty_url_overrides_exit_3(
    run_cli: RunCli, repo: Repo, ftp_server: FtpServer
) -> None:
    s = ftp_server
    repo.config("git-ftp.user", s.USER)
    repo.config("git-ftp.password", s.PASSWORD)
    repo.config("git-ftp.url", s.url())
    repo.config("git-ftp.testing.url", "")
    r = run_cli("init", "-s", "testing")
    assert r.code == 3


def test_cli_password_beats_scope(run_cli: RunCli, repo: Repo, ftp_server: FtpServer) -> None:
    s = ftp_server
    repo.config("git-ftp.user", s.USER)
    repo.config("git-ftp.password", "wrong")
    repo.config("git-ftp.url", s.url())
    repo.config("git-ftp.testing.password", "alsowrong")
    assert run_cli("init", "-s", "testing", "-p", s.PASSWORD).code == 0


def test_add_scope_password_with_colon_and_at(run_cli: RunCli, repo: Repo) -> None:
    r = run_cli("add-scope", "xyz", "ftpes://user:pa:ss@w@ftp.example.com/xyz")
    assert r.code == 0, r
    assert repo.git("config", "git-ftp.xyz.url").stdout.strip() == "ftpes://ftp.example.com/xyz"
    assert repo.git("config", "git-ftp.xyz.user").stdout.strip() == "user"
    assert repo.git("config", "git-ftp.xyz.password").stdout.strip() == "pa:ss@w"
    assert "Warning" not in r.stdout


def test_add_scope_password_starting_with_dash(run_cli: RunCli, repo: Repo) -> None:
    assert run_cli("add-scope", "d", "ftp://user:-p%40ss@h/x").code == 0
    assert repo.git("config", "git-ftp.d.password").stdout.strip() == "-p@ss"


def test_remove_scope(run_cli: RunCli, repo: Repo) -> None:
    assert run_cli("add-scope", "xyz", "ftp://h/x").code == 0
    r = run_cli("remove-scope", "xyz")
    assert r.code == 0
    assert "Successfully removed scope xyz." in r.stdout
    r = run_cli("remove-scope", "xyz")
    assert r.code == 8
    assert "fatal: Cannot find scope xyz." in r.stderr


def test_git_ftp_config_file(run_cli: RunCli, repo: Repo, ftp_server: FtpServer) -> None:
    s = ftp_server
    repo.write(
        ".git-ftp-config",
        f"[git-ftp]\n\turl = {s.url()}\n\tuser = {s.USER}\n\tpassword = {s.PASSWORD}\n"
        f'[git-ftp "other"]\n\turl = {s.url("other")}\n',
    )
    repo.commit("cfg")
    assert run_cli("init").code == 0
    assert s.remote().log() == repo.head()
    assert run_cli("init", "-s", "other").code == 0
    assert s.remote("other").log() == repo.head()


def test_env_precedence(
    run_cli: RunCli, repo: Repo, ftp_server: FtpServer, monkeypatch: pytest.MonkeyPatch
) -> None:
    s = ftp_server
    repo.config("git-ftp.password", "wrong")
    monkeypatch.setenv("GIT_FTP_PASSWORD", s.PASSWORD)
    assert run_cli("init", "-u", s.USER, s.url()).code == 0
    r = run_cli("init", "-u", s.USER, "-p", "cli-wrong", s.url("b"))
    assert r.code == 4


@pytest.mark.skipif(sys.platform == "win32", reason="sh")
def test_password_command(run_cli: RunCli, repo: Repo, ftp_server: FtpServer) -> None:
    s = ftp_server
    repo.config("git-ftp.password-command", f"printf '{s.PASSWORD}\\nignored'")
    assert run_cli("init", "-u", s.USER, s.url()).code == 0
    r = run_cli("init", "-u", s.USER, "--password-command", "exit 3", s.url("b"))
    assert r.code == 3
    assert "Password command failed" in r.stderr


def test_netrc_fallback(run_cli: RunCli, repo: Repo, ftp_server: FtpServer, home) -> None:  # type: ignore[no-untyped-def]
    s = ftp_server
    netrc = home / ".netrc"
    netrc.write_text(f"machine {s.host} login {s.USER} password {s.PASSWORD}\n")
    netrc.chmod(0o600)
    assert run_cli("init", s.url()).code == 0
    assert s.remote().log() == repo.head()


def test_ask_password(run_cli: RunCli, repo: Repo, ftp_server: FtpServer) -> None:
    s = ftp_server
    r = run_cli("init", "-u", s.USER, "-P", s.url(), input=f"{s.PASSWORD}\n")
    assert r.code == 0, r


def test_scope_user_env_and_url_beats_config(
    run_cli: RunCli, repo: Repo, ftp_server: FtpServer, monkeypatch: pytest.MonkeyPatch
) -> None:
    s = ftp_server
    repo.config("git-ftp.user", "wrong")
    monkeypatch.setenv("GIT_FTP_USER", s.USER)
    assert run_cli("init", "-p", s.PASSWORD, s.url()).code == 0
    assert auth(s)


def test_remote_root_replaces_url_path(run_cli: RunCli, repo: Repo, ftp_server: FtpServer) -> None:
    s = ftp_server
    r = run_cli("init", "--remote-root", "other", *auth(s), s.url("site"))
    assert r.code == 0
    assert s.remote("other").log() == repo.head()
    assert not s.remote("site").exists(".git-ftp.log")
    repo.config("git-ftp.remote-root", "third")
    repo.write("x", "x")
    repo.commit("x")
    assert run_cli("init", *auth(s), s.url("site")).code == 0
    assert s.remote("third").log() == repo.head()
