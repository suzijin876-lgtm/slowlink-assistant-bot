from __future__ import annotations

import logging
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Callable, Any
from zoneinfo import ZoneInfo

from . import __version__
from .config import BotConfig, chat_ref_for_api, chat_username_ref, normalize_chat_ref
from .reports import (
    format_display_time,
    format_period_label,
    format_report,
    manual_period,
    report_name,
    report_period_field,
    scheduled_period,
    should_run_report,
)
from .store import EventStore


LOG = logging.getLogger(__name__)
COPY_FAILURE_ALERT_THRESHOLD = 3
EVENT_RETENTION_DAYS = 90
UNAUTHORIZED_CHAT_NOTICE_INTERVAL = timedelta(hours=1)
WATCHDOG_STATUS_MAX_AGE = timedelta(seconds=120)
LAST_REPORT_PIN_STATE_KEY = "last_report_pin_message_id"
MODERATION_MIN_DOWNVOTES = 2
MODERATION_MIN_POOPS = 2
MODERATION_DELETE_DELAY = timedelta(minutes=1)
MODERATION_POST_MAX_AGE = timedelta(hours=1)
MODERATION_AUTO_DELETE_LIMIT = 4
MODERATION_AUTO_DELETE_WINDOW = timedelta(minutes=10)


class AssistantService:
    def __init__(self, config: BotConfig, api, store: EventStore, clock: Callable[[], datetime] | None = None):
        self.config = config
        self.api = api
        self.store = store
        self.tz = ZoneInfo(config.timezone)
        self.started_at = datetime.now(self.tz)
        self.clock = clock or (lambda: datetime.now(self.tz))
        self.consecutive_copy_failures = 0
        self.copy_failure_alert_active = False
        self.copy_failure_alert_times: dict[str, datetime] = {}
        self.unauthorized_chat_notice_times: dict[str, datetime] = {}
        self.last_cleanup_date: date | None = None
        self.last_backup_date: date | None = None

    def _now(self) -> datetime:
        now = self.clock()
        if now.tzinfo is None:
            return now.replace(tzinfo=self.tz)
        return now.astimezone(self.tz)

    def handle_update(self, update: dict[str, Any]) -> None:
        try:
            if "channel_post" in update:
                self._handle_channel_post(update["channel_post"])
            elif "message" in update:
                self._handle_message(update["message"])
            elif "my_chat_member" in update:
                self._handle_chat_member(update["my_chat_member"])
            elif "message_reaction_count" in update:
                self._handle_reaction_count(update["message_reaction_count"])
            elif "callback_query" in update:
                self._handle_callback_query(update["callback_query"])
        finally:
            update_id = update.get("update_id")
            if update_id is not None:
                self.store.set_offset(int(update_id) + 1)

    def _chat_allowed_as_source(self, chat: dict[str, Any]) -> bool:
        refs = {normalize_chat_ref(chat)}
        username = chat_username_ref(chat)
        if username:
            refs.add(username)
        return bool(refs & self.config.source_channel_refs)

    def verify_source_reactions(self) -> None:
        required = {"👎", "💩"}
        for source_ref in sorted(self.config.source_channel_refs):
            target = chat_ref_for_api(source_ref)
            try:
                chat = self.api.get_chat(target) or {}
            except Exception as exc:
                LOG.warning("频道反应检查失败：频道=%s 原因=%s", source_ref, exc)
                continue
            available = chat.get("available_reactions")
            if available is None:
                LOG.info("频道反应检查正常：频道=%s 可用=全部表情", source_ref)
                continue
            emojis = {
                str(item.get("emoji") or "")
                for item in available
                if isinstance(item, dict) and item.get("type") == "emoji"
            }
            missing = required - emojis
            if missing:
                LOG.warning(
                    "频道反应设置不完整：频道=%s 缺少=%s，请在Telegram频道设置中启用",
                    source_ref,
                    "、".join(sorted(missing)),
                )
                continue
            LOG.info("频道反应检查正常：频道=%s 可用=👎、💩", source_ref)

    def _handle_channel_post(self, message: dict[str, Any]) -> None:
        chat = message.get("chat") or {}
        if not self._chat_allowed_as_source(chat):
            return
        source_chat_id = str(chat.get("id") or "")
        source_title = str(chat.get("title") or chat.get("username") or source_chat_id)
        message_id = int(message.get("message_id") or 0)
        if not source_chat_id or not message_id:
            return
        if "pinned_message" in message:
            LOG.info("跳过频道置顶通知：来源=%s 消息=%s", source_title, message_id)
            return

        try:
            posted_at = datetime.fromtimestamp(int(message.get("date") or 0), self.tz)
        except (TypeError, ValueError, OSError):
            posted_at = self._now()
        if int(message.get("date") or 0) <= 0:
            posted_at = self._now()
        self.store.record_moderation_post(source_chat_id, source_title, message_id, posted_at)

        try:
            result = self.api.copy_message(self.config.owner_user_id, int(source_chat_id), message_id)
            copied_id = int((result or {}).get("message_id") or 0) or None
            self.store.record_copy_success(source_chat_id, source_title, message_id, str(self.config.owner_user_id), copied_id, self._now())
            self._handle_copy_recovery(source_title, message_id)
            LOG.info("已复制频道消息：来源=%s 消息=%s", source_chat_id, message_id)
        except Exception as exc:
            error = str(exc)
            self.store.record_copy_failure(source_chat_id, source_title, message_id, str(self.config.owner_user_id), error, self._now())
            LOG.warning("复制消息失败：来源=%s 消息=%s 原因=%s", source_chat_id, message_id, error)
            self._handle_copy_failure(source_title, message_id, error)

    def _handle_reaction_count(self, update: dict[str, Any]) -> None:
        chat = update.get("chat") or {}
        if not self._chat_allowed_as_source(chat):
            return
        source_chat_id = str(chat.get("id") or "")
        message_id = int(update.get("message_id") or 0)
        if not source_chat_id or not message_id:
            return
        post = self.store.get_moderation_post(source_chat_id, message_id)
        if not post:
            return

        now = self._now()
        if now.timestamp() - float(post.get("posted_at_ts") or 0) > MODERATION_POST_MAX_AGE.total_seconds():
            return
        thumbs_up, thumbs_down, poop_count = self._reaction_counts(update.get("reactions") or [])
        post = self.store.update_moderation_reactions(
            source_chat_id,
            message_id,
            thumbs_up,
            thumbs_down,
            now,
            poop_count=poop_count,
        )
        if not post:
            return

        status = str(post.get("status") or "")
        if status in {"deleted", "kept", "failed", "protected"}:
            return
        if poop_count >= MODERATION_MIN_POOPS:
            self._automatic_delete_or_protect(post, "poop", now)
            return
        should_delete = self._downvote_threshold_met(thumbs_down)
        if status == "pending":
            if not should_delete and self.store.cancel_moderation_pending(source_chat_id, message_id, now):
                self._update_moderation_notice(
                    post,
                    "✅自动删除已取消\n"
                    f"消息：#{message_id}\n"
                    f"👎{thumbs_down}｜💩{poop_count}\n"
                    "原因：票数已不满足删除条件",
                )
                LOG.info("👎自动删除已取消：消息=%s 👎=%s 💩=%s", message_id, thumbs_down, poop_count)
            return
        if status != "watching" or not should_delete:
            return

        delete_after = now + MODERATION_DELETE_DELAY
        if not self.store.set_moderation_pending(source_chat_id, message_id, delete_after, now):
            return
        notice_text = self._pending_moderation_text(post, thumbs_down, poop_count)
        try:
            result = self.api.send_message(
                self.config.owner_user_id,
                notice_text,
                reply_markup=self._moderation_keyboard(source_chat_id, message_id),
            )
        except Exception as exc:
            self.store.complete_moderation(source_chat_id, message_id, "failed", "failed", "notice", now)
            LOG.warning("待删除通知发送失败：消息=%s 原因=%s", message_id, exc)
            return
        notice_message_id = int((result or {}).get("message_id") or 0)
        if notice_message_id:
            self.store.set_moderation_notice(source_chat_id, message_id, notice_message_id, now)
        LOG.warning(
            "👎进入待删除：消息=%s 👎=%s 💩=%s 倒计时=%s秒",
            message_id,
            thumbs_down,
            poop_count,
            int(MODERATION_DELETE_DELAY.total_seconds()),
        )

    def _handle_callback_query(self, query: dict[str, Any]) -> None:
        callback_id = str(query.get("id") or "")
        user_id = int((query.get("from") or {}).get("id") or 0)
        if user_id != self.config.owner_user_id:
            self._answer_callback(callback_id, "无权限", show_alert=True)
            return
        parts = str(query.get("data") or "").split(":")
        if len(parts) != 4 or parts[0] != "mod" or parts[1] not in {"keep", "delete"}:
            self._answer_callback(callback_id, "操作无效", show_alert=True)
            return
        action, source_chat_id = parts[1], parts[2]
        try:
            message_id = int(parts[3])
        except ValueError:
            self._answer_callback(callback_id, "操作无效", show_alert=True)
            return
        post = self.store.get_moderation_post(source_chat_id, message_id)
        if not post or str(post.get("status") or "") not in {"pending", "protected"}:
            self._answer_callback(callback_id, "该消息已处理")
            return
        now = self._now()
        if action == "keep":
            self.store.complete_moderation(source_chat_id, message_id, "kept", "kept", "owner", now)
            self._update_moderation_notice(
                post,
                "✅帖子已保留\n"
                f"消息：#{message_id}\n"
                f"👎{int(post.get('thumbs_down') or 0)}｜💩{int(post.get('poop_count') or 0)}\n"
                "处理：主人确认保留",
            )
            LOG.info("帖子已保留：消息=%s 原因=主人确认", message_id)
            self._answer_callback(callback_id, "已保留")
            return

        deleted = self._delete_moderation_post(post, "owner", now)
        self._answer_callback(callback_id, "已删除" if deleted else "删除失败", show_alert=not deleted)

    def _reaction_counts(self, reactions: list[dict]) -> tuple[int, int, int]:
        thumbs_up = 0
        thumbs_down = 0
        poop_count = 0
        for reaction in reactions:
            reaction_type = reaction.get("type") or {}
            if reaction_type.get("type") != "emoji":
                continue
            emoji = reaction_type.get("emoji")
            count = max(0, int(reaction.get("total_count") or 0))
            if emoji == "👍":
                thumbs_up = count
            elif emoji == "👎":
                thumbs_down = count
            elif emoji == "💩":
                poop_count = count
        return thumbs_up, thumbs_down, poop_count

    def _downvote_threshold_met(self, thumbs_down: int) -> bool:
        return thumbs_down >= MODERATION_MIN_DOWNVOTES

    def _moderation_keyboard(self, source_chat_id: str, message_id: int) -> dict:
        return {
            "inline_keyboard": [
                [
                    {"text": "保留", "callback_data": f"mod:keep:{source_chat_id}:{message_id}"},
                    {"text": "立即删除", "callback_data": f"mod:delete:{source_chat_id}:{message_id}"},
                ]
            ]
        }

    def _pending_moderation_text(self, post: dict, thumbs_down: int, poop_count: int) -> str:
        return "\n".join(
            [
                "⚠️帖子进入待删除",
                f"频道：{post.get('source_title') or post.get('source_chat_id')}",
                f"消息：#{post.get('source_message_id')}",
                f"👎{thumbs_down}｜💩{poop_count}",
                f"倒计时：{int(MODERATION_DELETE_DELAY.total_seconds())}秒",
            ]
        )

    def _answer_callback(self, callback_id: str, text: str, show_alert: bool = False) -> None:
        if not callback_id:
            return
        try:
            self.api.answer_callback_query(callback_id, text, show_alert=show_alert)
        except Exception:
            pass

    def _update_moderation_notice(self, post: dict, text: str, keep_buttons: bool = False) -> None:
        notice_message_id = int(post.get("owner_notice_message_id") or 0)
        reply_markup = self._moderation_keyboard(str(post.get("source_chat_id")), int(post.get("source_message_id") or 0)) if keep_buttons else {"inline_keyboard": []}
        if notice_message_id:
            try:
                self.api.edit_message_text(
                    self.config.owner_user_id,
                    notice_message_id,
                    text,
                    reply_markup=reply_markup,
                )
                return
            except Exception:
                pass
        self._send_owner_notice(text)

    def _delete_moderation_post(self, post: dict, reason: str, now: datetime) -> bool:
        source_chat_id = str(post.get("source_chat_id") or "")
        message_id = int(post.get("source_message_id") or 0)
        try:
            self.api.delete_message(chat_ref_for_api(source_chat_id), message_id)
        except Exception as exc:
            self.store.complete_moderation(source_chat_id, message_id, "failed", "failed", reason, now)
            self._update_moderation_notice(
                post,
                "❌帖子删除失败\n"
                f"消息：#{message_id}\n"
                f"原因：{exc}",
            )
            LOG.warning("帖子删除失败：消息=%s 原因=%s", message_id, exc)
            return False
        self.store.complete_moderation(source_chat_id, message_id, "deleted", "deleted", reason, now)
        action = "自动删除" if reason == "auto" else "立即删除" if reason == "owner" else "直接删除"
        notice_message_id = int(post.get("owner_notice_message_id") or 0)
        if reason != "poop" or notice_message_id:
            self._update_moderation_notice(
                post,
                f"🗑帖子已{action}\n"
                f"消息：#{message_id}\n"
                f"👎{int(post.get('thumbs_down') or 0)}｜💩{int(post.get('poop_count') or 0)}",
            )
        log_action = "💩直接删除" if reason == "poop" else action
        LOG.info(
            "%s完成：消息=%s 👎=%s 💩=%s",
            log_action,
            message_id,
            int(post.get("thumbs_down") or 0),
            int(post.get("poop_count") or 0),
        )
        return True

    def _automatic_delete_or_protect(self, post: dict, reason: str, now: datetime) -> bool:
        source_chat_id = str(post.get("source_chat_id") or "")
        message_id = int(post.get("source_message_id") or 0)
        thumbs_down = int(post.get("thumbs_down") or 0)
        poop_count = int(post.get("poop_count") or 0)
        recent = self.store.count_recent_auto_deletions(now - MODERATION_AUTO_DELETE_WINDOW)
        if recent >= MODERATION_AUTO_DELETE_LIMIT:
            self.store.complete_moderation(source_chat_id, message_id, "protected", "protected", "rate_limit", now)
            self._update_moderation_notice(
                post,
                "🛡批量删除保护已触发\n"
                f"消息：#{message_id}\n"
                f"👎{thumbs_down}｜💩{poop_count}\n"
                f"原因：10分钟内已自动删除{MODERATION_AUTO_DELETE_LIMIT}条\n"
                "请手动选择保留或删除",
                keep_buttons=True,
            )
            LOG.warning(
                "批量删除保护已触发：10分钟内已删除%s条 消息=%s 触发=%s",
                recent,
                message_id,
                "💩" if reason == "poop" else "👎",
            )
            return False
        return self._delete_moderation_post(post, reason, now)

    def run_due_moderations(self, now: datetime | None = None) -> None:
        now = (now or self._now()).astimezone(self.tz)
        for post in self.store.due_moderation_posts(now):
            source_chat_id = str(post.get("source_chat_id") or "")
            message_id = int(post.get("source_message_id") or 0)
            thumbs_down = int(post.get("thumbs_down") or 0)
            poop_count = int(post.get("poop_count") or 0)
            if now.timestamp() - float(post.get("posted_at_ts") or 0) > MODERATION_POST_MAX_AGE.total_seconds():
                if self.store.cancel_moderation_pending(source_chat_id, message_id, now):
                    self._update_moderation_notice(post, f"✅自动删除已取消\n消息：#{message_id}\n原因：帖子已超过1小时")
                    LOG.info("帖子自动删除已取消：消息=%s 原因=超过1小时", message_id)
                continue
            if not self._downvote_threshold_met(thumbs_down):
                if self.store.cancel_moderation_pending(source_chat_id, message_id, now):
                    self._update_moderation_notice(post, f"✅自动删除已取消\n消息：#{message_id}\n原因：票数已不满足删除条件")
                    LOG.info("👎自动删除已取消：消息=%s 👎=%s 💩=%s", message_id, thumbs_down, poop_count)
                continue
            self._automatic_delete_or_protect(post, "auto", now)

    def _send_owner_notice(self, text: str) -> None:
        try:
            self.api.send_message(self.config.owner_user_id, text)
        except Exception:
            pass

    def _handle_copy_failure(self, source_title: str, message_id: int, error: str) -> None:
        self.consecutive_copy_failures += 1
        if self.consecutive_copy_failures < COPY_FAILURE_ALERT_THRESHOLD or self.copy_failure_alert_active:
            return
        now = self._now()
        error_key = error[:120]
        last_alert = self.copy_failure_alert_times.get(error_key)
        if last_alert and now - last_alert < timedelta(hours=1):
            return
        self.copy_failure_alert_active = True
        self.copy_failure_alert_times[error_key] = now
        self._send_owner_notice(
            "\n".join(
                [
                    "⚠️转发连续失败",
                    f"连续：{self.consecutive_copy_failures}次",
                    f"来源：{source_title}",
                    f"消息：#{message_id}",
                    f"原因：{error}",
                ]
            )
        )

    def _handle_copy_recovery(self, source_title: str, message_id: int) -> None:
        should_notice = self.copy_failure_alert_active
        self.consecutive_copy_failures = 0
        self.copy_failure_alert_active = False
        if not should_notice:
            return
        self._send_owner_notice(
            "\n".join(
                [
                    "✅转发已恢复",
                    f"来源：{source_title}",
                    f"消息：#{message_id}",
                ]
            )
        )

    def _handle_message(self, message: dict[str, Any]) -> None:
        chat = message.get("chat") or {}
        chat_type = str(chat.get("type") or "")
        from_user = message.get("from") or {}
        user_id = int(from_user.get("id") or 0)
        text = str(message.get("text") or "").strip()

        if chat_type == "private":
            if user_id != self.config.owner_user_id:
                return
            if text.startswith("/"):
                self._handle_owner_command(text)
            return

        if chat_type in {"group", "supergroup"}:
            chat_id = normalize_chat_ref(chat)
            if chat_id != self.config.report_chat_id and self.config.unauthorized_group_action == "leave":
                self._leave_unauthorized_chat(chat, chat_id)
                return
            if chat_id == self.config.report_chat_id:
                self._handle_report_group_command(chat_id, user_id, text)

    def _handle_report_group_command(self, chat_id: str, user_id: int, text: str) -> None:
        if user_id != self.config.owner_user_id or not text.startswith("/"):
            return
        command = text.split()[0].split("@")[0].lower()
        target_chat = chat_ref_for_api(chat_id)
        if command == "/report":
            self.send_current_report(target_chat)
        elif command in {"/start", "/help", "/id"}:
            self.api.send_message(target_chat, self.group_ready_text(), disable_web_page_preview=True)

    def _handle_chat_member(self, update: dict[str, Any]) -> None:
        chat = update.get("chat") or {}
        chat_type = str(chat.get("type") or "")
        if chat_type not in {"group", "supergroup", "channel"}:
            return
        chat_id = normalize_chat_ref(chat)
        allowed = chat_id == self.config.report_chat_id or self._chat_allowed_as_source(chat)
        if not allowed and self.config.unauthorized_group_action == "leave":
            self._leave_unauthorized_chat(chat, chat_id)

    def _leave_unauthorized_chat(self, chat: dict[str, Any], chat_id: str) -> None:
        title = str(chat.get("title") or chat.get("username") or "未知群组")
        now = self._now()
        try:
            self.api.leave_chat(chat_ref_for_api(chat_id))
            if self._should_send_unauthorized_chat_notice(chat_id, now):
                self._send_owner_notice(f"⚠️已退出未授权群\n名称：{title}")
        except Exception as exc:
            if self._should_send_unauthorized_chat_notice(chat_id, now):
                self._send_owner_notice(f"⚠️未授权群退出失败\n名称：{title}\n原因：{exc}")

    def _should_send_unauthorized_chat_notice(self, chat_id: str, now: datetime) -> bool:
        last_notice = self.unauthorized_chat_notice_times.get(chat_id)
        if last_notice and now - last_notice < UNAUTHORIZED_CHAT_NOTICE_INTERVAL:
            return False
        self.unauthorized_chat_notice_times[chat_id] = now
        return True

    def _handle_owner_command(self, text: str) -> None:
        command = text.split()[0].split("@")[0].lower()
        if command in {"/start", "/help"}:
            self.api.send_message(self.config.owner_user_id, self.help_text(), disable_web_page_preview=True)
        elif command == "/status":
            self.api.send_message(self.config.owner_user_id, self.status_text(), disable_web_page_preview=True)
        elif command == "/report":
            self.send_current_report()
        elif command == "/recent":
            self.api.send_message(self.config.owner_user_id, self.recent_text(self._recent_limit_from_command(text)), disable_web_page_preview=True)
        elif command == "/check":
            self.api.send_message(self.config.owner_user_id, self.check_text(), disable_web_page_preview=True)
        else:
            self.api.send_message(self.config.owner_user_id, "未知命令，发送 /help 查看可用功能。")

    def group_ready_text(self) -> str:
        return "✅此群已配置完成\n可用命令：/report"

    def help_text(self) -> str:
        return "\n".join(
            [
                "SlowLink Assistant Bot",
                "/status 查看运行状态",
                "/report 查看当前报告",
                "/recent 查看最近记录",
                "/check 自检",
            ]
        )

    def _format_duration(self, start: datetime, end: datetime) -> str:
        seconds = max(0, int((end - start).total_seconds()))
        days, rem = divmod(seconds, 86400)
        hours, rem = divmod(rem, 3600)
        minutes = rem // 60
        if days:
            return f"{days}天{hours}小时"
        if hours:
            return f"{hours}小时{minutes}分"
        return f"{minutes}分"

    def _recent_limit_from_command(self, text: str) -> int:
        parts = text.split()
        if len(parts) < 2:
            return 8
        try:
            limit = int(parts[1])
        except ValueError:
            return 8
        return max(1, min(30, limit))

    def _report_group_status_text(self) -> str:
        try:
            me = self.api.get_me()
            member = self.api.get_chat_member(self.config.report_chat_id_for_api, int(me.get("id") or 0))
        except Exception:
            return "异常"
        status = str(member.get("status") or "")
        if status in {"creator", "administrator"}:
            return "已配置"
        if status == "member" and member.get("can_send_messages") is not False:
            return "已配置"
        return "异常"

    def status_text(self) -> str:
        now = self._now()
        today = manual_period("daily", now)
        stats = self.store.stats_between(today.start, today.end)
        moderation_stats = self.store.moderation_stats_between(today.start, today.end)
        recent = format_display_time(stats.last_success_at, now)
        return "\n".join(
            [
                "✅运行状态",
                f"版本：{__version__}",
                f"源频道：{len(self.config.source_channel_refs)}个",
                f"报表群：{self._report_group_status_text()}",
                f"运行：{self._format_duration(self.started_at, now)}",
                f"今日：转发{stats.success_count}条/失败{stats.failure_count}条",
                f"今日纠错：删除{moderation_stats.deleted_count}条",
                f"最近：{recent}",
            ]
        )

    def check_text(self) -> str:
        now = self._now()
        today = manual_period("daily", now)
        stats = self.store.stats_between(today.start, today.end)
        try:
            db_ok = self.store.health_check(now)
        except Exception:
            db_ok = False
        recent = format_display_time(stats.last_success_at, now)
        return "\n".join(
            [
                "✅自检完成",
                "Bot：正常",
                f"数据库：{'正常' if db_ok else '异常'}",
                f"守护：{self._watchdog_status_text(now)}",
                f"源频道：{len(self.config.source_channel_refs)}个",
                f"报表群：{self._report_group_status_text()}",
                f"今日：转发{stats.success_count}条/失败{stats.failure_count}条",
                f"最近：{recent}",
            ]
        )

    def _watchdog_status_text(self, now: datetime) -> str:
        if self.store.path == ":memory:":
            return "未知"
        status_path = Path(self.store.path).parent / "watchdog_status.txt"
        try:
            values = {}
            for line in status_path.read_text(encoding="utf-8").splitlines():
                if "=" not in line:
                    continue
                key, value = line.split("=", 1)
                values[key.strip()] = value.strip()
            updated_at_ts = float(values.get("updated_at_ts") or "")
        except Exception:
            return "异常"
        age = now.timestamp() - updated_at_ts
        if 0 <= age <= WATCHDOG_STATUS_MAX_AGE.total_seconds():
            return "正常"
        return "异常"

    def recent_text(self, limit: int = 8) -> str:
        rows = self.store.recent_events(limit)
        if not rows:
            return "🧾最近记录\n暂无转发记录"
        lines = ["🧾最近记录"]
        for row in rows:
            ok = "转发成功" if int(row.get("ok") or 0) == 1 else "转发失败"
            event_time = format_display_time(str(row.get("created_at") or ""), self._now())
            detail = str(row.get("error") or "")
            suffix = f"｜{detail}" if detail else ""
            lines.append(f"{event_time}｜{ok}｜{row.get('source_title')}#{row.get('source_message_id')}{suffix}")
        return "\n".join(lines)

    def send_manual_report(self, kind: str) -> None:
        now = self._now()
        period = manual_period(kind, now)
        stats = self.store.stats_between(period.start, period.end)
        summary = self.store.failure_summary_between(period.start, period.end)
        moderation_stats = self.store.moderation_stats_between(period.start, period.end)
        self.api.send_message(
            self.config.owner_user_id,
            format_report(kind, period, stats, now, summary, moderation_stats),
            disable_web_page_preview=True,
        )

    def current_report_text(self) -> str:
        now = self._now()
        today = manual_period("daily", now)
        stats = self.store.stats_between(today.start, today.end)
        summary = self.store.failure_summary_between(today.start, today.end)
        moderation_stats = self.store.moderation_stats_between(today.start, today.end)
        recent = format_display_time(stats.last_success_at, now)
        status = "正常" if stats.failure_count == 0 else "有失败"
        if stats.total_count == 0:
            return "\n".join(
                [
                    "📌当前概览",
                    "今日暂无明显转发",
                    f"内容纠错：删除{moderation_stats.deleted_count}条",
                    "系统：待命中",
                    "异常：0次",
                ]
            )
        lines = [
            "📌当前概览",
            f"今日转发{stats.success_count}条",
            f"内容纠错：删除{moderation_stats.deleted_count}条",
            f"最近：{recent}",
            f"系统：{status if status == '正常' else '有异常'}",
            f"异常：{stats.failure_count}次",
        ]
        if summary:
            parts = [f"{row.get('error')}×{int(row.get('count') or 0)}" for row in summary]
            lines.append("原因：" + "，".join(parts))
        return "\n".join(lines)

    def send_current_report(self, chat_id=None) -> None:
        target_chat = self.config.owner_user_id if chat_id is None else chat_id
        self.api.send_message(target_chat, self.current_report_text(), disable_web_page_preview=True)

    def run_due_reports(self, now: datetime | None = None) -> None:
        now = (now or self._now()).astimezone(self.tz)
        self._backup_database(now)
        self._cleanup_old_events(now)
        pending = []
        for kind in ("daily", "weekly", "monthly"):
            if not should_run_report(kind, now, self.config.report_hour, self.config.report_minute):
                continue
            period = scheduled_period(kind, now)
            if self.store.was_report_sent(kind, period.key):
                continue
            stats = self.store.stats_between(period.start, period.end)
            summary = self.store.failure_summary_between(period.start, period.end)
            moderation_stats = self.store.moderation_stats_between(period.start, period.end)
            pending.append(
                {
                    "kind": kind,
                    "period": period,
                    "stats": stats,
                    "moderation_stats": moderation_stats,
                    "text": format_report(kind, period, stats, now, summary, moderation_stats),
                    "title": report_name(kind),
                }
            )

        if not pending:
            return

        combined = len(pending) > 1
        titles = "、".join(item["title"] for item in pending)
        message_text = "\n\n────────\n\n".join(item["text"] for item in pending)
        first = pending[0]
        if combined:
            log_name = "组合报表"
            log_context = f"包含={titles}"
            notice_context = f"包含：{titles}"
        else:
            period = first["period"]
            period_field = report_period_field(first["kind"])
            period_label = format_period_label(period)
            log_name = first["title"]
            log_context = f"{period_field}={period_label}"
            notice_context = f"{period_field}：{period_label}"

        try:
            result = self.api.send_message(self.config.report_chat_id_for_api, message_text, disable_web_page_preview=True)
        except Exception as exc:
            LOG.warning("%s发送失败：%s 原因=%s", log_name, log_context, exc)
            self._send_owner_notice(f"⚠️{log_name}发送失败\n{notice_context}\n原因：{exc}")
            return

        message_id = int((result or {}).get("message_id") or 0)
        if message_id:
            try:
                self.api.pin_chat_message(self.config.report_chat_id_for_api, message_id, disable_notification=True)
                self._unpin_previous_report(message_id)
            except Exception as exc:
                LOG.warning("%s置顶失败：%s 原因=%s", log_name, log_context, exc)
                self._send_owner_notice(f"⚠️{log_name}置顶失败\n{notice_context}\n原因：{exc}")

        for item in pending:
            self.store.mark_report_sent(item["kind"], item["period"].key, now)

        if combined:
            LOG.info("组合报表发送完成：包含=%s", titles)
        else:
            stats = first["stats"]
            LOG.info(
                "%s发送完成：%s=%s 转发=%s条 异常=%s次 纠错删除=%s条",
                first["title"],
                period_field,
                period_label,
                stats.success_count,
                stats.failure_count,
                first["moderation_stats"].deleted_count,
            )

    def _unpin_previous_report(self, current_message_id: int) -> None:
        previous_message_id = self.store.get_state(LAST_REPORT_PIN_STATE_KEY)
        self.store.set_state(LAST_REPORT_PIN_STATE_KEY, str(int(current_message_id)))
        if not previous_message_id:
            return
        try:
            previous = int(previous_message_id)
        except ValueError:
            return
        if previous == int(current_message_id):
            return
        try:
            self.api.unpin_chat_message(self.config.report_chat_id_for_api, previous)
        except Exception as exc:
            LOG.warning("旧报表取消置顶失败：消息=%s 原因=%s", previous, exc)

    def _backup_database(self, now: datetime) -> None:
        if self.last_backup_date == now.date():
            return
        try:
            backup_path = self.store.backup_database(now)
            self.last_backup_date = now.date()
            if backup_path:
                LOG.info("数据库备份完成：路径=%s", backup_path)
        except Exception as exc:
            LOG.warning("数据库备份失败：原因=%s", exc)
            self._send_owner_notice(f"⚠️数据库备份失败\n原因：{exc}")

    def _cleanup_old_events(self, now: datetime) -> None:
        if self.last_cleanup_date == now.date():
            return
        cutoff = now - timedelta(days=EVENT_RETENTION_DAYS)
        deleted = self.store.prune_copy_events_before(cutoff)
        self.last_cleanup_date = now.date()
        if deleted:
            LOG.info("已清理旧记录：数量=%s 截止日期=%s", deleted, cutoff.date())
