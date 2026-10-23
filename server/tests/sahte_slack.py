"""Testler için sahte Slack istemcisi: gerçek Slack'e gitmez, her çağrıyı kaydeder, sayfalı cevap verir."""
from datetime import datetime, timezone

from app.slack_baglayici.istemci import SlackHatasi

SIMDI = datetime(2026, 10, 23, 12, 0, tzinfo=timezone.utc)
IZINLI = ["genel", "dev", "yonetim"]


def ts(saat_once: int, sira: int = 100) -> str:
    """SIMDI'den saat_once saat önceki Slack ts'i (metin)."""
    return f"{int(SIMDI.timestamp()) - saat_once * 3600}.{sira:06d}"


def mesaj(yazan, metin, saat_once, sira=100, **alanlar) -> dict:
    satir = {"type": "message", "text": metin, "ts": ts(saat_once, sira)} | alanlar
    if yazan is not None:
        satir["user"] = yazan
    return satir


def kanal(slack_id, ad, ozel=False, uye=True) -> dict:
    return {"id": slack_id, "name": ad, "is_private": ozel, "is_member": uye}


class SahteSlack:
    def __init__(self, kanallar, kullanicilar, uyeler, mesajlar, sayfa_boyu=None):
        self.kanallar = kanallar
        self.kullanicilar = kullanicilar
        self.uyeler = uyeler
        self.mesajlar = mesajlar
        self.sayfa_boyu = sayfa_boyu
        self.hatalar: dict[tuple[str, str | None], str] = {}  # (uç, kanal) -> Slack hata kodu
        self.cagrilar: list[tuple[str, dict]] = []

    def cagir(self, uc, parametreler):
        self.cagrilar.append((uc, dict(parametreler)))
        kanal_id = parametreler.get("channel")
        if (uc, kanal_id) in self.hatalar:
            raise SlackHatasi(self.hatalar[(uc, kanal_id)])
        if uc == "conversations.list":
            liste, alan = self.kanallar, "channels"
        elif uc == "users.list":
            liste, alan = self.kullanicilar, "members"
        elif uc == "conversations.members":
            liste, alan = self.uyeler.get(kanal_id, []), "members"
        elif uc == "conversations.history":
            oldest = parametreler.get("oldest", "")
            liste = [m for m in self.mesajlar.get(kanal_id, []) if m["ts"] > oldest]
            alan = "messages"
        else:
            raise AssertionError(f"Beklenmeyen uç: {uc}")
        bas = int(parametreler.get("cursor") or 0)
        boy = self.sayfa_boyu or max(len(liste), 1)
        sonraki = bas + boy
        return {
            "ok": True,
            alan: liste[bas:sonraki],
            "response_metadata": {"next_cursor": str(sonraki) if sonraki < len(liste) else ""},
        }

    def kanal_cagrilari(self, kanal_id) -> list[str]:
        return [uc for uc, p in self.cagrilar if p.get("channel") == kanal_id]


def ornek_slack(**secenekler) -> SahteSlack:
    """genel, dev, yonetim (private) izinli; ik (private) ve satis hariç. Bot hepsinde üye."""
    return SahteSlack(
        kanallar=[
            kanal("C_GENEL", "genel"),
            kanal("C_DEV", "dev"),
            kanal("C_YON", "yonetim", ozel=True),
            kanal("C_IK", "ik", ozel=True),
            kanal("C_SATIS", "satis"),
        ],
        kullanicilar=[
            {"id": "U_ALI", "profile": {"display_name": "Ali", "real_name": "Ali Demo"}},
            {"id": "U_DENIZ", "profile": {"display_name": "Deniz", "real_name": "Deniz Demo"}},
            {"id": "U_NURI", "profile": {"display_name": "", "real_name": "Nuri Demo"}},
            {"id": "U_BOT", "is_bot": True, "profile": {"display_name": "agentstack-bot"}},
        ],
        uyeler={
            "C_GENEL": ["U_ALI", "U_DENIZ", "U_NURI", "U_BOT"],
            "C_DEV": ["U_ALI", "U_DENIZ", "U_BOT"],
            "C_YON": ["U_NURI", "U_BOT"],
            "C_IK": ["U_NURI", "U_BOT"],
            "C_SATIS": ["U_ALI", "U_BOT"],
        },
        mesajlar={
            "C_GENEL": [
                mesaj("U_ALI", "günaydın", 5, 100),
                mesaj("U_DENIZ", "toplantı saat 10'da", 4, 200),
                mesaj("U_BOT", "kanala katıldı", 6, 300, subtype="channel_join"),
            ],
            "C_DEV": [
                mesaj("U_DENIZ", "login sayfasını sen al", 3, 100),
                mesaj("U_ALI", "tamam", 2, 200),
                mesaj("U_ALI", "PR açtım", 1, 300),
            ],
            "C_YON": [mesaj("U_NURI", "bütçe toplantısı", 2, 100)],
            "C_IK": [mesaj("U_NURI", "maaş listesi", 2, 100)],
            "C_SATIS": [mesaj("U_ALI", "teklif hazır", 2, 100)],
        },
        **secenekler,
    )
