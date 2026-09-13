"""Command-line entry point: argv normalisation and exit-code mapping."""

from __future__ import annotations

import sys
import traceback

import click

from gitftp.cli.group import ACTIONS, build_group
from gitftp.cli.options import OPTIONAL_VALUE_OPTIONS, VALUE_OPTIONS, long_name
from gitftp.errors import Aborted, ExitCode, GitFtpError, MissingArgumentError
from gitftp.output import Level, Output

USAGE = "git-ftp <action> [<options>] [<url>]"
_PASSTHROUGH = {"-h", "--help", "--version"}


def level_from_argv(argv: list[str]) -> Level:
    level = Level.NORMAL
    for tok in argv:
        if tok in ("-n", "--silent"):
            return Level.SILENT
        if tok == "--verbose" or (tok.startswith("-v") and set(tok[1:]) == {"v"}):
            count = 1 if tok == "--verbose" else len(tok) - 1
            level = Level.TRACE if count >= 2 or level == Level.VERBOSE else Level.VERBOSE
    return level


def normalize_argv(argv: list[str]) -> list[str] | None:
    """Move the action to the front and make bare optional-value options explicit.

    Returns ``None`` when there is nothing to run (bare ``git-ftp``).
    """
    action: str | None = None
    rest: list[str] = []
    i = 0
    n = len(argv)
    while i < n:
        tok = argv[i]
        if tok == "--":
            rest.extend(argv[i:])
            break
        if action is None and tok in ACTIONS:
            action = tok
            i += 1
            continue
        if tok in OPTIONAL_VALUE_OPTIONS:
            nxt = argv[i + 1] if i + 1 < n else None
            if nxt is None or nxt.startswith("-") or (action is None and nxt in ACTIONS):
                rest.append(f"{long_name(tok)}=")
                i += 1
                continue
            rest.extend([tok, nxt])
            i += 2
            continue
        if tok in VALUE_OPTIONS:
            rest.extend(argv[i : i + 2])
            i += 2
            continue
        rest.append(tok)
        i += 1
    if action is None:
        if not argv:
            return None
        if any(tok in _PASSTHROUGH for tok in argv):
            return rest
        raise MissingArgumentError("Action unknown.")
    return [action, *rest]


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    out = Output(level_from_argv(args))
    try:
        normalized = normalize_argv(args)
        if normalized is None:
            out.raw(USAGE)
            return int(ExitCode.USAGE)
        build_group().main(args=normalized, prog_name="git-ftp", standalone_mode=False, obj=out)
    except click.exceptions.Exit as e:
        return int(e.exit_code)
    except (
        click.NoSuchOption,
        click.BadOptionUsage,
        click.MissingParameter,
        click.BadParameter,
    ) as e:
        out.fatal(e.format_message())
        return int(ExitCode.MISSING_ARGUMENTS)
    except click.UsageError as e:
        out.fatal(e.format_message())
        return int(ExitCode.USAGE)
    except click.Abort:
        out.fatal("Interrupted.")
        return int(ExitCode.INTERRUPTED)
    except Aborted:
        return int(ExitCode.OK)
    except GitFtpError as e:
        if e.message:
            out.fatal(e.message)
        return int(e.code)
    except KeyboardInterrupt:
        out.fatal("Interrupted.")
        return int(ExitCode.INTERRUPTED)
    except Exception as e:
        out.fatal(f"Unexpected error: {e}")
        if out.tracing:
            out.trace(traceback.format_exc())
        return int(ExitCode.UNKNOWN)
    return int(ExitCode.OK)
