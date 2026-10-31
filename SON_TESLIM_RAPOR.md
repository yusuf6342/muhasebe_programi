# Son Teslim — Alınan Sipariş (uzlaşma + fatura alt toplam + satır yüksekliği)

## Tamamlanan işler
- Alınan Sipariş alt toplamları Satış Faturası ile aynı iki kolon yerleşiminde (`siparis_tema.siparis_alt_ozet` → `fatura_yerlesim._toplamlar_kur`).
- Uzlaşılan Tutar / Fiyatları Düzenle / Dağıtımı Geri Al (`uzlasilan_tutar_service` + `satis_siparisi_ui`).
- Ürün satır yüksekliği Teklif ile eşitlendi (stil + bbox **29 px**, `TABLO_SATIR_TABAN` ölçeği).
- `genel_toplam` / `genel_islem_*` şema + kaydet / yeniden aç; tam aktarımda satır toplamı = net ise `genel_islem` taşınmaz; kısmi aktarımda uzlaşılan birim fiyat korunur.
- Excel çizgi / hücre düzenleyici (`treeview_excel_cizgi`) sipariş ve teklifte ortak.
- Menü: Alınan Siparişler → yeni kart (`satis_siparisi_yeni_ac`).

## Test sonuçları (canlı EXE DB kopyası)
| Kontrol | Sonuç |
|---|---|
| Footer iki kolon + Net = Uzlaşılan | OK (372,65) |
| Uzlaşma dağıtım / geri al / tekrar | OK |
| Teklif vs Sipariş satır yüksekliği | OK (29 / 29) |
| F10 bind, sağ tık/çift tık altyapı, Tab/Enter, MouseWheel | OK |
| Kaydet → yeniden aç | OK (id=230) |
| Tam / kısmi fatura aktarım fiyat/toplam | OK |

## Tamamlanamayan / başarılı sayılmayan
- Kullanıcı girişli **dondurulmuş EXE oturumunda** uçtan uca fare tıklamalı kontrol: oturum kapalıydı; Computer Use odak çakışması nedeniyle EXE UI tıklamaları güvenilir değildi. Doğrulama aynı kaynak + canlı DB kopyası + Tk kartı üzerinden yapıldı.
- Giriş şifresi olmadan masaüstü EXE içinde menüden açılış/oturum doğrulaması yapılamadı (başarı sayılmadı).

## EXE
- Yol: `dist\CinMuhasebe\CinMuhasebe.exe`
- Derleme: 2026-10-31 ~18:04 (yerel)
- Masaüstü kısayol: `Cin Muhasebe.lnk` → aynı EXE (WorkingDirectory = `dist\CinMuhasebe`)

## Commit kapsamı (bu teslim)
Kaynak: `satis_siparisi_ui.py`, `siparis_tema.py`, `database/models/satis_siparisi.py`, `database/satis_siparisi_service.py`, `database/siparis_form_view.py`, `treeview_excel_cizgi.py`, `teklif_ui.py`, `ana_panel_ui.py`, `fatura_tema.py`, `fatura_yerlesim.py`, `tests/test_fatura_yerlesim.py`, bu rapor.

Bilinçli olarak **dışarıda** bırakılan (diğer çalışmalar / geçici): `app.py` (büyük karma fatura diff; sipariş açılışı HEAD’de zaten var), cari/sorulan ürün/barkod/takvim/menü arama değişiklikleri, `tools/_shots_*`, `tools/_tmp_*`, `dist/`, DB/yedek/şifre.
