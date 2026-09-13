from __future__ import annotations

import sys

import pytest

from tests.conftest import RunCli
from tests.helpers.ftpserver import FtpServer
from tests.helpers.gitrepo import Repo
from tests.integration.conftest import auth, cacert_args


def test_hidden_file_uploaded(run_cli: RunCli, repo: Repo, ftp_server: FtpServer) -> None:
    s = ftp_server
    repo.write(".htaccess", "h\n")
    repo.commit("hidden")
    assert run_cli("init", *auth(s), s.url()).code == 0
    assert s.remote().exists(".htaccess")


def _roundtrip(run_cli: RunCli, repo: Repo, s: FtpServer, names: list[str]) -> None:
    for n in names:
        repo.write(n, f"content of {n}\n")
    repo.commit("odd names")
    r = run_cli("init", *auth(s), *cacert_args(s), s.url())
    assert r.code == 0, r
    for n in names:
        s.remote().assert_equals_local(n, repo)
    repo.rm(*names)
    repo.commit("rm")
    r = run_cli("push", *auth(s), *cacert_args(s), s.url())
    assert r.code == 0, r
    for n in names:
        assert not s.remote().exists(n), n


def test_hash_and_space_in_name_upload_and_delete(
    run_cli: RunCli, repo: Repo, any_ftp_server: FtpServer
) -> None:
    _roundtrip(
        run_cli,
        repo,
        any_ftp_server,
        [
            "#4253-Release Contest.md",
            "v1.2.0 #8950 - Custom Partner Player.md",
            "dir/with #hash/f.txt",
        ],
    )


def test_special_characters(run_cli: RunCli, repo: Repo, ftp_server: FtpServer) -> None:
    # Characters legal on every filesystem, including NTFS.
    _roundtrip(
        run_cli,
        repo,
        ftp_server,
        ["100%.txt", "[b]racket.txt", "semi;colon.txt", "a&b.txt", "at@sign.txt"],
    )


@pytest.mark.skipif(sys.platform == "win32", reason="characters illegal in NTFS filenames")
def test_special_characters_illegal_on_windows(
    run_cli: RunCli, repo: Repo, ftp_server: FtpServer
) -> None:
    _roundtrip(run_cli, repo, ftp_server, ["q?.txt", "star*.txt", "pipe|.txt", "lt<gt>.txt"])


def test_unicode_name_upload_and_delete(
    run_cli: RunCli, repo: Repo, any_ftp_server: FtpServer
) -> None:
    _roundtrip(run_cli, repo, any_ftp_server, ["umlaut_ä.md", "dir ü/日本語.txt"])


def test_leading_dash_name(run_cli: RunCli, repo: Repo, ftp_server: FtpServer) -> None:
    _roundtrip(run_cli, repo, ftp_server, ["-dash", "-dashdir/file.txt"])


def test_file_named_single_dash(run_cli: RunCli, repo: Repo, ftp_server: FtpServer) -> None:
    _roundtrip(run_cli, repo, ftp_server, ["-"])
