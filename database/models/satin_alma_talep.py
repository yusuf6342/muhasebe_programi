"""Satın alma talepleri — iç ihtiyaç / yeniden sipariş."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import TYPE_CHECKING

from sqlalchemy import Date, DateTime, ForeignKey, Integer, Numeric, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from database.database import Base

if TYPE_CHECKING:
    from database.models.cari import Cari


class SatinAlmaTalep(Base):
    __tablename__ = "satin_alma_talepleri"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    talep_no: Mapped[str] = mapped_column(String(30), unique=True, nullable=False)
    talep_tarihi: Mapped[date] = mapped_column(Date, nullable=False)
    ihtiyac_tarihi: Mapped[date | None] = mapped_column(Date, nullable=True)
    isteyen_kullanici: Mapped[str | None] = mapped_column(String(120), nullable=True)
    depo: Mapped[str | None] = mapped_column(String(100), nullable=True)
    oncelik: Mapped[str] = mapped_column(String(20), nullable=False, default="NORMAL")
    durum: Mapped[str] = mapped_column(String(30), nullable=False, default="TASLAK")
    aciklama: Mapped[str | None] = mapped_column(Text, nullable=True)
    olusturma_tarihi: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.now, nullable=False
    )

    satirlar: Mapped[list["SatinAlmaTalepSatiri"]] = relationship(
        "SatinAlmaTalepSatiri",
        back_populates="talep",
        cascade="all, delete-orphan",
    )


class SatinAlmaTalepSatiri(Base):
    __tablename__ = "satin_alma_talep_satirlari"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    talep_id: Mapped[int] = mapped_column(
        ForeignKey("satin_alma_talepleri.id"), nullable=False, index=True
    )
    urun_kodu: Mapped[str] = mapped_column(String(50), nullable=False)
    urun_adi: Mapped[str] = mapped_column(String(200), nullable=False)
    birim: Mapped[str] = mapped_column(String(20), nullable=False, default="Adet")
    miktar: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False)
    aciklama: Mapped[str | None] = mapped_column(String(500), nullable=True)
    depo: Mapped[str | None] = mapped_column(String(100), nullable=True)

    talep: Mapped["SatinAlmaTalep"] = relationship(
        "SatinAlmaTalep", back_populates="satirlar"
    )
