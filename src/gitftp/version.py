"""Version information."""

from __future__ import annotations

__all__ = ["__version__", "runtime_info", "version_line"]

try:
    from gitftp._version import __version__
except ImportError:  # pragma: no cover - only in an unbuilt checkout
    __version__ = "0.0.0+unknown"


def version_line() -> str:
    """The line printed by ``git-ftp --version``, in upstream's format."""
    return f"git-ftp version {__version__}"


def runtime_info() -> list[str]:
    """Which transports and libraries this installation has."""
    lines: list[str] = []
    try:
        import pycurl

        info = pycurl.version_info()
        protocols = " ".join(p for p in info[8] if p in ("ftp", "ftps"))
        lines.append(f"libcurl {info[1]} ({info[5] or 'no TLS'}), protocols: {protocols}")
    except ImportError:
        lines.append("libcurl: pycurl not available (ftp, ftps and ftpes disabled)")
    try:
        import paramiko

        lines.append(f"paramiko {paramiko.__version__} (sftp)")
    except ImportError:
        lines.append("paramiko: not available (sftp disabled)")
    return lines
