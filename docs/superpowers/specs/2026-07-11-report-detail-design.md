# SlowLink Assistant Bot Report Detail Design

## Goal

Make scheduled reports more informative while keeping them compact, and make all scheduled-report runtime logs readable Chinese.

## Report Content

- Use exact forwarding counts. Do not use `约`.
- Daily reports show the date, forwarding count, busiest hour, first forwarding time, last forwarding time, runtime status, and failure count.
- Weekly and monthly reports show the inclusive period, forwarding count, daily average, busiest date, last forwarding time, runtime status, and failure count.
- Empty periods show `转发：0条`, `运行状态：待命中`, and `异常记录：0次` without invented activity fields.
- Failure summaries remain available when failures exist.
- The manual current overview also removes `约`.

## Runtime Logs

- Replace internal names `daily`, `weekly`, and `monthly` with `日报`, `周报`, and `月报`.
- Successful sends include the visible period, exact forwarding count, and failure count.
- Send failures and pin failures use the same Chinese report name and visible period.

## Data And Performance

- Extend the existing `Stats` result with first-success, busiest-hour, and busiest-date fields.
- Reuse the existing indexed 90-day `copy_events` table. No schema migration or new dependency is required.
- The additional grouped queries only run when a report or status is generated, not on each forwarded message.

## Compatibility

- Preserve forwarding, private commands, report scheduling, report pinning, backups, watchdog behavior, and existing SQLite data.
- Deploy only `slowlink_assistant_bot`.
