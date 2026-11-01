# Fatura fare / klavye hız ve Kaydet–Onayla raporu — 1 Kasım 2026

## Veri kopyası

| | |
|--|--|
| Canlı kaynak | `%LOCALAPPDATA%\MuhasebeProgrami\data` (dokunulmadı) |
| Test kopyası | `%LOCALAPPDATA%\CinMuhasebeHizTest\data` |
| Kopyalama | SQLite `backup` API; `system.db` company `db_path` yalnız HizTest’e yazıldı |
| Integrity | `muhasebe.db` / `system.db` = ok |
| Anonim hacim (RAY) | ~2152 KB; satış faturası başlangıç 2; max satır/fatura ≈ 3; stok 3; cari 3 |
| Sentetik stres | Aynı kopyada 50 satırlı fatura (ayrı etiketlendi) |
| Kanıt | `canli_degismedi=true`, `kopya_ayri=true`, oturum DB = HizTest yolu |

Ham JSON: `_hiz_olcum_sonuc.json` (kişi/ürün adı yok).

## Sürüm / ortam

- Kaynak worktree: `muhasebe_programi_uzak_20261101_152451`
- Ölçüm: `.venv` + `MUHASEBE_DB_DIR=...\CinMuhasebeHizTest\data`
- EXE bu turda yeniden derlenmedi (önce kaynak doğrulama)
- Donanım: ev Windows 10; ekran ölçeği ölçümde zorlanmadı

## Kaydet / Onayla — `invalid command name ...!entry…`

**Neden:** Satış faturası açılışında gizli stub `Entry` (`girdiler['aciklama']`) `_siparis_miras_ust_panelini_kaldir` ile yok ediliyordu; `_ek_fatura_bilgileri` anahtar olduğu için yeni Entry kurmuyordu. Kaydet `girdiler['aciklama'].get()` → Tcl `invalid command name`.

**Düzeltme:** Canlılık kontrolü + zorunlu yeni Entry; kayıtta `_aciklama_metni_oku()` (Text/Not öncelikli).

**A–D (HizTest kopyası, açık hücre miktar=5, uzlaşılan 3500):**

| Yol | Sonuç | Kalıcı |
|-----|--------|--------|
| A fare Kaydet | OK ~8.5 s | fid oluştu, miktar 5, onaylı değil |
| B F1 | OK ~7.1 s | aynı |
| C fare Onayla | OK ~9.1 s | onaylandi=true |
| D F4 | OK ~7.7 s | onaylandi=true |

UI `showerror` yok; yeniden `getir` ile miktar doğrulandı. Mükerrer canlı yazım yok (yalnız kopya).

## Fare tek tık / klavye — nedenler ve düzeltmeler

1. **180 ms gecikmeli açılış** → senkron `hucre_duzenle`
2. **Excel çizgi `ButtonRelease` / `TreeviewSelect` yenilemesi** editör açılırken UI’yi saniyelerce kilitliyordu → editör açıkken `planla` no-op
3. **Vurgulu overlay** ile yarış → overlay zamanlayıcı iptali; gereksiz toplu destroy kaldırıldı
4. **Her gezinmede tam tablo `_satir_listesini_yenile`** → değer değişmediyse atla; değiştiyse `_satir_tek_satir_yenile`
5. **`_tab_ilerle` after_idle + 80 ms kilit** hızlı ↓ tuşunda editörsüz hücre → senkron geçiş, kilit anında kalkar

## Hız tablosu (son ölçüm)

Ölçüm sınırı: tıklamada senkron handler süresi (after kuyruğu hariç); tuşta `event_generate` + `update_idletasks`. Kaydet/Onayla tam servis süresi ayrı.

| Senaryo | Satır | n | P50 ms | P95 ms | Max ms | Hata | Hedef |
|---------|------|---|--------|--------|--------|------|-------|
| Fare tek tık | 3 (gerçek hacim) | 50 | **5.5** | **8.7** | 10.3 | 0 | ≤40 / ≤100 |
| Fare tek tık | 50 sentetik | 30 | **5.2** | **10.5** | 11.6 | 0 | ≤40 / ≤100 |
| Enter | 3 | 50 | **0.03** | 135.6* | 192 | 0 | ≤40 / ≤100 |
| Down | 3 | 50 | **0.02** | **0.03** | 0.07 | 0 | ≤40 / ≤100 |
| Down | 50 sentetik | 50 | **0.02** | **0.05** | 0.09 | 0 | ≤40 / ≤100 |

\*Enter P95: ara sıra sütun geçişinde ağır idle/yenileme kuyruğu; P50 hedef altında. 200 ms üzeri tekil yok (max 192).

## 100 girdi / hücre tutarlılığı

- Down ×50 (50 satır): hata 0 (önceki turda 80 ms kilit nedeniyle 42 kayıp vardı — düzeltildi)
- Kaydet sonrası form miktar = DB miktar (5)

## Değişen dosyalar

- `app.py` — aciklama yaşam döngüsü; overlay iptal; tek satır yenile
- `fatura_satir_hucre_edit.py` — senkron tık/gezinme; FocusOut yarışı; yenile bayrağı
- `treeview_excel_cizgi.py` — editör açıkken çizgi yenileme yok
- `tests/test_fatura_aciklama_olu_entry.py`
- `_hiz_olcum_v2.py`, `_hiz_olcum_sonuc.json`

## Bilinçli olarak yapılmayanlar

- Bu turda **EXE rebuild / commit / push yok** (doğrulama bitmeden gün sonuna geçilmedi)
- Canlı `MuhasebeProgrami` verisine yazılmadı
- Deneme faturaları yalnız `CinMuhasebeHizTest` kopyasında

## Kalan / sınır

- Enter P95 ~136 ms (hedef 100): seyrek ağır geçiş; P50 çok düşük
- Kaydet/Onayla ~7–9 s (veri bütünlüğü; 100 ms hedefi yok)
- Gerçek firmada max fatura satırı ≈3; 50 satır sentetik stres ayrı satırda
