# Changelog

All notable changes to this project are documented in this file. The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## [Unreleased]

First release: a native Python3 port of git-ftp 1.6.0. See [COMPATIBILITY.md](COMPATIBILITY.md) for what is unchanged, what was fixed and what is new.

### Added
- `--worktree` / `git-ftp.worktree`: deploy from a temporary Git worktree so edits to the working tree during an upload are ignored.
- Parallel uploads, deletes and downloads (`--jobs`, `git-ftp.jobs`).
- Native `download`, `pull` and `snapshot` without lftp.
- `unlock` action, `--password-command`, `--key-passphrase`, `--no-post-hooks`,
  `GIT_FTP_URL`/`GIT_FTP_USER`/`GIT_FTP_PASSWORD`.
- SFTP host key verification, ssh-agent support, encrypted keys.

### Fixed
- Every upstream bug listed in COMPATIBILITY.md.
