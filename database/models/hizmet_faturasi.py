"""Hizmet alış (gider) / hizmet satış (gelir) faturaları."""

from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import Date, DateTime, ForeignKey, Integer, Numeric, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from database.database import Base


class HizmetFaturasi(Base):
    __tablename__ = "hizmet_faturalari"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    fatura_no: Mapped[str] = mapped_column(String(30), unique=True, nullable=False, index=True)
    # GIDER = Hizmet Alış | GELIR = Hizmet Satış
    fatura_turu: Mapped[str] = mapped_column(String(10), nullable=False, index=True)
    fatura_tarihi: Mapped[date] = mapped_column(Date, nullable=False)
    islem_saati: Mapped[str | None] = mapped_column(String(8), nullable=True)
    vade_gunu: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    vade_tarihi: Mapped[date] = mapped_column(Date, nullable=False)
    cari_id: Mapped[int] = mapped_column(ForeignKey("cari_kartlar.id"), nullable=False, index=True)
    durum: Mapped[str] = mapped_column(String(20), nullable=False, default="AÇIK")
    # Gider: ödeme | Gelir: tahsilat — aynı alanlarda tutulur
    odeme_tutari: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False, default=0)
    odeme_sekli: Mapped[str | None] = mapped_column(String(50), nullable=True)
    odeme_hesabi: Mapped[str | None] = mapped_column(String(100), nullable=True)
    aciklama: Mapped[str | None] = mapped_column(Text, nullable=True)
    dokuman_yolu: Mapped[str | None] = mapped_column(String(500), nullable=True)
    olusturma_tarihi: Mapped[datetime] = mapped_column(DateTime, default=datetime.now, nullable=False)

    cari = relationship("Cari")
    satirlar: Mapped[list["HizmetFaturasiSatiri"]] = relationship(
        "HizmetFaturasiSatiri",
        back_populates="fatura",
        cascade="all, delete-orphan",
    )


class HizmetFaturasiSatiri(Base):
    __tablename__ = "hizmet_faturasi_satirlari"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    fatura_id: Mapped[int] = mapped_column(ForeignKey("hizmet_faturalari.id"), nullable=False, index=True)
    hizmet_id: Mapped[int | None] = mapped_column(ForeignKey("hizmet_kartlari.id"), nullable=True, index=True)
    hizmet_kodu: Mapped[str] = mapped_column(String(50), nullable=False)
    hizmet_adi: Mapped[str] = mapped_column(String(200), nullable=False)
    aciklama: Mapped[str | None] = mapped_column(String(500), nullable=True)
    miktar: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False)
    birim: Mapped[str] = mapped_column(String(30), nullable=False, default="Adet")
    birim_fiyat: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False)
    iskonto_orani: Mapped[Decimal] = mapped_column(Numeric(7, 2), nullable=False, default=0)
    kdv_orani: Mapped[Decimal] = mapped_column(Numeric(7, 2), nullable=False, default=20)

    fatura: Mapped["HizmetFaturasi"] = relationship("HizmetFaturasi", back_populates="satirlar")
    hizmet = relationship("HizmetKarti")
