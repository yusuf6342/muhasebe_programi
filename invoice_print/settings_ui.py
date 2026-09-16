"""Fatura Yazdırma Ayarları diyaloğu."""

from __future__ import annotations

import tkinter as tk
from tkinter import messagebox, ttk

from invoice_print.settings import (
    DEFAULT_SETTINGS,
    load_print_settings,
    reset_print_settings,
    save_print_settings,
)


class FaturaYazdirmaAyarlariDialog(tk.Toplevel):
    def __init__(self, parent):
        super().__init__(parent)
        self.title("Fatura Yazdırma Ayarları")
        self.geometry("460x560")
        self.transient(parent)
        self.grab_set()
        self.ayar = load_print_settings()
        self.degiskenler: dict[str, tk.Variable] = {}
        govde = ttk.Frame(self, padding=12)
        govde.pack(fill="both", expand=True)

        ttk.Label(govde, text="Şablon").grid(row=0, column=0, sticky="w", pady=4)
        self.sablon = ttk.Combobox(
            govde, values=("kurumsal", "sade", "dahili"), state="readonly", width=18
        )
        self.sablon.set(self.ayar.get("sablon_id") or "kurumsal")
        self.sablon.grid(row=0, column=1, sticky="w", pady=4)

        secenekler = [
            ("logo_goster", "Logo göster"),
            ("firma_bilgi_goster", "Firma bilgileri göster"),
            ("urun_kodu_goster", "Ürün kodu göster"),
            ("aciklama_goster", "Açıklama göster"),
            ("barkod_goster", "Barkod göster"),
            ("lot_goster", "Lot/seri göster"),
            ("kdv_dokum_goster", "KDV dökümü göster"),
            ("banka_goster", "Banka bilgileri göster"),
            ("imza_alani_goster", "İmza alanı göster"),
            ("kase_goster", "Kaşe/imza görseli göster"),
            ("yaziyla_toplam_goster", "Yazıyla toplam göster"),
            ("tahsil_kalan_goster", "Tahsil / kalan göster"),
            ("alt_bilgi_goster", "Alt bilgi göster"),
            ("taslak_filigran_goster", "Taslak filigranı göster"),
            ("ara_toplam_devri_goster", "Ara toplam devri göster"),
        ]
        for i, (anahtar, etiket) in enumerate(secenekler, start=1):
            var = tk.BooleanVar(value=bool(self.ayar.get(anahtar, True)))
            self.degiskenler[anahtar] = var
            ttk.Checkbutton(govde, text=etiket, variable=var).grid(
                row=i, column=0, columnspan=2, sticky="w", pady=2
            )

        alt = ttk.Frame(self, padding=10)
        alt.pack(fill="x")
        ttk.Button(alt, text="Varsayılana Dön", command=self._sifirla).pack(side="left")
        ttk.Button(alt, text="İptal", command=self.destroy).pack(side="right")
        ttk.Button(alt, text="Kaydet", command=self._kaydet).pack(side="right", padx=6)

    def _kaydet(self):
        yeni = dict(self.ayar)
        yeni["sablon_id"] = self.sablon.get() or "kurumsal"
        for k, var in self.degiskenler.items():
            yeni[k] = bool(var.get())
        for k, v in DEFAULT_SETTINGS.items():
            yeni.setdefault(k, v)
        save_print_settings(yeni)
        messagebox.showinfo("Ayarlar", "Yazdırma ayarları kaydedildi.", parent=self)
        self.destroy()

    def _sifirla(self):
        if not messagebox.askyesno("Ayarlar", "Varsayılanlara dönülsün mü?", parent=self):
            return
        self.ayar = reset_print_settings()
        self.sablon.set(self.ayar["sablon_id"])
        for k, var in self.degiskenler.items():
            var.set(bool(self.ayar.get(k, True)))
