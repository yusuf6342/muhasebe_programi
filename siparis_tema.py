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
    return ft.alt_ozet_cubugu(parent)


def tk_buton(parent, metin, komut, *, rol="kaydet", state="normal", **kwargs):
    return ft.tk_buton(parent, metin, komut, rol=rol, state=state, **kwargs)
