"""Proje takip — maliyet merkezi / raporlama boyutu (ikinci defter değil)."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from database.database import Base

DURUM_TASLAK = "TASLAK"
DURUM_AKTIF = "AKTIF"
DURUM_DURDURULDU = "DURDURULDU"
DURUM_TAMAMLANDI = "TAMAMLANDI"
DURUM_IPTAL = "IPTAL"
DURUMLAR = (DURUM_TASLAK, DURUM_AKTIF, DURUM_DURDURULDU, DURUM_TAMAMLANDI, DURUM_IPTAL)

ORNEK_TURLER = (
    "Müşteri Projesi",
    "Mağaza",
    "Tadilat",
    "Kurulum",
    "Özel Sipariş",
    "Toplu Satış",
    "İnternet",
    "Pazarlama",
    "İç Proje",
    "Diğer",
)


class Proje(Base):
    __tablename__ = "projeler"
    __table_args__ = (
        UniqueConstraint("firma_id", "kod", name="uq_proje_firma_kod"),
        Index("ix_proje_firma_durum", "firma_id", "durum"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    firma_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    kod: Mapped[str] = mapped_column(String(30), nullable=False)
    ad: Mapped[str] = mapped_column(String(200), nullable=False)
    kisa_ad: Mapped[str | None] = mapped_column(String(80), nullable=True)
    tur: Mapped[str | None] = mapped_column(String(60), nullable=True)
    grup: Mapped[str | None] = mapped_column(String(60), nullable=True)
    ana_proje_id: Mapped[int | None] = mapped_column(
        ForeignKey("projeler.id"), nullable=True, index=True
    )
    ana_musteri_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    sorumlu: Mapped[str | None] = mapped_column(String(120), nullable=True)
    satis_temsilcisi: Mapped[str | None] = mapped_column(String(120), nullable=True)
    baslangic: Mapped[date | None] = mapped_column(Date, nullable=True)
    plan_bitis: Mapped[date | None] = mapped_column(Date, nullable=True)
    gercek_bitis: Mapped[date | None] = mapped_column(Date, nullable=True)
    durum: Mapped[str] = mapped_column(String(20), nullable=False, default=DURUM_AKTIF)
    rapor_pb: Mapped[str] = mapped_column(String(3), nullable=False, default="TRY")
    hedef_gelir: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False, default=0)
    hedef_maliyet: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False, default=0)
    aciklama: Mapped[str | None] = mapped_column(Text, nullable=True)
    aktif: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    olusturma: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.now)
    olusturan: Mapped[str | None] = mapped_column(String(120), nullable=True)
    guncelleme: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    guncelleyen: Mapped[str | None] = mapped_column(String(120), nullable=True)

    baglantilar: Mapped[list["ProjeBelgeBaglanti"]] = relationship(
        "ProjeBelgeBaglanti",
        back_populates="proje",
        cascade="all, delete-orphan",
    )
    cariler: Mapped[list["ProjeCari"]] = relationship(
        "ProjeCari",
        back_populates="proje",
        cascade="all, delete-orphan",
    )


class ProjeCari(Base):
    __tablename__ = "proje_cariler"
    __table_args__ = (
        UniqueConstraint("proje_id", "cari_id", "rol", name="uq_proje_cari_rol"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    proje_id: Mapped[int] = mapped_column(ForeignKey("projeler.id"), nullable=False, index=True)
    cari_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    rol: Mapped[str] = mapped_column(String(40), nullable=False, default="MUSTERI")
    aciklama: Mapped[str | None] = mapped_column(String(200), nullable=True)
    aktif: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    proje: Mapped["Proje"] = relationship("Proje", back_populates="cariler")


class ProjeBelgeBaglanti(Base):
    """Kaynak belge → proje analitik etiketi (tutar/bakiye yeniden yazılmaz)."""

    __tablename__ = "proje_belge_baglantilari"
    __table_args__ = (
        UniqueConstraint(
            "firma_id",
            "kaynak_tip",
            "kaynak_id",
            "proje_id",
            name="uq_proje_belge",
        ),
        Index("ix_proje_belge_kaynak", "kaynak_tip", "kaynak_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    firma_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    proje_id: Mapped[int] = mapped_column(ForeignKey("projeler.id"), nullable=False, index=True)
    kaynak_tip: Mapped[str] = mapped_column(String(40), nullable=False)
    kaynak_id: Mapped[str] = mapped_column(String(80), nullable=False)
    kaynak_no: Mapped[str | None] = mapped_column(String(50), nullable=True)
    tutar_pay: Mapped[Decimal | None] = mapped_column(Numeric(18, 2), nullable=True)
    yuzde: Mapped[Decimal | None] = mapped_column(Numeric(9, 4), nullable=True)
    surum: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    aktif: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    olusturma: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.now)
    olusturan: Mapped[str | None] = mapped_column(String(120), nullable=True)

    proje: Mapped["Proje"] = relationship("Proje", back_populates="baglantilar")


class ProjeAyar(Base):
    __tablename__ = "proje_ayarlari"

    firma_id: Mapped[int] = mapped_column(Integer, primary_key=True)
    asama_aktif: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    coklu_dagitim: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    ortak_gider: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    hakedis: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    gorevler: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    guncelleme: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
