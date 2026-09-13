"""The ``pull`` action (native mirror, no lftp)."""

from __future__ import annotations

from typing import Any

import click

from gitftp import mirror
from gitftp.cli.options import common_options, session_for, url_argument


@click.command("pull", short_help="Download remote changes into a commit and merge it.")
@common_options
@url_argument
@click.pass_context
def command(ctx: click.Context, /, url: str | None, **kw: Any) -> None:
    opts, session = session_for(ctx, url, kw)
    mirror.run_pull(session, mirror.MirrorOptions.from_cli(opts))
