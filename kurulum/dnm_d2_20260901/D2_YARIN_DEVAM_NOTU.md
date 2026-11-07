# D2 — Yarın devam notu

**Güncelleme (2026-11-07 akşam):** Kart Açılış Tarihi geliştirmesi kodda tamamlandı; D1/D2 yerel yedek alındı.  
Mali yazım / K05 / K06 / EXE **kapalı**. EvoBulut kullanıma devam.

## Tamamlanan (bugün)
- Terminal HBA + D2 salt-okuma; Cari22/FIFO kullanıcı kararlarıyla netleştirildi.
- Sayısal aktarım önizlemesi: `D2_AKTARIM_ONIZLEME.json` (v2, `kaynak_okuma` ~17:39+03).
- **Kart Açılış Tarihi (Cin Muhasebe):**
  - Normal yeni cari/stok: ilk başarılı kayıt → `olusturma_tarihi` + `kart_acilis_tarihi`.
  - Devir/Evo Devir yeni kart: Kart Açılış = plan açılışı (`DevirIs.acilis_tarihi` veya D2 `ACILIS_SOZLESME.d2_acilis` = **01.09.2026**); dayanak «Devir»; sistem zamanı `olusturma_tarihi` ayrı.
  - Eski kart backfill yok; 49 pasif stok `kaynak_stok_id` ile create/update engelli.
  - Test: `tests/test_kart_acilis_tarihi.py` (17 passed).
  - Evo yazım yolu: `entegrasyon/evo_devir/aktarim.py` plan tarihini bağladı.
- Şema: `cari_kartlar` / `stok_kartlari` kolonları (`olusturma_tarihi`, `kart_acilis_tarihi`, `kart_acilis_dayanak`) — SQLite/PG ALTER; `cari_kart_sema` v4+v5.

## Kullanıcı kararları (kesin)
1. **Cari22×21** → 31.08.2026 kapanış ve D2 açılış **0 TL** (beyan). Eylül+ hareketler korunur; ekstre yok.
2. **49 pasif stok** → D2 stok aktarım/güncelleme **dışı** (belge/cari silinmez).
3. **Sıfır maliyet** teyit → aynen 0; doldurma yok. **10753** hem 49 hariç hem sıfır listesinde → **hariç öncelikli**; kaynak teyit 14, aktarım kapsamı **13**.

## Açık kalan gerçek eksikler
- Tüm cari açılış toplamı (sayısal) henüz hesaplanamadı.
- D2 dönem belge adedi (01.09 → kesim) ayrı onaylı çekim bekliyor.
- Banka 31.08 kapanış bakiyesi (Excel dönem net ≠ kapanış) — HESAPLANAMADI.
- Hedef D2 firma DB: şema hazır, **iş/kart kaydı 0** (mali yazım yok).
- **Ana makine şema:** Kart açılış kolonları uygulama açılışında `cari_kart_schemasini_guncelle` / stok ALTER ile eklenir. Henüz uygulanmamış D2 hedef DB’de yarın ilk uygulama/bağlantıda otomatik; manuel kontrol için firma DB’de kolon varlığı doğrulanır (aşağı).
- D2 mali aktarım / K05 / EXE — **kapalı**; ayrı izin gerekir.

## Yarın sabah sıra
1. EvoBulut’ta kayıt girişine ara ver; **son kayıt kesim anını** not et (tarih-saat +03).
2. Kaynak verileri kesim sonrası yeniden al; önizlemeyi yenile (komutlar aşağı).
3. Önizlemeyi kullanıcıyla doğrula.
4. Gerekirse D2 hedef DB’de kart açılış kolonlarını doğrula (şema).
5. K05/mali yazım **ayrı izin** olmadan açma / yazma.
6. Devir 2 bittikten sonra Devir 1’e `DEVIR1_DEVAM_NOTU` ile devam.

## Ana makine — kart açılış şema kontrolü (mali yazım değil)

Repo kökünde, hedef firma DB bağlıyken uygulama şema güncellemesi zaten ALTER ekler. Elle doğrulama (ör. `psql` / salt okuma):

```sql
SELECT column_name FROM information_schema.columns
 WHERE table_name IN ('cari_kartlar','stok_kartlari')
   AND column_name IN ('olusturma_tarihi','kart_acilis_tarihi','kart_acilis_dayanak')
 ORDER BY 1;
```

Eksikse uygulamayı bir kez firma seçerek açmak veya mevcut `cari_kart_schemasini_guncelle` yolunu çalıştırmak yeter; **eski satırları doldurma**.

## Yarın uygulanacak komutlar

```powershell
cd C:\Users\cigde\OneDrive\Belgeler\GitHub\muhasebe_programi

# Sayısal önizlemeyi yeniden hesapla (mali yazım yok)
.\.venv\Scripts\python.exe -m tools.dnm_d2.d2_aktarim_onizleme_hesapla

Get-Content .\kurulum\dnm_d2_20260901\D2_AKTARIM_ONIZLEME_OZET.json -Encoding UTF8

# (İsteğe bağlı) D2 salt okuma
.\.venv\Scripts\python.exe -m tools.dnm_d2.pg_d2_terminal_salt_okuma

# Kart açılış birim testleri
.\.venv\Scripts\python.exe -m pytest tests/test_kart_acilis_tarihi.py -q
```

Kesim anı belirlendikten sonra önizleme JSON’daki `donem.yarin_kesim` alanını güncelleyip aynı komutu tekrar çalıştırın.  
**D2 dönem hareket çekimi** (01.09 → kesim) ayrı onaylı adımdır.

## Koruma / devam
- D1 kaynak / yedek / `surumler/devam_noktasi_20261107_144902` korunur.
- Yerel tarihli yedek: `kurulum/_yedek_yerel/` altında günün damgası (Git’e eklenmez).
- **Devir 2 sonrasında Devir 1’e** `kurulum/dnm_d1_20260831/DEVIR1_DEVAM_NOTU` ile devam edilecek.
