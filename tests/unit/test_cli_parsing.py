from __future__ import annotations

import pytest

from gitftp.cli import level_from_argv, normalize_argv
from gitftp.errors import MissingArgumentError
from gitftp.output import Level


def test_action_moved_to_front() -> None:
    assert normalize_argv(["-u", "john", "push", "ftp://h/"]) == ["push", "-u", "john", "ftp://h/"]


def test_bare_optional_value_before_action() -> None:
    assert normalize_argv(["-u", "push", "ftp://h/"]) == ["push", "--user=", "ftp://h/"]
    assert normalize_argv(["push", "-s", "-D"]) == ["push", "--scope=", "-D"]
    assert normalize_argv(["push", "-k"]) == ["push", "--keychain="]


def test_value_options_keep_their_value() -> None:
    assert normalize_argv(["push", "-p", "-secret", "u"]) == ["push", "-p", "-secret", "u"]
    assert normalize_argv(["-b", "init", "push"]) == ["push", "-b", "init"]


def test_no_verify_does_not_swallow_argument() -> None:
    assert normalize_argv(["push", "--no-verify", "ftp://h/"]) == [
        "push",
        "--no-verify",
        "ftp://h/",
    ]


def test_empty_is_usage() -> None:
    assert normalize_argv([]) is None


def test_unknown_action() -> None:
    with pytest.raises(MissingArgumentError, match=r"Action unknown\."):
        normalize_argv(["bogus"])


def test_help_and_version_pass_through() -> None:
    assert normalize_argv(["--version"]) == ["--version"]
    assert normalize_argv(["-h"]) == ["-h"]


def test_levels() -> None:
    assert level_from_argv(["push"]) is Level.NORMAL
    assert level_from_argv(["push", "-v"]) is Level.VERBOSE
    assert level_from_argv(["push", "-vv"]) is Level.TRACE
    assert level_from_argv(["-v", "push", "-v"]) is Level.TRACE
    assert level_from_argv(["push", "-n"]) is Level.SILENT
