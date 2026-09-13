"""Configuration lookup with upstream's precedence.

Order for a key ``k`` with scope ``s`` (first *found* wins, even if the value
is empty, because ``git-ftp.<scope>.url ""`` is the documented way to mask a
default):

1. ``.git-ftp-config`` in the repository: ``git-ftp.<s>.k``
2. ``.git-ftp-config``: ``git-ftp.k``
3. git config (system, global, local merged): ``git-ftp.<s>.k``
4. git config: ``git-ftp.k``

A valueless key (a bare ``insecure`` line) is read as true, as git reads it.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from pathlib import Path

from gitftp import url as urlmod
from gitftp.errors import GitError, MissingArgumentError, UsageError
from gitftp.gitrepo import GitRunner

SECTION = "git-ftp"
CONFIG_FILE = ".git-ftp-config"
DEFAULT_DEPLOYED_SHA1_FILE = ".git-ftp.log"
DEFAULT_JOBS = 4
SCOPE_RE = re.compile(r"^[-0-9a-zA-Z_/]+$")

KEYS = (
    "url",
    "user",
    "password",
    "password-command",
    "keychain",
    "cacert",
    "insecure",
    "disable-epsv",
    "proxy",
    "no-commit",
    "branch",
    "syncroot",
    "key",
    "pubkey",
    "key-passphrase",
    "remote-root",
    "deployedsha1file",
    "jobs",
    "worktree",
)

_TRUE = frozenset({"true", "yes", "on", "1"})
_FALSE = frozenset({"false", "no", "off", "0", ""})


def parse_bool(value: str | None) -> bool | None:
    """Git's boolean spellings. ``None`` (valueless) is true; unknown text is ``None``."""
    if value is None:
        return True
    v = value.strip().lower()
    if v in _TRUE:
        return True
    if v in _FALSE:
        return False
    return None


class Config:
    def __init__(
        self,
        scope: str | None,
        file_cfg: Mapping[str, str | None],
        git_cfg: Mapping[str, str | None],
    ) -> None:
        self.scope = scope
        self._sources: tuple[Mapping[str, str | None], ...] = (file_cfg, git_cfg)

    @classmethod
    def load(cls, git: GitRunner, root: Path | None, scope: str | None) -> Config:
        file_cfg: Mapping[str, str | None] = {}
        base = root if root is not None else git.cwd
        cfg_file = base / CONFIG_FILE
        if cfg_file.is_file():
            file_cfg = git.config_list(cfg_file)
        git_cfg = git.config_list()
        return cls(scope, file_cfg, git_cfg)

    # -- lookups -----------------------------------------------------------
    def lookup_raw(self, key: str) -> tuple[bool, str | None]:
        """(found, value); value is None for a valueless key."""
        for src in self._sources:
            if self.scope:
                scoped = f"{SECTION}.{self.scope}.{key}"
                if scoped in src:
                    return True, src[scoped]
            plain = f"{SECTION}.{key}"
            if plain in src:
                return True, src[plain]
        return False, None

    def lookup(self, key: str) -> str | None:
        """The value, or ``None`` when the key is absent. A valueless key reads as ''."""
        found, value = self.lookup_raw(key)
        if not found:
            return None
        return "" if value is None else value

    def get(self, key: str, default: str = "") -> str:
        value = self.lookup(key)
        return default if value is None else value

    def get_bool(self, key: str, default: bool = False) -> bool:
        found, value = self.lookup_raw(key)
        if not found:
            return default
        parsed = parse_bool(value)
        if parsed is None:
            raise UsageError(f"Invalid boolean value '{value}' for git-ftp.{key}.")
        return parsed

    def get_int(self, key: str, default: int) -> int:
        value = self.lookup(key)
        if value is None or value == "":
            return default
        try:
            return int(value)
        except ValueError:
            raise UsageError(f"Invalid number '{value}' for git-ftp.{key}.") from None

    def git_option(self, dotted: str) -> str | None:
        """An ordinary (never scoped) git option such as ``http.proxy``."""
        value = self._sources[1].get(dotted.lower())
        return value


# -- scopes -----------------------------------------------------------------
def validate_scope(name: str, *, from_option: bool) -> str:
    if not name:
        raise MissingArgumentError("Missing scope argument.")
    if not SCOPE_RE.match(name):
        if from_option:
            raise UsageError(f"Invalid scope name '{name}'.")
        raise UsageError("Invalid scope name. Only these characters are allowed: 0-9 a-z A-Z - _ /")
    return name


def add_scope(git: GitRunner, scope: str, raw_url: str) -> None:
    """``git ftp add-scope``: store url/user/password in the local git config."""
    validate_scope(scope, from_option=False)
    if not raw_url:
        raise MissingArgumentError("Missing URL argument.")
    u = urlmod.parse(raw_url)
    lead = "/" if u.absolute else ""
    bare = (
        f"{u.scheme.value}://{u.host}/{lead}{u.path}".rstrip("/")
        if u.path
        else (f"{u.scheme.value}://{u.host}/{lead}".rstrip("/"))
    )
    git.config_set(f"{SECTION}.{scope}.url", bare)
    if u.user is not None:
        git.config_set(f"{SECTION}.{scope}.user", u.user)
    if u.password is not None:
        git.config_set(f"{SECTION}.{scope}.password", u.password)


def remove_scope(git: GitRunner, scope: str) -> None:
    validate_scope(scope, from_option=False)
    if not git.config_remove_section(f"{SECTION}.{scope}"):
        raise GitError(f"Cannot find scope {scope}.")
