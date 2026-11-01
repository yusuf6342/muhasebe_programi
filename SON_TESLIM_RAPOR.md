# Son teslim raporu — 1 Kasım 2026 (ev kapanış)

## Bugünkü işler

| Alan | Durum |
|------|--------|
| Fatura Kaydet/Onayla/Yeni, tahsilat, cari/finans bir kez | Kod + testler |
| Hücre klavye / F2 / sağ tık / F10 | Kod + testler |
| Tablo çizgi hizası, müşteri vadesi, teslim saati | Korundu |
| Kompakt iki ölçü grubu (panel ~74×24, dışı ~128×30) + «Yeni» | Uygulandı |
| Konsinye sahiplik / FIFO / kesin alım net / gerçek fatura bağ | Test OK |
| Konsinye raporları (A–I çekirdek) | Servis + UI |
| Kaydet `!entry` (ölü aciklama Entry) | Düzeltildi |
| Fare tek tık + Enter/↓ hız (Excel/overlay yarışı) | HizTest ölçümü OK |
| Mutabakat Excel/PDF tam otomasyon | Kısmi |
| Giriş sonrası her düğme canlı turu | Giriş engeli — kullanıcıda |

Hız raporu (kişisel veri yok): `FATURA_FARE_KLAVYE_HIZ_RAPORU_2026-11-01.md`

## Git

- Commit SHA: *(commit sonrası doldurulur)*
- Dal: `main` → `origin/main` (`yusuf6342/muhasebe_programi`)

## Son EXE

- Klasör: *(derleme sonrası)*
- SHA-256: *(derleme sonrası)*
- Kısayol: `Cin Muhasebe GUNCEL EV TEST 2026-11-01.lnk`
- Veri: `%LOCALAPPDATA%\CinMuhasebeTest\data` (**TEST**)

## Veri yedeği (Git dışı)

- Klasör: `C:\Users\Pc\Documents\CinMuhasebe_Teslim_Yedek_20261101_220608\`
- `TEST_data\` — integrity ok, FK=0
- `GERCEK_salt_okunur\` — canlı MuhasebeProgrami kopyası (ayrı; TEST ile birleştirilmez)
- Manifest: `MANIFEST.json`
- Taşıma: **yerelde hazır** — işyerine USB / kullanıcının özel yöntemi gerekir

## Buton ölçüleri

- Panel içi: ~74×24 (Yeni / Ara / Cari Kart)
- Panel dışı: ~128×30 (üst şerit + satır araçları)
