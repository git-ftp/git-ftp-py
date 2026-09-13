from __future__ import annotations

import io

from gitftp.output import Level, Output
from gitftp.progress import Progress


class _FakeTTY(io.StringIO):
    """A writable stream that claims to be a terminal."""

    def isatty(self) -> bool:
        return True


def test_disabled_when_not_a_tty() -> None:
    out = Output(Level.NORMAL, stdout=io.StringIO(), stderr=io.StringIO())
    with Progress(out, "Uploading", 3) as p:
        assert not p.enabled
        p.advance("a.txt")
        p.advance("b.txt")
    assert p.done == 2  # still counts
    assert p._spinner is None
    assert out.stderr.getvalue() == ""  # nothing drawn
    assert out.stdout.getvalue() == ""


def test_disabled_at_verbose_and_silent() -> None:
    for level in (Level.SILENT, Level.VERBOSE, Level.TRACE):
        out = Output(level, stdout=io.StringIO(), stderr=_FakeTTY())
        assert not Progress(out, "Uploading", 1).enabled


def test_text_formatting() -> None:
    out = Output(Level.NORMAL, stdout=io.StringIO(), stderr=io.StringIO())
    p = Progress(out, "Uploading", 40)
    assert p._text() == "Uploading 0/40"
    p.done = 3
    assert p._text("dir/app.js") == "Uploading 3/40  dir/app.js"


def test_enabled_on_a_tty_draws_only_to_stderr() -> None:
    stdout, stderr = io.StringIO(), _FakeTTY()
    out = Output(Level.NORMAL, stdout=stdout, stderr=stderr)
    p = Progress(out, "Uploading", 2)
    assert p.enabled
    with p:
        assert p._spinner is not None
        p.advance("one.txt")
        p.advance("two.txt")
    assert p._spinner is None  # stopped cleanly
    assert p.done == 2
    assert stdout.getvalue() == ""  # never touches stdout
