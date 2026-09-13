"""Credential resolution.

Precedence (first hit wins):

user:     -u flag (bare -u => the local user) > URL userinfo > $GIT_FTP_USER > git-ftp.user
password: -p > -P prompt > URL userinfo > password-command > keychain > $GIT_FTP_PASSWORD
          > git-ftp.password (present-but-empty counts) > none
netrc:    consulted only when no user and no password were found at all.
"""

from __future__ import annotations

import getpass
import netrc
import os
import re
import subprocess
import sys
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

from gitftp.config import Config
from gitftp.errors import MissingArgumentError
from gitftp.output import Output
from gitftp.url import RemoteURL


@dataclass
class AuthFlags:
    user: str | None = None  # None = not given; "" = bare -u
    password: str | None = None
    ask_password: bool = False
    password_command: str | None = None
    keychain: str | None = None  # None = not given; "" = bare -k
    key: str | None = None
    pubkey: str | None = None
    key_passphrase: str | None = None


@dataclass
class Credentials:
    user: str = ""
    password: str | None = None
    key: str | None = None
    pubkey: str | None = None
    key_passphrase: str | None = None


def local_user(env: Mapping[str, str]) -> str:
    for var in ("USER", "USERNAME", "LOGNAME"):
        if env.get(var):
            return env[var]
    try:
        return getpass.getuser()
    except Exception:
        return ""


def run_password_command(command: str, out: Output) -> str:
    """Run ``command`` through the shell; the first line of stdout is the password."""
    out.debug("Running password command.")
    if sys.platform == "win32":
        argv: list[str] = ["cmd.exe", "/c", command]
    else:
        argv = ["/bin/sh", "-c", command]
    try:
        proc = subprocess.run(argv, stdout=subprocess.PIPE, stdin=subprocess.DEVNULL, check=False)
    except OSError as e:
        raise MissingArgumentError(f"Password command failed: {e}") from e
    if proc.returncode != 0:
        raise MissingArgumentError(f"Password command failed with exit code {proc.returncode}.")
    text = proc.stdout.decode("utf-8", "surrogateescape")
    return text.split("\n", 1)[0].rstrip("\r")


def keychain_lookup(account: str, host: str, out: Output) -> str | None:
    """macOS ``security find-internet-password``; None when not found."""
    argv = ["security", "find-internet-password", "-g", "-a", account]
    if host:
        argv += ["-s", host]
    try:
        proc = subprocess.run(argv, capture_output=True, check=False)
    except OSError:
        return None
    err = proc.stderr.decode("utf-8", "replace")
    if proc.returncode != 0 or "could not be found" in err:
        return None
    m = re.search(r'^password: (?:0x([0-9A-Fa-f]+)\s+)?"(.*)"$', err, re.MULTILINE)
    if not m:
        return None
    if m.group(1):
        return bytes.fromhex(m.group(1)).decode("utf-8", "replace")
    return m.group(2)


def netrc_lookup(hostname: str, env: Mapping[str, str]) -> tuple[str, str | None] | None:
    if env.get("NETRC"):
        candidates = [Path(env["NETRC"])]
    else:
        home = Path(env.get("HOME") or Path.home())
        candidates = [home / ".netrc", home / "_netrc"]
    for path in candidates:
        if not path.is_file():
            continue
        try:
            rc = netrc.netrc(str(path))
        except (netrc.NetrcParseError, OSError):
            continue
        entry = rc.authenticators(hostname)
        if entry is None:
            for name, auth in rc.hosts.items():
                if name.lower() == hostname.lower():
                    entry = auth
                    break
        if entry is None and "default" in rc.hosts:
            entry = rc.hosts["default"]
        if entry is not None:
            login, _account, password = entry
            return login or "", password or None
    return None


def expand_path(p: str | None) -> str | None:
    if not p:
        return None
    return os.path.expanduser(p)


def resolve(
    cfg: Config,
    url: RemoteURL,
    flags: AuthFlags,
    out: Output,
    *,
    env: Mapping[str, str] | None = None,
) -> Credentials:
    env = os.environ if env is None else env

    # -- user ----------------------------------------------------------------
    if flags.user is not None:
        user = flags.user or local_user(env)
    elif url.user is not None:
        user = url.user
    elif env.get("GIT_FTP_USER"):
        user = env["GIT_FTP_USER"]
    else:
        user = cfg.get("user", "")

    # -- password ------------------------------------------------------------
    password: str | None
    if flags.password is not None:
        password = flags.password
    elif flags.ask_password:
        password = out.prompt_secret("Password: ")
    elif url.password is not None:
        password = url.password
    else:
        password = None
        command = flags.password_command or cfg.get("password-command")
        keychain_spec = flags.keychain if flags.keychain is not None else cfg.lookup("keychain")
        if command:
            password = run_password_command(command, out)
        elif keychain_spec is not None:
            if sys.platform != "darwin":
                out.debug("Ignoring -k on non-Darwin systems.")
            else:
                account, host = user, url.hostname
                if "@" in keychain_spec:
                    a, _, h = keychain_spec.partition("@")
                    account = a or account
                    host = h or host
                elif keychain_spec:
                    account = keychain_spec
                if not account:
                    raise MissingArgumentError("Missing keychain account.")
                found = keychain_lookup(account, host, out)
                if found is None:
                    raise MissingArgumentError(
                        f"Password not found in keychain for account '{account} @ {host}'."
                    )
                password = found
        if password is None:
            if env.get("GIT_FTP_PASSWORD"):
                password = env["GIT_FTP_PASSWORD"]
            else:
                password = cfg.lookup("password")

    # -- netrc ---------------------------------------------------------------
    if user == "" and password is None:
        entry = netrc_lookup(url.hostname, env)
        if entry is not None:
            out.debug("Using credentials from netrc.")
            user, password = entry

    # -- ssh keys ------------------------------------------------------------
    key = expand_path(flags.key or cfg.get("key"))
    pubkey = expand_path(flags.pubkey or cfg.get("pubkey"))
    if key and not pubkey and os.access(f"{key}.pub", os.R_OK):
        pubkey = f"{key}.pub"
    passphrase = (
        flags.key_passphrase if flags.key_passphrase is not None else cfg.lookup("key-passphrase")
    )

    out.add_secret(password)
    out.add_secret(passphrase)
    return Credentials(
        user=user, password=password, key=key, pubkey=pubkey, key_passphrase=passphrase
    )
