from datetime import date, datetime
from decimal import Decimal
from typing import TYPE_CHECKING

from sqlalchemy import Boolean, Date, DateTime, ForeignKey, Integer, Numeric, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from database.database import Base

if TYPE_CHECKING:
    from database.models.cari import Cari


class SatisSiparisi(Base):
    __tablename__ = "satis_siparisleri"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    siparis_no: Mapped[str] = mapped_column(String(30), unique=True, nullable=False)
    siparis_tarihi: Mapped[date] = mapped_column(Date, nullable=False)
    termin_tarihi: Mapped[date] = mapped_column(Date, nullable=False)
    cari_id: Mapped[int] = mapped_column(ForeignKey("cari_kartlar.id"), nullable=False, index=True)
    maliyet_yontemi: Mapped[str] = mapped_column(String(50), nullable=False)
    hedef_kar_marji: Mapped[Decimal] = mapped_column(Numeric(7, 2), nullable=False, default=0)
    aciklama: Mapped[str | None] = mapped_column(Text, nullable=True)
    durum: Mapped[str] = mapped_column(String(30), nullable=False, default="TASLAK")
    olusturma_tarihi: Mapped[datetime] = mapped_column(DateTime, default=datetime.now, nullable=False)
    # İşlemi yapan kullanıcı (migration ile eklenir; eski kayıtlar NULL)
    created_by_user_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_by_username: Mapped[str | None] = mapped_column(String(80), nullable=True)
    created_by_full_name: Mapped[str | None] = mapped_column(String(120), nullable=True)
    updated_by_user_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    updated_by_username: Mapped[str | None] = mapped_column(String(80), nullable=True)
    updated_by_full_name: Mapped[str | None] = mapped_column(String(120), nullable=True)
    updated_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    approved_by_user_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    approved_by_full_name: Mapped[str | None] = mapped_column(String(120), nullable=True)
    approved_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    cancelled_by_user_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    cancelled_by_full_name: Mapped[str | None] = mapped_column(String(120), nullable=True)
    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    cancellation_reason: Mapped[str | None] = mapped_column(String(500), nullable=True)

    cari: Mapped["Cari"] = relationship("Cari")
    satirlar: Mapped[list["SatisSiparisiSatiri"]] = relationship(
        "SatisSiparisiSatiri", back_populates="siparis", cascade="all, delete-orphan"
    )
    tahsilatlar: Mapped[list["SatisSiparisiTahsilati"]] = relationship(
        "SatisSiparisiTahsilati", back_populates="siparis", cascade="all, delete-orphan"
    )


class SatisSiparisiSatiri(Base):
    __tablename__ = "satis_siparisi_satirlari"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    siparis_id: Mapped[int] = mapped_column(ForeignKey("satis_siparisleri.id"), nullable=False, index=True)
    urun_kodu: Mapped[str] = mapped_column(String(50), nullable=False)
    urun_adi: Mapped[str] = mapped_column(String(200), nullable=False)
    aciklama: Mapped[str | None] = mapped_column(String(500), nullable=True)
    miktar: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False)
    birim: Mapped[str] = mapped_column(String(20), nullable=False)
    birim_satis_fiyati: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False)
    iskonto_orani: Mapped[Decimal] = mapped_column(Numeric(7, 2), nullable=False, default=0)
    kdv_orani: Mapped[Decimal] = mapped_column(Numeric(7, 2), nullable=False, default=20)
    fifo_birim_maliyeti: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False, default=0)
    son_alis_birim_maliyeti: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False, default=0)
    ortalama_birim_maliyeti: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False, default=0)
    agirlikli_ortalama_birim_maliyeti: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False, default=0)
    irsaliyelenen_miktar: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False, default=0)
    faturalanan_miktar: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False, default=0)
    irsaliye_belge_baglantisi: Mapped[str | None] = mapped_column(String(100), nullable=True)
    fatura_belge_baglantisi: Mapped[str | None] = mapped_column(String(100), nullable=True)
    is_manual_item: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    line_type: Mapped[str] = mapped_column(String(30), nullable=False, default="STOCK_PRODUCT")
    product_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    delivery_term_days: Mapped[int | None] = mapped_column(Integer, nullable=True)
    estimated_delivery_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    delivery_term_note: Mapped[str | None] = mapped_column(String(300), nullable=True)
    stock_pending: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    siparis: Mapped["SatisSiparisi"] = relationship("SatisSiparisi", back_populates="satirlar")


class SatisSiparisiTahsilati(Base):
    __tablename__ = "satis_siparisi_tahsilatlari"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    siparis_id: Mapped[int] = mapped_column(ForeignKey("satis_siparisleri.id"), nullable=False, index=True)
    tahsilat_tarihi: Mapped[date] = mapped_column(Date, nullable=False)
    tutar: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    odeme_sekli: Mapped[str] = mapped_column(String(30), nullable=False)
    hesap: Mapped[str | None] = mapped_column(String(100), nullable=True)
    aciklama: Mapped[str | None] = mapped_column(String(500), nullable=True)

    siparis: Mapped["SatisSiparisi"] = relationship("SatisSiparisi", back_populates="tahsilatlar")
