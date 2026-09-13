"""In-process FTP / FTPES / FTPS server on pyftpdlib."""

from __future__ import annotations

import errno
import logging
import os
import threading
from pathlib import Path
from typing import Any

from pyftpdlib.authorizers import DummyAuthorizer
from pyftpdlib.filesystems import AbstractedFS
from pyftpdlib.handlers import FTPHandler, ThrottledDTPHandler, TLS_FTPHandler
from pyftpdlib.servers import FTPServer

from tests.helpers.certs import Certs
from tests.helpers.remote import Remote

logging.getLogger("pyftpdlib").setLevel(logging.WARNING)

PERM = "elradfmwMT"


class NoChdirFS(AbstractedFS):
    """pyftpdlib's filesystem calls os.chdir() on CWD, which would change the
    working directory of the whole test process; track the directory instead."""

    def chdir(self, path: str) -> None:
        if not self.isdir(path):
            raise FileNotFoundError(errno.ENOENT, os.strerror(errno.ENOENT), path)
        self._cwd = self.fs2ftp(path)


class ImplicitTLSHandler(TLS_FTPHandler):
    """TLS from the first byte (ftps://), which pyftpdlib does not ship."""

    def handle(self) -> None:
        self.secure_connection(self.ssl_context)

    def handle_ssl_established(self) -> None:
        super().handle_ssl_established()
        TLS_FTPHandler.handle(self)

    def ftp_AUTH(self, line: str) -> None:
        self.respond("503 Already using TLS.")


class FtpServer:
    USER = "gitftp"
    PASSWORD = "s3cret"

    def __init__(
        self,
        root: Path,
        mode: str = "plain",
        certs: Certs | None = None,
        *,
        anonymous: bool = False,
        mlsd: bool = True,
        throttle: int | None = None,
    ) -> None:
        self.root = root
        self.mode = mode
        self.certs = certs
        self.received: list[str] = []
        self.denied: set[str] = set()
        self.max_concurrent = 0
        self._connected = 0
        self._lock = threading.Lock()

        authorizer = DummyAuthorizer()
        authorizer.add_user(self.USER, self.PASSWORD, str(root), perm=PERM)
        if anonymous:
            authorizer.add_anonymous(str(root), perm=PERM)
        handler = self._make_handler(mlsd)
        handler.authorizer = authorizer
        handler.abstracted_fs = NoChdirFS
        handler.passive_ports = None
        handler.masquerade_address = None
        handler.permit_foreign_addresses = False
        handler.timeout = 30
        handler.banner = "git-ftp test server ready."
        if throttle:
            dtp: Any = type(
                "ThrottledDTP",
                (ThrottledDTPHandler,),
                {"read_limit": throttle, "write_limit": throttle},
            )
            handler.dtp_handler = dtp
        if certs is not None:
            handler.certfile = str(certs.server_cert_pem)
            handler.keyfile = str(certs.server_key_pem)
            handler.ssl_context = None
            handler.tls_control_required = mode == "explicit"
            handler.tls_data_required = True
        self._server = FTPServer(("127.0.0.1", 0), handler)
        self.host, self.port = self._server.address[:2]
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._serve, name="ftpd", daemon=True)

    def _make_handler(self, mlsd: bool) -> Any:
        owner = self
        base: Any
        if self.mode == "plain":
            base = FTPHandler
        elif self.mode == "explicit":
            base = TLS_FTPHandler
        elif self.mode == "implicit":
            base = ImplicitTLSHandler
        else:
            raise ValueError(self.mode)

        def rel(file: str) -> str:
            return Path(file).resolve().relative_to(owner.root.resolve()).as_posix()

        class RecordingHandler(base):  # type: ignore[misc,valid-type,unused-ignore]
            def on_connect(self) -> None:
                with owner._lock:
                    owner._connected += 1
                    owner.max_concurrent = max(owner.max_concurrent, owner._connected)

            def on_disconnect(self) -> None:
                with owner._lock:
                    owner._connected -= 1

            def on_file_received(self, file: str) -> None:
                with owner._lock:
                    owner.received.append(rel(file))

            def ftp_STOR(self, file: str, mode: str = "w") -> Any:
                if rel(file) in owner.denied:
                    self.respond("553 Permission denied.")
                    return None
                return super().ftp_STOR(file, mode)

        if not mlsd:
            RecordingHandler.proto_cmds = {
                k: v for k, v in base.proto_cmds.items() if k not in ("MLSD", "MLST")
            }
        return RecordingHandler

    def _serve(self) -> None:
        while not self._stop.is_set():
            self._server.serve_forever(timeout=0.05, blocking=False, handle_exit=False)
        self._server.close_all()

    def start(self) -> FtpServer:
        self._thread.start()
        return self

    def stop(self) -> None:
        self._stop.set()
        self._thread.join(5)

    @property
    def scheme(self) -> str:
        return {"plain": "ftp", "explicit": "ftpes", "implicit": "ftps"}[self.mode]

    @property
    def hostport(self) -> str:
        return f"{self.host}:{self.port}"

    def url(self, path: str = "site", creds: bool = False, scheme: str | None = None) -> str:
        auth = f"{self.USER}:{self.PASSWORD}@" if creds else ""
        return f"{scheme or self.scheme}://{auth}{self.host}:{self.port}/{path}"

    def remote(self, path: str = "site", deployed_file: str = ".git-ftp.log") -> Remote:
        return Remote(self.root / path if path else self.root, deployed_file)

    def deny_upload(self, rel: str) -> None:
        self.denied.add(rel)

    @property
    def cacert(self) -> str | None:
        return str(self.certs.ca_pem) if self.certs else None
