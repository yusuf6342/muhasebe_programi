"""Stok Kartı — Yeni Depo diyaloğu (Depo ve Stok sekmesi)."""

from __future__ import annotations

import tkinter as tk
from tkinter import messagebox, ttk


class YeniDepoDialog(tk.Toplevel):
    def __init__(self, parent):
        super().__init__(parent)
        self.result = None
        self.title("Yeni Depo")
        self.resizable(False, False)
        self.transient(parent)
        self.grab_set()
        self.geometry("420x280")

        fr = ttk.Frame(self, padding=14)
        fr.pack(fill="both", expand=True)

        ttk.Label(fr, text="Depo Kodu *").grid(row=0, column=0, sticky="w", pady=4)
        self.kod = ttk.Entry(fr, width=28)
        self.kod.grid(row=0, column=1, sticky="ew", pady=4)

        ttk.Label(fr, text="Depo Adı *").grid(row=1, column=0, sticky="w", pady=4)
        self.ad = ttk.Entry(fr, width=28)
        self.ad.grid(row=1, column=1, sticky="ew", pady=4)

        ttk.Label(fr, text="Açıklama").grid(row=2, column=0, sticky="nw", pady=4)
        self.aciklama = tk.Text(fr, width=28, height=3)
        self.aciklama.grid(row=2, column=1, sticky="ew", pady=4)

        self.aktif = tk.BooleanVar(value=True)
        self.varsayilan = tk.BooleanVar(value=False)
        ttk.Checkbutton(fr, text="Aktif", variable=self.aktif).grid(
            row=3, column=1, sticky="w", pady=2
        )
        ttk.Checkbutton(fr, text="Varsayılan depo", variable=self.varsayilan).grid(
            row=4, column=1, sticky="w", pady=2
        )

        alt = ttk.Frame(fr)
        alt.grid(row=5, column=0, columnspan=2, sticky="e", pady=(12, 0))
        ttk.Button(alt, text="İptal", command=self.destroy).pack(side="right")
        self._kaydet_btn = ttk.Button(alt, text="Kaydet", command=self._kaydet)
        self._kaydet_btn.pack(side="right", padx=(0, 8))

        self.kod.focus_set()
        self.bind("<Return>", lambda _e: self._kaydet())
        self._kaydediliyor = False

    def _kaydet(self):
        if self._kaydediliyor:
            return
        self._kaydediliyor = True
        self._kaydet_btn.configure(state="disabled")
        try:
            from database.stok_service import StokService

            depo = StokService.depo_ekle(
                self.ad.get(),
                kod=self.kod.get(),
                aciklama=self.aciklama.get("1.0", "end").strip() or None,
                aktif=bool(self.aktif.get()),
                varsayilan=bool(self.varsayilan.get()),
            )
            self.result = depo
            self.destroy()
        except Exception as exc:
            messagebox.showerror("Depo", str(exc), parent=self)
            self._kaydediliyor = False
            self._kaydet_btn.configure(state="normal")
