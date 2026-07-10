from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

from .store import ModerationStats, Stats


REPORT_NAMES = {
    "daily": "日报",
    "weekly": "周报",
    "monthly": "月报",
}


def format_display_time(value: str | datetime, reference: datetime) -> str:
    if value == "-":
        return "暂无"
    if isinstance(value, datetime):
        event_time = value
    else:
        try:
            event_time = datetime.fromisoformat(str(value))
        except ValueError:
            return str(value) if value else "暂无"

    if reference.tzinfo is not None:
        if event_time.tzinfo is None:
            event_time = event_time.replace(tzinfo=reference.tzinfo)
        else:
            event_time = event_time.astimezone(reference.tzinfo)

    if event_time.date() == reference.date():
        return event_time.strftime("%H:%M")
    return event_time.strftime("%m-%d %H:%M")


@dataclass(frozen=True)
class Period:
    kind: str
    start: datetime
    end: datetime

    @property
    def key(self) -> str:
        if self.kind == "monthly":
            return self.start.strftime("%Y-%m")
        if self.kind == "weekly":
            return self.start.strftime("%Y-W%W")
        return self.start.strftime("%Y-%m-%d")

    @property
    def label(self) -> str:
        return format_period_label(self)


def report_name(kind: str) -> str:
    return REPORT_NAMES.get(kind, kind)


def report_period_field(kind: str) -> str:
    return "日期" if kind == "daily" else "周期"


def format_period_label(period: Period) -> str:
    if period.kind == "daily":
        return period.start.strftime("%Y-%m-%d")
    end = period.end
    if end.hour == 0 and end.minute == 0 and end.second == 0 and end.microsecond == 0:
        end -= timedelta(days=1)
    return f"{period.start:%Y-%m-%d}至{end:%Y-%m-%d}"


def _format_report_time(value: str | datetime, period: Period, reference: datetime) -> str:
    if value == "-":
        return "暂无"
    if isinstance(value, datetime):
        event_time = value
    else:
        try:
            event_time = datetime.fromisoformat(str(value))
        except ValueError:
            return str(value) if value else "暂无"
    if reference.tzinfo is not None:
        if event_time.tzinfo is None:
            event_time = event_time.replace(tzinfo=reference.tzinfo)
        else:
            event_time = event_time.astimezone(reference.tzinfo)
    if period.kind == "daily":
        return event_time.strftime("%H:%M")
    return event_time.strftime("%m-%d %H:%M")


def _format_peak_hour(hour: int) -> str:
    end_hour = hour + 1
    return f"{hour:02d}:00-{end_hour:02d}:00"


def _covered_days(period: Period) -> int:
    days = (period.end.date() - period.start.date()).days
    if period.end.hour or period.end.minute or period.end.second or period.end.microsecond:
        days += 1
    return max(1, days)


def _format_average(count: int, days: int) -> str:
    return f"{count / days:.1f}".rstrip("0").rstrip(".")


def start_of_day(now: datetime) -> datetime:
    return now.replace(hour=0, minute=0, second=0, microsecond=0)


def start_of_week(now: datetime) -> datetime:
    day = start_of_day(now)
    return day - timedelta(days=day.weekday())


def start_of_month(now: datetime) -> datetime:
    return now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)


def previous_month_start(now: datetime) -> datetime:
    current = start_of_month(now)
    last_day = current - timedelta(days=1)
    return start_of_month(last_day)


def manual_period(kind: str, now: datetime) -> Period:
    if kind == "daily":
        return Period(kind, start_of_day(now), now)
    if kind == "weekly":
        return Period(kind, start_of_week(now), now)
    if kind == "monthly":
        return Period(kind, start_of_month(now), now)
    raise ValueError(f"unknown report kind: {kind}")


def scheduled_period(kind: str, now: datetime) -> Period:
    anchor = now.replace(second=0, microsecond=0)
    if kind == "daily":
        end = start_of_day(anchor)
        return Period(kind, end - timedelta(days=1), end)
    if kind == "weekly":
        end = start_of_week(anchor)
        return Period(kind, end - timedelta(days=7), end)
    if kind == "monthly":
        end = start_of_month(anchor)
        return Period(kind, previous_month_start(anchor), end)
    raise ValueError(f"unknown report kind: {kind}")


def should_run_report(kind: str, now: datetime, hour: int, minute: int) -> bool:
    if now.hour != hour or now.minute != minute:
        return False
    if kind == "daily":
        return True
    if kind == "weekly":
        return now.weekday() == 0
    if kind == "monthly":
        return now.day == 1
    return False


def _failure_summary_text(failure_summary: list[dict] | None) -> str | None:
    if not failure_summary:
        return None
    parts = [f"{row.get('error')}×{int(row.get('count') or 0)}" for row in failure_summary if row.get("error")]
    if not parts:
        return None
    return "失败原因：" + "，".join(parts)


def _moderation_lines(moderation_stats: ModerationStats | None) -> list[str]:
    stats = moderation_stats or ModerationStats(deleted_count=0, kept_count=0, protected_count=0)
    lines = [f"内容纠错：删除{stats.deleted_count}条"]
    if stats.kept_count:
        lines.append(f"纠错保留：{stats.kept_count}条")
    if stats.protected_count:
        lines.append(f"批量保护：{stats.protected_count}次")
    return lines


def format_report(
    kind: str,
    period: Period,
    stats: Stats,
    generated_at: datetime,
    failure_summary: list[dict] | None = None,
    moderation_stats: ModerationStats | None = None,
) -> str:
    title = report_name(kind)
    period_field = report_period_field(kind)
    period_label = format_period_label(period)
    status = "正常" if stats.failure_count == 0 else "有异常"
    if stats.total_count == 0:
        lines = [
            f"📊{title}",
            f"{period_field}：{period_label}",
            "转发：0条",
        ]
        lines.extend(_moderation_lines(moderation_stats))
        lines.extend(["运行状态：待命中", "异常记录：0次"])
        return "\n".join(lines)

    lines = [
        f"📊{title}",
        f"{period_field}：{period_label}",
        f"转发：{stats.success_count}条",
    ]
    if kind == "daily" and stats.peak_hour is not None:
        lines.append(f"活跃时段：{_format_peak_hour(stats.peak_hour)}")
        lines.append(f"首次转发：{_format_report_time(stats.first_success_at, period, generated_at)}")
    elif kind in {"weekly", "monthly"}:
        lines.append(f"日均：{_format_average(stats.success_count, _covered_days(period))}条")
        if stats.peak_day:
            lines.append(f"最活跃：{stats.peak_day[5:]}（{stats.peak_day_count}条）")
    if stats.success_count:
        lines.append(f"最后转发：{_format_report_time(stats.last_success_at, period, generated_at)}")
    lines.extend(_moderation_lines(moderation_stats))
    lines.extend(
        [
            f"运行状态：{status}",
            f"异常记录：{stats.failure_count}次",
        ]
    )
    summary_text = _failure_summary_text(failure_summary)
    if summary_text:
        lines.append(summary_text.replace("失败原因：", "原因："))
    return "\n".join(lines)
