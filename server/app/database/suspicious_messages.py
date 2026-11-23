"""Suspicious message table (S4-02): the messages removed before the AI because they look like hidden instructions.

The text is stored the way it would have gone to the AI: secrets are [REDACTED], personal data and names are
placeholders (EMAIL_1, PERSON_1). A raw value is never written. This table is not part of the audit log, and the audit
event of the request carries only the count. Details: docs/data-model.md ("suspicious_messages").
"""
import sqlite3
from collections.abc import Iterable


class SuspiciousMessageWriteError(Exception):
    """The removed messages could not be written: the request stops (500) before the AI, the error is never hidden.

    It carries no text: no question, message, value or the original error message.
    """


def write_suspicious_messages(
    connection: sqlite3.Connection, *, created_at: str, request_id: str, items: Iterable[tuple[str, str]],
) -> None:
    """One row per removed message; items are (channel name, masked text). Does not commit (caller's transaction)."""
    connection.executemany(
        "INSERT INTO suspicious_messages (request_id, created_at, channel_name, masked_text) VALUES (?, ?, ?, ?)",
        [(request_id, created_at, channel_name, masked_text) for channel_name, masked_text in items],
    )
