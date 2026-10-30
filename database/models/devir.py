"""Yıllık devir işi, eşleştirme ve denetim kayıtları.

Aynı firma DB içinde dönemler arası açılış; kart/belge kimlikleri korunur.
Kaynak dönem silinmez; mükerrer bakiye yazımı benzersizlik anahtarıyla engellenir.
"""

from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from database.database import Base

SCHEMA_SURUM = 1

# Devir türü
TUR_ON = "ON_DEVIR"
TUR_KESIN = "KESIN_DEVIR"
TUR_LER = (TUR_ON, TUR_KESIN)

# İş durumları (ekran metinleriyle hizalı kodlar)
DURUM_HAZIRLANIYOR = "HAZIRLANIYOR"
DURUM_KONTROL_GEREKLI = "KONTROL_GEREKLI"
DURUM_ONIZLEME_HAZIR = "ONIZLEME_HAZIR"
DURUM_DEVREDILIYOR = "DEVREDILIYOR"
DURUM_DURAKLATILDI = "DURAKLATILDI"
DURUM_KARSILASTIRILIYOR = "KARSILASTIRILIYOR"
DURUM_TAMAMLANDI = "TAMAMLANDI"
DURUM_UYARILAR_VAR = "UYARILAR_VAR"
DURUM_BASARISIZ = "BASARISIZ"
DURUM_GERI_ALINDI = "GERI_ALINDI"
DURUMLAR = (
    DURUM_HAZIRLANIYOR,
    DURUM_KONTROL_GEREKLI,
    DURUM_ONIZLEME_HAZIR,
    DURUM_DEVREDILIYOR,
    DURUM_DURAKLATILDI,
    DURUM_KARSILASTIRILIYOR,
    DURUM_TAMAMLANDI,
    DURUM_UYARILAR_VAR,
    DURUM_BASARISIZ,
    DURUM_GERI_ALINDI,
)

MODUL_CARI = "CARI"
MODUL_STOK = "STOK"
MODUL_FINANS = "FINANS"
MODUL_ACIK_ISLEM = "ACIK_ISLEM"
MODUL_GM = "GENEL_MUHASEBE"
MODULLER = (MODUL_CARI, MODUL_STOK, MODUL_FINANS, MODUL_ACIK_ISLEM, MODUL_GM)

VARSAYILAN_AYARLAR: dict = {
    "cari_modu": "ACIK_BELGE_VADE",  # veya OZET_BAKIYE
    "stok_maliyet": "MEVCUT_YONTEM",  # FIFO / AO / DONEMSEL_AO / YALNIZ_MIKTAR / SECILEN_FIYAT
    "negatif_kayitlar": "AYNEN",
    "sifir_bakiyeli_kartlar": "KORU",
    "pasif_kartlar": "BAGLANTI_VARSA_ERIS",
    "doviz": "OZGU_KORU",
    "acik_operasyonlar": True,
    "genel_muhasebe": False,
    "donem_kilidi_kesin": True,
    "tolerans_para": "0.01",
    "tolerans_miktar": "0.000001",
}


class DevirAyar(Base):
    """Firma varsayılan devir tercihleri (sürümlü)."""

    __tablename__ = "devir_ayarlari"

    firma_id: Mapped[int] = mapped_column(Integer, primary_key=True)
    ayarlar_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    surum: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    guncelleme: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    guncelleyen: Mapped[str | None] = mapped_column(String(120), nullable=True)


class DevirIs(Base):
    """Kimlikli yıllık devir işi. Kod: DEV-YYYY-####."""

    __tablename__ = "devir_isleri"
    __table_args__ = (
        UniqueConstraint("firma_id", "is_no", name="uq_devir_is_firma_no"),
        Index("ix_devir_is_kaynak_hedef", "firma_id", "kaynak_donem_id", "hedef_donem_id"),
        Index("ix_devir_is_durum", "firma_id", "durum"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    is_no: Mapped[str] = mapped_column(String(24), nullable=False)
    firma_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    kaynak_donem_id: Mapped[int] = mapped_column(Integer, nullable=False)
    hedef_donem_id: Mapped[int] = mapped_column(Integer, nullable=False)
    kesim_tarihi: Mapped[date] = mapped_column(Date, nullable=False)
    acilis_tarihi: Mapped[date] = mapped_column(Date, nullable=False)
    devir_turu: Mapped[str] = mapped_column(String(20), nullable=False, default=TUR_ON)
    durum: Mapped[str] = mapped_column(String(30), nullable=False, default=DURUM_HAZIRLANIYOR)
    kapsam_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    ayarlar_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    ayarlar_surum: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    schema_surum: Mapped[int] = mapped_column(Integer, nullable=False, default=SCHEMA_SURUM)
    onizleme_gecerli: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    onizleme_ozet_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    yedek_yolu: Mapped[str | None] = mapped_column(String(500), nullable=True)
    yedek_dogrulandi: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    ilerleme_modul: Mapped[str | None] = mapped_column(String(40), nullable=True)
    ilerleme_islenen: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    ilerleme_toplam: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    kontrol_noktasi: Mapped[str | None] = mapped_column(String(80), nullable=True)
    hata_mesaji: Mapped[str | None] = mapped_column(Text, nullable=True)
    uyari_sayisi: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    hata_sayisi: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    olusturma: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.now)
    olusturan: Mapped[str | None] = mapped_column(String(120), nullable=True)
    baslama: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    bitis: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    eslesmeler: Mapped[list["DevirEslesme"]] = relationship(
        "DevirEslesme",
        back_populates="devir_is",
        cascade="all, delete-orphan",
    )
    denetimler: Mapped[list["DevirDenetim"]] = relationship(
        "DevirDenetim",
        back_populates="devir_is",
        cascade="all, delete-orphan",
    )


class DevirEslesme(Base):
    """Kaynak kalem → hedef açılış eşlemesi (tekrar çalıştırma güvenliği)."""

    __tablename__ = "devir_eslesmeler"
    __table_args__ = (
        UniqueConstraint(
            "firma_id",
            "benzersizlik_anahtar",
            name="uq_devir_eslesme_benzersiz",
        ),
        Index("ix_devir_eslesme_is_modul", "is_id", "modul"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    is_id: Mapped[int] = mapped_column(ForeignKey("devir_isleri.id"), nullable=False)
    firma_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    modul: Mapped[str] = mapped_column(String(40), nullable=False)
    kaynak_tip: Mapped[str] = mapped_column(String(60), nullable=False)
    kaynak_id: Mapped[str] = mapped_column(String(80), nullable=False)
    kaynak_anahtar: Mapped[str | None] = mapped_column(String(200), nullable=True)
    hedef_tip: Mapped[str | None] = mapped_column(String(60), nullable=True)
    hedef_id: Mapped[str | None] = mapped_column(String(80), nullable=True)
    benzersizlik_anahtar: Mapped[str] = mapped_column(String(240), nullable=False)
    tutar: Mapped[float | None] = mapped_column(Numeric(18, 4), nullable=True)
    miktar: Mapped[float | None] = mapped_column(Numeric(18, 6), nullable=True)
    para_birimi: Mapped[str | None] = mapped_column(String(3), nullable=True)
    durum: Mapped[str] = mapped_column(String(20), nullable=False, default="YAZILDI")
    detay_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    olusturma: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.now)

    devir_is: Mapped["DevirIs"] = relationship("DevirIs", back_populates="eslesmeler")


class DevirDenetim(Base):
    """Devir işi olay geçmişi (ayar sürümü, yedek, durum geçişi)."""

    __tablename__ = "devir_denetim"
    __table_args__ = (Index("ix_devir_denetim_is", "is_id", "olusturma"),)

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    is_id: Mapped[int | None] = mapped_column(
        ForeignKey("devir_isleri.id"), nullable=True, index=True
    )
    firma_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    olay: Mapped[str] = mapped_column(String(60), nullable=False)
    detay_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    olusturma: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.now)
    kullanici: Mapped[str | None] = mapped_column(String(120), nullable=True)

    devir_is: Mapped["DevirIs | None"] = relationship("DevirIs", back_populates="denetimler")
