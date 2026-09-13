from __future__ import annotations

import os
import shutil
import signal
import subprocess
import sys
import time
from collections.abc import Callable
from pathlib import Path

import pytest

from gitftp.version import __version__
from tests.conftest import RunCli
from tests.helpers.ftpserver import FtpServer
from tests.helpers.gitrepo import Repo
from tests.integration.conftest import auth


def test_console_script_exists_and_prints_version() -> None:
    exe = shutil.which("git-ftp")
    assert exe, "git-ftp console script not installed in this environment"
    out = subprocess.run([exe, "--version"], capture_output=True, text=True, check=True).stdout
    assert out.strip() == f"git-ftp version {__version__}"


def test_git_subcommand_dispatch(run_bin: RunCli, repo: Repo) -> None:
    exe = shutil.which("git-ftp")
    assert exe
    env = dict(os.environ, PATH=str(Path(exe).parent) + os.pathsep + os.environ["PATH"])
    out = subprocess.run(
        ["git", "ftp", "--version"], capture_output=True, text=True, env=env, cwd=repo.path
    )
    assert out.returncode == 0
    assert "git-ftp version" in out.stdout


def test_exit_codes_and_stderr_separation(
    run_bin: RunCli, repo: Repo, ftp_server: FtpServer
) -> None:
    s = ftp_server
    r = run_bin("push", *auth(s), s.url(), cwd=repo.path)
    assert r.code == 5
    assert r.stdout == ""
    assert r.stderr.startswith("fatal: ")
    r = run_bin("push", "-n", *auth(s), s.url(), cwd=repo.path)
    assert r.code == 5 and r.stdout == "" and "fatal:" in r.stderr
    r = run_bin("init", *auth(s), s.url(), cwd=repo.path)
    assert r.code == 0 and r.stderr == ""
    assert "Uploading ..." in r.stdout
    r = run_bin("init", "-v", "-a", *auth(s), s.url("two"), cwd=repo.path)
    assert r.code == 0
    assert "Host is" in r.stderr  # -v diagnostics go to stderr


@pytest.mark.slow
@pytest.mark.skipif(sys.platform == "win32", reason="SIGINT")
def test_ctrl_c_stops_promptly_and_leaves_log_untouched(
    repo: Repo, ftp_server_factory: Callable[..., FtpServer], cli_bin: list[str]
) -> None:
    s = ftp_server_factory("plain", None, throttle=64 * 1024)
    assert (
        subprocess.run(
            [*cli_bin, "init", *auth(s), s.url()], cwd=repo.path, capture_output=True
        ).returncode
        == 0
    )
    first = repo.head()
    for i in range(12):
        repo.write(f"big/f{i}.bin", "x" * 512 * 1024)
    repo.commit("big")
    proc = subprocess.Popen(
        [*cli_bin, "push", "-j", "2", *auth(s), s.url()],
        cwd=repo.path,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    deadline = time.time() + 30
    while time.time() < deadline and not any(x.startswith("site/big/") for x in s.received):
        time.sleep(0.05)
    assert proc.poll() is None, "push finished before it could be interrupted"
    proc.send_signal(signal.SIGINT)
    try:
        _out, err = proc.communicate(timeout=10)
    except subprocess.TimeoutExpired:
        proc.kill()
        pytest.fail("process did not stop within 10s after SIGINT")
    assert proc.returncode == 130, err
    assert "Interrupted." in err
    assert s.remote().log() == first
    assert not list(repo.path.rglob("*.git-ftp-part"))
