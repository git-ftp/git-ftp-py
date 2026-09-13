from __future__ import annotations

from pathlib import Path

import pytest

from gitftp.ignore import IgnoreRules, glob_to_regex


@pytest.mark.parametrize(
    ("pattern", "path", "expected"),
    [
        ("config/*", "config/a.txt", True),
        ("config/*", "config/sub/deep.txt", True),  # * crosses '/', as in bash case
        ("config/*", "other/config/a.txt", False),
        ("*.txt", "dir/a.txt", True),
        ("foobar.txt", "foobar.txt", True),
        ("foobar.txt", "dir/foobar.txt", False),  # whole path must match
        ("test", "test 1.txt", False),
        ("test*", "test 1.txt", True),
        ("test *.txt", "test 1.txt", True),
        ("*/.gitkeep", "dir 1/.gitkeep", True),
        ("*/.gitkeep", ".gitkeep", False),
        ("dir 1/*", "dir 1/test 1.txt", True),
        ("dir 1/*", "dir 2/test 2.txt", False),
        ("[ab]*.txt", "a1.txt", True),
        ("[!ab]*.txt", "a1.txt", False),
        ("{a,b}.txt", "{a,b}.txt", True),
        ("{a,b}.txt", "a.txt", False),
        ("a?c", "abc", True),
        ("a?c", "a/c", True),
        ("a\\*c", "a*c", True),
        ("a\\*c", "abc", False),
    ],
)
def test_glob(pattern: str, path: str, expected: bool) -> None:
    assert bool(glob_to_regex(pattern).match(path)) is expected


def test_parse_skips_comments_blank_and_crlf() -> None:
    rules = IgnoreRules.parse("# comment\r\n\r\n  \nfoo.txt\r\nbar/*\n")
    assert rules.patterns == ["foo.txt", "bar/*"]
    assert rules.matches("foo.txt")
    assert rules.matches("bar/x")
    assert not rules.matches("baz")


def test_filter_and_load(tmp_path: Path) -> None:
    (tmp_path / ".git-ftp-ignore").write_text("*.log\n")
    rules = IgnoreRules.load(tmp_path)
    assert len(rules) == 1
    assert rules.filter(["a.log", "b.txt"]) == ["b.txt"]
    assert len(IgnoreRules.load(tmp_path / "missing")) == 0
