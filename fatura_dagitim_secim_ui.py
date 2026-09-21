"""Dağıtım aktifken satır değişince kullanıcı seçimi (satış/alış ortak)."""

from __future__ import annotations

import tkinter as tk
from decimal import Decimal
from tkinter import ttk

from database.fatura_genel_toplam_service import (
    SECIM_DAGITIM_IPTAL,
    SECIM_HEDEF_KORU,
    SECIM_HEDEFE_EKLE,
)


def _para(tutar: Decimal) -> str:
    d = Decimal(str(tutar or 0))
    return f"{d:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".") + " TL"


def dagitim_satir_degisikligi_sec(
    parent,
    *,
    hedef_net: Decimal,
    satir_toplam: Decimal,
    calculated_gross: Decimal,
) -> str | None:
    """Üç seçenekli diyalog. Dönüş: SECIM_* veya None (vazgeç)."""
    dlg = tk.Toplevel(parent)
    dlg.title("Fatura geneli dağıtım")
    dlg.transient(parent)
    dlg.grab_set()
    dlg.resizable(False, False)

    delta = satir_toplam - hedef_net
    ttk.Label(
        dlg,
        text=(
            "Satırlar değişti; fatura geneli hedef toplam ile satır toplamı uyuşmuyor.\n\n"
            f"Hedef Net: {_para(hedef_net)}\n"
            f"Güncel satır toplamı: {_para(satir_toplam)}\n"
            f"Fark: {_para(delta)}\n"
            f"Güncel Brüt (hesaplanan): {_para(calculated_gross)}\n\n"
            "Ne yapmak istersiniz?"
        ),
        padding=14,
        justify="left",
    ).pack(anchor="w")

    sonuc: dict[str, str | None] = {"secim": None}

    def _sec(s: str):
        sonuc["secim"] = s
        dlg.destroy()

    alt = ttk.Frame(dlg, padding=(14, 0, 14, 14))
    alt.pack(fill="x")
    ttk.Button(
        alt,
        text="Mevcut hedef toplamı koru ve fiyatları yeniden dağıt",
        command=lambda: _sec(SECIM_HEDEF_KORU),
    ).pack(fill="x", pady=3)
    ttk.Button(
        alt,
        text="Yeni satır tutarını hedef toplama ekle",
        command=lambda: _sec(SECIM_HEDEFE_EKLE),
    ).pack(fill="x", pady=3)
    ttk.Button(
        alt,
        text="Fatura geneli dağıtımı iptal et ve normal hesapla",
        command=lambda: _sec(SECIM_DAGITIM_IPTAL),
    ).pack(fill="x", pady=3)
    ttk.Button(alt, text="Vazgeç", command=lambda: _sec("vazgec")).pack(fill="x", pady=(8, 0))

    dlg.protocol("WM_DELETE_WINDOW", lambda: _sec("vazgec"))
    try:
        dlg.wait_window()
    except tk.TclError:
        return None
    secim = sonuc["secim"]
    if secim in (None, "vazgec"):
        return None
    return secim
