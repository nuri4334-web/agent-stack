"""S1-05: veri seçimi kuralları ve sorgusu."""
import pytest

from app import ayarlar
from app.veri_secimi.kurallar import (
    MESAJ_SINIRI, hedef_kanallari_bul, slack_etiketlerini_coz, soruda_gecen_kanallar, yazan_adi,
)
from app.veri_secimi import secim as secim_modulu
from app.veri_secimi.secim import mesajlari_sec
from app.veritabani.tablolar import baglan, tablolari_olustur

DEV, GENEL, YONETIM = "C0C83M051QD", "C0C8ATRM073", "C0CB44VUCF2"
KANALLAR = [(DEV, "dev", "izinli"), (GENEL, "genel", "izinli"), (YONETIM, "yonetim", "izinli"),
            ("C0ESKI00001", "eski", "hariç")]


@pytest.fixture
def seedli():
    baglanti = baglan(ayarlar.VERITABANI_YOLU)
    yield baglanti
    baglanti.close()


def _haric_kanal_ekle(baglanti):
    with baglanti:
        baglanti.execute("INSERT INTO kanallar (slack_id, ad, ozel_mi, durum) VALUES ('C0ESKI00001', 'eski', 0, 'hariç')")
        baglanti.execute(
            "INSERT INTO mesajlar (kanal_id, ts, yazan_id, zaman, temiz_metin) "
            "VALUES ('C0ESKI00001', '1792665999.000001', 'U0CA5HH3M1V', '2026-10-22T10:46:39+00:00', 'TEST - hariç mesaj')"
        )


@pytest.mark.parametrize("soru, beklenen", [
    ("#dev'i özetle", ["dev"]),
    ("#yonetim'de neler var?", ["yonetim"]),
    ("#DEV ne durumda", ["dev"]),
    ("#dev, sonra", ["dev"]),
])
def test_hashli_kanal_adi_turkce_ekle_taniniyor(soru, beklenen):
    assert soruda_gecen_kanallar(soru) == beklenen


@pytest.mark.parametrize("soru", ["genel olarak neler oldu", "yonetim hakkında", "dev bir sorun var"])
def test_hashsiz_kanal_adi_taninmaz_butun_izinli_kanallara_gider(soru):
    assert soruda_gecen_kanallar(soru) == []
    assert hedef_kanallari_bul(soru, KANALLAR) == ("tamam", [DEV, GENEL, YONETIM])


@pytest.mark.parametrize("soru", ["PR #17 ne durumda", "#1 öncelik ne?", "#17'yi kim aldı"])
def test_yalnizca_rakamli_hash_kanal_adi_sayilmaz(soru):
    assert soruda_gecen_kanallar(soru) == []
    assert hedef_kanallari_bul(soru, KANALLAR) == ("tamam", [DEV, GENEL, YONETIM])


def test_birden_fazla_kanal_adi_hepsi_sirayla():
    assert soruda_gecen_kanallar("#genel ve #dev, bir de #genel") == ["genel", "dev"]
    assert hedef_kanallari_bul("#genel ve #dev", KANALLAR) == ("tamam", [GENEL, DEV])


def test_hedef_kanal_karari():
    assert hedef_kanallari_bul("#dev", []) == ("slack_verisi_yok", [])
    for soru in ("#bugs neler var", "#ik'i özetle", "#eski kanalı", "#dev ve #ik"):
        assert hedef_kanallari_bul(soru, KANALLAR) == ("kanal_izinli_degil", [])
    assert hedef_kanallari_bul("neler oldu?", KANALLAR) == ("tamam", [DEV, GENEL, YONETIM])


def test_yazan_adi_sirasi():
    assert yazan_adi("Ali Kaya", "ali", "U1") == "Ali Kaya"
    assert yazan_adi(None, "ali", "U1") == "ali"
    assert yazan_adi("  ", "", "U1") == "U1"


def test_slack_etiketleri_okunur_ada_cevriliyor():
    kullanicilar = {"U0CA5HH3M1V": "Ali Kaya"}
    kanallar = {YONETIM: "yonetim"}
    metin = ("<@U0CA5HH3M1V> ve <@U0CA5HH3M1V|ali> bak <#C0CB44VUCF2> <#C0CB44VUCF2|baska> "
             "<@U0BILINMEZ1> <#C0BILINMEZ1> <tel:+905000000000|+90 500> <https://ornek.test|link> <!here>")
    assert slack_etiketlerini_coz(metin, kullanicilar, kanallar) == (
        "@Ali Kaya ve @Ali Kaya bak #yonetim #yonetim "
        "<@U0BILINMEZ1> <#C0BILINMEZ1> <tel:+905000000000|+90 500> <https://ornek.test|link> <!here>"
    )


def test_dev_secimi_yalnizca_dev_eskiden_yeniye(seedli):
    secim = mesajlari_sec(seedli, "#dev'i özetle")
    assert secim.sonuc == "tamam"
    assert len(secim.mesajlar) == 27
    assert {m.kanal for m in secim.mesajlar} == {"dev"}
    zamanlar = [m.zaman for m in secim.mesajlar]
    assert zamanlar == sorted(zamanlar)
    assert not any("<@U" in m.metin for m in secim.mesajlar)


def test_ad_yoksa_yalnizca_izinli_kanallar(seedli):
    _haric_kanal_ekle(seedli)
    secim = mesajlari_sec(seedli, "geçen hafta neler oldu?")
    assert secim.sonuc == "tamam"
    assert len(secim.mesajlar) == 39
    assert {m.kanal for m in secim.mesajlar} == {"dev", "genel", "yonetim"}


def test_haric_kanal_sorgu_katmaninda_da_okunmaz(seedli, monkeypatch):
    _haric_kanal_ekle(seedli)
    # Hedef kararı yanlış olsa bile (hariç kanal listede) sorgu hariç kanalı döndürmez.
    monkeypatch.setattr(secim_modulu, "hedef_kanallari_bul", lambda soru, k: ("tamam", ["C0ESKI00001", DEV]))
    secim = mesajlari_sec(seedli, "herhangi")
    assert {m.kanal for m in secim.mesajlar} == {"dev"}
    assert not any("hariç mesaj" in m.metin for m in secim.mesajlar)


def test_elli_mesaj_siniri_en_yeni_elli():
    assert MESAJ_SINIRI == 50
    baglanti = baglan(":memory:")
    tablolari_olustur(baglanti)
    with baglanti:
        baglanti.execute("INSERT INTO slack_kullanicilari (slack_id, gercek_ad) VALUES ('U1', 'TEST - Kişi')")
        baglanti.execute("INSERT INTO kanallar (slack_id, ad, ozel_mi, durum) VALUES ('C1', 'dev', 0, 'izinli')")
        for i in range(1, 61):
            baglanti.execute(
                "INSERT INTO mesajlar (kanal_id, ts, yazan_id, zaman, temiz_metin) VALUES ('C1', ?, 'U1', ?, ?)",
                (f"{1792000000 + i}.000000", f"2026-10-22T10:{i // 60:02d}:{i % 60:02d}+00:00", f"mesaj {i}"),
            )
    secim = mesajlari_sec(baglanti, "#dev'i özetle")
    baglanti.close()
    assert len(secim.mesajlar) == 50
    assert [m.metin for m in secim.mesajlar] == [f"mesaj {i}" for i in range(11, 61)]


def test_izinli_kanalda_mesaj_yoksa_bos_liste():
    baglanti = baglan(":memory:")
    tablolari_olustur(baglanti)
    with baglanti:
        baglanti.execute("INSERT INTO kanallar (slack_id, ad, ozel_mi, durum) VALUES ('C1', 'dev', 0, 'izinli')")
    secim = mesajlari_sec(baglanti, "#dev'i özetle")
    baglanti.close()
    assert secim.sonuc == "tamam"
    assert secim.mesajlar == []
