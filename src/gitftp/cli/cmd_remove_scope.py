"""The ``remove-scope`` action."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import click

from gitftp import config
from gitftp.cli.options import common_options, prepare
from gitftp.gitrepo import GitRepo


@click.command("remove-scope", short_help="Delete a scope from the git config.")
@common_options
@click.argument("scope_name", metavar="SCOPE")
@click.pass_context
def command(ctx: click.Context, /, scope_name: str, **kw: Any) -> None:
    _opts, out = prepare(ctx, kw)
    repo = GitRepo.discover(Path.cwd())
    config.remove_scope(repo, scope_name)
    out.info(f"Successfully removed scope {scope_name}.")
