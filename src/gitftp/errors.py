"""Exit codes and the exception hierarchy.

Every layer raises a :class:`GitFtpError` subclass; only :func:`gitftp.cli.main`
maps them to process exit codes. The numeric codes are upstream git-ftp's.
"""

from __future__ import annotations

import enum


class ExitCode(enum.IntEnum):
    """Process exit codes, identical to upstream git-ftp 1.6.0."""

    OK = 0
    UNKNOWN = 1
    USAGE = 2
    MISSING_ARGUMENTS = 3
    UPLOAD = 4
    DOWNLOAD = 5
    UNKNOWN_PROTOCOL = 6
    REMOTE_LOCKED = 7
    GIT = 8
    HOOK = 9
    FILESYSTEM = 10
    INTERRUPTED = 130


class GitFtpError(Exception):
    """Base class: a fatal condition with an exit code."""

    code: ExitCode = ExitCode.UNKNOWN

    def __init__(self, message: str, *, code: ExitCode | None = None) -> None:
        super().__init__(message)
        self.message = message
        if code is not None:
            self.code = code

    def __str__(self) -> str:
        return self.message


class UsageError(GitFtpError):
    code = ExitCode.USAGE


class MissingArgumentError(GitFtpError):
    code = ExitCode.MISSING_ARGUMENTS


class UploadError(GitFtpError):
    code = ExitCode.UPLOAD


class DownloadError(GitFtpError):
    code = ExitCode.DOWNLOAD


class UnknownProtocolError(GitFtpError):
    code = ExitCode.UNKNOWN_PROTOCOL


class RemoteLockedError(GitFtpError):
    code = ExitCode.REMOTE_LOCKED


class GitError(GitFtpError):
    code = ExitCode.GIT


class HookError(GitFtpError):
    code = ExitCode.HOOK


class FilesystemError(GitFtpError):
    code = ExitCode.FILESYSTEM


class Aborted(GitFtpError):
    """The user declined at a prompt. Not an error: exit 0, as upstream."""

    code = ExitCode.OK

    def __init__(self, message: str = "Aborting...") -> None:
        super().__init__(message)
