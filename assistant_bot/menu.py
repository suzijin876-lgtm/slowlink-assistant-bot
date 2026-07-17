from __future__ import annotations

from collections.abc import Mapping

from . import __version__


REPORT_KIND_LABELS = {
    "daily": "日报",
    "weekly": "周报",
    "monthly": "月报",
}

REPORT_DESTINATION_LABELS = {
    "group": "报表群",
    "channel": "简报频道",
}


def main_menu_text() -> str:
    return (
        "🧭SlowLink Assistant控制面板\n"
        f"版本：V{__version__}\n"
        "模式：频道消息助手\n"
        "状态：正常运行\n\n"
        "💡点击下方按钮进入对应功能"
    )


def main_menu_keyboard(panel_url: str | None = None) -> dict:
    rows = []
    if panel_url:
        rows.append([{"text": "🌐SlowLink", "url": panel_url}])
    rows.extend(
        [
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
        ]
    )
    return {"inline_keyboard": rows}


def detail_keyboard(refresh_callback: str) -> dict:
    return {
        "inline_keyboard": [
            [
                {"text": "🔄刷新", "callback_data": refresh_callback},
                {"text": "↩返回", "callback_data": "menu:home"},
            ]
        ]
    }


def group_menu_keyboard() -> dict:
    return {"inline_keyboard": [[{"text": "📊当前报告", "callback_data": "group:report"}]]}


def group_report_keyboard() -> dict:
    return {
        "inline_keyboard": [
            [
                {"text": "🔄刷新", "callback_data": "group:report"},
                {"text": "↩返回", "callback_data": "group:home"},
            ]
        ]
    }


def report_settings_text(enabled: Mapping[tuple[str, str], bool], channel_configured: bool) -> str:
    lines = ["🗓简报设置", _destination_status_line("group", enabled)]
    if channel_configured:
        lines.append(_destination_status_line("channel", enabled))
    else:
        lines.append("简报频道：未配置")
    return "\n".join(lines)


def _destination_status_line(role: str, enabled: Mapping[tuple[str, str], bool]) -> str:
    states = [
        f"{label}{'开' if enabled.get((role, kind), True) else '关'}"
        for kind, label in REPORT_KIND_LABELS.items()
    ]
    return f"{REPORT_DESTINATION_LABELS[role]}：" + "｜".join(states)


def report_settings_keyboard(enabled: Mapping[tuple[str, str], bool], channel_configured: bool) -> dict:
    if channel_configured:
        rows = [
            [
                _settings_button("group", kind, label, enabled),
                _settings_button("channel", kind, label, enabled),
            ]
            for kind, label in REPORT_KIND_LABELS.items()
        ]
    else:
        rows = [_settings_row("group", enabled)]
    rows.append([{"text": "↩返回", "callback_data": "menu:home"}])
    return {"inline_keyboard": rows}


def _settings_row(role: str, enabled: Mapping[tuple[str, str], bool]) -> list[dict[str, str]]:
    return [
        _settings_button(role, kind, label, enabled)
        for kind, label in REPORT_KIND_LABELS.items()
    ]


def _settings_button(
    role: str,
    kind: str,
    label: str,
    enabled: Mapping[tuple[str, str], bool],
) -> dict[str, str]:
    prefix = "群" if role == "group" else "频道"
    return {
        "text": f"{prefix}·{label}{'✅' if enabled.get((role, kind), True) else '❌'}",
        "callback_data": f"settings:{role}:{kind}",
    }


def cover_panel_text(enabled: bool) -> str:
    return f"🖼封面管理\n状态：{'已启用' if enabled else '未设置'}"


def cover_panel_keyboard(enabled: bool) -> dict:
    rows = [
        [
            {"text": "🖼更换", "callback_data": "cover:upload"},
            {"text": "👁预览", "callback_data": "cover:preview"},
        ]
    ]
    if enabled:
        rows.append(
            [
                {"text": "⏸停用", "callback_data": "cover:off"},
                {"text": "↩返回", "callback_data": "menu:home"},
            ]
        )
    else:
        rows.append([{"text": "↩返回", "callback_data": "menu:home"}])
    return {"inline_keyboard": rows}


def cover_upload_text() -> str:
    return "🖼更换简报封面\n请直接发送一张图片"


def cover_upload_keyboard() -> dict:
    return {
        "inline_keyboard": [
            [
                {"text": "取消", "callback_data": "cover:cancel"},
                {"text": "↩返回", "callback_data": "menu:home"},
            ]
        ]
    }
