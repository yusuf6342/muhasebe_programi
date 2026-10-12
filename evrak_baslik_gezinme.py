"""Evrak üst bilgi alanları — Enter ve yön oklarıyla alan gezinme (fatura, iade, sipariş, irsaliye, teklif).

Kurallar:
- Enter / KP_Enter: görsel sırayla sonraki alan; son alanda ürün giriş satırı (``son_hedef``).
  Shift+Enter: önceki alan.
- ↓ / ↑: sonraki / önceki alan — açılır listelerde de; liste Alt+↓ veya fareyle açılır.
- → imleç metnin sonundayken (veya tümü seçiliyken) sonraki, ← başındayken önceki alan.
  Seçim listesi (readonly) alanlarda ← / → her zaman alan değiştirir.
- Pasif (disabled), salt okunur (readonly Entry) ve görünmeyen alanlar atlanır.
- Alanın kendi bağı "break" dönerse (ör. Enter ile cari arama penceresi açılırsa) gezinme yapılmaz;
  takvim ve cari seçim pencereleri kendi tuşlarını kullanır.
"""

from __future__ import annotations

import tkinter as tk
from tkinter import ttk
from typing import Callable, Iterable

ETIKET = "EvrakBaslikGezinme"
_GIRDI_SINIFLARI = (ttk.Entry, tk.Entry, ttk.Spinbox, tk.Spinbox)


def _girdi_mi(w) -> bool:
    return isinstance(w, _GIRDI_SINIFLARI)  # ttk.Combobox ttk.Entry alt sınıfıdır


def _tum_girdiler(kap) -> list:
    sonuc, yigin = [], [kap]
    while yigin:
        w = yigin.pop()
        try:
            cocuklar = w.winfo_children()
        except tk.TclError:
            continue
        for c in cocuklar:
            if _girdi_mi(c):
                sonuc.append(c)
            else:
                yigin.append(c)
    return sonuc


def alan_kullanilabilir_mi(w) -> bool:
    try:
        if not w.winfo_exists() or not w.winfo_viewable():
            return False
        durum = str(w.cget("state"))
        if durum == "disabled":
            return False
        if durum == "readonly" and not isinstance(w, ttk.Combobox):
            return False
        if str(w.cget("takefocus")) == "0":
            return False
    except tk.TclError:
        return False
    return True


def _grup(w, kap):
    """Görsel grup: kap altındaki en yakın LabelFrame (panel); yoksa kap."""
    p = w.master
    while p is not None and p is not kap:
        if isinstance(p, (ttk.Labelframe, tk.LabelFrame)):
            return p
        p = p.master
    return kap


def gorsel_sirala(alanlar: Iterable, kap) -> list:
    """Panel panel (soldan sağa), panel içinde satır satır (üstten alta, soldan sağa)."""
    gruplar: dict = {}
    for w in alanlar:
        gruplar.setdefault(_grup(w, kap), []).append(w)

    def _konum(w):
        return w.winfo_rootx(), w.winfo_rooty() + w.winfo_height() // 2

    sirali = []
    for g in sorted(gruplar, key=lambda g: (g.winfo_rooty() // 40, g.winfo_rootx())):
        ogeler = sorted(gruplar[g], key=lambda w: _konum(w)[1])
        satirlar: list[list] = []
        bas_y = None
        for w in ogeler:
            y = _konum(w)[1]
            if bas_y is None or y - bas_y > max(8, w.winfo_height() // 2):
                satirlar.append([])
                bas_y = y
            satirlar[-1].append(w)
        for s in satirlar:
            sirali.extend(sorted(s, key=lambda w: _konum(w)[0]))
    return sirali


def baslik_alanlari(dialog) -> list:
    ayar = getattr(dialog, "_baslik_gezinme", None)
    if not ayar:
        return []
    haric = ayar["haric"]
    sonuc: list = []
    try:
        for kap in ayar["kaplar"]:
            adaylar = [w for w in _tum_girdiler(kap) if w not in haric and alan_kullanilabilir_mi(w)]
            sonuc.extend(gorsel_sirala(adaylar, kap))
    except tk.TclError:
        return []
    return sonuc


def alan_odakla(w) -> None:
    try:
        w.focus_set()
        if str(w.cget("state")) != "readonly":
            w.selection_range(0, "end")
            w.icursor("end")
    except tk.TclError:
        pass


def alana_gec(dialog, w, yon: int) -> bool:
    """Sonraki (yon=1) / önceki (yon=-1) alana geçer; sondan ileri ``son_hedef``. Geçtiyse True."""
    alanlar = baslik_alanlari(dialog)
    if w not in alanlar:
        return False
    i = alanlar.index(w) + (1 if yon > 0 else -1)
    if 0 <= i < len(alanlar):
        alan_odakla(alanlar[i])
        return True
    if yon > 0:
        son = (getattr(dialog, "_baslik_gezinme", None) or {}).get("son")
        if callable(son):
            son()
            return True
    return False


def _imlec_ucta(w, yon: int) -> bool:
    from satir_klavye import ok_ile_gec

    return ok_ile_gec(w, yon)


def _dialog_bul(w):
    try:
        top = w.winfo_toplevel()
    except tk.TclError:
        return None
    return top if getattr(top, "_baslik_gezinme", None) else None


def _olay(yon: int, *, ok: bool = False):
    def _isle(event):
        w = event.widget
        dialog = _dialog_bul(w)
        if dialog is None:
            return None
        if ok and not _imlec_ucta(w, yon):
            return None
        return "break" if alana_gec(dialog, w, yon) else None

    return _isle


def _liste_ac(event):
    w = event.widget
    if isinstance(w, ttk.Combobox):
        from satir_klavye import combobox_listesini_ac

        combobox_listesini_ac(w)
        return "break"
    return None


def _sinif_baglari(widget) -> None:
    if getattr(widget, "_baslik_gezinme_sinif", False):
        return
    for tus, fn in (
        ("<Return>", _olay(1)),
        ("<KP_Enter>", _olay(1)),
        ("<Shift-Return>", _olay(-1)),
        ("<Down>", _olay(1)),
        ("<Up>", _olay(-1)),
        ("<Right>", _olay(1, ok=True)),
        ("<Left>", _olay(-1, ok=True)),
        ("<Alt-Down>", _liste_ac),
    ):
        widget.bind_class(ETIKET, tus, fn)
    widget._baslik_gezinme_sinif = True


def etiketle(w) -> None:
    """Alanın kendi bağlarından sonra, sınıf (TEntry/TCombobox) bağlarından önce çalışır."""
    try:
        etiketler = list(w.bindtags())
    except tk.TclError:
        return
    if ETIKET in etiketler:
        return
    etiketler.insert(1, ETIKET)
    w.bindtags(tuple(etiketler))


def baslik_gezinme_kur(
    dialog,
    kap,
    *,
    son_hedef: Callable[[], None] | None = None,
    haric: Iterable = (),
) -> None:
    """``kap`` (veya sıralı kap listesi) içindeki giriş alanlarına Enter / ok gezinmesi bağlar.

    Tekrar çağrılabilir (sonradan eklenen alanlar da etiketlenir).
    """
    kaplar = [k for k in (kap if isinstance(kap, (list, tuple)) else [kap]) if k is not None]
    if not kaplar:
        return
    dialog._baslik_gezinme = {"kaplar": kaplar, "son": son_hedef, "haric": set(haric)}
    _sinif_baglari(dialog)
    for k in kaplar:
        for w in _tum_girdiler(k):
            etiketle(w)


def urun_girisine_git(dialog) -> None:
    """Son üst alandan sonra: tablodaki boş ürün giriş satırı."""
    from fatura_satir_hucre_edit import _urun_arama_odakla

    _urun_arama_odakla(dialog)
