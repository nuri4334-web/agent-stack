"""Secret rules (S3-09): the S1-11 catalog as code."""
from .types import Span


def find_secrets(text: str) -> list[Span]:
    """The secrets in a normalized text. Never returns a weak finding."""
    # Skeleton (S3-01). Rules: Musa, Thu 12 Nov (S3-09).
    return []
