"""Data selection query (S1-05): reads only messages of allowed channels from the S1-04 tables."""
import logging
import sqlite3
from collections.abc import Collection, Iterable
from dataclasses import dataclass, field

from .. import settings
from ..schemas import SourceMessage
from ..database.rules import ALLOWED, channel_list_warnings, channel_status
from .rules import (
    MESSAGE_LIMIT, TargetResult, author_name, find_target_channels, resolve_slack_mentions, source_id,
)

log = logging.getLogger("agentstack")

# Channel setting warnings already written to the server log (each one once per process).
_reported_warnings: set[str] = set()


@dataclass
class Selection:
    result: TargetResult
    messages: list[SourceMessage] = field(default_factory=list)  # oldest to newest


def reset_reported_warnings() -> None:
    """Forgets which setting warnings were logged (for tests, so they do not depend on the order)."""
    _reported_warnings.clear()


def _report_warnings(allowed: list[str], blocked: list[str]) -> None:
    for warning in channel_list_warnings(allowed, blocked):
        if warning not in _reported_warnings:
            _reported_warnings.add(warning)
            log.warning("Channel settings: %s", warning)


def _channel_lists(
    allowed_channels: Iterable[str] | None, blocked_channels: Iterable[str] | None,
) -> tuple[list[str], list[str]]:
    return (
        list(settings.ALLOWED_CHANNELS if allowed_channels is None else allowed_channels),
        list(settings.BLOCKED_CHANNELS if blocked_channels is None else blocked_channels),
    )


def question_time_channels(
    connection: sqlite3.Connection,
    *,
    allowed_channels: Iterable[str] | None = None,
    blocked_channels: Iterable[str] | None = None,
) -> list[tuple[str, str, str]]:
    """(slack_id, name, status) rows. The status is "allowed" only if the table AND the current settings say so.

    The allow and blocked lists are by channel id (None -> the settings at call time), so a channel blocked in .env
    is not read even before a sync.
    """
    allowed, blocked = _channel_lists(allowed_channels, blocked_channels)
    _report_warnings(allowed, blocked)
    return [
        (slack_id, name, status if status != ALLOWED else channel_status(slack_id, allowed, blocked))
        for slack_id, name, status in connection.execute(
            "SELECT slack_id, name, status FROM channels ORDER BY slack_id"
        ).fetchall()
    ]


def member_channel_ids(connection: sqlite3.Connection, slack_user_id: str) -> frozenset[str]:
    """The channels the Slack account is a member of, as of the last sync."""
    return frozenset(channel_id for (channel_id,) in connection.execute(
        "SELECT channel_id FROM channel_memberships WHERE slack_user_id = ?", (slack_user_id,)
    ))


def select_messages(
    connection: sqlite3.Connection,
    question: str,
    *,
    readable_channel_ids: Collection[str],
    limit: int = MESSAGE_LIMIT,
    allowed_channels: Iterable[str] | None = None,
    blocked_channels: Iterable[str] | None = None,
) -> Selection:
    """Selects the newest `limit` messages for the question. Does not open or close the connection; only reads.

    Only channels in `readable_channel_ids` (the authorization decision) are read; there is no default, so nothing
    is read without a decision. The channel rule is applied here again, even if that decision is wrong.
    """
    allowed, blocked = _channel_lists(allowed_channels, blocked_channels)
    channels = question_time_channels(connection, allowed_channels=allowed, blocked_channels=blocked)
    result, targets = find_target_channels(question, channels)
    # The current settings are applied to the target list too, even if the target decision is wrong.
    targets = [t for t in targets if t in readable_channel_ids and channel_status(t, allowed, blocked) == ALLOWED]
    return Selection(result, _messages(connection, targets, channels, limit) if result == "ok" else [])


def _messages(connection, targets: list[str], channels, limit: int) -> list[SourceMessage]:
    if not targets:
        return []
    placeholders = ", ".join("?" * len(targets))
    # The status condition is applied independently of the target list too: an excluded channel is never read.
    rows = connection.execute(
        "SELECT m.channel_id, m.ts, m.sent_at, m.clean_text, c.name, u.slack_id, u.real_name, u.display_name "
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
            id=source_id(channel_id, ts),
            channel=channel_name,
            author=author_name(real_name, display_name, author_id),
            time=sent_at,
            text=resolve_slack_mentions(clean_text, user_names, channel_names),
        )
        for channel_id, ts, sent_at, clean_text, channel_name, author_id, real_name, display_name in reversed(rows)
    ]
