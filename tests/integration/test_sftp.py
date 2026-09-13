from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

import pytest

from tests.conftest import RunCli
from tests.helpers.gitrepo import Repo
from tests.helpers.sftpserver import SftpServer
from tests.integration.conftest import auth

pytestmark = pytest.mark.sftp


def test_no_known_hosts_file_refuses(run_cli: RunCli, repo: Repo, sftp_server: SftpServer) -> None:
    r = run_cli("init", *auth(sftp_server), sftp_server.url())
    assert r.code == 4, r
    assert "Host key verification failed" in r.stderr
    assert "ssh-keyscan" in r.stderr


def test_unknown_host_refused(
    run_cli: RunCli, repo: Repo, sftp_server_factory: Callable[..., SftpServer], home: Path
) -> None:
    a = sftp_server_factory()
    b = sftp_server_factory()
    (home / ".ssh").mkdir()
    line = b.known_hosts_line().replace(f"[{b.host}]:{b.port}", f"[{a.host}]:{a.port}")
    (home / ".ssh" / "known_hosts").write_text(line)
    r = run_cli("init", *auth(a), a.url())
    assert r.code == 4
    assert "does not match known_hosts" in r.stderr


def test_trusted_host_connects(
    run_cli: RunCli, repo: Repo, trusted_sftp_server: SftpServer
) -> None:
    s = trusted_sftp_server
    r = run_cli("init", *auth(s), s.url())
    assert r.code == 0, r
    assert s.remote().log() == repo.head()
    s.remote().assert_equals_local("dir 1/test 1.txt", repo)


def test_hashed_known_hosts_entry(
    run_cli: RunCli, repo: Repo, sftp_server: SftpServer, home: Path
) -> None:
    import paramiko

    s = sftp_server
    hk = paramiko.HostKeys()
    name = f"[{s.host}]:{s.port}"
    hk.add(paramiko.HostKeys.hash_host(name), s.host_key.get_name(), s.host_key)
    (home / ".ssh").mkdir()
    hk.save(str(home / ".ssh" / "known_hosts"))
    assert run_cli("init", *auth(s), s.url()).code == 0


def test_insecure_skips_verification(run_cli: RunCli, repo: Repo, sftp_server: SftpServer) -> None:
    s = sftp_server
    assert run_cli("init", "--insecure", *auth(s), s.url()).code == 0
    repo.config("git-ftp.insecure", "true")
    repo.write("x", "x")
    repo.commit("x")
    assert run_cli("push", *auth(s), s.url()).code == 0
    assert s.remote().exists("x")


def test_bad_password_exit_4(run_cli: RunCli, repo: Repo, trusted_sftp_server: SftpServer) -> None:
    s = trusted_sftp_server
    r = run_cli("init", "-u", s.USER, "-p", "wrong", s.url())
    assert r.code == 4
    assert "Failed to log in" in r.stderr


def test_key_auth_with_pub_sibling(
    run_cli: RunCli, repo: Repo, trusted_sftp_server: SftpServer
) -> None:
    s = trusted_sftp_server
    r = run_cli("init", "-u", s.USER, "--key", str(s.client_key_path), s.url())
    assert r.code == 0, r
    assert s.remote().log() == repo.head()


def test_key_auth_from_config(run_cli: RunCli, repo: Repo, trusted_sftp_server: SftpServer) -> None:
    s = trusted_sftp_server
    repo.config("git-ftp.key", str(s.client_key_path))
    repo.config("git-ftp.user", s.USER)
    assert run_cli("init", s.url()).code == 0


def test_encrypted_key_with_passphrase(
    run_cli: RunCli, repo: Repo, trusted_sftp_server: SftpServer
) -> None:
    s = trusted_sftp_server
    r = run_cli("init", "-u", s.USER, "--key", str(s.encrypted_client_key_path), s.url(), input="")
    assert r.code == 3
    assert "encrypted" in r.stderr
    r = run_cli(
        "init",
        "-u",
        s.USER,
        "--key",
        str(s.encrypted_client_key_path),
        "--key-passphrase",
        s.KEY_PASSPHRASE,
        s.url(),
    )
    assert r.code == 0, r
    repo.config("git-ftp.key-passphrase", s.KEY_PASSPHRASE)
    repo.write("y", "y")
    repo.commit("y")
    assert (
        run_cli("push", "-u", s.USER, "--key", str(s.encrypted_client_key_path), s.url()).code == 0
    )


def test_no_credentials_exit_3(
    run_cli: RunCli, repo: Repo, trusted_sftp_server: SftpServer
) -> None:
    s = trusted_sftp_server
    r = run_cli("init", "-u", s.USER, s.url())
    assert r.code == 3
    assert "No SFTP credentials" in r.stderr


def test_rsa_host_key(
    run_cli: RunCli, repo: Repo, sftp_server_factory: Callable[..., SftpServer], home: Path
) -> None:
    s = sftp_server_factory("rsa")
    (home / ".ssh").mkdir()
    (home / ".ssh" / "known_hosts").write_text(s.known_hosts_line())
    assert run_cli("init", *auth(s), s.url()).code == 0


def test_round_trip_push_delete_odd_names(
    run_cli: RunCli, repo: Repo, trusted_sftp_server: SftpServer
) -> None:
    s = trusted_sftp_server
    names = ["#hash file.txt", "umlaut_ä.md", "deep/er/x.txt"]
    for n in names:
        repo.write(n, n + "\n")
    repo.commit("odd")
    assert run_cli("init", *auth(s), s.url()).code == 0
    for n in names:
        s.remote().assert_equals_local(n, repo)
    repo.rm(*names)
    repo.commit("rm")
    assert run_cli("push", *auth(s), s.url()).code == 0
    for n in names:
        assert not s.remote().exists(n)
    assert s.remote().log() == repo.head()


@pytest.mark.slow
def test_parallel_jobs_4(run_cli: RunCli, repo: Repo, trusted_sftp_server: SftpServer) -> None:
    s = trusted_sftp_server
    names = [f"bulk/d{i % 5}/f{i:03}.txt" for i in range(50)]
    for n in names:
        repo.write(n, "x" * 2000 + "\n")
    repo.commit("bulk")
    r = run_cli("init", "-j", "4", *auth(s), s.url())
    assert r.code == 0, r
    for n in names:
        s.remote().assert_equals_local(n, repo)
    assert s.received[-1] == "site/.git-ftp.log"


def test_fail_fast_sftp(run_cli: RunCli, repo: Repo, trusted_sftp_server: SftpServer) -> None:
    s = trusted_sftp_server
    assert run_cli("init", *auth(s), s.url()).code == 0
    first = repo.head()
    for i in range(20):
        repo.write(f"bulk/f{i:03}.txt", "x\n")
    repo.commit("bulk")
    s.deny_upload("site/bulk/f010.txt")
    r = run_cli("push", "-j", "4", *auth(s), s.url())
    assert r.code == 4
    assert s.remote().log() == first


def test_download_and_pull_over_sftp(
    run_bin: RunCli, repo: Repo, trusted_sftp_server: SftpServer
) -> None:
    s = trusted_sftp_server
    assert run_bin("init", *auth(s), s.url(), cwd=repo.path).code == 0
    s.remote().write("external.txt", "x\n")
    s.remote().write("deep/er/y.txt", "y\n")
    s.remote().delete("test 1.txt")
    r = run_bin("download", *auth(s), s.url(), cwd=repo.path)
    assert r.code == 0, r
    assert repo.read("external.txt") == "x\n"
    assert repo.read("deep/er/y.txt") == "y\n"
    assert not repo.exists("test 1.txt")
    repo.git("checkout", "-q", "--", ".")
    repo.git("clean", "-fdq")
    r = run_bin("pull", *auth(s), s.url(), cwd=repo.path)
    assert r.code == 0, r
    assert repo.exists("external.txt")


def test_absolute_remote_path(run_cli: RunCli, repo: Repo, trusted_sftp_server: SftpServer) -> None:
    s = trusted_sftp_server
    url = f"sftp://{s.host}:{s.port}//abs/site"
    r = run_cli("init", *auth(s), url)
    assert r.code == 0, r
    assert s.remote("abs/site").log() == repo.head()


def test_netrc_fallback_sftp(
    run_cli: RunCli, repo: Repo, trusted_sftp_server: SftpServer, home: Path
) -> None:
    s = trusted_sftp_server
    (home / ".netrc").write_text(f"machine {s.host} login {s.USER} password {s.PASSWORD}\n")
    (home / ".netrc").chmod(0o600)
    assert run_cli("init", s.url()).code == 0
