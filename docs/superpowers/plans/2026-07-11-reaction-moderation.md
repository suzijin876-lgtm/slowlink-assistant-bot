# Reaction Moderation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add safe reaction-driven channel-post deletion, persistent owner controls, Chinese moderation logs, and moderation statistics to version 0.1.13.

**Architecture:** Extend the existing Telegram polling loop with reaction-count and callback updates. Persist moderation state and events in the existing SQLite database, process due deletions from the existing main loop, and feed period moderation totals into the existing report formatter.

**Tech Stack:** Python 3.11 standard library, Telegram Bot API, SQLite, `unittest`, Docker Compose.

---

### Task 1: Telegram API Moderation Operations

**Files:**
- Modify: `assistant_bot/telegram_api.py`
- Modify: `tests/test_telegram_api.py`

- [ ] Add failing payload tests for `sendMessage` inline keyboards, `deleteMessage`, `editMessageText`, and `answerCallbackQuery`.
- [ ] Run the Telegram API tests and verify they fail because the methods/parameters do not exist.
- [ ] Implement the minimum request wrappers and rerun the tests to green.

### Task 2: Persistent Moderation Store

**Files:**
- Modify: `assistant_bot/store.py`
- Modify: `tests/test_store_reports.py`

- [ ] Add failing tests for post registration, latest reaction counts, pending deadlines, restart persistence, final events, recent automatic-delete count, and period moderation statistics.
- [ ] Add `moderation_posts` and `moderation_events` tables and indexes with `CREATE TABLE IF NOT EXISTS` compatibility.
- [ ] Implement locked transactional state transitions and period queries.
- [ ] Extend 90-day cleanup to moderation data and rerun store tests to green.

### Task 3: Reaction And Owner-Control Workflow

**Files:**
- Modify: `assistant_bot/service.py`
- Modify: `tests/test_service.py`

- [ ] Add failing tests proving one downvote does nothing, two downvotes beat one upvote, tied votes do not trigger, and non-source/old posts are ignored.
- [ ] Add failing tests for 60-second pending deletion, vote-recovery cancellation, owner keep, owner immediate delete, restart-resumed deletion, delete failure, and four-per-ten-minute protection.
- [ ] Register eligible source posts before private copying.
- [ ] Handle `message_reaction_count` and owner callback updates.
- [ ] Persist deadlines before notifying the owner, and stop automatic deletion if owner notification cannot be delivered.
- [ ] Process due moderation records from the main loop with idempotent final states and Chinese logs.
- [ ] Rerun service tests to green.

### Task 4: Moderation Report Statistics

**Files:**
- Modify: `assistant_bot/reports.py`
- Modify: `assistant_bot/service.py`
- Modify: `tests/test_store_reports.py`
- Modify: `tests/test_service.py`

- [ ] Add failing report tests for always-visible deleted count and conditional kept/protection counts.
- [ ] Pass period moderation statistics into daily, weekly, monthly, manual, and combined scheduled reports.
- [ ] Keep forwarding failures and moderation statistics separate.
- [ ] Add moderation totals to successful scheduled-report server logs where applicable.

### Task 5: Polling, Version, And Documentation

**Files:**
- Modify: `assistant_bot/__main__.py`
- Modify: `assistant_bot/__init__.py`
- Modify: `VERSION`
- Modify: `README.md`
- Modify: `docs/FEATURES.md`
- Modify: `docs/OPERATIONS.md`
- Modify: `docs/VERSION_ARCHIVE.md`
- Create: `V0.1.13/slowlink_assistant_bot_v0_1_13_update_log.txt`

- [ ] Add `message_reaction_count` and `callback_query` to `ALLOWED_UPDATES`.
- [ ] Run due moderation checks on every completed long-poll iteration.
- [ ] Bump all current-version references to `0.1.13` and document permissions, rules, reports, and logs.

### Task 6: Verify, Package, And Deploy

**Files:**
- Create: `V0.1.13/slowlink_assistant_bot_app_v0_1_13.zip`
- Create: `V0.1.13/slowlink_assistant_bot_v0_1_13_full.zip`
- Deploy to: `/opt/slowlink_assistant_bot`

- [ ] Run AST syntax validation and the complete unit-test suite.
- [ ] Create and inspect archives without `.env`, `data`, caches, or older versions.
- [ ] Upload the full package while preserving server `.env` and `data/`.
- [ ] Rebuild and restart only `slowlink_assistant_bot`.
- [ ] Verify version, health, SQLite migration/integrity, watchdog, Telegram membership, `can_delete_messages`, and current logs.
- [ ] Do not generate a real downvote or delete a live channel post during deployment verification.
