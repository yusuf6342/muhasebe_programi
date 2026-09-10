"""EvoBulut açılış kayıtlarını geri al: EVB-ACL (cari) ve EVB-SG (stok)."""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import delete, select

from database.database import get_session
from database.models.cari import CariIslem, SatisHareketi
from database.models.stok import StokHareketi, StokLotu

# CLI bootstrap
from database.models.satis_siparisi import SatisSiparisi  # noqa: F401
from database.models.satis_irsaliyesi import SatisIrsaliyesi  # noqa: F401
from database.models.satis_faturasi import SatisFaturasi  # noqa: F401

CARI_ONEK = "EVB-ACL-"
STOK_ONEK = "EVB-SG-"


@dataclass
class TemizlikSonuc:
    cari_islem: int = 0
    cari_satis_hareket: int = 0
    stok_hareket: int = 0
    stok_lot: int = 0


def evb_acilislari_temizle() -> TemizlikSonuc:
    """EVB-ACL cari açılışları + EVB-SG stok GİRİŞ/lot kayıtlarını siler."""
    sonuc = TemizlikSonuc()
    with get_session() as session:
        # --- Cari ---
        cari_islemler = list(
            session.scalars(
                select(CariIslem).where(CariIslem.belge_no.like(f"{CARI_ONEK}%"))
            ).all()
        )
        belge_nos = {i.belge_no for i in cari_islemler if i.belge_no}
        sh_list = []
        if belge_nos:
            sh_list = list(
                session.scalars(
                    select(SatisHareketi).where(SatisHareketi.belge_no.in_(belge_nos))
                ).all()
            )
        # Ayrıca önek ile SatisHareketi (belge_no EVB-ACL)
        sh_extra = list(
            session.scalars(
                select(SatisHareketi).where(SatisHareketi.belge_no.like(f"{CARI_ONEK}%"))
            ).all()
        )
        sh_ids = {s.id for s in sh_list}
        for s in sh_extra:
            if s.id not in sh_ids:
                sh_list.append(s)
                sh_ids.add(s.id)

        for s in sh_list:
            session.delete(s)
            sonuc.cari_satis_hareket += 1
        for i in cari_islemler:
            session.delete(i)
            sonuc.cari_islem += 1

        # --- Stok (belge_no = lot_no = EVB-SG-…) ---
        hareketler = list(
            session.scalars(
                select(StokHareketi).where(StokHareketi.belge_no.like(f"{STOK_ONEK}%"))
            ).all()
        )
        lot_ids = {h.lot_id for h in hareketler if h.lot_id}
        for h in hareketler:
            session.delete(h)
            sonuc.stok_hareket += 1

        # Lotlar: EVB-SG lot_no veya yukarıdaki lot_id
        lotlar = list(
            session.scalars(
                select(StokLotu).where(StokLotu.lot_no.like(f"{STOK_ONEK}%"))
            ).all()
        )
        silinen_lot = set()
        for lot in lotlar:
            session.delete(lot)
            silinen_lot.add(lot.id)
            sonuc.stok_lot += 1
        for lid in lot_ids:
            if lid in silinen_lot:
                continue
            lot = session.get(StokLotu, lid)
            if lot is not None:
                session.delete(lot)
                sonuc.stok_lot += 1

        session.flush()
    return sonuc


if __name__ == "__main__":
    s = evb_acilislari_temizle()
    print(
        f"CariIslem={s.cari_islem} SatisHareketi={s.cari_satis_hareket} "
        f"StokHareketi={s.stok_hareket} StokLotu={s.stok_lot}"
    )
