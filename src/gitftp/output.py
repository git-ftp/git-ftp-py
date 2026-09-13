"""All user-facing output.

Upstream semantics are kept: progress lines go to stdout at normal verbosity,
diagnostics (``write_log``) are shown only with ``-v``, and ``-n`` silences
progress. Fixed: fatal errors always go to stderr, at every verbosity.
"""

from __future__ import annotations

import enum
import getpass
import sys
import threading
import time
from typing import TextIO


class Level(enum.IntEnum):
    SILENT = -1
    NORMAL = 0
    VERBOSE = 1
    TRACE = 2


class Output:
    """Thread-safe printer with secret redaction."""

    def __init__(
        self,
        level: Level = Level.NORMAL,
        stdout: TextIO | None = None,
        stderr: TextIO | None = None,
        stdin: TextIO | None = None,
    ) -> None:
        self.level = level
        self._stdout = stdout
        self._stderr = stderr
        self._stdin = stdin
        self._lock = threading.Lock()
        self._secrets: list[str] = []

    # Streams are resolved lazily so click's CliRunner can swap sys.stdout in tests.
    @property
    def stdout(self) -> TextIO:
        return self._stdout or sys.stdout

    @property
    def stderr(self) -> TextIO:
        return self._stderr or sys.stderr

    @property
    def stdin(self) -> TextIO:
        return self._stdin or sys.stdin

    @property
    def tracing(self) -> bool:
        return self.level >= Level.TRACE

    @property
    def verbose(self) -> bool:
        return self.level >= Level.VERBOSE

    # -- secrets -----------------------------------------------------------
    def add_secret(self, secret: str | None) -> None:
        if secret and secret not in self._secrets:
            self._secrets.append(secret)

    def redact(self, text: str) -> str:
        for s in self._secrets:
            text = text.replace(s, "***")
        return text

    # -- writing -----------------------------------------------------------
    def _write(self, stream: TextIO, text: str) -> None:
        with self._lock:
            stream.write(text + "\n")
            stream.flush()

    @staticmethod
    def _stamp() -> str:
        return time.strftime("%a %b %e %H:%M:%S %Z %Y")

    def info(self, msg: str) -> None:
        """A progress line. Plain at NORMAL, timestamped at VERBOSE, hidden at SILENT."""
        if self.level == Level.NORMAL:
            self._write(self.stdout, msg)
        elif self.level >= Level.VERBOSE:
            self._write(self.stdout, f"{self._stamp()}: {msg}")

    def debug(self, msg: str) -> None:
        """Upstream ``write_log``: shown only with ``-v``."""
        if self.level >= Level.VERBOSE:
            self._write(self.stderr, f"{self._stamp()}: {self.redact(msg)}")

    def warn(self, msg: str) -> None:
        if self.level > Level.SILENT:
            self._write(self.stderr, f"WARNING: {self.redact(msg)}")

    def trace(self, msg: str) -> None:
        """Protocol-level chatter, shown with ``-vv``."""
        if self.level >= Level.TRACE:
            self._write(self.stderr, self.redact(msg))

    def fatal(self, msg: str) -> None:
        """Always printed, always to stderr."""
        self._write(self.stderr, f"fatal: {self.redact(msg)}")

    def raw(self, text: str) -> None:
        """Verbatim text to stdout regardless of level (help, version)."""
        with self._lock:
            self.stdout.write(text)
            if not text.endswith("\n"):
                self.stdout.write("\n")
            self.stdout.flush()

    # -- reading -----------------------------------------------------------
    def ask(self, prompt: str) -> str:
        """Print ``prompt`` (no newline) and read one line; EOF reads as ''."""
        with self._lock:
            self.stdout.write(prompt)
            self.stdout.flush()
        line = self.stdin.readline()
        return line.rstrip("\r\n")

    def prompt_secret(self, prompt: str) -> str:
        if self._stdin is not None or not self.stdin.isatty():
            # Non-interactive: read a line without echo games (tests, pipes).
            with self._lock:
                self.stderr.write(prompt)
                self.stderr.flush()
            return self.stdin.readline().rstrip("\r\n")
        return getpass.getpass(prompt, stream=self.stderr)
