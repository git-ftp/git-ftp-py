"""The transport interface every backend implements."""

from __future__ import annotations

import threading
from abc import ABC, abstractmethod
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path


class RemoteNotFound(Exception):
    """The remote file or directory does not exist (not an access or network error)."""


class TransferCancelled(Exception):
    """Raised inside a worker when the pool's cancel event was set mid-transfer."""


@dataclass(frozen=True)
class Entry:
    name: str
    is_dir: bool
    size: int | None = None
    mtime: int | None = None  # unix seconds, UTC
    mtime_exact: bool = True  # False for LIST-derived times (minute resolution)
    is_link: bool = False


ProgressFn = Callable[[int, int], None]


class Transport(ABC):
    """One open connection.

    Paths are relative to the URL's remote directory and never start with '/'.
    Instances are not thread-safe; the transfer pool gives each worker its own.
    """

    def __init__(self) -> None:
        self.cancel = threading.Event()

    @abstractmethod
    def open(self) -> None: ...

    @abstractmethod
    def close(self) -> None: ...

    @abstractmethod
    def get(self, path: str) -> bytes:
        """Read a small file. Raises RemoteNotFound, else DownloadError."""

    @abstractmethod
    def get_file(self, path: str, local: Path, *, progress: ProgressFn | None = None) -> None:
        """Stream a remote file into ``local``."""

    @abstractmethod
    def put(
        self, local: Path, remote: str, size: int, *, progress: ProgressFn | None = None
    ) -> None:
        """Upload a file, creating missing parent directories. Raises UploadError."""

    @abstractmethod
    def put_bytes(self, data: bytes, remote: str) -> None: ...

    @abstractmethod
    def delete(self, path: str) -> None:
        """Remove a file; an already absent file is success. Raises UploadError."""

    @abstractmethod
    def mkdir_p(self, directory: str) -> None:
        """Create ``directory`` and parents; '' is the remote root itself."""

    @abstractmethod
    def exists(self, path: str) -> bool: ...

    @abstractmethod
    def stat(self, path: str) -> Entry | None: ...

    @abstractmethod
    def list_dir(self, path: str) -> list[Entry]:
        """Non-recursive listing without '.' and '..'. Raises RemoteNotFound."""

    def __enter__(self) -> Transport:
        self.open()
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()


Connector = Callable[[], Transport]
"""Returns a fresh, *opened* connection; the pool calls it once per worker."""
