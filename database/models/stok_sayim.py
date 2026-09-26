"""Stok sayım fişi — sistem vs sayılan miktar düzeltmesi."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import Date, DateTime, ForeignKey, Numeric, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from database.database import Base
from database.models.sube import Sube  # noqa: F401


class StokSayimFisi(Base):
    __tablename__ = "stok_sayim_fisleri"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    sube_id: Mapped[int | None] = mapped_column(ForeignKey("subeler.id"), nullable=True, index=True)
    fis_no: Mapped[str] = mapped_column(String(30), unique=True, nullable=False)
    fis_tarihi: Mapped[date] = mapped_column(Date, nullable=False)
    depo_id: Mapped[int] = mapped_column(ForeignKey("depolar.id"), nullable=False, index=True)
    durum: Mapped[str] = mapped_column(String(30), nullable=False, default="TASLAK")
    aciklama: Mapped[str | None] = mapped_column(Text, nullable=True)
    olusturma_tarihi: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.now, nullable=False
    )

    satirlar: Mapped[list["StokSayimSatiri"]] = relationship(
        "StokSayimSatiri", back_populates="fis", cascade="all, delete-orphan"
    )
    depo = relationship("Depo")


class StokSayimSatiri(Base):
    __tablename__ = "stok_sayim_satirlari"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    fis_id: Mapped[int] = mapped_column(
        ForeignKey("stok_sayim_fisleri.id"), nullable=False, index=True
    )
    stok_id: Mapped[int] = mapped_column(ForeignKey("stok_kartlari.id"), nullable=False, index=True)
    sistem_miktar: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False, default=0)
    sayilan_miktar: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False, default=0)
    fark: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False, default=0)
    fark_nedeni: Mapped[str | None] = mapped_column(String(200), nullable=True)

    fis: Mapped["StokSayimFisi"] = relationship("StokSayimFisi", back_populates="satirlar")
    stok = relationship("StokKarti")
