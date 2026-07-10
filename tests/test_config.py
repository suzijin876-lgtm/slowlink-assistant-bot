import tempfile
import unittest
from pathlib import Path

from assistant_bot.config import BotConfig, ConfigError, chat_ref_for_api, normalize_chat_ref, parse_chat_refs


class ConfigTests(unittest.TestCase):
    def test_parse_chat_refs_accepts_ids_and_usernames(self):
        self.assertEqual(
            parse_chat_refs("-1001, @ShardCatDen, source_channel"),
            frozenset({"-1001", "@shardcatden", "@source_channel"}),
        )

    def test_chat_ref_for_api_converts_numeric_ids(self):
        self.assertEqual(chat_ref_for_api("-100123"), -100123)
        self.assertEqual(chat_ref_for_api("@source"), "@source")

    def test_normalize_chat_ref_uses_chat_id_or_username(self):
        self.assertEqual(normalize_chat_ref({"id": -1001, "username": "ShardCatDen"}), "-1001")
        self.assertEqual(normalize_chat_ref({"username": "ShardCatDen"}), "@shardcatden")

    def test_loads_env_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            env_file = Path(tmp) / ".env"
            env_file.write_text(
                "\n".join(
                    [
                        "BOT_TOKEN=123:abc",
                        "OWNER_USER_ID=42",
                        "REPORT_CHAT_ID=-1009",
                        "SOURCE_CHANNEL_IDS=-1001,@source",
                    ]
                ),
                encoding="utf-8",
            )

            config = BotConfig.load(env={}, env_file=env_file)

        self.assertEqual(config.bot_token, "123:abc")
        self.assertEqual(config.owner_user_id, 42)
        self.assertEqual(config.report_chat_id, "-1009")
        self.assertEqual(config.source_channel_refs, frozenset({"-1001", "@source"}))

    def test_missing_required_config_raises_clear_error(self):
        with self.assertRaises(ConfigError) as ctx:
            BotConfig.load(env={}, env_file=None)

        self.assertIn("BOT_TOKEN", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
