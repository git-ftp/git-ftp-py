"""An interactive transfer progress bar (tqdm), rendered on stderr.

When the byte size of a batch is known (uploads, and downloads whose listing
reported every size) the bar tracks bytes with rate and ETA, followed by a
``<done>/<total> <current file>`` count; otherwise (deletes) it counts files.
It is active only on an interactive terminal at normal verbosity, so it never
touches the stdout that scripts and the test suite parse, and it stays silent
when output is piped, under ``-n``, or under ``-v``/``-vv`` (which print their
own per-file lines).
"""

from __future__ import annotations

import os
import threading
from types import TracebackType
from typing import Any, TextIO

from gitftp.output import Level, Output


def _screen_size(stream: TextIO) -> tuple[int, int]:
    """Columns and rows of the terminal, 80x24 when it reports none.

    tqdm hides its bar entirely on a terminal that reports 0 rows (bare ptys,
    serial consoles), so the size is always passed explicitly.
    """
    try:
        cols, rows = os.get_terminal_size(stream.fileno())
    except (AttributeError, OSError, ValueError):
        cols = rows = 0
    return cols or 80, rows or 24


class Progress:
    """Context manager wrapping a tqdm bar; a no-op when not on a TTY."""

    def __init__(self, out: Output, verb: str, total: int, *, size: int | None = None) -> None:
        self.out = out
        self.verb = verb
        self.total = total
        self.size = size or None  # total bytes; None (or 0) counts files instead
        self.done = 0
        self._bar: Any = None
        self._seen: dict[str, int] = {}  # bytes reported so far per in-flight file
        self._lock = threading.Lock()  # transfer threads report bytes concurrently
        self.enabled = out.level == Level.NORMAL and out.stderr.isatty()

    def _postfix(self, label: str = "") -> str:
        if self.size is None:
            return label  # the bar itself shows the file count
        base = f"{self.done}/{self.total}"
        return f"{base}  {label}" if label else base

    def __enter__(self) -> Progress:
        if self.enabled:
            from tqdm import tqdm

            if self.size is None:
                kw: dict[str, Any] = {"total": self.total, "unit": "file"}
            else:
                kw = {"total": self.size, "unit": "B", "unit_scale": True, "unit_divisor": 1024}
            ncols, nrows = _screen_size(self.out.stderr)
            self._bar = tqdm(
                desc=self.verb,
                file=self.out.stderr,
                leave=False,
                ncols=ncols,
                nrows=nrows,
                postfix=self._postfix() or None,
                **kw,
            )
        return self

    def transferred(self, label: str, nbytes: int) -> None:
        """Record ``nbytes`` done so far of one file; safe to call from transfer threads."""
        if self._bar is None or self.size is None:
            return
        with self._lock:
            delta = nbytes - self._seen.get(label, 0)  # negative when a transfer restarts
            self._seen[label] = nbytes
            if delta:
                self._bar.update(delta)

    def advance(self, label: str = "") -> None:
        """Count one finished transfer and refresh the bar."""
        with self._lock:
            self.done += 1
            self._seen.pop(label, None)
            if self._bar is not None:
                if self.size is None:
                    self._bar.set_postfix_str(self._postfix(label), refresh=False)
                    self._bar.update(1)
                else:
                    self._bar.set_postfix_str(self._postfix(label))

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        if self._bar is not None:
            self._bar.close()  # leave=False clears its line
            self._bar = None
