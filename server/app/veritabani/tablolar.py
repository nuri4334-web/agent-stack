"""Tablolar (S1-03): şema, bağlantı ve tablo oluşturma.

Mesajlarda ham metin alanı yoktur; olay kaydında mesaj metni ya da serbest metin yoktur.
Açıklamalar: docs/veri-yapisi.md
"""
import sqlite3
from pathlib import Path

from .. import ayarlar

# Koddaki şema sürümü (PRAGMA user_version).
SEMA_SURUMU = 1

# STRICT tablolar için gereken en düşük SQLite sürümü.
EN_DUSUK_SQLITE = (3, 37, 0)

# Zaman sütunlarında varsayılan yok: zamanı her zaman çağıran verir (ISO 8601 metin).
SEMA_SQL = """
CREATE TABLE IF NOT EXISTS kisiler (
    id          INTEGER PRIMARY KEY,
    gorunen_ad  TEXT NOT NULL CHECK (length(trim(gorunen_ad)) > 0),
    rol         TEXT NOT NULL DEFAULT 'kullanici' CHECK (rol IN ('kullanici', 'admin'))
) STRICT;

CREATE TABLE IF NOT EXISTS bagli_hesaplar (
    id               INTEGER PRIMARY KEY,
    kisi_id          INTEGER NOT NULL REFERENCES kisiler (id),
    kaynak           TEXT NOT NULL CHECK (kaynak IN ('slack', 'jira', 'github')),
    kaynak_kimligi   TEXT NOT NULL CHECK (length(kaynak_kimligi) > 0),
    baglanma_sekli   TEXT NOT NULL CHECK (baglanma_sekli IN ('yonetici', 'kendisi')),
    baglanma_zamani  TEXT NOT NULL,
    UNIQUE (kaynak, kaynak_kimligi),
    UNIQUE (kisi_id, kaynak)
) STRICT;

CREATE TABLE IF NOT EXISTS slack_kullanicilari (
    slack_id    TEXT PRIMARY KEY CHECK (length(slack_id) > 0),
    gorunen_ad  TEXT,
    gercek_ad   TEXT,
    bot_mu      INTEGER NOT NULL DEFAULT 0 CHECK (bot_mu IN (0, 1))
) STRICT;

CREATE TABLE IF NOT EXISTS kanallar (
    slack_id  TEXT PRIMARY KEY CHECK (length(slack_id) > 0),
    ad        TEXT NOT NULL CHECK (length(ad) > 0),
    ozel_mi   INTEGER NOT NULL CHECK (ozel_mi IN (0, 1)),
    durum     TEXT NOT NULL DEFAULT 'hariç' CHECK (durum IN ('izinli', 'hariç')),
    CHECK (NOT (lower(ad) = 'ik' AND durum = 'izinli'))
) STRICT;

CREATE TABLE IF NOT EXISTS kanal_uyelikleri (
    kanal_id            TEXT NOT NULL REFERENCES kanallar (slack_id),
    slack_kullanici_id  TEXT NOT NULL REFERENCES slack_kullanicilari (slack_id),
    guncelleme_zamani   TEXT NOT NULL,
    PRIMARY KEY (kanal_id, slack_kullanici_id)
) STRICT;
CREATE INDEX IF NOT EXISTS kanal_uyelikleri_kullanici
    ON kanal_uyelikleri (slack_kullanici_id);

CREATE TABLE IF NOT EXISTS mesajlar (
    id           INTEGER PRIMARY KEY,
    kanal_id     TEXT NOT NULL REFERENCES kanallar (slack_id),
    ts           TEXT NOT NULL CHECK (
                     length(ts) = 17
                     AND ts GLOB '[0-9][0-9][0-9][0-9][0-9][0-9][0-9][0-9][0-9][0-9].[0-9][0-9][0-9][0-9][0-9][0-9]'
                 ),
    yazan_id     TEXT NOT NULL REFERENCES slack_kullanicilari (slack_id),
    zaman        TEXT NOT NULL,
    temiz_metin  TEXT NOT NULL,
    supheli      INTEGER CHECK (supheli IS NULL OR supheli IN (0, 1)),
    UNIQUE (kanal_id, ts)
) STRICT;
CREATE INDEX IF NOT EXISTS mesajlar_kanal_zaman ON mesajlar (kanal_id, zaman);

CREATE TABLE IF NOT EXISTS olay_kayitlari (
    id                 INTEGER PRIMARY KEY,
    zaman              TEXT NOT NULL,
    istek_id           TEXT NOT NULL CHECK (
                           length(istek_id) BETWEEN 1 AND 64
                           AND istek_id NOT GLOB '*[^0-9a-f]*'
                       ),
    kisi_id            INTEGER REFERENCES kisiler (id),
    adim               TEXT NOT NULL CHECK (adim IN (
                           'kimlik', 'yetki', 'veri_secimi', 'temizlik',
                           'yapay_zekaya_sor', 'cevap_kontrolu', 'gosterim',
                           'slack_cekme')),
    karar              TEXT NOT NULL CHECK (karar IN ('gecti', 'durdu', 'tamam', 'hata')),
    sebep_kodu         TEXT CHECK (
                           sebep_kodu IS NULL OR (
                               length(sebep_kodu) BETWEEN 1 AND 40
                               AND sebep_kodu NOT GLOB '*[^A-Z0-9_]*')
                       ),
    kanal_id           TEXT REFERENCES kanallar (slack_id),
    mesaj_sayisi       INTEGER NOT NULL DEFAULT 0 CHECK (mesaj_sayisi >= 0),
    kanal_sayisi       INTEGER NOT NULL DEFAULT 0 CHECK (kanal_sayisi >= 0),
    kullanici_sayisi   INTEGER NOT NULL DEFAULT 0 CHECK (kullanici_sayisi >= 0),
    uyelik_sayisi      INTEGER NOT NULL DEFAULT 0 CHECK (uyelik_sayisi >= 0),
    engellenen_sayisi  INTEGER NOT NULL DEFAULT 0 CHECK (engellenen_sayisi >= 0),
    maskelenen_sayisi  INTEGER NOT NULL DEFAULT 0 CHECK (maskelenen_sayisi >= 0),
    supheli_sayisi     INTEGER NOT NULL DEFAULT 0 CHECK (supheli_sayisi >= 0),
    sure_ms            REAL NOT NULL CHECK (sure_ms >= 0)
) STRICT;
CREATE INDEX IF NOT EXISTS olay_kayitlari_istek ON olay_kayitlari (istek_id);

CREATE TABLE IF NOT EXISTS yapay_zeka_cagrilari (
    id                       INTEGER PRIMARY KEY,
    zaman                    TEXT NOT NULL,
    istek_id                 TEXT NOT NULL CHECK (
                                 length(istek_id) BETWEEN 1 AND 64
                                 AND istek_id NOT GLOB '*[^0-9a-f]*'
                             ),
    model                    TEXT NOT NULL CHECK (
                                 length(model) BETWEEN 1 AND 100
                                 AND model NOT GLOB '*[^A-Za-z0-9._-]*'
                             ),
    sonuc                    TEXT NOT NULL CHECK (
                                 sonuc IN ('tamam', 'saglayici_hatasi', 'zaman_asimi')
                             ),
    gonderilen_mesaj_sayisi  INTEGER NOT NULL CHECK (gonderilen_mesaj_sayisi >= 0),
    sure_ms                  REAL NOT NULL CHECK (sure_ms >= 0),
    girdi_token              INTEGER CHECK (girdi_token IS NULL OR girdi_token >= 0),
    cikti_token              INTEGER CHECK (cikti_token IS NULL OR cikti_token >= 0)
) STRICT;
CREATE INDEX IF NOT EXISTS yapay_zeka_cagrilari_istek ON yapay_zeka_cagrilari (istek_id);
"""


def baglan(yol: str | Path = ayarlar.VERITABANI_YOLU) -> sqlite3.Connection:
    """Bağlantı açar ve yabancı anahtar kontrolünü açar. Testler ":memory:" verir."""
    if sqlite3.sqlite_version_info < EN_DUSUK_SQLITE:
        raise RuntimeError(
            f"SQLite sürümü çok eski ({sqlite3.sqlite_version}); en az 3.37.0 gerekir."
        )
    baglanti = sqlite3.connect(yol)
    baglanti.execute("PRAGMA foreign_keys = ON")
    if baglanti.execute("PRAGMA foreign_keys").fetchone()[0] != 1:
        baglanti.close()
        raise RuntimeError("Yabancı anahtar kontrolü açılamadı.")
    return baglanti


def tablolari_olustur(baglanti: sqlite3.Connection) -> None:
    """Tabloları tek işlemde oluşturur. İki kez çalıştırmak güvenlidir; var olan satırlara dokunmaz."""
    surum = baglanti.execute("PRAGMA user_version").fetchone()[0]
    if surum > SEMA_SURUMU:
        raise RuntimeError(
            f"Veritabanının şema sürümü ({surum}) koddakinden ({SEMA_SURUMU}) daha yeni."
        )
    try:
        baglanti.executescript(
            f"BEGIN;\n{SEMA_SQL}\nPRAGMA user_version = {SEMA_SURUMU};\nCOMMIT;"
        )
    except sqlite3.Error:
        if baglanti.in_transaction:
            baglanti.rollback()
        raise
