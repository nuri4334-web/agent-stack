"""Data selection rules (S1-05): pure functions; use no database, network or clock."""
import re
from collections.abc import Callable, Collection, Mapping, Sequence
from dataclasses import dataclass
from typing import Literal, TypeVar

from ..database.rules import ALLOWED, normalize_channel_name

# Maximum number of messages that can go to the AI in one request (in total, not per channel).
MESSAGE_LIMIT = 50

# "#name": the name goes on with letters, digits, "_" or "-"; it stops at an apostrophe ("#dev'i" -> "dev").
_CHANNEL_PATTERN = re.compile(r"#([\w-]+)")
_USER_MENTION = re.compile(r"<@([UW][A-Z0-9]+)(?:\|[^>]*)?>")
_CHANNEL_MENTION = re.compile(r"<#(C[A-Z0-9]+)(?:\|[^>]*)?>")

TargetResult = Literal["ok", "no_slack_data", "channel_not_allowed"]

T = TypeVar("T")


@dataclass(frozen=True)
class AccessDecision:
    reason_code: str | None = None  # None: authorization passed
    channel_ids: tuple[str, ...] = ()  # the channels the person may read for this question


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


def _rows_by_name(channels: Sequence[tuple[str, str, str]]) -> dict[str, list[tuple[str, str]]]:
    by_name: dict[str, list[tuple[str, str]]] = {}
    for slack_id, name, status in channels:
        by_name.setdefault(normalize_channel_name(name), []).append((slack_id, status))
    return by_name


def _allowed_id(rows: Sequence[tuple[str, str]]) -> str | None:
    """The id of the name's only row if it is "allowed", otherwise None."""
    # More than one row with the same name (e.g. a stale old name): the safe side is to refuse.
    if len(rows) != 1 or rows[0][1] != ALLOWED:
        return None
    return rows[0][0]


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
    by_name = _rows_by_name(channels)
    targets = []
    for name in names:
        channel_id = _allowed_id(by_name.get(name, []))
        if channel_id is None:
            return "channel_not_allowed", []
        targets.append(channel_id)
    return "ok", targets


def decide_access(
    question: str,
    channels: Sequence[tuple[str, str, str]],
    member_channel_ids: Collection[str],
    *,
    slack_linked: bool,
) -> AccessDecision:
    """Which channels the person may read for this question. `channels`: (slack_id, name, question-time status) rows.

    A channel must be allowed and the person's Slack account must be a member of it; the role is not an input, so it
    never gives access. If the question names channels, the first refused name gives the reason and refuses them all.
    An empty table passes with no channels, so "no Slack data" stays the decision of data selection.
    """
    if not slack_linked:
        return AccessDecision("NO_SLACK_ACCOUNT")
    if not channels:
        return AccessDecision()
    names = channels_in_question(question)
    if not names:
        return AccessDecision(channel_ids=tuple(
            slack_id for slack_id, _, status in channels if status == ALLOWED and slack_id in member_channel_ids
        ))
    by_name = _rows_by_name(channels)
    targets = []
    for name in names:
        channel_id = _allowed_id(by_name.get(name, []))
        if channel_id is None:
            return AccessDecision("CHANNEL_NOT_ALLOWED")
        if channel_id not in member_channel_ids:
            return AccessDecision("NOT_CHANNEL_MEMBER")
        targets.append(channel_id)
    return AccessDecision(channel_ids=tuple(targets))


def source_id(channel_id: str, ts: str) -> str:
    """The stable id of a message in the answer (API contract 8). ts stays the text Slack gave."""
    return f"{channel_id}:{ts}"


def named_channel_id(question: str, channels: Sequence[tuple[str, str, str]]) -> str | None:
    """For the audit log: the id of the one channel the question names, whatever its status.

    None if the question names no channel or more than one, or if the name is not exactly one row of `channels`.
    """
    names = channels_in_question(question)
    if len(names) != 1:
        return None
    rows = [slack_id for slack_id, name, _ in channels if normalize_channel_name(name) == names[0]]
    return rows[0] if len(rows) == 1 else None


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


def split_suspicious(
    items: Sequence[T], text_of: Callable[[T], str], is_suspicious: Callable[[str], bool] | None,
) -> tuple[list[T], int]:
    """The items that are not suspicious (order kept) and how many were removed.

    is_suspicious None: no check is connected yet (Stage 4 connects the detector), so every item is kept and 0 removed.
    """
    if is_suspicious is None:
        return list(items), 0
    kept = [item for item in items if not is_suspicious(text_of(item))]
    return kept, len(items) - len(kept)
