"""Answer cleaning (S3-03): external links and images removed, second secret scan with mask_secrets."""
from collections.abc import Mapping
from dataclasses import dataclass, field


@dataclass(frozen=True)
class OutputResult:
    text: str
    links_removed: int = 0
    images_removed: int = 0
    secrets: Mapping[str, int] = field(default_factory=dict)  # kind -> count of the second secret scan


def clean_answer(text: str) -> OutputResult:
    """The answer with every external link and image replaced by "link removed" and its secrets masked."""
    # Skeleton (S3-01). Body: Boran, Mon-Tue 9-10 Nov (S3-03).
    return OutputResult(text=text)
