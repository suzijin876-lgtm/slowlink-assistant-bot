import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class WatchdogRuntimeTests(unittest.TestCase):
    def shell_tools(self):
        shell = shutil.which("dash") or shutil.which("sh")
        cygpath = None
        if os.name == "nt":
            git_usr_bin = Path(os.environ.get("ProgramFiles", r"C:\Program Files")) / "Git" / "usr" / "bin"
            if shell is None:
                candidate = git_usr_bin / "dash.exe"
                if candidate.is_file():
                    shell = str(candidate)
            candidate = git_usr_bin / "cygpath.exe"
            if candidate.is_file():
                cygpath = str(candidate)
        self.assertIsNotNone(shell, "dash or sh is required for watchdog runtime tests")
        return str(shell), cygpath

    def shell_path(self, path: Path, cygpath: str | None) -> str:
        if cygpath is None:
            return str(path)
        result = subprocess.run(
            [cygpath, "-u", str(path)],
            capture_output=True,
            text=True,
            check=True,
        )
        return result.stdout.strip()

    def test_stale_heartbeat_restarts_only_configured_bot_container(self):
        shell, cygpath = self.shell_tools()
        with tempfile.TemporaryDirectory() as tmp:
            temp = Path(tmp)
            fake_bin = temp / "bin"
            fake_bin.mkdir()
            restart_log = temp / "restarts.txt"
            fake_docker = fake_bin / "docker"
            fake_docker.write_text(
                "#!/bin/sh\n"
                "case \"$1\" in\n"
                "  stats) printf '0.00%%\\n' ;;\n"
                "  restart) printf '%s\\n' \"$2\" >> \"$WATCHDOG_TEST_RESTARTS\" ;;\n"
                "  logs) : ;;\n"
                "esac\n",
                encoding="utf-8",
            )
            fake_docker.chmod(0o755)

            fake_bin_path = self.shell_path(fake_bin, cygpath)
            script_path = self.shell_path(ROOT / "ops" / "slowlink_assistant_watchdog.sh", cygpath)
            env = os.environ.copy()
            env.update(
                {
                    "PATH": f"{fake_bin_path}:/usr/bin:/bin",
                    "APP_CONTAINER": "test_assistant_bot",
                    "CHECK_INTERVAL": "1",
                    "CPU_THRESHOLD": "85",
                    "HIGH_COUNT_LIMIT": "4",
                    "COOLDOWN_SECONDS": "600",
                    "LOG_FILE": self.shell_path(temp / "watchdog.log", cygpath),
                    "ENV_FILE": self.shell_path(temp / "missing.env", cygpath),
                    "STATUS_FILE": self.shell_path(temp / "watchdog_status.txt", cygpath),
                    "HEARTBEAT_FILE": self.shell_path(temp / "missing_heartbeat", cygpath),
                    "HEARTBEAT_MAX_AGE": "1",
                    "STALE_COUNT_LIMIT": "2",
                    "WATCHDOG_MAX_CHECKS": "2",
                    "WATCHDOG_TEST_RESTARTS": self.shell_path(restart_log, cygpath),
                }
            )

            result = subprocess.run(
                [shell, script_path],
                capture_output=True,
                text=True,
                env=env,
                timeout=10,
                check=False,
            )

            self.assertEqual(result.returncode, 0, result.stderr or result.stdout)
            self.assertEqual(restart_log.read_text(encoding="utf-8").splitlines(), ["test_assistant_bot"])
            watchdog_log = (temp / "watchdog.log").read_text(encoding="utf-8")
            self.assertIn("Bot心跳异常", watchdog_log)
            self.assertIn("容器重启完成：test_assistant_bot", watchdog_log)
            self.assertNotIn("slowlink_app", watchdog_log)


if __name__ == "__main__":
    unittest.main()
