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
    func,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from database.database import Base
from database.models.sube import Sube  # noqa: F401

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

KK_CEKIM_TURLERI = (
    ("TEK_CEKIM", "Tek Çekim"),
    ("TAKSITLI", "Taksitli Çekim"),
)

KK_MAX_TAKSIT = 24
POS_MAX_TAKSIT = 12
KREDI_MAX_TAKSIT = 120

KREDI_TURLERI = (
    ("ISLETME", "İşletme Kredisi"),
    ("SPOT", "Spot Kredi"),
    ("TAKSITLI", "Taksitli Ticari Kredi"),
    ("TASIT", "Taşıt Kredisi"),
    ("DIGER", "Diğer"),
)

KREDI_ODEME_HESAP_TURLERI = (
    ("MEVDUAT", "Mevduat"),
    ("KMH", "KMH"),
)

KREDI_FAIZ_TURLERI = (
    ("SABIT", "Sabit"),
    ("DEGISKEN", "Değişken"),
)

KREDI_TAKSIT_DONEMLERI = (
    ("AYLIK", "Aylık"),
    ("UCAYLIK", "Üç aylık"),
    ("OZEL", "Özel"),
)

KREDI_PARA_BIRIMLERI = (
    ("TRY", "TL"),
    ("USD", "USD"),
    ("EUR", "EUR"),
)

KREDI_TAKSIT_DURUMLARI = (
    ("BEKLIYOR", "Bekliyor"),
    ("YAKLASIYOR", "Yaklaşıyor"),
    ("VADESI_GECTI", "Vadesi geçti"),
    ("KISMEN_ODENDI", "Kısmen ödendi"),
    ("ODENDI", "Ödendi"),
    ("IPTAL", "İptal edildi"),
    ("YAPILANDIRILDI", "Yapılandırıldı"),
    ("ERKEN_KAPATILDI", "Erken kapatıldı"),
)

KREDI_GIDER_BILESENLERI = (
    ("FAIZ", "Faiz gideri", "KREDI_FAIZ"),
    ("BSMV", "BSMV", "KREDI_BSMV"),
    ("KKDF", "KKDF", "KREDI_KKDF"),
    ("KOMISYON", "Banka komisyonu", "KREDI_KOMISYON"),
    ("SIGORTA", "Sigorta gideri", "KREDI_SIGORTA"),
    ("DOSYA", "Dosya/işlem masrafı", "KREDI_DOSYA"),
    ("DIGER", "Diğer finansman giderleri", "KREDI_MASRAF"),
    ("GECIKME", "Gecikme faizi", "KREDI_GECIKME"),
)

KREDI_KISMI_DAGITIM_YONTEMLERI = (
    ("MANUEL", "Manuel dağıtım"),
    ("ONCE_MASRAF", "Önce masraflar ve faiz, sonra anapara"),
    ("ORANSAL", "Ödeme planı oranlarına göre"),
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
    # KMH (kredili mevduat): bu limite kadar eksi bakiyeye düşülebilir
    kmh_limiti: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False, default=0)
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
    kredi_kartlari: Mapped[list["KrediKartiTanimi"]] = relationship(
        "KrediKartiTanimi",
        back_populates="banka_karti",
        cascade="all, delete-orphan",
    )
    pos_taksit_komisyonlari: Mapped[list["PosTaksitKomisyon"]] = relationship(
        "PosTaksitKomisyon",
        back_populates="banka_karti",
        cascade="all, delete-orphan",
        order_by="PosTaksitKomisyon.taksit_sayisi",
    )
    banka_kredileri: Mapped[list["BankaKredisi"]] = relationship(
        "BankaKredisi",
        back_populates="banka_karti",
        cascade="all, delete-orphan",
    )


class BankAccountMatchRule(Base):
    """EvoBulut banka kartı ↔ yerel BankaKarti eşleştirme hafızası (hareket aktarımı için)."""

    __tablename__ = "bank_account_match_rules"
    __table_args__ = (UniqueConstraint("evo_banka_id", name="uq_bank_match_evo_id"),)

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    evo_banka_id: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    evo_banka_adi: Mapped[str | None] = mapped_column(String(200), nullable=True)
    banka_karti_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("banka_kartlari.id"), nullable=False, index=True
    )
    finans_hesap_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("finans_hesaplari.id"), nullable=True
    )
    alt_hesap_turu: Mapped[str] = mapped_column(String(20), nullable=False, default="MEVDUAT")
    iban: Mapped[str | None] = mapped_column(String(34), nullable=True)
    hesap_no: Mapped[str | None] = mapped_column(String(50), nullable=True)
    guven: Mapped[Decimal | None] = mapped_column(Numeric(5, 2), nullable=True)
    kaynak: Mapped[str | None] = mapped_column(String(40), nullable=True)  # api|manuel|iban
    aktif: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.now)
    updated_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class PosTaksitKomisyon(Base):
    """POS kredi kartı tahsilatında taksit sayısına göre komisyon oranı (1-12)."""

    __tablename__ = "pos_taksit_komisyonlari"
    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    banka_karti_id: Mapped[int] = mapped_column(ForeignKey("banka_kartlari.id"), nullable=False, index=True)
    taksit_sayisi: Mapped[int] = mapped_column(Integer, nullable=False)  # 1..12
    komisyon_orani: Mapped[Decimal] = mapped_column(Numeric(8, 4), nullable=False, default=0)
    banka_karti: Mapped["BankaKarti"] = relationship("BankaKarti", back_populates="pos_taksit_komisyonlari")


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
    # Kartın muhasebe karşılığı (muhasebe_hesap_plani.id); boşsa firma eşleştirmesi (kasa / banka / KMH...)
    muhasebe_hesap_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # Yalnız POS alt hesabı: komisyon gideri hesabı; boşsa firma eşleştirmesi (pos_komisyon_gideri)
    muhasebe_komisyon_hesap_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    banka_karti: Mapped["BankaKarti | None"] = relationship("BankaKarti", back_populates="alt_hesaplar")
    hareketler: Mapped[list["FinansHareketi"]] = relationship(
        "FinansHareketi", back_populates="hesap", cascade="all, delete-orphan"
    )


class FinansHareketi(Base):
    __tablename__ = "finans_hareketleri"
    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    hesap_id: Mapped[int] = mapped_column(ForeignKey("finans_hesaplari.id"), nullable=False, index=True)
    sube_id: Mapped[int | None] = mapped_column(ForeignKey("subeler.id"), nullable=True, index=True)
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
    taksit_sayisi: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    brut_tutar: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    komisyon_orani: Mapped[Decimal] = mapped_column(Numeric(8, 4), nullable=False, default=0)
    komisyon_tutari: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False, default=0)
    net_tutar: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    cari_id: Mapped[int | None] = mapped_column(nullable=True)
    durum: Mapped[str] = mapped_column(String(20), nullable=False, default="BEKLIYOR")  # BEKLIYOR|AKTARILDI
    aktarim_zamani: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    aciklama: Mapped[str | None] = mapped_column(String(500), nullable=True)
    banka_karti: Mapped["BankaKarti"] = relationship("BankaKarti", back_populates="pos_valor_kayitlari")


class KrediKartiTanimi(Base):
    """Firmanın ödeme aracı olan fiziksel/sanal kredi kartı tanımı (banka ana kartına bağlı)."""

    __tablename__ = "kredi_karti_tanimlari"
    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    banka_karti_id: Mapped[int] = mapped_column(ForeignKey("banka_kartlari.id"), nullable=False, index=True)
    kart_bankasi: Mapped[str | None] = mapped_column(String(100), nullable=True)
    kart_adi: Mapped[str] = mapped_column(String(100), nullable=False)
    kart_sahibi: Mapped[str | None] = mapped_column(String(100), nullable=True)
    kart_markasi: Mapped[str | None] = mapped_column(String(30), nullable=True)  # Visa|Mastercard|Troy|Amex
    kart_numarasi: Mapped[str | None] = mapped_column(String(32), nullable=True)
    son_dort_hane: Mapped[str | None] = mapped_column(String(4), nullable=True)
    son_kullanim: Mapped[str | None] = mapped_column(String(7), nullable=True)  # AA/YY
    guvenlik_kodu: Mapped[str | None] = mapped_column(String(4), nullable=True)
    kart_limiti: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False, default=0)
    hesap_kesim_gunu: Mapped[int | None] = mapped_column(Integer, nullable=True)  # ayın 1-31
    son_odeme_gunu: Mapped[int | None] = mapped_column(Integer, nullable=True)  # ayın 1-31
    kesimden_sonra_odeme_gun: Mapped[int | None] = mapped_column(Integer, nullable=True)
    para_birimi: Mapped[str | None] = mapped_column(String(10), nullable=True, default="TRY")
    bagli_hesap_id: Mapped[int | None] = mapped_column(Integer, nullable=True)  # FinansHesabi
    odeme_hesap_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    tatil_odeme_kurali: Mapped[str | None] = mapped_column(
        String(20), nullable=True, default="AYNI_GUN"
    )  # AYNI_GUN | SONRAKI_IS_GUNU | ONCEKI_IS_GUNU
    aciklama: Mapped[str | None] = mapped_column(String(500), nullable=True)
    aktif: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    banka_karti: Mapped["BankaKarti"] = relationship("BankaKarti", back_populates="kredi_kartlari")
    odemeler: Mapped[list["KrediKartiOdeme"]] = relationship(
        "KrediKartiOdeme",
        back_populates="kredi_karti",
    )
    ekstreler: Mapped[list["KrediKartiEkstre"]] = relationship(
        "KrediKartiEkstre",
        back_populates="kredi_karti",
        cascade="all, delete-orphan",
    )


class KrediKartiEkstre(Base):
    """Kart ekstresi — benzersiz anahtar: kredi_karti_id + kesim_tarihi."""

    __tablename__ = "kredi_karti_ekstreleri"
    __table_args__ = (
        UniqueConstraint("kredi_karti_id", "kesim_tarihi", name="uq_kk_ekstre_kart_kesim"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    kredi_karti_id: Mapped[int] = mapped_column(
        ForeignKey("kredi_karti_tanimlari.id"), nullable=False, index=True
    )
    kesim_tarihi: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    donem_baslangic: Mapped[date] = mapped_column(Date, nullable=False)
    donem_bitis: Mapped[date] = mapped_column(Date, nullable=False)
    # Kartın son ödeme günü tanımsızsa boş (tahmin edilmez); durum EKSIK_BILGI olur
    son_odeme_tarihi: Mapped[date | None] = mapped_column(Date, nullable=True, index=True)
    # KESILMEMIS | KESILMIS | KISMI | ODENDI | GECIKMIS | FAZLA | EKSIK_BILGI
    durum: Mapped[str] = mapped_column(String(20), nullable=False, default="KESILMEMIS")
    toplam_borc: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False, default=0)
    odenen: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False, default=0)
    kalan: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False, default=0)
    para_birimi: Mapped[str] = mapped_column(String(10), nullable=False, default="TRY")
    kesin: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    olusturma: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.now)
    guncelleme: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    kredi_karti: Mapped["KrediKartiTanimi"] = relationship(
        "KrediKartiTanimi", back_populates="ekstreler"
    )
    odemeler: Mapped[list["KrediKartiEkstreOdeme"]] = relationship(
        "KrediKartiEkstreOdeme",
        back_populates="ekstre",
        cascade="all, delete-orphan",
        order_by="KrediKartiEkstreOdeme.id",
    )


class KrediKartiEkstreOdeme(Base):
    """Ekstreye bağlı banka/kasa ödemesi — mükerrer belge_no engelli."""

    __tablename__ = "kredi_karti_ekstre_odemeleri"
    __table_args__ = (Index("ux_kk_ekstre_odeme_istek", "istek_anahtari", unique=True),)

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    ekstre_id: Mapped[int] = mapped_column(
        ForeignKey("kredi_karti_ekstreleri.id"), nullable=False, index=True
    )
    belge_no: Mapped[str] = mapped_column(String(50), unique=True, nullable=False, index=True)
    tarih: Mapped[date] = mapped_column(Date, nullable=False)
    tutar: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    hesap_turu: Mapped[str] = mapped_column(String(20), nullable=False, default="MEVDUAT")
    finans_hesap_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    dekont_no: Mapped[str | None] = mapped_column(String(50), nullable=True)
    aciklama: Mapped[str | None] = mapped_column(String(500), nullable=True)
    finans_belge_no: Mapped[str | None] = mapped_column(String(50), nullable=True)
    iptal: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    iptal_tarihi: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    olusturma: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.now)
    # Aynı istekle ikinci kayıt yeni ödeme üretmez (kayıtlı ödeme döner)
    istek_anahtari: Mapped[str | None] = mapped_column(String(64), nullable=True)
    # EKSTRE | KASADAN_BANKAYA | VIRMAN — ödemenin girildiği ekran (etki her durumda aynı)
    kaynak: Mapped[str | None] = mapped_column(String(20), nullable=True)
    kart_hesap_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    iptal_islem_tarihi: Mapped[date | None] = mapped_column(Date, nullable=True)
    iptal_nedeni: Mapped[str | None] = mapped_column(String(300), nullable=True)
    iptal_kullanici: Mapped[str | None] = mapped_column(String(120), nullable=True)
    ekstre: Mapped["KrediKartiEkstre"] = relationship(
        "KrediKartiEkstre", back_populates="odemeler"
    )


class KrediKartiEkstreOdemeTaksit(Base):
    """Ekstre ödemesinin kapattığı taksit payları (kısmi pay dahil); iptal edilen ödemenin satırları korunur."""

    __tablename__ = "kredi_karti_ekstre_odeme_taksitleri"
    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    ekstre_odeme_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    taksit_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    tutar: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    iptal: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)


class KartBakiyeOnarimGunlugu(Base):
    """Kart bakiyesi geçmiş kayıt onarımı: eski / yeni değer, kaynak kimliği, yedek; geri alınabilir."""

    __tablename__ = "kart_bakiye_onarim_gunlugu"
    __table_args__ = (UniqueConstraint("onarim_kodu", "anahtar", name="uq_kart_bakiye_onarim"),)
    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    onarim_kodu: Mapped[str] = mapped_column(String(40), nullable=False)
    anahtar: Mapped[str] = mapped_column(String(80), nullable=False)
    sinif: Mapped[str] = mapped_column(String(40), nullable=False)
    kaynak_turu: Mapped[str] = mapped_column(String(40), nullable=False)
    kaynak_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    belge_no: Mapped[str | None] = mapped_column(String(50), nullable=True)
    finans_hareketi_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    hesap_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    tutar: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False, default=0)
    eski_deger: Mapped[str | None] = mapped_column(String(200), nullable=True)
    yeni_deger: Mapped[str | None] = mapped_column(String(200), nullable=True)
    bakiye_once: Mapped[Decimal | None] = mapped_column(Numeric(18, 2), nullable=True)
    bakiye_sonra: Mapped[Decimal | None] = mapped_column(Numeric(18, 2), nullable=True)
    yedek_yolu: Mapped[str | None] = mapped_column(String(500), nullable=True)
    kullanici: Mapped[str | None] = mapped_column(String(120), nullable=True)
    uygulama_zamani: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.now)
    geri_alindi: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    geri_alma_zamani: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class KrediKartiOdeme(Base):
    """Kredi kartı ile yapılan cari ödeme evrakı (tek çekim veya taksitli)."""

    __tablename__ = "kredi_karti_odemeleri"
    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    belge_no: Mapped[str] = mapped_column(String(50), unique=True, nullable=False, index=True)
    tarih: Mapped[date] = mapped_column(Date, nullable=False)
    vade_tarihi: Mapped[date] = mapped_column(Date, nullable=False)  # tek çekim = tarih; taksit = 1. taksit
    banka_karti_id: Mapped[int] = mapped_column(ForeignKey("banka_kartlari.id"), nullable=False, index=True)
    kredi_karti_id: Mapped[int] = mapped_column(ForeignKey("kredi_karti_tanimlari.id"), nullable=False, index=True)
    # Gider kaynaklı ödemede cari yoktur: 0 yazılır, kaynak_turu=GIDER (cari hareketi oluşmaz)
    cari_id: Mapped[int] = mapped_column(nullable=False, index=True)
    cekim_turu: Mapped[str] = mapped_column(String(20), nullable=False)  # TEK_CEKIM | TAKSITLI | IADE
    taksit_sayisi: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    tutar: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    referans_no: Mapped[str | None] = mapped_column(String(50), nullable=True)  # POS/onay no
    aciklama: Mapped[str | None] = mapped_column(String(500), nullable=True)
    durum: Mapped[str] = mapped_column(String(20), nullable=False, default="AÇIK")  # AÇIK|İPTAL
    kaynak_turu: Mapped[str] = mapped_column(
        String(20), nullable=False, default="CARI", server_default="CARI"
    )  # CARI | GIDER
    gider_kart_odeme_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    # Kartla gider: bu kaydın muhasebede bir kez yazdığı finansman farkı (düzeltme kaydında fark değişimi, eksi
    # olabilir). Boşsa eski kural: yalnız ana kart ödemesi gider kaydındaki farkı yazar.
    finansman_farki: Mapped[Decimal | None] = mapped_column(Numeric(18, 2), nullable=True)
    # Kayıt düzeltmesiyle oluşan kart kaydında düzeltme günlüğü satırı
    duzeltme_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    kredi_karti: Mapped["KrediKartiTanimi"] = relationship("KrediKartiTanimi", back_populates="odemeler")
    taksitler: Mapped[list["KrediKartiOdemeTaksit"]] = relationship(
        "KrediKartiOdemeTaksit",
        back_populates="odeme",
        cascade="all, delete-orphan",
        order_by="KrediKartiOdemeTaksit.taksit_no",
    )


class KrediKartiOdemeTaksit(Base):
    """KK ödeme taksit satırı — vade = çekim günü + (n-1) ay (aynı gün)."""

    __tablename__ = "kredi_karti_odeme_taksitleri"
    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    odeme_id: Mapped[int] = mapped_column(ForeignKey("kredi_karti_odemeleri.id"), nullable=False, index=True)
    taksit_no: Mapped[int] = mapped_column(Integer, nullable=False)
    vade_tarihi: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    tutar: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    durum: Mapped[str] = mapped_column(String(20), nullable=False, default="BEKLIYOR")  # BEKLIYOR|ODENDI|IADE
    # Banka planındaki ekstre kesimi; boşsa çekim tarihi + taksit no kuralıyla hesaplanır
    ekstre_kesim_tarihi: Mapped[date | None] = mapped_column(Date, nullable=True)
    odeme: Mapped["KrediKartiOdeme"] = relationship("KrediKartiOdeme", back_populates="taksitler")


class GiderKartOdeme(Base):
    """Giderin kredi kartıyla ödenmesi: gider fişi + kart ödemesi (+ ayrı ücret) + sabit gider bağlantısı.

    gider_tutari giderin kapanan kısmıdır; kart_toplami karta borç yazılan toplamdır (finansman dahil).
    Aradaki fark finansman gideri olarak yalnız ana kart ödemesinin fişinde bir kez işlenir.
    """

    __tablename__ = "gider_kart_odemeleri"
    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    istek_anahtari: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    kaynak_turu: Mapped[str] = mapped_column(String(20), nullable=False)  # SABIT | GIDER_FISI
    kredi_karti_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    kk_odeme_id: Mapped[int] = mapped_column(Integer, nullable=False, unique=True)
    ucret_kk_odeme_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    gider_fisi_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    sabit_donem_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    baglanti_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    islem_tarihi: Mapped[date] = mapped_column(Date, nullable=False)
    gider_tutari: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    kart_toplami: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    finansman_farki: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False, default=0)
    faiz_durumu: Mapped[str] = mapped_column(String(10), nullable=False)  # FAIZSIZ | GIRILDI
    # Kartın kesim günü tanımsızken boş: dönem kesim günü girilince kendiliğinden belirlenir
    ilk_kesim: Mapped[date | None] = mapped_column(Date, nullable=True)
    aciklama: Mapped[str | None] = mapped_column(String(500), nullable=True)
    durum: Mapped[str] = mapped_column(String(10), nullable=False, default="AÇIK")  # AÇIK | IPTAL
    olusturan: Mapped[str | None] = mapped_column(String(120), nullable=True)
    olusturma: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.now)
    iptal_zamani: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    iptal_kullanici: Mapped[str | None] = mapped_column(String(120), nullable=True)
    iptal_nedeni: Mapped[str | None] = mapped_column(String(300), nullable=True)


class GiderKartDuzeltme(Base):
    """Kartla gider ödemesinin kayıt düzeltmesi günlüğü: eski / yeni değerler, neden, kullanıcı, zaman.

    TAM: hiçbir taksit / ekstre ödemesi yokken eski kart kayıtları DÜZELTİLDİ olur, yenileri yazılır.
    ACIK_DONEM: ödenmiş dönemler aynen kalır; yalnız açık dönemler düzeltme kaydıyla değişir.
    """

    __tablename__ = "gider_kart_duzeltmeleri"
    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    gider_kart_odeme_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    istek_anahtari: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    tur: Mapped[str] = mapped_column(String(12), nullable=False)  # TAM | ACIK_DONEM
    duzeltme_tarihi: Mapped[date] = mapped_column(Date, nullable=False)
    neden: Mapped[str] = mapped_column(String(300), nullable=False)
    kullanici: Mapped[str | None] = mapped_column(String(120), nullable=True)
    zaman: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.now)
    eski_degerler: Mapped[str] = mapped_column(Text, nullable=False)  # JSON
    yeni_degerler: Mapped[str] = mapped_column(Text, nullable=False)  # JSON
    eski_odemeler: Mapped[str | None] = mapped_column(String(500), nullable=True)  # DÜZELTİLDİ olan belgeler
    yeni_odemeler: Mapped[str | None] = mapped_column(String(500), nullable=True)
    duzeltme_odeme_id: Mapped[int | None] = mapped_column(Integer, nullable=True)  # açık dönem ters/fark kaydı


class GiderKartIade(Base):
    """Bankanın gerçek iadesi ve kırılımı: gider (ana para), faiz ve ayrı ücret payı ilgili kart kayıtlarına bağlı."""

    __tablename__ = "gider_kart_iadeleri"
    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    gider_kart_odeme_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    kk_odeme_id: Mapped[int] = mapped_column(Integer, nullable=False, unique=True)  # IADE kart kaydı
    istek_anahtari: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    tarih: Mapped[date] = mapped_column(Date, nullable=False)
    kesim: Mapped[date | None] = mapped_column(Date, nullable=True)
    gider_tutari: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False, default=0)
    faiz_tutari: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False, default=0)
    ucret_tutari: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False, default=0)
    faiz_kk_odeme_id: Mapped[int | None] = mapped_column(Integer, nullable=True)  # finansman farkını yazan kayıt
    ucret_kk_odeme_id: Mapped[int | None] = mapped_column(Integer, nullable=True)  # ayrı ücret kart kaydı
    aciklama: Mapped[str | None] = mapped_column(String(500), nullable=True)
    olusturan: Mapped[str | None] = mapped_column(String(120), nullable=True)
    olusturma: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.now)


class BankaKredisi(Base):
    """Banka kredisi — ana para krediler hesabına borç; faiz/masraf taksit gününde gider."""

    __tablename__ = "banka_kredileri"
    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    belge_no: Mapped[str] = mapped_column(String(50), unique=True, nullable=False, index=True)
    banka_karti_id: Mapped[int] = mapped_column(ForeignKey("banka_kartlari.id"), nullable=False, index=True)
    kredi_adi: Mapped[str] = mapped_column(String(120), nullable=False)
    kredi_turu: Mapped[str] = mapped_column(String(30), nullable=False, default="ISLETME")
    ana_para: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    toplam_faiz: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False, default=0)
    toplam_masraf: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False, default=0)
    taksit_sayisi: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    kullandirim_tarihi: Mapped[date] = mapped_column(Date, nullable=False)
    ilk_taksit_tarihi: Mapped[date] = mapped_column(Date, nullable=False)
    odeme_hesap_turu: Mapped[str] = mapped_column(String(20), nullable=False, default="MEVDUAT")
    sozlesme_no: Mapped[str | None] = mapped_column(String(50), nullable=True)
    aciklama: Mapped[str | None] = mapped_column(String(500), nullable=True)
    # KULLANDIRILDI | KAPALI | IPTAL | PASIF
    durum: Mapped[str] = mapped_column(String(20), nullable=False, default="KULLANDIRILDI")
    # Soft ALTER ile eklenen kurumsal alanlar
    kredi_kodu: Mapped[str | None] = mapped_column(String(40), nullable=True, index=True)
    banka_sube: Mapped[str | None] = mapped_column(String(100), nullable=True)
    kredi_hesap_no: Mapped[str | None] = mapped_column(String(50), nullable=True)
    kullanim_amaci: Mapped[str | None] = mapped_column(String(200), nullable=True)
    notlar: Mapped[str | None] = mapped_column(Text, nullable=True)
    faiz_orani: Mapped[Decimal | None] = mapped_column(Numeric(10, 4), nullable=True)
    faiz_turu: Mapped[str | None] = mapped_column(String(20), nullable=True, default="SABIT")
    taksit_donemi: Mapped[str | None] = mapped_column(String(20), nullable=True, default="AYLIK")
    para_birimi: Mapped[str | None] = mapped_column(String(10), nullable=True, default="TRY")
    kur: Mapped[Decimal | None] = mapped_column(Numeric(18, 6), nullable=True)
    kur_tarihi: Mapped[date | None] = mapped_column(Date, nullable=True)
    tl_karsiligi: Mapped[Decimal | None] = mapped_column(Numeric(18, 2), nullable=True)
    bitis_tarihi: Mapped[date | None] = mapped_column(Date, nullable=True)
    plan_versiyon: Mapped[int | None] = mapped_column(Integer, nullable=True, default=1)
    aktif: Mapped[bool | None] = mapped_column(Boolean, nullable=True, default=True)
    banka_karti: Mapped["BankaKarti"] = relationship("BankaKarti", back_populates="banka_kredileri")
    taksitler: Mapped[list["BankaKrediTaksit"]] = relationship(
        "BankaKrediTaksit",
        back_populates="kredi",
        cascade="all, delete-orphan",
        order_by="BankaKrediTaksit.taksit_no",
    )


class BankaKrediTaksit(Base):
    """Kredi taksit satırı — anapara / faiz / vergi / masraf ayrı; anapara gider yazılmaz."""

    __tablename__ = "banka_kredi_taksitleri"
    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    kredi_id: Mapped[int] = mapped_column(ForeignKey("banka_kredileri.id"), nullable=False, index=True)
    taksit_no: Mapped[int] = mapped_column(Integer, nullable=False)
    vade_tarihi: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    anapara: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False, default=0)
    faiz: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False, default=0)
    masraf: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False, default=0)
    durum: Mapped[str] = mapped_column(String(20), nullable=False, default="BEKLIYOR")
    odeme_tarihi: Mapped[date | None] = mapped_column(Date, nullable=True)
    odeme_belge_no: Mapped[str | None] = mapped_column(String(50), nullable=True, index=True)
    gider_belge_no: Mapped[str | None] = mapped_column(String(50), nullable=True, index=True)
    # Soft ALTER — bileşen kırılımı
    bsmv: Mapped[Decimal | None] = mapped_column(Numeric(18, 2), nullable=True, default=0)
    kkdf: Mapped[Decimal | None] = mapped_column(Numeric(18, 2), nullable=True, default=0)
    komisyon: Mapped[Decimal | None] = mapped_column(Numeric(18, 2), nullable=True, default=0)
    sigorta: Mapped[Decimal | None] = mapped_column(Numeric(18, 2), nullable=True, default=0)
    dosya_masrafi: Mapped[Decimal | None] = mapped_column(Numeric(18, 2), nullable=True, default=0)
    diger_masraflar: Mapped[Decimal | None] = mapped_column(Numeric(18, 2), nullable=True, default=0)
    gecikme_faizi: Mapped[Decimal | None] = mapped_column(Numeric(18, 2), nullable=True, default=0)
    odenen_anapara: Mapped[Decimal | None] = mapped_column(Numeric(18, 2), nullable=True, default=0)
    odenen_faiz: Mapped[Decimal | None] = mapped_column(Numeric(18, 2), nullable=True, default=0)
    odenen_masraf: Mapped[Decimal | None] = mapped_column(Numeric(18, 2), nullable=True, default=0)
    odenen_tutar: Mapped[Decimal | None] = mapped_column(Numeric(18, 2), nullable=True, default=0)
    banka_dekont_no: Mapped[str | None] = mapped_column(String(60), nullable=True, index=True)
    odeme_hesap_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    aciklama: Mapped[str | None] = mapped_column(String(500), nullable=True)
    transaction_id: Mapped[str | None] = mapped_column(String(60), nullable=True, index=True)
    kredi: Mapped["BankaKredisi"] = relationship("BankaKredisi", back_populates="taksitler")


class BankaKrediOdeme(Base):
    """Taksit / ara / erken kapama ödemesi — tek banka çıkışı + bağlı belgeler."""

    __tablename__ = "banka_kredi_odemeleri"
    __table_args__ = (
        UniqueConstraint("transaction_id", name="uq_bk_odeme_tx"),
        UniqueConstraint("odeme_belge_no", name="uq_bk_odeme_belge"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    transaction_id: Mapped[str] = mapped_column(String(60), nullable=False, index=True)
    kredi_id: Mapped[int] = mapped_column(ForeignKey("banka_kredileri.id"), nullable=False, index=True)
    taksit_id: Mapped[int | None] = mapped_column(
        ForeignKey("banka_kredi_taksitleri.id"), nullable=True, index=True
    )
    odeme_turu: Mapped[str] = mapped_column(String(30), nullable=False, default="TAKSIT")
    # TAKSIT | KISMI | ARA | ERKEN_KAPAMA | IPTAL
    odeme_tarihi: Mapped[date] = mapped_column(Date, nullable=False)
    odeme_belge_no: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    banka_hesap_id: Mapped[int] = mapped_column(ForeignKey("finans_hesaplari.id"), nullable=False)
    banka_dekont_no: Mapped[str | None] = mapped_column(String(60), nullable=True, index=True)
    anapara: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False, default=0)
    faiz: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False, default=0)
    bsmv: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False, default=0)
    kkdf: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False, default=0)
    komisyon: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False, default=0)
    sigorta: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False, default=0)
    dosya_masrafi: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False, default=0)
    diger_masraflar: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False, default=0)
    gecikme_faizi: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False, default=0)
    toplam: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False, default=0)
    para_birimi: Mapped[str] = mapped_column(String(10), nullable=False, default="TRY")
    kur: Mapped[Decimal | None] = mapped_column(Numeric(18, 6), nullable=True)
    kur_tarihi: Mapped[date | None] = mapped_column(Date, nullable=True)
    tl_karsiligi: Mapped[Decimal | None] = mapped_column(Numeric(18, 2), nullable=True)
    gider_belge_no: Mapped[str | None] = mapped_column(String(50), nullable=True, index=True)
    muhasebe_fis_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    banka_hareket_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    aciklama: Mapped[str | None] = mapped_column(String(500), nullable=True)
    durum: Mapped[str] = mapped_column(String(20), nullable=False, default="AKTIF")  # AKTIF|IPTAL
    iptal_nedeni: Mapped[str | None] = mapped_column(String(500), nullable=True)
    iptal_odeme_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_by: Mapped[str | None] = mapped_column(String(80), nullable=True)
    created_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True, default=datetime.now)


class BankaKrediIslemGunlugu(Base):
    """Kredi işlem audit kaydı."""

    __tablename__ = "banka_kredi_islem_gunlugu"
    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    kredi_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    taksit_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    odeme_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    transaction_id: Mapped[str | None] = mapped_column(String(60), nullable=True, index=True)
    islem: Mapped[str] = mapped_column(String(40), nullable=False)
    detay: Mapped[str | None] = mapped_column(Text, nullable=True)
    kullanici: Mapped[str | None] = mapped_column(String(80), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.now)


class BankaKrediPlanVersiyon(Base):
    """Ödeme planı sürümü — eski plan silinmez, pasife alınır."""

    __tablename__ = "banka_kredi_plan_versiyonlari"
    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    kredi_id: Mapped[int] = mapped_column(ForeignKey("banka_kredileri.id"), nullable=False, index=True)
    versiyon: Mapped[int] = mapped_column(Integer, nullable=False)
    plan_json: Mapped[str] = mapped_column(Text, nullable=False)
    aktif: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    aciklama: Mapped[str | None] = mapped_column(String(500), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.now)


class GiderFisi(Base):
    """Gider fişi — kasa/bankadan cari olmadan ödeme; hizmet kartı ile sınıflanır."""

    __tablename__ = "gider_fisleri"
    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    sube_id: Mapped[int | None] = mapped_column(ForeignKey("subeler.id"), nullable=True, index=True)
    belge_no: Mapped[str] = mapped_column(String(50), unique=True, nullable=False, index=True)
    tarih: Mapped[date] = mapped_column(Date, nullable=False)
    gider_turu: Mapped[str] = mapped_column(String(40), nullable=False)  # HIZMET | KREDI_*
    tutar: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    finans_hesap_id: Mapped[int | None] = mapped_column(
        ForeignKey("finans_hesaplari.id"), nullable=True, index=True
    )
    hizmet_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    bagli_belge_no: Mapped[str | None] = mapped_column(String(50), nullable=True, index=True)
    aciklama: Mapped[str | None] = mapped_column(String(500), nullable=True)
    durum: Mapped[str] = mapped_column(String(20), nullable=False, default="AÇIK")  # AÇIK|IPTAL
    finans_hesap = relationship("FinansHesabi")


class KasaMakbuzu(Base):
    """Tahsilat / ödeme makbuzu — cari zorunlu; tek veya çok satırlı tahsilat/ödeme."""

    __tablename__ = "kasa_makbuzlari"
    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    sube_id: Mapped[int | None] = mapped_column(ForeignKey("subeler.id"), nullable=True, index=True)
    belge_no: Mapped[str] = mapped_column(String(50), unique=True, nullable=False, index=True)
    tarih: Mapped[date] = mapped_column(Date, nullable=False)
    makbuz_turu: Mapped[str] = mapped_column(String(20), nullable=False)  # TAHSILAT | ODEME
    tutar: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    finans_hesap_id: Mapped[int] = mapped_column(
        ForeignKey("finans_hesaplari.id"), nullable=False, index=True
    )
    cari_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    makbuz_no: Mapped[str | None] = mapped_column(String(50), nullable=True)
    aciklama: Mapped[str | None] = mapped_column(String(500), nullable=True)
    durum: Mapped[str] = mapped_column(String(20), nullable=False, default="AÇIK")  # AÇIK|IPTAL
    finans_hesap = relationship("FinansHesabi")
    satirlar: Mapped[list["KasaMakbuzSatiri"]] = relationship(
        "KasaMakbuzSatiri",
        back_populates="makbuz",
        cascade="all, delete-orphan",
        order_by="KasaMakbuzSatiri.sira_no",
    )


class KasaMakbuzSatiri(Base):
    """Makbuz satırı — ödeme şekli + hesap + tutar (nakit, havale, POS vb.)."""

    __tablename__ = "kasa_makbuz_satirlari"
    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    makbuz_id: Mapped[int] = mapped_column(
        ForeignKey("kasa_makbuzlari.id"), nullable=False, index=True
    )
    sira_no: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    tarih: Mapped[date | None] = mapped_column(Date, nullable=True)
    odeme_sekli: Mapped[str] = mapped_column(String(50), nullable=False)
    finans_hesap_id: Mapped[int] = mapped_column(
        ForeignKey("finans_hesaplari.id"), nullable=False, index=True
    )
    tutar: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    aciklama: Mapped[str | None] = mapped_column(String(500), nullable=True)
    # Kart satırları: POS tahsilatı (kart_tipi + taksit) veya şirket kredi kartıyla ödeme
    kart_tipi: Mapped[str | None] = mapped_column(String(20), nullable=True)
    taksit_sayisi: Mapped[int | None] = mapped_column(Integer, nullable=True)
    kredi_karti_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    pos_valor_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    kk_odeme_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    makbuz: Mapped["KasaMakbuzu"] = relationship("KasaMakbuzu", back_populates="satirlar")
    finans_hesap = relationship("FinansHesabi")


# Aynı firmada (firma veritabanında) makbuz numarası tekrar edemez; boş numara serbest.
Index(
    "ux_kasa_makbuz_no",
    func.upper(func.trim(KasaMakbuzu.__table__.c.makbuz_no)),
    unique=True,
    sqlite_where=text("makbuz_no IS NOT NULL AND trim(makbuz_no) <> ''"),
)


class CariVirmanMakbuzu(Base):
    """Tahsilat makbuzu — Cari Virman: müşteriden alacak ve tedarikçiye borç aynı tutarda mahsup edilir.

    Kasa / banka / POS / kart hareketi yoktur. Bağlı iki cari hareket:
    tahsilat_belge_no (müşteri, alacak) ve odeme_belge_no (tedarikçi, alacak).
    Makbuz numarası kasa makbuzlarıyla ortak MKB serisindendir.
    """

    __tablename__ = "cari_virman_makbuzlari"
    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    sube_id: Mapped[int | None] = mapped_column(ForeignKey("subeler.id"), nullable=True, index=True)
    belge_no: Mapped[str] = mapped_column(String(50), unique=True, nullable=False, index=True)
    tahsilat_belge_no: Mapped[str] = mapped_column(String(50), unique=True, nullable=False)
    odeme_belge_no: Mapped[str] = mapped_column(String(50), unique=True, nullable=False)
    makbuz_no: Mapped[str | None] = mapped_column(String(50), nullable=True)
    tarih: Mapped[date] = mapped_column(Date, nullable=False)
    tutar: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    musteri_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    tedarikci_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    # FIFO ile kapatılan açık borç tutarları — düzenleme/iptalde tam bu kadar geri açılır
    musteri_kapanan: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False, default=0)
    tedarikci_kapanan: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False, default=0)
    aciklama: Mapped[str | None] = mapped_column(String(500), nullable=True)
    durum: Mapped[str] = mapped_column(String(20), nullable=False, default="AÇIK")  # AÇIK|IPTAL
    olusturma_tarihi: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.now)

    makbuz_turu = "TAHSILAT"
    virman = True


Index(
    "ux_cari_virman_makbuz_no",
    func.upper(func.trim(CariVirmanMakbuzu.__table__.c.makbuz_no)),
    unique=True,
    sqlite_where=text("makbuz_no IS NOT NULL AND trim(makbuz_no) <> ''"),
)


class SatisFaturaMakbuzBagi(Base):
    """Satış faturasından açılan tahsilat makbuzu ↔ fatura bağı (bir makbuz yalnız bir faturaya bağlanır).

    fatura_kapanan: makbuz tutarının bu faturanın açığına uygulanan kısmı; düzenleme/iptalde tam bu
    kadar faturaya geri açılır. Kalanı müşterinin diğer açık borçlarına (FIFO) uygulanmıştır.
    """

    __tablename__ = "satis_fatura_makbuz_baglari"
    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    makbuz_id: Mapped[int] = mapped_column(
        ForeignKey("kasa_makbuzlari.id"), unique=True, nullable=False, index=True
    )
    fatura_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    fatura_no: Mapped[str] = mapped_column(String(30), nullable=False)
    fatura_kapanan: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False, default=0)
    olusturma_tarihi: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.now)


class FinansEvrakKimligi(Base):
    """Kendi tablosu olmayan finans evraklarının kalıcı kimliği (muhasebeleştirme kaynağı).

    Cari tahsilat/ödeme, havale, kasa-banka virmanı ve cari virman hareket satırlarıyla tutulur;
    düzenlemede satırlar silinip aynı belge numarasıyla yeniden yazılır. Evrak türü + belge no
    benzersizdir; muhasebe fişi ve durum kaydı bu id'ye bağlanır (açıklama/tutar eşleştirmesi yok).
    ``cari_islem_id``: cari kartından yapılan tahsilat/ödemenin cari hareketi (kaynak kimliği).
    """

    __tablename__ = "finans_evrak_kimlikleri"
    __table_args__ = (UniqueConstraint("evrak_turu", "belge_no", name="uq_finans_evrak_kimligi"),)
    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    evrak_turu: Mapped[str] = mapped_column(String(40), nullable=False)
    belge_no: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    cari_islem_id: Mapped[int | None] = mapped_column(Integer, nullable=True, unique=True)
    kaynak: Mapped[str] = mapped_column(String(20), nullable=False, default="evrak")  # evrak|gecmis
    olusturma_tarihi: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.now)
