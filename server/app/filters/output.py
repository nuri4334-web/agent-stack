"""Answer cleaning (S3-03): external links and images removed, second secret scan with mask_secrets."""
from collections.abc import Mapping
from dataclasses import dataclass, field
import re

from .api import mask_secrets
from .normalize import normalize

REMOVED_NOTE = "link removed"

_MD_URL_PART = r"\((?:[^()\s]|\([^()\s]*\))*\)"
_MD_IMAGE = re.compile(r"!\[[^\]]*\]" + _MD_URL_PART)
_HTML_IMG = re.compile(r"<img\b[^>]*>", re.IGNORECASE | re.DOTALL)
_HTML_LINK = re.compile(r"<a\b[^>]*>.*?</a>|<a\b[^>]*>", re.IGNORECASE | re.DOTALL)
_MD_LINK = re.compile(r"\[([^\[\]]*)\]" + _MD_URL_PART)
_BARE_URL = re.compile(
    r"(?:https?://|(?<![:\w/])//(?=[a-z0-9])|(?<![\w/@.])www\.)[^\s<>\"'\]]+",
    re.IGNORECASE,
)
_TRAILING_PUNCT = ".,;:!?"


@dataclass(frozen=True)
class OutputResult:
    text: str
    links_removed: int = 0
    images_removed: int = 0
    secrets: Mapping[str, int] = field(default_factory=dict)  # kind -> count of the second secret scan


def _split_trailing_punct(raw: str) -> tuple[str, str]:
    """Strips sentence punctuation and unbalanced closing parentheses from the end of a bare URL."""
    end = len(raw)
    while end > 0:
        last = raw[end - 1]
        if last in _TRAILING_PUNCT:
            end -= 1
        elif last == ")" and raw[:end].count(")") > raw[:end].count("("):
            end -= 1
        else:
            break
    return raw[:end], raw[end:]


def clean_answer(text: str) -> OutputResult:
    """The answer with every external link and image replaced by "link removed" and its secrets masked."""
    cleaned = normalize(text)
    images_removed = 0
    links_removed = 0

    def _replace_image(_match: re.Match[str]) -> str:
        nonlocal images_removed
        images_removed += 1
        return REMOVED_NOTE

    def _replace_html_link(_match: re.Match[str]) -> str:
        nonlocal links_removed
        links_removed += 1
        return REMOVED_NOTE

    def _replace_md_link(match: re.Match[str]) -> str:
        nonlocal links_removed
        links_removed += 1
        label = match.group(1).strip()
        if not label or _BARE_URL.fullmatch(label):
            return REMOVED_NOTE
        label = _BARE_URL.sub(REMOVED_NOTE, label)
        return f"{label} ({REMOVED_NOTE})"

    def _replace_bare_url(match: re.Match[str]) -> str:
        nonlocal links_removed
        links_removed += 1
        _, suffix = _split_trailing_punct(match.group(0))
        return f"{REMOVED_NOTE}{suffix}"

    cleaned = _MD_IMAGE.sub(_replace_image, cleaned)
    cleaned = _HTML_IMG.sub(_replace_image, cleaned)
    cleaned = _HTML_LINK.sub(_replace_html_link, cleaned)
    cleaned = _MD_LINK.sub(_replace_md_link, cleaned)
    cleaned = _BARE_URL.sub(_replace_bare_url, cleaned)

    secret_scan = mask_secrets(cleaned)
    return OutputResult(
        text=secret_scan.text,
        links_removed=links_removed,
        images_removed=images_removed,
        secrets=dict(secret_scan.counts),
    )
