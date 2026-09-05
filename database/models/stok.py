from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import Boolean, Date, DateTime, ForeignKey, Numeric, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from database.database import Base


class Depo(Base):
    __tablename__ = "depolar"
    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    ad: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)
    aktif: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)


class StokKarti(Base):
    __tablename__ = "stok_kartlari"
    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    stok_kodu: Mapped[str] = mapped_column(String(50), unique=True, nullable=False)
    stok_adi: Mapped[str] = mapped_column(String(200), nullable=False, index=True)
    barkod: Mapped[str | None] = mapped_column(String(100), unique=True, nullable=True)
    birim: Mapped[str] = mapped_column(String(20), nullable=False, default="Adet")
    aktif: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    fiyatlar: Mapped[list["StokFiyati"]] = relationship("StokFiyati", back_populates="stok", cascade="all, delete-orphan")
    lotlar: Mapped[list["StokLotu"]] = relationship("StokLotu", back_populates="stok", cascade="all, delete-orphan")


class StokFiyati(Base):
    __tablename__ = "stok_fiyatlari"
    __table_args__ = (UniqueConstraint("stok_id", "fiyat_adi", name="uq_stok_fiyat_adi"),)
    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    stok_id: Mapped[int] = mapped_column(ForeignKey("stok_kartlari.id"), nullable=False, index=True)
    fiyat_adi: Mapped[str] = mapped_column(String(100), nullable=False)
    tutar: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False)
    para_birimi: Mapped[str] = mapped_column(String(10), nullable=False, default="TL")
    stok: Mapped["StokKarti"] = relationship("StokKarti", back_populates="fiyatlar")


class StokLotu(Base):
    __tablename__ = "stok_lotlari"
    __table_args__ = (UniqueConstraint("stok_id", "depo_id", "lot_no", name="uq_stok_depo_lot"),)
    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    stok_id: Mapped[int] = mapped_column(ForeignKey("stok_kartlari.id"), nullable=False, index=True)
    depo_id: Mapped[int] = mapped_column(ForeignKey("depolar.id"), nullable=False, index=True)
    lot_no: Mapped[str] = mapped_column(String(100), nullable=False)
    tedarikci: Mapped[str | None] = mapped_column(String(200), nullable=True)
    giris_tarihi: Mapped[date] = mapped_column(Date, nullable=False)
    kalan_miktar: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False, default=0)
    birim_maliyet: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False, default=0)
    stok: Mapped["StokKarti"] = relationship("StokKarti", back_populates="lotlar")
    depo: Mapped["Depo"] = relationship("Depo")


class StokHareketi(Base):
    __tablename__ = "stok_hareketleri"
    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    tarih: Mapped[date] = mapped_column(Date, nullable=False)
    hareket_turu: Mapped[str] = mapped_column(String(30), nullable=False)
    belge_no: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    stok_id: Mapped[int] = mapped_column(ForeignKey("stok_kartlari.id"), nullable=False, index=True)
    depo_id: Mapped[int] = mapped_column(ForeignKey("depolar.id"), nullable=False, index=True)
    lot_id: Mapped[int | None] = mapped_column(ForeignKey("stok_lotlari.id"), nullable=True)
    miktar: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False)
    birim_maliyet: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False, default=0)
    olusturma_tarihi: Mapped[datetime] = mapped_column(DateTime, default=datetime.now, nullable=False)

