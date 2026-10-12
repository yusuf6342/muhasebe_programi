"""Sabit gider ödeme planları — kira, muhasebe, ücret, SGK/vergi, fatura ve abonelik gibi düzenli ödemeler.

Plan ve dönem kayıtları yalnız ödeme takvimi içindir: cari borç, muhasebe fişi, kasa/banka hareketi
veya gerçekleşmiş ödeme oluşturmaz. Dönem kalanı, bağlı gerçek evraklardan (ödeme ya da borç belgesi)
hesaplanır; bağlantılar silinmez, iptal edilir.
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import Boolean, Date, DateTime, ForeignKey, Index, Integer, Numeric, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from database.database import Base

KATEGORILER: tuple[tuple[str, str], ...] = (
    ("KIRA", "Kira"),
    ("MUHASEBE", "Muhasebe / müşavirlik"),
    ("PERSONEL_UCRET", "Personel ücretleri"),
    ("SGK_VERGI", "SGK ve vergi ödemeleri"),
    ("ELEKTRIK", "Elektrik"),
    ("SU", "Su"),
    ("INTERNET", "İnternet / telefon"),
    ("ABONELIK", "Abonelik"),
    ("DIGER", "Diğer düzenli ödeme"),
)
KATEGORI_ADLARI = dict(KATEGORILER)

PERIYOT_AYLIK = "AYLIK"
PERIYOT_TEK = "TEK"
PERIYOTLAR = ((PERIYOT_AYLIK, "Aylık"), (PERIYOT_TEK, "Tek seferlik"))

PLAN_AKTIF = "AKTIF"
PLAN_DURDURULDU = "DURDURULDU"
PLAN_IPTAL = "IPTAL"
PLAN_DURUMLARI = ((PLAN_AKTIF, "Aktif"), (PLAN_DURDURULDU, "Durduruldu"), (PLAN_IPTAL, "İptal"))

DONEM_ACIK = "ACIK"
DONEM_IPTAL = "IPTAL"

BAGLANTI_ODEME = "ODEME"
BAGLANTI_BORC = "BORC_BELGESI"


class SabitGiderPlani(Base):
    __tablename__ = "sabit_gider_planlari"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    kategori: Mapped[str] = mapped_column(String(30), nullable=False)
    ad: Mapped[str] = mapped_column(String(150), nullable=False)
    cari_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    odeme_hesabi: Mapped[str | None] = mapped_column(String(100), nullable=True)
    periyot: Mapped[str] = mapped_column(String(10), nullable=False, default=PERIYOT_AYLIK)
    odeme_gunu: Mapped[int] = mapped_column(Integer, nullable=False)
    # Ayın ilk günü olarak saklanır (yıl-ay); bitiş boşsa süresiz
    baslangic_ay: Mapped[date] = mapped_column(Date, nullable=False)
    bitis_ay: Mapped[date | None] = mapped_column(Date, nullable=True)
    tutar: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    tahmini: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    durum: Mapped[str] = mapped_column(String(15), nullable=False, default=PLAN_AKTIF)
    aciklama: Mapped[str | None] = mapped_column(String(500), nullable=True)
    olusturan: Mapped[str | None] = mapped_column(String(120), nullable=True)
    olusturma: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.now)
    guncelleyen: Mapped[str | None] = mapped_column(String(120), nullable=True)
    guncelleme: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    tutar_gecmisi: Mapped[list["SabitGiderTutarDegisikligi"]] = relationship(
        "SabitGiderTutarDegisikligi", back_populates="plan", cascade="all, delete-orphan",
        order_by="SabitGiderTutarDegisikligi.gecerli_ay",
    )
    donemler: Mapped[list["SabitGiderDonemi"]] = relationship(
        "SabitGiderDonemi", back_populates="plan", cascade="all, delete-orphan",
        order_by="SabitGiderDonemi.vade_tarihi",
    )


class SabitGiderTutarDegisikligi(Base):
    """Plan tutarının hangi aydan itibaren değiştiği (zam / indirim); eski dönemler etkilenmez."""

    __tablename__ = "sabit_gider_tutar_degisiklikleri"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    plan_id: Mapped[int] = mapped_column(ForeignKey("sabit_gider_planlari.id"), nullable=False, index=True)
    gecerli_ay: Mapped[date] = mapped_column(Date, nullable=False)
    tutar: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    tahmini: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    kullanici: Mapped[str | None] = mapped_column(String(120), nullable=True)
    zaman: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.now)

    plan: Mapped["SabitGiderPlani"] = relationship("SabitGiderPlani", back_populates="tutar_gecmisi")


class SabitGiderDonemi(Base):
    """Planın bir aylık ödeme dönemi. Anahtar: plan + yıl + ay (firma = firma veritabanı)."""

    __tablename__ = "sabit_gider_donemleri"
    __table_args__ = (
        UniqueConstraint("plan_id", "yil", "ay", name="uq_sabit_gider_donem"),
        Index("ix_sabit_gider_donem_vade", "vade_tarihi", "durum"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    plan_id: Mapped[int] = mapped_column(ForeignKey("sabit_gider_planlari.id"), nullable=False, index=True)
    yil: Mapped[int] = mapped_column(Integer, nullable=False)
    ay: Mapped[int] = mapped_column(Integer, nullable=False)
    vade_tarihi: Mapped[date] = mapped_column(Date, nullable=False)
    tutar: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    tahmini: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    durum: Mapped[str] = mapped_column(String(10), nullable=False, default=DONEM_ACIK)
    olusturma: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.now)
    iptal_nedeni: Mapped[str | None] = mapped_column(String(300), nullable=True)

    plan: Mapped["SabitGiderPlani"] = relationship("SabitGiderPlani", back_populates="donemler")
    baglantilar: Mapped[list["SabitGiderBaglanti"]] = relationship(
        "SabitGiderBaglanti", back_populates="donem", cascade="all, delete-orphan",
        order_by="SabitGiderBaglanti.id",
    )


class SabitGiderBaglanti(Base):
    """Dönemi karşılayan gerçek evrak: ödeme (makbuz, gider fişi, havale) veya borç belgesi (fatura)."""

    __tablename__ = "sabit_gider_baglantilari"
    __table_args__ = (Index("ix_sabit_gider_baglanti_belge", "belge_no", "iptal"),)

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    donem_id: Mapped[int] = mapped_column(ForeignKey("sabit_gider_donemleri.id"), nullable=False, index=True)
    tur: Mapped[str] = mapped_column(String(15), nullable=False)
    belge_no: Mapped[str] = mapped_column(String(50), nullable=False)
    tutar: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    tarih: Mapped[date] = mapped_column(Date, nullable=False)
    aciklama: Mapped[str | None] = mapped_column(String(300), nullable=True)
    kullanici: Mapped[str | None] = mapped_column(String(120), nullable=True)
    olusturma: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.now)
    iptal: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    iptal_zamani: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    iptal_kullanici: Mapped[str | None] = mapped_column(String(120), nullable=True)
    iptal_nedeni: Mapped[str | None] = mapped_column(String(300), nullable=True)

    donem: Mapped["SabitGiderDonemi"] = relationship("SabitGiderDonemi", back_populates="baglantilar")
