# Report Detail Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Publish richer exact-count scheduled reports and fully Chinese scheduled-report logs as SlowLink Assistant Bot 0.1.11.

**Architecture:** Extend the existing SQLite report aggregation in `EventStore.stats_between()` and render the additional fields in `reports.py`. Keep scheduling and delivery in `AssistantService`, changing only presentation and log metadata.

**Tech Stack:** Python 3.11 standard library, SQLite, `unittest`, Docker Compose.

---

### Task 1: Lock Report Behavior With Tests

**Files:**
- Modify: `tests/test_store_reports.py`
- Modify: `tests/test_service.py`
- Modify: `tests/test_deploy_files.py`

- [ ] Add a store test with successes across multiple hours and days, asserting first success, last success, busiest hour, and busiest date.
- [ ] Change report text assertions to require `📊日报`, exact `转发：N条`, the visible date, busiest hour, first time, last time, and no `约`.
- [ ] Add weekly rendering assertions for inclusive period, daily average, and busiest date.
- [ ] Capture the successful scheduled-report log and require `日报发送完成` without `类型=daily`.
- [ ] Run `python -B -m unittest discover -s tests -v` and confirm the new assertions fail before implementation.

### Task 2: Implement Report Metrics And Formatting

**Files:**
- Modify: `assistant_bot/store.py`
- Modify: `assistant_bot/reports.py`
- Modify: `assistant_bot/service.py`

- [ ] Extend `Stats` with `first_success_at`, `peak_hour`, `peak_hour_count`, `peak_day`, and `peak_day_count`.
- [ ] Populate the new fields inside the existing locked `stats_between()` read path using deterministic SQLite queries.
- [ ] Add report-name, inclusive-period, busiest-hour, and daily-average formatting helpers.
- [ ] Render daily, weekly, monthly, empty, and failed reports with exact counts and compact Chinese labels.
- [ ] Remove `约` from the manual current overview.
- [ ] Localize scheduled send, send-failure, pin-failure, and owner-notice report names.
- [ ] Run the focused report and service tests and confirm they pass.

### Task 3: Version And Documentation

**Files:**
- Modify: `assistant_bot/__init__.py`
- Modify: `VERSION`
- Modify: `README.md`
- Modify: `docs/FEATURES.md`
- Modify: `docs/OPERATIONS.md`
- Modify: `docs/VERSION_ARCHIVE.md`
- Create: `V0.1.11/slowlink_assistant_bot_v0_1_11_update_log.txt`

- [ ] Bump every current-version reference from `0.1.10` to `0.1.11`.
- [ ] Document the richer reports and Chinese runtime logs.
- [ ] Add the `V0.1.11` archive entry and update log.

### Task 4: Verify And Package

**Files:**
- Create: `V0.1.11/slowlink_assistant_bot_app_v0_1_11.zip`
- Create: `V0.1.11/slowlink_assistant_bot_v0_1_11_full.zip`

- [ ] Run Python AST syntax validation for all source and test files.
- [ ] Run `python -B -m unittest discover -s tests -v` and require zero failures.
- [ ] Create the app archive from runtime files only.
- [ ] Create the full archive without `.env`, `data`, caches, or older version archives.
- [ ] List both archives and inspect their entries.

### Task 5: Deploy And Verify

**Files:**
- Deploy to: `/opt/slowlink_assistant_bot`

- [ ] Upload the 0.1.11 full package while preserving server `.env` and `data/`.
- [ ] Rebuild and restart only the `assistant_bot` Compose service.
- [ ] Verify running version `0.1.11`, healthy status, zero OOM, and active watchdog.
- [ ] Verify SQLite integrity and the latest local backup.
- [ ] Verify recent logs contain no traceback or fresh error.
- [ ] Confirm the running container code hashes match the local 0.1.11 source.
