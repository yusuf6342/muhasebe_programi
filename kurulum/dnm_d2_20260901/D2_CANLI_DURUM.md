# D2 canlı geçiş — durum (2026-11-08)

## Tamamlanan
- Dal: `feature/yerel-ag-postgresql` @ `c53213d`+ (yeni araçlar)
- D2 hedef DB boş şema doğrulandı: `cin_sistem/firma_dnm_d2_20260901`
- Sistem tohum: firma `DNM_D2`, 7 aktif kullanıcı (kabul hash’leri)
- Yazım öncesi yedek: `kurulum/dnm_d2_20260901/yedek/yazim_oncesi_*`
- Evo kaynak: anlık + 07.11 guncel_bakiye + kasa/banka hareket yenileme
- Önizleme üretildi; **mali yazım henüz yok** (bağlantı kabul profiline geri alındı)

## Karar bekleyen engel (mali)
Evo GRP_TOP / hareket neti ile D1 kabul kasa kapanışı uyuşmuyor:

| Kaynak | NAKİT | YÇ | Not |
|--------|------:|---:|-----|
| D1 kabul 31.08 | 2 209,55 | 2 550,01 | Kanıtlı kapanış |
| Evo ham ≤07.11 | −380 871,99 | 1 438 375,53 | GRP_TOP = hareket neti (açılışsız) |

Ekim evo_devir denemesi de aynı Evo ham yöntemiyle eksi nakit yazmıştı. Canlıya yanlış kasa ile geçilmemeli.

### Seçenekler
1. **D1 kasa açılışı (önerilen):** 31.08 D1 kapanışı → 01.09 açılış; Eylül–kesim kasa/banka **belge/hareket** aktarımı. Evo GRP_TOP kasa için kullanılmaz.
2. **Evo ham (evo_devir):** Kaynak API bakiyesini olduğu gibi yaz (−380 871 nakit dahil). Evo ekranıyla birebir; D1 kasa kanıtıyla çelişir.
3. **Kullanıcı beyanı:** Bugünkü gerçek kasa sayım/Evo kart bakiyesi tutarını ver; o tutar açılış kabul edilir.

## Son aktarım için
Kaynakta işlem sürüyorsa **kısa kayıt durdurma** gerekir (çift kayıt / kayıp önlemek için). Bildirim: kesim anı netleşince son fark aktarımı yapılacak.

## Ertelenen
- 01.09–07.11 tam belge geçmişi (fatura satır satır) — bakiye kesiminden sonra / seçime bağlı
- Görsel düzen, kapsamlı performans, D1 kalan FIFO/LOT detayları
- Devir 1 devamı (D2 sonrası)
