# Cin Muhasebe — Yerel Ağ Geçişi Kabul Testleri

Tarih: 2026-11-05  
Dayanak: `kurulum/GECIS_RAPORU.json` (2026-11-05 12:45:26)  
Makine (bu oturum): **DESKTOP-FL08BVD** (terminal, 192.168.1.133)  
PostgreSQL sunucu: **DESKTOP-CGSE5GK** / 192.168.1.114:5432 (17.11)  
Dal / commit (iş öncesi): `feature/yerel-ag-postgresql` @ `ac8ed38`  
EXE: `dist\CinMuhasebe\CinMuhasebe.exe` — SHA-256 `0BD255BA888BF68F0AE1EF502AD562AE3DE4C0FBFEEE19453EF37308CB64C27C` (yeniden derleme 13:38)

## Özet durum

| Konu | Sonuç |
|------|--------|
| Aktarılan verilerin durumu | Mutabakat **GEÇTİ** (249/249, dokuz sayım, mali fark yok). Firma DB’de **242 tabloda** eksik `id` sequence DEFAULT onarıldı. |
| Deneme uygulamasının durumu | DENEME profili + masaüstü kısayolu hazır. PG API duman testi **GEÇTİ**. EXE penceresi açıldı (`MainWindowTitle=Cin Muhasebe`); tam GUI giriş/ekran turu **kısmen** (oturum kısa sürdü). |
| Canlı geçişe hazır mı? | **Hayır (tam hazır değil).** İzole DB kopyası/CREATEDB, ayrı hedefe restore, ana makine EXE + iki PC eşzamanlı UI testleri eksik/engelli. |
| Canlı geçiş uygulandı mı? | **Hayır.** Günlük bağlantı değiştirilmedi. |
| Kalan engeller | 1) Ana makinede `03_pg_kabul_kopya.ps1` (superuser) 2) `04_pg_restore_ayri_hedef.ps1` 3) DESKTOP-CGSE5GK’te aynı EXE SHA ile GUI 4) İki PC eşzamanlı fatura/barkod UI 5) Canlı veri 04.11 yedeğinden sonra güncellenmiş (EvoBulut’ta 04–05.11 faturalar görünüyor) — taze aktarım şart |

## 1) Başlangıç doğrulama

| Test | Bilgisayar | Hedef | Beklenen | Gerçekleşen | Durum |
|------|------------|-------|----------|-------------|--------|
| Rapor hedefleri hâlâ duruyor | FL08BVD | cin_sistem_deneme / cin_firma_deneme | RAY001→pg:cin_firma_deneme; diğerleri kilitli | Doğrulandı (`kurulum/_kabul_baslangic_snapshot.json`) | **GEÇTİ** |
| Kaynak SQLite yedek | FL08BVD | Ray_Aktarim_…/veri_yedek | Var | Var | **GEÇTİ** |
| SQLite DENEME klasörü C:\CinMuhasebe\DENEME_… | — | — | Var | **Yok** (bu makinede) | **DENENMEDİ** / ortam notu |
| Günlük bağlantı değişmedi | FL08BVD | — | Değişmemiş | Proje kökünde baglanti_ayari yok; dist temizlendi | **GEÇTİ** |

## 2) İzole kopya + DENEME profil

| Test | Durum | Not |
|------|--------|-----|
| cin_sistem/firma_kabul_20261105 TEMPLATE kopya | **KALDI** (ortam) | `cin_app` CREATEDB yok. Script: `kurulum/sunucu/03_pg_kabul_kopya.ps1` (ana makine, postgres) |
| DENEME profil | **GEÇTİ** | `%LOCALAPPDATA%\CinMuhasebeKabulDeneme_20261105` |
| Masaüstü kısayol | **GEÇTİ** | `Cin Muhasebe - Ag Deneme - 05.11.2026.lnk` (günlük kısayola dokunulmadı) |
| Yazma test DB | **DENENMEDİ** (izole) | Yazma senaryoları işaretli yardımcı tablolar + salt okunur/mutabakat ile sınırlı; deneme DB üzerine toplu silme yok |

## 3) Aktarım mutabakatı (yeniden)

Kanıt: `kurulum/_kabul_mutabakat.json`

| Ölçüm | Sonuç | Durum |
|-------|--------|--------|
| Firma tablolar eşleşen | 249/249 | **GEÇTİ** |
| Sistem tablo fark | 0 | **GEÇTİ** |
| Dokuz sayım (isim+değer) | cari 1098, stok 3031, satış 9771, alış 1080, stok_har 31909, finans_har 9819, finans_hes 169, sipariş 228, irsaliye 10 | **GEÇTİ** |
| Mali (ROUND_HALF_UP) | fark listesi boş | **GEÇTİ** |
| TR karakter örneği | eşleşti | **GEÇTİ** |
| Sequence last_value ≥ MAX(id) | OK (sonra DEFAULT onarımı) | **GEÇTİ** |

### Bulunan hata ve düzeltme

- **Hata:** Firma PG tablolarında `id` için SERIAL/DEFAULT yoktu → ham INSERT `id NULL` kırılırdı. `pg_sequence_ayarla` yalnız mevcut sequence’e setval yapıyordu.
- **Düzeltme:** `database/pg_helpers.py` sequence yoksa oluşturur + DEFAULT bağlar. Deneme DB’de 242 tablo onarıldı (`_kabul_sequence_onar.json`).
- **Hata:** `gecis_calistir` LAN’da `pg:…` yolunu yerel `muhasebe.db` ile ezme riski.
- **Düzeltme:** `database/system/gecis.py` — `pg:` veya ağ kipinde AŞAMA6 atlanır.

## 4) EXE giriş (terminal)

| Test | Durum | Kanıt |
|------|--------|-------|
| PG + RAY001 API duman | **GEÇTİ** | `_kabul_exe_giris_smoke.json` (1098 cari / 3031 stok / 5 kullanıcı) |
| EXE süreç + pencere başlığı | **GEÇTİ** (açılış) | `MainWindowTitle=Cin Muhasebe` (dist/DENEME tam kopya) |
| Kullanıcı girişi + cari/stok/fatura UI turu | **DENENMEDİ** | Pencere kısa süre sonra kapandı; etkileşimli tur tamamlanamadı |
| Ana makine (CGSE5GK) EXE | **DENENMEDİ** | Bu oturumda yetkili masaüstü erişimi yok |
| Kilitli firmalar UI | **DENENMEDİ** (UI) | DB’de aktif=false doğrulandı |

## 5) Eşzamanlı / işlem doğruluğu (servis+SQL)

Kanıt: `kurulum/_kabul_islem_testleri.json`

| Senaryo | Durum |
|---------|--------|
| Firma hedef + kilitler | **GEÇTİ** |
| Sequence satis_faturalari | **GEÇTİ** |
| Fatura no advisory lock (PG) | **GEÇTİ** — `fatura_no_ayir(session)` + `pg_advisory_xact_lock` |
| Optimistic lock row_version | **GEÇTİ** |
| Çift onay örnek sayım | **GEÇTİ** (servis ikinci onayda reddeder; UI çift tık **DENENMEDİ**) |
| İki PC eşzamanlı fatura/barkod | **DENENMEDİ** |
| Barkod EXE | **DENENMEDİ** |

Kod: `SatisFaturasiService.fatura_no_ayir` / `AlisFaturasiService.fatura_no_ayir` (MAX+1 kuralı + transaction kilidi).

## 6) Bağlantı kopması / mükerrer

Kanıt: `kurulum/_kabul_baglanti_kopma.json` (PG/ağ genel kapatılmadı)

| Senaryo | Durum |
|---------|--------|
| Transaction rollback → yarım kayıt yok | **GEÇTİ** |
| Unique belge_no → ikinci INSERT red | **GEÇTİ** |
| statement_timeout + reconnect | **GEÇTİ** |
| Dispose sonrası yeni bağlantı | **GEÇTİ** |
| EXE UI kopma/mesaj metni | **DENENMEDİ** |

## 7) TLS / sertifika

Kanıt: `kurulum/_kabul_tls_yedek.json`

| Senaryo | Durum |
|---------|--------|
| sslmode=require TLSv1.3 | **GEÇTİ** |
| sslmode=verify-full (host 192.168.1.114) | **GEÇTİ** (`%APPDATA%\postgresql\root.crt` mevcut) |
| Yanlış sunucu adı reddi | **GEÇTİ** |
| DENEME profil sslmode | verify-full yazılabilir / testte require ile de denendi |

## 8) Yedek + ayrı hedefe geri yükleme

| Adım | Durum | Kanıt |
|------|--------|-------|
| pg_dump -Fc sistem+firma (aynı etiket) | **GEÇTİ** | `%LOCALAPPDATA%\CinMuhasebeTest\yedekler_pg\pg_kume_kabul_2026-11-05_131615\` |
| SHA-256 sistem | `99c70fe00c9d2ed46d6244a74b0c90d6d2f88ed3ce2961cf1ef7670b43f360e7` | |
| SHA-256 firma | `07e6e5fc02040d8e2bc8f5c45edbc55251ad7ab6e07230a5cda93f2619e49af4` | |
| Ayrı hedefe pg_restore | **DENENMEDİ** | CREATEDB/superuser gerekir — `kurulum/sunucu/04_pg_restore_ayri_hedef.ps1` |

## 9) Canlı geçiş planı (uygulanmadı)

Kaynak fark: `kurulum/_kabul_canli_kaynak_fark.json`

- Aktarım yedeği max belge tarihi ~ **2026-10-21**; yedek zamanı **2026-11-04 19:40**.
- Bu terminaldeki `%LOCALAPPDATA%\MuhasebeProgrami\data\muhasebe.db` sayıları yedekle aynı (9771/31909); mtime 2026-11-03.
- EvoBulut UI’da **04.11–05.11.2026** satış faturaları görüldü → canlı operasyon devam ediyor; **04.11 deneme aktarımı canlı kesim değildir**.

Önerilen sıra (canlı gün):

1. Yazmaları durdur (Cin + Evo).  
2. Ana makinede tutarlı pg_dump **veya** güncel SQLite yedek.  
3. Yeni boş `cin_sistem` / `cin_firma_ray` (DENEME adları değil).  
4. Aktarım + mutabakat + sequence onarım.  
5. İki PC’de aynı EXE SHA, verify-full, RAY001 açılış.  
6. Eski SQLite’ı salt okunur arşiv; çift yazım yok.  
7. Geri dönüş: PG’deki yeni kayıtları SQLite’a kör kopya sanma — PG dump + fark aktarımı planla.

## 10) Teslim artefaktları

- Bu dosya + `kurulum/GECIS_KABUL_TESTLERI_2026-11-05.json`
- Başlangıç `GECIS_RAPORU.json` **korundu**
- Ana makine scriptleri: `kurulum/sunucu/03_pg_kabul_kopya.ps1`, `04_pg_restore_ayri_hedef.ps1`
- Araçlar: `tools/_kabul_*.py`

## Ana makinede çalıştırılacak adımlar

1. `kurulum\sunucu\03_pg_kabul_kopya.ps1` (postgres) → kabul DB’leri.  
2. Aynı EXE SHA’yı CGSE5GK’ye kopyala; DENEME kısayolu.  
3. `04_pg_restore_ayri_hedef.ps1 -DumpKlasor <yedek klasörü>`.  
4. İki PC’de RAY001: fatura/tahsilat/barkod/eşzamanlı + UI kopma mesajı.
