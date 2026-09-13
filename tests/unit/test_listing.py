from __future__ import annotations

from datetime import datetime, timezone

from gitftp.transport.listing import parse_list, parse_mlsd, parse_nlst

MLSD = b"""type=cdir;modify=20240101120000;perm=el; .
type=pdir;modify=20240101120000;perm=el; ..
type=dir;modify=20240102030405;perm=el; dir 1
type=file;modify=20240102030405.123;size=1234;perm=r; test 1.txt
type=OS.unix=slink:/tmp/x;modify=20240102030405;size=5; link
"""

UNIX = b"""total 12
drwxr-xr-x    2 ftp      ftp          4096 Jan 02  2024 dir 1
-rw-r--r--    1 ftp      ftp          1234 Jan 02 03:04 test 1.txt
lrwxrwxrwx    1 ftp      ftp             5 Jan 02 03:04 link -> target
-rw-r--r--    1 1000     4096 Jan 02  2024 nogroup.txt
"""

DOS = b"""01-02-24  03:04PM       <DIR>          dir 1
01-02-24  03:04PM                 1234 test 1.txt
"""


def test_mlsd() -> None:
    entries = parse_mlsd(MLSD)
    names = [e.name for e in entries]
    assert names == ["dir 1", "test 1.txt", "link"]
    assert entries[0].is_dir and not entries[1].is_dir
    assert entries[1].size == 1234
    assert entries[1].mtime == int(datetime(2024, 1, 2, 3, 4, 5, tzinfo=timezone.utc).timestamp())
    assert entries[1].mtime_exact
    assert entries[2].is_link


def test_unix_list() -> None:
    now = datetime(2024, 6, 1, tzinfo=timezone.utc)
    entries = parse_list(UNIX, now)
    names = [e.name for e in entries]
    assert names == ["dir 1", "test 1.txt", "link", "nogroup.txt"]
    assert entries[0].is_dir
    assert entries[1].size == 1234 and not entries[1].mtime_exact
    assert entries[1].mtime == int(datetime(2024, 1, 2, 3, 4, tzinfo=timezone.utc).timestamp())
    assert entries[2].is_link
    assert entries[3].size == 4096


def test_unix_list_year_guess_in_future_uses_previous_year() -> None:
    now = datetime(2024, 1, 1, tzinfo=timezone.utc)
    (entry,) = parse_list(b"-rw-r--r-- 1 u g 1 Jun 02 03:04 f\n", now)
    assert entry.mtime == int(datetime(2023, 6, 2, 3, 4, tzinfo=timezone.utc).timestamp())


def test_dos_list() -> None:
    entries = parse_list(DOS)
    assert [e.name for e in entries] == ["dir 1", "test 1.txt"]
    assert entries[0].is_dir and entries[0].size is None
    assert entries[1].size == 1234
    assert entries[1].mtime == int(datetime(2024, 1, 2, 15, 4, tzinfo=timezone.utc).timestamp())


def test_nlst() -> None:
    assert parse_nlst(b".\r\n..\r\na\r\nsub/b\r\n") == ["a", "b"]
