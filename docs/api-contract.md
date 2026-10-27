# API contract — v2

What the frontend (web) sends to the server and what it gets back. Sprint 1 · S1-02.
If a change is needed, first a PR that updates this document is opened; the frontend and the server follow it.

Server address (development): `http://localhost:8000`. The frontend reads this address from a setting.

## 1. Health check

`GET /health` → `200`
```json
{ "status": "up" }
```

## 2. Ask a question

`POST /api/ask` · `Content-Type: application/json`

### Request
```json
{
  "question": "#dev'i özetle",
  "user": "ali"
}
```

| Field | Type | Description |
|---|---|---|
| `question` | text, 1–2000 characters | The user's question. |
| `user` | text | **TEMPORARY.** Removed in Stage 2; identity will be read from the session given by the server. If this field stays, it is the biggest authorization hole in the project: Ali can change this field and become Nuri. |

### Successful response — `200`
```json
{
  "request_id": "3f9c2a1b7d4e",
  "status": "ok",
  "answer": "This week in #dev the login page and ...",
  "sources": [
    {
      "channel": "dev",
      "author": "Deniz",
      "time": "2026-10-22T14:05:00+03:00",
      "text": "@Ali you take the login page"
    }
  ],
  "security": { "blocked": 0, "masked": 0, "suspicious": 0 }
}
```

| Field | Description |
|---|---|
| `request_id` | The request id. To match it with the audit log in the panel. |
| `status` | `"ok"` or `"no_access"`. When it is `no_access`, the AI was never called; `answer` is "You don't have access to this information." and `sources` is empty. (Comes into effect in Stage 2.) |
| `answer` | Plain text. **The frontend shows it as plain text**; links and images inside are not made active (against EchoLeak-type leaks). |
| `sources` | The messages the answer is based on. Can be empty. Empty in Sprint 1. |
| `security` | How many things were blocked, masked or found suspicious in this request. Always zero in Sprint 1. |

The answer is not streamed word by word (no streaming): the output check must see the whole answer. The frontend shows "Typing…" while waiting.

### Error response — every error has the same format
```json
{
  "error": { "code": "INVALID_REQUEST", "message": "Invalid request format. See the API contract." }
}
```

| HTTP | `code` | When |
|---|---|---|
| 422 | `INVALID_REQUEST` | A field is missing, empty or too long. |
| 502 | `PROVIDER_ERROR` | The AI provider returned an error or the request limit was reached (S1-08). |
| 504 | `TIMEOUT` | The AI did not answer in time (S1-08). |
| 500 | `SERVER_ERROR` | Unexpected error. |

The frontend may show the `error.message` text to the user; messages never contain keys, request content or technical details.

## Version notes
- **v1 (S1-02):** First version.
- **v2 (MIG-A):** English names, same behaviour. `GET /saglik` → `GET /health`, `POST /api/soru` → `POST /api/ask`; every field, value and error code renamed to English.
- **Planned (Stage 2):** the `user` field is removed; login and session are added. `status: "no_access"` comes into effect for per-user authorization.
