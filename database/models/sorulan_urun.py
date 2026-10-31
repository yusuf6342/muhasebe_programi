"""Sorulan Ürünler — ürün tanımı (aday) + müşteri talebi (stok/fatura hareketi yok)."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal

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
from sqlalchemy.orm import Mapped, mapped_column

from database.database import Base

# Teknik kodlar (DB); UI etiketleri serviste
TALEP_NEDENLERI = (
    "CESITTE_YOK",
    "STOKTA_YOK",
    "FIYAT_YUKSEK",
    "TEDARIK_GECIKME",
    "DIGER",
)
TALEP_NEDENI_ETIKET = {
    "CESITTE_YOK": "Çeşitte yok",
    "STOKTA_YOK": "Stokta yok",
    "FIYAT_YUKSEK": "Fiyat yüksek",
    "TEDARIK_GECIKME": "Tedarik gecikmesi",
    "DIGER": "Diğer",
}
NIYETLER = ("SADECE_SORDU", "ALMAK_ISTIYOR", "TEKLIF_ISTIYOR", "SIPARIS_VERECEK")
NIYET_ETIKET = {
    "SADECE_SORDU": "Sadece sordu",
    "ALMAK_ISTIYOR": "Almak istiyor",
    "TEKLIF_ISTIYOR": "Teklif istiyor",
    "SIPARIS_VERECEK": "Sipariş verecek",
}
TALEP_DURUMLARI = (
    "ACIK",
    "BILGI_BEKLENIYOR",
    "ARASTIRILIYOR",
    "TEDARIKCI_BEKLENIYOR",
    "FIYAT_BEKLENIYOR",
    "MUSTERIYE_BILDIRILDI",
    "KARSILANDI",
    "VAZGECILDI",
    "BULUNAMADI",
    "TAKIPTE",
    "SATINALMA_ARA",
    "SIPARIS_VERILDI",
    "URUN_GELDI",
    "ARAMA_BEKLIYOR",
    "SATISA_DONUSTU",
    "IPTAL",
    "ARSIV",
)
TALEP_DURUM_ETIKET = {
    "ACIK": "Açık",
    "BILGI_BEKLENIYOR": "Ek bilgi bekleniyor",
    "ARASTIRILIYOR": "Araştırılıyor",
    "TEDARIKCI_BEKLENIYOR": "Tedarikçi cevabı bekleniyor",
    "FIYAT_BEKLENIYOR": "Fiyat bekleniyor",
    "MUSTERIYE_BILDIRILDI": "Müşteriye bildirildi",
    "KARSILANDI": "Karşılandı",
    "VAZGECILDI": "Vazgeçildi",
    "BULUNAMADI": "Bulunamadı",
    "TAKIPTE": "Takipte",
    "SATINALMA_ARA": "Satınalma ara",
    "SIPARIS_VERILDI": "Sipariş verildi",
    "URUN_GELDI": "Ürün geldi",
    "ARAMA_BEKLIYOR": "Arama bekliyor",
    "SATISA_DONUSTU": "Satışa dönüştü",
    "IPTAL": "İptal",
    "ARSIV": "Arşiv",
}
URUN_TEDARIK_DURUMLARI = (
    "BEKLEMEDE",
    "ARAŞTIRILIYOR",
    "SIPARIS_VERILDI",
    "GELDI",
    "STOKTA",
)
TANIM_DURUMLARI = ("TANIMLANAMADI", "KISMEN", "TANIMLANDI")
TANIM_DURUM_ETIKET = {
    "TANIMLANAMADI": "Tanımlanamadı",
    "KISMEN": "Kısmen tanımlandı",
    "TANIMLANDI": "Tanımlandı",
}
MUADIL_SECENEKLERI = ("AYNISI_SART", "MUADIL_OLABILIR", "SORULMADI")
MUADIL_ETIKET = {
    "AYNISI_SART": "Aynısı şart",
    "MUADIL_OLABILIR": "Uygun muadil olabilir",
    "SORULMADI": "Henüz sorulmadı",
}
OLCU_KAYNAKLARI = (
    "MUSTERI_BILDIRDI",
    "TAHMINI",
    "NUMUNEDEN",
    "TEDARIKCI",
)
OLCU_KAYNAK_ETIKET = {
    "MUSTERI_BILDIRDI": "Müşteri bildirdi",
    "TAHMINI": "Tahmini",
    "NUMUNEDEN": "Numuneden ölçüldü",
    "TEDARIKCI": "Tedarikçi doğruladı",
}
ARAMA_SONUCLARI = (
    "ULASILDI",
    "ULASILAMADI",
    "FIYAT_BEKLIYOR",
    "DAHA_SONRA_ARA",
    "VAZGECTI",
    "SIPARISE_DONUSTU",
)
FOTOGRAF_ETIKETLERI = (
    "Önden",
    "Arkadan",
    "Takılı olduğu yer",
    "Etiket",
    "Ölçülü görünüm",
    "Diğer",
)


class SorulanUrunAday(Base):
    __tablename__ = "sorulan_urun_adaylari"
    __table_args__ = (
        UniqueConstraint("firma_id", "normalize_ad", name="uq_sorulan_urun_firma_norm"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    firma_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    urun_adi: Mapped[str] = mapped_column(String(200), nullable=False, default="")
    normalize_ad: Mapped[str] = mapped_column(String(220), nullable=False, index=True)
    # İlk müşteri tarifi — gerçek ad sonradan gelse de korunur
    ilk_tarif: Mapped[str | None] = mapped_column(Text, nullable=True)
    musteri_tarifi: Mapped[str | None] = mapped_column(Text, nullable=True)
    diger_adlar: Mapped[str | None] = mapped_column(String(400), nullable=True)
    urun_grubu: Mapped[str | None] = mapped_column(String(80), nullable=True)
    urun_grubu_aciklama: Mapped[str | None] = mapped_column(String(200), nullable=True)
    marka: Mapped[str | None] = mapped_column(String(100), nullable=True)
    model: Mapped[str | None] = mapped_column(String(100), nullable=True)
    uretici_kodu: Mapped[str | None] = mapped_column(String(100), nullable=True)
    barkod: Mapped[str | None] = mapped_column(String(80), nullable=True)
    urun_yazilari: Mapped[str | None] = mapped_column(Text, nullable=True)
    kullanim_amaci: Mapped[str | None] = mapped_column(Text, nullable=True)
    uyum_bilgisi: Mapped[str | None] = mapped_column(Text, nullable=True)
    malzeme: Mapped[str | None] = mapped_column(String(120), nullable=True)
    renk: Mapped[str | None] = mapped_column(String(80), nullable=True)
    kaplama: Mapped[str | None] = mapped_column(String(80), nullable=True)
    sekil: Mapped[str | None] = mapped_column(String(80), nullable=True)
    calisma_bicimi: Mapped[str | None] = mapped_column(String(120), nullable=True)
    numune_var: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    numune_yer: Mapped[str | None] = mapped_column(String(200), nullable=True)
    internet_link: Mapped[str | None] = mapped_column(String(500), nullable=True)
    katalog_sayfa: Mapped[str | None] = mapped_column(String(200), nullable=True)
    tanim_durumu: Mapped[str] = mapped_column(
        String(30), nullable=False, default="TANIMLANAMADI"
    )
    ozellik: Mapped[str | None] = mapped_column(String(300), nullable=True)
    birim: Mapped[str | None] = mapped_column(String(40), nullable=True)
    stok_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    talep_nedeni_ozet: Mapped[str | None] = mapped_column(String(40), nullable=True)
    tedarik_durumu: Mapped[str] = mapped_column(
        String(30), nullable=False, default="BEKLEMEDE"
    )
    sorumlu_personel: Mapped[str | None] = mapped_column(String(80), nullable=True)
    arsiv: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    olusturan: Mapped[str | None] = mapped_column(String(80), nullable=True)
    olusturma_tarihi: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=datetime.utcnow
    )
    guncelleme_tarihi: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class SorulanUrunTalep(Base):
    __tablename__ = "sorulan_urun_talepleri"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    firma_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    aday_id: Mapped[int] = mapped_column(
        ForeignKey("sorulan_urun_adaylari.id"), nullable=False, index=True
    )
    # Sorulduğu tarih (= müşterinin sorduğu gün); sistem kayıt zamanı ayrı
    talep_tarihi: Mapped[date] = mapped_column(Date, nullable=False)
    sorulma_saati: Mapped[str | None] = mapped_column(String(8), nullable=True)
    sorulma_tarihi_bilinmiyor: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False
    )
    cari_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    musteri_adi: Mapped[str | None] = mapped_column(String(200), nullable=True)
    telefon: Mapped[str | None] = mapped_column(String(40), nullable=True)
    anonim: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    miktar: Mapped[Decimal | None] = mapped_column(Numeric(18, 4), nullable=True)
    birim: Mapped[str | None] = mapped_column(String(40), nullable=True)
    karsilanan_miktar: Mapped[Decimal] = mapped_column(
        Numeric(18, 4), nullable=False, default=Decimal("0")
    )
    iptal_miktar: Mapped[Decimal] = mapped_column(
        Numeric(18, 4), nullable=False, default=Decimal("0")
    )
    niyet: Mapped[str] = mapped_column(String(30), nullable=False, default="SADECE_SORDU")
    talep_nedeni: Mapped[str] = mapped_column(String(40), nullable=False, default="CESITTE_YOK")
    durum: Mapped[str] = mapped_column(String(30), nullable=False, default="ACIK")
    talep_aciklama: Mapped[str | None] = mapped_column(Text, nullable=True)
    ihtiyac_tarihi: Mapped[date | None] = mapped_column(Date, nullable=True)
    aciliyet: Mapped[str | None] = mapped_column(String(40), nullable=True)
    muadil: Mapped[str] = mapped_column(String(30), nullable=False, default="SORULMADI")
    hedef_fiyat: Mapped[Decimal | None] = mapped_column(Numeric(18, 4), nullable=True)
    sorumlu_personel: Mapped[str | None] = mapped_column(String(80), nullable=True)
    sonraki_takip: Mapped[date | None] = mapped_column(Date, nullable=True)
    sonuc_tarihi: Mapped[date | None] = mapped_column(Date, nullable=True)
    kaynak: Mapped[str | None] = mapped_column(String(40), nullable=True)
    notlar: Mapped[str | None] = mapped_column(Text, nullable=True)
    sonraki_arama: Mapped[date | None] = mapped_column(Date, nullable=True)
    olusturan: Mapped[str | None] = mapped_column(String(80), nullable=True)
    olusturma_tarihi: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=datetime.utcnow
    )
    guncelleme_tarihi: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    gecersiz: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)


class SorulanUrunOlcu(Base):
    __tablename__ = "sorulan_urun_olculeri"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    aday_id: Mapped[int] = mapped_column(
        ForeignKey("sorulan_urun_adaylari.id"), nullable=False, index=True
    )
    olcu_adi: Mapped[str] = mapped_column(String(80), nullable=False)
    deger: Mapped[str | None] = mapped_column(String(40), nullable=True)  # bilinmiyor → None
    birim: Mapped[str | None] = mapped_column(String(20), nullable=True)
    aciklama: Mapped[str | None] = mapped_column(String(200), nullable=True)
    kaynak: Mapped[str] = mapped_column(String(30), nullable=False, default="TAHMINI")
    sira: Mapped[int] = mapped_column(Integer, nullable=False, default=0)


class SorulanUrunEk(Base):
    """Fotoğraf / PDF / çizim / kısa video — dosya yolu firma verisinde."""

    __tablename__ = "sorulan_urun_ekleri"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    aday_id: Mapped[int] = mapped_column(
        ForeignKey("sorulan_urun_adaylari.id"), nullable=False, index=True
    )
    dosya_yolu: Mapped[str] = mapped_column(String(500), nullable=False)
    orijinal_ad: Mapped[str | None] = mapped_column(String(200), nullable=True)
    mime: Mapped[str | None] = mapped_column(String(80), nullable=True)
    etiket: Mapped[str | None] = mapped_column(String(80), nullable=True)
    aciklama: Mapped[str | None] = mapped_column(String(300), nullable=True)
    ana_fotograf: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    onizleme_yolu: Mapped[str | None] = mapped_column(String(500), nullable=True)
    olusturma_tarihi: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=datetime.utcnow
    )


class SorulanUrunTekrar(Base):
    """Aynı talebe tarihli «Tekrar soruldu» — miktar/bağımsız talep artmaz."""

    __tablename__ = "sorulan_urun_tekrarlar"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    talep_id: Mapped[int] = mapped_column(
        ForeignKey("sorulan_urun_talepleri.id"), nullable=False, index=True
    )
    tekrar_tarihi: Mapped[date] = mapped_column(Date, nullable=False)
    tekrar_saati: Mapped[str | None] = mapped_column(String(8), nullable=True)
    notlar: Mapped[str | None] = mapped_column(Text, nullable=True)
    olusturan: Mapped[str | None] = mapped_column(String(80), nullable=True)
    olusturma_tarihi: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=datetime.utcnow
    )


class SorulanUrunGorusme(Base):
    """Tedarikçi / araştırma tarihli geçmiş."""

    __tablename__ = "sorulan_urun_gorusmeler"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    aday_id: Mapped[int] = mapped_column(
        ForeignKey("sorulan_urun_adaylari.id"), nullable=False, index=True
    )
    talep_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    gorusme_tarihi: Mapped[date] = mapped_column(Date, nullable=False)
    tedarikci: Mapped[str | None] = mapped_column(String(200), nullable=True)
    cevap: Mapped[str | None] = mapped_column(Text, nullable=True)
    bulunan_kod: Mapped[str | None] = mapped_column(String(100), nullable=True)
    fiyat: Mapped[Decimal | None] = mapped_column(Numeric(18, 4), nullable=True)
    teslim_suresi: Mapped[str | None] = mapped_column(String(80), nullable=True)
    notlar: Mapped[str | None] = mapped_column(Text, nullable=True)
    olusturan: Mapped[str | None] = mapped_column(String(80), nullable=True)
    olusturma_tarihi: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=datetime.utcnow
    )


class SorulanUrunTarihLog(Base):
    """Sorulma tarihi düzeltme geçmişi."""

    __tablename__ = "sorulan_urun_tarih_log"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    talep_id: Mapped[int] = mapped_column(
        ForeignKey("sorulan_urun_talepleri.id"), nullable=False, index=True
    )
    eski_tarih: Mapped[str | None] = mapped_column(String(20), nullable=True)
    yeni_tarih: Mapped[str | None] = mapped_column(String(20), nullable=True)
    kullanici: Mapped[str | None] = mapped_column(String(80), nullable=True)
    degisim_zamani: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=datetime.utcnow
    )
    notlar: Mapped[str | None] = mapped_column(String(200), nullable=True)
