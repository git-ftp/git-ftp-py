from __future__ import annotations

import pytest

from tests.conftest import RunCli
from tests.helpers.ftpserver import FtpServer
from tests.helpers.gitrepo import Repo
from tests.integration.conftest import auth, cacert_args


def bulk(repo: Repo, n: int = 60) -> list[str]:
    names = [f"bulk/f{i:03}.txt" for i in range(n)]
    for i, name in enumerate(names):
        repo.write(name, ("x" * (1024 + i * 50)) + "\n")
    repo.commit("bulk")
    return names


@pytest.mark.slow
def test_parallel_jobs_4_uploads_all_and_log_last(
    run_cli: RunCli, repo: Repo, any_ftp_server: FtpServer
) -> None:
    s = any_ftp_server
    names = bulk(repo)
    r = run_cli("init", "-j", "4", *auth(s), *cacert_args(s), s.url())
    assert r.code == 0, r
    for name in names:
        s.remote().assert_equals_local(name, repo)
    assert s.received[-1] == "site/.git-ftp.log"
    assert 1 < s.max_concurrent <= 5


def test_jobs_1_is_serial(run_cli: RunCli, repo: Repo, ftp_server: FtpServer) -> None:
    s = ftp_server
    names = bulk(repo, 20)
    assert run_cli("init", "-j", "1", *auth(s), s.url()).code == 0
    assert s.max_concurrent == 1
    assert [x for x in s.received if x.startswith("site/bulk/")] == [f"site/{n}" for n in names]


def test_jobs_from_config(run_cli: RunCli, repo: Repo, ftp_server: FtpServer) -> None:
    s = ftp_server
    bulk(repo, 30)
    repo.config("git-ftp.jobs", "3")
    r = run_cli("init", "-v", *auth(s), s.url())
    assert r.code == 0
    assert "Jobs is '3'." in r.stderr
    assert 1 < s.max_concurrent <= 4


def test_fail_fast_on_upload_error(run_cli: RunCli, repo: Repo, ftp_server: FtpServer) -> None:
    s = ftp_server
    assert run_cli("init", *auth(s), s.url()).code == 0
    first = repo.head()
    bulk(repo, 40)
    s.deny_upload("site/bulk/f030.txt")
    r = run_cli("push", "-j", "4", "--lock", *auth(s), s.url())
    assert r.code == 4, r
    assert "fatal: Could not upload files." in r.stderr
    assert "f030.txt" in r.stderr
    assert s.remote().log() == first
    assert s.remote().lock() is None


def test_parallel_delete(run_cli: RunCli, repo: Repo, ftp_server: FtpServer) -> None:
    s = ftp_server
    names = bulk(repo, 30)
    assert run_cli("init", "-j", "4", *auth(s), s.url()).code == 0
    repo.rm(*names)
    repo.commit("rm")
    r = run_cli("push", "-j", "4", *auth(s), s.url())
    assert r.code == 0, r
    for name in names:
        assert not s.remote().exists(name)
