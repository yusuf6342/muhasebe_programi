# D2 — Yarın devam notu

**Gün sonu (2026-11-07 ~18:15+03):** Kart açılış + PG/kabul/D1–D2 araçları Git’te; mali yazım / K05 / K06 / EXE **kapalı**.

## Git’e gidenler (bu dal: `feature/yerel-ag-postgresql`)

| Commit | İçerik |
|--------|--------|
| `ed39dad` | Kart Açılış Tarihi (cari/stok), Devir plan tarihi, testler, bu notun ilk sürümü |
| `1c19a90` | PG/LAN `pg:` firma yolu, dialect/migrate, kabul runner’ları + GECIS dokümanları, mesajlaşma, `tools/dnm_d1` + `tools/dnm_d2` kaynak araçları, sunucu HBA/D2 hedef scriptleri |

**Git’e eklenmedi (bilinçli):** `kurulum/dnm_d1_20260831` / D2 kaynak-kanıt JSON dökümleri, `baglanti_ayari.json`, parolalar, `.env`, paket ZIP’ler, `Banka_Guncelleme_Yedek`, yerel `_yedek_yerel`, EXE/`dist`.

## Yerel yedekte kalanlar

1. **Tam D1/D2 çalışma kökü (kaynak+kanıt+devam):**  
   `kurulum\_yedek_yerel\d1_d2_20261107_175657`  
   (D1 `DEVIR1_DEVAM_NOTU` / `surumler/devam_noktasi_20261107_144902` dahil)
2. **Commit dışı WIP (yama + seçili untracked):**  
   `kurulum\_yedek_yerel\wip_gunsonu_20261107_181541`  
   - `patches/evobulut_client.patch` (Evo stokjq/web yardımcıları — yarım/araç)  
   - `untracked/kurulum/dnm_d2_20260901` özet/plan kopyası  
   - `git_status_porcelain.txt`

D1 kaynakları ve devam noktaları **korunur**; üzerine yazma yok.

## Kullanıcı kararları (kesin)
1. Cari22×21 → 31.08 kapanış / D2 açılış **0 TL**; Eylül+ hareketler korunur.
2. **49 pasif stok** → D2 stok aktarım/güncelleme dışı.
3. Sıfır maliyet teyit; **10753** hariç öncelikli (aktarım sıfır kapsamı 13).

## Yarına kalan işler
1. EvoBulut’ta kayıt ara; **kesim anı** not et → kaynak yenile → `d2_aktarim_onizleme_hesapla` ile önizleme yenile.
2. Önizlemeyi kullanıcıyla doğrula; HESAPLANAMADI alanlar (cari açılış toplamı, D2 belge adedi, banka 31.08).
3. Ana makine D2 hedef DB’de kart-açılış kolonlarını doğrula (ALTER uygulama açılışıyla).
4. K05 / mali yazım / EXE — **ayrı izin olmadan yok**.
5. Devir 2 sonrası Devir 1: `kurulum/dnm_d1_20260831/DEVIR1_DEVAM_NOTU`.
6. İsteğe bağlı: `evobulut_client` WIP yamasını gözden geçir / birleştir (yerel yedekte).

## Yarın komutlar

```powershell
cd C:\Users\cigde\OneDrive\Belgeler\GitHub\muhasebe_programi
.\.venv\Scripts\python.exe -m tools.dnm_d2.d2_aktarim_onizleme_hesapla
Get-Content .\kurulum\dnm_d2_20260901\D2_AKTARIM_ONIZLEME_OZET.json -Encoding UTF8
.\.venv\Scripts\python.exe -m pytest tests/test_kart_acilis_tarihi.py tests/test_sqlite_to_postgres_gecis.py -q
```
