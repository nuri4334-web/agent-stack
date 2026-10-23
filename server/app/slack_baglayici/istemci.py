"""Slack istemcisi (S1-04): Web API çağrısı, 429 bekleme ve sayfalama.

Token yalnızca Authorization başlığında durur; URL'ye, loga, ekrana ya da hata mesajına asla girmez.
Testler gerçek Slack'e gitmez: akış SlackIstemcisi arayüzünü kullanır, testler sahtesini verir.
"""
from collections.abc import Callable
from typing import Protocol

import httpx

from .donusum import hata_kodunu_temizle

SLACK_ADRESI = "https://slack.com/api/"
ZAMAN_ASIMI_SN = 30.0

# 429 (çok fazla istek): Retry-After yoksa ya da geçersizse beklenen süre ve tek beklemenin üst sınırı.
VARSAYILAN_BEKLEME_SN = 5.0
EN_UZUN_BEKLEME_SN = 120.0

# Sonsuz döngüye karşı: bir listede en fazla bu kadar sayfa okunur.
EN_FAZLA_SAYFA = 1000


class SlackHatasi(Exception):
    """Slack çağrısı başarısız. Yalnızca temizlenmiş hata kodunu taşır (ör. "not_in_channel")."""

    def __init__(self, kod: object):
        self.kod = hata_kodunu_temizle(kod)
        super().__init__(self.kod)

    def __str__(self) -> str:
        return self.kod


class SlackIstemcisi(Protocol):
    def cagir(self, uc: str, parametreler: dict[str, str]) -> dict:
        """Tek bir Slack ucunu çağırır ve JSON gövdesini döndürür; hatada SlackHatasi."""
        ...


def _bekleme_suresi(retry_after: str | None) -> float:
    try:
        saniye = int(retry_after)
    except (TypeError, ValueError):
        return VARSAYILAN_BEKLEME_SN
    if saniye < 0:
        return VARSAYILAN_BEKLEME_SN
    return float(min(saniye, EN_UZUN_BEKLEME_SN))


class HttpxSlackIstemcisi:
    """httpx ile gerçek Slack istemcisi. 429'da Retry-After kadar bekleyip aynı isteği tekrarlar."""

    def __init__(
        self,
        token: str,
        uyku: Callable[[float], None],
        *,
        en_fazla_deneme: int = 5,
        transport: httpx.BaseTransport | None = None,
    ):
        self._uyku = uyku
        self._en_fazla_deneme = en_fazla_deneme
        self._http = httpx.Client(
            base_url=SLACK_ADRESI,
            headers={"Authorization": f"Bearer {token}"},
            timeout=ZAMAN_ASIMI_SN,
            transport=transport,
        )

    def __repr__(self) -> str:
        return "HttpxSlackIstemcisi(token=<gizli>)"

    def cagir(self, uc: str, parametreler: dict[str, str]) -> dict:
        for deneme in range(1, self._en_fazla_deneme + 1):
            try:
                cevap = self._http.get(uc, params=parametreler)
            except httpx.HTTPError:
                # Asıl istisna zincirlenmez: içinde istek ayrıntısı olabilir.
                raise SlackHatasi("baglanti_hatasi") from None
            if cevap.status_code == 429:
                if deneme == self._en_fazla_deneme:
                    break
                self._uyku(_bekleme_suresi(cevap.headers.get("Retry-After")))
                continue
            if cevap.status_code != 200:
                raise SlackHatasi(f"http_{cevap.status_code}")
            try:
                govde = cevap.json()
            except ValueError:
                raise SlackHatasi("gecersiz_cevap") from None
            if not isinstance(govde, dict):
                raise SlackHatasi("gecersiz_cevap")
            if govde.get("ok") is not True:
                raise SlackHatasi(govde.get("error"))
            return govde
        raise SlackHatasi("ratelimited")

    def kapat(self) -> None:
        self._http.close()


def sayfa_sayfa(istemci: SlackIstemcisi, uc: str, parametreler: dict[str, str], alan: str) -> list:
    """Bir listenin bütün sayfalarını (next_cursor bitene kadar) okuyup "alan" listelerini birleştirir."""
    hepsi: list = []
    imlec = ""
    for _ in range(EN_FAZLA_SAYFA):
        istek = dict(parametreler)
        if imlec:
            istek["cursor"] = imlec
        govde = istemci.cagir(uc, istek)
        sayfa = govde.get(alan)
        if not isinstance(sayfa, list):
            raise SlackHatasi("gecersiz_cevap")
        hepsi.extend(sayfa)
        ust_bilgi = govde.get("response_metadata")
        imlec = ust_bilgi.get("next_cursor") if isinstance(ust_bilgi, dict) else ""
        if not imlec or not isinstance(imlec, str):
            return hepsi
    raise SlackHatasi("sayfa_siniri")
