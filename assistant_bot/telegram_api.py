from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
from typing import Any


class TelegramAPIError(RuntimeError):
    pass


class TelegramAPI:
    RETRY_HTTP_CODES = {429, 500, 502, 503, 504}

    def __init__(self, token: str, base_url: str = "https://api.telegram.org", max_attempts: int = 2, retry_delay: float = 0.5):
        self.token = token
        self.base_url = base_url.rstrip("/")
        self.max_attempts = max(1, int(max_attempts))
        self.retry_delay = max(0.1, float(retry_delay))

    def _retry_delay(self, detail: str | dict[str, Any] | None = None) -> float:
        retry_after = None
        if isinstance(detail, str) and detail:
            try:
                detail = json.loads(detail)
            except json.JSONDecodeError:
                detail = None
        if isinstance(detail, dict):
            params = detail.get("parameters")
            if isinstance(params, dict):
                retry_after = params.get("retry_after")
        try:
            delay = float(retry_after) if retry_after is not None else self.retry_delay
        except (TypeError, ValueError):
            delay = self.retry_delay
        return min(max(delay, 0.1), 30.0)

    def _request(self, method: str, payload: dict[str, Any], timeout: int = 35) -> Any:
        url = f"{self.base_url}/bot{self.token}/{method}"
        data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"})
        for attempt in range(1, self.max_attempts + 1):
            try:
                with urllib.request.urlopen(req, timeout=timeout) as resp:
                    body = resp.read().decode("utf-8")
            except urllib.error.HTTPError as exc:
                detail = exc.read().decode("utf-8", errors="replace")
                if exc.code in self.RETRY_HTTP_CODES and attempt < self.max_attempts:
                    time.sleep(self._retry_delay(detail))
                    continue
                raise TelegramAPIError(f"{method} HTTP {exc.code}: {detail}") from exc
            except (urllib.error.URLError, TimeoutError) as exc:
                if attempt < self.max_attempts:
                    time.sleep(self.retry_delay)
                    continue
                raise TelegramAPIError(f"{method} network error: {exc}") from exc

            try:
                parsed = json.loads(body)
            except json.JSONDecodeError as exc:
                raise TelegramAPIError(f"{method} invalid JSON response") from exc
            if parsed.get("ok"):
                return parsed.get("result")
            params = parsed.get("parameters") if isinstance(parsed, dict) else None
            if attempt < self.max_attempts and isinstance(params, dict) and params.get("retry_after"):
                time.sleep(self._retry_delay(parsed))
                continue
            raise TelegramAPIError(f"{method} failed: {parsed.get('description', parsed)}")

        raise TelegramAPIError(f"{method} failed after retry")

    def delete_webhook(self, drop_pending_updates: bool = False):
        return self._request("deleteWebhook", {"drop_pending_updates": bool(drop_pending_updates)}, timeout=20)

    def get_me(self):
        return self._request("getMe", {}, timeout=20)

    def get_updates(self, offset: int | None, timeout: int, allowed_updates: list[str]):
        payload: dict[str, Any] = {"timeout": int(timeout), "allowed_updates": allowed_updates}
        if offset is not None:
            payload["offset"] = int(offset)
        return self._request("getUpdates", payload, timeout=int(timeout) + 10)

    def copy_message(self, chat_id, from_chat_id, message_id: int):
        return self._request(
            "copyMessage",
            {"chat_id": chat_id, "from_chat_id": from_chat_id, "message_id": int(message_id)},
            timeout=30,
        )

    def send_message(self, chat_id, text: str, disable_web_page_preview: bool = False, reply_markup=None):
        payload = {"chat_id": chat_id, "text": text, "disable_web_page_preview": bool(disable_web_page_preview)}
        if reply_markup is not None:
            payload["reply_markup"] = reply_markup
        return self._request("sendMessage", payload, timeout=30)

    def send_photo(self, chat_id, photo: str, caption: str):
        return self._request(
            "sendPhoto",
            {"chat_id": chat_id, "photo": str(photo), "caption": str(caption)},
            timeout=30,
        )

    def edit_message_text(self, chat_id, message_id: int, text: str, reply_markup=None):
        payload = {"chat_id": chat_id, "message_id": int(message_id), "text": text}
        if reply_markup is not None:
            payload["reply_markup"] = reply_markup
        return self._request("editMessageText", payload, timeout=20)

    def delete_message(self, chat_id, message_id: int):
        return self._request(
            "deleteMessage",
            {"chat_id": chat_id, "message_id": int(message_id)},
            timeout=20,
        )

    def get_chat(self, chat_id):
        return self._request("getChat", {"chat_id": chat_id}, timeout=20)

    def answer_callback_query(self, callback_query_id: str, text: str = "", show_alert: bool = False):
        payload = {"callback_query_id": str(callback_query_id), "text": text, "show_alert": bool(show_alert)}
        return self._request("answerCallbackQuery", payload, timeout=20)

    def pin_chat_message(self, chat_id, message_id: int, disable_notification: bool = True):
        return self._request(
            "pinChatMessage",
            {"chat_id": chat_id, "message_id": int(message_id), "disable_notification": bool(disable_notification)},
            timeout=20,
        )

    def unpin_chat_message(self, chat_id, message_id: int):
        return self._request(
            "unpinChatMessage",
            {"chat_id": chat_id, "message_id": int(message_id)},
            timeout=20,
        )

    def get_chat_member(self, chat_id, user_id: int):
        return self._request(
            "getChatMember",
            {"chat_id": chat_id, "user_id": int(user_id)},
            timeout=20,
        )

    def leave_chat(self, chat_id):
        return self._request("leaveChat", {"chat_id": chat_id}, timeout=20)
