"""Server fixtures for integration tests."""

from __future__ import annotations

import sys
from collections.abc import Callable, Iterator
from pathlib import Path

import pytest

from tests.helpers.certs import Certs, make_certs
from tests.helpers.ftpserver import FtpServer
from tests.helpers.sftpserver import SftpServer

# libcurl's Windows wheel uses the Schannel TLS backend, which cannot trust our
# self-signed test CA via a PEM --cacert (it fails closed on "revocation status
# unknown"), and its TLS data connection to the in-process pyftpdlib server hangs.
# FTPS/FTPES is a test-harness incompatibility there, not a git-ftp bug; it stays
# covered on Linux/macOS (OpenSSL) and by the docker pure-ftpd job.
_TLS_SKIP_REASON = (
    "libcurl uses the Schannel TLS backend on Windows; the in-process pyftpdlib "
    "TLS server is not interoperable (FTPS/FTPES is covered on Linux/macOS and by "
    "the docker job)"
)
_skip_tls_on_windows = pytest.mark.skipif(sys.platform == "win32", reason=_TLS_SKIP_REASON)


@pytest.fixture(scope="session")
def tls_certs(tmp_path_factory: pytest.TempPathFactory) -> Certs:
    return make_certs(tmp_path_factory.mktemp("certs"))


@pytest.fixture
def ftp_server_factory(tmp_path: Path) -> Iterator[Callable[..., FtpServer]]:
    servers: list[FtpServer] = []
    counter = [0]

    def factory(mode: str = "plain", certs: Certs | None = None, **kw: object) -> FtpServer:
        counter[0] += 1
        root = tmp_path / f"ftproot{counter[0]}"
        root.mkdir()
        server = FtpServer(root, mode=mode, certs=certs, **kw).start()  # type: ignore[arg-type]
        servers.append(server)
        return server

    yield factory
    for s in servers:
        s.stop()


@pytest.fixture
def ftp_server(ftp_server_factory: Callable[..., FtpServer]) -> FtpServer:
    return ftp_server_factory("plain")


@pytest.fixture
def ftpes_server(ftp_server_factory: Callable[..., FtpServer], tls_certs: Certs) -> FtpServer:
    if sys.platform == "win32":
        pytest.skip(_TLS_SKIP_REASON)
    return ftp_server_factory("explicit", tls_certs)


@pytest.fixture
def ftps_server(ftp_server_factory: Callable[..., FtpServer], tls_certs: Certs) -> FtpServer:
    if sys.platform == "win32":
        pytest.skip(_TLS_SKIP_REASON)
    return ftp_server_factory("implicit", tls_certs)


@pytest.fixture(
    params=[
        "ftp",
        pytest.param("ftpes", marks=_skip_tls_on_windows),
        pytest.param("ftps", marks=_skip_tls_on_windows),
    ]
)
def any_ftp_server(
    request: pytest.FixtureRequest, ftp_server_factory: Callable[..., FtpServer], tls_certs: Certs
) -> FtpServer:
    mode = {"ftp": "plain", "ftpes": "explicit", "ftps": "implicit"}[request.param]
    return ftp_server_factory(mode, tls_certs if mode != "plain" else None)


@pytest.fixture
def sftp_server_factory(tmp_path: Path) -> Iterator[Callable[..., SftpServer]]:
    servers: list[SftpServer] = []
    counter = [0]

    def factory(host_key: str = "ed25519") -> SftpServer:
        counter[0] += 1
        root = tmp_path / f"sftproot{counter[0]}"
        root.mkdir()
        server = SftpServer(root, tmp_path / f"keys{counter[0]}", host_key=host_key).start()
        servers.append(server)
        return server

    yield factory
    for s in servers:
        s.stop()


@pytest.fixture
def sftp_server(sftp_server_factory: Callable[..., SftpServer]) -> SftpServer:
    return sftp_server_factory()


@pytest.fixture
def trusted_sftp_server(sftp_server: SftpServer, home: Path) -> SftpServer:
    """An SFTP server whose host key is already in ~/.ssh/known_hosts."""
    ssh = home / ".ssh"
    ssh.mkdir(exist_ok=True)
    (ssh / "known_hosts").write_text(sftp_server.known_hosts_line())
    return sftp_server


def cacert_args(server: FtpServer) -> list[str]:
    return ["--cacert", server.cacert] if server.cacert else []


def auth(server: FtpServer | SftpServer) -> list[str]:
    return ["-u", server.USER, "-p", server.PASSWORD]
