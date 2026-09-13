"""The ``help`` action."""

from __future__ import annotations

from typing import Any

import click

from gitftp.cli.options import common_options


@click.command("help", short_help="Show this help.")
@common_options
@click.pass_context
def command(ctx: click.Context, /, **_kw: Any) -> None:
    root = ctx.find_root()
    click.echo(root.get_help())
    click.echo()
    for name in root.command.list_commands(root) if isinstance(root.command, click.Group) else []:
        cmd = (
            root.command.get_command(root, name) if isinstance(root.command, click.Group) else None
        )
        if cmd is not None and name not in ("help", "version"):
            click.echo(f"  {name:14s} {cmd.get_short_help_str(limit=80)}")
    click.echo()
    click.echo("Options accepted by every action:")
    with click.Context(ctx.command, info_name="<action>") as sub:
        formatter = sub.make_formatter()
        ctx.command.format_options(sub, formatter)
        click.echo(formatter.getvalue().rstrip())
