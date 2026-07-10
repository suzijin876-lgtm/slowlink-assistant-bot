# Public Installer And Release Layout Design

## Goal

Prepare SlowLink Assistant Bot for future public use with a clean GitHub repository, reproducible Releases, and one-command installation on Ubuntu and Debian.

## Repository Layout

- Keep source code, tests, documentation, deployment files, `install.sh`, `manage.sh`, and `CHANGELOG.md` in the Git repository.
- Remove root-level `V0.1.x/` directories and `slowlink_assistant_bot_deploy.zip` from the current branch.
- Preserve every existing version directory in a sibling local archive outside the Git repository before removal.
- Consolidate historical update notes from V0.1.0 through V0.1.15 into `CHANGELOG.md` in descending version order.
- Store release ZIP files only as GitHub Release assets. Existing Git history retains the original snapshot if an old file must be recovered.

## Installer

- `install.sh` supports Ubuntu and Debian and must run as root.
- It installs required command-line packages and installs Docker Engine with the official Docker installer only when Docker Compose is unavailable.
- It queries the GitHub Releases API, downloads the latest stable full ZIP and `SHA256SUMS.txt`, and verifies the checksum before extraction.
- `--version X.Y.Z` installs a specific release; `--update` reuses existing configuration without prompting.
- Interactive installation reads secrets from `/dev/tty`, hides `BOT_TOKEN`, validates required IDs, and writes `.env` with mode `600`.
- Re-running installation preserves `.env`, `data/`, SQLite databases, and backups.
- It installs and enables the scoped CPU watchdog, builds/restarts only `slowlink_assistant_bot`, waits for Docker health, and prints Chinese diagnostics on failure.
- The public one-line command becomes usable after the GitHub repository is changed from private to public.

## Management Script

- `manage.sh status` shows version, Docker health, CPU/memory, and watchdog state.
- `manage.sh logs` follows Bot logs.
- `manage.sh restart` restarts only the Assistant Bot container.
- `manage.sh update` downloads and runs the current installer in update mode.
- `manage.sh backup` creates a timestamped SQLite backup.
- `manage.sh uninstall` stops the Bot and watchdog but preserves files and data.
- `manage.sh purge` requires an explicit typed confirmation before deleting the install directory.
- `uninstall.sh` provides a standalone one-line uninstall; normal mode preserves configuration and data, while `--purge` requires the same explicit confirmation.

## GitHub Releases

- Add `.github/workflows/release.yml`, triggered by `v*` tags.
- The workflow runs the Python test suite and syntax compilation before packaging.
- It creates app/full ZIPs including all install/manage/uninstall scripts, a version-specific update log extracted from `CHANGELOG.md`, and `SHA256SUMS.txt`.
- It publishes those files to the matching GitHub Release using the repository `GITHUB_TOKEN`.
- V0.1.15 is the first release generated from the clean layout.

## Version And Deployment

- Bump the project to `0.1.15` because public installation and release automation are user-visible distribution features.
- Create local V0.1.15 release assets in the external archive as a recovery copy.
- Commit the clean layout to `main`, push it, create and push tag `v0.1.15`, and verify the GitHub Actions release.
- Deploy V0.1.15 to `/opt/slowlink_assistant_bot`, preserving `.env` and `data`, and do not restart main SlowLink.

## Safety And Testing

- Never package or commit `.env`, Bot tokens, server credentials, live databases, caches, or logs.
- Add regression tests for script structure, supported commands, secret handling, data preservation, release packaging, and the absence of version directories in the repository root.
- Run `bash -n` with Git for Windows Bash, all Python tests, compileall, package-content checks, Git status checks, and production health verification.
