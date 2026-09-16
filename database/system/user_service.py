"""Sistem kullanıcı yönetimi (system.db)."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import selectinload

from database.database import get_system_session
from database.session_manager import oturum
from database.system.auth_service import AuthService
from database.system.models import Role, User, UserCompany
from database.system.password import guvenli_parola_uret, hash_parola


class UserService:
    @staticmethod
    def _yetki_kontrol() -> None:
        if not oturum.has_permission("kullanici_yonetme"):
            raise PermissionError("Kullanıcı yönetimi yetkiniz yok.")

    @staticmethod
    def listele(arama: str = "") -> list[dict]:
        UserService._yetki_kontrol()
        with get_system_session() as session:
            statement = (
                select(User)
                .options(selectinload(User.role), selectinload(User.companies))
                .order_by(User.kullanici_adi)
            )
            arama = (arama or "").strip()
            if arama:
                ifade = f"%{arama}%"
                statement = statement.where(
                    or_(
                        User.kullanici_adi.ilike(ifade),
                        User.ad_soyad.ilike(ifade),
                        User.kullanici_kodu.ilike(ifade),
                    )
                )
            sonuc = []
            for u in session.scalars(statement).all():
                sonuc.append({
                    "id": u.id,
                    "kullanici_kodu": u.kullanici_kodu,
                    "ad_soyad": u.ad_soyad,
                    "kullanici_adi": u.kullanici_adi,
                    "rol": u.role.ad if u.role else "",
                    "role_id": u.role_id,
                    "aktif": u.aktif,
                    "varsayilan_firma_id": u.varsayilan_firma_id,
                    "firma_idler": [uc.company_id for uc in u.companies],
                    "olusturma_tarihi": u.olusturma_tarihi,
                    "son_giris_tarihi": u.son_giris_tarihi,
                    "sifre_degistirmeli": u.sifre_degistirmeli,
                    "pin_tanimli": bool(getattr(u, "hizli_pin_hash", None)),
                })
            return sonuc

    @staticmethod
    def getir(user_id: int) -> dict | None:
        UserService._yetki_kontrol()
        with get_system_session() as session:
            u = session.scalar(
                select(User)
                .options(selectinload(User.role), selectinload(User.companies))
                .where(User.id == user_id)
            )
            if u is None:
                return None
            return {
                "id": u.id,
                "kullanici_kodu": u.kullanici_kodu,
                "ad_soyad": u.ad_soyad,
                "kullanici_adi": u.kullanici_adi,
                "role_id": u.role_id,
                "rol": u.role.ad if u.role else "",
                "aktif": u.aktif,
                "varsayilan_firma_id": u.varsayilan_firma_id,
                "firma_idler": [uc.company_id for uc in u.companies],
                "olusturma_tarihi": u.olusturma_tarihi,
                "son_giris_tarihi": u.son_giris_tarihi,
                "sifre_degistirmeli": u.sifre_degistirmeli,
                "pin_tanimli": bool(getattr(u, "hizli_pin_hash", None)),
            }

    @staticmethod
    def roller() -> list[tuple[int, str]]:
        with get_system_session() as session:
            return [
                (r.id, r.ad)
                for r in session.scalars(select(Role).order_by(Role.ad)).all()
            ]

    @staticmethod
    def ekle(veriler: dict) -> tuple[int, str | None]:
        """Döner: (user_id, tek_seferlik_parola | None)."""
        UserService._yetki_kontrol()
        parola = (veriler.get("parola") or "").strip()
        uretilen = None
        if not parola:
            parola = guvenli_parola_uret(10)
            uretilen = parola
        with get_system_session() as session:
            user = User(
                kullanici_kodu=veriler["kullanici_kodu"].strip(),
                ad_soyad=veriler["ad_soyad"].strip(),
                kullanici_adi=veriler["kullanici_adi"].strip(),
                parola_hash=hash_parola(parola),
                role_id=int(veriler["role_id"]),
                aktif=bool(veriler.get("aktif", True)),
                varsayilan_firma_id=veriler.get("varsayilan_firma_id"),
                sifre_degistirmeli=True,
            )
            session.add(user)
            try:
                session.flush()
            except IntegrityError as hata:
                raise ValueError("Kullanıcı kodu veya kullanıcı adı zaten kullanılıyor.") from hata
            for cid in veriler.get("firma_idler") or []:
                session.add(UserCompany(user_id=user.id, company_id=int(cid)))
            AuthService.audit(
                session, "yeni_kayit", modul="kullanici", kayit_id=str(user.id),
                yeni_deger=user.kullanici_adi,
            )
            return user.id, uretilen

    @staticmethod
    def guncelle(user_id: int, veriler: dict) -> None:
        UserService._yetki_kontrol()
        with get_system_session() as session:
            user = session.get(User, user_id)
            if user is None:
                raise ValueError("Kullanıcı bulunamadı.")
            user.kullanici_kodu = veriler["kullanici_kodu"].strip()
            user.ad_soyad = veriler["ad_soyad"].strip()
            user.kullanici_adi = veriler["kullanici_adi"].strip()
            user.role_id = int(veriler["role_id"])
            user.aktif = bool(veriler.get("aktif", True))
            user.varsayilan_firma_id = veriler.get("varsayilan_firma_id")
            try:
                session.flush()
            except IntegrityError as hata:
                raise ValueError("Kullanıcı kodu veya kullanıcı adı zaten kullanılıyor.") from hata
            mevcut = {uc.company_id: uc for uc in user.companies}
            hedef = {int(x) for x in (veriler.get("firma_idler") or [])}
            for cid, uc in list(mevcut.items()):
                if cid not in hedef:
                    session.delete(uc)
            for cid in hedef:
                if cid not in mevcut:
                    session.add(UserCompany(user_id=user.id, company_id=cid))
            AuthService.audit(
                session, "duzenleme", modul="kullanici", kayit_id=str(user_id),
                yeni_deger=user.kullanici_adi,
            )

    @staticmethod
    def pasife_al(user_id: int) -> None:
        UserService._yetki_kontrol()
        if oturum.user_id == user_id:
            raise ValueError("Kendi hesabınızı pasife alamazsınız.")
        with get_system_session() as session:
            user = session.get(User, user_id)
            if user is None:
                raise ValueError("Kullanıcı bulunamadı.")
            user.aktif = False
            AuthService.audit(session, "pasife_alma", modul="kullanici", kayit_id=str(user_id))

    @staticmethod
    def sifre_sifirla(user_id: int) -> str:
        """Yeni geçici parola üretir; kullanıcı ilk girişte değiştirir."""
        UserService._yetki_kontrol()
        yeni = guvenli_parola_uret(10)
        with get_system_session() as session:
            user = session.get(User, user_id)
            if user is None:
                raise ValueError("Kullanıcı bulunamadı.")
            user.parola_hash = hash_parola(yeni)
            user.sifre_degistirmeli = True
            AuthService.audit(session, "sifre_sifirlama", modul="kullanici", kayit_id=str(user_id))
        return yeni
