from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import Date, DateTime, ForeignKey, Numeric, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from database.database import Base


class SatisIadeFaturasi(Base):
    __tablename__ = "satis_iade_faturalari"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    iade_no: Mapped[str] = mapped_column(String(30), unique=True, nullable=False)
    iade_tarihi: Mapped[date] = mapped_column(Date, nullable=False)
    cari_id: Mapped[int] = mapped_column(ForeignKey("cari_kartlar.id"), nullable=False, index=True)
    kaynak_fatura_id: Mapped[int | None] = mapped_column(ForeignKey("satis_faturalari.id"), nullable=True, index=True)
    durum: Mapped[str] = mapped_column(String(20), nullable=False, default="AÇIK")
    depo: Mapped[str] = mapped_column(String(100), nullable=False, default="ANA DEPO")
    iade_odeme_tutari: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False, default=0)
    iade_odeme_sekli: Mapped[str | None] = mapped_column(String(50), nullable=True)
    iade_odeme_hesabi: Mapped[str | None] = mapped_column(String(100), nullable=True)
    aciklama: Mapped[str | None] = mapped_column(Text, nullable=True)
    olusturma_tarihi: Mapped[datetime] = mapped_column(DateTime, default=datetime.now, nullable=False)

    cari = relationship("Cari")
    kaynak_fatura = relationship("SatisFaturasi")
    satirlar: Mapped[list["SatisIadeFaturasiSatiri"]] = relationship(
        "SatisIadeFaturasiSatiri", back_populates="iade", cascade="all, delete-orphan"
    )


class SatisIadeFaturasiSatiri(Base):
    __tablename__ = "satis_iade_faturasi_satirlari"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    iade_id: Mapped[int] = mapped_column(ForeignKey("satis_iade_faturalari.id"), nullable=False, index=True)
    kaynak_fatura_satiri_id: Mapped[int | None] = mapped_column(
        ForeignKey("satis_faturasi_satirlari.id"), nullable=True, index=True
    )
    urun_kodu: Mapped[str] = mapped_column(String(50), nullable=False)
    urun_adi: Mapped[str] = mapped_column(String(200), nullable=False)
    miktar: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False)
    birim: Mapped[str] = mapped_column(String(20), nullable=False)
    birim_fiyat: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False)
    iskonto_orani: Mapped[Decimal] = mapped_column(Numeric(7, 2), nullable=False, default=0)
    kdv_orani: Mapped[Decimal] = mapped_column(Numeric(7, 2), nullable=False, default=20)
    onceki_alis_fiyati: Mapped[Decimal | None] = mapped_column(Numeric(18, 4), nullable=True)
    onceki_fatura_no: Mapped[str | None] = mapped_column(String(30), nullable=True)
    fifo_birim_maliyeti: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False, default=0)
    lot_no: Mapped[str | None] = mapped_column(String(100), nullable=True)

    iade: Mapped["SatisIadeFaturasi"] = relationship("SatisIadeFaturasi", back_populates="satirlar")
