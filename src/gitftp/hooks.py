"""pre-ftp-push and post-ftp-push hooks (upstream's experimental interface)."""

from __future__ import annotations

import os
import subprocess
from collections.abc import Sequence

from gitftp.gitrepo import GitRepo
from gitftp.output import Output

PRE_PUSH = "pre-ftp-push"
POST_PUSH = "post-ftp-push"


def run_hook(
    repo: GitRepo, name: str, args: Sequence[str], stdin: bytes, out: Output
) -> int | None:
    """Run ``<hooks dir>/<name>`` if it exists and is executable; None when absent."""
    path = repo.hooks_dir() / name
    if not path.is_file() or not os.access(path, os.X_OK):
        return None
    out.debug(f"Running hook {name}.")
    proc = subprocess.run(
        [str(path), *args],
        cwd=repo.root,
        input=stdin,
        check=False,
    )
    return proc.returncode
