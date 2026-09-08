from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import Boolean, Date, DateTime, ForeignKey, Integer, Numeric, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from database.database import Base

# Banka ana kartındaki alt hesap türleri (sağ üst bakiyeler + alt menüler)
BANKA_ALT_HESAP_TURLERI = (
    ("MEVDUAT", "Mevduat Hesabı"),
    ("KMH", "KMH Hesabı"),
    ("POS", "POS Hesabı"),
    ("KREDI_KARTI", "Kredi Kartı Hesabı"),
    ("KREDILER", "Krediler Hesabı"),
)

POS_KART_TIPLERI = (
    ("KREDI_KARTI", "Kredi Kartı"),
    ("BANKA_KARTI", "Banka Kartı"),
)


class BankaKarti(Base):
    """Banka ana kartı — hesap no, IBAN, banka/şube; altında 5 finans hesabı."""

    __tablename__ = "banka_kartlari"
    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    banka_adi: Mapped[str] = mapped_column(String(100), nullable=False)
    sube: Mapped[str | None] = mapped_column(String(100), nullable=True)
    hesap_no: Mapped[str | None] = mapped_column(String(50), nullable=True)
    iban: Mapped[str | None] = mapped_column(String(34), nullable=True)
    aciklama: Mapped[str | None] = mapped_column(String(500), nullable=True)
    # POS hesabı ile bağlantılı komisyon / valör ayarları
    kk_komisyon_orani: Mapped[Decimal] = mapped_column(Numeric(8, 4), nullable=False, default=0)
    banka_karti_komisyon_orani: Mapped[Decimal] = mapped_column(Numeric(8, 4), nullable=False, default=0)
    pos_valor_gun: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    aktif: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    alt_hesaplar: Mapped[list["FinansHesabi"]] = relationship(
        "FinansHesabi",
        back_populates="banka_karti",
        cascade="all, delete-orphan",
    )
    pos_valor_kayitlari: Mapped[list["PosValorKaydi"]] = relationship(
        "PosValorKaydi",
        back_populates="banka_karti",
        cascade="all, delete-orphan",
    )


class FinansHesabi(Base):
    __tablename__ = "finans_hesaplari"
    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    hesap_adi: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)
    hesap_turu: Mapped[str] = mapped_column(String(30), nullable=False)  # KASA | BANKA | KREDİ KARTI
    acilis_bakiyesi: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False, default=0)
    banka_adi: Mapped[str | None] = mapped_column(String(100), nullable=True)
    sube: Mapped[str | None] = mapped_column(String(100), nullable=True)
    iban: Mapped[str | None] = mapped_column(String(34), nullable=True)
    aciklama: Mapped[str | None] = mapped_column(String(500), nullable=True)
    aktif: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    banka_karti_id: Mapped[int | None] = mapped_column(
        ForeignKey("banka_kartlari.id"), nullable=True, index=True
    )
    alt_hesap_turu: Mapped[str | None] = mapped_column(String(30), nullable=True)  # MEVDUAT|KMH|...
    banka_karti: Mapped["BankaKarti | None"] = relationship("BankaKarti", back_populates="alt_hesaplar")
    hareketler: Mapped[list["FinansHareketi"]] = relationship(
        "FinansHareketi", back_populates="hesap", cascade="all, delete-orphan"
    )


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


class PosValorKaydi(Base):
    """POS tahsilat sonrası komisyon düşülmüş net tutarın KMH'ye valör aktarımı."""

    __tablename__ = "pos_valor_kayitlari"
    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    banka_karti_id: Mapped[int] = mapped_column(ForeignKey("banka_kartlari.id"), nullable=False, index=True)
    pos_hesap_id: Mapped[int] = mapped_column(ForeignKey("finans_hesaplari.id"), nullable=False)
    kmh_hesap_id: Mapped[int] = mapped_column(ForeignKey("finans_hesaplari.id"), nullable=False)
    belge_no: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    tahsilat_tarihi: Mapped[date] = mapped_column(Date, nullable=False)
    valor_tarihi: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    valor_saati: Mapped[str] = mapped_column(String(8), nullable=False, default="08:00")
    kart_tipi: Mapped[str] = mapped_column(String(20), nullable=False)  # KREDI_KARTI | BANKA_KARTI
    brut_tutar: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    komisyon_orani: Mapped[Decimal] = mapped_column(Numeric(8, 4), nullable=False, default=0)
    komisyon_tutari: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False, default=0)
    net_tutar: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    cari_id: Mapped[int | None] = mapped_column(nullable=True)
    durum: Mapped[str] = mapped_column(String(20), nullable=False, default="BEKLIYOR")  # BEKLIYOR|AKTARILDI
    aktarim_zamani: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    aciklama: Mapped[str | None] = mapped_column(String(500), nullable=True)
    banka_karti: Mapped["BankaKarti"] = relationship("BankaKarti", back_populates="pos_valor_kayitlari")
