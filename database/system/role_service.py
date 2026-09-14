"""Rol ve izin yönetimi (system.db)."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import selectinload

from database.database import get_system_session
from database.session_manager import oturum
from database.system.auth_service import AuthService
from database.system.models import Permission, Role, RolePermission


class RoleService:
    @staticmethod
    def _yetki() -> None:
        if not oturum.has_permission("kullanici_yonetme"):
            raise PermissionError("Rol/yetki yönetimi için kullanıcı yönetme yetkisi gerekir.")

    @staticmethod
    def roller() -> list[dict]:
        RoleService._yetki()
        with get_system_session() as session:
            sonuc = []
            for r in session.scalars(
                select(Role).options(selectinload(Role.permissions)).order_by(Role.ad)
            ).all():
                izin_idler = [rp.permission_id for rp in r.permissions]
                sonuc.append({
                    "id": r.id,
                    "kod": r.kod,
                    "ad": r.ad,
                    "aciklama": r.aciklama,
                    "sistem": r.sistem,
                    "izin_idler": izin_idler,
                })
            return sonuc

    @staticmethod
    def izinler() -> list[dict]:
        with get_system_session() as session:
            return [
                {"id": p.id, "kod": p.kod, "ad": p.ad, "modul": p.modul}
                for p in session.scalars(
                    select(Permission).order_by(Permission.modul, Permission.ad)
                ).all()
            ]

    @staticmethod
    def rol_izinlerini_kaydet(role_id: int, izin_idler: list[int]) -> None:
        RoleService._yetki()
        with get_system_session() as session:
            rol = session.get(Role, role_id)
            if rol is None:
                raise ValueError("Rol bulunamadı.")
            if rol.kod == "YONETICI":
                # Yönetici her zaman tüm izinlere sahip kalsın
                tum = [p.id for p in session.scalars(select(Permission)).all()]
                izin_idler = tum
            mevcut = {
                rp.permission_id: rp
                for rp in session.scalars(
                    select(RolePermission).where(RolePermission.role_id == role_id)
                ).all()
            }
            hedef = set(izin_idler)
            for pid, rp in list(mevcut.items()):
                if pid not in hedef:
                    session.delete(rp)
            for pid in hedef:
                if pid not in mevcut:
                    session.add(RolePermission(role_id=role_id, permission_id=pid))
            AuthService.audit(
                session, "yetki_degistirme", modul="rol", kayit_id=str(role_id),
                yeni_deger=rol.kod,
            )
