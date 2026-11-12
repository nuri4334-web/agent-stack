"""Message sanitizing (S1-04, S3-05): sanitize() is called right before each message is written to the database.

Both paths go through here: Slack sync and seed load. Only secrets are masked here ([REDACTED]); personal data and
names are masked per request in the gateway. The per-kind counts are kept next to the text (secret_counts), never a value.
"""
import json

from ..filters import api
from ..filters.types import SECRET_KINDS, FilterResult


def sanitize(text: str) -> FilterResult:
    """The message text with its secrets masked, and how many of each kind were masked."""
    return api.mask_secrets(text)


def counts_json(result: FilterResult) -> str:
    """The per-kind counts as a JSON object with sorted keys ('{}' if none). Only secret kinds and counts of at least 1.

    ValueError for anything else: these counts reach the screen counter and the event kinds later, so a wrong
    kind or count must stop the write instead of being stored.
    """
    counts = dict(result.counts)
    for kind, count in counts.items():
        if kind not in SECRET_KINDS:
            raise ValueError("secret_counts accepts only secret kinds.")
        if type(count) is not int or count < 1:
            raise ValueError("secret_counts accepts only whole counts of at least 1.")
    return json.dumps(dict(sorted(counts.items())), separators=(",", ":"))
