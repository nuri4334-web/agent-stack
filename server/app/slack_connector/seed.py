"""Seed data (S1-04): exports synced Slack data to JSON and loads it into an empty database.

Run (inside server/):
  .venv/Scripts/python -m app.slack_connector.seed export [--file PATH] [--overwrite]
  .venv/Scripts/python -m app.slack_connector.seed load [--file PATH]

Only allowed channels, their memberships and messages, and the users they mention go into the file.
The audit log, AI calls, people and linked accounts do not.
Secret check: the token used for syncing cannot appear in the file; every text matching a token pattern must contain "EXAMPLE".
"""
import argparse
import json
import re
import sqlite3
import sys
from collections.abc import Callable, Iterable
from datetime import datetime, timezone
from pathlib import Path

from .. import settings
from ..database.rules import ALLOWED, BLOCKED, blocked_list_error, channel_list_warnings, channel_status
from ..database.schema import connect, create_tables
from .transform import is_valid_ts

FORMAT = "agentstack-slack-seed"
VERSION = 2
SEED_PATH = settings.ROOT / "demo-data" / "slack-seed.json"

# Every match of these patterns must contain "EXAMPLE" (the fake keys in the demo data are like this).
SECRET_PATTERNS = {
    "slack_token": re.compile(r"xox[a-z]-[A-Za-z0-9-]+"),
    "github_token": re.compile(r"ghp_[A-Za-z0-9]+"),
    "google_api_key": re.compile(r"AIza[A-Za-z0-9_-]+"),
    "aws_access_key": re.compile(r"AKIA[A-Z0-9]+"),
}

SLACK_TABLES = ("channels", "slack_users", "channel_memberships", "messages")


class SeedError(ValueError):
    """The seed could not be written or read. Its message never contains secrets or message text."""


def _is_id(d: object) -> bool:
    return isinstance(d, str) and len(d) > 0


def _is_text_or_none(d: object) -> bool:
    return d is None or isinstance(d, str)


def _is_bit(d: object) -> bool:
    return type(d) is int and d in (0, 1)


def _is_text(d: object) -> bool:
    return isinstance(d, str)


# Fields and checks of the rows in each list (extra or missing fields are not accepted).
FIELDS = {
    "channels": {"slack_id": _is_id, "name": _is_id, "is_private": _is_bit},
    "slack_users": {
        "slack_id": _is_id, "display_name": _is_text_or_none, "real_name": _is_text_or_none, "is_bot": _is_bit,
    },
    "channel_memberships": {"channel_id": _is_id, "slack_user_id": _is_id},
    "messages": {
        "channel_id": _is_id, "ts": is_valid_ts, "author_id": _is_id, "sent_at": _is_id, "clean_text": _is_text,
    },
}


def check_for_secrets(content: str, token: str = "") -> None:
    """SeedError if the token value appears in the content or a token pattern without EXAMPLE is found.

    The error message does not show the matching text, only the name of the pattern.
    """
    if token and token in content:
        raise SeedError("The seed content contains the Slack token used for syncing.")
    for name, pattern in SECRET_PATTERNS.items():
        for match in pattern.finditer(content):
            if "EXAMPLE" not in match.group():
                raise SeedError(f"The seed content has a secret pattern without EXAMPLE ({name}).")


def _serialize(data: dict) -> str:
    return json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True) + "\n"


def _rows(connection, sql: str, params=()) -> list[dict]:
    cursor = connection.execute(sql, params)
    names = [c[0] for c in cursor.description]
    return [dict(zip(names, row)) for row in cursor.fetchall()]


def export_seed(connection: sqlite3.Connection) -> dict:
    """Returns the allowed channels in the database, their memberships, messages and the users they mention."""
    channels = _rows(
        connection, "SELECT slack_id, name, is_private FROM channels WHERE status = ? ORDER BY slack_id", (ALLOWED,),
    )
    memberships = _rows(
        connection,
        "SELECT m.channel_id, m.slack_user_id FROM channel_memberships m "
        "JOIN channels c ON c.slack_id = m.channel_id WHERE c.status = ? "
        "ORDER BY m.channel_id, m.slack_user_id",
        (ALLOWED,),
    )
    messages = _rows(
        connection,
        "SELECT m.channel_id, m.ts, m.author_id, m.sent_at, m.clean_text FROM messages m "
        "JOIN channels c ON c.slack_id = m.channel_id WHERE c.status = ? ORDER BY m.channel_id, m.ts",
        (ALLOWED,),
    )
    mentioned = {m["slack_user_id"] for m in memberships} | {m["author_id"] for m in messages}
    users = [
        u for u in _rows(
            connection,
            "SELECT slack_id, display_name, real_name, is_bot FROM slack_users ORDER BY slack_id",
        )
        if u["slack_id"] in mentioned
    ]
    return {
        "format": FORMAT, "version": VERSION, "channels": channels, "slack_users": users,
        "channel_memberships": memberships, "messages": messages,
    }


def write_seed_file(data: dict, path: Path, *, overwrite: bool = False, token: str = "") -> None:
    """Writes the seed as JSON (UTF-8, LF). Does not write at all if the secret check fails."""
    content = _serialize(data)
    check_for_secrets(content, token)
    if path.exists() and not overwrite:
        raise SeedError(f"{path.name} already exists; use --overwrite to overwrite it.")
    with open(path, "w", encoding="utf-8", newline="\n") as file:
        file.write(content)


def _validate(data: object) -> None:
    if not isinstance(data, dict) or data.get("format") != FORMAT or data.get("version") != VERSION:
        raise SeedError(f"Seed file is invalid: format must be '{FORMAT}' and version {VERSION}.")
    if set(data) != {"format", "version", *FIELDS}:
        raise SeedError("Seed file is invalid: an unexpected or missing list.")
    for list_name, checks in FIELDS.items():
        rows = data[list_name]
        if not isinstance(rows, list):
            raise SeedError(f"Seed file is invalid: {list_name} must be a list.")
        for index, row in enumerate(rows):
            if not isinstance(row, dict) or set(row) != set(checks):
                raise SeedError(f"Seed file is invalid: {list_name}[{index}] has wrong fields.")
            for field, check in checks.items():
                if not check(row[field]):
                    raise SeedError(f"Seed file is invalid: {list_name}[{index}].{field}")


def read_seed(path: Path, token: str = "") -> dict:
    """Reads the seed file, checks its format and runs the secret check."""
    try:
        raw = path.read_text(encoding="utf-8")
    except OSError as error:
        raise SeedError(f"Seed file could not be read: {path} ({type(error).__name__})") from None
    check_for_secrets(raw, token)
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        raise SeedError("Seed file is not valid JSON.") from None
    _validate(data)
    # Text hidden with escape sequences (\u...) is checked too.
    check_for_secrets(_serialize(data), token)
    return data


def load_seed(
    connection: sqlite3.Connection,
    data: dict,
    allowed_channels: Iterable[str],
    now: Callable[[], datetime],
    *,
    blocked_channels: Iterable[str],
) -> dict[str, int]:
    """Loads the seed into an empty database in one transaction.

    Channel status is computed again from the channel id with the loader's allow and blocked lists (blocked wins).
    """
    create_tables(connection)
    for table in SLACK_TABLES:
        if connection.execute(f"SELECT count(*) FROM {table}").fetchone()[0]:
            raise SeedError(
                "The database is not empty; nothing was loaded. "
                "For a new database, delete the database file (server/agentstack.db)."
            )
    allowed = list(allowed_channels)
    blocked = list(blocked_channels)
    updated_at = now().isoformat()
    counts = {
        "channels": 0, "allowed_channels": 0, "blocked_channels": 0, "users": 0, "memberships": 0, "messages": 0,
    }
    allowed_ids = set()
    try:
        with connection:
            for u in data["slack_users"]:
                connection.execute(
                    "INSERT INTO slack_users (slack_id, display_name, real_name, is_bot) "
                    "VALUES (:slack_id, :display_name, :real_name, :is_bot)",
                    u,
                )
                counts["users"] += 1
            for c in data["channels"]:
                status = channel_status(c["slack_id"], allowed, blocked)
                connection.execute(
                    "INSERT INTO channels (slack_id, name, is_private, status) VALUES (?, ?, ?, ?)",
                    (c["slack_id"], c["name"], c["is_private"], status),
                )
                counts["channels"] += 1
                if status == ALLOWED:
                    allowed_ids.add(c["slack_id"])
                elif status == BLOCKED:
                    counts["blocked_channels"] += 1
            counts["allowed_channels"] = len(allowed_ids)
            for m in data["channel_memberships"]:
                if m["channel_id"] in allowed_ids:
                    connection.execute(
                        "INSERT INTO channel_memberships (channel_id, slack_user_id, updated_at) "
                        "VALUES (?, ?, ?)",
                        (m["channel_id"], m["slack_user_id"], updated_at),
                    )
                    counts["memberships"] += 1
            for m in data["messages"]:
                if m["channel_id"] in allowed_ids:
                    connection.execute(
                        "INSERT INTO messages (channel_id, ts, author_id, sent_at, clean_text) "
                        "VALUES (:channel_id, :ts, :author_id, :sent_at, :clean_text)",
                        m,
                    )
                    counts["messages"] += 1
    except sqlite3.IntegrityError:
        raise SeedError("Seed file is inconsistent (missing user/channel or a repeated row); "
                        "nothing was loaded.") from None
    return counts


def run_command(
    argv: list[str],
    *,
    database_path: str | Path,
    allowed_channels: Iterable[str],
    blocked_channels: Iterable[str],
    now: Callable[[], datetime],
    write: Callable[[str], None],
    token: str = "",
) -> int:
    """Command line. Exit: 0 ok, 1 error, 2 wrong usage."""
    parser = argparse.ArgumentParser(
        prog="python -m app.slack_connector.seed", description="Slack seed data.",
    )
    sub = parser.add_subparsers(dest="command", required=True)
    export = sub.add_parser("export", help="Writes the allowed channel data in the database to JSON.")
    export.add_argument("--file", type=Path, default=SEED_PATH)
    export.add_argument("--overwrite", action="store_true", help="Overwrites an existing file.")
    load = sub.add_parser("load", help="Loads the JSON file into an empty database.")
    load.add_argument("--file", type=Path, default=SEED_PATH)
    try:
        args = parser.parse_args(argv)
    except SystemExit as exit_:
        return 0 if exit_.code == 0 else 2

    try:
        if args.command == "export":
            connection = connect(database_path)
            try:
                create_tables(connection)
                data = export_seed(connection)
            finally:
                connection.close()
            if not data["channels"]:
                write("No allowed channel in the database; run 'python -m app.slack_connector.sync' first.")
                return 1
            write_seed_file(data, args.file, overwrite=args.overwrite, token=token)
            write(f"{args.file} written: {len(data['channels'])} channels, "
                  f"{len(data['slack_users'])} users, {len(data['channel_memberships'])} memberships, "
                  f"{len(data['messages'])} messages.")
            return 0

        allowed_channels, blocked_channels = list(allowed_channels), list(blocked_channels)
        # A wrongly written blocked list must not look like protection: nothing is loaded.
        error = blocked_list_error(blocked_channels)
        if error:
            write(f"ERROR: {error}. Nothing was loaded.")
            return 2
        for warning in channel_list_warnings(allowed_channels, blocked_channels):
            write(f"WARNING: {warning}")
        data = read_seed(args.file, token)
        connection = connect(database_path)
        try:
            create_tables(connection)
            counts = load_seed(connection, data, allowed_channels, now, blocked_channels=blocked_channels)
        finally:
            connection.close()
        write(f"Loaded: {counts['channels']} channels (allowed {counts['allowed_channels']}, "
              f"blocked {counts['blocked_channels']}), "
              f"{counts['users']} users, {counts['memberships']} memberships, {counts['messages']} messages.")
        return 0
    except SeedError as error:
        write(f"ERROR: {error}")
        return 1


def main() -> None:
    sys.exit(run_command(
        sys.argv[1:],
        database_path=settings.DATABASE_PATH,
        allowed_channels=settings.ALLOWED_CHANNELS,
        blocked_channels=settings.BLOCKED_CHANNELS,
        now=lambda: datetime.now(timezone.utc),
        write=print,
        token=settings.SLACK_BOT_TOKEN,
    ))


if __name__ == "__main__":
    main()
