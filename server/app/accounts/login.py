"""Login and logout flow (S2-03; API contract 5 and 6). No web framework here; the time comes from the caller.

The user name, the password, the token and its hash are never written to the audit log or the server log.
"""
import logging
import sqlite3
import time
import uuid
from dataclasses import dataclass
from datetime import datetime

from ..audit.log import write_event
from .login_limit import LoginLimiter, login_limiter
from .rules import (
    SignedInPerson, new_session_token, normalize_username, username_problem, verify_password,
)
from .sessions import create_session, delete_session, find_login_account, resolve_session

log = logging.getLogger("agentstack")


@dataclass(frozen=True)
class LoginResult:
    person: SignedInPerson | None = None
    token: str | None = None
    retry_after: int | None = None  # person None and retry_after None: INVALID_CREDENTIALS


def attempt_login(
    connection: sqlite3.Connection,
    username: str,
    password: str,
    ip: str,
    now: datetime,
    limiter: LoginLimiter = login_limiter,
) -> LoginResult:
    """Every failure looks the same from outside: scrypt runs exactly once, whatever the reason.

    A temporary failure (an exception) gives the attempt back, so it does not count against the limit.
    """
    start = time.perf_counter()
    name = normalize_username(username)
    claim = limiter.claim(name, ip, now)
    person_id = None
    try:
        account = None if username_problem(name) else find_login_account(connection, name)
        person_id = account["id"] if account else None
        if claim.retry_after is not None:
            _write_login_failure(connection, now, start, "TOO_MANY_ATTEMPTS", person_id)
            return LoginResult(retry_after=claim.retry_after)
        verified = verify_password(account["password_hash"] if account else None, password)
        person = token = None
        if verified and account and account["is_active"]:
            token = new_session_token()
            create_session(connection, account["id"], token, now)
            person = resolve_session(connection, token, now)
    except Exception:
        if claim.retry_after is None:
            limiter.cancel(name, ip, claim)
        raise
    if person is None:
        _write_login_failure(connection, now, start, "INVALID_CREDENTIALS", person_id)
        return LoginResult()
    limiter.succeeded(name, ip, claim)
    _write_auth_event(
        connection, step="login", decision="passed", now=now, duration_ms=_elapsed_ms(start), person_id=person.id,
    )
    return LoginResult(person=person, token=token)


def end_session(connection: sqlite3.Connection, token: str, now: datetime) -> None:
    """Deletes the session. An event is written only if a session row was really deleted."""
    start = time.perf_counter()
    person_id = delete_session(connection, token)
    if person_id is not None:
        _write_auth_event(
            connection, step="logout", decision="passed", now=now, duration_ms=_elapsed_ms(start),
            person_id=person_id,
        )


def _write_login_failure(
    connection: sqlite3.Connection, now: datetime, start: float, reason_code: str, person_id: int | None,
) -> None:
    _write_auth_event(
        connection, step="login", decision="stopped", now=now, duration_ms=_elapsed_ms(start),
        reason_code=reason_code, person_id=person_id,
    )


def _write_auth_event(
    connection: sqlite3.Connection,
    *,
    step: str,
    decision: str,
    now: datetime,
    duration_ms: float,
    reason_code: str | None = None,
    person_id: int | None = None,
) -> None:
    """Writes one event (only codes and durations). If it cannot be written, the login still works; the error is logged."""
    request_id = uuid.uuid4().hex[:12]
    try:
        with connection:
            write_event(
                connection, created_at=now.isoformat(), request_id=request_id, step=step, decision=decision,
                duration_ms=duration_ms, reason_code=reason_code, person_id=person_id,
            )
    except Exception as error:
        log.error("Failed to write %s event (request %s): %s", step, request_id, type(error).__name__)


def _elapsed_ms(start: float) -> float:
    return round((time.perf_counter() - start) * 1000, 2)
