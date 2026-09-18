"""Tedarikçi fiyat listesi CRUD."""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Any

from sqlalchemy import or_, select
from sqlalchemy.orm import selectinload

from database.access import yazma_zorunlu
from database.database import get_session
from database.models.tedarikci_fiyat import TedarikciFiyat
from database.satis_siparisi_service import decimal
from database.satin_alma_hub_service import SatinAlmaHubService


class TedarikciFiyatService:
    @staticmethod
    def schema_hazirla() -> None:
        SatinAlmaHubService.schema_hazirla()

    @staticmethod
    def listele(cari_id: int | None = None, arama: str = "") -> list[dict[str, Any]]:
        TedarikciFiyatService.schema_hazirla()
        with get_session() as session:
            q = select(TedarikciFiyat).options(selectinload(TedarikciFiyat.cari)).where(
                TedarikciFiyat.aktif.is_(True)
            )
            if cari_id:
                q = q.where(TedarikciFiyat.cari_id == int(cari_id))
            if arama.strip():
                ifade = f"%{arama.strip()}%"
                q = q.where(
                    or_(
                        TedarikciFiyat.urun_kodu.ilike(ifade),
                        TedarikciFiyat.urun_adi.ilike(ifade),
                    )
                )
            q = q.order_by(TedarikciFiyat.urun_kodu, TedarikciFiyat.gecerlilik_baslangic.desc())
            return [
                {
                    "id": r.id,
                    "cari_id": r.cari_id,
                    "tedarikci": r.cari.unvan if r.cari else "",
                    "urun_kodu": r.urun_kodu,
                    "urun_adi": r.urun_adi,
                    "birim": r.birim,
                    "birim_fiyat": r.birim_fiyat,
                    "iskonto_orani": r.iskonto_orani,
                    "para_birimi": r.para_birimi,
                    "baslangic": r.gecerlilik_baslangic,
                    "bitis": r.gecerlilik_bitis,
                }
                for r in session.scalars(q).all()
            ]

    @staticmethod
    def guncel_fiyat(cari_id: int, urun_kodu: str, gun: date | None = None) -> Decimal | None:
        TedarikciFiyatService.schema_hazirla()
        gun = gun or date.today()
        with get_session() as session:
            kayit = session.scalar(
                select(TedarikciFiyat)
                .where(
                    TedarikciFiyat.cari_id == int(cari_id),
                    TedarikciFiyat.urun_kodu == (urun_kodu or "").strip(),
                    TedarikciFiyat.aktif.is_(True),
                    TedarikciFiyat.gecerlilik_baslangic <= gun,
                    or_(
                        TedarikciFiyat.gecerlilik_bitis.is_(None),
                        TedarikciFiyat.gecerlilik_bitis >= gun,
                    ),
                )
                .order_by(TedarikciFiyat.gecerlilik_baslangic.desc())
                .limit(1)
            )
            return kayit.birim_fiyat if kayit else None

    @staticmethod
    def kaydet(veriler: dict[str, Any], kayit_id: int | None = None) -> int:
        yazma_zorunlu("alis_fiyat_duzenleme", "alis_duzenleme", "yeni_kayit")
        TedarikciFiyatService.schema_hazirla()
        with get_session() as session:
            if kayit_id:
                kayit = session.get(TedarikciFiyat, int(kayit_id))
                if kayit is None:
                    raise ValueError("Fiyat kaydı bulunamadı.")
            else:
                kayit = TedarikciFiyat(
                    gecerlilik_baslangic=veriler.get("gecerlilik_baslangic") or date.today()
                )
                session.add(kayit)
            kayit.cari_id = int(veriler["cari_id"])
            kayit.urun_kodu = (veriler["urun_kodu"] or "").strip()
            kayit.urun_adi = veriler["urun_adi"]
            kayit.birim = veriler.get("birim") or "Adet"
            kayit.birim_fiyat = decimal(veriler["birim_fiyat"], "Birim fiyat", Decimal("0"))
            kayit.iskonto_orani = decimal(
                veriler.get("iskonto_orani", 0), "İskonto", Decimal("0")
            )
            kayit.para_birimi = veriler.get("para_birimi") or "TRY"
            kayit.gecerlilik_baslangic = veriler["gecerlilik_baslangic"]
            kayit.gecerlilik_bitis = veriler.get("gecerlilik_bitis")
            kayit.aktif = bool(veriler.get("aktif", True))
            session.flush()
            return int(kayit.id)

    @staticmethod
    def pasif_et(kayit_id: int) -> None:
        yazma_zorunlu("alis_fiyat_duzenleme", "alis_duzenleme")
        with get_session() as session:
            kayit = session.get(TedarikciFiyat, int(kayit_id))
            if kayit is None:
                raise ValueError("Kayıt bulunamadı.")
            kayit.aktif = False
