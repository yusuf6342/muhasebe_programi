# D2 canlı geçiş — durum (2026-11-08)

## Bağlantı (yeniden kontrol)
| Adım | Sonuç |
|------|--------|
| Terminal | `DESKTOP-FL08BVD` / `192.168.1.133` |
| Ana makine IP | `192.168.1.114` (DESKTOP-CGSE5GK) — ICMP ping yok, **TCP 5432 açık** |
| Kimlik | `cin_app` → D2 sistem/firma OK |
| Hedef | `cin_sistem_dnm_d2_20260901` + `cin_firma_dnm_d2_20260901` / firma `DNM_D2` |
| Kabul | Yazılmıyor |
| DB recreate | Yok |

Kanıt: `D2_PG_ERISIM_DURUM.json`, `D2_HEDEF_DURUM_KONTROL.json`

## Kayıt noktası
1. İlk kart denemesi şema eksikliğiyle kısmi kaldı (kasa/banka 32; cari/stok 0) — `olusturma_tarihi` / `kart_acilis_*` yoktu.
2. Şema ALTER uygulandı: `D2_SEMA_UYGULA.json` (`ok: true`), DB yeniden oluşturulmadı.
3. Aktarım yeniden başlatıldı (ImportBatch mükerrer koruması; uygulanan banka/kasa atlanır).

## Zorunlu son kabul
- `tools/dnm_d2/d2_son_mutabakat.py` — kaynak/hedef/fark/açıklama; kaynaksız düzeltme yok.
- `aktarim_tamamlandi` / `canli_kullanim_hazir` yalnız mutabakat KABUL ise.
- Fark aktarım: `d2_fark_aktar.py` (08.11); öncesi durdurma bildirimi.

## Politika
Opening+Docs; D1 kasa açılışı; GRP_TOP yazılmaz; net cari tek başına yetmez.
