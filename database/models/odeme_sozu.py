"""Ödeme sözleri — finansal etkisi olmayan planlama / takip kayıtları (firma veritabanında)."""

from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import Boolean, Date, DateTime, ForeignKey, Index, Integer, Numeric, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from database.database import Base


class OdemeSozu(Base):
    """Müşteriden alınan (ALINAN) veya tedarikçiye verilen (VERILEN) ödeme sözü.

    Kalan tutar yalnız gerçek ödeme evraklarına bağlantılardan hesaplanır; söz bakiye, fatura,
    kasa/banka veya fişe hiçbir kayıt yazmaz.
    """

    __tablename__ = "odeme_sozleri"
    __table_args__ = (Index("ix_odeme_sozu_vade", "vade_tarihi", "yon"),)

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    cari_id: Mapped[int] = mapped_column(ForeignKey("cari_kartlar.id"), nullable=False, index=True)
    yon: Mapped[str] = mapped_column(String(10), nullable=False)  # ALINAN | VERILEN
    soz_tarihi: Mapped[date] = mapped_column(Date, nullable=False)
    vade_tarihi: Mapped[date] = mapped_column(Date, nullable=False)
    tutar: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    para_birimi: Mapped[str] = mapped_column(String(3), nullable=False, default="TRY")
    yontem: Mapped[str] = mapped_column(String(30), nullable=False, default="Havale/EFT")
    gorusulen_kisi: Mapped[str | None] = mapped_column(String(120), nullable=True)
    aciklama: Mapped[str | None] = mapped_column(String(500), nullable=True)
    sorumlu: Mapped[str | None] = mapped_column(String(120), nullable=True)
    # None | IPTAL | TAMAMLANDI (yetkili düzeltme; para hareketi oluşturmaz)
    kapanis: Mapped[str | None] = mapped_column(String(20), nullable=True)
    kapanis_nedeni: Mapped[str | None] = mapped_column(String(300), nullable=True)
    ertelendi: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    son_not: Mapped[str | None] = mapped_column(String(500), nullable=True)
    son_not_tarihi: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    hatirlat_tarihi: Mapped[date | None] = mapped_column(Date, nullable=True)
    olusturan: Mapped[str | None] = mapped_column(String(120), nullable=True)
    olusturma: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.now)
    guncelleyen: Mapped[str | None] = mapped_column(String(120), nullable=True)
    guncelleme: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    faturalar: Mapped[list["OdemeSozuFatura"]] = relationship(
        "OdemeSozuFatura", back_populates="soz", cascade="all, delete-orphan"
    )
    baglantilar: Mapped[list["OdemeSozuBaglanti"]] = relationship(
        "OdemeSozuBaglanti", back_populates="soz", cascade="all, delete-orphan"
    )
    gecmis: Mapped[list["OdemeSozuGecmis"]] = relationship(
        "OdemeSozuGecmis", back_populates="soz", cascade="all, delete-orphan",
        order_by="OdemeSozuGecmis.id",
    )


class OdemeSozuFatura(Base):
    """Sözün ilgili olduğu fatura(lar) ve tutar(lar)ı — bilgi amaçlı; faturayı kapatmaz."""

    __tablename__ = "odeme_sozu_faturalari"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    soz_id: Mapped[int] = mapped_column(ForeignKey("odeme_sozleri.id"), nullable=False, index=True)
    belge_no: Mapped[str] = mapped_column(String(50), nullable=False)
    tutar: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)

    soz: Mapped["OdemeSozu"] = relationship("OdemeSozu", back_populates="faturalar")


class OdemeSozuBaglanti(Base):
    """Gerçek ödeme evrakı ↔ söz bağlantısı (çoktan çoğa). İptal edilir, silinmez."""

    __tablename__ = "odeme_sozu_baglantilari"
    __table_args__ = (Index("ix_odeme_sozu_baglanti_evrak", "evrak_belge_no", "iptal"),)

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    soz_id: Mapped[int] = mapped_column(ForeignKey("odeme_sozleri.id"), nullable=False, index=True)
    evrak_turu: Mapped[str] = mapped_column(String(40), nullable=False)
    evrak_belge_no: Mapped[str] = mapped_column(String(50), nullable=False)
    evrak_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    evrak_tutari: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False, default=0)
    tutar: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    para_birimi: Mapped[str] = mapped_column(String(3), nullable=False, default="TRY")
    tarih: Mapped[date] = mapped_column(Date, nullable=False)
    kullanici: Mapped[str | None] = mapped_column(String(120), nullable=True)
    olusturma: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.now)
    iptal: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    iptal_zamani: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    iptal_kullanici: Mapped[str | None] = mapped_column(String(120), nullable=True)
    iptal_nedeni: Mapped[str | None] = mapped_column(String(300), nullable=True)

    soz: Mapped["OdemeSozu"] = relationship("OdemeSozu", back_populates="baglantilar")


class OdemeSozuGecmis(Base):
    """Söz değişiklik ve görüşme geçmişi — üzerine yazılmaz, yalnız eklenir."""

    __tablename__ = "odeme_sozu_gecmisi"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    soz_id: Mapped[int] = mapped_column(ForeignKey("odeme_sozleri.id"), nullable=False, index=True)
    zaman: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.now)
    kullanici: Mapped[str | None] = mapped_column(String(120), nullable=True)
    islem: Mapped[str] = mapped_column(String(30), nullable=False)
    eski_deger: Mapped[str | None] = mapped_column(String(200), nullable=True)
    yeni_deger: Mapped[str | None] = mapped_column(String(200), nullable=True)
    aciklama: Mapped[str | None] = mapped_column(String(500), nullable=True)

    soz: Mapped["OdemeSozu"] = relationship("OdemeSozu", back_populates="gecmis")


class OdemeSozuAyar(Base):
    """Firma bazlı ödeme sözü ayarları (ör. yaklaşıyor eşiği)."""

    __tablename__ = "odeme_sozu_ayarlari"

    anahtar: Mapped[str] = mapped_column(String(50), primary_key=True)
    deger: Mapped[str] = mapped_column(String(200), nullable=False)
