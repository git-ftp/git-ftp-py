"""Options shared by every action, plus helpers for command modules."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any, TypeVar

import click

from gitftp.options import CliOptions
from gitftp.output import Output
from gitftp.session import Session, open_session

F = TypeVar("F", bound=Callable[..., Any])

# Options that take a value; the CLI normaliser must not mistake the value for the action.
VALUE_OPTIONS = frozenset(
    {
        "-u",
        "--user",
        "-p",
        "--passwd",
        "--password",
        "--password-command",
        "-k",
        "--keychain",
        "--key",
        "--pubkey",
        "--key-passphrase",
        "-b",
        "--branch",
        "-c",
        "--commit",
        "-s",
        "--scope",
        "--syncroot",
        "--remote-root",
        "--cacert",
        "-x",
        "--proxy",
        "-j",
        "--jobs",
    }
)
OPTIONAL_VALUE_OPTIONS = frozenset({"-u", "--user", "-k", "--keychain", "-s", "--scope"})
_LONG = {"-u": "--user", "-k": "--keychain", "-s": "--scope"}


def long_name(opt: str) -> str:
    return _LONG.get(opt, opt)


def common_options(f: F) -> F:
    decorators = [
        click.option(
            "-u",
            "--user",
            "user",
            is_flag=False,
            flag_value="",
            default=None,
            metavar="[USER]",
            help="FTP login name (bare -u: the local user).",
        ),
        click.option(
            "-p",
            "--passwd",
            "--password",
            "password",
            default=None,
            metavar="PASSWORD",
            help="FTP password.",
        ),
        click.option(
            "-P",
            "--ask-passwd",
            "ask_password",
            is_flag=True,
            help="Ask for the password interactively.",
        ),
        click.option(
            "--password-command",
            default=None,
            metavar="CMD",
            help="Shell command whose first output line is the password.",
        ),
        click.option(
            "-k",
            "--keychain",
            "keychain",
            is_flag=False,
            flag_value="",
            default=None,
            metavar="[[ACCOUNT]@[HOST]]",
            help="macOS keychain entry (bare -k: guess).",
        ),
        click.option("--key", default=None, metavar="FILE", help="SFTP private key."),
        click.option("--pubkey", default=None, metavar="FILE", help="SFTP public key."),
        click.option(
            "--key-passphrase",
            default=None,
            metavar="TEXT",
            help="Passphrase of the SFTP private key.",
        ),
        click.option(
            "-b",
            "--branch",
            default=None,
            metavar="BRANCH",
            help="Deploy this branch instead of the current one.",
        ),
        click.option(
            "-c",
            "--commit",
            default=None,
            metavar="SHA",
            help="Treat SHA as the deployed commit instead of reading the remote log.",
        ),
        click.option(
            "-s",
            "--scope",
            "scope",
            is_flag=False,
            flag_value="",
            default=None,
            metavar="[SCOPE]",
            help="Configuration scope (bare -s: current branch).",
        ),
        click.option(
            "--syncroot",
            default=None,
            metavar="DIR",
            help="Deploy only this directory, as the remote root.",
        ),
        click.option(
            "--remote-root",
            default=None,
            metavar="DIR",
            help="Remote directory, replacing the path in the URL.",
        ),
        click.option(
            "--cacert", default=None, metavar="FILE", help="CA certificate bundle for FTPS/FTPES."
        ),
        click.option("-x", "--proxy", default=None, metavar="URL", help="Proxy URL."),
        click.option(
            "-j",
            "--jobs",
            type=int,
            default=None,
            metavar="N",
            help="Parallel connections (default 4, 1 = sequential).",
        ),
        click.option(
            "-a", "--all", "all", is_flag=True, help="Upload all files, not only changes."
        ),
        click.option("-A", "--active", is_flag=True, help="Use FTP active mode."),
        click.option("-l", "--lock", is_flag=True, help="Lock the remote during the deploy."),
        click.option("-D", "--dry-run", is_flag=True, help="Show what would happen."),
        click.option("-f", "--force", is_flag=True, help="Skip the lock check and questions."),
        click.option("-n", "--silent", is_flag=True, help="Print nothing but fatal errors."),
        click.option("-v", "--verbose", count=True, help="Verbose (-vv: protocol trace)."),
        click.option(
            "--insecure", is_flag=True, help="Do not verify TLS certificates / host keys."
        ),
        click.option("--disable-epsv", is_flag=True, help="Use PASV instead of EPSV."),
        click.option("--no-commit", is_flag=True, help="pull: merge without committing."),
        click.option(
            "--changed-only",
            is_flag=True,
            help="download/pull: only files that changed locally as well.",
        ),
        click.option("--no-verify", is_flag=True, help="Skip the pre-ftp-push hook."),
        click.option("--no-post-hooks", is_flag=True, help="Skip the post-ftp-push hook."),
        click.option(
            "--enable-post-errors", is_flag=True, help="Fail when the post-ftp-push hook fails."
        ),
        click.option("--auto-init", is_flag=True, help="push: init when the remote has no log."),
        click.option(
            "--worktree",
            is_flag=True,
            help="Upload files from a temporary git worktree so edits to the working "
            "tree during the upload are ignored.",
        ),
    ]
    for d in reversed(decorators):
        f = d(f)
    return f


url_argument = click.argument("url", required=False, metavar="[URL]")


def prepare(ctx: click.Context, kw: dict[str, Any]) -> tuple[CliOptions, Output]:
    opts = CliOptions.from_kwargs(kw)
    out: Output = ctx.obj if isinstance(ctx.obj, Output) else Output()
    out.level = opts.level
    ctx.obj = out
    return opts, out


def session_for(
    ctx: click.Context, url: str | None, kw: dict[str, Any], *, need_repo: bool = True
) -> tuple[CliOptions, Session]:
    opts, out = prepare(ctx, kw)
    session = open_session(opts, url, out, cwd=Path.cwd(), need_repo=need_repo)
    ctx.call_on_close(session.close)
    return opts, session
