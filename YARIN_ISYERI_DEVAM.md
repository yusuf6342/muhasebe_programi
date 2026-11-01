# Yarın işyeri açılışı — 2 Kasım 2026

Kişisel/veritabanı içeriği yok. Makineye özel yollar yerel aktarım yönergesinde.

## Sıra

1. İşyerindeki açık programı ve gerçek veri kaynağını belirle; kaydedilmemiş işi yedekle.
2. Uzak `origin/main` son commit SHA’sını doğrula; yerel iş varsa silmeden güvenli pull/birleştir.
3. Teslim paketinin SHA-256 / MANIFEST ve SQLite `integrity_check` sonuçlarını kontrol et.
4. **TEST** veri paketini işyerinde ayrı TEST konumuna aç — üretim DB üzerine yazma.
5. Gerçek veri gerekiyorsa firma UID/dönem ve iki taraftaki yeni kayıt farklarını karşılaştır; kör üzerine yazma.
6. İşyeri `system.db` dosyasını ev kopyasıyla düşünmeden değiştirme.
7. Veri yolunu işyeri bilgisayarına göre yerelleştir; ev mutlak yollarını taşıma.
8. Son EV TEST paketini veya temiz kaynaktan derlemeyi TEST ayarıyla aç; eski Programs kısayolunu kullanma.
9. Firma/dönem, şema, kritik kayıt adetlerini manifest ile karşılaştır; fatura + konsinye ekranlarını aç.
10. Doğrulama geçince çalışmaya devam et. Burada sınanamayan adımlar: işyerinde doğrulanacak.

## Kaynak

- Repo: `yusuf6342/muhasebe_programi` · dal: `main`
- Ev worktree: `muhasebe_programi_uzak_20261101_152451`
- Commit SHA: teslim raporunda / `git rev-parse origin/main`
- Veri yedek (Git dışı, ev): `CinMuhasebe_Teslim_Yedek_20261101_220608` — USB ile taşınacak
