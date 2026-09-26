from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import Boolean, Date, DateTime, ForeignKey, Integer, Numeric, String, Text, UniqueConstraint
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
    son_odeme_tarihi: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    # KESILMEMIS | KESILMIS | KISMI | ODENDI | GECIKMIS | FAZLA
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
    ekstre: Mapped["KrediKartiEkstre"] = relationship(
        "KrediKartiEkstre", back_populates="odemeler"
    )


class KrediKartiOdeme(Base):
    """Kredi kartı ile yapılan cari ödeme evrakı (tek çekim veya taksitli)."""

    __tablename__ = "kredi_karti_odemeleri"
    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    belge_no: Mapped[str] = mapped_column(String(50), unique=True, nullable=False, index=True)
    tarih: Mapped[date] = mapped_column(Date, nullable=False)
    vade_tarihi: Mapped[date] = mapped_column(Date, nullable=False)  # tek çekim = tarih; taksit = 1. taksit
    banka_karti_id: Mapped[int] = mapped_column(ForeignKey("banka_kartlari.id"), nullable=False, index=True)
    kredi_karti_id: Mapped[int] = mapped_column(ForeignKey("kredi_karti_tanimlari.id"), nullable=False, index=True)
    cari_id: Mapped[int] = mapped_column(nullable=False, index=True)
    cekim_turu: Mapped[str] = mapped_column(String(20), nullable=False)  # TEK_CEKIM | TAKSITLI
    taksit_sayisi: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    tutar: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    referans_no: Mapped[str | None] = mapped_column(String(50), nullable=True)  # POS/onay no
    aciklama: Mapped[str | None] = mapped_column(String(500), nullable=True)
    durum: Mapped[str] = mapped_column(String(20), nullable=False, default="AÇIK")  # AÇIK|İPTAL
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
    durum: Mapped[str] = mapped_column(String(20), nullable=False, default="BEKLIYOR")  # BEKLIYOR|ODENDI
    odeme: Mapped["KrediKartiOdeme"] = relationship("KrediKartiOdeme", back_populates="taksitler")


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
    makbuz: Mapped["KasaMakbuzu"] = relationship("KasaMakbuzu", back_populates="satirlar")
    finans_hesap = relationship("FinansHesabi")
