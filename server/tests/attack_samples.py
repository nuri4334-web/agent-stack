"""S3-02b: shared values and helpers of the secret and personal-data attack tests (no tests in this file).

Every value here is made up: secrets contain EXAMPLE and the mark S302B, in the length and character set of the real format
(otherwise a rule could not catch them and the test would mean nothing). Personal data has a correct checksum but
belongs to nobody. Nothing is copied from demo-data/.

Values must never appear in test output: tests compute a bool first (`leaked = value in text`) and assert the bool
with a message that names only the kind.
"""
import re
import sqlite3
from dataclasses import dataclass

ASK = "/api/ask"
EVENTS = "/api/admin/events?limit=100"
REDACTED = "[REDACTED]"
DEV_CHANNEL_ID = "C0C83M051QD"  # #dev of the demo seed (tests/conftest.py TEST_ALLOWED_CHANNELS)

# Placeholders of the Vault (API contract v4, section 0).
PLACEHOLDER = re.compile(r"\b(?:EMAIL|PHONE|TCKN|IBAN|CARD|PERSON)_\d+\b")


# --- Checksum generators -------------------------------------------------------------------------------------

def tckn(prefix9: str) -> str:
    """A TC identity number from 9 digits: d10 = ((d1+d3+d5+d7+d9)*7 - (d2+d4+d6+d8)) mod 10, d11 = sum(d1..d10) mod 10."""
    digits = [int(c) for c in prefix9]
    if len(digits) != 9 or digits[0] == 0:
        raise ValueError("tckn needs 9 digits, the first not 0")
    d10 = (sum(digits[0:9:2]) * 7 - sum(digits[1:8:2])) % 10
    d11 = (sum(digits) + d10) % 10
    return prefix9 + str(d10) + str(d11)


def tckn_is_valid(value: str) -> bool:
    return len(value) == 11 and value.isdigit() and value[0] != "0" and tckn(value[:9]) == value


def _iban_number(text: str) -> int:
    return int("".join(str(int(c, 36)) for c in text))


def iban_tr(bban: str) -> str:
    """A Turkish IBAN (26 characters) from 22 digits: ISO 13616 check digits = 98 - (bban + "TR00" as number) mod 97."""
    if len(bban) != 22 or not bban.isdigit():
        raise ValueError("iban_tr needs 22 digits")
    check = 98 - _iban_number(bban + "TR00") % 97
    return f"TR{check:02d}{bban}"


def iban_is_valid(value: str) -> bool:
    return len(value) == 26 and _iban_number(value[4:] + value[:4]) % 97 == 1


def luhn(payload: str) -> str:
    """The payload with its Luhn check digit appended."""
    total = 0
    for i, c in enumerate(reversed(payload)):
        d = int(c)
        if i % 2 == 0:  # these digits are doubled once the check digit is appended
            d = d * 2 - 9 if d > 4 else d * 2
        total += d
    return payload + str((10 - total % 10) % 10)


def luhn_is_valid(value: str) -> bool:
    return value.isdigit() and luhn(value[:-1]) == value


# --- Secret samples (one per kind of types.SECRET_KINDS) -------------------------------------------------------

@dataclass(frozen=True)
class Sample:
    kind: str
    text: str  # how the value is written (with its key name or prefix)
    values: tuple[str, ...]  # the parts that must never be left: any of them in a text = leaked

    def leaked_in(self, text: str) -> bool:
        return any(v in text for v in self.values)


# Every secret value contains "EXAMPLE" and this task's own mark "S302B", has at most 4 equal characters in a row,
# and keeps the prefix, length and character set of the real format.
MARK = "S302BEXAMPLE"
# Mixed letters and digits without a repeated character (alphanumeric, so valid in every format below).
_MIX = "q7Rt3Kz9Lm2Wx5Vb8Np4Hs6Jd1Fc0Ya"


def _mixed(length: int, start: int = 0) -> str:
    """`length` characters of _MIX, starting at `start` and wrapping around."""
    return (_MIX * (length // len(_MIX) + 2))[start:start + length]


# xoxb- + 12 digits + "-" + 13 digits + "-" + 24 letters/digits
SLACK_TOKEN = "xoxb-302418765093-4718203956172-" + MARK + "x7Kq9Lm2Rt4W"
# ghp_ + 36 letters/digits
GITHUB_TOKEN = "ghp_" + MARK + "aZ3kP9qR7mT2wX5vB8nC4dF6"
# AKIA + 16 upper-case letters/digits
AWS_KEY = "AKIA" + MARK + "Q7ZK"
# AIza + 35 of [A-Za-z0-9_-]
GOOGLE_KEY = "AIza" + "Sy" + MARK + "q4Rt8-Vz2Kp_7mWx3LbN9"
# sk-proj- + 48 letters/digits
OPENAI_KEY = "sk-proj-" + MARK + "Tq7Lm3Xz9Rb2Kw5Nv8Pd4Hs6Jc1Fg0Ya7Ue3"
# sk-ant-api03- + 93 characters ending in AA
ANTHROPIC_KEY = "sk-ant-api03-" + MARK + _mixed(79, 5) + "AA"
# Base64 lines of 64 characters; the last line is shorter and padded.
PRIVATE_KEY_BODY = (
    "MIIEpAIBAAKCAQEA" + MARK + _mixed(36, 3),
    MARK + _mixed(52, 11),
    MARK + _mixed(20, 17) + "==",
)
PRIVATE_KEY = (
    "-----BEGIN RSA PRIVATE KEY-----\n" + "\n".join(PRIVATE_KEY_BODY) + "\n-----END RSA PRIVATE KEY-----"
)
ENV_SECRET_VALUE = MARK + "-jwt-" + _mixed(24, 7)
DB_PASSWORD = MARK + "pw7Rt3Kz"
# At least 40 characters.
BEARER_TOKEN = MARK + "q7Rt3Kz9Lm2Wx5Vb8Np4Hs6Jd1Fc0Ya7Ue3"
# 40 characters with "/" and "+", like a cloud secret access key.
AWS_SECRET_VALUE = MARK + "/q7Rt3Kz9Lm2W+x5Vb8Np4Hs6Jd1"

SECRET_SAMPLES = {
    "slack_token": Sample("slack_token", SLACK_TOKEN, (SLACK_TOKEN,)),
    "github_token": Sample("github_token", GITHUB_TOKEN, (GITHUB_TOKEN,)),
    "aws_key": Sample("aws_key", AWS_KEY, (AWS_KEY,)),
    "google_key": Sample("google_key", GOOGLE_KEY, (GOOGLE_KEY,)),
    "openai_key": Sample("openai_key", OPENAI_KEY, (OPENAI_KEY,)),
    "anthropic_key": Sample("anthropic_key", ANTHROPIC_KEY, (ANTHROPIC_KEY,)),
    "private_key": Sample("private_key", PRIVATE_KEY, PRIVATE_KEY_BODY),
    "env_secret": Sample("env_secret", f"JWT_SECRET={ENV_SECRET_VALUE}", (ENV_SECRET_VALUE,)),
    "db_password": Sample(
        "db_password", f"DATABASE_URL=postgres://app:{DB_PASSWORD}@db.internal:5432/app", (DB_PASSWORD,),
    ),
    "bearer_token": Sample("bearer_token", f"Authorization: Bearer {BEARER_TOKEN}", (BEARER_TOKEN,)),
}

ALL_SECRET_VALUES = tuple(v for s in SECRET_SAMPLES.values() for v in s.values) + (AWS_SECRET_VALUE,)


# --- Personal data samples ------------------------------------------------------------------------------------

EMAIL = "test.user@example.com"  # example.com is reserved for documentation
PHONE_INTL = "+90 555 000 00 00"
PHONE_LOCAL = "0555 000 00 00"
TCKN = tckn("100000000")  # mostly zeros, so no real person is expected
IBAN = iban_tr("00000" + "0" + "0" * 15 + "1")  # bank code 00000: no real bank
CARD = luhn("400000000000000")

# case id -> (value, placeholder prefix)
PERSONAL_SAMPLES = {
    "email": (EMAIL, "EMAIL"),
    "phone_intl": (PHONE_INTL, "PHONE"),
    "phone_local": (PHONE_LOCAL, "PHONE"),
    "iban": (IBAN, "IBAN"),
    "tckn": (TCKN, "TCKN"),
    "card": (CARD, "CARD"),
}


# --- The test's own observer of raw secret shapes (not a filter rule; app/ never uses it) -----------------------

RAW_SECRET_SHAPES = {
    "slack_token": re.compile(r"xox[abprs]-[A-Za-z0-9-]{10,}"),
    "github_token": re.compile(r"gh[pousr]_[A-Za-z0-9]{20,}"),
    "github_pat": re.compile(r"github_pat_[A-Za-z0-9_]{20,}"),
    "aws_key": re.compile(r"AKIA[0-9A-Z]{16}"),
    "google_key": re.compile(r"AIza[0-9A-Za-z_-]{30,}"),
    "sk_key": re.compile(r"sk-(?:proj-|ant-)?[A-Za-z0-9_-]{20,}"),
    "private_key": re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
    "url_password": re.compile(r"[a-z][a-z0-9+.-]*://[^:\s/@]+:(?!\[REDACTED\]@)[^@\s]+@"),
    "bearer_token": re.compile(r"Bearer\s+[A-Za-z0-9._~+/-]{20,}"),
}


def raw_shapes_in(text: str) -> list[str]:
    """Names (never matches) of the raw secret shapes in the text, plus "sample" if one of our own values is in it."""
    found = [name for name, pattern in RAW_SECRET_SHAPES.items() if pattern.search(text)]
    if any(v in text for v in ALL_SECRET_VALUES):
        found.append("sample")
    return found


def db_text_cells(connection: sqlite3.Connection) -> list[str]:
    """Every text cell of every table of the database."""
    cells = []
    tables = [row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type = 'table'")]
    for table in tables:
        for row in connection.execute(f'SELECT * FROM "{table}"'):
            cells.extend(cell for cell in row if isinstance(cell, str))
    return cells


# --- HTTP helpers -------------------------------------------------------------------------------------------

def ask(client, question: str):
    return client.post(ASK, json={"question": question})


def event_row(admin_client, request_id: str, step: str) -> tuple[dict | None, str]:
    """The event row of one step of a request, and the whole event list as text (for the "no value" checks)."""
    r = admin_client.get(EVENTS)
    assert r.status_code == 200, "admin could not read the event list"
    rows = [e for e in r.json()["events"] if e["request_id"] == request_id and e["step"] == step]
    return (rows[0] if rows else None), r.text


def question_part(data: str) -> str:
    """The question part of a data text sent to the AI (format of gateway.ask_ai: "User question: ..." first)."""
    rest = data.split("User question: ", 1)[-1]
    return rest.split("\n\nRelevant messages:", 1)[0]
