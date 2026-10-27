"""Data selection rules (S1-05): pure functions; use no database, network or clock."""
import re
from collections.abc import Mapping, Sequence
from typing import Literal

from ..database.rules import ALLOWED, normalize_channel_name

# Maximum number of messages that can go to the AI in one request (in total, not per channel).
MESSAGE_LIMIT = 50

# "#name": the name goes on with letters, digits, "_" or "-"; it stops at an apostrophe ("#dev'i" -> "dev").
_CHANNEL_PATTERN = re.compile(r"#([\w-]+)")
_USER_MENTION = re.compile(r"<@([UW][A-Z0-9]+)(?:\|[^>]*)?>")
_CHANNEL_MENTION = re.compile(r"<#(C[A-Z0-9]+)(?:\|[^>]*)?>")

TargetResult = Literal["ok", "no_slack_data", "channel_not_allowed"]


def channels_in_question(question: str) -> list[str]:
    """Channel names written as "#name" in the question (lower case, without "#", in first-seen order, no repeats).

    Names without "#" are not recognized. Expressions made only of digits ("PR #17", "#1") are not channel names.
    """
    names: list[str] = []
    for match in _CHANNEL_PATTERN.finditer(question):
        name = normalize_channel_name(match.group(1))
        if name.isdigit() or name in names:
            continue
        names.append(name)
    return names


def find_target_channels(
    question: str, channels: Sequence[tuple[str, str, str]]
) -> tuple[TargetResult, list[str]]:
    """Channel ids to read. `channels`: (slack_id, name, status) rows.

    "no_slack_data" if the channels table is empty. If the question names channels, each name must belong to exactly
    one row and that row must be "allowed"; if even one is not (unknown, more than one row with the name, not allowed),
    "channel_not_allowed" and an empty list. If no name is given, all allowed channels.
    """
    if not channels:
        return "no_slack_data", []
    names = channels_in_question(question)
    if not names:
        return "ok", [slack_id for slack_id, _, status in channels if status == ALLOWED]
    by_name: dict[str, list[tuple[str, str]]] = {}
    for slack_id, name, status in channels:
        by_name.setdefault(normalize_channel_name(name), []).append((slack_id, status))
    targets = []
    for name in names:
        rows = by_name.get(name, [])
        # More than one row with the same name (e.g. a stale old name): the safe side is to refuse.
        if len(rows) != 1 or rows[0][1] != ALLOWED:
            return "channel_not_allowed", []
        targets.append(rows[0][0])
    return "ok", targets


def author_name(real_name: str | None, display_name: str | None, slack_id: str) -> str:
    """Real name first, otherwise display name, otherwise the Slack id. Only spaces count as empty."""
    for name in (real_name, display_name):
        if name and name.strip():
            return name.strip()
    return slack_id


def resolve_slack_mentions(
    text: str, user_names: Mapping[str, str], channel_names: Mapping[str, str]
) -> str:
    """<@U..> -> @name, <#C..> -> #name. The name comes from the database, not from the "|.." part of the mention.

    Unknown ids and other <...> forms (<tel:..>, <https://..>, <!here>) stay as they are.
    """
    def user(m: re.Match) -> str:
        name = user_names.get(m.group(1))
        return f"@{name}" if name else m.group(0)

    def channel(m: re.Match) -> str:
        name = channel_names.get(m.group(1))
        return f"#{name}" if name else m.group(0)

    return _CHANNEL_MENTION.sub(channel, _USER_MENTION.sub(user, text))
