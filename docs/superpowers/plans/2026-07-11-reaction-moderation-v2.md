# Reaction Moderation V2 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Release SlowLink Assistant Bot V0.1.14 with `👎` delayed correction, `💩` immediate correction, a one-hour eligibility window, and deletion totals in current owner views.

**Architecture:** Keep the existing Bot API long-polling and SQLite moderation flow. Extend stored reaction counts with `poop_count`, make reaction decisions in `AssistantService`, configure source-channel reactions at startup, and reuse `ModerationStats` for `/report` and `/status`.

**Tech Stack:** Python 3, standard-library `unittest`, SQLite, Telegram Bot API, Docker Compose, PowerShell packaging, Paramiko deployment.

---

### Task 1: Persist the new reaction count safely

**Files:**
- Modify: `assistant_bot/store.py`
- Test: `tests/test_store_reports.py`

- [ ] **Step 1: Write failing migration and persistence tests**

Add tests which create an old-schema SQLite database without `poop_count`, reopen it through `EventStore`, and assert both moderation tables gain `poop_count`. Extend the pending-state test to call:

```python
store.update_moderation_reactions(
    "-1001", 55, thumbs_up=0, thumbs_down=2, poop_count=3, at=posted_at
)
```

Then assert `post["poop_count"] == 3` after reopening.

- [ ] **Step 2: Run the focused tests and verify RED**

Run: `python -m unittest tests.test_store_reports.StoreAndReportTests.test_moderation_schema_migrates_poop_count tests.test_store_reports.StoreAndReportTests.test_moderation_pending_state_survives_database_reopen -v`

Expected: failure because `poop_count` and the new parameter do not exist.

- [ ] **Step 3: Implement idempotent SQLite migration and persistence**

In `_init_schema`, include `poop_count INTEGER NOT NULL DEFAULT 0` in new tables and add an `_ensure_column(table, column, declaration)` helper based on `PRAGMA table_info`. Update `update_moderation_reactions` and `complete_moderation` to read/write `poop_count` while retaining old `thumbs_up` columns.

- [ ] **Step 4: Re-run focused tests and verify GREEN**

Run the command from Step 2. Expected: both tests pass.

### Task 2: Add Telegram reaction verification

**Files:**
- Modify: `assistant_bot/telegram_api.py`
- Modify: `assistant_bot/service.py`
- Modify: `assistant_bot/__main__.py`
- Test: `tests/test_telegram_api.py`
- Test: `tests/test_service.py`
- Test: `tests/test_main_logging.py`

- [ ] **Step 1: Write failing API and startup tests**

Add `test_get_chat_uses_expected_payload` expecting:

```python
{"chat_id": -1001}
```

Add service tests that verify all configured source channels are passed to `verify_source_reactions()`, missing `💩` produces a Chinese warning, and lookup failures do not terminate startup.

- [ ] **Step 2: Run focused tests and verify RED**

Run: `python -m unittest tests.test_telegram_api tests.test_service tests.test_main_logging -v`

Expected: new tests fail because the API/service verification methods do not exist.

- [ ] **Step 3: Implement configuration**

Add `TelegramAPI.get_chat(chat_id)` using `getChat`. Add `AssistantService.verify_source_reactions()` which checks whether `👎` and `💩` are available and logs Chinese status/warnings. Call it after Telegram initialization; failures must not stop forwarding. Telegram's Bot API cannot change available reactions, so the owner changes the channel setting manually.

- [ ] **Step 4: Re-run focused tests and verify GREEN**

Run the command from Step 2. Expected: all focused tests pass.

### Task 3: Implement the two correction paths

**Files:**
- Modify: `assistant_bot/service.py`
- Test: `tests/test_service.py`

- [ ] **Step 1: Update the reaction test helper first**

Change `send_reaction_count` to accept `thumbs_down=0`, `poop_count=0`, and optional `thumbs_up=0` only for backward-compatibility assertions. Include `💩` in the generated Bot API reaction list.

- [ ] **Step 2: Write failing behavior tests**

Cover these cases independently:

```text
👎=2 enters pending even when 👍 is higher
👎 falls to 1 and cancels pending
💩=2 deletes immediately without an owner notice or 60-second wait
💩=1 does not delete
💩 immediate deletion uses the existing 4-per-10-minute protection
posts older than 1 hour are ignored
owner-facing pending/deleted text contains 👎/💩 but no 👍
```

- [ ] **Step 3: Run the new service tests and verify RED**

Run: `python -m unittest tests.test_service.AssistantServiceTests -v`

Expected: failures on the new threshold, immediate path, age limit, and text assertions.

- [ ] **Step 4: Implement minimal moderation logic**

Set `MODERATION_POST_MAX_AGE = timedelta(hours=1)`. Parse counts as `(thumbs_down, poop_count)`. Use `thumbs_down >= 2` for the pending path and `poop_count >= 2` for immediate deletion. Apply the batch limit before all automatic deletes, use reason `poop` for direct correction, and preserve reason `auto` for due `👎` deletion. Remove `👍` from notices and logs.

- [ ] **Step 5: Re-run service tests and verify GREEN**

Run the command from Step 3. Expected: all service tests pass.

### Task 4: Add deletion totals to owner views

**Files:**
- Modify: `assistant_bot/service.py`
- Test: `tests/test_service.py`

- [ ] **Step 1: Write failing current-view tests**

Create a deleted moderation event in today's period and assert:

```python
self.assertIn("内容纠错：删除1条", self.service.current_report_text())
self.assertIn("今日纠错：删除1条", self.service.status_text())
```

Also assert an empty-forward current report still displays `内容纠错：删除0条`.

- [ ] **Step 2: Run focused tests and verify RED**

Run: `python -m unittest tests.test_service.AssistantServiceTests.test_current_report_includes_today_deletions tests.test_service.AssistantServiceTests.test_empty_current_report_includes_zero_deletions tests.test_service.AssistantServiceTests.test_status_includes_today_deletions -v`

Expected: all three fail because the lines are absent.

- [ ] **Step 3: Query and render `ModerationStats`**

In both methods, call `moderation_stats_between(today.start, today.end)`. Always add the required deletion line without changing scheduled report formatting.

- [ ] **Step 4: Re-run focused tests and verify GREEN**

Run the command from Step 2. Expected: all three pass.

### Task 5: Version, documentation, and complete verification

**Files:**
- Modify: `assistant_bot/__init__.py`
- Modify: `VERSION`
- Modify: `README.md`
- Modify: `docs/FEATURES.md`
- Modify: `docs/OPERATIONS.md`
- Modify: `docs/VERSION_ARCHIVE.md`
- Create: `V0.1.14/slowlink_assistant_bot_v0_1_14_update_log.txt`

- [ ] **Step 1: Bump version and update documentation**

Set version to `0.1.14`, document the two reaction paths, one-hour eligibility, current-view deletion totals, and Telegram delivery-delay caveat.

- [ ] **Step 2: Run the full verification suite**

Run:

```powershell
python -m unittest discover -s tests -v
python -m compileall -q assistant_bot tests
```

Expected: all tests pass and compileall exits zero.

- [ ] **Step 3: Build version archives**

Create:

```text
V0.1.14/slowlink_assistant_bot_app_v0_1_14.zip
V0.1.14/slowlink_assistant_bot_v0_1_14_full.zip
V0.1.14/slowlink_assistant_bot_v0_1_14_update_log.txt
```

Refresh `slowlink_assistant_bot_deploy.zip` from the full package. Exclude `.env`, live `data`, caches, and older version archives.

- [ ] **Step 4: Deploy only Assistant Bot**

Upload the full package to `/opt/slowlink_assistant_bot`, preserve `.env` and `data`, rebuild/restart only `slowlink_assistant_bot`, and leave the main SlowLink containers untouched.

- [ ] **Step 5: Verify production**

Confirm version `0.1.14`, container `healthy`, restart count and OOM state, SQLite integrity and migrated columns, watchdog status, source-channel reaction check, matching local/server code hashes, and no fresh traceback in Docker logs.

This directory is not a Git worktree, so no commit steps are included.
