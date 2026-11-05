# server/

Python (FastAPI) server. All logic is here; the frontend has no keys.

## Folders (`app/`)

| Folder / file | What it does | Owner |
|---|---|---|
| `main.py` | Server entry point: endpoints (`/health`, `/api/auth/*`, `/api/ask`) and error format. | Nuri |
| `gateway.py` | Security gateway (main flow). Every question passes through seven steps in order. | Nuri |
| `schemas.py` | The API contract in code: request and response formats. | Nuri |
| `settings.py` | Reads settings from the `.env` file. | Nuri |
| `slack_connector/` | Fetching channels, users, memberships and messages from Slack. | Nuri |
| `ai/` | AI connection: Gemini and fake provider. | Boran |
| `filters/` | Secret and name masking, hidden instruction detection. | Musa |
| `audit/` | The decision and duration of every step; contains no message text. | Nuri |
| `database/` | SQLite tables. | Nuri |
| `accounts/` | Accounts: password and session token rules, login flow, attempt limit, sessions, account commands (server only). | Nuri |
| `data_selection/` | Selects the messages that go to the AI for a question. | Nuri |

## Single path rule

**Only `gateway.py` calls** the AI connection (`ai/`). Neither the frontend nor another module reaches the AI directly. No shortcut.

## Run (Windows, PowerShell)

```powershell
cd server
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
uvicorn app.main:app --reload
```
In the browser: http://localhost:8000/health and http://localhost:8000/docs

## Tests

```powershell
cd server
.venv\Scripts\Activate.ps1
pytest
```

## Slack data

Inside `server/`, with the venv:

```powershell
# Sync from Slack (SLACK_BOT_TOKEN is needed in .env). Running it again does not duplicate messages.
.venv/Scripts/python -m app.slack_connector.sync
# Last 7 days; or first delete all messages and memberships and sync from scratch
.venv/Scripts/python -m app.slack_connector.sync --days 7
.venv/Scripts/python -m app.slack_connector.sync --from-scratch
# Write the synced data to the demo-data/slack-seed.json file
.venv/Scripts/python -m app.slack_connector.seed export
# Without a bot token: load the seed file into an empty database
.venv/Scripts/python -m app.slack_connector.seed load
```

`--days` default is 30; the demo messages were written on 22 October 2026, so to get them in a real sync after about 21 November, increase `--days` or use the seed.
The schema version is 4. If you have an older local database, delete `server/agentstack.db`, run `seed load` again
and create the demo accounts again (see "Accounts").
Details: [`docs/data-model.md`](../docs/data-model.md) ("Slack sync and seed data").

## Channel IDs

`ALLOWED_CHANNELS` and `BLOCKED_CHANNELS` in `.env` take Slack **channel IDs** (e.g. `C0123ABCDEF`), comma separated, not names.
A channel name can be changed in Slack; its ID cannot, so a name never allows a channel.

- Where to find a channel ID: in Slack click the channel name → channel details → **Channel ID** at the bottom;
  or, in the browser while the channel is open, the last part of the address.
- `BLOCKED_CHANNELS`: channels that are never read (write the IDs of HR, finance and similar channels here).
  It always wins: an ID on both lists is not read (in sync, in `seed load` and at question time).
- Empty `ALLOWED_CHANNELS`: no channel is read. Empty `BLOCKED_CHANNELS`: valid, no channel is blocked.
- A value that is not an ID (e.g. an old `ALLOWED_CHANNELS=genel,dev,yonetim`) opens no channel; `sync` and `seed load`
  print `WARNING: ALLOWED_CHANNELS now takes channel IDs ...` and the server logs the same warning once.
- A value that is not an ID in `BLOCKED_CHANNELS` (e.g. `ik`) stops `sync` and `seed load` (exit code 2, nothing is written).

## Accounts

Accounts are created only on the server, with a command; there is no default password. The command asks for the
password twice with hidden input (at least 12 characters). Never write a password on the command line.
Inside `server/`, with the venv, the demo accounts:

```powershell
# After a new database: load the seed first (link-slack needs the Slack users)
.venv/Scripts/python -m app.slack_connector.seed load
.venv/Scripts/python -m app.accounts create --username ali --name "Ali Kaya"
.venv/Scripts/python -m app.accounts create --username ayse --name "Ayşe Demir"
.venv/Scripts/python -m app.accounts create --username admin --name "Admin" --role admin
# Link the Slack accounts (Slack user IDs of the demo workspace); admin stays without Slack
.venv/Scripts/python -m app.accounts link-slack --username ali --slack-id U0CA5HH3M1V
.venv/Scripts/python -m app.accounts link-slack --username ayse --slack-id U0CAQKKLXTN
.venv/Scripts/python -m app.accounts list
```

Other commands: `set-password --username ali` (ends the account's sessions), `deactivate --username ali`
(the account stays, cannot log in, its sessions end), `activate --username ali`.
A Slack account can be linked to one person only. Exit codes: 0 ok, 1 system error, 2 user error.
Details: [`docs/data-model.md`](../docs/data-model.md) ("Accounts (S2-02)").

## Sign-in and local development

Identity comes only from the server session: `POST /api/auth/login` sets the `agentstack_session` cookie,
`POST /api/auth/logout` ends it, `GET /api/auth/me` tells who is signed in. `POST /api/ask` without a session gets 401.

- `SESSION_COOKIE_SECURE` in `.env` is `true` by default. While you try the screen on `http://localhost`, write
  `SESSION_COOKIE_SECURE=false` in `.env`; otherwise the browser does not send the cookie back: the login looks
  successful, but the next requests get 401. Use `false` **only** for local development over `http://localhost`, never
  in a shared deployment. Any value other than `true` or `false` stops the server at start.
- Use the same host name for the frontend and the server (`localhost` for both, or `127.0.0.1` for both).
- **Run one server process.** The login attempt limit (at most 5 failed attempts per user name and at most 30 per IP
  address in 15 minutes) and the limit of audit events without a session (at most 30 per IP address in 15 minutes) are
  kept in memory: a restart resets them, and with several processes (`uvicorn --workers N`) every process has its own
  counter, so the real limit is higher.
- The IP address is the address of the connection. Proxy headers such as `X-Forwarded-For` are not read: behind a proxy
  all requests count as one IP address.
- All stored password hashes use the same scrypt parameters today. A hash with a different `n` would make "wrong
  password" and "no such account" take different times; if the parameters ever change, re-check this.

Try it in `http://localhost:8000/docs`: `POST /api/auth/login` → Try it out → your user name and password; the browser
keeps the cookie for the next requests.

## Who can read what

A person reads only channels that are allowed and that their linked Slack account is a member of; the role gives no
channel access, and an account without a linked Slack account reads nothing. Details:
[`docs/data-model.md`](../docs/data-model.md) ("Authorization chain").

**Stale access:** memberships come from the last Slack sync. A person removed from a channel in Slack can still see it
until the next `sync`; automatic sync comes in Stage 5. A channel added to `BLOCKED_CHANNELS` is closed on the next
question, without a sync.

## Audit log

Every gateway step that runs writes one row to `audit_events` (at most 7 rows per question, the same `request_id` as the
answer); the row has only codes, counts and durations, never the question, a message, the answer or a password.

See the events locally: sign in as an admin account in `http://localhost:8000/docs` (`POST /api/auth/login`), then
`GET /api/admin/events` → Try it out (or open `http://localhost:8000/api/admin/events?limit=10` in the same browser).
Newest event first, `limit` at least 1 and at most 100, default 50. A signed-in account that is not an admin gets 403;
without a session the answer is 401.

If a gateway event cannot be written (disk full, database locked), the question stops with 500 `SERVER_ERROR` and the
AI is not called if it has not been called yet: nothing runs without a record. The server log gets only the step, the
request id and the error type. Two records are different on purpose: if a login or logout event or an `ai_calls` row
cannot be written, the login or the answer still works and the error is logged.
Details: [`docs/data-model.md`](../docs/data-model.md) (section 7).

## End-to-end try

Inside `server/`, with the venv (in `.env`: `ALLOWED_CHANNELS` with the demo channel IDs of genel, dev and yonetim,
`BLOCKED_CHANNELS` with the ID of ik, `AI_PROVIDER=fake`, `SESSION_COOKIE_SECURE=false`; the demo accounts from "Accounts"):

```powershell
# If the database does not exist or is empty
.venv/Scripts/python -m app.slack_connector.seed load
.venv/Scripts/python -m uvicorn app.main:app --reload
```

http://localhost:8000/docs → `POST /api/auth/login` → Try it out → sign in; then `POST /api/ask` → Try it out → `{"question": "#dev'i özetle"}`.
Data selection rules: [`docs/data-model.md`](../docs/data-model.md) ("Data selection (S1-05)").

API contract: [`docs/api-contract.md`](../docs/api-contract.md)
