# Data model — v2

The server's SQLite tables. Sprint 1 · S1-03. The schema itself: `server/app/database/schema.py`.

- The database is opened with Python's own `sqlite3` module; there is no extra package, ORM or migration tool.
- The file location is the `DATABASE_PATH` setting in `.env` (a relative path is resolved from the repo root). Tests use an in-memory (`:memory:`) database or a seeded database in a temporary folder; they never touch the real file.
- The schema version is kept in `PRAGMA user_version`; the current version is **3** (MIG-B: channel status `blocked`, no name rule in the table). If the database version is higher than the code's, the tables are not created and an error is raised. If it is lower (and not 0), an error is raised too: delete the database file and load the seed again (no migration code).
- All tables are `STRICT` (a value of the wrong type is rejected; at least SQLite 3.37.0 is needed).
- Time fields are ISO 8601 text (e.g. `2026-10-22T14:05:00+03:00`). The database does not fill in the time itself; the writing code always gives the time.
- There is no cascading delete (`ON DELETE CASCADE`).

## Authorization chain

Which messages a person can see is found with this chain:
`people` → `linked_accounts` (source `slack`) → `slack_users` → `channel_memberships` → `channels` (status `allowed`).
So a person can see the messages of channels where their linked Slack account is a member and whose status is `allowed`; if one link of the chain is missing, they can see nothing.
The authorization check in Stage 2 (`gateway.py` step 2) will use this chain. The temporary `user` field of the request is not part of this chain.

## 1. `people`

People who can log in to the system.

| Field | Description |
|---|---|
| `id` | The person's number id in the system. |
| `display_name` | Name shown on the screen; cannot be empty. |
| `role` | `user` or `admin`; if not given, it is `user`, the one with the least permission. |

## 2. `linked_accounts`

A person's accounts in other sources (Slack, Jira, GitHub).

| Field | Description |
|---|---|
| `id` | Number id of the link row. |
| `person_id` | The person the account is linked to (`people.id`). |
| `source` | Source of the account: `slack`, `jira` or `github`. |
| `source_account_id` | The account's id in that source (e.g. Slack user id `U123`). |
| `link_method` | Who linked the account: `admin` or `self`. |
| `linked_at` | When the account was linked. |

The same source account (`source` + `source_account_id`) cannot be linked to two people; a person can be linked to at most one account in the same source.

## 3. `slack_users`

Everyone in Slack: including people who never log in to the system, and bots.

| Field | Description |
|---|---|
| `slack_id` | Slack user id (e.g. `U123`). |
| `display_name` | Display name in Slack; empty (NULL) if unknown. |
| `real_name` | Real name in Slack; empty (NULL) if unknown. |
| `is_bot` | 1 if a bot, 0 if a human; default 0. |

## 4. `channels`

Slack channels and whether the assistant can read them.

| Field | Description |
|---|---|
| `slack_id` | Slack channel id (e.g. `C123`). |
| `name` | Channel name, without `#` (e.g. `dev`). |
| `is_private` | 1 if the channel is private in Slack, otherwise 0. |
| `status` | `allowed`, `excluded` or `blocked`; a new channel always starts as `excluded`; being private or not does not change this. |

The status is computed from the **channel id** (`slack_id`) with the `channel_status()` rule (`server/app/database/rules.py`) and the two lists in `.env`, both written as Slack channel IDs:
`BLOCKED_CHANNELS` (never read) and `ALLOWED_CHANNELS` (allow list). The blocked list always wins: an id on the blocked list is `blocked` even if it is also on the allow list.
An id on the allow list is `allowed`; every other channel is `excluded`. The channel name never decides (a name can be changed in Slack, the id cannot); the table has no rule about names.
A value on a list that is not a channel id (`C…` or `G…`, upper case letters and digits) opens no channel.
Note: the channel status `blocked` (a channel on `BLOCKED_CHANNELS`) is not the same thing as `audit_events.blocked_count` or `security.blocked` in the API (things blocked by a filter).

## 5. `channel_memberships`

Which Slack user is a member of which channel.

| Field | Description |
|---|---|
| `channel_id` | Channel (`channels.slack_id`). |
| `slack_user_id` | The Slack user who is a member (`slack_users.slack_id`). |
| `updated_at` | When this membership was last confirmed from Slack; to measure old permission (stale membership). |

A user is written as a member of a channel at most once.

## 6. `messages`

Messages in channels; only sanitized text is kept, there is no raw text field.

| Field | Description |
|---|---|
| `id` | Number id of the message row. |
| `channel_id` | The message's channel (`channels.slack_id`). |
| `ts` | Slack message id; as text and in exactly the "10 digits . 6 digits" format (e.g. `1729500000.000100`); it cannot be written as a decimal number. |
| `author_id` | The Slack user or bot who wrote the message (`slack_users.slack_id`). |
| `sent_at` | When the message was written. |
| `clean_text` | Sanitized message text; the only field where message text is kept. |
| `is_suspicious` | 1 if the message was found suspicious, 0 if not; empty (NULL) if not checked yet. |

The same `ts` cannot be written twice in the same channel.

## 7. `audit_events`

Decisions of the gateway steps and of Slack sync runs. There is no message text, question, answer or free text field; only codes, counts and durations are kept.

| Field | Description |
|---|---|
| `id` | Number id of the record row. |
| `created_at` | Time of the event. |
| `request_id` | The request id (lower case hex characters, at most 64); for Slack sync it is the id of that run. |
| `person_id` | The person who made the request (`people.id`); empty (NULL) if identity could not be found or for Slack sync. |
| `step` | One of the 7 gateway steps (`identity` … `presentation`) or `slack_sync`. |
| `decision` | `passed` / `stopped` for a gateway step, `ok` / `error` for Slack sync. |
| `reason_code` | Fixed code of the decision (only upper case letters, digits and `_`, at most 40 characters; e.g. `NOT_CHANNEL_MEMBER`); can be empty. |
| `channel_id` | The channel the event is about (`channels.slack_id`); e.g. a channel that could not be fetched; can be empty. |
| `message_count` | Number of messages handled in the step; for Slack sync, the number of new messages. |
| `channel_count` | Number of channels handled in Slack sync. |
| `user_count` | Number of users handled in Slack sync. |
| `membership_count` | Number of memberships handled in Slack sync. |
| `blocked_count` | Number of things blocked in this step. |
| `masked_count` | Number of things masked in this step. |
| `suspicious_count` | Number of things found suspicious in this step. |
| `duration_ms` | Duration of the step, milliseconds. |

All counts are at least 0 and are 0 if not given.

**Slack sync record (S1-04):** Every sync run gets a new id (same format as `request_id` in the gateway, lower case hex) and writes this id to the `request_id` field; `person_id` stays empty.
At the end of the run one summary row is written (`step = slack_sync`, `decision = ok`, with `channel_count`, `user_count`, `membership_count`, `message_count` filled).
For every channel that could not be fetched a separate row is written (`decision = error`, e.g. `reason_code = CHANNEL_FETCH_FAILED`, `channel_id` filled).

Reason codes of Slack sync:

| Code | Decision | Meaning |
|---|---|---|
| `CHANNEL_LIST_FAILED` | `error` | The channel list could not be fetched; nothing was written. |
| `USER_LIST_FAILED` | `error` | The user list could not be fetched; nothing was written. |
| `DB_WRITE_FAILED` | `error` | The user and channel lists could not be written; nothing was written. |
| `BOT_NOT_IN_CHANNEL` | `error` | The channel is allowed but the bot is not in it; no request to Slack was made for that channel. |
| `CHANNEL_FETCH_FAILED` | `error` | The channel's members or messages could not be fetched (e.g. Slack `not_in_channel`, too many requests); old rows of the channel were not touched. |
| `CHANNEL_WRITE_FAILED` | `error` | The channel's data could not be written to the database; that channel's transaction was rolled back. |
| `SOME_CHANNELS_FAILED` | `ok` | Summary row: at least one channel failed. If there is no error, `reason_code` is empty. |

Slack's own error code (e.g. `not_in_channel`) is not written to the audit log; it only appears on the screen.

## 8. `ai_calls`

Measurements of every call made to the AI. Prompt and answer text are not kept.

| Field | Description |
|---|---|
| `id` | Number id of the call row. |
| `created_at` | When the call was made. |
| `request_id` | The request the call belongs to (same value as `audit_events.request_id`). |
| `model` | Name of the model used (only letters, digits, `.`, `_`, `-`; at most 100 characters). |
| `result` | `ok`, `provider_error` or `timeout`; matches the `PROVIDER_ERROR` and `TIMEOUT` errors in the API contract. |
| `messages_sent` | Number of messages sent to the AI. |
| `duration_ms` | Duration of the call, milliseconds. |
| `input_tokens` | Number of tokens sent; empty (NULL) if unknown (e.g. on error). |
| `output_tokens` | Number of tokens received; empty (NULL) if unknown (e.g. on error). |

**When it is written (S1-05):** Every time the gateway calls the AI, one row is written (`gateway.ask_ai`). If the provider returns an error, the row is written first (`TIMEOUT` → `timeout`, all other codes → `provider_error`, tokens empty, model name from the `GEMINI_MODEL` setting or `unknown`), then the error goes back unchanged as 502/504 in the API contract. For a request where the AI is not called (no access, no messages) no row is written. If the row cannot be written, the real answer or error does not change; only the request id and the error type are written to the server log.

## Slack sync and seed data (S1-04)

Code: `server/app/slack_connector/`. Commands run inside `server/`:

```powershell
.venv/Scripts/python -m app.slack_connector.sync [--days 30] [--from-scratch]
.venv/Scripts/python -m app.slack_connector.seed export [--file PATH] [--overwrite]
.venv/Scripts/python -m app.slack_connector.seed load [--file PATH]
```

Sync rules:

- The token is read only from `SLACK_BOT_TOKEN` in `.env`; it is never written to the screen, the audit log, an error message or the seed file.
- The status of channels is computed again on every run from the channel id with `ALLOWED_CHANNELS` and `BLOCKED_CHANNELS`. Right before a member or message request for a channel, the status is computed once more from the id; no request at all is made to Slack for an `excluded` or `blocked` channel.
- A renamed channel keeps its id, so it keeps its status; a new channel opened with an old name has a new id and starts as `excluded`.
- A channel no longer seen in the Slack channel list (archived, deleted, bot removed from a private channel) becomes `excluded` (or `blocked` if its id is on `BLOCKED_CHANNELS`); never `allowed`.
- The messages and memberships of every channel with status `excluded` or `blocked` are deleted; the channel row stays (the audit log may point to it).
- Before starting, the command checks the lists: a value in `BLOCKED_CHANNELS` that is not a channel id stops it (`ERROR: BLOCKED_CHANNELS takes channel IDs; invalid values: …`, exit code 2, nothing is fetched or written). A value in `ALLOWED_CHANNELS` that is not a channel id, an empty `ALLOWED_CHANNELS` and an id on both lists give a `WARNING:` line; the command goes on.
- If the bot is not in an allowed channel, no request is made for that channel and a `BOT_NOT_IN_CHANNEL` record is written.
- The member list of every allowed channel is renewed in one transaction: a membership row no longer in Slack is deleted, the `updated_at` of the others is renewed.
- Only people's plain messages are written: every message with a subtype (`subtype`) (joined the channel, bot message, channel renamed, reply sent from a thread to the channel, etc.), a message with no author or an empty text is skipped. The screen shows the number skipped per channel and the breakdown of reasons (e.g. `3 skipped: channel_join 3`); this breakdown is not written to the audit log.
- `sanitize.sanitize()` is called right before a message is written to the database (for now it does not change the text; the filter is connected in Stage 3).
- The same message (`channel_id` + `ts`) is not written twice; running the command again does not duplicate messages.
- If Slack says "too many requests" (HTTP 429), it waits for `Retry-After` (one wait is at most 120 seconds) and tries at most 5 times.
- `--days` default is 30 (minimum 1, maximum 365). The demo messages were written on 22 October 2026; to get them in a real sync after about 21 November, increase `--days` or use the seed.
- `--from-scratch`: before syncing, all `messages` and `channel_memberships` rows are deleted; the audit log and other tables stay. If the database file is deleted, the command also works on an empty file.

Seed data, default file `demo-data/slack-seed.json`:

- JSON, UTF-8, LF. Fields: `format` (`agentstack-slack-seed`), `version` (2), `channels` (`slack_id`, `name`, `is_private`), `slack_users` (`slack_id`, `display_name`, `real_name`, `is_bot`), `channel_memberships` (`channel_id`, `slack_user_id`), `messages` (`channel_id`, `ts`, `author_id`, `sent_at`, `clean_text`). The loader accepts only version 2.
- Only allowed channels, their memberships and messages, and the users these rows mention go in. The audit log, AI calls, people, linked accounts, `status`, `updated_at` and `is_suspicious` do not.
- Secret check (when writing and reading): the token used for syncing cannot appear in the file; every text matching the `xox?-`, `ghp_`, `AIza`, `AKIA` patterns must contain `EXAMPLE`. A file that fails the check is not written or loaded; the error message shows only the name of the pattern.
- `load` loads only into a database whose Slack tables are empty. The channel status is computed again from the channel id with the loader's `ALLOWED_CHANNELS` and `BLOCKED_CHANNELS` lists (the seed file has no status); memberships and messages of a channel that comes out `excluded` or `blocked` are not loaded. The same list checks as in sync apply (an invalid `BLOCKED_CHANNELS` value stops `load`, exit code 2, nothing is loaded).

## Data selection (S1-05)

Code: `server/app/data_selection/`. The gateway's step 3 (`gateway.data_selection`) selects the messages that go to the AI like this:

- A channel name is recognized only in the `#name` form; the name goes on with letters, digits, `_` and `-` and stops at an apostrophe (`#dev'i`, `#yonetim'de` → `dev`, `yonetim`). Upper/lower case does not matter. If more than one name appears, all are selected.
- Names without `#` are not recognized ("genel olarak…", "dev bir sorun", "yonetim hakkında"); these questions go to all allowed channels.
- `#` expressions made only of digits ("PR #17", "#1 öncelik") are not channel names; they are ignored.
- The name in the question is turned into a channel row by the `name` in the table; the permission is checked from that row's id and status.
- If at least one of the names in the question is not in the database, belongs to more than one row (e.g. a stale old name), or is not `allowed` (e.g. `#ik`, `#bugs`), the request stops: the AI is not called, the answer status is `no_access`. This is a channel-level check, not per-person authorization (Stage 2).
- At question time a channel is read only if it is `allowed` in the table **and** by the current `.env` lists (`ALLOWED_CHANNELS`, `BLOCKED_CHANNELS`); so a channel blocked or removed from the allow list in `.env` is not read even before the next sync or seed load. List warnings are written to the server log once per process.
- If the question has no channel name, all channels with status `allowed` are read (with the same question-time check).
- The query also always applies the `channels.status = 'allowed'` condition; a message of an `excluded` or `blocked` channel is never selected by any path.
- At most 50 messages (in total, not per channel) are selected: the newest 50 messages (by `ts`), sent to the AI from oldest to newest.
- Author name: `real_name`, otherwise `display_name`, otherwise `slack_id`. The `<@U…>` and `<#C…>` mentions in the text are turned into readable names only in the data sent to the AI (`@Ali Kaya`, `#yonetim`); `clean_text` does not change, other `<…>` forms stay as they are.
- If there are no messages in the selected channels, the AI is not called and the answer is "No messages were found for this question." If the `channels` table is completely empty, the server log says to run `seed load` or `sync` first.
- `sources` in the answer stays empty in Sprint 1.

## Known limitations

- A message edited in Slack is not updated in the database; a deleted message stays in the database (fixed with `--from-scratch`).
- If a channel's member list cannot be fetched, the channel's old memberships stay; how old they are can be seen from `updated_at`.
- `sanitize()` does not change the text for now: until Stage 3, `clean_text` is actually the text in Slack.
- The foreign key check works only on a connection opened with `connect()`; code that opens the database another way (`sqlite3.connect`) loses this check.
- The value list of `audit_events.step` matches `gateway.STEPS` by hand; if a step is added to the gateway, the schema must be updated too (a test catches the difference).
- Thread replies, attachments and files are out of scope.
- A separate table for the masked text sent to the AI will be added in Stage 3.
