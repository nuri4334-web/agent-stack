from fastapi.testclient import TestClient

from app import kapi
from app.main import app

istemci = TestClient(app)


def test_saglik():
    r = istemci.get("/saglik")
    assert r.status_code == 200
    assert r.json() == {"durum": "ayakta"}


def test_soru_anlasmaya_uygun_cevap_doner():
    r = istemci.post("/api/soru", json={"soru": "#dev'i özetle", "kullanici": "ali"})
    assert r.status_code == 200
    govde = r.json()
    assert set(govde) == {"istek_id", "durum", "cevap", "kaynaklar", "guvenlik"}
    assert govde["durum"] == "tamam"
    assert govde["kaynaklar"] == []
    assert govde["guvenlik"] == {"engellenen": 0, "maskelenen": 0, "supheli": 0}


def test_hatali_istek_anlasilir_hata_doner():
    r = istemci.post("/api/soru", json={"soru": ""})
    assert r.status_code == 422
    assert r.json()["hata"]["kod"] == "GECERSIZ_ISTEK"


def test_kapinin_yedi_adimi_sirayla_duruyor():
    assert [ad for ad, _ in kapi.ADIMLAR] == [
        "kimlik", "yetki", "veri_secimi", "temizlik",
        "yapay_zekaya_sor", "cevap_kontrolu", "gosterim",
    ]


def test_durdurulan_istek_yapay_zekaya_gitmez(monkeypatch):
    cagrildi = []

    def reddet(b):
        b.durum = "erisim_yok"
        b.durdu = True

    monkeypatch.setattr(kapi, "ADIMLAR", [
        ("yetki", reddet),
        ("yapay_zekaya_sor", lambda b: cagrildi.append(1)),
    ])
    cevap = kapi.soru_isle("yonetim ne konuştu?", "ali")
    assert cevap.durum == "erisim_yok"
    assert cagrildi == []
