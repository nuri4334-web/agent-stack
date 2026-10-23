"""Tüm testler için ortak pytest yapılandırması."""
import pytest

from app import ayarlar


@pytest.fixture(autouse=True)
def _varsayilan_sahte_saglayici(monkeypatch):
    """Her testte varsayılan olarak sahte sağlayıcıyı ve boş anahtarı zorla.

    Böylece geliştiricinin .env dosyasında AI_SAGLAYICI=gemini yazılı olsa bile
    test_iskelet.py gibi genel testler gerçek Gemini API'sine istek atmaz.
    """
    monkeypatch.setattr(ayarlar, "AI_SAGLAYICI", "sahte")
    monkeypatch.setattr(ayarlar, "GEMINI_API_KEY", "")