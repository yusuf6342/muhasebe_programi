"""Ayarlar → Satış Ayarları → Fatura Varsayılanları."""

from __future__ import annotations

import tkinter as tk
from tkinter import messagebox, ttk

from database.fatura_kdv_service import (
    FIRMA_VARSAYILAN_KDV_SECENEKLERI,
    firma_varsayilan_kdv_ayarla,
    firma_varsayilan_kdv_orani,
    kdv_oran_metni,
)
from database.session_manager import oturum


def satis_ayarlari_goster(app) -> None:
    """Ana panel Ayarlar altından Satış Ayarları sayfası."""
    app._icerigi_temizle()
    kabuk = getattr(app, "_ana_panel_kabuk", None)
    if kabuk:
        kabuk.menu_secili_guncelle("ayarlar")
    ttk.Label(app.icerik, text="SATIŞ AYARLARI", style="Baslik.TLabel").pack(
        anchor="w", padx=20, pady=(16, 0)
    )
    ttk.Label(
        app.icerik,
        text="Firma bazlı fatura varsayılanları.",
        style="AnaPanelMuted.TLabel",
    ).pack(anchor="w", padx=20, pady=(8, 0))

    cerceve = ttk.LabelFrame(app.icerik, text="Fatura Varsayılanları", padding=16)
    cerceve.pack(fill="x", padx=20, pady=(24, 0))

    firma_ad = getattr(oturum, "firma_unvan", None) or getattr(oturum, "firma_kodu", None) or "—"
    ttk.Label(cerceve, text=f"Aktif firma: {firma_ad}").grid(
        row=0, column=0, columnspan=2, sticky="w", pady=(0, 12)
    )

    ttk.Label(cerceve, text="Varsayılan KDV Oranı:").grid(row=1, column=0, sticky="w", padx=(0, 12))
    degerler = [kdv_oran_metni(x) for x in FIRMA_VARSAYILAN_KDV_SECENEKLERI]
    mevcut = kdv_oran_metni(firma_varsayilan_kdv_orani())
    if mevcut not in degerler:
        degerler = degerler + [mevcut]
    kdv_var = tk.StringVar(value=mevcut)
    kdv_box = ttk.Combobox(
        cerceve,
        textvariable=kdv_var,
        values=degerler,
        state="readonly",
        width=8,
        justify="center",
    )
    kdv_box.grid(row=1, column=1, sticky="w")

    ttk.Label(
        cerceve,
        text="Yeni fatura satırına otomatik aktarılır. Stok kartında oran varsa stok önceliklidir.",
        wraplength=480,
    ).grid(row=2, column=0, columnspan=2, sticky="w", pady=(10, 0))

    def _kaydet():
        try:
            oran = firma_varsayilan_kdv_ayarla(kdv_var.get())
            messagebox.showinfo(
                "Satış Ayarları",
                f"Varsayılan KDV oranı {kdv_oran_metni(oran)} olarak kaydedildi.",
                parent=app,
            )
        except ValueError as hata:
            messagebox.showerror("Satış Ayarları", str(hata), parent=app)
        except Exception as hata:
            messagebox.showerror("Satış Ayarları", str(hata), parent=app)

    alt = ttk.Frame(app.icerik)
    alt.pack(fill="x", padx=20, pady=20)
    ttk.Button(alt, text="Kaydet", command=_kaydet).pack(side="left")
    ttk.Button(alt, text="Geri", command=lambda: app.sayfa_goster("ayarlar")).pack(
        side="left", padx=8
    )
