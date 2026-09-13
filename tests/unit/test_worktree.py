from __future__ import annotations

from pathlib import Path

from gitftp.gitrepo import GitRepo
from tests.helpers.gitrepo import make_repo


def test_temporary_worktree_holds_committed_content_and_cleans_up(
    home: Path, tmp_path: Path
) -> None:
    r = make_repo(tmp_path / "p")
    r.write("test 1.txt", "committed\n")
    r.commit("change")
    # Make the live tree differ from HEAD to prove the worktree is a clean snapshot.
    r.write("test 1.txt", "dirty local edit\n")
    g = GitRepo.discover(r.path)

    with g.temporary_worktree(g.head_sha()) as tree:
        assert tree.is_dir()
        assert (tree / "test 1.txt").read_text() == "committed\n"
        assert "git-ftp-worktree-" in str(tree)
        listing = g.run("worktree", "list").stdout.decode()
        assert len(listing.strip().splitlines()) == 2

    assert not tree.exists()
    assert not tree.parent.exists()
    listing = g.run("worktree", "list").stdout.decode()
    assert len(listing.strip().splitlines()) == 1
