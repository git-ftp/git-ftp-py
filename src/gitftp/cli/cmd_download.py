"""The ``download`` action (native mirror, no lftp)."""

from __future__ import annotations

from typing import Any

import click

from gitftp import mirror
from gitftp.cli.options import common_options, session_for, url_argument


@click.command("download", short_help="Download the remote files into the working tree.")
@common_options
@url_argument
@click.pass_context
def command(ctx: click.Context, /, url: str | None, **kw: Any) -> None:
    opts, session = session_for(ctx, url, kw)
    mirror.run_download(session, mirror.MirrorOptions.from_cli(opts))
