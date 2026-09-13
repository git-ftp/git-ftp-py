"""The push action."""

from __future__ import annotations

from typing import Any

import click

from gitftp import deploy
from gitftp.cli.options import common_options, session_for, url_argument


@click.command(
    "push", short_help="Upload changed and delete removed files since the last deployment."
)
@common_options
@url_argument
@click.pass_context
def command(ctx: click.Context, /, url: str | None, **kw: Any) -> None:
    opts, session = session_for(ctx, url, kw)
    deploy.run(deploy.Action.PUSH, session, deploy.DeployOptions.from_cli(opts))
