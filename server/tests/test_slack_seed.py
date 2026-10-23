import json

import pytest

from app.slack_baglayici.cek import slack_cek
from app.slack_baglayici.seed import (
    SEED_YOLU, SeedHatasi, disa_aktar, seed_dosyasi_yaz, seed_oku, yukle,
)
from app.veritabani.tablolar import baglan
from tests.sahte_slack import IZINLI, SIMDI, mesaj, ornek_slack

SLACK_TABLOLARI = ["kanallar", "slack_kullanicilari", "kanal_uyelikleri", "mesajlar"]
D21_BENZERI = (
    "SLACK_BOT_TOKEN=xoxb-0000-EXAMPLE-1111 GITHUB=ghp_EXAMPLE1234 "
    "GEMINI=AIzaEXAMPLE_abc-12 AWS=AKIAEXAMPLE0000"
)


@pytest.fixture
def db():
    baglanti = baglan(":memory:")
    yield baglanti
    baglanti.close()


def _dolu(db, slack=None):
    slack_cek(db, slack or ornek_slack(), IZINLI, gun=30, simdi=lambda: SIMDI, calisma_id="a1b2c3d4")
    return db


def _bos_db():
    return baglan(":memory:")


def _sayilar(db):
    return {t: db.execute(f"SELECT count(*) FROM {t}").fetchone()[0] for t in SLACK_TABLOLARI}


def _icerik(db):
    return (
        set(db.execute("SELECT kanal_id, ts, yazan_id, zaman, temiz_metin FROM mesajlar")),
        set(db.execute("SELECT kanal_id, slack_kullanici_id FROM kanal_uyelikleri")),
        set(db.execute("SELECT slack_id, gorunen_ad, gercek_ad, bot_mu FROM slack_kullanicilari")),
        set(db.execute("SELECT slack_id, ad, ozel_mi, durum FROM kanallar")),
    )


def test_seed_disa_aktar_bos_veritabanina_yukle_ayni_sayilar(db, tmp_path):
    _dolu(db)
    yol = tmp_path / "seed.json"
    seed_dosyasi_yaz(disa_aktar(db), yol)
    yeni = _bos_db()
    sayilar = yukle(yeni, seed_oku(yol), IZINLI, lambda: SIMDI)
    assert sayilar == {"kanal": 3, "izinli_kanal": 3, "kullanici": 4, "uyelik": 9, "mesaj": 6}
    beklenen = _icerik(db)
    gelen = _icerik(yeni)
    assert gelen[0] == beklenen[0]
    assert gelen[1] == beklenen[1]
    assert gelen[2] == beklenen[2]
    assert gelen[3] == {k for k in beklenen[3] if k[3] == "izinli"}
    assert yeni.execute("SELECT DISTINCT typeof(ts) FROM mesajlar").fetchall() == [("text",)]
    yeni.close()


def test_seedde_olay_kaydi_ve_haric_kanal_yok(db, tmp_path):
    _dolu(db)
    yol = tmp_path / "seed.json"
    seed_dosyasi_yaz(disa_aktar(db), yol)
    metin = yol.read_text(encoding="utf-8")
    veri = json.loads(metin)
    assert set(veri) == {"bicim", "surum", "kanallar", "slack_kullanicilari", "kanal_uyelikleri", "mesajlar"}
    for yasak in ["olay_kayitlari", "yapay_zeka", "istek_id", "C_IK", "C_SATIS", "maaş", "teklif"]:
        assert yasak not in metin
    assert b"\r\n" not in yol.read_bytes()


def test_dolu_veritabanina_yukleme_reddediliyor(db, tmp_path):
    _dolu(db)
    veri = disa_aktar(db)
    once = _sayilar(db)
    with pytest.raises(SeedHatasi):
        yukle(db, veri, IZINLI, lambda: SIMDI)
    assert _sayilar(db) == once


def test_seed_token_kalibi_iceriyorsa_yazilmiyor(db, tmp_path):
    slack = ornek_slack()
    slack.mesajlar["C_DEV"].append(mesaj("U_ALI", "anahtar: xoxb-1234-abcd-gercek", 1, 900))
    _dolu(db, slack)
    veri = disa_aktar(db)
    yol = tmp_path / "seed.json"
    with pytest.raises(SeedHatasi) as hata:
        seed_dosyasi_yaz(veri, yol)
    assert "slack_token" in str(hata.value)
    assert "xoxb-1234" not in str(hata.value)
    assert not yol.exists()

    # Elle yazılmış dosya da okunurken reddedilir (kaçış dizisiyle gizlenmiş olsa bile).
    for ensure_ascii in [False, True]:
        yol.write_text(json.dumps(veri, ensure_ascii=ensure_ascii).replace("xoxb", "\\u0078oxb"),
                       encoding="utf-8")
        with pytest.raises(SeedHatasi) as hata:
            seed_oku(yol)
        assert "slack_token" in str(hata.value)


def test_example_iceren_sahte_anahtarlar_seedde_kaliyor(db, tmp_path):
    slack = ornek_slack()
    slack.mesajlar["C_DEV"].append(mesaj("U_ALI", D21_BENZERI, 1, 900))
    _dolu(db, slack)
    yol = tmp_path / "seed.json"
    seed_dosyasi_yaz(disa_aktar(db), yol)
    yeni = _bos_db()
    yukle(yeni, seed_oku(yol), IZINLI, lambda: SIMDI)
    assert yeni.execute(
        "SELECT temiz_metin FROM mesajlar WHERE kanal_id = 'C_DEV' AND temiz_metin LIKE 'SLACK_BOT%'"
    ).fetchone() == (D21_BENZERI,)
    yeni.close()


def test_kullanilan_token_mesajda_geciyorsa_reddediliyor(db, tmp_path):
    # EXAMPLE içerdiği için kalıp kuralından geçer; yalnızca "kullanılan token" kuralı yakalar.
    token = "xoxb-EXAMPLE-9999-KULLANILAN"
    slack = ornek_slack()
    slack.mesajlar["C_DEV"].append(mesaj("U_ALI", f"yanlışlıkla yapıştırdım {token}", 1, 900))
    _dolu(db, slack)
    yol = tmp_path / "seed.json"
    with pytest.raises(SeedHatasi) as hata:
        seed_dosyasi_yaz(disa_aktar(db), yol, token=token)
    assert token not in str(hata.value)
    assert not yol.exists()
    seed_dosyasi_yaz(disa_aktar(db), yol, token="")
    with pytest.raises(SeedHatasi):
        seed_oku(yol, token)


def test_yukleyenin_izin_listesi_uygulaniyor(db, tmp_path):
    _dolu(db)
    yeni = _bos_db()
    sayilar = yukle(yeni, disa_aktar(db), ["genel", "yonetim"], lambda: SIMDI)
    assert sayilar["izinli_kanal"] == 2
    assert yeni.execute("SELECT durum FROM kanallar WHERE slack_id = 'C_DEV'").fetchone() == ("hariç",)
    assert yeni.execute("SELECT count(*) FROM mesajlar WHERE kanal_id = 'C_DEV'").fetchone() == (0,)
    assert yeni.execute("SELECT count(*) FROM kanal_uyelikleri WHERE kanal_id = 'C_DEV'").fetchone() == (0,)
    yeni.close()


def test_repodaki_seed_dosyasi_gecerli():
    if not SEED_YOLU.exists():
        pytest.skip("demo-verisi/slack-baslangic-verisi.json henüz yok (gerçek çekmeden sonra eklenecek).")
    # seed_oku EXAMPLE dışında token kalıbı olan dosyayı reddeder.
    veri = seed_oku(SEED_YOLU)
    adlar = [k["ad"] for k in veri["kanallar"]]
    assert "ik" not in [a.lower() for a in adlar]
    yeni = _bos_db()
    sayilar = yukle(yeni, veri, adlar, lambda: SIMDI)
    assert sayilar["mesaj"] == len(veri["mesajlar"])
    assert sayilar["uyelik"] == len(veri["kanal_uyelikleri"])
    yeni.close()
