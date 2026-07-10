# Installer Prompts And Pinned Service Filter Design

## Goal

Make first-time installation understandable without external documentation, and stop Telegram channel pin notifications from being treated as failed forwards.

## Installer Prompt Design

The installer keeps the existing four required values but presents them as numbered Chinese steps:

1. Bot Token: explain that it comes from `@BotFather`, show a fake format example, and state that the entered value is visible.
2. Owner User ID: explain that this is the owner's personal Telegram numeric ID.
3. Report Group ID: explain that this is the group receiving daily, weekly, and monthly reports and is normally a negative ID.
4. Source Channel IDs: explain that these are the monitored channels, normally negative IDs, with multiple values separated by English commas.

The user explicitly chose visible Bot Token input. The installer must remove terminal echo suppression and must not print the entered value again after submission. Environment-variable based unattended installation remains unchanged.

Validation errors must name the invalid field and repeat the expected format. Report groups and source channels accept negative numeric chat IDs or Telegram usernames; a positive numeric value such as `1` is rejected for those two fields.

## Pinned Service Message Handling

Telegram sends a channel pin action as a `channel_post` service message containing `pinned_message`. `copyMessage` cannot copy that service message and returns HTTP 400.

For an allowed source channel, the service must detect `pinned_message` before creating a moderation record or calling `copyMessage`. It logs one informational line and returns. The skipped notification must not:

- be copied to the owner;
- create a moderation post;
- create a successful or failed copy event;
- affect daily, weekly, monthly, current, or status failure statistics;
- contribute to consecutive-failure alerts.

Normal channel posts continue through the existing copy and moderation flow unchanged.

## Production Data Correction

The already confirmed false failure caused by the pin notification will be removed from production only after a fresh SQLite backup. Cleanup is limited to the exact known failed copy row and its matching moderation row; unrelated failures remain untouched.

## Version And Release

Release as `0.1.16`. Update `VERSION`, runtime version, `CHANGELOG.md`, and user documentation. Run all tests and package checks, publish the GitHub Release, then deploy only `slowlink_assistant_bot`. Do not restart or modify the main SlowLink containers.

## Tests

- Distribution test verifies all four numbered Chinese prompts, field explanations, visible Token input, and absence of `stty -echo`.
- Installer validation test verifies positive numeric report/source IDs are rejected by the shell validation helper.
- Service test sends a `channel_post` containing `pinned_message` and verifies no copy call, no moderation row, and zero copy statistics.
- Existing normal channel-post tests remain green.
