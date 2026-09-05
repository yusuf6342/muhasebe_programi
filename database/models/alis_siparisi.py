from datetime import date, datetime
from decimal import Decimal
from typing import TYPE_CHECKING

from sqlalchemy import Date, DateTime, ForeignKey, Numeric, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from database.database import Base

if TYPE_CHECKING:
    from database.models.cari import Cari


class AlisSiparisi(Base):
    __tablename__ = "alis_siparisleri"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    siparis_no: Mapped[str] = mapped_column(String(30), unique=True, nullable=False)
    siparis_tarihi: Mapped[date] = mapped_column(Date, nullable=False)
    termin_tarihi: Mapped[date] = mapped_column(Date, nullable=False)
    cari_id: Mapped[int] = mapped_column(ForeignKey("cari_kartlar.id"), nullable=False, index=True)
    aciklama: Mapped[str | None] = mapped_column(Text, nullable=True)
    durum: Mapped[str] = mapped_column(String(30), nullable=False, default="AÇIK")
    olusturma_tarihi: Mapped[datetime] = mapped_column(DateTime, default=datetime.now, nullable=False)

    cari: Mapped["Cari"] = relationship("Cari")
    satirlar: Mapped[list["AlisSiparisiSatiri"]] = relationship(
        "AlisSiparisiSatiri", back_populates="siparis", cascade="all, delete-orphan"
    )
    odemeler: Mapped[list["AlisSiparisiOdemesi"]] = relationship(
        "AlisSiparisiOdemesi", back_populates="siparis", cascade="all, delete-orphan"
    )


class AlisSiparisiSatiri(Base):
    __tablename__ = "alis_siparisi_satirlari"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    siparis_id: Mapped[int] = mapped_column(ForeignKey("alis_siparisleri.id"), nullable=False, index=True)
    urun_kodu: Mapped[str] = mapped_column(String(50), nullable=False)
    urun_adi: Mapped[str] = mapped_column(String(200), nullable=False)
    aciklama: Mapped[str | None] = mapped_column(String(500), nullable=True)
    miktar: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False)
    birim: Mapped[str] = mapped_column(String(20), nullable=False)
    birim_alis_fiyati: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False)
    iskonto_orani: Mapped[Decimal] = mapped_column(Numeric(7, 2), nullable=False, default=0)
    kdv_orani: Mapped[Decimal] = mapped_column(Numeric(7, 2), nullable=False, default=20)
    irsaliyelenen_miktar: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False, default=0)
    faturalanan_miktar: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False, default=0)
    irsaliye_belge_baglantisi: Mapped[str | None] = mapped_column(String(100), nullable=True)
    fatura_belge_baglantisi: Mapped[str | None] = mapped_column(String(100), nullable=True)

    siparis: Mapped["AlisSiparisi"] = relationship("AlisSiparisi", back_populates="satirlar")


class AlisSiparisiOdemesi(Base):
    __tablename__ = "alis_siparisi_odemeleri"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    siparis_id: Mapped[int] = mapped_column(ForeignKey("alis_siparisleri.id"), nullable=False, index=True)
    odeme_tarihi: Mapped[date] = mapped_column(Date, nullable=False)
    tutar: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    odeme_sekli: Mapped[str] = mapped_column(String(30), nullable=False)
    hesap: Mapped[str | None] = mapped_column(String(100), nullable=True)
    aciklama: Mapped[str | None] = mapped_column(String(500), nullable=True)

    siparis: Mapped["AlisSiparisi"] = relationship("AlisSiparisi", back_populates="odemeler")
