"""Satın alma talepleri — iç ihtiyaç / yeniden sipariş.

Talep stok, cari, KDV veya genel muhasebe etkisi üretmez; yalnızca alış siparişine
satır bazında (``SatinAlmaTalepSiparisBagi``) aktarılır.
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import TYPE_CHECKING

from sqlalchemy import Boolean, Date, DateTime, ForeignKey, Integer, Numeric, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from database.database import Base

if TYPE_CHECKING:
    from database.models.cari import Cari


class SatinAlmaTalep(Base):
    __tablename__ = "satin_alma_talepleri"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    talep_no: Mapped[str] = mapped_column(String(30), unique=True, nullable=False)
    talep_tarihi: Mapped[date] = mapped_column(Date, nullable=False)
    ihtiyac_tarihi: Mapped[date | None] = mapped_column(Date, nullable=True)
    isteyen_kullanici: Mapped[str | None] = mapped_column(String(120), nullable=True)
    depo: Mapped[str | None] = mapped_column(String(100), nullable=True)
    oncelik: Mapped[str] = mapped_column(String(20), nullable=False, default="NORMAL")
    durum: Mapped[str] = mapped_column(String(30), nullable=False, default="TASLAK")
    aciklama: Mapped[str | None] = mapped_column(Text, nullable=True)
    olusturma_tarihi: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.now, nullable=False
    )
    departman: Mapped[str | None] = mapped_column(String(100), nullable=True)
    talep_nedeni: Mapped[str | None] = mapped_column(String(300), nullable=True)
    proje_ref: Mapped[str | None] = mapped_column(String(100), nullable=True)
    isteyen_kullanici_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    gonderen: Mapped[str | None] = mapped_column(String(120), nullable=True)
    gonderme_tarihi: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    onaylayan: Mapped[str | None] = mapped_column(String(120), nullable=True)
    onay_tarihi: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    red_nedeni: Mapped[str | None] = mapped_column(String(300), nullable=True)
    geri_gonderme_nedeni: Mapped[str | None] = mapped_column(String(300), nullable=True)
    iptal_nedeni: Mapped[str | None] = mapped_column(String(300), nullable=True)
    row_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    guncelleme_tarihi: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    satirlar: Mapped[list["SatinAlmaTalepSatiri"]] = relationship(
        "SatinAlmaTalepSatiri",
        back_populates="talep",
        cascade="all, delete-orphan",
        order_by="SatinAlmaTalepSatiri.id",
    )


class SatinAlmaTalepSatiri(Base):
    __tablename__ = "satin_alma_talep_satirlari"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    talep_id: Mapped[int] = mapped_column(
        ForeignKey("satin_alma_talepleri.id"), nullable=False, index=True
    )
    urun_kodu: Mapped[str] = mapped_column(String(50), nullable=False)
    urun_adi: Mapped[str] = mapped_column(String(200), nullable=False)
    birim: Mapped[str] = mapped_column(String(20), nullable=False, default="Adet")
    miktar: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False)
    # Teknik açıklama / özellik
    aciklama: Mapped[str | None] = mapped_column(String(500), nullable=True)
    depo: Mapped[str | None] = mapped_column(String(100), nullable=True)
    sira: Mapped[int | None] = mapped_column(Integer, nullable=True)
    stok_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    manuel: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    onerilen_tedarikci_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    ihtiyac_tarihi: Mapped[date | None] = mapped_column(Date, nullable=True)
    tahmini_birim_fiyat: Mapped[Decimal | None] = mapped_column(Numeric(18, 4), nullable=True)
    para_birimi: Mapped[str | None] = mapped_column(String(3), nullable=True)
    kur: Mapped[Decimal | None] = mapped_column(Numeric(18, 6), nullable=True)
    fiyat_kaynagi: Mapped[str | None] = mapped_column(String(60), nullable=True)
    iptal_miktar: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False, default=0)
    iptal_nedeni: Mapped[str | None] = mapped_column(String(300), nullable=True)
    # İade edilen malın kullanıcı kararıyla yeniden aktarılabilir ihtiyaca açılan kısmı
    yeniden_acilan_miktar: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False, default=0)
    yeniden_acma_nedeni: Mapped[str | None] = mapped_column(String(300), nullable=True)

    talep: Mapped["SatinAlmaTalep"] = relationship(
        "SatinAlmaTalep", back_populates="satirlar"
    )


class SatinAlmaTalepSiparisBagi(Base):
    """Talep satırının hangi alış sipariş satırına ne kadar aktarıldığı (çoktan çoğa)."""

    __tablename__ = "satin_alma_talep_siparis_baglari"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    talep_satiri_id: Mapped[int] = mapped_column(
        ForeignKey("satin_alma_talep_satirlari.id"), nullable=False, index=True
    )
    siparis_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    siparis_satiri_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    miktar: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False)
    olusturma_tarihi: Mapped[datetime] = mapped_column(DateTime, default=datetime.now, nullable=False)


class SatinAlmaTalepGecmisi(Base):
    __tablename__ = "satin_alma_talep_gecmisi"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    talep_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    islem: Mapped[str] = mapped_column(String(40), nullable=False)
    eski_durum: Mapped[str | None] = mapped_column(String(30), nullable=True)
    yeni_durum: Mapped[str | None] = mapped_column(String(30), nullable=True)
    detay: Mapped[str | None] = mapped_column(Text, nullable=True)
    kullanici: Mapped[str | None] = mapped_column(String(120), nullable=True)
    tarih: Mapped[datetime] = mapped_column(DateTime, default=datetime.now, nullable=False)


class SatinAlmaTalepEki(Base):
    __tablename__ = "satin_alma_talep_ekleri"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    talep_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    dosya_adi: Mapped[str] = mapped_column(String(255), nullable=False)
    goreli_yol: Mapped[str] = mapped_column(String(500), nullable=False)
    ekleyen: Mapped[str | None] = mapped_column(String(120), nullable=True)
    tarih: Mapped[datetime] = mapped_column(DateTime, default=datetime.now, nullable=False)
