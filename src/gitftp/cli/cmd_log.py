"""The log action."""

from __future__ import annotations

from typing import Any

import click

from gitftp.cli.options import common_options, session_for, url_argument
from gitftp.errors import DownloadError, GitError
from gitftp.transport import registry
from gitftp.transport.base import RemoteNotFound


@click.command("log", short_help="Run 'git log' on the deployed commit.")
@common_options
@url_argument
@click.pass_context
def command(ctx: click.Context, /, url: str | None, **kw: Any) -> None:
    _opts, session = session_for(ctx, url, kw)
    registry.check_available(session.url.scheme)
    try:
        data = session.primary.get(session.deployed_sha1_file)
    except (RemoteNotFound, DownloadError) as e:
        raise DownloadError(f"Could not get uploaded log file. {e}") from e
    sha = data.decode("utf-8", "replace").strip()
    if not sha:
        raise DownloadError("Could not get uploaded log file. It is empty.")
    session.close()
    if session.require_repo().log(sha) != 0:
        raise GitError(f"git log {sha} failed.")
