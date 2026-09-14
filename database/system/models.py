"""system.db tabloları — operasyonel muhasebe kayıtları burada tutulmaz."""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class SystemBase(DeclarativeBase):
    pass


class SchemaMigration(SystemBase):
    __tablename__ = "schema_migrations"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    surum: Mapped[str] = mapped_column(String(50), unique=True, nullable=False)
    aciklama: Mapped[str | None] = mapped_column(String(255), nullable=True)
    uygulanma_tarihi: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.now, nullable=False
    )


class Role(SystemBase):
    __tablename__ = "roles"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    kod: Mapped[str] = mapped_column(String(40), unique=True, nullable=False)
    ad: Mapped[str] = mapped_column(String(80), nullable=False)
    aciklama: Mapped[str | None] = mapped_column(String(255), nullable=True)
    sistem: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    permissions: Mapped[list["RolePermission"]] = relationship(
        back_populates="role", cascade="all, delete-orphan"
    )
    users: Mapped[list["User"]] = relationship(back_populates="role")


class Permission(SystemBase):
    __tablename__ = "permissions"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    kod: Mapped[str] = mapped_column(String(60), unique=True, nullable=False)
    ad: Mapped[str] = mapped_column(String(100), nullable=False)
    modul: Mapped[str | None] = mapped_column(String(60), nullable=True)

    roles: Mapped[list["RolePermission"]] = relationship(back_populates="permission")
    users: Mapped[list["UserPermission"]] = relationship(back_populates="permission")


class RolePermission(SystemBase):
    __tablename__ = "role_permissions"
    __table_args__ = (UniqueConstraint("role_id", "permission_id"),)

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    role_id: Mapped[int] = mapped_column(ForeignKey("roles.id"), nullable=False)
    permission_id: Mapped[int] = mapped_column(
        ForeignKey("permissions.id"), nullable=False
    )

    role: Mapped["Role"] = relationship(back_populates="permissions")
    permission: Mapped["Permission"] = relationship(back_populates="roles")


class Company(SystemBase):
    """Firma meta bilgisi — operasyon DB yolu burada tutulur."""

    __tablename__ = "companies"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    firma_uid: Mapped[str] = mapped_column(String(36), unique=True, nullable=False)
    firma_kodu: Mapped[str] = mapped_column(String(30), unique=True, nullable=False)
    unvan: Mapped[str] = mapped_column(String(200), nullable=False)
    kisa_ad: Mapped[str | None] = mapped_column(String(80), nullable=True)
    vergi_dairesi: Mapped[str | None] = mapped_column(String(100), nullable=True)
    vergi_no: Mapped[str | None] = mapped_column(String(20), nullable=True)
    telefon: Mapped[str | None] = mapped_column(String(30), nullable=True)
    email: Mapped[str | None] = mapped_column(String(150), nullable=True)
    internet: Mapped[str | None] = mapped_column(String(200), nullable=True)
    adres: Mapped[str | None] = mapped_column(String(500), nullable=True)
    il: Mapped[str | None] = mapped_column(String(50), nullable=True)
    ilce: Mapped[str | None] = mapped_column(String(50), nullable=True)
    logo_yolu: Mapped[str | None] = mapped_column(String(500), nullable=True)
    varsayilan_para_birimi: Mapped[str] = mapped_column(
        String(3), default="TRY", nullable=False
    )
    fatura_seri: Mapped[str | None] = mapped_column(String(20), nullable=True)
    aktif: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    db_path: Mapped[str] = mapped_column(String(500), nullable=False)
    olusturma_tarihi: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.now, nullable=False
    )

    user_links: Mapped[list["UserCompany"]] = relationship(
        back_populates="company", cascade="all, delete-orphan"
    )


class User(SystemBase):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    kullanici_kodu: Mapped[str] = mapped_column(String(30), unique=True, nullable=False)
    ad_soyad: Mapped[str] = mapped_column(String(120), nullable=False)
    kullanici_adi: Mapped[str] = mapped_column(String(80), unique=True, nullable=False)
    parola_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    role_id: Mapped[int] = mapped_column(ForeignKey("roles.id"), nullable=False)
    aktif: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    varsayilan_firma_id: Mapped[int | None] = mapped_column(
        ForeignKey("companies.id"), nullable=True
    )
    sifre_degistirmeli: Mapped[bool] = mapped_column(
        Boolean, default=False, nullable=False
    )
    olusturma_tarihi: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.now, nullable=False
    )
    son_giris_tarihi: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    role: Mapped["Role"] = relationship(back_populates="users")
    companies: Mapped[list["UserCompany"]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )
    extra_permissions: Mapped[list["UserPermission"]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )


class UserCompany(SystemBase):
    __tablename__ = "user_companies"
    __table_args__ = (UniqueConstraint("user_id", "company_id"),)

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    company_id: Mapped[int] = mapped_column(ForeignKey("companies.id"), nullable=False)

    user: Mapped["User"] = relationship(back_populates="companies")
    company: Mapped["Company"] = relationship(back_populates="user_links")


class UserPermission(SystemBase):
    """Kullanıcı bazlı özel izin (rol dışı ekleme veya yasaklama)."""

    __tablename__ = "user_permissions"
    __table_args__ = (UniqueConstraint("user_id", "permission_id"),)

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    permission_id: Mapped[int] = mapped_column(
        ForeignKey("permissions.id"), nullable=False
    )
    # True = izin ver, False = rol iznini bile kaldır
    izinli: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    user: Mapped["User"] = relationship(back_populates="extra_permissions")
    permission: Mapped["Permission"] = relationship(back_populates="users")


class AppSetting(SystemBase):
    __tablename__ = "app_settings"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    anahtar: Mapped[str] = mapped_column(String(80), unique=True, nullable=False)
    deger: Mapped[str | None] = mapped_column(Text, nullable=True)


class LoginLog(SystemBase):
    __tablename__ = "login_logs"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    kullanici_adi: Mapped[str] = mapped_column(String(80), nullable=False)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    basarili: Mapped[bool] = mapped_column(Boolean, nullable=False)
    mesaj: Mapped[str | None] = mapped_column(String(255), nullable=True)
    bilgisayar: Mapped[str | None] = mapped_column(String(120), nullable=True)
    tarih: Mapped[datetime] = mapped_column(DateTime, default=datetime.now, nullable=False)


class AuditLog(SystemBase):
    __tablename__ = "audit_logs"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    company_id: Mapped[int | None] = mapped_column(
        ForeignKey("companies.id"), nullable=True
    )
    donem_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    islem_turu: Mapped[str] = mapped_column(String(40), nullable=False)
    modul: Mapped[str | None] = mapped_column(String(60), nullable=True)
    kayit_id: Mapped[str | None] = mapped_column(String(60), nullable=True)
    eski_deger: Mapped[str | None] = mapped_column(Text, nullable=True)
    yeni_deger: Mapped[str | None] = mapped_column(Text, nullable=True)
    bilgisayar: Mapped[str | None] = mapped_column(String(120), nullable=True)
    tarih: Mapped[datetime] = mapped_column(DateTime, default=datetime.now, nullable=False)
