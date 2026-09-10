"""Gelir / gider hizmet kartları ve hareketleri."""

from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import Boolean, Date, DateTime, ForeignKey, Integer, Numeric, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from database.database import Base

HIZMET_TURLERI = (
    ("GIDER", "Gider Hizmeti"),
    ("GELIR", "Gelir Hizmeti"),
)

# Gider kartı rapor sınıfları (yalnızca hizmet_turu=GIDER)
GIDER_SINIFLARI = (
    ("ISLETME", "İşletme giderleri"),
    ("PERSONEL", "Personel giderleri"),
    ("FINANS_MALI", "Finans ve mali giderler"),
    ("ARAC", "Araç giderleri"),
)

GIDER_SINIF_KODLARI = {k for k, _ in GIDER_SINIFLARI}

# Otomatik hizmet kodu ön ekleri
GIDER_SINIF_ONEKLERI = {
    "ISLETME": "IGZ",
    "PERSONEL": "PGZ",
    "FINANS_MALI": "FMZ",
    "ARAC": "AGZ",
}


def gider_sinifi_etiket(kod: str | None) -> str:
    if not kod:
        return "—"
    return dict(GIDER_SINIFLARI).get(str(kod).upper(), str(kod))


HIZMET_BIRIMLERI = (
    "Adet",
    "Saat",
    "Gün",
    "Ay",
    "Yıl",
    "Km",
    "m²",
    "Paket",
    "Diğer",
)

KDV_ORANLARI = ("0", "1", "10", "20")


class HizmetKarti(Base):
    """Gelir veya gider hizmet kartı — faturalarda kullanılacak hizmet tanımı."""

    __tablename__ = "hizmet_kartlari"
    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    hizmet_kodu: Mapped[str] = mapped_column(String(40), unique=True, nullable=False, index=True)
    hizmet_adi: Mapped[str] = mapped_column(String(200), nullable=False)
    # GIDER | GELIR
    hizmet_turu: Mapped[str] = mapped_column(String(10), nullable=False, index=True)
    # ISLETME | PERSONEL | FINANS_MALI | ARAC — yalnızca GIDER kartlarında dolu
    gider_sinifi: Mapped[str | None] = mapped_column(String(20), nullable=True, index=True)
    birim: Mapped[str] = mapped_column(String(30), nullable=False, default="Adet")
    alis_fiyati: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False, default=0)
    satis_fiyati: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False, default=0)
    kdv_orani: Mapped[Decimal] = mapped_column(Numeric(8, 2), nullable=False, default=20)
    # Muhasebe hesap kodları
    muhasebe_gider_kodu: Mapped[str | None] = mapped_column(String(50), nullable=True)
    muhasebe_gelir_kodu: Mapped[str | None] = mapped_column(String(50), nullable=True)
    muhasebe_kdv_alis_kodu: Mapped[str | None] = mapped_column(String(50), nullable=True)
    muhasebe_kdv_satis_kodu: Mapped[str | None] = mapped_column(String(50), nullable=True)
    aciklama: Mapped[str | None] = mapped_column(String(500), nullable=True)
    aktif: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    olusturma_zamani: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.now)
    hareketler: Mapped[list["HizmetHareketi"]] = relationship(
        "HizmetHareketi",
        back_populates="hizmet",
        cascade="all, delete-orphan",
        order_by="HizmetHareketi.id",
    )


class HizmetHareketi(Base):
    """Hizmet kartı hareketi — fatura / iade bağlantılı satırlar burada listelenir."""

    __tablename__ = "hizmet_hareketleri"
    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    hizmet_id: Mapped[int] = mapped_column(ForeignKey("hizmet_kartlari.id"), nullable=False, index=True)
    tarih: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    # HİZMET ALIŞ (GİDER) | HİZMET ALIŞ İADE | HİZMET SATIŞ (GELİR) | HİZMET SATIŞ İADE | MANUEL
    hareket_turu: Mapped[str] = mapped_column(String(40), nullable=False)
    belge_no: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    miktar: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False, default=1)
    birim_fiyat: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False, default=0)
    kdv_orani: Mapped[Decimal] = mapped_column(Numeric(8, 2), nullable=False, default=0)
    tutar: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False, default=0)
    # +1 giriş (gelir / iade alışı), -1 çıkış (gider / iade satışı) — rapor için
    isaret: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    cari_id: Mapped[int | None] = mapped_column(nullable=True, index=True)
    aciklama: Mapped[str | None] = mapped_column(String(500), nullable=True)
    hizmet: Mapped["HizmetKarti"] = relationship("HizmetKarti", back_populates="hareketler")
