"""Remote URL parsing and rendering.

Fixes over upstream: ``user:pass@host`` userinfo is credentials (upstream took
``user`` for the host), ``host:2121/path`` without a scheme is accepted as
ftp (the built-in help promised it), and ``--remote-root`` replaces the path.
Credentials never appear in any rendered URL except :meth:`RemoteURL.display`,
which masks the password.
"""

from __future__ import annotations

import enum
import re
from dataclasses import dataclass
from urllib.parse import quote, unquote

from gitftp.errors import MissingArgumentError, UnknownProtocolError


class Scheme(str, enum.Enum):
    FTP = "ftp"
    FTPS = "ftps"  # implicit TLS
    FTPES = "ftpes"  # explicit TLS (AUTH TLS)
    SFTP = "sftp"

    @property
    def secure(self) -> bool:
        return self in (Scheme.FTPS, Scheme.FTPES)

    @property
    def curl_scheme(self) -> str:
        """libcurl has no ``ftpes``; explicit TLS is ``ftp://`` plus CURLOPT_USE_SSL."""
        return "ftp" if self is Scheme.FTPES else self.value


DEFAULT_SCHEME = Scheme.FTP
_SCHEME_RE = re.compile(r"^([A-Za-z][A-Za-z0-9+.-]*)://(.*)$", re.DOTALL)
_PORT_HOST_RE = re.compile(r"^[^/:]+:\d+$")


@dataclass
class RemoteURL:
    scheme: Scheme
    host: str  # hostname, with ``:port`` when given
    path: str = ""  # "" or "dir/sub/" (no leading slash, exactly one trailing slash)
    absolute: bool = False  # the raw path began with a second '/' (``host//var/www``)
    user: str | None = None
    password: str | None = None

    # -- normalisation -----------------------------------------------------
    def set_path(self, raw: str) -> None:
        raw = raw.replace("\\", "/")
        self.absolute = raw.startswith("/")
        stripped = raw.strip("/")
        self.path = f"{stripped}/" if stripped else ""

    def child(self, rel_dir: str) -> RemoteURL:
        """The URL of a subdirectory (used for submodules)."""
        rel = rel_dir.strip("/")
        return RemoteURL(
            scheme=self.scheme,
            host=self.host,
            path=f"{self.path}{rel}/" if rel else self.path,
            absolute=self.absolute,
            user=self.user,
            password=self.password,
        )

    @property
    def hostname(self) -> str:
        host, _ = _split_host_port(self.host)
        return host

    @property
    def port(self) -> int | None:
        _, port = _split_host_port(self.host)
        return port

    # -- rendering ---------------------------------------------------------
    def display(self) -> str:
        """For messages and hooks: ``ftp://user:***@host/path/``."""
        cred = f"{self.user}:***@" if self.user else ""
        lead = "/" if self.absolute else ""
        return f"{self.scheme.value}://{cred}{self.host}/{lead}{self.path}"

    def name(self) -> str:
        """``host/path/`` as used in "No changed files for ..." messages."""
        lead = "/" if self.absolute else ""
        return f"{self.host}/{lead}{self.path}"

    def curl_base(self) -> str:
        return f"{self.scheme.curl_scheme}://{self.host}"

    def _curl_path(self, rel: str) -> str:
        lead = "%2F" if self.absolute else ""
        return lead + escape_path(self.path + rel)

    def curl_file_url(self, rel: str) -> str:
        return f"{self.curl_base()}/{self._curl_path(rel)}"

    def curl_dir_url(self, rel_dir: str = "") -> str:
        rel = rel_dir.strip("/")
        if rel:
            rel += "/"
        return f"{self.curl_base()}/{self._curl_path(rel)}"

    def sftp_path(self, rel: str = "") -> str:
        """Path for the SFTP subsystem: absolute, ``~/``-relative or login-dir relative."""
        base = self.path
        if base.startswith("~/"):
            base = base[2:]
        lead = "/" if self.absolute else ""
        p = f"{lead}{base}{rel}"
        return p if p else "."


def _split_host_port(host: str) -> tuple[str, int | None]:
    if host.startswith("["):  # [v6]:port
        end = host.find("]")
        if end != -1:
            rest = host[end + 1 :]
            if rest.startswith(":") and rest[1:].isdigit():
                return host[1:end], int(rest[1:])
            return host[1:end], None
    if host.count(":") == 1:
        name, _, port = host.partition(":")
        if port.isdigit():
            return name, int(port)
    return host, None


_SAFE_PATH = frozenset(
    b"ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-._~!$&'()*+,;=:@/"
)


def escape_path(path: str) -> str:
    """Percent-encode a remote path for a URL; ``/`` is kept.

    Encodes everything libcurl would otherwise misread: control bytes, space,
    non-ASCII, and ``" # % < > ? [ ] ^ ` { | } \\``.
    """
    raw = path.encode("utf-8", "surrogateescape")
    out = []
    for b in raw:
        if b in _SAFE_PATH:
            out.append(chr(b))
        else:
            out.append(f"%{b:02X}")
    return "".join(out)


def escape_userinfo(s: str) -> str:
    return quote(s, safe="")


def unescape(s: str) -> str:
    return unquote(s, errors="surrogateescape")


def parse(raw: str) -> RemoteURL:
    """Parse ``[scheme://][user[:password]@]host[:port][/path]``."""
    raw = raw.strip()
    if not raw:
        raise MissingArgumentError("Remote host not set.")

    m = _SCHEME_RE.match(raw)
    if m:
        scheme_name, rest = m.group(1).lower(), m.group(2)
        try:
            scheme = Scheme(scheme_name)
        except ValueError:
            raise UnknownProtocolError(f"Protocol unknown '{scheme_name}://'.") from None
    else:
        rest = raw
        head = rest.split("/", 1)[0]
        # "ftp:host" (one slash missing) or "foo:bar" is not a host:port form.
        if (
            ":" in head
            and "@" not in head
            and not _PORT_HOST_RE.match(head)
            and re.match(r"^[A-Za-z][A-Za-z0-9+.-]*:", head)
            and not head.split(":", 1)[1].isdigit()
        ):
            name = head.split(":", 1)[0]
            raise UnknownProtocolError(f"Protocol unknown '{name}:'.")
        scheme = DEFAULT_SCHEME

    # userinfo: split at the LAST '@' of the authority part (passwords may contain '@').
    authority, sep, path = rest.partition("/")
    user: str | None = None
    password: str | None = None
    if "@" in authority:
        userinfo, _, hostport = authority.rpartition("@")
        authority = hostport
        u, has_pw, p = userinfo.partition(":")
        user = unescape(u)
        password = unescape(p) if has_pw else None
    if not authority:
        raise MissingArgumentError("Remote host not set.")

    url = RemoteURL(scheme=scheme, host=authority, user=user, password=password)
    url.set_path(path if sep else "")
    return url
