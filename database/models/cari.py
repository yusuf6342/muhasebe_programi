from datetime import date
from decimal import Decimal

from sqlalchemy import Boolean, Date, ForeignKey, Integer, Numeric, String
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
    tc_kimlik: Mapped[str | None] = mapped_column(String(11), nullable=True)
    telefon: Mapped[str | None] = mapped_column(String(30), nullable=True)
    telefon2: Mapped[str | None] = mapped_column(String(30), nullable=True)
    telefon3: Mapped[str | None] = mapped_column(String(30), nullable=True)
    email: Mapped[str | None] = mapped_column(String(150), nullable=True)
    musteri_grubu: Mapped[str | None] = mapped_column(String(100), nullable=True)
    satis_fiyat_listesi: Mapped[str | None] = mapped_column(String(100), nullable=True)
    alis_fiyat_listesi: Mapped[str | None] = mapped_column(String(100), nullable=True)
    acik_hesap_risk_limiti: Mapped[Decimal | None] = mapped_column(Numeric(18, 2), nullable=True)
    cek_risk_limiti: Mapped[Decimal | None] = mapped_column(Numeric(18, 2), nullable=True)
    senet_risk_limiti: Mapped[Decimal | None] = mapped_column(Numeric(18, 2), nullable=True)
    satis_vade_gunu: Mapped[int | None] = mapped_column(Integer, nullable=True)
    alis_vade_gunu: Mapped[int | None] = mapped_column(Integer, nullable=True)
    muhasebe_borclu_kodu: Mapped[str | None] = mapped_column(String(50), nullable=True)
    muhasebe_alacakli_kodu: Mapped[str | None] = mapped_column(String(50), nullable=True)
    muhasebe_satis_kodu: Mapped[str | None] = mapped_column(String(50), nullable=True)
    muhasebe_alis_kodu: Mapped[str | None] = mapped_column(String(50), nullable=True)
    muhasebe_kdv_satis_kodu: Mapped[str | None] = mapped_column(String(50), nullable=True)
    muhasebe_kdv_alis_kodu: Mapped[str | None] = mapped_column(String(50), nullable=True)
    adres: Mapped[str | None] = mapped_column(String(500), nullable=True)
    il: Mapped[str | None] = mapped_column(String(50), nullable=True)
    ilce: Mapped[str | None] = mapped_column(String(50), nullable=True)
    adres_tipi: Mapped[str | None] = mapped_column(String(40), nullable=True)
    adres2: Mapped[str | None] = mapped_column(String(500), nullable=True)
    il2: Mapped[str | None] = mapped_column(String(50), nullable=True)
    ilce2: Mapped[str | None] = mapped_column(String(50), nullable=True)
    adres_tipi2: Mapped[str | None] = mapped_column(String(40), nullable=True)
    adres3: Mapped[str | None] = mapped_column(String(500), nullable=True)
    il3: Mapped[str | None] = mapped_column(String(50), nullable=True)
    ilce3: Mapped[str | None] = mapped_column(String(50), nullable=True)
    adres_tipi3: Mapped[str | None] = mapped_column(String(40), nullable=True)
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


class CariIslem(Base):
    """Tahsilat, ödeme, virman ve KK çekimi kayıtları."""

    __tablename__ = "cari_islemleri"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    cari_id: Mapped[int] = mapped_column(ForeignKey("cari_kartlar.id"), nullable=False, index=True)
    tarih: Mapped[date] = mapped_column(Date, nullable=False)
    islem_turu: Mapped[str] = mapped_column(String(40), nullable=False)
    belge_no: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    aciklama: Mapped[str | None] = mapped_column(String(500), nullable=True)
    borc: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False, default=0)
    alacak: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False, default=0)
    hesap_adi: Mapped[str | None] = mapped_column(String(100), nullable=True)
    karsi_cari_id: Mapped[int | None] = mapped_column(ForeignKey("cari_kartlar.id"), nullable=True)

    cari: Mapped["Cari"] = relationship("Cari", foreign_keys=[cari_id])
