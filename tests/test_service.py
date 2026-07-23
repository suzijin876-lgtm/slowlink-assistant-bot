import tempfile
import unittest
from dataclasses import replace
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import patch
from zoneinfo import ZoneInfo

from assistant_bot import __version__
from assistant_bot.config import BotConfig
from assistant_bot.menu import cover_panel_keyboard
from assistant_bot.reports import scheduled_period
from assistant_bot.service import AssistantService
from assistant_bot.store import EventStore


TZ = ZoneInfo("Asia/Shanghai")


class FakeAPI:
    def __init__(self):
        self.copied = []
        self.sent = []
        self.photos = []
        self.photo_attempts = []
        self.left = []
        self.pinned = []
        self.unpinned = []
        self.get_chat_member_calls = []
        self.sent_reply_markups = []
        self.edited = []
        self.deleted = []
        self.answered_callbacks = []
        self.get_chat_calls = []
        self.fail_get_chat_for = set()
        self.chat_info = {}
        self.next_copy_message_id = 900
        self.next_send_message_id = 100
        self.fail_send_for_chats = set()
        self.fail_photo_for_chats = set()
        self.fail_pin = False
        self.fail_delete = False
        self.me = {"id": 777, "username": "slowlinkbot"}
        self.chat_member = {"status": "administrator", "can_send_messages": True}

    def copy_message(self, chat_id, from_chat_id, message_id):
        self.copied.append((chat_id, from_chat_id, message_id))
        return {"message_id": self.next_copy_message_id}

    def send_message(self, chat_id, text, disable_web_page_preview=False, reply_markup=None):
        if chat_id in self.fail_send_for_chats:
            raise RuntimeError("send failed")
        self.sent.append((chat_id, text, disable_web_page_preview))
        self.sent_reply_markups.append(reply_markup)
        self.next_send_message_id += 1
        return {"message_id": self.next_send_message_id}

    def send_photo(self, chat_id, photo, caption):
        self.photo_attempts.append((chat_id, photo, caption))
        if chat_id in self.fail_photo_for_chats:
            raise RuntimeError("photo failed")
        self.photos.append((chat_id, photo, caption))
        self.next_send_message_id += 1
        return {"message_id": self.next_send_message_id}

    def edit_message_text(self, chat_id, message_id, text, reply_markup=None):
        self.edited.append((chat_id, message_id, text, reply_markup))
        return True

    def delete_message(self, chat_id, message_id):
        if self.fail_delete:
            raise RuntimeError("delete failed")
        self.deleted.append((chat_id, message_id))
        return True

    def answer_callback_query(self, callback_query_id, text="", show_alert=False):
        self.answered_callbacks.append((callback_query_id, text, show_alert))
        return True

    def leave_chat(self, chat_id):
        self.left.append(chat_id)
        return True

    def pin_chat_message(self, chat_id, message_id, disable_notification=True):
        if self.fail_pin:
            raise RuntimeError("pin failed")
        self.pinned.append((chat_id, message_id, disable_notification))
        return True

    def unpin_chat_message(self, chat_id, message_id: int):
        self.unpinned.append((chat_id, message_id))
        return True

    def get_me(self):
        return self.me

    def get_chat_member(self, chat_id, user_id):
        self.get_chat_member_calls.append((chat_id, user_id))
        return self.chat_member

    def get_chat(self, chat_id):
        self.get_chat_calls.append(chat_id)
        if chat_id in self.fail_get_chat_for:
            raise RuntimeError("reaction check failed")
        return self.chat_info.get(
            chat_id,
            {
                "available_reactions": [
                    {"type": "emoji", "emoji": "👎"},
                    {"type": "emoji", "emoji": "💩"},
                ]
            },
        )


def make_config():
    return BotConfig(
        bot_token="123:abc",
        owner_user_id=42,
        report_chat_id="-1009",
        source_channel_refs=frozenset({"-1001", "@source"}),
        slowlink_panel_url="https://slowlink.example/",
        data_path=":memory:",
        timezone="Asia/Shanghai",
        poll_timeout=1,
        poll_interval=0.01,
        report_hour=0,
        report_minute=0,
        unauthorized_group_action="leave",
        startup_drop_pending_updates=False,
    )


def make_config_with_data_path(data_path):
    config = make_config()
    return BotConfig(
        bot_token=config.bot_token,
        owner_user_id=config.owner_user_id,
        report_chat_id=config.report_chat_id,
        source_channel_refs=config.source_channel_refs,
        data_path=str(data_path),
        timezone=config.timezone,
        poll_timeout=config.poll_timeout,
        poll_interval=config.poll_interval,
        report_hour=config.report_hour,
        report_minute=config.report_minute,
        unauthorized_group_action=config.unauthorized_group_action,
        startup_drop_pending_updates=config.startup_drop_pending_updates,
    )


class AssistantServiceTests(unittest.TestCase):
    def make_service(self):
        self.api = FakeAPI()
        self.store = EventStore(":memory:")
        self.service = AssistantService(make_config(), self.api, self.store, clock=lambda: datetime(2026, 7, 10, 12, 0, tzinfo=TZ))
        self.service.started_at = datetime(2026, 7, 10, 9, 30, tzinfo=TZ)

    def make_service_with_report_channel(self):
        self.api = FakeAPI()
        self.store = EventStore(":memory:")
        config = replace(make_config(), report_channel_id="-1008")
        self.service = AssistantService(
            config,
            self.api,
            self.store,
            clock=lambda: datetime(2026, 7, 10, 12, 0, tzinfo=TZ),
        )
        self.service.started_at = datetime(2026, 7, 10, 9, 30, tzinfo=TZ)

    def send_source_post(self, message_id=55, at=None):
        at = at or datetime(2026, 7, 10, 12, 0, tzinfo=TZ)
        self.service.handle_update({
            "update_id": message_id,
            "channel_post": {
                "message_id": message_id,
                "date": int(at.timestamp()),
                "chat": {"id": -1001, "type": "channel", "title": "Source"},
                "text": f"https://t.me/ShardCatDen/{message_id}",
            },
        })

    def send_owner_reply(self, text, copied_message_id=900, user_id=42, update_id=1000):
        self.service.handle_update({
            "update_id": update_id,
            "message": {
                "message_id": update_id,
                "chat": {"id": 42, "type": "private"},
                "from": {"id": user_id},
                "text": text,
                "reply_to_message": {
                    "message_id": copied_message_id,
                    "chat": {"id": 42, "type": "private"},
                },
            },
        })

    def send_callback(
        self,
        data,
        *,
        user_id=42,
        chat_id=42,
        chat_type="private",
        message_id=500,
        update_id=2000,
    ):
        self.service.handle_update({
            "update_id": update_id,
            "callback_query": {
                "id": f"callback-{update_id}",
                "from": {"id": user_id},
                "message": {
                    "message_id": message_id,
                    "chat": {"id": chat_id, "type": chat_type},
                },
                "data": data,
            },
        })

    def send_reaction_count(self, message_id, thumbs_down=0, poop_count=0, thumbs_up=0, update_id=900):
        reactions = []
        if thumbs_up:
            reactions.append({"type": {"type": "emoji", "emoji": "👍"}, "total_count": thumbs_up})
        if thumbs_down:
            reactions.append({"type": {"type": "emoji", "emoji": "👎"}, "total_count": thumbs_down})
        if poop_count:
            reactions.append({"type": {"type": "emoji", "emoji": "💩"}, "total_count": poop_count})
        self.service.handle_update({
            "update_id": update_id,
            "message_reaction_count": {
                "chat": {"id": -1001, "type": "channel", "title": "Source"},
                "message_id": message_id,
                "date": int(datetime(2026, 7, 10, 12, 0, tzinfo=TZ).timestamp()),
                "reactions": reactions,
            },
        })

    def tearDown(self):
        store = getattr(self, "store", None)
        if store is not None:
            store.close()

    def test_channel_post_from_source_is_copied_to_owner_private_chat(self):
        self.make_service()
        update = {
            "update_id": 1,
            "channel_post": {
                "message_id": 55,
                "chat": {"id": -1001, "type": "channel", "title": "Source"},
                "text": "https://t.me/ShardCatDen/555090",
            },
        }

        self.service.handle_update(update)

        self.assertEqual(self.api.copied, [(42, -1001, 55)])
        stats = self.store.stats_between(datetime(2026, 7, 10, 0, 0, tzinfo=TZ), datetime(2026, 7, 11, 0, 0, tzinfo=TZ))
        self.assertEqual(stats.success_count, 1)

    def test_owner_reply_shan_deletes_source_and_keeps_private_copy(self):
        self.make_service()
        self.send_source_post()

        self.send_owner_reply("删")

        post = self.store.get_moderation_post("-1001", 55)
        event = self.store._conn.execute(
            "SELECT event_type, reason FROM moderation_events WHERE source_message_id = 55"
        ).fetchone()
        self.assertEqual(self.api.deleted, [(-1001, 55)])
        self.assertNotIn((42, 900), self.api.deleted)
        self.assertEqual(post["status"], "deleted")
        self.assertEqual(dict(event), {"event_type": "deleted", "reason": "owner"})
        self.assertIn("帖子已立即删除", self.api.sent[-1][1])

    def test_owner_reply_shanchu_also_deletes_source(self):
        self.make_service()
        self.send_source_post()

        self.send_owner_reply("删除")

        self.assertEqual(self.api.deleted, [(-1001, 55)])
        self.assertEqual(self.store.get_moderation_post("-1001", 55)["status"], "deleted")

    def test_owner_reply_already_deleted_only_records_manual_deletion(self):
        self.make_service()
        self.send_source_post()

        self.send_owner_reply("已删除")
        self.service.clock = lambda: datetime(2026, 7, 10, 12, 1, tzinfo=TZ)

        post = self.store.get_moderation_post("-1001", 55)
        event = self.store._conn.execute(
            "SELECT event_type, reason FROM moderation_events WHERE source_message_id = 55"
        ).fetchone()
        copy_stats = self.store.stats_between(
            datetime(2026, 7, 10, 0, 0, tzinfo=TZ),
            datetime(2026, 7, 11, 0, 0, tzinfo=TZ),
        )
        moderation_stats = self.store.moderation_stats_between(
            datetime(2026, 7, 10, 0, 0, tzinfo=TZ),
            datetime(2026, 7, 11, 0, 0, tzinfo=TZ),
        )
        report = self.service.current_report_text()
        self.assertEqual(self.api.deleted, [])
        self.assertEqual(post["status"], "deleted")
        self.assertEqual(dict(event), {"event_type": "deleted", "reason": "manual"})
        self.assertEqual(copy_stats.success_count, 1)
        self.assertEqual(moderation_stats.deleted_count, 1)
        self.assertIn("内容纠错：删除1条", report)
        self.assertNotIn("已删除：", report)
        self.assertIn("已记录为删除", self.api.sent[-1][1])

    def test_owner_reply_delete_bypasses_one_hour_limit(self):
        self.make_service()
        self.send_source_post(at=datetime(2026, 7, 10, 10, 0, tzinfo=TZ))

        self.send_owner_reply("删除")

        self.assertEqual(self.api.deleted, [(-1001, 55)])
        self.assertEqual(self.store.get_moderation_post("-1001", 55)["status"], "deleted")

    def test_owner_reply_delete_bypasses_batch_protection(self):
        self.make_service()
        now = datetime(2026, 7, 10, 12, 0, tzinfo=TZ)
        for message_id in range(1, 5):
            at = now - timedelta(minutes=message_id)
            self.store.record_moderation_post("-1001", "Source", message_id, at)
            self.store.complete_moderation("-1001", message_id, "deleted", "deleted", "auto", at)
        self.send_source_post()

        self.send_owner_reply("删")

        self.assertEqual(self.api.deleted, [(-1001, 55)])
        self.assertEqual(self.store.get_moderation_post("-1001", 55)["status"], "deleted")

    def test_owner_reply_action_requires_owner_and_known_copied_message(self):
        self.make_service()
        self.send_source_post()

        self.send_owner_reply("删除", user_id=99)
        self.send_owner_reply("删除", copied_message_id=901, update_id=1001)

        self.assertEqual(self.api.deleted, [])
        self.assertEqual(self.store.get_moderation_post("-1001", 55)["status"], "watching")

    def test_owner_reply_action_requires_exact_text_and_a_reply(self):
        self.make_service()
        self.send_source_post()

        self.send_owner_reply("帮我删除")
        self.service.handle_update({
            "update_id": 1001,
            "message": {
                "message_id": 1001,
                "chat": {"id": 42, "type": "private"},
                "from": {"id": 42},
                "text": "删除",
            },
        })

        self.assertEqual(self.api.deleted, [])
        self.assertEqual(self.store.get_moderation_post("-1001", 55)["status"], "watching")

    def test_owner_reply_manual_deletion_is_idempotent(self):
        self.make_service()
        self.send_source_post()

        self.send_owner_reply("已删除")
        self.send_owner_reply("已删除", update_id=1001)

        event_count = self.store._conn.execute(
            "SELECT COUNT(*) FROM moderation_events WHERE source_message_id = 55 AND event_type = 'deleted'"
        ).fetchone()[0]
        self.assertEqual(event_count, 1)
        self.assertEqual(self.api.deleted, [])
        self.assertIn("已经处理", self.api.sent[-1][1])

    def test_owner_reply_can_retry_after_delete_failure(self):
        self.make_service()
        self.send_source_post()
        self.api.fail_delete = True
        self.send_owner_reply("删除")

        self.assertEqual(self.store.get_moderation_post("-1001", 55)["status"], "failed")
        self.api.fail_delete = False
        self.send_owner_reply("删", update_id=1001)

        self.assertEqual(self.api.deleted, [(-1001, 55)])
        self.assertEqual(self.store.get_moderation_post("-1001", 55)["status"], "deleted")

    def test_owner_reply_can_confirm_manual_deletion_after_delete_failure(self):
        self.make_service()
        self.send_source_post()
        self.api.fail_delete = True
        self.send_owner_reply("删除")
        self.send_owner_reply("已删除", update_id=1001)

        stats = self.store.moderation_stats_between(
            datetime(2026, 7, 10, 0, 0, tzinfo=TZ),
            datetime(2026, 7, 11, 0, 0, tzinfo=TZ),
        )
        self.assertEqual(self.api.deleted, [])
        self.assertEqual(self.store.get_moderation_post("-1001", 55)["status"], "deleted")
        self.assertEqual(stats.deleted_count, 1)

    def test_owner_reply_treats_missing_source_as_confirmed_deletion(self):
        self.make_service()
        self.send_source_post()

        def missing_source(*args):
            raise RuntimeError("deleteMessage failed: Bad Request: message to delete not found")

        self.api.delete_message = missing_source
        self.send_owner_reply("删除")

        stats = self.store.moderation_stats_between(
            datetime(2026, 7, 10, 0, 0, tzinfo=TZ),
            datetime(2026, 7, 11, 0, 0, tzinfo=TZ),
        )
        self.assertEqual(self.api.deleted, [])
        self.assertEqual(self.store.get_moderation_post("-1001", 55)["status"], "deleted")
        self.assertEqual(stats.deleted_count, 1)
        self.assertIn("已确认删除", self.api.sent[-1][1])

    def test_owner_manual_deletion_clears_pending_notice_buttons(self):
        self.make_service()
        self.send_source_post()
        self.send_reaction_count(55, thumbs_down=2)
        self.assertEqual(self.store.get_moderation_post("-1001", 55)["status"], "pending")

        self.send_owner_reply("已删除", update_id=1001)

        post = self.store.get_moderation_post("-1001", 55)
        self.assertEqual(post["status"], "deleted")
        self.assertEqual(self.api.deleted, [])
        self.assertEqual(self.api.edited[-1][1], 101)
        self.assertEqual(self.api.edited[-1][3], {"inline_keyboard": []})
        self.assertIn("已记录为删除", self.api.edited[-1][2])

    def test_owner_manual_deletion_clears_protected_notice_buttons(self):
        self.make_service()
        self.send_source_post()
        now = datetime(2026, 7, 10, 12, 0, tzinfo=TZ)
        self.store.complete_moderation("-1001", 55, "protected", "protected", "rate_limit", now)
        self.store.set_moderation_notice("-1001", 55, 777, now)

        self.send_owner_reply("已删除")

        self.assertEqual(self.store.get_moderation_post("-1001", 55)["status"], "deleted")
        self.assertEqual(self.api.edited[-1][1], 777)
        self.assertEqual(self.api.edited[-1][3], {"inline_keyboard": []})

    def test_group_current_report_hides_runtime_diagnostics_but_private_keeps_them(self):
        self.make_service()
        self.store.set_state("statistics_coverage_started_at", datetime(2026, 7, 9, 0, 0, tzinfo=TZ).isoformat())
        self.store.record_copy_success(
            "-1001", "Source", 54, "42", 899, datetime(2026, 7, 9, 10, 0, tzinfo=TZ)
        )
        self.store.record_copy_success(
            "-1001", "Source", 55, "42", 900, datetime(2026, 7, 10, 12, 0, tzinfo=TZ)
        )
        self.store.record_copy_success(
            "-1001", "Source", 57, "42", 901, datetime(2026, 7, 10, 12, 1, tzinfo=TZ)
        )
        self.store.record_moderation_post("-1001", "Source", 57, datetime(2026, 7, 10, 12, 1, tzinfo=TZ))
        self.store.complete_moderation(
            "-1001", 57, "deleted", "deleted", "owner_reply", datetime(2026, 7, 10, 12, 1, 30, tzinfo=TZ)
        )
        self.store.record_copy_failure(
            "-1001", "Source", 56, "42", "bad request", datetime(2026, 7, 10, 12, 1, tzinfo=TZ)
        )
        self.service.clock = lambda: datetime(2026, 7, 10, 12, 2, tzinfo=TZ)

        self.service.send_current_report(-1009)
        group_text = self.api.sent[-1][1]
        self.service.send_current_report()
        private_text = self.api.sent[-1][1]

        self.assertNotIn("系统：", group_text)
        self.assertNotIn("异常：", group_text)
        self.assertNotIn("内容纠错", group_text)
        self.assertIn("日期：2026-07-10", group_text)
        self.assertIn("转发：1条", group_text)
        self.assertIn("较昨日同期：持平", group_text)
        self.assertIn("高峰时段：12:00-13:00", group_text)
        self.assertIn("首次转发：12:00", group_text)
        self.assertIn("最后转发：12:00", group_text)
        self.assertIn("系统：", private_text)
        self.assertIn("异常：1次", private_text)
        self.assertIn("今日转发2条", private_text)
        self.assertIn("内容纠错：删除1条", private_text)

    def test_private_channel_post_link_in_caption_is_copied(self):
        self.make_service()
        self.service.handle_update({
            "update_id": 2,
            "channel_post": {
                "message_id": 56,
                "chat": {"id": -1001, "type": "channel", "title": "Source"},
                "caption": "  https://t.me/c/1234567890/56\n",
            },
        })

        self.assertEqual(self.api.copied, [(42, -1001, 56)])

    def test_plain_text_source_post_is_ignored(self):
        self.make_service()
        self.service.handle_update({
            "update_id": 3,
            "channel_post": {
                "message_id": 57,
                "chat": {"id": -1001, "type": "channel", "title": "Source"},
                "text": "今晚频道抽奖，欢迎参加",
            },
        })

        self.assertEqual(self.api.copied, [])
        self.assertIsNone(self.store.get_moderation_post("-1001", 57))

    def test_source_post_with_extra_text_around_link_is_ignored(self):
        self.make_service()
        self.service.handle_update({
            "update_id": 4,
            "channel_post": {
                "message_id": 58,
                "chat": {"id": -1001, "type": "channel", "title": "Source"},
                "text": "抽奖地址：https://t.me/ShardCatDen/577869",
            },
        })

        self.assertEqual(self.api.copied, [])
        self.assertIsNone(self.store.get_moderation_post("-1001", 58))

    def test_non_post_links_are_ignored(self):
        self.make_service()
        invalid_links = (
            "https://example.com/ShardCatDen/577869",
            "https://t.me/ShardCatDen",
            "https://t.me/+invite_code",
            "https://t.me/slowlinkbot?start=577869",
        )

        for index, text in enumerate(invalid_links, start=60):
            with self.subTest(text=text):
                self.service.handle_update({
                    "update_id": index,
                    "channel_post": {
                        "message_id": index,
                        "chat": {"id": -1001, "type": "channel", "title": "Source"},
                        "text": text,
                    },
                })

        self.assertEqual(self.api.copied, [])

    def test_channel_pin_service_message_is_ignored(self):
        self.make_service()
        update = {
            "update_id": 3,
            "channel_post": {
                "message_id": 57,
                "date": int(datetime(2026, 7, 10, 12, 0, tzinfo=TZ).timestamp()),
                "chat": {"id": -1001, "type": "channel", "title": "Source"},
                "pinned_message": {"message_id": 55, "text": "original"},
            },
        }

        with self.assertLogs("assistant_bot.service", level="INFO") as captured:
            self.service.handle_update(update)

        self.assertEqual(self.api.copied, [])
        self.assertIsNone(self.store.get_moderation_post("-1001", 57))
        stats = self.store.stats_between(
            datetime(2026, 7, 10, 0, 0, tzinfo=TZ),
            datetime(2026, 7, 11, 0, 0, tzinfo=TZ),
        )
        self.assertEqual(stats.success_count, 0)
        self.assertEqual(stats.failure_count, 0)
        self.assertIn("跳过频道置顶通知", "\n".join(captured.output))

    def test_channel_post_from_unlisted_source_is_ignored(self):
        self.make_service()
        update = {
            "update_id": 2,
            "channel_post": {
                "message_id": 56,
                "chat": {"id": -1002, "type": "channel", "title": "Other"},
                "text": "ignored",
            },
        }

        self.service.handle_update(update)

        self.assertEqual(self.api.copied, [])

    def test_one_downvote_does_not_schedule_deletion(self):
        self.make_service()
        self.send_source_post()

        self.send_reaction_count(55, thumbs_up=0, thumbs_down=1)

        post = self.store.get_moderation_post("-1001", 55)
        self.assertEqual(post["status"], "watching")
        self.assertEqual(self.api.sent, [])

    def test_two_downvotes_schedule_regardless_of_upvotes(self):
        self.make_service()
        self.send_source_post()

        self.send_reaction_count(55, thumbs_up=99, thumbs_down=2)

        post = self.store.get_moderation_post("-1001", 55)
        self.assertEqual(post["status"], "pending")
        self.assertEqual(post["delete_after"], "2026-07-10T12:01:00+08:00")
        self.assertEqual(self.api.sent[0][0], 42)
        self.assertIn("帖子进入待删除", self.api.sent[0][1])
        self.assertIn("👎2", self.api.sent[0][1])
        self.assertNotIn("👍", self.api.sent[0][1])
        keyboard = self.api.sent_reply_markups[0]["inline_keyboard"]
        self.assertEqual([button["text"] for button in keyboard[0]], ["保留", "立即删除"])

    def test_one_poop_does_not_delete(self):
        self.make_service()
        self.send_source_post()

        self.send_reaction_count(55, poop_count=1)

        post = self.store.get_moderation_post("-1001", 55)
        self.assertEqual(post["status"], "watching")
        self.assertEqual(self.api.deleted, [])

    def test_two_poops_delete_immediately_without_waiting(self):
        self.make_service()
        self.send_source_post()

        self.send_reaction_count(55, poop_count=2)

        post = self.store.get_moderation_post("-1001", 55)
        event = self.store._conn.execute(
            "SELECT reason, poop_count FROM moderation_events WHERE source_message_id = 55"
        ).fetchone()
        self.assertEqual(post["status"], "deleted")
        self.assertEqual(self.api.deleted, [(-1001, 55)])
        self.assertEqual(self.api.sent, [])
        self.assertEqual(event["reason"], "poop")
        self.assertEqual(event["poop_count"], 2)

    def test_vote_recovery_cancels_pending_deletion(self):
        self.make_service()
        self.send_source_post()
        self.send_reaction_count(55, thumbs_up=1, thumbs_down=2)

        self.send_reaction_count(55, thumbs_up=99, thumbs_down=1, update_id=901)

        post = self.store.get_moderation_post("-1001", 55)
        self.assertEqual(post["status"], "watching")
        self.assertEqual(self.api.deleted, [])
        self.assertIn("自动删除已取消", self.api.edited[-1][2])

    def test_pending_post_is_deleted_after_one_minute(self):
        self.make_service()
        current = {"now": datetime(2026, 7, 10, 12, 0, tzinfo=TZ)}
        self.service.clock = lambda: current["now"]
        self.send_source_post(at=current["now"])
        self.send_reaction_count(55, thumbs_up=1, thumbs_down=2)

        current["now"] = datetime(2026, 7, 10, 12, 1, 1, tzinfo=TZ)
        self.service.run_due_moderations()

        post = self.store.get_moderation_post("-1001", 55)
        stats = self.store.moderation_stats_between(
            datetime(2026, 7, 10, 0, 0, tzinfo=TZ),
            datetime(2026, 7, 11, 0, 0, tzinfo=TZ),
        )
        self.assertEqual(self.api.deleted, [(-1001, 55)])
        self.assertEqual(post["status"], "deleted")
        self.assertEqual(stats.deleted_count, 1)
        self.assertIn("帖子已自动删除", self.api.edited[-1][2])

    def test_owner_can_keep_pending_post(self):
        self.make_service()
        self.send_source_post()
        self.send_reaction_count(55, thumbs_up=1, thumbs_down=2)

        self.service.handle_update({
            "update_id": 902,
            "callback_query": {
                "id": "callback-keep",
                "from": {"id": 42},
                "message": {"message_id": 101, "chat": {"id": 42, "type": "private"}},
                "data": "mod:keep:-1001:55",
            },
        })

        post = self.store.get_moderation_post("-1001", 55)
        self.assertEqual(post["status"], "kept")
        self.assertEqual(self.api.deleted, [])
        self.assertIn("帖子已保留", self.api.edited[-1][2])
        self.assertEqual(self.api.answered_callbacks[-1][1], "已保留")

    def test_owner_can_delete_pending_post_immediately(self):
        self.make_service()
        self.send_source_post()
        self.send_reaction_count(55, thumbs_up=1, thumbs_down=2)

        self.service.handle_update({
            "update_id": 903,
            "callback_query": {
                "id": "callback-delete",
                "from": {"id": 42},
                "message": {"message_id": 101, "chat": {"id": 42, "type": "private"}},
                "data": "mod:delete:-1001:55",
            },
        })

        post = self.store.get_moderation_post("-1001", 55)
        self.assertEqual(post["status"], "deleted")
        self.assertEqual(self.api.deleted, [(-1001, 55)])
        self.assertIn("帖子已立即删除", self.api.edited[-1][2])

    def test_posts_older_than_one_hour_are_not_scheduled(self):
        self.make_service()
        self.service.clock = lambda: datetime(2026, 7, 10, 12, 0, tzinfo=TZ)
        self.send_source_post(at=datetime(2026, 7, 10, 10, 59, tzinfo=TZ))

        self.send_reaction_count(55, thumbs_up=0, thumbs_down=3)

        post = self.store.get_moderation_post("-1001", 55)
        self.assertEqual(post["status"], "watching")
        self.assertEqual(self.api.sent, [])

    def test_pending_post_older_than_one_hour_is_cancelled_with_correct_reason(self):
        self.make_service()
        posted_at = datetime(2026, 7, 10, 10, 59, tzinfo=TZ)
        now = datetime(2026, 7, 10, 12, 0, tzinfo=TZ)
        self.store.record_moderation_post("-1001", "Source", 55, posted_at)
        self.store.update_moderation_reactions("-1001", 55, 0, 2, posted_at)
        self.store.set_moderation_pending("-1001", 55, posted_at + timedelta(minutes=1), posted_at)
        self.store.set_moderation_notice("-1001", 55, 900, posted_at)

        self.service.run_due_moderations(now)

        post = self.store.get_moderation_post("-1001", 55)
        self.assertEqual(post["status"], "watching")
        self.assertEqual(self.api.deleted, [])
        self.assertIn("超过1小时", self.api.edited[-1][2])

    def test_fifth_poop_delete_in_ten_minutes_is_protected(self):
        self.make_service()
        current = {"now": datetime(2026, 7, 10, 12, 0, tzinfo=TZ)}
        self.service.clock = lambda: current["now"]
        for message_id in range(1, 5):
            at = current["now"] - timedelta(minutes=message_id)
            self.store.record_moderation_post("-1001", "Source", message_id, at)
            self.store.update_moderation_reactions("-1001", message_id, 0, 0, at, poop_count=2)
            self.store.complete_moderation("-1001", message_id, "deleted", "deleted", "poop", at)
        self.send_source_post(message_id=55, at=current["now"])

        self.send_reaction_count(55, poop_count=2)

        post = self.store.get_moderation_post("-1001", 55)
        self.assertEqual(post["status"], "protected")
        self.assertEqual(self.api.deleted, [])
        self.assertIn("批量删除保护已触发", self.api.sent[-1][1])

    def test_verify_source_reactions_checks_all_configured_channels(self):
        self.make_service()

        self.service.verify_source_reactions()

        self.assertEqual(self.api.get_chat_calls, [-1001, "@source"])

    def test_reaction_check_warns_when_poop_is_not_available(self):
        self.make_service()
        self.api.chat_info[-1001] = {
            "available_reactions": [
                {"type": "emoji", "emoji": "👍"},
                {"type": "emoji", "emoji": "👎"},
            ]
        }

        with self.assertLogs("assistant_bot.service", level="WARNING") as captured:
            self.service.verify_source_reactions()

        self.assertTrue(any("缺少=💩" in line for line in captured.output))

    def test_reaction_check_failure_does_not_stop_other_channels(self):
        self.make_service()
        self.api.fail_get_chat_for.add(-1001)

        self.service.verify_source_reactions()

        self.assertEqual(self.api.get_chat_calls, [-1001, "@source"])

    def test_owner_notice_failure_stops_automatic_deletion(self):
        self.make_service()
        self.api.fail_send_for_chats.add(42)
        self.send_source_post()

        self.send_reaction_count(55, thumbs_up=0, thumbs_down=2)

        post = self.store.get_moderation_post("-1001", 55)
        self.assertEqual(post["status"], "failed")
        self.assertEqual(self.store.due_moderation_posts(datetime(2026, 7, 10, 12, 2, tzinfo=TZ)), [])

    def test_delete_failure_marks_post_failed(self):
        self.make_service()
        current = {"now": datetime(2026, 7, 10, 12, 0, tzinfo=TZ)}
        self.service.clock = lambda: current["now"]
        self.send_source_post(at=current["now"])
        self.send_reaction_count(55, thumbs_up=0, thumbs_down=2)
        self.api.fail_delete = True

        current["now"] += timedelta(minutes=1, seconds=1)
        self.service.run_due_moderations()

        post = self.store.get_moderation_post("-1001", 55)
        self.assertEqual(post["status"], "failed")
        self.assertEqual(self.api.deleted, [])
        self.assertIn("帖子删除失败", self.api.edited[-1][2])

    def test_fifth_auto_delete_in_ten_minutes_is_protected(self):
        self.make_service()
        current = {"now": datetime(2026, 7, 10, 12, 0, tzinfo=TZ)}
        self.service.clock = lambda: current["now"]
        for message_id in range(1, 5):
            at = current["now"] - timedelta(minutes=message_id)
            self.store.record_moderation_post("-1001", "Source", message_id, at)
            self.store.update_moderation_reactions("-1001", message_id, 0, 2, at)
            self.store.complete_moderation("-1001", message_id, "deleted", "deleted", "auto", at)
        self.send_source_post(message_id=55, at=current["now"])
        self.send_reaction_count(55, thumbs_up=0, thumbs_down=2)

        current["now"] += timedelta(minutes=1, seconds=1)
        self.service.run_due_moderations()

        post = self.store.get_moderation_post("-1001", 55)
        stats = self.store.moderation_stats_between(
            datetime(2026, 7, 10, 0, 0, tzinfo=TZ),
            datetime(2026, 7, 11, 0, 0, tzinfo=TZ),
        )
        self.assertEqual(post["status"], "protected")
        self.assertEqual(self.api.deleted, [])
        self.assertEqual(stats.protected_count, 1)
        self.assertIn("批量删除保护已触发", self.api.edited[-1][2])

    def test_private_command_only_works_for_owner(self):
        self.make_service()
        self.service.handle_update({
            "update_id": 3,
            "message": {
                "message_id": 1,
                "chat": {"id": 42, "type": "private"},
                "from": {"id": 42},
                "text": "/status",
            },
        })
        self.service.handle_update({
            "update_id": 4,
            "message": {
                "message_id": 2,
                "chat": {"id": 99, "type": "private"},
                "from": {"id": 99},
                "text": "/status",
            },
        })

        self.assertEqual(len(self.api.sent), 1)
        self.assertIn("运行状态", self.api.sent[0][1])
        self.assertIn("今日：转发0条/失败0条", self.api.sent[0][1])
        self.assertIn("今日纠错：删除0条", self.api.sent[0][1])
        self.assertIn("运行：2小时30分", self.api.sent[0][1])
        self.assertNotIn(" 条", self.api.sent[0][1])
        self.assertNotIn(" / ", self.api.sent[0][1])
        self.assertNotIn("T", self.api.sent[0][1])
        self.assertNotIn("+08:00", self.api.sent[0][1])

    def test_owner_private_command_is_deleted_but_bot_reply_is_kept(self):
        self.make_service()

        with patch("threading.Timer") as timer:
            self.service.handle_update({
                "update_id": 5,
                "message": {
                    "message_id": 41,
                    "chat": {"id": 42, "type": "private"},
                    "from": {"id": 42},
                    "text": "/status",
                },
            })

        self.assertEqual(self.api.deleted, [(42, 41)])
        self.assertEqual(len(self.api.sent), 1)
        self.assertIn("运行状态", self.api.sent[0][1])
        timer.assert_not_called()

    def test_private_photo_caption_command_is_processed_before_deletion(self):
        self.make_service()
        self.store.set_state("scheduled_report_cover_file_id", "old-cover")
        self.service.cover_upload_deadline = datetime(2026, 7, 10, 12, 10, tzinfo=TZ)
        events = []
        original_handler = self.service._handle_cover_command
        original_delete = self.api.delete_message

        def handle_cover(message, text):
            original_handler(message, text)
            events.append("processed")

        def delete_message(chat_id, message_id):
            events.append("deleted")
            return original_delete(chat_id, message_id)

        self.service._handle_cover_command = handle_cover
        self.api.delete_message = delete_message
        self.service.handle_update({
            "update_id": 6,
            "message": {
                "message_id": 42,
                "chat": {"id": 42, "type": "private"},
                "from": {"id": 42},
                "caption": "/cover off",
                "photo": [{"file_id": "cover", "width": 1280, "height": 720}],
            },
        })

        self.assertIsNone(self.store.get_state("scheduled_report_cover_file_id"))
        self.assertEqual(events, ["processed", "deleted"])
        self.assertEqual(self.api.deleted, [(42, 42)])

    def test_command_delete_failure_only_logs_warning(self):
        self.make_service()
        self.api.fail_delete = True

        with self.assertLogs("assistant_bot.service", level="WARNING") as captured:
            self.service.handle_update({
                "update_id": 7,
                "message": {
                    "message_id": 43,
                    "chat": {"id": 42, "type": "private"},
                    "from": {"id": 42},
                    "text": "/status",
                },
            })

        self.assertEqual(len(self.api.sent), 1)
        self.assertTrue(any("命令消息清理失败" in line and "消息=43" in line for line in captured.output))

    def test_start_opens_private_button_panel_without_command_list(self):
        self.make_service()

        self.service.handle_update({
            "update_id": 300,
            "message": {
                "message_id": 1,
                "chat": {"id": 42, "type": "private"},
                "from": {"id": 42},
                "text": "/start",
            },
        })

        self.assertIn("SlowLink Assistant", self.api.sent[0][1])
        self.assertNotIn("/status", self.api.sent[0][1])
        keyboard = self.api.sent_reply_markups[0]["inline_keyboard"]
        self.assertEqual(
            keyboard,
            [
                [
                    {"text": "🌐SlowLink", "url": "https://slowlink.example/"},
                ],
                [
                    {"text": "📊当前报告", "callback_data": "menu:report"},
                    {"text": "✅运行状态", "callback_data": "menu:status"},
                ],
                [
                    {"text": "🧾最近记录", "callback_data": "menu:recent"},
                    {"text": "🩺系统自检", "callback_data": "menu:check"},
                ],
                [
                    {"text": "🗓简报设置", "callback_data": "menu:settings"},
                    {"text": "🖼封面管理", "callback_data": "menu:cover"},
                ],
            ],
        )

    def test_start_uses_wide_two_column_control_panel(self):
        self.make_service()

        self.service.handle_update({
            "update_id": 302,
            "message": {
                "message_id": 1,
                "chat": {"id": 42, "type": "private"},
                "from": {"id": 42},
                "text": "/start",
            },
        })

        text = self.api.sent[0][1]
        self.assertIn("🧭SlowLink Assistant控制面板", text)
        self.assertIn(f"版本：V{__version__}", text)
        self.assertIn("模式：频道消息助手", text)
        self.assertIn("状态：正常运行", text)
        self.assertIn("点击下方按钮进入对应功能", text)
        repository_version = (Path(__file__).resolve().parents[1] / "VERSION").read_text(encoding="utf-8").strip()
        self.assertEqual(__version__, repository_version)
        keyboard = self.api.sent_reply_markups[0]["inline_keyboard"]
        self.assertEqual([len(row) for row in keyboard], [1, 2, 2, 2])

    def test_private_panel_edits_one_message_and_returns_home(self):
        self.make_service()

        self.send_callback("menu:status")

        self.assertEqual(self.api.sent, [])
        self.assertIn("运行状态", self.api.edited[-1][2])
        labels = [
            button["text"]
            for row in self.api.edited[-1][3]["inline_keyboard"]
            for button in row
        ]
        self.assertEqual(labels, ["🔄刷新", "↩返回"])
        self.assertEqual(self.api.answered_callbacks[-1][0], "callback-2000")

        self.send_callback("menu:home", update_id=2001)

        self.assertIn("SlowLink Assistant", self.api.edited[-1][2])
        self.assertIn("📊当前报告", [button["text"] for row in self.api.edited[-1][3]["inline_keyboard"] for button in row])

    def test_cover_panel_uses_compact_two_column_rows(self):
        keyboard = cover_panel_keyboard(True)["inline_keyboard"]

        self.assertEqual(
            [[button["text"] for button in row] for row in keyboard],
            [["🖼更换", "👁预览"], ["⏸停用", "↩返回"]],
        )

    def test_report_group_panel_only_has_refresh_and_legacy_home_keeps_report(self):
        self.make_service()
        group = {"id": -1009, "type": "supergroup", "title": "Report Group"}
        self.service.handle_update({
            "update_id": 301,
            "message": {
                "message_id": 1,
                "chat": group,
                "from": {"id": 42},
                "text": "/start",
            },
        })

        self.assertIn("当前概览", self.api.sent[0][1])
        self.assertNotIn("此群已配置完成", self.api.sent[0][1])
        keyboard = self.api.sent_reply_markups[0]["inline_keyboard"]
        self.assertEqual(keyboard, [[{"text": "🔄刷新", "callback_data": "group:report"}]])

        self.send_callback("group:report", chat_id=-1009, chat_type="supergroup", update_id=2002)
        self.assertIn("当前概览", self.api.edited[-1][2])
        self.assertEqual(
            self.api.edited[-1][3]["inline_keyboard"],
            [[{"text": "🔄刷新", "callback_data": "group:report"}]],
        )

        self.send_callback("group:home", chat_id=-1009, chat_type="supergroup", update_id=2003)
        self.assertIn("当前概览", self.api.edited[-1][2])
        self.assertNotIn("此群已配置完成", self.api.edited[-1][2])
        self.assertEqual(
            self.api.edited[-1][3]["inline_keyboard"],
            [[{"text": "🔄刷新", "callback_data": "group:report"}]],
        )

        edit_count = len(self.api.edited)
        self.send_callback(
            "group:report",
            user_id=99,
            chat_id=-1009,
            chat_type="supergroup",
            update_id=2004,
        )
        self.assertEqual(len(self.api.edited), edit_count)
        self.assertEqual(self.api.answered_callbacks[-1][1], "无权限")

    def test_report_settings_toggle_group_daily_without_disabling_channel_daily(self):
        self.make_service_with_report_channel()

        self.send_callback("menu:settings")
        rows = self.api.edited[-1][3]["inline_keyboard"]
        self.assertEqual([len(row) for row in rows], [2, 2, 2, 1])
        labels = [button["text"] for row in rows for button in row]
        self.assertIn("群·日报✅", labels)
        self.assertIn("频道·日报✅", labels)

        self.send_callback("settings:group:daily", update_id=2004)

        self.assertEqual(self.store.get_state("report_enabled:group:daily"), "0")
        labels = [button["text"] for row in self.api.edited[-1][3]["inline_keyboard"] for button in row]
        self.assertIn("群·日报❌", labels)
        self.assertIn("频道·日报✅", labels)

        now = datetime(2026, 7, 10, 0, 0, tzinfo=TZ)
        self.store.set_state("statistics_coverage_started_at", datetime(2026, 7, 8, 0, 0, tzinfo=TZ).isoformat())
        self.service.run_due_reports(now)

        report_targets = [item[0] for item in self.api.sent if item[0] in {-1009, -1008}]
        self.assertEqual(report_targets, [-1008])
        self.assertEqual(self.api.pinned, [(-1008, 101, True)])
        self.assertTrue(self.store.was_report_sent("daily", scheduled_period("daily", now).key))

    def test_combined_report_respects_different_group_and_channel_switches(self):
        self.make_service_with_report_channel()
        self.store.set_state("report_enabled:group:daily", "0")
        now = datetime(2026, 7, 13, 0, 0, tzinfo=TZ)

        self.service.run_due_reports(now)

        reports = {chat_id: text for chat_id, text, _ in self.api.sent if chat_id in {-1009, -1008}}
        self.assertIn("📊上周周报", reports[-1009])
        self.assertNotIn("昨日（", reports[-1009])
        self.assertIn("📊周期简报", reports[-1008])
        self.assertIn("昨日（", reports[-1008])
        self.assertIn("上周（", reports[-1008])

    def test_cover_panel_accepts_next_owner_photo_without_caption_command(self):
        self.make_service()

        self.send_callback("menu:cover")
        self.send_callback("cover:upload", update_id=2005)
        self.assertIn("直接发送一张图片", self.api.edited[-1][2])

        self.service.handle_update({
            "update_id": 302,
            "message": {
                "message_id": 2,
                "chat": {"id": 42, "type": "private"},
                "from": {"id": 42},
                "photo": [
                    {"file_id": "small", "width": 320, "height": 180, "file_size": 100},
                    {"file_id": "cover-from-panel", "width": 1280, "height": 720, "file_size": 1000},
                ],
            },
        })

        self.assertEqual(self.store.get_state("scheduled_report_cover_file_id"), "cover-from-panel")
        self.assertEqual(self.api.photo_attempts[-1][0:2], (42, "cover-from-panel"))

    def test_report_command_sends_single_current_report(self):
        self.make_service()
        self.store.record_copy_success("-1001", "Source", 1, "42", 9, datetime(2026, 7, 10, 1, 0, tzinfo=TZ))
        deleted_at = datetime(2026, 7, 10, 2, 0, tzinfo=TZ)
        self.store.record_moderation_post("-1001", "Source", 2, deleted_at)
        self.store.update_moderation_reactions("-1001", 2, 0, 0, deleted_at, poop_count=2)
        self.store.complete_moderation("-1001", 2, "deleted", "deleted", "poop", deleted_at)

        self.service.handle_update({
            "update_id": 30,
            "message": {
                "message_id": 1,
                "chat": {"id": 42, "type": "private"},
                "from": {"id": 42},
                "text": "/report",
            },
        })

        self.assertEqual(len(self.api.sent), 1)
        self.assertIn("当前概览", self.api.sent[0][1])
        self.assertIn("今日转发1条", self.api.sent[0][1])
        self.assertIn("内容纠错：删除1条", self.api.sent[0][1])
        self.assertNotIn("约", self.api.sent[0][1])
        self.assertIn("最近：01:00", self.api.sent[0][1])
        self.assertIn("系统：正常", self.api.sent[0][1])
        self.assertNotIn("仅统计Bot转发，不代表内容正确。", self.api.sent[0][1])
        self.assertNotIn("成功率", self.api.sent[0][1])
        self.assertNotIn(" / ", self.api.sent[0][1])
        self.assertNotIn("T", self.api.sent[0][1])
        self.assertNotIn("+08:00", self.api.sent[0][1])
        self.assertNotIn("复制", self.api.sent[0][1])

    def test_report_command_uses_natural_empty_text(self):
        self.make_service()

        self.service.handle_update({
            "update_id": 36,
            "message": {
                "message_id": 1,
                "chat": {"id": 42, "type": "private"},
                "from": {"id": 42},
                "text": "/report",
            },
        })

        self.assertEqual(len(self.api.sent), 1)
        self.assertIn("今日暂无明显转发", self.api.sent[0][1])
        self.assertIn("系统：待命中", self.api.sent[0][1])
        self.assertIn("内容纠错：删除0条", self.api.sent[0][1])
        self.assertNotIn("仅统计Bot转发，不代表内容正确。", self.api.sent[0][1])
        self.assertNotIn("转发 0 条", self.api.sent[0][1])
        self.assertNotIn("转发0条", self.api.sent[0][1])

    def test_current_report_keeps_failure_count_without_reason(self):
        self.make_service()
        self.store.record_copy_failure(
            "-1001",
            "Source",
            1,
            "42",
            "copyMessage HTTP 400: message cannot be copied",
            datetime(2026, 7, 10, 1, 0, tzinfo=TZ),
        )

        text = self.service.current_report_text()

        self.assertIn("系统：有异常", text)
        self.assertIn("异常：1次", text)
        self.assertNotIn("原因：", text)
        self.assertNotIn("copyMessage", text)

    def test_report_group_only_owner_can_request_current_report(self):
        self.make_service()
        self.store.record_copy_success("-1001", "Source", 1, "42", 9, datetime(2026, 7, 10, 1, 0, tzinfo=TZ))

        self.service.handle_update({
            "update_id": 32,
            "message": {
                "message_id": 1,
                "chat": {"id": -1009, "type": "supergroup", "title": "Report Group"},
                "from": {"id": 99},
                "text": "/report",
            },
        })
        self.service.handle_update({
            "update_id": 33,
            "message": {
                "message_id": 2,
                "chat": {"id": -1009, "type": "supergroup", "title": "Report Group"},
                "from": {"id": 42},
                "text": "/report",
            },
        })

        self.assertEqual(len(self.api.sent), 1)
        self.assertEqual(self.api.sent[0][0], -1009)
        self.assertIn("当前概览", self.api.sent[0][1])
        self.assertIn("转发：1条", self.api.sent[0][1])
        self.assertIn("较昨日同期：暂无可比数据", self.api.sent[0][1])
        self.assertNotIn("较昨日同期：增加1条", self.api.sent[0][1])

    def test_report_group_deletes_command_now_and_reply_after_45_seconds(self):
        self.make_service()
        timers = []
        events = []
        original_send = self.api.send_message
        original_delete = self.api.delete_message

        def send_message(chat_id, text, disable_web_page_preview=False, reply_markup=None):
            events.append("reply-sent")
            return original_send(chat_id, text, disable_web_page_preview, reply_markup)

        def delete_message(chat_id, message_id):
            events.append(f"deleted-{message_id}")
            return original_delete(chat_id, message_id)

        self.api.send_message = send_message
        self.api.delete_message = delete_message

        class RecordingTimer:
            def __init__(self, interval, function):
                self.interval = interval
                self.function = function
                self.daemon = False
                self.started = False
                timers.append(self)

            def start(self):
                self.started = True

        with patch("threading.Timer", RecordingTimer):
            self.service.handle_update({
                "update_id": 35,
                "message": {
                    "message_id": 44,
                    "chat": {"id": -1009, "type": "supergroup", "title": "Report Group"},
                    "from": {"id": 42},
                    "text": "/report",
                },
            })

        self.assertEqual(events[:2], ["deleted-44", "reply-sent"])
        self.assertEqual(self.api.deleted, [(-1009, 44)])
        self.assertEqual(len(timers), 1)
        self.assertEqual(timers[0].interval, 45)
        self.assertTrue(timers[0].daemon)
        self.assertTrue(timers[0].started)

        timers[0].function()

        self.assertEqual(self.api.deleted, [(-1009, 44), (-1009, 101)])

    def test_group_panel_fallback_reply_is_deleted_after_45_seconds(self):
        self.make_service()
        timers = []

        class RecordingTimer:
            def __init__(self, interval, function):
                self.interval = interval
                self.function = function
                self.daemon = False
                self.started = False
                timers.append(self)

            def start(self):
                self.started = True

        with patch("threading.Timer", RecordingTimer):
            self.service.handle_update({
                "update_id": 36,
                "message": {
                    "message_id": 45,
                    "chat": {"id": -1009, "type": "supergroup", "title": "Report Group"},
                    "from": {"id": 42},
                    "text": "/start",
                },
            })

            def fail_edit(*args, **kwargs):
                raise RuntimeError("edit failed")

            self.api.edit_message_text = fail_edit
            self.send_callback(
                "group:report",
                chat_id=-1009,
                chat_type="supergroup",
                message_id=101,
                update_id=2004,
            )

        self.assertEqual(len(timers), 2)
        self.assertEqual(timers[1].interval, 45)
        self.assertTrue(timers[1].daemon)
        self.assertTrue(timers[1].started)

        timers[1].function()

        self.assertEqual(self.api.deleted[-1], (-1009, 102))

    def test_scheduled_reports_are_never_added_to_command_cleanup(self):
        self.make_service_with_report_channel()
        self.store.set_state("scheduled_report_cover_file_id", "cover-file-id")
        timers = []

        class RecordingTimer:
            def __init__(self, interval, function):
                timers.append((interval, function))

            def start(self):
                pass

        with patch("threading.Timer", RecordingTimer):
            self.service.run_due_reports(datetime(2026, 7, 13, 0, 0, tzinfo=TZ))

        self.assertEqual(timers, [])
        self.assertEqual(self.api.deleted, [])
        self.assertEqual(self.api.sent, [])
        self.assertEqual(len(self.api.photos), 2)
        self.assertTrue(all("周期简报" in photo[2] for photo in self.api.photos))
        self.assertEqual({chat_id for chat_id, _, _ in self.api.photos}, {-1009, -1008})

    def test_report_group_commands_all_show_current_report(self):
        self.make_service()

        for index, command in enumerate(("/start", "/help", "/id", "/report"), start=1):
            self.service.handle_update({
                "update_id": 40 + index,
                "message": {
                    "message_id": index,
                    "chat": {"id": -1009, "type": "supergroup", "title": "Report Group"},
                    "from": {"id": 42},
                    "text": command,
                },
            })

        self.assertEqual(len(self.api.sent), 4)
        for sent, reply_markup in zip(self.api.sent, self.api.sent_reply_markups):
            self.assertEqual(sent[0], -1009)
            self.assertIn("当前概览", sent[1])
            self.assertNotIn("此群已配置完成", sent[1])
            self.assertNotIn("-1009", sent[1])
            self.assertEqual(
                reply_markup["inline_keyboard"],
                [[{"text": "🔄刷新", "callback_data": "group:report"}]],
            )

    def test_daily_weekly_monthly_are_not_manual_commands(self):
        self.make_service()

        help_text = self.service.help_text()
        self.assertNotIn("/report", help_text)
        self.assertNotIn("/check", help_text)
        self.assertIn("SlowLink Assistant", help_text)
        self.assertNotIn("/daily", help_text)
        self.assertNotIn("/weekly", help_text)
        self.assertNotIn("/monthly", help_text)
        self.assertNotIn("/id", help_text)

        self.service.handle_update({
            "update_id": 31,
            "message": {
                "message_id": 1,
                "chat": {"id": 42, "type": "private"},
                "from": {"id": 42},
                "text": "/daily",
            },
        })

        self.assertEqual(len(self.api.sent), 1)
        self.assertIn("SlowLink Assistant", self.api.sent[0][1])
        self.assertIsNotNone(self.api.sent_reply_markups[0])

    def test_owner_can_set_replace_query_and_disable_scheduled_report_cover(self):
        self.make_service()

        self.service.handle_update({
            "update_id": 201,
            "message": {
                "message_id": 1,
                "chat": {"id": 42, "type": "private"},
                "from": {"id": 42},
                "caption": "/cover",
                "photo": [
                    {"file_id": "cover-small", "file_size": 100, "width": 320, "height": 180},
                    {"file_id": "cover-a", "file_size": 1000, "width": 1280, "height": 720},
                ],
            },
        })
        self.assertEqual(self.store.get_state("scheduled_report_cover_file_id"), "cover-a")
        self.assertEqual(self.api.photos[-1][0], 42)
        self.assertEqual(self.api.photos[-1][1], "cover-a")
        self.assertIn("简报封面已更新", self.api.photos[-1][2])
        self.assertIn("📊本周进度（封面预览）", self.api.photos[-1][2])
        self.assertIn("较上周同期：暂无可比数据", self.api.photos[-1][2])
        self.assertNotIn(-1009, [chat_id for chat_id, _, _ in self.api.photos])

        self.service.handle_update({
            "update_id": 202,
            "message": {
                "message_id": 2,
                "chat": {"id": 42, "type": "private"},
                "from": {"id": 42},
                "caption": "/cover",
                "photo": [{"file_id": "cover-b", "width": 1920, "height": 1080}],
            },
        })
        self.assertEqual(self.store.get_state("scheduled_report_cover_file_id"), "cover-b")
        self.assertEqual(self.api.photos[-1][0:2], (42, "cover-b"))

        self.service.handle_update({
            "update_id": 203,
            "message": {
                "message_id": 3,
                "chat": {"id": 42, "type": "private"},
                "from": {"id": 42},
                "text": "/cover",
            },
        })
        self.assertIn("封面管理", self.api.sent[-1][1])
        self.assertIn("状态：已启用", self.api.sent[-1][1])

        self.service.handle_update({
            "update_id": 204,
            "message": {
                "message_id": 4,
                "chat": {"id": 42, "type": "private"},
                "from": {"id": 42},
                "text": "/cover off",
            },
        })
        self.assertIsNone(self.store.get_state("scheduled_report_cover_file_id"))
        self.assertIn("状态：未设置", self.api.sent[-1][1])

    def test_non_owner_cannot_change_scheduled_report_cover(self):
        self.make_service()

        self.service.handle_update({
            "update_id": 205,
            "message": {
                "message_id": 1,
                "chat": {"id": 99, "type": "private"},
                "from": {"id": 99},
                "caption": "/cover",
                "photo": [{"file_id": "not-allowed", "width": 1280, "height": 720}],
            },
        })

        self.assertIsNone(self.store.get_state("scheduled_report_cover_file_id"))
        self.assertEqual(self.api.sent, [])

    def test_cover_preview_failure_keeps_cover_and_reports_private_warning(self):
        self.make_service()
        self.api.fail_photo_for_chats.add(42)

        self.service.handle_update({
            "update_id": 207,
            "message": {
                "message_id": 1,
                "chat": {"id": 42, "type": "private"},
                "from": {"id": 42},
                "caption": "/cover",
                "photo": [{"file_id": "cover-kept", "width": 1280, "height": 720}],
            },
        })

        self.assertEqual(self.store.get_state("scheduled_report_cover_file_id"), "cover-kept")
        self.assertEqual(self.api.photo_attempts[-1][0:2], (42, "cover-kept"))
        self.assertIn("简报封面已更新", self.api.sent[-1][1])
        self.assertIn("私聊预览发送失败", self.api.sent[-1][1])

    def test_non_cover_media_caption_does_not_run_owner_command(self):
        self.make_service()

        self.service.handle_update({
            "update_id": 206,
            "message": {
                "message_id": 1,
                "chat": {"id": 42, "type": "private"},
                "from": {"id": 42},
                "caption": "/report",
                "photo": [{"file_id": "ordinary-photo", "width": 1280, "height": 720}],
            },
        })

        self.assertEqual(self.api.sent, [])
        self.assertIsNone(self.store.get_state("scheduled_report_cover_file_id"))

    def test_cover_command_is_hidden_from_runtime_help(self):
        self.make_service()

        self.assertNotIn("/cover", self.service.help_text())

    def test_private_id_command_is_removed(self):
        self.make_service()

        self.service.handle_update({
            "update_id": 35,
            "message": {
                "message_id": 1,
                "chat": {"id": 42, "type": "private"},
                "from": {"id": 42},
                "text": "/id",
            },
        })

        self.assertEqual(len(self.api.sent), 1)
        self.assertIn("SlowLink Assistant", self.api.sent[0][1])
        self.assertNotIn("42", self.api.sent[0][1])

    def test_unauthorized_group_is_left(self):
        self.make_service()
        self.service.handle_update({
            "update_id": 5,
            "message": {
                "message_id": 1,
                "chat": {"id": -2000, "type": "supergroup", "title": "Bad Group"},
                "from": {"id": 99},
                "text": "/start",
            },
        })

        self.assertEqual(self.api.left, [-2000])
        self.assertEqual(len(self.api.sent), 1)
        self.assertEqual(self.api.sent[0][0], 42)
        self.assertIn("已退出未授权群", self.api.sent[0][1])
        self.assertIn("Bad Group", self.api.sent[0][1])

    def test_configured_report_channel_is_not_left_when_it_is_not_a_source(self):
        self.make_service_with_report_channel()

        self.service.handle_update({
            "update_id": 6,
            "my_chat_member": {
                "chat": {"id": -1008, "type": "channel", "title": "Reports"},
                "new_chat_member": {"status": "administrator"},
            },
        })

        self.assertEqual(self.api.left, [])

    def test_unauthorized_group_notice_is_rate_limited_per_chat(self):
        self.make_service()
        current = {"now": datetime(2026, 7, 10, 12, 0, tzinfo=TZ)}
        self.service.clock = lambda: current["now"]
        chat = {"id": -2000, "type": "supergroup", "title": "Bad Group"}

        for update_id in (50, 51, 52):
            self.service.handle_update({
                "update_id": update_id,
                "message": {
                    "message_id": update_id,
                    "chat": chat,
                    "from": {"id": 99},
                    "text": "/start",
                },
            })

        notices = [text for _, text, _ in self.api.sent if "已退出未授权群" in text]
        self.assertEqual(self.api.left, [-2000, -2000, -2000])
        self.assertEqual(len(notices), 1)

        current["now"] += timedelta(hours=1, minutes=1)
        self.service.handle_update({
            "update_id": 53,
            "message": {
                "message_id": 53,
                "chat": chat,
                "from": {"id": 99},
                "text": "/start",
            },
        })

        notices = [text for _, text, _ in self.api.sent if "已退出未授权群" in text]
        self.assertEqual(len(notices), 2)

    def test_scheduled_daily_report_goes_to_fixed_group_only(self):
        self.make_service()
        self.store.set_state("statistics_coverage_started_at", datetime(2026, 7, 8, 0, 0, tzinfo=TZ).isoformat())
        self.store.record_copy_success("-1001", "Source", 0, "42", 8, datetime(2026, 7, 8, 1, 0, tzinfo=TZ))
        self.store.record_copy_success("-1001", "Source", 1, "42", 9, datetime(2026, 7, 9, 1, 0, tzinfo=TZ))
        self.store.record_moderation_post("-1001", "Source", 2, datetime(2026, 7, 9, 2, 0, tzinfo=TZ))
        self.store.update_moderation_reactions("-1001", 2, 0, 2, datetime(2026, 7, 9, 2, 0, tzinfo=TZ))
        self.store.complete_moderation("-1001", 2, "deleted", "deleted", "auto", datetime(2026, 7, 9, 2, 1, tzinfo=TZ))

        with self.assertLogs("assistant_bot.service", level="INFO") as captured:
            self.service.run_due_reports(datetime(2026, 7, 10, 0, 0, tzinfo=TZ))

        self.assertEqual(self.api.sent[0][0], -1009)
        self.assertIn("📊昨日日报", self.api.sent[0][1])
        self.assertIn("日期：2026-07-09", self.api.sent[0][1])
        self.assertIn("转发：1条", self.api.sent[0][1])
        self.assertIn("较前日：持平", self.api.sent[0][1])
        self.assertIn("高峰时段：01:00-02:00", self.api.sent[0][1])
        self.assertIn("高峰转发：1条", self.api.sent[0][1])
        self.assertIn("首次转发：01:00", self.api.sent[0][1])
        self.assertIn("最后转发：01:00", self.api.sent[0][1])
        self.assertNotIn("内容纠错", self.api.sent[0][1])
        self.assertNotIn("运行状态：", self.api.sent[0][1])
        self.assertNotIn("异常记录：", self.api.sent[0][1])
        self.assertNotIn("约", self.api.sent[0][1])
        self.assertNotIn("仅统计Bot转发，不代表内容正确。", self.api.sent[0][1])
        self.assertEqual(self.api.pinned, [(-1009, 101, True)])
        self.assertNotIn(" 条", self.api.sent[0][1])
        self.assertNotIn("成功率", self.api.sent[0][1])
        self.assertNotIn("复制", self.api.sent[0][1])
        logs = "\n".join(captured.output)
        self.assertIn("日报发送完成：日期=2026-07-09 转发=1条 异常=0次 纠错删除=1条", logs)
        self.assertNotIn("类型=daily", logs)

    def test_all_combined_reports_use_same_cover_and_pin_in_group_and_channel(self):
        self.make_service_with_report_channel()
        self.store.set_state("scheduled_report_cover_file_id", "cover-file-id")
        self.store.set_state("last_report_pin_message_id", "77")
        self.store.set_state("last_report_channel_pin_message_id", "88")
        now = datetime(2026, 6, 1, 0, 0, tzinfo=TZ)

        self.service.run_due_reports(now)

        self.assertEqual([item[0] for item in self.api.photos], [-1009, -1008])
        self.assertEqual(self.api.photos[0][1:], self.api.photos[1][1:])
        caption = self.api.photos[0][2]
        self.assertIn("昨日（", caption)
        self.assertIn("上周（", caption)
        self.assertIn("上月（", caption)
        self.assertEqual(self.api.pinned, [(-1009, 101, True), (-1008, 102, True)])
        self.assertEqual(self.api.unpinned, [(-1009, 77), (-1008, 88)])
        self.assertEqual(self.store.get_state("last_report_pin_message_id"), "101")
        self.assertEqual(self.store.get_state("last_report_channel_pin_message_id"), "102")
        for kind in ("daily", "weekly", "monthly"):
            period = scheduled_period(kind, now)
            self.assertTrue(self.store.was_report_delivered(kind, period.key, "group:-1009"))
            self.assertTrue(self.store.was_report_delivered(kind, period.key, "channel:-1008"))
            self.assertTrue(self.store.was_report_sent(kind, period.key))

    def test_failed_channel_delivery_retries_without_duplicate_group_report(self):
        self.make_service_with_report_channel()
        self.store.set_state("statistics_coverage_started_at", datetime(2026, 7, 8, 0, 0, tzinfo=TZ).isoformat())
        now = datetime(2026, 7, 10, 0, 0, tzinfo=TZ)
        period = scheduled_period("daily", now)
        self.api.fail_send_for_chats.add(-1008)

        self.service.run_due_reports(now)

        self.assertTrue(self.store.was_report_delivered("daily", period.key, "group:-1009"))
        self.assertFalse(self.store.was_report_delivered("daily", period.key, "channel:-1008"))
        self.assertFalse(self.store.was_report_sent("daily", period.key))

        self.api.fail_send_for_chats.clear()
        self.service.run_due_reports(now + timedelta(minutes=1))

        report_messages = [item for item in self.api.sent if item[0] in {-1009, -1008}]
        self.assertEqual([item[0] for item in report_messages], [-1009, -1008])
        self.assertEqual(report_messages[0][1], report_messages[1][1])
        self.assertTrue(self.store.was_report_delivered("daily", period.key, "channel:-1008"))
        self.assertTrue(self.store.was_report_sent("daily", period.key))

    def test_scheduled_daily_report_catches_up_after_exact_minute(self):
        self.make_service()
        self.store.set_state("statistics_coverage_started_at", datetime(2026, 7, 8, 0, 0, tzinfo=TZ).isoformat())
        self.store.record_copy_success("-1001", "Source", 1, "42", 9, datetime(2026, 7, 9, 1, 0, tzinfo=TZ))
        now = datetime(2026, 7, 10, 0, 5, tzinfo=TZ)

        self.service.run_due_reports(now)
        self.service.run_due_reports(now + timedelta(minutes=1))

        self.assertEqual(len(self.api.sent), 1)
        self.assertIn("📊昨日日报", self.api.sent[0][1])
        self.assertIn("日期：2026-07-09", self.api.sent[0][1])

    def test_fresh_install_does_not_backfill_periods_without_history(self):
        self.make_service()

        self.service.run_due_reports(datetime(2026, 7, 10, 12, 0, tzinfo=TZ))

        self.assertEqual(self.api.sent, [])

    def test_scheduled_report_does_not_treat_missing_history_as_zero(self):
        self.make_service()
        self.store.record_copy_success("-1001", "Source", 1, "42", 9, datetime(2026, 7, 9, 1, 0, tzinfo=TZ))

        self.service.run_due_reports(datetime(2026, 7, 10, 0, 0, tzinfo=TZ))

        text = self.api.sent[0][1]
        self.assertIn("数据范围：2026-07-09 01:00至2026-07-09", text)
        self.assertIn("较前日：暂无可比数据", text)
        self.assertNotIn("较前日：增加1条", text)

    def test_scheduled_report_preserves_real_zero_when_history_is_fully_covered(self):
        self.make_service()
        self.store.set_state("statistics_coverage_started_at", datetime(2026, 7, 8, 0, 0, tzinfo=TZ).isoformat())
        self.store.record_copy_success("-1001", "Source", 1, "42", 9, datetime(2026, 7, 9, 1, 0, tzinfo=TZ))

        self.service.run_due_reports(datetime(2026, 7, 10, 0, 0, tzinfo=TZ))

        self.assertIn("较前日：增加1条", self.api.sent[0][1])
        self.assertNotIn("暂无可比数据", self.api.sent[0][1])

    def test_successful_scheduled_report_saves_auditable_snapshot(self):
        self.make_service()
        self.store.set_state("statistics_coverage_started_at", datetime(2026, 7, 8, 0, 0, tzinfo=TZ).isoformat())
        self.store.record_copy_success("-1001", "Source", 1, "42", 9, datetime(2026, 7, 9, 1, 0, tzinfo=TZ))
        now = datetime(2026, 7, 10, 0, 0, tzinfo=TZ)

        self.service.run_due_reports(now)

        period = scheduled_period("daily", now)
        snapshot = self.store.get_report_snapshot("daily", period.key)
        self.assertIsNotNone(snapshot)
        self.assertEqual(snapshot["success_count"], 1)
        self.assertEqual(snapshot["previous_success_count"], 0)
        self.assertEqual(snapshot["comparison_status"], "available")
        self.assertEqual(snapshot["message_id"], 101)
        self.assertIn("较前日：增加1条", snapshot["report_text"])

    def test_scheduled_report_unpins_previous_report_after_new_pin(self):
        self.make_service()
        self.store.record_copy_success("-1001", "Source", 1, "42", 9, datetime(2026, 7, 9, 1, 0, tzinfo=TZ))
        self.store.set_state("last_report_pin_message_id", "77")

        self.service.run_due_reports(datetime(2026, 7, 10, 0, 0, tzinfo=TZ))

        self.assertEqual(self.api.pinned, [(-1009, 101, True)])
        self.assertEqual(self.api.unpinned, [(-1009, 77)])
        self.assertEqual(self.store.get_state("last_report_pin_message_id"), "101")

    def test_scheduled_report_uses_configured_cover_and_pins_photo(self):
        self.make_service()
        self.store.set_state("scheduled_report_cover_file_id", "cover-file-id")

        self.service.run_due_reports(datetime(2026, 7, 10, 0, 0, tzinfo=TZ))

        self.assertEqual(len(self.api.photos), 1)
        self.assertEqual(self.api.photos[0][0], -1009)
        self.assertEqual(self.api.photos[0][1], "cover-file-id")
        self.assertIn("📊昨日日报", self.api.photos[0][2])
        self.assertEqual(self.api.sent, [])
        self.assertEqual(self.api.pinned, [(-1009, 101, True)])

    def test_current_report_stays_text_only_when_cover_is_configured(self):
        self.make_service()
        self.store.set_state("scheduled_report_cover_file_id", "cover-file-id")

        self.service.send_current_report(-1009)

        self.assertEqual(len(self.api.sent), 1)
        self.assertEqual(self.api.sent[0][0], -1009)
        self.assertIn("当前概览", self.api.sent[0][1])
        self.assertEqual(self.api.photo_attempts, [])

    def test_daily_and_weekly_reports_are_combined_into_one_message(self):
        self.make_service()
        now = datetime(2026, 7, 13, 0, 0, tzinfo=TZ)

        with self.assertLogs("assistant_bot.service", level="INFO") as captured:
            self.service.run_due_reports(now)

        self.assertEqual(len(self.api.sent), 1)
        self.assertEqual(self.api.sent[0][0], -1009)
        self.assertEqual(
            self.api.sent[0][1],
            "\n".join(
                [
                    "📊周期简报",
                    "",
                    "昨日（07-12）",
                    "转发：0条｜较前日：持平",
                    "",
                    "上周（07-06至07-12）",
                    "转发：0条｜较前周：暂无可比数据",
                    "数据范围：07-10 09:30至07-12",
                ]
            ),
        )
        self.assertEqual(self.api.pinned, [(-1009, 101, True)])
        daily = scheduled_period("daily", now)
        weekly = scheduled_period("weekly", now)
        self.assertTrue(self.store.was_report_sent("daily", daily.key))
        self.assertTrue(self.store.was_report_sent("weekly", weekly.key))
        logs = "\n".join(captured.output)
        self.assertIn("组合报表发送完成：包含=日报、周报", logs)

    def test_daily_and_monthly_reports_are_combined_into_one_message(self):
        self.make_service()
        now = datetime(2026, 8, 1, 0, 0, tzinfo=TZ)

        self.service.run_due_reports(now)

        self.assertEqual(len(self.api.sent), 1)
        self.assertIn("📊周期简报", self.api.sent[0][1])
        self.assertIn("昨日（07-31）", self.api.sent[0][1])
        self.assertNotIn("上周（", self.api.sent[0][1])
        self.assertIn("上月（07-01至07-31）", self.api.sent[0][1])
        self.assertIn("数据范围：07-10 09:30至07-31", self.api.sent[0][1])
        self.assertNotIn("────────", self.api.sent[0][1])
        self.assertEqual(self.api.pinned, [(-1009, 101, True)])
        daily = scheduled_period("daily", now)
        monthly = scheduled_period("monthly", now)
        self.assertTrue(self.store.was_report_sent("daily", daily.key))
        self.assertTrue(self.store.was_report_sent("monthly", monthly.key))

    def test_daily_weekly_and_monthly_reports_are_combined_into_one_message(self):
        self.make_service()
        now = datetime(2026, 6, 1, 0, 0, tzinfo=TZ)
        self.store.set_state("statistics_coverage_started_at", datetime(2026, 4, 1, 0, 0, tzinfo=TZ).isoformat())
        self.store.record_copy_success(
            "-1001", "Source", 1, "42", 101, datetime(2026, 5, 30, 9, 0, tzinfo=TZ)
        )
        self.store.record_copy_success(
            "-1001", "Source", 2, "42", 102, datetime(2026, 5, 31, 10, 0, tzinfo=TZ)
        )
        self.store.record_copy_success(
            "-1001", "Source", 3, "42", 103, datetime(2026, 5, 31, 10, 30, tzinfo=TZ)
        )

        self.service.run_due_reports(now)

        self.assertEqual(len(self.api.sent), 1)
        self.assertEqual(
            self.api.sent[0][1],
            "\n".join(
                [
                    "📊周期简报",
                    "",
                    "昨日（05-31）",
                    "转发：2条｜较前日：增加1条",
                    "高峰：10:00-11:00",
                    "",
                    "上周（05-25至05-31）",
                    "转发：3条｜较前周：增加3条",
                    "日均：0.4条｜最活跃：05-31",
                    "",
                    "上月（05-01至05-31）",
                    "转发：3条｜较前月：增加3条",
                    "日均：0.1条｜活跃：2天",
                ]
            ),
        )
        self.assertNotIn("────────", self.api.sent[0][1])
        self.assertNotIn("首次转发", self.api.sent[0][1])
        self.assertNotIn("最后转发", self.api.sent[0][1])
        self.assertEqual(self.api.pinned, [(-1009, 101, True)])
        for kind in ("daily", "weekly", "monthly"):
            period = scheduled_period(kind, now)
            self.assertTrue(self.store.was_report_sent(kind, period.key))

    def test_combined_reports_use_one_cover_photo(self):
        self.make_service()
        self.store.set_state("scheduled_report_cover_file_id", "cover-file-id")
        now = datetime(2026, 6, 1, 0, 0, tzinfo=TZ)

        self.service.run_due_reports(now)

        self.assertEqual(len(self.api.photos), 1)
        self.assertEqual(self.api.photos[0][1], "cover-file-id")
        self.assertEqual(self.api.photos[0][2].count("📊"), 1)
        self.assertIn("📊周期简报", self.api.photos[0][2])
        self.assertIn("昨日（", self.api.photos[0][2])
        self.assertIn("上周（", self.api.photos[0][2])
        self.assertIn("上月（", self.api.photos[0][2])
        self.assertLessEqual(len(self.api.photos[0][2]), 1024)
        self.assertEqual(self.api.sent, [])
        self.assertEqual(self.api.pinned, [(-1009, 101, True)])

    def test_combined_report_failure_marks_no_period_as_sent(self):
        self.make_service()
        self.api.fail_send_for_chats.add(-1009)
        now = datetime(2026, 7, 13, 0, 0, tzinfo=TZ)

        self.service.run_due_reports(now)

        self.assertEqual(len(self.api.sent), 1)
        self.assertEqual(self.api.sent[0][0], 42)
        self.assertIn("组合报表发送失败", self.api.sent[0][1])
        for kind in ("daily", "weekly"):
            period = scheduled_period(kind, now)
            self.assertFalse(self.store.was_report_sent(kind, period.key))

    def test_recent_text_uses_forwarding_terms(self):
        self.make_service()
        self.store.record_copy_success("-1001", "Source", 1, "42", 9, datetime(2026, 7, 10, 1, 0, tzinfo=TZ))
        text = self.service.recent_text()

        self.assertIn("最近记录", text)
        self.assertIn("01:00｜转发成功｜Source#1", text)
        self.assertNotIn("|", text)
        self.assertNotIn("  ", text)
        self.assertNotIn("T", text)
        self.assertNotIn("+08:00", text)
        self.assertNotIn("复制", text)

    def test_recent_command_accepts_limited_count(self):
        self.make_service()
        for index in range(1, 13):
            self.store.record_copy_success("-1001", "Source", index, "42", index, datetime(2026, 7, 10, index % 12, 0, tzinfo=TZ))

        self.service.handle_update({
            "update_id": 38,
            "message": {
                "message_id": 1,
                "chat": {"id": 42, "type": "private"},
                "from": {"id": 42},
                "text": "/recent 20",
            },
        })

        lines = self.api.sent[0][1].splitlines()
        self.assertEqual(len(lines), 13)
        self.assertIn("Source#12", self.api.sent[0][1])

    def test_check_command_reports_health_and_recent_forward(self):
        self.make_service()
        self.store.record_copy_success("-1001", "Source", 1, "42", 9, datetime(2026, 7, 10, 1, 0, tzinfo=TZ))

        self.service.handle_update({
            "update_id": 37,
            "message": {
                "message_id": 1,
                "chat": {"id": 42, "type": "private"},
                "from": {"id": 42},
                "text": "/check",
            },
        })

        self.assertEqual(len(self.api.sent), 1)
        text = self.api.sent[0][1]
        self.assertIn("自检完成", text)
        self.assertIn("Bot：正常", text)
        self.assertIn("数据库：正常", text)
        self.assertIn("守护：未知", text)
        self.assertIn("源频道：2个", text)
        self.assertIn("报表群：已配置", text)
        self.assertEqual(self.api.get_chat_member_calls, [(-1009, 777)])
        self.assertIn("今日：转发1条/失败0条", text)
        self.assertIn("最近：01:00", text)
        self.assertNotIn(" / ", text)
        self.assertNotIn(" 个", text)

    def test_status_reports_channel_post_and_pin_permission(self):
        self.make_service_with_report_channel()

        text = self.service.status_text()

        self.assertIn("简报频道：已配置", text)
        self.assertEqual(self.api.get_chat_member_calls, [(-1009, 777), (-1008, 777)])

        self.api.get_chat_member_calls.clear()
        self.api.chat_member = {
            "status": "administrator",
            "can_post_messages": True,
            "can_edit_messages": False,
        }

        text = self.service.check_text()

        self.assertIn("简报频道：异常", text)

    def test_check_command_reports_watchdog_status_from_status_file(self):
        temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(temp_dir.cleanup)
        tmp = Path(temp_dir.name)
        data_path = tmp / "assistant.sqlite3"
        self.api = FakeAPI()
        self.store = EventStore(data_path)
        self.service = AssistantService(
            make_config_with_data_path(data_path),
            self.api,
            self.store,
            clock=lambda: datetime(2026, 7, 10, 12, 0, tzinfo=TZ),
        )
        (tmp / "watchdog_status.txt").write_text(
            "\n".join(
                [
                    "updated_at_ts=1783655990",
                    "updated_at=2026-07-10 11:59:50",
                    "container=slowlink_assistant_bot",
                    "cpu=1",
                ]
            ),
            encoding="utf-8",
        )

        self.service.handle_update({
            "update_id": 41,
            "message": {
                "message_id": 1,
                "chat": {"id": 42, "type": "private"},
                "from": {"id": 42},
                "text": "/check",
            },
        })

        self.assertIn("守护：正常", self.api.sent[0][1])

    def test_check_command_reports_stale_watchdog_status_as_problem(self):
        temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(temp_dir.cleanup)
        tmp = Path(temp_dir.name)
        data_path = tmp / "assistant.sqlite3"
        self.api = FakeAPI()
        self.store = EventStore(data_path)
        self.service = AssistantService(
            make_config_with_data_path(data_path),
            self.api,
            self.store,
            clock=lambda: datetime(2026, 7, 10, 12, 0, tzinfo=TZ),
        )
        (tmp / "watchdog_status.txt").write_text(
            "updated_at_ts=1783650000\nupdated_at=2026-07-10 10:20:00\n",
            encoding="utf-8",
        )

        self.service.handle_update({
            "update_id": 42,
            "message": {
                "message_id": 1,
                "chat": {"id": 42, "type": "private"},
                "from": {"id": 42},
                "text": "/check",
            },
        })

        self.assertIn("守护：异常", self.api.sent[0][1])

    def test_check_command_reports_group_permission_problem(self):
        self.make_service()
        self.api.chat_member = {"status": "restricted", "can_send_messages": False}

        self.service.handle_update({
            "update_id": 39,
            "message": {
                "message_id": 1,
                "chat": {"id": 42, "type": "private"},
                "from": {"id": 42},
                "text": "/check",
            },
        })

        self.assertIn("报表群：异常", self.api.sent[0][1])

    def test_single_failure_is_recorded_without_owner_notice(self):
        self.make_service()

        def fail_copy(*args, **kwargs):
            raise RuntimeError("bad request")

        self.api.copy_message = fail_copy
        self.service.handle_update({
            "update_id": 40,
            "channel_post": {
                "message_id": 88,
                "chat": {"id": -1001, "type": "channel", "title": "Source"},
                "text": "https://t.me/ShardCatDen/88",
            },
        })

        self.assertEqual(self.api.sent, [])
        stats = self.store.stats_between(datetime(2026, 7, 10, 0, 0, tzinfo=TZ), datetime(2026, 7, 11, 0, 0, tzinfo=TZ))
        self.assertEqual(stats.failure_count, 1)

    def test_three_consecutive_failures_notify_once_and_recovery_is_reported(self):
        self.make_service()

        def fail_copy(*args, **kwargs):
            raise RuntimeError("bad request")

        self.api.copy_message = fail_copy
        for message_id in (88, 89, 90, 91):
            self.service.handle_update({
                "update_id": message_id,
                "channel_post": {
                    "message_id": message_id,
                    "chat": {"id": -1001, "type": "channel", "title": "Source"},
                    "text": f"https://t.me/ShardCatDen/{message_id}",
                },
            })

        self.assertEqual(len(self.api.sent), 1)
        self.assertEqual(self.api.sent[0][0], 42)
        self.assertIn("转发连续失败", self.api.sent[0][1])
        self.assertIn("连续：3次", self.api.sent[0][1])
        self.assertNotIn("复制", self.api.sent[0][1])

        self.api.copy_message = FakeAPI().copy_message
        self.service.handle_update({
            "update_id": 92,
            "channel_post": {
                "message_id": 92,
                "chat": {"id": -1001, "type": "channel", "title": "Source"},
                "text": "https://t.me/ShardCatDen/92",
            },
        })

        self.assertEqual(len(self.api.sent), 2)
        self.assertIn("转发已恢复", self.api.sent[1][1])
        self.assertNotIn("复制", self.api.sent[1][1])

    def test_same_failure_notice_is_rate_limited_for_one_hour(self):
        self.make_service()
        current = {"now": datetime(2026, 7, 10, 12, 0, tzinfo=TZ)}
        self.service.clock = lambda: current["now"]

        def fail_copy(*args, **kwargs):
            raise RuntimeError("bad request")

        self.api.copy_message = fail_copy
        for message_id in (1, 2, 3):
            self.service.handle_update({
                "update_id": message_id,
                "channel_post": {
                    "message_id": message_id,
                    "chat": {"id": -1001, "type": "channel", "title": "Source"},
                    "text": f"https://t.me/ShardCatDen/{message_id}",
                },
            })
        self.assertEqual(len(self.api.sent), 1)

        self.service.consecutive_copy_failures = 0
        self.service.copy_failure_alert_active = False
        current["now"] = datetime(2026, 7, 10, 12, 30, tzinfo=TZ)
        for message_id in (4, 5, 6):
            self.service.handle_update({
                "update_id": message_id,
                "channel_post": {
                    "message_id": message_id,
                    "chat": {"id": -1001, "type": "channel", "title": "Source"},
                    "text": f"https://t.me/ShardCatDen/{message_id}",
                },
            })
        self.assertEqual(len(self.api.sent), 1)

        self.service.consecutive_copy_failures = 0
        self.service.copy_failure_alert_active = False
        current["now"] = datetime(2026, 7, 10, 13, 1, tzinfo=TZ)
        for message_id in (7, 8, 9):
            self.service.handle_update({
                "update_id": message_id,
                "channel_post": {
                    "message_id": message_id,
                    "chat": {"id": -1001, "type": "channel", "title": "Source"},
                    "text": f"https://t.me/ShardCatDen/{message_id}",
                },
            })
        self.assertEqual(len(self.api.sent), 2)

    def test_report_send_failure_notifies_owner_and_is_not_marked_sent(self):
        self.make_service()
        self.api.fail_send_for_chats.add(-1009)

        self.service.run_due_reports(datetime(2026, 7, 10, 0, 0, tzinfo=TZ))

        self.assertEqual(len(self.api.sent), 1)
        self.assertEqual(self.api.sent[0][0], 42)
        self.assertIn("日报发送失败", self.api.sent[0][1])
        period = __import__("assistant_bot.reports", fromlist=["scheduled_period"]).scheduled_period("daily", datetime(2026, 7, 10, 0, 0, tzinfo=TZ))
        self.assertFalse(self.store.was_report_sent("daily", period.key))

    def test_cover_failure_falls_back_to_text_and_marks_report_sent(self):
        self.make_service()
        self.store.set_state("scheduled_report_cover_file_id", "invalid-cover")
        self.api.fail_photo_for_chats.add(-1009)
        now = datetime(2026, 7, 10, 0, 0, tzinfo=TZ)

        with self.assertLogs("assistant_bot.service", level="WARNING") as captured:
            self.service.run_due_reports(now)

        self.assertEqual(len(self.api.photo_attempts), 1)
        self.assertEqual(self.api.sent[0][0], -1009)
        self.assertIn("📊昨日日报", self.api.sent[0][1])
        self.assertEqual(self.api.sent[1][0], 42)
        self.assertIn("封面发送失败，已改发纯文字", self.api.sent[1][1])
        self.assertEqual(self.api.pinned, [(-1009, 101, True)])
        self.assertTrue(self.store.was_report_sent("daily", scheduled_period("daily", now).key))
        self.assertIn("日报封面发送失败，已改发纯文字", "\n".join(captured.output))

    def test_overlong_photo_caption_falls_back_to_text(self):
        self.make_service()
        self.store.set_state("scheduled_report_cover_file_id", "cover-file-id")
        message_text = "文" * 1025

        self.service._send_scheduled_report(message_text, "日报", "日期：2026-07-09")

        self.assertEqual(self.api.photo_attempts, [])
        self.assertEqual(self.api.sent[0], (-1009, message_text, True))
        self.assertEqual(self.api.sent[1][0], 42)
        self.assertIn("简报文字超过图片说明长度限制", self.api.sent[1][1])

    def test_cover_and_text_failure_leave_report_unmarked(self):
        self.make_service()
        self.store.set_state("scheduled_report_cover_file_id", "invalid-cover")
        self.api.fail_photo_for_chats.add(-1009)
        self.api.fail_send_for_chats.add(-1009)
        now = datetime(2026, 7, 10, 0, 0, tzinfo=TZ)

        self.service.run_due_reports(now)

        self.assertEqual(len(self.api.photo_attempts), 1)
        self.assertEqual(len(self.api.sent), 1)
        self.assertEqual(self.api.sent[0][0], 42)
        self.assertIn("日报发送失败", self.api.sent[0][1])
        self.assertEqual(self.api.pinned, [])
        self.assertFalse(self.store.was_report_sent("daily", scheduled_period("daily", now).key))

    def test_report_pin_failure_notifies_owner_but_marks_sent(self):
        self.make_service()
        self.api.fail_pin = True

        self.service.run_due_reports(datetime(2026, 7, 10, 0, 0, tzinfo=TZ))

        self.assertEqual(len(self.api.sent), 2)
        self.assertEqual(self.api.sent[0][0], -1009)
        self.assertEqual(self.api.sent[1][0], 42)
        self.assertIn("日报置顶失败", self.api.sent[1][1])

    def test_run_due_reports_prunes_old_events_once_per_day(self):
        self.make_service()
        self.store.record_copy_success("-1001", "Old", 1, "42", 9, datetime(2026, 3, 1, 1, 0, tzinfo=TZ))
        self.store.record_copy_success("-1001", "Recent", 2, "42", 10, datetime(2026, 7, 10, 1, 0, tzinfo=TZ))

        self.service.run_due_reports(datetime(2026, 7, 10, 12, 0, tzinfo=TZ))
        self.service.run_due_reports(datetime(2026, 7, 10, 13, 0, tzinfo=TZ))

        all_stats = self.store.stats_between(datetime(2026, 1, 1, 0, 0, tzinfo=TZ), datetime(2026, 8, 1, 0, 0, tzinfo=TZ))
        self.assertEqual(all_stats.success_count, 1)
        self.assertEqual(self.service.last_cleanup_date.isoformat(), "2026-07-10")


if __name__ == "__main__":
    unittest.main()
