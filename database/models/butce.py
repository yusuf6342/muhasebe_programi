"""Firma bütçe planı, aylık satırlar ve (ileride) kaynak eşleştirme stub'ı.

Bütçe yalnız planlama / raporlama katmanıdır; fatura, fiş veya stok hareketi üretmez.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from database.database import Base

# Ölçü türleri (MVP)
OLCU_SATIS = "SATIS"
OLCU_ALIS = "ALIS"
OLCU_GIDER = "GIDER"
OLCU_KARLILIK = "KARLILIK"
OLCU_NAKIT = "NAKIT"
OLCU_BILANCO = "BILANCO"
OLCU_TURLERI = (OLCU_SATIS, OLCU_ALIS, OLCU_GIDER, OLCU_KARLILIK, OLCU_NAKIT, OLCU_BILANCO)

SENARYO_TEMEL = "TEMEL"
SENARYO_IYIMSER = "IYIMSER"
SENARYO_TEMKINLI = "TEMKINLI"
SENARYOLAR = (SENARYO_TEMEL, SENARYO_IYIMSER, SENARYO_TEMKINLI)

# Plan durumları
DURUM_TASLAK = "TASLAK"
DURUM_INCELEMEDE = "INCELEMEDE"
DURUM_ONAYLI = "ONAYLI"
DURUM_KILITLI = "KILITLI"
DURUM_ARSIV = "ARSIVLENDI"
DURUMLAR = (
    DURUM_TASLAK,
    DURUM_INCELEMEDE,
    DURUM_ONAYLI,
    DURUM_KILITLI,
    DURUM_ARSIV,
)

# Durum geçişleri (tek kullanıcılı onay yeterli)
DURUM_GECISLER = {
    DURUM_TASLAK: (DURUM_INCELEMEDE, DURUM_ONAYLI, DURUM_ARSIV),
    DURUM_INCELEMEDE: (DURUM_TASLAK, DURUM_ONAYLI, DURUM_ARSIV),
    DURUM_ONAYLI: (DURUM_KILITLI, DURUM_INCELEMEDE),
    DURUM_KILITLI: (DURUM_ARSIV,),
    DURUM_ARSIV: (),
}


class ButcePlan(Base):
    """Firma + mali yıl bütçe kartı. Kod: BTC-YYYY-####."""

    __tablename__ = "butce_planlari"
    __table_args__ = (
        UniqueConstraint("firma_id", "kod", name="uq_butce_plan_firma_kod"),
        Index("ix_butce_plan_firma_yil", "firma_id", "mali_yil"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    kod: Mapped[str] = mapped_column(String(20), nullable=False)
    ad: Mapped[str] = mapped_column(String(200), nullable=False)
    mali_yil: Mapped[int] = mapped_column(Integer, nullable=False)
    durum: Mapped[str] = mapped_column(String(20), nullable=False, default=DURUM_TASLAK)
    para_birimi: Mapped[str] = mapped_column(String(3), nullable=False, default="TRY")
    firma_id: Mapped[int] = mapped_column(Integer, nullable=False, default=0, index=True)
    surum: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    senaryo: Mapped[str] = mapped_column(String(20), nullable=False, default=SENARYO_TEMEL)
    # Revizyon / senaryo kopyası: kaynak plan
    kaynak_plan_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    proje_kodu: Mapped[str | None] = mapped_column(String(40), nullable=True)
    aciklama: Mapped[str | None] = mapped_column(Text, nullable=True)
    olusturma: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.now)
    olusturan: Mapped[str | None] = mapped_column(String(120), nullable=True)
    guncelleme: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    guncelleyen: Mapped[str | None] = mapped_column(String(120), nullable=True)
    onay_tarihi: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    onaylayan: Mapped[str | None] = mapped_column(String(120), nullable=True)

    satirlar: Mapped[list["ButceSatir"]] = relationship(
        "ButceSatir",
        back_populates="plan",
        cascade="all, delete-orphan",
    )
    bilanco_hedefleri: Mapped[list["ButceBilancoHedef"]] = relationship(
        "ButceBilancoHedef",
        back_populates="plan",
        cascade="all, delete-orphan",
    )


class ButceSatir(Base):
    """Aylık plan satırı — ölçü + kategori + ay (1–12) + tutar."""

    __tablename__ = "butce_satirlari"
    __table_args__ = (
        UniqueConstraint(
            "plan_id",
            "olcu_turu",
            "kategori",
            "ay",
            name="uq_butce_satir_plan_olcu_kat_ay",
        ),
        Index("ix_butce_satir_plan_olcu", "plan_id", "olcu_turu"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    plan_id: Mapped[int] = mapped_column(
        ForeignKey("butce_planlari.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    olcu_turu: Mapped[str] = mapped_column(String(20), nullable=False)
    kategori: Mapped[str] = mapped_column(String(80), nullable=False, default="GENEL")
    ay: Mapped[int] = mapped_column(Integer, nullable=False)  # 1–12
    tutar: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False, default=0)
    aciklama: Mapped[str | None] = mapped_column(String(500), nullable=True)
    # DAGITIM | MANUEL | EXCEL — otomatik dağıtım ile manuel revizyon ayrımı
    kaynak_giris: Mapped[str | None] = mapped_column(String(20), nullable=True)

    plan: Mapped["ButcePlan"] = relationship("ButcePlan", back_populates="satirlar")


class ButceEslesme(Base):
    """Ön / genel muhasebe kategori–hesap eşleştirme."""

    __tablename__ = "butce_eslesmeler"
    __table_args__ = (
        Index("ix_butce_eslesme_firma_olcu", "firma_id", "olcu_turu"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    firma_id: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    olcu_turu: Mapped[str] = mapped_column(String(20), nullable=False)
    kategori: Mapped[str] = mapped_column(String(80), nullable=False, default="GENEL")
    # ON_MUHASEBE | GENEL_MUHASEBE
    kaynak: Mapped[str] = mapped_column(String(20), nullable=False, default="ON_MUHASEBE")
    # Belge türü / hesap ailesi kodu
    kaynak_kod: Mapped[str | None] = mapped_column(String(80), nullable=True)
    aktif: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    aciklama: Mapped[str | None] = mapped_column(String(300), nullable=True)
    olusturma: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.now)


class ButceBilancoHedef(Base):
    """Dönem sonu bilanço hedefi — hareket toplamı ile karıştırılmaz."""

    __tablename__ = "butce_bilanco_hedefleri"
    __table_args__ = (
        UniqueConstraint(
            "plan_id",
            "hesap_grubu",
            "ay",
            name="uq_butce_bilanco_plan_hesap_ay",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    plan_id: Mapped[int] = mapped_column(
        ForeignKey("butce_planlari.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    hesap_grubu: Mapped[str] = mapped_column(String(80), nullable=False)  # STOK, ALACAK, …
    ay: Mapped[int] = mapped_column(Integer, nullable=False, default=12)  # kesim ayı 1–12
    hedef_tutar: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False, default=0)
    aciklama: Mapped[str | None] = mapped_column(String(300), nullable=True)

    plan: Mapped["ButcePlan"] = relationship("ButcePlan", back_populates="bilanco_hedefleri")
