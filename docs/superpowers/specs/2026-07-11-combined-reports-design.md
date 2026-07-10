# SlowLink Assistant Bot Combined Reports Design

## Goal

Prevent scheduled daily, weekly, and monthly reports from producing multiple group messages when their schedules overlap.

## Rules

- Collect every unsent report due in the current scheduled minute before sending anything.
- One due report keeps the existing single-report message and log behavior.
- Two due reports are joined into one Telegram message with a visible separator.
- Three due reports are joined into one Telegram message with the same separator.
- A combined message is sent once, pinned once, and unpins the previous report once.
- After a successful send, every included report is marked sent with its own existing period key.
- If the combined send fails, none of the included reports are marked sent, allowing the existing retry loop to try again.
- If pinning fails, the combined message remains marked sent and the owner receives one warning.

## Logs

- Two-report example: `组合报表发送完成：包含=日报、周报`.
- Three-report example: `组合报表发送完成：包含=日报、周报、月报`.
- Combined failures and pin failures use the same Chinese report list.
- Single reports keep the existing `日报发送完成` / `周报发送完成` / `月报发送完成` format.

## Compatibility

- Preserve existing report text, report periods, SQLite schema, forwarding, backups, and watchdog behavior.
- Deploy only `slowlink_assistant_bot`.
