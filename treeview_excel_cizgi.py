"""Treeview Excel ızgarası — yatay/dikey çizgiler yalnızca satır/sütun sınırlarında.

Çizgiler Treeview'un kendi koordinat sisteminde (bbox ile aynı) place edilir;
tree.master + winfo_x/y ofseti kullanılmaz (padding/bordermode sapması olmaz).
Yatay çizgi satır alt sınırında; dikey çizgi sütun kenarında. Overlay tıklamaları
Treeview'a iletilir; metin etiketleri yenile_sonrasi ile üstte kalır.
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
        yenile_sonrasi: Callable[[], None] | None = None,
    ):
        self.host = host
        self.tree = tree
        self.style_name = style_name
        self.bag_adi = bag_adi
        self.tiklama_sonrasi = tiklama_sonrasi
        self.yenile_sonrasi = yenile_sonrasi
        self._cizgiler: list[tk.Frame] = []
        self._after: Any = None
        self._kurulu = False
        self._onceki_yscroll = None
        self._onceki_xscroll = None
        self._yukleme_bekliyor = False

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
        yatay_sb = None
        for w in parent.winfo_children():
            if not isinstance(w, ttk.Scrollbar):
                continue
            try:
                orient = str(w.cget("orient"))
            except tk.TclError:
                continue
            if orient == "vertical" and dikey is None:
                dikey = w
            elif orient == "horizontal" and yatay_sb is None:
                yatay_sb = w

        def planla(_event=None):
            # Hücre editörü / fatura açılışı sırasında çizgi yenilemesi UI'yi kilitlemesin
            host = self.host
            if getattr(host, "_satir_editor_aciliyor", False):
                return
            if getattr(host, "_fatura_yukleniyor", False):
                self._yukleme_bekliyor = True
                return
            ed = getattr(host, "_satir_hucre_editor", None)
            if ed is not None:
                try:
                    if ed.winfo_exists():
                        return
                except tk.TclError:
                    pass
            if self._after is not None:
                try:
                    self.host.after_cancel(self._after)
                except tk.TclError:
                    pass
            # Configure fırtınasını tek yenilemede birleştir (15 ms yetmiyordu)
            self._after = self.host.after(50, self.yenile)

        onceki_y = tree.cget("yscrollcommand")
        onceki_x = tree.cget("xscrollcommand")
        self._onceki_yscroll = onceki_y
        self._onceki_xscroll = onceki_x

        def _scroll_cagir(onceki, sb, *args):
            if onceki:
                try:
                    tree.tk.call(onceki, *args)
                    return
                except tk.TclError:
                    try:
                        if callable(onceki):
                            onceki(*args)
                            return
                    except Exception:
                        pass
            if sb is not None:
                try:
                    sb.set(*args)
                except tk.TclError:
                    pass

        def yscroll_birlesik(*args):
            _scroll_cagir(onceki_y, dikey, *args)
            planla()

        def xscroll_birlesik(*args):
            _scroll_cagir(onceki_x, yatay_sb, *args)
            planla()

        tree.configure(yscrollcommand=yscroll_birlesik, xscrollcommand=xscroll_birlesik)
        tree.bind("<Configure>", planla, add="+")
        tree.bind("<MouseWheel>", planla, add="+")
        tree.bind("<Shift-MouseWheel>", planla, add="+")
        tree.bind("<ButtonRelease-1>", planla, add="+")
        tree.bind("<<TreeviewSelect>>", planla, add="+")
        parent.bind("<Configure>", planla, add="+")
        self._kurulu = True
        planla()

    def _stil_rowheight(self) -> int:
        stil = ttk.Style(self.host)
        try:
            return max(8, int(float(stil.lookup(self.style_name, "rowheight") or 28)))
        except (TypeError, ValueError):
            return 28

    def _baslik_yuksekligi(self, tablo_h: int, dcols: list[str]) -> int:
        tree = self.tree
        children = list(tree.get_children())
        for item in children:
            for col in dcols:
                try:
                    box = tree.bbox(item, col)
                except tk.TclError:
                    box = None
                if box:
                    y = int(box[1])
                    if y > 2:
                        return y
                    break

        son_baslik = 0
        ust = min(max(8, tablo_h), 160)
        for y in range(0, ust):
            try:
                bolge = tree.identify_region(4, y)
            except tk.TclError:
                continue
            if bolge == "heading":
                son_baslik = y
            elif son_baslik > 0 and bolge in ("cell", "tree", "nothing"):
                return son_baslik + 1
        if son_baslik > 0:
            return son_baslik + 1
        return max(18, int(round(self._stil_rowheight() * 0.9)))

    def _kolon_kenarlari(
        self, dcols: list[str], children: list[str]
    ) -> list[tuple[int, int]]:
        tree = self.tree
        for item in children:
            kenarlar: list[tuple[int, int]] = []
            eksik = False
            for col in dcols:
                try:
                    box = tree.bbox(item, col)
                except tk.TclError:
                    box = None
                if box and int(box[2]) > 1:
                    kenarlar.append((int(box[0]), int(box[2])))
                else:
                    eksik = True
                    break
            if not eksik and kenarlar:
                return kenarlar

        toplam_w = sum(max(20, int(tree.column(c, "width") or 20)) for c in dcols) or 1
        try:
            sol = float(tree.xview()[0]) * toplam_w
        except (tk.TclError, ValueError, IndexError):
            sol = 0.0
        kenarlar = []
        cum = 0
        for col in dcols:
            w = max(20, int(tree.column(col, "width") or 20))
            kenarlar.append((int(cum - sol), w))
            cum += w
        return kenarlar

    def yukleme_bitince_yenile(self) -> None:
        """Fatura açılışı bittikten sonra ertelenmiş çizgi yenilemesini çalıştır."""
        self._yukleme_bekliyor = False
        if self._after is not None:
            try:
                self.host.after_cancel(self._after)
            except tk.TclError:
                pass
        self._after = self.host.after(30, self.yenile)

    def yenile(self) -> None:
        self._after = None
        tree = self.tree
        host = self.host
        if getattr(host, "_fatura_yukleniyor", False):
            self._yukleme_bekliyor = True
            return
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
            tablo_h = int(tree.winfo_height())
            tablo_w = int(tree.winfo_width())
        except tk.TclError:
            return
        if tablo_h < 8 or tablo_w < 8:
            return

        havuz = self._cizgiler
        self._cizgiler = []
        kullanilan = 0

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

        def cizgi() -> tk.Frame:
            nonlocal kullanilan
            if kullanilan < len(havuz):
                fr = havuz[kullanilan]
            else:
                # Doğrudan Treeview üzerinde: bbox ile aynı koordinat sistemi
                fr = tk.Frame(tree, bg=CIZGI_RENK, highlightthickness=0, bd=0)
                fr.bind("<Button-1>", _tiklama_aktar)
                fr.bind("<Double-1>", lambda e: _tiklama_aktar(e, cift=True))
                fr.bind("<Button-3>", _sag_tik)
            kullanilan += 1
            self._cizgiler.append(fr)
            return fr

        def yatay_sinir(x: int, y_tree: int, w: int) -> None:
            """y_tree: Treeview içi Y (bbox ile aynı)."""
            if w <= 1:
                return
            if y_tree < 0 or y_tree >= tablo_h:
                return
            # bordermode=ignore: tree iç kenar boşluğu tekrar eklenmez
            cizgi().place(
                x=x, y=y_tree, width=max(1, w), height=1, bordermode="ignore"
            )

        def dikey_sinir(x_tree: int, y_tree: int, h: int) -> None:
            if h <= 1:
                return
            if x_tree < -2 or x_tree >= tablo_w + 2:
                return
            cizgi().place(
                x=x_tree, y=y_tree, width=1, height=max(1, h), bordermode="ignore"
            )

        rh_stil = self._stil_rowheight()
        children = list(tree.get_children())
        baslik_h = self._baslik_yuksekligi(tablo_h, dcols)
        kolon_xw = self._kolon_kenarlari(dcols, children)

        # Satır bantları: bbox üst + gerçek alt (sonraki satır üstü veya y+h)
        satir_bantlari: list[tuple[int, int, int]] = []  # ust, alt, bbox_h
        for item in children:
            ustler: list[int] = []
            bbox_hs: list[int] = []
            for col in dcols:
                try:
                    box = tree.bbox(item, col)
                except tk.TclError:
                    box = None
                if not box:
                    continue
                _x, y, _w, h = (int(v) for v in box)
                if h <= 1:
                    continue
                ustler.append(y)
                bbox_hs.append(h)
            if not ustler:
                continue
            ust = min(ustler)
            bbox_h = max(bbox_hs) if bbox_hs else rh_stil
            # max(h, rh_stil) ile altı şişirme: çizgiyi sonraki satıra taşıyabilir — kullanma
            satir_bantlari.append((ust, ust + bbox_h, bbox_h))

        for i in range(len(satir_bantlari)):
            ust, alt, bh = satir_bantlari[i]
            if i + 1 < len(satir_bantlari):
                sonraki_ust = satir_bantlari[i + 1][0]
                if sonraki_ust > ust:
                    satir_bantlari[i] = (ust, sonraki_ust, bh)

        # Başlık
        if baslik_h > 2 and kolon_xw:
            for sira, (x, w) in enumerate(kolon_xw):
                if x + w < 0:
                    continue
                yatay_sinir(x, 0, w)
                yatay_sinir(x, baslik_h, w)
                dikey_sinir(x + w - 1, 0, baslik_h)
                if sira == 0:
                    dikey_sinir(x, 0, baslik_h)

        # Veri satırları
        for ust, alt, _bh in satir_bantlari:
            h_band = max(1, alt - ust)
            for sira, (x, w) in enumerate(kolon_xw):
                if x + w < 0:
                    continue
                dikey_sinir(x + w - 1, ust, h_band)
                if sira == 0:
                    dikey_sinir(x, ust, h_band)
                yatay_sinir(x, alt, w)

        # Boş alan
        if satir_bantlari:
            y = satir_bantlari[-1][1]
            if len(satir_bantlari) >= 2:
                rh = max(8, satir_bantlari[-1][0] - satir_bantlari[-2][0])
            else:
                rh = max(8, satir_bantlari[-1][2], rh_stil)
        else:
            y = baslik_h
            rh = rh_stil

        # Boş alan: tüm yüksekliği doldurmak yüzlerce Frame yaratıyordu; birkaç satır yeter
        guvenlik = 0
        max_bos = 6
        while y + rh <= tablo_h and guvenlik < max_bos and kolon_xw:
            for sira, (x, w) in enumerate(kolon_xw):
                if x + w < 0:
                    continue
                dikey_sinir(x + w - 1, y, rh)
                if sira == 0:
                    dikey_sinir(x, y, rh)
                yatay_sinir(x, y + rh, w)
            y += rh
            guvenlik += 1

        # Kullanılmayan havuz çerçevelerini kaldır
        for fr in havuz[kullanilan:]:
            try:
                fr.destroy()
            except tk.TclError:
                pass

        # Çizgiler Treeview seçim boyasının üstünde kalsın; vurgulu/edit
        # etiketleri yenile_sonrasi ile çizgilerin üstüne alınır.
        for fr in self._cizgiler:
            try:
                fr.lift()
            except tk.TclError:
                pass

        if self.yenile_sonrasi is not None:
            try:
                self.yenile_sonrasi()
            except Exception:
                pass

        # Açık hücre editörü çizgi/overlay yenilemesinden sonra üstte kalsın
        ed = getattr(self.host, "_satir_hucre_editor", None)
        if ed is not None:
            try:
                if ed.winfo_ismapped():
                    ed.lift()
            except tk.TclError:
                pass


def excel_cizgi_bagla(
    host: tk.Misc,
    tree: ttk.Treeview,
    *,
    style_name: str = "Treeview",
    bag_adi: str = "excel",
    tiklama_sonrasi: Callable[[], None] | None = None,
    yenile_sonrasi: Callable[[], None] | None = None,
) -> TreeviewExcelCizgi:
    """Host üzerinde tek örnek sakla ve kur."""
    attr = f"_{bag_adi}_excel_overlay"
    mevcut = getattr(host, attr, None)
    if isinstance(mevcut, TreeviewExcelCizgi) and mevcut.tree is tree:
        mevcut.style_name = style_name
        mevcut.tiklama_sonrasi = tiklama_sonrasi
        if yenile_sonrasi is not None:
            mevcut.yenile_sonrasi = yenile_sonrasi
        mevcut.kur()
        return mevcut
    overlay = TreeviewExcelCizgi(
        host,
        tree,
        style_name=style_name,
        bag_adi=bag_adi,
        tiklama_sonrasi=tiklama_sonrasi,
        yenile_sonrasi=yenile_sonrasi,
    )
    setattr(host, attr, overlay)
    overlay.kur()
    return overlay
