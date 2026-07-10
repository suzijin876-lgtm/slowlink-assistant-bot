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
        self.assertIn('validate_source_refs "$SOURCE_CHANNEL_IDS_VALUE"', text)

        package_guard = text.index("安装包包含不应覆盖的配置、数据或Git目录")
        deploy_copy = text.index('cp -a "$STAGE"/. "$INSTALL_DIR"/')
        self.assertLess(package_guard, deploy_copy)
        self.assertGreaterEqual(text.count('| .url'), 2)
        self.assertIn('-H "Accept: $accept"', text)
        self.assertGreaterEqual(text.count('"application/octet-stream"'), 2)
        self.assertNotIn('.browser_download_url', text)

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
            'python -m compileall -q assistant_bot tests',
            'slowlink_assistant_bot_app_',
            'slowlink_assistant_bot_v',
            'SHA256SUMS.txt',
            'gh release create',
            'GH_TOKEN:',
            'uninstall.sh',
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

    def test_repository_root_has_no_version_archive_directories_or_deploy_zip(self):
        version_dirs = [path.name for path in ROOT.iterdir() if path.is_dir() and path.name.startswith("V0.1.")]

        self.assertEqual(version_dirs, [])
        self.assertFalse((ROOT / "slowlink_assistant_bot_deploy.zip").exists())


if __name__ == "__main__":
    unittest.main()
