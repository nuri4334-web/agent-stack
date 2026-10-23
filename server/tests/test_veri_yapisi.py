import sqlite3

import pytest

from app import kapi
from app.veritabani.tablolar import SEMA_SURUMU, baglan, tablolari_olustur

TABLOLAR = {
    "kisiler", "bagli_hesaplar", "slack_kullanicilari", "kanallar",
    "kanal_uyelikleri", "mesajlar", "olay_kayitlari", "yapay_zeka_cagrilari",
}
ZAMAN = "2026-10-22T14:05:00+03:00"
TS = "1729500000.000100"


@pytest.fixture
def db():
    baglanti = baglan(":memory:")
    tablolari_olustur(baglanti)
    yield baglanti
    baglanti.close()


def _sutunlar(db, tablo):
    return {satir[1] for satir in db.execute(f"PRAGMA table_info({tablo})")}


def _ekle(db, tablo, satir):
    sutunlar = ", ".join(satir)
    yerler = ", ".join("?" * len(satir))
    return db.execute(f"INSERT INTO {tablo} ({sutunlar}) VALUES ({yerler})", tuple(satir.values()))


def _kanal_ekle(db, slack_id="C1", ad="dev", ozel_mi=0, **alanlar):
    _ekle(db, "kanallar", {"slack_id": slack_id, "ad": ad, "ozel_mi": ozel_mi} | alanlar)


def _kullanici_ekle(db, slack_id="U1"):
    _ekle(db, "slack_kullanicilari", {"slack_id": slack_id, "gorunen_ad": "Deniz"})


def _mesaj_ekle(db, kanal_id="C1", ts=TS, yazan_id="U1"):
    _ekle(db, "mesajlar", {
        "kanal_id": kanal_id, "ts": ts, "yazan_id": yazan_id,
        "zaman": ZAMAN, "temiz_metin": "login sayfasını sen al",
    })


def _kisi_ekle(db, ad="Ali", **alanlar):
    return _ekle(db, "kisiler", {"gorunen_ad": ad} | alanlar).lastrowid


def _hesap_bagla(db, kisi_id, kaynak_kimligi, kaynak="slack", baglanma_sekli="yonetici"):
    _ekle(db, "bagli_hesaplar", {
        "kisi_id": kisi_id, "kaynak": kaynak, "kaynak_kimligi": kaynak_kimligi,
        "baglanma_sekli": baglanma_sekli, "baglanma_zamani": ZAMAN,
    })


def _olay_ekle(db, **alanlar):
    satir = {
        "zaman": ZAMAN, "istek_id": "3f9c2a1b7d4e", "adim": "yetki",
        "karar": "gecti", "sure_ms": 1.5,
    } | alanlar
    return _ekle(db, "olay_kayitlari", satir).lastrowid


def _yz_ekle(db, **alanlar):
    satir = {
        "zaman": ZAMAN, "istek_id": "3f9c2a1b7d4e", "model": "gemini-2.0-flash",
        "sonuc": "tamam", "gonderilen_mesaj_sayisi": 12, "sure_ms": 850.25,
        "girdi_token": 1200, "cikti_token": 300,
    } | alanlar
    _ekle(db, "yapay_zeka_cagrilari", satir)


def test_tablolar_bosken_olusuyor(db):
    adlar = {s[0] for s in db.execute(
        "SELECT name FROM sqlite_master WHERE type = 'table' AND name NOT LIKE 'sqlite_%'"
    )}
    assert adlar == TABLOLAR
    for tablo in TABLOLAR:
        assert db.execute(f"SELECT count(*) FROM {tablo}").fetchone()[0] == 0
    assert db.execute("PRAGMA user_version").fetchone()[0] == SEMA_SURUMU == 1


def test_iki_kez_olusturma_sorun_cikarmiyor(db):
    _kanal_ekle(db)
    db.commit()
    tablolari_olustur(db)
    assert db.execute("SELECT count(*) FROM kanallar").fetchone()[0] == 1
    assert db.execute("PRAGMA user_version").fetchone()[0] == SEMA_SURUMU


def test_daha_yeni_surum_veritabani_reddedilir():
    baglanti = baglan(":memory:")
    baglanti.execute("PRAGMA user_version = 2")
    with pytest.raises(RuntimeError):
        tablolari_olustur(baglanti)
    baglanti.close()


def test_yabanci_anahtar_acik(db):
    assert db.execute("PRAGMA foreign_keys").fetchone()[0] == 1
    _kullanici_ekle(db)
    with pytest.raises(sqlite3.IntegrityError):
        _mesaj_ekle(db, kanal_id="C_YOK")


def test_mesajlarda_ham_metin_sutunu_yok(db):
    sutunlar = _sutunlar(db, "mesajlar")
    assert sutunlar == {"id", "kanal_id", "ts", "yazan_id", "zaman", "temiz_metin", "supheli"}
    assert not any("ham" in s or "raw" in s for s in sutunlar)


def test_olay_kayitlarinda_metin_sutunu_yok(db):
    assert _sutunlar(db, "olay_kayitlari") == {
        "id", "zaman", "istek_id", "kisi_id", "adim", "karar", "sebep_kodu", "kanal_id",
        "mesaj_sayisi", "kanal_sayisi", "kullanici_sayisi", "uyelik_sayisi",
        "engellenen_sayisi", "maskelenen_sayisi", "supheli_sayisi", "sure_ms",
    }


def test_olay_sebebi_serbest_metin_kabul_etmez(db):
    _olay_ekle(db, karar="durdu", sebep_kodu="KANAL_UYESI_DEGIL")
    for sebep in ["Ali: şifre 1234", "kanal_uyesi_degil", "", "A" * 41]:
        with pytest.raises(sqlite3.IntegrityError):
            _olay_ekle(db, karar="durdu", sebep_kodu=sebep)


def test_olay_adimlari_kapi_ile_ayni(db):
    for ad in [ad for ad, _ in kapi.ADIMLAR] + ["slack_cekme"]:
        _olay_ekle(db, adim=ad)
    with pytest.raises(sqlite3.IntegrityError):
        _olay_ekle(db, adim="baska_adim")


def test_olay_karari_sinirli(db):
    for karar in ["gecti", "durdu", "tamam", "hata"]:
        _olay_ekle(db, karar=karar)
    with pytest.raises(sqlite3.IntegrityError):
        _olay_ekle(db, karar="basarili")


def test_slack_cekme_ozeti_yazilabiliyor(db):
    satir_id = _olay_ekle(
        db, adim="slack_cekme", karar="tamam", istek_id="a1b2c3d4e5f6",
        kanal_sayisi=3, kullanici_sayisi=5, uyelik_sayisi=9, mesaj_sayisi=42,
    )
    satir = db.execute(
        "SELECT kisi_id, kanal_sayisi, kullanici_sayisi, uyelik_sayisi, mesaj_sayisi "
        "FROM olay_kayitlari WHERE id = ?", (satir_id,)
    ).fetchone()
    assert satir == (None, 3, 5, 9, 42)
    with pytest.raises(sqlite3.IntegrityError):
        _olay_ekle(db, adim="slack_cekme", karar="tamam", kanal_sayisi=-1)


def test_cekilemeyen_kanal_kaydi_yazilabiliyor(db):
    _kanal_ekle(db)
    _olay_ekle(db, adim="slack_cekme", karar="hata", sebep_kodu="KANAL_CEKILEMEDI", kanal_id="C1")
    with pytest.raises(sqlite3.IntegrityError):
        _olay_ekle(db, adim="slack_cekme", karar="hata", sebep_kodu="KANAL_CEKILEMEDI",
                   kanal_id="C_YOK")


def test_yapay_zeka_cagrisinda_metin_sutunu_yok(db):
    assert _sutunlar(db, "yapay_zeka_cagrilari") == {
        "id", "zaman", "istek_id", "model", "sonuc", "gonderilen_mesaj_sayisi",
        "sure_ms", "girdi_token", "cikti_token",
    }
    _yz_ekle(db)
    with pytest.raises(sqlite3.IntegrityError):
        _yz_ekle(db, model="gemini 2.0 flash")
    with pytest.raises(sqlite3.IntegrityError):
        _yz_ekle(db, girdi_token=-1)


def test_yapay_zeka_sonucu_sinirli(db):
    _yz_ekle(db, sonuc="saglayici_hatasi", girdi_token=None, cikti_token=None)
    _yz_ekle(db, sonuc="zaman_asimi", girdi_token=None, cikti_token=None)
    for sonuc in ["SAGLAYICI_HATASI", "basarisiz", ""]:
        with pytest.raises(sqlite3.IntegrityError):
            _yz_ekle(db, sonuc=sonuc)


def test_yeni_kanal_varsayilani_haric(db):
    _kanal_ekle(db, "C1", "dev", ozel_mi=0)
    _kanal_ekle(db, "C2", "yonetim", ozel_mi=1)
    durumlar = [s[0] for s in db.execute("SELECT durum FROM kanallar")]
    assert durumlar == ["hariç", "hariç"]


def test_kanal_durumu_yalnizca_izinli_ya_da_haric(db):
    for durum in ["public", "private", "haric"]:
        with pytest.raises(sqlite3.IntegrityError):
            _kanal_ekle(db, "C1", "dev", durum=durum)


def test_ik_kanali_tabloda_izinli_olamaz(db):
    for ad in ["ik", "IK"]:
        with pytest.raises(sqlite3.IntegrityError):
            _kanal_ekle(db, "C9", ad, ozel_mi=1, durum="izinli")
    _kanal_ekle(db, "C9", "ik", ozel_mi=1)
    with pytest.raises(sqlite3.IntegrityError):
        db.execute("UPDATE kanallar SET durum = 'izinli' WHERE slack_id = 'C9'")


def test_kanal_ve_ts_tekrar_yazilamiyor(db):
    _kanal_ekle(db, "C1", "dev")
    _kanal_ekle(db, "C2", "genel")
    _kullanici_ekle(db)
    _mesaj_ekle(db, "C1")
    with pytest.raises(sqlite3.IntegrityError):
        _mesaj_ekle(db, "C1")
    _mesaj_ekle(db, "C2")


def test_ts_metin_olarak_saklaniyor(db):
    _kanal_ekle(db)
    _kullanici_ekle(db)
    _mesaj_ekle(db)
    assert db.execute("SELECT ts, typeof(ts) FROM mesajlar").fetchone() == (TS, "text")


def test_ts_ondalik_sayi_olarak_yazilamiyor(db):
    _kanal_ekle(db)
    _kullanici_ekle(db)
    for ts in [1729500000.0001, 1729500000, "1729500000.0001"]:
        with pytest.raises(sqlite3.IntegrityError):
            _mesaj_ekle(db, ts=ts)


def test_supheli_varsayilani_bos(db):
    _kanal_ekle(db)
    _kullanici_ekle(db)
    _mesaj_ekle(db)
    assert db.execute("SELECT supheli FROM mesajlar").fetchone()[0] is None


def test_rol_varsayilani_kullanici(db):
    kisi_id = _kisi_ekle(db)
    assert db.execute("SELECT rol FROM kisiler WHERE id = ?", (kisi_id,)).fetchone()[0] == "kullanici"
    _kisi_ekle(db, "Nuri", rol="admin")
    with pytest.raises(sqlite3.IntegrityError):
        _kisi_ekle(db, "Musa", rol="superadmin")


def test_ayni_slack_hesabi_iki_kisiye_baglanamiyor(db):
    ali = _kisi_ekle(db, "Ali")
    deniz = _kisi_ekle(db, "Deniz")
    _hesap_bagla(db, ali, "U123")
    with pytest.raises(sqlite3.IntegrityError):
        _hesap_bagla(db, deniz, "U123")
    _hesap_bagla(db, deniz, "U123", kaynak="github")


def test_kisi_ayni_kaynakta_iki_hesap_baglayamaz(db):
    ali = _kisi_ekle(db)
    _hesap_bagla(db, ali, "U1")
    with pytest.raises(sqlite3.IntegrityError):
        _hesap_bagla(db, ali, "U2")


def test_kaynak_ve_baglanma_sekli_sinirli(db):
    ali = _kisi_ekle(db)
    with pytest.raises(sqlite3.IntegrityError):
        _hesap_bagla(db, ali, "U1", kaynak="gitlab")
    with pytest.raises(sqlite3.IntegrityError):
        _hesap_bagla(db, ali, "U1", baglanma_sekli="otomatik")


def test_uyelik_bilinmeyen_kullaniciyla_yazilamiyor(db):
    _kanal_ekle(db)
    with pytest.raises(sqlite3.IntegrityError):
        _ekle(db, "kanal_uyelikleri", {
            "kanal_id": "C1", "slack_kullanici_id": "U_YOK", "guncelleme_zamani": ZAMAN,
        })
