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

# SQLite veritabanı dosyası. Göreli yol repo köküne göre çözülür (boşsa varsayılan kullanılır).
VERITABANI_YOLU = KOK / (os.getenv("VERITABANI_YOLU") or "server/agentstack.db")
