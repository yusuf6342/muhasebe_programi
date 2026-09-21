"""Belge (fatura/sipariş/teklif/irsaliye) pencereleri — ekrana sığdırma ve popup ortalama.

Yalnızca yerleşim; hesaplama / iş mantığı yok.
Windows iş alanı (görev çubuğu hariç) dikkate alınır.
"""

from __future__ import annotations

import sys
import tkinter as tk
from typing import Any


def calisma_alani(pencere: tk.Misc | None = None) -> tuple[int, int, int, int]:
    """(x, y, genislik, yukseklik) — görev çubuğu dışı kullanılabilir alan."""
    if sys.platform == "win32":
        try:
            import ctypes
            from ctypes import wintypes

            class RECT(ctypes.Structure):
                _fields_ = [
                    ("left", wintypes.LONG),
                    ("top", wintypes.LONG),
                    ("right", wintypes.LONG),
                    ("bottom", wintypes.LONG),
                ]

            rect = RECT()
            SPI_GETWORKAREA = 0x0030
            if ctypes.windll.user32.SystemParametersInfoW(SPI_GETWORKAREA, 0, ctypes.byref(rect), 0):
                return (
                    int(rect.left),
                    int(rect.top),
                    int(rect.right - rect.left),
                    int(rect.bottom - rect.top),
                )
        except Exception:
            pass
    try:
        root = pencere or tk._default_root  # type: ignore[attr-defined]
        if root is not None:
            return (0, 0, int(root.winfo_screenwidth()), int(root.winfo_screenheight()))
    except Exception:
        pass
    return (0, 0, 1280, 720)


def belge_penceresini_hazirla(
    win: tk.Toplevel,
    *,
    min_genislik: int = 900,
    min_yukseklik: int = 520,
    varsayilan_genislik: int = 1200,
    varsayilan_yukseklik: int = 720,
    maximize: bool = True,
) -> dict[str, Any]:
    """Belge kartını iş alanına oturtur; görev çubuğunun altında kalmaz.

    - minsize, ekranın %85'ini aşmaz (küçük çözünürlük / yüksek DPI)
    - maximize=True → state('zoomed'); başarısızsa iş alanına geometry
    """
    try:
        win.update_idletasks()
    except tk.TclError:
        pass

    x, y, aw, ah = calisma_alani(win)
    # Min boyutları iş alanına göre sınırla (bileşenler bozulmasın ama sığsın)
    min_w = max(720, min(int(min_genislik), max(720, aw - 24)))
    min_h = max(480, min(int(min_yukseklik), max(480, ah - 24)))
    try:
        win.minsize(min_w, min_h)
    except tk.TclError:
        pass
    try:
        win.resizable(True, True)
    except tk.TclError:
        pass

    gw = min(max(int(varsayilan_genislik), min_w), aw)
    gh = min(max(int(varsayilan_yukseklik), min_h), ah)
    gx = x + max(0, (aw - gw) // 2)
    gy = y + max(0, (ah - gh) // 2)

    zoomed = False
    if maximize:
        try:
            # Önce iş alanına yerleştir, sonra maximize (Windows zoomed = work area)
            win.geometry(f"{gw}x{gh}+{gx}+{gy}")
            win.update_idletasks()
            win.state("zoomed")
            zoomed = True
        except tk.TclError:
            try:
                win.geometry(f"{aw}x{ah}+{x}+{y}")
            except tk.TclError:
                pass
    else:
        try:
            win.geometry(f"{gw}x{gh}+{gx}+{gy}")
        except tk.TclError:
            pass

    return {
        "work_x": x,
        "work_y": y,
        "work_w": aw,
        "work_h": ah,
        "min_w": min_w,
        "min_h": min_h,
        "zoomed": zoomed,
    }


def popup_ortala(
    popup: tk.Toplevel,
    parent: tk.Misc | None = None,
    *,
    genislik: int | None = None,
    yukseklik: int | None = None,
) -> None:
    """Popup'ı ana belge penceresine (veya ekrana) göre ortalar; iş alanı dışına taşmaz."""
    try:
        popup.update_idletasks()
    except tk.TclError:
        return

    w = genislik or popup.winfo_width()
    h = yukseklik or popup.winfo_height()
    if w < 40:
        w = max(popup.winfo_reqwidth(), genislik or 400)
    if h < 40:
        h = max(popup.winfo_reqheight(), yukseklik or 280)

    ax, ay, aw, ah = calisma_alani(popup)
    # Parent varsa onun ortasına koy
    px = py = pw = ph = None
    hedef = parent
    if hedef is None:
        try:
            hedef = popup.master
        except Exception:
            hedef = None
    if hedef is not None:
        try:
            # Üst Toplevel'e çık
            ust = hedef.winfo_toplevel()
            ust.update_idletasks()
            px, py = int(ust.winfo_rootx()), int(ust.winfo_rooty())
            pw, ph = int(ust.winfo_width()), int(ust.winfo_height())
        except tk.TclError:
            px = py = pw = ph = None

    if px is not None and pw and ph and pw > 50 and ph > 50:
        x = px + (pw - w) // 2
        y = py + (ph - h) // 2
    else:
        x = ax + (aw - w) // 2
        y = ay + (ah - h) // 2

    # İş alanı içine sıkıştır
    x = max(ax, min(x, ax + aw - w))
    y = max(ay, min(y, ay + ah - h))
    try:
        popup.geometry(f"{int(w)}x{int(h)}+{int(x)}+{int(y)}")
        popup.lift()
    except tk.TclError:
        pass


def sticky_footer_layout(
    win: tk.Toplevel,
    *,
    ust: tk.Misc | None = None,
    orta: tk.Misc | None = None,
    alt: tk.Misc | None = None,
) -> None:
    """Üst sabit / orta expand / alt sabit — yalnızca pack (grid ile karıştırma).

    Aynı Toplevel'de pack+grid karışımı Tk'te boş ekrana yol açar.
    Sıra: önce alt (bottom), sonra üst (top), sonra orta (expand).
    """

    def _unmanage(w):
        if w is None:
            return
        try:
            mgr = w.winfo_manager()
            if mgr == "pack":
                w.pack_forget()
            elif mgr == "place":
                w.place_forget()
            elif mgr == "grid":
                w.grid_forget()
        except tk.TclError:
            pass

    _unmanage(ust)
    _unmanage(orta)
    _unmanage(alt)

    try:
        if alt is not None:
            alt.pack(side="bottom", fill="x")
        if ust is not None:
            ust.pack(side="top", fill="x")
        if orta is not None:
            orta.pack(side="top", fill="both", expand=True)
    except tk.TclError:
        pass
