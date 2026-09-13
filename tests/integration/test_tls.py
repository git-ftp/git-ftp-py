from __future__ import annotations

import socket
import ssl

from tests.conftest import RunCli
from tests.helpers.ftpserver import FtpServer
from tests.helpers.gitrepo import Repo
from tests.integration.conftest import auth


def test_ftps_fixture_handshakes(ftps_server: FtpServer) -> None:
    ctx = ssl.create_default_context(cafile=ftps_server.cacert)
    with socket.create_connection((ftps_server.host, ftps_server.port), timeout=5) as raw:
        with ctx.wrap_socket(raw, server_hostname="localhost") as tls:
            banner = tls.recv(100)
    assert banner.startswith(b"220")


def test_tls_verification_fails_without_cacert_exit_4(
    run_cli: RunCli, repo: Repo, ftpes_server: FtpServer
) -> None:
    s = ftpes_server
    r = run_cli("init", *auth(s), s.url())
    assert r.code == 4
    assert "TLS verification failed" in r.stderr
    assert "--cacert" in r.stderr and "--insecure" in r.stderr


def test_cacert_option_and_config(run_cli: RunCli, repo: Repo, ftpes_server: FtpServer) -> None:
    s = ftpes_server
    assert s.cacert
    assert run_cli("init", "--cacert", s.cacert, *auth(s), s.url()).code == 0
    repo.config("git-ftp.cacert", s.cacert)
    repo.write("x", "x")
    repo.commit("x")
    assert run_cli("push", *auth(s), s.url()).code == 0
    assert s.remote().exists("x")


def test_insecure_skips_verification(run_cli: RunCli, repo: Repo, ftpes_server: FtpServer) -> None:
    s = ftpes_server
    assert run_cli("init", "--insecure", *auth(s), s.url()).code == 0
    assert s.remote().log() == repo.head()


def test_ftps_implicit_round_trip(run_cli: RunCli, repo: Repo, ftps_server: FtpServer) -> None:
    s = ftps_server
    assert run_cli("init", "--cacert", str(s.cacert), *auth(s), s.url()).code == 0
    repo.rm("test 1.txt")
    repo.write("new.txt", "n\n")
    repo.commit("c")
    assert run_cli("push", "--cacert", str(s.cacert), *auth(s), s.url()).code == 0
    assert not s.remote().exists("test 1.txt")
    assert s.remote().exists("new.txt")


def test_ftpes_server_requires_tls(run_cli: RunCli, repo: Repo, ftpes_server: FtpServer) -> None:
    s = ftpes_server
    r = run_cli("init", *auth(s), s.url(scheme="ftp"))
    assert r.code == 4
