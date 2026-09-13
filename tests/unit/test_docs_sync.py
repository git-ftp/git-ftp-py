"""The hand-maintained man page must mention every command and every long option."""

from __future__ import annotations

from pathlib import Path

import click

from gitftp.cli.group import ACTIONS, build_group

MAN = Path(__file__).resolve().parents[2] / "docs" / "git-ftp.1.md"


def test_man_page_documents_every_command_and_option() -> None:
    text = MAN.read_text(encoding="utf-8")
    group = build_group()
    missing: list[str] = []
    for name in ACTIONS:
        if f"*{name}*" not in text:
            missing.append(name)
    ctx = click.Context(group)
    for name in ACTIONS:
        cmd = group.get_command(ctx, name)
        assert cmd is not None
        for param in cmd.params:
            for opt in param.opts:
                if opt.startswith("--") and opt not in text:
                    missing.append(f"{name}: {opt}")
    assert not missing, f"undocumented in docs/git-ftp.1.md: {sorted(set(missing))}"
