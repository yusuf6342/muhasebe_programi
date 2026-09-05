from datetime import date
from decimal import Decimal

from sqlalchemy import Boolean, Date, ForeignKey, Numeric, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from database.database import Base


class FinansHesabi(Base):
    __tablename__ = "finans_hesaplari"
    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    hesap_adi: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)
    hesap_turu: Mapped[str] = mapped_column(String(30), nullable=False)
    acilis_bakiyesi: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False, default=0)
    aktif: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    hareketler: Mapped[list["FinansHareketi"]] = relationship("FinansHareketi", back_populates="hesap", cascade="all, delete-orphan")


class FinansHareketi(Base):
    __tablename__ = "finans_hareketleri"
    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    hesap_id: Mapped[int] = mapped_column(ForeignKey("finans_hesaplari.id"), nullable=False, index=True)
    tarih: Mapped[date] = mapped_column(Date, nullable=False)
    hareket_turu: Mapped[str] = mapped_column(String(50), nullable=False)
    belge_no: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    tutar: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    aciklama: Mapped[str | None] = mapped_column(String(500), nullable=True)
    hesap: Mapped["FinansHesabi"] = relationship("FinansHesabi", back_populates="hareketler")
