"""Against a real pure-ftpd (see .github/workflows/test.yml and docker-compose.test.yml)."""

from __future__ import annotations

import os
import uuid

import pytest

from tests.conftest import RunCli
from tests.helpers.gitrepo import Repo

pytestmark = pytest.mark.docker


def _env(name: str, default: str = "") -> str:
    return os.environ.get(name, default)


def _url(addr: str, path: str) -> str:
    return f"ftp://{addr}/{path}"


def _auth() -> list[str]:
    return [
        "-u",
        _env("GIT_FTP_TEST_FTP_USER", "gitftp"),
        "-p",
        _env("GIT_FTP_TEST_FTP_PASS", "s3cret"),
    ]


@pytest.fixture
def site() -> str:
    return f"site-{uuid.uuid4().hex[:8]}"


def test_cli_init_push_against_pure_ftpd(run_cli: RunCli, repo: Repo, site: str) -> None:
    url = _url(_env("GIT_FTP_TEST_FTP_ADDR"), site)
    names = ["with space.txt", "unicöde.txt", "hash#tag.txt", "deep/er/file.txt"]
    for n in names:
        repo.write(n, n + "\n")
    repo.commit("odd")
    r = run_cli("init", "-j", "4", *_auth(), url)
    assert r.code == 0, r
    repo.rm(*names)
    repo.commit("rm")
    r = run_cli("push", *_auth(), url)
    assert r.code == 0, r
    r = run_cli("push", *_auth(), url)
    assert "Everything up-to-date." in r.stdout


def test_active_mode(run_cli: RunCli, repo: Repo, site: str) -> None:
    url = _url(_env("GIT_FTP_TEST_FTP_ADDR"), site)
    r = run_cli("init", "-A", *_auth(), url)
    assert r.code == 0, r


def test_bad_pasv_address_ignored_with_disable_epsv(run_cli: RunCli, repo: Repo, site: str) -> None:
    url = _url(_env("GIT_FTP_TEST_FTP_BADPASV_ADDR"), site)
    r = run_cli("init", "--disable-epsv", *_auth(), url)
    assert r.code == 0, r
    repo.write("x.txt", "x\n")
    repo.commit("x")
    r = run_cli("push", "--disable-epsv", *_auth(), url)
    assert r.code == 0, r


def test_download_round_trip(run_cli: RunCli, repo: Repo, site: str) -> None:
    url = _url(_env("GIT_FTP_TEST_FTP_ADDR"), site)
    assert run_cli("init", *_auth(), url).code == 0
    repo.rm("test 1.txt")
    repo.commit("rm locally")
    # Sequential download: this pure-ftpd fixture allows only 5 connections per IP
    # (-c 5 -C 5), and a parallel scan-then-download can brush that limit and stall
    # a data connection. The parallel download path is covered by the pyftpdlib tests.
    r = run_cli("download", "-j", "1", *_auth(), url)
    assert r.code == 0, r
    assert repo.exists("test 1.txt")
