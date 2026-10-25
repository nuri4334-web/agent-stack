"""Tüm testler için ortak pytest yapılandırması."""
from datetime import datetime, timezone

import pytest

from app import ayarlar
from app.slack_baglayici import seed
from app.veritabani.tablolar import baglan

# Testlerin izin listesi (.env'den bağımsız).
TEST_IZINLI_KANALLAR = ["genel", "dev", "yonetim"]


@pytest.fixture(scope="session")
def _seed_verisi():
    return seed.seed_oku(seed.SEED_YOLU)


@pytest.fixture(autouse=True)
def _gecici_veritabani(monkeypatch, tmp_path, _seed_verisi):
    """Her testte gerçek server/agentstack.db yerine seed yüklü geçici bir veritabanı."""
    yol = tmp_path / "test-agentstack.db"
    baglanti = baglan(yol)
    try:
        seed.yukle(
            baglanti, _seed_verisi, TEST_IZINLI_KANALLAR,
            lambda: datetime(2026, 10, 24, tzinfo=timezone.utc),
        )
    finally:
        baglanti.close()
    monkeypatch.setattr(ayarlar, "VERITABANI_YOLU", yol)
    return yol


@pytest.fixture(autouse=True)
def _varsayilan_sahte_saglayici(monkeypatch):
    """Her testte varsayılan olarak sahte sağlayıcıyı ve boş anahtarı zorla.

    Böylece geliştiricinin .env dosyasında AI_SAGLAYICI=gemini yazılı olsa bile
    test_iskelet.py gibi genel testler gerçek Gemini API'sine istek atmaz.
    """
    monkeypatch.setattr(ayarlar, "AI_SAGLAYICI", "sahte")
    monkeypatch.setattr(ayarlar, "GEMINI_API_KEY", "")