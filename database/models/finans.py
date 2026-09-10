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
    hesap_kesim_gunu: Mapped[int | None] = mapped_column(Integer, nullable=True)  # ayın 1-28
    son_odeme_gunu: Mapped[int | None] = mapped_column(Integer, nullable=True)  # ayın 1-28
    aciklama: Mapped[str | None] = mapped_column(String(500), nullable=True)
    aktif: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    banka_karti: Mapped["BankaKarti"] = relationship("BankaKarti", back_populates="kredi_kartlari")
    odemeler: Mapped[list["KrediKartiOdeme"]] = relationship(
        "KrediKartiOdeme",
        back_populates="kredi_karti",
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
    # KULLANDIRILDI | KAPALI | IPTAL
    durum: Mapped[str] = mapped_column(String(20), nullable=False, default="KULLANDIRILDI")
    banka_karti: Mapped["BankaKarti"] = relationship("BankaKarti", back_populates="banka_kredileri")
    taksitler: Mapped[list["BankaKrediTaksit"]] = relationship(
        "BankaKrediTaksit",
        back_populates="kredi",
        cascade="all, delete-orphan",
        order_by="BankaKrediTaksit.taksit_no",
    )


class BankaKrediTaksit(Base):
    """Kredi taksit satırı — anapara / faiz / masraf ayrı; faiz+masraf ödeme gününde gider fişi."""

    __tablename__ = "banka_kredi_taksitleri"
    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    kredi_id: Mapped[int] = mapped_column(ForeignKey("banka_kredileri.id"), nullable=False, index=True)
    taksit_no: Mapped[int] = mapped_column(Integer, nullable=False)
    vade_tarihi: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    anapara: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False, default=0)
    faiz: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False, default=0)
    masraf: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False, default=0)
    durum: Mapped[str] = mapped_column(String(20), nullable=False, default="BEKLIYOR")  # BEKLIYOR|ODENDI
    odeme_tarihi: Mapped[date | None] = mapped_column(Date, nullable=True)
    odeme_belge_no: Mapped[str | None] = mapped_column(String(50), nullable=True, index=True)
    gider_belge_no: Mapped[str | None] = mapped_column(String(50), nullable=True, index=True)
    kredi: Mapped["BankaKredisi"] = relationship("BankaKredisi", back_populates="taksitler")


class GiderFisi(Base):
    """Gider fişi — kasa/bankadan cari olmadan ödeme; hizmet kartı ile sınıflanır."""

    __tablename__ = "gider_fisleri"
    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    belge_no: Mapped[str] = mapped_column(String(50), unique=True, nullable=False, index=True)
    tarih: Mapped[date] = mapped_column(Date, nullable=False)
    gider_turu: Mapped[str] = mapped_column(String(40), nullable=False)  # HIZMET | KREDI_FAIZ | KREDI_MASRAF
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
    """Kasa tahsilat / ödeme makbuzu — cari zorunlu, kasa hesabından giriş veya çıkış."""

    __tablename__ = "kasa_makbuzlari"
    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
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
