from __future__ import annotations

import pytest

from tests.conftest import RunCli
from tests.helpers.ftpserver import FtpServer
from tests.helpers.gitrepo import Repo
from tests.integration.conftest import auth


def init_verbose(run_cli: RunCli, s: FtpServer, *extra: str) -> str:
    r = run_cli("init", "-v", *extra, *auth(s), s.url())
    assert r.code == 0, r
    return r.stderr


def test_insecure_default_0(run_cli: RunCli, repo: Repo, ftp_server: FtpServer) -> None:
    assert "Insecure is '0'." in init_verbose(run_cli, ftp_server)


@pytest.mark.parametrize(
    ("value", "expected"), [("1", "1"), ("0", "0"), ("true", "1"), ("false", "0")]
)
def test_insecure_from_config(
    run_cli: RunCli, repo: Repo, ftp_server: FtpServer, value: str, expected: str
) -> None:
    repo.config("git-ftp.insecure", value)
    assert f"Insecure is '{expected}'." in init_verbose(run_cli, ftp_server)


def test_insecure_flag(run_cli: RunCli, repo: Repo, ftp_server: FtpServer) -> None:
    assert "Insecure is '1'." in init_verbose(run_cli, ftp_server, "--insecure")


def test_epsv_default_not_disabled(run_cli: RunCli, repo: Repo, ftp_server: FtpServer) -> None:
    assert "Disable EPSV" not in init_verbose(run_cli, ftp_server)


@pytest.mark.parametrize(
    ("value", "disabled"), [("1", True), ("0", False), ("true", True), ("false", False)]
)
def test_epsv_from_config(
    run_cli: RunCli, repo: Repo, ftp_server: FtpServer, value: str, disabled: bool
) -> None:
    repo.config("git-ftp.disable-epsv", value)
    err = init_verbose(run_cli, ftp_server)
    assert ("Disable EPSV is '1'." in err) is disabled


def test_epsv_flag(run_cli: RunCli, repo: Repo, ftp_server: FtpServer) -> None:
    assert "Disable EPSV is '1'." in init_verbose(run_cli, ftp_server, "--disable-epsv")


def test_active_mode(run_cli: RunCli, repo: Repo, ftp_server: FtpServer) -> None:
    # Sequential on purpose: pyftpdlib's single-threaded active-mode connector is
    # flaky with several simultaneous PORT transfers under the coverage tracer.
    # The docker job exercises active mode with parallel connections.
    s = ftp_server
    r = run_cli("init", "-A", "-j", "1", *auth(s), s.url())
    assert r.code == 0, r
    assert s.remote().log() == repo.head()


def test_trace_output_redacts_password(run_cli: RunCli, repo: Repo, ftp_server: FtpServer) -> None:
    s = ftp_server
    r = run_cli("init", "-vv", *auth(s), s.url())
    assert r.code == 0
    assert "PASS ***" in r.stderr
    assert s.PASSWORD not in r.stderr
