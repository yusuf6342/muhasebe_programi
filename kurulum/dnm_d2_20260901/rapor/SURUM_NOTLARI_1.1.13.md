# Cin Muhasebe 1.1.13 — sürüm notları

**Dal:** `feature/yerel-ag-postgresql`  
**Commit:** `c49674b845456ed94a52fc3ded17b9705f9d9af1` (+ önceki `142dc8b` 1.1.12)  
**Derleme:** `C:\CinMuhasebeDerleme\20261118_145544` (bu committen)

## Bu sürümde

- Canlı DNM_D2’deki Cursor demo kredi kümesi (`KRK-DEMO-BC880F` / `KTO-2026-0001` / bağlı GDF) iptal mekanizmasıyla temizlendi; gerçek faturalar (HAG000002, EVB-BNC-*, NAV/OMK) korundu.
- Banka hareketinden kaynak evrak: KRK / KTO / KTI / KKE / GDF / açılış; Sil ile bağlı etkiler birlikte iptal.
- BANKA hesap sayfasında Belgeyi Aç (KASA ile aynı).
- Canlı firmaya örnek veri / demo kredi yazımı engellendi; AG’de iskelet hesap seed’i mevcut hesap varken atlanır.
- 1.1.12 ile gelen hizmet ödeme/tahsilat ve KK hesap filtresi dahildir.

## Kurulum

Kurulum mevcut firma verilerini ve ayarlarını korur. Canlı DB / yedek / şifre paket veya Git’e eklenmez.

## Paket

- EXE (onedir): `CinMuhasebe\CinMuhasebe.exe`
- Kurulum: `CinMuhasebe_Setup_1.1.13_20261118.exe`
