"""Independent Sprint 4 black-box acceptance tests; synthetic inputs only."""
import json
import logging
import runpy
import sys

import pytest

from app.filters import injection
from app.filters.names import find_names
from app.filters.normalize import normalize


class FakeClassifier:
    def predict(self, text):
        return [0.9 if text.startswith("flag") else 0.1]


@pytest.fixture(autouse=True)
def detector_isolation(monkeypatch):
    injection._reset_for_tests()
    monkeypatch.setattr(injection, "_loader", lambda: FakeClassifier())
    yield
    injection._reset_for_tests()


def cli(monkeypatch, capsys, module, *args):
    monkeypatch.setattr(sys, "argv", [module, *map(str, args)])
    try:
        runpy.run_module(module, run_name="__main__")
    except SystemExit as error:
        code = error.code
    else:
        code = 0
    out = capsys.readouterr()
    return code, out.out, out.err


def unavailable():
    raise RuntimeError("PRIVATE_MODEL_PATH_AND_TEXT")


@pytest.mark.parametrize("ready", [True, False])
def test_s4_04_k1_detector_check_exact_output(monkeypatch, capsys, ready):
    if not ready:
        monkeypatch.setattr(injection, "_loader", unavailable)
    code, out, err = cli(monkeypatch, capsys, "app.filters.detector_check")
    assert code == (0 if ready else 1)
    assert out == ("detector ready\n" if ready else "detector not available\n")
    assert err == ""


@pytest.mark.parametrize("ready", [True, False])
def test_s4_04_k1_warm_up_boolean_and_once(monkeypatch, ready):
    calls = []
    def load():
        calls.append(1)
        if not ready:
            unavailable()
        return FakeClassifier()
    monkeypatch.setattr(injection, "_loader", load)
    assert injection.warm_up() is ready
    assert injection.warm_up() is ready
    assert len(calls) == 1


@pytest.mark.parametrize("ready", [True, False])
def test_s4_04_k2_server_startup_warms_once_and_stays_healthy(monkeypatch, caplog, ready):
    from fastapi.testclient import TestClient
    from app.main import app
    calls = []
    def warm():
        calls.append(1)
        return ready
    monkeypatch.setattr(injection, "warm_up", warm)
    with caplog.at_level(logging.INFO):
        with TestClient(app) as client:
            assert client.get("/health").json() == {"status": "up"}
            assert client.get("/health").status_code == 200
    assert calls == [1]
    lines = [r.getMessage() for r in caplog.records
             if r.getMessage() in ("detector ready", "detector not available")]
    assert lines == ["detector ready" if ready else "detector not available"]


def test_s4_04_k3_missing_model_server_starts(monkeypatch, caplog):
    from fastapi.testclient import TestClient
    from app.main import app
    monkeypatch.setattr(injection, "_loader", unavailable)
    with caplog.at_level(logging.INFO):
        with TestClient(app) as client:
            assert client.get("/health").status_code == 200
    assert injection.warm_up() is False
    assert "PRIVATE_MODEL_PATH_AND_TEXT" not in caplog.text


@pytest.mark.parametrize(("text", "people", "expected"), [
    ("Deniz Aydın geldi.", ["Deniz Aydın"], ["Deniz Aydın"]),
    ("deniz kaya Can someone Ali", ["Deniz Aydın", "Ali Kaya", "Can Demir"], []),
    ("Ali Kaya'nın @Ali Kaya Alican Kaya", ["Ali Kaya"], ["Ali Kaya", "Ali Kaya"]),
    ("ALİ KAYA ve ali kaya", ["Ali Kaya"], ["ALİ KAYA", "ali kaya"]),
    ("Can geldi; Alican gelmedi.", ["Can"], ["Can"]),
    ("Deniz\n  Aydın ve Ali\t Kaya", ["Deniz Aydın", "Ali Kaya"],
     ["Deniz\n  Aydın", "Ali\t Kaya"]),
    ("Ali Kaya ve Ali Kaya", ["Ali Kaya", "Ali Kaya"], ["Ali Kaya", "Ali Kaya"]),
])
def test_s4_05_k1_k2_k3_k4_k5_k6_full_display_names(text, people, expected):
    clean = normalize(text)
    spans = find_names(text, people)
    assert [clean[s.start:s.end] for s in spans] == expected
    assert all(s.kind == "person" and s.confidence == "certain" for s in spans)
    assert all(a.end <= b.start for a, b in zip(spans, spans[1:]))


def write_rows(tmp_path, rows):
    path = tmp_path / "synthetic.jsonl"
    path.write_text("".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows),
                    encoding="utf-8")
    return path


def test_s4_06_k1_k4_counts_ids_and_never_text(monkeypatch, capsys, tmp_path):
    rows = [
        {"id": "tp", "text": "flag synthetic attack marker", "label": "injection"},
        {"id": "fp", "text": "flag synthetic safe marker", "label": "safe"},
        {"id": "fn", "text": "quiet synthetic attack marker", "label": "injection"},
        {"id": "tn", "text": "quiet İstanbul safe marker", "label": "safe"},
    ]
    code, out, err = cli(monkeypatch, capsys, "app.filters.detector_measure",
                         write_rows(tmp_path, rows))
    assert code == 0
    assert json.loads(out) == {
        "total": 4, "true_positives": 1, "false_positives": 1,
        "false_negatives": 1, "false_positive_ids": ["fp"], "false_negative_ids": ["fn"],
    }
    assert err == ""
    assert all(row["text"] not in out + err for row in rows)
    assert injection.THRESHOLD == 0.5


def test_s4_06_k2_unavailable_has_no_counts(monkeypatch, capsys, tmp_path):
    monkeypatch.setattr(injection, "_loader", unavailable)
    path = write_rows(tmp_path, [{"id": "one", "text": "PRIVATE_TEXT", "label": "safe"}])
    code, out, err = cli(monkeypatch, capsys, "app.filters.detector_measure", path)
    assert (code, out, err) == (1, "detector not available\n", "")


@pytest.mark.parametrize("bad", [
    '{"PRIVATE_TEXT":',
    '{"id":"bad","text":"PRIVATE_TEXT"}',
    '{"id":"bad","text":"PRIVATE_TEXT","label":"PRIVATE_UNKNOWN_LABEL"}',
    '{"id":"bad","label":"safe"}',
    '{"text":"PRIVATE_TEXT","label":"safe"}',
])
def test_s4_06_k3_invalid_line_safe_error(monkeypatch, capsys, tmp_path, bad):
    path = tmp_path / "PRIVATE_PATH.jsonl"
    path.write_text('{"id":"ok","text":"quiet example","label":"safe"}\n' + bad + "\n",
                    encoding="utf-8")
    code, out, err = cli(monkeypatch, capsys, "app.filters.detector_measure", path)
    assert code == 2
    assert (out + err).strip() == "invalid input at line 2"
    assert "PRIVATE" not in out + err
    assert "total" not in out + err


def test_s4_06_k3_missing_file_safe_error(monkeypatch, capsys, tmp_path):
    code, out, err = cli(monkeypatch, capsys, "app.filters.detector_measure",
                         tmp_path / "PRIVATE_MISSING.jsonl")
    assert code == 2
    assert (out + err).strip() == "input not available"
