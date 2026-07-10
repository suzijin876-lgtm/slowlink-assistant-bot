# SlowLink Assistant Bot Reaction Moderation V2 Design

## Goal

Simplify channel correction to two negative reactions, shorten the eligible post window, and expose deletion totals in the owner's current views.

## Reaction Rules

- The intended source-channel reaction set is `👎` and `💩`; Telegram channel settings must be changed manually because the Bot API has no setter for available reactions.
- `👎 >= 2` starts the existing 60-second pending-delete flow.
- `💩 >= 2` skips the 60-second wait and attempts automatic deletion as soon as the Bot receives the aggregate reaction update.
- `👍` is ignored by the algorithm and removed from owner notices and runtime logs.
- If both thresholds are present, the `💩` immediate-delete rule takes priority.
- A pending `👎` deletion is cancelled when the latest `👎` count drops below 2.

## Safety Rules

- Only posts observed by this Bot after deployment are eligible.
- Only posts less than 1 hour old are eligible; this is an event-validity window, not an old-message polling loop.
- Both `👎` and `💩` automatic deletions share the existing limit of at most 4 automatic deletions in a rolling 10-minute window.
- The fifth automatic deletion enters protected state and requires the owner to choose `保留` or `立即删除`.
- An explicit owner `立即删除` action continues to bypass the automatic batch limit.
- Telegram reaction-count delivery can still be delayed; immediate means no additional Bot-side 60-second wait after a qualifying `💩` update arrives.

## Persistence And Compatibility

- Add a `poop_count` field to moderation post and event records with a default of zero.
- Apply an idempotent SQLite migration so the existing database and statistics are preserved.
- Keep the old `thumbs_up` columns for database compatibility, but stop using them in decisions or user-facing text.
- Existing backups, forwarding history, report history, and Telegram configuration remain untouched.

## Reports And Logs

- `/report` current report always includes today's `内容纠错：删除N条`, including when there were no forwards.
- `/status` includes today's `今日纠错：删除N条`.
- Daily, weekly, monthly, and combined scheduled reports keep their existing correction statistics.
- Chinese server logs distinguish `👎进入待删除`, `💩直接删除`, cancellation, batch protection, owner action, and failure.

## Telegram Setup

- Add Bot API `getChat` support and verify source-channel available reactions during startup.
- Log a Chinese warning when `👎` or `💩` is missing, but do not stop forwarding or reporting.
- The owner enables only `👎` and `💩` in Telegram channel settings; `👍` remains ignored even if it is still visible.
- The Bot must remain a channel administrator with permission to delete messages.

## Verification And Delivery

- Add regression tests for both thresholds, cancellation, one-hour expiry, shared batch protection, SQLite migration, report/status totals, reaction verification, and Chinese logs.
- Bump the version to `0.1.14`.
- Run the complete unit-test and syntax suites, create the normal app/full/update-log archive, deploy only `slowlink_assistant_bot`, and verify the running version, health, database, reaction configuration, and recent logs.

## Scope

- Change only SlowLink Assistant Bot.
- Do not modify the main SlowLink system.
- Do not add historical-message polling or user-account clients.
