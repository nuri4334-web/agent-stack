"""S2-03: the login attempt limit (pure logic; the time is a parameter)."""
import threading
from datetime import datetime, timedelta, timezone

from app.accounts.login_limit import IP_LIMIT, USERNAME_LIMIT, WINDOW, LoginLimiter, login_limiter, reset_login_attempts

NOW = datetime(2026, 11, 2, 9, 0, tzinfo=timezone.utc)


def _fail(limiter, count, *, username="ali", ip="1.1.1.1", at=NOW):
    for _ in range(count):
        assert limiter.claim(username, ip, at).retry_after is None


def test_limits_are_the_contract_values():
    assert (USERNAME_LIMIT, IP_LIMIT, WINDOW) == (5, 30, timedelta(minutes=15))


def test_five_failures_allowed_sixth_limited():
    limiter = LoginLimiter()
    _fail(limiter, 5)
    assert limiter.claim("ali", "1.1.1.1", NOW).retry_after == 900


def test_username_limit_is_per_username_and_any_ip():
    limiter = LoginLimiter()
    for number in range(5):
        _fail(limiter, 1, ip=f"1.1.1.{number}")
    assert limiter.claim("ali", "2.2.2.2", NOW).retry_after == 900
    assert limiter.claim("ayse", "2.2.2.2", NOW).retry_after is None


def test_ip_limit_thirty_failures_thirty_first_limited():
    limiter = LoginLimiter()
    for number in range(30):
        _fail(limiter, 1, username=f"user{number}")
    assert limiter.claim("other", "1.1.1.1", NOW).retry_after == 900
    assert limiter.claim("other", "2.2.2.2", NOW).retry_after is None


def test_sliding_window_oldest_failure_expires():
    limiter = LoginLimiter()
    _fail(limiter, 1, at=NOW)
    _fail(limiter, 4, at=NOW + timedelta(minutes=5))
    # One second before the oldest failure leaves the window: still closed.
    just_before = NOW + WINDOW - timedelta(seconds=1)
    assert limiter.claim("ali", "1.1.1.1", just_before).retry_after == 1
    # The moment it leaves, exactly one place opens.
    _fail(limiter, 1, at=NOW + WINDOW)
    assert limiter.claim("ali", "1.1.1.1", NOW + WINDOW).retry_after == 300


def test_retry_after_is_whole_seconds_rounded_up():
    limiter = LoginLimiter()
    _fail(limiter, 5)
    assert limiter.claim("ali", "1.1.1.1", NOW + timedelta(seconds=10.5)).retry_after == 890
    almost = NOW + WINDOW - timedelta(milliseconds=1)
    assert limiter.claim("ali", "1.1.1.1", almost).retry_after == 1


def test_retry_after_uses_larger_when_both_full():
    limiter = LoginLimiter()
    for number in range(29):
        _fail(limiter, 1, username=f"user{number}", at=NOW)
    _fail(limiter, 1, username="ali", at=NOW)
    later = NOW + timedelta(minutes=10)
    for number in range(5):
        _fail(limiter, 1, username="ayse", ip=f"2.2.2.{number}", at=later)
    # The IP opens in 5 minutes, the user name in 15: the next attempt is accepted after the larger one.
    assert limiter.claim("ayse", "1.1.1.1", later).retry_after == 900


def test_limited_attempt_is_not_counted():
    limiter = LoginLimiter()
    _fail(limiter, 5)
    for minute in range(1, 15):
        assert limiter.claim("ali", "1.1.1.1", NOW + timedelta(minutes=minute)).retry_after is not None
    # Attempts over the limit did not lengthen the window.
    assert limiter.claim("ali", "1.1.1.1", NOW + WINDOW).retry_after is None


def test_success_clears_username_keeps_ip():
    limiter = LoginLimiter()
    for _ in range(4):
        limiter.claim("ali", "1.1.1.1", NOW)
    limiter.succeeded("ali", "1.1.1.1", limiter.claim("ali", "1.1.1.1", NOW))
    # Five more failures fit for the user name again.
    _fail(limiter, 5)
    assert limiter.claim("ali", "1.1.1.1", NOW).retry_after is not None
    # The IP keeps its 4 + 5 failures, the successful attempt is not one of them: 21 more fit.
    for number in range(21):
        _fail(limiter, 1, username=f"user{number}")
    assert limiter.claim("other", "1.1.1.1", NOW).retry_after is not None


def test_cancel_does_not_count_attempt():
    limiter = LoginLimiter()
    _fail(limiter, 4)
    limiter.cancel("ali", "1.1.1.1", limiter.claim("ali", "1.1.1.1", NOW))
    _fail(limiter, 1)
    assert limiter.claim("ali", "1.1.1.1", NOW).retry_after is not None


def test_cancel_after_success_of_parallel_login_does_nothing():
    limiter = LoginLimiter()
    first = limiter.claim("ali", "1.1.1.1", NOW)
    second = limiter.claim("ali", "1.1.1.1", NOW)
    limiter.succeeded("ali", "1.1.1.1", first)
    limiter.cancel("ali", "1.1.1.1", second)
    limiter.cancel("ali", "1.1.1.1", second)
    assert limiter._by_username == {} and limiter._by_ip == {}


def test_parallel_claims_never_exceed_limit():
    limiter = LoginLimiter()
    results = []
    start = threading.Barrier(50)

    def attempt():
        start.wait()
        results.append(limiter.claim("ali", "1.1.1.1", NOW).retry_after)

    threads = [threading.Thread(target=attempt) for _ in range(50)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert len(results) == 50
    assert results.count(None) == 5


def test_empty_keys_are_removed():
    limiter = LoginLimiter()
    _fail(limiter, 2)
    _fail(limiter, 1, username="ayse", ip="2.2.2.2", at=NOW + WINDOW)
    assert set(limiter._by_username) == {"ayse"}
    assert set(limiter._by_ip) == {"2.2.2.2"}


def test_reset_clears_everything():
    limiter = LoginLimiter()
    _fail(limiter, 5)
    limiter.reset()
    assert limiter.claim("ali", "1.1.1.1", NOW).retry_after is None


def test_reset_login_attempts_clears_the_shared_limiter():
    _fail(login_limiter, 5)
    reset_login_attempts()
    assert login_limiter.claim("ali", "1.1.1.1", NOW).retry_after is None
