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
