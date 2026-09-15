"""Hızlı Satış — bekleyen (hold) sepet tabloları.

Stok hareketi yok; yalnızca bellek sepetinin DB kopyası.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, ForeignKey, Integer, Numeric, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from database.database import Base

if TYPE_CHECKING:
    pass

DURUM_BEKLIYOR = "BEKLIYOR"
DURUM_CAGIRILDI = "CAGIRILDI"
DURUM_IPTAL = "IPTAL"


class HizliSatisBekleyen(Base):
    """Bekleyen hızlı satış başlığı (stok rezervasyonu yok)."""

    __tablename__ = "hizli_satis_bekleyenler"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    etiket: Mapped[str | None] = mapped_column(String(120), nullable=True)
    cari_id: Mapped[int | None] = mapped_column(
        ForeignKey("cari_kartlar.id"), nullable=True, index=True
    )
    cari_kodu: Mapped[str | None] = mapped_column(String(50), nullable=True)
    cari_unvan: Mapped[str | None] = mapped_column(String(200), nullable=True)
    kullanici_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    kullanici_adi: Mapped[str | None] = mapped_column(String(100), nullable=True)
    durum: Mapped[str] = mapped_column(
        String(20), nullable=False, default=DURUM_BEKLIYOR, index=True
    )
    genel_toplam: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False, default=0)
    satir_sayisi: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    odeme_niyeti: Mapped[str | None] = mapped_column(String(50), nullable=True)
    not_: Mapped[str | None] = mapped_column("not", Text, nullable=True)
    olusturma_tarihi: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.now, nullable=False
    )
    guncelleme_tarihi: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.now, onupdate=datetime.now, nullable=False
    )

    satirlar: Mapped[list["HizliSatisBekleyenSatiri"]] = relationship(
        "HizliSatisBekleyenSatiri",
        back_populates="bekleyen",
        cascade="all, delete-orphan",
        order_by="HizliSatisBekleyenSatiri.sira",
    )


class HizliSatisBekleyenSatiri(Base):
    """Bekleyen sepet satırı — fiyat/iskonto/miktar kopyası (stok düşmez)."""

    __tablename__ = "hizli_satis_bekleyen_satirlari"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    bekleyen_id: Mapped[int] = mapped_column(
        ForeignKey("hizli_satis_bekleyenler.id"), nullable=False, index=True
    )
    sira: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    stok_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    stok_kodu: Mapped[str] = mapped_column(String(50), nullable=False)
    stok_adi: Mapped[str] = mapped_column(String(200), nullable=False)
    birim: Mapped[str] = mapped_column(String(20), nullable=False, default="Adet")
    miktar: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False)
    birim_fiyat: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False, default=0)
    iskonto_orani: Mapped[Decimal] = mapped_column(Numeric(7, 2), nullable=False, default=0)
    kdv_orani: Mapped[Decimal] = mapped_column(Numeric(7, 2), nullable=False, default=20)
    carpan: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False, default=1)
    barkod: Mapped[str | None] = mapped_column(String(100), nullable=True)

    bekleyen: Mapped["HizliSatisBekleyen"] = relationship(
        "HizliSatisBekleyen", back_populates="satirlar"
    )
