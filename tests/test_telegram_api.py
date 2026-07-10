import unittest
import urllib.error

import assistant_bot.telegram_api as telegram_api
from assistant_bot.telegram_api import TelegramAPI


class _FakeResponse:
    def __init__(self, body: bytes):
        self.body = body

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def read(self):
        return self.body


class TelegramAPITests(unittest.TestCase):
    def make_capturing_api(self):
        api = TelegramAPI("123:abc")
        calls = []

        def capture(method, payload, timeout=35):
            calls.append((method, payload, timeout))
            return True

        api._request = capture
        return api, calls

    def test_request_retries_once_after_temporary_network_error(self):
        calls = []

        def fake_urlopen(req, timeout):
            calls.append((req.full_url, timeout))
            if len(calls) == 1:
                raise urllib.error.URLError("temporary timeout")
            return _FakeResponse(b'{"ok": true, "result": {"id": 123, "username": "slowlinkbot"}}')

        original_urlopen = telegram_api.urllib.request.urlopen
        original_sleep = telegram_api.time.sleep
        telegram_api.urllib.request.urlopen = fake_urlopen
        telegram_api.time.sleep = lambda _seconds: None
        try:
            result = TelegramAPI("123:abc").get_me()
        finally:
            telegram_api.urllib.request.urlopen = original_urlopen
            telegram_api.time.sleep = original_sleep

        self.assertEqual(result["username"], "slowlinkbot")
        self.assertEqual(len(calls), 2)

    def test_send_message_accepts_inline_keyboard(self):
        api, calls = self.make_capturing_api()
        keyboard = {"inline_keyboard": [[{"text": "保留", "callback_data": "mod:keep:-1001:55"}]]}

        api.send_message(42, "待处理", reply_markup=keyboard)

        self.assertEqual(calls[0][0], "sendMessage")
        self.assertEqual(calls[0][1]["reply_markup"], keyboard)

    def test_delete_message_uses_expected_payload(self):
        api, calls = self.make_capturing_api()

        api.delete_message(-1001, 55)

        self.assertEqual(calls[0][0], "deleteMessage")
        self.assertEqual(calls[0][1], {"chat_id": -1001, "message_id": 55})

    def test_get_chat_uses_expected_payload(self):
        api, calls = self.make_capturing_api()

        api.get_chat(-1001)

        self.assertEqual(calls[0][0], "getChat")
        self.assertEqual(calls[0][1], {"chat_id": -1001})

    def test_edit_message_text_can_remove_inline_keyboard(self):
        api, calls = self.make_capturing_api()

        api.edit_message_text(42, 100, "已保留", reply_markup={"inline_keyboard": []})

        self.assertEqual(calls[0][0], "editMessageText")
        self.assertEqual(calls[0][1]["message_id"], 100)
        self.assertEqual(calls[0][1]["reply_markup"], {"inline_keyboard": []})

    def test_answer_callback_query_uses_expected_payload(self):
        api, calls = self.make_capturing_api()

        api.answer_callback_query("callback-1", "已处理", show_alert=True)

        self.assertEqual(calls[0][0], "answerCallbackQuery")
        self.assertEqual(
            calls[0][1],
            {"callback_query_id": "callback-1", "text": "已处理", "show_alert": True},
        )


if __name__ == "__main__":
    unittest.main()
