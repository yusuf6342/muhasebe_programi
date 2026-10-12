"""Cari risk limiti / vade farkı oranı değişiklik geçmişi, risk aşım olayları ve firma risk ayarı."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from sqlalchemy import DateTime, Index, Integer, Numeric, String
from sqlalchemy.orm import Mapped, mapped_column

from database.database import Base


class CariRiskDegisiklik(Base):
    """Cari kartta limit, limit uygulama, vade farkı oranı veya dönem değişikliği (silinmez iz)."""

    __tablename__ = "cari_risk_degisiklikleri"
    __table_args__ = (Index("ix_cari_risk_degisiklik_cari", "cari_id", "zaman"),)

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    cari_id: Mapped[int] = mapped_column(Integer, nullable=False)
    alan: Mapped[str] = mapped_column(String(40), nullable=False)
    eski_deger: Mapped[str | None] = mapped_column(String(60), nullable=True)
    yeni_deger: Mapped[str | None] = mapped_column(String(60), nullable=True)
    kullanici_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    kullanici_adi: Mapped[str | None] = mapped_column(String(120), nullable=True)
    zaman: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.now)


class CariRiskOlayi(Base):
    """Risk limiti aşımına rağmen yapılan kayıt (uyarı geçişi veya yetkili geçiş)."""

    __tablename__ = "cari_risk_olaylari"
    __table_args__ = (Index("ix_cari_risk_olay_cari", "cari_id", "zaman"),)

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    cari_id: Mapped[int] = mapped_column(Integer, nullable=False)
    belge_turu: Mapped[str] = mapped_column(String(40), nullable=False)
    belge_no: Mapped[str | None] = mapped_column(String(50), nullable=True)
    risk_turu: Mapped[str] = mapped_column(String(20), nullable=False)
    mevcut_risk: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False, default=0)
    islem_etkisi: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False, default=0)
    yeni_risk: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False, default=0)
    limit: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False, default=0)
    politika: Mapped[str] = mapped_column(String(10), nullable=False)
    karar: Mapped[str] = mapped_column(String(20), nullable=False)
    gerekce: Mapped[str | None] = mapped_column(String(300), nullable=True)
    kullanici_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    kullanici_adi: Mapped[str | None] = mapped_column(String(120), nullable=True)
    zaman: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.now)


class CariRiskAyari(Base):
    """Firma veritabanında risk politikası (anahtar/değer)."""

    __tablename__ = "cari_risk_ayarlari"

    anahtar: Mapped[str] = mapped_column(String(60), primary_key=True)
    deger: Mapped[str | None] = mapped_column(String(200), nullable=True)
