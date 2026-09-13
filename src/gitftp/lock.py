"""The remote lock file ``git-ftp.lck``.

Content: ``<sha>\\n<user>@<host> on <RFC 2822 date>``. Upstream wrote a literal
backslash-n (``echo`` without ``-e``); both forms are accepted when reading.
"""

from __future__ import annotations

import getpass
import socket
from datetime import datetime, timezone
from email.utils import format_datetime

from gitftp.errors import RemoteLockedError, UploadError
from gitftp.output import Output
from gitftp.transport.base import RemoteNotFound, Transport

LOCK_FILE = "git-ftp.lck"


def parse(data: bytes) -> tuple[str, str]:
    """Return (sha, holder) from a lock file, tolerant of upstream's literal ``\\n``."""
    text = data.decode("utf-8", "replace")
    if "\n" not in text and "\\n" in text:
        text = text.replace("\\n", "\n", 1)
    lines = text.splitlines()
    sha = lines[0].strip() if lines else ""
    holder = lines[1].strip() if len(lines) > 1 else ""
    return sha, holder


def holder_message(now: datetime | None = None) -> str:
    when = now or datetime.now(timezone.utc)
    try:
        user = getpass.getuser()
    except Exception:
        user = "unknown"
    return f"{user}@{socket.getfqdn()} on {format_datetime(when)}"


class RemoteLock:
    def __init__(
        self,
        transport: Transport,
        local_sha: str,
        *,
        enabled: bool,
        force: bool,
        dry_run: bool,
        out: Output,
    ) -> None:
        self.transport = transport
        self.local_sha = local_sha
        self.enabled = enabled
        self.force = force
        self.dry_run = dry_run
        self.out = out
        self.held = False

    def check(self) -> None:
        self.out.debug("Checking remote lock.")
        try:
            data = self.transport.get(LOCK_FILE)
        except RemoteNotFound:
            return
        sha, holder = parse(data)
        if sha and sha != self.local_sha:
            raise RemoteLockedError(f"Remote locked by {holder}.")

    def acquire(self) -> None:
        """Check and write the lock; only with ``--lock``, as upstream."""
        if not self.enabled:
            return
        if not self.force:
            self.check()
        if self.dry_run:
            return
        self.out.debug("Creating remote lock.")
        content = f"{self.local_sha}\n{holder_message()}\n".encode()
        try:
            self.transport.put_bytes(content, LOCK_FILE)
        except UploadError as e:
            raise UploadError(f"Could not upload lock file. {e}") from e
        self.held = True

    def release(self) -> None:
        if not self.held:
            return
        self.out.debug("Releasing remote lock.")
        try:
            self.transport.delete(LOCK_FILE)
        except Exception as e:
            self.out.warn(f"Could not remove remote lock: {e}")
        self.held = False
