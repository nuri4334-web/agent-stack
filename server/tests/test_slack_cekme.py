from datetime import datetime

import pytest

from app.slack_baglayici import temizlik
from app.slack_baglayici.cek import komutu_calistir, ozeti_yaz, slack_cek
from app.veritabani.tablolar import baglan
from tests.sahte_slack import IZINLI, SIMDI, mesaj, ornek_slack, ts

KANAL_UCLARI = {"conversations.members", "conversations.history"}


@pytest.fixture
def db():
    # slack_cek tabloları kendisi oluşturur (tablolari_olustur ilk iş).
    baglanti = baglan(":memory:")
    yield baglanti
    baglanti.close()


def _cek(db, slack, izinli=IZINLI, calisma_id="a1b2c3d4", **secenekler):
    return slack_cek(db, slack, izinli, gun=30, simdi=lambda: SIMDI, calisma_id=calisma_id, **secenekler)


def _say(db, sql, *parametreler):
    return db.execute(sql, parametreler).fetchone()[0]


def _mesaj_sayisi(db, kanal_id=None):
    if kanal_id is None:
        return _say(db, "SELECT count(*) FROM mesajlar")
    return _say(db, "SELECT count(*) FROM mesajlar WHERE kanal_id = ?", kanal_id)


def _ozet_satiri(db):
    return db.execute(
        "SELECT istek_id, kisi_id, karar, sebep_kodu, kanal_sayisi, kullanici_sayisi, "
        "uyelik_sayisi, mesaj_sayisi FROM olay_kayitlari WHERE adim = 'slack_cekme' AND karar = 'tamam' "
        "ORDER BY id DESC LIMIT 1"
    ).fetchone()


def _hata_satirlari(db):
    return db.execute(
        "SELECT sebep_kodu, kanal_id FROM olay_kayitlari WHERE karar = 'hata' ORDER BY id"
    ).fetchall()


def test_haric_kanal_icin_uye_ve_mesaj_istegi_yapilmiyor(db):
    slack = ornek_slack()
    _cek(db, slack)
    assert slack.kanal_cagrilari("C_SATIS") == []
    assert _mesaj_sayisi(db, "C_SATIS") == 0
    assert _say(db, "SELECT count(*) FROM kanal_uyelikleri WHERE kanal_id = 'C_SATIS'") == 0
    assert _say(db, "SELECT durum FROM kanallar WHERE slack_id = 'C_SATIS'") == "hariç"


def test_ik_izin_listesinde_olsa_bile_cekilmiyor(db):
    slack = ornek_slack()
    _cek(db, slack, izinli=IZINLI + ["ik", "#IK"])
    assert slack.kanal_cagrilari("C_IK") == []
    assert _mesaj_sayisi(db, "C_IK") == 0
    assert _say(db, "SELECT count(*) FROM kanal_uyelikleri WHERE kanal_id = 'C_IK'") == 0
    assert _say(db, "SELECT durum FROM kanallar WHERE slack_id = 'C_IK'") == "hariç"


def test_private_yonetim_mesajlari_cekiliyor(db):
    _cek(db, ornek_slack())
    assert _say(db, "SELECT ozel_mi FROM kanallar WHERE slack_id = 'C_YON'") == 1
    assert _say(db, "SELECT durum FROM kanallar WHERE slack_id = 'C_YON'") == "izinli"
    assert _mesaj_sayisi(db, "C_YON") == 1


def test_iki_kez_calisinca_mesaj_sayisi_degismiyor(db):
    slack = ornek_slack()
    ilk = _cek(db, slack)
    ikinci = _cek(db, slack, calisma_id="e5f6")
    assert ilk.mesaj_sayisi == 6
    assert ikinci.mesaj_sayisi == 0
    assert _mesaj_sayisi(db) == 6
    assert _ozet_satiri(db)[7] == 0


def test_sayfalama_tum_sayfalari_aliyor(db):
    slack = ornek_slack(sayfa_boyu=1)
    ozet = _cek(db, slack)
    assert ozet.mesaj_sayisi == 6
    assert ozet.uyelik_sayisi == 9
    assert _say(db, "SELECT count(*) FROM kanallar") == 5
    assert _say(db, "SELECT count(*) FROM slack_kullanicilari") == 4
    gecmis = [p.get("cursor") for uc, p in slack.cagrilar
              if uc == "conversations.history" and p["channel"] == "C_DEV"]
    assert gecmis == [None, "1", "2"]


def test_bir_kanal_hata_verince_digerleri_devam_ediyor(db):
    slack = ornek_slack()
    slack.hatalar[("conversations.history", "C_DEV")] = "not_in_channel"
    ozet = _cek(db, slack)
    assert _mesaj_sayisi(db, "C_DEV") == 0
    assert _mesaj_sayisi(db, "C_GENEL") == 2
    assert _mesaj_sayisi(db, "C_YON") == 1
    assert _hata_satirlari(db) == [("KANAL_CEKILEMEDI", "C_DEV")]
    assert _ozet_satiri(db)[3] == "BAZI_KANALLAR_CEKILEMEDI"
    assert ozet.kanal_sayisi == 2
    dev = next(k for k in ozet.kanallar if k.ad == "dev")
    assert dev.hata_detayi == "Slack: not_in_channel"


def test_bot_kanalda_degilse_istek_yok_ve_hata_kaydi(db):
    slack = ornek_slack()
    slack.kanallar[1]["is_member"] = False
    _cek(db, slack)
    assert slack.kanal_cagrilari("C_DEV") == []
    assert _hata_satirlari(db) == [("BOT_KANALDA_DEGIL", "C_DEV")]


def test_ozet_satiri_dogru_sayilarla_yaziliyor(db):
    _cek(db, ornek_slack())
    assert _ozet_satiri(db) == ("a1b2c3d4", None, "tamam", None, 3, 4, 9, 6)
    assert _say(db, "SELECT count(*) FROM olay_kayitlari") == 1


def test_bilinmeyen_yazan_once_slack_kullanicilarina_ekleniyor(db):
    slack = ornek_slack()
    slack.mesajlar["C_DEV"].append(mesaj("U_YABANCI", "merhaba", 1, 900))
    _cek(db, slack)
    satir = db.execute(
        "SELECT gorunen_ad, gercek_ad, bot_mu FROM slack_kullanicilari WHERE slack_id = 'U_YABANCI'"
    ).fetchone()
    assert satir == (None, None, 0)
    assert _say(db, "SELECT count(*) FROM mesajlar WHERE yazan_id = 'U_YABANCI'") == 1


def test_ts_metin_olarak_kaliyor(db):
    _cek(db, ornek_slack())
    beklenen = ts(5, 100)
    assert beklenen.endswith(".000100")
    assert db.execute(
        "SELECT ts, typeof(ts) FROM mesajlar WHERE kanal_id = 'C_GENEL' ORDER BY ts LIMIT 1"
    ).fetchone() == (beklenen, "text")


def test_cikan_uye_sonraki_cekmede_siliniyor(db):
    slack = ornek_slack()
    _cek(db, slack)
    slack.uyeler["C_DEV"].remove("U_DENIZ")
    sonraki = "2026-10-24T12:00:00+00:00"
    slack_cek(db, slack, IZINLI, gun=30, simdi=lambda: datetime.fromisoformat(sonraki), calisma_id="e5f6")
    uyeler = db.execute(
        "SELECT slack_kullanici_id, guncelleme_zamani FROM kanal_uyelikleri WHERE kanal_id = 'C_DEV' "
        "ORDER BY slack_kullanici_id"
    ).fetchall()
    assert uyeler == [("U_ALI", sonraki), ("U_BOT", sonraki)]


def test_alt_turlu_mesajlar_atlaniyor(db):
    slack = ornek_slack()
    slack.mesajlar["C_GENEL"] += [
        mesaj(None, "bot yazdı", 3, 400, subtype="bot_message", bot_id="B1"),
        mesaj("U_ALI", "thread cevabı", 3, 500, subtype="thread_broadcast"),
        mesaj("U_ALI", "   ", 3, 600),
        mesaj(None, "yazansız", 3, 700),
    ]
    ozet = _cek(db, slack)
    genel = next(k for k in ozet.kanallar if k.ad == "genel")
    assert genel.yeni_mesaj == 2
    assert genel.cekilen_mesaj == 7
    assert dict(genel.atlanan) == {
        "channel_join": 1, "bot_message": 1, "thread_broadcast": 1, "bos_metin": 1, "yazan_yok": 1,
    }
    assert _mesaj_sayisi(db, "C_GENEL") == 2
    satirlar = []
    ozeti_yaz(ozet, satirlar.append)
    genel_satiri = next(s for s in satirlar if s.startswith("#genel"))
    assert "5 atlandı: bos_metin 1, bot_message 1, channel_join 1, thread_broadcast 1, yazan_yok 1" in genel_satiri
    cikti = "\n".join(satirlar)
    for metin in ["bot yazdı", "thread cevabı", "kanala katıldı", "günaydın"]:
        assert metin not in cikti


def test_temizle_yazmadan_once_cagriliyor(db, monkeypatch):
    monkeypatch.setattr(temizlik, "temizle", lambda metin: "[TEMİZ]")
    _cek(db, ornek_slack())
    assert {s[0] for s in db.execute("SELECT temiz_metin FROM mesajlar")} == {"[TEMİZ]"}


def test_izin_listesinden_cikan_kanalin_verisi_siliniyor(db):
    slack = ornek_slack()
    _cek(db, slack)
    _cek(db, slack, izinli=["genel", "yonetim"], calisma_id="e5f6")
    assert _say(db, "SELECT durum FROM kanallar WHERE slack_id = 'C_DEV'") == "hariç"
    assert _mesaj_sayisi(db, "C_DEV") == 0
    assert _say(db, "SELECT count(*) FROM kanal_uyelikleri WHERE kanal_id = 'C_DEV'") == 0
    assert _mesaj_sayisi(db, "C_GENEL") == 2
    # Olay kayıtları silinmez; kanal satırı kalır.
    assert _say(db, "SELECT count(*) FROM olay_kayitlari") == 2


def test_slackte_gorunmeyen_kanal_haric_oluyor(db):
    slack = ornek_slack()
    _cek(db, slack)
    slack.kanallar = [k for k in slack.kanallar if k["id"] != "C_DEV"]
    ozet = _cek(db, slack, calisma_id="e5f6")
    assert _say(db, "SELECT durum FROM kanallar WHERE slack_id = 'C_DEV'") == "hariç"
    assert _mesaj_sayisi(db, "C_DEV") == 0
    assert slack.kanal_cagrilari("C_DEV") == ["conversations.members", "conversations.history"]
    dev = next(k for k in ozet.kanallar if k.ad == "dev")
    assert (dev.durum, dev.silinen_mesaj) == ("hariç", 3)


def test_sifirdan_mesajlari_bastan_ceker(db):
    slack = ornek_slack()
    _cek(db, slack)
    slack.mesajlar["C_DEV"].pop()
    _cek(db, slack, calisma_id="e5f6")
    assert _mesaj_sayisi(db, "C_DEV") == 3
    ozet = _cek(db, slack, calisma_id="f7a8", sifirdan=True)
    assert _mesaj_sayisi(db, "C_DEV") == 2
    assert ozet.mesaj_sayisi == 5
    assert _say(db, "SELECT count(*) FROM olay_kayitlari") == 3


def test_kanal_listesi_cekilemezse_hicbir_sey_yazilmiyor(db):
    slack = ornek_slack()
    slack.hatalar[("conversations.list", None)] = "invalid_auth"
    ozet = _cek(db, slack)
    assert ozet.baslayamadi == "KANAL_LISTESI_CEKILEMEDI"
    assert _hata_satirlari(db) == [("KANAL_LISTESI_CEKILEMEDI", None)]
    assert _say(db, "SELECT count(*) FROM olay_kayitlari") == 1
    for tablo in ["kanallar", "slack_kullanicilari", "kanal_uyelikleri", "mesajlar"]:
        assert _say(db, f"SELECT count(*) FROM {tablo}") == 0
    assert not any(uc in KANAL_UCLARI for uc, _ in slack.cagrilar)


def test_oldest_parametresi_gun_sayisindan(db):
    slack = ornek_slack()
    _cek(db, slack)
    beklenen = f"{int(SIMDI.timestamp()) - 30 * 86400}.000000"
    oldest = {p["oldest"] for uc, p in slack.cagrilar if uc == "conversations.history"}
    assert oldest == {beklenen}


def test_token_yoksa_baslamiyor(tmp_path):
    yol = tmp_path / "test.db"
    uretilen = []
    satirlar = []

    def calistir(argv, token):
        return komutu_calistir(
            argv, token=token, istemci_uret=lambda t: uretilen.append(t) or ornek_slack(),
            veritabani_yolu=yol, izinli_kanallar=IZINLI, simdi=lambda: SIMDI, yaz=satirlar.append,
        )

    assert calistir([], "") == 2
    assert calistir(["--gun", "0"], "xoxb-EXAMPLE") == 2
    assert calistir(["--gun", "366"], "xoxb-EXAMPLE") == 2
    assert uretilen == []
    assert not yol.exists()
    assert "SLACK_BOT_TOKEN" in satirlar[0]
