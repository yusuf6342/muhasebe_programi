"""Konsinye teslim / satış bildirimi / iade — stok sahipliği ile fiziksel konum ayrımı."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Optional

from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    ForeignKey,
    Integer,
    Numeric,
    String,
    Text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from database.database import Base


class KonsinyeTeslim(Base):
    """Verilen veya alınan konsinye teslim başlığı (taslak / onaylı)."""

    __tablename__ = "konsinye_teslimler"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    belge_no: Mapped[str] = mapped_column(String(40), unique=True, nullable=False, index=True)
    yon: Mapped[str] = mapped_column(String(20), nullable=False, index=True)  # VERILEN | ALINAN
    durum: Mapped[str] = mapped_column(String(30), nullable=False, default="TASLAK", index=True)
    # TASLAK | ONAYLI | KAPALI | IPTAL
    belge_tarihi: Mapped[date] = mapped_column(Date, nullable=False)
    cari_id: Mapped[int] = mapped_column(ForeignKey("cari_kartlar.id"), nullable=False, index=True)
    depo_id: Mapped[int] = mapped_column(ForeignKey("depolar.id"), nullable=False)
    aciklama: Mapped[str | None] = mapped_column(Text, nullable=True)
    olusturma_tarihi: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)
    onay_tarihi: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    olusturan: Mapped[str | None] = mapped_column(String(100), nullable=True)
    onaylayan: Mapped[str | None] = mapped_column(String(100), nullable=True)

    satirlar: Mapped[list["KonsinyeTeslimSatiri"]] = relationship(
        "KonsinyeTeslimSatiri", back_populates="teslim", cascade="all, delete-orphan"
    )


class KonsinyeTeslimSatiri(Base):
    """Teslim satırı — miktar temel birimde; kalan / bildirilen / faturalanan ayrı."""

    __tablename__ = "konsinye_teslim_satirlari"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    teslim_id: Mapped[int] = mapped_column(
        ForeignKey("konsinye_teslimler.id"), nullable=False, index=True
    )
    stok_id: Mapped[int] = mapped_column(ForeignKey("stok_kartlari.id"), nullable=False, index=True)
    stok_kodu: Mapped[str] = mapped_column(String(50), nullable=False)
    stok_adi: Mapped[str] = mapped_column(String(200), nullable=False)
    birim: Mapped[str] = mapped_column(String(30), nullable=False, default="Adet")
    birim_carpani: Mapped[Decimal] = mapped_column(Numeric(18, 6), nullable=False, default=1)
    miktar: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False)  # işlem biriminde
    temel_miktar: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False)  # temel birim
    birim_fiyat: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False, default=0)
    # Anlaşılan satış/alış fiyatı (stok maliyetinden ayrı)
    fifo_birim_maliyet: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False, default=0)
    lot_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    lot_no: Mapped[str | None] = mapped_column(String(100), nullable=True)
    # İzleme (temel birim)
    kalan_miktar: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False, default=0)
    bildirilen_miktar: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False, default=0)
    faturalanan_miktar: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False, default=0)
    # Taslak faturaya ayrılan (henüz onaylanmamış) miktar
    taslak_ayrilan_miktar: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False, default=0)
    iade_miktar: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False, default=0)

    teslim: Mapped["KonsinyeTeslim"] = relationship("KonsinyeTeslim", back_populates="satirlar")


class KonsinyeHareket(Base):
    """Satış bildirimi / iade / fatura bağlama — mükerrer miktar engeli."""

    __tablename__ = "konsinye_hareketler"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    teslim_satiri_id: Mapped[int] = mapped_column(
        ForeignKey("konsinye_teslim_satirlari.id"), nullable=False, index=True
    )
    hareket_turu: Mapped[str] = mapped_column(String(30), nullable=False, index=True)
    # SATIS_BILDIRIM | IADE | KESIN_AL | FATURA_TASLAK | FATURA_ONAY
    miktar: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False)  # temel birim
    gercek_tarih: Mapped[date | None] = mapped_column(Date, nullable=True)
    kayit_tarihi: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)
    belge_no: Mapped[str | None] = mapped_column(String(40), nullable=True)
    belge_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # SATIS | ALIS — gerçek fatura türü; boşsa bağlanmamış sayılır
    fatura_turu: Mapped[str | None] = mapped_column(String(20), nullable=True, index=True)
    fatura_satir_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    aciklama: Mapped[str | None] = mapped_column(String(300), nullable=True)
    iptal: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    olusturan: Mapped[str | None] = mapped_column(String(100), nullable=True)
    # Mükerrer bağlama engeli (iptal edilmemiş kayıtlar)
    islem_anahtari: Mapped[str | None] = mapped_column(String(120), nullable=True, index=True)
