"""Alış fatura ek masraf dağıtımı (nakliye, hamaliye, sigorta vb.)."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from sqlalchemy import Boolean, DateTime, ForeignKey, Numeric, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from database.database import Base


class AlisMasraf(Base):
    __tablename__ = "alis_masraflari"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    fatura_id: Mapped[int] = mapped_column(
        ForeignKey("alis_faturalari.id"), nullable=False, index=True
    )
    masraf_turu: Mapped[str] = mapped_column(String(50), nullable=False)
    tutar: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    dagitim_yontemi: Mapped[str] = mapped_column(
        String(20), nullable=False, default="TUTAR"
    )  # TUTAR | MIKTAR | MANUEL
    maliyete_dahil: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    aciklama: Mapped[str | None] = mapped_column(Text, nullable=True)
    olusturma_tarihi: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.now, nullable=False
    )

    dagitimlar: Mapped[list["AlisMasrafDagitim"]] = relationship(
        "AlisMasrafDagitim",
        back_populates="masraf",
        cascade="all, delete-orphan",
    )
    fatura = relationship("AlisFaturasi")


class AlisMasrafDagitim(Base):
    __tablename__ = "alis_masraf_dagitimlari"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    masraf_id: Mapped[int] = mapped_column(
        ForeignKey("alis_masraflari.id"), nullable=False, index=True
    )
    fatura_satiri_id: Mapped[int] = mapped_column(
        ForeignKey("alis_faturasi_satirlari.id"), nullable=False, index=True
    )
    tutar: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False)
    oran: Mapped[Decimal] = mapped_column(Numeric(10, 6), nullable=False, default=0)

    masraf: Mapped["AlisMasraf"] = relationship("AlisMasraf", back_populates="dagitimlar")
