import logging
import inspect
import unittest

import assistant_bot.__main__ as main_module


class MainLoggingTests(unittest.TestCase):
    def test_log_formatter_uses_beijing_time(self):
        formatter = main_module.ChinaTimeFormatter("[%(asctime)s] [%(levelname)s] %(message)s")
        record = logging.LogRecord("test", logging.INFO, __file__, 1, "启动", (), None)
        record.created = 1783622787.0

        text = formatter.format(record)

        self.assertIn("[2026-07-10 02:46:27]", text)
        self.assertIn("启动", text)

    def test_poll_loop_only_pauses_when_no_updates(self):
        self.assertFalse(main_module.should_pause_after_poll([{"update_id": 1}]))
        self.assertTrue(main_module.should_pause_after_poll([]))

    def test_polling_requests_reaction_and_callback_updates(self):
        self.assertIn("message_reaction_count", main_module.ALLOWED_UPDATES)
        self.assertIn("callback_query", main_module.ALLOWED_UPDATES)

    def test_startup_verifies_source_channel_reactions(self):
        self.assertIn("service.verify_source_reactions()", inspect.getsource(main_module.main))

    def test_expected_poll_error_logs_one_warning_without_traceback(self):
        source = inspect.getsource(main_module.main)

        self.assertEqual(source.count("except TelegramAPIError as exc:"), 2)
        self.assertIn('log.warning("Telegram 轮询异常：%s，5秒后重试", exc)', source)
        self.assertLess(
            source.rindex("except TelegramAPIError as exc:"),
            source.index("except Exception as exc:"),
        )


if __name__ == "__main__":
    unittest.main()
