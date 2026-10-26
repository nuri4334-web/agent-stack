"""Tables (S1-03): schema, connection and table creation.

Messages have no raw text column; the audit log has no message text or free text.
Details: docs/data-model.md
"""
import sqlite3
from pathlib import Path

from .. import settings

# Schema version in the code (PRAGMA user_version).
SCHEMA_VERSION = 2

# Lowest SQLite version needed for STRICT tables.
MIN_SQLITE_VERSION = (3, 37, 0)

# Time columns have no default: the caller always gives the time (ISO 8601 text).
SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS people (
    id            INTEGER PRIMARY KEY,
    display_name  TEXT NOT NULL CHECK (length(trim(display_name)) > 0),
    role          TEXT NOT NULL DEFAULT 'user' CHECK (role IN ('user', 'admin'))
) STRICT;

CREATE TABLE IF NOT EXISTS linked_accounts (
    id                 INTEGER PRIMARY KEY,
    person_id          INTEGER NOT NULL REFERENCES people (id),
    source             TEXT NOT NULL CHECK (source IN ('slack', 'jira', 'github')),
    source_account_id  TEXT NOT NULL CHECK (length(source_account_id) > 0),
    link_method        TEXT NOT NULL CHECK (link_method IN ('admin', 'self')),
    linked_at          TEXT NOT NULL,
    UNIQUE (source, source_account_id),
    UNIQUE (person_id, source)
) STRICT;

CREATE TABLE IF NOT EXISTS slack_users (
    slack_id      TEXT PRIMARY KEY CHECK (length(slack_id) > 0),
    display_name  TEXT,
    real_name     TEXT,
    is_bot        INTEGER NOT NULL DEFAULT 0 CHECK (is_bot IN (0, 1))
) STRICT;

CREATE TABLE IF NOT EXISTS channels (
    slack_id    TEXT PRIMARY KEY CHECK (length(slack_id) > 0),
    name        TEXT NOT NULL CHECK (length(name) > 0),
    is_private  INTEGER NOT NULL CHECK (is_private IN (0, 1)),
    status      TEXT NOT NULL DEFAULT 'excluded' CHECK (status IN ('allowed', 'excluded')),
    CHECK (NOT (lower(name) = 'ik' AND status = 'allowed'))
) STRICT;

CREATE TABLE IF NOT EXISTS channel_memberships (
    channel_id     TEXT NOT NULL REFERENCES channels (slack_id),
    slack_user_id  TEXT NOT NULL REFERENCES slack_users (slack_id),
    updated_at     TEXT NOT NULL,
    PRIMARY KEY (channel_id, slack_user_id)
) STRICT;
CREATE INDEX IF NOT EXISTS channel_memberships_user
    ON channel_memberships (slack_user_id);

CREATE TABLE IF NOT EXISTS messages (
    id             INTEGER PRIMARY KEY,
    channel_id     TEXT NOT NULL REFERENCES channels (slack_id),
    ts             TEXT NOT NULL CHECK (
                       length(ts) = 17
                       AND ts GLOB '[0-9][0-9][0-9][0-9][0-9][0-9][0-9][0-9][0-9][0-9].[0-9][0-9][0-9][0-9][0-9][0-9]'
                   ),
    author_id      TEXT NOT NULL REFERENCES slack_users (slack_id),
    sent_at        TEXT NOT NULL,
    clean_text     TEXT NOT NULL,
    is_suspicious  INTEGER CHECK (is_suspicious IS NULL OR is_suspicious IN (0, 1)),
    UNIQUE (channel_id, ts)
) STRICT;
CREATE INDEX IF NOT EXISTS messages_channel_sent_at ON messages (channel_id, sent_at);

CREATE TABLE IF NOT EXISTS audit_events (
    id                INTEGER PRIMARY KEY,
    created_at        TEXT NOT NULL,
    request_id        TEXT NOT NULL CHECK (
                          length(request_id) BETWEEN 1 AND 64
                          AND request_id NOT GLOB '*[^0-9a-f]*'
                      ),
    person_id         INTEGER REFERENCES people (id),
    step              TEXT NOT NULL CHECK (step IN (
                          'identity', 'authorization', 'data_selection', 'sanitization',
                          'ask_ai', 'response_check', 'presentation',
                          'slack_sync')),
    decision          TEXT NOT NULL CHECK (decision IN ('passed', 'stopped', 'ok', 'error')),
    reason_code       TEXT CHECK (
                          reason_code IS NULL OR (
                              length(reason_code) BETWEEN 1 AND 40
                              AND reason_code NOT GLOB '*[^A-Z0-9_]*')
                      ),
    channel_id        TEXT REFERENCES channels (slack_id),
    message_count     INTEGER NOT NULL DEFAULT 0 CHECK (message_count >= 0),
    channel_count     INTEGER NOT NULL DEFAULT 0 CHECK (channel_count >= 0),
    user_count        INTEGER NOT NULL DEFAULT 0 CHECK (user_count >= 0),
    membership_count  INTEGER NOT NULL DEFAULT 0 CHECK (membership_count >= 0),
    blocked_count     INTEGER NOT NULL DEFAULT 0 CHECK (blocked_count >= 0),
    masked_count      INTEGER NOT NULL DEFAULT 0 CHECK (masked_count >= 0),
    suspicious_count  INTEGER NOT NULL DEFAULT 0 CHECK (suspicious_count >= 0),
    duration_ms       REAL NOT NULL CHECK (duration_ms >= 0)
) STRICT;
CREATE INDEX IF NOT EXISTS audit_events_request ON audit_events (request_id);

CREATE TABLE IF NOT EXISTS ai_calls (
    id             INTEGER PRIMARY KEY,
    created_at     TEXT NOT NULL,
    request_id     TEXT NOT NULL CHECK (
                       length(request_id) BETWEEN 1 AND 64
                       AND request_id NOT GLOB '*[^0-9a-f]*'
                   ),
    model          TEXT NOT NULL CHECK (
                       length(model) BETWEEN 1 AND 100
                       AND model NOT GLOB '*[^A-Za-z0-9._-]*'
                   ),
    result         TEXT NOT NULL CHECK (
                       result IN ('ok', 'provider_error', 'timeout')
                   ),
    messages_sent  INTEGER NOT NULL CHECK (messages_sent >= 0),
    duration_ms    REAL NOT NULL CHECK (duration_ms >= 0),
    input_tokens   INTEGER CHECK (input_tokens IS NULL OR input_tokens >= 0),
    output_tokens  INTEGER CHECK (output_tokens IS NULL OR output_tokens >= 0)
) STRICT;
CREATE INDEX IF NOT EXISTS ai_calls_request ON ai_calls (request_id);
"""


def connect(path: str | Path = settings.DATABASE_PATH) -> sqlite3.Connection:
    """Opens a connection and turns on foreign key checks. Tests pass ":memory:"."""
    if sqlite3.sqlite_version_info < MIN_SQLITE_VERSION:
        raise RuntimeError(
            f"SQLite version is too old ({sqlite3.sqlite_version}); at least 3.37.0 is needed."
        )
    connection = sqlite3.connect(path)
    connection.execute("PRAGMA foreign_keys = ON")
    if connection.execute("PRAGMA foreign_keys").fetchone()[0] != 1:
        connection.close()
        raise RuntimeError("Could not turn on foreign key checks.")
    return connection


def create_tables(connection: sqlite3.Connection) -> None:
    """Creates the tables in one transaction. Safe to run twice; existing rows are not touched."""
    version = connection.execute("PRAGMA user_version").fetchone()[0]
    if version > SCHEMA_VERSION:
        raise RuntimeError(
            f"Database schema version ({version}) is newer than the code ({SCHEMA_VERSION})."
        )
    if 0 < version < SCHEMA_VERSION:
        raise RuntimeError(
            f"Database schema version ({version}) is older than the code ({SCHEMA_VERSION}). "
            "Delete the database file and load the seed again: python -m app.slack_connector.seed load"
        )
    try:
        connection.executescript(
            f"BEGIN;\n{SCHEMA_SQL}\nPRAGMA user_version = {SCHEMA_VERSION};\nCOMMIT;"
        )
    except sqlite3.Error:
        if connection.in_transaction:
            connection.rollback()
        raise
