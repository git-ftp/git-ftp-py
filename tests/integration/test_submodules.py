from __future__ import annotations

from tests.conftest import RunCli
from tests.helpers.ftpserver import FtpServer
from tests.helpers.gitrepo import Repo
from tests.integration.conftest import auth


def test_submodule_files_uploaded_with_own_log(
    run_cli: RunCli, repo: Repo, ftp_server: FtpServer
) -> None:
    s = ftp_server
    sub = repo.add_submodule("sub", {"file.txt": "sub\n"})
    r = run_cli("init", *auth(s), s.url())
    assert r.code == 0, r
    assert "Handling submodule sync for sub." in r.stdout
    assert s.remote().read("sub/file.txt") == "sub\n"
    assert s.remote("site/sub").log() == sub.head()
    assert s.remote().log() == repo.head()


def test_submodule_push_after_change(run_cli: RunCli, repo: Repo, ftp_server: FtpServer) -> None:
    s = ftp_server
    sub = repo.add_submodule("sub", {"file.txt": "sub\n"})
    assert run_cli("init", *auth(s), s.url()).code == 0
    sub.write("file.txt", "changed\n")
    sub.commit("sub change")
    repo.commit("bump sub")
    r = run_cli("push", *auth(s), s.url())
    assert r.code == 0, r
    assert s.remote().read("sub/file.txt") == "changed\n"
    assert s.remote("site/sub").log() == sub.head()


def test_submodule_uses_netrc(run_cli: RunCli, repo: Repo, ftp_server: FtpServer, home) -> None:  # type: ignore[no-untyped-def]
    s = ftp_server
    repo.add_submodule("sub", {"file.txt": "sub\n"})
    netrc = home / ".netrc"
    netrc.write_text(f"machine {s.host} login {s.USER} password {s.PASSWORD}\n")
    netrc.chmod(0o600)
    assert run_cli("init", s.url()).code == 0
    assert s.remote().exists("sub/file.txt")


def test_submodule_catchup_writes_sub_log(
    run_cli: RunCli, repo: Repo, ftp_server: FtpServer
) -> None:
    s = ftp_server
    sub = repo.add_submodule("sub", {"file.txt": "sub\n"})
    r = run_cli("catchup", *auth(s), s.url())
    assert r.code == 0, r
    assert "Catching up submodule sub." in r.stdout
    assert s.remote("site/sub").log() == sub.head()


def test_catchup_with_two_submodules(run_cli: RunCli, repo: Repo, ftp_server: FtpServer) -> None:
    s = ftp_server
    sub1 = repo.add_submodule("sub1", {"a.txt": "a\n"})
    sub2 = repo.add_submodule("sub2", {"b.txt": "b\n"}, at="nested/sub2")
    assert run_cli("catchup", *auth(s), s.url()).code == 0
    assert s.remote("site/sub1").log() == sub1.head()
    assert s.remote("site/nested/sub2").log() == sub2.head()


def test_submodule_under_syncroot(run_cli: RunCli, repo: Repo, ftp_server: FtpServer) -> None:
    s = ftp_server
    repo.write("dist/index.html", "i\n")
    repo.commit("dist")
    repo.add_submodule("sub", {"file.txt": "sub\n"}, at="dist/sub")
    assert run_cli("init", "--syncroot", "dist", *auth(s), s.url()).code == 0
    assert s.remote().read("sub/file.txt") == "sub\n"
    assert s.remote().exists("index.html")


def test_insecure_propagates_to_submodule(
    run_cli: RunCli, repo: Repo, ftpes_server: FtpServer
) -> None:
    s = ftpes_server
    repo.add_submodule("sub", {"file.txt": "sub\n"})
    r = run_cli("init", "-v", "--insecure", *auth(s), s.url())
    assert r.code == 0, r
    assert r.stderr.count("Insecure is '1'.") == 2
    assert s.remote().exists("sub/file.txt")
