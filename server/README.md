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
The schema version is 2. If you have an older local database, delete `server/agentstack.db` and run `seed load` again.
Details: [`docs/data-model.md`](../docs/data-model.md) ("Slack sync and seed data").

## End-to-end try

Inside `server/`, with the venv (`ALLOWED_CHANNELS=genel,dev,yonetim`, `AI_PROVIDER=fake` in `.env`):

```powershell
# If the database does not exist or is empty
.venv/Scripts/python -m app.slack_connector.seed load
.venv/Scripts/python -m uvicorn app.main:app --reload
```

http://localhost:8000/docs → `POST /api/ask` → Try it out → `{"question": "#dev'i özetle", "user": "ali"}`.
Data selection rules: [`docs/data-model.md`](../docs/data-model.md) ("Data selection (S1-05)").

API contract: [`docs/api-contract.md`](../docs/api-contract.md)
