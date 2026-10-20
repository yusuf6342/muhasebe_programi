"""Personel kart fotoğrafı — firma DB içinde; masaüstü yoluna bağımlı değil."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import select

from database.access import yazma_zorunlu
from database.cari_foto_service import DOSYA_FILTRESI, goruntu_hazirla
from database.database import get_session
from database.models.personel import Personel, PersonelFotograf
from database.personel_sema import schema_hazirla

__all__ = ["DOSYA_FILTRESI", "PersonelFotoService", "goruntu_hazirla"]


class PersonelFotoService:
    @staticmethod
    def kaydet(personel_id: int, kaynak, *, hazir: dict | None = None) -> dict[str, Any]:
        yazma_zorunlu("personel_duzenleme", "duzenleme")
        schema_hazirla()
        foto = hazir or goruntu_hazirla(kaynak)
        with get_session() as session:
            p = session.get(Personel, int(personel_id))
            if p is None:
                raise ValueError("Personel bulunamadı. Önce kartı kaydedin.")
            kayit = session.scalar(
                select(PersonelFotograf).where(PersonelFotograf.personel_id == int(personel_id))
            )
            if kayit is None:
                kayit = PersonelFotograf(personel_id=int(personel_id))
                session.add(kayit)
            for alan in ("bicim", "genislik", "yukseklik", "veri", "kucuk", "kaynak_adi"):
                setattr(kayit, alan, foto.get(alan))
            kayit.guncelleme = datetime.now()
            session.flush()
            return {
                "id": int(kayit.id),
                "personel_id": int(personel_id),
                "genislik": kayit.genislik,
                "yukseklik": kayit.yukseklik,
            }

    @staticmethod
    def kaldir(personel_id: int) -> bool:
        yazma_zorunlu("personel_duzenleme", "duzenleme")
        schema_hazirla()
        with get_session() as session:
            kayit = session.scalar(
                select(PersonelFotograf).where(PersonelFotograf.personel_id == int(personel_id))
            )
            if kayit is None:
                return False
            session.delete(kayit)
            return True

    @staticmethod
    def getir(personel_id: int, *, kucuk: bool = False) -> bytes | None:
        from database.access import yetki_zorunlu

        yetki_zorunlu("personel_goruntuleme", "personel_duzenleme", "goruntuleme")
        schema_hazirla()
        with get_session() as session:
            kayit = session.scalar(
                select(PersonelFotograf).where(PersonelFotograf.personel_id == int(personel_id))
            )
            if kayit is None:
                return None
            return bytes(kayit.kucuk if kucuk else kayit.veri)
