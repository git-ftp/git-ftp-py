"""In-process SFTP server on paramiko, jailed to a temporary directory."""

from __future__ import annotations

import contextlib
import io
import os
import socket
import threading
from pathlib import Path
from typing import Any

import paramiko
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ed25519
from paramiko import ServerInterface, SFTPAttributes, SFTPHandle, SFTPServer, SFTPServerInterface
from paramiko.common import (
    AUTH_FAILED,
    AUTH_SUCCESSFUL,
    OPEN_FAILED_ADMINISTRATIVELY_PROHIBITED,
    OPEN_SUCCEEDED,
)
from paramiko.sftp import SFTP_OK, SFTP_PERMISSION_DENIED

from tests.helpers.remote import Remote


def _errno(e: OSError) -> int:
    return int(SFTPServer.convert_errno(e.errno or 0))


class _Handle(SFTPHandle):
    readfile: Any
    writefile: Any
    filename: str

    def __init__(self, flags: int = 0, owner: SftpServer | None = None, rel: str = "") -> None:
        super().__init__(flags)
        self._owner = owner
        self._rel = rel

    def stat(self) -> Any:
        try:
            return SFTPAttributes.from_stat(os.fstat(self.readfile.fileno()))
        except OSError as e:
            return _errno(e)

    def chattr(self, attr: Any) -> int:
        try:
            SFTPServer.set_file_attr(self.filename, attr)
            return int(SFTP_OK)
        except OSError as e:
            return _errno(e)

    def close(self) -> None:
        super().close()
        if self._owner is not None and self._rel:
            with self._owner._lock:
                self._owner.received.append(self._rel)


class _Fs(SFTPServerInterface):
    def __init__(self, server: Any, *args: Any, root: Path, owner: SftpServer, **kw: Any) -> None:
        super().__init__(server, *args, **kw)
        self.root = root.resolve()
        self.owner = owner

    def _real(self, path: str) -> Path:
        canon = self.canonicalize(path)
        p = (self.root / canon.lstrip("/")).resolve()
        if p != self.root and self.root not in p.parents:
            raise PermissionError(path)
        return p

    def _rel(self, path: str) -> str:
        return self._real(path).relative_to(self.root).as_posix()

    def list_folder(self, path: str) -> Any:
        try:
            out = []
            for name in sorted(os.listdir(self._real(path))):
                attr = SFTPAttributes.from_stat(os.lstat(self._real(path) / name))
                attr.filename = name
                out.append(attr)
            return out
        except OSError as e:
            return _errno(e)

    def stat(self, path: str) -> Any:
        try:
            return SFTPAttributes.from_stat(os.stat(self._real(path)))
        except OSError as e:
            return _errno(e)

    def lstat(self, path: str) -> Any:
        try:
            return SFTPAttributes.from_stat(os.lstat(self._real(path)))
        except OSError as e:
            return _errno(e)

    def open(self, path: str, flags: int, attr: Any) -> Any:
        rel = self._rel(path)
        writing = bool(flags & (os.O_WRONLY | os.O_RDWR))
        if writing and rel in self.owner.denied:
            return int(SFTP_PERMISSION_DENIED)
        real = self._real(path)
        binary_flag = getattr(os, "O_BINARY", 0)
        flags |= binary_flag
        mode = getattr(attr, "st_mode", None) or 0o666
        try:
            fd = os.open(real, flags, mode)
        except OSError as e:
            return _errno(e)
        if flags & os.O_CREAT and attr is not None:
            attr._flags &= ~attr.FLAG_PERMISSIONS
            SFTPServer.set_file_attr(str(real), attr)
        if flags & os.O_WRONLY:
            fstr = "ab" if flags & os.O_APPEND else "wb"
        elif flags & os.O_RDWR:
            fstr = "a+b" if flags & os.O_APPEND else "r+b"
        else:
            fstr = "rb"
        try:
            f = os.fdopen(fd, fstr)
        except OSError as e:
            return _errno(e)
        handle = _Handle(flags, self.owner if writing else None, rel if writing else "")
        handle.filename = str(real)
        handle.readfile = f
        handle.writefile = f
        return handle

    def remove(self, path: str) -> int:
        try:
            os.remove(self._real(path))
            return int(SFTP_OK)
        except OSError as e:
            return _errno(e)

    def rename(self, oldpath: str, newpath: str) -> int:
        try:
            os.rename(self._real(oldpath), self._real(newpath))
            return int(SFTP_OK)
        except OSError as e:
            return _errno(e)

    def posix_rename(self, oldpath: str, newpath: str) -> int:
        return self.rename(oldpath, newpath)

    def mkdir(self, path: str, attr: Any) -> int:
        try:
            os.mkdir(self._real(path))
            if attr is not None:
                SFTPServer.set_file_attr(str(self._real(path)), attr)
            return int(SFTP_OK)
        except OSError as e:
            return _errno(e)

    def rmdir(self, path: str) -> int:
        try:
            os.rmdir(self._real(path))
            return int(SFTP_OK)
        except OSError as e:
            return _errno(e)

    def chattr(self, path: str, attr: Any) -> int:
        try:
            SFTPServer.set_file_attr(str(self._real(path)), attr)
            return int(SFTP_OK)
        except OSError as e:
            return _errno(e)


class _Auth(ServerInterface):
    def __init__(self, owner: SftpServer) -> None:
        self.owner = owner

    def check_auth_password(self, username: str, password: str) -> int:
        ok = (username, password) == (self.owner.USER, self.owner.PASSWORD)
        return int(AUTH_SUCCESSFUL if ok else AUTH_FAILED)

    def check_auth_publickey(self, username: str, key: Any) -> int:
        ok = username == self.owner.USER and key == self.owner.client_pub
        return int(AUTH_SUCCESSFUL if ok else AUTH_FAILED)

    def get_allowed_auths(self, username: str) -> str:
        return "password,publickey"

    def check_channel_request(self, kind: str, chanid: int) -> int:
        return int(OPEN_SUCCEEDED if kind == "session" else OPEN_FAILED_ADMINISTRATIVELY_PROHIBITED)


def _ed25519_key() -> paramiko.Ed25519Key:
    priv = ed25519.Ed25519PrivateKey.generate()
    pem = priv.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.OpenSSH,
        serialization.NoEncryption(),
    ).decode()
    return paramiko.Ed25519Key.from_private_key(io.StringIO(pem))


class SftpServer:
    USER = "gitftp"
    PASSWORD = "s3cret"
    KEY_PASSPHRASE = "keypass"

    def __init__(self, root: Path, keydir: Path, host_key: str = "ed25519") -> None:
        self.root = root
        self.received: list[str] = []
        self.denied: set[str] = set()
        self._lock = threading.Lock()
        self.host_key: paramiko.PKey
        if host_key == "rsa":
            self.host_key = paramiko.RSAKey.generate(2048)
        else:
            self.host_key = _ed25519_key()
        keydir.mkdir(parents=True, exist_ok=True)
        client = ed25519.Ed25519PrivateKey.generate()
        self.client_key_path = keydir / "id_ed25519"
        self.client_key_path.write_bytes(
            client.private_bytes(
                serialization.Encoding.PEM,
                serialization.PrivateFormat.OpenSSH,
                serialization.NoEncryption(),
            )
        )
        self.client_key_path.chmod(0o600)
        self.encrypted_client_key_path = keydir / "id_ed25519_enc"
        self.encrypted_client_key_path.write_bytes(
            client.private_bytes(
                serialization.Encoding.PEM,
                serialization.PrivateFormat.OpenSSH,
                serialization.BestAvailableEncryption(self.KEY_PASSPHRASE.encode()),
            )
        )
        self.encrypted_client_key_path.chmod(0o600)
        self.client_pub = paramiko.Ed25519Key.from_private_key_file(str(self.client_key_path))
        (keydir / "id_ed25519.pub").write_text(
            f"{self.client_pub.get_name()} {self.client_pub.get_base64()} test\n"
        )
        self._sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._sock.bind(("127.0.0.1", 0))
        self._sock.listen(32)
        self.host, self.port = self._sock.getsockname()
        self._transports: list[paramiko.Transport] = []
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._accept_loop, name="sftpd", daemon=True)

    def _accept_loop(self) -> None:
        while not self._stop.is_set():
            try:
                conn, _ = self._sock.accept()
            except OSError:
                return
            t = paramiko.Transport(conn)
            t.add_server_key(self.host_key)
            t.set_subsystem_handler("sftp", SFTPServer, _Fs, root=self.root, owner=self)
            try:
                t.start_server(server=_Auth(self))
            except paramiko.SSHException:
                continue
            self._transports.append(t)

    def start(self) -> SftpServer:
        self._thread.start()
        return self

    def stop(self) -> None:
        self._stop.set()
        with contextlib.suppress(OSError):
            self._sock.close()
        for t in self._transports:
            t.close()
        self._thread.join(5)

    @property
    def hostport(self) -> str:
        return f"{self.host}:{self.port}"

    def url(self, path: str = "site", creds: bool = False) -> str:
        auth = f"{self.USER}:{self.PASSWORD}@" if creds else ""
        return f"sftp://{auth}{self.host}:{self.port}/{path}"

    def known_hosts_line(self) -> str:
        return (
            f"[{self.host}]:{self.port} {self.host_key.get_name()} {self.host_key.get_base64()}\n"
        )

    def remote(self, path: str = "site", deployed_file: str = ".git-ftp.log") -> Remote:
        return Remote(self.root / path if path else self.root, deployed_file)

    def deny_upload(self, rel: str) -> None:
        self.denied.add(rel)
