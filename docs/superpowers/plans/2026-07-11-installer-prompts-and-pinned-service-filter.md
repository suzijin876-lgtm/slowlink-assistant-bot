# Installer Prompts And Pinned Service Filter Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Release V0.1.16 with understandable visible installer inputs and correct handling of Telegram channel pin service messages.

**Architecture:** Keep the existing shell installer and AssistantService boundaries. Improve only the four interactive prompt strings and chat-reference validation in `install.sh`; filter `pinned_message` at the start of the allowed channel-post flow before persistence or Telegram API calls.

**Tech Stack:** POSIX shell, Python 3.11, Telegram Bot API, SQLite, `unittest`, Docker Compose, GitHub Actions.

---

### Task 1: Ignore channel pin service messages

**Files:**
- Modify: `tests/test_service.py`
- Modify: `assistant_bot/service.py`

- [ ] **Step 1: Write the failing service test**

Add a test that sends an allowed `channel_post` with `pinned_message`, then asserts that no copy, moderation row, or copy event exists:

```python
def test_channel_pin_service_message_is_ignored(self):
    self.make_service()
    self.service.handle_update({
        "update_id": 3,
        "channel_post": {
            "message_id": 57,
            "date": int(datetime(2026, 7, 10, 12, 0, tzinfo=TZ).timestamp()),
            "chat": {"id": -1001, "type": "channel", "title": "Source"},
            "pinned_message": {"message_id": 55, "text": "original"},
        },
    })

    self.assertEqual(self.api.copied, [])
    self.assertIsNone(self.store.get_moderation_post("-1001", 57))
    stats = self.store.stats_between(
        datetime(2026, 7, 10, 0, 0, tzinfo=TZ),
        datetime(2026, 7, 11, 0, 0, tzinfo=TZ),
    )
    self.assertEqual(stats.success_count, 0)
    self.assertEqual(stats.failure_count, 0)
```

- [ ] **Step 2: Run the focused test and verify RED**

Run:

```powershell
python -m unittest tests.test_service.AssistantServiceTests.test_channel_pin_service_message_is_ignored -v
```

Expected: FAIL because the current service calls `copy_message` and creates records.

- [ ] **Step 3: Implement the minimal service filter**

In `_handle_channel_post`, after resolving source and message IDs but before `record_moderation_post`, add:

```python
if "pinned_message" in message:
    LOG.info("跳过频道置顶通知：来源=%s 消息=%s", source_title, message_id)
    return
```

- [ ] **Step 4: Run the focused and service test suites**

```powershell
python -m unittest tests.test_service.AssistantServiceTests.test_channel_pin_service_message_is_ignored -v
python -m unittest tests.test_service -v
```

Expected: PASS.

### Task 2: Replace cryptic installer prompts with a visible guided wizard

**Files:**
- Modify: `tests/test_distribution_scripts.py`
- Modify: `install.sh`

- [ ] **Step 1: Write failing prompt and validation tests**

Assert that `install.sh` contains `[1/4]` through `[4/4]`, `@BotFather`, Chinese descriptions for owner/report/source IDs, and a visible-input notice. Assert that `stty -echo` and the secret argument are absent.

Add a shell behavior test that extracts the installer helper functions and runs them through `dash` or `sh`, expecting `-1001234567890` and `@valid_name` to pass while positive numeric report/source value `1` fails.

- [ ] **Step 2: Run the focused test and verify RED**

```powershell
python -m unittest tests.test_distribution_scripts -v
```

Expected: FAIL because prompts are variable names, Token echo is disabled, and positive numeric chat refs currently pass.

- [ ] **Step 3: Implement visible input and numbered prompts**

Simplify `prompt_value` to normal terminal input:

```sh
prompt_value() {
  prompt=$1
  value=""
  while [ -z "$value" ]; do
    printf '%s' "$prompt" > /dev/tty
    IFS= read -r value < /dev/tty || value=""
  done
  printf '%s' "$value"
}
```

Use four multiline prompts with fake examples only. Change the all-numeric positive branch in `is_chat_ref` to `return 1`, while retaining negative numeric IDs and Telegram usernames.

Update validation errors to explain the accepted format, for example:

```sh
is_chat_ref "$REPORT_CHAT_ID_VALUE" || die "报表群ID格式不正确：请填写负数群ID或群用户名"
```

- [ ] **Step 4: Run focused tests and shell syntax checks**

```powershell
python -m unittest tests.test_distribution_scripts -v
& 'C:\Program Files\Git\usr\bin\dash.exe' -n install.sh
& 'C:\Program Files\Git\bin\bash.exe' -n install.sh
```

Expected: PASS.

### Task 3: Release documentation and version

**Files:**
- Modify: `VERSION`
- Modify: `assistant_bot/__init__.py`
- Modify: `CHANGELOG.md`
- Modify: `README.md`
- Modify: `docs/FEATURES.md`
- Modify: `docs/OPERATIONS.md`

- [ ] **Step 1: Bump the version to 0.1.16**

Set both runtime version files to `0.1.16`.

- [ ] **Step 2: Document the behavior**

Add a V0.1.16 changelog section covering guided visible input, rejection of positive group/channel IDs, and ignored pin service notifications. Update installation documentation with the four required values and where each comes from.

- [ ] **Step 3: Run version consistency checks**

```powershell
rg -n '0\.1\.15|0\.1\.16' VERSION assistant_bot README.md docs CHANGELOG.md install.sh
```

Expected: current-version references use `0.1.16`; historical V0.1.15 references remain only in changelog/history documents.

### Task 4: Verify, publish, correct production data, and deploy

**Files:**
- External archive: `D:\Users\szjhs\Documents\tg\slowlink_assistant_bot_releases\V0.1.16\`
- Server: `/opt/slowlink_assistant_bot`

- [ ] **Step 1: Run all local verification**

```powershell
python -m unittest discover -s tests
python -m compileall -q assistant_bot tests
& 'C:\Program Files\Git\usr\bin\dash.exe' -n install.sh manage.sh uninstall.sh ops/slowlink_assistant_watchdog.sh
git diff --check
```

- [ ] **Step 2: Build and independently inspect V0.1.16 assets**

Create app ZIP, full ZIP, update log, and `SHA256SUMS.txt`. ZIP entries must use `/`, and full ZIP must exclude `.env`, `data`, tests, caches, Git data, logs, and local archives.

- [ ] **Step 3: Commit, push, and publish**

Commit the implementation, push `main`, create annotated tag `v0.1.16`, and verify the GitHub Actions Release contains four valid assets.

- [ ] **Step 4: Back up and clean the known false event**

Create a fresh SQLite backup. Delete only the confirmed `copy_events` row for the pin notification whose message ID and exact `message can't be copied` error match, plus its matching moderation row. Verify the report failure count decreases by one and unrelated failures remain.

- [ ] **Step 5: Deploy only Assistant Bot**

Preserve `.env` and `data`, rebuild/recreate only `slowlink_assistant_bot`, restart only its watchdog, and verify:

```text
version=0.1.16
container=healthy
SQLite integrity=ok
watchdog=active
recent logs contain no traceback/error
main slowlink_app and slowlink_redis start times are unchanged
```
