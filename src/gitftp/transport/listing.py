"""Parsers for FTP directory listings (MLSD, Unix/DOS LIST, NLST)."""

from __future__ import annotations

import calendar
import re
from datetime import datetime, timezone

from gitftp.transport.base import Entry

_MONTHS = {m.lower(): i for i, m in enumerate(calendar.month_abbr) if m}

_UNIX_RE = re.compile(
    r"^(?P<type>[-dlcbps])(?P<perm>[rwxsStTlL\-+@.]{9,})\s+"
    r"(?:\d+\s+)?"  # link count (may be absent on some servers)
    r"(?P<owner>\S+)\s+(?:(?P<group>\S+)\s+)?"
    r"(?P<size>\d+)\s+"
    r"(?P<month>[A-Za-z]{3})\s+(?P<day>\d{1,2})\s+"
    r"(?:(?P<year>\d{4})|(?P<hour>\d{1,2}):(?P<minute>\d{2}))\s+"
    r"(?P<name>.+)$"
)
_DOS_RE = re.compile(
    r"^(?P<month>\d{2})-(?P<day>\d{2})-(?P<year>\d{2,4})\s+"
    r"(?P<hour>\d{2}):(?P<minute>\d{2})(?P<ampm>[AP]M)\s+"
    r"(?P<size><DIR>|\d+)\s+(?P<name>.+)$"
)


def _decode(data: bytes) -> list[str]:
    text = data.decode("utf-8", "surrogateescape")
    return [line.rstrip("\r") for line in text.split("\n") if line.strip("\r")]


def _parse_mlsd_time(value: str) -> int | None:
    m = re.match(r"^(\d{14})(?:\.\d+)?$", value)
    if not m:
        return None
    dt = datetime.strptime(m.group(1), "%Y%m%d%H%M%S").replace(tzinfo=timezone.utc)
    return int(dt.timestamp())


def parse_mlsd(data: bytes) -> list[Entry]:
    entries: list[Entry] = []
    for line in _decode(data):
        facts_part, sep, name = line.partition(" ")
        if not sep or not name:
            continue
        facts: dict[str, str] = {}
        for fact in facts_part.split(";"):
            if "=" in fact:
                k, v = fact.split("=", 1)
                facts[k.lower()] = v
        ftype = facts.get("type", "file").lower()
        if ftype in ("cdir", "pdir") or name in (".", ".."):
            continue
        is_link = ftype.startswith("os.unix=slink") or ftype == "os.unix=symlink"
        is_dir = ftype == "dir"
        size = int(facts["size"]) if facts.get("size", "").isdigit() else None
        mtime = _parse_mlsd_time(facts["modify"]) if "modify" in facts else None
        entries.append(
            Entry(
                name=name, is_dir=is_dir, size=size, mtime=mtime, mtime_exact=True, is_link=is_link
            )
        )
    return entries


def _guess_year_ts(month: int, day: int, hour: int, minute: int, now: datetime) -> int:
    year = now.year
    try:
        dt = datetime(year, month, day, hour, minute, tzinfo=timezone.utc)
    except ValueError:
        return 0
    if dt.timestamp() > now.timestamp() + 86400:
        dt = dt.replace(year=year - 1)
    return int(dt.timestamp())


def parse_list(data: bytes, now: datetime | None = None) -> list[Entry]:
    """Parse a ``LIST`` reply in Unix ``ls -l`` or DOS/IIS format."""
    now = now or datetime.now(timezone.utc)
    entries: list[Entry] = []
    for line in _decode(data):
        if line.lower().startswith("total "):
            continue
        m = _UNIX_RE.match(line)
        if m:
            name = m.group("name")
            is_link = m.group("type") == "l"
            if is_link and " -> " in name:
                name = name.split(" -> ", 1)[0]
            if name in (".", ".."):
                continue
            month = _MONTHS.get(m.group("month").lower())
            if month is None:
                continue
            day = int(m.group("day"))
            if m.group("year"):
                dt = datetime(int(m.group("year")), month, day, tzinfo=timezone.utc)
                mtime = int(dt.timestamp())
            else:
                mtime = _guess_year_ts(
                    month, day, int(m.group("hour")), int(m.group("minute")), now
                )
            entries.append(
                Entry(
                    name=name,
                    is_dir=m.group("type") == "d",
                    size=int(m.group("size")),
                    mtime=mtime,
                    mtime_exact=False,
                    is_link=is_link,
                )
            )
            continue
        m = _DOS_RE.match(line)
        if m:
            name = m.group("name")
            if name in (".", ".."):
                continue
            year = int(m.group("year"))
            if year < 100:
                year += 2000 if year < 70 else 1900
            hour = int(m.group("hour")) % 12
            if m.group("ampm") == "PM":
                hour += 12
            dt = datetime(
                year,
                int(m.group("month")),
                int(m.group("day")),
                hour,
                int(m.group("minute")),
                tzinfo=timezone.utc,
            )
            is_dir = m.group("size") == "<DIR>"
            entries.append(
                Entry(
                    name=name,
                    is_dir=is_dir,
                    size=None if is_dir else int(m.group("size")),
                    mtime=int(dt.timestamp()),
                    mtime_exact=False,
                )
            )
    return entries


def parse_nlst(data: bytes) -> list[str]:
    names = []
    for line in _decode(data):
        name = line.rsplit("/", 1)[-1] if line.endswith("/") is False else line.rstrip("/")
        name = name.rsplit("/", 1)[-1]
        if name and name not in (".", ".."):
            names.append(name)
    return names
