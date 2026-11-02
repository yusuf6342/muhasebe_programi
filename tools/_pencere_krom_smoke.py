"""Pencere OS krom (— □ ✕) smoke: transient temiz, resizable, iconify/zoomed."""
from __future__ import annotations

import os
import sys
import time
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ.setdefault(
    "MUHASEBE_DB_DIR",
    str(Path(os.environ.get("LOCALAPPDATA", "")) / "CinMuhasebeTest" / "data"),
)


def _krom_ok(win, ad: str) -> dict:
    import tkinter as tk

    win.update_idletasks()
    win.update()
    try:
        tr = str(win.wm_transient() or "")
    except tk.TclError:
        tr = "?"
    try:
        res = win.resizable()
    except tk.TclError:
        res = (None, None)
    # iconify / zoomed / restore
    onceki = win.geometry()
    win.iconify()
    win.update()
    time.sleep(0.05)
    win.deiconify()
    win.update()
    win.state("zoomed")
    win.update()
    zoomed = str(win.state()) == "zoomed"
    win.state("normal")
    try:
        win.geometry(onceki)
    except tk.TclError:
        pass
    win.update()
    ok = (not tr) and res == (True, True) and zoomed
    print(
        f"{ad}: transient={tr!r} resizable={res} zoomed_ok={zoomed} => {'OK' if ok else 'FAIL'}",
        flush=True,
    )
    return {"ad": ad, "ok": ok, "transient": tr, "resizable": res}


def main() -> None:
    import tkinter as tk

    from ui_pencere import pencere_os_krom_ac, belge_penceresini_hazirla

    patches = [
        patch("tkinter.messagebox.showerror", return_value="ok"),
        patch("tkinter.messagebox.showwarning", return_value="ok"),
        patch("tkinter.messagebox.showinfo", return_value="ok"),
        patch("tkinter.messagebox.askyesno", return_value=False),
        patch("tkinter.messagebox.askyesnocancel", return_value=False),
    ]
    for p in patches:
        p.start()

    root = tk.Tk()
    root.withdraw()
    sonuclar = []

    # 1) Ham Toplevel + transient sonra krom
    w = tk.Toplevel(root)
    w.title("test_krom")
    w.geometry("800x500")
    w.transient(root)
    w.grab_set()
    pencere_os_krom_ac(w)
    sonuclar.append(_krom_ok(w, "ham+krom"))
    w.destroy()

    # 2) belge_penceresini_hazirla (after krom)
    w2 = tk.Toplevel(root)
    w2.title("test_belge")
    belge_penceresini_hazirla(w2, maximize=False)
    w2.transient(root)
    w2.grab_set()
    root.update()
    time.sleep(0.12)  # after(80) krom
    root.update()
    sonuclar.append(_krom_ok(w2, "belge_hazirla"))
    w2.destroy()

    # 3) Alış fatura (ağır) — yalnız aç / krom / kapat
    try:
        from alis_ui import AlisFaturasiDialog

        t0 = time.perf_counter()
        dlg = AlisFaturasiDialog(root)
        dlg.update()
        time.sleep(0.12)
        dlg.update()
        sonuclar.append(_krom_ok(dlg, "alis_fatura"))
        print(f"alis_open_ms={(time.perf_counter() - t0) * 1000:.0f}", flush=True)
        dlg.destroy()
    except Exception as e:
        print("alis_fatura SKIP/FAIL", e, flush=True)
        sonuclar.append({"ad": "alis_fatura", "ok": False})

    # 4) Stok kartı
    try:
        from stok_ui import StokKartiDialog

        dlg = StokKartiDialog(root)
        dlg.update()
        time.sleep(0.05)
        sonuclar.append(_krom_ok(dlg, "stok_kart"))
        dlg.destroy()
    except Exception as e:
        print("stok_kart SKIP/FAIL", e, flush=True)
        sonuclar.append({"ad": "stok_kart", "ok": False})

    root.destroy()
    for p in patches:
        p.stop()

    fail = [s for s in sonuclar if not s.get("ok")]
    print("OZET", f"ok={len(sonuclar) - len(fail)}/{len(sonuclar)}", "fail", [f['ad'] for f in fail], flush=True)
    if fail:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
