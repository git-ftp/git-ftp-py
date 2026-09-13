from __future__ import annotations

import pytest

from gitftp.config import Config, parse_bool
from gitftp.errors import UsageError


def make(
    scope: str | None = None,
    file: dict[str, str | None] | None = None,
    git: dict[str, str | None] | None = None,
) -> Config:
    return Config(scope, file or {}, git or {})


def test_precedence_file_scoped_first() -> None:
    cfg = make(
        "prod",
        file={"git-ftp.prod.url": "f-scoped", "git-ftp.url": "f-plain"},
        git={"git-ftp.prod.url": "g-scoped", "git-ftp.url": "g-plain"},
    )
    assert cfg.get("url") == "f-scoped"
    assert (
        make("prod", file={"git-ftp.url": "f-plain"}, git={"git-ftp.prod.url": "g-scoped"}).get(
            "url"
        )
        == "f-plain"
    )
    assert (
        make("prod", git={"git-ftp.prod.url": "g-scoped", "git-ftp.url": "g-plain"}).get("url")
        == "g-scoped"
    )
    assert make("prod", git={"git-ftp.url": "g-plain"}).get("url") == "g-plain"
    assert make(None, git={"git-ftp.prod.url": "x"}).lookup("url") is None


def test_scoped_empty_masks_default() -> None:
    cfg = make("testing", git={"git-ftp.testing.url": "", "git-ftp.url": "ftp://default/"})
    assert cfg.lookup("url") == ""
    assert cfg.get("url", "fallback") == ""


def test_valueless_key_is_true() -> None:
    cfg = make(None, git={"git-ftp.insecure": None})
    assert cfg.get_bool("insecure") is True
    assert cfg.lookup("insecure") == ""


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("true", True),
        ("yes", True),
        ("on", True),
        ("1", True),
        ("TRUE", True),
        ("false", False),
        ("no", False),
        ("off", False),
        ("0", False),
        ("", False),
    ],
)
def test_bools(value: str, expected: bool) -> None:
    assert parse_bool(value) is expected
    assert make(None, git={"git-ftp.no-commit": value}).get_bool("no-commit") is expected


def test_invalid_bool() -> None:
    with pytest.raises(UsageError):
        make(None, git={"git-ftp.insecure": "maybe"}).get_bool("insecure")


def test_get_int() -> None:
    assert make(None, git={"git-ftp.jobs": "8"}).get_int("jobs", 4) == 8
    assert make(None).get_int("jobs", 4) == 4
    with pytest.raises(UsageError):
        make(None, git={"git-ftp.jobs": "many"}).get_int("jobs", 4)


def test_git_option_unscoped() -> None:
    cfg = make("s", git={"http.proxy": "http://p:3128"})
    assert cfg.git_option("http.proxy") == "http://p:3128"
