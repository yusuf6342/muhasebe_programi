"""Tedarikçi fiyat listesi — alış fiyatı / iskonto / geçerlilik."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import Boolean, Date, DateTime, ForeignKey, Numeric, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from database.database import Base


class TedarikciFiyat(Base):
    __tablename__ = "tedarikci_fiyatlari"
    __table_args__ = (
        UniqueConstraint(
            "cari_id", "urun_kodu", "gecerlilik_baslangic", name="uq_tedarikci_fiyat"
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    cari_id: Mapped[int] = mapped_column(
        ForeignKey("cari_kartlar.id"), nullable=False, index=True
    )
    urun_kodu: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    urun_adi: Mapped[str] = mapped_column(String(200), nullable=False)
    birim: Mapped[str] = mapped_column(String(20), nullable=False, default="Adet")
    birim_fiyat: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False)
    iskonto_orani: Mapped[Decimal] = mapped_column(Numeric(7, 2), nullable=False, default=0)
    para_birimi: Mapped[str] = mapped_column(String(3), nullable=False, default="TRY")
    gecerlilik_baslangic: Mapped[date] = mapped_column(Date, nullable=False)
    gecerlilik_bitis: Mapped[date | None] = mapped_column(Date, nullable=True)
    aktif: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    olusturma_tarihi: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.now, nullable=False
    )

    cari = relationship("Cari")
