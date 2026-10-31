"""Treeview Excel ızgarası — yatay/dikey çizgiler yalnızca satır/sütun sınırlarında.

Çizgiler hücre içeriğinin (metin) üzerine binmez: yatay çizgi satırın
alt sınırına (bbox y+h) konur; dikey çizgi sütun kenarına. Overlay
Frame tıklamaları Treeview'a iletir.
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
        self._onceki_yscroll = None

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
            tablo_h = int(tree.winfo_height())
            tablo_w = int(tree.winfo_width())
        except tk.TclError:
            return
        if tablo_h < 8 or tablo_w < 8:
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
            try:
                fr.lift(tree)
            except tk.TclError:
                pass
            cizgiler.append(fr)
            return fr

        def yatay_sinir(x: int, y_abs: int, w: int) -> None:
            """Yatay çizgi — satırın alt kenar pikseli (metin payı rowheight ile sağlanır)."""
            if w <= 1:
                return
            # Treeview alanının dışına taşmasın
            if y_abs < ty or y_abs >= ty + tablo_h:
                return
            cizgi(height=1, width=w).place(x=tx + x, y=y_abs)

        def dikey_sinir(x_abs: int, y: int, h: int) -> None:
            if h <= 1:
                return
            cizgi(width=1, height=h).place(x=x_abs, y=ty + y)

        stil = ttk.Style(self.host)
        try:
            rh_stil = int(float(stil.lookup(self.style_name, "rowheight") or 28))
        except (TypeError, ValueError):
            rh_stil = 28

        children = list(tree.get_children())
        kolon_xw: list[tuple[int, int]] | None = None
        baslik_h: int | None = None
        satir_adim: int | None = None
        son_alt: int | None = None
        ilk_veri_y: int | None = None
        onceki_y: int | None = None

        for item in children:
            satir_y = None
            satir_h = None
            for sira, col in enumerate(dcols):
                box = tree.bbox(item, col)
                if not box:
                    continue
                x, y, w, h = (int(v) for v in box)
                if w <= 1 or h <= 1:
                    continue
                if ilk_veri_y is None:
                    ilk_veri_y = y
                    baslik_h = y
                if satir_y is None:
                    satir_y = y
                    # ttk bazen bbox yüksekliğini stil rowheight'ten kısa verir;
                    # kısa h ile çizilen yatay çizgi metnin ORTASINDAN geçer.
                    satir_h = max(h, rh_stil)
                if kolon_xw is None:
                    kolon_xw = []
                    for c2 in dcols:
                        b2 = tree.bbox(item, c2)
                        if b2:
                            kolon_xw.append((int(b2[0]), int(b2[2])))
                        else:
                            kolon_xw.append((0, max(20, int(tree.column(c2, "width") or 20))))
                # Dikey çizgi: stil satır yüksekliği (bbox h kısa olsa bile)
                rh_ciz = max(h, rh_stil)
                dikey_sinir(tx + x + w - 1, y, rh_ciz)
                if sira == 0:
                    dikey_sinir(tx + x, y, rh_ciz)
            if satir_y is not None and satir_h is not None:
                if onceki_y is not None:
                    adim = satir_y - onceki_y
                    if adim > 0:
                        satir_adim = adim
                onceki_y = satir_y
                # Yatay çizgi: stil/adım ile satır ALT sınırı (asla bbox-orta değil)
                if kolon_xw:
                    for x, w in kolon_xw:
                        if x + w < 0:
                            continue
                        # Hücre altına (y+h): son içerik pikseline binmez
                        yatay_sinir(x, ty + satir_y + satir_h, w)
                son_alt = satir_y + satir_h
                if satir_adim is None:
                    satir_adim = satir_h

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
            satir_adim = rh_stil

        # Başlık: üst + alt kenar, dikeyler (veri satırı x ile aynı kolon_xw)
        if baslik_h and baslik_h > 2 and kolon_xw:
            for sira, (x, w) in enumerate(kolon_xw):
                if x + w < 0:
                    continue
                yatay_sinir(x, ty, w)
                yatay_sinir(x, ty + baslik_h, w)
                dikey_sinir(tx + x + w - 1, 0, baslik_h)
                if sira == 0:
                    dikey_sinir(tx + x, 0, baslik_h)

        rh = max(satir_adim or rh_stil, 8)
        y = son_alt if son_alt is not None else (baslik_h or 26)
        guvenlik = 0
        while y + rh <= tablo_h and guvenlik < 80 and kolon_xw:
            for sira, (x, w) in enumerate(kolon_xw):
                if x + w < 0:
                    continue
                dikey_sinir(tx + x + w - 1, y, rh)
                if sira == 0:
                    dikey_sinir(tx + x, y, rh)
                yatay_sinir(x, ty + y + rh, w)
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
        mevcut.style_name = style_name
        mevcut.tiklama_sonrasi = tiklama_sonrasi
        mevcut.kur()
        return mevcut
    overlay = TreeviewExcelCizgi(
        host, tree, style_name=style_name, bag_adi=bag_adi, tiklama_sonrasi=tiklama_sonrasi
    )
    setattr(host, attr, overlay)
    overlay.kur()
    return overlay
