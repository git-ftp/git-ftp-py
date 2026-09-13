from __future__ import annotations

from pathlib import Path

import pytest

from gitftp.auth import AuthFlags, resolve
from gitftp.config import Config
from gitftp.errors import MissingArgumentError
from gitftp.output import Level, Output
from gitftp.url import parse


def cfg(**kw: str | None) -> Config:
    return Config(None, {}, {f"git-ftp.{k.replace('_', '-')}": v for k, v in kw.items()})


def out() -> Output:
    return Output(Level.SILENT)


def test_user_precedence(monkeypatch: pytest.MonkeyPatch) -> None:
    env = {"GIT_FTP_USER": "envuser", "USER": "local"}
    u = parse("ftp://urluser@h/")
    assert resolve(cfg(user="cfg"), u, AuthFlags(user="flag"), out(), env=env).user == "flag"
    assert resolve(cfg(user="cfg"), u, AuthFlags(user=""), out(), env=env).user == "local"
    assert resolve(cfg(user="cfg"), u, AuthFlags(), out(), env=env).user == "urluser"
    assert (
        resolve(cfg(user="cfg"), parse("ftp://h/"), AuthFlags(), out(), env=env).user == "envuser"
    )
    assert resolve(cfg(user="cfg"), parse("ftp://h/"), AuthFlags(), out(), env={}).user == "cfg"


def test_password_precedence(tmp_path: Path) -> None:
    env = {"GIT_FTP_PASSWORD": "envpw"}
    u = parse("ftp://u:urlpw@h/")
    assert (
        resolve(cfg(password="cfgpw"), u, AuthFlags(password="flagpw"), out(), env=env).password
        == "flagpw"
    )
    assert resolve(cfg(password="cfgpw"), u, AuthFlags(), out(), env=env).password == "urlpw"
    plain = parse("ftp://u@h/")
    assert resolve(cfg(password="cfgpw"), plain, AuthFlags(), out(), env=env).password == "envpw"
    assert resolve(cfg(password="cfgpw"), plain, AuthFlags(), out(), env={}).password == "cfgpw"
    assert resolve(cfg(password=""), plain, AuthFlags(), out(), env={}).password == ""
    assert resolve(cfg(), plain, AuthFlags(), out(), env={}).password is None


def test_password_dash_prefixed_flag() -> None:
    creds = resolve(cfg(), parse("ftp://u@h/"), AuthFlags(password="-secret"), out(), env={})
    assert creds.password == "-secret"


def test_password_command(tmp_path: Path) -> None:
    creds = resolve(
        cfg(password_command="printf 'cmdpw\\nsecond'"),
        parse("ftp://u@h/"),
        AuthFlags(),
        out(),
        env={},
    )
    assert creds.password == "cmdpw"
    with pytest.raises(MissingArgumentError):
        resolve(cfg(password_command="exit 2"), parse("ftp://u@h/"), AuthFlags(), out(), env={})


def test_netrc_only_without_user_and_password(tmp_path: Path) -> None:
    netrc = tmp_path / ".netrc"
    netrc.write_text("machine h login nuser password npw\ndefault login duser password dpw\n")
    env = {"HOME": str(tmp_path)}
    creds = resolve(cfg(), parse("ftp://h/"), AuthFlags(), out(), env=env)
    assert (creds.user, creds.password) == ("nuser", "npw")
    creds = resolve(cfg(), parse("ftp://other/"), AuthFlags(), out(), env=env)
    assert (creds.user, creds.password) == ("duser", "dpw")
    creds = resolve(cfg(), parse("ftp://alice@h/"), AuthFlags(), out(), env=env)
    assert (creds.user, creds.password) == ("alice", None)
    env2 = {"NETRC": str(netrc)}
    assert resolve(cfg(), parse("ftp://h/"), AuthFlags(), out(), env=env2).user == "nuser"


def test_keys_and_pub_sibling(tmp_path: Path) -> None:
    key = tmp_path / "id"
    key.write_text("k")
    (tmp_path / "id.pub").write_text("p")
    creds = resolve(
        cfg(key=str(key), key_passphrase="pp"), parse("sftp://u@h/"), AuthFlags(), out(), env={}
    )
    assert creds.key == str(key)
    assert creds.pubkey == str(key) + ".pub"
    assert creds.key_passphrase == "pp"
    creds = resolve(
        cfg(), parse("sftp://u@h/"), AuthFlags(key="~/id", pubkey="~/x.pub"), out(), env={}
    )
    assert creds.key is not None and not creds.key.startswith("~")


def test_secrets_are_redacted() -> None:
    o = out()
    resolve(cfg(), parse("ftp://u:topsecret@h/"), AuthFlags(), o, env={})
    assert o.redact("PASS topsecret") == "PASS ***"


def test_keychain_ignored_off_darwin(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("gitftp.auth.sys.platform", "linux")
    creds = resolve(
        cfg(keychain="acct@host", password="cfgpw"), parse("ftp://u@h/"), AuthFlags(), out(), env={}
    )
    assert creds.password == "cfgpw"
