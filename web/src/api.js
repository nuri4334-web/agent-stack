// Sunucu adresi ayardan okunur (Arayüzde hiçbir gizli anahtar yoktur)
export const API_URL = import.meta.env.VITE_API_URL || 'http://localhost:8000';

// S1-07: Sahte sohbet akışı (S1-09'da sadece fetch'e çevrilecek)
export async function soruSor(soru, kullanici = 'ali') {
  return new Promise((resolve) => {
    setTimeout(() => {
      resolve({
        istek_id: 'sahte-istek-001',
        durum: 'tamam',
        cevap: `"${soru}" sorusu için (${kullanici}) sahte yanıt: #dev kanalında bu hafta login sayfası ve API bağlantıları konuşuldu.`,
        kaynaklar: [
          {
            kanal: 'dev',
            yazan: 'Deniz',
            zaman: '2026-10-22T14:05:00+03:00',
            metin: '@Ali login sayfasını sen al',
          },
        ],
        guvenlik: { engellenen: 0, maskelenen: 0, supheli: 0 },
      });
    }, 1000);
  });
}