import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class DistributionScriptTests(unittest.TestCase):
    def read_required(self, relative_path: str) -> str:
        path = ROOT / relative_path
        self.assertTrue(path.is_file(), f"missing {relative_path}")
        return path.read_text(encoding="utf-8")

    def test_install_script_has_safe_public_install_contract(self):
        text = self.read_required("install.sh")

        self.assertTrue(text.startswith("#!/bin/sh\nset -eu\n"))
        for fragment in (
            'REPO="suzijin876-lgtm/slowlink-assistant-bot"',
            '/opt/slowlink_assistant_bot',
            '--version',
            '--update',
            '/dev/tty',
            'umask 077',
            'chmod 600',
            'SHA256SUMS.txt',
            'sha256sum -c',
            'application/octet-stream',
            'get.docker.com',
            'docker compose version',
            'slowlink-assistant-watchdog.service',
            'find "$INSTALL_DIR/assistant_bot" -type f -exec touch {} +',
            'docker compose build --no-cache assistant_bot',
            'docker compose up -d --no-deps assistant_bot',
            'slowlink_assistant_bot',
            '安装',
        ):
            self.assertIn(fragment, text)
        self.assertIn('.env', text)
        self.assertIn('data', text)
        self.assertIn("| .url", text)
        self.assertNotIn("browser_download_url", text)
        self.assertIn("trap cleanup 0", text)
        self.assertIn("trap 'exit 130' INT", text)
        self.assertIn("trap 'exit 143' TERM", text)
        self.assertNotIn("trap cleanup EXIT", text)
        self.assertIn('[ "$OWNER_USER_ID_VALUE" -gt 0 ]', text)
        self.assertIn('is_chat_ref "$REPORT_CHAT_ID_VALUE"', text)
        self.assertIn('[ -z "$REPORT_CHANNEL_ID_VALUE" ] || is_chat_ref "$REPORT_CHANNEL_ID_VALUE"', text)
        self.assertIn('validate_source_refs "$SOURCE_CHANNEL_IDS_VALUE"', text)

        package_guard = text.index("安装包包含不应覆盖的配置、数据或Git目录")
        deploy_copy = text.index('cp -a "$STAGE"/. "$INSTALL_DIR"/')
        refresh_build_inputs = text.index('find "$INSTALL_DIR/assistant_bot" -type f -exec touch {} +')
        no_cache_build = text.index('docker compose build --no-cache assistant_bot')
        self.assertLess(package_guard, deploy_copy)
        self.assertLess(deploy_copy, refresh_build_inputs)
        self.assertLess(refresh_build_inputs, no_cache_build)
        self.assertGreaterEqual(text.count('| .url'), 2)
        self.assertIn('-H "Accept: $accept"', text)
        self.assertGreaterEqual(text.count('"application/octet-stream"'), 2)
        self.assertNotIn('.browser_download_url', text)

    def test_install_script_explains_each_visible_input(self):
        text = self.read_required("install.sh")

        for fragment in (
            "[1/6]机器人Token",
            "从@BotFather获取",
            "输入内容会显示",
            "[2/6]主人用户ID",
            "你自己的Telegram数字ID",
            "[3/6]报表群ID",
            "接收日报、周报和月报",
            "[4/6]简报频道ID",
            "直接回车则不向频道发送简报",
            "[5/6]源频道ID",
            "多个用英文逗号分隔",
            "[6/6]SlowLink面板地址",
            "直接回车则不显示跳转按钮",
        ):
            self.assertIn(fragment, text)
        self.assertNotIn("stty -echo", text)
        self.assertNotIn("secret=", text)

    def test_install_chat_ref_validation_rejects_positive_group_ids(self):
        text = self.read_required("install.sh")
        helpers = text.split("\nusage() {", 1)[0]
        script = helpers + """
is_chat_ref "-1001234567890" || exit 10
is_chat_ref "@valid_name" || exit 11
if is_chat_ref "1"; then exit 12; fi
validate_source_refs "-1001234567890,@valid_name" || exit 13
if validate_source_refs "-1001234567890,1"; then exit 14; fi
"""

        shell = shutil.which("dash") or shutil.which("sh")
        if shell is None and os.name == "nt":
            candidate = Path(os.environ.get("ProgramFiles", r"C:\Program Files")) / "Git" / "usr" / "bin" / "dash.exe"
            if candidate.is_file():
                shell = str(candidate)
        self.assertIsNotNone(shell, "dash or sh is required for installer validation tests")

        env = os.environ.copy()
        env["PATH"] = str(Path(shell).resolve().parent) + os.pathsep + env.get("PATH", "")
        result = subprocess.run([shell], input=script.encode("utf-8"), capture_output=True, env=env, check=False)

        output = (result.stderr or result.stdout).decode("utf-8", errors="replace")
        self.assertEqual(result.returncode, 0, output)

    def test_install_script_offers_unified_management_menu(self):
        text = self.read_required("install.sh")

        for fragment in (
            "SlowLink Assistant Bot 管理",
            "1.安装",
            "2.更新到最新版本",
            "3.卸载",
            "4.修改配置",
            "0.退出",
            "卸载方式",
            "1.卸载程序，保留配置和数据库",
            "2.彻底删除程序、配置和数据库",
            "0.返回上一级",
            'IFS= read -r choice < /dev/tty',
            'sh "$INSTALL_DIR/uninstall.sh"',
            'sh "$INSTALL_DIR/uninstall.sh" --purge',
            "SHOW_MENU=1",
            "UPDATE_ONLY=1",
            "CONFIGURE_ONLY=1",
        ):
            self.assertIn(fragment, text)
        for option in ("--version", "--update", "--help"):
            self.assertIn(option, text)
        self.assertIn("尚未检测到安装，请先选择1安装", text)
        self.assertIn("请输入0、1、2、3或4", text)
        self.assertEqual(text.count("printf '请选择：' > /dev/tty"), 2)

    def test_config_editor_is_atomic_scoped_and_rolls_back_on_unhealthy_container(self):
        text = self.read_required("install.sh")

        for fragment in (
            "configure_existing",
            "机器人Token（已配置，直接回车保留",
            "SlowLink面板地址（可选）",
            "write_updated_env",
            'install -m 600 "$NEW_ENV" "$INSTALL_DIR/.env.next"',
            'mv -f "$INSTALL_DIR/.env.next" "$INSTALL_DIR/.env"',
            "docker compose up -d --no-deps --force-recreate assistant_bot",
            'install -m 600 "$OLD_ENV" "$INSTALL_DIR/.env.rollback"',
            "新配置启动失败，已恢复旧配置",
        ):
            self.assertIn(fragment, text)

        configure = text.split("configure_existing() {", 1)[1].split("\n}\n", 1)[0]
        self.assertNotIn("docker compose down", configure)
        self.assertNotIn("slowlink_app", configure)
        self.assertNotIn("slowlink_redis", configure)

    def test_config_editor_replaces_only_managed_values(self):
        text = self.read_required("install.sh")
        helpers = text.split("\nusage() {", 1)[0]
        script = helpers + r'''
BOT_TOKEN_VALUE="222:new_token"
OWNER_USER_ID_VALUE="222"
REPORT_CHAT_ID_VALUE="-100222"
REPORT_CHANNEL_ID_VALUE="-100444"
SOURCE_CHANNEL_IDS_VALUE="-100333,@new_source"
SLOWLINK_PANEL_URL_VALUE="https://new.example/"
write_updated_env "$INPUT_ENV" "$OUTPUT_ENV"
'''

        shell = shutil.which("dash") or shutil.which("sh")
        if shell is None and os.name == "nt":
            candidate = Path(os.environ.get("ProgramFiles", r"C:\Program Files")) / "Git" / "usr" / "bin" / "dash.exe"
            if candidate.is_file():
                shell = str(candidate)
        self.assertIsNotNone(shell, "dash or sh is required for config editor tests")

        with tempfile.TemporaryDirectory() as temp_dir:
            temp = Path(temp_dir)
            source = temp / "source.env"
            output = temp / "output.env"
            source.write_text(
                "BOT_TOKEN=111:old_token\n"
                "OWNER_USER_ID=111\n"
                "REPORT_CHAT_ID=-100111\n"
                "REPORT_CHANNEL_ID=-100111\n"
                "SOURCE_CHANNEL_IDS=-100111\n"
                "SLOWLINK_PANEL_URL=https://old.example/\n"
                "POLL_TIMEOUT=99\n"
                "CUSTOM_SETTING=keep_me\n",
                encoding="utf-8",
            )
            env = os.environ.copy()
            env["PATH"] = str(Path(shell).resolve().parent) + os.pathsep + env.get("PATH", "")
            env["INPUT_ENV"] = str(source)
            env["OUTPUT_ENV"] = str(output)
            result = subprocess.run([shell], input=script.encode("utf-8"), capture_output=True, env=env, check=False)

            message = (result.stderr or result.stdout).decode("utf-8", errors="replace")
            self.assertEqual(result.returncode, 0, message)
            values = output.read_text(encoding="utf-8").splitlines()

        self.assertEqual(
            values,
            [
                "BOT_TOKEN=222:new_token",
                "OWNER_USER_ID=222",
                "REPORT_CHAT_ID=-100222",
                "REPORT_CHANNEL_ID=-100444",
                "SOURCE_CHANNEL_IDS=-100333,@new_source",
                "SLOWLINK_PANEL_URL=https://new.example/",
                "POLL_TIMEOUT=99",
                "CUSTOM_SETTING=keep_me",
            ],
        )

    def test_manage_script_exposes_scoped_commands_and_delegates_uninstall(self):
        text = self.read_required("manage.sh")

        self.assertTrue(text.startswith("#!/bin/sh\nset -eu\n"))
        for command in ("status", "logs", "restart", "update", "backup", "uninstall", "purge"):
            self.assertIn(f"{command})", text)
        self.assertIn('slowlink_assistant_bot', text)
        self.assertIn('slowlink-assistant-watchdog.service', text)
        self.assertIn('docker compose restart assistant_bot', text)
        self.assertIn('"$INSTALL_DIR/uninstall.sh"', text)
        self.assertIn("trap 'rm -f \"$tmp\"' 0", text)

    def test_uninstall_script_supports_one_command_and_protected_purge(self):
        text = self.read_required("uninstall.sh")

        self.assertTrue(text.startswith("#!/bin/sh\nset -eu\n"))
        for fragment in (
            '/opt/slowlink_assistant_bot',
            'slowlink_assistant_bot',
            'slowlink-assistant-watchdog.service',
            '--purge',
            '/dev/tty',
            'PURGE',
            'docker compose stop assistant_bot',
            'docker compose rm -f assistant_bot',
            '保留',
        ):
            self.assertIn(fragment, text)
        confirmation = text.index('[ "$answer" = "PURGE" ]')
        fixed_path_guard = text.index('[ "$INSTALL_DIR" = "/opt/slowlink_assistant_bot" ]')
        service_stop = text.index('systemctl disable --now "$WATCHDOG_SERVICE"')
        permanent_delete = text.index('rm -rf -- "$INSTALL_DIR"')
        self.assertLess(confirmation, fixed_path_guard)
        self.assertLess(fixed_path_guard, service_stop)
        self.assertLess(service_stop, permanent_delete)

    def test_release_workflow_builds_verified_release_assets(self):
        text = self.read_required(".github/workflows/release.yml")

        for fragment in (
            'tags:',
            'v*',
            'contents: write',
            'python -m unittest discover -s tests',
            'python -m compileall -q assistant_bot scripts tests',
            'python scripts/build_release.py --version "$version" --output dist',
            'slowlink_assistant_bot_app_',
            'slowlink_assistant_bot_v',
            'SHA256SUMS.txt',
            'gh release create',
            'GH_TOKEN:',
            'uninstall.sh',
            '--notes-file "dist/slowlink_assistant_bot_v${file_version}_update_log.txt"',
        ):
            self.assertIn(fragment, text)
        self.assertIn(
            'bash -n install.sh manage.sh uninstall.sh ops/slowlink_assistant_watchdog.sh',
            text,
        )
        self.assertIn(
            'dash -n install.sh manage.sh uninstall.sh ops/slowlink_assistant_watchdog.sh',
            text,
        )
        self.assertNotIn('--generate-notes', text)

    def test_repository_root_has_no_version_archive_directories_or_deploy_zip(self):
        version_dirs = [path.name for path in ROOT.iterdir() if path.is_dir() and path.name.startswith("V0.1.")]

        self.assertEqual(version_dirs, [])
        self.assertFalse((ROOT / "slowlink_assistant_bot_deploy.zip").exists())


if __name__ == "__main__":
    unittest.main()
