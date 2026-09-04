from datetime import date
from decimal import Decimal

from sqlalchemy import Boolean, Date, ForeignKey, Numeric, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from database.database import Base

class Cari(Base):
    __tablename__ = "cari_kartlar"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    cari_kodu: Mapped[str] = mapped_column(String(20), unique=True, nullable=False)
    unvan: Mapped[str] = mapped_column(String(200), nullable=False)
    cari_turu: Mapped[str] = mapped_column(String(20), nullable=False)
    vergi_dairesi: Mapped[str | None] = mapped_column(String(100), nullable=True)
    vergi_numarasi: Mapped[str | None] = mapped_column(String(20), nullable=True)
    telefon: Mapped[str | None] = mapped_column(String(30), nullable=True)
    email: Mapped[str | None] = mapped_column(String(150), nullable=True)
    musteri_grubu: Mapped[str | None] = mapped_column(String(100), nullable=True)
    adres: Mapped[str | None] = mapped_column(String(500), nullable=True)
    ozel_notlar: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    aktif: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    satis_hareketleri: Mapped[list["SatisHareketi"]] = relationship(
        "SatisHareketi",
        back_populates="cari",
        cascade="all, delete-orphan",
    )


class MusteriGrubu(Base):
    __tablename__ = "musteri_gruplari"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    ad: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)


class SatisHareketi(Base):
    __tablename__ = "cari_satis_hareketleri"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    cari_id: Mapped[int] = mapped_column(ForeignKey("cari_kartlar.id"), nullable=False, index=True)
    satis_tarihi: Mapped[date] = mapped_column(Date, nullable=False)
    belge_no: Mapped[str] = mapped_column(String(50), nullable=False)
    satis_tutari: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    kalan_acik_tutar: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)

    cari: Mapped["Cari"] = relationship("Cari", back_populates="satis_hareketleri")
