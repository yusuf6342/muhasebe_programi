"""Cari defter satırına firma KK taksit planı meta / ayrıntı (tek ana satır + açılır taksitler)."""

from __future__ import annotations

from datetime import date
from decimal import Decimal, ROUND_HALF_UP
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import selectinload

from database.database import get_session
from database.models.finans import (
    KasaMakbuzu,
    KasaMakbuzSatiri,
    KrediKartiOdeme,
    KrediKartiOdemeTaksit,
)

SIFIR = Decimal("0.00")


def _d(val) -> Decimal:
    return Decimal(str(val or 0)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def _taksit_ozet(odeme: KrediKartiOdeme) -> dict[str, Any]:
    aktif = [
        t
        for t in (odeme.taksitler or [])
        if getattr(t, "aktif", True) is not False
        and (t.durum or "").upper() not in ("PLAN_IPTAL", "IADE")
    ]
    aktif.sort(key=lambda t: int(t.taksit_no))
    n = int(odeme.taksit_sayisi or len(aktif) or 1)
    satirlar = [
        {
            "taksit_no": int(t.taksit_no),
            "taksit_sayisi": n,
            "islem_tarihi": odeme.tarih,
            "vade_tarihi": t.vade_tarihi,
            "tutar": _d(t.tutar),
            "durum": t.durum,
            "ekstre_kesim_tarihi": getattr(t, "ekstre_kesim_tarihi", None),
            "banka_vade_tarihi": getattr(t, "banka_vade_tarihi", None),
        }
        for t in aktif
    ]
    return {
        "kk_odeme_id": int(odeme.id),
        "taksit_sayisi": n,
        "taksit_etiket": "Tek çekim" if n <= 1 else f"{n} taksit",
        "taksit_satirlari": satirlar,
        "genisletilebilir": n > 1,
        "belge_tipi": "kk_taksit",
    }


class CariKkTaksitDetayService:
    @staticmethod
    def hareketlere_kk_taksit_meta_ekle(kayitlar: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Ödeme makbuzu / KKO satırlarına taksit sayısı ve kk_odeme_id ekler."""
        if not kayitlar:
            return kayitlar
        omk_nolar: set[str] = set()
        kko_nolar: set[str] = set()
        for k in kayitlar:
            bn = (k.get("belge_no") or "").strip()
            if not bn:
                continue
            if bn.startswith(("OMK-", "TMK-")):
                omk_nolar.add(bn)
            elif bn.startswith("KKO-"):
                kko_nolar.add(bn)
            # Cari ödeme türü + KK açıklaması yedek
            elif (k.get("tur") or "") == "Ödeme" and "KREDİ KART" in (
                (k.get("aciklama") or "").upper()
            ):
                omk_nolar.add(bn)

        if not omk_nolar and not kko_nolar:
            for k in kayitlar:
                k.setdefault("taksit_sayisi", None)
                k.setdefault("taksit_etiket", "")
            return kayitlar

        harita: dict[str, dict[str, Any]] = {}
        with get_session() as s:
            if omk_nolar:
                makbuzlar = list(
                    s.scalars(
                        select(KasaMakbuzu)
                        .where(KasaMakbuzu.belge_no.in_(list(omk_nolar)))
                        .options(selectinload(KasaMakbuzu.satirlar))
                    ).all()
                )
                odeme_idler = [
                    int(sat.kk_odeme_id)
                    for m in makbuzlar
                    for sat in (m.satirlar or [])
                    if sat.kk_odeme_id
                ]
                odemeler = {}
                if odeme_idler:
                    for o in s.scalars(
                        select(KrediKartiOdeme)
                        .where(KrediKartiOdeme.id.in_(odeme_idler))
                        .options(selectinload(KrediKartiOdeme.taksitler))
                    ).all():
                        odemeler[int(o.id)] = o
                for m in makbuzlar:
                    for sat in m.satirlar or []:
                        if not sat.kk_odeme_id:
                            continue
                        o = odemeler.get(int(sat.kk_odeme_id))
                        if o is None:
                            continue
                        harita[(m.belge_no or "").strip()] = _taksit_ozet(o)
                        break
            if kko_nolar:
                for o in s.scalars(
                    select(KrediKartiOdeme)
                    .where(KrediKartiOdeme.belge_no.in_(list(kko_nolar)))
                    .options(selectinload(KrediKartiOdeme.taksitler))
                ).all():
                    harita[(o.belge_no or "").strip()] = _taksit_ozet(o)

        for k in kayitlar:
            bn = (k.get("belge_no") or "").strip()
            meta = harita.get(bn)
            if meta:
                k["kk_odeme_id"] = meta["kk_odeme_id"]
                k["taksit_sayisi"] = meta["taksit_sayisi"]
                k["taksit_etiket"] = meta["taksit_etiket"]
                k["taksit_satirlari"] = meta["taksit_satirlari"]
                if meta["genisletilebilir"]:
                    # Fatura meta'sı yoksa veya üzerine yazılabilir: KK taksit açılır
                    if not k.get("fatura_id"):
                        k["genisletilebilir"] = True
                        k["belge_tipi"] = "kk_taksit"
                    else:
                        # Hem fatura hem KK olmaz; fatura öncelikli
                        pass
                else:
                    k.setdefault("genisletilebilir", k.get("genisletilebilir", False))
            else:
                k.setdefault("taksit_sayisi", None)
                k.setdefault("taksit_etiket", "")
        return kayitlar

    @staticmethod
    def taksit_satirlari(kk_odeme_id: int) -> list[dict[str, Any]]:
        with get_session() as s:
            o = s.scalar(
                select(KrediKartiOdeme)
                .where(KrediKartiOdeme.id == int(kk_odeme_id))
                .options(selectinload(KrediKartiOdeme.taksitler))
            )
            if o is None:
                return []
            return list(_taksit_ozet(o)["taksit_satirlari"])
