# API contract — v5

What the frontend (web) sends to the server and what it gets back. v1: Sprint 1 · S1-02; v3: Sprint 2 · S2-01; v4: Sprint 3 · S3-02; v5: Sprint 4 · S4-01.
If a change is needed, first a PR that updates this document is opened; the frontend and the server follow it.

Server address (development): `http://localhost:8000`. The frontend reads this address from a setting (`VITE_API_URL`).

## 0. What is in effect when

v3 described Sprint 2 as a whole; v4 adds the Sprint 3 fields; v5 adds the Sprint 4 rows. The rows up to S3-12 are unchanged. Each section starts with an **In effect from** line; this table is the summary.

| Behaviour | In effect from |
|---|---|
| `user` field of `POST /api/ask` optional and ignored; an unknown field → 422; CORS with credentials; `Retry-After` readable by the browser; an inexact `FRONTEND_ORIGINS` value stops the server | **S2-01** |
| `POST /api/auth/login`, `POST /api/auth/logout`, `GET /api/auth/me`; session cookie; `POST /api/ask` without a session → 401; `user` field removed (sending it → 422); login limit → 429 + `Retry-After` | **S2-03** |
| `GET /api/admin/events`; an audit row for every gateway step | **S2-04** |
| `status: "no_access"` per person (Slack account, allowed channel, membership); `sources` filled, with `id` | **S2-05** |
| `answer`: external links and images removed by the response check, each replaced by the text `link removed`; their count in `security.blocked` and in `blocked_count` of the `response_check` event; second secret scan of the answer (only in `masked_count` / `masked_kinds` of the `response_check` event, never in `security.masked`) | **S3-03** |
| `security.alarm`; `security.masked` counts the secrets masked in the question and the selected messages; event fields `masked_kinds` and `alarm` | **S3-08** |
| Personal data and Slack people names masked before the AI (`EMAIL_1`, `PHONE_1`, `TCKN_1`, `IBAN_1`, `CARD_1`, `PERSON_1`) and restored in `answer` and `sources[].text`; `[REDACTED]` is never restored. `security.masked` also counts personal data from here on, but never names; names are counted in the event rows (kind `person`) | **S3-12** |
| `no_access` answer: "There is no channel you can ask about with this name." for every refused channel (a channel that does not exist, is not allowed, or the person is not a member of get the same body) | **S4-01** |
| `security.suspicious`: messages with hidden instructions removed before the AI; not in `sources`; if every selected message is suspicious the AI is not called; `503 SECURITY_CHECK_UNAVAILABLE` when the detector does not work; table `suspicious_messages` (schema 8) | **S4-02** |
| `GET /api/channels` | **S4-03** |
| `GET /api/admin/masked-texts` | **S4-10** |

Until a task is merged, the server behaves as in the rows above it. Example: before S2-03, `POST /api/ask` works without a session. Before S3-08, `security` has no `alarm` field and the events have no `masked_kinds` and `alarm` fields: the frontend treats a missing `alarm` as `false` and a missing `masked_kinds` as `{}`.

## 1. Health check

**In effect from:** v1 (unchanged).

`GET /health` → `200`
```json
{ "status": "up" }
```

## 2. Session and cookie

**In effect from:** S2-03.

- Cookie name `agentstack_session`, attributes `HttpOnly; Secure; SameSite=Lax; Path=/; Max-Age=28800`.
- A session lasts at most 8 hours, counted from login (absolute). There is no idle timeout. After 8 hours every request gets `401 UNAUTHENTICATED`.
- The cookie value is a random token (at least 32 random bytes). The database keeps only the SHA-256 hash of the token, never the token itself.
- `Secure` is on by default. The setting `SESSION_COOKIE_SECURE=false` turns it off **only on a single computer over `http://localhost`** (local development, or a demo on that computer); never in a shared or networked deployment.
- Every successful login creates a **new** session (an old cookie is never reused). Logout deletes the session on the server.
- The frontend cannot read the cookie (`HttpOnly`). It learns who is signed in only from `GET /api/auth/me`.

## 3. CORS and how the frontend calls the server

**In effect from:** S2-01.

- The server allows credentials (`allow_credentials`) only for the exact origins listed in `FRONTEND_ORIGINS` (default `http://localhost:5173`).
- Every value must be an exact origin: `http://` or `https://`, a lower-case host name and an optional port; no path, no trailing `/`. `*` and `null` are never allowed. Any other value stops the server at start with:
  `FRONTEND_ORIGINS must list exact origins like http://localhost:5173 (no path, no trailing slash); '*' and 'null' are not allowed.`
  An empty list is valid: no browser page can call the server.
- Methods `GET`, `POST`; request header `Content-Type`. The response header `Retry-After` is readable by the browser (`expose_headers`).
- The frontend sends every request with `fetch(url, { credentials: 'include', ... })`; POST bodies with `Content-Type: application/json`.
- `http://localhost:5173` and `http://localhost:8000` are different origins (so CORS is needed) but the same *site* (the port does not count), so the `SameSite=Lax` cookie is sent. Use the same host name for both: `localhost` and `127.0.0.1` are different sites.
- Decided (frontend owner, 29 Oct 2026): CORS with the exact list above; no Vite proxy.

## 4. CSRF note

**In effect from:** S2-01 (JSON only), S2-03 (cookie).

POST endpoints accept only `application/json` bodies; any other `Content-Type` → `422 INVALID_REQUEST`. A page on another site can send JSON only after a CORS preflight, which the server refuses for origins not on the list; together with `SameSite=Lax` (the browser sends no cookie on a cross-site POST) this is enough for the POC.

## 5. Login — `POST /api/auth/login`

**In effect from:** S2-03.

### Request
```json
{ "username": "ali", "password": "TEST-password-2026" }
```

| Field | Type | Description |
|---|---|---|
| `username` | text, 1–64 characters | The account's user name. |
| `password` | text, 1–128 characters | The password. The "at least 12 characters" rule is checked only when a password is set (account commands), never at login: checking it at login would tell an attacker the rule. |

An unknown field → `422 INVALID_REQUEST`.

### Successful response — `200`
`Set-Cookie: agentstack_session=…; HttpOnly; Secure; SameSite=Lax; Path=/; Max-Age=28800`
```json
{ "username": "ali", "name": "Ali Kaya", "role": "user", "slack_linked": true }
```

| Field | Description |
|---|---|
| `username` | The user name (the panel shows the same value in `person`). |
| `name` | Name shown on the screen. |
| `role` | `user` or `admin`. |
| `slack_linked` | `true` if the person has a linked Slack account. Without one, channel questions get `no_access`. |

### Failed login — `401`
The user does not exist, the account is inactive, the password is wrong, or the account has no password yet: **all four** get the same status, the same body and a similar response time, so nobody can find out which user names exist.
```json
{ "error": { "code": "INVALID_CREDENTIALS", "message": "Username or password is incorrect." } }
```

### Too many attempts — `429`
`Retry-After: 840` (whole seconds until the next attempt is accepted)
```json
{ "error": { "code": "TOO_MANY_ATTEMPTS", "message": "Too many login attempts. Try again later." } }
```
- At most 5 failed attempts per user name in 15 minutes. When the limit is reached, even the correct password gets 429 until the 15 minutes pass.
- At most 30 failed attempts per IP address in 15 minutes (higher, because in the demo everyone uses the same IP address).
- An attempt over a limit gets 429, never 401. The 429 body is the same whether or not the user name exists.

## 6. Logout — `POST /api/auth/logout`

**In effect from:** S2-03.

No body. → `204`. The server deletes the session and the response clears the cookie (`Max-Age=0`).
Without a session (or with an expired one) the answer is also `204`: logout can be repeated safely and tells nothing.

## 7. Who am I — `GET /api/auth/me`

**In effect from:** S2-03.

`200` → the same body as login:
```json
{ "username": "ali", "name": "Ali Kaya", "role": "user", "slack_linked": true }
```
No session, an expired session or an inactive account → `401`:
```json
{ "error": { "code": "UNAUTHENTICATED", "message": "Please sign in." } }
```

## 8. Ask a question — `POST /api/ask`

**In effect from:** body rules S2-01; session S2-03; per-person access and `sources` S2-05; `security` fields and filtered text S3-03 / S3-08 / S3-12; `no_access` text S4-01; suspicious messages and the security check S4-02 (section 0).

### Request
```json
{ "question": "#dev'i özetle" }
```

| Field | Type | Description |
|---|---|---|
| `question` | text, 1–2000 characters | The user's question. |
| `user` | text | **Deprecated.** S2-01: optional, no decision uses it. **S2-03: removed; sending it → 422.** Identity comes only from the session. |

Any other field → `422 INVALID_REQUEST` (from S2-01), so an old client never works silently.

From S2-03: without a valid session → `401 UNAUTHENTICATED`, checked **before** the body. No gateway step runs and the AI is never called.
From S2-04: such a request also writes one `identity` / `stopped` / `UNAUTHENTICATED` audit row, at most 30 rows per IP address in 15 minutes; the answer is the same `401` over this limit too.

### Successful response — `200`
```json
{
  "request_id": "3f9c2a1b7d4e",
  "status": "ok",
  "answer": "This week in #dev the login page and ...",
  "sources": [
    {
      "id": "C0C83M051QD:1792665328.994119",
      "channel": "dev",
      "author": "Deniz Aydın",
      "time": "2026-10-22T11:05:00+00:00",
      "text": "@Ali you take the login page"
    }
  ],
  "security": { "blocked": 0, "masked": 0, "suspicious": 0, "alarm": false }
}
```

A question that itself contained secrets (from S3-08; names and personal data from S3-12). The question was **not** stopped: the secrets were replaced by `[REDACTED]` before the AI. In this example two secrets were masked and three people names were replaced by `PERSON_n`; `security.masked` is `2` because names are never counted here (the `sanitization` event of the same request in section 9 shows `masked_count` `5`):
```json
{
  "request_id": "7c2e9a0b1d3f",
  "status": "ok",
  "answer": "The deploy in #dev failed because the token was refused. Deniz Aydın asked Ali Kaya and Ayşe Yılmaz to check it.",
  "sources": [
    {
      "id": "C0C83M051QD:1792665328.994119",
      "channel": "dev",
      "author": "Deniz Aydın",
      "time": "2026-10-22T11:05:00+00:00",
      "text": "deploy failed again, the token is [REDACTED]"
    }
  ],
  "security": { "blocked": 0, "masked": 2, "suspicious": 0, "alarm": true }
}
```

| Field | Description |
|---|---|
| `request_id` | The request id. To match it with the audit log in the panel. |
| `status` | `"ok"` or `"no_access"`. |
| `answer` | Plain text. **The frontend shows it as plain text**; links and images inside are not made active (against EchoLeak-type leaks). From S3-03 every external link or image is removed by the response check and replaced by the text `link removed`. From S3-12 the placeholders (`PERSON_1`, `EMAIL_1` …) are restored to the real names and personal data for the asking person, in the presentation step (after the response check); only placeholders created for this request are restored, so text that already looked like a placeholder stays as it was; `[REDACTED]` is never restored. |
| `sources` | The messages really sent to the AI, in the same order (oldest to newest), at most 50. Empty in a `no_access` answer and in the "No messages were found for this question." answer. Error answers have no `sources` field. From S4-02 messages removed as suspicious are not sent to the AI, so they are not in `sources`. |
| `sources[].id` | `"<channel_id>:<ts>"` (Slack channel id and message `ts`). Stable (does not change when the database is loaded again), unique, contains no message text. The frontend uses it as the list key, never the array index. |
| `sources[].time` | ISO 8601 in **UTC** (`+00:00`). The frontend converts it to local time. |
| `sources[].text` | The message text as stored: secrets are already `[REDACTED]`. From S3-12 names and personal data are shown with their real values to the asking person (the AI saw placeholders); `[REDACTED]` is never restored. |
| `security` | What the filters did in this request. Every count is at least 0. Error answers have no `security` field (so no `alarm` either). |
| `security.masked` | How many secrets (S3-08) and personal data (`email`, `phone`, `tckn`, `iban`, `card`; S3-12) were masked in the text sent to the AI: the question and the selected messages. Secrets that were already replaced by `[REDACTED]` when the message was synced from Slack count too: the number is how many secrets and personal data are hidden in what the AI saw, whether they were masked at sync or at question time. One value is counted once, under its most specific kind. **Names are counted in the event rows (kind `person`) but not in `security.masked`.** Not counted here either: the second scan of the answer (only in the `response_check` event). So `masked_count` of the `sanitization` event can be larger than `security.masked` of the same request. |
| `security.blocked` | How many external links and images were removed from the answer (S3-03). Not the channel status `blocked`. |
| `security.suspicious` | How many of the selected messages were removed before the AI because they looked like hidden instructions (S4-02). Until then 0. The removed messages are not in `sources`. There is no new field: when `suspicious > 0` the screen shows its own warning, `N message(s) were removed for security reasons.` (N = this value); the server sends no such text. |
| `security.alarm` | `true` if the question itself contained a certain secret (S3-08). The question is not stopped: the secret is replaced by `[REDACTED]` before the AI and never stored. It can be `true` only when the `sanitization` step ran; it is always `false` in a `no_access` answer and in the "No messages were found for this question." answer. The frontend shows its own warning text; the contract has no text. |

Sources come only from channels the person may read and only from messages that were really sent to the AI.

A person with a linked Slack account who may read no channel and asks without naming a channel gets `200` with `status: "ok"`, `answer: "No messages were found for this question."` and empty `sources`; the AI is not called.

### Suspicious messages (S4-02)
Messages that look like hidden instructions are removed before the AI and are not in `sources`; `security.suspicious` is how many were removed. Example: 2 of the selected messages were removed:
```json
{
  "request_id": "5d6e7f8a9b0c",
  "status": "ok",
  "answer": "This week in #dev the login page and ...",
  "sources": [
    {
      "id": "C0C83M051QD:1792665328.994119",
      "channel": "dev",
      "author": "Deniz Aydın",
      "time": "2026-10-22T11:05:00+00:00",
      "text": "@Ali you take the login page"
    }
  ],
  "security": { "blocked": 0, "masked": 0, "suspicious": 2, "alarm": false }
}
```
The frontend shows its own warning when `suspicious > 0`: `N message(s) were removed for security reasons.` (for the example: `2 message(s) were removed for security reasons.`).

If **every** selected message is suspicious, the AI is not called. The answer is `200` with `status: "ok"`, `answer: "No messages were found for this question."`, empty `sources` and `suspicious` equal to the number of removed messages (here 3):
```json
{
  "request_id": "1a2b3c4d5e6f",
  "status": "ok",
  "answer": "No messages were found for this question.",
  "sources": [],
  "security": { "blocked": 0, "masked": 0, "suspicious": 3, "alarm": false }
}
```

### Security check not available — `503` (S4-02)
If the hidden instruction detector does not work, no message can be checked, so none is sent. The AI is not called:
```json
{ "error": { "code": "SECURITY_CHECK_UNAVAILABLE", "message": "The security check is not available right now. Please tell the administrator." } }
```
This happens only when at least one message was selected. A question that is not authorized is still `no_access` (below), and a question with no matching message still gets the "No messages were found for this question." answer. The `sanitization` step writes an event with decision `stopped` and the same reason code (sections 9 and 11). Error answers have no `sources` and no `security` field.

### No access — still `200`
Signed in, but the person has no linked Slack account, the channel does not exist, the channel is not allowed, or the person's Slack account is not a member of the channel. From S4-01 the body is the same for every reason: a channel that does not exist, a channel that is not allowed and a channel the person is not a member of get the same answer, so it never tells whether a channel exists or is private. Only `request_id` differs; the reason is only in the audit log (`NO_SLACK_ACCOUNT`, `NOT_CHANNEL_MEMBER`, `CHANNEL_NOT_ALLOWED`; the codes in the panel do not change):
```json
{
  "request_id": "9a1b2c3d4e5f",
  "status": "no_access",
  "answer": "There is no channel you can ask about with this name.",
  "sources": [],
  "security": { "blocked": 0, "masked": 0, "suspicious": 0, "alarm": false }
}
```
The AI is never called. The role does not give channel access: an `admin` without a Slack account gets `no_access` too. `/api/ask` never answers `403`.

The answer is not streamed word by word (no streaming): the output check must see the whole answer. The frontend shows "Typing…" while waiting.

## 9. Admin event list — `GET /api/admin/events?limit=50`

**In effect from:** S2-04; `masked_kinds` and `alarm` S3-08; the `sanitization` / `stopped` / `SECURITY_CHECK_UNAVAILABLE` event and `suspicious_count` S4-02 (section 0).

`limit`: whole number written with digits only (no sign, spaces or decimal point), at least 1, at most 100, default 50. Any other value (0, 101, not a number, empty) or `limit` given more than once → `422 INVALID_REQUEST`. Newest event first.

### Successful response — `200`
```json
{
  "events": [
    {
      "created_at": "2026-10-30T09:12:03+00:00",
      "request_id": "3f9c2a1b7d4e",
      "person": "ali",
      "channel": "yonetim",
      "step": "authorization",
      "decision": "stopped",
      "reason_code": "NOT_CHANNEL_MEMBER",
      "message_count": 0,
      "blocked_count": 0,
      "masked_count": 0,
      "suspicious_count": 0,
      "masked_kinds": {},
      "alarm": false,
      "duration_ms": 0.42
    }
  ]
}
```

The `sanitization` event of the question in section 8 (secrets from S3-08, the kind `person` from S3-12). It counts the two secrets **and** the three names, so `masked_count` is `5`, while `security.masked` of the same request is `2` (names are not counted there):
```json
{
  "created_at": "2026-11-12T09:12:03+00:00",
  "request_id": "7c2e9a0b1d3f",
  "person": "ali",
  "channel": "dev",
  "step": "sanitization",
  "decision": "passed",
  "reason_code": null,
  "message_count": 0,
  "blocked_count": 0,
  "masked_count": 5,
  "suspicious_count": 0,
  "masked_kinds": { "slack_token": 2, "person": 3 },
  "alarm": true,
  "duration_ms": 0.81
}
```

| Field | Description |
|---|---|
| `created_at` | ISO 8601 in **UTC** (`+00:00`); may have fractional seconds (at most 6 digits). The frontend converts it to local time. |
| `request_id` | Same value as `request_id` of `/api/ask`. |
| `person` | The user name, or `null` (identity unknown, login with an unknown user name, Slack sync). |
| `channel` | The channel **name** the event is about, or `null`. Only the name, never message text. For a question: from `authorization` on, the channel if the question names exactly one channel and that name is exactly one known channel; otherwise `null`. |
| `step` | A gateway step (`identity` … `presentation`), `login`, `logout` or `slack_sync`. |
| `decision` | `passed` / `stopped` for a gateway step, `login` and `logout`; `ok` / `error` for Slack sync. |
| `reason_code` | A code from section 11, or `null`. |
| `message_count`, `blocked_count`, `masked_count`, `suspicious_count` | Counts in this step, at least 0. `masked_count` is filled on `sanitization` (the question and the selected messages, S3-08) and on `response_check` (the second scan of the answer, S3-03); `blocked_count` on `response_check` (removed links and images, S3-03); `suspicious_count` on `sanitization` (S4-02). 0 on every other row. `masked_count` counts every kind, `person` included, so on the `sanitization` row it can be larger than `security.masked` of the same request (section 8). |
| `masked_kinds` | Object: kind → count. Only kinds with a count of at least 1; `{}` if nothing was masked. On the `sanitization` row it includes the secrets already masked at sync in the selected messages (same rule as `security.masked`). The sum of the values equals `masked_count` of the same row. Kinds: `slack_token`, `github_token`, `aws_key`, `google_key`, `openai_key`, `anthropic_key`, `private_key`, `env_secret`, `db_password`, `bearer_token` (secrets), `email`, `phone`, `tckn`, `iban`, `card` (personal data), `person` (people names). Never a value. `{}` on the `login`, `logout` and `slack_sync` rows. |
| `alarm` | `true` only on the `sanitization` row of a request whose question itself contained a certain secret; `false` on every other row. |
| `duration_ms` | Duration of the step, milliseconds. |

The list never contains message text, the question, the answer, passwords, session tokens or any masked value: only the kind and the count. The rows of one request count different texts (the `sanitization` row the question and the messages, the `response_check` row the answer), so their counts can be added up.

### Errors
- No session, an expired session or an **inactive account** → `401 UNAUTHENTICATED`.
- `403` only when the session is valid, the account is active and the role is not `admin`:
```json
{ "error": { "code": "FORBIDDEN", "message": "You don't have permission for this page." } }
```
The endpoint itself checks the session, the active status and the role on every request (not only the frontend).

When the hidden instruction detector does not work (S4-02), the `sanitization` row of that request is `decision` `stopped` with `reason_code` `SECURITY_CHECK_UNAVAILABLE` (the same code as the `503` in section 8). No text is written to the event row.

## 9a. List channels — `GET /api/channels`

**In effect from:** S4-03.

The channels the signed-in person can ask about, for the screen's channel choice. There is no request body and no query parameter.

### Successful response — `200`
```json
{ "channels": [ { "name": "dev" }, { "name": "genel" } ] }
```

| Field | Description |
|---|---|
| `channels` | Sorted by `name`. Only channels that are `allowed` **and** that the person's Slack account is a member of. |
| `channels[].name` | The channel name without `#`. No channel id and no other field. |

- The list is empty (`{ "channels": [] }`) if the person has no linked Slack account.
- The `admin` role gives no channel: an `admin` gets the same list as any other person with the same Slack account (nothing without one).
- Read from the database on every request, so a change in membership or in the allowed channels counts from the next request.

### Errors
- No session, an expired session or an inactive account → `401 UNAUTHENTICATED` (section 10).

## 9b. Masked texts — `GET /api/admin/masked-texts?limit=50`

**In effect from:** S4-10 (the `removed_suspicious` items come with S4-02).

The texts the panel may show for control, newest first: what was sent to the AI and the messages removed as suspicious. Admin only.

`limit`: a whole number from 1 to 100, default 50. Any other value (0, 101, not a number, empty) → `422 INVALID_REQUEST`.

### Successful response — `200`
```json
{
  "items": [
    {
      "request_id": "5d6e7f8a9b0c",
      "created_at": "2026-11-24T09:12:03+00:00",
      "kind": "removed_suspicious",
      "channel": "dev",
      "text": "…the message text after secrets and personal data were masked…"
    },
    {
      "request_id": "5d6e7f8a9b0c",
      "created_at": "2026-11-24T09:12:03+00:00",
      "kind": "sent",
      "channel": null,
      "text": "…the text sent to the AI, masked…"
    }
  ]
}
```

| Field | Description |
|---|---|
| `items` | Newest first. |
| `items[].request_id` | Same value as `request_id` of `/api/ask`. |
| `items[].created_at` | ISO 8601 in **UTC** (`+00:00`). |
| `items[].kind` | `sent`: the text sent to the AI (`channel` is `null`). `removed_suspicious`: a message removed as suspicious (S4-02), with its channel name in `channel`. |
| `items[].channel` | The channel **name**, or `null` for `sent`. |
| `items[].text` | The masked text, as stored. Secrets and personal data are already masked; the stored text never holds a real secret value. |

Stored data (schema 8, S4-02): the table `suspicious_messages(id, request_id, created_at, channel_name, masked_text)` holds the removed messages. Like `masked_texts`, its rows are deleted after 7 days. No text is ever written to the event list (section 9).

### Errors
- No session, an expired session or an inactive account → `401 UNAUTHENTICATED`.
- A valid session whose role is not `admin` → `403 FORBIDDEN` (same body as section 9).
- An invalid `limit` → `422 INVALID_REQUEST`.

## 9c. Detector and test helpers (S4-01)

**In effect from:** S4-01 (the helpers); the detector is the existing S3-10 module.

- Detector (existing, `app/filters/injection.py`): `injection.warm_up() -> bool` (is the model ready) and `injection.detect(text) -> InjectionResult(suspicious, score)`. The detector sees the message as stored in the database (secrets are already masked).
- Test helpers (`server/tests/conftest.py`):
  - `fake_detector`: runs by itself in every test (autouse). `injection.warm_up()` returns `True`; `injection.detect(text)` decides only with the rule layer (`injection.matches_rules`); no model is loaded, and it works without `torch` and `transformers`. The two seed messages with hidden instructions (D23, D24) are suspicious; ordinary messages are not. `detect` still returns `InjectionResult(suspicious: bool, score: float)`; the score is `0.0` (a rule hit never changes the score).
  - `detector_unavailable`: in a test that uses it `injection.warm_up()` returns `False` and `injection.detect(...)` returns `suspicious=True` for every text. It never leaks into the next test (every test starts clean).
  - Existing: `client_as("ali")`, `anonymous_client`, `sent_to_ai`.

## 10. Errors — every error has the same format

```json
{
  "error": { "code": "INVALID_REQUEST", "message": "Invalid request format. See the API contract." }
}
```

| HTTP | `code` | When | What the frontend does |
|---|---|---|---|
| 401 | `UNAUTHENTICATED` | No session, expired session, inactive account (S2-03). | Go to the login screen. |
| 401 | `INVALID_CREDENTIALS` | Login failed, for any reason (S2-03). | "Username or password is incorrect." |
| 403 | `FORBIDDEN` | Signed in and active, but not allowed; admin endpoints only (S2-04). | "You don't have permission." |
| 422 | `INVALID_REQUEST` | A field is missing, empty, too long or unknown; the body is not JSON; `limit` is invalid. | |
| 429 | `TOO_MANY_ATTEMPTS` | Login limit reached; `Retry-After` gives the seconds (S2-03). | Show the waiting time. |
| 503 | `SECURITY_CHECK_UNAVAILABLE` | The hidden instruction detector does not work and at least one message was selected (S4-02). The AI is not called. | Show the message; "The security check is not available right now. Please tell the administrator." |
| 502 | `PROVIDER_ERROR` | The AI provider returned an error or the request limit was reached (S1-08). | |
| 504 | `TIMEOUT` | The AI did not answer in time (S1-08). | |
| 500 | `SERVER_ERROR` | Unexpected error. | |

401 means "sign in"; 403 means "you are signed in, but you may not do this". "No access to a channel" is not an error: it is `200` with `status: "no_access"`.

The frontend may show the `error.message` text to the user; messages never contain keys, passwords, request content, technical details or whether a user name exists.

## 11. Reason codes (audit log and panel)

**In effect from:** S2-03 (the `login` codes), S2-04 (the gateway codes), S2-05 (`NO_SLACK_ACCOUNT`, `NOT_CHANNEL_MEMBER`), S4-02 (`SECURITY_CHECK_UNAVAILABLE`).

| Code | Step | Meaning |
|---|---|---|
| `UNAUTHENTICATED` | identity | No valid session. |
| `INVALID_CREDENTIALS` | login | Login failed. |
| `TOO_MANY_ATTEMPTS` | login | Login limit reached. |
| `NO_SLACK_ACCOUNT` | authorization | The person has no linked Slack account. |
| `NOT_CHANNEL_MEMBER` | authorization | The person's Slack account is not a member of the channel. |
| `CHANNEL_NOT_ALLOWED` | authorization / data_selection | The channel is not `allowed`. |
| `NO_SLACK_DATA` | data_selection | The database has no Slack data. |
| `NO_MESSAGES` | data_selection | No message matched the question. |
| `SECURITY_CHECK_UNAVAILABLE` | sanitization | The hidden instruction detector does not work (S4-02). |
| `PROVIDER_ERROR`, `TIMEOUT` | ask_ai | The AI call failed. |

The reason codes of Slack sync are in `docs/data-model.md`. From schema version 4 (S2-02) the step column also accepts login and logout; the login endpoint writes these events from S2-03, the gateway writes its step events from S2-04. `CHANNEL_NOT_ALLOWED` normally comes from `authorization`; `data_selection` checks the channel again as a second layer (e.g. a setting changed between the two steps). If a question names several channels, the first refused name gives the code; for each name the channel rule comes before membership, and `NO_SLACK_ACCOUNT` comes before both. An unexpected error has no code: the step is `stopped` with `reason_code` `null`. A secret in the question does not stop the request, so it has no reason code: it is shown by `alarm` (section 9, from S3-08).

## Version notes
- **v1 (S1-02):** First version.
- **v2 (MIG-A):** English names, same behaviour. `GET /saglik` → `GET /health`, `POST /api/soru` → `POST /api/ask`; every field, value and error code renamed to English.
- **v3 (S2-01):** Identity and authorization for Sprint 2. Added: session cookie (S2-03), `POST /api/auth/login`, `POST /api/auth/logout`, `GET /api/auth/me` (S2-03), `GET /api/admin/events` (S2-04), errors 401 `UNAUTHENTICATED`, 401 `INVALID_CREDENTIALS`, 403 `FORBIDDEN`, 429 `TOO_MANY_ATTEMPTS`, reason codes, `sources[].id` and per-person `no_access` (S2-05). Changed now (S2-01): `user` optional and ignored, an unknown field → 422, a non-JSON body → 422, CORS with credentials and readable `Retry-After`. The `user` field, which let anyone claim to be another user, is removed in S2-03. Times are UTC.
- **v4 (S3-02):** Input filter for Sprint 3. Added: `security.alarm` (S3-08); the exact meaning of `security.masked` (secrets from S3-08, personal data from S3-12; never names and never the second scan of the answer), `security.blocked` (removed links and images, S3-03) and `security.suspicious` (Stage 4); `link removed` in `answer` (S3-03); restored names and personal data in `answer` and `sources[].text`, `[REDACTED]` never restored (S3-12); event fields `masked_kinds` and `alarm` (S3-08). Names are counted in the event rows (kind `person`) but not in `security.masked`. No change to requests, errors or reason codes. Masked values never appear in any response or event.
- **v5 (S4-01):** Sprint 4 contract and test helpers. Added: the new `no_access` answer text, "There is no channel you can ask about with this name." (it was "You don't have access to this information."), the same for a channel that does not exist, is not allowed, or the person is not a member of; panel reason codes unchanged (S4-01). `security.suspicious` is filled and the removed messages are not in `sources`; if all selected messages are suspicious the AI is not called (200, "No messages were found for this question."); `503 SECURITY_CHECK_UNAVAILABLE` with the `sanitization` / `stopped` event and the reason code `SECURITY_CHECK_UNAVAILABLE`; the table `suspicious_messages` (schema 8) (S4-02). `GET /api/channels` (S4-03). `GET /api/admin/masked-texts` (S4-10). Test helpers `fake_detector` and `detector_unavailable` (S4-01). This version only writes the table into the contract; the behaviour of S4-02, S4-03 and S4-10 comes with their own tasks.
