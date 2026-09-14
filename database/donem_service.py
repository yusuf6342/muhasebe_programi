"""Firma çalışma dönemleri (aktif firma operasyon DB)."""

from __future__ import annotations

from datetime import date

from sqlalchemy import select, update

from database.database import get_session
from database.models.donem import Donem
from database.models.firma import Firma
from database.session_manager import oturum
from database.system.auth_service import AuthService
from database.database import get_system_session


class DonemService:
    @staticmethod
    def _yerel_firma_id(session) -> int:
        firma = session.scalar(select(Firma).order_by(Firma.id).limit(1))
        if firma is None:
            firma = Firma(
                firma_kodu=(oturum.firma_kodu or "FRM")[:20],
                unvan=oturum.firma_unvan or "Firma",
                aktif=True,
            )
            session.add(firma)
            session.flush()
        return firma.id

    @staticmethod
    def listele() -> list[dict]:
        with get_session() as session:
            return [
                {
                    "id": d.id,
                    "donem_adi": d.donem_adi,
                    "baslangic_tarihi": d.baslangic_tarihi,
                    "bitis_tarihi": d.bitis_tarihi,
                    "aktif": d.aktif,
                    "kapali": bool(getattr(d, "kapali", False)),
                    "varsayilan": bool(getattr(d, "varsayilan", False)),
                }
                for d in session.scalars(
                    select(Donem).order_by(Donem.baslangic_tarihi.desc())
                ).all()
            ]

    @staticmethod
    def ekle(veriler: dict) -> int:
        if not oturum.has_permission("donem_degistirme") and oturum.role_kod != "YONETICI":
            raise PermissionError("Dönem yönetimi yetkiniz yok.")
        with get_session() as session:
            firma_id = DonemService._yerel_firma_id(session)
            donem = Donem(
                firma_id=firma_id,
                donem_adi=veriler["donem_adi"].strip(),
                baslangic_tarihi=veriler["baslangic_tarihi"],
                bitis_tarihi=veriler["bitis_tarihi"],
                aktif=bool(veriler.get("aktif", True)),
                kapali=bool(veriler.get("kapali", False)),
                varsayilan=bool(veriler.get("varsayilan", False)),
            )
            if donem.varsayilan:
                session.execute(update(Donem).values(varsayilan=False))
            session.add(donem)
            session.flush()
            donem_id = donem.id
        with get_system_session() as session:
            AuthService.audit(
                session, "yeni_kayit", modul="donem", kayit_id=str(donem_id),
                yeni_deger=veriler["donem_adi"],
            )
        return donem_id

    @staticmethod
    def guncelle(donem_id: int, veriler: dict) -> None:
        if not oturum.has_permission("donem_degistirme") and oturum.role_kod != "YONETICI":
            raise PermissionError("Dönem yönetimi yetkiniz yok.")
        with get_session() as session:
            donem = session.get(Donem, donem_id)
            if donem is None:
                raise ValueError("Dönem bulunamadı.")
            donem.donem_adi = veriler["donem_adi"].strip()
            donem.baslangic_tarihi = veriler["baslangic_tarihi"]
            donem.bitis_tarihi = veriler["bitis_tarihi"]
            donem.aktif = bool(veriler.get("aktif", True))
            donem.kapali = bool(veriler.get("kapali", False))
            donem.varsayilan = bool(veriler.get("varsayilan", False))
            if donem.varsayilan:
                session.execute(
                    update(Donem).where(Donem.id != donem_id).values(varsayilan=False)
                )
        with get_system_session() as session:
            AuthService.audit(
                session, "duzenleme", modul="donem", kayit_id=str(donem_id),
                yeni_deger=veriler["donem_adi"],
            )

    @staticmethod
    def kapat_ac(donem_id: int, kapali: bool) -> None:
        if not oturum.has_permission("donem_degistirme") and oturum.role_kod != "YONETICI":
            raise PermissionError("Dönem yönetimi yetkiniz yok.")
        if kapali is False and oturum.role_kod != "YONETICI":
            raise PermissionError("Kapalı dönemi yalnızca yönetici açabilir.")
        with get_session() as session:
            donem = session.get(Donem, donem_id)
            if donem is None:
                raise ValueError("Dönem bulunamadı.")
            donem.kapali = kapali
        with get_system_session() as session:
            AuthService.audit(
                session,
                "donem_kapatma" if kapali else "donem_acma",
                modul="donem",
                kayit_id=str(donem_id),
            )

    @staticmethod
    def varsayilan_yap(donem_id: int) -> None:
        if not oturum.has_permission("donem_degistirme") and oturum.role_kod != "YONETICI":
            raise PermissionError("Dönem yönetimi yetkiniz yok.")
        with get_session() as session:
            donem = session.get(Donem, donem_id)
            if donem is None:
                raise ValueError("Dönem bulunamadı.")
            session.execute(update(Donem).values(varsayilan=False))
            donem.varsayilan = True
            donem.aktif = True
            oturum.set_period(donem.id, donem.donem_adi)

    @staticmethod
    def aktif_veya_varsayilan() -> dict | None:
        with get_session() as session:
            d = session.scalar(
                select(Donem).where(Donem.varsayilan.is_(True)).limit(1)
            )
            if d is None:
                d = session.scalar(
                    select(Donem).where(Donem.aktif.is_(True)).order_by(Donem.id.desc()).limit(1)
                )
            if d is None:
                return None
            return {
                "id": d.id,
                "donem_adi": d.donem_adi,
                "kapali": bool(getattr(d, "kapali", False)),
            }

    @staticmethod
    def kayit_izinli_mi() -> bool:
        """Kapalı döneme normal kullanıcı kayıt ekleyemez."""
        bilgi = DonemService.aktif_veya_varsayilan()
        if bilgi is None:
            return True
        if not bilgi.get("kapali"):
            return True
        return oturum.role_kod == "YONETICI"
