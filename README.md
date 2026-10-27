# Agent Stack

Security-first AI assistant for company data (Slack). Permission checks, secret masking, prompt-injection defense and attack tests.

An open source system that gives company data (Slack first) to an AI assistant safely. Core principle: **even if the AI is tricked, nothing leaks.** Security comes from the architecture, not from the model behaving well.

> Status: POC, in development (Sprint 1). Works only with fake data in the test Slack.

## Folders

| Folder | What is inside? |
|---|---|
| `server/` | Python (FastAPI) server: security gateway, Slack connector, AI connection, filters, audit log, database (SQLite). |
| `web/` | React frontend: chat screen and security panel. It contains no keys. |
| `demo-data/` | Fake demo data: scenario document, secret catalog examples, seed data. Excluded from secret scanning. |
| `slack-manifest.yaml` | Ready definition of the Slack app (read-only permissions). |

## Single path rule

Every request that goes to the AI passes through the security gateway. Only the gateway calls the AI connection; the frontend never reaches the AI directly.

## Setup (development)

1. Copy `.env.example` as `.env` and enter your own values. `.env` never goes into the repo.
2. Server and frontend setup steps will be added in Sprint 1.

## Security rules

- A real key, password or personal information never goes into the repo.
- Everyone uses their own Gemini key; keys are not shared.
- Every change that goes into the main branch is reviewed by someone else.
