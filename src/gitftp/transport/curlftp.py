"""FTP, FTPS (implicit TLS) and FTPES (explicit TLS) through libcurl (pycurl).

One easy handle per instance is reused for every operation; libcurl keeps the
control connection in its cache, so each worker logs in once. Credentials are
passed through CURLOPT_USERNAME/PASSWORD, never inside the URL.
"""

from __future__ import annotations

import io
import posixpath
from collections.abc import Callable
from pathlib import Path
from typing import Any

from gitftp.auth import Credentials
from gitftp.errors import DownloadError, UploadError
from gitftp.output import Output
from gitftp.transport import listing
from gitftp.transport.base import Entry, ProgressFn, RemoteNotFound, Transport
from gitftp.url import RemoteURL, Scheme

# libcurl error codes we interpret
E_UNSUPPORTED_PROTOCOL = 1
E_COULDNT_RESOLVE_PROXY = 5
E_COULDNT_RESOLVE_HOST = 6
E_COULDNT_CONNECT = 7
E_REMOTE_ACCESS_DENIED = 9
E_FTP_COULDNT_RETR_FILE = 19
E_QUOTE_ERROR = 21
E_UPLOAD_FAILED = 25
E_OPERATION_TIMEDOUT = 28
E_SSL_CONNECT_ERROR = 35
E_ABORTED_BY_CALLBACK = 42
E_PEER_FAILED_VERIFICATION = 60
E_USE_SSL_FAILED = 64
E_LOGIN_DENIED = 67
E_REMOTE_FILE_NOT_FOUND = 78
E_SSL_CACERT_BADFILE = 77
E_SSL_PEER_CERTIFICATE = 51

NOT_FOUND_CODES = frozenset(
    {E_REMOTE_ACCESS_DENIED, E_FTP_COULDNT_RETR_FILE, E_REMOTE_FILE_NOT_FOUND}
)
TLS_CODES = frozenset(
    {E_SSL_CONNECT_ERROR, E_PEER_FAILED_VERIFICATION, E_SSL_CACERT_BADFILE, E_SSL_PEER_CERTIFICATE}
)


class CurlOptions:
    """Transport settings coming from the command line and config."""

    def __init__(
        self,
        *,
        insecure: bool = False,
        cacert: str | None = None,
        active: bool = False,
        disable_epsv: bool = False,
        proxy: str | None = None,
        trace: Callable[[str], None] | None = None,
    ) -> None:
        self.insecure = insecure
        self.cacert = cacert
        self.active = active
        self.disable_epsv = disable_epsv
        self.proxy = proxy
        self.trace = trace


def check_available(scheme: Scheme) -> None:
    try:
        import pycurl
    except ImportError as e:
        raise DownloadError(
            "pycurl is not available; install git-ftp with its wheels or the libcurl "
            "development headers."
        ) from e
    info = pycurl.version_info()
    protocols = set(info[8])
    if "ftp" not in protocols:
        raise DownloadError("Protocol 'ftp' is not supported by the installed libcurl.")
    if scheme.secure and ("ftps" not in protocols or not info[5]):
        raise DownloadError(
            f"Protocol '{scheme.value}' is not supported by the installed libcurl (no TLS)."
        )


def describe_error(code: int, message: str, url: RemoteURL) -> str:
    """Upstream's ``check_curl_exit_status`` texts, with a few TLS hints added."""
    display = url.display()
    if code == E_REMOTE_ACCESS_DENIED:
        return (
            "Access to resource denied. This usually means that the file or directory "
            "does not exist. Wrong path?"
        )
    if code == E_LOGIN_DENIED:
        return f"Can't access remote '{display}'. Failed to log in. Correct user and password?"
    if code == E_REMOTE_FILE_NOT_FOUND:
        return "The resource does not exist."
    if code in TLS_CODES:
        return (
            f"Can't access remote '{display}'. TLS verification failed ({message}). "
            "Use --cacert to trust the server certificate or --insecure to skip verification."
        )
    if code == E_USE_SSL_FAILED:
        return f"Can't access remote '{display}'. The server refused TLS ({message})."
    return f"Can't access remote '{display}'. Network down? Wrong URL? ({message})"


def _discard(_data: bytes) -> None:
    """Header sink: without it libcurl prints FTP pseudo-headers to stdout."""


def _discard_body(data: bytes) -> int:
    """Body sink for NOBODY requests (SIZE/MDTM replies are delivered as body too)."""
    return len(data)


class CurlFtpTransport(Transport):
    def __init__(
        self, url: RemoteURL, creds: Credentials, options: CurlOptions, out: Output
    ) -> None:
        super().__init__()
        self.url = url
        self.creds = creds
        self.options = options
        self.out = out
        self._curl: Any = None
        self._mlsd_supported = True
        self._progress: ProgressFn | None = None

    # -- lifecycle ---------------------------------------------------------
    def open(self) -> None:
        import pycurl

        self._pycurl = pycurl
        self._curl = pycurl.Curl()

    def close(self) -> None:
        if self._curl is not None:
            self._curl.close()
            self._curl = None

    # -- callbacks ---------------------------------------------------------
    def _xferinfo(self, dl_total: int, dl_now: int, ul_total: int, ul_now: int) -> int:
        if self.cancel.is_set():
            return 1
        if self._progress is not None:
            if ul_total or ul_now:
                self._progress(ul_now, ul_total)
            else:
                self._progress(dl_now, dl_total)
        return 0

    def _debug(self, kind: int, data: bytes) -> None:
        if self.options.trace is None or kind > 2:
            return
        prefix = {0: "* ", 1: "< ", 2: "> "}[kind]
        text = data.decode("utf-8", "replace").rstrip("\r\n")
        for line in text.split("\n"):
            self.options.trace(prefix + line.rstrip("\r"))

    # -- request setup -----------------------------------------------------
    def _prepare(self, target: str) -> Any:
        pc = self._pycurl
        c = self._curl
        c.reset()
        c.setopt(pc.URL, target)
        if hasattr(pc, "PROTOCOLS_STR"):
            c.setopt(pc.PROTOCOLS_STR, "ftp,ftps")
        else:  # pragma: no cover - older libcurl
            c.setopt(pc.PROTOCOLS, pc.PROTO_FTP | pc.PROTO_FTPS)
        if self.creds.user:
            c.setopt(pc.USERNAME, self.creds.user.encode("utf-8", "surrogateescape"))
            if self.creds.password is not None:
                c.setopt(pc.PASSWORD, self.creds.password.encode("utf-8", "surrogateescape"))
            c.setopt(pc.NETRC, pc.NETRC_IGNORED)
        else:
            c.setopt(pc.NETRC, pc.NETRC_OPTIONAL)
        c.setopt(pc.NOSIGNAL, 1)
        c.setopt(pc.TCP_KEEPALIVE, 1)
        c.setopt(pc.CONNECTTIMEOUT_MS, 30000)
        c.setopt(pc.LOW_SPEED_LIMIT, 1)
        c.setopt(pc.LOW_SPEED_TIME, 60)
        c.setopt(pc.FTP_RESPONSE_TIMEOUT, 60)
        c.setopt(pc.FTP_SKIP_PASV_IP, 1)
        if self.options.active:
            c.setopt(pc.FTPPORT, "-")
        elif self.options.disable_epsv:
            c.setopt(pc.FTP_USE_EPSV, 0)
        if self.options.proxy:
            c.setopt(pc.PROXY, self.options.proxy)
        if self.url.scheme.secure:
            c.setopt(pc.USE_SSL, pc.USESSL_ALL)
            c.setopt(pc.SSLVERSION, pc.SSLVERSION_TLSv1_2)
            if self.options.insecure:
                c.setopt(pc.SSL_VERIFYPEER, 0)
                c.setopt(pc.SSL_VERIFYHOST, 0)
            if self.options.cacert:
                c.setopt(pc.CAINFO, self.options.cacert)
        c.setopt(pc.HEADERFUNCTION, _discard)
        c.setopt(pc.WRITEFUNCTION, _discard_body)
        c.setopt(pc.NOPROGRESS, 0)
        c.setopt(pc.XFERINFOFUNCTION, self._xferinfo)
        if self.options.trace is not None:
            c.setopt(pc.VERBOSE, 1)
            c.setopt(pc.DEBUGFUNCTION, self._debug)
        return c

    def _perform(self, c: Any) -> None:
        """Perform, re-raising libcurl errors as :class:`CurlError`."""
        try:
            c.perform()
        except self._pycurl.error as e:
            args: tuple[Any, ...] = tuple(e.args)
            code = int(args[0]) if args else 0
            message = str(args[1]) if len(args) > 1 else ""
            raise CurlError(code, message) from None

    def _file_url(self, path: str) -> str:
        return self.url.curl_file_url(path)

    # -- operations --------------------------------------------------------
    def get(self, path: str) -> bytes:
        buf = io.BytesIO()
        c = self._prepare(self._file_url(path))
        c.setopt(self._pycurl.WRITEDATA, buf)
        try:
            self._perform(c)
        except CurlError as e:
            if e.code in NOT_FOUND_CODES:
                raise RemoteNotFound(path) from e
            raise DownloadError(describe_error(e.code, e.message, self.url)) from e
        return buf.getvalue()

    def get_file(self, path: str, local: Path, *, progress: ProgressFn | None = None) -> None:
        self._progress = progress
        try:
            with open(local, "wb") as fh:
                c = self._prepare(self._file_url(path))
                c.setopt(self._pycurl.WRITEDATA, fh)
                try:
                    self._perform(c)
                except CurlError as e:
                    if e.code in NOT_FOUND_CODES:
                        raise RemoteNotFound(path) from e
                    raise DownloadError(describe_error(e.code, e.message, self.url)) from e
        finally:
            self._progress = None

    def _upload(self, reader: Any, size: int, remote: str) -> None:
        pc = self._pycurl
        c = self._prepare(self._file_url(remote))
        c.setopt(pc.UPLOAD, 1)
        c.setopt(pc.READDATA, reader)
        c.setopt(pc.INFILESIZE_LARGE, size)
        c.setopt(pc.FTP_CREATE_MISSING_DIRS, 2)
        try:
            self._perform(c)
        except CurlError as e:
            raise UploadError(describe_error(e.code, e.message, self.url)) from e

    def put(
        self, local: Path, remote: str, size: int, *, progress: ProgressFn | None = None
    ) -> None:
        self._progress = progress
        try:
            with open(local, "rb") as fh:
                self._upload(fh, size, remote)
        finally:
            self._progress = None

    def put_bytes(self, data: bytes, remote: str) -> None:
        self._upload(io.BytesIO(data), len(data), remote)

    def delete(self, path: str) -> None:
        pc = self._pycurl
        directory, name = posixpath.split(path)
        c = self._prepare(self.url.curl_dir_url(directory))
        c.setopt(pc.NOBODY, 1)
        c.setopt(pc.POSTQUOTE, [b"DELE " + name.encode("utf-8", "surrogateescape")])
        try:
            self._perform(c)
        except CurlError as e:
            if e.code == E_REMOTE_ACCESS_DENIED:
                return  # the directory is gone, so is the file
            if e.code == E_QUOTE_ERROR and not self.exists(path):
                return
            raise UploadError(f"Could not delete '{path}': {e.message}") from e

    def mkdir_p(self, directory: str) -> None:
        pc = self._pycurl
        c = self._prepare(self.url.curl_dir_url(directory))
        c.setopt(pc.NOBODY, 1)
        c.setopt(pc.FTP_CREATE_MISSING_DIRS, 2)
        try:
            self._perform(c)
        except CurlError as e:
            raise UploadError(describe_error(e.code, e.message, self.url)) from e

    def stat(self, path: str) -> Entry | None:
        pc = self._pycurl
        c = self._prepare(self._file_url(path))
        c.setopt(pc.NOBODY, 1)
        c.setopt(pc.OPT_FILETIME, 1)
        try:
            self._perform(c)
        except CurlError as e:
            if e.code in NOT_FOUND_CODES or e.code == E_QUOTE_ERROR:
                return None
            raise DownloadError(describe_error(e.code, e.message, self.url)) from e
        mtime = c.getinfo(pc.INFO_FILETIME)
        size_attr = getattr(pc, "CONTENT_LENGTH_DOWNLOAD_T", pc.CONTENT_LENGTH_DOWNLOAD)
        size = c.getinfo(size_attr)
        return Entry(
            name=posixpath.basename(path),
            is_dir=False,
            size=int(size) if size is not None and size >= 0 else None,
            mtime=int(mtime) if mtime is not None and mtime >= 0 else None,
        )

    def exists(self, path: str) -> bool:
        return self.stat(path) is not None

    def _list_raw(self, directory: str, custom: str | None, names_only: bool = False) -> bytes:
        pc = self._pycurl
        buf = io.BytesIO()
        c = self._prepare(self.url.curl_dir_url(directory))
        c.setopt(pc.WRITEDATA, buf)
        if custom:
            c.setopt(pc.CUSTOMREQUEST, custom)
        if names_only:
            c.setopt(pc.DIRLISTONLY, 1)
        self._perform(c)
        return buf.getvalue()

    def list_dir(self, path: str) -> list[Entry]:
        directory = path.strip("/")
        if self._mlsd_supported:
            try:
                data = self._list_raw(directory, "MLSD")
            except CurlError as e:
                if e.code == E_REMOTE_ACCESS_DENIED:
                    raise RemoteNotFound(path) from e
                if e.code in (E_FTP_COULDNT_RETR_FILE, E_QUOTE_ERROR, E_REMOTE_FILE_NOT_FOUND):
                    self._mlsd_supported = False
                else:
                    raise DownloadError(describe_error(e.code, e.message, self.url)) from e
            else:
                entries = listing.parse_mlsd(data)
                if entries or not data.strip():
                    return entries
                self._mlsd_supported = False
        try:
            data = self._list_raw(directory, None)
        except CurlError as e:
            if e.code in (E_REMOTE_ACCESS_DENIED, E_REMOTE_FILE_NOT_FOUND):
                raise RemoteNotFound(path) from e
            raise DownloadError(describe_error(e.code, e.message, self.url)) from e
        entries = listing.parse_list(data)
        if entries or not data.strip():
            return entries
        # Unparsable LIST format: fall back to names and probe each one.
        names = listing.parse_nlst(self._list_raw(directory, None, names_only=True))
        result = []
        for name in names:
            child = f"{directory}/{name}" if directory else name
            try:
                self._list_raw(child, None, names_only=True)
                result.append(Entry(name=name, is_dir=True))
            except CurlError:
                st = self.stat(child)
                result.append(
                    Entry(
                        name=name,
                        is_dir=False,
                        size=st.size if st else None,
                        mtime=st.mtime if st else None,
                    )
                )
        return result


class CurlError(Exception):
    def __init__(self, code: int, message: str) -> None:
        super().__init__(code, message)
        self.code = code
        self.message = message
