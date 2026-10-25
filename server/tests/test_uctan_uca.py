"""S1-05: uçtan uca akış, yapay zekâ çağrı kaydı ve ilk kırmızı yetki testi."""
import logging
import re
import sqlite3
from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient

from app import ayarlar, kapi, yapay_zeka
from app.main import app
from app.veritabani.tablolar import baglan

istemci = TestClient(app)

ALI = "U0CA5HH3M1V"
SABIT_SIMDI = datetime(2026, 10, 25, 9, 30, tzinfo=timezone.utc)
SATIR_BASI = re.compile(r"^\[#([\w-]+) \| ", re.MULTILINE)


@pytest.fixture
def giden(monkeypatch):
    """Yapay zekâya giden veri metinlerini yakalar; asıl sahte sağlayıcıyı çağırır (sayaç çalışır)."""
    yakalanan = []
    asil = yapay_zeka.sor

    def casus(talimat, veri):
        yakalanan.append(veri)
        return asil(talimat=talimat, veri=veri)

    monkeypatch.setattr(yapay_zeka, "sor", casus)
    yapay_zeka.sahte_sayaci_sifirla()
    return yakalanan


def _sorgu(sql, parametreler=()):
    baglanti = baglan(ayarlar.VERITABANI_YOLU)
    try:
        return baglanti.execute(sql, parametreler).fetchall()
    finally:
        baglanti.close()


def _kanal_metinleri(ad):
    return [m for (m,) in _sorgu(
        "SELECT m.temiz_metin FROM mesajlar m JOIN kanallar k ON k.slack_id = m.kanal_id WHERE k.ad = ?", (ad,),
    )]


def _cagri_satirlari():
    return _sorgu(
        "SELECT zaman, istek_id, model, sonuc, gonderilen_mesaj_sayisi, sure_ms, girdi_token, cikti_token "
        "FROM yapay_zeka_cagrilari ORDER BY id"
    )


def _sor(soru, kullanici="ali"):
    return istemci.post("/api/soru", json={"soru": soru, "kullanici": kullanici})


def _haric_kanal_ekle():
    baglanti = baglan(ayarlar.VERITABANI_YOLU)
    try:
        with baglanti:
            baglanti.execute(
                "INSERT INTO kanallar (slack_id, ad, ozel_mi, durum) VALUES ('C0ESKI00001', 'eski', 0, 'hariç')"
            )
            baglanti.execute(
                "INSERT INTO mesajlar (kanal_id, ts, yazan_id, zaman, temiz_metin) VALUES "
                "('C0ESKI00001', '1792665999.000001', ?, '2026-10-22T10:46:39+00:00', 'TEST - hariç mesaj')",
                (ALI,),
            )
    finally:
        baglanti.close()


def test_dev_ozetle_yapay_zeka_bir_kez_ve_yalnizca_dev(giden):
    r = _sor("#dev'i özetle")
    assert r.status_code == 200
    govde = r.json()
    assert govde["durum"] == "tamam"
    assert govde["cevap"] == yapay_zeka.SAHTE_SABIT_CEVAP
    assert govde["kaynaklar"] == []
    assert yapay_zeka.sahte_cagri_sayisi() == 1
    assert len(giden) == 1
    kanallar = SATIR_BASI.findall(giden[0])
    assert set(kanallar) == {"dev"}
    assert len(kanallar) == 27
    for metin in _kanal_metinleri("yonetim") + _kanal_metinleri("genel"):
        assert metin not in giden[0]


def test_kanal_adi_yoksa_yalnizca_izinli_kanallar(giden):
    _haric_kanal_ekle()
    r = _sor("geçen hafta neler oldu?")
    assert r.status_code == 200
    assert r.json()["durum"] == "tamam"
    kanallar = SATIR_BASI.findall(giden[0])
    assert set(kanallar) == {"dev", "genel", "yonetim"}
    assert len(kanallar) == 39
    assert "TEST - hariç mesaj" not in giden[0]


def test_pr_numarasi_erisim_yok_almaz_butun_izinli_kanallara_gider(giden):
    r = _sor("PR #17 ne durumda?")
    assert r.status_code == 200
    assert r.json()["durum"] == "tamam"
    assert yapay_zeka.sahte_cagri_sayisi() == 1
    assert set(SATIR_BASI.findall(giden[0])) == {"dev", "genel", "yonetim"}


@pytest.mark.parametrize("soru", ["#ik'i özetle", "#bugs neler var", "#dev ve #ik"])
def test_izinli_olmayan_kanal_erisim_yok_yapay_zeka_cagrilmaz(giden, soru):
    r = _sor(soru)
    assert r.status_code == 200
    govde = r.json()
    assert govde["durum"] == "erisim_yok"
    assert govde["cevap"] == kapi.ERISIM_YOK_CEVABI
    assert govde["kaynaklar"] == []
    assert yapay_zeka.sahte_cagri_sayisi() == 0
    assert giden == []
    assert _cagri_satirlari() == []


def test_mesaj_yoksa_yapay_zeka_cagrilmaz(giden, monkeypatch, tmp_path, caplog):
    monkeypatch.setattr(ayarlar, "VERITABANI_YOLU", tmp_path / "bos.db")
    with caplog.at_level(logging.WARNING, logger="agentstack"):
        r = _sor("#dev'i özetle")
    assert r.status_code == 200
    govde = r.json()
    assert govde["durum"] == "tamam"
    assert govde["cevap"] == kapi.MESAJ_YOK_CEVABI
    assert yapay_zeka.sahte_cagri_sayisi() == 0
    assert _cagri_satirlari() == []
    assert "Slack verisi yok" in caplog.text
    assert "#dev" not in caplog.text


def test_cagri_kaydi_dogru_ve_metin_icermez(giden):
    soru = "#dev'i özetle"
    cevap = kapi.soru_isle(soru, "ali", simdi=lambda: SABIT_SIMDI)
    satirlar = _cagri_satirlari()
    assert len(satirlar) == 1
    zaman, istek_id, model, sonuc, sayi, sure_ms, girdi, cikti = satirlar[0]
    assert zaman == SABIT_SIMDI.isoformat()
    assert istek_id == cevap.istek_id
    assert (model, sonuc, sayi) == ("sahte-v1", "tamam", 27)
    assert sure_ms >= 0
    assert girdi > 0 and cikti > 0
    metin_sutunlari = " ".join(str(d) for d in satirlar[0])
    assert soru not in metin_sutunlari
    assert yapay_zeka.SAHTE_SABIT_CEVAP not in metin_sutunlari
    for metin in _kanal_metinleri("dev"):
        assert metin not in metin_sutunlari


@pytest.mark.parametrize("kod, http, sonuc", [
    ("ZAMAN_ASIMI", 504, "zaman_asimi"),
    ("SAGLAYICI_HATASI", 502, "saglayici_hatasi"),
    ("KOTA_ASILDI", 502, "saglayici_hatasi"),
])
def test_saglayici_hatasinda_kayit_ve_502_504(monkeypatch, kod, http, sonuc):
    def hata_ver(talimat, veri):
        raise yapay_zeka.YapayZekaHatasi(kod=kod, mesaj="TEST - sağlayıcı hatası")

    monkeypatch.setattr(yapay_zeka, "sor", hata_ver)
    r = _sor("#dev'i özetle")
    assert r.status_code == http
    assert r.json()["hata"]["kod"] == ("ZAMAN_ASIMI" if kod == "ZAMAN_ASIMI" else "SAGLAYICI_HATASI")
    satirlar = _cagri_satirlari()
    assert len(satirlar) == 1
    _, _, model, yazilan_sonuc, sayi, _, girdi, cikti = satirlar[0]
    assert (model, yazilan_sonuc, sayi, girdi, cikti) == ("bilinmiyor", sonuc, 27, None, None)


def test_gemini_hatasinda_model_adi_ayardan(monkeypatch):
    monkeypatch.setattr(ayarlar, "AI_SAGLAYICI", "gemini")
    monkeypatch.setattr(ayarlar, "GEMINI_MODEL", "gemini-test-model")

    def hata_ver(talimat, veri):
        raise yapay_zeka.YapayZekaHatasi(kod="ZAMAN_ASIMI", mesaj="TEST")

    monkeypatch.setattr(yapay_zeka, "sor", hata_ver)
    assert _sor("#dev'i özetle").status_code == 504
    assert _cagri_satirlari()[0][2] == "gemini-test-model"


def test_kayit_yazilamazsa_cevap_ve_hata_bozulmaz(giden, monkeypatch, caplog):
    def bozuk(*args, **kwargs):
        raise sqlite3.OperationalError("TEST - yazılamadı")

    monkeypatch.setattr(kapi, "yapay_zeka_cagrisi_yaz", bozuk)
    with caplog.at_level(logging.ERROR, logger="agentstack"):
        r = _sor("#dev'i özetle")
    assert r.status_code == 200
    assert r.json()["cevap"] == yapay_zeka.SAHTE_SABIT_CEVAP
    assert "Yapay zekâ çağrı kaydı yazılamadı" in caplog.text

    def hata_ver(talimat, veri):
        raise yapay_zeka.YapayZekaHatasi(kod="ZAMAN_ASIMI", mesaj="TEST")

    monkeypatch.setattr(yapay_zeka, "sor", hata_ver)
    r = _sor("#dev'i özetle")
    assert r.status_code == 504
    assert r.json()["hata"]["kod"] == "ZAMAN_ASIMI"


@pytest.mark.parametrize("hata_olsun", [False, True])
def test_baglanti_her_istekte_acilip_kapaniyor(monkeypatch, hata_olsun):
    acilanlar = []

    def izle(yol):
        acilanlar.append((yol, baglan(yol)))
        return acilanlar[-1][1]

    monkeypatch.setattr(kapi, "baglan", izle)
    if hata_olsun:
        def hata_ver(talimat, veri):
            raise yapay_zeka.YapayZekaHatasi(kod="SAGLAYICI_HATASI", mesaj="TEST")
        monkeypatch.setattr(yapay_zeka, "sor", hata_ver)
    r = _sor("#dev'i özetle")
    assert r.status_code == (502 if hata_olsun else 200)
    assert len(acilanlar) == 1
    yol, baglanti = acilanlar[0]
    assert yol == ayarlar.VERITABANI_YOLU
    with pytest.raises(sqlite3.ProgrammingError):
        baglanti.execute("SELECT 1")


def test_testler_gercek_veritabanina_dokunmuyor(tmp_path_factory):
    gercek = ayarlar.KOK / "server" / "agentstack.db"
    assert ayarlar.VERITABANI_YOLU != gercek
    assert ayarlar.VERITABANI_YOLU.is_relative_to(tmp_path_factory.getbasetemp())

    def durum():
        return (gercek.stat().st_size, gercek.stat().st_mtime_ns) if gercek.exists() else None

    once = durum()
    assert _sor("#dev'i özetle").status_code == 200
    assert durum() == once


def test_kirmizi_testin_on_kosullari():
    assert _sorgu("SELECT durum FROM kanallar WHERE ad = 'yonetim'") == [("izinli",)]
    assert _kanal_metinleri("yonetim")
    assert _sorgu(
        "SELECT 1 FROM kanal_uyelikleri u JOIN kanallar k ON k.slack_id = u.kanal_id "
        "WHERE k.ad = 'yonetim' AND u.slack_kullanici_id = ?", (ALI,),
    ) == []


@pytest.mark.xfail(strict=True, raises=AssertionError, reason="Aşama 2: yetki katmanı yok")
def test_ali_yonetim_sorusunda_yapay_zeka_cagrilmaz(giden):
    r = _sor("#yonetim'de neler konuşuldu?", kullanici="ali")
    assert r.status_code == 200
    govde = r.json()
    assert yapay_zeka.sahte_cagri_sayisi() == 0
    assert giden == []
    for metin in _kanal_metinleri("yonetim"):
        assert metin not in govde["cevap"]
        assert all(metin not in k["metin"] for k in govde["kaynaklar"])
    assert govde["durum"] == "erisim_yok"
