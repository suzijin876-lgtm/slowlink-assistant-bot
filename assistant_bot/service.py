from __future__ import annotations

import logging
import re
import threading
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Callable, Any
from zoneinfo import ZoneInfo

from . import __version__
from .config import BotConfig, chat_ref_for_api, chat_username_ref, normalize_chat_ref
from .menu import (
    REPORT_DESTINATION_LABELS,
    REPORT_KIND_LABELS,
    cover_panel_keyboard,
    cover_panel_text,
    cover_upload_keyboard,
    cover_upload_text,
    detail_keyboard,
    group_report_keyboard,
    main_menu_keyboard,
    main_menu_text,
    report_settings_keyboard,
    report_settings_text,
)
from .reports import (
    Period,
    format_compact_report,
    format_count_change,
    format_data_range,
    format_display_time,
    format_period_label,
    format_report,
    manual_period,
    previous_period,
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
LAST_REPORT_CHANNEL_PIN_STATE_KEY = "last_report_channel_pin_message_id"
REPORT_COVER_STATE_KEY = "scheduled_report_cover_file_id"
PHOTO_CAPTION_LIMIT = 1024
COVER_UPLOAD_TIMEOUT = timedelta(minutes=10)
MODERATION_MIN_DOWNVOTES = 2
MODERATION_MIN_POOPS = 2
MODERATION_DELETE_DELAY = timedelta(minutes=1)
MODERATION_POST_MAX_AGE = timedelta(hours=1)
MODERATION_AUTO_DELETE_LIMIT = 4
MODERATION_AUTO_DELETE_WINDOW = timedelta(minutes=10)
GROUP_COMMAND_REPLY_DELETE_DELAY_SECONDS = 45
OWNER_REPLY_DELETE_COMMANDS = {"删", "删除", "已删除"}
TELEGRAM_POST_LINK_RE = re.compile(
    r"https://(?:"
    r"(?:t\.me|telegram\.me)/(?!c/)[A-Za-z0-9_]+/[1-9]\d*(?:/[1-9]\d*)?"
    r"|t\.me/c/[1-9]\d*/[1-9]\d*(?:/[1-9]\d*)?"
    r")",
    re.IGNORECASE,
)


def _is_telegram_post_link(message: dict[str, Any]) -> bool:
    content = message.get("text")
    if content is None:
        content = message.get("caption")
    return bool(TELEGRAM_POST_LINK_RE.fullmatch(str(content or "").strip()))


class AssistantService:
    def __init__(self, config: BotConfig, api, store: EventStore, clock: Callable[[], datetime] | None = None):
        self.config = config
        self.api = api
        self.store = store
        self.tz = ZoneInfo(config.timezone)
        self.clock = clock or (lambda: datetime.now(self.tz))
        self.started_at = self._now()
        self.store.statistics_coverage_start(self.started_at)
        self.consecutive_copy_failures = 0
        self.copy_failure_alert_active = False
        self.copy_failure_alert_times: dict[str, datetime] = {}
        self.unauthorized_chat_notice_times: dict[str, datetime] = {}
        self.last_cleanup_date: date | None = None
        self.last_backup_date: date | None = None
        self.cover_upload_deadline: datetime | None = None

    def _now(self) -> datetime:
        now = self.clock()
        if now.tzinfo is None:
            return now.replace(tzinfo=self.tz)
        return now.astimezone(self.tz)

    def _statistics_coverage_start(self, reference: datetime | None = None) -> datetime:
        fallback = self.started_at
        if reference is not None and reference < fallback:
            fallback = reference
        return self.store.statistics_coverage_start(fallback)

    def _comparison_count(self, period: Period, coverage_start: datetime) -> int | None:
        if coverage_start > period.start:
            return None
        return self.store.report_stats_between(period.start, period.end).success_count

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
        if not _is_telegram_post_link(message):
            LOG.debug("跳过非Telegram帖子链接：来源=%s 消息=%s", source_title, message_id)
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
        data = str(query.get("data") or "")
        if data.startswith("menu:"):
            self._handle_menu_callback(query, data)
            return
        if data.startswith("settings:"):
            self._handle_report_settings_callback(query, data)
            return
        if data.startswith("cover:"):
            self._handle_cover_panel_callback(query, data)
            return
        if data.startswith("group:"):
            self._handle_group_panel_callback(query, data)
            return

        parts = data.split(":")
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

    def _handle_menu_callback(self, query: dict[str, Any], data: str) -> None:
        callback_id = str(query.get("id") or "")
        if not self._callback_is_private(query):
            self._answer_callback(callback_id, "操作无效", show_alert=True)
            return
        action = data.split(":", 1)[1]
        if action == "home":
            self.cover_upload_deadline = None
            text, keyboard = main_menu_text(), main_menu_keyboard(self.config.slowlink_panel_url)
        elif action == "report":
            text, keyboard = self.current_report_text(), detail_keyboard("menu:report")
        elif action == "status":
            text, keyboard = self.status_text(), detail_keyboard("menu:status")
        elif action == "recent":
            text, keyboard = self.recent_text(), detail_keyboard("menu:recent")
        elif action == "check":
            text, keyboard = self.check_text(), detail_keyboard("menu:check")
        elif action == "settings":
            text, keyboard = self._report_settings_view()
        elif action == "cover":
            enabled = bool(self.store.get_state(REPORT_COVER_STATE_KEY))
            text, keyboard = cover_panel_text(enabled), cover_panel_keyboard(enabled)
        else:
            self._answer_callback(callback_id, "操作无效", show_alert=True)
            return
        self._edit_callback_panel(query, text, keyboard)
        self._answer_callback(callback_id, "已刷新" if action not in {"home", "settings", "cover"} else "")

    def _handle_report_settings_callback(self, query: dict[str, Any], data: str) -> None:
        callback_id = str(query.get("id") or "")
        if not self._callback_is_private(query):
            self._answer_callback(callback_id, "操作无效", show_alert=True)
            return
        parts = data.split(":")
        if (
            len(parts) != 3
            or parts[1] not in REPORT_DESTINATION_LABELS
            or parts[2] not in REPORT_KIND_LABELS
        ):
            self._answer_callback(callback_id, "操作无效", show_alert=True)
            return
        role, kind = parts[1], parts[2]
        if role == "channel" and not self.config.report_channel_id:
            self._answer_callback(callback_id, "简报频道未配置", show_alert=True)
            return
        enabled = not self._report_kind_enabled(role, kind)
        self.store.set_state(self._report_enabled_state_key(role, kind), "1" if enabled else "0")
        text, keyboard = self._report_settings_view()
        self._edit_callback_panel(query, text, keyboard)
        self._answer_callback(
            callback_id,
            f"{REPORT_DESTINATION_LABELS[role]}{REPORT_KIND_LABELS[kind]}已{'开启' if enabled else '关闭'}",
        )

    def _handle_cover_panel_callback(self, query: dict[str, Any], data: str) -> None:
        callback_id = str(query.get("id") or "")
        if not self._callback_is_private(query):
            self._answer_callback(callback_id, "操作无效", show_alert=True)
            return
        action = data.split(":", 1)[1]
        if action == "upload":
            self.cover_upload_deadline = self._now() + COVER_UPLOAD_TIMEOUT
            self._edit_callback_panel(query, cover_upload_text(), cover_upload_keyboard())
            self._answer_callback(callback_id, "等待图片")
            return
        if action == "cancel":
            self.cover_upload_deadline = None
            enabled = bool(self.store.get_state(REPORT_COVER_STATE_KEY))
            self._edit_callback_panel(query, cover_panel_text(enabled), cover_panel_keyboard(enabled))
            self._answer_callback(callback_id, "已取消")
            return
        if action == "off":
            self.cover_upload_deadline = None
            self.store.delete_state(REPORT_COVER_STATE_KEY)
            self._edit_callback_panel(query, cover_panel_text(False), cover_panel_keyboard(False))
            self._answer_callback(callback_id, "封面已停用")
            LOG.info("简报封面已停用")
            return
        if action == "preview":
            cover = self.store.get_state(REPORT_COVER_STATE_KEY)
            if not cover:
                self._answer_callback(callback_id, "尚未设置封面", show_alert=True)
                return
            try:
                self.api.send_photo(self.config.owner_user_id, cover, self._cover_preview_text())
            except Exception as exc:
                LOG.warning("简报封面预览发送失败：原因=%s", exc)
                self._answer_callback(callback_id, "预览发送失败", show_alert=True)
                return
            self._answer_callback(callback_id, "预览已发送")
            return
        self._answer_callback(callback_id, "操作无效", show_alert=True)

    def _handle_group_panel_callback(self, query: dict[str, Any], data: str) -> None:
        callback_id = str(query.get("id") or "")
        message = query.get("message") or {}
        chat = message.get("chat") or {}
        if normalize_chat_ref(chat) != self.config.report_chat_id:
            self._answer_callback(callback_id, "操作无效", show_alert=True)
            return
        action = data.split(":", 1)[1]
        if action in {"report", "home"}:
            text, keyboard = self.current_report_text(include_diagnostics=False), group_report_keyboard()
        else:
            self._answer_callback(callback_id, "操作无效", show_alert=True)
            return
        self._edit_callback_panel(query, text, keyboard)
        self._answer_callback(callback_id, "已刷新" if action == "report" else "")

    def _callback_is_private(self, query: dict[str, Any]) -> bool:
        message = query.get("message") or {}
        return str((message.get("chat") or {}).get("type") or "") == "private"

    def _edit_callback_panel(self, query: dict[str, Any], text: str, keyboard: dict) -> None:
        message = query.get("message") or {}
        chat = message.get("chat") or {}
        chat_id = chat_ref_for_api(normalize_chat_ref(chat))
        message_id = int(message.get("message_id") or 0)
        if not chat_id or not message_id:
            return
        try:
            self.api.edit_message_text(chat_id, message_id, text, reply_markup=keyboard)
        except Exception as exc:
            if "message is not modified" in str(exc).lower():
                return
            response = self.api.send_message(chat_id, text, disable_web_page_preview=True, reply_markup=keyboard)
            if (
                str(chat.get("type") or "") in {"group", "supergroup"}
                and normalize_chat_ref(chat) == self.config.report_chat_id
            ):
                self._schedule_group_reply_cleanup(chat_id, response)

    @staticmethod
    def _report_enabled_state_key(role: str, kind: str) -> str:
        return f"report_enabled:{role}:{kind}"

    def _report_kind_enabled(self, role: str, kind: str) -> bool:
        return self.store.get_state(self._report_enabled_state_key(role, kind)) != "0"

    def _report_settings_view(self) -> tuple[str, dict]:
        enabled = {
            (role, kind): self._report_kind_enabled(role, kind)
            for role in REPORT_DESTINATION_LABELS
            for kind in REPORT_KIND_LABELS
        }
        channel_configured = bool(self.config.report_channel_id)
        return (
            report_settings_text(enabled, channel_configured),
            report_settings_keyboard(enabled, channel_configured),
        )

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

    def _complete_deleted_moderation(
        self,
        post: dict,
        reason: str,
        now: datetime,
        action: str | None = None,
    ) -> bool:
        source_chat_id = str(post.get("source_chat_id") or "")
        message_id = int(post.get("source_message_id") or 0)
        completed = self.store.complete_moderation(
            source_chat_id,
            message_id,
            "deleted",
            "deleted",
            reason,
            now,
            allow_terminal_delete=reason == "owner",
        )
        if not completed:
            LOG.warning("帖子删除状态未更新：消息=%s", message_id)
            return False
        action = action or ("自动删除" if reason == "auto" else "立即删除" if reason == "owner" else "直接删除")
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

    def _delete_moderation_post(self, post: dict, reason: str, now: datetime) -> bool:
        source_chat_id = str(post.get("source_chat_id") or "")
        message_id = int(post.get("source_message_id") or 0)
        try:
            self.api.delete_message(chat_ref_for_api(source_chat_id), message_id)
        except Exception as exc:
            if self._is_missing_source_error(exc):
                return self._complete_deleted_moderation(post, reason, now, action="确认删除")
            self.store.complete_moderation(source_chat_id, message_id, "failed", "failed", reason, now)
            self._update_moderation_notice(
                post,
                "❌帖子删除失败\n"
                f"消息：#{message_id}\n"
                f"原因：{exc}",
            )
            LOG.warning("帖子删除失败：消息=%s 原因=%s", message_id, exc)
            return False
        return self._complete_deleted_moderation(post, reason, now)

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

    @staticmethod
    def _is_missing_source_error(error: Exception) -> bool:
        detail = str(error).lower()
        return "message to delete not found" in detail or "message not found" in detail

    def _handle_owner_reply_action(self, message: dict[str, Any], text: str) -> None:
        reply = message.get("reply_to_message") or {}
        copied_message_id = int(reply.get("message_id") or 0)
        if not copied_message_id:
            self._send_owner_notice("请回复要处理的转发消息")
            return

        event = self.store.get_copy_event_by_target_message(str(self.config.owner_user_id), copied_message_id)
        if not event:
            self._send_owner_notice("未找到对应的转发记录")
            return

        source_chat_id = str(event.get("source_chat_id") or "")
        source_message_id = int(event.get("source_message_id") or 0)
        post = self.store.get_moderation_post(source_chat_id, source_message_id)
        if not post:
            self._send_owner_notice("未找到对应的纠错记录")
            return
        if str(post.get("status") or "") == "deleted":
            self._send_owner_notice("这条消息已经处理")
            return

        now = self._now()
        if text == "已删除":
            if self.store.complete_moderation(
                source_chat_id,
                source_message_id,
                "deleted",
                "deleted",
                "manual",
                now,
                allow_terminal_delete=True,
            ):
                self._update_moderation_notice(post, f"✅已记录为删除\n消息：#{source_message_id}")
                LOG.info("手动删除已记录：消息=%s 原因=主人已在频道删除", source_message_id)
            else:
                self._send_owner_notice("这条消息已经处理")
            return

        self._delete_moderation_post(post, "owner", now)

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
            command_text = text
            caption_command = False
            if not command_text:
                caption = str(message.get("caption") or "").strip()
                command = ""
                if caption.startswith("/"):
                    command = caption.split()[0].split("@")[0].lower()
                if command == "/cover":
                    command_text = caption
                    caption_command = True
            if command_text.startswith("/"):
                command = command_text.split()[0].split("@")[0].lower()
                if caption_command:
                    try:
                        self._handle_cover_command(message, command_text)
                    finally:
                        self._delete_command_message(message)
                else:
                    self._delete_command_message(message)
                    if command == "/cover":
                        self._handle_cover_command(message, command_text)
                    else:
                        self._handle_owner_command(command_text)
                return
            if message.get("photo") and self.cover_upload_deadline is not None:
                if self._now() <= self.cover_upload_deadline:
                    self._save_cover_photo(message)
                    return
                self.cover_upload_deadline = None
            if text in OWNER_REPLY_DELETE_COMMANDS:
                self._handle_owner_reply_action(message, text)
            return

        if chat_type in {"group", "supergroup"}:
            chat_id = normalize_chat_ref(chat)
            if chat_id != self.config.report_chat_id and self.config.unauthorized_group_action == "leave":
                self._leave_unauthorized_chat(chat, chat_id)
                return
            if chat_id == self.config.report_chat_id:
                if user_id == self.config.owner_user_id and text.startswith("/"):
                    self._delete_command_message(message)
                self._handle_report_group_command(chat_id, user_id, text)

    def _delete_command_message(self, message: dict[str, Any]) -> None:
        chat_id = chat_ref_for_api(normalize_chat_ref(message.get("chat") or {}))
        message_id = int(message.get("message_id") or 0)
        self._delete_message_safely(chat_id, message_id, "命令消息")

    def _delete_message_safely(self, chat_id, message_id: int, label: str) -> None:
        if not chat_id or not message_id:
            return
        try:
            self.api.delete_message(chat_id, message_id)
        except Exception as exc:
            LOG.warning("%s清理失败：聊天=%s 消息=%s 原因=%s", label, chat_id, message_id, exc)

    def _schedule_group_reply_cleanup(self, chat_id, response) -> None:
        if not isinstance(response, dict):
            return
        message_id = int(response.get("message_id") or 0)
        if not message_id:
            return
        timer = threading.Timer(
            GROUP_COMMAND_REPLY_DELETE_DELAY_SECONDS,
            lambda: self._delete_message_safely(chat_id, message_id, "群聊临时回复"),
        )
        timer.daemon = True
        timer.start()

    def _handle_cover_command(self, message: dict[str, Any], text: str) -> None:
        parts = text.split()
        if len(parts) > 1 and parts[1].lower() == "off":
            self.cover_upload_deadline = None
            self.store.delete_state(REPORT_COVER_STATE_KEY)
            self.api.send_message(
                self.config.owner_user_id,
                cover_panel_text(False),
                reply_markup=cover_panel_keyboard(False),
            )
            LOG.info("简报封面已停用")
            return

        photos = [item for item in message.get("photo") or [] if item.get("file_id")]
        if photos:
            self._save_cover_photo(message)
            return

        enabled = bool(self.store.get_state(REPORT_COVER_STATE_KEY))
        self.api.send_message(
            self.config.owner_user_id,
            cover_panel_text(enabled),
            reply_markup=cover_panel_keyboard(enabled),
        )

    def _save_cover_photo(self, message: dict[str, Any]) -> None:
        photos = [item for item in message.get("photo") or [] if item.get("file_id")]
        if not photos:
            return
        selected = max(
            photos,
            key=lambda item: (
                int(item.get("file_size") or 0),
                int(item.get("width") or 0) * int(item.get("height") or 0),
            ),
        )
        file_id = str(selected["file_id"])
        self.cover_upload_deadline = None
        self.store.set_state(REPORT_COVER_STATE_KEY, file_id)
        try:
            self.api.send_photo(self.config.owner_user_id, file_id, self._cover_preview_text())
            LOG.info("简报封面已更新，私聊预览发送完成")
        except Exception as exc:
            LOG.warning("简报封面已更新，但私聊预览发送失败：原因=%s", exc)
            self.api.send_message(
                self.config.owner_user_id,
                f"✅简报封面已更新\n⚠️私聊预览发送失败\n原因：{exc}",
                reply_markup=main_menu_keyboard(self.config.slowlink_panel_url),
            )

    def _cover_preview_text(self) -> str:
        now = self._now()
        period = manual_period("weekly", now)
        if period.end <= period.start:
            return "✅简报封面已更新\n📊封面预览\n本周统计尚未开始"
        coverage_start = self._statistics_coverage_start(now)
        stats = self.store.report_stats_between(period.start, period.end)
        comparison_period = Period(
            "weekly",
            period.start - timedelta(days=7),
            period.end - timedelta(days=7),
        )
        previous_count = self._comparison_count(comparison_period, coverage_start)
        report_text = format_report(
            "weekly",
            period,
            stats,
            now,
            include_diagnostics=False,
            previous_success_count=previous_count,
            include_moderation=False,
            include_comparison=True,
            data_start=coverage_start if coverage_start > period.start else None,
            title_override="本周进度（封面预览）",
            comparison_label_override="较上周同期",
            generated_at_label=True,
        )
        return f"✅简报封面已更新\n{report_text}"

    def _handle_report_group_command(self, chat_id: str, user_id: int, text: str) -> None:
        if user_id != self.config.owner_user_id or not text.startswith("/"):
            return
        command = text.split()[0].split("@")[0].lower()
        target_chat = chat_ref_for_api(chat_id)
        response = None
        if command in {"/start", "/help", "/id", "/report"}:
            response = self.send_current_report(target_chat, reply_markup=group_report_keyboard())
        self._schedule_group_reply_cleanup(target_chat, response)

    def _handle_chat_member(self, update: dict[str, Any]) -> None:
        chat = update.get("chat") or {}
        chat_type = str(chat.get("type") or "")
        if chat_type not in {"group", "supergroup", "channel"}:
            return
        chat_id = normalize_chat_ref(chat)
        allowed = (
            chat_id == self.config.report_chat_id
            or chat_id == self.config.report_channel_id
            or self._chat_allowed_as_source(chat)
        )
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
            self.api.send_message(
                self.config.owner_user_id,
                self.help_text(),
                disable_web_page_preview=True,
                reply_markup=main_menu_keyboard(self.config.slowlink_panel_url),
            )
        elif command == "/status":
            self.api.send_message(
                self.config.owner_user_id,
                self.status_text(),
                disable_web_page_preview=True,
                reply_markup=detail_keyboard("menu:status"),
            )
        elif command == "/report":
            self.send_current_report(reply_markup=detail_keyboard("menu:report"))
        elif command == "/recent":
            self.api.send_message(
                self.config.owner_user_id,
                self.recent_text(self._recent_limit_from_command(text)),
                disable_web_page_preview=True,
                reply_markup=detail_keyboard("menu:recent"),
            )
        elif command == "/check":
            self.api.send_message(
                self.config.owner_user_id,
                self.check_text(),
                disable_web_page_preview=True,
                reply_markup=detail_keyboard("menu:check"),
            )
        else:
            self.api.send_message(
                self.config.owner_user_id,
                main_menu_text(),
                reply_markup=main_menu_keyboard(self.config.slowlink_panel_url),
            )

    def help_text(self) -> str:
        return main_menu_text()

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

    def _report_channel_status_text(self) -> str:
        if self.config.report_channel_id_for_api is None:
            return "未配置"
        try:
            me = self.api.get_me()
            member = self.api.get_chat_member(self.config.report_channel_id_for_api, int(me.get("id") or 0))
        except Exception:
            return "异常"
        status = str(member.get("status") or "")
        if status == "creator":
            return "已配置"
        if (
            status == "administrator"
            and member.get("can_post_messages") is not False
            and member.get("can_edit_messages") is not False
        ):
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
                f"简报频道：{self._report_channel_status_text()}",
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
                f"简报频道：{self._report_channel_status_text()}",
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
        moderation_stats = self.store.moderation_stats_between(period.start, period.end)
        self.api.send_message(
            self.config.owner_user_id,
            format_report(kind, period, stats, now, moderation_stats=moderation_stats),
            disable_web_page_preview=True,
        )

    def current_report_text(self, include_diagnostics: bool = True) -> str:
        now = self._now()
        today = manual_period("daily", now)
        if not include_diagnostics:
            coverage_start = self._statistics_coverage_start(now)
            stats = self.store.report_stats_between(today.start, today.end)
            comparison_period = Period(
                "daily",
                today.start - timedelta(days=1),
                today.end - timedelta(days=1),
            )
            previous_count = self._comparison_count(comparison_period, coverage_start)
            recent = format_display_time(stats.last_success_at, now)
            lines = [
                "📌当前概览",
                f"日期：{today.start:%Y-%m-%d}",
                f"转发：{stats.success_count}条",
                format_count_change("较昨日同期", stats.success_count, previous_count),
            ]
            if coverage_start > today.start:
                lines.insert(2, format_data_range(today, coverage_start))
            if stats.peak_hour is not None:
                lines.extend(
                    [
                        f"高峰时段：{stats.peak_hour:02d}:00-{stats.peak_hour + 1:02d}:00",
                        f"高峰转发：{stats.peak_hour_count}条",
                        f"首次转发：{format_display_time(stats.first_success_at, now)}",
                        f"最后转发：{recent}",
                    ]
                )
            else:
                lines.append("今日暂无明显转发")
            return "\n".join(lines)

        stats = self.store.stats_between(today.start, today.end)
        moderation_stats = self.store.moderation_stats_between(today.start, today.end)
        recent = format_display_time(stats.last_success_at, now)
        status = "正常" if stats.failure_count == 0 else "有失败"
        if stats.total_count == 0:
            lines = [
                "📌当前概览",
                "今日暂无明显转发",
                f"内容纠错：删除{moderation_stats.deleted_count}条",
            ]
            if include_diagnostics:
                lines.extend(["系统：待命中", "异常：0次"])
            return "\n".join(lines)
        lines = [
            "📌当前概览",
            f"今日转发{stats.success_count}条",
            f"内容纠错：删除{moderation_stats.deleted_count}条",
            f"最近：{recent}",
        ]
        if include_diagnostics:
            lines.extend(
                [
                    f"系统：{status if status == '正常' else '有异常'}",
                    f"异常：{stats.failure_count}次",
                ]
            )
        return "\n".join(lines)

    def send_current_report(self, chat_id=None, reply_markup=None):
        target_chat = self.config.owner_user_id if chat_id is None else chat_id
        include_diagnostics = str(target_chat) == str(self.config.owner_user_id)
        return self.api.send_message(
            target_chat,
            self.current_report_text(include_diagnostics=include_diagnostics),
            disable_web_page_preview=True,
            reply_markup=reply_markup,
        )

    def _scheduled_report_destinations(self) -> list[dict[str, Any]]:
        destinations = [
            {
                "role": "group",
                "key": f"group:{self.config.report_chat_id}",
                "name": "报表群",
                "chat_id": self.config.report_chat_id_for_api,
                "pin_state_key": LAST_REPORT_PIN_STATE_KEY,
            }
        ]
        if self.config.report_channel_id and self.config.report_channel_id != self.config.report_chat_id:
            destinations.append(
                {
                    "role": "channel",
                    "key": f"channel:{self.config.report_channel_id}",
                    "name": "简报频道",
                    "chat_id": self.config.report_channel_id_for_api,
                    "pin_state_key": LAST_REPORT_CHANNEL_PIN_STATE_KEY,
                }
            )
        return destinations

    def _send_scheduled_report(
        self,
        message_text: str,
        log_name: str,
        notice_context: str,
        target_chat_id=None,
        target_name: str = "报表群",
    ):
        target_chat_id = self.config.report_chat_id_for_api if target_chat_id is None else target_chat_id
        cover = self.store.get_state(REPORT_COVER_STATE_KEY)
        cover_error = None
        if cover and len(message_text) <= PHOTO_CAPTION_LIMIT:
            try:
                return self.api.send_photo(
                    target_chat_id,
                    cover,
                    message_text,
                )
            except Exception as exc:
                cover_error = exc
        elif cover:
            cover_error = ValueError("简报文字超过图片说明长度限制")

        if cover_error is not None:
            LOG.warning(
                "%s封面发送失败，已改发纯文字：%s 目标=%s 原因=%s",
                log_name,
                notice_context,
                target_name,
                cover_error,
            )

        result = self.api.send_message(
            target_chat_id,
            message_text,
            disable_web_page_preview=True,
        )
        if cover_error is not None:
            self._send_owner_notice(
                f"⚠️{log_name}封面发送失败，已改发纯文字\n目标：{target_name}\n{notice_context}\n原因：{cover_error}"
            )
        return result

    def run_due_reports(self, now: datetime | None = None) -> None:
        now = (now or self._now()).astimezone(self.tz)
        self._backup_database(now)
        self._cleanup_old_events(now)
        coverage_start = self._statistics_coverage_start(now)
        destinations = self._scheduled_report_destinations()
        pending = []
        for kind in ("daily", "weekly", "monthly"):
            if not should_run_report(kind, now, self.config.report_hour, self.config.report_minute):
                continue
            period = scheduled_period(kind, now)
            if self.store.was_report_sent(kind, period.key):
                continue
            pending_destination_keys = {
                destination["key"]
                for destination in destinations
                if self._report_kind_enabled(destination["role"], kind)
                and not self.store.was_report_delivered(kind, period.key, destination["key"])
            }
            if not pending_destination_keys:
                self.store.mark_report_sent(kind, period.key, now)
                continue
            scheduled_at = now.replace(
                hour=self.config.report_hour,
                minute=self.config.report_minute,
                second=0,
                microsecond=0,
            )
            if now > scheduled_at and coverage_start >= period.end:
                continue
            stats = self.store.report_stats_between(period.start, period.end)
            comparison_period = previous_period(period)
            previous_count = self._comparison_count(comparison_period, coverage_start)
            moderation_stats = self.store.moderation_stats_between(period.start, period.end)
            pending.append(
                {
                    "kind": kind,
                    "period": period,
                    "stats": stats,
                    "moderation_stats": moderation_stats,
                    "text": format_report(
                        kind,
                        period,
                        stats,
                        now,
                        moderation_stats=moderation_stats,
                        include_diagnostics=False,
                        previous_success_count=previous_count,
                        include_moderation=False,
                        include_comparison=True,
                        data_start=coverage_start if coverage_start > period.start else None,
                    ),
                    "title": report_name(kind),
                    "comparison_period": comparison_period,
                    "previous_success_count": previous_count,
                    "comparison_status": "available" if previous_count is not None else "unavailable",
                    "data_start": max(period.start, coverage_start),
                    "pending_destination_keys": pending_destination_keys,
                }
            )

        if not pending:
            return

        for destination in destinations:
            target_pending = [
                item for item in pending if destination["key"] in item["pending_destination_keys"]
            ]
            if not target_pending:
                continue

            combined = len(target_pending) > 1
            titles = "、".join(item["title"] for item in target_pending)
            first = target_pending[0]
            if combined:
                compact_sections = [
                    format_compact_report(
                        item["kind"],
                        item["period"],
                        item["stats"],
                        item["previous_success_count"],
                        data_start=item["data_start"],
                    )
                    for item in target_pending
                ]
                message_text = "📊周期简报\n\n" + "\n\n".join(compact_sections)
                log_name = "组合报表"
                log_context = f"包含={titles}"
                notice_context = f"包含：{titles}"
            else:
                message_text = first["text"]
                period = first["period"]
                period_field = report_period_field(first["kind"])
                period_label = format_period_label(period)
                log_name = first["title"]
                log_context = f"{period_field}={period_label}"
                notice_context = f"{period_field}：{period_label}"

            try:
                result = self._send_scheduled_report(
                    message_text,
                    log_name,
                    notice_context,
                    target_chat_id=destination["chat_id"],
                    target_name=destination["name"],
                )
            except Exception as exc:
                LOG.warning(
                    "%s发送失败：%s 目标=%s 原因=%s",
                    log_name,
                    log_context,
                    destination["name"],
                    exc,
                )
                self._send_owner_notice(
                    f"⚠️{log_name}发送失败\n目标：{destination['name']}\n{notice_context}\n原因：{exc}"
                )
                continue

            message_id = int((result or {}).get("message_id") or 0)
            if message_id:
                try:
                    self.api.pin_chat_message(destination["chat_id"], message_id, disable_notification=True)
                    self._unpin_previous_report(
                        message_id,
                        chat_id=destination["chat_id"],
                        state_key=destination["pin_state_key"],
                        target_name=destination["name"],
                    )
                except Exception as exc:
                    LOG.warning(
                        "%s置顶失败：%s 目标=%s 原因=%s",
                        log_name,
                        log_context,
                        destination["name"],
                        exc,
                    )
                    self._send_owner_notice(
                        f"⚠️{log_name}置顶失败\n目标：{destination['name']}\n{notice_context}\n原因：{exc}"
                    )

            for item in target_pending:
                if self.store.get_report_snapshot(item["kind"], item["period"].key) is not None:
                    continue
                try:
                    self.store.save_report_snapshot(
                        period_type=item["kind"],
                        period_key=item["period"].key,
                        period_start=item["period"].start,
                        period_end=item["period"].end,
                        data_start=item["data_start"],
                        success_count=item["stats"].success_count,
                        failure_count=item["stats"].failure_count,
                        deleted_count=item["moderation_stats"].deleted_count,
                        comparison_start=item["comparison_period"].start,
                        comparison_end=item["comparison_period"].end,
                        previous_success_count=item["previous_success_count"],
                        comparison_status=item["comparison_status"],
                        message_id=message_id,
                        report_text=item["text"],
                        sent_at=now,
                    )
                except Exception as exc:
                    LOG.warning(
                        "报表快照保存失败：类型=%s 周期=%s 原因=%s",
                        item["kind"],
                        item["period"].key,
                        exc,
                    )
                    self._send_owner_notice(
                        f"⚠️报表已发送，但快照保存失败\n类型：{item['title']}\n周期：{item['period'].key}"
                    )

            for item in target_pending:
                self.store.mark_report_delivered(
                    item["kind"],
                    item["period"].key,
                    destination["key"],
                    now,
                )

            if combined:
                LOG.info("组合报表发送完成：包含=%s 目标=%s", titles, destination["name"])
            else:
                stats = first["stats"]
                LOG.info(
                    "%s发送完成：%s=%s 转发=%s条 异常=%s次 纠错删除=%s条 目标=%s",
                    first["title"],
                    period_field,
                    period_label,
                    stats.success_count,
                    stats.failure_count,
                    first["moderation_stats"].deleted_count,
                    destination["name"],
                )

        for item in pending:
            if all(
                self.store.was_report_delivered(item["kind"], item["period"].key, destination["key"])
                for destination in destinations
                if self._report_kind_enabled(destination["role"], item["kind"])
            ):
                self.store.mark_report_sent(item["kind"], item["period"].key, now)

    def _unpin_previous_report(
        self,
        current_message_id: int,
        chat_id=None,
        state_key: str = LAST_REPORT_PIN_STATE_KEY,
        target_name: str = "报表群",
    ) -> None:
        chat_id = self.config.report_chat_id_for_api if chat_id is None else chat_id
        previous_message_id = self.store.get_state(state_key)
        self.store.set_state(state_key, str(int(current_message_id)))
        if not previous_message_id:
            return
        try:
            previous = int(previous_message_id)
        except ValueError:
            return
        if previous == int(current_message_id):
            return
        try:
            self.api.unpin_chat_message(chat_id, previous)
        except Exception as exc:
            LOG.warning("旧报表取消置顶失败：目标=%s 消息=%s 原因=%s", target_name, previous, exc)

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
