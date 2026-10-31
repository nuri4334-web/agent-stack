"""Account storage (S2-02): people, their Slack link and their sessions in the database.

Every write runs in one transaction. Nothing here reads, returns or prints a password hash or a session token.
"""
import sqlite3

from .rules import is_slack_user_id


class AccountError(ValueError):
    """An account change that the user can correct. Its message never contains a password, hash or token."""


def find_person(connection: sqlite3.Connection, username: str) -> dict | None:
    """The account with this (normalized) user name, or None. Without the password hash."""
    row = connection.execute(
        "SELECT id, username, display_name, role, is_active FROM people WHERE username = ?", (username,)
    ).fetchone()
    if row is None:
        return None
    return dict(zip(("id", "username", "display_name", "role", "is_active"), row))


def create_account(
    connection: sqlite3.Connection,
    *,
    username: str,
    name: str,
    role: str,
    password_hash: str | None,
    created_at: str,
) -> int:
    """Adds an active account and returns its id. AccountError if the user name is taken."""
    try:
        with connection:
            cursor = connection.execute(
                "INSERT INTO people (username, display_name, role, password_hash, created_at) "
                "VALUES (?, ?, ?, ?, ?)",
                (username, name, role, password_hash, created_at),
            )
    except sqlite3.IntegrityError:
        if find_person(connection, username):
            raise AccountError(f"An account with the user name '{username}' already exists.") from None
        raise AccountError("The account could not be written (invalid user name, name or role).") from None
    return cursor.lastrowid


def _delete_sessions(connection: sqlite3.Connection, person_id: int) -> int:
    return connection.execute("DELETE FROM sessions WHERE person_id = ?", (person_id,)).rowcount


def set_password_hash(connection: sqlite3.Connection, person_id: int, password_hash: str) -> int:
    """Replaces the password hash and ends all sessions of the person. Returns the number of sessions ended."""
    with connection:
        connection.execute("UPDATE people SET password_hash = ? WHERE id = ?", (password_hash, person_id))
        return _delete_sessions(connection, person_id)


def link_slack_account(connection: sqlite3.Connection, person_id: int, slack_id: str, *, linked_at: str) -> None:
    """Links a human Slack account to the person (link_method 'admin').

    AccountError if the id is not a Slack user id, is not in slack_users, is a bot, the person already has
    a Slack account, or the Slack account is linked to someone else.
    """
    if not is_slack_user_id(slack_id):
        raise AccountError("Slack user id must look like U0123ABCDEF (U or W, then upper case letters and digits).")
    user = connection.execute("SELECT is_bot FROM slack_users WHERE slack_id = ?", (slack_id,)).fetchone()
    if user is None:
        raise AccountError(f"Slack user {slack_id} is not in the database; run 'seed load' or 'sync' first.")
    if user[0]:
        raise AccountError(f"Slack user {slack_id} is a bot; a bot cannot be linked to a person.")
    if connection.execute(
        "SELECT 1 FROM linked_accounts WHERE person_id = ? AND source = 'slack'", (person_id,)
    ).fetchone():
        raise AccountError("This account already has a linked Slack account.")
    try:
        with connection:
            connection.execute(
                "INSERT INTO linked_accounts (person_id, source, source_account_id, link_method, linked_at) "
                "VALUES (?, 'slack', ?, 'admin', ?)",
                (person_id, slack_id, linked_at),
            )
    except sqlite3.IntegrityError:
        other = connection.execute(
            "SELECT p.username FROM linked_accounts a JOIN people p ON p.id = a.person_id "
            "WHERE a.source = 'slack' AND a.source_account_id = ?",
            (slack_id,),
        ).fetchone()
        if other:
            raise AccountError(
                f"This Slack account is already linked to another account ({other[0]})."
            ) from None
        raise AccountError("The Slack account could not be linked.") from None


def deactivate(connection: sqlite3.Connection, person_id: int) -> int:
    """Makes the account inactive and ends all its sessions. The person is never deleted."""
    with connection:
        connection.execute("UPDATE people SET is_active = 0 WHERE id = ?", (person_id,))
        return _delete_sessions(connection, person_id)


def activate(connection: sqlite3.Connection, person_id: int) -> None:
    """Makes the account active again. Opens no session."""
    with connection:
        connection.execute("UPDATE people SET is_active = 1 WHERE id = ?", (person_id,))


def list_accounts(connection: sqlite3.Connection) -> list[dict]:
    """All accounts by user name: whether a password is set (never the hash) and the linked Slack id."""
    cursor = connection.execute(
        "SELECT p.username, p.display_name, p.role, p.is_active, p.password_hash IS NOT NULL, a.source_account_id "
        "FROM people p LEFT JOIN linked_accounts a ON a.person_id = p.id AND a.source = 'slack' "
        "ORDER BY p.username"
    )
    names = ("username", "display_name", "role", "is_active", "has_password", "slack_id")
    return [dict(zip(names, row)) | {"has_password": bool(row[4])} for row in cursor.fetchall()]
