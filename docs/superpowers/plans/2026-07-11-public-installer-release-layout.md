# Public Installer And Release Layout Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Produce a clean V0.1.15 repository with Ubuntu/Debian one-command installation, management commands, and automatic GitHub Release packaging.

**Architecture:** Shell scripts install and manage a release ZIP under `/opt/slowlink_assistant_bot` while preserving `.env` and `data`. GitHub Actions packages tagged commits into Release assets; the Git repository stores source and changelog rather than historical binary folders.

**Tech Stack:** Bash, Docker Compose, systemd, Python `unittest`, GitHub Actions, GitHub Releases, PowerShell/Git for Windows verification.

---

### Task 1: Define installer behavior with tests

**Files:**
- Create: `tests/test_distribution_scripts.py`
- Create: `install.sh`
- Create: `manage.sh`
- Create: `uninstall.sh`

- [ ] Write failing tests asserting both scripts exist, use `#!/bin/sh` and `set -eu`, keep all output/config prompts in Chinese, and target only `/opt/slowlink_assistant_bot` and `slowlink_assistant_bot`.
- [ ] Add assertions that `install.sh` supports `--version` and `--update`, reads interactive values from `/dev/tty`, uses `umask 077` plus `chmod 600`, downloads `SHA256SUMS.txt`, verifies SHA-256, preserves `.env` and `data`, installs Docker only when `docker compose` is unavailable, installs the watchdog, and waits for health.
- [ ] Add assertions that `manage.sh` exposes `status`, `logs`, `restart`, `update`, `backup`, `uninstall`, and `purge`, and delegates removal to `uninstall.sh`.
- [ ] Add assertions that standalone `uninstall.sh` preserves data by default and requires the literal confirmation `PURGE` for `--purge`.
- [ ] Run `python -m unittest tests.test_distribution_scripts -v` and verify RED because the scripts do not exist.
- [ ] Implement `install.sh`, `manage.sh`, and `uninstall.sh` with the specified behavior.
- [ ] Run the focused tests and Git Bash syntax checks; expected result is green.

### Task 2: Add release automation

**Files:**
- Create: `.github/workflows/release.yml`
- Modify: `tests/test_distribution_scripts.py`

- [ ] Add failing tests asserting the workflow triggers on `v*` tags, grants `contents: write`, runs tests and compileall, packages app/full ZIPs, emits a version update log and `SHA256SUMS.txt`, and calls `gh release create` with `GH_TOKEN`.
- [ ] Run the focused test and verify RED.
- [ ] Implement the workflow using Ubuntu's `zip`, Python for extracting the matching `CHANGELOG.md` section, and GitHub CLI for Release publication.
- [ ] Run the focused test and verify GREEN.

### Task 3: Clean repository history presentation

**Files:**
- Create: `CHANGELOG.md`
- Modify: `README.md`
- Modify: `docs/FEATURES.md`
- Modify: `docs/OPERATIONS.md`
- Modify: `docs/VERSION_ARCHIVE.md`
- Modify: `assistant_bot/__init__.py`
- Modify: `VERSION`
- Remove from current branch: `V0.1.0/` through `V0.1.14/`
- Remove from current branch: `slowlink_assistant_bot_deploy.zip`

- [ ] Copy all existing version directories to `D:\Users\szjhs\Documents\tg\slowlink_assistant_bot_releases` and verify file counts/hashes before removing them from the Git working tree.
- [ ] Build `CHANGELOG.md` with V0.1.15 first and concise entries for V0.1.14 through V0.1.0.
- [ ] Bump runtime version to `0.1.15` and update documentation for the one-line installer, management commands, GitHub Releases, private/public repository behavior, and the new clean layout.
- [ ] Remove root version directories and duplicate deploy ZIP from the current branch.
- [ ] Add a regression test asserting no `V0.1.*` directory or deploy ZIP remains at repository root.
- [ ] Run the focused and full tests.

### Task 4: Build and validate V0.1.15 assets

**Files:**
- External archive: `D:\Users\szjhs\Documents\tg\slowlink_assistant_bot_releases\V0.1.15\`

- [ ] Build app ZIP from `assistant_bot/` only.
- [ ] Build full ZIP from runtime files, `install.sh`, `manage.sh`, `CHANGELOG.md`, deployment files, and user documentation; exclude `.env`, `data`, tests, caches, `.git`, and local archives.
- [ ] Extract the V0.1.15 changelog section into `slowlink_assistant_bot_v0_1_15_update_log.txt`.
- [ ] Create `SHA256SUMS.txt` and verify every checksum.
- [ ] Extract the full ZIP to a temporary directory and run an import/version smoke test.

### Task 5: Commit, publish, and deploy

**Files:**
- Git branch: `main`
- Git tag: `v0.1.15`
- Server: `/opt/slowlink_assistant_bot`

- [ ] Run all tests, compileall, Bash syntax checks, secret scans, package-content checks, and `git diff --check`.
- [ ] Commit the installer/release-layout change, push `main`, create annotated tag `v0.1.15`, and push the tag.
- [ ] Wait for GitHub Actions and verify the V0.1.15 Release contains app/full/update-log/checksum assets.
- [ ] Upload the locally verified full ZIP to the server, preserve `.env` and `data`, and rebuild only `slowlink_assistant_bot`.
- [ ] Verify version `0.1.15`, healthy container, SQLite integrity, watchdog, current logs, code hashes, and that main SlowLink containers were not restarted.
