"""Slack sync (S1-04): channels, users, members of allowed channels and messages of the last N days.

Run (inside server/): .venv/Scripts/python -m app.slack_connector.sync [--days 30] [--from-scratch]

- The allow list is checked again BEFORE every channel request: no request is made to Slack for an "excluded" channel.
- The same message (channel + ts) is not written twice; running the command again is safe.
- If a channel fails, it is written to the audit log and the other channels continue.
- The token is never written to any output, the audit log or an error message.
"""
import argparse
import sqlite3
import sys
import time
import uuid
from collections import Counter
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from .. import settings
from ..audit.log import write_event
from ..database.rules import ALLOWED, EXCLUDED, channel_status
from ..database.schema import connect, create_tables
from . import sanitize
from .transform import channel_row, oldest_ts, skip_reason, ts_to_iso, user_row
from .client import HttpxSlackClient, SlackError, SlackClient, paginate

STEP = "slack_sync"
DEFAULT_DAYS = 30
MIN_DAYS = 1
MAX_DAYS = 365
PAGE_SIZE = "200"


@dataclass
class ChannelResult:
    """The result of one channel in this run. Carries no message text."""

    name: str
    status: str  # "ok", "error" or "excluded"
    new_messages: int = 0
    fetched_messages: int = 0
    skipped: Counter = field(default_factory=Counter)  # skip reason (subtype name) -> count
    member_count: int = 0
    deleted_messages: int = 0
    reason_code: str | None = None
    error_detail: str | None = None


@dataclass
class SyncSummary:
    run_id: str
    days: int
    channel_count: int = 0
    user_count: int = 0
    membership_count: int = 0
    message_count: int = 0
    channels: list[ChannelResult] = field(default_factory=list)
    failed_to_start: str | None = None  # reason code if a list could not be fetched
    error_detail: str | None = None

    @property
    def has_errors(self) -> bool:
        return self.failed_to_start is not None or any(c.status == "error" for c in self.channels)


def _duration_ms(timer: Callable[[], float], start: float) -> float:
    return round(max(timer() - start, 0.0) * 1000, 2)


def _error_detail(error: Exception) -> str:
    if isinstance(error, SlackError):
        return f"Slack: {error.code}"
    if isinstance(error, sqlite3.Error):
        return f"database: {type(error).__name__}"
    return "Slack: invalid_response"


def _write_error(connection, *, now, run_id, reason_code, duration_ms, channel_id=None) -> None:
    with connection:
        write_event(
            connection, created_at=now().isoformat(), request_id=run_id, step=STEP, decision="error",
            reason_code=reason_code, channel_id=channel_id, duration_ms=duration_ms,
        )


def _failed_to_start(connection, summary: SyncSummary, reason_code: str, error: Exception, *, now,
                     duration_ms) -> SyncSummary:
    _write_error(connection, now=now, run_id=summary.run_id, reason_code=reason_code, duration_ms=duration_ms)
    summary.failed_to_start = reason_code
    summary.error_detail = _error_detail(error)
    return summary


def _write_lists(connection, channels, users, *, from_scratch: bool) -> dict[str, ChannelResult]:
    """Writes users and channels in one transaction; deletes messages and memberships of excluded channels."""
    seen = {row["slack_id"] for row, _ in channels}
    previously_allowed = {s[0] for s in connection.execute(
        "SELECT slack_id FROM channels WHERE status = ?", (ALLOWED,)
    )}
    results: dict[str, ChannelResult] = {}
    with connection:
        if from_scratch:
            connection.execute("DELETE FROM channel_memberships")
            connection.execute("DELETE FROM messages")
        for u in users:
            connection.execute(
                "INSERT INTO slack_users (slack_id, display_name, real_name, is_bot) "
                "VALUES (:slack_id, :display_name, :real_name, :is_bot) "
                "ON CONFLICT (slack_id) DO UPDATE SET display_name = excluded.display_name, "
                "real_name = excluded.real_name, is_bot = excluded.is_bot",
                u,
            )
        for row, _ in channels:
            connection.execute(
                "INSERT INTO channels (slack_id, name, is_private, status) "
                "VALUES (:slack_id, :name, :is_private, :status) "
                "ON CONFLICT (slack_id) DO UPDATE SET name = excluded.name, "
                "is_private = excluded.is_private, status = excluded.status",
                row,
            )
        # A channel no longer seen in the Slack list (archived, deleted, bot removed) is not read.
        for (slack_id,) in connection.execute("SELECT slack_id FROM channels").fetchall():
            if slack_id not in seen:
                connection.execute("UPDATE channels SET status = ? WHERE slack_id = ?", (EXCLUDED, slack_id))
        # Old data of an excluded channel is not kept.
        for slack_id, name in connection.execute(
            "SELECT slack_id, name FROM channels WHERE status = ?", (EXCLUDED,)
        ).fetchall():
            connection.execute("DELETE FROM channel_memberships WHERE channel_id = ?", (slack_id,))
            deleted = connection.execute("DELETE FROM messages WHERE channel_id = ?", (slack_id,)).rowcount
            if slack_id in seen or slack_id in previously_allowed or deleted:
                results[slack_id] = ChannelResult(name=name, status=EXCLUDED, deleted_messages=deleted)
    return results


def _sync_channel(connection, client, row, bot_member, allowed, *, oldest, now, run_id, timer) -> ChannelResult:
    start = timer()
    channel_id = row["slack_id"]
    result = ChannelResult(name=row["name"], status="ok")

    def error(reason_code: str, detail: str) -> ChannelResult:
        result.status, result.reason_code, result.error_detail = "error", reason_code, detail
        _write_error(
            connection, now=now, run_id=run_id, reason_code=reason_code,
            duration_ms=_duration_ms(timer, start), channel_id=channel_id,
        )
        return result

    # Defense: right before the request the status is computed again with the current name in Slack.
    if channel_status(row["name"], allowed) != ALLOWED:
        result.status = EXCLUDED
        return result
    if not bot_member:
        return error("BOT_NOT_IN_CHANNEL", "bot is not in the channel; invite it to the channel")

    try:
        members = paginate(
            client, "conversations.members", {"channel": channel_id, "limit": PAGE_SIZE}, "members",
        )
        if not all(isinstance(m, str) and m for m in members):
            raise SlackError("invalid_response")
        messages = paginate(
            client, "conversations.history",
            {"channel": channel_id, "oldest": oldest, "limit": PAGE_SIZE}, "messages",
        )
    except SlackError as e:
        return error("CHANNEL_FETCH_FAILED", _error_detail(e))

    to_keep = []
    skipped: Counter = Counter()
    for m in messages:
        reason = skip_reason(m)
        if reason:
            skipped[reason] += 1
        else:
            to_keep.append(m)

    updated_at = now().isoformat()
    member_set = set(members)
    new = 0
    try:
        with connection:
            # For an unknown member or author, first a user row with empty names.
            for user_id in sorted(member_set | {m["user"] for m in to_keep}):
                connection.execute(
                    "INSERT INTO slack_users (slack_id) VALUES (?) ON CONFLICT (slack_id) DO NOTHING",
                    (user_id,),
                )
            for member in sorted(member_set):
                connection.execute(
                    "INSERT INTO channel_memberships (channel_id, slack_user_id, updated_at) "
                    "VALUES (?, ?, ?) ON CONFLICT (channel_id, slack_user_id) "
                    "DO UPDATE SET updated_at = excluded.updated_at",
                    (channel_id, member, updated_at),
                )
            # Memberships of people who left the channel are deleted (no stale permission stays).
            for (old,) in connection.execute(
                "SELECT slack_user_id FROM channel_memberships WHERE channel_id = ?", (channel_id,)
            ).fetchall():
                if old not in member_set:
                    connection.execute(
                        "DELETE FROM channel_memberships WHERE channel_id = ? AND slack_user_id = ?",
                        (channel_id, old),
                    )
            for m in to_keep:
                cursor = connection.execute(
                    "INSERT INTO messages (channel_id, ts, author_id, sent_at, clean_text) "
                    "VALUES (?, ?, ?, ?, ?) ON CONFLICT (channel_id, ts) DO NOTHING",
                    (channel_id, m["ts"], m["user"], ts_to_iso(m["ts"]), sanitize.sanitize(m["text"])),
                )
                new += cursor.rowcount
    except sqlite3.Error as e:
        return error("CHANNEL_WRITE_FAILED", _error_detail(e))

    result.new_messages = new
    result.fetched_messages = len(messages)
    result.skipped = skipped
    result.member_count = len(member_set)
    return result


def sync_slack(
    connection: sqlite3.Connection,
    client: SlackClient,
    allowed_channels: Iterable[str],
    *,
    days: int,
    now: Callable[[], datetime],
    run_id: str,
    from_scratch: bool = False,
    timer: Callable[[], float] = time.perf_counter,
) -> SyncSummary:
    """Fetches and writes channels, users, members of allowed channels and messages of the last `days` days."""
    create_tables(connection)
    allowed = list(allowed_channels)
    start = timer()
    summary = SyncSummary(run_id=run_id, days=days)

    # 1. Lists: first all pages are fetched, then written.
    try:
        channels = [
            (channel_row(c, allowed), c.get("is_member") is True)
            for c in paginate(
                client, "conversations.list",
                {"types": "public_channel,private_channel", "exclude_archived": "true",
                 "limit": PAGE_SIZE},
                "channels",
            )
        ]
    except (SlackError, ValueError) as e:
        return _failed_to_start(connection, summary, "CHANNEL_LIST_FAILED", e, now=now,
                                duration_ms=_duration_ms(timer, start))
    try:
        users = [
            user_row(u)
            for u in paginate(client, "users.list", {"limit": PAGE_SIZE}, "members")
        ]
    except (SlackError, ValueError) as e:
        return _failed_to_start(connection, summary, "USER_LIST_FAILED", e, now=now,
                                duration_ms=_duration_ms(timer, start))

    # 2. Users, channels and statuses in one transaction.
    try:
        results = _write_lists(connection, channels, users, from_scratch=from_scratch)
    except sqlite3.Error as e:
        return _failed_to_start(connection, summary, "DB_WRITE_FAILED", e, now=now,
                                duration_ms=_duration_ms(timer, start))
    summary.user_count = len(users)

    # 3. Allowed channels, each in its own transaction.
    oldest = oldest_ts(now(), days)
    for row, bot_member in sorted(channels, key=lambda c: c[0]["name"]):
        if row["status"] != ALLOWED:
            continue
        results[row["slack_id"]] = _sync_channel(
            connection, client, row, bot_member, allowed,
            oldest=oldest, now=now, run_id=run_id, timer=timer,
        )

    # 4. Summary row.
    summary.channels = sorted(results.values(), key=lambda r: r.name)
    succeeded = [r for r in summary.channels if r.status == "ok"]
    summary.channel_count = len(succeeded)
    summary.membership_count = sum(r.member_count for r in succeeded)
    summary.message_count = sum(r.new_messages for r in succeeded)
    with connection:
        write_event(
            connection, created_at=now().isoformat(), request_id=run_id, step=STEP, decision="ok",
            reason_code="SOME_CHANNELS_FAILED" if summary.has_errors else None,
            duration_ms=_duration_ms(timer, start),
            channel_count=summary.channel_count, user_count=summary.user_count,
            membership_count=summary.membership_count, message_count=summary.message_count,
        )
    return summary


def _channel_line(r: ChannelResult, width: int) -> str:
    name = f"#{r.name}".ljust(width)
    if r.status == EXCLUDED:
        extra = f", {r.deleted_messages} old messages deleted" if r.deleted_messages else ""
        return f"{name} excluded  (no request made{extra})"
    if r.status == "error":
        return f"{name} ERROR     {r.reason_code} ({r.error_detail})"
    skipped = sum(r.skipped.values())
    breakdown = ""
    if skipped:
        ordered = sorted(r.skipped.items(), key=lambda x: (-x[1], x[0]))
        breakdown = ": " + ", ".join(f"{reason} {count}" for reason, count in ordered)
    return (f"{name} ok        {r.new_messages} new / {r.fetched_messages} fetched / "
            f"{skipped} skipped{breakdown} · {r.member_count} members")


def print_summary(summary: SyncSummary, write: Callable[[str], None]) -> None:
    """Writes the result of the run to the screen: message counts per channel. No message text is written."""
    if summary.failed_to_start:
        write(f"ERROR {summary.failed_to_start} ({summary.error_detail}). No channel was synced.")
        return
    allowed = sum(1 for r in summary.channels if r.status != EXCLUDED)
    write(f"Users: {summary.user_count} · Channels: {len(summary.channels)} "
          f"(allowed {allowed}, excluded {len(summary.channels) - allowed})")
    width = max((len(r.name) for r in summary.channels), default=0) + 1
    for r in summary.channels:
        write(_channel_line(r, width))
    write(f"Summary: {summary.channel_count} channels, {summary.user_count} users, "
          f"{summary.membership_count} memberships, {summary.message_count} new messages. "
          "Written to the audit log.")


def run_command(
    argv: list[str],
    *,
    token: str,
    client_factory: Callable[[str], SlackClient],
    database_path: str | Path,
    allowed_channels: Iterable[str],
    now: Callable[[], datetime],
    write: Callable[[str], None],
    run_id_factory: Callable[[], str] = lambda: uuid.uuid4().hex,
) -> int:
    """Command line. Exit: 0 all ok, 1 at least one channel failed, 2 could not start."""
    parser = argparse.ArgumentParser(
        prog="python -m app.slack_connector.sync",
        description="Fetches channels, users, memberships and messages from Slack.",
    )
    parser.add_argument("--days", type=int, default=DEFAULT_DAYS,
                        help=f"Messages of the last how many days (default {DEFAULT_DAYS}, "
                             f"minimum {MIN_DAYS}, maximum {MAX_DAYS}).")
    parser.add_argument("--from-scratch", action="store_true",
                        help="Deletes all messages and memberships before syncing.")
    try:
        args = parser.parse_args(argv)
    except SystemExit as exit_:
        return 0 if exit_.code == 0 else 2

    if not MIN_DAYS <= args.days <= MAX_DAYS:
        write(f"--days must be at least {MIN_DAYS} and at most {MAX_DAYS}.")
        return 2
    if not token:
        write("SLACK_BOT_TOKEN is empty in .env. If you have no bot token, "
              "use the 'python -m app.slack_connector.seed load' command.")
        return 2

    client = client_factory(token)
    connection = connect(database_path)
    try:
        create_tables(connection)
        run_id = run_id_factory()
        scratch_note = ", messages and memberships will be deleted first" if args.from_scratch else ""
        write(f"Slack sync started (last {args.days} days{scratch_note}). Run: {run_id[:12]}")
        summary = sync_slack(
            connection, client, allowed_channels, days=args.days, now=now,
            run_id=run_id, from_scratch=args.from_scratch,
        )
    finally:
        connection.close()
        close = getattr(client, "close", None)
        if close:
            close()
    print_summary(summary, write)
    if summary.failed_to_start:
        return 2
    return 1 if summary.has_errors else 0


def main() -> None:
    sys.exit(run_command(
        sys.argv[1:],
        token=settings.SLACK_BOT_TOKEN,
        client_factory=lambda token: HttpxSlackClient(token, time.sleep),
        database_path=settings.DATABASE_PATH,
        allowed_channels=settings.ALLOWED_CHANNELS,
        now=lambda: datetime.now(timezone.utc),
        write=print,
    ))


if __name__ == "__main__":
    main()
