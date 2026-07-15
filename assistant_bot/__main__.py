from __future__ import annotations

import logging
import sys
import time
from datetime import datetime
from zoneinfo import ZoneInfo

from . import __version__
from .config import BotConfig, ConfigError
from .health import Heartbeat
from .service import AssistantService
from .store import EventStore
from .telegram_api import TelegramAPI, TelegramAPIError


ALLOWED_UPDATES = ["message", "channel_post", "my_chat_member", "message_reaction_count", "callback_query"]
LOG_TIMEZONE = ZoneInfo("Asia/Shanghai")


class ChinaTimeFormatter(logging.Formatter):
    def formatTime(self, record, datefmt=None):
        value = datetime.fromtimestamp(record.created, LOG_TIMEZONE)
        if datefmt:
            return value.strftime(datefmt)
        return value.strftime("%Y-%m-%d %H:%M:%S")


def setup_logging() -> None:
    handler = logging.StreamHandler()
    handler.setFormatter(ChinaTimeFormatter("[%(asctime)s] [%(levelname)s] %(message)s"))
    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(logging.INFO)


def should_pause_after_poll(updates: list[dict]) -> bool:
    return len(updates) == 0


def main() -> int:
    setup_logging()
    log = logging.getLogger("assistant_bot")
    try:
        config = BotConfig.load()
    except ConfigError as exc:
        log.error("配置错误：%s", exc)
        return 2

    store = EventStore(config.data_path)
    api = TelegramAPI(config.bot_token)
    service = AssistantService(config, api, store)
    heartbeat = Heartbeat(config.data_path)
    heartbeat.clear()

    try:
        api.delete_webhook(drop_pending_updates=config.startup_drop_pending_updates)
        me = api.get_me()
    except TelegramAPIError as exc:
        log.error("Telegram 初始化失败：%s", exc)
        return 3
    heartbeat.touch(force=True)
    try:
        api.set_my_commands([{"command": "start", "description": "打开主面板"}])
    except TelegramAPIError as exc:
        log.warning("按钮入口设置失败，Bot继续运行：%s", exc)
    log.info("SlowLink Assistant 已启动：版本=%s", __version__)
    log.info(
        "Bot 信息：账号=@%s 源频道=%d个 报表群=已配置 简报频道=%s",
        me.get("username", "unknown"),
        len(config.source_channel_refs),
        "已配置" if config.report_channel_id else "未配置",
    )
    service.verify_source_reactions()

    offset = store.get_offset()
    while True:
        try:
            updates = api.get_updates(offset=offset, timeout=config.poll_timeout, allowed_updates=ALLOWED_UPDATES)
            for update in updates:
                service.handle_update(update)
                offset = store.get_offset()
                heartbeat.touch()
            service.run_due_moderations()
            service.run_due_reports()
            if should_pause_after_poll(updates):
                time.sleep(config.poll_interval)
        except KeyboardInterrupt:
            log.info("停止运行")
            return 0
        except TelegramAPIError as exc:
            log.warning("Telegram 轮询异常：%s，5秒后重试", exc)
            time.sleep(5)
        except Exception as exc:
            log.exception("主循环异常：%s", exc)
            time.sleep(5)
        finally:
            try:
                heartbeat.touch()
            except OSError as exc:
                log.warning("Bot心跳更新失败：%s", exc)


if __name__ == "__main__":
    sys.exit(main())
