"""Audit log writing (S1-04): one row in the audit_events table. Takes only codes, counts and durations."""
import sqlite3

# Count columns in the audit_events table.
COUNT_COLUMNS = frozenset({
    "message_count", "channel_count", "user_count", "membership_count",
    "blocked_count", "masked_count", "suspicious_count",
})

# The fields of the admin event list (API contract 9), in the order of the query in list_events.
EVENT_LIST_FIELDS = (
    "created_at", "request_id", "person", "channel", "step", "decision", "reason_code",
    "message_count", "blocked_count", "masked_count", "suspicious_count", "duration_ms",
)


class AuditWriteError(Exception):
    """An event of a gateway step could not be written: the request stops (500), the error is never hidden."""


def write_event(
    connection: sqlite3.Connection,
    *,
    created_at: str,
    request_id: str,
    step: str,
    decision: str,
    duration_ms: float,
    reason_code: str | None = None,
    channel_id: str | None = None,
    person_id: int | None = None,
    **counts: int,
) -> None:
    """Adds one event row. Does not commit: used inside the caller's transaction."""
    unknown = set(counts) - COUNT_COLUMNS
    if unknown:
        raise ValueError(f"Unknown count field: {', '.join(sorted(unknown))}")
    row = {
        "created_at": created_at, "request_id": request_id, "person_id": person_id, "step": step,
        "decision": decision, "reason_code": reason_code, "channel_id": channel_id, "duration_ms": duration_ms,
    } | counts
    columns = ", ".join(row)
    placeholders = ", ".join("?" * len(row))
    connection.execute(f"INSERT INTO audit_events ({columns}) VALUES ({placeholders})", tuple(row.values()))


def list_events(connection: sqlite3.Connection, limit: int) -> list[dict[str, object]]:
    """The newest `limit` events (id order: the order of writing), with the user name and the channel name."""
    rows = connection.execute(
        "SELECT e.created_at, e.request_id, p.username, c.name, e.step, e.decision, e.reason_code, "
        "e.message_count, e.blocked_count, e.masked_count, e.suspicious_count, e.duration_ms "
        "FROM audit_events e "
        "LEFT JOIN people p ON p.id = e.person_id "
        "LEFT JOIN channels c ON c.slack_id = e.channel_id "
        "ORDER BY e.id DESC LIMIT ?",
        (limit,),
    ).fetchall()
    return [dict(zip(EVENT_LIST_FIELDS, row)) for row in rows]


def write_ai_call(
    connection: sqlite3.Connection,
    *,
    created_at: str,
    request_id: str,
    model: str,
    result: str,
    messages_sent: int,
    duration_ms: float,
    input_tokens: int | None = None,
    output_tokens: int | None = None,
) -> None:
    """One row in the ai_calls table (S1-05). Takes no text. Does not commit: used inside the caller's transaction."""
    connection.execute(
        "INSERT INTO ai_calls "
        "(created_at, request_id, model, result, messages_sent, duration_ms, input_tokens, output_tokens) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (created_at, request_id, model, result, messages_sent, duration_ms, input_tokens, output_tokens),
    )
