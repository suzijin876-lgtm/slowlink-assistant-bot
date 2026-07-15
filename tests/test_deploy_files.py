import unittest
from pathlib import Path


class DeployFileTests(unittest.TestCase):
    def test_docker_compose_has_healthcheck(self):
        text = Path("docker-compose.yml").read_text(encoding="utf-8")

        self.assertIn("healthcheck:", text)
        self.assertIn("heartbeat_is_fresh", text)
        self.assertIn('max-size: "10m"', text)
        self.assertIn('max-file: "3"', text)

    def test_example_configuration_documents_optional_report_channel(self):
        text = Path(".env.example").read_text(encoding="utf-8")

        self.assertIn("REPORT_CHANNEL_ID=", text)
        self.assertIn("optional", text.lower())

    def test_dockerignore_keeps_build_context_small(self):
        text = Path(".dockerignore").read_text(encoding="utf-8")

        for item in ["V0.1.*/", "docs/", "deploy/", "ops/", "*.zip"]:
            self.assertIn(item, text)

    def test_assistant_watchdog_files_are_present_and_scoped_to_bot(self):
        service_text = Path("deploy/slowlink-assistant-watchdog.service").read_text(encoding="utf-8")
        script_text = Path("ops/slowlink_assistant_watchdog.sh").read_text(encoding="utf-8")

        self.assertIn("slowlink_assistant_bot", service_text)
        self.assertIn("/opt/slowlink_assistant_bot/ops/slowlink_assistant_watchdog.sh", service_text)
        self.assertIn("APP_CONTAINER=slowlink_assistant_bot", service_text)
        self.assertIn("LOG_FILE=/opt/slowlink_assistant_bot/watchdog.log", service_text)
        self.assertNotIn("slowlink_app", service_text)

        self.assertIn("监控已启动", script_text)
        self.assertIn("CPU过高", script_text)
        self.assertIn("准备重启容器", script_text)
        self.assertIn("容器重启完成", script_text)
        self.assertIn("docker restart \"$APP_CONTAINER\"", script_text)
        self.assertIn("STATUS_FILE=", script_text)
        self.assertIn("watchdog_status.txt", script_text)
        self.assertIn("write_status", script_text)
        self.assertIn("sendMessage", script_text)
        self.assertIn("CPU过高，Bot已自动重启", script_text)
        self.assertIn("BOT_TOKEN", script_text)
        self.assertIn("OWNER_USER_ID", script_text)
        self.assertIn("HEARTBEAT_FILE=", service_text)
        self.assertIn("HEARTBEAT_MAX_AGE=120", service_text)
        self.assertIn("Bot心跳超时", script_text)
        self.assertIn("heartbeat_age", script_text)

        install_text = Path("install.sh").read_text(encoding="utf-8")
        self.assertIn('systemctl restart "$WATCHDOG_SERVICE"', install_text)

    def test_runtime_log_messages_are_chinese(self):
        main_text = Path("assistant_bot/__main__.py").read_text(encoding="utf-8")
        service_text = Path("assistant_bot/service.py").read_text(encoding="utf-8")
        combined = main_text + service_text

        for text in [
            "Assistant 已启动",
            "Bot 信息：账号",
            "停止运行",
            "已复制频道消息",
            "复制消息失败",
            "发送失败",
            "置顶失败",
            "发送完成",
            "数据库备份完成",
            "数据库备份失败",
            "已清理旧记录",
            "帖子进入待删除",
            "帖子自动删除已取消",
            "帖子已保留",
            "帖子删除失败",
            "批量删除保护已触发",
        ]:
            self.assertIn(text, combined)

        for text in [
            "copied channel post",
            "copy failed source",
            "send %s report failed",
            "pin %s report failed",
            "sent %s report",
            "database backup created",
            "database backup failed",
            "pruned old copy events",
            "report_group=configured",
            "stopping",
        ]:
            self.assertNotIn(text, combined)

        for text in ["类型=daily", "类型=weekly", "类型=monthly", "定时报表已发送"]:
            self.assertNotIn(text, combined)


if __name__ == "__main__":
    unittest.main()
