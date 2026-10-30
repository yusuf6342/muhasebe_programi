"""Lot'a bağlı barkod ve etiket baskı kuyruğu (Code 128, L########)."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    Boolean,
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


class StokLotBarkodu(Base):
    """Ürün + lot + birim için değişmez Code 128 kayıt kodu (örn. L00001234)."""

    __tablename__ = "stok_lot_barkodlari"
    __table_args__ = (
        UniqueConstraint("barkod", name="uq_stok_lot_barkod_kod"),
        UniqueConstraint(
            "stok_id", "lot_id", "birim", "katsayi_surum",
            name="uq_stok_lot_barkod_aktif_eslesme",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    barkod: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    stok_id: Mapped[int] = mapped_column(ForeignKey("stok_kartlari.id"), nullable=False, index=True)
    lot_id: Mapped[int] = mapped_column(ForeignKey("stok_lotlari.id"), nullable=False, index=True)
    birim: Mapped[str] = mapped_column(String(30), nullable=False, default="Adet")
    birim_carpani: Mapped[Decimal] = mapped_column(Numeric(18, 6), nullable=False, default=1)
    katsayi_surum: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    aktif: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    olusturma_tarihi: Mapped[datetime] = mapped_column(DateTime, default=datetime.now, nullable=False)
    olusturan: Mapped[str | None] = mapped_column(String(100), nullable=True)

    stok = relationship("StokKarti", foreign_keys=[stok_id])
    lot = relationship("StokLotu", foreign_keys=[lot_id])


class StokLotBarkodSayac(Base):
    """Tek satırlık barkod sıra sayacı (L + 8 hane)."""

    __tablename__ = "stok_lot_barkod_sayac"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    son_no: Mapped[int] = mapped_column(Integer, nullable=False, default=0)


class StokEtiketIsi(Base):
    """Mal girişinden sonra oluşan etiket baskı işi."""

    __tablename__ = "stok_etiket_isleri"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    kaynak_tur: Mapped[str] = mapped_column(String(40), nullable=False)  # ALIS_FATURA, ...
    kaynak_belge_no: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    kaynak_belge_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    durum: Mapped[str] = mapped_column(String(40), nullable=False, default="ETIKET_BEKLIYOR")
    olusturma_tarihi: Mapped[datetime] = mapped_column(DateTime, default=datetime.now, nullable=False)
    olusturan: Mapped[str | None] = mapped_column(String(100), nullable=True)
    tamamlayan: Mapped[str | None] = mapped_column(String(100), nullable=True)
    tamamlanma_tarihi: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    notlar: Mapped[str | None] = mapped_column(Text, nullable=True)

    satirlar: Mapped[list["StokEtiketIsSatiri"]] = relationship(
        "StokEtiketIsSatiri", back_populates="is_", cascade="all, delete-orphan"
    )


class StokEtiketIsSatiri(Base):
    __tablename__ = "stok_etiket_is_satirlari"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    is_id: Mapped[int] = mapped_column(ForeignKey("stok_etiket_isleri.id"), nullable=False, index=True)
    lot_barkod_id: Mapped[int] = mapped_column(
        ForeignKey("stok_lot_barkodlari.id"), nullable=False, index=True
    )
    stok_id: Mapped[int] = mapped_column(ForeignKey("stok_kartlari.id"), nullable=False)
    lot_id: Mapped[int] = mapped_column(ForeignKey("stok_lotlari.id"), nullable=False)
    birim: Mapped[str] = mapped_column(String(30), nullable=False)
    giren_miktar: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False, default=0)
    etiket_adedi: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    # Baskı anlık görüntüsü
    urun_adi: Mapped[str | None] = mapped_column(String(200), nullable=True)
    satis_fiyati: Mapped[Decimal | None] = mapped_column(Numeric(18, 4), nullable=True)
    para_birimi: Mapped[str] = mapped_column(String(3), nullable=False, default="TRY")
    kdv_dahil: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    durum: Mapped[str] = mapped_column(String(40), nullable=False, default="ETIKET_BEKLIYOR")
    basilan_adet: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    son_baski_tarihi: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    is_ = relationship("StokEtiketIsi", back_populates="satirlar")
    lot_barkod = relationship("StokLotBarkodu", foreign_keys=[lot_barkod_id])
