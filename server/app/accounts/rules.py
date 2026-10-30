"""Account rules (S2-02): pure functions; use no database, network or clock.

A password and a session token are never stored as plain text: a password as a salted scrypt hash,
a session token as its SHA-256 hash. Error texts never contain a password, a hash or a token.
"""
import hashlib
import hmac
import re
import secrets
import unicodedata
from datetime import datetime, timedelta

# The same limits as the login request in the API contract (5. Login). Checked only when a password is set.
PASSWORD_MIN_LENGTH = 12
PASSWORD_MAX_LENGTH = 128

# scrypt parameters for new hashes (OWASP minimum: N=2^14, r=8, p=5). Never lowered, not even for tests.
SCRYPT_N = 2**14
SCRYPT_R = 8
SCRYPT_P = 5
SCRYPT_DKLEN = 32
SALT_BYTES = 16
HASH_SCHEME = "scrypt"

# Limits for parameters read back from a stored hash (a stored hash may not ask for unlimited work or memory).
_STORED_N = frozenset(2**k for k in range(14, 18))
_STORED_R = range(1, 9)
_STORED_P = range(1, 17)
_STORED_SALT_BYTES = range(16, 65)
_STORED_DKLEN = range(32, 65)
# Enough for n = 2**17 and r = 8 (128 MiB) with room for OpenSSL's own use.
_SCRYPT_MAXMEM = 2**28

# A missing or broken hash is "checked" against this salt, so it takes as long as a real check.
_DUMMY_SALT = bytes(SALT_BYTES)

USERNAME_PATTERN = re.compile(r"[a-z0-9][a-z0-9._-]{2,31}", re.ASCII)
# Slack user id: "U..." or "W..." (Enterprise Grid), upper case letters and digits.
SLACK_USER_ID_PATTERN = re.compile(r"[UW][A-Z0-9]{2,31}", re.ASCII)
NAME_MAX_LENGTH = 100

# A session lasts at most 8 hours from login (absolute; API contract 2. Session and cookie).
SESSION_LIFETIME = timedelta(hours=8)


def _normalize_password(password: str) -> str:
    return unicodedata.normalize("NFC", password)


def password_problem(password: str) -> str | None:
    """Why the password cannot be set, or None. Only for setting a password, never at login."""
    length = len(_normalize_password(password))
    if length < PASSWORD_MIN_LENGTH:
        return f"Password must be at least {PASSWORD_MIN_LENGTH} characters."
    if length > PASSWORD_MAX_LENGTH:
        return f"Password must be at most {PASSWORD_MAX_LENGTH} characters."
    return None


def _scrypt(password: str, salt: bytes, n: int, r: int, p: int, dklen: int) -> bytes:
    return hashlib.scrypt(
        _normalize_password(password).encode("utf-8"), salt=salt, n=n, r=r, p=p, dklen=dklen,
        maxmem=_SCRYPT_MAXMEM,
    )


def hash_password(password: str) -> str:
    """A new salted hash as one text: "scrypt$<n>$<r>$<p>$<salt hex>$<hash hex>". ValueError if the rule fails."""
    problem = password_problem(password)
    if problem:
        raise ValueError(problem)
    salt = secrets.token_bytes(SALT_BYTES)
    digest = _scrypt(password, salt, SCRYPT_N, SCRYPT_R, SCRYPT_P, SCRYPT_DKLEN)
    return f"{HASH_SCHEME}${SCRYPT_N}${SCRYPT_R}${SCRYPT_P}${salt.hex()}${digest.hex()}"


def _parse_hash(stored_hash: object) -> tuple[int, int, int, bytes, bytes] | None:
    if not isinstance(stored_hash, str):
        return None
    parts = stored_hash.split("$")
    if len(parts) != 6 or parts[0] != HASH_SCHEME:
        return None
    if not all(part.isascii() and part.isdigit() for part in parts[1:4]):
        return None
    n, r, p = (int(part) for part in parts[1:4])
    try:
        salt, digest = bytes.fromhex(parts[4]), bytes.fromhex(parts[5])
    except ValueError:
        return None
    if (n not in _STORED_N or r not in _STORED_R or p not in _STORED_P
            or len(salt) not in _STORED_SALT_BYTES or len(digest) not in _STORED_DKLEN):
        return None
    return n, r, p, salt, digest


def verify_password(stored_hash: str | None, password: str) -> bool:
    """True only if the password matches the stored hash.

    An empty, broken or unknown hash returns False after the same scrypt work as a real check,
    so "no such account" and "wrong password" take the same time. Never raises for a bad hash.
    """
    parsed = _parse_hash(stored_hash)
    if parsed is None:
        _scrypt(password, _DUMMY_SALT, SCRYPT_N, SCRYPT_R, SCRYPT_P, SCRYPT_DKLEN)
        return False
    n, r, p, salt, digest = parsed
    return hmac.compare_digest(_scrypt(password, salt, n, r, p, len(digest)), digest)


def normalize_username(value: str) -> str:
    """Strips spaces and converts to lower case (" Ali " -> "ali"); the same at account creation and at login."""
    return value.strip().lower()


def username_problem(username: str) -> str | None:
    """Why the (normalized) user name is not valid, or None."""
    if not USERNAME_PATTERN.fullmatch(username):
        return ("User name must be 3 to 32 characters: lower case letters a-z, digits, '.', '_' or '-', "
                "starting with a letter or digit.")
    return None


def name_problem(name: str) -> str | None:
    """Why the (stripped) display name is not valid, or None."""
    if not name:
        return "Name cannot be empty."
    if len(name) > NAME_MAX_LENGTH:
        return f"Name must be at most {NAME_MAX_LENGTH} characters."
    if any(unicodedata.category(c) == "Cc" for c in name):
        return "Name cannot contain control characters."
    return None


def is_slack_user_id(value: object) -> bool:
    """Is value a Slack user id (no spaces, no case conversion)."""
    return isinstance(value, str) and SLACK_USER_ID_PATTERN.fullmatch(value) is not None


def new_session_token() -> str:
    """A new random session token (32 random bytes, URL-safe text). Only its hash is stored."""
    return secrets.token_urlsafe(32)


def hash_session_token(token: str) -> str:
    """SHA-256 of the token as 64 lower case hex characters; this is what the sessions table keeps."""
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def session_expires_at(now: datetime) -> datetime:
    """End of a session that starts at now (now + 8 hours). now must have a time zone."""
    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("now must have a time zone.")
    return now + SESSION_LIFETIME
