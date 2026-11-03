"""Limit of the events written for /api/ask without a session (S2-04): at most 30 per IP in 15 minutes.

That endpoint is open to anyone, so without a limit anyone could fill the audit table. Only the event is limited,
never the 401 answer. Pure logic: no database, network or clock (the caller gives the time). Kept in memory, so a
server restart resets it and every server process has its own counter. Requests run in separate threads: a lock guards it.
"""
import threading
from collections import deque
from dataclasses import dataclass
from datetime import datetime, timedelta

from ..accounts.login_limit import forget_old

WINDOW = timedelta(minutes=15)
IP_LIMIT = 30


@dataclass(frozen=True)
class EventPermit:
    allowed: bool
    skipped: int  # events of this IP skipped so far in the window; 0 if allowed


class UnauthenticatedEventLimiter:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._by_ip: dict[str, deque[datetime]] = {}
        self._skipped: dict[str, int] = {}

    def allow(self, ip: str, now: datetime) -> EventPermit:
        """Under the limit: counts the event and allows it. Otherwise counts it as skipped."""
        with self._lock:
            forget_old(self._by_ip, now, WINDOW)
            self._skipped = {key: count for key, count in self._skipped.items() if key in self._by_ip}
            events = self._by_ip.setdefault(ip, deque())
            if len(events) < IP_LIMIT:
                events.append(now)
                self._skipped.pop(ip, None)
                return EventPermit(allowed=True, skipped=0)
            self._skipped[ip] = self._skipped.get(ip, 0) + 1
            return EventPermit(allowed=False, skipped=self._skipped[ip])

    def reset(self) -> None:
        with self._lock:
            self._by_ip.clear()
            self._skipped.clear()


unauthenticated_event_limiter = UnauthenticatedEventLimiter()


def reset_unauthenticated_events() -> None:
    unauthenticated_event_limiter.reset()
