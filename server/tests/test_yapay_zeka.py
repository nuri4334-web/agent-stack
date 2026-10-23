"""S1-08: Yapay zekâ bağlantısı v1 testleri."""
import httpx
import pytest
from fastapi.testclient import TestClient

from app import ayarlar, kapi, yapay_zeka
from app.main import app
from app.yapay_zeka import gemini

istemci = TestClient(app)


def test_sahte_saglayici_sabit_cevap_ve_sayac(monkeypatch):
    monkeypatch.setattr(ayarlar, "AI_SAGLAYICI", "sahte")
    yapay_zeka.sahte_sayaci_sifirla()

    assert yapay_zeka.sahte_cagri_sayisi() == 0
    sonuc1 = yapay_zeka.sor(talimat="Özetle", veri="Mesaj 1")
    sonuc2 = yapay_zeka.sor(talimat="Özetle", veri="Mesaj 2")

    assert sonuc1.cevap == yapay_zeka.SAHTE_SABIT_CEVAP
    assert sonuc2.cevap == yapay_zeka.SAHTE_SABIT_CEVAP
    assert sonuc1.model == "sahte-v1"
    assert sonuc1.sure_ms >= 0
    assert sonuc1.girdi_token > 0
    assert sonuc1.cikti_token > 0
    assert yapay_zeka.sahte_cagri_sayisi() == 2


def test_durdurulan_istek_sahte_sayacini_artirmaz(monkeypatch):
    monkeypatch.setattr(ayarlar, "AI_SAGLAYICI", "sahte")
    yapay_zeka.sahte_sayaci_sifirla()

    def reddet(b):
        b.durum = "erisim_yok"
        b.durdu = True

    monkeypatch.setattr(
        kapi,
        "ADIMLAR",
        [
            ("yetki", reddet),
            ("yapay_zekaya_sor", kapi.yapay_zekaya_sor),
        ],
    )
    cevap = kapi.soru_isle("yonetim ne konuştu?", "ali")
    assert cevap.durum == "erisim_yok"
    assert yapay_zeka.sahte_cagri_sayisi() == 0


def test_gemini_talimat_ve_veriyi_ayri_alanlara_koyar_ve_arac_vermez(monkeypatch):
    monkeypatch.setattr(ayarlar, "AI_SAGLAYICI", "gemini")
    monkeypatch.setattr(ayarlar, "GEMINI_API_KEY", "test-gizli-anahtar-123")
    monkeypatch.setattr(ayarlar, "GEMINI_MODEL", "gemini-3.5-flash-lite")

    yakalanan_istek = {}

    class SahteYanit:
        status_code = 200

        def json(self):
            return {
                "candidates": [
                    {"content": {"parts": [{"text": "Gemini test özeti."}]}}
                ],
                "usageMetadata": {
                    "promptTokenCount": 15,
                    "candidatesTokenCount": 4,
                },
            }

    class SahteClient:
        def __init__(self, timeout):
            yakalanan_istek["timeout"] = timeout

        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def post(self, url, json, headers):
            yakalanan_istek["url"] = url
            yakalanan_istek["json"] = json
            yakalanan_istek["headers"] = headers
            return SahteYanit()

    monkeypatch.setattr(httpx, "Client", SahteClient)

    sonuc = yapay_zeka.sor(talimat="Sistem kuralı", veri="Slack mesajları")
    assert sonuc.cevap == "Gemini test özeti."
    assert sonuc.model == "gemini-3.5-flash-lite"
    assert sonuc.girdi_token == 15
    assert sonuc.cikti_token == 4

    # Talimat ve veri ayrı alanlarda olmalı, araç (tools) olmamalı (Kafes)
    govde = yakalanan_istek["json"]
    assert govde["system_instruction"]["parts"][0]["text"] == "Sistem kuralı"
    assert govde["contents"][0]["parts"][0]["text"] == "Slack mesajları"
    assert "tools" not in govde


def test_gemini_hata_ve_zaman_asiminda_anahtar_sizdirmaz(monkeypatch):
    gizli = "AIzaSyGIZLI_TEST_ANAHTARI_999"
    monkeypatch.setattr(ayarlar, "AI_SAGLAYICI", "gemini")
    monkeypatch.setattr(ayarlar, "GEMINI_API_KEY", gizli)

    class ZamanAsimiClient:
        def __init__(self, timeout):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def post(self, url, json, headers):
            raise httpx.TimeoutException(f"Timeout for key {gizli}")

    monkeypatch.setattr(httpx, "Client", ZamanAsimiClient)

    with pytest.raises(yapay_zeka.YapayZekaHatasi) as exc_info:
        gemini.sor(talimat="Talimat", veri="Veri")

    assert exc_info.value.kod == "ZAMAN_ASIMI"
    assert gizli not in exc_info.value.mesaj
    assert gizli not in str(exc_info.value)

    # Sohbet anlaşması: Zaman aşımında sunucu 504 ve ZAMAN_ASIMI dönmeli
    r_504 = istemci.post("/api/soru", json={"soru": "test sorusu", "kullanici": "ali"})
    assert r_504.status_code == 504
    govde_504 = r_504.json()
    assert govde_504["hata"]["kod"] == "ZAMAN_ASIMI"
    assert gizli not in str(govde_504)

    # Diğer sağlayıcı hatalarında sunucu 502 ve SAGLAYICI_HATASI dönmeli
    class SunucuHatasiClient(ZamanAsimiClient):
        def post(self, url, json, headers):
            class HataYaniti:
                status_code = 503
            return HataYaniti()

    monkeypatch.setattr(httpx, "Client", SunucuHatasiClient)
    r_502 = istemci.post("/api/soru", json={"soru": "test sorusu", "kullanici": "ali"})
    assert r_502.status_code == 502
    govde_502 = r_502.json()
    assert govde_502["hata"]["kod"] == "SAGLAYICI_HATASI"
    assert gizli not in str(govde_502)