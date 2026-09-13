from __future__ import annotations

from tests.conftest import RunCli
from tests.helpers.ftpserver import FtpServer
from tests.helpers.gitrepo import Repo
from tests.integration.conftest import auth


def init_with_ignore(run_cli: RunCli, repo: Repo, s: FtpServer, ignore: str, *extra: str) -> None:
    repo.write(".git-ftp-ignore", ignore)
    r = run_cli("init", *extra, *auth(s), s.url())
    assert r.code == 0, r


def test_ignore_single_file(run_cli: RunCli, repo: Repo, ftp_server: FtpServer) -> None:
    init_with_ignore(run_cli, repo, ftp_server, "test 1.txt\n")
    assert not ftp_server.remote().exists("test 1.txt")
    assert ftp_server.remote().exists("test 2.txt")


def test_ignore_applies_with_force_unknown_commit(
    run_cli: RunCli, repo: Repo, ftp_server: FtpServer
) -> None:
    s = ftp_server
    init_with_ignore(run_cli, repo, s, "test 1.txt\n")
    s.remote().write(".git-ftp.log", "000000000\n")
    assert run_cli("push", "-f", *auth(s), s.url()).code == 0
    assert not s.remote().exists("test 1.txt")


def test_ignore_dir_glob(run_cli: RunCli, repo: Repo, ftp_server: FtpServer) -> None:
    init_with_ignore(run_cli, repo, ftp_server, "dir 1/*\n")
    assert not ftp_server.remote().exists("dir 1/test 1.txt")
    assert ftp_server.remote().exists("dir 2/test 2.txt")


def test_ignore_prefix_star(run_cli: RunCli, repo: Repo, ftp_server: FtpServer) -> None:
    init_with_ignore(run_cli, repo, ftp_server, "test*\n")
    for i in range(1, 6):
        assert not ftp_server.remote().exists(f"test {i}.txt")
    assert ftp_server.remote().exists("dir 1/test 1.txt")


def test_ignore_exact_name_only(run_cli: RunCli, repo: Repo, ftp_server: FtpServer) -> None:
    repo.write("test", "t\n")
    repo.commit("t")
    init_with_ignore(run_cli, repo, ftp_server, "test\n")
    assert not ftp_server.remote().exists("test")
    for i in range(1, 6):
        assert ftp_server.remote().exists(f"test {i}.txt")


def test_ignore_wildcard_with_space(run_cli: RunCli, repo: Repo, ftp_server: FtpServer) -> None:
    init_with_ignore(run_cli, repo, ftp_server, "test *.txt\n")
    for i in range(1, 6):
        assert not ftp_server.remote().exists(f"test {i}.txt")


def test_ignore_dotfiles_and_nested_gitkeep(
    run_cli: RunCli, repo: Repo, ftp_server: FtpServer
) -> None:
    repo.write(".gitignore", "x\n")
    repo.write("dir 1/.gitkeep", "")
    repo.commit("dotfiles")
    init_with_ignore(run_cli, repo, ftp_server, ".gitignore\n*/.gitkeep\n.git-ftp-ignore\n")
    remote = ftp_server.remote()
    assert not remote.exists(".gitignore")
    assert not remote.exists("dir 1/.gitkeep")
    assert not remote.exists(".git-ftp-ignore")
    assert remote.exists("test 1.txt")


def test_ignored_file_is_not_deleted_remotely(
    run_cli: RunCli, repo: Repo, ftp_server: FtpServer
) -> None:
    s = ftp_server
    assert run_cli("init", *auth(s), s.url()).code == 0
    repo.write(".git-ftp-ignore", "test 1.txt\n")
    repo.rm("test 1.txt")
    repo.commit("rm")
    assert run_cli("push", *auth(s), s.url()).code == 0
    assert s.remote().exists("test 1.txt")
