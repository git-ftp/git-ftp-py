from __future__ import annotations

from tests.conftest import RunCli
from tests.helpers.ftpserver import FtpServer
from tests.helpers.gitrepo import Repo
from tests.integration.conftest import auth


def test_delete_file_then_directory_contents(
    run_cli: RunCli, repo: Repo, ftp_server: FtpServer
) -> None:
    s = ftp_server
    assert run_cli("init", *auth(s), s.url()).code == 0
    repo.rm("test 1.txt")
    repo.commit("rm")
    assert run_cli("push", *auth(s), s.url()).code == 0
    assert not s.remote().exists("test 1.txt")
    assert s.remote().exists("dir 1/test 1.txt")
    repo.rm("dir 1", recursive=True)
    repo.commit("rm dir")
    r = run_cli("push", *auth(s), s.url())
    assert r.code == 0, r
    assert not s.remote().exists("dir 1/test 1.txt")
    # Upstream behaviour (issue #168): emptied directories are kept.
    assert s.remote().exists("dir 1")


def test_delete_failure_is_warning_only(run_cli: RunCli, repo: Repo, ftp_server: FtpServer) -> None:
    s = ftp_server
    assert run_cli("init", *auth(s), s.url()).code == 0
    s.remote().delete("test 1.txt")
    repo.rm("test 1.txt")
    repo.commit("rm")
    r = run_cli("push", *auth(s), s.url())
    assert r.code == 0, r
    assert s.remote().log() == repo.head()
