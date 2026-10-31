"""Treeview Excel ızgarası — teklif ürün tablosuyla aynı yatay/dikey hücre çizgileri.

Boş görünür alana da çizgi çizer; gerçek belge satırı eklemez.
Frame overlay tıklamaları Treeview'a iletir (hücre düzenleme / sağ tık bozulmaz).
"""
from __future__ import annotations

import tkinter as tk
from tkinter import ttk
from typing import Any, Callable


CIZGI_RENK = "#BDBDBD"


class TreeviewExcelCizgi:
    """Bir Treeview için ince Excel ızgara overlay'i."""

    def __init__(
        self,
        host: tk.Misc,
        tree: ttk.Treeview,
        *,
        style_name: str = "Treeview",
        bag_adi: str = "excel",
        tiklama_sonrasi: Callable[[], None] | None = None,
    ):
        self.host = host
        self.tree = tree
        self.style_name = style_name
        self.bag_adi = bag_adi
        self.tiklama_sonrasi = tiklama_sonrasi
        self._cizgiler: list[tk.Frame] = []
        self._after: Any = None
        self._kurulu = False

    def temizle(self) -> None:
        for w in self._cizgiler:
            try:
                w.destroy()
            except tk.TclError:
                pass
        self._cizgiler = []
        if self._after is not None:
            try:
                self.host.after_cancel(self._after)
            except tk.TclError:
                pass
            self._after = None

    def kur(self) -> None:
        if self._kurulu:
            self.yenile()
            return
        tree = self.tree
        parent = tree.master
        dikey = None
        for w in parent.winfo_children():
            if not isinstance(w, ttk.Scrollbar):
                continue
            try:
                if str(w.cget("orient")) == "vertical":
                    dikey = w
                    break
            except tk.TclError:
                continue

        def planla(_event=None):
            if self._after is not None:
                try:
                    self.host.after_cancel(self._after)
                except tk.TclError:
                    pass
            self._after = self.host.after(15, self.yenile)

        def yset(*args):
            if dikey is not None:
                try:
                    dikey.set(*args)
                except tk.TclError:
                    pass
            planla()

        # Mevcut yscrollcommand'ı koru (yatay + dikey birlikte olabilir)
        onceki = tree.cget("yscrollcommand")
        self._onceki_yscroll = onceki

        def yscroll_birlesik(*args):
            if onceki:
                try:
                    tree.tk.call(onceki, *args)
                except tk.TclError:
                    try:
                        if callable(onceki):
                            onceki(*args)
                    except Exception:
                        pass
            elif dikey is not None:
                try:
                    dikey.set(*args)
                except tk.TclError:
                    pass
            planla()

        tree.configure(yscrollcommand=yscroll_birlesik)
        tree.bind("<Configure>", planla, add="+")
        tree.bind("<MouseWheel>", planla, add="+")
        tree.bind("<ButtonRelease-1>", planla, add="+")
        tree.bind("<<TreeviewSelect>>", planla, add="+")
        parent.bind("<Configure>", planla, add="+")
        self._kurulu = True
        planla()

    def yenile(self) -> None:
        self._after = None
        tree = self.tree
        parent = tree.master
        self.temizle()
        try:
            if not tree.winfo_ismapped():
                return
        except tk.TclError:
            return

        dcols = tree["displaycolumns"]
        if not dcols or dcols in ("#all", ("#all",)):
            dcols = tree["columns"]
        dcols = list(dcols or ())
        if not dcols:
            return
        try:
            tx, ty = tree.winfo_x(), tree.winfo_y()
        except tk.TclError:
            return

        cizgiler = self._cizgiler

        def _tiklama_aktar(event, cift=False):
            try:
                rx, ry = int(event.x_root), int(event.y_root)
                x = rx - tree.winfo_rootx()
                y = ry - tree.winfo_rooty()
            except (tk.TclError, TypeError, ValueError):
                return "break"
            row = tree.identify_row(y)
            if row:
                try:
                    tree.selection_set(row)
                    tree.focus(row)
                except tk.TclError:
                    pass
            try:
                # rootx/rooty şart — bind_class sağ tık / hücre identify bunları kullanır
                tree.event_generate(
                    "<Double-1>" if cift else "<Button-1>",
                    x=x,
                    y=y,
                    rootx=rx,
                    rooty=ry,
                )
            except tk.TclError:
                pass
            if self.tiklama_sonrasi is not None:
                try:
                    self.tiklama_sonrasi()
                except Exception:
                    pass
            return "break"

        def _sag_tik(event):
            try:
                rx, ry = int(event.x_root), int(event.y_root)
                x = rx - tree.winfo_rootx()
                y = ry - tree.winfo_rooty()
            except (tk.TclError, TypeError, ValueError):
                return "break"
            row = tree.identify_row(y)
            if row:
                try:
                    tree.selection_set(row)
                    tree.focus(row)
                except tk.TclError:
                    pass
            try:
                tree.event_generate("<Button-3>", x=x, y=y, rootx=rx, rooty=ry)
            except tk.TclError:
                pass
            return "break"

        def cizgi(**kwargs):
            fr = tk.Frame(parent, bg=CIZGI_RENK, highlightthickness=0, bd=0, **kwargs)
            fr.bind("<Button-1>", _tiklama_aktar)
            fr.bind("<Double-1>", lambda e: _tiklama_aktar(e, cift=True))
            fr.bind("<Button-3>", _sag_tik)
            cizgiler.append(fr)
            return fr

        def hucre(x, y, w, h, sol=False, ust=False):
            if w <= 1 or h <= 1:
                return
            if ust:
                cizgi(height=1, width=w).place(x=tx + x, y=ty + y)
            cizgi(height=1, width=w).place(x=tx + x, y=ty + y + h - 1)
            if sol:
                cizgi(width=1, height=h).place(x=tx + x, y=ty + y)
            cizgi(width=1, height=h).place(x=tx + x + w - 1, y=ty + y)

        stil = ttk.Style(self.host)
        try:
            rh = int(float(stil.lookup(self.style_name, "rowheight") or 28))
        except (TypeError, ValueError):
            rh = 28

        children = list(tree.get_children())
        kolon_xw = None
        baslik_h = None
        son_alt = None
        ilk_veri_y = None

        for item in children:
            for sira, col in enumerate(dcols):
                box = tree.bbox(item, col)
                if not box:
                    continue
                x, y, w, h = box
                if ilk_veri_y is None:
                    ilk_veri_y = y
                hucre(x, y, w, h, sol=(sira == 0), ust=(y == ilk_veri_y))
                if kolon_xw is None:
                    kolon_xw = []
                    for c2 in dcols:
                        b2 = tree.bbox(item, c2)
                        if b2:
                            kolon_xw.append((b2[0], b2[2]))
                    baslik_h = y
                    rh = h
                son_alt = y + h

        if kolon_xw is None:
            toplam_w = sum(max(20, int(tree.column(c, "width") or 20)) for c in dcols) or 1
            try:
                sol = float(tree.xview()[0]) * toplam_w
            except (tk.TclError, ValueError, IndexError):
                sol = 0.0
            kolon_xw = []
            cum = 0
            for col in dcols:
                w = max(20, int(tree.column(col, "width") or 20))
                kolon_xw.append((int(cum - sol), w))
                cum += w
            baslik_h = 26
            son_alt = baslik_h

        if baslik_h and baslik_h > 2 and kolon_xw:
            for sira, (x, w) in enumerate(kolon_xw):
                if x + w < 0:
                    continue
                hucre(x, 0, w, baslik_h, sol=(sira == 0), ust=True)

        try:
            tablo_h = tree.winfo_height()
        except tk.TclError:
            return
        y = son_alt if son_alt is not None else (baslik_h or 26)
        guvenlik = 0
        while y + rh <= tablo_h and guvenlik < 60 and kolon_xw:
            for sira, (x, w) in enumerate(kolon_xw):
                if x + w < 0:
                    continue
                hucre(x, y, w, rh, sol=(sira == 0), ust=False)
            y += rh
            guvenlik += 1


def excel_cizgi_bagla(
    host: tk.Misc,
    tree: ttk.Treeview,
    *,
    style_name: str = "Treeview",
    bag_adi: str = "excel",
    tiklama_sonrasi: Callable[[], None] | None = None,
) -> TreeviewExcelCizgi:
    """Host üzerinde tek örnek sakla ve kur."""
    attr = f"_{bag_adi}_excel_overlay"
    mevcut = getattr(host, attr, None)
    if isinstance(mevcut, TreeviewExcelCizgi) and mevcut.tree is tree:
        mevcut.kur()
        return mevcut
    overlay = TreeviewExcelCizgi(
        host, tree, style_name=style_name, bag_adi=bag_adi, tiklama_sonrasi=tiklama_sonrasi
    )
    setattr(host, attr, overlay)
    overlay.kur()
    return overlay
