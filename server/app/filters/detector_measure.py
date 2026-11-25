"""Measure local detector decisions without printing example text."""
import io
import json
import logging
import math
import re
import sys
from contextlib import redirect_stderr, redirect_stdout

from . import injection
from .detector_check import is_ready
from .normalize import normalize

_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}", re.ASCII)


def _valid_id(value) -> bool:
    return (type(value) is int and value >= 0) or (isinstance(value, str) and _ID.fullmatch(value) is not None)


def main(argv=None) -> int:
    args = sys.argv[1:] if argv is None else argv
    if len(args) != 1:
        print("input not available")
        return 2
    rows = []
    try:
        with open(args[0], "rb") as source:
            for number, line in enumerate(source, 1):
                try:
                    row = json.loads(line.decode("utf-8"))
                    if (not isinstance(row, dict) or not _valid_id(row.get("id"))
                            or not isinstance(row.get("text"), str)
                            or row.get("label") not in ("injection", "safe")):
                        raise ValueError
                except (ValueError, TypeError, UnicodeError, RecursionError):
                    print(f"invalid input at line {number}")
                    return 2
                rows.append(row)
    except OSError:
        print("input not available")
        return 2
    if not is_ready():
        print("detector not available")
        return 1
    stats = {"total": len(rows), "true_positives": 0, "false_positives": 0,
             "false_negatives": 0, "false_positive_ids": [], "false_negative_ids": []}
    detector_log = logging.getLogger(injection.__name__)
    was_disabled = detector_log.disabled
    try:
        detector_log.disabled = True
        with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
            for row in rows:
                result = injection.detect(row["text"])
                score = result.score
                empty_safe = (not normalize(row["text"]).strip() and result.suspicious is False
                              and score == injection.NO_SCORE)
                if (type(result.suspicious) is not bool or type(score) not in (float, int)
                        or not math.isfinite(score) or (not 0 <= score <= 1 and not empty_safe)):
                    raise ValueError
                if result.suspicious and row["label"] == "injection":
                    stats["true_positives"] += 1
                elif result.suspicious:
                    stats["false_positives"] += 1
                    stats["false_positive_ids"].append(row["id"])
                elif row["label"] == "injection":
                    stats["false_negatives"] += 1
                    stats["false_negative_ids"].append(row["id"])
    except Exception:
        print("detector not available")
        return 1
    finally:
        detector_log.disabled = was_disabled
    print(json.dumps(stats))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
