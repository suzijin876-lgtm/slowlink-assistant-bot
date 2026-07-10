# SlowLink Assistant Bot Reaction Moderation Design

## Goal

Let channel followers flag bad posts with reactions and let Assistant Bot safely remove confirmed bad posts without changing the main SlowLink system.

## Trigger And Safety Rules

- Listen to aggregate channel reaction-count updates for configured source channels.
- Only standard `👍` and `👎` emoji count.
- Enter pending deletion only when `👎 >= 2` and `👎 > 👍`.
- Wait 60 seconds after the threshold is first observed.
- Cancel pending deletion if the latest stored counts no longer satisfy both conditions.
- Only posts first observed by this Bot and less than 24 hours old are eligible.
- Automatically delete at most 4 posts in a rolling 10-minute window.
- The fifth due post enters protected state and requires an owner decision.

## Owner Controls

- When a post enters pending deletion, privately notify the owner with `保留` and `立即删除` buttons.
- `保留` permanently exempts that message from automatic deletion.
- `立即删除` bypasses the automatic batch limit because it is an explicit owner action.
- If the owner does nothing, the Bot applies the automatic rule after 60 seconds.
- Owner notices are updated after cancellation, deletion, protection, or failure.

## Persistence

- Store observed channel posts, latest reaction counts, moderation state, deadline, and owner notice message ID in SQLite.
- Store final moderation events separately for reporting and rate-limit calculations.
- Pending deadlines survive container restarts.
- Existing daily SQLite backups include the moderation tables automatically.

## Reporting And Logs

- Daily, weekly, and monthly reports always show `内容纠错：删除N条`.
- Show `纠错保留：N条` and `批量保护：N次` only when nonzero.
- Server logs record pending, vote cancellation, owner keep, automatic/owner deletion, protection, and deletion failure in Chinese.
- Moderation actions do not count as forwarding failures.

## Telegram Requirements

- Add `message_reaction_count` and `callback_query` to allowed updates.
- Add Bot API support for `deleteMessage`, `answerCallbackQuery`, and `editMessageText`.
- The Bot must remain an administrator with `can_delete_messages`; this permission was verified before implementation.

## Scope

- Modify only SlowLink Assistant Bot.
- Do not change the main SlowLink project or its posting logic.
- Do not attempt content restoration in this version; the owner's private copy remains available for inspection.
