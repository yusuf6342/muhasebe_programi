"""Satış faturası Treeview — satır içi hücre düzenleme (miktar, birim, fiyat, PB, kur, iskonto, KDV, açıklama)."""

from __future__ import annotations

import tkinter as tk
from decimal import Decimal, InvalidOperation
from tkinter import messagebox, ttk
from typing import Callable

from database.models.doviz import PARA_BIRIMLERI
from database.models.stok import KDV_ORANLARI
from database.stok_service import BirimDonusumHatasi
from fatura_tema import HUCRE_EDITOR_TABAN_PX, scale_height
from satir_klavye import odak_tabloda_mi, satir_stok_karti_ac, urun_kolonlari
from fatura_satir_birim_service import (
    birim_degistir,
    birim_satis_fiyati,
    miktar_metnini_coz,
    stok_aktif_birimleri,
    temel_miktar,
)

# Düzenlenebilir kolonlar (tıklama / tooltip)
DUZENLENEBILIR_KOLONLAR = (
    "miktar",
    "birim",
    "fiyat",
    "para_birimi",
    "kur",
    "iskonto",
    "iskonto_tutar",
    "kdv",
    "aciklama",
)

# Enter / Tab gezinme sırası (stabil kimlik; gizli/yetkisiz atlanır)
EDITABLE_COLUMN_ORDER = (
    "miktar",
    "birim",
    "fiyat",
    "para_birimi",
    "kur",
    "iskonto",
    "iskonto_tutar",
    "kdv",
    "aciklama",
)


def _d(metin, varsayilan: Decimal = Decimal("0")) -> Decimal:
    ham = str(metin or "").strip().replace("✦", "").strip()
    if not ham:
        return varsayilan
    if "," in ham and "." in ham:
        if ham.rfind(",") > ham.rfind("."):
            ham = ham.replace(".", "").replace(",", ".")
        else:
            ham = ham.replace(",", "")
    elif "," in ham:
        ham = ham.replace(".", "").replace(",", ".")
    try:
        return Decimal(ham)
    except (InvalidOperation, ValueError):
        return varsayilan


def _kolon_gorunur_mu(dialog, kolon: str) -> bool:
    tablo = getattr(dialog, "satir_tablosu", None)
    if tablo is None:
        return False
    try:
        gorunen = list(tablo["displaycolumns"] or ())
    except tk.TclError:
        return True
    if not gorunen or gorunen == ["#all"] or gorunen == ("#all",):
        return True
    return kolon in gorunen


def _bagli_kaynak_belge(satir: dict) -> str | None:
    if satir.get("irsaliye_satiri_id"):
        return "irsaliyeden"
    if satir.get("siparis_satiri_id"):
        return "siparişten"
    return None


def kolon_duzenlenebilir_mi(dialog, idx: int, kolon: str) -> bool:
    """Görünür + yetki + satır koşulu — Enter gezinmede atlama kararı."""
    if getattr(dialog, "_fatura_kilitli", False):
        return False
    if kolon not in EDITABLE_COLUMN_ORDER:
        return False
    if kolon in getattr(dialog, "DUZENLENEMEZ_KOLONLAR", ()):
        return False
    if not _kolon_gorunur_mu(dialog, kolon):
        return False
    if not (0 <= idx < len(getattr(dialog, "satirlar", []) or [])):
        return False
    satir = dialog.satirlar[idx]
    if kolon == "birim":
        # Kartta tek birim olsa da açılır: kartta tanımsız birim seçilince katsayı sorulur
        return not _bagli_kaynak_belge(satir)
    if kolon == "fiyat":
        try:
            from fatura_manuel_fiyat_ui import fiyat_degistirme_yetkisi

            return bool(fiyat_degistirme_yetkisi())
        except Exception:
            return True
    if kolon == "kur":
        pb = (satir.get("satir_para_birimi") or satir.get("para_birimi") or "TRY").upper()
        return pb not in ("TRY", "TL", "")
    return True


def find_next_editable_cell(
    dialog, row_id: int, column_id: str | None, direction: int = 1
) -> tuple[int, str] | None:
    """Sonraki/önceki kullanılabilir hücre (satır + kolon). Yoksa None."""
    n = len(getattr(dialog, "satirlar", []) or [])
    if n <= 0:
        return None
    order = list(EDITABLE_COLUMN_ORDER)
    if not order:
        return None
    # Başlangıç indeksi
    try:
        ci = order.index(column_id) if column_id in order else -1
    except ValueError:
        ci = -1
    r, c = int(row_id), ci
    adim = 1 if direction >= 0 else -1
    # En fazla tüm hücreler kadar dene
    for _ in range(n * len(order) + 2):
        c += adim
        if c >= len(order):
            r += 1
            c = 0
            if r >= n:
                return None
        elif c < 0:
            r -= 1
            c = len(order) - 1
            if r < 0:
                return None
        kolon = order[c]
        if kolon_duzenlenebilir_mi(dialog, r, kolon):
            return r, kolon
    return None


def ilk_duzenlenebilir_kolon(dialog, idx: int) -> str | None:
    for kolon in EDITABLE_COLUMN_ORDER:
        if kolon_duzenlenebilir_mi(dialog, idx, kolon):
            return kolon
    return None


def _urun_arama_odakla(dialog) -> None:
    """Satırın son alanı sonrası: tablo sonundaki boş ürün giriş satırı."""
    from satir_ici_urun_giris import giris_bileseni

    giris = giris_bileseni(dialog)
    if giris is not None:
        giris.odakla()
        return
    for ad in ("barkod", "urun_kodu", "urun_adi"):
        w = (getattr(dialog, "satir_girdileri", None) or {}).get(ad)
        if w is not None:
            try:
                w.focus_set()
                if hasattr(w, "selection_range"):
                    w.selection_range(0, "end")
                return
            except tk.TclError:
                continue
    be = getattr(dialog, "barkod_okut_entry", None)
    if be is not None:
        try:
            be.focus_set()
        except tk.TclError:
            pass


def focus_editable_cell(dialog, row_id: int, column_id: str, *, deneme: int = 0) -> None:
    """Satırı seç/görünür yap, bbox hazırsa editörü aç."""
    if getattr(dialog, "_fatura_kilitli", False):
        return
    if not kolon_duzenlenebilir_mi(dialog, row_id, column_id):
        hedef = find_next_editable_cell(dialog, row_id, column_id, direction=1)
        if hedef:
            focus_editable_cell(dialog, hedef[0], hedef[1], deneme=0)
        return
    tablo = getattr(dialog, "satir_tablosu", None)
    if tablo is None:
        return
    iid = str(row_id)
    try:
        tablo.selection_set(iid)
        tablo.focus(iid)
        tablo.see(iid)
        tablo.focus_set()
    except tk.TclError:
        return
    box = _hucre_bbox(tablo, iid, column_id)
    if not box:
        _kolonu_gorunur_kaydir(tablo, column_id)
        box = _hucre_bbox(tablo, iid, column_id)
    if not box:
        if deneme < 4:
            try:
                dialog.update_idletasks()
            except tk.TclError:
                pass
            dialog.after(
                25,
                lambda: focus_editable_cell(dialog, row_id, column_id, deneme=deneme + 1),
            )
        return
    hucre_duzenle(dialog, idx=row_id, kolon=column_id)


def satir_ilk_alana_odakla(dialog, idx: int) -> None:
    """Ürün eklendikten / miktar arttıktan sonra ilk düzenlenebilir hücre."""
    kolon = ilk_duzenlenebilir_kolon(dialog, idx)
    if not kolon:
        return

    def _ac():
        focus_editable_cell(dialog, idx, kolon)

    try:
        dialog.after_idle(_ac)
    except tk.TclError:
        dialog.after(30, _ac)


def _sonraki_kolon(kolon: str, geri: bool = False) -> str | None:
    """Geriye uyum — görünürlük kontrolsüz; tercihen find_next_editable_cell kullan."""
    try:
        i = EDITABLE_COLUMN_ORDER.index(kolon)
    except ValueError:
        try:
            i = DUZENLENEBILIR_KOLONLAR.index(kolon)
            order = DUZENLENEBILIR_KOLONLAR
        except ValueError:
            return None
        else:
            j = i - 1 if geri else i + 1
            if 0 <= j < len(order):
                return order[j]
            return None
    j = i - 1 if geri else i + 1
    if 0 <= j < len(EDITABLE_COLUMN_ORDER):
        return EDITABLE_COLUMN_ORDER[j]
    return None


def _kolon_adi(tablo: ttk.Treeview, event) -> str | None:
    try:
        if tablo.identify_region(event.x, event.y) != "cell":
            return None
        kolon_id = tablo.identify_column(event.x)
        kolon_sira = int(kolon_id.replace("#", "")) - 1
        gorunen = tablo["displaycolumns"]
        if not gorunen or gorunen == ("#all",):
            gorunen = tablo["columns"]
        return gorunen[kolon_sira]
    except (tk.TclError, ValueError, IndexError, TypeError):
        return None


def _hucre_bbox(tablo: ttk.Treeview, iid: str, kolon: str):
    try:
        return tablo.bbox(iid, kolon)
    except tk.TclError:
        return None


def _kolonu_gorunur_kaydir(tablo: ttk.Treeview, kolon: str) -> None:
    """Tablo yatayda taşıyorsa kolonu görünür alana kaydırır (ekran dışı hücrenin bbox'ı boştur)."""
    try:
        gorunen = list(tablo["displaycolumns"] or ())
        if not gorunen or gorunen[0] == "#all":
            gorunen = list(tablo["columns"])
        if kolon not in gorunen:
            return
        genislikler = [int(tablo.column(k, "width")) for k in gorunen]
        if "tree" in str(tablo.cget("show")):
            genislikler.insert(0, int(tablo.column("#0", "width")))
            gorunen.insert(0, "#0")
        toplam = sum(genislikler)
        if toplam <= 0:
            return
        i = gorunen.index(kolon)
        sol = sum(genislikler[:i])
        sag = sol + genislikler[i]
        bas, son = tablo.xview()
        if sol / toplam < bas:
            tablo.xview_moveto(sol / toplam)
        elif sag / toplam > son:
            tablo.xview_moveto(max(0.0, sag / toplam - (son - bas)))
        tablo.update_idletasks()
    except (tk.TclError, ValueError, TypeError):
        pass


def _editor_kapat(dialog) -> None:
    ed = getattr(dialog, "_satir_hucre_editor", None)
    if ed is None:
        return
    try:
        ed.destroy()
    except tk.TclError:
        pass
    dialog._satir_hucre_editor = None


def acik_editor(dialog):
    """Açık hücre editörü; yok edilmiş editör kaydı temizlenir."""
    ed = getattr(dialog, "_satir_hucre_editor", None)
    if ed is None:
        return None
    try:
        if ed.winfo_exists():
            return ed
    except tk.TclError:
        pass
    dialog._satir_hucre_editor = None
    return None


def editoru_birak(dialog) -> bool:
    """Başka hücreye / satıra geçmeden önce açık editörün değerini yazıp kapatır; geçersizse False."""
    if acik_editor(dialog) is None:
        return True
    return acik_editoru_uygula(dialog)


def _odak_cikinca_uygula(dialog, editor, *parcalar) -> None:
    """Odak editör dışına (aynı penceredeki başka bir alana) geçince değer yazılır ve editör kapanır."""

    def _cikti(_e=None):
        def _kontrol():
            if getattr(dialog, "_satir_hucre_editor", None) is not editor:
                return
            # Mesaj kutusu / başka uygulama odağı almışsa pencerenin son odağı hâlâ editördür
            try:
                odak = str(dialog.tk.call("focus", "-lastfor", str(dialog)))
            except tk.TclError:
                return
            if not odak or odak.startswith(str(editor)):
                return
            editoru_birak(dialog)

        try:
            dialog.after(120, _kontrol)
        except tk.TclError:
            pass

    for w in parcalar or (editor,):
        w.bind("<FocusOut>", _cikti, add="+")


def acik_editoru_uygula(dialog) -> bool:
    """Kaydet öncesi açık hücre editöründeki değeri satıra yazar; geçersizse False."""
    ed = getattr(dialog, "_satir_hucre_editor", None)
    if ed is None:
        return True
    fn = getattr(ed, "_uygula_fn", None)
    if fn is None:
        _editor_kapat(dialog)
        return True
    dialog._satir_gezinme_kilit = True
    try:
        fn()
    finally:
        dialog._satir_gezinme_kilit = False
    return getattr(dialog, "_satir_hucre_editor", None) is None


def uzlasma_etkisini_kaldir(dialog, *, yalniz_referansli: bool = False) -> bool:
    """Satır miktar/fiyatı değişince uzlaşılan Net'i kaldırır; toplam satırlardan yeniden hesaplanır.

    Eski uzlaşma tutarı yeni satır toplamına sessizce uygulanmaz. Fiyatlara dağıtılmış
    (``referans_birim_fiyat`` taşıyan) satırlar referans fiyatlarına döner; indirimli fiyat
    yeni Genel Toplam'ın referansı olmaz. ``yalniz_referansli``: yalnız referanslı faturada çalışır.
    """
    if getattr(dialog, "_fatura_yukleniyor", False):
        return False
    satirlar = getattr(dialog, "satirlar", None) or []
    referansli = any(s.get("referans_birim_fiyat") not in (None, "") for s in satirlar)
    if yalniz_referansli and not referansli:
        return False
    if (
        not referansli
        and getattr(dialog, "_uzlasilan_tutar", None) is None
        and not getattr(dialog, "_uzlasilan_fiyat_snapshot", None)
    ):
        return False
    fiyat_dondu = False
    for s in satirlar:
        ref = s.pop("referans_birim_fiyat", None)
        if ref in (None, ""):
            continue
        ref_d = _d(ref)
        if _d(s.get("birim_satis_fiyati")) != ref_d:
            fiyat_dondu = True
        s["birim_satis_fiyati"] = str(ref_d)
        if "birim_fiyat" in s:
            s["birim_fiyat"] = str(ref_d)
    dialog._uzlasilan_tutar = None
    dialog._uzlasilan_fiyat_snapshot = None
    dialog._uzlasilan_snapshot_brut = None
    yaz = getattr(dialog, "_uzlasilan_tutar_yaz", None)
    if callable(yaz):
        dialog._uzlasilan_ui_kilit = True
        try:
            yaz(None)
        finally:
            dialog._uzlasilan_ui_kilit = False
    try:
        from fatura_mesaj_paneli import _panel_ac_kapa, _yerel_teknik

        _yerel_teknik(
            dialog,
            "Satır miktarı/fiyatı değişti: Uzlaşılan Tutar kaldırıldı, Net Toplam satırlardan "
            "yeniden hesaplandı. Gerekirse uzlaşmayı yeniden girin."
            + (" Dağıtılmış satır fiyatları orijinal (Genel Toplam) fiyatlarına döndü." if fiyat_dondu else ""),
        )
        _panel_ac_kapa(dialog, True)
    except Exception:
        pass
    return True


def _yenile_koru(dialog, tablo, iid: str):
    # GENEL Entry odak bayrağı takılı kalırsa alt toplam güncellenmez
    try:
        dialog._genel_toplam_duzenleniyor = False
    except Exception:
        pass
    kaydir = tablo.yview()
    dialog._satir_listesini_yenile()
    dialog._toplamlari_guncelle()
    try:
        tablo.selection_set(iid)
        tablo.focus(iid)
        tablo.see(iid)
        tablo.yview_moveto(kaydir[0])
    except tk.TclError:
        pass


def _stok_kontrol(dialog, idx: int, yeni_temel: Decimal, kod: str) -> bool:
    """Miktar/birim düzenlemede stok engeli yok — kontrol yalnızca onayda."""
    _ = (dialog, idx, yeni_temel, kod)
    return True


def hucre_duzenle(
    dialog,
    *,
    idx: int,
    kolon: str,
    event=None,
    on_done: Callable[[], None] | None = None,
) -> None:
    """Kolona göre uygun editörü aç."""
    if kolon in getattr(dialog, "DUZENLENEMEZ_KOLONLAR", ()):
        return
    if kolon == "miktar":
        miktar_hucre_duzenle(dialog, idx=idx, event=event, on_done=on_done)
    elif kolon == "birim":
        birim_hucre_duzenle(dialog, idx=idx, event=event, on_done=on_done)
    elif kolon == "fiyat":
        fiyat_hucre_duzenle(dialog, idx=idx, event=event, on_done=on_done)
    elif kolon == "para_birimi":
        pb_hucre_duzenle(dialog, idx=idx, event=event, on_done=on_done)
    elif kolon == "kur":
        kur_hucre_duzenle(dialog, idx=idx, event=event, on_done=on_done)
    elif kolon == "iskonto":
        iskonto_yuzde_hucre(dialog, idx=idx, event=event, on_done=on_done)
    elif kolon == "iskonto_tutar":
        iskonto_tutar_hucre(dialog, idx=idx, event=event, on_done=on_done)
    elif kolon == "kdv":
        kdv_hucre_duzenle(dialog, idx=idx, event=event, on_done=on_done)
    elif kolon == "aciklama":
        aciklama_hucre_duzenle(dialog, idx=idx, event=event, on_done=on_done)


def _satir_ici_var(dialog) -> bool:
    from satir_ici_urun_giris import giris_bileseni

    return giris_bileseni(dialog) is not None


def _satira_gec(dialog, idx: int, kolon: str, satir_yon: int) -> None:
    """↑/↓: aynı kolonda önceki/sonraki satır; son satırdan aşağı ürün giriş satırı."""
    hedef = idx + (1 if satir_yon > 0 else -1)
    n = len(getattr(dialog, "satirlar", []) or [])
    tablo = getattr(dialog, "satir_tablosu", None)
    if hedef >= n:
        if _satir_ici_var(dialog):
            _urun_arama_odakla(dialog)
            return
        hedef = n - 1
    hedef = max(0, hedef)
    if hedef != idx and kolon_duzenlenebilir_mi(dialog, hedef, kolon):
        focus_editable_cell(dialog, hedef, kolon)
        return
    if tablo is None or n <= 0:
        return
    try:
        tablo.selection_set(str(hedef))
        tablo.focus(str(hedef))
        tablo.see(str(hedef))
        tablo.focus_set()
    except tk.TclError:
        pass


def _tab_ilerle(dialog, idx: int, kolon: str, geri: bool = False, satir_yon: int = 0):
    """Enter/Tab sonrası tek adım — çift atlamayı önler."""
    if getattr(dialog, "_satir_gezinme_kilit", False):
        return
    dialog._satir_gezinme_kilit = True

    def _ac():
        try:
            if satir_yon:
                _satira_gec(dialog, idx, kolon, satir_yon)
                return
            hedef = find_next_editable_cell(
                dialog, idx, kolon, direction=-1 if geri else 1
            )
            if hedef is None or (not geri and hedef[0] != idx and _satir_ici_var(dialog)):
                if not geri:
                    _urun_arama_odakla(dialog)
                return
            r, c = hedef
            dialog._hucre_giris_geri = geri
            try:
                focus_editable_cell(dialog, r, c)
            finally:
                dialog._hucre_giris_geri = False
        finally:
            try:
                dialog.after(80, lambda: setattr(dialog, "_satir_gezinme_kilit", False))
            except tk.TclError:
                dialog._satir_gezinme_kilit = False

    try:
        dialog.after_idle(_ac)
    except tk.TclError:
        dialog.after(30, _ac)


def _ok_ile_gec(editor, yon: int) -> bool:
    from satir_klavye import ok_ile_gec

    return ok_ile_gec(editor, yon)


def _ok_gezinme_bagla(editor, uygula) -> None:
    """``uygula(tab=True, geri=...)`` değeri yazar ve sonraki/önceki hücreye geçer.

    ↑/↓ değeri yazar ve aynı kolonda önceki/sonraki satıra geçer; açılır listede Alt+↓ listeyi açar.
    """
    from satir_klavye import combobox_listesini_ac

    def _sag(_e=None):
        return uygula(tab=True) if _ok_ile_gec(editor, 1) else None

    def _sol(_e=None):
        return uygula(tab=True, geri=True) if _ok_ile_gec(editor, -1) else None

    editor.bind("<Right>", _sag)
    editor.bind("<Left>", _sol)
    editor.bind("<Up>", lambda _e: uygula(tab=True, satir_yon=-1))
    editor.bind("<Down>", lambda _e: uygula(tab=True, satir_yon=1))
    if isinstance(editor, ttk.Combobox):
        editor.bind("<Alt-Down>", lambda _e: (combobox_listesini_ac(editor), "break")[1])


def _listeyi_ac(editor, event) -> None:
    """Fareyle açılınca liste hemen açılır; Enter/ok ile gelinince kapalı kalır (oklar gezinsin)."""
    if event is None:
        return
    from satir_klavye import combobox_listesini_ac

    combobox_listesini_ac(editor)


def _overlay_entry(dialog, tablo, iid, kolon, metin, *, justify="right"):
    _editor_kapat(dialog)
    box = _hucre_bbox(tablo, iid, kolon)
    if not box:
        return None, None
    bx, by, bw, bh = box
    var = tk.StringVar(value=metin)
    editor = ttk.Entry(tablo, textvariable=var, justify=justify, font=("Segoe UI", 10))
    editor.place(x=bx, y=by, width=max(bw, 50), height=max(bh, scale_height(HUCRE_EDITOR_TABAN_PX)))
    editor.lift()
    editor.focus_set()
    editor.selection_range(0, "end")
    dialog._satir_hucre_editor = editor
    _odak_cikinca_uygula(dialog, editor)
    return editor, var


def miktar_hucre_duzenle(dialog, *, idx: int, event=None, on_done=None) -> None:
    if getattr(dialog, "_fatura_kilitli", False):
        messagebox.showwarning("Miktar", "Onaylı faturada miktar değiştirilemez.", parent=dialog)
        return
    if not (0 <= idx < len(dialog.satirlar)):
        return
    tablo = dialog.satir_tablosu
    iid = str(idx)
    tablo.selection_set(iid)
    mevcut = dialog.satirlar[idx].get("miktar") or "1"
    try:
        from app import miktar_goster as _mg

        baslangic = _mg(mevcut)
    except Exception:
        baslangic = str(mevcut).replace(".", ",")
    editor, var = _overlay_entry(
        dialog, tablo, iid, "miktar", baslangic, justify="right"
    )
    if editor is None:
        return

    def _iptal(_e=None):
        _editor_kapat(dialog)
        return "break"

    def _kaydet(_e=None, tab=False, geri=False, satir_yon=0):
        try:
            yeni = miktar_metnini_coz(var.get())
        except ValueError as hata:
            messagebox.showerror("Miktar", str(hata), parent=dialog)
            return "break"
        satir = dialog.satirlar[idx]
        kod = (satir.get("urun_kodu") or "").strip()
        birim = (satir.get("birim") or "Adet").strip()
        try:
            yeni_temel = temel_miktar(yeni, birim, kod)
        except BirimDonusumHatasi as hata:
            messagebox.showwarning("Birim dönüşümü", str(hata), parent=dialog)
            return "break"
        if not _stok_kontrol(dialog, idx, yeni_temel, kod):
            return "break"
        if _d(satir.get("miktar")) != yeni:
            uzlasma_etkisini_kaldir(dialog)
        satir["miktar"] = str(yeni)
        satir["temel_miktar"] = str(yeni_temel)
        _editor_kapat(dialog)
        _yenile_koru(dialog, tablo, iid)
        if tab:
            _tab_ilerle(dialog, idx, "miktar", geri=geri, satir_yon=satir_yon)
        if on_done:
            on_done()
        return "break"

    editor.bind("<Return>", lambda e: _kaydet(tab=True))
    editor._uygula_fn = lambda: _kaydet()
    editor.bind("<KP_Enter>", lambda e: _kaydet(tab=True))
    editor.bind("<Shift-Return>", lambda e: _kaydet(tab=True, geri=True))
    editor.bind("<Escape>", _iptal)
    editor.bind("<Tab>", lambda e: _kaydet(tab=True))
    editor.bind("<Shift-Tab>", lambda e: _kaydet(tab=True, geri=True))
    _ok_gezinme_bagla(editor, _kaydet)


def birim_hucre_duzenle(dialog, *, idx: int, event=None, on_done=None) -> None:
    if getattr(dialog, "_fatura_kilitli", False):
        messagebox.showwarning("Birim", "Onaylı faturada birim değiştirilemez.", parent=dialog)
        return
    if not (0 <= idx < len(dialog.satirlar)):
        return
    tablo = dialog.satir_tablosu
    iid = str(idx)
    satir = dialog.satirlar[idx]
    belge = _bagli_kaynak_belge(satir)
    if belge:
        messagebox.showwarning(
            "Birim",
            f"Bu satır {belge} aktarıldı; birimi kaynak belgedeki birimle aynı kalmalıdır.",
            parent=dialog,
        )
        return
    from birim_secim_ui import evrak_birim_secenekleri, kart_birimini_hazirla

    kod = (satir.get("urun_kodu") or "").strip()
    from fatura_satir_birim_service import _stok_yukle

    # Faturada yalnız stok kartının birimleri; kartsız satırda genel birim listesi
    if kod and _stok_yukle(kod) is not None:
        birimler = stok_aktif_birimleri(kod)
    else:
        birimler = evrak_birim_secenekleri(kod)
    _editor_kapat(dialog)
    box = _hucre_bbox(tablo, iid, "birim")
    mevcut = (satir.get("birim") or birimler[0]).strip()
    var = tk.StringVar(value=mevcut)
    if not box:
        return
    bx, by, bw, bh = box
    editor = ttk.Combobox(
        tablo,
        textvariable=var,
        values=tuple(birimler),
        state="readonly",
        font=("Segoe UI", 10),
        justify="center",
    )
    editor.place(x=bx, y=by, width=max(bw, 70), height=max(bh, scale_height(HUCRE_EDITOR_TABAN_PX)))
    editor.focus_set()
    dialog._satir_hucre_editor = editor
    _odak_cikinca_uygula(dialog, editor)

    def _iptal(_e=None):
        _editor_kapat(dialog)
        return "break"

    def _uygula(_e=None, tab=False, geri=False, satir_yon=0):
        yeni_birim = (var.get() or "").strip()
        if not yeni_birim or yeni_birim.casefold() == mevcut.casefold():
            _editor_kapat(dialog)
            if tab:
                _tab_ilerle(dialog, idx, "birim", geri=geri, satir_yon=satir_yon)
            if on_done:
                on_done()
            return "break"
        if not kart_birimini_hazirla(dialog, kod, yeni_birim):
            _editor_kapat(dialog)
            return "break"
        manuel = bool(satir.get("manuel_fiyat"))
        mod = "yeniden"
        if manuel:
            cevap = messagebox.askyesnocancel(
                "Manuel fiyat",
                "Manuel birim fiyat var.\n\n"
                "Evet: Yeni birime göre yeniden hesapla\n"
                "Hayır: Manuel fiyatı koru\n"
                "İptal: Vazgeç",
                parent=dialog,
            )
            if cevap is None:
                _editor_kapat(dialog)
                return "break"
            mod = "yeniden" if cevap else "koru"
        musteri = None
        if hasattr(dialog, "_secili_musteri"):
            try:
                musteri = dialog._secili_musteri()
            except Exception:
                pass
        kaynak = satir
        if satir.get("referans_birim_fiyat") not in (None, ""):
            # Dağıtılmış satır: dönüşüm referans (Genel Toplam) fiyatından yapılır
            kaynak = dict(satir)
            kaynak["birim_satis_fiyati"] = str(_d(satir["referans_birim_fiyat"]))
            kaynak.pop("referans_birim_fiyat", None)
        try:
            guncel = birim_degistir(kaynak, yeni_birim, musteri=musteri, manuel_fiyat_modu=mod)
        except BirimDonusumHatasi as hata:
            messagebox.showwarning("Birim dönüşümü", str(hata), parent=dialog)
            _editor_kapat(dialog)
            return "break"
        if guncel is None:
            _editor_kapat(dialog)
            return "break"
        from fatura_satir_birim_service import satir_temel_talep

        if not _stok_kontrol(dialog, idx, satir_temel_talep(guncel), kod):
            _editor_kapat(dialog)
            return "break"
        uzlasma_etkisini_kaldir(dialog)
        guncel.pop("referans_birim_fiyat", None)
        dialog.satirlar[idx] = guncel
        _editor_kapat(dialog)
        _yenile_koru(dialog, tablo, iid)
        if tab:
            _tab_ilerle(dialog, idx, "birim", geri=geri, satir_yon=satir_yon)
        if on_done:
            on_done()
        return "break"

    editor.bind("<<ComboboxSelected>>", lambda e: _uygula(tab=True))
    editor.bind("<Return>", lambda e: _uygula(tab=True))
    editor._uygula_fn = lambda: _uygula()
    editor.bind("<KP_Enter>", lambda e: _uygula(tab=True))
    editor.bind("<Shift-Return>", lambda e: _uygula(tab=True, geri=True))
    editor.bind("<Escape>", _iptal)
    editor.bind("<Tab>", lambda e: _uygula(tab=True))
    editor.bind("<Shift-Tab>", lambda e: _uygula(tab=True, geri=True))
    _ok_gezinme_bagla(editor, _uygula)
    _listeyi_ac(editor, event)


def _satir_pb(satir: dict) -> str:
    pb = (satir.get("satir_para_birimi") or satir.get("para_birimi") or "TRY").upper()
    return "TRY" if pb == "TL" else pb


def _satir_kuru(satir: dict) -> Decimal:
    if _satir_pb(satir) == "TRY":
        return Decimal("1")
    kur = _d(satir.get("kur"), Decimal("0"))
    return kur if kur > 0 else Decimal("0")


def _tl_fiyat(doviz_fiyat, satir: dict) -> Decimal:
    """Satır hesap esası TL'dir: döviz birim fiyat × satır kuru."""
    return (_d(doviz_fiyat) * _satir_kuru(satir)).quantize(Decimal("0.0001"))


def _baslik_doviz_pb(dialog) -> str | None:
    """Fatura başlığı dövizliyse para birimini döner (satır PB/kuru başlıktan yönetilir)."""
    var = getattr(dialog, "_doviz_para_birimi", None)
    if var is None:
        return None
    try:
        pb = (var.get() or "TRY").upper()
    except Exception:
        return None
    return None if pb in ("TRY", "TL") else pb


def fiyat_hucre_duzenle(dialog, *, idx: int, event=None, on_done=None) -> None:
    if getattr(dialog, "_fatura_kilitli", False):
        messagebox.showwarning("Fiyat", "Onaylı faturada fiyat değiştirilemez.", parent=dialog)
        return
    if not (0 <= idx < len(dialog.satirlar)):
        return
    # Yetki
    try:
        from fatura_manuel_fiyat_ui import fiyat_degistirme_yetkisi

        if not fiyat_degistirme_yetkisi():
            messagebox.showwarning("Yetki", "Birim fiyatı değiştirme yetkiniz yok.", parent=dialog)
            return
    except Exception:
        pass
    tablo = dialog.satir_tablosu
    iid = str(idx)
    satir = dialog.satirlar[idx]
    satir_pb = _satir_pb(satir)
    doviz_giris = satir_pb != "TRY" and _satir_kuru(satir) > 0
    if doviz_giris:
        mevcut_deger = (
            _d(satir.get("birim_satis_fiyati")) / _satir_kuru(satir)
        ).quantize(Decimal("0.0001"))
    else:
        mevcut_deger = satir.get("birim_satis_fiyati")
    mevcut = str(mevcut_deger or "0").replace(".", ",")
    editor, var = _overlay_entry(dialog, tablo, iid, "fiyat", mevcut, justify="right")
    if editor is None:
        return

    def _iptal(_e=None):
        _editor_kapat(dialog)
        return "break"

    def _kaydet(_e=None, tab=False, geri=False, satir_yon=0):
        yeni = _d(var.get())
        if yeni < 0:
            messagebox.showerror("Fiyat", "Fiyat negatif olamaz.", parent=dialog)
            return "break"
        try:
            from fatura_manuel_fiyat_ui import maliyet_alti_kontrol

            if getattr(dialog, "MALIYET_ALTI_KONTROLU", True) and not maliyet_alti_kontrol(
                _tl_fiyat(yeni, satir) if doviz_giris else yeni,
                satir,
                yontem=dialog.yontem.get() if hasattr(dialog, "yontem") else None,
                parent=dialog,
                hedef_marj=dialog._fatura_hedef_marj() if hasattr(dialog, "_fatura_hedef_marj") else None,
            ):
                return "break"
        except Exception:
            pass
        if yeni != _d(mevcut_deger):
            uzlasma_etkisini_kaldir(dialog)
        if doviz_giris:
            satir["birim_fiyat_doviz"] = str(yeni)
            satir["birim_satis_fiyati"] = str(_tl_fiyat(yeni, satir))
        else:
            satir["birim_satis_fiyati"] = str(yeni)
        satir["manuel_fiyat"] = True
        _editor_kapat(dialog)
        _yenile_koru(dialog, tablo, iid)
        if tab:
            _tab_ilerle(dialog, idx, "fiyat", geri=geri, satir_yon=satir_yon)
        if on_done:
            on_done()
        return "break"

    editor.bind("<Return>", lambda e: _kaydet(tab=True))
    editor._uygula_fn = lambda: _kaydet()
    editor.bind("<KP_Enter>", lambda e: _kaydet(tab=True))
    editor.bind("<Shift-Return>", lambda e: _kaydet(tab=True, geri=True))
    editor.bind("<Escape>", _iptal)
    editor.bind("<Tab>", lambda e: _kaydet(tab=True))
    editor.bind("<Shift-Tab>", lambda e: _kaydet(tab=True, geri=True))
    _ok_gezinme_bagla(editor, _kaydet)


def pb_hucre_duzenle(dialog, *, idx: int, event=None, on_done=None) -> None:
    if getattr(dialog, "_fatura_kilitli", False):
        return
    if not (0 <= idx < len(dialog.satirlar)):
        return
    baslik_pb = _baslik_doviz_pb(dialog)
    if baslik_pb:
        messagebox.showinfo(
            "Para Birimi",
            f"Bu fatura {baslik_pb} olarak düzenleniyor. Satır para birimi ve kuru "
            "fatura başlığındaki döviz panelinden yönetilir.",
            parent=dialog,
        )
        return
    tablo = dialog.satir_tablosu
    iid = str(idx)
    satir = dialog.satirlar[idx]
    mevcut = _satir_pb(satir)
    _editor_kapat(dialog)
    box = _hucre_bbox(tablo, iid, "para_birimi")
    if not box:
        return
    bx, by, bw, bh = box
    var = tk.StringVar(value=mevcut)
    editor = ttk.Combobox(
        tablo,
        textvariable=var,
        values=PARA_BIRIMLERI,
        state="readonly",
        justify="center",
        font=("Segoe UI", 10),
    )
    editor.place(x=bx, y=by, width=max(bw, 60), height=max(bh, scale_height(HUCRE_EDITOR_TABAN_PX)))
    editor.focus_set()
    dialog._satir_hucre_editor = editor
    _odak_cikinca_uygula(dialog, editor)

    def _iptal(_e=None):
        _editor_kapat(dialog)
        return "break"

    def _uygula(_e=None, tab=False, geri=False, satir_yon=0):
        yeni = (var.get() or "TRY").upper()
        if yeni == "TL":
            yeni = "TRY"
        eski = mevcut
        if yeni == eski:
            _editor_kapat(dialog)
            if tab:
                _tab_ilerle(dialog, idx, "para_birimi", geri=geri, satir_yon=satir_yon)
            if on_done:
                on_done()
            return "break"
        # Dağıtım varsa önce referans fiyata dön; döviz fiyatı onun üzerinden türetilir
        uzlasma_etkisini_kaldir(dialog)
        # TL birim fiyat (hesap esası) korunur; döviz fiyatı yeni kurdan türetilir
        tl_fiyat = _d(satir.get("birim_satis_fiyati"))
        if yeni == "TRY":
            satir["kur"] = "1"
            satir["birim_fiyat_doviz"] = 0
        else:
            kur = _satir_kur_varsayilan(dialog, yeni)
            satir["kur"] = str(kur)
            satir["birim_fiyat_doviz"] = (
                str((tl_fiyat / kur).quantize(Decimal("0.0001"))) if kur > 0 else 0
            )
        satir["satir_para_birimi"] = yeni
        satir["para_birimi"] = yeni
        _editor_kapat(dialog)
        _yenile_koru(dialog, tablo, iid)
        if tab:
            _tab_ilerle(dialog, idx, "para_birimi", geri=geri, satir_yon=satir_yon)
        if on_done:
            on_done()
        return "break"

    editor.bind("<<ComboboxSelected>>", lambda e: _uygula(tab=True))
    editor.bind("<Return>", lambda e: _uygula(tab=True))
    editor._uygula_fn = lambda: _uygula()
    editor.bind("<KP_Enter>", lambda e: _uygula(tab=True))
    editor.bind("<Shift-Return>", lambda e: _uygula(tab=True, geri=True))
    editor.bind("<Escape>", _iptal)
    editor.bind("<Tab>", lambda e: _uygula(tab=True))
    editor.bind("<Shift-Tab>", lambda e: _uygula(tab=True, geri=True))
    _ok_gezinme_bagla(editor, _uygula)
    _listeyi_ac(editor, event)


def _satir_kur_varsayilan(dialog, pb: str) -> Decimal:
    pb = (pb or "TRY").upper()
    if pb in ("TRY", "TL"):
        return Decimal("1")
    try:
        from database.doviz_service import DovizService
        from datetime import date

        tarih = date.today()
        if hasattr(dialog, "girdiler") and "siparis_tarihi" in dialog.girdiler:
            from datetime import datetime

            try:
                tarih = datetime.strptime(
                    dialog.girdiler["siparis_tarihi"].get().strip(), "%d.%m.%Y"
                ).date()
            except Exception:
                pass
        kur_turu = "forex_selling"
        if hasattr(dialog, "_doviz_kur_turu"):
            kur_turu = dialog._doviz_kur_turu.get() or kur_turu
        return Decimal(str(DovizService.kur_degeri(tarih, pb, kur_turu) or 1))
    except Exception:
        try:
            if hasattr(dialog, "_doviz_kur"):
                return Decimal(str(dialog._doviz_kur.get() or "1").replace(",", "."))
        except Exception:
            pass
    return Decimal("1")


def _kur_duzenlenebilir(dialog, row) -> bool:
    """TL satırında kur 1'dir; hücre tıklanınca hiçbir şey açılmaz."""
    try:
        return kolon_duzenlenebilir_mi(dialog, int(row), "kur")
    except (TypeError, ValueError):
        return False


def kur_hucre_duzenle(dialog, *, idx: int, event=None, on_done=None) -> None:
    if getattr(dialog, "_fatura_kilitli", False):
        return
    if not (0 <= idx < len(dialog.satirlar)):
        return
    baslik_pb = _baslik_doviz_pb(dialog)
    if baslik_pb:
        messagebox.showinfo(
            "Kur",
            f"Bu fatura {baslik_pb} olarak düzenleniyor. Kur, fatura başlığındaki "
            "döviz panelinden değiştirilir (tüm satırlar aynı kurla hesaplanır).",
            parent=dialog,
        )
        return
    tablo = dialog.satir_tablosu
    iid = str(idx)
    satir = dialog.satirlar[idx]
    if _satir_pb(satir) == "TRY":
        return
    mevcut = str(satir.get("kur") or "1").replace(".", ",")
    editor, var = _overlay_entry(dialog, tablo, iid, "kur", mevcut, justify="right")
    if editor is None:
        return

    def _iptal(_e=None):
        _editor_kapat(dialog)
        return "break"

    def _kaydet(_e=None, tab=False, geri=False, satir_yon=0):
        yeni = _d(var.get(), Decimal("1"))
        if yeni <= 0:
            messagebox.showerror("Kur", "Kur sıfırdan büyük olmalıdır.", parent=dialog)
            return "break"
        eski_kur = _satir_kuru(satir)
        if yeni != eski_kur:
            uzlasma_etkisini_kaldir(dialog)
        doviz_fiyat = (
            _d(satir.get("birim_satis_fiyati")) / eski_kur if eski_kur > 0 else Decimal("0")
        )
        satir["kur"] = str(yeni)
        if doviz_fiyat > 0:
            satir["birim_fiyat_doviz"] = str(doviz_fiyat.quantize(Decimal("0.0001")))
            satir["birim_satis_fiyati"] = str(_tl_fiyat(doviz_fiyat, satir))
        _editor_kapat(dialog)
        _yenile_koru(dialog, tablo, iid)
        if tab:
            _tab_ilerle(dialog, idx, "kur", geri=geri, satir_yon=satir_yon)
        if on_done:
            on_done()
        return "break"

    editor.bind("<Return>", lambda e: _kaydet(tab=True))
    editor._uygula_fn = lambda: _kaydet()
    editor.bind("<KP_Enter>", lambda e: _kaydet(tab=True))
    editor.bind("<Shift-Return>", lambda e: _kaydet(tab=True, geri=True))
    editor.bind("<Escape>", _iptal)
    editor.bind("<Tab>", lambda e: _kaydet(tab=True))
    editor.bind("<Shift-Tab>", lambda e: _kaydet(tab=True, geri=True))
    _ok_gezinme_bagla(editor, _kaydet)


def iskonto_yuzde_hucre(dialog, *, idx: int, event=None, on_done=None) -> None:
    """İskonto 1 → 2 → 3 ardışık hücreler (Enter / Tab / → sıradaki); tek kademeli belgede tek hücre."""
    if getattr(dialog, "_fatura_kilitli", False):
        return
    if not (0 <= idx < len(dialog.satirlar)):
        return
    from satir_ici_urun_giris import iskonto_metni_coz, sayi_metni
    from satir_klavye import ISKONTO_ALANLARI, UcluIskontoEditor, iskonto_birlestir

    tablo = dialog.satir_tablosu
    iid = str(idx)
    satir = dialog.satirlar[idx]
    tek_kademe = bool(getattr(dialog, "TEK_KADEME_ISKONTO", False))
    _editor_kapat(dialog)
    box = _hucre_bbox(tablo, iid, "iskonto")
    if not box:
        return

    def _bitir(degerler, hareket):
        try:
            i1, i2, i3 = iskonto_metni_coz(iskonto_birlestir(degerler))
            if tek_kademe and (i2 or i3):
                raise ValueError("Bu belgede tek kademe iskonto girilir (ör. 10).")
        except ValueError as hata:
            messagebox.showerror("İskonto", str(hata), parent=dialog)
            return False
        _kaydet(
            i1, i2, i3,
            tab=hareket != "kal",
            geri=hareket == "geri",
            satir_yon={"yukari": -1, "asagi": 1}.get(hareket, 0),
        )
        return True

    def _kaydet(i1, i2, i3, tab=False, geri=False, satir_yon=0):
        oranlar = {"iskonto_orani": str(i1), "iskonto_orani_2": str(i2), "iskonto_orani_3": str(i3)}
        eski = {k: satir.get(k) for k in oranlar}
        if any(_d(eski.get(k)) != _d(v) for k, v in oranlar.items()):
            uzlasma_etkisini_kaldir(dialog)
            satir.update(oranlar)
            satir.pop("_iskonto_tutar_manuel", None)
            if hasattr(dialog, "_fatura_iskonto_audit"):
                try:
                    dialog._fatura_iskonto_audit(idx, eski, oranlar)
                except Exception:
                    pass
        _editor_kapat(dialog)
        _yenile_koru(dialog, tablo, iid)
        if tab:
            _tab_ilerle(dialog, idx, "iskonto", geri=geri, satir_yon=satir_yon)
        if on_done:
            on_done()

    editor = UcluIskontoEditor(
        tablo,
        box,
        [sayi_metni(satir.get(k) or 0) for k in ISKONTO_ALANLARI],
        adet=1 if tek_kademe else 3,
        on_bitir=_bitir,
        on_iptal=lambda: _editor_kapat(dialog),
        yukseklik=scale_height(HUCRE_EDITOR_TABAN_PX),
    )
    if getattr(dialog, "_hucre_giris_geri", False):
        editor.kutu_odakla(len(editor.kutular) - 1)
    dialog._satir_hucre_editor = editor
    _odak_cikinca_uygula(dialog, editor, *editor.kutular)


def iskonto_penceresi_ac(dialog, *, idx: int, event=None, on_done=None) -> None:
    """Satır işlemleri menüsünden: ortak üçlü iskonto penceresi."""
    if getattr(dialog, "_fatura_kilitli", False):
        return
    if not (0 <= idx < len(dialog.satirlar)):
        return
    from fatura_iskonto_ui import satir_iskontolari_ac

    satir = dialog.satirlar[idx]

    def _uygula(oranlar: dict):
        eski = {
            "iskonto_orani": satir.get("iskonto_orani"),
            "iskonto_orani_2": satir.get("iskonto_orani_2"),
            "iskonto_orani_3": satir.get("iskonto_orani_3"),
        }
        if any(_d(eski.get(k)) != _d(v) for k, v in oranlar.items()):
            uzlasma_etkisini_kaldir(dialog)
        satir.update(oranlar)
        satir.pop("_iskonto_tutar_manuel", None)
        if hasattr(dialog, "_fatura_iskonto_audit"):
            try:
                dialog._fatura_iskonto_audit(idx, eski, oranlar)
            except Exception:
                pass
        _yenile_koru(dialog, dialog.satir_tablosu, str(idx))
        if on_done:
            on_done()
        else:
            # Uygula sonrası sıradaki kullanılabilir hücre (çift atlama yok)
            _tab_ilerle(dialog, idx, "iskonto")

    satir_iskontolari_ac(
        dialog,
        belge_turu=getattr(dialog, "ISKONTO_BELGE_TURU", "Satış"),
        satir=satir,
        fiyat_alani="birim_satis_fiyati",
        on_uygula=_uygula,
        satir_kimlik=idx,
        tek_kademe=bool(getattr(dialog, "TEK_KADEME_ISKONTO", False)),
    )


def iskonto_tutar_hucre(dialog, *, idx: int, event=None, on_done=None) -> None:
    """İskonto tutarı → yüzdeye çevir (döngü yok: yalnızca oran yazılır)."""
    if getattr(dialog, "_fatura_kilitli", False):
        return
    if not (0 <= idx < len(dialog.satirlar)):
        return
    tablo = dialog.satir_tablosu
    iid = str(idx)
    satir = dialog.satirlar[idx]
    miktar = _d(satir.get("miktar"))
    fiyat = _d(satir.get("birim_satis_fiyati"))
    brut = miktar * fiyat
    # Mevcut indirim
    from database.satis_faturasi_service import SatisFaturasiService

    _, indirim, _ = SatisFaturasiService._satir_net(
        miktar,
        fiyat,
        satir.get("iskonto_orani") or 0,
        satir.get("iskonto_orani_2") or 0,
        satir.get("iskonto_orani_3") or 0,
    )
    editor, var = _overlay_entry(
        dialog, tablo, iid, "iskonto_tutar", str(indirim).replace(".", ","), justify="right"
    )
    if editor is None:
        return

    def _iptal(_e=None):
        _editor_kapat(dialog)
        return "break"

    def _kaydet(_e=None, tab=False, geri=False, satir_yon=0):
        tutar = _d(var.get())
        if tutar < 0:
            messagebox.showerror("İskonto", "İskonto tutarı negatif olamaz.", parent=dialog)
            return "break"
        if brut > 0 and tutar > brut:
            messagebox.showerror("İskonto", "İskonto tutarı brüt tutarı aşamaz.", parent=dialog)
            return "break"
        if brut <= 0:
            oran = Decimal("0")
        else:
            hane = Decimal("0.01") if getattr(dialog, "TEK_KADEME_ISKONTO", False) else Decimal("0.0001")
            oran = (tutar / brut * Decimal("100")).quantize(hane)
        if tutar != indirim:
            uzlasma_etkisini_kaldir(dialog)
        satir["iskonto_orani"] = str(oran)
        satir["iskonto_orani_2"] = "0"
        satir["iskonto_orani_3"] = "0"
        _editor_kapat(dialog)
        _yenile_koru(dialog, tablo, iid)
        if tab:
            _tab_ilerle(dialog, idx, "iskonto_tutar", geri=geri, satir_yon=satir_yon)
        if on_done:
            on_done()
        return "break"

    editor.bind("<Return>", lambda e: _kaydet(tab=True))
    editor._uygula_fn = lambda: _kaydet()
    editor.bind("<KP_Enter>", lambda e: _kaydet(tab=True))
    editor.bind("<Shift-Return>", lambda e: _kaydet(tab=True, geri=True))
    editor.bind("<Escape>", _iptal)
    editor.bind("<Tab>", lambda e: _kaydet(tab=True))
    editor.bind("<Shift-Tab>", lambda e: _kaydet(tab=True, geri=True))
    _ok_gezinme_bagla(editor, _kaydet)


def kdv_hucre_duzenle(dialog, *, idx: int, event=None, on_done=None) -> None:
    if getattr(dialog, "_fatura_kilitli", False):
        return
    if not (0 <= idx < len(dialog.satirlar)):
        return
    tablo = dialog.satir_tablosu
    iid = str(idx)
    satir = dialog.satirlar[idx]
    mevcut = str(satir.get("kdv_orani") or "0").rstrip("0").rstrip(".") if "." in str(satir.get("kdv_orani") or "") else str(satir.get("kdv_orani") or "0")
    _editor_kapat(dialog)
    box = _hucre_bbox(tablo, iid, "kdv")
    if not box:
        return
    bx, by, bw, bh = box
    degerler = tuple(str(x) for x in KDV_ORANLARI)
    if mevcut not in degerler:
        degerler = degerler + (mevcut,)
    var = tk.StringVar(value=mevcut)
    editor = ttk.Combobox(
        tablo,
        textvariable=var,
        values=degerler,
        state="readonly",
        justify="center",
        font=("Segoe UI", 10),
    )
    editor.place(x=bx, y=by, width=max(bw, 72), height=max(bh, scale_height(26)))
    editor.focus_set()
    dialog._satir_hucre_editor = editor
    _odak_cikinca_uygula(dialog, editor)

    def _iptal(_e=None):
        _editor_kapat(dialog)
        return "break"

    def _uygula(_e=None, tab=False, geri=False, satir_yon=0):
        if getattr(dialog, "_kdv_uygulaniyor", False):
            return "break"
        # Editor yoksa (önceki ComboboxSelected sonrası FocusOut) tekrar işleme
        if getattr(dialog, "_satir_hucre_editor", None) is None and _e is not None:
            return "break"
        dialog._kdv_uygulaniyor = True
        try:
            from database.fatura_kdv_service import kdv_orani_dogrula

            try:
                yeni = kdv_orani_dogrula(var.get())
            except ValueError as hata:
                messagebox.showerror("KDV", str(hata), parent=dialog)
                var.set(mevcut)
                return "break"
            if _d(satir.get("kdv_orani")) != _d(yeni):
                uzlasma_etkisini_kaldir(dialog)
            satir["kdv_orani"] = str(yeni)
            try:
                dialog._genel_toplam_duzenleniyor = False
            except Exception:
                pass
            _editor_kapat(dialog)
            _yenile_koru(dialog, tablo, iid)
            if tab:
                _tab_ilerle(dialog, idx, "kdv", geri=geri, satir_yon=satir_yon)
            if on_done:
                on_done()
        finally:
            dialog._kdv_uygulaniyor = False
        return "break"

    editor.bind("<<ComboboxSelected>>", lambda e: _uygula(tab=True))
    editor.bind("<Return>", lambda e: _uygula(tab=True))
    editor._uygula_fn = lambda: _uygula()
    editor.bind("<KP_Enter>", lambda e: _uygula(tab=True))
    editor.bind("<Shift-Return>", lambda e: _uygula(tab=True, geri=True))
    editor.bind("<Escape>", _iptal)
    editor.bind("<Tab>", lambda e: _uygula(tab=True))
    editor.bind("<Shift-Tab>", lambda e: _uygula(tab=True, geri=True))
    _ok_gezinme_bagla(editor, _uygula)
    _listeyi_ac(editor, event)


def aciklama_hucre_duzenle(dialog, *, idx: int, event=None, on_done=None) -> None:
    if getattr(dialog, "_fatura_kilitli", False):
        return
    if not (0 <= idx < len(dialog.satirlar)):
        return
    tablo = dialog.satir_tablosu
    iid = str(idx)
    satir = dialog.satirlar[idx]
    mevcut = satir.get("aciklama") or ""
    editor, var = _overlay_entry(dialog, tablo, iid, "aciklama", mevcut, justify="left")
    if editor is None:
        return

    def _iptal(_e=None):
        _editor_kapat(dialog)
        return "break"

    def _kaydet(_e=None, tab=False, geri=False, satir_yon=0):
        satir["aciklama"] = (var.get() or "").strip()
        _editor_kapat(dialog)
        _yenile_koru(dialog, tablo, iid)
        if tab:
            _tab_ilerle(dialog, idx, "aciklama", geri=geri, satir_yon=satir_yon)
        if on_done:
            on_done()
        return "break"

    editor.bind("<Return>", lambda e: _kaydet(tab=True))
    editor._uygula_fn = lambda: _kaydet()
    editor.bind("<KP_Enter>", lambda e: _kaydet(tab=True))
    editor.bind("<Shift-Return>", lambda e: _kaydet(tab=True, geri=True))
    editor.bind("<Escape>", _iptal)
    editor.bind("<Tab>", lambda e: _kaydet(tab=True))
    editor.bind("<Shift-Tab>", lambda e: _kaydet(tab=True, geri=True))
    _ok_gezinme_bagla(editor, _kaydet)


def fatura_satir_hucre_etkilesim(dialog) -> None:
    """Tek tık hücre düzenleme; ürün adı/kodu/barkod çift tık veya F2 stok kartı; bind çoğalmasını engeller."""
    tablo = getattr(dialog, "satir_tablosu", None)
    if tablo is None:
        return
    if getattr(dialog, "_satir_hucre_etkilesim_kurulu", False):
        return
    dialog._satir_hucre_etkilesim_kurulu = True

    tip = getattr(dialog, "_satir_hucre_tooltip", None)
    if tip is None:
        tip = tk.Label(
            dialog,
            text="",
            background="#FFFDE7",
            foreground="#333",
            relief="solid",
            borderwidth=1,
            font=("Segoe UI", 8),
            padx=4,
            pady=1,
        )
        dialog._satir_hucre_tooltip = tip

    def _tooltip_gizle(_e=None):
        try:
            tip.place_forget()
        except tk.TclError:
            pass

    def _motion(event):
        if getattr(dialog, "_fatura_kilitli", False):
            _tooltip_gizle()
            return
        kolon = _kolon_adi(tablo, event)
        row = tablo.identify_row(event.y)
        if (
            not row
            or row == "__yeni__"
            or kolon not in DUZENLENEBILIR_KOLONLAR
            or (kolon == "kur" and not _kur_duzenlenebilir(dialog, row))
        ):
            _tooltip_gizle()
            try:
                tablo.configure(cursor="")
            except tk.TclError:
                pass
            return
        try:
            tablo.configure(cursor="hand2" if kolon in ("birim", "para_birimi", "kdv") else "xterm")
        except tk.TclError:
            pass
        if kolon == "iskonto":
            tip.configure(text="Tıkla — iskonto 1 / 2 / 3 (Enter ile sıradaki)")
        else:
            tip.configure(text=f"Tıkla — {kolon} düzenle")
        try:
            tip.place(
                x=event.x_root - dialog.winfo_rootx() + 12,
                y=event.y_root - dialog.winfo_rooty() + 18,
            )
        except tk.TclError:
            pass
        if kolon == "urun_adi" and row:
            try:
                idx = int(row)
                ad = dialog.satirlar[idx].get("urun_adi") or ""
                if len(ad) > 30:
                    tip.configure(text=ad)
            except Exception:
                pass

    def _tek_tik(event):
        _tooltip_gizle()
        if getattr(dialog, "_fatura_kilitli", False):
            return None
        kolon = _kolon_adi(tablo, event)
        row = tablo.identify_row(event.y)
        if not editoru_birak(dialog):
            return "break"
        if not row or row == "__yeni__" or kolon not in DUZENLENEBILIR_KOLONLAR:
            return None
        try:
            idx = int(row)
        except (TypeError, ValueError):
            return None
        tablo.selection_set(row)
        if kolon == "kur" and not _kur_duzenlenebilir(dialog, row):
            return None
        # Kısa gecikme: seçim + odak otursun, çift tık ile çakışmasın
        def _ac(_i=idx, _k=kolon):
            if getattr(dialog, "_satir_cift_tik_engel", False):
                return
            hucre_duzenle(dialog, idx=_i, kolon=_k, event=event)

        dialog.after(180, _ac)
        return None

    def _cift_tik(event):
        dialog._satir_cift_tik_engel = True
        dialog.after(250, lambda: setattr(dialog, "_satir_cift_tik_engel", False))
        _tooltip_gizle()
        kolon = _kolon_adi(tablo, event)
        row = tablo.identify_row(event.y)
        if row and row != "__yeni__" and kolon in urun_kolonlari(dialog):
            try:
                idx = int(row)
            except (TypeError, ValueError):
                return None
            tablo.selection_set(row)
            satir_stok_karti_ac(dialog, idx)
            return "break"
        if row and kolon in DUZENLENEBILIR_KOLONLAR:
            try:
                idx = int(row)
            except (TypeError, ValueError):
                return "break"
            tablo.selection_set(row)
            if kolon == "kur" and not _kur_duzenlenebilir(dialog, row):
                return "break"
            hucre_duzenle(dialog, idx=idx, kolon=kolon, event=event)
            return "break"
        return None

    def _f2(_event=None):
        """F2: seçili satırın bağlı stok kartı (kilitli/onaylı faturada da açılır)."""
        if not odak_tabloda_mi(dialog, tablo):
            return None
        ed = getattr(dialog, "_satir_hucre_editor", None)
        secim = [i for i in tablo.selection() if i != "__yeni__"]
        if not secim:
            return "break"
        try:
            idx = int(secim[0])
        except (TypeError, ValueError):
            return "break"
        if ed is not None and not acik_editoru_uygula(dialog):
            return "break"
        satir_stok_karti_ac(dialog, idx)
        return "break"

    def _enter_tablo(event=None):
        """Seçili satırda editör yoksa ilk alana gir; çift işleme yok."""
        if getattr(dialog, "_fatura_kilitli", False):
            return None
        secim = _secili_satirlar()
        if not editoru_birak(dialog):
            return "break"
        # İskonto modalı açıksa sızma
        try:
            for w in dialog.winfo_children():
                if isinstance(w, tk.Toplevel) and w.winfo_exists():
                    baslik = (w.title() or "").casefold()
                    if "iskonto" in baslik:
                        return "break"
        except tk.TclError:
            pass
        if not secim:
            return None
        try:
            idx = int(secim[0])
        except (TypeError, ValueError):
            return None
        kolon = ilk_duzenlenebilir_kolon(dialog, idx)
        if not kolon:
            return "break"
        focus_editable_cell(dialog, idx, kolon)
        return "break"

    def _secili_satirlar() -> list[str]:
        # Açık editör yazılınca tablo kendi satırını yeniden seçer; kullanıcının seçimi önce alınır
        try:
            return [i for i in tablo.selection() if i != "__yeni__"]
        except tk.TclError:
            return []

    def _ok_tablo(geri: bool):
        """Seçili satırda sağ ok ilk, sol ok son düzenlenebilir hücreyi açar (açık editör önce yazılır)."""
        if getattr(dialog, "_fatura_kilitli", False):
            return None
        secim = _secili_satirlar()
        if not editoru_birak(dialog):
            return "break"
        if not secim:
            return None
        try:
            idx = int(secim[0])
        except (TypeError, ValueError):
            return None
        sira = reversed(EDITABLE_COLUMN_ORDER) if geri else EDITABLE_COLUMN_ORDER
        kolon = next((k for k in sira if kolon_duzenlenebilir_mi(dialog, idx, k)), None)
        if kolon:
            focus_editable_cell(dialog, idx, kolon)
        return "break"

    def _kapanista_temizle(_e=None):
        # Toplevel <Destroy> bağı her alt widget yok edildiğinde de tetiklenir
        if _e is not None and getattr(_e, "widget", dialog) is not dialog:
            return
        _tooltip_gizle()
        _editor_kapat(dialog)
        dialog._satir_hucre_etkilesim_kurulu = False

    tablo.bind("<Button-1>", _tek_tik, add="+")
    tablo.bind("<Double-1>", _cift_tik)
    tablo.bind("<F2>", _f2)
    tablo.bind("<Return>", _enter_tablo)
    tablo.bind("<KP_Enter>", _enter_tablo)
    tablo.bind("<Right>", lambda e: _ok_tablo(False))
    tablo.bind("<Left>", lambda e: _ok_tablo(True))
    tablo.bind("<Motion>", _motion)
    tablo.bind("<Leave>", _tooltip_gizle)
    dialog.bind("<F2>", _f2)
    dialog.bind("<Destroy>", _kapanista_temizle, add="+")
