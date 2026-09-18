"""Tedarikçi teklifleri — çoklu tedarikçi fiyat/şart karşılaştırması."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import TYPE_CHECKING

from sqlalchemy import Boolean, Date, DateTime, ForeignKey, Integer, Numeric, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from database.database import Base

if TYPE_CHECKING:
    from database.models.cari import Cari


class TedarikciTeklif(Base):
    __tablename__ = "tedarikci_teklifleri"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    teklif_no: Mapped[str] = mapped_column(String(30), unique=True, nullable=False)
    teklif_tarihi: Mapped[date] = mapped_column(Date, nullable=False)
    talep_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    durum: Mapped[str] = mapped_column(String(30), nullable=False, default="TASLAK")
    aciklama: Mapped[str | None] = mapped_column(Text, nullable=True)
    olusturma_tarihi: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.now, nullable=False
    )

    satirlar: Mapped[list["TedarikciTeklifSatiri"]] = relationship(
        "TedarikciTeklifSatiri",
        back_populates="teklif",
        cascade="all, delete-orphan",
    )


class TedarikciTeklifSatiri(Base):
    __tablename__ = "tedarikci_teklif_satirlari"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    teklif_id: Mapped[int] = mapped_column(
        ForeignKey("tedarikci_teklifleri.id"), nullable=False, index=True
    )
    cari_id: Mapped[int] = mapped_column(
        ForeignKey("cari_kartlar.id"), nullable=False, index=True
    )
    urun_kodu: Mapped[str] = mapped_column(String(50), nullable=False)
    urun_adi: Mapped[str] = mapped_column(String(200), nullable=False)
    birim: Mapped[str] = mapped_column(String(20), nullable=False, default="Adet")
    miktar: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False)
    birim_fiyat: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False, default=0)
    iskonto_orani: Mapped[Decimal] = mapped_column(Numeric(7, 2), nullable=False, default=0)
    kdv_orani: Mapped[Decimal] = mapped_column(Numeric(7, 2), nullable=False, default=20)
    para_birimi: Mapped[str] = mapped_column(String(3), nullable=False, default="TRY")
    vade_gun: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    termin_gun: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    nakliye_tutari: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False, default=0)
    odeme_sarti: Mapped[str | None] = mapped_column(String(200), nullable=True)
    secildi: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    teklif: Mapped["TedarikciTeklif"] = relationship(
        "TedarikciTeklif", back_populates="satirlar"
    )
    cari: Mapped["Cari"] = relationship("Cari")
