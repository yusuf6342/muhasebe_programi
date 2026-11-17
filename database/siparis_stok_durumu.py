"""Alınan Sipariş — bilgilendirme amaçlı anlık stok durumu (Var / Kısmi / Yok).

Tüm depoların net lot bakiyesi (S) ile satır miktarının temel birim karşılığı (Q) karşılaştırılır.
Rezervasyon / bekleyen sipariş düşülmez. Stok veya cari hareket üretmez.
"""
from __future__ import annotations

from decimal import Decimal
from typing import Any

from sqlalchemy import func, select

from database.database import get_session
from database.models.stok import StokHareketi, StokKarti, StokLotu

DURUM_VAR = "Var"
DURUM_KISMI = "Kısmi"
DURUM_YOK = "Yok"
DURUM_BOS = ""

# Açık kırmızı satır zemini (ekran); PDF'ye taşınmaz
RENK_UYARI_BG = "#FFE4E4"
RENK_UYARI_FG = "#7F1D1D"


def _d(v) -> Decimal:
    try:
        return Decimal(str(v or 0))
    except Exception:
        return Decimal("0")


def durum_etiketi(s_temel: Decimal, q_temel: Decimal) -> str:
    """S = net fiili stok (temel birim), Q = satır ihtiyacı (temel birim)."""
    if q_temel is None or q_temel <= 0:
        return DURUM_BOS
    s = _d(s_temel)
    q = _d(q_temel)
    if s <= 0:
        return DURUM_YOK
    if s < q:
        return DURUM_KISMI
    return DURUM_VAR


def uyari_durumu_mu(durum: str | None) -> bool:
    return (durum or "") in (DURUM_KISMI, DURUM_YOK)


def net_lot_toplamlari(urun_kodlari: list[str] | tuple[str, ...] | set[str]) -> dict[str, Decimal]:
    """Ürün kodu → tüm depolardaki net lot kalan toplamı (tek sorgu).

    Lotu olmayan kartlar 0 döner. Aynı ürün birden fazla satırda olsa da stok
    bir kez toplanır (katlama yok).
    """
    kodlar = sorted({(k or "").strip() for k in (urun_kodlari or []) if (k or "").strip()})
    if not kodlar:
        return {}
    with get_session() as session:
        rows = session.execute(
            select(
                StokKarti.stok_kodu,
                func.coalesce(func.sum(StokLotu.kalan_miktar), 0),
            )
            .select_from(StokKarti)
            .outerjoin(StokLotu, StokLotu.stok_id == StokKarti.id)
            .where(StokKarti.stok_kodu.in_(kodlar))
            .group_by(StokKarti.stok_kodu)
        ).all()
        sonuc = {str(kod): _d(top) for kod, top in rows}
        for kod in kodlar:
            sonuc.setdefault(kod, Decimal("0"))
        return sonuc


def hareket_imza(urun_kodlari: list[str] | tuple[str, ...] | set[str]) -> tuple[int, str]:
    """İzlenen ürünler için hafif DB imzası: (max hareket id, net lot toplamı).

    Başka terminaldeki stok giriş/çıkışını görmek için paylaşılan DB okunur.
    """
    kodlar = sorted({(k or "").strip() for k in (urun_kodlari or []) if (k or "").strip()})
    if not kodlar:
        return (0, "0")
    with get_session() as session:
        ids = list(
            session.scalars(
                select(StokKarti.id).where(StokKarti.stok_kodu.in_(kodlar))
            ).all()
        )
        if not ids:
            return (0, "0")
        max_hid = session.scalar(
            select(func.coalesce(func.max(StokHareketi.id), 0)).where(
                StokHareketi.stok_id.in_(ids)
            )
        )
        net = session.scalar(
            select(func.coalesce(func.sum(StokLotu.kalan_miktar), 0)).where(
                StokLotu.stok_id.in_(ids)
            )
        )
        return (int(max_hid or 0), str(_d(net)))


def _temel_miktar_kart(veri: dict[str, Any], kart: Any | None) -> Decimal:
    from database.stok_service import StokService

    miktar = _d(veri.get("miktar"))
    if miktar <= 0:
        return Decimal("0")
    if kart is None:
        return miktar
    birim = (veri.get("birim") or getattr(kart, "birim", None) or "Adet").strip() or "Adet"
    try:
        carpan = StokService.birim_carpani_kesin(kart, birim)
    except Exception:
        carpan = Decimal("1")
    return (miktar * _d(carpan)).quantize(Decimal("0.000001"))


def satir_durumlari(
    satirlar: list[dict[str, Any]],
    *,
    stok_map: dict[str, Decimal] | None = None,
) -> list[str]:
    """Her satır için durum etiketi (aynı ürün stoku bir kez okunur, tek oturum)."""
    from sqlalchemy.orm import selectinload

    kodlar = sorted(
        {(v.get("urun_kodu") or "").strip() for v in (satirlar or []) if (v.get("urun_kodu") or "").strip()}
    )
    if not satirlar:
        return []
    with get_session() as session:
        kartlar = {
            k.stok_kodu: k
            for k in session.scalars(
                select(StokKarti)
                .where(StokKarti.stok_kodu.in_(kodlar))
                .options(selectinload(StokKarti.birimler))
            ).all()
        } if kodlar else {}
        if stok_map is not None:
            stoklar = stok_map
        elif kodlar:
            ids = [int(k.id) for k in kartlar.values()]
            stoklar = {kod: Decimal("0") for kod in kodlar}
            if ids:
                id_to_kod = {int(k.id): k.stok_kodu for k in kartlar.values()}
                for sid, top in session.execute(
                    select(StokLotu.stok_id, func.coalesce(func.sum(StokLotu.kalan_miktar), 0))
                    .where(StokLotu.stok_id.in_(ids))
                    .group_by(StokLotu.stok_id)
                ).all():
                    kod = id_to_kod.get(int(sid))
                    if kod:
                        stoklar[kod] = _d(top)
        else:
            stoklar = {}
        sonuc: list[str] = []
        for veri in satirlar:
            kod = (veri.get("urun_kodu") or "").strip()
            miktar = _d(veri.get("miktar"))
            if not kod or miktar <= 0:
                sonuc.append(DURUM_BOS)
                continue
            q = _temel_miktar_kart(veri, kartlar.get(kod))
            s = stoklar.get(kod, Decimal("0"))
            sonuc.append(durum_etiketi(s, q))
        return sonuc
