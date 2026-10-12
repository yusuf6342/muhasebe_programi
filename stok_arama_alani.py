"""Stok kartı adı kutusunda yazarken açılan stok listesi.

Arama ``SearchService.search_stocks`` ile yapılır: çok kelimeli, Türkçe harf ve büyük/küçük
harf duyarsız; ad, kod ve barkodda arar.
"""

from __future__ import annotations

from typing import Any

from cari_arama_alani import MIN_HARF, CariAramaAlani

AZAMI_STOK = 50


def stok_ara(metin: str, limit: int = AZAMI_STOK) -> list[Any]:
    from database.search_service import SearchService, tokenize_query

    if len((metin or "").strip()) < MIN_HARF or not tokenize_query(metin):
        return []
    return list(SearchService.search_stocks(metin, limit=limit).get("urunler") or [])


class StokAramaAlani(CariAramaAlani):
    """Yeni ürün adı yazılırken Enter mevcut bir kartı açmasın diye ilk sonuç seçili gelmez."""

    KOLONLAR = (
        ("kod", "Stok Kodu", 120, False),
        ("ad", "Stok Adı", 340, True),
        ("birim", "Birim", 70, False),
    )
    ILK_SONUC_SECILI = False

    def __init__(self, dialog, entry, *, on_secim, secili_ad, arka_plan: bool = True):
        super().__init__(
            dialog,
            entry,
            cari_turu="",
            on_secim=on_secim,
            on_temizle=lambda: None,
            secili_ad=secili_ad,
            kayit_adi="Stok",
            arka_plan=arka_plan,
        )

    def _sorgu(self, metin: str) -> list[Any]:
        return stok_ara(metin)

    def _satir(self, kayit) -> tuple:
        return (
            getattr(kayit, "stok_kodu", "") or "",
            getattr(kayit, "stok_adi", "") or "",
            getattr(kayit, "birim", "") or "",
        )
