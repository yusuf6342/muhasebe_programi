"""Gider rapor sınıflandırma, bütçe ve dağıtım ayarları."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import Boolean, Date, DateTime, ForeignKey, Integer, Numeric, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from database.database import Base

# Varsayılan ana gruplar (talimat tablosu) — kod kararlı kimliktir
GIDER_ANA_GRUPLAR = (
    ("PERSONEL", "Personel ve işveren yükleri", "O"),
    ("KIRA", "Kira ve yer kullanım giderleri", "O"),
    ("ENERJI", "Enerji iletişim ve yazılım", "O"),
    ("ARAC", "Araç ve sevkiyat", "O"),
    ("SATIS", "Satış ve pazarlama", "O"),
    ("POS", "POS ve banka hizmetleri", "O"),
    ("DIS_HIZMET", "Profesyonel ve dış hizmetler", "O"),
    ("ISLETME", "Bakım sarf ve işletme", "O"),
    ("SIGORTA", "Sigorta vergi harç ve aidat", "O"),
    ("AMORTISMAN", "Amortisman ve diğer nakit dışı giderler", "O"),
    ("FINANSMAN", "Finansman giderleri", "F"),
    ("DIGER", "Diğer ve sınıflandırılmamış", "O"),
)

# Mevcut dört kart sınıfı → varsayılan ana grup
SINIF_ANA_GRUP = {
    "ISLETME": "ISLETME",
    "PERSONEL": "PERSONEL",
    "FINANS_MALI": "FINANSMAN",
    "ARAC": "ARAC",
}

MALIYET_DAVRANISLARI = (
    ("SABIT", "Sabit"),
    ("DEGISKEN", "Değişken"),
    ("KARMA", "Karma"),
    ("BELIRSIZ", "Belirsiz"),
)

DUZENLILIKLER = (
    ("DUZENLI", "Düzenli"),
    ("TEK", "Tek seferlik"),
)


class GiderAnaGrup(Base):
    __tablename__ = "gider_ana_gruplari"
    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    kod: Mapped[str] = mapped_column(String(40), unique=True, nullable=False, index=True)
    ad: Mapped[str] = mapped_column(String(200), nullable=False)
    # O = faaliyet | F = finansman
    sonuc_yeri: Mapped[str] = mapped_column(String(5), nullable=False, default="O")
    sira: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    aktif: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    alt_gruplar: Mapped[list["GiderAltGrup"]] = relationship(
        back_populates="ana_grup", cascade="all, delete-orphan", order_by="GiderAltGrup.sira"
    )


class GiderAltGrup(Base):
    __tablename__ = "gider_alt_gruplari"
    __table_args__ = (UniqueConstraint("ana_grup_id", "kod", name="uq_gider_alt_grup"),)
    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    ana_grup_id: Mapped[int] = mapped_column(ForeignKey("gider_ana_gruplari.id"), nullable=False, index=True)
    kod: Mapped[str] = mapped_column(String(40), nullable=False)
    ad: Mapped[str] = mapped_column(String(200), nullable=False)
    sira: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    aktif: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    ana_grup: Mapped["GiderAnaGrup"] = relationship(back_populates="alt_gruplar")


class GiderButceSatiri(Base):
    """Onaylı / taslak bütçe satırı — firma+yıl+ay+grup bazlı."""

    __tablename__ = "gider_butce_satirlari"
    __table_args__ = (
        UniqueConstraint(
            "mali_yil", "ay", "ana_grup_kod", "alt_grup_kod", "surum",
            name="uq_gider_butce",
        ),
    )
    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    mali_yil: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    ay: Mapped[int] = mapped_column(Integer, nullable=False)  # 1-12
    ana_grup_kod: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    alt_grup_kod: Mapped[str | None] = mapped_column(String(40), nullable=True)
    tutar: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False, default=0)
    # TASLAK | ONAYLI | REVIZE
    durum: Mapped[str] = mapped_column(String(20), nullable=False, default="TASLAK")
    surum: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    gerekce: Mapped[str | None] = mapped_column(String(500), nullable=True)
    olusturma_zamani: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.now)
    onay_tarihi: Mapped[date | None] = mapped_column(Date, nullable=True)


class GiderDagitimAnahtari(Base):
    """Ortak gider dağıtım anahtarı (yüzde paylar JSON-benzeri satırlar)."""

    __tablename__ = "gider_dagitim_anahtarlari"
    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    kod: Mapped[str] = mapped_column(String(40), unique=True, nullable=False)
    ad: Mapped[str] = mapped_column(String(200), nullable=False)
    aciklama: Mapped[str | None] = mapped_column(String(500), nullable=True)
    aktif: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    gecerlilik_baslangic: Mapped[date | None] = mapped_column(Date, nullable=True)
    paylar: Mapped[list["GiderDagitimPay"]] = relationship(
        back_populates="anahtar", cascade="all, delete-orphan"
    )


class GiderDagitimPay(Base):
    __tablename__ = "gider_dagitim_paylari"
    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    anahtar_id: Mapped[int] = mapped_column(ForeignKey("gider_dagitim_anahtarlari.id"), nullable=False)
    hedef_kod: Mapped[str] = mapped_column(String(80), nullable=False)  # şube/kanal kodu
    hedef_ad: Mapped[str] = mapped_column(String(200), nullable=False)
    yuzde: Mapped[Decimal] = mapped_column(Numeric(8, 4), nullable=False, default=0)
    anahtar: Mapped["GiderDagitimAnahtari"] = relationship(back_populates="paylar")
