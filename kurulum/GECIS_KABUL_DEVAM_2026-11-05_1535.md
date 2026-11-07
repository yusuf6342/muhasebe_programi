# Geçiş kabul devam raporu — 2026-11-05 15:35

**Makine:** DESKTOP-FL08BVD (terminal, 192.168.1.133) → PG DESKTOP-CGSE5GK (192.168.1.114)  
**Kısıtlar:** Günlük bağlantı değiştirilmedi · DNM aktarımı başlatılmadı · DB/HBA betikleri yeniden çalıştırılmadı

## Özet

| Alan | Sonuç |
|------|--------|
| 4 DB verify-full | **GEÇTİ** (TLSv1.3) |
| Kabul mutabakatı | **GEÇTİ** (251/251, mali fark yok) |
| Restore mutabakatı | **GEÇTİ** (mali/dokuz eşleşti; yalnız 2 dump-sonrası test tablosu eksik) |
| Terminal EXE SHA | **GEÇTİ** `0BD255BA…C27C` (dist = DENEME profil) |
| Ana makine EXE SHA | **DENENMEDİ** (C$ paylaşım erişimi yok) |
| API/yazma testleri (kabul DB) | **GEÇTİ** |
| EXE GUI + iki PC UI | **DENENMEDİ** |

## 1) verify-full (4 DB)

Kanıt: `kurulum/_kabul_verify_full_4db.json` — `hepsi_ok: true`

| DB | TLS |
|----|-----|
| cin_sistem_kabul_20261105 | TLSv1.3 |
| cin_firma_kabul_20261105 | TLSv1.3 |
| cin_sistem_restore_20261105 | TLSv1.3 |
| cin_firma_restore_20261105 | TLSv1.3 |

## 2) Mutabakat (ayrı değerlendirme)

Kanıt: `kurulum/_kabul_cift_mutabakat.json`, `kurulum/_kabul_restore_sema_fark.json`

### Kabul ← deneme — **GEÇTİ**
- Firma 251/251, sistem fark 0, mali fark `[]`, dokuz OK  
- RAY001 → `pg:cin_firma_kabul_20261105`

### Restore ← deneme — **GEÇTİ** (mali; şema notu ile)
- Mali fark `[]`, dokuz OK, ortak tablo satır farkı **0**
- Firma fark adedi **2**: `kabul_kopma_test`, `kabul_no_lock_test` (dump **sonrası** script tabloları; restore’da yok — beklenen)
- İlk ölçümde görünen 155× `hedef=-1` **yanlış pozitif**: eksik tablo sonrası aborted transaction. `_pg_sayimlar` SAVEPOINT ile düzeltildi; yeniden ölçüm gerçekçi.

**Kaynak yedekten sonra değişim:** İş verisi değişmemiş; yalnızca kabul test yardımcı tabloları deneme/kabul’a eklenmiş.

## 3) EXE SHA + DENEME giriş

| Kontrol | Durum | Kanıt |
|---------|-------|-------|
| dist EXE SHA | **GEÇTİ** | `0BD255BA888BF68F0AE1EF502AD562AE3DE4C0FBFEEE19453EF37308CB64C27C` |
| DENEME profil EXE aynı SHA | **GEÇTİ** | `kurulum/_kabul_exe_giris_smoke.json` |
| CGSE5GK aynı SHA | **DENENMEDİ** | `\\DESKTOP-CGSE5GK\C$` / `\\192.168.1.114\C$` erişim engeli |
| API duman (verify-full → kabul) | **GEÇTİ** | RAY001, users, cari 1098, stok 3031 |
| EXE GUI oturum | **DENENMEDİ** | Süreç açıldı; yeni `acil_asama_log` yok; pencere başlığı boş |

Profil `baglanti_ayari.json`: `cin_sistem/firma_kabul_20261105`, `sslmode=verify-full`, `ortam=DENEME`.

## 4) Yazma / eşzamanlı / kopma (kabul DB, verify-full)

Kanıt: `kurulum/_kabul_islem_testleri.json`, `kurulum/_kabul_baglanti_kopma.json`

| Senaryo | Durum |
|---------|-------|
| Fatura sequence + advisory lock + optimistic lock | **GEÇTİ** |
| Cari okuma + kontrollü yazma | **GEÇTİ** |
| Stok okuma + kontrollü yazma | **GEÇTİ** |
| Barkod okuma | **GEÇTİ** |
| Tahsilat okuma (`satis_faturasi_tahsilatlari`) | **GEÇTİ** |
| Eşzamanlı fatura_no | **GEÇTİ** |
| Bağlantı kopması / rollback / mükerrer / timeout+reconnect | **GEÇTİ** |
| UI üzerinden fatura/cari/stok/tahsilat/barkod | **DENENMEDİ** |
| İki PC eşzamanlı UI | **DENENMEDİ** |

## 5) Yapılmayanlar (bilinçli)

- Günlük `baglanti_ayari` değiştirilmedi  
- DNM / 31.08.2026 dönemi aktarımı başlatılmadı  
- `03`/`04`/`06` DB-HBA betikleri yeniden çalıştırılmadı  

## Kalan engeller

1. Ana makinede aynı EXE SHA’yı yerelde doğrula (`Get-FileHash …\CinMuhasebe.exe`).  
2. Her iki PC’de DENEME bat ile GUI giriş + UI senaryoları.  
3. İki PC eşzamanlı fatura/barkod.
