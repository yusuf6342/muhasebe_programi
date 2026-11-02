"""Fatura ızgara + OS krom smoke (TEST) — GUI kısa açılış."""
from __future__ import annotations

import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ.setdefault(
    "MUHASEBE_DB_DIR",
    str(Path(os.environ.get("LOCALAPPDATA", "")) / "CinMuhasebeTest" / "data"),
)


def main():
    import tkinter as tk

    from treeview_excel_cizgi import excel_cizgi_bagla
    from ui_pencere import pencere_os_krom_ac

    root = tk.Tk()
    root.withdraw()
    sonuclar = []

    # Izgara: boş alan canvas ile dolmalı
    win = tk.Toplevel(root)
    win.geometry("800x500")
    from tkinter import ttk

    fr = ttk.Frame(win)
    fr.pack(fill="both", expand=True)
    tree = ttk.Treeview(fr, columns=("a", "b"), show="headings", height=8)
    tree.heading("a", text="A")
    tree.heading("b", text="B")
    tree.column("a", width=200)
    tree.column("b", width=200)
    tree.pack(fill="both", expand=True)
    tree.insert("", "end", values=("1", "x"))
    ov = excel_cizgi_bagla(win, tree, style_name="Treeview", bag_adi="smoke")
    win.update_idletasks()
    win.update()
    time.sleep(0.15)
    ov.yenile()
    win.update()
    cv = getattr(ov, "_bos_canvas", None)
    ok_grid = cv is not None and cv.winfo_ismapped() and int(cv.winfo_height()) > 20
    h = int(cv.winfo_height()) if cv is not None else 0
    sonuclar.append(("Izgara boş alan canvas", "tamamlandı" if ok_grid else "başarısız", f"h={h}"))

    # Krom
    win2 = tk.Toplevel(root)
    win2.geometry("640x400")
    win2.transient(root)
    win2.grab_set()
    pencere_os_krom_ac(win2)
    win2.update()
    try:
        tr = str(win2.wm_transient() or "").strip()
    except tk.TclError:
        tr = "?"
    krom_ok = getattr(win2, "_os_krom_acik", False) and tr in ("", ".",)
    sonuclar.append(("OS krom transient temiz", "tamamlandı" if krom_ok else "başarısız", f"tr={tr!r}"))

    # iconify / deiconify grab
    win2.iconify()
    win2.update()
    time.sleep(0.05)
    win2.deiconify()
    win2.update()
    sonuclar.append(("iconify/deiconify", "tamamlandı", "smoke"))

    for ad, durum, not_ in sonuclar:
        print(f"{ad:36} {durum:12} {not_}")
    ozet = {}
    for _, d, _ in sonuclar:
        ozet[d] = ozet.get(d, 0) + 1
    print("OZET", ozet)
    try:
        win.destroy()
        win2.destroy()
        root.destroy()
    except Exception:
        pass
    return 0 if ozet.get("başarısız", 0) == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
