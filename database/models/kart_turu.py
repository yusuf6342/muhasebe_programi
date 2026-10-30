"""Ana / alt kart türü tanımları (stok ve cari)."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from database.database import Base

KAPSAM_STOK = "STOK"
KAPSAM_CARI = "CARI"


class KartAnaTuru(Base):
    __tablename__ = "kart_ana_turleri"
    __table_args__ = (
        UniqueConstraint("kapsam", "kod", name="uq_kart_ana_tur_kapsam_kod"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    kapsam: Mapped[str] = mapped_column(String(10), nullable=False, index=True)  # STOK | CARI
    kod: Mapped[str] = mapped_column(String(40), nullable=False)
    ad: Mapped[str] = mapped_column(String(100), nullable=False)
    aciklama: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Cari: MUSTERI | TEDARIKCI | PERSONEL | MUSTERI_TEDARIKCI
    muhasebe_rol: Mapped[str | None] = mapped_column(String(40), nullable=True)
    aktif: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    sira: Mapped[int] = mapped_column(Integer, default=100, nullable=False)
    sistem: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    olusturma_tarihi: Mapped[datetime] = mapped_column(DateTime, default=datetime.now, nullable=False)
    guncelleme_tarihi: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    alt_turler: Mapped[list["KartAltTuru"]] = relationship(
        "KartAltTuru", back_populates="ana_tur", cascade="all, delete-orphan"
    )


class KartAltTuru(Base):
    __tablename__ = "kart_alt_turleri"
    __table_args__ = (
        UniqueConstraint("ana_tur_id", "kod", name="uq_kart_alt_tur_ana_kod"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    ana_tur_id: Mapped[int] = mapped_column(
        ForeignKey("kart_ana_turleri.id"), nullable=False, index=True
    )
    kod: Mapped[str] = mapped_column(String(40), nullable=False)
    ad: Mapped[str] = mapped_column(String(100), nullable=False)
    aciklama: Mapped[str | None] = mapped_column(Text, nullable=True)
    aktif: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    sira: Mapped[int] = mapped_column(Integer, default=100, nullable=False)
    sistem: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    olusturma_tarihi: Mapped[datetime] = mapped_column(DateTime, default=datetime.now, nullable=False)
    guncelleme_tarihi: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    ana_tur: Mapped["KartAnaTuru"] = relationship("KartAnaTuru", back_populates="alt_turler")
