from app.slack_baglayici.donusum import kullanici_satiri, ts_gecerli_mi, ts_zamani


def test_ts_gecerli_mi():
    assert ts_gecerli_mi("1729500000.000100")
    for ts in [1729500000.0001, 1729500000, "1729500000.0001", "", None, "172950000a.000100"]:
        assert not ts_gecerli_mi(ts)


def test_ts_zamani_sayiya_cevirmeden():
    assert ts_zamani("1729500000.000100") == "2024-10-21T08:40:00+00:00"


def test_kullanici_satiri_ve_bot():
    assert kullanici_satiri({"id": "U1", "profile": {"display_name": "", "real_name": ""}}) == {
        "slack_id": "U1", "gorunen_ad": None, "gercek_ad": None, "bot_mu": 0,
    }
    assert kullanici_satiri({"id": "U2", "real_name": "Deniz Demo"})["gercek_ad"] == "Deniz Demo"
    assert kullanici_satiri({"id": "USLACKBOT", "is_bot": False})["bot_mu"] == 1
    assert kullanici_satiri({"id": "U_BOT", "is_bot": True})["bot_mu"] == 1
