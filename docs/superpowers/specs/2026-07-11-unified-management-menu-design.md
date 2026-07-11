# Unified Management Menu Design

## Goal

Replace the scattered public install, update, and uninstall commands with one interactive entry point while preserving safe command-line flags for automation.

## Main Menu

Running `install.sh` without arguments, including through the public `curl | sudo bash` command, opens this menu and reads choices from `/dev/tty`:

```text
SlowLink Assistant Bot 管理
1.安装
2.更新到最新版本
3.卸载
0.退出
请选择：
```

- `1` continues through the existing installation flow and four-step configuration wizard.
- `2` requires an existing `/opt/slowlink_assistant_bot/.env`, preserves `.env` and `data`, then downloads and deploys the latest stable GitHub Release.
- `3` opens the uninstall submenu.
- `0` exits without installing packages or changing services.
- Invalid values show a short Chinese error and redisplay the same menu.

## Uninstall Submenu

```text
卸载方式
1.卸载程序，保留配置和数据库
2.彻底删除程序、配置和数据库
0.返回上一级
请选择：
```

- Option `1` delegates to the installed `uninstall.sh` default mode.
- Option `2` delegates to `uninstall.sh --purge`; the existing literal `PURGE` confirmation remains mandatory before any service is stopped or data is deleted.
- Option `0` returns to the main menu.
- If the installed uninstall script is missing, the menu reports that the Bot is not installed and returns without changing the system.

## Compatibility

The current `--version`, `--update`, and `--help` flags remain available and bypass the menu. `manage.sh` and standalone `uninstall.sh` remain in the package for automation and recovery, but normal documentation promotes the single interactive command.

All menu input uses `/dev/tty`, because stdin belongs to the download pipe when the script is run as `curl ... | sudo bash`.

## Safety

- The menu itself performs no destructive filesystem operation.
- Update refuses to act when no existing `.env` is present and tells the user to select installation instead.
- Default uninstall preserves configuration and SQLite data.
- Permanent removal keeps both the submenu choice and the existing typed `PURGE` confirmation.
- Only `slowlink_assistant_bot` and its watchdog are managed; main SlowLink containers remain untouched.

## Version And Tests

Release as `0.1.17`. Add regression tests for the exact menu entries, `/dev/tty` input, update-state assignment, uninstall delegation, submenu return, and preservation of existing CLI flags. Run all Python and shell checks, publish the GitHub Release, and deploy only the Assistant Bot.
