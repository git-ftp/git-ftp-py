from __future__ import annotations

from tests.conftest import RunCli
from tests.helpers.ftpserver import FtpServer
from tests.helpers.gitrepo import Repo
from tests.integration.conftest import auth


def setup(run_bin: RunCli, repo: Repo, s: FtpServer) -> None:
    assert run_bin("init", *auth(s), s.url(), cwd=repo.path).code == 0


def test_pull_commits_remote_changes(run_bin: RunCli, repo: Repo, ftp_server: FtpServer) -> None:
    s = ftp_server
    setup(run_bin, repo, s)
    s.remote().write("external.txt", "x\n")
    r = run_bin("pull", *auth(s), s.url(), cwd=repo.path)
    assert r.code == 0, r
    assert repo.read("external.txt") == "x\n"
    log = repo.git("log", "-1", "--pretty=%B").stdout
    assert "[git-ftp] remotely untracked modifications" in log
    assert "external.txt" in log
    assert s.remote().log() == repo.head()
    assert repo.status_sb().startswith("## master")


def test_pull_no_changes_exit_0(run_bin: RunCli, repo: Repo, ftp_server: FtpServer) -> None:
    s = ftp_server
    setup(run_bin, repo, s)
    head = repo.head()
    assert run_bin("pull", *auth(s), s.url(), cwd=repo.path).code == 0
    assert repo.head() == head


def test_pull_returns_to_branch(run_bin: RunCli, repo: Repo, ftp_server: FtpServer) -> None:
    s = ftp_server
    repo.checkout("deploy-branch", new=True)
    repo.write("branch-only.txt", "b\n")
    repo.commit("branch")
    setup(run_bin, repo, s)
    s.remote().write("external.txt", "x\n")
    assert run_bin("pull", *auth(s), s.url(), cwd=repo.path).code == 0
    assert repo.status_sb() == "## deploy-branch"
    assert repo.exists("branch-only.txt")
    assert repo.exists("external.txt")


def test_pull_no_commit_option(run_bin: RunCli, repo: Repo, ftp_server: FtpServer) -> None:
    s = ftp_server
    setup(run_bin, repo, s)
    head = repo.head()
    s.remote().write("external.txt", "x\n")
    r = run_bin("pull", "--no-commit", *auth(s), s.url(), cwd=repo.path)
    assert r.code == 0, r
    assert repo.exists("external.txt")
    assert repo.head() == head
    assert "Fast-forward" not in r.stdout


def test_pull_no_commit_config_bool(run_bin: RunCli, repo: Repo, ftp_server: FtpServer) -> None:
    s = ftp_server
    setup(run_bin, repo, s)
    head = repo.head()
    repo.config("git-ftp.no-commit", "true")
    s.remote().write("external.txt", "x\n")
    assert run_bin("pull", *auth(s), s.url(), cwd=repo.path).code == 0
    assert repo.head() == head
    repo.git("merge", "--abort", check=False)
    repo.git("reset", "-q", "--hard", head)
    repo.git("clean", "-fdq")
    repo.config("git-ftp.no-commit", "false")
    assert run_bin("catchup", *auth(s), s.url(), cwd=repo.path).code == 0
    s.remote().write("external2.txt", "y\n")
    assert run_bin("pull", *auth(s), s.url(), cwd=repo.path).code == 0
    assert repo.head() != head  # committed: "false" really means false


def test_pull_dry_run(run_bin: RunCli, repo: Repo, ftp_server: FtpServer) -> None:
    s = ftp_server
    setup(run_bin, repo, s)
    head = repo.head()
    s.remote().write("external.txt", "x\n")
    r = run_bin("pull", "--dry-run", *auth(s), s.url(), cwd=repo.path)
    assert r.code == 0, r
    assert not repo.exists("external.txt")
    assert "Last deployment changed" not in r.stdout
    assert repo.head() == head
    assert s.remote().log() == head


def test_pull_keeps_gitignored_file(run_bin: RunCli, repo: Repo, ftp_server: FtpServer) -> None:
    s = ftp_server
    repo.write(".gitignore", "local-only.txt\n")
    repo.commit("ignore")
    setup(run_bin, repo, s)
    repo.write("local-only.txt", "l\n")
    s.remote().write("external.txt", "x\n")
    assert run_bin("pull", *auth(s), s.url(), cwd=repo.path).code == 0
    assert repo.exists("local-only.txt")
    assert "local-only.txt" not in repo.git("log", "--pretty=%B").stdout


def test_pull_preserves_stash(run_bin: RunCli, repo: Repo, ftp_server: FtpServer) -> None:
    s = ftp_server
    setup(run_bin, repo, s)
    repo.write("internal.txt", "i\n")
    repo.git("stash", "push", "-u", "-q")
    s.remote().write("external.txt", "x\n")
    assert run_bin("pull", *auth(s), s.url(), cwd=repo.path).code == 0
    assert len(repo.git("stash", "list").stdout.splitlines()) == 1
    assert not repo.exists("internal.txt")


def test_pull_changed_only_merges(run_bin: RunCli, repo: Repo, ftp_server: FtpServer) -> None:
    s = ftp_server
    repo.write("both.txt", "line1\n")
    repo.write("local.txt", "l\n")
    repo.commit("base")
    setup(run_bin, repo, s)
    repo.write("both.txt", "line1\nline2 local\n")
    repo.write("local.txt", "l2\n")
    repo.commit("local edits")
    s.remote().write("both.txt", "line0 remote\nline1\n")
    s.remote().write("remote-only.txt", "r\n")
    s.remote().write("local.txt", "l\n")
    r = run_bin("pull", "--changed-only", *auth(s), s.url(), cwd=repo.path)
    assert r.code == 0, r
    assert not repo.exists("remote-only.txt")
    assert repo.read("both.txt").splitlines() == ["line0 remote", "line1", "line2 local"]
    assert repo.read("local.txt") == "l2\n"


def test_pull_without_log_exit_5(run_bin: RunCli, repo: Repo, ftp_server: FtpServer) -> None:
    r = run_bin("pull", *auth(ftp_server), ftp_server.url(), cwd=repo.path)
    assert r.code == 5
    assert "Could not get last commit" in r.stderr
