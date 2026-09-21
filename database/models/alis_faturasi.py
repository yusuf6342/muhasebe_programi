from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import Boolean, Date, DateTime, ForeignKey, Numeric, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from database.database import Base


class AlisFaturasi(Base):
    __tablename__ = "alis_faturalari"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    fatura_no: Mapped[str] = mapped_column(String(30), unique=True, nullable=False)
    fatura_tarihi: Mapped[date] = mapped_column(Date, nullable=False)
    islem_saati: Mapped[str | None] = mapped_column(String(8), nullable=True)
    vade_gunu: Mapped[int] = mapped_column(nullable=False, default=0)
    vade_tarihi: Mapped[date] = mapped_column(Date, nullable=False)
    cari_id: Mapped[int] = mapped_column(ForeignKey("cari_kartlar.id"), nullable=False, index=True)
    siparis_id: Mapped[int | None] = mapped_column(ForeignKey("alis_siparisleri.id"), nullable=True, index=True)
    irsaliye_id: Mapped[int | None] = mapped_column(ForeignKey("alis_irsaliyeleri.id"), nullable=True, index=True)
    durum: Mapped[str] = mapped_column(String(20), nullable=False, default="AÇIK")
    depo: Mapped[str] = mapped_column(String(100), nullable=False, default="ANA DEPO")
    odeme_tutari: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False, default=0)
    odeme_sekli: Mapped[str | None] = mapped_column(String(50), nullable=True)
    odeme_hesabi: Mapped[str | None] = mapped_column(String(100), nullable=True)
    aciklama: Mapped[str | None] = mapped_column(Text, nullable=True)
    dokuman_yolu: Mapped[str | None] = mapped_column(String(500), nullable=True)
    para_birimi: Mapped[str] = mapped_column(String(3), nullable=False, default="TRY")
    kur: Mapped[Decimal] = mapped_column(Numeric(18, 6), nullable=False, default=1)
    kur_tarihi: Mapped[date | None] = mapped_column(Date, nullable=True)
    kur_turu: Mapped[str] = mapped_column(String(30), nullable=False, default="forex_selling")
    kur_kaynagi: Mapped[str] = mapped_column(String(20), nullable=False, default="TCMB")
    kur_sabitlendi: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    doviz_ara_toplam: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False, default=0)
    tl_matrah: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False, default=0)
    tl_kdv: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False, default=0)
    tl_genel_toplam: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False, default=0)
    tl_brut_toplam: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False, default=0)
    genel_islem_turu: Mapped[str | None] = mapped_column(String(20), nullable=True)
    genel_islem_orani: Mapped[Decimal] = mapped_column(Numeric(12, 6), nullable=False, default=0)
    genel_islem_tutari: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False, default=0)
    row_version: Mapped[int] = mapped_column(nullable=False, default=1)
    olusturma_tarihi: Mapped[datetime] = mapped_column(DateTime, default=datetime.now, nullable=False)

    cari = relationship("Cari")
    siparis = relationship("AlisSiparisi")
    irsaliye = relationship("AlisIrsaliyesi")
    satirlar: Mapped[list["AlisFaturasiSatiri"]] = relationship(
        "AlisFaturasiSatiri", back_populates="fatura", cascade="all, delete-orphan"
    )


class AlisFaturasiSatiri(Base):
    __tablename__ = "alis_faturasi_satirlari"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    fatura_id: Mapped[int] = mapped_column(ForeignKey("alis_faturalari.id"), nullable=False, index=True)
    siparis_satiri_id: Mapped[int | None] = mapped_column(ForeignKey("alis_siparisi_satirlari.id"), nullable=True, index=True)
    irsaliye_satiri_id: Mapped[int | None] = mapped_column(ForeignKey("alis_irsaliyesi_satirlari.id"), nullable=True, index=True)
    urun_kodu: Mapped[str] = mapped_column(String(50), nullable=False)
    urun_adi: Mapped[str] = mapped_column(String(200), nullable=False)
    barkod: Mapped[str | None] = mapped_column(String(100), nullable=True)
    aciklama: Mapped[str | None] = mapped_column(String(500), nullable=True)
    lot_no: Mapped[str | None] = mapped_column(String(100), nullable=True)
    lot_girisi: Mapped[str | None] = mapped_column(String(100), nullable=True)
    miktar: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False)
    birim: Mapped[str] = mapped_column(String(20), nullable=False)
    birim_fiyat: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False)
    iskonto_orani: Mapped[Decimal] = mapped_column(Numeric(7, 2), nullable=False, default=0)
    iskonto_orani_2: Mapped[Decimal] = mapped_column(Numeric(7, 2), nullable=False, default=0)
    iskonto_orani_3: Mapped[Decimal] = mapped_column(Numeric(7, 2), nullable=False, default=0)
    kdv_orani: Mapped[Decimal] = mapped_column(Numeric(7, 2), nullable=False, default=20)
    fifo_birim_maliyeti: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False, default=0)
    birim_fiyat_doviz: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False, default=0)
    tl_birim_fiyat: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False, default=0)
    tl_tutar: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False, default=0)

    fatura: Mapped["AlisFaturasi"] = relationship("AlisFaturasi", back_populates="satirlar")
