"""Fatura kartı — Dosyadan Aktar seçimi (kalem ekle / yeni taslak).

Talimat: dolu kartta varsayılan kalem ekleme; PDF/XML/Excel ortak giriş.
EXE güncellemesi bu modülde yapılmaz.
"""

from __future__ import annotations

import tkinter as tk
from tkinter import messagebox, ttk


def dosyadan_aktar_sec(parent, *, yon: str = "SATIS", kart_dolu: bool = False) -> str | None:
    """Döner: 'kalem_ekle' | 'yeni_taslak' | None (iptal)."""
    sonuc: dict[str, str | None] = {"secim": None}
    dlg = tk.Toplevel(parent)
    dlg.title("Dosyadan Aktar")
    dlg.transient(parent)
    dlg.grab_set()
    dlg.resizable(False, False)

    ttk.Label(
        dlg,
        text="Excel, PDF veya XML dosyasından ne yapılsın?",
        wraplength=420,
    ).pack(anchor="w", padx=16, pady=(16, 8))

    var = tk.StringVar(value="kalem_ekle" if kart_dolu else "yeni_taslak")
    ttk.Radiobutton(
        dlg,
        text="Bu faturaya kalem ekle (cari, tarih, depo ve para birimi korunur)",
        variable=var,
        value="kalem_ekle",
    ).pack(anchor="w", padx=16, pady=4)
    ttk.Radiobutton(
        dlg,
        text="Dosyadan yeni fatura taslağı oluştur (onay / kesinleştirme ayrı)",
        variable=var,
        value="yeni_taslak",
    ).pack(anchor="w", padx=16, pady=4)

    ttk.Label(
        dlg,
        text="Dosya okumak tek başına stok veya cari hareketi oluşturmaz.",
        foreground="#64748B",
    ).pack(anchor="w", padx=16, pady=(8, 4))

    alt = ttk.Frame(dlg)
    alt.pack(fill="x", padx=16, pady=16)

    def _iptal():
        sonuc["secim"] = None
        dlg.destroy()

    def _devam():
        sonuc["secim"] = var.get()
        dlg.destroy()

    ttk.Button(alt, text="İptal", command=_iptal).pack(side="right")
    ttk.Button(alt, text="Devam", command=_devam).pack(side="right", padx=(0, 8))

    dlg.protocol("WM_DELETE_WINDOW", _iptal)
    dlg.wait_window()
    return sonuc["secim"]


def _ana_uygulama(widget):
    w = widget
    while w is not None:
        if hasattr(w, "satis_fatura_belge_aktar") or hasattr(w, "alis_fatura_belge_aktar"):
            return w
        w = getattr(w, "master", None)
    return None


def fatura_dosyadan_aktar_calistir(parent, *, yon: str, kart_dolu: bool = False) -> None:
    """Seçime göre açık karta kalem ekler veya belge aktarım merkezini açar."""
    secim = dosyadan_aktar_sec(parent, yon=yon, kart_dolu=kart_dolu)
    if not secim:
        return

    yon_norm = "SATIS" if yon.upper().startswith("S") else "ALIS"

    if secim == "kalem_ekle":
        from pathlib import Path
        from tkinter import filedialog

        yol = filedialog.askopenfilename(
            parent=parent,
            title="Faturaya kalem ekle — dosya seçin",
            filetypes=[
                ("Desteklenen", "*.xlsx *.xlsm *.pdf *.xml"),
                ("Excel", "*.xlsx *.xlsm"),
                ("PDF", "*.pdf"),
                ("XML", "*.xml"),
                ("Tümü", "*.*"),
            ],
        )
        if not yol:
            return
        ext = Path(yol).suffix.lower()
        if ext in {".xlsx", ".xlsm"}:
            from fatura_kalem_excel_ekle import acik_faturaya_excel_kalem_ekle

            acik_faturaya_excel_kalem_ekle(parent, yol, yon=yon_norm)
            return
        messagebox.showinfo(
            "Kalem ekle",
            "PDF/XML için açık faturaya doğrudan kalem ekleme sonraki adımda tamamlanacak.\n"
            "Belge aktarım merkezinde taslak oluşturup eşleştirme akışını kullanın.\n"
            "Dosya okumak stok veya cari hareketi oluşturmaz.",
            parent=parent,
        )

    app = _ana_uygulama(parent)
    if app is None:
        messagebox.showerror("Dosyadan Aktar", "Ana uygulama penceresi bulunamadı.", parent=parent)
        return
    from fatura_belge_aktarim_ui import fatura_belge_aktarim_goster

    fatura_belge_aktarim_goster(app, yon=yon_norm, geri_fn=None)