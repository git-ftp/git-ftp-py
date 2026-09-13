"""Command-line options as a plain dataclass (independent of click)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from gitftp.auth import AuthFlags
from gitftp.output import Level


@dataclass
class CliOptions:
    user: str | None = None
    password: str | None = None
    ask_password: bool = False
    password_command: str | None = None
    keychain: str | None = None
    key: str | None = None
    pubkey: str | None = None
    key_passphrase: str | None = None
    branch: str | None = None
    commit: str | None = None
    scope: str | None = None
    syncroot: str | None = None
    remote_root: str | None = None
    cacert: str | None = None
    proxy: str | None = None
    jobs: int | None = None
    all: bool = False
    active: bool = False
    lock: bool = False
    dry_run: bool = False
    force: bool = False
    silent: bool = False
    verbose: int = 0
    insecure: bool = False
    disable_epsv: bool = False
    no_commit: bool = False
    changed_only: bool = False
    no_verify: bool = False
    no_post_hooks: bool = False
    enable_post_errors: bool = False
    auto_init: bool = False

    @classmethod
    def from_kwargs(cls, kw: dict[str, Any]) -> CliOptions:
        fields = {f for f in cls.__dataclass_fields__}
        return cls(**{k: v for k, v in kw.items() if k in fields})

    @property
    def level(self) -> Level:
        if self.silent:
            return Level.SILENT
        if self.verbose >= 2:
            return Level.TRACE
        if self.verbose == 1:
            return Level.VERBOSE
        return Level.NORMAL

    def auth_flags(self) -> AuthFlags:
        return AuthFlags(
            user=self.user,
            password=self.password,
            ask_password=self.ask_password,
            password_command=self.password_command,
            keychain=self.keychain,
            key=self.key,
            pubkey=self.pubkey,
            key_passphrase=self.key_passphrase,
        )
