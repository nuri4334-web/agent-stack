"""Name rules (S3-07): the names of the Slack people."""
from collections.abc import Sequence

from .types import Span


def find_names(text: str, people: Sequence[str]) -> list[Span]:
    """Whole-word, case-insensitive matches (Turkish İ/ı handled) of people, the shown names of non-bot Slack users."""
    # Skeleton (S3-01). Rules: Görkem, Wed 11 Nov (S3-07).
    return []
