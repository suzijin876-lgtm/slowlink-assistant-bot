# Combined Scheduled Reports Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Merge any two or three overlapping scheduled reports into one Telegram message while preserving independent sent-state records.

**Architecture:** Change `AssistantService.run_due_reports()` from immediate per-kind sending to a collect-then-send flow. Existing report formatting and SQLite report keys remain unchanged; only delivery, pinning, logging, and state finalization are grouped.

**Tech Stack:** Python 3.11 standard library, SQLite, `unittest`, Docker Compose.

---

### Task 1: Add Failing Collision Tests

**Files:**
- Modify: `tests/test_service.py`

- [ ] Add a Monday test that requires daily and weekly sections in one sent message, one pin, and both report states marked sent.
- [ ] Add a month-first test that requires daily and monthly sections in one sent message.
- [ ] Add a Monday/month-first test that requires daily, weekly, and monthly sections in one sent message.
- [ ] Add a combined-send failure test that requires neither included report state to be marked sent.
- [ ] Run `python -B -m unittest discover -s tests -v` and confirm the new tests fail because the current code sends separate messages.

### Task 2: Implement Collect-Then-Send Delivery

**Files:**
- Modify: `assistant_bot/service.py`

- [ ] Collect due unsent report records as kind, period, stats, and rendered text tuples.
- [ ] Return without sending when the collection is empty.
- [ ] Join multiple report texts with `────────`; keep a single report unchanged.
- [ ] Send and pin exactly one Telegram message.
- [ ] Use combined Chinese logs and owner notices when more than one report is included.
- [ ] Mark every included report sent only after the shared message succeeds.
- [ ] Run the complete test suite and require zero failures.

### Task 3: Version And Documentation

**Files:**
- Modify: `assistant_bot/__init__.py`
- Modify: `VERSION`
- Modify: `README.md`
- Modify: `docs/FEATURES.md`
- Modify: `docs/OPERATIONS.md`
- Modify: `docs/VERSION_ARCHIVE.md`
- Create: `V0.1.12/slowlink_assistant_bot_v0_1_12_update_log.txt`

- [ ] Bump the current version from `0.1.11` to `0.1.12`.
- [ ] Document two-report and three-report collision behavior.
- [ ] Add the new version archive entry and update log.

### Task 4: Verify, Package, And Deploy

**Files:**
- Create: `V0.1.12/slowlink_assistant_bot_app_v0_1_12.zip`
- Create: `V0.1.12/slowlink_assistant_bot_v0_1_12_full.zip`
- Deploy to: `/opt/slowlink_assistant_bot`

- [ ] Run AST syntax validation and the complete unit-test suite.
- [ ] Create and inspect the app/full archives without `.env`, `data`, caches, or older versions.
- [ ] Upload the full package while preserving server `.env` and `data/`.
- [ ] Rebuild and restart only `slowlink_assistant_bot`.
- [ ] Verify version, health, SQLite integrity, watchdog state, Telegram permissions, and current logs.
