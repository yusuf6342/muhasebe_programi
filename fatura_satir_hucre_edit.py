"""Satış faturası Treeview — satır içi hücre düzenleme (miktar, birim, fiyat, PB, kur, iskonto, KDV, açıklama)."""

from __future__ import annotations

import tkinter as tk
from decimal import Decimal, InvalidOperation
from tkinter import messagebox, ttk
from typing import Callable

from database.models.doviz import PARA_BIRIMLERI
from database.models.stok import KDV_ORANLARI
from fatura_tema import HUCRE_EDITOR_TABAN_PX, scale_height
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


def kolon_duzenlenebilir_mi(dialog, idx: int, kolon: str) -> bool:
    """Görünür + yetki + satır koşulu — Enter gezinmede atlama kararı."""
    if getattr(dialog, "_fatura_kilitli", False):
        return False
    if kolon not in EDITABLE_COLUMN_ORDER:
        return False
    if not _kolon_gorunur_mu(dialog, kolon):
        return False
    if not (0 <= idx < len(getattr(dialog, "satirlar", []) or [])):
        return False
    satir = dialog.satirlar[idx]
    if kolon == "birim":
        kod = (satir.get("urun_kodu") or "").strip()
        try:
            return len(stok_aktif_birimleri(kod)) > 1
        except Exception:
            return False
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
    """Son satır son alan sonrası: Barkod / ürün kodu / ürün adı."""
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


def _editor_kapat(dialog) -> None:
    ed = getattr(dialog, "_satir_hucre_editor", None)
    if ed is None:
        return
    try:
        ed.destroy()
    except tk.TclError:
        pass
    dialog._satir_hucre_editor = None


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


def _tab_ilerle(dialog, idx: int, kolon: str, geri: bool = False):
    """Enter/Tab sonrası tek adım — çift atlamayı önler."""
    if getattr(dialog, "_satir_gezinme_kilit", False):
        return
    dialog._satir_gezinme_kilit = True

    def _ac():
        try:
            hedef = find_next_editable_cell(
                dialog, idx, kolon, direction=-1 if geri else 1
            )
            if hedef is None:
                if not geri:
                    _urun_arama_odakla(dialog)
                return
            r, c = hedef
            focus_editable_cell(dialog, r, c)
        finally:
            try:
                dialog.after(80, lambda: setattr(dialog, "_satir_gezinme_kilit", False))
            except tk.TclError:
                dialog._satir_gezinme_kilit = False

    try:
        dialog.after_idle(_ac)
    except tk.TclError:
        dialog.after(30, _ac)


def _overlay_entry(dialog, tablo, iid, kolon, metin, *, justify="right"):
    _editor_kapat(dialog)
    box = _hucre_bbox(tablo, iid, kolon)
    if not box:
        return None, None
    bx, by, bw, bh = box
    var = tk.StringVar(value=metin)
    editor = ttk.Entry(tablo, textvariable=var, justify=justify, font=("Segoe UI", 10))
    editor.place(x=bx, y=by, width=max(bw, 50), height=max(bh, scale_height(HUCRE_EDITOR_TABAN_PX)))
    editor.focus_set()
    editor.selection_range(0, "end")
    dialog._satir_hucre_editor = editor
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

    def _kaydet(_e=None, tab=False, geri=False):
        try:
            yeni = miktar_metnini_coz(var.get())
        except ValueError as hata:
            messagebox.showerror("Miktar", str(hata), parent=dialog)
            return "break"
        satir = dialog.satirlar[idx]
        kod = (satir.get("urun_kodu") or "").strip()
        birim = (satir.get("birim") or "Adet").strip()
        yeni_temel = temel_miktar(yeni, birim, kod)
        if not _stok_kontrol(dialog, idx, yeni_temel, kod):
            return "break"
        satir["miktar"] = str(yeni)
        satir["temel_miktar"] = str(yeni_temel)
        _editor_kapat(dialog)
        _yenile_koru(dialog, tablo, iid)
        if tab:
            _tab_ilerle(dialog, idx, "miktar", geri=geri)
        if on_done:
            on_done()
        return "break"

    editor.bind("<Return>", lambda e: _kaydet(tab=True))
    editor.bind("<KP_Enter>", lambda e: _kaydet(tab=True))
    editor.bind("<Shift-Return>", lambda e: _kaydet(tab=True, geri=True))
    editor.bind("<Escape>", _iptal)
    editor.bind("<Tab>", lambda e: _kaydet(tab=True))
    editor.bind("<Shift-Tab>", lambda e: _kaydet(tab=True, geri=True))


def birim_hucre_duzenle(dialog, *, idx: int, event=None, on_done=None) -> None:
    if getattr(dialog, "_fatura_kilitli", False):
        messagebox.showwarning("Birim", "Onaylı faturada birim değiştirilemez.", parent=dialog)
        return
    if not (0 <= idx < len(dialog.satirlar)):
        return
    tablo = dialog.satir_tablosu
    iid = str(idx)
    satir = dialog.satirlar[idx]
    kod = (satir.get("urun_kodu") or "").strip()
    birimler = stok_aktif_birimleri(kod)
    if len(birimler) <= 1:
        messagebox.showinfo(
            "Birim",
            "Bu stok kartında yalnızca ana birim tanımlı.",
            parent=dialog,
        )
        return
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

    def _iptal(_e=None):
        _editor_kapat(dialog)
        return "break"

    def _uygula(_e=None, tab=False, geri=False):
        yeni_birim = (var.get() or "").strip()
        if not yeni_birim or yeni_birim.casefold() == mevcut.casefold():
            _editor_kapat(dialog)
            if tab:
                _tab_ilerle(dialog, idx, "birim", geri=geri)
            if on_done:
                on_done()
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
        guncel = birim_degistir(satir, yeni_birim, musteri=musteri, manuel_fiyat_modu=mod)
        if guncel is None:
            _editor_kapat(dialog)
            return "break"
        from fatura_satir_birim_service import satir_temel_talep

        if not _stok_kontrol(dialog, idx, satir_temel_talep(guncel), kod):
            _editor_kapat(dialog)
            return "break"
        dialog.satirlar[idx] = guncel
        _editor_kapat(dialog)
        _yenile_koru(dialog, tablo, iid)
        if tab:
            _tab_ilerle(dialog, idx, "birim", geri=geri)
        if on_done:
            on_done()
        return "break"

    editor.bind("<<ComboboxSelected>>", lambda e: _uygula(tab=True))
    editor.bind("<Return>", lambda e: _uygula(tab=True))
    editor.bind("<KP_Enter>", lambda e: _uygula(tab=True))
    editor.bind("<Shift-Return>", lambda e: _uygula(tab=True, geri=True))
    editor.bind("<Escape>", _iptal)
    editor.bind("<Tab>", lambda e: _uygula(tab=True))
    editor.bind("<Shift-Tab>", lambda e: _uygula(tab=True, geri=True))
    try:
        editor.event_generate("<Down>")
    except tk.TclError:
        pass


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
    mevcut = str(satir.get("birim_satis_fiyati") or "0").replace(".", ",")
    editor, var = _overlay_entry(dialog, tablo, iid, "fiyat", mevcut, justify="right")
    if editor is None:
        return

    def _iptal(_e=None):
        _editor_kapat(dialog)
        return "break"

    def _kaydet(_e=None, tab=False, geri=False):
        yeni = _d(var.get())
        if yeni < 0:
            messagebox.showerror("Fiyat", "Fiyat negatif olamaz.", parent=dialog)
            return "break"
        try:
            from fatura_manuel_fiyat_ui import maliyet_alti_kontrol

            if not maliyet_alti_kontrol(
                yeni,
                satir,
                yontem=dialog.yontem.get() if hasattr(dialog, "yontem") else None,
                parent=dialog,
                hedef_marj=dialog._fatura_hedef_marj() if hasattr(dialog, "_fatura_hedef_marj") else None,
            ):
                return "break"
        except Exception:
            pass
        satir["birim_satis_fiyati"] = str(yeni)
        satir["manuel_fiyat"] = True
        pb = (satir.get("satir_para_birimi") or satir.get("para_birimi") or "TRY").upper()
        if pb not in ("TRY", "TL"):
            satir["birim_fiyat_doviz"] = str(yeni)
        _editor_kapat(dialog)
        _yenile_koru(dialog, tablo, iid)
        if tab:
            _tab_ilerle(dialog, idx, "fiyat", geri=geri)
        if on_done:
            on_done()
        return "break"

    editor.bind("<Return>", lambda e: _kaydet(tab=True))
    editor.bind("<KP_Enter>", lambda e: _kaydet(tab=True))
    editor.bind("<Shift-Return>", lambda e: _kaydet(tab=True, geri=True))
    editor.bind("<Escape>", _iptal)
    editor.bind("<Tab>", lambda e: _kaydet(tab=True))
    editor.bind("<Shift-Tab>", lambda e: _kaydet(tab=True, geri=True))


def pb_hucre_duzenle(dialog, *, idx: int, event=None, on_done=None) -> None:
    if getattr(dialog, "_fatura_kilitli", False):
        return
    if not (0 <= idx < len(dialog.satirlar)):
        return
    tablo = dialog.satir_tablosu
    iid = str(idx)
    satir = dialog.satirlar[idx]
    mevcut = (satir.get("satir_para_birimi") or satir.get("para_birimi") or "TRY").upper()
    if mevcut == "TL":
        mevcut = "TRY"
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

    def _iptal(_e=None):
        _editor_kapat(dialog)
        return "break"

    def _uygula(_e=None, tab=False, geri=False):
        yeni = (var.get() or "TRY").upper()
        if yeni == "TL":
            yeni = "TRY"
        eski = mevcut
        if yeni == eski:
            _editor_kapat(dialog)
            if tab:
                _tab_ilerle(dialog, idx, "para_birimi", geri=geri)
            if on_done:
                on_done()
            return "break"
        # Kur
        if yeni == "TRY":
            satir["kur"] = "1"
        else:
            kur = _satir_kur_varsayilan(dialog, yeni)
            satir["kur"] = str(kur)
        satir["satir_para_birimi"] = yeni
        satir["para_birimi"] = yeni
        _editor_kapat(dialog)
        _yenile_koru(dialog, tablo, iid)
        if tab:
            _tab_ilerle(dialog, idx, "para_birimi", geri=geri)
        if on_done:
            on_done()
        return "break"

    editor.bind("<<ComboboxSelected>>", lambda e: _uygula(tab=True))
    editor.bind("<Return>", lambda e: _uygula(tab=True))
    editor.bind("<KP_Enter>", lambda e: _uygula(tab=True))
    editor.bind("<Shift-Return>", lambda e: _uygula(tab=True, geri=True))
    editor.bind("<Escape>", _iptal)
    editor.bind("<Tab>", lambda e: _uygula(tab=True))
    editor.bind("<Shift-Tab>", lambda e: _uygula(tab=True, geri=True))
    try:
        editor.event_generate("<Down>")
    except tk.TclError:
        pass


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
        return Decimal(str(DovizService.kur_degeri(tarih, pb) or 1))
    except Exception:
        try:
            if hasattr(dialog, "_doviz_kur"):
                return Decimal(str(dialog._doviz_kur.get() or "1").replace(",", "."))
        except Exception:
            pass
    return Decimal("1")


def kur_hucre_duzenle(dialog, *, idx: int, event=None, on_done=None) -> None:
    if getattr(dialog, "_fatura_kilitli", False):
        return
    if not (0 <= idx < len(dialog.satirlar)):
        return
    tablo = dialog.satir_tablosu
    iid = str(idx)
    satir = dialog.satirlar[idx]
    pb = (satir.get("satir_para_birimi") or satir.get("para_birimi") or "TRY").upper()
    if pb in ("TRY", "TL"):
        messagebox.showinfo("Kur", "TL satırında kur sabittir (1).", parent=dialog)
        return
    mevcut = str(satir.get("kur") or "1").replace(".", ",")
    editor, var = _overlay_entry(dialog, tablo, iid, "kur", mevcut, justify="right")
    if editor is None:
        return

    def _iptal(_e=None):
        _editor_kapat(dialog)
        return "break"

    def _kaydet(_e=None, tab=False, geri=False):
        yeni = _d(var.get(), Decimal("1"))
        if yeni <= 0:
            messagebox.showerror("Kur", "Kur sıfırdan büyük olmalıdır.", parent=dialog)
            return "break"
        satir["kur"] = str(yeni)
        _editor_kapat(dialog)
        _yenile_koru(dialog, tablo, iid)
        if tab:
            _tab_ilerle(dialog, idx, "kur", geri=geri)
        if on_done:
            on_done()
        return "break"

    editor.bind("<Return>", lambda e: _kaydet(tab=True))
    editor.bind("<KP_Enter>", lambda e: _kaydet(tab=True))
    editor.bind("<Shift-Return>", lambda e: _kaydet(tab=True, geri=True))
    editor.bind("<Escape>", _iptal)
    editor.bind("<Tab>", lambda e: _kaydet(tab=True))
    editor.bind("<Shift-Tab>", lambda e: _kaydet(tab=True, geri=True))


def iskonto_yuzde_hucre(dialog, *, idx: int, event=None, on_done=None) -> None:
    """İskonto hücresi → ortak üçlü iskonto modalı (doğrudan hücreye serbest giriş yok)."""
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
        belge_turu="Satış",
        satir=satir,
        fiyat_alani="birim_satis_fiyati",
        on_uygula=_uygula,
        satir_kimlik=idx,
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

    def _kaydet(_e=None, tab=False, geri=False):
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
            oran = (tutar / brut * Decimal("100")).quantize(Decimal("0.0001"))
        satir["iskonto_orani"] = str(oran)
        satir["iskonto_orani_2"] = "0"
        satir["iskonto_orani_3"] = "0"
        _editor_kapat(dialog)
        _yenile_koru(dialog, tablo, iid)
        if tab:
            _tab_ilerle(dialog, idx, "iskonto_tutar", geri=geri)
        if on_done:
            on_done()
        return "break"

    editor.bind("<Return>", lambda e: _kaydet(tab=True))
    editor.bind("<KP_Enter>", lambda e: _kaydet(tab=True))
    editor.bind("<Shift-Return>", lambda e: _kaydet(tab=True, geri=True))
    editor.bind("<Escape>", _iptal)
    editor.bind("<Tab>", lambda e: _kaydet(tab=True))
    editor.bind("<Shift-Tab>", lambda e: _kaydet(tab=True, geri=True))


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

    def _iptal(_e=None):
        _editor_kapat(dialog)
        return "break"

    def _uygula(_e=None, tab=False, geri=False):
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
            satir["kdv_orani"] = str(yeni)
            try:
                dialog._genel_toplam_duzenleniyor = False
            except Exception:
                pass
            _editor_kapat(dialog)
            _yenile_koru(dialog, tablo, iid)
            if tab:
                _tab_ilerle(dialog, idx, "kdv", geri=geri)
            if on_done:
                on_done()
        finally:
            dialog._kdv_uygulaniyor = False
        return "break"

    editor.bind("<<ComboboxSelected>>", lambda e: _uygula(tab=True))
    editor.bind("<Return>", lambda e: _uygula(tab=True))
    editor.bind("<KP_Enter>", lambda e: _uygula(tab=True))
    editor.bind("<Shift-Return>", lambda e: _uygula(tab=True, geri=True))
    editor.bind("<Escape>", _iptal)
    editor.bind("<Tab>", lambda e: _uygula(tab=True))
    editor.bind("<Shift-Tab>", lambda e: _uygula(tab=True, geri=True))
    # FocusOut: seçim sonrası çift tetiklemeyi _satir_hucre_editor kontrolü keser
    editor.bind("<FocusOut>", lambda e: _uygula(tab=False))
    try:
        editor.event_generate("<Down>")
    except tk.TclError:
        pass


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

    def _kaydet(_e=None, tab=False, geri=False):
        satir["aciklama"] = (var.get() or "").strip()
        _editor_kapat(dialog)
        _yenile_koru(dialog, tablo, iid)
        if tab:
            _tab_ilerle(dialog, idx, "aciklama", geri=geri)
        if on_done:
            on_done()
        return "break"

    editor.bind("<Return>", lambda e: _kaydet(tab=True))
    editor.bind("<KP_Enter>", lambda e: _kaydet(tab=True))
    editor.bind("<Shift-Return>", lambda e: _kaydet(tab=True, geri=True))
    editor.bind("<Escape>", _iptal)
    editor.bind("<Tab>", lambda e: _kaydet(tab=True))
    editor.bind("<Shift-Tab>", lambda e: _kaydet(tab=True, geri=True))


def fatura_satir_hucre_etkilesim(dialog) -> None:
    """Tek tık hücre düzenleme; iskonto için çift tık / F2; bind çoğalmasını engeller."""
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
        if not row or kolon not in DUZENLENEBILIR_KOLONLAR:
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
        if kolon in ("iskonto", "iskonto_tutar"):
            tip.configure(text="Çift tık veya F2 — çoklu iskonto")
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
        if getattr(dialog, "_satir_hucre_editor", None) is not None:
            return None
        kolon = _kolon_adi(tablo, event)
        row = tablo.identify_row(event.y)
        if not row or kolon not in DUZENLENEBILIR_KOLONLAR:
            return None
        # İskonto: çift tık / F2 / araç çubuğu
        if kolon in ("iskonto", "iskonto_tutar"):
            try:
                tablo.selection_set(row)
            except tk.TclError:
                pass
            return None
        try:
            idx = int(row)
        except (TypeError, ValueError):
            return None
        tablo.selection_set(row)
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
        if row and kolon in DUZENLENEBILIR_KOLONLAR:
            try:
                idx = int(row)
            except (TypeError, ValueError):
                return "break"
            tablo.selection_set(row)
            hucre_duzenle(dialog, idx=idx, kolon=kolon, event=event)
            return "break"
        return None

    def _f2(_event=None):
        if getattr(dialog, "_fatura_kilitli", False):
            return "break"
        if getattr(dialog, "_satir_hucre_editor", None) is not None:
            return "break"
        secim = tablo.selection()
        if not secim:
            return "break"
        try:
            idx = int(secim[0])
        except (TypeError, ValueError):
            return "break"
        kolon = ilk_duzenlenebilir_kolon(dialog, idx) or "miktar"
        focus_editable_cell(dialog, idx, kolon)
        return "break"

    def _enter_tablo(event=None):
        """Seçili satırda editör yoksa ilk alana gir; çift işleme yok."""
        if getattr(dialog, "_fatura_kilitli", False):
            return None
        if getattr(dialog, "_satir_hucre_editor", None) is not None:
            return None
        # İskonto modalı açıksa sızma
        try:
            for w in dialog.winfo_children():
                if isinstance(w, tk.Toplevel) and w.winfo_exists():
                    baslik = (w.title() or "").casefold()
                    if "iskonto" in baslik:
                        return "break"
        except tk.TclError:
            pass
        secim = tablo.selection()
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

    def _kapanista_temizle(_e=None):
        _tooltip_gizle()
        _editor_kapat(dialog)
        dialog._satir_hucre_etkilesim_kurulu = False

    tablo.bind("<Button-1>", _tek_tik, add="+")
    tablo.bind("<Double-1>", _cift_tik)
    tablo.bind("<F2>", _f2)
    tablo.bind("<Return>", _enter_tablo)
    tablo.bind("<KP_Enter>", _enter_tablo)
    tablo.bind("<Motion>", _motion)
    tablo.bind("<Leave>", _tooltip_gizle)
    dialog.bind("<F2>", _f2)
    dialog.bind("<Destroy>", _kapanista_temizle, add="+")
