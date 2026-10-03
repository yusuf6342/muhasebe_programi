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
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from database.database import Base
from database.models.sube import Sube  # noqa: F401

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
    # Banka kredileri
    ("kredi_kisa_vadeli", "Kısa vadeli banka kredileri (300)"),
    ("kredi_uzun_vadeli", "Uzun vadeli banka kredileri (400)"),
    ("kredi_faiz_gideri", "Faiz giderleri"),
    ("kredi_bsmv_gideri", "BSMV giderleri"),
    ("kredi_kkdf_gideri", "KKDF giderleri"),
    ("kredi_komisyon_gideri", "Banka komisyon giderleri"),
    ("kredi_sigorta_gideri", "Sigorta giderleri"),
    ("kredi_dosya_masrafi", "Dosya/işlem masrafları"),
    ("kredi_gecikme_faizi", "Gecikme faizleri"),
    ("kredi_diger_finansman", "Diğer finansman giderleri"),
    ("kredi_ara_hesap", "Kredi ara hesabı"),
    ("kur_farki_geliri", "Kur farkı gelirleri"),
    ("kur_farki_gideri", "Kur farkı giderleri"),
    ("alis_iade_maliyet_farki_olumlu", "Alış iadesi olumlu maliyet farkı (iade bedeli > FIFO stok maliyeti)"),
    ("alis_iade_maliyet_farki_olumsuz", "Alış iadesi olumsuz maliyet farkı (iade bedeli < FIFO stok maliyeti)"),
    # Finans işlem ayarları (Ayarlar → Muhasebeleştirme Ayarları → Finans İşlem Ayarları)
    ("kmh_hesabi", "KMH (kredili mevduat) hesabı"),
    ("pos_valor_alacagi", "POS valör alacağı (bankadan alınacak kart tahsilatı)"),
    ("pos_komisyon_gideri", "POS komisyon gideri"),
    ("sirket_kart_borcu", "Şirket kredi kartı borcu"),
    ("cek_portfoy", "Alınan çekler — portföyde"),
    ("cek_tahsilde", "Alınan çekler — tahsile verilen"),
    ("cek_teminatta", "Alınan çekler — teminata verilen"),
    ("senet_portfoy", "Alacak senetleri — portföyde"),
    ("senet_tahsilde", "Alacak senetleri — tahsile verilen"),
    ("senet_teminatta", "Alacak senetleri — teminata verilen"),
    ("verilen_cekler", "Verilen çekler ve ödeme emirleri"),
    ("borc_senetleri", "Borç senetleri"),
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
    sube_id: Mapped[int | None] = mapped_column(ForeignKey("subeler.id"), nullable=True, index=True)
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


YONTEM_OTOMATIK = "otomatik"
YONTEM_SONRADAN = "sonradan"
YONTEM_VARSAYILAN = "varsayilan"
FIRMA_GENELI = "*"

BELGE_BEKLIYOR = "Bekliyor"
BELGE_MUHASEBELESTIRILDI = "Muhasebeleştirildi"
BELGE_HATALI = "Hatalı"
BELGE_INCELEME = "İnceleme gerekiyor"
BELGE_IPTAL = "İptal edildi"
BELGE_MUHASEBE_DISI = "Muhasebe dışı"
BELGE_DURUMLARI = (
    BELGE_BEKLIYOR,
    BELGE_HATALI,
    BELGE_INCELEME,
    BELGE_MUHASEBELESTIRILDI,
    BELGE_IPTAL,
    BELGE_MUHASEBE_DISI,
)
# Sonradan muhasebeleştirilebilecek durumlar
BELGE_ISLENEBILIR = (BELGE_BEKLIYOR, BELGE_HATALI, BELGE_INCELEME)


class MuhasebelestirmeAyari(Base):
    """Firma ve evrak türü bazında muhasebeleştirme yöntemi.

    ``evrak_turu == "*"`` satırı firma geneli: genel muhasebe kullanımı ve varsayılan yöntem.
    Diğer satırlar evrak türüne özel yöntem (``varsayilan`` = firma genelini kullan).
    """

    __tablename__ = "muhasebe_muhasebelestirme_ayarlari"
    __table_args__ = (
        UniqueConstraint("firma_id", "evrak_turu", name="uq_mhl_ayar_evrak"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    firma_id: Mapped[int] = mapped_column(ForeignKey("firmalar.id"), nullable=False, index=True)
    evrak_turu: Mapped[str] = mapped_column(String(40), nullable=False)
    gm_kullan: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    yontem: Mapped[str] = mapped_column(String(20), nullable=False)
    kaynak: Mapped[str] = mapped_column(String(20), default="kullanici", nullable=False)
    aciklama: Mapped[Optional[str]] = mapped_column(String(300), nullable=True)
    guncelleyen_kullanici_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    guncelleyen_kullanici_adi: Mapped[Optional[str]] = mapped_column(String(80), nullable=True)
    guncelleme_tarihi: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.now, nullable=False
    )


class MuhasebeFinansAyari(Base):
    """Firma bazlı finans işlem muhasebe seçenekleri (çek/senet aşamaları, banka kredisi fiş zamanı vb.).

    Hesaplar ``MuhasebeHesapEsleme``'de tutulur; burada yalnız seçenek değerleri vardır. Satır yoksa
    seçenek tanımsızdır ve ilgili evrak "İnceleme gerekiyor" kalır (varsayılan tahmin edilmez).
    """

    __tablename__ = "muhasebe_finans_ayarlari"
    __table_args__ = (UniqueConstraint("firma_id", "anahtar", name="uq_mh_finans_ayar"),)

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    firma_id: Mapped[int] = mapped_column(ForeignKey("firmalar.id"), nullable=False, index=True)
    anahtar: Mapped[str] = mapped_column(String(60), nullable=False)
    deger: Mapped[str] = mapped_column(String(60), nullable=False)
    guncelleyen_kullanici_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    guncelleyen_kullanici_adi: Mapped[Optional[str]] = mapped_column(String(80), nullable=True)
    guncelleme_tarihi: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.now, nullable=False
    )


class MuhasebeBelgeDurumu(Base):
    """Kaynak evrakın muhasebeleştirme kimliği ve durumu (firma + evrak türü + kalıcı evrak id).

    Evrak numarası/açıklama yalnız görüntüleme içindir; eşleştirme için kullanılmaz.
    """

    __tablename__ = "muhasebe_belge_durumlari"
    __table_args__ = (
        UniqueConstraint("firma_id", "evrak_turu", "kaynak_id", name="uq_mhl_belge"),
        Index("ix_mhl_belge_durum_tarih", "firma_id", "durum", "belge_tarihi"),
        Index("ix_mhl_belge_fis", "fis_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    firma_id: Mapped[int] = mapped_column(ForeignKey("firmalar.id"), nullable=False)
    evrak_turu: Mapped[str] = mapped_column(String(40), nullable=False)
    kaynak_id: Mapped[int] = mapped_column(Integer, nullable=False)
    durum: Mapped[str] = mapped_column(String(30), nullable=False)
    fis_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("muhasebe_fisleri.id"), nullable=True
    )
    belge_no: Mapped[Optional[str]] = mapped_column(String(60), nullable=True)
    belge_tarihi: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    cari_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    cari_adi: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)
    tutar: Mapped[Decimal] = mapped_column(Numeric(18, 2), default=Decimal("0"), nullable=False)
    para_birimi: Mapped[str] = mapped_column(String(10), default="TRY", nullable=False)
    aciklama: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    yontem: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
    deneme_sayisi: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    row_version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    olusturma_tarihi: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.now, nullable=False
    )
    guncelleme_tarihi: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.now, nullable=False
    )
    guncelleyen_kullanici_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    guncelleyen_kullanici_adi: Mapped[Optional[str]] = mapped_column(String(80), nullable=True)


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


KUR_FARKI_HESAPLANDI = "HESAPLANDI"
KUR_FARKI_INCELEME = "INCELEME"
KUR_FARKI_IPTAL = "IPTAL"


class KurFarkiKaydi(Base):
    """Dövizli borç/alacak kapatmasında gerçekleşen kur farkı (kaynak belge + kapatma bağlantısıyla).

    Bir kapatma (``kapatma_turu`` + ``kapatma_id``) için en çok bir etkin (iptal olmayan) kayıt bulunur;
    iptal edilen kayıt silinmez. ``kur_farki`` işaretlidir: + kur farkı geliri, − kur farkı gideri.
    Kur veya kaynak bilgisi eksikse durum ``INCELEME`` olur ve fark hesaplanmaz (tahmin edilmez).
    """

    __tablename__ = "muhasebe_kur_farki_kayitlari"
    __table_args__ = (
        Index("ix_mh_kf_kapatma", "kapatma_turu", "kapatma_id", "durum"),
        Index("ix_mh_kf_kaynak", "kaynak_evrak", "kaynak_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    firma_id: Mapped[int] = mapped_column(ForeignKey("firmalar.id"), nullable=False, index=True)
    yon: Mapped[str] = mapped_column(String(10), nullable=False)  # SATIS (alacak) | ALIS (borç)
    cari_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    kaynak_evrak: Mapped[str] = mapped_column(String(40), nullable=False)
    kaynak_id: Mapped[int] = mapped_column(Integer, nullable=False)
    kaynak_belge_no: Mapped[Optional[str]] = mapped_column(String(60), nullable=True)
    kapatma_turu: Mapped[str] = mapped_column(String(40), nullable=False)
    kapatma_id: Mapped[int] = mapped_column(Integer, nullable=False)
    kapatma_belge_no: Mapped[Optional[str]] = mapped_column(String(60), nullable=True)
    tarih: Mapped[date] = mapped_column(Date, nullable=False)
    para_birimi: Mapped[str] = mapped_column(String(10), nullable=False)
    doviz_tutar: Mapped[Decimal] = mapped_column(Numeric(18, 2), default=Decimal("0"), nullable=False)
    kaynak_kur: Mapped[Optional[Decimal]] = mapped_column(Numeric(18, 6), nullable=True)
    odeme_kuru: Mapped[Optional[Decimal]] = mapped_column(Numeric(18, 6), nullable=True)
    kaynak_tl: Mapped[Decimal] = mapped_column(Numeric(18, 2), default=Decimal("0"), nullable=False)
    odeme_tl: Mapped[Decimal] = mapped_column(Numeric(18, 2), default=Decimal("0"), nullable=False)
    kur_farki: Mapped[Decimal] = mapped_column(Numeric(18, 2), default=Decimal("0"), nullable=False)
    durum: Mapped[str] = mapped_column(String(20), nullable=False, default=KUR_FARKI_HESAPLANDI)
    aciklama: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    olusturma: Mapped[datetime] = mapped_column(DateTime, default=datetime.now, nullable=False)
    olusturan: Mapped[Optional[str]] = mapped_column(String(80), nullable=True)
    iptal_zamani: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    iptal_nedeni: Mapped[Optional[str]] = mapped_column(String(300), nullable=True)
