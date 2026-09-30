"""Masraf dağıtımı — kayıtlı gider belgesini alış maliyetlerine aktarma."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import Date, DateTime, ForeignKey, Integer, Numeric, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from database.database import Base


class MasrafDagitim(Base):
    __tablename__ = "masraf_dagitimlari"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    dagitim_no: Mapped[str] = mapped_column(String(30), unique=True, nullable=False, index=True)
    dagitim_tarihi: Mapped[date] = mapped_column(Date, nullable=False)
    # HIZMET_FATURASI (hizmet alış / gider faturası)
    kaynak_turu: Mapped[str] = mapped_column(String(30), nullable=False, index=True)
    kaynak_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    kaynak_no: Mapped[str] = mapped_column(String(50), nullable=False)
    kaynak_cari_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    yontem: Mapped[str] = mapped_column(String(20), nullable=False, default="TUTAR")
    tutar: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False, default=0)
    para_birimi: Mapped[str] = mapped_column(String(3), nullable=False, default="TRY")
    kur: Mapped[Decimal] = mapped_column(Numeric(18, 6), nullable=False, default=1)
    # TASLAK | ONAYLANDI | İPTAL EDİLDİ
    durum: Mapped[str] = mapped_column(String(20), nullable=False, default="TASLAK", index=True)
    aciklama: Mapped[str | None] = mapped_column(Text, nullable=True)
    onizleme_imza: Mapped[str | None] = mapped_column(String(64), nullable=True)
    row_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    stok_payi: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False, default=0)
    smm_payi: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False, default=0)
    iade_payi: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False, default=0)
    fis_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    ters_fis_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    olusturan: Mapped[str | None] = mapped_column(String(120), nullable=True)
    olusturma_tarihi: Mapped[datetime] = mapped_column(DateTime, default=datetime.now, nullable=False)
    guncelleme_tarihi: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    onaylayan: Mapped[str | None] = mapped_column(String(120), nullable=True)
    onay_tarihi: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    geri_alan: Mapped[str | None] = mapped_column(String(120), nullable=True)
    geri_alma_tarihi: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    geri_alma_nedeni: Mapped[str | None] = mapped_column(String(300), nullable=True)

    kaynak_satirlari: Mapped[list["MasrafDagitimKaynakSatiri"]] = relationship(
        "MasrafDagitimKaynakSatiri",
        back_populates="dagitim",
        cascade="all, delete-orphan",
        order_by="MasrafDagitimKaynakSatiri.id",
    )
    satirlar: Mapped[list["MasrafDagitimSatiri"]] = relationship(
        "MasrafDagitimSatiri",
        back_populates="dagitim",
        cascade="all, delete-orphan",
        order_by="MasrafDagitimSatiri.id",
    )


class MasrafDagitimKaynakSatiri(Base):
    """Kaynak gider belgesinin hangi satırından ne kadar dağıtıldığı."""

    __tablename__ = "masraf_dagitim_kaynak_satirlari"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    dagitim_id: Mapped[int] = mapped_column(
        ForeignKey("masraf_dagitimlari.id"), nullable=False, index=True
    )
    kaynak_satir_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    aciklama: Mapped[str | None] = mapped_column(String(250), nullable=True)
    tutar: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False, default=0)

    dagitim: Mapped["MasrafDagitim"] = relationship("MasrafDagitim", back_populates="kaynak_satirlari")


class MasrafDagitimSatiri(Base):
    """Hedef alış faturası satırı (FIFO katmanı) ve aldığı pay."""

    __tablename__ = "masraf_dagitim_satirlari"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    dagitim_id: Mapped[int] = mapped_column(
        ForeignKey("masraf_dagitimlari.id"), nullable=False, index=True
    )
    alis_fatura_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    alis_fatura_satiri_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    alis_fatura_no: Mapped[str] = mapped_column(String(50), nullable=False)
    urun_kodu: Mapped[str] = mapped_column(String(50), nullable=False)
    urun_adi: Mapped[str] = mapped_column(String(200), nullable=False)
    depo: Mapped[str | None] = mapped_column(String(100), nullable=True)
    birim: Mapped[str | None] = mapped_column(String(20), nullable=True)
    lot_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    ana_miktar: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False, default=0)
    alis_tutari: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False, default=0)
    olcu: Mapped[Decimal | None] = mapped_column(Numeric(18, 6), nullable=True)
    elle_tutar: Mapped[Decimal | None] = mapped_column(Numeric(18, 2), nullable=True)
    baz: Mapped[Decimal] = mapped_column(Numeric(24, 6), nullable=False, default=0)
    pay: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False, default=0)
    eski_birim_maliyet: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False, default=0)
    yeni_birim_maliyet: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False, default=0)
    stok_payi: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False, default=0)
    smm_payi: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False, default=0)
    iade_payi: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False, default=0)

    dagitim: Mapped["MasrafDagitim"] = relationship("MasrafDagitim", back_populates="satirlar")


class MasrafDagitimGecmisi(Base):
    __tablename__ = "masraf_dagitim_gecmisi"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    dagitim_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    islem: Mapped[str] = mapped_column(String(40), nullable=False)
    detay: Mapped[str | None] = mapped_column(Text, nullable=True)
    kullanici: Mapped[str | None] = mapped_column(String(120), nullable=True)
    tarih: Mapped[datetime] = mapped_column(DateTime, default=datetime.now, nullable=False)
