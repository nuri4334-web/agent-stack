"""Measurement contract with synthetic examples and fake detector decisions."""
import json

import pytest

from app.filters import detector_measure as measure, injection


def write_rows(tmp_path, rows):
    path = tmp_path / "synthetic.jsonl"
    path.write_text("".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8")
    return str(path)


def row(identifier=1, label="safe"):
    return {"id": identifier, "text": "synthetic private example", "label": label}


def test_decisions_and_only_ids_are_reported(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(measure, "is_ready", lambda: True)
    decisions = iter([True, True, False, False])
    monkeypatch.setattr(injection, "detect", lambda text: injection.InjectionResult(next(decisions), 0.4))
    path = write_rows(tmp_path, [row("tp", "injection"), row("fp"), row(3, "injection"), row("tn")])
    assert measure.main([path]) == 0
    output = capsys.readouterr()
    assert output.err == ""
    assert json.loads(output.out) == {"total": 4, "true_positives": 1, "false_positives": 1,
                                      "false_negatives": 1, "false_positive_ids": ["fp"], "false_negative_ids": [3]}
    assert "synthetic" not in output.out


@pytest.mark.parametrize("bad", [
    {}, row(True), row(-1), row("private sentence here"), row("x" * 129), row(label="other"),
    {"id": 1, "text": 3, "label": "safe"}, [],
])
def test_invalid_rows_are_rejected_before_readiness(tmp_path, monkeypatch, capsys, bad):
    def forbidden():
        pytest.fail("invalid input must not load the detector")
    monkeypatch.setattr(measure, "is_ready", forbidden)
    assert measure.main([write_rows(tmp_path, [row(), bad])]) == 2
    assert capsys.readouterr() == ("invalid input at line 2\n", "")


@pytest.mark.parametrize("payload", [b"{broken}\n", b"\xff\n"])
def test_invalid_encoding_and_json_have_exact_line(tmp_path, capsys, payload):
    path = tmp_path / "input.jsonl"
    path.write_bytes(json.dumps(row()).encode() + b"\n" + payload)
    assert measure.main([str(path)]) == 2
    assert capsys.readouterr() == ("invalid input at line 2\n", "")


def test_missing_file_and_arguments_are_generic(tmp_path, capsys):
    for args in [[], [str(tmp_path / "missing")], ["one", "two"]]:
        assert measure.main(args) == 2
        assert capsys.readouterr() == ("input not available\n", "")


def test_unavailable_warmup_has_no_counts(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(measure, "is_ready", lambda: False)
    assert measure.main([write_rows(tmp_path, [row()])]) == 1
    assert capsys.readouterr() == ("detector not available\n", "")


@pytest.mark.parametrize("score", [-1.0, float("nan"), float("inf"), 1.1, "0.4", True])
def test_unusable_score_discards_all_stats(tmp_path, monkeypatch, capsys, score):
    monkeypatch.setattr(measure, "is_ready", lambda: True)
    results = iter([injection.InjectionResult(True, 0.9), injection.InjectionResult(True, score)])
    monkeypatch.setattr(injection, "detect", lambda text: next(results))
    assert measure.main([write_rows(tmp_path, [row(), row(2)])]) == 1
    assert capsys.readouterr() == ("detector not available\n", "")


def test_inference_exception_hides_diagnostics(tmp_path, monkeypatch, capsys, caplog):
    monkeypatch.setattr(measure, "is_ready", lambda: True)
    previous = injection.logger.disabled
    def broken(text):
        print(text)
        injection.logger.warning(text)
        raise RuntimeError(text)
    monkeypatch.setattr(injection, "detect", broken)
    assert measure.main([write_rows(tmp_path, [row()])]) == 1
    assert capsys.readouterr() == ("detector not available\n", "")
    assert "synthetic private" not in caplog.text
    assert injection.logger.disabled is previous


def test_normalized_empty_text_is_valid_safe_or_missed_injection(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(measure, "is_ready", lambda: True)
    monkeypatch.setattr(injection, "detect", lambda text: injection.InjectionResult(False, injection.NO_SCORE))
    examples = [{"id": 1, "text": "", "label": "safe"},
                {"id": 2, "text": " \n\u200b\u2060", "label": "injection"}]
    assert measure.main([write_rows(tmp_path, examples)]) == 0
    assert json.loads(capsys.readouterr().out) == {
        "total": 2, "true_positives": 0, "false_positives": 0, "false_negatives": 1,
        "false_positive_ids": [], "false_negative_ids": [2]}
