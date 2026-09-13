"""An interactive transfer spinner (yaspin), rendered on stderr.

The spinner shows a running ``<verb> <done>/<total> <current file>`` count while
files transfer. It is active only on an interactive terminal at normal
verbosity, so it never touches the stdout that scripts and the test suite parse,
and it stays silent when output is piped, under ``-n``, or under ``-v``/``-vv``
(which print their own per-file lines).
"""

from __future__ import annotations

from types import TracebackType
from typing import Any

from gitftp.output import Level, Output


class Progress:
    """Context manager wrapping a yaspin spinner; a no-op when not on a TTY."""

    def __init__(self, out: Output, verb: str, total: int) -> None:
        self.out = out
        self.verb = verb
        self.total = total
        self.done = 0
        self._spinner: Any = None
        self.enabled = out.level == Level.NORMAL and out.stderr.isatty()

    def _text(self, label: str = "") -> str:
        base = f"{self.verb} {self.done}/{self.total}"
        return f"{base}  {label}" if label else base

    def __enter__(self) -> Progress:
        if self.enabled:
            from yaspin import yaspin

            self._spinner = yaspin(text=self._text(), stream=self.out.stderr)
            self._spinner.start()
        return self

    def advance(self, label: str = "") -> None:
        """Count one finished transfer and refresh the spinner text."""
        self.done += 1
        if self._spinner is not None:
            self._spinner.text = self._text(label)

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        if self._spinner is not None:
            self._spinner.stop()  # clears its line and restores the cursor
            self._spinner = None
