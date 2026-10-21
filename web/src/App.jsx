import { useState } from 'react';
import { API_URL, soruSor } from './api';

// Geçici kullanıcı ve rol sabitleri (Aşama 2'de oturumdan gelecek)
// Rolü 'admin' yaparsanız Güvenlik Paneli sekmesi görünür
const AKTIF_KULLANICI = { ad: 'ayse', rol: 'admin' }; // 'kullanici' | 'admin'

export default function App() {
  // 3 sayfa arasında geçiş: 'giris' | 'sohbet' | 'panel'
  const [aktifSayfa, setAktifSayfa] = useState('sohbet');
  const [profilAcik, setProfilAcik] = useState(false);

  // Sohbet akışı durumları
  const [soru, setSoru] = useState('');
  const [gonderilenSoru, setGonderilenSoru] = useState('');
  const [yaziyor, setYaziyor] = useState(false);
  const [cevapVerisi, setCevapVerisi] = useState(null);
  const [hataMesaji, setHataMesaji] = useState('');

  const soruGonder = async (e) => {
    e.preventDefault();
    if (!soru.trim() || yaziyor) return;

    const mevcutSoru = soru;
    setGonderilenSoru(mevcutSoru);
    setSoru('');
    setYaziyor(true);
    setCevapVerisi(null);
    setHataMesaji('');

    try {
      const sonuc = await soruSor(mevcutSoru, AKTIF_KULLANICI.ad);
      if (sonuc.hata) {
        setHataMesaji(sonuc.hata.mesaj || 'Bir hata oluştu.');
      } else {
        setCevapVerisi(sonuc);
      }
    } catch (err) {
      setHataMesaji(err?.hata?.mesaj || 'Sunucuya ulaşılamadı.');
    } finally {
      setYaziyor(false);
    }
  };

  return (
    <div>
      {/* Üst Menü: 3 Sayfa Arasında Geçiş */}
      <header className="navbar">
        <div className="brand">
          ASP <span>Agent Stack Project</span>
        </div>

        <nav className="nav-links">
          <button
            className={`nav-link ${aktifSayfa === 'giris' ? 'active' : ''}`}
            onClick={() => setAktifSayfa('giris')}
          >
            Giriş
          </button>
          <button
            className={`nav-link ${aktifSayfa === 'sohbet' ? 'active' : ''}`}
            onClick={() => setAktifSayfa('sohbet')}
          >
            Sohbet
          </button>

          {/* Güvenlik Paneli yalnızca admin rolüne görünür */}
          {AKTIF_KULLANICI.rol === 'admin' && (
            <button
              className={`nav-link ${aktifSayfa === 'panel' ? 'active' : ''}`}
              onClick={() => setAktifSayfa('panel')}
            >
              Güvenlik Paneli
            </button>
          )}

          {/* Profil & Bağlı Hesaplar Açılır Menüsü */}
          <div className="profile-wrapper">
            <button
              className="profile-pill"
              onClick={() => setProfilAcik(!profilAcik)}
            >
              <div className="avatar">
                {AKTIF_KULLANICI.ad.slice(0, 2).toUpperCase()}
              </div>
              <div style={{ textAlign: 'left', fontSize: '12px' }}>
                <div style={{ fontWeight: 600 }}>{AKTIF_KULLANICI.ad}</div>
                <div style={{ color: '#94A3B8', fontSize: '11px' }}>
                  {AKTIF_KULLANICI.rol === 'admin' ? 'Admin' : 'Kullanıcı'}
                </div>
              </div>
              <div className="status-dot" />
            </button>

            {profilAcik && (
              <div className="popover">
                <div style={{ fontSize: '12px', color: '#94A3B8', marginBottom: '4px' }}>
                  Profil & Bağlı Hesaplar
                </div>
                <button className="popover-btn">🔗 Jira hesabını bağla</button>
                <button className="popover-btn">🔗 GitHub hesabını bağla</button>
              </div>
            )}
          </div>
        </nav>
      </header>

      <main className="container">
        {/* 1. SAYFA: GİRİŞ */}
        {aktifSayfa === 'giris' && (
          <div className="card">
            <h2>Giriş Ekranı (İskelet)</h2>
            <p style={{ color: '#94A3B8', marginTop: '8px' }}>
              Aşama 2&apos;de aktifleşecek giriş ve Slack ile giriş ekranı iskeleti.
            </p>
          </div>
        )}

        {/* 2. SAYFA: SOHBET */}
        {aktifSayfa === 'sohbet' && (
          <div>
            <div className="card">
              <h2>Sohbet</h2>
              <p style={{ color: '#94A3B8', fontSize: '13px', marginTop: '4px' }}>
                Bağlı Sunucu Adresi (Ayardan Okunan): <code>{API_URL}</code>
              </p>

              {gonderilenSoru && (
                <div style={{ marginTop: '20px', textAlign: 'right' }}>
                  <span
                    style={{
                      display: 'inline-block',
                      backgroundColor: '#0F172A',
                      border: '1px solid #334155',
                      padding: '10px 16px',
                      borderRadius: '10px',
                    }}
                  >
                    {gonderilenSoru}
                  </span>
                </div>
              )}

              {/* "Yazıyor..." Bekleme Durumu */}
              {yaziyor && (
                <div className="meta-box" style={{ marginTop: '16px', color: '#38BDF8' }}>
                  Yazıyor...
                </div>
              )}

              {/* Hata Durumu */}
              {hataMesaji && !yaziyor && (
                <div
                  className="meta-box"
                  style={{
                    marginTop: '16px',
                    color: '#FCA5A5',
                    borderColor: '#EF4444',
                  }}
                >
                  {hataMesaji}
                </div>
              )}

              {/* Cevap, Kaynaklar ve Güvenlik Özeti */}
              {cevapVerisi && !yaziyor && (
                <div style={{ marginTop: '20px' }}>
                  <div
                    style={{
                      backgroundColor: '#0F172A',
                      border: '1px solid #334155',
                      padding: '16px',
                      borderRadius: '8px',
                      lineHeight: '1.5',
                    }}
                  >
                    {/* Düz metin gösterimi */}
                    {cevapVerisi.cevap}
                  </div>

                  <div className="meta-box">
                    <strong>Dayandığı Mesajlar (Kaynaklar):</strong>
                    {cevapVerisi.kaynaklar.length === 0 ? (
                      <div>Kaynak yok</div>
                    ) : (
                      <ul style={{ marginTop: '6px', paddingLeft: '18px' }}>
                        {cevapVerisi.kaynaklar.map((k, idx) => (
                          <li key={idx}>
                            #{k.kanal} — {k.yazan}: &quot;{k.metin}&quot;
                          </li>
                        ))}
                      </ul>
                    )}
                  </div>

                  <div className="meta-box">
                    <strong>Güvenlik Özeti: </strong>
                    Engellenen: {cevapVerisi.guvenlik.engellenen} | Maskelenen:{' '}
                    {cevapVerisi.guvenlik.maskelenen} | Şüpheli:{' '}
                    {cevapVerisi.guvenlik.supheli}
                  </div>
                </div>
              )}

              <form className="input-row" onSubmit={soruGonder}>
                <input
                  type="text"
                  className="text-input"
                  placeholder="Sorunuzu yazın... (Örn: #dev'i özetle)"
                  value={soru}
                  onChange={(e) => setSoru(e.target.value)}
                />
                <button type="submit" className="btn-primary" disabled={yaziyor}>
                  Gönder
                </button>
              </form>
            </div>
          </div>
        )}

        {/* 3. SAYFA: GÜVENLİK PANELİ */}
        {aktifSayfa === 'panel' && AKTIF_KULLANICI.rol === 'admin' && (
          <div className="card">
            <h2>Güvenlik Paneli (İskelet)</h2>
            <p style={{ color: '#94A3B8', marginTop: '8px' }}>
              Yalnızca admin rolüne görünecek güvenlik olayları paneli iskeleti.
            </p>
          </div>
        )}
      </main>
    </div>
  );
}