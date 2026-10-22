"""Ayarlar: değerler .env dosyasından okunur. Hiçbir sır kodda durmaz."""
import os
from pathlib import Path

from dotenv import load_dotenv

# Repo kökündeki .env dosyasını yükle (server/app/ayarlar.py -> iki üst klasör)
KOK = Path(__file__).resolve().parents[2]
load_dotenv(KOK / ".env")


def _liste(deger: str) -> list[str]:
    return [p.strip() for p in deger.split(",") if p.strip()]


# Asistanın okuyacağı kanallar. Listede olmayan kanal okunmaz (varsayılan: hiçbiri).
IZINLI_KANALLAR = _liste(os.getenv("IZINLI_KANALLAR", ""))

# Arayüzün çalıştığı adres(ler); tarayıcı yalnızca buradan sunucuya istek atabilir.
ARAYUZ_ADRESLERI = _liste(os.getenv("ARAYUZ_ADRESLERI", "http://localhost:5173"))

# Yapay zekâ sağlayıcısı: 'gemini' ya da 'sahte' (varsayılan: 'sahte')
AI_SAGLAYICI = os.getenv("AI_SAGLAYICI", "sahte").strip().lower()

# Gizli Gemini API anahtarı (Loglara, hata mesajlarına, ekrana asla yazılmaz)
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "").strip()

# Gemini model adı ve zaman aşımı süresi (saniye)
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-3.5-flash-lite").strip()
AI_ZAMAN_ASIMI_SN = float(os.getenv("AI_ZAMAN_ASIMI_SN", "30"))