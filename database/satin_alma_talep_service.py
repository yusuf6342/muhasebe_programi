"""Satın alma talebi CRUD."""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import selectinload

from database.access import yazma_zorunlu
from database.database import get_session
from database.models.satin_alma_talep import SatinAlmaTalep, SatinAlmaTalepSatiri
from database.satis_siparisi_service import decimal
from database.satin_alma_hub_service import SatinAlmaHubService
from database.session_manager import oturum

DURUMLAR = ("TASLAK", "ONAY BEKLİYOR", "ONAYLANDI", "SİPARİŞE AKTARILDI", "İPTAL")
ONCELIKLER = ("DÜŞÜK", "NORMAL", "YÜKSEK", "ACİL")


class SatinAlmaTalepService:
    @staticmethod
    def schema_hazirla() -> None:
        SatinAlmaHubService.schema_hazirla()

    @staticmethod
    def talep_no() -> str:
        SatinAlmaTalepService.schema_hazirla()
        onek = "TAL"
        with get_session() as session:
            son = session.scalar(
                select(SatinAlmaTalep.talep_no)
                .where(SatinAlmaTalep.talep_no.like(f"{onek}%"))
                .order_by(SatinAlmaTalep.talep_no.desc())
            )
        if not son:
            return f"{onek}000001"
        try:
            sira = int(str(son)[len(onek) :]) + 1
        except ValueError:
            sira = 1
        return f"{onek}{sira:06d}"

    @staticmethod
    def listele(durum: str | None = None) -> list[dict[str, Any]]:
        SatinAlmaTalepService.schema_hazirla()
        with get_session() as session:
            q = (
                select(SatinAlmaTalep)
                .options(selectinload(SatinAlmaTalep.satirlar))
                .order_by(SatinAlmaTalep.id.desc())
            )
            if durum and durum != "Tümü":
                q = q.where(SatinAlmaTalep.durum == durum)
            kayitlar = list(session.scalars(q).all())
            return [
                {
                    "id": t.id,
                    "talep_no": t.talep_no,
                    "talep_tarihi": t.talep_tarihi,
                    "ihtiyac_tarihi": t.ihtiyac_tarihi,
                    "isteyen": t.isteyen_kullanici or "",
                    "depo": t.depo or "",
                    "oncelik": t.oncelik,
                    "durum": t.durum,
                    "satir_adet": len(t.satirlar or []),
                    "aciklama": t.aciklama or "",
                }
                for t in kayitlar
            ]

    @staticmethod
    def getir(talep_id: int) -> SatinAlmaTalep | None:
        SatinAlmaTalepService.schema_hazirla()
        with get_session() as session:
            return session.scalar(
                select(SatinAlmaTalep)
                .options(selectinload(SatinAlmaTalep.satirlar))
                .where(SatinAlmaTalep.id == int(talep_id))
            )

    @staticmethod
    def kaydet(
        veriler: dict[str, Any],
        satir_verileri: list[dict[str, Any]],
        talep_id: int | None = None,
    ) -> int:
        yazma_zorunlu("alis_talep_duzenleme", "alis_duzenleme", "yeni_kayit")
        SatinAlmaTalepService.schema_hazirla()
        if not satir_verileri:
            raise ValueError("En az bir talep satırı girin.")
        with get_session() as session:
            if talep_id:
                talep = session.get(SatinAlmaTalep, int(talep_id))
                if talep is None:
                    raise ValueError("Talep bulunamadı.")
                if talep.durum in ("SİPARİŞE AKTARILDI", "İPTAL"):
                    raise ValueError("Bu durumdaki talep düzenlenemez.")
                talep.satirlar.clear()
            else:
                talep = SatinAlmaTalep(
                    talep_no=(veriler.get("talep_no") or "").strip()
                    or SatinAlmaTalepService.talep_no(),
                    durum="TASLAK",
                )
                session.add(talep)

            talep.talep_tarihi = veriler["talep_tarihi"]
            talep.ihtiyac_tarihi = veriler.get("ihtiyac_tarihi")
            talep.isteyen_kullanici = (
                veriler.get("isteyen_kullanici")
                or oturum.ad_soyad
                or oturum.kullanici_adi
                or ""
            )
            talep.depo = veriler.get("depo") or "ANA DEPO"
            talep.oncelik = veriler.get("oncelik") or "NORMAL"
            talep.durum = veriler.get("durum") or talep.durum or "TASLAK"
            talep.aciklama = veriler.get("aciklama")

            for veri in satir_verileri:
                talep.satirlar.append(
                    SatinAlmaTalepSatiri(
                        urun_kodu=veri["urun_kodu"],
                        urun_adi=veri["urun_adi"],
                        birim=veri.get("birim") or "Adet",
                        miktar=decimal(veri["miktar"], "Miktar", Decimal("0.0001")),
                        aciklama=veri.get("aciklama"),
                        depo=veri.get("depo") or talep.depo,
                    )
                )
            session.flush()
            return int(talep.id)

    @staticmethod
    def durum_degistir(talep_id: int, yeni_durum: str) -> None:
        yazma_zorunlu("alis_talep_duzenleme", "alis_duzenleme")
        if yeni_durum not in DURUMLAR:
            raise ValueError("Geçersiz durum.")
        with get_session() as session:
            talep = session.get(SatinAlmaTalep, int(talep_id))
            if talep is None:
                raise ValueError("Talep bulunamadı.")
            talep.durum = yeni_durum

    @staticmethod
    def iptal_et(talep_id: int) -> None:
        SatinAlmaTalepService.durum_degistir(talep_id, "İPTAL")
