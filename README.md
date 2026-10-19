# Agent Stack

Security-first AI assistant for company data (Slack). Permission checks, secret masking, prompt-injection defense and attack tests.

Şirket verisini (önce Slack) yapay zekâ asistanına güvenli şekilde veren açık kaynak bir sistem. Temel ilke: **yapay zekâ kandırılsa bile hiçbir şey sızmasın.** Güvenlik modelin iyi davranmasına değil, mimariye dayanır.

> Durum: POC, geliştirme aşamasında (Sprint 1). Yalnızca test Slack'indeki sahte veriyle çalışır.

## Klasörler

| Klasör | Ne var? |
|---|---|
| `server/` | Python (FastAPI) sunucu: güvenlik kapısı, Slack bağlayıcısı, yapay zekâ bağlantısı, filtreler, olay kaydı, veritabanı (SQLite). |
| `web/` | React arayüz: sohbet ekranı ve güvenlik paneli. İçinde hiçbir anahtar yoktur. |
| `demo-verisi/` | Sahte demo verisi: senaryo dokümanı, sır kataloğu örnekleri, başlangıç verisi. Anahtar taramasında hariç tutulur. |
| `slack-manifest.yaml` | Slack uygulamasının hazır tanımı (yalnızca okuma izinleri). |

## Tek yol kuralı

Yapay zekâya giden her istek güvenlik kapısından geçer. Yapay zekâ bağlantısını yalnızca kapı çağırır; arayüz yapay zekâya hiçbir zaman doğrudan ulaşmaz.

## Kurulum (geliştirme)

1. `.env.example` dosyasını `.env` olarak kopyala ve kendi değerlerini gir. `.env` repoya girmez.
2. Sunucu ve arayüz kurulum adımları Sprint 1'de eklenecek.

## Güvenlik kuralları

- Gerçek anahtar, şifre ya da kişisel bilgi asla repoya girmez.
- Herkes kendi Gemini anahtarını kullanır; anahtarlar paylaşılmaz.
- Ana dala giren her kod başka biri tarafından incelenir.
