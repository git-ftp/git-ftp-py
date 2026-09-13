"""The ``snapshot`` action: turn a remote directory into a new repository."""

from __future__ import annotations

from typing import Any

import click

from gitftp import mirror
from gitftp.cli.options import common_options, prepare, url_argument


@click.command("snapshot", short_help="Download a remote directory into a new repository.")
@common_options
@url_argument
@click.argument("directory", required=False, metavar="[DIRECTORY]")
@click.pass_context
def command(ctx: click.Context, /, url: str | None, directory: str | None, **kw: Any) -> None:
    opts, out = prepare(ctx, kw)
    mirror.run_snapshot(opts, url, directory, out)
