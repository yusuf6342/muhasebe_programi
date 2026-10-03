"""Stok uyarıları ve sipariş ihtiyacı.

İhtiyaç kaydı stok/cari/muhasebe etkisi üretmez; kesinleşmiş stok hareketlerinden türetilir.
Aynı ürün–depo için en fazla bir etkin ihtiyaç (``aktif = 1``) kısmi tekil indeksle güvenceye alınır.
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import Boolean, Date, DateTime, ForeignKey, Index, Integer, Numeric, String, Text, text
from sqlalchemy.orm import Mapped, mapped_column

from database.database import Base


class StokUyariAyari(Base):
    """Ürün (depo_id NULL) veya ürün–depo bazında uyarı ayarı; boş alan bir üst seviyeden gelir."""

    __tablename__ = "stok_uyari_ayarlari"
    __table_args__ = (
        Index("uq_stok_uyari_ayar_urun", "stok_id", unique=True, sqlite_where=text("depo_id IS NULL")),
        Index("uq_stok_uyari_ayar_depo", "stok_id", "depo_id", unique=True,
              sqlite_where=text("depo_id IS NOT NULL")),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    stok_id: Mapped[int] = mapped_column(ForeignKey("stok_kartlari.id"), nullable=False, index=True)
    depo_id: Mapped[int | None] = mapped_column(ForeignKey("depolar.id"), nullable=True, index=True)
    takip: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    minimum: Mapped[Decimal | None] = mapped_column(Numeric(18, 4), nullable=True)
    hedef: Mapped[Decimal | None] = mapped_column(Numeric(18, 4), nullable=True)
    alim_birimi: Mapped[str | None] = mapped_column(String(30), nullable=True)
    paket_kati: Mapped[Decimal | None] = mapped_column(Numeric(18, 4), nullable=True)
    tercih_tedarikci_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    guncelleme_tarihi: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    guncelleyen: Mapped[str | None] = mapped_column(String(120), nullable=True)


class StokUyariGenelAyar(Base):
    """Firma varsayılanları (anahtar–değer)."""

    __tablename__ = "stok_uyari_genel_ayarlari"

    anahtar: Mapped[str] = mapped_column(String(60), primary_key=True)
    deger: Mapped[str | None] = mapped_column(String(300), nullable=True)


class StokIhtiyac(Base):
    __tablename__ = "stok_ihtiyaclari"
    __table_args__ = (
        Index("uq_stok_ihtiyac_aktif", "stok_id", "depo_id", unique=True, sqlite_where=text("aktif = 1")),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    stok_id: Mapped[int] = mapped_column(ForeignKey("stok_kartlari.id"), nullable=False, index=True)
    depo_id: Mapped[int] = mapped_column(ForeignKey("depolar.id"), nullable=False, index=True)
    aktif: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, index=True)
    # Virgülle ayrılmış: TUKENDI, SATILABILIR_YOK, KRITIK
    nedenler: Mapped[str] = mapped_column(String(100), nullable=False, default="")
    fiziksel: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False, default=0)
    rezerve: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False, default=0)
    satilabilir: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False, default=0)
    beklenen: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False, default=0)
    minimum: Mapped[Decimal | None] = mapped_column(Numeric(18, 4), nullable=True)
    hedef: Mapped[Decimal | None] = mapped_column(Numeric(18, 4), nullable=True)
    oneri_temel: Mapped[Decimal | None] = mapped_column(Numeric(18, 4), nullable=True)
    oneri_alim: Mapped[Decimal | None] = mapped_column(Numeric(18, 4), nullable=True)
    alim_birimi: Mapped[str | None] = mapped_column(String(30), nullable=True)
    musteri_talebi: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False, default=0)
    diger_depo_stok: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False, default=0)
    olay_no: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    ilk_olusma: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.now)
    son_degerlendirme: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.now)
    kapanma_tarihi: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    kapanma_nedeni: Mapped[str | None] = mapped_column(String(200), nullable=True)
    erteleme_bitis: Mapped[date | None] = mapped_column(Date, nullable=True)
    erteleme_nedeni: Mapped[str | None] = mapped_column(String(300), nullable=True)
    goruldu: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    row_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)


class StokIhtiyacGecmisi(Base):
    __tablename__ = "stok_ihtiyac_gecmisi"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    ihtiyac_id: Mapped[int] = mapped_column(ForeignKey("stok_ihtiyaclari.id"), nullable=False, index=True)
    tarih: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.now)
    islem: Mapped[str] = mapped_column(String(40), nullable=False)
    detay: Mapped[str | None] = mapped_column(Text, nullable=True)
    kullanici: Mapped[str | None] = mapped_column(String(120), nullable=True)


class StokIhtiyacSiparisBagi(Base):
    """İhtiyaç → alış sipariş satırı (çoktan çoğa; kısmi karşılama)."""

    __tablename__ = "stok_ihtiyac_siparis_baglari"
    __table_args__ = (
        Index("uq_stok_ihtiyac_siparis_satiri", "ihtiyac_id", "siparis_satiri_id", unique=True),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    ihtiyac_id: Mapped[int] = mapped_column(ForeignKey("stok_ihtiyaclari.id"), nullable=False, index=True)
    siparis_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    siparis_satiri_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    miktar_temel: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False)
    olusturma_tarihi: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.now)
    olusturan: Mapped[str | None] = mapped_column(String(120), nullable=True)


class StokUyariBekleyen(Base):
    """Kesinleşme sırasında değerlendirilemeyen ürün–depo çiftleri (yeniden deneme kuyruğu)."""

    __tablename__ = "stok_uyari_bekleyenler"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    stok_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    depo_id: Mapped[int] = mapped_column(Integer, nullable=False)
    hata: Mapped[str | None] = mapped_column(String(500), nullable=True)
    tarih: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.now)
