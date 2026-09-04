from datetime import date, datetime
from decimal import Decimal
from typing import TYPE_CHECKING

from sqlalchemy import Date, DateTime, ForeignKey, Numeric, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from database.database import Base

if TYPE_CHECKING:
    from database.models.cari import Cari


class SatisSiparisi(Base):
    __tablename__ = "satis_siparisleri"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    siparis_no: Mapped[str] = mapped_column(String(30), unique=True, nullable=False)
    siparis_tarihi: Mapped[date] = mapped_column(Date, nullable=False)
    termin_tarihi: Mapped[date] = mapped_column(Date, nullable=False)
    cari_id: Mapped[int] = mapped_column(ForeignKey("cari_kartlar.id"), nullable=False, index=True)
    maliyet_yontemi: Mapped[str] = mapped_column(String(50), nullable=False)
    hedef_kar_marji: Mapped[Decimal] = mapped_column(Numeric(7, 2), nullable=False, default=0)
    aciklama: Mapped[str | None] = mapped_column(Text, nullable=True)
    durum: Mapped[str] = mapped_column(String(30), nullable=False, default="AÇIK")
    olusturma_tarihi: Mapped[datetime] = mapped_column(DateTime, default=datetime.now, nullable=False)

    cari: Mapped["Cari"] = relationship("Cari")
    satirlar: Mapped[list["SatisSiparisiSatiri"]] = relationship(
        "SatisSiparisiSatiri", back_populates="siparis", cascade="all, delete-orphan"
    )
    tahsilatlar: Mapped[list["SatisSiparisiTahsilati"]] = relationship(
        "SatisSiparisiTahsilati", back_populates="siparis", cascade="all, delete-orphan"
    )


class SatisSiparisiSatiri(Base):
    __tablename__ = "satis_siparisi_satirlari"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    siparis_id: Mapped[int] = mapped_column(ForeignKey("satis_siparisleri.id"), nullable=False, index=True)
    urun_kodu: Mapped[str] = mapped_column(String(50), nullable=False)
    urun_adi: Mapped[str] = mapped_column(String(200), nullable=False)
    aciklama: Mapped[str | None] = mapped_column(String(500), nullable=True)
    miktar: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False)
    birim: Mapped[str] = mapped_column(String(20), nullable=False)
    birim_satis_fiyati: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False)
    iskonto_orani: Mapped[Decimal] = mapped_column(Numeric(7, 2), nullable=False, default=0)
    kdv_orani: Mapped[Decimal] = mapped_column(Numeric(7, 2), nullable=False, default=20)
    fifo_birim_maliyeti: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False, default=0)
    son_alis_birim_maliyeti: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False, default=0)
    ortalama_birim_maliyeti: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False, default=0)
    agirlikli_ortalama_birim_maliyeti: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False, default=0)
    irsaliyelenen_miktar: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False, default=0)
    faturalanan_miktar: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False, default=0)
    irsaliye_belge_baglantisi: Mapped[str | None] = mapped_column(String(100), nullable=True)
    fatura_belge_baglantisi: Mapped[str | None] = mapped_column(String(100), nullable=True)

    siparis: Mapped["SatisSiparisi"] = relationship("SatisSiparisi", back_populates="satirlar")


class SatisSiparisiTahsilati(Base):
    __tablename__ = "satis_siparisi_tahsilatlari"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    siparis_id: Mapped[int] = mapped_column(ForeignKey("satis_siparisleri.id"), nullable=False, index=True)
    tahsilat_tarihi: Mapped[date] = mapped_column(Date, nullable=False)
    tutar: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    odeme_sekli: Mapped[str] = mapped_column(String(30), nullable=False)
    hesap: Mapped[str | None] = mapped_column(String(100), nullable=True)
    aciklama: Mapped[str | None] = mapped_column(String(500), nullable=True)

    siparis: Mapped["SatisSiparisi"] = relationship("SatisSiparisi", back_populates="tahsilatlar")
