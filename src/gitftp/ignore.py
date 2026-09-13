""".git-ftp-ignore: shell-glob patterns matched against the whole git path.

Upstream matches with a bash ``case`` statement, so ``*`` and ``?`` also match
``/`` and the pattern must cover the entire path (``config/*`` ignores
``config/a/b`` but ``foo.txt`` does not ignore ``dir/foo.txt``).
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from pathlib import Path

IGNORE_FILE = ".git-ftp-ignore"


def glob_to_regex(pattern: str) -> re.Pattern[str]:
    """Translate a bash ``case`` glob into an anchored regex."""
    i, n = 0, len(pattern)
    out = ["^"]
    while i < n:
        c = pattern[i]
        i += 1
        if c == "*":
            out.append(".*")
        elif c == "?":
            out.append(".")
        elif c == "\\" and i < n:
            out.append(re.escape(pattern[i]))
            i += 1
        elif c == "[":
            j = i
            if j < n and pattern[j] in "!^":
                j += 1
            if j < n and pattern[j] == "]":
                j += 1
            while j < n and pattern[j] != "]":
                j += 1
            if j >= n:
                out.append(re.escape(c))
            else:
                body = pattern[i:j]
                i = j + 1
                if body and body[0] in "!^":
                    body = "^" + body[1:]
                body = body.replace("\\", "\\\\")
                out.append(f"[{body}]")
        else:
            out.append(re.escape(c))
    out.append("$")
    return re.compile("".join(out), re.DOTALL)


class IgnoreRules:
    def __init__(self, patterns: Iterable[str] = ()) -> None:
        self.patterns = [p for p in patterns if p]
        self._regexes = [glob_to_regex(p) for p in self.patterns]

    @classmethod
    def parse(cls, text: str) -> IgnoreRules:
        patterns = []
        for line in text.splitlines():
            line = line.rstrip("\r")
            if not line.strip() or line.startswith("#"):
                continue
            patterns.append(line)
        return cls(patterns)

    @classmethod
    def load(cls, root: Path) -> IgnoreRules:
        path = root / IGNORE_FILE
        if not path.is_file():
            return cls()
        return cls.parse(path.read_text(encoding="utf-8", errors="surrogateescape"))

    def __len__(self) -> int:
        return len(self.patterns)

    def matches(self, path: str) -> bool:
        return any(r.match(path) for r in self._regexes)

    def filter(self, paths: Iterable[str]) -> list[str]:
        return [p for p in paths if not self.matches(p)]
