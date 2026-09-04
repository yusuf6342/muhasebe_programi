from datetime import date, datetime
from decimal import Decimal
from typing import TYPE_CHECKING

from sqlalchemy import Date, DateTime, ForeignKey, Numeric, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from database.database import Base

if TYPE_CHECKING:
    from database.models.cari import Cari
    from database.models.satis_siparisi import SatisSiparisi


class SatisIrsaliyesi(Base):
    __tablename__ = "satis_irsaliyeleri"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    irsaliye_no: Mapped[str] = mapped_column(String(30), unique=True, nullable=False)
    irsaliye_tarihi: Mapped[date] = mapped_column(Date, nullable=False)
    cari_id: Mapped[int] = mapped_column(ForeignKey("cari_kartlar.id"), nullable=False, index=True)
    siparis_id: Mapped[int | None] = mapped_column(ForeignKey("satis_siparisleri.id"), nullable=True, index=True)
    durum: Mapped[str] = mapped_column(String(30), nullable=False, default="AÇIK")
    aciklama: Mapped[str | None] = mapped_column(Text, nullable=True)
    ayrintili_notlar: Mapped[str | None] = mapped_column(Text, nullable=True)
    olusturma_tarihi: Mapped[datetime] = mapped_column(DateTime, default=datetime.now, nullable=False)

    cari: Mapped["Cari"] = relationship("Cari")
    siparis: Mapped["SatisSiparisi | None"] = relationship("SatisSiparisi")
    satirlar: Mapped[list["SatisIrsaliyesiSatiri"]] = relationship(
        "SatisIrsaliyesiSatiri", back_populates="irsaliye", cascade="all, delete-orphan"
    )


class SatisIrsaliyesiSatiri(Base):
    __tablename__ = "satis_irsaliyesi_satirlari"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    irsaliye_id: Mapped[int] = mapped_column(ForeignKey("satis_irsaliyeleri.id"), nullable=False, index=True)
    siparis_satiri_id: Mapped[int | None] = mapped_column(ForeignKey("satis_siparisi_satirlari.id"), nullable=True, index=True)
    urun_kodu: Mapped[str] = mapped_column(String(50), nullable=False)
    urun_adi: Mapped[str] = mapped_column(String(200), nullable=False)
    aciklama: Mapped[str | None] = mapped_column(String(500), nullable=True)
    miktar: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False)
    birim: Mapped[str] = mapped_column(String(20), nullable=False)
    birim_fiyat: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False)
    iskonto_orani: Mapped[Decimal] = mapped_column(Numeric(7, 2), nullable=False, default=0)
    kdv_orani: Mapped[Decimal] = mapped_column(Numeric(7, 2), nullable=False, default=20)
    faturalanan_miktar: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False, default=0)
    fatura_belge_baglantisi: Mapped[str | None] = mapped_column(String(100), nullable=True)

    irsaliye: Mapped["SatisIrsaliyesi"] = relationship("SatisIrsaliyesi", back_populates="satirlar")