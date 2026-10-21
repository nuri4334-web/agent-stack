import pytest

from app.veritabani.kurallar import HARIC, IZINLI, kanal_durumu

IZIN_LISTESI = ["genel", "dev", "yonetim"]


# yonetim private ama izinli: private olmak kararı etkilemez.
@pytest.mark.parametrize("kanal", ["genel", "dev", "yonetim"])
def test_listedeki_kanal_izinli(kanal):
    assert kanal_durumu(kanal, IZIN_LISTESI) == IZINLI


def test_listede_olmayan_kanal_haric():
    assert kanal_durumu("satis", IZIN_LISTESI) == HARIC


def test_bos_liste_her_seyi_haric_yapar():
    for kanal in IZIN_LISTESI:
        assert kanal_durumu(kanal, []) == HARIC


def test_ik_her_durumda_haric():
    liste = IZIN_LISTESI + ["ik", "#ik", "IK"]
    for kanal in ["ik", "#ik", " IK "]:
        assert kanal_durumu(kanal, liste) == HARIC


def test_ad_bicimi_duzeltiliyor():
    assert kanal_durumu(" #Dev ", IZIN_LISTESI) == IZINLI
    assert kanal_durumu("dev", ["#dev"]) == IZINLI


def test_bos_kanal_adi_haric():
    for kanal in ["", "#", "  "]:
        assert kanal_durumu(kanal, IZIN_LISTESI + [""]) == HARIC
