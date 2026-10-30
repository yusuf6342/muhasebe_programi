"""Üretim modülü — reçete, emir, sarf ve mamul giriş modelleri.

Paket üretiminden (StokPaket*) bağımsız; stok hareketleri mevcut StokService üzerinden.
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    ForeignKey,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from database.database import Base


class UretimRecete(Base):
    __tablename__ = "uretim_receteler"
    __table_args__ = (
        UniqueConstraint("recete_kodu", "surum", name="uq_uretim_recete_kod_surum"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    recete_kodu: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    mamul_stok_id: Mapped[int] = mapped_column(
        ForeignKey("stok_kartlari.id"), nullable=False, index=True
    )
    mamul_stok_kodu: Mapped[str] = mapped_column(String(50), nullable=False)
    esas_miktar: Mapped[Decimal] = mapped_column(Numeric(18, 6), nullable=False, default=1)
    cikti_birimi: Mapped[str] = mapped_column(String(30), nullable=False, default="Adet")
    surum: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    durum: Mapped[str] = mapped_column(String(20), nullable=False, default="TASLAK", index=True)
    # TASLAK | AKTIF | PASIF
    gecerlilik_baslangic: Mapped[date | None] = mapped_column(Date, nullable=True)
    gecerlilik_bitis: Mapped[date | None] = mapped_column(Date, nullable=True)
    aciklama: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.now)
    updated_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    is_deleted: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    satirlar: Mapped[list[UretimReceteSatir]] = relationship(
        "UretimReceteSatir",
        back_populates="recete",
        cascade="all, delete-orphan",
        order_by="UretimReceteSatir.sira",
    )


class UretimReceteSatir(Base):
    __tablename__ = "uretim_recete_satirlari"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    recete_id: Mapped[int] = mapped_column(
        ForeignKey("uretim_receteler.id"), nullable=False, index=True
    )
    sira: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    malzeme_stok_id: Mapped[int] = mapped_column(
        ForeignKey("stok_kartlari.id"), nullable=False, index=True
    )
    malzeme_stok_kodu: Mapped[str] = mapped_column(String(50), nullable=False)
    birim: Mapped[str] = mapped_column(String(30), nullable=False, default="Adet")
    net_miktar: Mapped[Decimal] = mapped_column(Numeric(18, 6), nullable=False, default=0)
    fire_orani: Mapped[Decimal] = mapped_column(Numeric(8, 4), nullable=False, default=0)
    # 0–0.9999; brüt = net / (1 - fire)
    kaynak_depo: Mapped[str | None] = mapped_column(String(100), nullable=True)
    aciklama: Mapped[str | None] = mapped_column(String(300), nullable=True)

    recete: Mapped[UretimRecete] = relationship("UretimRecete", back_populates="satirlar")


class UretimEmri(Base):
    __tablename__ = "uretim_emirleri"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    emir_no: Mapped[str] = mapped_column(String(30), unique=True, nullable=False)
    tarih: Mapped[date] = mapped_column(Date, nullable=False)
    uretim_bicimi: Mapped[str] = mapped_column(String(20), nullable=False, default="HIZLI")
    # HIZLI | ASAMALI
    recete_id: Mapped[int] = mapped_column(
        ForeignKey("uretim_receteler.id"), nullable=False, index=True
    )
    recete_surum: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    mamul_stok_id: Mapped[int] = mapped_column(
        ForeignKey("stok_kartlari.id"), nullable=False, index=True
    )
    mamul_stok_kodu: Mapped[str] = mapped_column(String(50), nullable=False)
    planlanan_miktar: Mapped[Decimal] = mapped_column(Numeric(18, 6), nullable=False)
    birim: Mapped[str] = mapped_column(String(30), nullable=False, default="Adet")
    kaynak_depo: Mapped[str] = mapped_column(String(100), nullable=False, default="ANA DEPO")
    mamul_depo: Mapped[str] = mapped_column(String(100), nullable=False, default="ANA DEPO")
    durum: Mapped[str] = mapped_column(String(30), nullable=False, default="PLANLANDI", index=True)
    # PLANLANDI | MALZEME_VERILDI | KISMI | KAPALI | IPTAL
    maliyet_durumu: Mapped[str] = mapped_column(String(20), nullable=False, default="TAHMINI")
    # TAHMINI | GECICI | KESIN
    muhasebe_durumu: Mapped[str] = mapped_column(String(20), nullable=False, default="BEKLIYOR")
    # BEKLIYOR | ISLENDI | HATA
    uretilen_miktar: Mapped[Decimal] = mapped_column(Numeric(18, 6), nullable=False, default=0)
    tahmini_maliyet: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False, default=0)
    gercek_maliyet: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False, default=0)
    aciklama: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.now)
    updated_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    is_deleted: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    plan_satirlari: Mapped[list[UretimEmriPlanSatir]] = relationship(
        "UretimEmriPlanSatir",
        back_populates="emir",
        cascade="all, delete-orphan",
        order_by="UretimEmriPlanSatir.sira",
    )


class UretimEmriPlanSatir(Base):
    """Emir açılırken reçeteden kopyalanır; sonraki reçete değişikliği etkilemez."""

    __tablename__ = "uretim_emri_plan_satirlari"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    emir_id: Mapped[int] = mapped_column(
        ForeignKey("uretim_emirleri.id"), nullable=False, index=True
    )
    sira: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    malzeme_stok_id: Mapped[int] = mapped_column(
        ForeignKey("stok_kartlari.id"), nullable=False, index=True
    )
    malzeme_stok_kodu: Mapped[str] = mapped_column(String(50), nullable=False)
    birim: Mapped[str] = mapped_column(String(30), nullable=False, default="Adet")
    plan_miktar: Mapped[Decimal] = mapped_column(Numeric(18, 6), nullable=False, default=0)
    fire_orani: Mapped[Decimal] = mapped_column(Numeric(8, 4), nullable=False, default=0)
    kaynak_depo: Mapped[str | None] = mapped_column(String(100), nullable=True)
    aciklama: Mapped[str | None] = mapped_column(String(300), nullable=True)

    emir: Mapped[UretimEmri] = relationship("UretimEmri", back_populates="plan_satirlari")


class UretimSarfFisi(Base):
    __tablename__ = "uretim_sarf_fisleri"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    fis_no: Mapped[str] = mapped_column(String(30), unique=True, nullable=False)
    emir_id: Mapped[int] = mapped_column(
        ForeignKey("uretim_emirleri.id"), nullable=False, index=True
    )
    tarih: Mapped[date] = mapped_column(Date, nullable=False)
    depo: Mapped[str] = mapped_column(String(100), nullable=False, default="ANA DEPO")
    toplam_maliyet: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False, default=0)
    aciklama: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.now)
    is_deleted: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    satirlar: Mapped[list[UretimSarfSatir]] = relationship(
        "UretimSarfSatir",
        back_populates="fis",
        cascade="all, delete-orphan",
    )


class UretimSarfSatir(Base):
    __tablename__ = "uretim_sarf_satirlari"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    fis_id: Mapped[int] = mapped_column(
        ForeignKey("uretim_sarf_fisleri.id"), nullable=False, index=True
    )
    malzeme_stok_id: Mapped[int] = mapped_column(ForeignKey("stok_kartlari.id"), nullable=False)
    malzeme_stok_kodu: Mapped[str] = mapped_column(String(50), nullable=False)
    miktar: Mapped[Decimal] = mapped_column(Numeric(18, 6), nullable=False)
    birim: Mapped[str] = mapped_column(String(30), nullable=False, default="Adet")
    birim_maliyet: Mapped[Decimal] = mapped_column(Numeric(18, 6), nullable=False, default=0)
    tutar: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False, default=0)
    lot_cikisi: Mapped[str | None] = mapped_column(String(200), nullable=True)

    fis: Mapped[UretimSarfFisi] = relationship("UretimSarfFisi", back_populates="satirlar")


class UretimRezervasyon(Base):
    """Plan rezervasyonu — stok hareketi / muhasebe üretmez; kullanılabilir stoğu ayırır."""

    __tablename__ = "uretim_rezervasyonlar"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    emir_id: Mapped[int] = mapped_column(
        ForeignKey("uretim_emirleri.id"), nullable=False, index=True
    )
    malzeme_stok_kodu: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    depo: Mapped[str] = mapped_column(String(100), nullable=False, default="ANA DEPO")
    miktar: Mapped[Decimal] = mapped_column(Numeric(18, 6), nullable=False, default=0)
    # Ayrılan; sarf ile azalır, iptal/kapanışta serbest
    durum: Mapped[str] = mapped_column(String(20), nullable=False, default="AKTIF")
    # AKTIF | SERBEST | TUKETILDI
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.now)
    updated_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class UretimMamulGiris(Base):
    __tablename__ = "uretim_mamul_girisleri"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    fis_no: Mapped[str] = mapped_column(String(30), unique=True, nullable=False)
    emir_id: Mapped[int] = mapped_column(
        ForeignKey("uretim_emirleri.id"), nullable=False, index=True
    )
    tarih: Mapped[date] = mapped_column(Date, nullable=False)
    mamul_stok_id: Mapped[int] = mapped_column(ForeignKey("stok_kartlari.id"), nullable=False)
    mamul_stok_kodu: Mapped[str] = mapped_column(String(50), nullable=False)
    miktar: Mapped[Decimal] = mapped_column(Numeric(18, 6), nullable=False)
    birim: Mapped[str] = mapped_column(String(30), nullable=False, default="Adet")
    depo: Mapped[str] = mapped_column(String(100), nullable=False, default="ANA DEPO")
    birim_maliyet: Mapped[Decimal] = mapped_column(Numeric(18, 6), nullable=False, default=0)
    toplam_maliyet: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False, default=0)
    parti_no: Mapped[str | None] = mapped_column(String(60), nullable=True)
    lot_girisi: Mapped[str | None] = mapped_column(String(80), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.now)
    is_deleted: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
