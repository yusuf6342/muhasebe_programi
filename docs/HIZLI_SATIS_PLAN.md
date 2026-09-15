# Hızlı Satış ve Tahsilat — Uygulama Planı



## Mimari (Aşama 0 — kabul)



- Ayrı POS belge tablosu yok; final satış `SatisFaturasiService.kaydet` + `onayla` (tek transaction, Aşama 5).

- Beklet / favori / log tabloları sonraki aşamalarda. → Beklet: Aşama 6 tamam.

- Aynı SQLite firma DB, Tkinter+ttk, mevcut kalıplar.



## Aşamalar



| Aşama | Konu | Durum |

|-------|------|--------|

| 0 | Mimari kararlar | tamam |

| 1 | Menü + geniş iskelet UI (5 bölge, renkler) | tamam |

| 2 | Barkod okutma + ürün sepete ekleme | tamam |

| 3 | Ürün grupları + tıklanabilir kartlar | tamam |

| **4** | Yetkiler (tam) + müşteri / fiyat kuralları | **tamam** |

| **5** | Tahsilat + `kaydet`/`onayla` tek transaction | **tamam** |

| **6** | Beklet / geri çağır | **tamam** |

| **7** | İptal / kısmi iade | **tamam** |

| **8** | Yazdırma / fiş / PDF + gün sonu / log | **tamam** |

| **9** | Talimat §23 test senaryoları + manuel UAT | **tamam** |



**Plan durumu: Aşama 0–9 tamamlandı.**



## Aşama 1 teslimi



- Sol menü: **HIZLI SATIŞ** (sarı vurgu; klasik «HIZLI SATIŞ FATURASI» diyalogundan ayrı)

- Dosya: `hizli_satis_ui.py` — üst / sol / orta / sağ / alt placeholder bölgeler

- Yetki: mevcut `satis_duzenleme` / `satis_goruntuleme` / `goruntuleme` (Aşama 4 genişletecek)



## Aşama 2 teslimi



- Barkod Enter → `StokService.barkod_ile_bul` (tam eşleşme, soft-delete dışı) → sepete ekle

- Paket/koli barkodu: `StokBirim.carpan` ile ana birim miktarı; paket fiyatı varsa birim fiyatına bölünür

- Manuel arama: `UrunSecDialog` (F1 / Ara); mevcut stok kartı — ikinci ürün master yok

- Sepet bellekte: `hizli_satis_sepet.py` — miktar (ondalık), birim, isk %, KDV %, satır/genel toplam

- Kısayol: Del / F7 satır sil; +/- miktar; çift tık miktar diyaloğu

- Ödeme / tamamla butonları hâlâ stub (Aşama 5)

- Ürün grup kartları Aşama 3'e bırakıldı

- Test: `python test_hizli_satis_sepet.py`



## Aşama 3 teslimi



- Sol: dinamik ürün grupları — `StokSecenek(tur=rapor_grubu)` ∪ stok kartı `rapor_grubu` + **Sık Satılanlar** + gerekirse **Grup Yok**

- Orta: tıklanabilir ürün kartları (ad, Satış Fiyatı 1, resim veya placeholder); sayfalama (24) + kaydırma

- Kart tıklama → mevcut bellek sepeti (`hizli_satis_sepet` / `_sepete_ekle_kayit`)

- Sık satılanlar: onaylı satış fatura satırlarından best-effort; boşsa bilgilendirme (ayrı favori tablosu yok)

- Soft-delete / pasif stoklar listede yok

- UI: `hizli_satis_urun_panel_ui.py`; yardımcılar: `StokService.hizli_satis_gruplari` / `hizli_satis_urunleri`

- Ödeme hâlâ stub; Aşama 4+ başlatılmadı

- Test: `python test_hizli_satis_sepet.py` (+ grup sabitleri smoke)



## Aşama 4 teslimi



- Varsayılan cari: seed `perakende_cari_hazirla` → `PRK001` / ünvan **PERAKENDE MÜŞTERİ** (grup zaten vardı); POS açılışında seçilir

- Üst bar: **Seç (F2)** → mevcut `MusteriSecimDialog` + `CariService.aktif_musteriler` (soft-delete dışı)

- Fiyat listesi: `hizli_satis_musteri.fiyat_listesi_coz` — ödeme niyeti (placeholder) > kart `satis_fiyat_listesi` > grup → SF1–4 eşlemesi; satır ekleme + müşteri değişince sepet/kart fiyatları yenilenir

- Risk: `acik_hesap_risk_degerlendir` — UI uyarı/engel (`hizli_satis_acik_hesap`); sert enforce Aşama 5

- İzinler (`bootstrap.py`): `hizli_satis_fiyat_degistirme`, `hizli_satis_yuksek_iskonto`, `hizli_satis_acik_hesap` → SATIS (+ YONETICI `*`)

- Sepet: Fiyat / İsk % butonları + bellek içi `FiyatDegisiklikGunlugu` (Aşama 8+ log)

- Ödeme / tamamla hâlâ stub — Aşama 5+ başlatılmadı

- Test: `python test_hizli_satis_sepet.py` (fiyat çözümü, risk, yetki, bootstrap)



## Aşama 5 teslimi



- Tahsilat diyaloğu: `hizli_satis_tahsilat_ui.py` — nakit (hızlı tutar + para üstü), KK/POS (banka/taksit notu), havale, açık hesap; kısmi ödemeler

- Servis: `database/hizli_satis_service.py` — sepet → onaylı `SatisFaturasi` **tek transaction** (iç içe session yok); idempotency jetonu; stok UI+DB; eksi stok yok

- Ödeme şekilleri: mevcut `NAKİT / KASA`, `GELEN HAVALE`, `KREDİ KARTIYLA TAHSİLAT` + açık hesap kalanı (`hizli_satis_acik_hesap`); `FinansService.fatura_tahsilati`

- UI: F10 / F12 → tahsilat → başarıda sepet temizlenir; fiş yazdırma stub mesajı (Aşama 8)

- Sert enforce: yazma yetkisi + kapalı dönem (`yazma_zorunlu`); açık hesap risk/yetki

- Aşama 6+ başlatılmadı (beklet / iade / gün sonu yok) → Aşama 6 ayrı teslim

- Test: `python test_hizli_satis_service.py` + `python test_hizli_satis_sepet.py`



## Aşama 6 teslimi



- Bekleyen sepet DB: `hizli_satis_bekleyenler` + `hizli_satis_bekleyen_satirlari` (`database/models/hizli_satis.py`)

- Servis: `save_hold` / `list_holds` / `load_hold` / `delete_hold` + `schema_hazirla` (checkfirst); **stok düşmez / rezervasyon yok**

- Geri çağır: sepete yükler, hold `CAGIRILDI` (listeden düşer); iptal → `IPTAL`

- UI: `hizli_satis_bekleyen_ui.py`; POS: **F8 BEKLET** / **F9 ÇAĞIR**

- Şema: `database.py` `hizli_satis_schema_hazirla` + `main.py` açılış

- Aşama 7 ayrı teslim (iptal / iade)

- Test: `python test_hizli_satis_service.py` + `python test_hizli_satis_sepet.py`



## Aşama 7 teslimi



- Tam iptal: `HizliSatisService.satisi_iptal` → `SatisFaturasiService.iptal_et` (stok/kasa/cari geri; soft İPTAL + silinen kayıt günlüğü; fiziksel silme yok)

- Kısmi / tam iade: `HizliSatisService.satisi_iade` → `SatisIadeFaturasiService.kaydet` (kaynak fatura satırına bağlı; kalan miktar kontrolü)

- Önceki iade varsa tam iptal engellenir (çift stok riski)

- Yetki: `hizli_satis_iptal` (bootstrap + SATIS rolü); neden zorunlu

- UI: `hizli_satis_iptal_ui.py`; POS kırmızı **İPTAL** — sepet doluysa bellek temizle (DB yok); boşsa bugünkü/son satış listesi

- Etiket: fatura açıklaması «Hızlı Satış» / `[HIZLI_SATIS]`

- Sınırlama: POS komisyon/valör geri alımı best-effort değil (yalnızca `FATURA TAHSİLATI`)

- Aşama 8+ başlatılmadı (fiş/PDF / gün sonu / log yok)

- Test: `python test_hizli_satis_service.py` (10) + `python test_hizli_satis_sepet.py` (12)



## Aşama 8 teslimi



- Satış sonrası diyalog: fatura no + **Fiş Yazdır** / **A4 Yazdır** / **PDF** / **Kapat**

- `hizli_satis_cikti_ui.py` — HTML fiş + A4 (tarayıcı `window.print`); PDF = bağımlılıksız metin PDF (çek/senet kalıbı)

- Yazıcı / önizleme hatası satışı **geri almaz**; hata işlem loguna yazılır

- Yeniden yazdır: POS alt şerit «Son fişi yazdır / Son A4 / Son PDF» (`_son_fatura_id`)

- Gün sonu: `hizli_satis_gun_sonu_ui.py` + `HizliSatisService.gun_sonu_ozeti` — onaylı Hızlı Satış faturaları (adet, brüt, isk/KDV, tahsilat, açık hesap, nakit/KK/havale, iptal/iade)

- İşlem logu: `%LOCALAPPDATA%/CinMuhasebe/logs/hizli_satis_islem.log` (JSON satır; fiyat değişikliği anında + SATIS/IPTAL/IADE/PDF)

- **Ertelendi:** thermal SDK, WhatsApp otomatik gönderim (PDF dosyası paylaşılabilir)

- Test: `python test_hizli_satis_sepet.py` (13) + `python test_hizli_satis_service.py`



## Aşama 9 teslimi



- Talimat §23 senaryoları otomatik + manuel UAT ayrımı (aşağıdaki tablo)

- Genişletilen testler: `test_hizli_satis_sepet.py`, `test_hizli_satis_service.py`

- Çalıştırma:
  - `python test_hizli_satis_sepet.py`
  - `python test_hizli_satis_service.py`

- Plan **0–9 tamam**; EXE / git commit bu aşamada yok (isteğe bağlı)



### §23 otomasyon vs manuel UAT



| §23 senaryo | Otomatik | Manuel UAT (GUI) |
|-------------|----------|------------------|
| Barkod tek ürün + aynı barkod tekrar (miktar birleşir) | sepet + servis smoke | Barkod okuyucu Enter; odak temizliği |
| Manuel arama / ürün grubu kartından ekleme | import/API smoke | F1 Ara, grup kartı tık |
| Adetli ve ondalıklı miktar | sepet + `test_s23_ondalikli_miktar_satis` | Miktar diyaloğu / +/- |
| Satır ve genel iskonto | sepet (satır + tüm satıra oran) | Fiyat/İsk butonları, yetki uyarıları |
| Nakit + para üstü | para üstü kuralı + tahsilat aşımı reddi | Nakit fazla giriş, hızlı tutar butonları |
| Kredi kartı | `test_s23_kredi_karti_satis` | POS hesap seçimi, taksit notu |
| Parçalı ödeme | `test_s23_parcali_odeme_nakit_ve_acik` | Birden fazla ödeme satırı UI |
| Açık hesap | yetkili + yetkisiz kapı | Risk uyarısı, onay diyaloğu |
| Stoktan fazla satış | `test_yetersiz_stok_reddedilir` | Kırmızı stok uyarısı ekranda |
| Beklet / geri çağır | mevcut + kalıcılık | F8 / F9 listesi |
| Program kapanıp açılınca bekleyenler | `test_s23_beklet_kalicilik_yeniden_okuma` | Uygulamayı kapat/aç, F9 |
| Satış iptali / kısmi iade | mevcut servis testleri | İPTAL diyaloğu, neden girişi |
| Çift kayıt engeli | `test_cift_gonderim_reddedilir` | F12 art arda / buton disable |
| Yazıcı yokken satış kalır | `test_s23_yazici_hatasi_satisi_geri_almaz` | Yazıcı kapalıyken fiş/PDF |
| Gün sonu tutarlılığı | `test_s23_gun_sonu_...` + özet birimi | Gün sonu ekranı görsel kontrol |
| Kısayollar / dokunmatik / 1366×768 | — | Manuel |
| Sesli/görsel barkod bulunamadı | — | Manuel |
| WhatsApp / thermal SDK | ertelendi | — |



### Manuel UAT kontrol listesi (kısa)



1. HIZLI SATIŞ menüsü → ekran 1366×768 taşmadan açılır; barkod odağı hazır.

2. Barkod okut → sepete ekle → aynı barkod tekrar → miktar artar; alan temizlenir.

3. F1 manuel arama + sol grup / kart tık ile ekleme.

4. Ondalık miktar (kg/m) ve satır iskonto; yetkisiz fiyat değişiminde engel.

5. F10 tahsilat: nakit para üstü, KK, parçalı, açık hesap (yetkili/yetkisiz).

6. Yetersiz stokta tamamlanamaz; yetkili kullanıcıda da eksi stok yok (mevcut politika).

7. F8 beklet → programı kapat/aç → F9 ile geri çağır; stok düşmez.

8. Satış tamamla → fiş/A4/PDF; yazıcı hatasında satış kaydı durur (geri alınmaz).

9. İPTAL / kısmi iade → stok ve cari/kasa geri; neden zorunlu.

10. Gün sonu özeti: nakit/KK/havale/açık hesap/iptal rakamları bugünkü satışlarla uyumlu.

11. F1–F12 / Esc / Del kısayolları çift kayıt üretmez.
