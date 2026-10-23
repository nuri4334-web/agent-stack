"""Slack çekme (S1-04): kanallar, kullanıcılar, izinli kanalların üyeleri ve son N günün mesajları.

Çalıştırma (server/ içinde): .venv/Scripts/python -m app.slack_baglayici.cek [--gun 30] [--sifirdan]

- İzin listesi her kanal isteğinden ÖNCE yeniden kontrol edilir: "hariç" kanal için Slack'e istek yapılmaz.
- Aynı mesaj (kanal + ts) ikinci kez yazılmaz; komutu tekrar çalıştırmak güvenlidir.
- Bir kanal hata verirse olay kaydına yazılır ve diğer kanallarla devam edilir.
- Token hiçbir çıktıya, olay kaydına ya da hata mesajına yazılmaz.
"""
import argparse
import sqlite3
import sys
import time
import uuid
from collections import Counter
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from .. import ayarlar
from ..olay_kaydi.kayit import olay_yaz
from ..veritabani.kurallar import HARIC, IZINLI, kanal_durumu
from ..veritabani.tablolar import baglan, tablolari_olustur
from . import temizlik
from .donusum import atlama_nedeni, en_eski_ts, kanal_satiri, kullanici_satiri, ts_zamani
from .istemci import HttpxSlackIstemcisi, SlackHatasi, SlackIstemcisi, sayfa_sayfa

ADIM = "slack_cekme"
VARSAYILAN_GUN = 30
EN_AZ_GUN = 1
EN_FAZLA_GUN = 365
SAYFA_BOYUTU = "200"


@dataclass
class KanalSonucu:
    """Bir kanalın bu çalıştırmadaki sonucu. Mesaj metni taşımaz."""

    ad: str
    durum: str  # "tamam", "hata" ya da "hariç"
    yeni_mesaj: int = 0
    cekilen_mesaj: int = 0
    atlanan: Counter = field(default_factory=Counter)  # atlama nedeni (alt tür adı) -> sayı
    uye_sayisi: int = 0
    silinen_mesaj: int = 0
    sebep_kodu: str | None = None
    hata_detayi: str | None = None


@dataclass
class CekmeOzeti:
    calisma_id: str
    gun: int
    kanal_sayisi: int = 0
    kullanici_sayisi: int = 0
    uyelik_sayisi: int = 0
    mesaj_sayisi: int = 0
    kanallar: list[KanalSonucu] = field(default_factory=list)
    baslayamadi: str | None = None  # liste çekilemediyse sebep kodu
    hata_detayi: str | None = None

    @property
    def hata_var(self) -> bool:
        return self.baslayamadi is not None or any(k.durum == "hata" for k in self.kanallar)


def _sure_ms(olcer: Callable[[], float], bas: float) -> float:
    return round(max(olcer() - bas, 0.0) * 1000, 2)


def _hata_detayi(hata: Exception) -> str:
    if isinstance(hata, SlackHatasi):
        return f"Slack: {hata.kod}"
    if isinstance(hata, sqlite3.Error):
        return f"veritabanı: {type(hata).__name__}"
    return "Slack: gecersiz_cevap"


def _hata_kaydi(baglanti, *, simdi, calisma_id, sebep_kodu, sure_ms, kanal_id=None) -> None:
    with baglanti:
        olay_yaz(
            baglanti, zaman=simdi().isoformat(), istek_id=calisma_id, adim=ADIM, karar="hata",
            sebep_kodu=sebep_kodu, kanal_id=kanal_id, sure_ms=sure_ms,
        )


def _baslayamadi(baglanti, ozet: CekmeOzeti, sebep_kodu: str, hata: Exception, *, simdi, sure_ms) -> CekmeOzeti:
    _hata_kaydi(baglanti, simdi=simdi, calisma_id=ozet.calisma_id, sebep_kodu=sebep_kodu, sure_ms=sure_ms)
    ozet.baslayamadi = sebep_kodu
    ozet.hata_detayi = _hata_detayi(hata)
    return ozet


def _listeleri_yaz(baglanti, kanallar, kullanicilar, *, sifirdan: bool) -> dict[str, KanalSonucu]:
    """Kullanıcıları ve kanalları tek işlemde yazar; hariç kanalların mesaj ve üyeliklerini siler."""
    gorulen = {satir["slack_id"] for satir, _ in kanallar}
    onceki_izinli = {s[0] for s in baglanti.execute(
        "SELECT slack_id FROM kanallar WHERE durum = ?", (IZINLI,)
    )}
    sonuclar: dict[str, KanalSonucu] = {}
    with baglanti:
        if sifirdan:
            baglanti.execute("DELETE FROM kanal_uyelikleri")
            baglanti.execute("DELETE FROM mesajlar")
        for k in kullanicilar:
            baglanti.execute(
                "INSERT INTO slack_kullanicilari (slack_id, gorunen_ad, gercek_ad, bot_mu) "
                "VALUES (:slack_id, :gorunen_ad, :gercek_ad, :bot_mu) "
                "ON CONFLICT (slack_id) DO UPDATE SET gorunen_ad = excluded.gorunen_ad, "
                "gercek_ad = excluded.gercek_ad, bot_mu = excluded.bot_mu",
                k,
            )
        for satir, _ in kanallar:
            baglanti.execute(
                "INSERT INTO kanallar (slack_id, ad, ozel_mi, durum) "
                "VALUES (:slack_id, :ad, :ozel_mi, :durum) "
                "ON CONFLICT (slack_id) DO UPDATE SET ad = excluded.ad, "
                "ozel_mi = excluded.ozel_mi, durum = excluded.durum",
                satir,
            )
        # Slack listesinde artık görünmeyen kanal (arşivlendi, silindi, bot çıkarıldı) okunmaz.
        for (slack_id,) in baglanti.execute("SELECT slack_id FROM kanallar").fetchall():
            if slack_id not in gorulen:
                baglanti.execute("UPDATE kanallar SET durum = ? WHERE slack_id = ?", (HARIC, slack_id))
        # Hariç kanalın eski verisi tutulmaz.
        for slack_id, ad in baglanti.execute(
            "SELECT slack_id, ad FROM kanallar WHERE durum = ?", (HARIC,)
        ).fetchall():
            baglanti.execute("DELETE FROM kanal_uyelikleri WHERE kanal_id = ?", (slack_id,))
            silinen = baglanti.execute("DELETE FROM mesajlar WHERE kanal_id = ?", (slack_id,)).rowcount
            if slack_id in gorulen or slack_id in onceki_izinli or silinen:
                sonuclar[slack_id] = KanalSonucu(ad=ad, durum=HARIC, silinen_mesaj=silinen)
    return sonuclar


def _kanali_cek(baglanti, istemci, satir, bot_uye, izinliler, *, oldest, simdi, calisma_id, olcer) -> KanalSonucu:
    bas = olcer()
    kanal_id = satir["slack_id"]
    sonuc = KanalSonucu(ad=satir["ad"], durum="tamam")

    def hata(sebep_kodu: str, detay: str) -> KanalSonucu:
        sonuc.durum, sonuc.sebep_kodu, sonuc.hata_detayi = "hata", sebep_kodu, detay
        _hata_kaydi(
            baglanti, simdi=simdi, calisma_id=calisma_id, sebep_kodu=sebep_kodu,
            sure_ms=_sure_ms(olcer, bas), kanal_id=kanal_id,
        )
        return sonuc

    # Savunma: istekten hemen önce durum Slack'teki güncel adla yeniden hesaplanır.
    if kanal_durumu(satir["ad"], izinliler) != IZINLI:
        sonuc.durum = HARIC
        return sonuc
    if not bot_uye:
        return hata("BOT_KANALDA_DEGIL", "bot kanalda değil; kanala davet edin")

    try:
        uyeler = sayfa_sayfa(
            istemci, "conversations.members", {"channel": kanal_id, "limit": SAYFA_BOYUTU}, "members",
        )
        if not all(isinstance(u, str) and u for u in uyeler):
            raise SlackHatasi("gecersiz_cevap")
        mesajlar = sayfa_sayfa(
            istemci, "conversations.history",
            {"channel": kanal_id, "oldest": oldest, "limit": SAYFA_BOYUTU}, "messages",
        )
    except SlackHatasi as h:
        return hata("KANAL_CEKILEMEDI", _hata_detayi(h))

    alinacak = []
    atlanan: Counter = Counter()
    for m in mesajlar:
        neden = atlama_nedeni(m)
        if neden:
            atlanan[neden] += 1
        else:
            alinacak.append(m)

    zaman = simdi().isoformat()
    uye_kumesi = set(uyeler)
    yeni = 0
    try:
        with baglanti:
            # Bilinmeyen üye ya da yazan için önce adları boş bir kullanıcı satırı.
            for kullanici_id in sorted(uye_kumesi | {m["user"] for m in alinacak}):
                baglanti.execute(
                    "INSERT INTO slack_kullanicilari (slack_id) VALUES (?) ON CONFLICT (slack_id) DO NOTHING",
                    (kullanici_id,),
                )
            for uye in sorted(uye_kumesi):
                baglanti.execute(
                    "INSERT INTO kanal_uyelikleri (kanal_id, slack_kullanici_id, guncelleme_zamani) "
                    "VALUES (?, ?, ?) ON CONFLICT (kanal_id, slack_kullanici_id) "
                    "DO UPDATE SET guncelleme_zamani = excluded.guncelleme_zamani",
                    (kanal_id, uye, zaman),
                )
            # Kanaldan çıkanların üyeliği silinir (bayat yetki kalmasın).
            for (eski,) in baglanti.execute(
                "SELECT slack_kullanici_id FROM kanal_uyelikleri WHERE kanal_id = ?", (kanal_id,)
            ).fetchall():
                if eski not in uye_kumesi:
                    baglanti.execute(
                        "DELETE FROM kanal_uyelikleri WHERE kanal_id = ? AND slack_kullanici_id = ?",
                        (kanal_id, eski),
                    )
            for m in alinacak:
                imlec = baglanti.execute(
                    "INSERT INTO mesajlar (kanal_id, ts, yazan_id, zaman, temiz_metin) "
                    "VALUES (?, ?, ?, ?, ?) ON CONFLICT (kanal_id, ts) DO NOTHING",
                    (kanal_id, m["ts"], m["user"], ts_zamani(m["ts"]), temizlik.temizle(m["text"])),
                )
                yeni += imlec.rowcount
    except sqlite3.Error as h:
        return hata("KANAL_YAZILAMADI", _hata_detayi(h))

    sonuc.yeni_mesaj = yeni
    sonuc.cekilen_mesaj = len(mesajlar)
    sonuc.atlanan = atlanan
    sonuc.uye_sayisi = len(uye_kumesi)
    return sonuc


def slack_cek(
    baglanti: sqlite3.Connection,
    istemci: SlackIstemcisi,
    izinli_kanallar: Iterable[str],
    *,
    gun: int,
    simdi: Callable[[], datetime],
    calisma_id: str,
    sifirdan: bool = False,
    olcer: Callable[[], float] = time.perf_counter,
) -> CekmeOzeti:
    """Kanalları, kullanıcıları, izinli kanalların üyelerini ve son gun günün mesajlarını çekip yazar."""
    tablolari_olustur(baglanti)
    izinliler = list(izinli_kanallar)
    bas = olcer()
    ozet = CekmeOzeti(calisma_id=calisma_id, gun=gun)

    # 1. Listeler: önce bütün sayfalar çekilir, sonra yazılır.
    try:
        kanallar = [
            (kanal_satiri(k, izinliler), k.get("is_member") is True)
            for k in sayfa_sayfa(
                istemci, "conversations.list",
                {"types": "public_channel,private_channel", "exclude_archived": "true",
                 "limit": SAYFA_BOYUTU},
                "channels",
            )
        ]
    except (SlackHatasi, ValueError) as h:
        return _baslayamadi(baglanti, ozet, "KANAL_LISTESI_CEKILEMEDI", h, simdi=simdi,
                            sure_ms=_sure_ms(olcer, bas))
    try:
        kullanicilar = [
            kullanici_satiri(k)
            for k in sayfa_sayfa(istemci, "users.list", {"limit": SAYFA_BOYUTU}, "members")
        ]
    except (SlackHatasi, ValueError) as h:
        return _baslayamadi(baglanti, ozet, "KULLANICI_LISTESI_CEKILEMEDI", h, simdi=simdi,
                            sure_ms=_sure_ms(olcer, bas))

    # 2. Kullanıcılar, kanallar ve durumlar tek işlemde.
    try:
        sonuclar = _listeleri_yaz(baglanti, kanallar, kullanicilar, sifirdan=sifirdan)
    except sqlite3.Error as h:
        return _baslayamadi(baglanti, ozet, "VERITABANI_YAZILAMADI", h, simdi=simdi,
                            sure_ms=_sure_ms(olcer, bas))
    ozet.kullanici_sayisi = len(kullanicilar)

    # 3. İzinli kanallar, her biri kendi işleminde.
    oldest = en_eski_ts(simdi(), gun)
    for satir, bot_uye in sorted(kanallar, key=lambda k: k[0]["ad"]):
        if satir["durum"] != IZINLI:
            continue
        sonuclar[satir["slack_id"]] = _kanali_cek(
            baglanti, istemci, satir, bot_uye, izinliler,
            oldest=oldest, simdi=simdi, calisma_id=calisma_id, olcer=olcer,
        )

    # 4. Özet satırı.
    ozet.kanallar = sorted(sonuclar.values(), key=lambda s: s.ad)
    basarili = [s for s in ozet.kanallar if s.durum == "tamam"]
    ozet.kanal_sayisi = len(basarili)
    ozet.uyelik_sayisi = sum(s.uye_sayisi for s in basarili)
    ozet.mesaj_sayisi = sum(s.yeni_mesaj for s in basarili)
    with baglanti:
        olay_yaz(
            baglanti, zaman=simdi().isoformat(), istek_id=calisma_id, adim=ADIM, karar="tamam",
            sebep_kodu="BAZI_KANALLAR_CEKILEMEDI" if ozet.hata_var else None,
            sure_ms=_sure_ms(olcer, bas),
            kanal_sayisi=ozet.kanal_sayisi, kullanici_sayisi=ozet.kullanici_sayisi,
            uyelik_sayisi=ozet.uyelik_sayisi, mesaj_sayisi=ozet.mesaj_sayisi,
        )
    return ozet


def _kanal_satiri_metni(s: KanalSonucu, genislik: int) -> str:
    ad = f"#{s.ad}".ljust(genislik)
    if s.durum == HARIC:
        ek = f", {s.silinen_mesaj} eski mesaj silindi" if s.silinen_mesaj else ""
        return f"{ad} hariç  (hiç istek yapılmadı{ek})"
    if s.durum == "hata":
        return f"{ad} HATA   {s.sebep_kodu} ({s.hata_detayi})"
    atlanan = sum(s.atlanan.values())
    dagilim = ""
    if atlanan:
        sirali = sorted(s.atlanan.items(), key=lambda x: (-x[1], x[0]))
        dagilim = ": " + ", ".join(f"{neden} {sayi}" for neden, sayi in sirali)
    return (f"{ad} tamam  {s.yeni_mesaj} yeni / {s.cekilen_mesaj} çekildi / "
            f"{atlanan} atlandı{dagilim} · {s.uye_sayisi} üye")


def ozeti_yaz(ozet: CekmeOzeti, yaz: Callable[[str], None]) -> None:
    """Çalışmanın sonucunu ekrana yazar: kanal başına mesaj sayıları. Mesaj metni yazılmaz."""
    if ozet.baslayamadi:
        yaz(f"HATA {ozet.baslayamadi} ({ozet.hata_detayi}). Hiçbir kanal çekilmedi.")
        return
    izinli = sum(1 for s in ozet.kanallar if s.durum != HARIC)
    yaz(f"Kullanıcı: {ozet.kullanici_sayisi} · Kanal: {len(ozet.kanallar)} "
        f"(izinli {izinli}, hariç {len(ozet.kanallar) - izinli})")
    genislik = max((len(s.ad) for s in ozet.kanallar), default=0) + 1
    for s in ozet.kanallar:
        yaz(_kanal_satiri_metni(s, genislik))
    yaz(f"Özet: {ozet.kanal_sayisi} kanal, {ozet.kullanici_sayisi} kullanıcı, "
        f"{ozet.uyelik_sayisi} üyelik, {ozet.mesaj_sayisi} yeni mesaj. Olay kaydına yazıldı.")


def komutu_calistir(
    argv: list[str],
    *,
    token: str,
    istemci_uret: Callable[[str], SlackIstemcisi],
    veritabani_yolu: str | Path,
    izinli_kanallar: Iterable[str],
    simdi: Callable[[], datetime],
    yaz: Callable[[str], None],
    calisma_id_uret: Callable[[], str] = lambda: uuid.uuid4().hex,
) -> int:
    """Komut satırı. Çıkış: 0 hepsi tamam, 1 en az bir kanal hatalı, 2 başlayamadı."""
    ayristirici = argparse.ArgumentParser(
        prog="python -m app.slack_baglayici.cek",
        description="Slack'ten kanal, kullanıcı, üyelik ve mesaj çeker.",
    )
    ayristirici.add_argument("--gun", type=int, default=VARSAYILAN_GUN,
                             help=f"Son kaç günün mesajları (varsayılan {VARSAYILAN_GUN}, "
                                  f"en az {EN_AZ_GUN}, en fazla {EN_FAZLA_GUN}).")
    ayristirici.add_argument("--sifirdan", action="store_true",
                             help="Çekmeden önce bütün mesajları ve üyelikleri siler.")
    try:
        argumanlar = ayristirici.parse_args(argv)
    except SystemExit as cikis:
        return 0 if cikis.code == 0 else 2

    if not EN_AZ_GUN <= argumanlar.gun <= EN_FAZLA_GUN:
        yaz(f"--gun en az {EN_AZ_GUN}, en fazla {EN_FAZLA_GUN} olabilir.")
        return 2
    if not token:
        yaz("SLACK_BOT_TOKEN .env içinde boş. Bot anahtarın yoksa "
            "'python -m app.slack_baglayici.seed yukle' komutunu kullan.")
        return 2

    istemci = istemci_uret(token)
    baglanti = baglan(veritabani_yolu)
    try:
        tablolari_olustur(baglanti)
        calisma_id = calisma_id_uret()
        sifirdan_notu = ", önce mesajlar ve üyelikler silinecek" if argumanlar.sifirdan else ""
        yaz(f"Slack çekme başladı (son {argumanlar.gun} gün{sifirdan_notu}). Çalışma: {calisma_id[:12]}")
        ozet = slack_cek(
            baglanti, istemci, izinli_kanallar, gun=argumanlar.gun, simdi=simdi,
            calisma_id=calisma_id, sifirdan=argumanlar.sifirdan,
        )
    finally:
        baglanti.close()
        kapat = getattr(istemci, "kapat", None)
        if kapat:
            kapat()
    ozeti_yaz(ozet, yaz)
    if ozet.baslayamadi:
        return 2
    return 1 if ozet.hata_var else 0


def main() -> None:
    sys.exit(komutu_calistir(
        sys.argv[1:],
        token=ayarlar.SLACK_BOT_TOKEN,
        istemci_uret=lambda token: HttpxSlackIstemcisi(token, time.sleep),
        veritabani_yolu=ayarlar.VERITABANI_YOLU,
        izinli_kanallar=ayarlar.IZINLI_KANALLAR,
        simdi=lambda: datetime.now(timezone.utc),
        yaz=print,
    ))


if __name__ == "__main__":
    main()
