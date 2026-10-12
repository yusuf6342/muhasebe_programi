"""Ürün bazlı fon payı: fon tanımı, stok fon oranı, satış payı hareketi ve iç para takibi.

Satış payı ``fon_hareketleri`` tablosunda satır×fon bazında saklanır; kaynak belge onayı kaldırıldığında
veya iptal edildiğinde kayıt silinmez, ``durum=IPTAL`` olur. Para ayırma / kullanım yalnızca iç
takiptir (banka transferi veya muhasebe fişi oluşturmaz); düzeltme ters kayıtla yapılır.
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal

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
from sqlalchemy.orm import Mapped, mapped_column

from database.database import Base

YONTEM_IC_PAY = "IC_PAY"
YONTEM_EK_BEDEL = "EK_BEDEL"

KAYNAK_SATIS = "SATIS_FATURASI"
KAYNAK_IADE = "SATIS_IADE"

OLAY_SATIS = "SATIS_PAYI"
OLAY_IADE = "IADE_DUZELTME"
OLAY_INCELEME = "IADE_INCELEME"

DURUM_AKTIF = "AKTIF"
DURUM_IPTAL = "IPTAL"
DURUM_INCELEME = "INCELEME"

PARA_AYIR = "AYIRMA"
PARA_AYIR_GERI = "AYIRMA_GERI"
PARA_KULLANIM = "KULLANIM"
PARA_KULLANIM_GERI = "KULLANIM_GERI"
PARA_TRANSFER_CIKIS = "TRANSFER_CIKIS"
PARA_TRANSFER_GIRIS = "TRANSFER_GIRIS"

TRANSFER_AKTIF = "AKTIF"
TRANSFER_IPTAL = "IPTAL"


class Fon(Base):
    __tablename__ = "fonlar"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    kod: Mapped[str] = mapped_column(String(20), unique=True, nullable=False)
    ad: Mapped[str] = mapped_column(String(100), nullable=False)
    amac: Mapped[str | None] = mapped_column(String(300), nullable=True)
    para_birimi: Mapped[str] = mapped_column(String(3), nullable=False, default="TRY")
    aktif: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    aciklama: Mapped[str | None] = mapped_column(Text, nullable=True)
    yontem: Mapped[str] = mapped_column(String(20), nullable=False, default=YONTEM_IC_PAY)
    ek_bedel_kdv_orani: Mapped[Decimal | None] = mapped_column(Numeric(7, 2), nullable=True)
    # Hesap eşlemeleri mevcut hesap planından seçilir (kod saklanır; hesap açılmaz)
    kullanim_hesap_kodu: Mapped[str | None] = mapped_column(String(30), nullable=True)
    ayirma_hesap_kodu: Mapped[str | None] = mapped_column(String(30), nullable=True)
    ek_bedel_hesap_kodu: Mapped[str | None] = mapped_column(String(30), nullable=True)
    olusturma: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.now)
    olusturan: Mapped[str | None] = mapped_column(String(120), nullable=True)
    guncelleme: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    guncelleyen: Mapped[str | None] = mapped_column(String(120), nullable=True)


class StokFonOrani(Base):
    """Ürün × fon oranı (yüzde). Ürün/fon başına tek kayıt — çakışan aktif tanım oluşamaz."""

    __tablename__ = "stok_fon_oranlari"
    __table_args__ = (UniqueConstraint("stok_id", "fon_id", name="uq_stok_fon_orani"),)

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    stok_id: Mapped[int] = mapped_column(ForeignKey("stok_kartlari.id"), nullable=False, index=True)
    fon_id: Mapped[int] = mapped_column(ForeignKey("fonlar.id"), nullable=False, index=True)
    oran: Mapped[Decimal] = mapped_column(Numeric(9, 4), nullable=False, default=0)
    aktif: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    aciklama: Mapped[str | None] = mapped_column(String(300), nullable=True)
    guncelleme: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.now)
    guncelleyen: Mapped[str | None] = mapped_column(String(120), nullable=True)


class FonOranGecmisi(Base):
    __tablename__ = "fon_oran_gecmisi"
    __table_args__ = (Index("ix_fon_oran_gecmisi_stok", "stok_id", "fon_id"),)

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    stok_id: Mapped[int] = mapped_column(Integer, nullable=False)
    fon_id: Mapped[int] = mapped_column(Integer, nullable=False)
    eski_oran: Mapped[Decimal | None] = mapped_column(Numeric(9, 4), nullable=True)
    yeni_oran: Mapped[Decimal | None] = mapped_column(Numeric(9, 4), nullable=True)
    eski_aktif: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    yeni_aktif: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    kaynak: Mapped[str] = mapped_column(String(20), nullable=False, default="KART")  # KART | TOPLU
    aciklama: Mapped[str | None] = mapped_column(String(300), nullable=True)
    kullanici: Mapped[str | None] = mapped_column(String(120), nullable=True)
    zaman: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.now)


class FonBelgeOrani(Base):
    """Belgenin ilk kesinleştiği andaki ürün×fon oranı; yeniden kesinleştirmede eski oran korunur."""

    __tablename__ = "fon_belge_oranlari"
    __table_args__ = (
        UniqueConstraint("kaynak_turu", "belge_id", "stok_id", "fon_id", name="uq_fon_belge_orani"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    kaynak_turu: Mapped[str] = mapped_column(String(20), nullable=False)
    belge_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    stok_id: Mapped[int] = mapped_column(Integer, nullable=False)
    fon_id: Mapped[int] = mapped_column(Integer, nullable=False)
    oran: Mapped[Decimal] = mapped_column(Numeric(9, 4), nullable=False)
    yontem: Mapped[str] = mapped_column(String(20), nullable=False, default=YONTEM_IC_PAY)
    zaman: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.now)


class FonHareketi(Base):
    """Satış payı / iade düzeltmesi (satır × fon × olay × revizyon)."""

    __tablename__ = "fon_hareketleri"
    __table_args__ = (
        UniqueConstraint(
            "firma_id", "kaynak_turu", "belge_id", "revizyon", "satir_sira", "fon_id", "olay",
            name="uq_fon_hareketi",
        ),
        Index("ix_fon_hareketi_fon_tarih", "fon_id", "durum", "tarih"),
        Index("ix_fon_hareketi_belge", "kaynak_turu", "belge_id", "durum"),
        Index("ix_fon_hareketi_kaynak_satir", "kaynak_satir_id"),
        Index("ix_fon_hareketi_stok", "stok_id", "fon_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    firma_id: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    sube_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    kaynak_turu: Mapped[str] = mapped_column(String(20), nullable=False)
    belge_id: Mapped[int] = mapped_column(Integer, nullable=False)
    belge_no: Mapped[str] = mapped_column(String(50), nullable=False)
    revizyon: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    satir_sira: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    satir_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # İade satırında: kaynak satış satırı (oran ve pay bu satırdan alınır)
    kaynak_satir_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    kaynak_fatura_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    stok_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    urun_kodu: Mapped[str | None] = mapped_column(String(50), nullable=True)
    urun_adi: Mapped[str | None] = mapped_column(String(200), nullable=True)
    cari_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    fon_id: Mapped[int] = mapped_column(ForeignKey("fonlar.id"), nullable=False)
    olay: Mapped[str] = mapped_column(String(20), nullable=False)
    yontem: Mapped[str] = mapped_column(String(20), nullable=False, default=YONTEM_IC_PAY)
    oran: Mapped[Decimal] = mapped_column(Numeric(9, 4), nullable=False, default=0)
    oran_zamani: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    miktar: Mapped[Decimal] = mapped_column(Numeric(18, 6), nullable=False, default=0)
    taban: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False, default=0)
    tutar: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False, default=0)
    para_birimi: Mapped[str] = mapped_column(String(3), nullable=False, default="TRY")
    kur: Mapped[Decimal | None] = mapped_column(Numeric(18, 6), nullable=True)
    doviz_taban: Mapped[Decimal | None] = mapped_column(Numeric(18, 2), nullable=True)
    doviz_tutar: Mapped[Decimal | None] = mapped_column(Numeric(18, 2), nullable=True)
    tarih: Mapped[date] = mapped_column(Date, nullable=False)
    durum: Mapped[str] = mapped_column(String(20), nullable=False, default=DURUM_AKTIF)
    aciklama: Mapped[str | None] = mapped_column(String(300), nullable=True)
    olusturma: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.now)
    kullanici: Mapped[str | None] = mapped_column(String(120), nullable=True)
    iptal_zamani: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    iptal_nedeni: Mapped[str | None] = mapped_column(String(300), nullable=True)


class FonBelgeEkBedeli(Base):
    """Belgeye eklenen fon bedeli (fon başına): matrah, oran, tutar, KDV ve hesap belgede saklanır.

    Ayar sonradan değişse de belge tutarı bu kayıttan okunur. İade belgesinde iade edilen pay yazılır.
    """

    __tablename__ = "fon_belge_ek_bedelleri"
    __table_args__ = (
        UniqueConstraint("kaynak_turu", "belge_id", "fon_id", name="uq_fon_belge_ek_bedeli"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    kaynak_turu: Mapped[str] = mapped_column(String(20), nullable=False)
    belge_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    fon_id: Mapped[int] = mapped_column(ForeignKey("fonlar.id"), nullable=False)
    matrah: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False, default=0)
    # Tüm satırlarda aynı oran varsa yazılır; farklı oranlarda boş kalır (satır payları fon hareketinde)
    oran: Mapped[Decimal | None] = mapped_column(Numeric(9, 4), nullable=True)
    tutar: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False, default=0)
    kdv_orani: Mapped[Decimal] = mapped_column(Numeric(7, 2), nullable=False, default=0)
    kdv: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False, default=0)
    hesap_kodu: Mapped[str | None] = mapped_column(String(30), nullable=True)
    para_birimi: Mapped[str] = mapped_column(String(3), nullable=False, default="TRY")
    kur: Mapped[Decimal | None] = mapped_column(Numeric(18, 6), nullable=True)
    kaynak_fatura_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    zaman: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.now)


class FonTransferi(Base):
    """Aynı firmadaki iki fon arasında ayrılmış (kullanılabilir) TL bakiyenin aktarımı.

    Satış payı ve tahsilatı değiştirmez; kaynakta ``TRANSFER_CIKIS``, hedefte ``TRANSFER_GIRIS`` para
    hareketi aynı transfer kimliğiyle (``ref_id``) yazılır. İptal bağlı ters hareketlerle yapılır.
    """

    __tablename__ = "fon_transferleri"
    __table_args__ = (Index("ix_fon_transfer_tarih", "tarih"),)

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    transfer_no: Mapped[str] = mapped_column(String(30), nullable=False, unique=True)
    firma_id: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    tarih: Mapped[date] = mapped_column(Date, nullable=False)
    kaynak_fon_id: Mapped[int] = mapped_column(ForeignKey("fonlar.id"), nullable=False, index=True)
    hedef_fon_id: Mapped[int] = mapped_column(ForeignKey("fonlar.id"), nullable=False, index=True)
    tutar: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    aciklama: Mapped[str | None] = mapped_column(String(500), nullable=True)
    durum: Mapped[str] = mapped_column(String(10), nullable=False, default=TRANSFER_AKTIF)
    istek_kimligi: Mapped[str | None] = mapped_column(String(64), nullable=True, unique=True)
    kullanici: Mapped[str | None] = mapped_column(String(120), nullable=True)
    olusturma: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.now)
    iptal_tarihi: Mapped[date | None] = mapped_column(Date, nullable=True)
    iptal_gerekcesi: Mapped[str | None] = mapped_column(String(300), nullable=True)
    iptal_eden: Mapped[str | None] = mapped_column(String(120), nullable=True)
    iptal_zamani: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class FonParaHareketi(Base):
    """İç takip: para ayırma, ayırmayı geri alma, kullanım, kullanım düzeltmesi, fon transferi."""

    __tablename__ = "fon_para_hareketleri"
    __table_args__ = (
        Index("ix_fon_para_fon_tarih", "fon_id", "tarih"),
        Index("ix_fon_para_kaynak", "kaynak_anahtar"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    firma_id: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    sube_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    fon_id: Mapped[int] = mapped_column(ForeignKey("fonlar.id"), nullable=False)
    tur: Mapped[str] = mapped_column(String(20), nullable=False)
    tarih: Mapped[date] = mapped_column(Date, nullable=False)
    tutar: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    aciklama: Mapped[str | None] = mapped_column(String(500), nullable=True)
    hesap_adi: Mapped[str | None] = mapped_column(String(100), nullable=True)
    finans_belge_no: Mapped[str | None] = mapped_column(String(50), nullable=True)
    belgesiz: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    # Kaynak tahsilat: "FT:<id>" (fatura tahsilatı) / "MKB:<belge_no>" / "THS:<belge_no>"
    kaynak_anahtar: Mapped[str | None] = mapped_column(String(80), nullable=True)
    kaynak_aciklama: Mapped[str | None] = mapped_column(String(200), nullable=True)
    yardim_alan: Mapped[str | None] = mapped_column(String(200), nullable=True)
    amac: Mapped[str | None] = mapped_column(String(300), nullable=True)
    ref_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    gerekce: Mapped[str | None] = mapped_column(String(300), nullable=True)
    # Aynı ekran işleminin tekrar kaydını engeller (çift tıklama / tekrar gönderim)
    istek_kimligi: Mapped[str | None] = mapped_column(String(64), nullable=True, unique=True)
    kullanici: Mapped[str | None] = mapped_column(String(120), nullable=True)
    olusturma: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.now)
