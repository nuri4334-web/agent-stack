"""Check local detector readiness without exposing loader diagnostics."""
import io
import logging
from contextlib import redirect_stderr, redirect_stdout

from . import injection


def is_ready() -> bool:
    """Call warm_up once, retaining only its readiness result."""
    detector_log = logging.getLogger(injection.__name__)
    was_disabled = detector_log.disabled
    try:
        detector_log.disabled = True
        with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
            try:
                return injection.warm_up() is True
            except Exception:
                return False
    finally:
        detector_log.disabled = was_disabled


def main() -> int:
    ready = is_ready()
    print("detector ready" if ready else "detector not available")
    return 0 if ready else 1


if __name__ == "__main__":
    raise SystemExit(main())
