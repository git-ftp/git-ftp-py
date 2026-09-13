from __future__ import annotations

from gitftp.include import IncludeRule, parse_rules, resolve_source


def test_parse_rules() -> None:
    rules = parse_rules(
        "# c\n!VERSION.txt\ncss/style.css:scss/style.scss\r\nvendor/:composer.lock\n\nnocolon\n"
    )
    assert rules == [
        IncludeRule("VERSION.txt", None, True),
        IncludeRule("css/style.css", "scss/style.scss", False),
        IncludeRule("vendor/", "composer.lock", False),
    ]


def test_bang_line_with_colon_is_always() -> None:
    rules = parse_rules("!a:b\n")
    assert rules == [IncludeRule("a:b", None, True)]


def test_resolve_source() -> None:
    assert resolve_source("style.scss", "html/") == "html/style.scss"
    assert resolve_source("/src/style.scss", "dist/") == "src/style.scss"
    assert resolve_source("x", "") == "x"
