# Data model — v3

The server's SQLite tables. Sprint 1 · S1-03; accounts and sessions: Sprint 2 · S2-02. The schema itself: `server/app/database/schema.py`.

- The database is opened with Python's own `sqlite3` module; there is no extra package, ORM or migration tool.
- The file location is the `DATABASE_PATH` setting in `.env` (a relative path is resolved from the repo root). Tests use an in-memory (`:memory:`) database or a seeded database in a temporary folder; they never touch the real file.
- The schema version is kept in `PRAGMA user_version`; the current version is **6** (S3-08: `audit_events.masked_kinds` and `audit_events.alarm`; version 5, S3-05: `messages.secret_counts`; version 4, S2-02: accounts in `people`, the `sessions` table, `login`/`logout` steps; version 3, MIG-B: channel status `blocked`, no name rule in the table). If the database version is higher than the code's, the tables are not created and an error is raised. If it is lower (and not 0), an error is raised too: delete the database file and load the seed again (no migration code).
- All tables are `STRICT` (a value of the wrong type is rejected; at least SQLite 3.38.0 is needed: 3.37 for `STRICT`, 3.38 for the built-in JSON functions of the `secret_counts` check).
- Time fields are ISO 8601 text (e.g. `2026-10-22T14:05:00+03:00`). The database does not fill in the time itself; the writing code always gives the time.
- There is no cascading delete (`ON DELETE CASCADE`).

## Authorization chain

Which messages a person can see is found with this chain (S2-05, `gateway.py` step 2):
`people` → `linked_accounts` (source `slack`) → `channel_memberships` → `channels` (allowed at question time).
So a person can see the messages of channels where their linked Slack account is a member and which are allowed; if one link of the chain is missing, they can see nothing.

- The linked Slack id comes from the session (`linked_accounts.source_account_id`) and is compared with `channel_memberships.slack_user_id`; `slack_users` is not queried (the foreign key of `channel_memberships` keeps the row there).
- "Allowed at question time": `allowed` in the table **and** by the current `ALLOWED_CHANNELS` and `BLOCKED_CHANNELS` (`question_time_channels`, `server/app/data_selection/selection.py`). The blocked list always wins, even with a membership row.
- The decision is the pure function `decide_access` (`server/app/data_selection/rules.py`). The role is not one of its inputs: an `admin` sees only the channels their Slack account is a member of.
- Memberships are read from the database on every question, there is no cache: a change counts from the next question. The memberships themselves change only with a Slack sync, so a person removed from a channel can see it until the next sync.
- Data selection reads only the channels of this decision; without a decision it reads nothing.

## 1. `people`

People who can log in to the system (accounts). Accounts are created only with the account commands on the server (see "Accounts (S2-02)"); there is no default password.

| Field | Description |
|---|---|
| `id` | The person's number id in the system. |
| `username` | User name for login; unique, 3–32 characters: lower case `a-z`, digits, `.`, `_`, `-`, starting with a letter or digit. The commands (and the login in S2-03) convert it to lower case first, so `Ali` and `ali` are the same account. |
| `display_name` | Name shown on the screen; cannot be empty. The API contract calls it `name`. |
| `role` | `user` or `admin`; if not given, it is `user`, the one with the least permission. |
| `password_hash` | The scrypt hash of the password, never the password: `scrypt$<n>$<r>$<p>$<salt hex>$<hash hex>` (random 16-byte salt per password; today n = 2^14, r = 8, p = 5, 32 bytes). The table accepts only values starting with `scrypt$`, so a plain password cannot be written by mistake. Empty (NULL): the account cannot log in with any password. |
| `is_active` | 1 active (default), 0 inactive. An inactive account cannot log in and its sessions are ended. Accounts are never deleted. |
| `created_at` | When the account was created. |

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
| `secret_counts` | How many secrets of each kind were masked (`[REDACTED]`) in this message before it was written (S3-05): a JSON object, kind → count, e.g. `{"env_secret":1,"slack_token":2}`; `{}` if none (also the default). Only the 10 secret kinds and counts of at least 1; never a value. Read by the gateway's sanitization step for `security.masked` and `masked_kinds` (S3-08). |

The same `ts` cannot be written twice in the same channel.

## 7. `audit_events`

Decisions of the gateway steps and of Slack sync runs. There is no message text, question, answer or free text field; only codes, counts and durations are kept.

| Field | Description |
|---|---|
| `id` | Number id of the record row. |
| `created_at` | Time of the event. |
| `request_id` | The request id (lower case hex characters, at most 64); for Slack sync it is the id of that run. |
| `person_id` | The person who made the request (`people.id`); empty (NULL) if identity could not be found or for Slack sync. |
| `step` | One of the 7 gateway steps (`identity` … `presentation`), `slack_sync`, `login` or `logout`. |
| `decision` | `passed` / `stopped` for a gateway step, `login` and `logout`; `ok` / `error` for Slack sync. |
| `reason_code` | Fixed code of the decision (only upper case letters, digits and `_`, at most 40 characters; e.g. `NOT_CHANNEL_MEMBER`); can be empty. |
| `channel_id` | The channel the event is about (`channels.slack_id`); e.g. a channel that could not be fetched; can be empty. |
| `message_count` | Number of messages handled in the step; for Slack sync, the number of new messages. |
| `channel_count` | Number of channels handled in Slack sync. |
| `user_count` | Number of users handled in Slack sync. |
| `membership_count` | Number of memberships handled in Slack sync. |
| `blocked_count` | Number of things blocked in this step. |
| `masked_count` | Number of things masked in this step. |
| `suspicious_count` | Number of things found suspicious in this step. |
| `masked_kinds` | What `masked_count` counted, by kind (S3-08): a JSON object, kind → count, e.g. `{"person":3,"slack_token":2}`; `{}` if nothing (also the default). Only the 16 filter kinds and counts of at least 1; the sum of the values equals `masked_count` (checked when the row is written). Never a value. |
| `alarm` | 1 only on a `sanitization` row whose question itself had a certain secret (S3-08); 0 on every other row (a check rejects 1 on any other step). |
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
| `CHANNEL_FILTER_FAILED` | `error` | The secret filter failed on a message of the channel (S3-05); nothing of that channel was written, never a raw text. The screen shows only the error type. |
| `SOME_CHANNELS_FAILED` | `ok` | Summary row: at least one channel failed. If there is no error, `reason_code` is empty. |

Slack's own error code (e.g. `not_in_channel`) is not written to the audit log; it only appears on the screen.

**Login and logout (schema version 4; written from S2-03):** `step = login` with `decision = passed`, or `stopped` with one of the reason codes below; `step = logout` with `decision = passed`. The user name and the password are never written; `person_id` is filled only when the person is known.

| Code | Decision | Meaning |
|---|---|---|
| `INVALID_CREDENTIALS` | `stopped` | Login failed (no such user, inactive account, wrong password or no password set; all the same code). |
| `TOO_MANY_ATTEMPTS` | `stopped` | Login limit reached. |

**Gateway steps (S2-04):** Every step that runs writes one row right after it finishes, in its own transaction, with the `request_id` of the answer and the `person_id` of the session. A stopped request writes nothing for the later steps, so a complete request has 7 rows. `decision = passed` has no reason code; `decision = stopped` has one of the codes below.

| Code | Step | Meaning |
|---|---|---|
| `UNAUTHENTICATED` | `identity` | No valid session. |
| `NO_SLACK_ACCOUNT` | `authorization` | The person has no linked Slack account. |
| `NOT_CHANNEL_MEMBER` | `authorization` | The person's Slack account is not a member of the channel. |
| `CHANNEL_NOT_ALLOWED` | `authorization` / `data_selection` | The channel is not `allowed`. |
| `NO_SLACK_DATA` | `data_selection` | The database has no Slack data. |
| `NO_MESSAGES` | `data_selection` | No message matched the question. |
| `PROVIDER_ERROR`, `TIMEOUT` | `ask_ai` | The AI call failed; `TIMEOUT` → `TIMEOUT`, every other AI error code (e.g. `QUOTA_EXCEEDED`) → `PROVIDER_ERROR`. |

- An unexpected error inside a step: the step is `stopped` with an empty `reason_code`, then the answer is 500.
- `message_count`: messages selected (`data_selection`) or sent to the AI (`ask_ai`); 0 in the other steps.
- `sanitization` (S3-08): `masked_count` / `masked_kinds` count what was masked in the question and in the messages sent to the AI, names (`person`) included, plus the secrets masked at sync (`messages.secret_counts`) of those messages; a value already `[REDACTED]` is not counted again. `alarm` as above; `suspicious_count` is the number of messages removed as suspicious (0 until Stage 4).
- `response_check` (S3-03, S3-08): `blocked_count` = removed links and images; `masked_count` / `masked_kinds` = the secrets of the answer's second scan.
- Every other count is 0, and `masked_kinds` is `{}` on every other row (also `login`, `logout`, `slack_sync`).
- A wrong `messages.secret_counts` value (not a secret kind, or not a whole count of at least 1) stops the question in `data_selection` (500, no reason code); it is never counted as 0.
- `channel_id`: from `authorization` on, the channel if the question names exactly one channel and that name is exactly one row of `channels`, whatever its status; otherwise empty (no name, more than one name, a name that is not in the table). So `#ik` is empty in a database loaded from the seed (the seed has no `ik` row) and filled after a real sync.
- `/api/ask` without a session: no step runs; one row is written (`identity`, `stopped`, `UNAUTHENTICATED`, `person_id` empty), at most 30 rows per IP address in 15 minutes (in memory). Over the limit only a count goes to the server log. `/api/auth/me` and the admin endpoint write no row.
- **If a row cannot be written, the request stops:** the answer is 500 `SERVER_ERROR`, no later step runs and the AI is not called if it has not been called yet; the server log gets only the step, the request id and the error type. Without a session the answer stays 401 and the error is only logged. This is stricter than the login and logout events and `ai_calls`, where the login or the answer still works and the error is logged.

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

## 9. `sessions`

Signed-in sessions (used from S2-03). The session token itself (the cookie value) is in no column: only its SHA-256 hash, so a stolen database gives no usable cookie.

| Field | Description |
|---|---|
| `id` | Number id of the session row. |
| `person_id` | The signed-in person (`people.id`). |
| `token_hash` | SHA-256 of the session token, exactly 64 lower case hex characters; unique. |
| `created_at` | When the session started (login). |
| `expires_at` | When the session ends: at most 8 hours after `created_at` (absolute, no idle timeout). |
| `last_seen_at` | Last request with this session. |

Times are ISO 8601 text in UTC (`+00:00`), given by the writing code. `set-password` and `deactivate` delete all sessions of the person. Expired sessions are rejected and deleted by the login code (S2-03); this version has no clean-up job.

## Accounts (S2-02)

Code: `server/app/accounts/` (`rules.py` pure rules, `store.py` database, `commands.py` command line). Commands run inside `server/`, only on the server:

```powershell
.venv/Scripts/python -m app.accounts create --username ali --name "Ali Kaya" [--role admin]
.venv/Scripts/python -m app.accounts set-password --username ali
.venv/Scripts/python -m app.accounts link-slack --username ali --slack-id U0CA5HH3M1V
.venv/Scripts/python -m app.accounts deactivate --username ali
.venv/Scripts/python -m app.accounts activate --username ali
.venv/Scripts/python -m app.accounts list
```

- The password is never a command line argument (it would stay in the shell history). `create` and `set-password` ask for it twice with hidden input. A password must be at least 12 and at most 128 characters (checked only when it is set, never at login). If it is too short or too long, or the two entries do not match, the command asks again; after 3 failed attempts it stops with exit code 2 and changes nothing.
- `--role` is `user` (default) or `admin`.
- `link-slack` links a Slack user id (`U…` or `W…`) with link method `admin`. The id must be in `slack_users` (load the seed or sync first) and must not be a bot. A Slack account linked to another person, or a person who already has a Slack account, gives an error (exit code 2); the table also blocks the first case.
- `set-password` and `deactivate` end all sessions of the person. `deactivate` never deletes the account; `activate` makes it active again (opens no session).
- `list` shows user name, name, role, active, whether a password is set and the Slack id; never the password hash.
- Exit codes: 0 ok, 1 system error (the database cannot be opened, old schema version), 2 user error or wrong usage. No output ever contains a password, a password hash or a session token.

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
- `sanitize.sanitize()` is called right before a message is written to the database (S3-05): it masks secrets with `mask_secrets` (`[REDACTED]`) and the per-kind counts go to `secret_counts`. Personal data and names are not masked here (only per request, in the gateway). If the filter fails on a message, nothing of that channel is written (`CHANNEL_FILTER_FAILED`). The sync summary and the audit row do not show these counts (`masked_count` of `slack_sync` stays 0, API contract 9).
- The same message (`channel_id` + `ts`) is not written twice; running the command again does not duplicate messages.
- If Slack says "too many requests" (HTTP 429), it waits for `Retry-After` (one wait is at most 120 seconds) and tries at most 5 times.
- `--days` default is 30 (minimum 1, maximum 365). The demo messages were written on 22 October 2026; to get them in a real sync after about 21 November, increase `--days` or use the seed.
- `--from-scratch`: before syncing, all `messages` and `channel_memberships` rows are deleted; the audit log and other tables stay. If the database file is deleted, the command also works on an empty file.

Seed data, default file `demo-data/slack-seed.json`:

- JSON, UTF-8, LF. Fields: `format` (`agentstack-slack-seed`), `version` (2), `channels` (`slack_id`, `name`, `is_private`), `slack_users` (`slack_id`, `display_name`, `real_name`, `is_bot`), `channel_memberships` (`channel_id`, `slack_user_id`), `messages` (`channel_id`, `ts`, `author_id`, `sent_at`, `clean_text`). The loader accepts only version 2.
- Only allowed channels, their memberships and messages, and the users these rows mention go in. The audit log, AI calls, people, linked accounts, `status`, `updated_at` and `is_suspicious` do not.
- Secret check (when writing and reading): the token used for syncing cannot appear in the file; every text matching the `xox?-`, `ghp_`, `AIza`, `AKIA` patterns must contain `EXAMPLE`. A file that fails the check is not written or loaded; the error message shows only the name of the pattern.
- `load` masks secrets the same way as sync (S3-05): the file may contain fake keys (the `.env` message of `#dev`), the database never keeps them; `secret_counts` is computed while loading (the file has no counts). If the filter fails, nothing is loaded (exit code 1). `export` writes the text as stored, so an export of a masked database has `[REDACTED]` and loses the counts when loaded again.
- `load` loads only into a database whose Slack tables are empty. The channel status is computed again from the channel id with the loader's `ALLOWED_CHANNELS` and `BLOCKED_CHANNELS` lists (the seed file has no status); memberships and messages of a channel that comes out `excluded` or `blocked` are not loaded. The same list checks as in sync apply (an invalid `BLOCKED_CHANNELS` value stops `load`, exit code 2, nothing is loaded).

Raw secret check (S3-05), the proof that the database keeps no secret:

```powershell
.venv/Scripts/python -m app.database.check_db [--db PATH]
```

- Scans every `messages.clean_text` (the only column with message text) with the same secret rules as sync and load (`find_secrets` on the normalized text). Every finding counts, certain or suspicious.
- Opens the database read only; it never creates, changes or fixes anything. To fix a finding, delete the database and run `seed load` or sync again.
- Prints only `message <id>: <kind>` per finding and a last line (`0 raw secrets.` or e.g. `2 raw secrets in 1 message.`); never a value or message text.
- Exit codes: 0 no raw secret, 1 at least one, 2 the check could not run (no database file, schema version not the code's, a failing rule: `The secret check failed (<error type>).`, wrong usage). It never prints `0 raw secrets.` when the check did not run.

## Data selection (S1-05)

Code: `server/app/data_selection/`. The gateway's step 3 (`gateway.data_selection`) selects the messages that go to the AI like this:

- A channel name is recognized only in the `#name` form; the name goes on with letters, digits, `_` and `-` and stops at an apostrophe (`#dev'i`, `#yonetim'de` → `dev`, `yonetim`). Upper/lower case does not matter. If more than one name appears, all are selected.
- Names without `#` are not recognized ("genel olarak…", "dev bir sorun", "yonetim hakkında"); these questions go to all allowed channels.
- `#` expressions made only of digits ("PR #17", "#1 öncelik") are not channel names; they are ignored.
- The name in the question is turned into a channel row by the `name` in the table; the permission is checked from that row's id and status.
- If at least one of the names in the question is not in the database, belongs to more than one row (e.g. a stale old name), or is not `allowed` (e.g. `#ik`, `#bugs`), the request stops: the AI is not called, the answer status is `no_access`. Authorization (step 2) decides this first; data selection applies the same channel rule again as a second layer.
- At question time a channel is read only if it is `allowed` in the table **and** by the current `.env` lists (`ALLOWED_CHANNELS`, `BLOCKED_CHANNELS`); so a channel blocked or removed from the allow list in `.env` is not read even before the next sync or seed load. List warnings are written to the server log once per process.
- Only the channels of the authorization decision are read (see "Authorization chain"). If the question has no channel name, these are all allowed channels the person's Slack account is a member of (with the same question-time check).
- The query also always applies the `channels.status = 'allowed'` condition; a message of an `excluded` or `blocked` channel is never selected by any path.
- At most 50 messages (in total, not per channel) are selected: the newest 50 messages (by `ts`), sent to the AI from oldest to newest.
- Author name: `real_name`, otherwise `display_name`, otherwise `slack_id`. The `<@U…>` and `<#C…>` mentions in the text are turned into readable names only in the data sent to the AI (`@Ali Kaya`, `#yonetim`); `clean_text` does not change, other `<…>` forms stay as they are.
- If there are no messages in the selected channels, the AI is not called and the answer is "No messages were found for this question." If the `channels` table is completely empty, the server log says to run `seed load` or `sync` first.
- `sources` in the answer is the list of messages really sent to the AI, in the same order; its `id` is `<channel_id>:<ts>`, which is not sent to the AI (S2-05).

## Known limitations

- A message edited in Slack is not updated in the database; a deleted message stays in the database (fixed with `--from-scratch`).
- If a channel's member list cannot be fetched, the channel's old memberships stay; how old they are can be seen from `updated_at`.
- `sanitize()` masks only what the secret rules (S3-09) find; until they are merged, `clean_text` is the text in Slack and `secret_counts` is `{}`.
- The seed file (version 2) has no `secret_counts`: a seed exported from a masked database loses the counts when loaded.
- The foreign key check works only on a connection opened with `connect()`; code that opens the database another way (`sqlite3.connect`) loses this check.
- The value list of `audit_events.step` (without `slack_sync`, `login`, `logout`) matches `gateway.STEPS` by hand; if a step is added to the gateway, the schema must be updated too (a test catches the difference).
- Thread replies, attachments and files are out of scope.
- A separate table for the masked text sent to the AI will be added in Stage 3.
