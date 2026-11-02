"""Session rows (S2-03): the token itself is in no column, only its SHA-256 hash (API contract 2).

find_login_account is the only function that returns a password hash; only the login flow calls it.
"""
import logging
import sqlite3
from datetime import datetime, timedelta

from .rules import SignedInPerson, hash_session_token, session_expires_at

log = logging.getLogger("agentstack")

# last_seen_at is not written on every request, so that a read does not take the write lock each time.
LAST_SEEN_INTERVAL = timedelta(minutes=1)


def find_login_account(connection: sqlite3.Connection, username: str) -> dict | None:
    """The id, active status and password hash of the (normalized) user name, or None. Only for checking a login."""
    row = connection.execute(
        "SELECT id, is_active, password_hash FROM people WHERE username = ?", (username,)
    ).fetchone()
    if row is None:
        return None
    return dict(zip(("id", "is_active", "password_hash"), row))


def create_session(connection: sqlite3.Connection, person_id: int, token: str, now: datetime) -> None:
    """Writes a new session and deletes the expired sessions of this person in one transaction."""
    created_at = now.isoformat()
    expired = [
        (session_id,)
        for session_id, expires_at in connection.execute(
            "SELECT id, expires_at FROM sessions WHERE person_id = ?", (person_id,)
        ).fetchall()
        if datetime.fromisoformat(expires_at) <= now
    ]
    with connection:
        connection.executemany("DELETE FROM sessions WHERE id = ?", expired)
        connection.execute(
            "INSERT INTO sessions (person_id, token_hash, created_at, expires_at, last_seen_at) "
            "VALUES (?, ?, ?, ?, ?)",
            (person_id, hash_session_token(token), created_at, session_expires_at(now).isoformat(), created_at),
        )


def resolve_session(connection: sqlite3.Connection, token: str, now: datetime) -> SignedInPerson | None:
    """The person of a valid session, or None. The active status is read on every request.

    The row of an expired session or an inactive account is deleted, so activating the account later
    does not bring an old session back.
    """
    token_hash = hash_session_token(token)
    row = connection.execute(
        "SELECT s.expires_at, s.last_seen_at, p.id, p.username, p.display_name, p.role, p.is_active, "
        "a.source_account_id "
        "FROM sessions s JOIN people p ON p.id = s.person_id "
        "LEFT JOIN linked_accounts a ON a.person_id = p.id AND a.source = 'slack' "
        "WHERE s.token_hash = ?",
        (token_hash,),
    ).fetchone()
    if row is None:
        return None
    expires_at, last_seen_at, person_id, username, display_name, role, is_active, slack_user_id = row
    if datetime.fromisoformat(expires_at) <= now or not is_active:
        with connection:
            connection.execute("DELETE FROM sessions WHERE token_hash = ?", (token_hash,))
        return None
    if now - datetime.fromisoformat(last_seen_at) > LAST_SEEN_INTERVAL:
        _write_last_seen(connection, token_hash, now)
    return SignedInPerson(
        id=person_id, username=username, display_name=display_name, role=role, slack_user_id=slack_user_id,
    )


def _write_last_seen(connection: sqlite3.Connection, token_hash: str, now: datetime) -> None:
    """A failed write does not change who the person is; only the error type is logged."""
    try:
        with connection:
            connection.execute(
                "UPDATE sessions SET last_seen_at = ? WHERE token_hash = ?", (now.isoformat(), token_hash)
            )
    except sqlite3.Error as error:
        log.error("Failed to write session last seen time: %s", type(error).__name__)


def delete_session(connection: sqlite3.Connection, token: str) -> int | None:
    """Deletes the session of this token and returns its person id; None if there is no such session."""
    with connection:
        row = connection.execute(
            "DELETE FROM sessions WHERE token_hash = ? RETURNING person_id", (hash_session_token(token),)
        ).fetchone()
    return None if row is None else row[0]
