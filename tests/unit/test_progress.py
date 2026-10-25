from __future__ import annotations

import io
import threading

from gitftp.output import Level, Output
from gitftp.progress import Progress, _screen_size


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
    assert p._bar is None
    assert out.stderr.getvalue() == ""  # nothing drawn
    assert out.stdout.getvalue() == ""


def test_disabled_at_verbose_and_silent() -> None:
    for level in (Level.SILENT, Level.VERBOSE, Level.TRACE):
        out = Output(level, stdout=io.StringIO(), stderr=_FakeTTY())
        assert not Progress(out, "Uploading", 1).enabled


def test_postfix_formatting() -> None:
    out = Output(Level.NORMAL, stdout=io.StringIO(), stderr=io.StringIO())
    p = Progress(out, "Uploading", 40, size=1000)
    assert p._postfix() == "0/40"
    p.done = 3
    assert p._postfix("dir/app.js") == "3/40  dir/app.js"
    # Counting files: the bar shows the count itself, the postfix only the file.
    assert Progress(out, "Deleting", 40)._postfix("dir/app.js") == "dir/app.js"


def test_zero_bytes_counts_files() -> None:
    out = Output(Level.NORMAL, stdout=io.StringIO(), stderr=_FakeTTY())
    with Progress(out, "Uploading", 3, size=0) as p:
        assert p.size is None
        assert p._bar.total == 3


def test_enabled_on_a_tty_draws_only_to_stderr() -> None:
    stdout, stderr = io.StringIO(), _FakeTTY()
    out = Output(Level.NORMAL, stdout=stdout, stderr=stderr)
    p = Progress(out, "Uploading", 2)
    assert p.enabled
    with p:
        assert p._bar is not None
        p.advance("one.txt")
        p.advance("two.txt")
        assert p._bar.n == 2
    assert p._bar is None  # closed cleanly
    assert p.done == 2
    assert "Uploading" in stderr.getvalue()
    assert stdout.getvalue() == ""  # never touches stdout


def test_bytes_mode_counts_deltas() -> None:
    out = Output(Level.NORMAL, stdout=io.StringIO(), stderr=_FakeTTY())
    with Progress(out, "Uploading", 2, size=30) as p:
        assert p._bar.total == 30
        p.transferred("a", 4)
        p.transferred("a", 10)
        p.transferred("a", 10)  # repeated reports add nothing
        p.advance("a")
        p.transferred("b", 20)
        assert p._bar.n == 30
        p.advance("b")
        assert p._bar.n == 30  # finishing a file adds no bytes
        assert p._seen == {}
    assert p.done == 2


def test_bytes_mode_restarted_transfer_goes_back() -> None:
    out = Output(Level.NORMAL, stdout=io.StringIO(), stderr=_FakeTTY())
    with Progress(out, "Uploading", 1, size=10) as p:
        p.transferred("a", 8)
        p.transferred("a", 3)
        assert p._bar.n == 3


def test_bytes_mode_concurrent_reports() -> None:
    out = Output(Level.NORMAL, stdout=io.StringIO(), stderr=_FakeTTY())
    files, chunks = 8, 500
    with Progress(out, "Uploading", files, size=files * chunks) as p:

        def worker(label: str) -> None:
            for n in range(1, chunks + 1):
                p.transferred(label, n)

        threads = [threading.Thread(target=worker, args=(f"f{i}",)) for i in range(files)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        assert p._bar.n == files * chunks


def test_transferred_is_a_noop_when_disabled() -> None:
    out = Output(Level.NORMAL, stdout=io.StringIO(), stderr=io.StringIO())
    with Progress(out, "Uploading", 1, size=10) as p:
        p.transferred("a", 5)
        assert p._seen == {}


def test_screen_size_falls_back_when_unknown() -> None:
    assert _screen_size(io.StringIO()) == (80, 24)


def test_draws_on_a_zero_size_pty() -> None:
    import os
    import pty
    import select

    master, slave = pty.openpty()  # reports 0x0, on which tqdm would hide the bar
    try:
        with os.fdopen(slave, "w") as stderr:
            out = Output(Level.NORMAL, stdout=io.StringIO(), stderr=stderr)
            assert _screen_size(stderr) == (80, 24)
            with Progress(out, "Uploading", 2):
                pass
        drawn = b""
        while select.select([master], [], [], 0.2)[0]:
            try:
                chunk = os.read(master, 4096)
            except OSError:
                break
            if not chunk:
                break
            drawn += chunk
    finally:
        os.close(master)
    assert b"Uploading" in drawn
