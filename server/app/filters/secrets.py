"""Secret rules (S3-09): the S1-11 catalog (S1-S14) as code; S15 (an unlabelled random string) is weak, never returned.

Certain: a known prefix or structure, and an .env line (product decision N5: a pasted .env secret also alarms).
Suspicious: a name and a value outside an .env line (aws_secret_access_key = ...).
Only the value is a span: "DB_PASSWORD=[REDACTED]", "postgres://user:[REDACTED]@host".
A value that is already [REDACTED] is never found again.
"""
import re

from .types import Span

REDACTED = "[REDACTED]"

# A token is not part of a longer word: no letter, digit, "_" or "-" right before or after it.
_BEFORE = r"(?<![A-Za-z0-9_\-])"
_AFTER = r"(?![A-Za-z0-9_\-])"

# Every repeat has an upper bound, so a long or crafted message cannot make a rule slow (no catastrophic backtracking).

# (kind, pattern): the whole match is the secret; all certain.
_CERTAIN_TOKENS = [
    ("slack_token", re.compile(
        _BEFORE + r"(?:xoxe\.)?xapp-\d{1,3}-[A-Za-z0-9]{1,64}-\d{1,32}-[A-Za-z0-9]{1,256}" + _AFTER)),
    ("slack_token", re.compile(_BEFORE + r"xox[abposre]-\d{1,32}(?:-\d{1,32}){0,4}-[A-Za-z0-9]{1,256}" + _AFTER)),
    ("github_token", re.compile(_BEFORE + r"gh[pousr]_[A-Za-z0-9]{36}" + _AFTER)),
    ("github_token", re.compile(_BEFORE + r"github_pat_[A-Za-z0-9_]{82}" + _AFTER)),
    ("aws_key", re.compile(_BEFORE + r"(?:AKIA|ASIA)[A-Z0-9]{16}" + _AFTER)),
    ("google_key", re.compile(_BEFORE + r"AIza[0-9A-Za-z_\-]{35}" + _AFTER)),
    ("openai_key", re.compile(
        _BEFORE + r"sk-(?:(?:proj|svcacct|admin)-)?[A-Za-z0-9_\-]{20,256}T3BlbkFJ[A-Za-z0-9_\-]{20,256}" + _AFTER)),
    # A project, service account or admin key is certain also without the T3BlbkFJ mark, if it is long enough
    # (at least 40 characters with the prefix). A plain "sk-..." still needs the mark (too many look-alikes).
    ("openai_key", re.compile(_BEFORE + r"sk-(?:proj|svcacct|admin)-[A-Za-z0-9_\-]{32,512}" + _AFTER)),
    ("anthropic_key", re.compile(_BEFORE + r"sk-ant-(?:api|admin)\d{2}-[A-Za-z0-9_\-]{80,256}" + _AFTER)),
    # A block without its END line (pasted only partly) is masked to the end of the text.
    ("private_key", re.compile(
        r"-----BEGIN [A-Z0-9 ]{0,40}PRIVATE KEY-----[\s\S]*?(?:-----END [A-Z0-9 ]{0,40}PRIVATE KEY-----|\Z)")),
    ("bearer_token", re.compile(
        _BEFORE + r"eyJ[A-Za-z0-9_\-]{8,4096}\.eyJ[A-Za-z0-9_\-]{8,4096}\.[A-Za-z0-9_\-]{0,4096}" + _AFTER)),
]

# (kind, confidence, pattern): group "value" is the secret.
_VALUE_RULES = [
    ("bearer_token", "certain", re.compile(
        r"\bBearer[ \t]{1,8}(?P<value>[A-Za-z0-9._~+/\-]{20,4096}={0,2})", re.IGNORECASE)),
    # Only the password of an address: scheme://user:password@host.
    ("db_password", "certain", re.compile(
        r"(?<![A-Za-z0-9+.\-])[A-Za-z][A-Za-z0-9+.\-]{0,31}://[^\s:/@]{1,256}:(?P<value>[^\s@/]{1,256})@")),
    ("aws_key", "suspicious", re.compile(
        r"aws_secret_access_key[\"']?[ \t]{0,8}[=:][ \t]{0,8}[\"']?(?P<value>[A-Za-z0-9/+]{40})(?![A-Za-z0-9/+])",
        re.IGNORECASE)),
]

# An .env line: NAME=value. The name (upper case, as in .env) is checked for a secret word in code, not in the pattern.
_ENV_LINE = re.compile(
    r"(?<![A-Za-z0-9_])(?P<name>[A-Z0-9_]{1,128})[ \t]{0,8}[=:][ \t]{0,8}"
    r"(?:\"(?P<dq>[^\"\n]{1,1024})\"|'(?P<sq>[^'\n]{1,1024})'|(?P<bare>[^\s\"']{1,1024}))"
)
_SECRET_WORDS = ("KEY", "TOKEN", "SECRET", "PASSWORD", "PASSWD", "PASS", "PWD")
# Names of settings, not secrets: PASSWORD_MIN_LENGTH=8, TOKEN_URL=https://..., SSH_KEY_PATH=...
_SETTING_NAME_ENDINGS = (
    "_URL", "_URI", "_PATH", "_FILE", "_DIR", "_HOST", "_PORT", "_ID", "_NAME", "_ENDPOINT",
    "_LENGTH", "_LEN", "_MIN", "_MAX", "_COUNT", "_SIZE", "_LIMIT", "_TIMEOUT", "_TTL", "_SECONDS",
    "_MINUTES", "_HOURS", "_DAYS", "_ATTEMPTS", "_ENABLED", "_REQUIRED", "_HEADER", "_TYPE",
)
_NOT_A_SECRET_VALUE = re.compile(r"(?i)(?:true|false|yes|no|none|null|nil|\$\{?[A-Z0-9_]+\}?)")
_PLAIN_URL = re.compile(r"(?i)[a-z][a-z0-9+.\-]*://[^\s:@/]+(?:[/?#][^\s]*)?")


def _env_secrets(text: str) -> list[Span]:
    spans = []
    for match in _ENV_LINE.finditer(text):
        group = next(g for g in ("dq", "sq", "bare") if match.group(g) is not None)
        value = match.group(group)
        name = match.group("name")
        if (not any(word in name for word in _SECRET_WORDS) or name.endswith(_SETTING_NAME_ENDINGS)
                or REDACTED in value
                or _NOT_A_SECRET_VALUE.fullmatch(value) or _PLAIN_URL.fullmatch(value)):
            continue
        spans.append(Span(match.start(group), match.end(group), "env_secret", "certain"))
    return spans


def find_secrets(text: str) -> list[Span]:
    """The secrets in a normalized text, possibly overlapping (the caller resolves overlaps). Never a weak finding."""
    spans = []
    for kind, pattern in _CERTAIN_TOKENS:
        spans.extend(Span(m.start(), m.end(), kind, "certain") for m in pattern.finditer(text))
    for kind, confidence, pattern in _VALUE_RULES:
        for m in pattern.finditer(text):
            if m.group("value") != REDACTED:
                spans.append(Span(m.start("value"), m.end("value"), kind, confidence))
    spans.extend(_env_secrets(text))
    return [s for s in spans if REDACTED not in text[s.start:s.end]]
