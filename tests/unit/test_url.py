from __future__ import annotations

import pytest

from gitftp import url as urlmod
from gitftp.errors import MissingArgumentError, UnknownProtocolError
from gitftp.url import Scheme, escape_path, parse


def test_plain_ftp_with_path() -> None:
    u = parse("ftp://example.com/public_html")
    assert u.scheme is Scheme.FTP
    assert u.host == "example.com"
    assert u.path == "public_html/"
    assert u.user is None and u.password is None
    assert not u.absolute


def test_default_scheme_is_ftp() -> None:
    u = parse("example.com/foo/bar/")
    assert u.scheme is Scheme.FTP
    assert u.path == "foo/bar/"


def test_host_port_without_scheme() -> None:
    u = parse("127.0.0.1:2121/site")
    assert u.scheme is Scheme.FTP
    assert u.host == "127.0.0.1:2121"
    assert u.hostname == "127.0.0.1"
    assert u.port == 2121


def test_userinfo_is_credentials() -> None:
    u = parse("ftp://alice:s3cret@example.com/x")
    assert u.host == "example.com"
    assert u.user == "alice"
    assert u.password == "s3cret"


def test_password_with_colon_and_at() -> None:
    u = parse("ftpes://user:pa:ss@w@ftp.example.com/x")
    assert u.user == "user"
    assert u.password == "pa:ss@w"
    assert u.host == "ftp.example.com"


def test_percent_encoded_userinfo() -> None:
    u = parse("ftp://a%40b:p%23w@h/")
    assert u.user == "a@b"
    assert u.password == "p#w"


def test_user_without_password() -> None:
    u = parse("ftp://alice@example.com/")
    assert u.user == "alice"
    assert u.password is None


@pytest.mark.parametrize("scheme", ["ftp", "ftps", "ftpes", "sftp", "FTPS"])
def test_all_schemes(scheme: str) -> None:
    u = parse(f"{scheme}://h/p")
    assert u.scheme.value == scheme.lower()


def test_unknown_scheme() -> None:
    with pytest.raises(UnknownProtocolError, match=r"Protocol unknown 'badprotocol://'\."):
        parse("badProtocol://localhost/")


def test_one_slash_scheme_is_unknown() -> None:
    with pytest.raises(UnknownProtocolError):
        parse("ftp:host/path")


def test_empty_is_missing() -> None:
    with pytest.raises(MissingArgumentError):
        parse("   ")


def test_absolute_path() -> None:
    u = parse("sftp://h//var/www")
    assert u.absolute
    assert u.path == "var/www/"
    assert u.sftp_path("a.txt") == "/var/www/a.txt"
    assert u.curl_file_url("a.txt") == "sftp://h/%2Fvar/www/a.txt"


def test_sftp_relative_and_home() -> None:
    assert parse("sftp://h/~/public").sftp_path("x") == "public/x"
    assert parse("sftp://h/public").sftp_path("x") == "public/x"
    assert parse("sftp://h").sftp_path("") == "."


def test_set_path_replaces() -> None:
    u = parse("ftp://h/old/path")
    u.set_path("/new")
    assert u.path == "new/"
    assert u.absolute


def test_child() -> None:
    u = parse("ftp://h/site")
    assert u.child("sub").path == "site/sub/"
    assert u.child("").path == "site/"


def test_display_masks_password() -> None:
    u = parse("ftp://alice:secret@h:21/site")
    assert u.display() == "ftp://alice:***@h:21/site/"
    assert "secret" not in u.display()
    assert u.name() == "h:21/site/"


def test_curl_urls_never_have_credentials() -> None:
    u = parse("ftpes://alice:secret@h/site")
    assert u.curl_base() == "ftp://h"
    assert u.curl_file_url("a b#c.txt") == "ftp://h/site/a%20b%23c.txt"
    assert u.curl_dir_url("d") == "ftp://h/site/d/"
    assert u.curl_dir_url("") == "ftp://h/site/"


def test_escape_path() -> None:
    assert escape_path("a/b c") == "a/b%20c"
    assert escape_path("x#y?z%[1]") == "x%23y%3Fz%25%5B1%5D"
    assert escape_path("umlaut_ä.md") == "umlaut_%C3%A4.md"
    assert escape_path("back\\slash") == "back%5Cslash"
    assert escape_path("-dash") == "-dash"


def test_ipv6_host() -> None:
    u = parse("ftp://[::1]:2121/x")
    assert u.hostname == "::1"
    assert u.port == 2121


def test_escape_module_roundtrip() -> None:
    assert urlmod.unescape(urlmod.escape_userinfo("p@:s/s")) == "p@:s/s"
