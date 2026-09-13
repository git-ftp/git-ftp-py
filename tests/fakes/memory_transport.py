"""A dict-backed Transport with injectable failures, for engine tests."""

from __future__ import annotations

import posixpath
import threading
import time
from pathlib import Path

from gitftp.errors import DownloadError, UploadError
from gitftp.transport.base import Entry, ProgressFn, RemoteNotFound, Transport


class MemoryStore:
    """Shared state for every MemoryTransport of one test."""

    def __init__(self) -> None:
        self.files: dict[str, bytes] = {}
        self.dirs: set[str] = set()
        self.lock = threading.Lock()
        self.ops: list[tuple[str, str]] = []
        self.fail_put: set[str] = set()
        self.fail_delete: set[str] = set()
        self.get_error: Exception | None = None
        self.connect_error: Exception | None = None
        self.opened = 0
        self.closed = 0
        self.put_delay = 0.0
        self.max_concurrent = 0
        self._active = 0

    def connect(self) -> Transport:
        if self.connect_error is not None:
            raise self.connect_error
        t = MemoryTransport(self)
        t.open()
        return t


class MemoryTransport(Transport):
    def __init__(self, store: MemoryStore) -> None:
        super().__init__()
        self.store = store

    def open(self) -> None:
        with self.store.lock:
            self.store.opened += 1

    def close(self) -> None:
        with self.store.lock:
            self.store.closed += 1

    def _record(self, op: str, path: str) -> None:
        with self.store.lock:
            self.store.ops.append((op, path))

    def get(self, path: str) -> bytes:
        self._record("get", path)
        if self.store.get_error is not None:
            raise self.store.get_error
        with self.store.lock:
            if path not in self.store.files:
                raise RemoteNotFound(path)
            return self.store.files[path]

    def get_file(self, path: str, local: Path, *, progress: ProgressFn | None = None) -> None:
        data = self.get(path)
        local.write_bytes(data)

    def _enter(self) -> None:
        with self.store.lock:
            self.store._active += 1
            self.store.max_concurrent = max(self.store.max_concurrent, self.store._active)

    def _leave(self) -> None:
        with self.store.lock:
            self.store._active -= 1

    def put(
        self, local: Path, remote: str, size: int, *, progress: ProgressFn | None = None
    ) -> None:
        self.put_bytes(local.read_bytes(), remote)

    def put_bytes(self, data: bytes, remote: str) -> None:
        self._enter()
        try:
            if self.store.put_delay:
                time.sleep(self.store.put_delay)
            if self.cancel.is_set():
                from gitftp.transport.base import TransferCancelled

                raise TransferCancelled()
            if remote in self.store.fail_put:
                raise UploadError(f"upload of {remote} refused")
            self.mkdir_p(posixpath.dirname(remote))
            with self.store.lock:
                self.store.files[remote] = data
            self._record("put", remote)
        finally:
            self._leave()

    def delete(self, path: str) -> None:
        if path in self.store.fail_delete:
            raise UploadError(f"delete of {path} refused")
        with self.store.lock:
            self.store.files.pop(path, None)
        self._record("delete", path)

    def mkdir_p(self, directory: str) -> None:
        directory = directory.strip("/")
        with self.store.lock:
            parts = [p for p in directory.split("/") if p]
            for i in range(len(parts)):
                self.store.dirs.add("/".join(parts[: i + 1]))
        self._record("mkdir", directory)

    def exists(self, path: str) -> bool:
        with self.store.lock:
            return path in self.store.files

    def stat(self, path: str) -> Entry | None:
        with self.store.lock:
            if path not in self.store.files:
                return None
            return Entry(
                name=posixpath.basename(path),
                is_dir=False,
                size=len(self.store.files[path]),
                mtime=None,
            )

    def list_dir(self, path: str) -> list[Entry]:
        prefix = path.strip("/")
        prefix = prefix + "/" if prefix else ""
        with self.store.lock:
            if (
                prefix
                and prefix.rstrip("/") not in self.store.dirs
                and not any(f.startswith(prefix) for f in self.store.files)
            ):
                raise RemoteNotFound(path)
            names: dict[str, Entry] = {}
            for f, data in self.store.files.items():
                if not f.startswith(prefix):
                    continue
                rest = f[len(prefix) :]
                head, sep, _ = rest.partition("/")
                if sep:
                    names.setdefault(head, Entry(name=head, is_dir=True))
                else:
                    names[head] = Entry(
                        name=head, is_dir=False, size=len(data), mtime=1_700_000_000
                    )
            for d in self.store.dirs:
                if d.startswith(prefix) and d != prefix.rstrip("/"):
                    head = d[len(prefix) :].split("/", 1)[0]
                    if head:
                        names.setdefault(head, Entry(name=head, is_dir=True))
            return sorted(names.values(), key=lambda e: e.name)


def raise_download_error(msg: str = "boom") -> DownloadError:
    return DownloadError(msg)
