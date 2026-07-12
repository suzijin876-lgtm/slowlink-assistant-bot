import tempfile
import unittest
import sqlite3
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from assistant_bot.reports import format_report, manual_period, scheduled_period, should_run_report
from assistant_bot.store import EventStore, ModerationStats


TZ = ZoneInfo("Asia/Shanghai")


class StoreAndReportTests(unittest.TestCase):
    def test_moderation_schema_migrates_poop_count(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "assistant.sqlite3"
            conn = sqlite3.connect(db_path)
            try:
                conn.executescript(
                    """
                    CREATE TABLE moderation_posts (
                        source_chat_id TEXT NOT NULL,
                        source_title TEXT NOT NULL,
                        source_message_id INTEGER NOT NULL,
                        posted_at TEXT NOT NULL,
                        posted_at_ts REAL NOT NULL,
                        thumbs_up INTEGER NOT NULL DEFAULT 0,
                        thumbs_down INTEGER NOT NULL DEFAULT 0,
                        status TEXT NOT NULL DEFAULT 'watching',
                        delete_after TEXT NOT NULL DEFAULT '',
                        delete_after_ts REAL,
                        owner_notice_message_id INTEGER,
                        updated_at TEXT NOT NULL,
                        updated_at_ts REAL NOT NULL,
                        PRIMARY KEY (source_chat_id, source_message_id)
                    );
                    CREATE TABLE moderation_events (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        source_chat_id TEXT NOT NULL,
                        source_message_id INTEGER NOT NULL,
                        event_type TEXT NOT NULL,
                        reason TEXT NOT NULL DEFAULT '',
                        thumbs_up INTEGER NOT NULL DEFAULT 0,
                        thumbs_down INTEGER NOT NULL DEFAULT 0,
                        created_at TEXT NOT NULL,
                        created_at_ts REAL NOT NULL
                    );
                    """
                )
                conn.commit()
            finally:
                conn.close()

            store = EventStore(db_path)
            try:
                post_columns = {row["name"] for row in store._conn.execute("PRAGMA table_info(moderation_posts)")}
                event_columns = {row["name"] for row in store._conn.execute("PRAGMA table_info(moderation_events)")}
            finally:
                store.close()

        self.assertIn("poop_count", post_columns)
        self.assertIn("poop_count", event_columns)

    def test_store_counts_success_and_failure_in_period(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = EventStore(Path(tmp) / "assistant.sqlite3")
            try:
                store.record_copy_success("-1001", "source", 10, "42", 99, datetime(2026, 7, 10, 1, 0, tzinfo=TZ))
                store.record_copy_failure("-1001", "source", 11, "42", "bad request", datetime(2026, 7, 10, 2, 0, tzinfo=TZ))

                stats = store.stats_between(
                    datetime(2026, 7, 10, 0, 0, tzinfo=TZ),
                    datetime(2026, 7, 11, 0, 0, tzinfo=TZ),
                )
            finally:
                store.close()

        self.assertEqual(stats.success_count, 1)
        self.assertEqual(stats.failure_count, 1)
        self.assertEqual(stats.total_count, 2)

    def test_store_collects_first_last_and_peak_activity(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = EventStore(Path(tmp) / "assistant.sqlite3")
            try:
                store.record_copy_success("-1001", "source", 10, "42", 99, datetime(2026, 7, 9, 1, 15, tzinfo=TZ))
                store.record_copy_success("-1001", "source", 11, "42", 100, datetime(2026, 7, 9, 20, 10, tzinfo=TZ))
                store.record_copy_success("-1001", "source", 12, "42", 101, datetime(2026, 7, 9, 20, 45, tzinfo=TZ))
                store.record_copy_success("-1001", "source", 13, "42", 102, datetime(2026, 7, 10, 8, 0, tzinfo=TZ))

                stats = store.stats_between(
                    datetime(2026, 7, 9, 0, 0, tzinfo=TZ),
                    datetime(2026, 7, 11, 0, 0, tzinfo=TZ),
                )
            finally:
                store.close()

        self.assertEqual(stats.first_success_at, "2026-07-09T01:15:00+08:00")
        self.assertEqual(stats.last_success_at, "2026-07-10T08:00:00+08:00")
        self.assertEqual(stats.peak_hour, 20)
        self.assertEqual(stats.peak_hour_count, 2)
        self.assertEqual(stats.peak_day, "2026-07-09")
        self.assertEqual(stats.peak_day_count, 3)

    def test_store_creates_indexes_for_report_queries(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = EventStore(Path(tmp) / "assistant.sqlite3")
            try:
                rows = store._conn.execute("PRAGMA index_list(copy_events)").fetchall()
            finally:
                store.close()

        names = {str(row["name"]) for row in rows}
        self.assertIn("idx_copy_events_created_at_ts", names)
        self.assertIn("idx_copy_events_ok_created_at_ts", names)

    def test_store_summarizes_failure_reasons(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = EventStore(Path(tmp) / "assistant.sqlite3")
            try:
                store.record_copy_failure("-1001", "source", 11, "42", "bad request", datetime(2026, 7, 10, 2, 0, tzinfo=TZ))
                store.record_copy_failure("-1001", "source", 12, "42", "bad request", datetime(2026, 7, 10, 2, 5, tzinfo=TZ))
                store.record_copy_failure("-1001", "source", 13, "42", "timeout", datetime(2026, 7, 10, 2, 10, tzinfo=TZ))

                summary = store.failure_summary_between(
                    datetime(2026, 7, 10, 0, 0, tzinfo=TZ),
                    datetime(2026, 7, 11, 0, 0, tzinfo=TZ),
                )
            finally:
                store.close()

        self.assertEqual(summary, [{"error": "bad request", "count": 2}, {"error": "timeout", "count": 1}])

    def test_moderation_pending_state_survives_database_reopen(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "assistant.sqlite3"
            store = EventStore(db_path)
            posted_at = datetime(2026, 7, 11, 10, 0, tzinfo=TZ)
            delete_after = datetime(2026, 7, 11, 10, 1, tzinfo=TZ)
            try:
                store.record_moderation_post("-1001", "Source", 55, posted_at)
                store.update_moderation_reactions(
                    "-1001", 55, thumbs_up=1, thumbs_down=2, at=posted_at, poop_count=3
                )
                store.set_moderation_pending("-1001", 55, delete_after, posted_at)
                store.set_moderation_notice("-1001", 55, 900, posted_at)
            finally:
                store.close()

            reopened = EventStore(db_path)
            try:
                post = reopened.get_moderation_post("-1001", 55)
                due = reopened.due_moderation_posts(delete_after)
            finally:
                reopened.close()

        self.assertEqual(post["status"], "pending")
        self.assertEqual(post["thumbs_up"], 1)
        self.assertEqual(post["thumbs_down"], 2)
        self.assertEqual(post["poop_count"], 3)
        self.assertEqual(post["owner_notice_message_id"], 900)
        self.assertEqual(len(due), 1)
        self.assertEqual(due[0]["source_message_id"], 55)

    def test_moderation_events_support_limits_and_report_statistics(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = EventStore(Path(tmp) / "assistant.sqlite3")
            try:
                start = datetime(2026, 7, 11, 10, 0, tzinfo=TZ)
                for message_id in range(1, 7):
                    at = start.replace(minute=message_id)
                    store.record_moderation_post("-1001", "Source", message_id, at)
                    store.update_moderation_reactions("-1001", message_id, 0, 2, at)
                for message_id in range(1, 5):
                    store.complete_moderation("-1001", message_id, "deleted", "deleted", "auto", start.replace(minute=message_id))
                store.complete_moderation("-1001", 5, "kept", "kept", "owner", start.replace(minute=5))
                store.complete_moderation("-1001", 6, "protected", "protected", "rate_limit", start.replace(minute=6))

                recent = store.count_recent_auto_deletions(start)
                stats = store.moderation_stats_between(start, datetime(2026, 7, 11, 11, 0, tzinfo=TZ))
            finally:
                store.close()

        self.assertEqual(recent, 4)
        self.assertEqual(stats.deleted_count, 4)
        self.assertEqual(stats.kept_count, 1)
        self.assertEqual(stats.protected_count, 1)

    def test_store_prunes_old_copy_events(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = EventStore(Path(tmp) / "assistant.sqlite3")
            try:
                store.record_copy_success("-1001", "old", 10, "42", 99, datetime(2026, 3, 1, 1, 0, tzinfo=TZ))
                store.record_copy_success("-1001", "new", 11, "42", 100, datetime(2026, 7, 10, 1, 0, tzinfo=TZ))

                deleted = store.prune_copy_events_before(datetime(2026, 4, 11, 0, 0, tzinfo=TZ))
                stats = store.stats_between(
                    datetime(2026, 1, 1, 0, 0, tzinfo=TZ),
                    datetime(2026, 8, 1, 0, 0, tzinfo=TZ),
                )
            finally:
                store.close()

        self.assertEqual(deleted, 1)
        self.assertEqual(stats.success_count, 1)

    def test_store_backs_up_database_and_keeps_recent_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "assistant.sqlite3"
            store = EventStore(db_path)
            try:
                store.record_copy_success("-1001", "source", 10, "42", 99, datetime(2026, 7, 10, 1, 0, tzinfo=TZ))
                backup_path = store.backup_database(datetime(2026, 7, 10, 12, 0, tzinfo=TZ), keep_days=7)
                for day in range(1, 10):
                    old = db_path.parent / "backups" / f"assistant_2026070{day}.sqlite3"
                    old.parent.mkdir(parents=True, exist_ok=True)
                    old.write_text("old", encoding="utf-8")
                    old.touch()
                second_backup = store.backup_database(datetime(2026, 7, 11, 12, 0, tzinfo=TZ), keep_days=7)
            finally:
                store.close()

            self.assertIsNotNone(backup_path)
            self.assertTrue(Path(backup_path).exists())
            self.assertIsNotNone(second_backup)
            backups = sorted((db_path.parent / "backups").glob("assistant_*.sqlite3"))
            self.assertLessEqual(len(backups), 7)

    def test_format_report_uses_polished_forwarding_copy(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = EventStore(Path(tmp) / "assistant.sqlite3")
            try:
                store.record_copy_success("-1001", "source", 10, "42", 99, datetime(2026, 7, 9, 1, 18, tzinfo=TZ))
                store.record_copy_success("-1001", "source", 11, "42", 100, datetime(2026, 7, 9, 20, 10, tzinfo=TZ))
                store.record_copy_success("-1001", "source", 12, "42", 101, datetime(2026, 7, 9, 20, 45, tzinfo=TZ))
                stats = store.stats_between(
                    datetime(2026, 7, 9, 0, 0, tzinfo=TZ),
                    datetime(2026, 7, 10, 0, 0, tzinfo=TZ),
                )
            finally:
                store.close()
        period = scheduled_period("daily", datetime(2026, 7, 10, 0, 0, tzinfo=TZ))

        text = format_report("daily", period, stats, datetime(2026, 7, 10, 0, 0, tzinfo=TZ))

        self.assertIn("📊昨日日报", text)
        self.assertIn("日期：2026-07-09", text)
        self.assertIn("转发：3条", text)
        self.assertIn("活跃时段：20:00-21:00", text)
        self.assertIn("首次转发：01:18", text)
        self.assertIn("最后转发：20:45", text)
        self.assertIn("运行状态：正常", text)
        self.assertIn("异常记录：0次", text)
        self.assertNotIn("约", text)
        self.assertNotIn("仅统计Bot转发，不代表内容正确。", text)
        self.assertNotIn("转发成功", text)
        self.assertNotIn("成功率", text)
        self.assertNotIn(" 条", text)
        self.assertNotIn("T", text)
        self.assertNotIn("+08:00", text)
        self.assertNotIn("复制", text)

    def test_format_report_hides_failure_reasons_and_handles_empty_periods(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = EventStore(Path(tmp) / "assistant.sqlite3")
            try:
                failed_stats = store.stats_between(
                    datetime(2026, 7, 9, 0, 0, tzinfo=TZ),
                    datetime(2026, 7, 10, 0, 0, tzinfo=TZ),
                )
                store.record_copy_failure("-1001", "source", 10, "42", "bad request", datetime(2026, 7, 10, 1, 0, tzinfo=TZ))
                store.record_copy_failure("-1001", "source", 11, "42", "bad request", datetime(2026, 7, 10, 1, 5, tzinfo=TZ))
                stats = store.stats_between(
                    datetime(2026, 7, 10, 0, 0, tzinfo=TZ),
                    datetime(2026, 7, 11, 0, 0, tzinfo=TZ),
                )
            finally:
                store.close()

        period = scheduled_period("daily", datetime(2026, 7, 10, 0, 0, tzinfo=TZ))
        empty_text = format_report("daily", period, failed_stats, datetime(2026, 7, 10, 0, 0, tzinfo=TZ))
        self.assertIn("转发：0条", empty_text)
        self.assertIn("内容纠错：删除0条", empty_text)
        self.assertNotIn("纠错保留", empty_text)
        self.assertNotIn("批量保护", empty_text)
        self.assertIn("运行状态：待命中", empty_text)
        self.assertIn("异常记录：0次", empty_text)
        self.assertNotIn("仅统计Bot转发，不代表内容正确。", empty_text)

        failed_period = scheduled_period("daily", datetime(2026, 7, 11, 0, 0, tzinfo=TZ))
        failed_text = format_report("daily", failed_period, stats, datetime(2026, 7, 11, 0, 0, tzinfo=TZ))
        self.assertIn("异常记录：2次", failed_text)
        self.assertNotIn("原因：", failed_text)
        self.assertNotIn("bad request", failed_text)
        self.assertIn("运行状态：有异常", failed_text)

    def test_report_includes_moderation_statistics(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = EventStore(Path(tmp) / "assistant.sqlite3")
            try:
                stats = store.stats_between(
                    datetime(2026, 7, 10, 0, 0, tzinfo=TZ),
                    datetime(2026, 7, 11, 0, 0, tzinfo=TZ),
                )
            finally:
                store.close()
        period = scheduled_period("daily", datetime(2026, 7, 11, 0, 0, tzinfo=TZ))

        text = format_report(
            "daily",
            period,
            stats,
            datetime(2026, 7, 11, 0, 0, tzinfo=TZ),
            moderation_stats=ModerationStats(deleted_count=2, kept_count=1, protected_count=1),
        )

        self.assertIn("内容纠错：删除2条", text)
        self.assertIn("纠错保留：1条", text)
        self.assertIn("批量保护：1次", text)

    def test_weekly_report_shows_exact_average_and_peak_day(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = EventStore(Path(tmp) / "assistant.sqlite3")
            try:
                store.record_copy_success("-1001", "source", 10, "42", 99, datetime(2026, 7, 6, 9, 0, tzinfo=TZ))
                for index, hour in enumerate((8, 12, 20), start=11):
                    store.record_copy_success("-1001", "source", index, "42", 100 + index, datetime(2026, 7, 10, hour, 0, tzinfo=TZ))
                stats = store.stats_between(
                    datetime(2026, 7, 6, 0, 0, tzinfo=TZ),
                    datetime(2026, 7, 13, 0, 0, tzinfo=TZ),
                )
            finally:
                store.close()

        period = scheduled_period("weekly", datetime(2026, 7, 13, 0, 0, tzinfo=TZ))
        text = format_report("weekly", period, stats, datetime(2026, 7, 13, 0, 0, tzinfo=TZ))

        self.assertIn("📊上周周报", text)
        self.assertIn("周期：2026-07-06至2026-07-12", text)
        self.assertIn("转发：4条", text)
        self.assertIn("日均：0.6条", text)
        self.assertIn("最活跃：07-10（3条）", text)
        self.assertIn("最后转发：07-10 20:00", text)
        self.assertNotIn("约", text)

    def test_scheduled_report_titles_describe_previous_periods(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = EventStore(Path(tmp) / "assistant.sqlite3")
            try:
                stats = store.stats_between(
                    datetime(2026, 5, 1, 0, 0, tzinfo=TZ),
                    datetime(2026, 6, 2, 0, 0, tzinfo=TZ),
                )
            finally:
                store.close()

        cases = (
            ("daily", datetime(2026, 6, 2, 0, 0, tzinfo=TZ), "📊昨日日报"),
            ("weekly", datetime(2026, 6, 1, 0, 0, tzinfo=TZ), "📊上周周报"),
            ("monthly", datetime(2026, 6, 1, 0, 0, tzinfo=TZ), "📊上月月报"),
        )
        for kind, now, expected_title in cases:
            with self.subTest(kind=kind):
                period = scheduled_period(kind, now)
                text = format_report(kind, period, stats, now)
                self.assertTrue(text.startswith(expected_title + "\n"))

    def test_manual_daily_period_is_today_to_now(self):
        now = datetime(2026, 7, 10, 16, 20, tzinfo=TZ)
        period = manual_period("daily", now)

        self.assertEqual(period.start, datetime(2026, 7, 10, 0, 0, tzinfo=TZ))
        self.assertEqual(period.end, now)

    def test_manual_current_periods_cover_today_week_and_month(self):
        now = datetime(2026, 7, 10, 16, 20, tzinfo=TZ)

        self.assertEqual(manual_period("daily", now).start, datetime(2026, 7, 10, 0, 0, tzinfo=TZ))
        self.assertEqual(manual_period("weekly", now).start, datetime(2026, 7, 6, 0, 0, tzinfo=TZ))
        self.assertEqual(manual_period("monthly", now).start, datetime(2026, 7, 1, 0, 0, tzinfo=TZ))

    def test_scheduled_weekly_period_on_monday_is_previous_week(self):
        now = datetime(2026, 7, 13, 0, 0, tzinfo=TZ)
        period = scheduled_period("weekly", now)

        self.assertEqual(period.start, datetime(2026, 7, 6, 0, 0, tzinfo=TZ))
        self.assertEqual(period.end, datetime(2026, 7, 13, 0, 0, tzinfo=TZ))

    def test_should_run_reports_at_midnight(self):
        now = datetime(2026, 8, 1, 0, 0, tzinfo=TZ)

        self.assertEqual(should_run_report("daily", now, 0, 0), True)
        self.assertEqual(should_run_report("weekly", now, 0, 0), False)
        self.assertEqual(should_run_report("monthly", now, 0, 0), True)


if __name__ == "__main__":
    unittest.main()
