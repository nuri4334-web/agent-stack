# server/

Python (FastAPI) sunucu. Bütün mantık burada; arayüzde hiçbir anahtar yoktur.

## Klasörler (`app/`)

| Klasör / dosya | Ne işe yarar | Sahibi |
|---|---|---|
| `main.py` | Sunucunun giriş noktası: uçlar (`/saglik`, `/api/soru`) ve hata biçimi. | Nuri |
| `kapi.py` | Güvenlik kapısı (ana akış). Her soru sırayla yedi adımdan geçer. | Nuri |
| `sema.py` | Sohbet anlaşmasının kod hali: istek ve cevap biçimleri. | Nuri |
| `ayarlar.py` | `.env` dosyasından ayarları okur. | Nuri |
| `slack_baglayici/` | Slack'ten kanal, kullanıcı, üyelik ve mesaj çekme. | Nuri |
| `yapay_zeka/` | Yapay zekâ bağlantısı: Gemini ve sahte sağlayıcı. | Boran |
| `filtreler/` | Sır ve isim maskeleme, gizli talimat tespiti. | Musa |
| `olay_kaydi/` | Her adımın kararı ve süresi; mesaj metni içermez. | Nuri |
| `veritabani/` | SQLite tabloları. | Nuri |

## Tek yol kuralı

Yapay zekâ bağlantısını (`yapay_zeka/`) **yalnızca `kapi.py` çağırır**. Ne arayüz ne başka bir modül yapay zekâya doğrudan ulaşır. Kestirme yok.

## Çalıştırma (Windows, PowerShell)

```powershell
cd server
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
uvicorn app.main:app --reload
```
Tarayıcıda: http://localhost:8000/saglik ve http://localhost:8000/docs

## Testler

```powershell
cd server
.venv\Scripts\Activate.ps1
pytest
```

Sohbet anlaşması: [`docs/sohbet-anlasmasi.md`](../docs/sohbet-anlasmasi.md)
