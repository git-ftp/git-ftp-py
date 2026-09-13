"""Parallel transfer engine.

A pool of worker threads, each with its own connection. Uploads and downloads
are fail-fast (the first failure cancels the rest); deletes collect their
failures, which upstream treats as warnings.
"""

from __future__ import annotations

import contextlib
import os
import threading
from collections.abc import Callable, Sequence
from concurrent.futures import FIRST_COMPLETED, Future, ThreadPoolExecutor, wait
from dataclasses import dataclass
from pathlib import Path
from typing import Generic, TypeVar

from gitftp.output import Output
from gitftp.transport.base import Connector, TransferCancelled, Transport

T = TypeVar("T")
R = TypeVar("R")


@dataclass(frozen=True)
class UploadTask:
    local: Path
    remote: str
    size: int
    label: str


@dataclass(frozen=True)
class DeleteTask:
    remote: str
    label: str


@dataclass(frozen=True)
class DownloadTask:
    remote: str
    local: Path
    size: int | None
    mtime: int | None
    label: str


class TransferError(Exception):
    def __init__(self, label: str, cause: BaseException) -> None:
        super().__init__(f"{label}: {cause}")
        self.label = label
        self.cause = cause


class _Skipped:
    def __repr__(self) -> str:
        return "<skipped>"


SKIPPED = _Skipped()


class _Result(Generic[R]):
    __slots__ = ("value",)

    def __init__(self, value: R | TransferError | _Skipped) -> None:
        self.value = value


class TransferPool:
    def __init__(
        self,
        connect: Connector,
        jobs: int,
        out: Output,
        *,
        primary: Transport | None = None,
    ) -> None:
        self.connect = connect
        self.jobs = max(1, jobs)
        self.out = out
        self.primary = primary
        self._cancel = threading.Event()
        self._local = threading.local()
        self._opened: list[Transport] = []
        self._opened_lock = threading.Lock()
        self._own_primary = False

    # -- lifecycle ---------------------------------------------------------
    def __enter__(self) -> TransferPool:
        if self.primary is not None:
            self.primary.cancel = self._cancel
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    def close(self) -> None:
        if self.primary is not None and not self._own_primary:
            # The session keeps using this connection after the pool; a cancelled
            # pool must not poison it.
            self.primary.cancel = threading.Event()
        with self._opened_lock:
            opened, self._opened = self._opened, []
        for t in opened:
            with contextlib.suppress(Exception):
                t.close()
        if self._own_primary and self.primary is not None:
            with contextlib.suppress(Exception):
                self.primary.close()
            self.primary = None
            self._own_primary = False

    def cancel(self) -> None:
        self._cancel.set()

    @property
    def cancelled(self) -> bool:
        return self._cancel.is_set()

    def _primary(self) -> Transport:
        if self.primary is None:
            self.primary = self.connect()
            self.primary.cancel = self._cancel
            self._own_primary = True
        return self.primary

    def _worker_transport(self) -> Transport:
        t: Transport | None = getattr(self._local, "transport", None)
        if t is not None:
            return t
        failure: BaseException | None = getattr(self._local, "failure", None)
        if failure is not None:
            raise failure
        try:
            t = self.connect()
        except BaseException as e:
            self._local.failure = e
            raise
        t.cancel = self._cancel
        with self._opened_lock:
            self._opened.append(t)
        self._local.transport = t
        return t

    # -- the primitive -----------------------------------------------------
    def map(
        self,
        fn: Callable[[Transport, T], R],
        items: Sequence[T],
        *,
        fail_fast: bool = True,
        label: Callable[[T], str] = str,
        on_done: Callable[[str], None] | None = None,
    ) -> list[R | TransferError | _Skipped]:
        if not items:
            return []
        if self.jobs == 1 or len(items) == 1:
            return self._map_serial(fn, items, fail_fast=fail_fast, label=label, on_done=on_done)
        return self._map_parallel(fn, items, fail_fast=fail_fast, label=label, on_done=on_done)

    def _map_serial(
        self,
        fn: Callable[[Transport, T], R],
        items: Sequence[T],
        *,
        fail_fast: bool,
        label: Callable[[T], str],
        on_done: Callable[[str], None] | None = None,
    ) -> list[R | TransferError | _Skipped]:
        results: list[R | TransferError | _Skipped] = []
        t = self._primary()
        for item in items:
            if self._cancel.is_set():
                results.append(SKIPPED)
                continue
            try:
                results.append(fn(t, item))
            except TransferCancelled:
                results.append(SKIPPED)
            except Exception as e:
                err = TransferError(label(item), e)
                if fail_fast:
                    raise err from e
                results.append(err)
            else:
                if on_done is not None:
                    on_done(label(item))
        return results

    def _run_one(self, fn: Callable[[Transport, T], R], item: T) -> R | _Skipped:
        if self._cancel.is_set():
            return SKIPPED
        t = self._worker_transport()
        try:
            return fn(t, item)
        except TransferCancelled:
            return SKIPPED
        except Exception:
            if self._cancel.is_set():
                return SKIPPED
            raise

    def _map_parallel(
        self,
        fn: Callable[[Transport, T], R],
        items: Sequence[T],
        *,
        fail_fast: bool,
        label: Callable[[T], str],
        on_done: Callable[[str], None] | None = None,
    ) -> list[R | TransferError | _Skipped]:
        workers = min(self.jobs, len(items))
        executor = ThreadPoolExecutor(max_workers=workers, thread_name_prefix="git-ftp")
        futures: list[Future[R | _Skipped]] = []
        first_error: TransferError | None = None
        results: dict[Future[R | _Skipped], R | TransferError | _Skipped] = {}
        try:
            for item in items:
                futures.append(executor.submit(self._run_one, fn, item))
            pending = set(futures)
            while pending:
                done, pending = wait(pending, timeout=0.5, return_when=FIRST_COMPLETED)
                for fut in done:
                    idx = futures.index(fut)
                    try:
                        result = fut.result()
                    except Exception as e:
                        err = TransferError(label(items[idx]), e)
                        results[fut] = err
                        if fail_fast and first_error is None:
                            first_error = err
                            self._cancel.set()
                    else:
                        results[fut] = result
                        if on_done is not None and not isinstance(result, _Skipped):
                            on_done(label(items[idx]))
        except BaseException:
            self._cancel.set()
            executor.shutdown(wait=False, cancel_futures=True)
            raise
        executor.shutdown(wait=True)
        if first_error is not None:
            raise first_error
        return [results[f] for f in futures]

    # -- typed helpers -----------------------------------------------------
    def upload(
        self, tasks: Sequence[UploadTask], *, on_done: Callable[[str], None] | None = None
    ) -> None:
        def do(t: Transport, task: UploadTask) -> None:
            t.put(task.local, task.remote, task.size)
            self.out.debug(f"Uploaded '{task.label}'.")

        self.map(do, tasks, fail_fast=True, label=lambda task: task.label, on_done=on_done)

    def delete(
        self, tasks: Sequence[DeleteTask], *, on_done: Callable[[str], None] | None = None
    ) -> list[TransferError]:
        def do(t: Transport, task: DeleteTask) -> None:
            t.delete(task.remote)
            self.out.debug(f"Deleted '{task.label}'.")

        results = self.map(
            do, tasks, fail_fast=False, label=lambda task: task.label, on_done=on_done
        )
        return [r for r in results if isinstance(r, TransferError)]

    def download(
        self, tasks: Sequence[DownloadTask], *, on_done: Callable[[str], None] | None = None
    ) -> None:
        def do(t: Transport, task: DownloadTask) -> None:
            part = task.local.with_name(f".{task.local.name}.git-ftp-part")
            task.local.parent.mkdir(parents=True, exist_ok=True)
            try:
                t.get_file(task.remote, part)
                if task.mtime is not None:
                    os.utime(part, (task.mtime, task.mtime))
                os.replace(part, task.local)
            except BaseException:
                with contextlib.suppress(OSError):
                    part.unlink()
                raise
            self.out.debug(f"Downloaded '{task.label}'.")

        self.map(do, tasks, fail_fast=True, label=lambda task: task.label, on_done=on_done)
