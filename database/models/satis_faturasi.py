from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import Date, DateTime, ForeignKey, Numeric, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from database.database import Base


class SatisFaturasi(Base):
    __tablename__ = "satis_faturalari"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    fatura_no: Mapped[str] = mapped_column(String(30), unique=True, nullable=False)
    fatura_tarihi: Mapped[date] = mapped_column(Date, nullable=False)
    islem_saati: Mapped[str | None] = mapped_column(String(8), nullable=True)
    vade_gunu: Mapped[int] = mapped_column(nullable=False, default=0)
    vade_tarihi: Mapped[date] = mapped_column(Date, nullable=False)
    cari_id: Mapped[int] = mapped_column(ForeignKey("cari_kartlar.id"), nullable=False, index=True)
    siparis_id: Mapped[int | None] = mapped_column(ForeignKey("satis_siparisleri.id"), nullable=True, index=True)
    irsaliye_id: Mapped[int | None] = mapped_column(ForeignKey("satis_irsaliyeleri.id"), nullable=True, index=True)
    durum: Mapped[str] = mapped_column(String(20), nullable=False, default="AÇIK")
    depo: Mapped[str] = mapped_column(String(100), nullable=False, default="ANA DEPO")
    tahsilat_tutari: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False, default=0)
    tahsilat_sekli: Mapped[str | None] = mapped_column(String(50), nullable=True)
    tahsilat_hesabi: Mapped[str | None] = mapped_column(String(100), nullable=True)
    aciklama: Mapped[str | None] = mapped_column(Text, nullable=True)
    dokuman_yolu: Mapped[str | None] = mapped_column(String(500), nullable=True)
    olusturma_tarihi: Mapped[datetime] = mapped_column(DateTime, default=datetime.now, nullable=False)

    cari = relationship("Cari")
    siparis = relationship("SatisSiparisi")
    irsaliye = relationship("SatisIrsaliyesi")
    satirlar: Mapped[list["SatisFaturasiSatiri"]] = relationship(
        "SatisFaturasiSatiri", back_populates="fatura", cascade="all, delete-orphan"
    )


class SatisFaturasiSatiri(Base):
    __tablename__ = "satis_faturasi_satirlari"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    fatura_id: Mapped[int] = mapped_column(ForeignKey("satis_faturalari.id"), nullable=False, index=True)
    siparis_satiri_id: Mapped[int | None] = mapped_column(ForeignKey("satis_siparisi_satirlari.id"), nullable=True, index=True)
    irsaliye_satiri_id: Mapped[int | None] = mapped_column(ForeignKey("satis_irsaliyesi_satirlari.id"), nullable=True, index=True)
    urun_kodu: Mapped[str] = mapped_column(String(50), nullable=False)
    urun_adi: Mapped[str] = mapped_column(String(200), nullable=False)
    barkod: Mapped[str | None] = mapped_column(String(100), nullable=True)
    aciklama: Mapped[str | None] = mapped_column(String(500), nullable=True)
    lot_no: Mapped[str | None] = mapped_column(String(100), nullable=True)
    lot_cikisi: Mapped[str | None] = mapped_column(String(100), nullable=True)
    miktar: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False)
    birim: Mapped[str] = mapped_column(String(20), nullable=False)
    birim_fiyat: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False)
    iskonto_orani: Mapped[Decimal] = mapped_column(Numeric(7, 2), nullable=False, default=0)
    kdv_orani: Mapped[Decimal] = mapped_column(Numeric(7, 2), nullable=False, default=20)
    fifo_birim_maliyeti: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False, default=0)
    son_alis_birim_maliyeti: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False, default=0)
    ortalama_birim_maliyeti: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False, default=0)
    agirlikli_ortalama_birim_maliyeti: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False, default=0)

    fatura: Mapped["SatisFaturasi"] = relationship("SatisFaturasi", back_populates="satirlar")
