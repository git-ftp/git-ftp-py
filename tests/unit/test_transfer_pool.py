from __future__ import annotations

import threading
from pathlib import Path

import pytest

from gitftp.errors import UploadError
from gitftp.output import Level, Output
from gitftp.transfer import DeleteTask, DownloadTask, TransferError, TransferPool, UploadTask
from gitftp.transport.base import Transport
from tests.fakes.memory_transport import MemoryStore


def make_tasks(tmp_path: Path, n: int) -> list[UploadTask]:
    tasks = []
    for i in range(n):
        p = tmp_path / f"f{i:03}.txt"
        p.write_text(f"{i}\n")
        tasks.append(
            UploadTask(local=p, remote=f"bulk/f{i:03}.txt", size=p.stat().st_size, label=p.name)
        )
    return tasks


def test_parallel_upload_uses_several_connections(tmp_path: Path) -> None:
    store = MemoryStore()
    store.put_delay = 0.01
    tasks = make_tasks(tmp_path, 40)
    with TransferPool(store.connect, 4, Output(Level.SILENT)) as pool:
        pool.upload(tasks)
    assert len(store.files) == 40
    assert store.opened == 4
    assert store.closed == 4
    assert store.max_concurrent > 1


def test_jobs_1_is_serial_on_primary(tmp_path: Path) -> None:
    store = MemoryStore()
    primary = store.connect()
    tasks = make_tasks(tmp_path, 5)
    with TransferPool(store.connect, 1, Output(Level.SILENT), primary=primary) as pool:
        pool.upload(tasks)
    assert store.opened == 1
    assert [p for op, p in store.ops if op == "put"] == [t.remote for t in tasks]


def test_fail_fast_cancels_rest(tmp_path: Path) -> None:
    store = MemoryStore()
    store.put_delay = 0.01
    store.fail_put.add("bulk/f005.txt")
    tasks = make_tasks(tmp_path, 40)
    with (
        TransferPool(store.connect, 4, Output(Level.SILENT)) as pool,
        pytest.raises(TransferError) as ei,
    ):
        pool.upload(tasks)
    assert ei.value.label == "f005.txt"
    assert isinstance(ei.value.cause, UploadError)
    assert pool.cancelled
    assert len(store.files) < 40


def test_delete_collects_errors(tmp_path: Path) -> None:
    store = MemoryStore()
    store.files.update({"a": b"", "b": b"", "c": b""})
    store.fail_delete.add("b")
    with TransferPool(store.connect, 3, Output(Level.SILENT)) as pool:
        errors = pool.delete([DeleteTask(remote=p, label=p) for p in ("a", "b", "c")])
    assert [e.label for e in errors] == ["b"]
    assert set(store.files) == {"b"}


def test_connect_failure_is_reported_once(tmp_path: Path) -> None:
    store = MemoryStore()
    store.connect_error = UploadError("login failed")
    tasks = make_tasks(tmp_path, 8)
    with (
        TransferPool(store.connect, 4, Output(Level.SILENT)) as pool,
        pytest.raises(TransferError) as ei,
    ):
        pool.upload(tasks)
    assert "login failed" in str(ei.value)


def test_download_writes_via_part_file(tmp_path: Path) -> None:
    store = MemoryStore()
    store.files["r/a.txt"] = b"hello"
    dest = tmp_path / "out" / "a.txt"
    with TransferPool(store.connect, 2, Output(Level.SILENT)) as pool:
        pool.download(
            [DownloadTask(remote="r/a.txt", local=dest, size=5, mtime=1_600_000_000, label="a")]
        )
    assert dest.read_bytes() == b"hello"
    assert int(dest.stat().st_mtime) == 1_600_000_000
    assert not (tmp_path / "out" / ".a.txt.git-ftp-part").exists()


def test_download_failure_removes_part_file(tmp_path: Path) -> None:
    store = MemoryStore()
    dest = tmp_path / "a.txt"
    with TransferPool(store.connect, 1, Output(Level.SILENT)) as pool, pytest.raises(TransferError):
        pool.download(
            [DownloadTask(remote="missing", local=dest, size=None, mtime=None, label="a")]
        )
    assert not dest.exists()
    assert not (tmp_path / ".a.txt.git-ftp-part").exists()


def test_map_generic(tmp_path: Path) -> None:
    store = MemoryStore()
    store.files.update({"x/1": b"1", "y/2": b"22"})

    def size(t: Transport, path: str) -> int:
        return len(t.get(path))

    with TransferPool(store.connect, 2, Output(Level.SILENT)) as pool:
        assert pool.map(size, ["x/1", "y/2"]) == [1, 2]


def test_cancel_event_shared_with_workers(tmp_path: Path) -> None:
    store = MemoryStore()
    store.put_delay = 0.05
    tasks = make_tasks(tmp_path, 10)
    pool = TransferPool(store.connect, 3, Output(Level.SILENT))
    with pool:
        threading.Timer(0.02, pool.cancel).start()
        pool.upload(tasks)  # no error: cancelled tasks are skipped, not failed
    assert len(store.files) < 10
