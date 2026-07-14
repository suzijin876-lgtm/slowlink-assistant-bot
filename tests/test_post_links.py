import unittest

from assistant_bot.service import _is_telegram_post_link


class TelegramPostLinkTests(unittest.TestCase):
    def test_public_post_uses_telegram_me(self):
        self.assertTrue(
            _is_telegram_post_link({"text": "https://telegram.me/ShardCatDen/577869"})
        )

    def test_public_forum_post_uses_telegram_me(self):
        self.assertTrue(
            _is_telegram_post_link(
                {"text": "https://telegram.me/ShardCatDen/1234/577869"}
            )
        )

    def test_private_post_keeps_t_me_c(self):
        self.assertTrue(
            _is_telegram_post_link({"text": "https://t.me/c/1234567890/577869"})
        )

    def test_private_forum_post_keeps_t_me_c(self):
        self.assertTrue(
            _is_telegram_post_link(
                {"text": "https://t.me/c/1234567890/1234/577869"}
            )
        )


if __name__ == "__main__":
    unittest.main()
