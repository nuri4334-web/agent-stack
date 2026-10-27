"""Data selection query (S1-05): reads only messages of allowed channels from the S1-04 tables."""
import sqlite3
from dataclasses import dataclass, field

from ..schemas import SourceMessage
from ..database.rules import ALLOWED
from .rules import MESSAGE_LIMIT, TargetResult, author_name, find_target_channels, resolve_slack_mentions


@dataclass
class Selection:
    result: TargetResult
    messages: list[SourceMessage] = field(default_factory=list)  # oldest to newest


def select_messages(connection: sqlite3.Connection, question: str, *, limit: int = MESSAGE_LIMIT) -> Selection:
    """Selects the newest `limit` messages for the question. Does not open or close the connection; only reads."""
    channels = connection.execute("SELECT slack_id, name, status FROM channels ORDER BY slack_id").fetchall()
    result, targets = find_target_channels(question, channels)
    return Selection(result, _messages(connection, targets, channels, limit) if result == "ok" else [])


def _messages(connection, targets: list[str], channels, limit: int) -> list[SourceMessage]:
    if not targets:
        return []
    placeholders = ", ".join("?" * len(targets))
    # The status condition is applied independently of the target list too: an excluded channel is never read.
    rows = connection.execute(
        "SELECT m.ts, m.sent_at, m.clean_text, c.name, u.slack_id, u.real_name, u.display_name "
        "FROM messages m "
        "JOIN channels c ON c.slack_id = m.channel_id "
        "JOIN slack_users u ON u.slack_id = m.author_id "
        f"WHERE c.status = ? AND m.channel_id IN ({placeholders}) "
        "ORDER BY m.ts DESC, m.channel_id DESC "
        "LIMIT ?",
        (ALLOWED, *targets, limit),
    ).fetchall()
    user_names = {
        slack_id: author_name(real_name, display_name, slack_id)
        for slack_id, real_name, display_name in connection.execute(
            "SELECT slack_id, real_name, display_name FROM slack_users"
        )
    }
    channel_names = {slack_id: name for slack_id, name, _ in channels}
    return [
        SourceMessage(
            channel=channel_name,
            author=author_name(real_name, display_name, author_id),
            time=sent_at,
            text=resolve_slack_mentions(clean_text, user_names, channel_names),
        )
        for _, sent_at, clean_text, channel_name, author_id, real_name, display_name in reversed(rows)
    ]
