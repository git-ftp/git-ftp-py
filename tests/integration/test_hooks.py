from __future__ import annotations

import sys

import pytest

from tests.conftest import RunCli
from tests.helpers.ftpserver import FtpServer
from tests.helpers.gitrepo import Repo
from tests.integration.conftest import auth

pytestmark = pytest.mark.skipif(sys.platform == "win32", reason="hooks are sh scripts")


def test_pre_push_output_stdin_format_veto_and_no_verify(
    run_bin: RunCli, repo: Repo, ftp_server: FtpServer
) -> None:
    s = ftp_server
    repo.rm("test 2.txt")
    repo.commit("rm")
    repo.hook(
        "pre-ftp-push",
        'echo "pre hook"\ntr "\\0" "\\n" > "$(git rev-parse --show-toplevel)/../hookin.txt"\n',
    )
    r = run_bin("init", *auth(s), s.url(), cwd=repo.path)
    assert r.code == 0, r
    assert r.stdout.splitlines()[0] == "pre hook"
    lines = (repo.path.parent / "hookin.txt").read_text().splitlines()
    assert lines[0] == "A dir 1/test 1.txt"
    assert "D test 2.txt" not in lines  # init uploads everything, deletes nothing
    repo.write("test 3.txt", "x\n")
    repo.git("rm", "-q", "--", "test 4.txt")
    repo.commit("push")
    repo.hook("pre-ftp-push", 'tr "\\0" "\\n" > "$(git rev-parse --show-toplevel)/../hookin.txt"\n')
    assert run_bin("push", *auth(s), s.url(), cwd=repo.path).code == 0
    lines = (repo.path.parent / "hookin.txt").read_text().splitlines()
    assert lines == ["A test 3.txt", "D test 4.txt"]
    repo.write("test 5.txt", "y\n")
    repo.commit("veto")
    repo.hook("pre-ftp-push", "exit 1\n")
    r = run_bin("push", *auth(s), s.url(), cwd=repo.path)
    assert r.code == 9
    assert r.stdout == ""
    assert s.remote().read("test 5.txt") == "5\n"
    r = run_bin("push", "--no-verify", *auth(s), s.url(), cwd=repo.path)
    assert r.code == 0, r
    assert s.remote().read("test 5.txt") == "y\n"


def test_post_push_runs_after_init(run_bin: RunCli, repo: Repo, ftp_server: FtpServer) -> None:
    s = ftp_server
    repo.hook("post-ftp-push", 'echo "post hook"\n')
    r = run_bin("init", "-n", *auth(s), s.url(), cwd=repo.path)
    assert r.code == 0
    assert r.stdout.strip() == "post hook"


def test_post_push_args(run_bin: RunCli, repo: Repo, ftp_server: FtpServer) -> None:
    s = ftp_server
    repo.hook(
        "post-ftp-push",
        'printf "%s|%s|%s|%s" "$1" "$2" "$3" "$4" '
        '> "$(git rev-parse --show-toplevel)/../hookargs.txt"\n',
    )
    assert run_bin("init", *auth(s), s.url(), cwd=repo.path).code == 0
    first = repo.head()
    args = (repo.path.parent / "hookargs.txt").read_text().split("|")
    assert args == [s.hostport, f"ftp://{s.USER}:***@{s.hostport}/site/", first, ""]
    repo.write("x.txt", "x\n")
    repo.commit("x")
    assert run_bin("push", "-s", "myscope", *auth(s), s.url(), cwd=repo.path).code == 0
    args = (repo.path.parent / "hookargs.txt").read_text().split("|")
    assert args == ["myscope", f"ftp://{s.USER}:***@{s.hostport}/site/", repo.head(), first]


def test_post_push_failure_ignored_by_default(
    run_bin: RunCli, repo: Repo, ftp_server: FtpServer
) -> None:
    s = ftp_server
    repo.hook("post-ftp-push", "exit 99\n")
    assert run_bin("init", *auth(s), s.url(), cwd=repo.path).code == 0


def test_post_push_failure_exit_9_with_enable_post_errors(
    run_bin: RunCli, repo: Repo, ftp_server: FtpServer
) -> None:
    s = ftp_server
    repo.hook("post-ftp-push", "exit 99\n")
    r = run_bin("init", "--enable-post-errors", *auth(s), s.url(), cwd=repo.path)
    assert r.code == 9
    assert s.remote().log() == repo.head()  # the deploy itself completed


def test_no_post_hooks(run_bin: RunCli, repo: Repo, ftp_server: FtpServer) -> None:
    s = ftp_server
    repo.hook("post-ftp-push", 'echo "post hook"\n')
    r = run_bin("init", "--no-post-hooks", *auth(s), s.url(), cwd=repo.path)
    assert r.code == 0
    assert "post hook" not in r.stdout


def test_core_hookspath(run_bin: RunCli, repo: Repo, ftp_server: FtpServer) -> None:
    s = ftp_server
    hooks = repo.path.parent / "hooks"
    hooks.mkdir()
    (hooks / "post-ftp-push").write_text("#!/bin/sh\necho custom-path\n")
    (hooks / "post-ftp-push").chmod(0o755)
    repo.config("core.hooksPath", str(hooks))
    r = run_bin("init", "-n", *auth(s), s.url(), cwd=repo.path)
    assert r.stdout.strip() == "custom-path"
