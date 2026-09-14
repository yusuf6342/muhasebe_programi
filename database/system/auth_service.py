"""Kimlik doğrulama ve yetki yardımcıları (servis seviyesi)."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from database.session_manager import oturum
from database.system.bootstrap import bilgisayar_adi, kullanici_izinlerini_yukle
from database.system.models import AuditLog, Company, LoginLog, User
from database.system.password import hash_parola, parola_dogrula


class AuthService:
    @staticmethod
    def giris(session: Session, kullanici_adi: str, parola: str) -> User:
        ad = (kullanici_adi or "").strip()
        kayit = session.scalar(
            select(User)
            .options(
                selectinload(User.role),
                selectinload(User.extra_permissions),
                selectinload(User.companies),
            )
            .where(User.kullanici_adi == ad)
        )
        basarili = False
        mesaj = "Kullanıcı adı veya şifre hatalı."
        user_id = None

        if kayit is None:
            mesaj = "Kullanıcı adı veya şifre hatalı."
        elif not kayit.aktif:
            mesaj = "Bu kullanıcı pasif durumda; giriş yapılamaz."
        elif not parola_dogrula(parola, kayit.parola_hash):
            mesaj = "Kullanıcı adı veya şifre hatalı."
        else:
            basarili = True
            mesaj = "Giriş başarılı."
            user_id = kayit.id
            kayit.son_giris_tarihi = datetime.now()

        session.add(
            LoginLog(
                kullanici_adi=ad or "(boş)",
                user_id=user_id,
                basarili=basarili,
                mesaj=mesaj,
                bilgisayar=bilgisayar_adi(),
            )
        )
        session.flush()

        if not basarili:
            raise ValueError(mesaj)

        assert kayit is not None
        izinler = kullanici_izinlerini_yukle(session, kayit)
        oturum.set_user(
            user_id=kayit.id,
            kullanici_adi=kayit.kullanici_adi,
            ad_soyad=kayit.ad_soyad,
            role_kod=kayit.role.kod if kayit.role else "",
            role_ad=kayit.role.ad if kayit.role else "",
            permissions=izinler,
            sifre_degistirmeli=bool(kayit.sifre_degistirmeli),
        )
        return kayit

    @staticmethod
    def cikis() -> None:
        oturum.clear()

    @staticmethod
    def sifre_degistir(session: Session, user_id: int, eski: str, yeni: str) -> None:
        user = session.get(User, user_id)
        if user is None:
            raise ValueError("Kullanıcı bulunamadı.")
        if not parola_dogrula(eski, user.parola_hash):
            raise ValueError("Mevcut şifre hatalı.")
        if len(yeni or "") < 6:
            raise ValueError("Yeni şifre en az 6 karakter olmalıdır.")
        user.parola_hash = hash_parola(yeni)
        user.sifre_degistirmeli = False
        oturum.sifre_degistirmeli = False
        session.flush()

    @staticmethod
    def kullanici_firmalari(session: Session, user: User) -> list[Company]:
        if user.role and user.role.kod == "YONETICI":
            return list(
                session.scalars(
                    select(Company).where(Company.aktif.is_(True)).order_by(Company.unvan)
                ).all()
            )
        idler = [uc.company_id for uc in user.companies]
        if not idler:
            return []
        return list(
            session.scalars(
                select(Company)
                .where(Company.id.in_(idler), Company.aktif.is_(True))
                .order_by(Company.unvan)
            ).all()
        )

    @staticmethod
    def audit(
        session: Session,
        islem_turu: str,
        *,
        modul: str | None = None,
        kayit_id: str | None = None,
        eski_deger: str | None = None,
        yeni_deger: str | None = None,
    ) -> None:
        session.add(
            AuditLog(
                user_id=oturum.user_id,
                company_id=oturum.company_id,
                donem_id=oturum.period_id,
                islem_turu=islem_turu,
                modul=modul,
                kayit_id=kayit_id,
                eski_deger=eski_deger,
                yeni_deger=yeni_deger,
                bilgisayar=bilgisayar_adi(),
            )
        )
