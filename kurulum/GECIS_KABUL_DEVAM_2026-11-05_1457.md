# Cin Muhasebe — Kabul Devam (kopya/restore sonrası)

Saat: **2026-11-05 14:57**  
Bu oturum: **DESKTOP-FL08BVD** (terminal)  
Kullanıcı bildirimi: CGSE5GK’te kopya+restore exit 0 (betikler yeniden çalıştırılmadı)

## Özet

| Madde | Durum |
|-------|--------|
| Kabul DB oluşumu (kullanıcı) | Bildirildi: `cin_*_kabul_20261105` |
| Restore DB oluşumu (kullanıcı) | Bildirildi: `cin_*_restore_20261105` |
| Terminal → kabul DB bağlantısı | **KALDI** — `pg_hba`: 192.168.1.133 → `cin_sistem_kabul_20261105` yok |
| Satır/mali mutabakat (kabul/restore) | **DENENMEDİ** (bağlantı engeli) |
| DENEME profil → kabul çifti (terminal) | **GEÇTİ** (ayar yazıldı; bağlantı hba sonrası) |
| verify-full deneme DB | **GEÇTİ** |
| verify-full kabul DB (LAN) | **KALDI** (hba) |
| İki PC EXE UI testleri | **DENENMEDİ** |
| Günlük bağlantı / DNM | Değiştirilmedi / başlatılmadı |

## Kanıt: pg_hba engeli

```
FATAL: no pg_hba.conf entry for host "192.168.1.133", user "cin_app",
database "cin_sistem_kabul_20261105", SSL encryption
```

`cin_sistem_deneme` aynı host’tan **açılıyor**; yeni DB adları hba’da yok.

## Terminalde yapılanlar

1. DENEME profili kabul çiftine yönlendirildi (`verify-full`):  
   `%LOCALAPPDATA%\CinMuhasebeKabulDeneme_20261105\program\baglanti_ayari.json`  
   → sistem `cin_sistem_kabul_20261105` / firma `cin_firma_kabul_20261105`
2. DENEME kısayolu güncellendi: `Cin Muhasebe - Ag Deneme - 05.11.2026.lnk` (günlük değil)
3. EXE SHA (terminal): `0BD255BA888BF68F0AE1EF502AD562AE3DE4C0FBFEEE19453EF37308CB64C27C`  
   `dist\CinMuhasebe\CinMuhasebe.exe` (24 376 959 bayt, 13:38)
4. Scriptler: `06_pg_hba_kabul_db_izin.ps1`, `07_kabul_mutabakat_yerel.ps1`, mutabakat aracı

## Sıradaki adımlar (somut)

### A) DESKTOP-CGSE5GK — zorunlu (tek blokaj)

Yönetici PowerShell:

```powershell
cd C:\Users\cigde\OneDrive\Belgeler\GitHub\muhasebe_programi
.\kurulum\sunucu\06_pg_hba_kabul_db_izin.ps1
```

Beklenen: 4 `hostssl` satırı + `pg_ctl reload`.

İsteğe bağlı hemen ardından (yerel mutabakat, 127.0.0.1):

```powershell
.\kurulum\sunucu\07_kabul_mutabakat_yerel.ps1
```

Beklenen: exit 0, `kurulum\_kabul_cift_mutabakat.json` kabul_ok=true.

### B) DESKTOP-CGSE5GK — EXE SHA

```powershell
Get-FileHash "...\dist\CinMuhasebe\CinMuhasebe.exe" -Algorithm SHA256
```

Terminal ile **aynı** hash olmalı. Farklıysa aynı `dist\CinMuhasebe` paketini kopyalayın (yeniden derleme gerekmez).  
Profil şablonu: `kurulum\ANA_MAKINE_DENEME_PROFIL.txt` (host `127.0.0.1` veya LAN IP; sslmode verify-full).

### C) Bu sohbete dönüş

hba reload + (mümkünse) 07 çıktısından sonra terminalden mutabakat, verify-full, EXE giriş ve iki PC senaryolarına devam edilir.

## Test tablosu

| Test | Bilgisayar | Durum |
|------|------------|--------|
| Kabul/restore DB varlık (bildirim) | CGSE5GK | **GEÇTİ** (kullanıcı) |
| pg_hba kabul izin | CGSE5GK | **DENENMEDİ** |
| Mutabakat kabul↔deneme | — | **DENENMEDİ** |
| Mutabakat restore | — | **DENENMEDİ** |
| Profil kabul (terminal) | FL08BVD | **GEÇTİ** (dosya) |
| verify-full deneme | FL08BVD | **GEÇTİ** |
| verify-full kabul LAN | FL08BVD | **KALDI** (hba) |
| EXE giriş / fatura / barkod / eşzamanlı / kopma | iki PC | **DENENMEDİ** |
