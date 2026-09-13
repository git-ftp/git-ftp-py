"""SFTP through paramiko.

Deliberate difference from upstream: host keys are verified against
``~/.ssh/known_hosts`` and ``/etc/ssh/ssh_known_hosts``; ``--insecure`` skips
the check. Authentication order: --key, ssh-agent, password.
"""

from __future__ import annotations

import contextlib
import errno
import logging
import os
import posixpath
import socket
import stat as statmod
import threading
from collections.abc import Callable
from pathlib import Path
from typing import Any

from gitftp.auth import Credentials
from gitftp.errors import DownloadError, MissingArgumentError, UploadError
from gitftp.output import Output
from gitftp.transport.base import Entry, ProgressFn, RemoteNotFound, TransferCancelled, Transport
from gitftp.url import RemoteURL

DEFAULT_PORT = 22
SYSTEM_KNOWN_HOSTS = ["/etc/ssh/ssh_known_hosts"]


def check_available() -> None:
    try:
        import paramiko  # noqa: F401
    except ImportError as e:
        raise DownloadError("paramiko is not available; sftp support is disabled.") from e


class DirCache:
    """Remembers created directories so parallel workers do not race on mkdir."""

    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.known: set[str] = set()


class SftpOptions:
    def __init__(
        self,
        *,
        insecure: bool = False,
        trace: Callable[[str], None] | None = None,
        known_hosts_files: list[str] | None = None,
    ) -> None:
        self.insecure = insecure
        self.trace = trace
        self.known_hosts_files = known_hosts_files


class _TraceHandler(logging.Handler):
    def __init__(self, fn: Callable[[str], None]) -> None:
        super().__init__(logging.DEBUG)
        self.fn = fn

    def emit(self, record: logging.LogRecord) -> None:
        self.fn("* " + record.getMessage())


class SftpTransport(Transport):
    def __init__(
        self,
        url: RemoteURL,
        creds: Credentials,
        options: SftpOptions,
        out: Output,
        dircache: DirCache | None = None,
    ) -> None:
        super().__init__()
        self.url = url
        self.creds = creds
        self.options = options
        self.out = out
        self.dircache = dircache or DirCache()
        self._transport: Any = None
        self._sftp: Any = None

    # -- lifecycle ---------------------------------------------------------
    def open(self) -> None:
        import paramiko

        host = self.url.hostname
        port = self.url.port or DEFAULT_PORT
        if self.options.trace is not None:
            logger = logging.getLogger("paramiko.transport")
            logger.setLevel(logging.DEBUG)
            if not any(isinstance(h, _TraceHandler) for h in logger.handlers):
                logger.addHandler(_TraceHandler(self.options.trace))
        try:
            sock = socket.create_connection((host, port), timeout=30)
        except OSError as e:
            raise DownloadError(
                f"Can't access remote '{self.url.display()}'. Network down? Wrong URL? ({e})"
            ) from e
        t = paramiko.Transport(sock)
        expected = None
        if not self.options.insecure:
            expected = self._known_host_keys(host, port)
            if expected:
                opts = t.get_security_options()
                preferred = [k for k in expected if k in opts.key_types]
                opts.key_types = tuple(
                    preferred + [k for k in opts.key_types if k not in preferred]
                )
        try:
            t.start_client(timeout=30)
        except (paramiko.SSHException, OSError) as e:
            t.close()
            raise DownloadError(
                f"Can't access remote '{self.url.display()}'. SSH handshake failed ({e})."
            ) from e
        if not self.options.insecure:
            self._verify_host_key(t, host, port, expected or {})
        self._transport = t
        try:
            self._authenticate(t)
        except BaseException:
            t.close()
            raise
        sftp = paramiko.SFTPClient.from_transport(t)
        if sftp is None:  # pragma: no cover
            t.close()
            raise DownloadError("Could not open the SFTP subsystem.")
        chan = sftp.get_channel()
        if chan is not None:
            chan.settimeout(60)
        self._sftp = sftp

    def close(self) -> None:
        if self._sftp is not None:
            with contextlib.suppress(Exception):
                self._sftp.close()
            self._sftp = None
        if self._transport is not None:
            with contextlib.suppress(Exception):
                self._transport.close()
            self._transport = None

    # -- host keys ---------------------------------------------------------
    def _known_hosts_paths(self) -> list[Path]:
        if self.options.known_hosts_files is not None:
            return [Path(p) for p in self.options.known_hosts_files]
        paths = [Path.home() / ".ssh" / "known_hosts"]
        paths += [Path(p) for p in SYSTEM_KNOWN_HOSTS]
        return paths

    def _known_host_keys(self, host: str, port: int) -> dict[str, Any]:
        import paramiko

        hostkeys = paramiko.HostKeys()
        for path in self._known_hosts_paths():
            if path.is_file():
                try:
                    hostkeys.load(str(path))
                except OSError:
                    continue
        name = host if port == DEFAULT_PORT else f"[{host}]:{port}"
        found = hostkeys.lookup(name)
        if found is None and port != DEFAULT_PORT:
            found = None
        return dict(found) if found else {}

    def _verify_host_key(self, t: Any, host: str, port: int, expected: dict[str, Any]) -> None:
        key = t.get_remote_server_key()
        name = host if port == DEFAULT_PORT else f"[{host}]:{port}"
        hint = f"ssh-keyscan -p {port} {host} >> ~/.ssh/known_hosts"
        if not expected:
            t.close()
            raise DownloadError(
                f"Host key verification failed: '{name}' is not in known_hosts. "
                f"Add it with '{hint}' or pass --insecure."
            )
        known = expected.get(key.get_name())
        if known is None or known.asbytes() != key.asbytes():
            t.close()
            raise DownloadError(
                f"Host key verification failed: the {key.get_name()} key of '{name}' does not "
                "match known_hosts. If the server changed, update known_hosts "
                f"({hint}) or pass --insecure."
            )

    # -- auth --------------------------------------------------------------
    def _load_private_key(self) -> Any:
        import paramiko

        assert self.creds.key
        path = self.creds.key
        passphrase = self.creds.key_passphrase
        classes: list[type[paramiko.PKey]] = [
            paramiko.Ed25519Key,
            paramiko.RSAKey,
            paramiko.ECDSAKey,
        ]
        for _attempt in range(2):
            last: Exception | None = None
            for cls in classes:
                try:
                    return cls.from_private_key_file(path, password=passphrase or None)
                except paramiko.PasswordRequiredException:
                    last = None
                    break
                except paramiko.SSHException as e:
                    last = e
            else:
                raise DownloadError(f"Could not read private key '{path}': {last}")
            # Needs a passphrase
            if passphrase:
                raise DownloadError(f"Wrong passphrase for private key '{path}'.")
            if not self.out.stdin.isatty() and self.out._stdin is None:
                raise MissingArgumentError(
                    f"Private key '{path}' is encrypted; give --key-passphrase."
                )
            passphrase = self.out.prompt_secret(f"Enter passphrase for {path}: ")
            self.out.add_secret(passphrase)
        raise DownloadError(f"Could not read private key '{path}'.")

    def _authenticate(self, t: Any) -> None:
        import paramiko

        user = self.creds.user or os.environ.get("USER") or os.environ.get("USERNAME") or ""
        if not user:
            import getpass

            user = getpass.getuser()
        errors: list[str] = []
        if self.creds.key:
            key = self._load_private_key()
            try:
                t.auth_publickey(user, key)
                return
            except paramiko.AuthenticationException as e:
                errors.append(f"key: {e}")
        if os.environ.get("SSH_AUTH_SOCK"):
            try:
                agent_keys = paramiko.Agent().get_keys()
            except paramiko.SSHException:
                agent_keys = ()
            for key in agent_keys:
                try:
                    t.auth_publickey(user, key)
                    return
                except paramiko.AuthenticationException:
                    continue
            if agent_keys:
                errors.append("agent: no accepted key")
        if self.creds.password is not None:
            password = self.creds.password
            try:
                t.auth_password(user, password)
                return
            except paramiko.BadAuthenticationType as e:
                errors.append(f"password: {e}")
            except paramiko.AuthenticationException as e:
                errors.append(f"password: {e}")
            try:

                def handler(_title: str, _instr: str, prompts: Any) -> list[str]:
                    return [password for _ in prompts]

                t.auth_interactive(user, handler)
                return
            except paramiko.AuthenticationException:
                pass
        if not errors:
            raise MissingArgumentError(
                "No SFTP credentials: give a password, a key (--key) or run an ssh-agent."
            )
        raise UploadError(
            f"Can't access remote '{self.url.display()}'. Failed to log in. "
            "Correct user, password or key?"
        )

    # -- helpers -----------------------------------------------------------
    def _path(self, rel: str) -> str:
        return self.url.sftp_path(rel)

    def _check_cancel(self) -> None:
        if self.cancel.is_set():
            raise TransferCancelled()

    def _callback(self, progress: ProgressFn | None) -> Callable[[int, int], None]:
        def cb(done: int, total: int) -> None:
            if self.cancel.is_set():
                raise TransferCancelled()
            if progress is not None:
                progress(done, total)

        return cb

    @staticmethod
    def _is_enoent(e: OSError) -> bool:
        return isinstance(e, FileNotFoundError) or e.errno == errno.ENOENT

    # -- operations --------------------------------------------------------
    def get(self, path: str) -> bytes:
        try:
            with self._sftp.open(self._path(path), "rb") as fh:
                data: bytes = fh.read()
                return data
        except OSError as e:
            if self._is_enoent(e):
                raise RemoteNotFound(path) from e
            raise DownloadError(f"Could not read '{path}': {e}") from e

    def get_file(self, path: str, local: Path, *, progress: ProgressFn | None = None) -> None:
        try:
            with open(local, "wb") as fh:
                self._sftp.getfo(self._path(path), fh, callback=self._callback(progress))
        except OSError as e:
            if self._is_enoent(e):
                raise RemoteNotFound(path) from e
            raise DownloadError(f"Could not download '{path}': {e}") from e

    def put(
        self, local: Path, remote: str, size: int, *, progress: ProgressFn | None = None
    ) -> None:
        self.mkdir_p(posixpath.dirname(remote))
        try:
            with open(local, "rb") as fh:
                self._sftp.putfo(
                    fh,
                    self._path(remote),
                    file_size=size,
                    callback=self._callback(progress),
                    confirm=False,
                )
        except OSError as e:
            raise UploadError(f"Could not upload '{remote}': {e}") from e

    def put_bytes(self, data: bytes, remote: str) -> None:
        import io

        self.mkdir_p(posixpath.dirname(remote))
        try:
            self._sftp.putfo(
                io.BytesIO(data), self._path(remote), file_size=len(data), confirm=False
            )
        except OSError as e:
            raise UploadError(f"Could not upload '{remote}': {e}") from e

    def delete(self, path: str) -> None:
        try:
            self._sftp.remove(self._path(path))
        except OSError as e:
            if self._is_enoent(e):
                return
            raise UploadError(f"Could not delete '{path}': {e}") from e

    def mkdir_p(self, directory: str) -> None:
        base = self.url.sftp_path("")
        base = "" if base == "." else base
        full = posixpath.normpath(posixpath.join(base, directory.strip("/")))
        if full in (".", "", "/"):
            return
        lead = "/" if full.startswith("/") else ""
        acc = ""
        for part in [p for p in full.split("/") if p]:
            acc = f"{acc}/{part}" if acc else lead + part
            with self.dircache.lock:
                if acc in self.dircache.known:
                    continue
                try:
                    st = self._sftp.stat(acc)
                    if not statmod.S_ISDIR(st.st_mode or 0):
                        raise UploadError(f"'{acc}' exists on the remote but is not a directory.")
                except OSError as e:
                    if not self._is_enoent(e):
                        raise UploadError(f"Could not stat '{acc}': {e}") from e
                    try:
                        self._sftp.mkdir(acc)
                    except OSError as e2:
                        try:
                            self._sftp.stat(acc)
                        except OSError:
                            raise UploadError(f"Could not create directory '{acc}': {e2}") from e2
                self.dircache.known.add(acc)

    def stat(self, path: str) -> Entry | None:
        try:
            st = self._sftp.stat(self._path(path))
        except OSError as e:
            if self._is_enoent(e):
                return None
            raise DownloadError(f"Could not stat '{path}': {e}") from e
        return Entry(
            name=posixpath.basename(path),
            is_dir=statmod.S_ISDIR(st.st_mode or 0),
            size=st.st_size,
            mtime=int(st.st_mtime) if st.st_mtime is not None else None,
        )

    def exists(self, path: str) -> bool:
        return self.stat(path) is not None

    def list_dir(self, path: str) -> list[Entry]:
        target = self._path(path.strip("/") + "/" if path.strip("/") else "")
        if target.endswith("/") and len(target) > 1:
            target = target.rstrip("/")
        try:
            attrs = self._sftp.listdir_attr(target)
        except OSError as e:
            if self._is_enoent(e):
                raise RemoteNotFound(path) from e
            raise DownloadError(f"Could not list '{path}': {e}") from e
        entries = []
        for a in attrs:
            if a.filename in (".", ".."):
                continue
            mode = a.st_mode or 0
            is_link = statmod.S_ISLNK(mode)
            is_dir = statmod.S_ISDIR(mode)
            if is_link:
                child = posixpath.join(target, a.filename) if target != "." else a.filename
                try:
                    is_dir = statmod.S_ISDIR(self._sftp.stat(child).st_mode or 0)
                except OSError:
                    is_dir = False
            entries.append(
                Entry(
                    name=a.filename,
                    is_dir=is_dir,
                    size=a.st_size,
                    mtime=int(a.st_mtime) if a.st_mtime is not None else None,
                    is_link=is_link,
                )
            )
        return entries
