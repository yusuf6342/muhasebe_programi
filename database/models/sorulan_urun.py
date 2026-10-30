"""Sorulan Ürünler — müşteri talebi adayları (stok hareketi üretmez)."""

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
from sqlalchemy.orm import Mapped, mapped_column

from database.database import Base

TALEP_NEDENLERI = (
    "CESITTE_YOK",
    "STOKTA_YOK",
    "FIYAT_YUKSEK",
    "TEDARIK_GECIKME",
    "DIGER",
)
NIYETLER = ("SADECE_SORDU", "ALMAK_ISTIYOR", "TEKLIF_ISTIYOR", "SIPARIS_VERECEK")
TALEP_DURUMLARI = (
    "ACIK",
    "TAKIPTE",
    "SATINALMA_ARA",
    "SIPARIS_VERILDI",
    "URUN_GELDI",
    "ARAMA_BEKLIYOR",
    "SATISA_DONUSTU",
    "IPTAL",
    "ARSIV",
)
URUN_TEDARIK_DURUMLARI = (
    "BEKLEMEDE",
    "ARAŞTIRILIYOR",
    "SIPARIS_VERILDI",
    "GELDI",
    "STOKTA",
)
ARAMA_SONUCLARI = (
    "ULASILDI",
    "ULASILAMADI",
    "FIYAT_BEKLIYOR",
    "DAHA_SONRA_ARA",
    "VAZGECTI",
    "SIPARISE_DONUSTU",
)


class SorulanUrunAday(Base):
    __tablename__ = "sorulan_urun_adaylari"
    __table_args__ = (
        UniqueConstraint("firma_id", "normalize_ad", name="uq_sorulan_urun_firma_norm"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    firma_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    urun_adi: Mapped[str] = mapped_column(String(200), nullable=False)
    normalize_ad: Mapped[str] = mapped_column(String(220), nullable=False, index=True)
    ozellik: Mapped[str | None] = mapped_column(String(300), nullable=True)
    birim: Mapped[str | None] = mapped_column(String(40), nullable=True)
    stok_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    talep_nedeni_ozet: Mapped[str | None] = mapped_column(String(40), nullable=True)
    tedarik_durumu: Mapped[str] = mapped_column(
        String(30), nullable=False, default="BEKLEMEDE"
    )
    sorumlu_personel: Mapped[str | None] = mapped_column(String(80), nullable=True)
    arsiv: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    olusturan: Mapped[str | None] = mapped_column(String(80), nullable=True)
    olusturma_tarihi: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=datetime.utcnow
    )
    guncelleme_tarihi: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class SorulanUrunTalep(Base):
    __tablename__ = "sorulan_urun_talepleri"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    firma_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    aday_id: Mapped[int] = mapped_column(
        ForeignKey("sorulan_urun_adaylari.id"), nullable=False, index=True
    )
    talep_tarihi: Mapped[date] = mapped_column(Date, nullable=False)
    cari_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    musteri_adi: Mapped[str | None] = mapped_column(String(200), nullable=True)
    telefon: Mapped[str | None] = mapped_column(String(40), nullable=True)
    anonim: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    miktar: Mapped[Decimal | None] = mapped_column(Numeric(18, 4), nullable=True)
    birim: Mapped[str | None] = mapped_column(String(40), nullable=True)
    karsilanan_miktar: Mapped[Decimal] = mapped_column(
        Numeric(18, 4), nullable=False, default=Decimal("0")
    )
    iptal_miktar: Mapped[Decimal] = mapped_column(
        Numeric(18, 4), nullable=False, default=Decimal("0")
    )
    niyet: Mapped[str] = mapped_column(String(30), nullable=False, default="SADECE_SORDU")
    talep_nedeni: Mapped[str] = mapped_column(String(40), nullable=False, default="CESITTE_YOK")
    durum: Mapped[str] = mapped_column(String(30), nullable=False, default="ACIK")
    kaynak: Mapped[str | None] = mapped_column(String(40), nullable=True)
    notlar: Mapped[str | None] = mapped_column(Text, nullable=True)
    sonraki_arama: Mapped[date | None] = mapped_column(Date, nullable=True)
    olusturan: Mapped[str | None] = mapped_column(String(80), nullable=True)
    olusturma_tarihi: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=datetime.utcnow
    )
    guncelleme_tarihi: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    gecersiz: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
