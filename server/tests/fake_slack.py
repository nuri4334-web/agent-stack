"""Fake Slack client for tests: never goes to real Slack, records every call, gives paged answers."""
from datetime import datetime, timezone

from app.slack_connector.client import SlackError

NOW = datetime(2026, 10, 23, 12, 0, tzinfo=timezone.utc)
# Channel id lists of the sample workspace (MIG-B: the rule works with ids, not names).
ALLOWED_IDS = ["C_GENEL", "C_DEV", "C_YON"]
BLOCKED_IDS = ["C_IK"]


def ts(hours_ago: int, seq: int = 100) -> str:
    """Slack ts (text) from hours_ago hours before NOW."""
    return f"{int(NOW.timestamp()) - hours_ago * 3600}.{seq:06d}"


def message(author, text, hours_ago, seq=100, **fields) -> dict:
    row = {"type": "message", "text": text, "ts": ts(hours_ago, seq)} | fields
    if author is not None:
        row["user"] = author
    return row


def channel(slack_id, name, private=False, member=True) -> dict:
    return {"id": slack_id, "name": name, "is_private": private, "is_member": member}


class FakeSlack:
    def __init__(self, channels, users, members, messages, page_size=None):
        self.channels = channels
        self.users = users
        self.members = members
        self.messages = messages
        self.page_size = page_size
        self.errors: dict[tuple[str, str | None], str] = {}  # (endpoint, channel) -> Slack error code
        self.calls: list[tuple[str, dict]] = []

    def call(self, endpoint, params):
        self.calls.append((endpoint, dict(params)))
        channel_id = params.get("channel")
        if (endpoint, channel_id) in self.errors:
            raise SlackError(self.errors[(endpoint, channel_id)])
        if endpoint == "conversations.list":
            items, field = self.channels, "channels"
        elif endpoint == "users.list":
            items, field = self.users, "members"
        elif endpoint == "conversations.members":
            items, field = self.members.get(channel_id, []), "members"
        elif endpoint == "conversations.history":
            oldest = params.get("oldest", "")
            items = [m for m in self.messages.get(channel_id, []) if m["ts"] > oldest]
            field = "messages"
        else:
            raise AssertionError(f"Unexpected endpoint: {endpoint}")
        start = int(params.get("cursor") or 0)
        size = self.page_size or max(len(items), 1)
        next_start = start + size
        return {
            "ok": True,
            field: items[start:next_start],
            "response_metadata": {"next_cursor": str(next_start) if next_start < len(items) else ""},
        }

    def channel_calls(self, channel_id) -> list[str]:
        return [endpoint for endpoint, p in self.calls if p.get("channel") == channel_id]


def sample_slack(**options) -> FakeSlack:
    """With ALLOWED_IDS / BLOCKED_IDS: genel, dev, yonetim (private) allowed; ik (private) blocked; sales excluded.

    The bot is a member of all.
    """
    return FakeSlack(
        channels=[
            channel("C_GENEL", "genel"),
            channel("C_DEV", "dev"),
            channel("C_YON", "yonetim", private=True),
            channel("C_IK", "ik", private=True),
            channel("C_SALES", "sales"),
        ],
        users=[
            {"id": "U_ALI", "profile": {"display_name": "Ali", "real_name": "Ali Demo"}},
            {"id": "U_DENIZ", "profile": {"display_name": "Deniz", "real_name": "Deniz Demo"}},
            {"id": "U_NURI", "profile": {"display_name": "", "real_name": "Nuri Demo"}},
            {"id": "U_BOT", "is_bot": True, "profile": {"display_name": "agentstack-bot"}},
        ],
        members={
            "C_GENEL": ["U_ALI", "U_DENIZ", "U_NURI", "U_BOT"],
            "C_DEV": ["U_ALI", "U_DENIZ", "U_BOT"],
            "C_YON": ["U_NURI", "U_BOT"],
            "C_IK": ["U_NURI", "U_BOT"],
            "C_SALES": ["U_ALI", "U_BOT"],
        },
        messages={
            "C_GENEL": [
                message("U_ALI", "günaydın", 5, 100),
                message("U_DENIZ", "toplantı saat 10'da", 4, 200),
                message("U_BOT", "kanala katıldı", 6, 300, subtype="channel_join"),
            ],
            "C_DEV": [
                message("U_DENIZ", "login sayfasını sen al", 3, 100),
                message("U_ALI", "tamam", 2, 200),
                message("U_ALI", "PR açtım", 1, 300),
            ],
            "C_YON": [message("U_NURI", "bütçe toplantısı", 2, 100)],
            "C_IK": [message("U_NURI", "maaş listesi", 2, 100)],
            "C_SALES": [message("U_ALI", "teklif hazır", 2, 100)],
        },
        **options,
    )
