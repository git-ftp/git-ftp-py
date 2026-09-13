from __future__ import annotations

from pathlib import Path

import pytest

from gitftp import changeset
from gitftp.gitrepo import GitRepo, UnknownCommit
from gitftp.output import Level, Output
from tests.helpers.gitrepo import Repo, make_repo


@pytest.fixture
def grepo(home: Path, tmp_path: Path) -> tuple[Repo, GitRepo]:
    r = make_repo(tmp_path / "p")
    return r, GitRepo.discover(r.path)


def test_all_files(grepo: tuple[Repo, GitRepo]) -> None:
    _r, g = grepo
    cs = changeset.build(g, "", None, True, Output(Level.SILENT))
    assert len(cs.uploads) == 10 and cs.deletes == []
    assert cs.uploads[0] == "dir 1/test 1.txt"
    assert cs.hook_status().startswith(b"A dir 1/test 1.txt\0")


def test_diff_uploads_and_deletes(grepo: tuple[Repo, GitRepo]) -> None:
    r, g = grepo
    base = r.head()
    r.write("new.txt", "n")
    r.write("test 1.txt", "changed")
    r.rm("test 2.txt")
    r.commit("c")
    cs = changeset.build(g, "", base, False, Output(Level.SILENT))
    assert cs.uploads == ["new.txt", "test 1.txt"]
    assert cs.deletes == ["test 2.txt"]
    assert cs.hook_status() == b"A new.txt\0A test 1.txt\0D test 2.txt\0"


def test_unknown_commit(grepo: tuple[Repo, GitRepo]) -> None:
    _, g = grepo
    with pytest.raises(UnknownCommit):
        changeset.build(g, "", "0000000", False, Output(Level.SILENT))


def test_syncroot_and_remote_path(grepo: tuple[Repo, GitRepo]) -> None:
    _r, g = grepo
    cs = changeset.build(g, "dir 1/", None, True, Output(Level.SILENT))
    assert cs.uploads == ["dir 1/test 1.txt"]
    assert changeset.remote_path("dir 1/test 1.txt", "dir 1/") == "test 1.txt"
    assert changeset.remote_path("other/x", "dir 1/") == "other/x"


def test_include_then_ignore(grepo: tuple[Repo, GitRepo]) -> None:
    r, g = grepo
    r.write("untracked.txt", "u")
    r.write("gone-dep.txt", "")
    r.write(".git-ftp-include", "!untracked.txt\nmissing.txt:test 1.txt\nvetoed.txt:test 1.txt\n")
    r.write(".git-ftp-ignore", "vetoed.txt\ntest 5.txt\n")
    r.write("vetoed.txt", "v")
    cs = changeset.build(g, "", None, True, Output(Level.SILENT))
    assert "untracked.txt" in cs.uploads
    assert "vetoed.txt" not in cs.uploads
    assert "test 5.txt" not in cs.uploads
    assert cs.deletes == ["missing.txt"]


def test_submodules_marked_and_uninitialised_skipped(grepo: tuple[Repo, GitRepo]) -> None:
    r, g = grepo
    r.add_submodule("sub", {"file.txt": "s\n"})
    cs = changeset.build(g, "", None, True, Output(Level.SILENT))
    assert "sub" in cs.uploads and "sub" in cs.submodules
    # a clone without `submodule update` has an uninitialised gitlink
    clone = Repo(r.path.parent / "clone")
    r.git("clone", "-q", str(r.path), str(clone.path), cwd=r.path.parent)
    g2 = GitRepo.discover(clone.path)
    cs2 = changeset.build(g2, "", None, True, Output(Level.SILENT))
    assert "sub" not in cs2.uploads
    assert cs2.submodules == set()
