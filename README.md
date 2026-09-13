# git-ftp (Python)

[![test](https://github.com/git-ftp/git-ftp-py/actions/workflows/test.yml/badge.svg)](https://github.com/git-ftp/git-ftp-py/actions/workflows/test.yml)
[![PyPI](https://img.shields.io/pypi/v/git-ftp.svg)](https://pypi.org/project/git-ftp/)
[![Python versions](https://img.shields.io/pypi/pyversions/git-ftp.svg)](https://pypi.org/project/git-ftp/)
[![License](https://img.shields.io/pypi/l/git-ftp.svg)](https://www.gnu.org/licenses/gpl-3.0)

This is a native Python port of the Bash [git-ftp](https://github.com/git-ftp/git-ftp): deploy a
Git repository to a server over **FTP, FTPS, FTPES or SFTP**, uploading only the
files that changed since the last deployment.

git-ftp records the deployed commit in a file on the remote (`.git-ftp.log`).
On the next push it diffs that commit against `HEAD` and transfers exactly the
files that were added, modified or deleted, in parallel. No server-side
software is needed.

If your server forbids writing dot-files (some hardened FTP servers reject any
name starting with a `.`), set a non-dot-file name with
`git config git-ftp.deployedsha1file gitftp.log`.

This port reads the same configuration and the same remote files as the Bash
original, so an existing deployment carries over unchanged. It needs Python 3.10
or newer and `git`; libcurl comes bundled with the `pycurl` wheel and SFTP is
spoken by `paramiko`. See [COMPATIBILITY.md](COMPATIBILITY.md) for what was
kept, fixed and added.

## Install

```sh
pip install git-ftp # or: pipx install git-ftp, uv tool install git-ftp
git ftp --version
```

Git runs the `git-ftp` script as `git ftp` when it is on your `PATH`.

## Usage

```sh
# First deployment: upload everything and record the commit.
git ftp init -u alice -P ftp://example.com/public_html

# Every deployment after that: only what changed.
git ftp push -u alice -P ftp://example.com/public_html

# The remote already has the current files? Just record the commit.
git ftp catchup ftp://example.com/public_html

# What is deployed?
git ftp show
git ftp log
```

`-P` prompts for the password. Better than typing it every time:

```sh
git config git-ftp.url ftp://example.com/public_html
git config git-ftp.user alice
git config git-ftp.password s3cret                    # or:
git config git-ftp.password-command "pass show example.com/ftp"
git ftp push
```

In CI, `GIT_FTP_URL`, `GIT_FTP_USER` and `GIT_FTP_PASSWORD` do the same without
touching any file.

### Scopes

Several targets in one repository:

```sh
git ftp add-scope production ftp://alice:s3cret@live.example.com/htdocs
git ftp add-scope staging   ftp://alice:s3cret@staging.example.com/htdocs
git ftp push -s production
git ftp push -s             # bare -s: the current branch name is the scope
```

Scope keys (`git-ftp.<scope>.<key>`) override the plain keys; an explicit empty
scope value masks the default.

### Protocols

| URL | Transport | Encryption |
|---|---|---|
| `ftp://host/path` | libcurl | none |
| `ftpes://host/path` | libcurl | explicit TLS (`AUTH TLS`), data channel too |
| `ftps://host/path` | libcurl | implicit TLS (port 990) |
| `sftp://host/path` | paramiko | SSH |

TLS certificates are verified; use `--cacert FILE` for a private CA or
`--insecure` to skip verification. SFTP host keys are checked against
`~/.ssh/known_hosts` (`ssh-keyscan host >> ~/.ssh/known_hosts` to add one).
SFTP authenticates with `--key FILE` (`--key-passphrase` for encrypted keys),
a running `ssh-agent`, or a password. `sftp://host/~/dir` and
`sftp://host//absolute/dir` work as in curl.

### Choosing what to deploy

- `--syncroot DIR` deploys only `DIR`, with `DIR` as the remote root.
- `.git-ftp-ignore` lists shell globs of Git paths never to upload (`*` also
  matches `/`, and a pattern must match the whole path).
- `.git-ftp-include` uploads untracked files: `!VERSION.txt` always, or
  `css/style.css:scss/style.scss` whenever the tracked source changed. A
  directory target (`vendor/:composer.lock`) uploads everything below it.
- `--dry-run` shows the plan; `-a` uploads everything; `-c SHA` diffs against
  a specific commit; `-b BRANCH` deploys another branch.

### Parallel transfers

Files are transferred over up to four connections. `--jobs N` or
`git config git-ftp.jobs N` changes that; `--jobs 1` is sequential. Uploads
happen first, then deletes, and the commit log is written last, only when every
upload succeeded, so an interrupted deploy never claims a commit it did not
finish. Ctrl-C stops promptly.

In an interactive terminal a spinner shows a `done/total` count with the current
file on stderr. It is off when output is piped, in CI, or under `-n`, so scripts
see the plain lines unchanged.

### Consistent uploads while editing

`--worktree`, or `git config git-ftp.worktree true`, reads the files to upload
from a throwaway Git worktree checked out at the commit being deployed. Editing
the working tree while a long upload runs then cannot change what is sent. The
worktree is removed when the deploy finishes.

### Hooks and locking

`.git/hooks/pre-ftp-push` (veto with a non-zero exit; skipped by `--no-verify`)
and `post-ftp-push` (`--enable-post-errors` makes its failure fatal) receive
`<scope-or-host> <url> <local-commit> <deployed-commit>`; the pre hook also gets
the NUL-separated `A path` / `D path` change list on stdin.

`--lock` writes `git-ftp.lck` on the remote for the duration of the deploy;
another deploy of a different commit is refused with exit 7. `git ftp unlock`
removes a stale lock.

### download, pull, snapshot

These mirror the remote into the working tree:

```sh
git ftp download   # remote -> working tree (refuses to run with untracked files)
git ftp pull       # download into a commit on the deployed revision, then merge
git ftp snapshot ftp://example.com/htdocs [dir]   # new repository from a remote
```

`--changed-only` limits `pull` to files that changed locally as well;
`--no-commit` (or `git-ftp.no-commit`) leaves the merge uncommitted.

### Exit codes

| Code | Meaning |
|---|---|
| 0 | success |
| 1 | unexpected error |
| 2 | wrong usage |
| 3 | missing argument |
| 4 | error while uploading (also: remote unreachable, login failed) |
| 5 | error while downloading (also: `push` before `init`) |
| 6 | unknown protocol |
| 7 | remote locked |
| 8 | git error (not a repository, dirty working tree, bad branch) |
| 9 | hook failed |
| 10 | local filesystem error |
| 130 | interrupted |

### Shell completion

```sh
eval "$(_GIT_FTP_COMPLETE=bash_source git-ftp)"   # zsh: zsh_source, fish: fish_source
```

## Development

```sh
uv sync --all-groups
make lint typecheck test          # ruff, mypy, pytest (in-process FTP/FTPS/SFTP servers)
make test-docker                  # pure-ftpd containers, Linux only
```

The manual page source is `docs/git-ftp.1.md` (`make man` renders it with
pandoc).

## Releasing

The version is derived from the Git tag by `hatch-vcs`; there is no version
string to edit. Pushing a `v*` tag runs `.github/workflows/publish.yml`, which
builds the sdist and wheel and publishes them to PyPI via Trusted Publishing (no
API token), then creates a GitHub release whose notes are the matching
`CHANGELOG.md` section.

One-time setup: on PyPI (and TestPyPI) add a Trusted Publisher for this
repository with workflow `publish.yml` and environment `pypi` (`testpypi`), and
create those two environments in the GitHub repository settings.

To cut a release:

```sh
# 1. Move the entries under "## [Unreleased]" into a new "## [X.Y.Z]" section
#    in CHANGELOG.md, then commit.
$EDITOR CHANGELOG.md
git add CHANGELOG.md
git commit -m "Release X.Y.Z"

# 2. Tag and push. The tag must be v<version>; the workflow checks that it
#    matches the version hatch-vcs computes.
git tag -a -m "Release X.Y.Z" vX.Y.Z
git push origin main vX.Y.Z
```

Between tags, builds report a development version such as `X.Y.Z.devN+g<hash>`.
To rehearse against TestPyPI without tagging, run the `publish` workflow manually
(`workflow_dispatch`) with the TestPyPI option enabled.

## License

GPL-3.0-or-later
