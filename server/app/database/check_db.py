"""Raw secret check (S3-05): proves that no message in the database still contains a secret.

Run (inside server/): .venv/Scripts/python -m app.database.check_db [--db PATH]

- Scans messages.clean_text (the only column that keeps message text) with the same secret rules as sync and seed
  load (find_secrets on the normalized text). Every finding counts, certain or suspicious.
- Opens the database read only: it never creates, changes or fixes anything.
- Prints only the message id and the kind of each finding, never a value or any message text.
- Exit: 0 no raw secret, 1 at least one raw secret, 2 the check could not run (no database file, old schema,
  a failing rule, wrong usage). It never reports "0 raw secrets" when the check did not run.
"""
import argparse
import sqlite3
import sys
from collections.abc import Callable
from pathlib import Path

from .. import settings
from ..filters import normalize as normalize_rules
from ..filters import secrets as secret_rules
from .schema import SCHEMA_VERSION

RELOAD_HINT = "Delete the database file and load the seed again: python -m app.slack_connector.seed load"


def _plural(count: int, word: str) -> str:
    return f"{count} {word}" if count == 1 else f"{count} {word}s"


def _read_messages(path: Path, write: Callable[[str], None]) -> list[tuple[int, str]] | None:
    """The (id, clean_text) rows, or None after writing why they could not be read."""
    if not path.is_file():
        write(f"ERROR: database file not found: {path}. "
              "Load the seed first: python -m app.slack_connector.seed load")
        return None
    try:
        connection = sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True)
    except sqlite3.Error as error:
        write(f"ERROR: the database cannot be opened ({type(error).__name__}).")
        return None
    try:
        version = connection.execute("PRAGMA user_version").fetchone()[0]
        if version != SCHEMA_VERSION:
            write(f"ERROR: database schema version ({version}) is not the code's ({SCHEMA_VERSION}). {RELOAD_HINT}")
            return None
        return connection.execute("SELECT id, clean_text FROM messages ORDER BY id").fetchall()
    except sqlite3.Error as error:
        write(f"ERROR: the messages cannot be read ({type(error).__name__}). {RELOAD_HINT}")
        return None
    finally:
        connection.close()


def run_command(argv: list[str], *, database_path: str | Path, write: Callable[[str], None]) -> int:
    """Command line. Exit: 0 clean, 1 raw secrets found, 2 the check could not run."""
    parser = argparse.ArgumentParser(
        prog="python -m app.database.check_db",
        description="Checks that no message in the database contains a raw secret.",
    )
    parser.add_argument("--db", type=Path, default=None, help="Database file (default: DATABASE_PATH in .env).")
    try:
        args = parser.parse_args(argv)
    except SystemExit as exit_:
        return 0 if exit_.code == 0 else 2

    rows = _read_messages(Path(args.db) if args.db else Path(database_path), write)
    if rows is None:
        return 2
    try:
        findings = sorted(
            (message_id, span.kind)
            for message_id, text in rows
            for span in secret_rules.find_secrets(normalize_rules.normalize(text))
        )
    except Exception as error:
        # Closed on error: a rule that fails must never look like a clean database.
        write(f"The secret check failed ({type(error).__name__}).")
        return 2

    write(f"Checked {_plural(len(rows), 'message')}.")
    for message_id, kind in findings:
        write(f"message {message_id}: {kind}")
    if not findings:
        write("0 raw secrets.")
        return 0
    messages = len({message_id for message_id, _ in findings})
    write(f"{_plural(len(findings), 'raw secret')} in {_plural(messages, 'message')}.")
    return 1


def main() -> None:
    sys.exit(run_command(sys.argv[1:], database_path=settings.DATABASE_PATH, write=print))


if __name__ == "__main__":
    main()
