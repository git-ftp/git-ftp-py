"""The ``unlock`` action (new): remove a stale remote lock."""

from __future__ import annotations

from typing import Any

import click

from gitftp import mirror
from gitftp.cli.options import common_options, session_for, url_argument


@click.command("unlock", short_help="Remove a stale remote lock left by an interrupted deploy.")
@common_options
@url_argument
@click.pass_context
def command(ctx: click.Context, /, url: str | None, **kw: Any) -> None:
    _opts, session = session_for(ctx, url, kw, need_repo=False)
    mirror.run_unlock(session)
