import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from assistant_bot.config import BotConfig
from assistant_bot.reports import scheduled_period
from assistant_bot.service import AssistantService
from assistant_bot.store import EventStore


TZ = ZoneInfo("Asia/Shanghai")


class FakeAPI:
    def __init__(self):
        self.copied = []
        self.sent = []
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

    def send_source_post(self, message_id=55, at=None):
        at = at or datetime(2026, 7, 10, 12, 0, tzinfo=TZ)
        self.service.handle_update({
            "update_id": message_id,
            "channel_post": {
                "message_id": message_id,
                "date": int(at.timestamp()),
                "chat": {"id": -1001, "type": "channel", "title": "Source"},
                "text": "test",
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
                "text": "Homeless\nhttps://t.me/ShardCatDen/555090",
            },
        }

        self.service.handle_update(update)

        self.assertEqual(self.api.copied, [(42, -1001, 55)])
        stats = self.store.stats_between(datetime(2026, 7, 10, 0, 0, tzinfo=TZ), datetime(2026, 7, 11, 0, 0, tzinfo=TZ))
        self.assertEqual(stats.success_count, 1)

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
        self.assertIn("今日转发1条", self.api.sent[0][1])

    def test_report_group_id_command_confirms_configuration_without_exposing_id(self):
        self.make_service()

        self.service.handle_update({
            "update_id": 34,
            "message": {
                "message_id": 1,
                "chat": {"id": -1009, "type": "supergroup", "title": "Report Group"},
                "from": {"id": 42},
                "text": "/id",
            },
        })

        self.assertEqual(len(self.api.sent), 1)
        self.assertEqual(self.api.sent[0][0], -1009)
        self.assertIn("此群已配置完成", self.api.sent[0][1])
        self.assertNotIn("-1009", self.api.sent[0][1])
        self.assertNotIn("ID", self.api.sent[0][1])

    def test_daily_weekly_monthly_are_not_manual_commands(self):
        self.make_service()

        help_text = self.service.help_text()
        self.assertIn("/report", help_text)
        self.assertIn("/check", help_text)
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
        self.assertIn("未知命令", self.api.sent[0][1])

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
        self.assertIn("未知命令", self.api.sent[0][1])
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
        self.store.record_copy_success("-1001", "Source", 1, "42", 9, datetime(2026, 7, 9, 1, 0, tzinfo=TZ))
        self.store.record_moderation_post("-1001", "Source", 2, datetime(2026, 7, 9, 2, 0, tzinfo=TZ))
        self.store.update_moderation_reactions("-1001", 2, 0, 2, datetime(2026, 7, 9, 2, 0, tzinfo=TZ))
        self.store.complete_moderation("-1001", 2, "deleted", "deleted", "auto", datetime(2026, 7, 9, 2, 1, tzinfo=TZ))

        with self.assertLogs("assistant_bot.service", level="INFO") as captured:
            self.service.run_due_reports(datetime(2026, 7, 10, 0, 0, tzinfo=TZ))

        self.assertEqual(self.api.sent[0][0], -1009)
        self.assertIn("📊日报", self.api.sent[0][1])
        self.assertIn("日期：2026-07-09", self.api.sent[0][1])
        self.assertIn("转发：1条", self.api.sent[0][1])
        self.assertIn("内容纠错：删除1条", self.api.sent[0][1])
        self.assertIn("运行状态：正常", self.api.sent[0][1])
        self.assertNotIn("约", self.api.sent[0][1])
        self.assertNotIn("仅统计Bot转发，不代表内容正确。", self.api.sent[0][1])
        self.assertEqual(self.api.pinned, [(-1009, 101, True)])
        self.assertNotIn(" 条", self.api.sent[0][1])
        self.assertNotIn("成功率", self.api.sent[0][1])
        self.assertNotIn("复制", self.api.sent[0][1])
        logs = "\n".join(captured.output)
        self.assertIn("日报发送完成：日期=2026-07-09 转发=1条 异常=0次 纠错删除=1条", logs)
        self.assertNotIn("类型=daily", logs)

    def test_scheduled_report_unpins_previous_report_after_new_pin(self):
        self.make_service()
        self.store.record_copy_success("-1001", "Source", 1, "42", 9, datetime(2026, 7, 9, 1, 0, tzinfo=TZ))
        self.store.set_state("last_report_pin_message_id", "77")

        self.service.run_due_reports(datetime(2026, 7, 10, 0, 0, tzinfo=TZ))

        self.assertEqual(self.api.pinned, [(-1009, 101, True)])
        self.assertEqual(self.api.unpinned, [(-1009, 77)])
        self.assertEqual(self.store.get_state("last_report_pin_message_id"), "101")

    def test_daily_and_weekly_reports_are_combined_into_one_message(self):
        self.make_service()
        now = datetime(2026, 7, 13, 0, 0, tzinfo=TZ)

        with self.assertLogs("assistant_bot.service", level="INFO") as captured:
            self.service.run_due_reports(now)

        self.assertEqual(len(self.api.sent), 1)
        self.assertEqual(self.api.sent[0][0], -1009)
        self.assertIn("📊日报", self.api.sent[0][1])
        self.assertIn("📊周报", self.api.sent[0][1])
        self.assertNotIn("📊月报", self.api.sent[0][1])
        self.assertIn("────────", self.api.sent[0][1])
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
        self.assertIn("📊日报", self.api.sent[0][1])
        self.assertNotIn("📊周报", self.api.sent[0][1])
        self.assertIn("📊月报", self.api.sent[0][1])
        self.assertEqual(self.api.pinned, [(-1009, 101, True)])
        daily = scheduled_period("daily", now)
        monthly = scheduled_period("monthly", now)
        self.assertTrue(self.store.was_report_sent("daily", daily.key))
        self.assertTrue(self.store.was_report_sent("monthly", monthly.key))

    def test_daily_weekly_and_monthly_reports_are_combined_into_one_message(self):
        self.make_service()
        now = datetime(2026, 6, 1, 0, 0, tzinfo=TZ)

        self.service.run_due_reports(now)

        self.assertEqual(len(self.api.sent), 1)
        self.assertEqual(self.api.sent[0][1].count("📊"), 3)
        self.assertIn("📊日报", self.api.sent[0][1])
        self.assertIn("📊周报", self.api.sent[0][1])
        self.assertIn("📊月报", self.api.sent[0][1])
        self.assertEqual(self.api.pinned, [(-1009, 101, True)])
        for kind in ("daily", "weekly", "monthly"):
            period = scheduled_period(kind, now)
            self.assertTrue(self.store.was_report_sent(kind, period.key))

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
                "text": "x",
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
                    "text": "x",
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
                "text": "x",
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
                    "text": "x",
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
                    "text": "x",
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
                    "text": "x",
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
