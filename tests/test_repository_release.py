import hashlib
import importlib.util
import subprocess
import tempfile
import unittest
import zipfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class RepositoryReleaseTests(unittest.TestCase):
    def read_required(self, relative_path: str) -> str:
        path = ROOT / relative_path
        self.assertTrue(path.is_file(), f"missing {relative_path}")
        return path.read_text(encoding="utf-8")

    def test_readme_is_concise_and_matches_repository_presentation(self):
        text = self.read_required("README.md")

        self.assertTrue(text.startswith('<div align="center">\n'))
        for fragment in (
            "# SlowLink Assistant Bot",
            "Telegram 频道消息复制、私聊通知与定时报表 Bot",
            "github/v/release/suzijin876-lgtm/slowlink-assistant-bot",
            "github/actions/workflow/status/suzijin876-lgtm/slowlink-assistant-bot/release.yml",
            "Python-3.11",
            "Docker-Compose",
            "github/license/suzijin876-lgtm/slowlink-assistant-bot",
            "curl -fsSL https://raw.githubusercontent.com/suzijin876-lgtm/slowlink-assistant-bot/main/install.sh | sudo bash",
            "## 主要功能",
            "## 工作流程",
            "```mermaid",
            "## 日常管理",
            "| 命令 | 用途 |",
            "频道消息复制",
            "主人私聊",
            "日报、周报和月报",
        ):
            self.assertIn(fragment, text)

        self.assertLess(text.index("## 快速安装"), text.index("## 主要功能"))
        self.assertLess(len(text), 7000)

    def test_repository_has_mit_license_and_ignores_private_runtime_data(self):
        license_text = self.read_required("LICENSE")
        ignore_text = self.read_required(".gitignore")

        self.assertIn("MIT License", license_text)
        self.assertIn("Copyright (c) 2026 suzijin876-lgtm", license_text)
        for fragment in (
            ".env.*",
            "!.env.example",
            "data/",
            "*.session",
            "*.sqlite3",
            "*.log",
            "backups/",
            "dist/",
            "V0.1.*/",
            "*.zip",
            "docs/superpowers/",
        ):
            self.assertIn(fragment, ignore_text)

    def test_release_workflow_uses_builder_and_publishes_only_three_assets(self):
        text = self.read_required(".github/workflows/release.yml")

        for fragment in (
            'tags:',
            'v*',
            'python -m compileall -q assistant_bot scripts tests',
            'python -m unittest discover -s tests',
            'bash -n install.sh manage.sh uninstall.sh ops/slowlink_assistant_watchdog.sh',
            'dash -n install.sh manage.sh uninstall.sh ops/slowlink_assistant_watchdog.sh',
            'python scripts/build_release.py --version "$version" --output dist',
            'sha256sum -c SHA256SUMS.txt',
            '--notes-file "dist/slowlink_assistant_bot_v${file_version}_update_log.txt"',
        ):
            self.assertIn(fragment, text)

        self.assertNotIn("--generate-notes", text)
        publish_assets = text.split("gh release create", 1)[1].split("--verify-tag", 1)[0]
        self.assertIn('"dist/slowlink_assistant_bot_app_v${file_version}.zip"', publish_assets)
        self.assertIn('"dist/slowlink_assistant_bot_v${file_version}_full.zip"', publish_assets)
        self.assertIn("dist/SHA256SUMS.txt", publish_assets)
        self.assertNotIn("update_log.txt", publish_assets)

    def test_release_builder_creates_four_local_files_and_two_zip_checksums(self):
        builder_path = ROOT / "scripts" / "build_release.py"
        self.assertTrue(builder_path.is_file(), "missing scripts/build_release.py")

        spec = importlib.util.spec_from_file_location("assistant_build_release", builder_path)
        self.assertIsNotNone(spec)
        self.assertIsNotNone(spec.loader)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)

        version = "0.1.18"
        expected_names = (
            "slowlink_assistant_bot_app_v0_1_18.zip",
            "slowlink_assistant_bot_v0_1_18_full.zip",
            "slowlink_assistant_bot_v0_1_18_update_log.txt",
            "SHA256SUMS.txt",
        )
        self.assertEqual(module.expected_asset_names(version), expected_names)
        self.assertIn("## [0.1.18]", module.extract_changelog(version))

        with tempfile.TemporaryDirectory() as temp_dir:
            output_dir = Path(temp_dir)
            assets = module.build(version, output_dir)
            self.assertEqual(tuple(path.name for path in assets), expected_names)
            self.assertEqual({path.name for path in output_dir.iterdir()}, set(expected_names))

            app_zip, full_zip, update_log, checksum_file = assets
            with zipfile.ZipFile(app_zip) as archive:
                app_members = archive.namelist()
            with zipfile.ZipFile(full_zip) as archive:
                full_members = archive.namelist()

            self.assertTrue(app_members)
            self.assertTrue(all(name == "LICENSE" or name.startswith("assistant_bot/") for name in app_members))
            for required in (
                "LICENSE",
                "VERSION",
                "Dockerfile",
                "docker-compose.yml",
                "install.sh",
                "manage.sh",
                "uninstall.sh",
                "scripts/build_release.py",
            ):
                self.assertIn(required, full_members)

            forbidden_parts = (
                "/.env",
                "/data/",
                "/sessions/",
                "/.git/",
                "/backups/",
                "/backup/",
                "/__pycache__/",
                "/docs/superpowers/",
            )
            for member in app_members + full_members:
                normalized = f"/{member.lower()}"
                self.assertNotEqual(normalized, "/.env", member)
                self.assertFalse(any(part in normalized for part in forbidden_parts[1:]), member)
                self.assertFalse(
                    normalized.endswith((".session", ".sqlite", ".sqlite3", ".db", ".rdb", ".log")),
                    member,
                )

            self.assertIn("## [0.1.18]", update_log.read_text(encoding="utf-8"))
            checksum_lines = checksum_file.read_text(encoding="utf-8").splitlines()
            self.assertEqual(len(checksum_lines), 2)
            self.assertEqual(
                {line.split("  ", 1)[1] for line in checksum_lines},
                {app_zip.name, full_zip.name},
            )
            for line in checksum_lines:
                digest, name = line.split("  ", 1)
                self.assertEqual(hashlib.sha256((output_dir / name).read_bytes()).hexdigest(), digest)

    def test_public_repository_has_no_internal_plans_or_runtime_artifacts(self):
        self.assertFalse((ROOT / "docs" / "superpowers").exists())

        tracked = set(
            subprocess.check_output(["git", "ls-files"], cwd=ROOT, text=True).splitlines()
        )
        for relative_path in (".env", "watchdog.log"):
            self.assertNotIn(relative_path, tracked)
        self.assertFalse(any(path == "data" or path.startswith("data/") for path in tracked))

        version_dirs = [path.name for path in ROOT.iterdir() if path.is_dir() and path.name.startswith("V0.1.")]
        root_archives = [path.name for path in ROOT.iterdir() if path.is_file() and path.suffix.lower() == ".zip"]
        self.assertEqual(version_dirs, [])
        self.assertEqual(root_archives, [])


if __name__ == "__main__":
    unittest.main()
