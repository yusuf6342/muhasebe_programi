"""Kart listelerini yeniden alınabilir Excel'e aktarma."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any, Iterable

from excel_aktarim.types import getir
from excel_aktarim.writer import SABLON_SURUM, excel_yaz


def _alan_deger(kart: Any, kod: str) -> Any:
    if isinstance(kart, dict):
        return kart.get(kod)
    return getattr(kart, kod, None)


def kartlari_excel_aktar(
    hedef: str | Path,
    *,
    tip_kod: str,
    kartlar: Iterable[Any],
    firma: str = "",
    donem: str = "",
    filtreler: str = "",
) -> Path:
    tip = getir(tip_kod)
    basliklar = [a.baslik for a in tip.alanlar]
    kodlar = [a.kod for a in tip.alanlar]
    tipler = []
    for a in tip.alanlar:
        k = a.kod.lower()
        if any(x in k for x in ("barkod", "kod", "vergi", "telefon", "iban", "tckn", "gsm")):
            tipler.append("kod")
        elif "tarih" in k:
            tipler.append("tarih")
        elif any(x in k for x in ("fiyat", "tutar", "bakiye", "limit")):
            tipler.append("para")
        elif any(x in k for x in ("oran", "kdv", "iskonto")):
            tipler.append("yuzde")
        else:
            tipler.append("metin")

    satirlar = []
    for kart in kartlar:
        satirlar.append([_alan_deger(kart, kod) for kod in kodlar])

    return excel_yaz(
        hedef,
        basliklar=basliklar,
        satirlar=satirlar,
        kolon_tipleri=tipler,
        anahtarlar=kodlar,
        amac="yeniden_al",
        sayfa_adi="Kartlar",
        meta={
            "sablon_surum": SABLON_SURUM,
            "sablon_turu": tip.kod,
            "firma": firma,
            "donem": donem,
            "filtreler": filtreler,
            "kayit_sayisi": len(satirlar),
            "hazirlama_zamani": datetime.now().strftime("%d.%m.%Y %H:%M:%S"),
            "aciklama": tip.ad,
        },
    )


def stok_kartlari_excel_aktar(hedef: str | Path, kartlar: Iterable[Any], **meta) -> Path:
    return kartlari_excel_aktar(hedef, tip_kod="stok_karti", kartlar=kartlar, **meta)


def musteri_kartlari_excel_aktar(hedef: str | Path, kartlar: Iterable[Any], **meta) -> Path:
    return kartlari_excel_aktar(hedef, tip_kod="musteri_cari", kartlar=kartlar, **meta)


def tedarikci_kartlari_excel_aktar(hedef: str | Path, kartlar: Iterable[Any], **meta) -> Path:
    return kartlari_excel_aktar(hedef, tip_kod="tedarikci_cari", kartlar=kartlar, **meta)
