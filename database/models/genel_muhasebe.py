"""Genel muhasebe — hesap planı, fişler, hesap eşleştirmeleri (firma operasyon DB)."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Optional

from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    ForeignKey,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from database.database import Base

HESAP_TURLERI = ("Aktif", "Pasif", "Gelir", "Gider", "Nazım")

FIS_TURLERI = (
    "Mahsup Fişi",
    "Tahsil Fişi",
    "Tediye Fişi",
    "Açılış Fişi",
)

FIS_DURUMLARI = ("Taslak", "Kesinleşmiş", "İptal")

# Tekdüzen ana hesap sınıfları (kod, ad, tür)
ANA_HESAP_SINIFLARI = (
    ("1", "Dönen Varlıklar", "Aktif"),
    ("2", "Duran Varlıklar", "Aktif"),
    ("3", "Kısa Vadeli Yabancı Kaynaklar", "Pasif"),
    ("4", "Uzun Vadeli Yabancı Kaynaklar", "Pasif"),
    ("5", "Öz Kaynaklar", "Pasif"),
    ("6", "Gelir Tablosu Hesapları", "Gelir"),
    ("7", "Maliyet Hesapları", "Gider"),
    ("9", "Nazım Hesaplar", "Nazım"),
)

# Entegrasyon eşleştirme anahtarları (kod içine sabit hesap yazılmaz)
ESLEME_ANAHTARLARI = (
    ("musteriler", "Müşteriler hesabı"),
    ("tedarikciler", "Tedarikçiler hesabı"),
    ("kasa", "Kasa hesabı"),
    ("banka", "Banka hesabı"),
    ("yurtici_satislar", "Yurtiçi satışlar hesabı"),
    ("satilan_mal_maliyeti", "Satılan malın maliyeti hesabı"),
    ("ticari_mallar", "Ticari mallar / stok hesabı"),
    ("hesaplanan_kdv", "Hesaplanan KDV"),
    ("indirilecek_kdv", "İndirilecek KDV"),
    ("giderler", "Gider hesapları (genel)"),
)


class HesapPlani(Base):
    __tablename__ = "muhasebe_hesap_plani"
    __table_args__ = (UniqueConstraint("firma_id", "hesap_kodu", name="uq_mh_hesap_kodu"),)

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    firma_id: Mapped[int] = mapped_column(ForeignKey("firmalar.id"), nullable=False, index=True)
    hesap_kodu: Mapped[str] = mapped_column(String(30), nullable=False)
    hesap_adi: Mapped[str] = mapped_column(String(200), nullable=False)
    ust_hesap_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("muhasebe_hesap_plani.id"), nullable=True
    )
    hesap_seviyesi: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    hesap_turu: Mapped[str] = mapped_column(String(20), nullable=False)
    borc_toplam: Mapped[Decimal] = mapped_column(
        Numeric(18, 2), default=Decimal("0"), nullable=False
    )
    alacak_toplam: Mapped[Decimal] = mapped_column(
        Numeric(18, 2), default=Decimal("0"), nullable=False
    )
    aktif: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    olusturma_tarihi: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.now, nullable=False
    )
    guncelleme_tarihi: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)

    ust_hesap: Mapped[Optional["HesapPlani"]] = relationship(
        "HesapPlani", remote_side="HesapPlani.id", back_populates="alt_hesaplar"
    )
    alt_hesaplar: Mapped[list["HesapPlani"]] = relationship(
        "HesapPlani", back_populates="ust_hesap"
    )


class MuhasebeFisi(Base):
    __tablename__ = "muhasebe_fisleri"
    __table_args__ = (
        UniqueConstraint("firma_id", "mali_yil", "fis_no", name="uq_mh_fis_no"),
        UniqueConstraint("firma_id", "kaynak_turu", "kaynak_id", name="uq_mh_kaynak"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    firma_id: Mapped[int] = mapped_column(ForeignKey("firmalar.id"), nullable=False, index=True)
    donem_id: Mapped[Optional[int]] = mapped_column(ForeignKey("donemler.id"), nullable=True)
    mali_yil: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    fis_no: Mapped[str] = mapped_column(String(40), nullable=False)
    fis_tarihi: Mapped[date] = mapped_column(Date, nullable=False)
    fis_turu: Mapped[str] = mapped_column(String(40), nullable=False)
    aciklama: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    belge_no: Mapped[Optional[str]] = mapped_column(String(60), nullable=True)
    durum: Mapped[str] = mapped_column(String(20), default="Taslak", nullable=False)
    toplam_borc: Mapped[Decimal] = mapped_column(
        Numeric(18, 2), default=Decimal("0"), nullable=False
    )
    toplam_alacak: Mapped[Decimal] = mapped_column(
        Numeric(18, 2), default=Decimal("0"), nullable=False
    )
    # Otomatik entegrasyon için (çift fiş engeli)
    kaynak_turu: Mapped[Optional[str]] = mapped_column(String(40), nullable=True)
    kaynak_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    iptal_nedeni: Mapped[Optional[str]] = mapped_column(String(300), nullable=True)
    ters_fis_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("muhasebe_fisleri.id"), nullable=True
    )
    olusturan_kullanici_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    olusturma_tarihi: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.now, nullable=False
    )
    guncelleyen_kullanici_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    guncelleme_tarihi: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)

    satirlar: Mapped[list["MuhasebeFisiSatiri"]] = relationship(
        "MuhasebeFisiSatiri",
        back_populates="fis",
        cascade="all, delete-orphan",
        order_by="MuhasebeFisiSatiri.sira_no",
    )


class MuhasebeFisiSatiri(Base):
    __tablename__ = "muhasebe_fis_satirlari"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    fis_id: Mapped[int] = mapped_column(
        ForeignKey("muhasebe_fisleri.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    firma_id: Mapped[int] = mapped_column(ForeignKey("firmalar.id"), nullable=False, index=True)
    sira_no: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    hesap_id: Mapped[int] = mapped_column(
        ForeignKey("muhasebe_hesap_plani.id"), nullable=False, index=True
    )
    hesap_kodu: Mapped[str] = mapped_column(String(30), nullable=False)
    hesap_adi: Mapped[str] = mapped_column(String(200), nullable=False)
    aciklama: Mapped[Optional[str]] = mapped_column(String(400), nullable=True)
    borc: Mapped[Decimal] = mapped_column(Numeric(18, 2), default=Decimal("0"), nullable=False)
    alacak: Mapped[Decimal] = mapped_column(Numeric(18, 2), default=Decimal("0"), nullable=False)
    belge_tarihi: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    belge_no: Mapped[Optional[str]] = mapped_column(String(60), nullable=True)

    fis: Mapped["MuhasebeFisi"] = relationship("MuhasebeFisi", back_populates="satirlar")
    hesap: Mapped["HesapPlani"] = relationship("HesapPlani")


class MuhasebeHesapEsleme(Base):
    """Firma bazlı entegrasyon hesap eşleştirmeleri — kod içine sabit hesap yazılmaz."""

    __tablename__ = "muhasebe_hesap_eslemeleri"
    __table_args__ = (
        UniqueConstraint("firma_id", "anahtar", name="uq_mh_esleme_anahtar"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    firma_id: Mapped[int] = mapped_column(ForeignKey("firmalar.id"), nullable=False, index=True)
    anahtar: Mapped[str] = mapped_column(String(60), nullable=False)
    aciklama: Mapped[str] = mapped_column(String(200), nullable=False)
    hesap_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("muhasebe_hesap_plani.id"), nullable=True
    )
    aktif: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)


class MuhasebeIslemGecmisi(Base):
    __tablename__ = "muhasebe_islem_gecmisi"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    firma_id: Mapped[int] = mapped_column(ForeignKey("firmalar.id"), nullable=False, index=True)
    kayit_turu: Mapped[str] = mapped_column(String(40), nullable=False)
    kayit_id: Mapped[int] = mapped_column(Integer, nullable=False)
    islem: Mapped[str] = mapped_column(String(40), nullable=False)
    detay: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    kullanici_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    kullanici_adi: Mapped[Optional[str]] = mapped_column(String(80), nullable=True)
    tarih: Mapped[datetime] = mapped_column(DateTime, default=datetime.now, nullable=False)
