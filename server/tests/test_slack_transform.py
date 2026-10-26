from app.slack_connector.transform import user_row, is_valid_ts, ts_to_iso


def test_is_valid_ts():
    assert is_valid_ts("1729500000.000100")
    for ts in [1729500000.0001, 1729500000, "1729500000.0001", "", None, "172950000a.000100"]:
        assert not is_valid_ts(ts)


def test_ts_to_iso_without_converting_to_number():
    assert ts_to_iso("1729500000.000100") == "2024-10-21T08:40:00+00:00"


def test_user_row_and_bot():
    assert user_row({"id": "U1", "profile": {"display_name": "", "real_name": ""}}) == {
        "slack_id": "U1", "display_name": None, "real_name": None, "is_bot": 0,
    }
    assert user_row({"id": "U2", "real_name": "Deniz Demo"})["real_name"] == "Deniz Demo"
    assert user_row({"id": "USLACKBOT", "is_bot": False})["is_bot"] == 1
    assert user_row({"id": "U_BOT", "is_bot": True})["is_bot"] == 1
