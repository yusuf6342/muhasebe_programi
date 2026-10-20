from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    LargeBinary,
    Numeric,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from database.database import Base

class Cari(Base):
    __tablename__ = "cari_kartlar"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    cari_kodu: Mapped[str] = mapped_column(String(20), unique=True, nullable=False)
    unvan: Mapped[str] = mapped_column(String(200), nullable=False)
    cari_turu: Mapped[str] = mapped_column(String(20), nullable=False)
    vergi_dairesi: Mapped[str | None] = mapped_column(String(100), nullable=True)
    vergi_numarasi: Mapped[str | None] = mapped_column(String(20), nullable=True)
    tc_kimlik: Mapped[str | None] = mapped_column(String(11), nullable=True)
    telefon: Mapped[str | None] = mapped_column(String(30), nullable=True)
    telefon2: Mapped[str | None] = mapped_column(String(30), nullable=True)
    telefon3: Mapped[str | None] = mapped_column(String(30), nullable=True)
    email: Mapped[str | None] = mapped_column(String(150), nullable=True)
    musteri_grubu: Mapped[str | None] = mapped_column(String(100), nullable=True)
    satis_fiyat_listesi: Mapped[str | None] = mapped_column(String(100), nullable=True)
    alis_fiyat_listesi: Mapped[str | None] = mapped_column(String(100), nullable=True)
    acik_hesap_risk_limiti: Mapped[Decimal | None] = mapped_column(Numeric(18, 2), nullable=True)
    cek_risk_limiti: Mapped[Decimal | None] = mapped_column(Numeric(18, 2), nullable=True)
    senet_risk_limiti: Mapped[Decimal | None] = mapped_column(Numeric(18, 2), nullable=True)
    toplam_risk_limiti: Mapped[Decimal | None] = mapped_column(Numeric(18, 2), nullable=True)
    # Limit denetimi yalnız işaretliyse yapılır; işaretli ve 0 TL geçerli limittir.
    acik_hesap_limit_uygula: Mapped[bool] = mapped_column(Boolean, default=False, server_default="0", nullable=False)
    cek_limit_uygula: Mapped[bool] = mapped_column(Boolean, default=False, server_default="0", nullable=False)
    senet_limit_uygula: Mapped[bool] = mapped_column(Boolean, default=False, server_default="0", nullable=False)
    toplam_limit_uygula: Mapped[bool] = mapped_column(Boolean, default=False, server_default="0", nullable=False)
    vade_farki_aylik_oran: Mapped[Decimal | None] = mapped_column(Numeric(9, 4), nullable=True)
    vade_farki_yillik_oran: Mapped[Decimal | None] = mapped_column(Numeric(9, 4), nullable=True)
    vade_farki_donem: Mapped[str | None] = mapped_column(String(10), nullable=True)
    vade_farki_aciklama: Mapped[str | None] = mapped_column(String(200), nullable=True)
    # Genel Risk yüzdeleri (0–100); muhasebe bakiyesini değiştirmez.
    risk_orani_ciro_cek: Mapped[Decimal] = mapped_column(
        Numeric(5, 2), default=Decimal("100"), server_default="100", nullable=False
    )
    risk_orani_diger_cek: Mapped[Decimal] = mapped_column(
        Numeric(5, 2), default=Decimal("100"), server_default="100", nullable=False
    )
    risk_orani_senet: Mapped[Decimal] = mapped_column(
        Numeric(5, 2), default=Decimal("100"), server_default="100", nullable=False
    )
    satis_vade_gunu: Mapped[int | None] = mapped_column(Integer, nullable=True)
    alis_vade_gunu: Mapped[int | None] = mapped_column(Integer, nullable=True)
    muhasebe_borclu_kodu: Mapped[str | None] = mapped_column(String(50), nullable=True)
    muhasebe_alacakli_kodu: Mapped[str | None] = mapped_column(String(50), nullable=True)
    muhasebe_satis_kodu: Mapped[str | None] = mapped_column(String(50), nullable=True)
    muhasebe_alis_kodu: Mapped[str | None] = mapped_column(String(50), nullable=True)
    muhasebe_kdv_satis_kodu: Mapped[str | None] = mapped_column(String(50), nullable=True)
    muhasebe_kdv_alis_kodu: Mapped[str | None] = mapped_column(String(50), nullable=True)
    adres: Mapped[str | None] = mapped_column(String(500), nullable=True)
    il: Mapped[str | None] = mapped_column(String(50), nullable=True)
    ilce: Mapped[str | None] = mapped_column(String(50), nullable=True)
    adres_tipi: Mapped[str | None] = mapped_column(String(40), nullable=True)
    adres2: Mapped[str | None] = mapped_column(String(500), nullable=True)
    il2: Mapped[str | None] = mapped_column(String(50), nullable=True)
    ilce2: Mapped[str | None] = mapped_column(String(50), nullable=True)
    adres_tipi2: Mapped[str | None] = mapped_column(String(40), nullable=True)
    adres3: Mapped[str | None] = mapped_column(String(500), nullable=True)
    il3: Mapped[str | None] = mapped_column(String(50), nullable=True)
    ilce3: Mapped[str | None] = mapped_column(String(50), nullable=True)
    adres_tipi3: Mapped[str | None] = mapped_column(String(40), nullable=True)
    ozel_notlar: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    uyari_notu: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    aktif: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    is_deleted: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    deleted_by_user_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    deletion_log_id: Mapped[int | None] = mapped_column(Integer, nullable=True)

    satis_hareketleri: Mapped[list["SatisHareketi"]] = relationship(
        "SatisHareketi",
        back_populates="cari",
        cascade="all, delete-orphan",
    )
    yetkililer: Mapped[list["CariYetkili"]] = relationship(
        "CariYetkili",
        back_populates="cari",
        cascade="all, delete-orphan",
    )


class CariYetkili(Base):
    """Cari karta bağlı işletme yetkilisi (çoklu kayıt)."""

    __tablename__ = "cari_yetkililer"
    __table_args__ = (
        Index("ix_cari_yetkili_cari_aktif", "cari_id", "aktif"),
        Index("ix_cari_yetkili_dogum", "dogum_tarihi"),
        Index("ix_cari_yetkili_ad_norm", "ad_soyad_norm"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    cari_id: Mapped[int] = mapped_column(ForeignKey("cari_kartlar.id"), nullable=False, index=True)

    ad: Mapped[str] = mapped_column(String(80), nullable=False)
    soyad: Mapped[str] = mapped_column(String(80), nullable=False)
    ad_soyad_norm: Mapped[str | None] = mapped_column(String(200), nullable=True)
    unvan: Mapped[str | None] = mapped_column(String(100), nullable=True)
    departman: Mapped[str | None] = mapped_column(String(100), nullable=True)
    gorev: Mapped[str | None] = mapped_column(String(100), nullable=True)
    ana_yetkili: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    aktif: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    cep_telefonu: Mapped[str | None] = mapped_column(String(30), nullable=True)
    telefon2: Mapped[str | None] = mapped_column(String(30), nullable=True)
    whatsapp_telefonu: Mapped[str | None] = mapped_column(String(30), nullable=True)
    is_telefonu: Mapped[str | None] = mapped_column(String(30), nullable=True)
    dahili: Mapped[str | None] = mapped_column(String(20), nullable=True)
    email: Mapped[str | None] = mapped_column(String(150), nullable=True)

    dogum_tarihi: Mapped[date | None] = mapped_column(Date, nullable=True)
    # Yıl bilinmiyorsa yalnız gün/ay saklanır; dogum_tarihi yalnız yıl biliniyorsa dolar.
    dogum_gun: Mapped[int | None] = mapped_column(Integer, nullable=True)
    dogum_ay: Mapped[int | None] = mapped_column(Integer, nullable=True)
    dogum_yili: Mapped[int | None] = mapped_column(Integer, nullable=True)
    departman_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    gorev_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    dogum_gunu_hatirlat: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    hitap: Mapped[str | None] = mapped_column(String(40), nullable=True)
    iletisim_kanali: Mapped[str | None] = mapped_column(String(40), nullable=True)

    adres: Mapped[str | None] = mapped_column(String(500), nullable=True)
    il: Mapped[str | None] = mapped_column(String(50), nullable=True)
    ilce: Mapped[str | None] = mapped_column(String(50), nullable=True)
    ozel_notlar: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    gorusme_notu: Mapped[str | None] = mapped_column(String(1000), nullable=True)

    pazarlama_izni: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    kvkk_onayi: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    onay_tarihi: Mapped[date | None] = mapped_column(Date, nullable=True)

    is_deleted: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    updated_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_by_user_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_by_username: Mapped[str | None] = mapped_column(String(80), nullable=True)
    updated_by_user_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    updated_by_username: Mapped[str | None] = mapped_column(String(80), nullable=True)

    cari: Mapped["Cari"] = relationship("Cari", back_populates="yetkililer")


class CariYetkiliDepartman(Base):
    """Yetkili departman tanımı (firma veritabanı kapsamında)."""

    __tablename__ = "cari_yetkili_departmanlari"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    ad: Mapped[str] = mapped_column(String(100), nullable=False)
    ad_norm: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)
    aktif: Mapped[bool] = mapped_column(Boolean, default=True, server_default="1", nullable=False)


class CariYetkiliGorev(Base):
    """Yetkili görev tanımı; ``departman_id`` doluysa yalnız o departmanda önerilir."""

    __tablename__ = "cari_yetkili_gorevleri"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    ad: Mapped[str] = mapped_column(String(100), nullable=False)
    ad_norm: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)
    departman_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    aktif: Mapped[bool] = mapped_column(Boolean, default=True, server_default="1", nullable=False)


class CariFotograf(Base):
    """Cari veya yetkili fotoğrafı: küçültülmüş görüntü + küçük önizleme (firma veritabanında)."""

    __tablename__ = "cari_fotograflari"
    __table_args__ = (UniqueConstraint("sahip_turu", "sahip_id", name="uq_cari_foto_sahip"),)

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    sahip_turu: Mapped[str] = mapped_column(String(10), nullable=False)
    sahip_id: Mapped[int] = mapped_column(Integer, nullable=False)
    cari_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    bicim: Mapped[str] = mapped_column(String(10), nullable=False)
    genislik: Mapped[int] = mapped_column(Integer, nullable=False)
    yukseklik: Mapped[int] = mapped_column(Integer, nullable=False)
    veri: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    kucuk: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    kaynak_adi: Mapped[str | None] = mapped_column(String(200), nullable=True)
    guncelleme: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class MusteriGrubuAyari(Base):
    """Sistem rolündeki grup (ör. aday / perakende müşteri) → grup adı; satır yoksa varsayılan ad."""

    __tablename__ = "musteri_grubu_ayarlari"

    anahtar: Mapped[str] = mapped_column(String(60), primary_key=True)
    deger: Mapped[str] = mapped_column(String(100), nullable=False)


class MusteriGrubu(Base):
    __tablename__ = "musteri_gruplari"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    ad: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)


class SatisHareketi(Base):
    __tablename__ = "cari_satis_hareketleri"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    cari_id: Mapped[int] = mapped_column(ForeignKey("cari_kartlar.id"), nullable=False, index=True)
    satis_tarihi: Mapped[date] = mapped_column(Date, nullable=False)
    belge_no: Mapped[str] = mapped_column(String(50), nullable=False)
    satis_tutari: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    kalan_acik_tutar: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    para_birimi: Mapped[str] = mapped_column(String(3), nullable=False, default="TRY")
    doviz_tutari: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False, default=0)
    kur: Mapped[Decimal] = mapped_column(Numeric(18, 6), nullable=False, default=1)
    borc_esasi: Mapped[str] = mapped_column(String(20), nullable=False, default="TL_SABIT")

    cari: Mapped["Cari"] = relationship("Cari", back_populates="satis_hareketleri")


class CariIslem(Base):
    """Tahsilat, ödeme, virman ve KK çekimi kayıtları."""

    __tablename__ = "cari_islemleri"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    cari_id: Mapped[int] = mapped_column(ForeignKey("cari_kartlar.id"), nullable=False, index=True)
    tarih: Mapped[date] = mapped_column(Date, nullable=False)
    islem_turu: Mapped[str] = mapped_column(String(40), nullable=False)
    belge_no: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    aciklama: Mapped[str | None] = mapped_column(String(500), nullable=True)
    borc: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False, default=0)
    alacak: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False, default=0)
    hesap_adi: Mapped[str | None] = mapped_column(String(100), nullable=True)
    karsi_cari_id: Mapped[int | None] = mapped_column(ForeignKey("cari_kartlar.id"), nullable=True)
    para_birimi: Mapped[str] = mapped_column(String(3), nullable=False, default="TRY")
    doviz_borc: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False, default=0)
    doviz_alacak: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False, default=0)
    kur: Mapped[Decimal] = mapped_column(Numeric(18, 6), nullable=False, default=1)
    borc_esasi: Mapped[str] = mapped_column(String(20), nullable=False, default="TL_SABIT")

    cari: Mapped["Cari"] = relationship("Cari", foreign_keys=[cari_id])


class CariUsdKarsilik(Base):
    """TL cari hareketin işlem tarihindeki USD karşılığı (yalnız raporlama).

    TL borç/alacak, evrak ve kapatma bu kayıttan etkilenmez. Kur yoksa durum EKSIK
    olur; asla bugünün kuru veya 1 varsayılmaz.
    """

    __tablename__ = "cari_usd_karsiliklari"
    __table_args__ = (
        UniqueConstraint("kaynak", "kaynak_id", name="uq_cari_usd_kaynak"),
        Index("ix_cari_usd_cari_tarih", "cari_id", "islem_tarihi"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    kaynak: Mapped[str] = mapped_column(String(20), nullable=False)
    kaynak_id: Mapped[int] = mapped_column(Integer, nullable=False)
    cari_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    belge_no: Mapped[str | None] = mapped_column(String(50), nullable=True)
    islem_tarihi: Mapped[date] = mapped_column(Date, nullable=False)
    tl_borc: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False, default=0)
    tl_alacak: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False, default=0)
    usd_kur: Mapped[Decimal | None] = mapped_column(Numeric(18, 6), nullable=True)
    kur_tarihi: Mapped[date | None] = mapped_column(Date, nullable=True)
    kur_turu: Mapped[str] = mapped_column(String(20), nullable=False, default="forex_selling")
    kur_kaynagi: Mapped[str | None] = mapped_column(String(20), nullable=True)
    usd_borc: Mapped[Decimal | None] = mapped_column(Numeric(18, 2), nullable=True)
    usd_alacak: Mapped[Decimal | None] = mapped_column(Numeric(18, 2), nullable=True)
    durum: Mapped[str] = mapped_column(String(10), nullable=False, default="EKSIK")
    guncelleme: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.now)


class CariKapatma(Base):
    """Açık kalem tahsisi: bir kaynak evrakın (tahsilat/ödeme/iade/avans) hedef açık kalemi kapatması.

    Hedef/kaynak kalem kimlikleri bilinçli olarak FK değildir: eski akışlar açık kalem satırını
    silebilir; tahsis kaydı denetim izi olarak kalır (iptal edilir, silinmez).
    """

    __tablename__ = "cari_kapatmalar"
    __table_args__ = (
        Index("ix_cari_kapatma_kaynak", "kaynak_belge_no", "iptal"),
        Index("ix_cari_kapatma_hedef", "hedef_hareket_id", "iptal"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    islem_kimligi: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    cari_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    kaynak_belge_no: Mapped[str] = mapped_column(String(50), nullable=False)
    kaynak_tur: Mapped[str] = mapped_column(String(30), nullable=False)
    kaynak_hareket_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    hedef_hareket_id: Mapped[int] = mapped_column(Integer, nullable=False)
    hedef_belge_no: Mapped[str] = mapped_column(String(50), nullable=False)
    tutar: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    para_birimi: Mapped[str] = mapped_column(String(3), nullable=False, default="TRY")
    tarih: Mapped[date] = mapped_column(Date, nullable=False)
    yontem: Mapped[str] = mapped_column(String(10), nullable=False, default="FIFO")
    kullanici_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    kullanici_adi: Mapped[str | None] = mapped_column(String(120), nullable=True)
    olusturma: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.now)
    iptal: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    iptal_zamani: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    iptal_kullanici: Mapped[str | None] = mapped_column(String(120), nullable=True)
    iptal_nedeni: Mapped[str | None] = mapped_column(String(300), nullable=True)
    iptal_islem_kimligi: Mapped[str | None] = mapped_column(String(36), nullable=True)


# Cari hareket kaydedilirken USD karşılığını yazan oturum dinleyicisi
from database import cari_usd_karsilik_service as _cari_usd_karsilik_service  # noqa: E402,F401
from database.models import cari_risk as _cari_risk  # noqa: E402,F401
