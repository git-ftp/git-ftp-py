"""The ``add-scope`` action."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import click

from gitftp import config
from gitftp.cli.options import common_options, prepare
from gitftp.gitrepo import GitRepo


@click.command("add-scope", short_help="Store a URL (with credentials) under a scope name.")
@common_options
@click.argument("scope_name", metavar="SCOPE")
@click.argument("url", metavar="URL")
@click.pass_context
def command(ctx: click.Context, /, scope_name: str, url: str, **kw: Any) -> None:
    _opts, _out = prepare(ctx, kw)
    repo = GitRepo.discover(Path.cwd())
    config.add_scope(repo, scope_name, url)
