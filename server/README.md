# server/

Python (FastAPI) server. All logic is here; the frontend has no keys.

## Folders (`app/`)

| Folder / file | What it does | Owner |
|---|---|---|
| `main.py` | Server entry point: endpoints (`/health`, `/api/ask`) and error format. | Nuri |
| `gateway.py` | Security gateway (main flow). Every question passes through seven steps in order. | Nuri |
| `schemas.py` | The API contract in code: request and response formats. | Nuri |
| `settings.py` | Reads settings from the `.env` file. | Nuri |
| `slack_connector/` | Fetching channels, users, memberships and messages from Slack. | Nuri |
| `ai/` | AI connection: Gemini and fake provider. | Boran |
| `filters/` | Secret and name masking, hidden instruction detection. | Musa |
| `audit/` | The decision and duration of every step; contains no message text. | Nuri |
| `database/` | SQLite tables. | Nuri |
| `accounts/` | Accounts: password and session token rules, account commands (server only). | Nuri |
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

## End-to-end try

Inside `server/`, with the venv (in `.env`: `ALLOWED_CHANNELS` with the demo channel IDs of genel, dev and yonetim,
`BLOCKED_CHANNELS` with the ID of ik, `AI_PROVIDER=fake`):

```powershell
# If the database does not exist or is empty
.venv/Scripts/python -m app.slack_connector.seed load
.venv/Scripts/python -m uvicorn app.main:app --reload
```

http://localhost:8000/docs → `POST /api/ask` → Try it out → `{"question": "#dev'i özetle"}`.
Data selection rules: [`docs/data-model.md`](../docs/data-model.md) ("Data selection (S1-05)").

API contract: [`docs/api-contract.md`](../docs/api-contract.md)
