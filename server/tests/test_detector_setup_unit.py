"""Synthetic readiness checks; no local model or optional libraries needed."""
import logging

import pytest
from fastapi.testclient import TestClient

from app import main
from app.filters import detector_check, injection


@pytest.mark.parametrize("ready,code,line", [
    (True, 0, "detector ready\n"),
    (False, 1, "detector not available\n"),
])
def test_check_exact_output(monkeypatch, capsys, ready, code, line):
    calls = []

    def warm_up():
        calls.append(True)
        return ready

    monkeypatch.setattr(injection, "warm_up", warm_up)
    assert detector_check.main() == code
    assert calls == [True]
    assert capsys.readouterr() == (line, "")


def test_loader_diagnostics_are_hidden_and_logger_restored(monkeypatch, capsys, caplog):
    previous = injection.logger.disabled

    def broken():
        print("private loader diagnostic")
        injection.logger.warning("private loader diagnostic")
        raise RuntimeError("private loader diagnostic")

    monkeypatch.setattr(injection, "warm_up", broken)
    assert detector_check.main() == 1
    assert capsys.readouterr() == ("detector not available\n", "")
    assert "private loader diagnostic" not in caplog.text
    assert injection.logger.disabled is previous


@pytest.mark.parametrize("outcome", [True, False, RuntimeError("private diagnostic")])
def test_each_startup_checks_once_and_health_stays_open(monkeypatch, caplog, outcome):
    calls = []

    def warm_up():
        calls.append(True)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome

    monkeypatch.setattr(injection, "warm_up", warm_up)
    with caplog.at_level(logging.INFO, logger="agentstack"):
        for _ in range(2):
            with TestClient(main.app) as client:
                assert client.get("/health").json() == {"status": "up"}
    assert calls == [True, True]
    expected = "detector ready" if outcome is True else "detector not available"
    assert [r.getMessage() for r in caplog.records if r.name == "agentstack"] == [expected, expected]
