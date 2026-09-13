"""The ``version`` action."""

from __future__ import annotations

from typing import Any

import click

from gitftp.cli.options import common_options
from gitftp.version import runtime_info, version_line


@click.command("version", short_help="Print the version.")
@common_options
def command(verbose: int = 0, **_kw: Any) -> None:
    click.echo(version_line())
    if verbose:
        for line in runtime_info():
            click.echo(line)
