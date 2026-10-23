import logging

import httpx
import pytest

from app.slack_baglayici import cek, seed
from app.slack_baglayici.istemci import HttpxSlackIstemcisi, SlackHatasi
from app.veritabani.tablolar import baglan
from tests.sahte_slack import SIMDI, ts

TOKEN = "xoxb-EXAMPLE-0000-TEST"


def _istemci(isleyici):
    beklemeler = []
    istemci = HttpxSlackIstemcisi(TOKEN, beklemeler.append, transport=httpx.MockTransport(isleyici))
    return istemci, beklemeler


def test_429_da_retry_after_kadar_bekleyip_tekrar_deniyor():
    cevaplar = [
        httpx.Response(429, headers={"Retry-After": "3"}),
        httpx.Response(200, json={"ok": True, "channels": []}),
    ]
    istemci, beklemeler = _istemci(lambda istek: cevaplar.pop(0))
    assert istemci.cagir("conversations.list", {"limit": "200"}) == {"ok": True, "channels": []}
    assert beklemeler == [3]
    assert cevaplar == []


def test_429_surerse_ratelimited_hatasi():
    istekler = []

    def isleyici(istek):
        istekler.append(istek)
        return httpx.Response(429, headers={"Retry-After": "abc"})

    istemci, beklemeler = _istemci(isleyici)
    with pytest.raises(SlackHatasi) as hata:
        istemci.cagir("conversations.history", {"channel": "C1"})
    assert hata.value.kod == "ratelimited"
    assert len(istekler) == 5
    assert beklemeler == [5.0] * 4


def test_slack_hata_kodu_temizlenip_veriliyor():
    for cevap, beklenen in [
        (httpx.Response(200, json={"ok": False, "error": "not_in_channel"}), "not_in_channel"),
        (httpx.Response(200, json={"ok": False, "error": "Not In Channel! <script>"}), "bilinmeyen_hata"),
        (httpx.Response(200, json={"ok": False}), "bilinmeyen_hata"),
        (httpx.Response(500, text="sunucu"), "http_500"),
        (httpx.Response(200, text="json değil"), "gecersiz_cevap"),
    ]:
        istemci, _ = _istemci(lambda istek, c=cevap: c)
        with pytest.raises(SlackHatasi) as hata:
            istemci.cagir("users.list", {})
        assert hata.value.kod == beklenen
        assert str(hata.value) == beklenen


def test_token_hicbir_ciktida_yok(tmp_path, capsys, caplog):
    caplog.set_level(logging.DEBUG)
    istekler = []
    members_denemesi = []

    def isleyici(istek):
        istekler.append(istek)
        uc = istek.url.path.rsplit("/", 1)[-1]
        kanal = istek.url.params.get("channel")
        if uc == "conversations.list":
            return httpx.Response(200, json={"ok": True, "channels": [
                {"id": "C_DEV", "name": "dev", "is_private": False, "is_member": True},
                {"id": "C_GENEL", "name": "genel", "is_private": False, "is_member": True},
            ]})
        if uc == "users.list":
            return httpx.Response(200, json={"ok": True, "members": [{"id": "U_ALI"}]})
        if uc == "conversations.members":
            members_denemesi.append(kanal)
            if members_denemesi.count(kanal) == 1:
                return httpx.Response(429, headers={"Retry-After": "1"})
            return httpx.Response(200, json={"ok": True, "members": ["U_ALI"]})
        if uc == "conversations.history" and kanal == "C_DEV":
            return httpx.Response(200, json={"ok": True, "messages": [
                {"type": "message", "user": "U_ALI", "text": "login sayfası", "ts": ts(1)},
            ]})
        return httpx.Response(200, json={"ok": False, "error": "invalid_auth"})

    db_yolu = tmp_path / "test.db"
    beklemeler = []
    sonuc = cek.komutu_calistir(
        [], token=TOKEN,
        istemci_uret=lambda t: HttpxSlackIstemcisi(t, beklemeler.append, transport=httpx.MockTransport(isleyici)),
        veritabani_yolu=db_yolu, izinli_kanallar=["dev", "genel"], simdi=lambda: SIMDI, yaz=print,
    )
    assert sonuc == 1
    assert beklemeler == [1, 1]

    # Token yalnızca başlıkta gider, URL'de yok.
    assert istekler
    for istek in istekler:
        assert istek.headers["authorization"] == f"Bearer {TOKEN}"
        assert TOKEN not in str(istek.url)

    # Ağ hatası ve repr token göstermez.
    def kopuk(istek):
        raise httpx.ConnectError(f"bağlantı yok: {istek.url} {istek.headers}")

    istemci = HttpxSlackIstemcisi(TOKEN, lambda s: None, transport=httpx.MockTransport(kopuk))
    with pytest.raises(SlackHatasi) as hata:
        istemci.cagir("users.list", {})
    assert hata.value.kod == "baglanti_hatasi"
    assert hata.value.__cause__ is None
    assert TOKEN not in str(hata.value)
    assert TOKEN not in repr(istemci)

    # Seed dışa aktarımı.
    seed_yolu = tmp_path / "seed.json"
    assert seed.komutu_calistir(
        ["disa-aktar", "--dosya", str(seed_yolu)], veritabani_yolu=db_yolu, izinli_kanallar=["dev"],
        simdi=lambda: SIMDI, yaz=print, token=TOKEN,
    ) == 0

    baglanti = baglan(db_yolu)
    dokum = "\n".join(baglanti.iterdump())
    baglanti.close()
    assert "login sayfası" in dokum
    assert TOKEN not in dokum
    assert TOKEN not in seed_yolu.read_text(encoding="utf-8")
    cikti = capsys.readouterr()
    assert "invalid_auth" in cikti.out
    assert TOKEN not in cikti.out + cikti.err
    assert TOKEN not in caplog.text
