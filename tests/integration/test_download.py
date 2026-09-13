from __future__ import annotations

import os
import time
from collections.abc import Callable

from tests.conftest import RunCli
from tests.helpers.ftpserver import FtpServer
from tests.helpers.gitrepo import Repo
from tests.integration.conftest import auth, cacert_args


def test_download_fetches_foreign_file(
    run_cli: RunCli, repo: Repo, any_ftp_server: FtpServer
) -> None:
    s = any_ftp_server
    assert run_cli("init", *auth(s), *cacert_args(s), s.url()).code == 0
    s.remote().write("external.txt", "from remote\n")
    s.remote().write("newdir/deep/file.txt", "deep\n")
    r = run_cli("download", *auth(s), *cacert_args(s), s.url())
    assert r.code == 0, r
    assert repo.read("external.txt") == "from remote\n"
    assert repo.read("newdir/deep/file.txt") == "deep\n"
    assert not repo.exists(".git-ftp.log")


def test_download_insecure_over_tls(run_cli: RunCli, repo: Repo, ftpes_server: FtpServer) -> None:
    s = ftpes_server
    assert run_cli("init", "--insecure", *auth(s), s.url()).code == 0
    s.remote().write("external.txt", "x\n")
    assert run_cli("download", "--insecure", *auth(s), s.url()).code == 0
    assert repo.exists("external.txt")


def test_download_refuses_untracked_exit_8(
    run_cli: RunCli, repo: Repo, ftp_server: FtpServer
) -> None:
    s = ftp_server
    assert run_cli("init", *auth(s), s.url()).code == 0
    s.remote().write("external.txt", "x\n")
    repo.write("untracked.txt", "u\n")
    r = run_cli("download", *auth(s), s.url())
    assert r.code == 8
    assert "Dirty repository: Having untracked files. Exiting..." in r.stderr
    assert not repo.exists("external.txt")
    assert repo.exists("untracked.txt")


def test_download_into_syncroot(run_cli: RunCli, repo: Repo, ftp_server: FtpServer) -> None:
    s = ftp_server
    repo.write("foobar/index.html", "i\n")
    repo.commit("sync")
    assert run_cli("init", "--syncroot", "foobar", *auth(s), s.url()).code == 0
    s.remote().write("external.txt", "x\n")
    assert run_cli("download", "--syncroot", "foobar/", *auth(s), s.url()).code == 0
    assert repo.exists("foobar/external.txt")
    assert not repo.exists("external.txt")
    assert repo.exists("test 1.txt")  # outside the syncroot: untouched


def test_download_dry_run_touches_nothing(
    run_cli: RunCli, repo: Repo, ftp_server: FtpServer
) -> None:
    s = ftp_server
    assert run_cli("init", *auth(s), s.url()).code == 0
    s.remote().write("external.txt", "x\n")
    s.remote().delete("test 1.txt")
    r = run_cli("download", "--dry-run", *auth(s), s.url())
    assert r.code == 0
    assert "Would download 'external.txt'." in r.stdout
    assert "Would delete local 'test 1.txt'." in r.stdout
    assert not repo.exists("external.txt")
    assert repo.exists("test 1.txt")


def test_download_deletes_local_files_missing_on_remote_except_ignored(
    run_cli: RunCli, repo: Repo, ftp_server: FtpServer
) -> None:
    s = ftp_server
    repo.write(".git-ftp-ignore", "test 5.txt\n")
    repo.commit("ignore")
    assert run_cli("init", *auth(s), s.url()).code == 0
    s.remote().delete("test 1.txt")
    s.remote().delete("dir 2/test 2.txt")
    (s.remote().root / "dir 2").rmdir()
    assert not s.remote().exists("test 5.txt")
    r = run_cli("download", *auth(s), s.url())
    assert r.code == 0, r
    assert not repo.exists("test 1.txt")
    assert not repo.exists("dir 2")
    assert repo.exists("test 5.txt")
    assert repo.exists(".git")
    assert repo.exists(".git-ftp-ignore")


def test_download_changed_only(run_cli: RunCli, repo: Repo, ftp_server: FtpServer) -> None:
    s = ftp_server
    assert run_cli("init", *auth(s), s.url()).code == 0
    repo.write("test 1.txt", "local change\n")
    repo.commit("local")
    s.remote().write("test 1.txt", "remote change\n")
    s.remote().write("external.txt", "x\n")
    s.remote().delete("test 2.txt")
    r = run_cli("download", "--changed-only", *auth(s), s.url())
    assert r.code == 0, r
    assert repo.read("test 1.txt") == "remote change\n"
    assert not repo.exists("external.txt")
    assert repo.exists("test 2.txt")


def test_download_falls_back_to_list_when_mlsd_missing(
    run_cli: RunCli, repo: Repo, ftp_server_factory: Callable[..., FtpServer]
) -> None:
    s = ftp_server_factory("plain", None, mlsd=False)
    assert run_cli("init", *auth(s), s.url()).code == 0
    s.remote().write("external.txt", "x\n")
    s.remote().write("deep/er/file.txt", "d\n")
    r = run_cli("download", "-v", *auth(s), s.url())
    assert r.code == 0, r
    assert repo.read("external.txt") == "x\n"
    assert repo.read("deep/er/file.txt") == "d\n"


def test_download_updates_changed_files_only(
    run_cli: RunCli, repo: Repo, ftp_server: FtpServer
) -> None:
    s = ftp_server
    assert run_cli("init", *auth(s), s.url()).code == 0
    s.remote().write("test 3.txt", "changed size\n")
    # The remote files carry their upload time, a moment after the local files were
    # created. On a slow runner that gap exceeds the 1s mtime tolerance and an
    # unchanged, same-size file would also be pulled. Stamp the local tree into the
    # future so only the size-changed file is downloaded, regardless of runner speed.
    future = time.time() + 3600
    for path in repo.path.rglob("*"):
        if path.is_file() and ".git" not in path.relative_to(repo.path).parts:
            os.utime(path, (future, future))
    r = run_cli("download", *auth(s), s.url())
    assert r.code == 0
    assert "Downloaded 1 file(s), deleted 0 local file(s)." in r.stdout
    assert repo.read("test 3.txt") == "changed size\n"
