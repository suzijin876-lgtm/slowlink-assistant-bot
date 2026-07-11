# Unified Management Menu Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Release V0.1.17 with one interactive command for installation, latest-version update, safe uninstall, and exit.

**Architecture:** Add a `/dev/tty` main menu and uninstall submenu to `install.sh`. Menu selections set the existing install/update state or delegate to the installed `uninstall.sh`; command-line flags and the underlying scripts remain unchanged for automation.

**Tech Stack:** POSIX shell, Python `unittest`, Docker Compose, GitHub Actions, GitHub Releases.

---

### Task 1: Define the menu contract with a failing test

**Files:**
- Modify: `tests/test_distribution_scripts.py`
- Modify: `install.sh`

- [ ] **Step 1: Add a failing distribution test**

Add `test_install_script_offers_unified_management_menu` and assert these exact behaviors:

```python
for fragment in (
    "SlowLink Assistant Bot 管理",
    "1.安装",
    "2.更新到最新版本",
    "3.卸载",
    "0.退出",
    "卸载方式",
    "1.卸载程序，保留配置和数据库",
    "2.彻底删除程序、配置和数据库",
    "0.返回上一级",
    'IFS= read -r choice < /dev/tty',
    'sh "$INSTALL_DIR/uninstall.sh"',
    'sh "$INSTALL_DIR/uninstall.sh" --purge',
):
    self.assertIn(fragment, text)
```

Also assert that `--version`, `--update`, and `--help` remain present.

- [ ] **Step 2: Run the focused test and verify RED**

```powershell
python -m unittest tests.test_distribution_scripts.DistributionScriptTests.test_install_script_offers_unified_management_menu -v
```

Expected: FAIL because no interactive management menu exists.

- [ ] **Step 3: Implement the main menu and uninstall submenu**

Track whether no arguments were supplied:

```sh
SHOW_MENU=0
[ "$#" -eq 0 ] && SHOW_MENU=1
```

Implement `uninstall_menu` as a loop that reads `choice` from `/dev/tty`, delegates option 1 to the default installed uninstaller, option 2 to `--purge`, and returns on 0.

Implement `main_menu` as a loop:

```sh
case "$choice" in
  1) return ;;
  2)
    [ -f "$INSTALL_DIR/.env" ] || {
      printf '[提示]尚未检测到安装，请先选择1安装。\n' > /dev/tty
      continue
    }
    UPDATE_ONLY=1
    return
    ;;
  3) uninstall_menu ;;
  0) printf '已退出。\n' > /dev/tty; exit 0 ;;
  *) printf '[输入错误]请输入0、1、2或3。\n' > /dev/tty ;;
esac
```

After argument parsing and the root check, call `main_menu` only when `SHOW_MENU=1`. Explicit `--update` must also reject a missing `.env` with the same install-first guidance.

- [ ] **Step 4: Run focused tests and shell syntax checks**

```powershell
python -m unittest tests.test_distribution_scripts -v
& 'C:\Program Files\Git\usr\bin\dash.exe' -n install.sh
& 'C:\Program Files\Git\bin\bash.exe' -n install.sh
```

Expected: PASS.

### Task 2: Update version and user documentation

**Files:**
- Modify: `VERSION`
- Modify: `assistant_bot/__init__.py`
- Modify: `CHANGELOG.md`
- Modify: `README.md`
- Modify: `docs/FEATURES.md`
- Modify: `docs/OPERATIONS.md`
- Modify: `docs/VERSION_ARCHIVE.md`

- [ ] **Step 1: Set version 0.1.17**

Update both runtime version files and the installer usage example.

- [ ] **Step 2: Make the unified command primary**

README and operations documentation show one public command followed by the main and uninstall menus. Move `--version`, `--update`, standalone uninstall, and purge examples into a short advanced/automation section instead of presenting them as separate normal workflows.

- [ ] **Step 3: Add the V0.1.17 changelog**

Document the main menu, nested uninstall choices, retained `PURGE` protection, `/dev/tty` compatibility with piped execution, and preserved command-line flags.

### Task 3: Verify, publish, and deploy

**Files:**
- External archive: `D:\Users\szjhs\Documents\tg\slowlink_assistant_bot_releases\V0.1.17\`
- Server: `/opt/slowlink_assistant_bot`

- [ ] **Step 1: Run all checks**

```powershell
python -m unittest discover -s tests
python -m compileall -q assistant_bot tests
& 'C:\Program Files\Git\usr\bin\dash.exe' -n install.sh manage.sh uninstall.sh ops/slowlink_assistant_watchdog.sh
git diff --check
```

- [ ] **Step 2: Build four V0.1.17 assets**

Create app/full ZIPs, update log, and `SHA256SUMS.txt`. Independently extract the full ZIP, verify version `0.1.17`, forward-slash ZIP entries, shell syntax, and absence of `.env`, `data`, tests, caches, Git files, logs, and local archives.

- [ ] **Step 3: Publish**

Commit and push `main`, create annotated tag `v0.1.17`, wait for GitHub Actions, then verify all four online Release assets and their checksums.

- [ ] **Step 4: Deploy only Assistant Bot**

Preserve `.env` and `data`, rebuild/recreate only `slowlink_assistant_bot`, and restart only its watchdog. Verify version, health, SQLite integrity, logs, code hashes, and unchanged main SlowLink container start times.

- [ ] **Step 5: Exercise the production menu safely**

Open a real PTY and send `3`, `0`, `0`. Verify the uninstall submenu opens, returns to the main menu, and exits without stopping the Bot. Also run `0` directly and verify no package installation or service change occurs.
