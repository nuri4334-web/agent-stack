"""Account commands (S2-02): run only on the server by an admin.

Run (inside server/):
  .venv/Scripts/python -m app.accounts create --username ali --name "Ali Kaya" [--role admin]
  .venv/Scripts/python -m app.accounts set-password --username ali
  .venv/Scripts/python -m app.accounts link-slack --username ali --slack-id U0CA5HH3M1V
  .venv/Scripts/python -m app.accounts deactivate --username ali
  .venv/Scripts/python -m app.accounts activate --username ali
  .venv/Scripts/python -m app.accounts list

A password is never a command line argument (it would stay in the shell history): the command asks for it
twice with hidden input. Nothing is ever printed with a password, a password hash or a session token.
"""
import argparse
import getpass
import sqlite3
import sys
from collections.abc import Callable
from datetime import datetime, timezone
from pathlib import Path

from .. import settings
from ..database.schema import connect, create_tables
from . import store
from .rules import hash_password, name_problem, normalize_username, password_problem, username_problem
from .store import AccountError

MAX_PASSWORD_ATTEMPTS = 3

USAGE_ERROR = ("Wrong arguments; see 'python -m app.accounts --help'. "
               "A password is never given on the command line; the command asks for it.")


class _UsageError(Exception):
    pass


class _Parser(argparse.ArgumentParser):
    """argparse would print the wrong arguments (perhaps a password typed by mistake); this parser does not."""

    def error(self, message):
        raise _UsageError()


def _parser() -> argparse.ArgumentParser:
    parser = _Parser(prog="python -m app.accounts", description="Accounts (server only).")
    sub = parser.add_subparsers(dest="command", required=True)
    create = sub.add_parser("create", help="Creates an account; asks for the password.")
    create.add_argument("--username", required=True)
    create.add_argument("--name", required=True, help="Name shown on the screen.")
    create.add_argument("--role", choices=["user", "admin"], default="user")
    for command, text in [
        ("set-password", "Sets a new password; ends the account's sessions."),
        ("deactivate", "Makes the account inactive; ends its sessions."),
        ("activate", "Makes an inactive account active again."),
    ]:
        sub.add_parser(command, help=text).add_argument("--username", required=True)
    link = sub.add_parser("link-slack", help="Links a Slack account (link method admin).")
    link.add_argument("--username", required=True)
    link.add_argument("--slack-id", required=True)
    sub.add_parser("list", help="Lists the accounts (never the password hash).")
    return parser


def _ask_new_password(read_password: Callable[[str], str], write: Callable[[str], None]) -> str:
    """Asks for a new password twice, at most 3 attempts. AccountError if no valid password was given."""
    for _ in range(MAX_PASSWORD_ATTEMPTS):
        password = read_password("Password: ")
        problem = password_problem(password)
        if problem:
            write(problem)
            continue
        if read_password("Password again: ") != password:
            write("The two passwords do not match.")
            continue
        return password
    raise AccountError(f"No valid password after {MAX_PASSWORD_ATTEMPTS} attempts. No change was made.")


def _username(value: str) -> str:
    username = normalize_username(value)
    problem = username_problem(username)
    if problem:
        raise AccountError(problem)
    return username


def _existing(connection: sqlite3.Connection, value: str) -> dict:
    username = _username(value)
    person = store.find_person(connection, username)
    if person is None:
        raise AccountError(f"No account with the user name '{username}'.")
    return person


def _list_lines(accounts: list[dict]) -> list[str]:
    rows = [("username", "name", "role", "active", "password", "slack")] + [
        (a["username"], a["display_name"], a["role"], "yes" if a["is_active"] else "no",
         "set" if a["has_password"] else "not set", a["slack_id"] or "-")
        for a in accounts
    ]
    widths = [max(len(row[i]) for row in rows) for i in range(len(rows[0]))]
    return ["  ".join(cell.ljust(width) for cell, width in zip(row, widths)).rstrip() for row in rows]


def _run(args, connection, now, write, read_password) -> None:
    if args.command == "list":
        accounts = store.list_accounts(connection)
        if not accounts:
            write("No accounts yet; create one with 'python -m app.accounts create'.")
            return
        for line in _list_lines(accounts):
            write(line)
        return

    if args.command == "create":
        username = _username(args.username)
        name = args.name.strip()
        problem = name_problem(name)
        if problem:
            raise AccountError(problem)
        if store.find_person(connection, username):
            raise AccountError(f"An account with the user name '{username}' already exists.")
        password_hash = hash_password(_ask_new_password(read_password, write))
        store.create_account(
            connection, username=username, name=name, role=args.role,
            password_hash=password_hash, created_at=now().isoformat(),
        )
        write(f"Account created: {username} ({name}, role {args.role}). No Slack account is linked yet.")
        return

    person = _existing(connection, args.username)
    username = person["username"]
    if args.command == "set-password":
        password_hash = hash_password(_ask_new_password(read_password, write))
        ended = store.set_password_hash(connection, person["id"], password_hash)
        write(f"Password changed for {username}; {ended} sessions ended.")
    elif args.command == "link-slack":
        slack_id = args.slack_id.strip()
        store.link_slack_account(connection, person["id"], slack_id, linked_at=now().isoformat())
        write(f"Slack account {slack_id} linked to {username}.")
    elif args.command == "deactivate":
        if not person["is_active"]:
            write(f"{username} is already inactive.")
            return
        ended = store.deactivate(connection, person["id"])
        write(f"{username} deactivated; {ended} sessions ended.")
    elif args.command == "activate":
        if person["is_active"]:
            write(f"{username} is already active.")
            return
        store.activate(connection, person["id"])
        write(f"{username} activated.")


def run_command(
    argv: list[str],
    *,
    database_path: str | Path,
    now: Callable[[], datetime],
    write: Callable[[str], None],
    read_password: Callable[[str], str],
) -> int:
    """Command line. Exit: 0 ok, 1 system error (database, schema version), 2 user error or wrong usage."""
    try:
        args = _parser().parse_args(argv)
    except _UsageError:
        write(f"ERROR: {USAGE_ERROR}")
        return 2
    except SystemExit as exit_:
        return 0 if exit_.code == 0 else 2

    try:
        connection = connect(database_path)
        try:
            create_tables(connection)
            _run(args, connection, now, write, read_password)
        finally:
            connection.close()
        return 0
    except AccountError as error:
        write(f"ERROR: {error}")
        return 2
    except (KeyboardInterrupt, EOFError):
        write("Cancelled. No change was made.")
        return 2
    except RuntimeError as error:
        write(f"ERROR: {error}")
        return 1
    except sqlite3.Error as error:
        write(f"ERROR: database error ({type(error).__name__}).")
        return 1


def main() -> None:
    sys.exit(run_command(
        sys.argv[1:],
        database_path=settings.DATABASE_PATH,
        now=lambda: datetime.now(timezone.utc),
        write=print,
        read_password=getpass.getpass,
    ))
