# Teslim — Hızlı Satış başlangıç müşterisi 1.1.46 (2026-11-24)

## Özet

| Madde | Sonuç |
|--|--|
| Sürüm | **1.1.46** |
| Commit | `4df243c1bdd1cc95874ec0d5156c79812c39b544` |
| Branch | `feature/yerel-ag-postgresql` |
| Push | `origin/feature/yerel-ag-postgresql` (force yok) |
| T1 güncelleme | OK — eski kısayol, SHA eşleşti |
| USB | OK — Ortak kurulum + ZIP SHA eşleşti |

## Değişen dosyalar (commit)

- `branding.py` — APP_VERSION 1.1.46
- `ana_panel_ui.py` — Ayarlar → HIZLI SATIŞ AYARLARI
- `hizli_satis_ayarlari_ui.py` — yeni ayar ekranı
- `database/hizli_satis_ayarlari_service.py` — firma DB ayarı
- `database/hizli_satis_service.py` — şema hazırlık
- `hizli_satis_ui.py` — başlangıç müşteri / yeni satış reset / F2 korunur
- `tests/test_hizli_satis_baslangic_musteri.py`

## Ayar saklama

- Tablo: `hizli_satis_baslangic_ayarlari` (firma DB, `firma_id` PK)
- Alanlar: `baslangic_mod` (`BOS` \| `ATANAN`), `baslangic_cari_id`
- Kapsam: firma bazlı; Ana/T1/T2 aynı DB’yi okur
- Kurulum klasöründe tutulmaz; sürüm güncellemesi silmez
- Kayıt yoksa davranış: **BOS** (müşteri alanı boş; yeni perakende kartı oluşturulmaz)
- İşlem sırası F2 seçimi ayarı değiştirmez; yeni satışta ayara döner
- Beklet/Çağır belge müşterisini korur

## Testler

- `tests.test_hizli_satis_baslangic_musteri` → 7/7 OK
- Ekran doğrulama (`_tmp_hs_baslangic_ekran_dogrula.py`) → boş/atanmış açılış, F2 ayarı bozmaz → OK
- Canlı satış / ödeme yazılmadı

## T1 (DESKTOP-FL08BVD)

| Madde | Değer |
|--|--|
| Kısayol | `C:\Users\cigde\Desktop\Cin Muhasebe.lnk` (ad/hedef korundu) |
| Hedef / WorkDir | `%LOCALAPPDATA%\CinMuhasebe\DNM_D2\CinMuhasebe\` |
| Çalışan EXE | aynı yol — PID doğrulandı |
| Uygulama SHA-256 | `DAB6CC68D7D2B8653B3E63D92B89379C8C553254257FEE054CAA166D0D4AEEF9` |
| Geri dönüş yedeği | `%LOCALAPPDATA%\CinMuhasebe\DNM_D2_GERI_20261124_164015` |
| baglanti / DB | korundu |

## Ortak kurulum (Ana / T2)

| Madde | Yol |
|--|--|
| Yerel Setup | `C:\CinMuhasebeKurulum\CinMuhasebe_Setup_1.1.46_20261124.exe` |
| Yerel Ortak | `C:\CinMuhasebeKurulum\CinMuhasebe_Ortak_Kurulum_1.1.46.exe` |
| USB klasör | `D:\USB_TESLIM_20261124_HIZLI_SATIS_1.1.46\` |
| USB Ortak | `D:\USB_TESLIM_20261124_HIZLI_SATIS_1.1.46\CinMuhasebe_Ortak_Kurulum_1.1.46.exe` |
| Ortak SHA-256 | `B4A25BC2E9A01AE00359BAC62F65BCFBDBBE0194577512A09AC1429406809E36` |
| USB SHA doğrulama | **True** (yerel = USB) |
| D2 ZIP | `CinMuhasebe_DNM_D2_GUNCELLE_20261124_1642.zip` · SHA `8FE09FA90AC253465B551724F6C88832D20D1B3E52649D73E37823A2E4B5FBCC` · USB OK |
| Rol seçimi | `CinMuhasebe\GUNCELLE.cmd` → `[2] Ana Makine` / `[3] Terminal 2` |
| Yönerge | `D:\...\KURULUM_YONERGESI.txt` + `SHA256.txt` |

## Notlar

- Ana Makine / T2 üzerinde bu oturumda kurulum çalıştırılmadı (USB paket hazır).
- USB’ye tam SonGuncelleme ağaç kopyası yavaş kaldığı için ZIP + GUNCELLE.cmd bırakıldı; Ortak EXE birincil teslimdir.
