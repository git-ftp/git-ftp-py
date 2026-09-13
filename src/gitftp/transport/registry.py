"""Scheme to transport factory."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from gitftp.auth import Credentials
from gitftp.errors import UnknownProtocolError
from gitftp.output import Output
from gitftp.transport.base import Connector, Transport
from gitftp.url import RemoteURL, Scheme


@dataclass
class TransportOptions:
    insecure: bool = False
    cacert: str | None = None
    active: bool = False
    disable_epsv: bool = False
    proxy: str | None = None
    trace: Callable[[str], None] | None = None
    known_hosts_files: list[str] | None = None


def check_available(scheme: Scheme) -> None:
    if scheme is Scheme.SFTP:
        from gitftp.transport import sftp

        sftp.check_available()
    else:
        from gitftp.transport import curlftp

        curlftp.check_available(scheme)


def connector(
    url: RemoteURL, creds: Credentials, topts: TransportOptions, out: Output
) -> Connector:
    """Return a factory that opens a fresh connection each time it is called."""
    if url.scheme is Scheme.SFTP:
        from gitftp.transport.sftp import DirCache, SftpOptions, SftpTransport

        cache = DirCache()
        sopts = SftpOptions(
            insecure=topts.insecure, trace=topts.trace, known_hosts_files=topts.known_hosts_files
        )

        def open_sftp() -> Transport:
            t = SftpTransport(url, creds, sopts, out, dircache=cache)
            t.open()
            return t

        return open_sftp
    if url.scheme in (Scheme.FTP, Scheme.FTPS, Scheme.FTPES):
        from gitftp.transport.curlftp import CurlFtpTransport, CurlOptions

        copts = CurlOptions(
            insecure=topts.insecure,
            cacert=topts.cacert,
            active=topts.active,
            disable_epsv=topts.disable_epsv,
            proxy=topts.proxy,
            trace=topts.trace,
        )

        def open_ftp() -> Transport:
            t = CurlFtpTransport(url, creds, copts, out)
            t.open()
            return t

        return open_ftp
    raise UnknownProtocolError(f"Protocol unknown '{url.scheme.value}://'.")
