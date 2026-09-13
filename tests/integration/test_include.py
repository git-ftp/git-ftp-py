from __future__ import annotations

from tests.conftest import RunCli
from tests.helpers.ftpserver import FtpServer
from tests.helpers.gitrepo import Repo
from tests.integration.conftest import auth


def test_include_target_source_on_init(run_cli: RunCli, repo: Repo, ftp_server: FtpServer) -> None:
    s = ftp_server
    repo.write("unversioned.txt", "u\n")
    repo.write(".gitignore", "unversioned.txt\n")
    repo.write(".git-ftp-include", "unversioned.txt:test 1.txt\n")
    repo.commit("include")
    assert run_cli("init", *auth(s), s.url()).code == 0
    s.remote().assert_equals_local("unversioned.txt", repo)


def test_include_directory_with_trailing_slash(
    run_cli: RunCli, repo: Repo, ftp_server: FtpServer
) -> None:
    s = ftp_server
    repo.write("unversioned/a.txt", "a\n")
    repo.write("unversioned/deep/b.txt", "b\n")
    repo.write("unversioned-not-included/c.txt", "c\n")
    repo.write(".gitignore", "unversioned*\n")
    repo.write(".git-ftp-include", "unversioned/:test 1.txt\n")
    repo.commit("include")
    assert run_cli("init", *auth(s), s.url()).code == 0
    assert s.remote().exists("unversioned/a.txt")
    assert s.remote().exists("unversioned/deep/b.txt")
    assert not s.remote().exists("unversioned-not-included/c.txt")


def test_include_bang_directory(run_cli: RunCli, repo: Repo, ftp_server: FtpServer) -> None:
    s = ftp_server
    repo.write("unversioned/a.txt", "a\n")
    repo.write(".gitignore", "unversioned\n")
    repo.write(".git-ftp-include", "!unversioned/\n")
    repo.commit("include")
    assert run_cli("init", *auth(s), s.url()).code == 0
    assert s.remote().exists("unversioned/a.txt")


def test_include_missing_source_not_uploaded(
    run_cli: RunCli, repo: Repo, ftp_server: FtpServer
) -> None:
    s = ftp_server
    repo.write("unversioned.txt", "u\n")
    repo.write(".gitignore", "unversioned.txt\n")
    repo.write(".git-ftp-include", "unversioned.txt:test X.txt\n")
    repo.commit("include")
    assert run_cli("init", *auth(s), s.url()).code == 0
    assert not s.remote().exists("unversioned.txt")


def test_include_on_push_when_source_changed(
    run_cli: RunCli, repo: Repo, ftp_server: FtpServer
) -> None:
    s = ftp_server
    assert run_cli("init", *auth(s), s.url()).code == 0
    repo.write("unversioned.txt", "u\n")
    repo.write(".gitignore", "unversioned.txt\n")
    repo.write(".git-ftp-include", "unversioned.txt:test 1.txt\n")
    repo.commit("include")
    assert run_cli("push", *auth(s), s.url()).code == 0
    assert not s.remote().exists("unversioned.txt")
    repo.write("test 1.txt", "changed\n")
    repo.commit("trigger")
    assert run_cli("push", *auth(s), s.url()).code == 0
    s.remote().assert_equals_local("unversioned.txt", repo)


def test_include_target_deleted_when_local_gone(
    run_cli: RunCli, repo: Repo, ftp_server: FtpServer
) -> None:
    s = ftp_server
    repo.write("unversioned.txt", "u\n")
    repo.write(".gitignore", "unversioned.txt\n")
    repo.write(".git-ftp-include", "unversioned.txt:test 1.txt\nunversioned.txt:test 2.txt\n")
    repo.commit("include")
    assert run_cli("init", *auth(s), s.url()).code == 0
    assert s.remote().exists("unversioned.txt")
    repo.rm("test 1.txt")
    repo.commit("rm trigger")
    assert run_cli("push", *auth(s), s.url()).code == 0
    assert s.remote().exists("unversioned.txt")
    (repo.path / "unversioned.txt").unlink()
    repo.write("test 2.txt", "changed\n")
    repo.commit("change other trigger")
    r = run_cli("push", *auth(s), s.url())
    assert r.code == 0, r
    assert not s.remote().exists("unversioned.txt")


def test_include_then_gitignore_init(run_cli: RunCli, repo: Repo, ftp_server: FtpServer) -> None:
    s = ftp_server
    repo.write(".htaccess.prod", "prod\n")
    repo.write(".gitignore", ".htaccess.prod\n")
    repo.write(".git-ftp-include", ".htaccess:.htaccess.prod\n")
    repo.write(".htaccess", "dev\n")
    repo.commit("include")
    assert run_cli("init", *auth(s), s.url()).code == 0
    assert s.remote().exists(".htaccess")
    assert not s.remote().exists(".htaccess.prod")


def test_bang_include_with_empty_commit(run_cli: RunCli, repo: Repo, ftp_server: FtpServer) -> None:
    s = ftp_server
    assert run_cli("init", *auth(s), s.url()).code == 0
    repo.write("untracked.txt", "u\n")
    repo.write(".gitignore", "untracked.txt\n")
    repo.write(".git-ftp-include", "!untracked.txt\n")
    repo.commit("include")
    assert run_cli("push", *auth(s), s.url()).code == 0
    repo.git("commit", "-q", "--allow-empty", "-m", "empty")
    assert run_cli("push", *auth(s), s.url()).code == 0
    assert s.remote().exists("untracked.txt")


def test_ftp_ignore_beats_include(run_cli: RunCli, repo: Repo, ftp_server: FtpServer) -> None:
    s = ftp_server
    repo.write(".htaccess.prod", "prod\n")
    repo.write(".gitignore", ".htaccess.prod\n")
    repo.write(".git-ftp-ignore", ".htaccess.prod\n")
    repo.write(".git-ftp-include", ".htaccess.prod:test 1.txt\n!.htaccess.prod\n")
    repo.commit("include")
    assert run_cli("init", *auth(s), s.url()).code == 0
    assert not s.remote().exists(".htaccess.prod")
    repo.write("test 1.txt", "x\n")
    repo.commit("x")
    assert run_cli("push", *auth(s), s.url()).code == 0
    assert not s.remote().exists(".htaccess.prod")


def test_bang_include_under_syncroot(run_cli: RunCli, repo: Repo, ftp_server: FtpServer) -> None:
    s = ftp_server
    repo.write("public_html/index.html", "i\n")
    repo.write("public_html/always.html", "a\n")
    repo.write(".gitignore", "always.html\n")
    repo.write(".git-ftp-include", "!public_html/always.html\n")
    repo.commit("syncroot")
    assert run_cli("init", "--syncroot", "public_html", *auth(s), s.url()).code == 0
    assert s.remote().exists("always.html")
    assert s.remote().exists("index.html")
    assert not s.remote().exists("public_html/always.html")


def test_include_source_relative_to_syncroot(
    run_cli: RunCli, repo: Repo, ftp_server: FtpServer
) -> None:
    s = ftp_server
    repo.write("public_html/style.sass", "sass\n")
    repo.write("public_html/style.css", "css\n")
    repo.write(".gitignore", "style.css\n")
    repo.write(".git-ftp-include", "public_html/style.css:style.sass\n")
    repo.commit("syncroot")
    assert run_cli("init", "--syncroot", "public_html", *auth(s), s.url()).code == 0
    assert s.remote().exists("style.css")


def test_include_similar_names_issue_41(run_cli: RunCli, repo: Repo, ftp_server: FtpServer) -> None:
    s = ftp_server
    repo.write("templates/foo.html", "t\n")
    repo.write("foo.html", "f\n")
    repo.write(".gitignore", "/foo.html\n")
    repo.write(".git-ftp-include", "foo.html:templates/foo.html\n")
    repo.commit("similar")
    assert run_cli("init", *auth(s), s.url()).code == 0
    assert s.remote().exists("foo.html")
    assert s.remote().exists("templates/foo.html")


def test_include_absolute_source_with_syncroot_issue_245(
    run_cli: RunCli, repo: Repo, ftp_server: FtpServer
) -> None:
    s = ftp_server
    repo.write("src/main.scss", "m\n")
    repo.write("src/other.scss", "o\n")
    repo.write("src/three.scss", "3\n")
    repo.write("dist/main.css", "m\n")
    repo.write("dist/other.css", "o\n")
    repo.write("dist/three.css", "3\n")
    repo.write(".gitignore", "dist/\n")
    repo.write(".git-ftp-include", "dist/main.css:/src/main.scss\n")
    repo.commit("one")
    assert run_cli("init", "--syncroot", "dist", *auth(s), s.url()).code == 0
    assert s.remote().listdir() == [".git-ftp.log", "main.css"]
    repo.write(
        ".git-ftp-include",
        "dist/main.css:/src/main.scss\ndist/other.css:/src/other.scss\ndist/three.css:/src/three.scss\n",
    )
    repo.commit("two")
    assert run_cli("push", "--syncroot", "dist", *auth(s), s.url()).code == 0
    assert s.remote().listdir() == [".git-ftp.log", "main.css"]
    repo.write("src/other.scss", "changed\n")
    repo.commit("three")
    assert run_cli("push", "--syncroot", "dist", *auth(s), s.url()).code == 0
    assert s.remote().listdir() == [".git-ftp.log", "main.css", "other.css"]
