"""Login attempt limit (S2-03; API contract 5): at most 5 failed attempts per user name and 30 per IP in 15 minutes.

Pure logic: no database, network or clock (the caller gives the time). Kept in memory, so a server restart resets
it and every server process has its own counter. FastAPI requests run in separate threads, so a lock guards it.

An attempt reserves its place before the slow password check (claim), so parallel requests cannot pass the limit.
A wrong password leaves the reservation as a failed attempt; a temporary failure gives it back (cancel).
"""
import math
import threading
from collections import deque
from dataclasses import dataclass
from datetime import datetime, timedelta

WINDOW = timedelta(minutes=15)
USERNAME_LIMIT = 5
IP_LIMIT = 30


@dataclass(frozen=True)
class Claim:
    retry_after: int | None  # None: allowed, one attempt is reserved. Otherwise whole seconds until the next attempt.
    at: datetime


class LoginLimiter:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._by_username: dict[str, deque[datetime]] = {}
        self._by_ip: dict[str, deque[datetime]] = {}

    def claim(self, username: str, ip: str, now: datetime) -> Claim:
        """Over a limit: the seconds to wait (the attempt is not counted). Otherwise reserves one failed attempt."""
        with self._lock:
            _forget_old(self._by_username, now)
            _forget_old(self._by_ip, now)
            waits = [
                _seconds_until_free(attempts, limit, now)
                for attempts, limit in (
                    (self._by_username.get(username), USERNAME_LIMIT),
                    (self._by_ip.get(ip), IP_LIMIT),
                )
                if attempts is not None and len(attempts) >= limit
            ]
            if waits:
                return Claim(retry_after=max(waits), at=now)
            self._by_username.setdefault(username, deque()).append(now)
            self._by_ip.setdefault(ip, deque()).append(now)
            return Claim(retry_after=None, at=now)

    def cancel(self, username: str, ip: str, claim: Claim) -> None:
        """A temporary failure: the reserved attempt does not count."""
        with self._lock:
            _remove_one(self._by_username, username, claim.at)
            _remove_one(self._by_ip, ip, claim.at)

    def succeeded(self, username: str, ip: str, claim: Claim) -> None:
        """A successful login clears the failures of the user name; the failures of the IP stay."""
        with self._lock:
            self._by_username.pop(username, None)
            _remove_one(self._by_ip, ip, claim.at)

    def reset(self) -> None:
        with self._lock:
            self._by_username.clear()
            self._by_ip.clear()


def _forget_old(counters: dict[str, deque[datetime]], now: datetime) -> None:
    for key in list(counters):
        attempts = counters[key]
        while attempts and attempts[0] + WINDOW <= now:
            attempts.popleft()
        if not attempts:
            del counters[key]


def _seconds_until_free(attempts: deque[datetime], limit: int, now: datetime) -> int:
    # The attempt that must leave the window for a place to open.
    blocking = attempts[len(attempts) - limit]
    return max(1, math.ceil((blocking + WINDOW - now).total_seconds()))


def _remove_one(counters: dict[str, deque[datetime]], key: str, at: datetime) -> None:
    attempts = counters.get(key)
    if attempts is None:
        return
    try:
        attempts.remove(at)
    except ValueError:
        return
    if not attempts:
        del counters[key]


login_limiter = LoginLimiter()


def reset_login_attempts() -> None:
    login_limiter.reset()
