from __future__ import annotations

import os
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping, Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


class ConfigError(ValueError):
    pass


def _read_env_file(path: Path | None) -> dict[str, str]:
    if path is None or not path.exists():
        return {}
    values: dict[str, str] = {}
    for raw_line in path.read_text(encoding="utf-8-sig").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip()
        if (value.startswith('"') and value.endswith('"')) or (value.startswith("'") and value.endswith("'")):
            value = value[1:-1]
        values[key] = value
    return values


def parse_chat_refs(value: str) -> frozenset[str]:
    refs: set[str] = set()
    for item in str(value or "").replace("\n", ",").split(","):
        item = item.strip()
        if not item:
            continue
        if item.lstrip("-").isdigit():
            refs.add(item)
        else:
            refs.add("@" + item.lstrip("@").lower())
    return frozenset(refs)


def normalize_chat_ref(chat: Mapping[str, Any] | str | int) -> str:
    if isinstance(chat, int):
        return str(chat)
    if isinstance(chat, str):
        if chat.lstrip("-").isdigit():
            return chat
        return "@" + chat.lstrip("@").lower()
    chat_id = chat.get("id")
    if chat_id is not None:
        return str(chat_id)
    username = str(chat.get("username") or "").strip()
    if username:
        return "@" + username.lstrip("@").lower()
    return ""


def chat_username_ref(chat: Mapping[str, Any]) -> str:
    username = str(chat.get("username") or "").strip()
    return ("@" + username.lstrip("@").lower()) if username else ""


def chat_ref_for_api(ref: str):
    ref = str(ref).strip()
    if ref.lstrip("-").isdigit():
        return int(ref)
    return ref


def _int_value(values: Mapping[str, str], name: str, default: int | None = None) -> int:
    raw = values.get(name)
    if raw is None or raw == "":
        if default is None:
            raise ConfigError(f"缺少配置：{name}")
        return default
    try:
        return int(raw)
    except ValueError as exc:
        raise ConfigError(f"{name} 必须是整数") from exc


def _bounded_int(
    values: Mapping[str, str],
    name: str,
    default: int,
    minimum: int,
    maximum: int,
) -> int:
    value = _int_value(values, name, default)
    if not minimum <= value <= maximum:
        raise ConfigError(f"{name} 必须在 {minimum} 到 {maximum} 之间")
    return value


def _float_value(
    values: Mapping[str, str],
    name: str,
    default: float,
    minimum: float,
    maximum: float,
) -> float:
    raw = values.get(name)
    try:
        value = float(default if raw is None or raw == "" else raw)
    except (TypeError, ValueError) as exc:
        raise ConfigError(f"{name} 必须是数字") from exc
    if not math.isfinite(value) or not minimum <= value <= maximum:
        raise ConfigError(f"{name} 必须在 {minimum:g} 到 {maximum:g} 之间")
    return value


@dataclass(frozen=True)
class BotConfig:
    bot_token: str
    owner_user_id: int
    report_chat_id: str
    source_channel_refs: frozenset[str]
    data_path: str = "data/assistant.sqlite3"
    timezone: str = "Asia/Shanghai"
    poll_timeout: int = 25
    poll_interval: float = 1.0
    report_hour: int = 0
    report_minute: int = 0
    unauthorized_group_action: str = "leave"
    startup_drop_pending_updates: bool = False

    @classmethod
    def load(cls, env: Mapping[str, str] | None = None, env_file: str | Path | None = ".env") -> "BotConfig":
        file_values = _read_env_file(Path(env_file) if env_file else None)
        merged = dict(os.environ if env is None else env)
        values = {**file_values, **merged}

        token = str(values.get("BOT_TOKEN") or "").strip()
        if not token:
            raise ConfigError("缺少配置：BOT_TOKEN")
        owner_user_id = _int_value(values, "OWNER_USER_ID")
        if owner_user_id <= 0:
            raise ConfigError("OWNER_USER_ID 必须大于0")
        report_chat_id = str(values.get("REPORT_CHAT_ID") or "").strip()
        if not report_chat_id:
            raise ConfigError("缺少配置：REPORT_CHAT_ID")
        report_chat_id = normalize_chat_ref(report_chat_id)
        source_channel_refs = parse_chat_refs(str(values.get("SOURCE_CHANNEL_IDS") or ""))
        if not source_channel_refs:
            raise ConfigError("缺少配置：SOURCE_CHANNEL_IDS")

        unauthorized_action = str(values.get("UNAUTHORIZED_GROUP_ACTION") or "leave").strip().lower()
        if unauthorized_action not in {"leave", "ignore"}:
            raise ConfigError("UNAUTHORIZED_GROUP_ACTION 只能是 leave 或 ignore")

        timezone = str(values.get("TIMEZONE") or "Asia/Shanghai").strip()
        try:
            ZoneInfo(timezone)
        except (ZoneInfoNotFoundError, ValueError) as exc:
            raise ConfigError("TIMEZONE 不是有效时区") from exc

        return cls(
            bot_token=token,
            owner_user_id=owner_user_id,
            report_chat_id=report_chat_id,
            source_channel_refs=source_channel_refs,
            data_path=str(values.get("DATA_PATH") or "data/assistant.sqlite3"),
            timezone=timezone,
            poll_timeout=_bounded_int(values, "POLL_TIMEOUT", 25, 1, 50),
            poll_interval=_float_value(values, "POLL_INTERVAL", 1.0, 0.1, 60.0),
            report_hour=_bounded_int(values, "REPORT_HOUR", 0, 0, 23),
            report_minute=_bounded_int(values, "REPORT_MINUTE", 0, 0, 59),
            unauthorized_group_action=unauthorized_action,
            startup_drop_pending_updates=str(values.get("STARTUP_DROP_PENDING_UPDATES") or "0").strip() == "1",
        )

    @property
    def report_chat_id_for_api(self):
        return chat_ref_for_api(self.report_chat_id)
