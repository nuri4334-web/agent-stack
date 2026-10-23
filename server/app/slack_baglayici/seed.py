"""Başlangıç verisi (seed, S1-04): çekilen Slack verisini JSON'a aktarır ve boş bir veritabanına yükler.

Çalıştırma (server/ içinde):
  .venv/Scripts/python -m app.slack_baglayici.seed disa-aktar [--dosya YOL] [--uzerine-yaz]
  .venv/Scripts/python -m app.slack_baglayici.seed yukle [--dosya YOL]

Dosyaya yalnızca izinli kanallar, onların üyelikleri ve mesajları, bunların andığı kullanıcılar girer.
Olay kaydı, yapay zekâ çağrıları, kişiler ve bağlı hesaplar girmez.
Gizli bilgi kontrolü: çekmede kullanılan token dosyada geçemez; token kalıplarına uyan her metin "EXAMPLE" içermelidir.
"""
import argparse
import json
import re
import sqlite3
import sys
from collections.abc import Callable, Iterable
from datetime import datetime, timezone
from pathlib import Path

from .. import ayarlar
from ..veritabani.kurallar import IZINLI, kanal_durumu
from ..veritabani.tablolar import baglan, tablolari_olustur
from .donusum import ts_gecerli_mi

BICIM = "agentstack-slack-seed"
SURUM = 1
SEED_YOLU = ayarlar.KOK / "demo-verisi" / "slack-baslangic-verisi.json"

# Bu kalıplara uyan her eşleşme "EXAMPLE" içermek zorunda (demo verisindeki sahte anahtarlar böyle).
SIR_KALIPLARI = {
    "slack_token": re.compile(r"xox[a-z]-[A-Za-z0-9-]+"),
    "github_token": re.compile(r"ghp_[A-Za-z0-9]+"),
    "google_api_anahtari": re.compile(r"AIza[A-Za-z0-9_-]+"),
    "aws_erisim_anahtari": re.compile(r"AKIA[A-Z0-9]+"),
}

SLACK_TABLOLARI = ("kanallar", "slack_kullanicilari", "kanal_uyelikleri", "mesajlar")


class SeedHatasi(ValueError):
    """Seed yazılamadı ya da okunamadı. Mesajında gizli bilgi ya da mesaj metni olmaz."""


def _kimlik(d: object) -> bool:
    return isinstance(d, str) and len(d) > 0


def _metin_ya_da_bos(d: object) -> bool:
    return d is None or isinstance(d, str)


def _bit(d: object) -> bool:
    return type(d) is int and d in (0, 1)


def _metin(d: object) -> bool:
    return isinstance(d, str)


# Her listedeki satırın alanları ve kontrolleri (fazla ya da eksik alan kabul edilmez).
ALANLAR = {
    "kanallar": {"slack_id": _kimlik, "ad": _kimlik, "ozel_mi": _bit},
    "slack_kullanicilari": {
        "slack_id": _kimlik, "gorunen_ad": _metin_ya_da_bos, "gercek_ad": _metin_ya_da_bos, "bot_mu": _bit,
    },
    "kanal_uyelikleri": {"kanal_id": _kimlik, "slack_kullanici_id": _kimlik},
    "mesajlar": {
        "kanal_id": _kimlik, "ts": ts_gecerli_mi, "yazan_id": _kimlik, "zaman": _kimlik, "temiz_metin": _metin,
    },
}


def gizli_bilgi_kontrolu(icerik: str, token: str = "") -> None:
    """Token değeri içerikte geçiyorsa ya da EXAMPLE içermeyen bir token kalıbı varsa SeedHatasi.

    Hata mesajı eşleşen metni göstermez, yalnızca kalıbın adını gösterir.
    """
    if token and token in icerik:
        raise SeedHatasi("Seed içeriğinde çekmede kullanılan Slack token'ı geçiyor.")
    for ad, kalip in SIR_KALIPLARI.items():
        for eslesme in kalip.finditer(icerik):
            if "EXAMPLE" not in eslesme.group():
                raise SeedHatasi(f"Seed içeriğinde EXAMPLE içermeyen bir gizli bilgi kalıbı var ({ad}).")


def _serilestir(veri: dict) -> str:
    return json.dumps(veri, ensure_ascii=False, indent=2, sort_keys=True) + "\n"


def _satirlar(baglanti, sql: str, parametreler=()) -> list[dict]:
    imlec = baglanti.execute(sql, parametreler)
    adlar = [s[0] for s in imlec.description]
    return [dict(zip(adlar, satir)) for satir in imlec.fetchall()]


def disa_aktar(baglanti: sqlite3.Connection) -> dict:
    """Veritabanındaki izinli kanalları, üyeliklerini, mesajlarını ve andıkları kullanıcıları döndürür."""
    kanallar = _satirlar(
        baglanti, "SELECT slack_id, ad, ozel_mi FROM kanallar WHERE durum = ? ORDER BY slack_id", (IZINLI,),
    )
    uyelikler = _satirlar(
        baglanti,
        "SELECT u.kanal_id, u.slack_kullanici_id FROM kanal_uyelikleri u "
        "JOIN kanallar k ON k.slack_id = u.kanal_id WHERE k.durum = ? "
        "ORDER BY u.kanal_id, u.slack_kullanici_id",
        (IZINLI,),
    )
    mesajlar = _satirlar(
        baglanti,
        "SELECT m.kanal_id, m.ts, m.yazan_id, m.zaman, m.temiz_metin FROM mesajlar m "
        "JOIN kanallar k ON k.slack_id = m.kanal_id WHERE k.durum = ? ORDER BY m.kanal_id, m.ts",
        (IZINLI,),
    )
    anilan = {u["slack_kullanici_id"] for u in uyelikler} | {m["yazan_id"] for m in mesajlar}
    kullanicilar = [
        k for k in _satirlar(
            baglanti,
            "SELECT slack_id, gorunen_ad, gercek_ad, bot_mu FROM slack_kullanicilari ORDER BY slack_id",
        )
        if k["slack_id"] in anilan
    ]
    return {
        "bicim": BICIM, "surum": SURUM, "kanallar": kanallar, "slack_kullanicilari": kullanicilar,
        "kanal_uyelikleri": uyelikler, "mesajlar": mesajlar,
    }


def seed_dosyasi_yaz(veri: dict, yol: Path, *, uzerine_yaz: bool = False, token: str = "") -> None:
    """Seed'i JSON olarak (UTF-8, LF) yazar. Gizli bilgi kontrolünden geçmezse hiç yazmaz."""
    icerik = _serilestir(veri)
    gizli_bilgi_kontrolu(icerik, token)
    if yol.exists() and not uzerine_yaz:
        raise SeedHatasi(f"{yol.name} zaten var; üzerine yazmak için --uzerine-yaz kullanın.")
    with open(yol, "w", encoding="utf-8", newline="\n") as dosya:
        dosya.write(icerik)


def _dogrula(veri: object) -> None:
    if not isinstance(veri, dict) or veri.get("bicim") != BICIM or veri.get("surum") != SURUM:
        raise SeedHatasi(f"Seed dosyası geçersiz: bicim '{BICIM}' ve surum {SURUM} olmalı.")
    if set(veri) != {"bicim", "surum", *ALANLAR}:
        raise SeedHatasi("Seed dosyası geçersiz: beklenmeyen ya da eksik liste var.")
    for liste, kontroller in ALANLAR.items():
        satirlar = veri[liste]
        if not isinstance(satirlar, list):
            raise SeedHatasi(f"Seed dosyası geçersiz: {liste} bir liste olmalı.")
        for sira, satir in enumerate(satirlar):
            if not isinstance(satir, dict) or set(satir) != set(kontroller):
                raise SeedHatasi(f"Seed dosyası geçersiz: {liste}[{sira}] alanları hatalı.")
            for alan, kontrol in kontroller.items():
                if not kontrol(satir[alan]):
                    raise SeedHatasi(f"Seed dosyası geçersiz: {liste}[{sira}].{alan}")


def seed_oku(yol: Path, token: str = "") -> dict:
    """Seed dosyasını okur, biçimini ve gizli bilgi kontrolünü yapar."""
    try:
        ham = yol.read_text(encoding="utf-8")
    except OSError as hata:
        raise SeedHatasi(f"Seed dosyası okunamadı: {yol} ({type(hata).__name__})") from None
    gizli_bilgi_kontrolu(ham, token)
    try:
        veri = json.loads(ham)
    except json.JSONDecodeError:
        raise SeedHatasi("Seed dosyası geçerli JSON değil.") from None
    _dogrula(veri)
    # Kaçış dizileriyle (\u...) gizlenmiş metin de kontrol edilsin.
    gizli_bilgi_kontrolu(_serilestir(veri), token)
    return veri


def yukle(
    baglanti: sqlite3.Connection,
    veri: dict,
    izinli_kanallar: Iterable[str],
    simdi: Callable[[], datetime],
) -> dict[str, int]:
    """Seed'i boş veritabanına tek işlemde yükler. Kanal durumu yükleyenin izin listesiyle yeniden hesaplanır."""
    tablolari_olustur(baglanti)
    for tablo in SLACK_TABLOLARI:
        if baglanti.execute(f"SELECT count(*) FROM {tablo}").fetchone()[0]:
            raise SeedHatasi(
                "Veritabanı boş değil; yükleme yapılmadı. "
                "Yeni bir veritabanı için veritabanı dosyasını (server/agentstack.db) silin."
            )
    izinliler = list(izinli_kanallar)
    zaman = simdi().isoformat()
    sayilar = {"kanal": 0, "izinli_kanal": 0, "kullanici": 0, "uyelik": 0, "mesaj": 0}
    izinli_idler = set()
    try:
        with baglanti:
            for k in veri["slack_kullanicilari"]:
                baglanti.execute(
                    "INSERT INTO slack_kullanicilari (slack_id, gorunen_ad, gercek_ad, bot_mu) "
                    "VALUES (:slack_id, :gorunen_ad, :gercek_ad, :bot_mu)",
                    k,
                )
                sayilar["kullanici"] += 1
            for k in veri["kanallar"]:
                durum = kanal_durumu(k["ad"], izinliler)
                baglanti.execute(
                    "INSERT INTO kanallar (slack_id, ad, ozel_mi, durum) VALUES (?, ?, ?, ?)",
                    (k["slack_id"], k["ad"], k["ozel_mi"], durum),
                )
                sayilar["kanal"] += 1
                if durum == IZINLI:
                    izinli_idler.add(k["slack_id"])
            sayilar["izinli_kanal"] = len(izinli_idler)
            for u in veri["kanal_uyelikleri"]:
                if u["kanal_id"] in izinli_idler:
                    baglanti.execute(
                        "INSERT INTO kanal_uyelikleri (kanal_id, slack_kullanici_id, guncelleme_zamani) "
                        "VALUES (?, ?, ?)",
                        (u["kanal_id"], u["slack_kullanici_id"], zaman),
                    )
                    sayilar["uyelik"] += 1
            for m in veri["mesajlar"]:
                if m["kanal_id"] in izinli_idler:
                    baglanti.execute(
                        "INSERT INTO mesajlar (kanal_id, ts, yazan_id, zaman, temiz_metin) "
                        "VALUES (:kanal_id, :ts, :yazan_id, :zaman, :temiz_metin)",
                        m,
                    )
                    sayilar["mesaj"] += 1
    except sqlite3.IntegrityError:
        raise SeedHatasi("Seed dosyası tutarsız (eksik kullanıcı/kanal ya da tekrar eden satır); "
                         "yükleme yapılmadı.") from None
    return sayilar


def komutu_calistir(
    argv: list[str],
    *,
    veritabani_yolu: str | Path,
    izinli_kanallar: Iterable[str],
    simdi: Callable[[], datetime],
    yaz: Callable[[str], None],
    token: str = "",
) -> int:
    """Komut satırı. Çıkış: 0 tamam, 1 hata, 2 hatalı kullanım."""
    ayristirici = argparse.ArgumentParser(
        prog="python -m app.slack_baglayici.seed", description="Slack başlangıç verisi (seed).",
    )
    alt = ayristirici.add_subparsers(dest="komut", required=True)
    disa = alt.add_parser("disa-aktar", help="Veritabanındaki izinli kanal verisini JSON'a yazar.")
    disa.add_argument("--dosya", type=Path, default=SEED_YOLU)
    disa.add_argument("--uzerine-yaz", action="store_true", help="Var olan dosyanın üzerine yazar.")
    yuk = alt.add_parser("yukle", help="JSON dosyasını boş veritabanına yükler.")
    yuk.add_argument("--dosya", type=Path, default=SEED_YOLU)
    try:
        argumanlar = ayristirici.parse_args(argv)
    except SystemExit as cikis:
        return 0 if cikis.code == 0 else 2

    try:
        if argumanlar.komut == "disa-aktar":
            baglanti = baglan(veritabani_yolu)
            try:
                tablolari_olustur(baglanti)
                veri = disa_aktar(baglanti)
            finally:
                baglanti.close()
            if not veri["kanallar"]:
                yaz("Veritabanında izinli kanal yok; önce 'python -m app.slack_baglayici.cek' çalıştırın.")
                return 1
            seed_dosyasi_yaz(veri, argumanlar.dosya, uzerine_yaz=argumanlar.uzerine_yaz, token=token)
            yaz(f"{argumanlar.dosya} yazıldı: {len(veri['kanallar'])} kanal, "
                f"{len(veri['slack_kullanicilari'])} kullanıcı, {len(veri['kanal_uyelikleri'])} üyelik, "
                f"{len(veri['mesajlar'])} mesaj.")
            return 0

        veri = seed_oku(argumanlar.dosya, token)
        baglanti = baglan(veritabani_yolu)
        try:
            tablolari_olustur(baglanti)
            sayilar = yukle(baglanti, veri, izinli_kanallar, simdi)
        finally:
            baglanti.close()
        yaz(f"Yüklendi: {sayilar['kanal']} kanal (izinli {sayilar['izinli_kanal']}), "
            f"{sayilar['kullanici']} kullanıcı, {sayilar['uyelik']} üyelik, {sayilar['mesaj']} mesaj.")
        return 0
    except SeedHatasi as hata:
        yaz(f"HATA: {hata}")
        return 1


def main() -> None:
    sys.exit(komutu_calistir(
        sys.argv[1:],
        veritabani_yolu=ayarlar.VERITABANI_YOLU,
        izinli_kanallar=ayarlar.IZINLI_KANALLAR,
        simdi=lambda: datetime.now(timezone.utc),
        yaz=print,
        token=ayarlar.SLACK_BOT_TOKEN,
    ))


if __name__ == "__main__":
    main()
