"""The click group and the action registry."""

from __future__ import annotations

import importlib
from typing import Any

import click

from gitftp.version import version_line

ACTIONS: tuple[str, ...] = (
    "init",
    "push",
    "catchup",
    "show",
    "log",
    "download",
    "pull",
    "snapshot",
    "add-scope",
    "remove-scope",
    "unlock",
    "help",
    "version",
)

_MODULES = {name: f"gitftp.cli.cmd_{name.replace('-', '_')}" for name in ACTIONS}


class GitFtpGroup(click.Group):
    def list_commands(self, ctx: click.Context) -> list[str]:
        return list(ACTIONS)


def _print_version(ctx: click.Context, _param: click.Parameter, value: bool) -> None:
    if not value or ctx.resilient_parsing:
        return
    click.echo(version_line())
    ctx.exit(0)


def build_group() -> click.Group:
    @click.group(
        cls=GitFtpGroup,
        name="git-ftp",
        context_settings={"help_option_names": ["-h", "--help"], "max_content_width": 100},
        invoke_without_command=True,
        help="Git powered FTP, FTPS, FTPES and SFTP client.",
    )
    @click.option(
        "--version",
        is_flag=True,
        expose_value=False,
        is_eager=True,
        callback=_print_version,
        help="Print the version and exit.",
    )
    @click.pass_context
    def group(ctx: click.Context, /, **_kw: Any) -> None:
        if ctx.invoked_subcommand is None:
            click.echo("git-ftp <action> [<options>] [<url>]")
            ctx.exit(2)

    for name, module_name in _MODULES.items():
        module = importlib.import_module(module_name)
        group.add_command(module.command, name=name)
    return group
