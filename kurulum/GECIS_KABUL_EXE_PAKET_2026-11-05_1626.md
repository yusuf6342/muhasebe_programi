# EXE paket + ekran test raporu — 2026-11-05 16:26

Günlük kısayol değiştirilmedi. DNM aktarımı başlatılmadı.

## Paket (Google Drive)

**Tam yol:**  
`C:\Users\cigde\OneDrive\Belgeler\GitHub\muhasebe_programi\paket\CinMuhasebe_AG_DENEME_20261105_20261105_1626.zip`  
(~124.7 MB)

**EXE SHA-256:** `E76DDA517073B80807357A06E87C1A177B61B1E91339F30EBDB6500A126D2896`

İçerik: `CinMuhasebe\` (onedir) + `kurulum\01_ANA_MAKINE_KUR.ps1` + `root.crt` + `OKU_BENI.txt`.  
Python/Cursor gerektirmez. Ana makinede ZIP aç → `kurulum\01_ANA_MAKINE_KUR.ps1` (parola Credential Manager’a güvenli girilir) → masaüstü **Cin Muhasebe - Ağ Deneme - 05.11.2026**.

Hedef: RAY001 · `cin_sistem_kabul_20261105` / `cin_firma_kabul_20261105` · host `192.168.1.114` · `verify-full`.

> Eski ZIP’leri (`…_1547`, `…_1558`, `…_1609`, `…_1619`) kullanmayın — PG açılış düzeltmeleri bu pakette.

## A) API / SQL (önceki + korunan) — ayrı

| Test | Durum | Kanıt |
|------|-------|-------|
| 4 DB verify-full | **GEÇTİ** | `_kabul_verify_full_4db.json` |
| Kabul mutabakat | **GEÇTİ** | `_kabul_cift_mutabakat.json` |
| Restore mutabakat | **GEÇTİ** | mali OK; yalnız dump-sonrası test tabloları |
| Fatura/cari/stok/tahsilat/barkod/eşzamanlı (SQL) | **GEÇTİ** | `_kabul_islem_testleri.json` |
| Bağlantı kopması | **GEÇTİ** | `_kabul_baglanti_kopma.json` |

## B) Gerçek ekran — ayrı

| Test | Durum | Kanıt |
|------|-------|-------|
| Terminal DENEME profil + kısayol | **GEÇTİ** | `%LOCALAPPDATA%\CinMuhasebeKabulDeneme_20261105`, masaüstü lnk |
| Terminal dist ↔ profil EXE SHA | **GEÇTİ** | aynı `E76DDA…2896` |
| verify-full / CA / TCP | **GEÇTİ** | kurulum + 4db probe |
| cin_app parola (Credential Manager) | **GEÇTİ** | mevcut kayıt; kur betiği `cmdkey` ile güvenli giriş |
| EXE açılış → `pg:cin_firma_kabul_20261105` | **GEÇTİ** | `acil_asama_log` 16:29: `baslatma_adimlari TAMAM` |
| Kullanıcı giriş ekranı | **GEÇTİ** | «Cin Muhasebe - Kullanıcı Girişi», kullanıcı=admin |
| Admin şifre ile giriş + fatura/cari/stok/tahsilat/barkod UI | **DENENMEDİ** | interaktif uygulama parolası bu oturumda girilmedi |
| Eşzamanlı iki PC UI | **DENENMEDİ** | ana makine paketi henüz kurulmadı |
| Ana makine EXE SHA karşılaştırması | **DENENMEDİ** | CGSE5GK’te kurulum sonrası `Get-FileHash` / `KURULUM_SONUC.json` |

## Bu turda düzeltilen engeller (yeniden derleme gerekti)

1. PG `depolar.varsayilan = 1` boolean hatası  
2. Boş yerel `muhasebe.db` ile RAY001 `pg:` yolunun ezilmesi (geri alındı + koruma)  
3. PG’de SQLite açılış yedeği / `sqlite_master`  
4. `kredi_karti_ekstreleri` 3 kolon eksiği (kabul DB’de eklendi)

## Ana makine adımları

1. Drive’a `…_1626.zip` yükle, aç.  
2. `powershell -ExecutionPolicy Bypass -File .\kurulum\01_ANA_MAKINE_KUR.ps1`  
3. SHA’yı terminalle karşılaştır (`E76DDA…2896`).  
4. DENEME kısayolu → giriş → UI senaryoları.  
5. Sonuçları bu rapora işleyin.
