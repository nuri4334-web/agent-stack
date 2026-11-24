"""Masked text table (S3-14): the exact data text the gateway sends to the AI, after masking.

Secrets are already [REDACTED], personal data and names are placeholders (EMAIL_1, PERSON_1). The Vault mapping
(placeholder -> real value) is never written, so the table alone can never be restored. This table is not part of the
audit log. Details: docs/data-model.md ("masked_texts").
"""
import sqlite3


class MaskedTextWriteError(Exception):
    """The masked text could not be written: the request stops (500) before the AI, the error is never hidden.

    It carries no text: no question, message, value or the original error message.
    """


def write_masked_text(connection: sqlite3.Connection, *, created_at: str, request_id: str, masked_text: str) -> None:
    """One row in masked_texts: the exact masked data text sent to the AI. Does not commit (caller's transaction)."""
    connection.execute(
        "INSERT INTO masked_texts (created_at, request_id, masked_text) VALUES (?, ?, ?)",
        (created_at, request_id, masked_text),
    )


def read_masked_texts(connection: sqlite3.Connection, *, limit: int = 50) -> list[dict[str, str | None]]:
    """Reads masked texts and suspicious messages together, newest first.

    Returns dicts with keys: request_id, created_at, kind, channel, text.
    """
    cursor = connection.execute(
        """
        SELECT request_id, created_at, 'sent' AS kind, NULL AS channel, masked_text AS text, id
        FROM masked_texts
        UNION ALL
        SELECT request_id, created_at, 'removed_suspicious' AS kind, channel_name AS channel, masked_text AS text, id
        FROM suspicious_messages
        ORDER BY created_at DESC, id DESC
        LIMIT ?
        """,
        (limit,),
    )
    return [
        {
            "request_id": row[0],
            "created_at": row[1],
            "kind": row[2],
            "channel": row[3],
            "text": row[4],
        }
        for row in cursor.fetchall()
    ]
