"""Alınan Sipariş Kartı — kurumsal chrome (fatura_tema üzerine)."""

from __future__ import annotations

import tkinter as tk
from typing import Any

import fatura_tema as ft

ACIK_BG = ft.ACIK_BG
BEYAZ = ft.BEYAZ
LACIVERT = ft.LACIVERT

# Sipariş durum renkleri (mevcut operasyonel durumlar)
SIPARIS_DURUM_RENKLERI = {
    "TASLAK": ("#64748B", ft.BEYAZ),
    "AÇIK": (ft.BASARI, ft.BEYAZ),
    "ONAYLANDI": (ft.BASARI, ft.BEYAZ),
    "KISMİ İRSALİYELİ": (ft.UYARI, ft.BEYAZ),
    "İRSALİYELİ": (ft.LACIVERT_ORTA, ft.BEYAZ),
    "KISMİ FATURALI": ("#EA580C", ft.BEYAZ),
    "FATURALI": ("#0E7490", ft.BEYAZ),
    "TAMAMLANDI": (ft.LACIVERT, ft.BEYAZ),
    "İPTAL": (ft.IPTAL, ft.BEYAZ),
}

ONCELIK_RENKLERI = {
    "Normal": ("#E5E7EB", "#374151"),
    "Acil": (ft.UYARI, ft.BEYAZ),
    "Çok Acil": (ft.IPTAL, ft.BEYAZ),
}


def stil_uygula(root=None):
    # Durum paletini genişlet
    ft.DURUM_RENKLERI.update(SIPARIS_DURUM_RENKLERI)
    return ft.stil_uygula(root=root)


def siparis_ust_toolbar(
    parent,
    *,
    siparis_no: str = "Yeni",
    musteri_kisa: str = "",
    durum: str = "TASLAK",
) -> dict[str, Any]:
    ft.DURUM_RENKLERI.update(SIPARIS_DURUM_RENKLERI)
    refs = ft.ust_toolbar(
        parent,
        baslik="ALINAN SİPARİŞ",
        fatura_no=siparis_no or "Yeni",
        musteri_kisa=musteri_kisa,
        durum=durum,
    )
    if refs.get("rozet"):
        ft.rozet_guncelle(refs["rozet"], durum)
    return refs


def siparis_alt_ozet(parent) -> dict[str, Any]:
    """Alınan sipariş alt özeti — Fiyat Analiz / Çalışma paneli yok (yalnız Notlar + toplamlar)."""
    refs = ft.alt_ozet_cubugu(parent)
    analiz = refs.get("analiz")
    if analiz is not None:
        try:
            analiz.destroy()
        except tk.TclError:
            pass
        refs["analiz"] = None
        refs["islem"] = None

    kart = refs.get("kart")
    sol = refs.get("sol")
    sag = refs.get("sag")
    if kart is not None and sol is not None and sag is not None:
        try:
            kart.columnconfigure(0, weight=1, minsize=220)
            kart.columnconfigure(1, weight=0)
            kart.columnconfigure(2, weight=0)
            sol.grid(row=0, column=0, sticky="nsew", padx=(0, 10))
            sag.grid(row=0, column=1, sticky="ne")
        except tk.TclError:
            pass
        for w in sol.winfo_children():
            if isinstance(w, tk.Text):
                try:
                    w.configure(width=42, height=6)
                    w.pack(fill="both", expand=True, pady=(2, 0), anchor="w")
                except tk.TclError:
                    pass

    # İndirim / Masraf / döviz / uzlaşılan ipucu — siparişte gizle
    degerler = refs.get("degerler") or {}
    for anahtar in ("indirim", "indirim_oran", "masraf", "masraf_oran", "doviz"):
        w = degerler.get(anahtar)
        if w is None:
            continue
        try:
            # Etiket + değer satırını gizle (grid_remove)
            row = int(w.grid_info().get("row") or 0)
            for cocuk in sag.grid_slaves(row=row) if sag is not None else []:
                try:
                    cocuk.grid_remove()
                except tk.TclError:
                    pass
        except (tk.TclError, ValueError, TypeError):
            pass
    if sag is not None:
        for cocuk in sag.winfo_children():
            try:
                if isinstance(cocuk, tk.Label) and "Uzlaşılan" in (cocuk.cget("text") or ""):
                    cocuk.grid_remove()
            except tk.TclError:
                pass
    return refs


def tk_buton(parent, metin, komut, *, rol="kaydet", state="normal", **kwargs):
    return ft.tk_buton(parent, metin, komut, rol=rol, state=state, **kwargs)
