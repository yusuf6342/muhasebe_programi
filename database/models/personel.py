"""Personel / özlük / SGK takip modelleri.

Resmî portal gönderimi yok; beyan ve bildirim kayıtları hazırlık + kanıt takibidir.
Hassas (sağlık / adli sicil) belgeler ayrı gizlilik sınıfındadır.
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
    LargeBinary,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from database.database import Base

# --- Durum / sınıf sabitleri -------------------------------------------------

DURUM_AKTIF = "AKTIF"
DURUM_ISE_BASLAYACAK = "ISE_BASLAYACAK"
DURUM_AYRILDI = "AYRILDI"
DURUM_PASIF = "PASIF"
CALISMA_DURUMLARI = (
    (DURUM_AKTIF, "Aktif"),
    (DURUM_ISE_BASLAYACAK, "İşe başlayacak"),
    (DURUM_AYRILDI, "Ayrıldı"),
    (DURUM_PASIF, "Pasif"),
)

KIMLIK_TCKN = "TCKN"
KIMLIK_YABANCI = "YABANCI_KIMLIK"
KIMLIK_DIGER = "DIGER"
KIMLIK_TURLERI = (
    (KIMLIK_TCKN, "T.C. kimlik no"),
    (KIMLIK_YABANCI, "Yabancı kimlik no"),
    (KIMLIK_DIGER, "Diğer kimlik"),
)

UCRET_NET = "NET"
UCRET_BRUT = "BRUT"
UCRET_TURLERI = ((UCRET_NET, "Net"), (UCRET_BRUT, "Brüt"))

BELGE_SINIF_ZORUNLU = "ZORUNLU"
BELGE_SINIF_KOSULLU = "KOSULLU"
BELGE_SINIF_ISTEGE = "ISTEGE_BAGLI"
BELGE_SINIFLARI = (
    (BELGE_SINIF_ZORUNLU, "Zorunlu"),
    (BELGE_SINIF_KOSULLU, "Koşullu"),
    (BELGE_SINIF_ISTEGE, "İsteğe bağlı"),
)

GIZLILIK_NORMAL = "NORMAL"
GIZLILIK_HASSAS_SAGLIK = "HASSAS_SAGLIK"
GIZLILIK_HASSAS_ADLI = "HASSAS_ADLI"
GIZLILIK_SINIFLARI = (
    (GIZLILIK_NORMAL, "Normal"),
    (GIZLILIK_HASSAS_SAGLIK, "Hassas — sağlık"),
    (GIZLILIK_HASSAS_ADLI, "Hassas — adli sicil"),
)

BELGE_DURUM_EKSIK = "EKSIK"
BELGE_DURUM_YUKLENDI = "YUKLENDI"
BELGE_DURUM_INCELENDI = "INCELENDI"
BELGE_DURUM_YENILEME = "YENILEME_YAKLASIYOR"
BELGE_DURUM_SURESI_DOLDU = "SURESI_DOLDU"
BELGE_DURUM_UYGULANMIYOR = "UYGULANMIYOR"
BELGE_DURUMLARI = (
    (BELGE_DURUM_EKSIK, "Eksik"),
    (BELGE_DURUM_YUKLENDI, "Yüklendi"),
    (BELGE_DURUM_INCELENDI, "İncelendi"),
    (BELGE_DURUM_YENILEME, "Yenileme yaklaşıyor"),
    (BELGE_DURUM_SURESI_DOLDU, "Süresi doldu"),
    (BELGE_DURUM_UYGULANMIYOR, "Uygulanmıyor"),
)

HAKEDIS_TASLAK = "TASLAK"
HAKEDIS_ONAYLI = "ONAYLI"
HAKEDIS_IPTAL = "IPTAL"
HAKEDIS_DURUMLARI = (
    (HAKEDIS_TASLAK, "Taslak"),
    (HAKEDIS_ONAYLI, "Onaylı"),
    (HAKEDIS_IPTAL, "İptal"),
)

HAREKET_AVANS = "AVANS"
HAREKET_MAAS_ODEME = "MAAS_ODEME"
HAREKET_MAHSUP = "AVANS_MAHSUP"
HAREKET_MASRAF = "MASRAF"
HAREKET_MASRAF_IADE = "MASRAF_IADE"
HAREKET_IPTAL = "IPTAL"
HAREKET_TURLERI = (
    (HAREKET_AVANS, "Avans"),
    (HAREKET_MAAS_ODEME, "Maaş ödemesi"),
    (HAREKET_MAHSUP, "Avans mahsubu"),
    (HAREKET_MASRAF, "Masraf (personel ödedi)"),
    (HAREKET_MASRAF_IADE, "Masraf geri ödeme"),
    (HAREKET_IPTAL, "İptal"),
)

IZIN_YILLIK = "YILLIK"
IZIN_UCRETLI = "UCRETLI"
IZIN_UCRETSIZ = "UCRETSIZ"
IZIN_ISTIRAHAT = "ISTIRAHAT"
IZIN_DIGER = "DIGER"
IZIN_TURLERI = (
    (IZIN_YILLIK, "Yıllık izin"),
    (IZIN_UCRETLI, "Ücretli izin"),
    (IZIN_UCRETSIZ, "Ücretsiz izin"),
    (IZIN_ISTIRAHAT, "İstirahat"),
    (IZIN_DIGER, "Diğer"),
)

IZIN_TALEP = "TALEP"
IZIN_ONAYLI = "ONAYLI"
IZIN_KULLANIM = "KULLANIM"
IZIN_IPTAL = "IPTAL"
IZIN_DURUMLARI = (
    (IZIN_TALEP, "Talep"),
    (IZIN_ONAYLI, "Onaylı"),
    (IZIN_KULLANIM, "Kullanım"),
    (IZIN_IPTAL, "İptal"),
)

PUANTAJ_CALISMA = "CALISMA"
PUANTAJ_DEVAMSIZ = "DEVAMSIZLIK"
PUANTAJ_FAZLA = "FAZLA_MESAI"
PUANTAJ_IZIN = "IZIN"
PUANTAJ_ISTIRAHAT = "ISTIRAHAT"
PUANTAJ_DIGER = "DIGER"
PUANTAJ_TURLERI = (
    (PUANTAJ_CALISMA, "Çalışma"),
    (PUANTAJ_DEVAMSIZ, "Devamsızlık"),
    (PUANTAJ_FAZLA, "Fazla mesai"),
    (PUANTAJ_IZIN, "İzin"),
    (PUANTAJ_ISTIRAHAT, "İstirahat"),
    (PUANTAJ_DIGER, "Diğer"),
)

SGK_HAZIRLANACAK = "HAZIRLANACAK"
SGK_HAZIRLANDI = "HAZIRLANDI"
SGK_KONTROL = "KONTROL_BEKLIYOR"
SGK_RESMI_ONAY = "RESMI_ONAY_BELGESI_KAYDEDILDI"
SGK_DUZELTME = "DUZELTME_GEREKLI"
SGK_IPTAL = "IPTAL"
SGK_DURUMLARI = (
    (SGK_HAZIRLANACAK, "Hazırlanacak"),
    (SGK_HAZIRLANDI, "Hazırlandı"),
    (SGK_KONTROL, "Kontrol bekliyor"),
    (SGK_RESMI_ONAY, "Resmî onay belgesi kaydedildi"),
    (SGK_DUZELTME, "Düzeltme gerekli"),
    (SGK_IPTAL, "İptal"),
)

SGK_ISLEM_GIRIS = "ISE_GIRIS"
SGK_ISLEM_CIKIS = "ISTEN_AYRILIS"
SGK_ISLEM_MPHB = "MPHB"
SGK_ISLEM_PRIM = "PRIM_VERGI_ODEME"
SGK_ISLEM_ISTIRAHAT = "ISTIRAHAT"
SGK_ISLEM_DIGER = "DIGER"
SGK_ISLEM_TURLERI = (
    (SGK_ISLEM_GIRIS, "İşe giriş bildirimi"),
    (SGK_ISLEM_CIKIS, "İşten ayrılış bildirimi"),
    (SGK_ISLEM_MPHB, "Muhtasar ve Prim Hizmet Beyannamesi"),
    (SGK_ISLEM_PRIM, "Prim / vergi ödeme takibi"),
    (SGK_ISLEM_ISTIRAHAT, "İstirahat / diğer bildirim"),
    (SGK_ISLEM_DIGER, "Diğer"),
)

# Belge kategori kodları (tohum)
KAT_KIMLIK = "KIMLIK_CALISMA"
KAT_SGK = "SGK_BEYAN"
KAT_UCRET = "UCRET_ODEME"
KAT_IZIN = "IZIN_PUANTAJ"
KAT_SAGLIK = "SAGLIK_ISG"
KAT_ADLI = "ADLI_SICIL"
KAT_GOREV = "GOREV_BAGLI"
KAT_ISYERI = "ISYERI_BELGE"
KAT_AYRILIS = "AYRILIS"
BELGE_KATEGORILERI = (
    (KAT_KIMLIK, "Kimlik ve çalışma ilişkisi"),
    (KAT_SGK, "SGK ve beyan"),
    (KAT_UCRET, "Ücret ve ödeme"),
    (KAT_IZIN, "İzin ve puantaj"),
    (KAT_SAGLIK, "Sağlık ve İSG"),
    (KAT_ADLI, "Adli sicil kaydı"),
    (KAT_GOREV, "Göreve bağlı belgeler"),
    (KAT_ISYERI, "İşyeri belgeleri"),
    (KAT_AYRILIS, "Ayrılış ve diğer evraklar"),
)


class Personel(Base):
    """Firma içi personel kartı (kimlik geçmişi korunur; fiziksel silme yok)."""

    __tablename__ = "personel_kartlari"
    __table_args__ = (
        UniqueConstraint("kod", name="uq_personel_kod"),
        Index("ix_personel_ad_soyad", "ad", "soyad"),
        Index("ix_personel_durum", "calisma_durumu"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    kod: Mapped[str] = mapped_column(String(30), nullable=False)
    ad: Mapped[str] = mapped_column(String(80), nullable=False)
    soyad: Mapped[str] = mapped_column(String(80), nullable=False)
    kimlik_turu: Mapped[str] = mapped_column(String(20), nullable=False, default=KIMLIK_TCKN)
    kimlik_no: Mapped[str | None] = mapped_column(String(30), nullable=True)
    dogum_tarihi: Mapped[date | None] = mapped_column(Date, nullable=True)
    telefon: Mapped[str | None] = mapped_column(String(40), nullable=True)
    eposta: Mapped[str | None] = mapped_column(String(120), nullable=True)
    adres: Mapped[str | None] = mapped_column(String(500), nullable=True)
    il: Mapped[str | None] = mapped_column(String(50), nullable=True)
    ilce: Mapped[str | None] = mapped_column(String(50), nullable=True)
    calisma_durumu: Mapped[str] = mapped_column(String(20), nullable=False, default=DURUM_AKTIF)
    notlar: Mapped[str | None] = mapped_column(Text, nullable=True)
    olusturan: Mapped[str | None] = mapped_column(String(120), nullable=True)
    olusturma: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.now)
    guncelleyen: Mapped[str | None] = mapped_column(String(120), nullable=True)
    guncelleme: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    donemler: Mapped[list["PersonelCalismaDonemi"]] = relationship(
        back_populates="personel", cascade="all, delete-orphan",
        order_by="PersonelCalismaDonemi.giris_tarihi.desc()",
    )
    foto: Mapped["PersonelFotograf | None"] = relationship(
        back_populates="personel", uselist=False, cascade="all, delete-orphan",
    )


class PersonelGorevTanim(Base):
    """İş unvanı / görev tanımı — kullanıcı yetki rolünden bağımsızdır."""

    __tablename__ = "personel_gorev_tanimlari"
    __table_args__ = (UniqueConstraint("kod", name="uq_personel_gorev_kod"),)

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    kod: Mapped[str] = mapped_column(String(40), nullable=False)
    ad: Mapped[str] = mapped_column(String(120), nullable=False)
    aktif: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    sira: Mapped[int] = mapped_column(Integer, nullable=False, default=100)
    aciklama: Mapped[str | None] = mapped_column(String(300), nullable=True)


class PersonelCalismaDonemi(Base):
    """Aynı kişi ayrılıp yeniden başlarsa yeni dönem; eski ücret/bildirge taşınmaz."""

    __tablename__ = "personel_calisma_donemleri"
    __table_args__ = (Index("ix_personel_donem_personel", "personel_id"),)

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    personel_id: Mapped[int] = mapped_column(ForeignKey("personel_kartlari.id"), nullable=False)
    giris_tarihi: Mapped[date] = mapped_column(Date, nullable=False)
    cikis_tarihi: Mapped[date | None] = mapped_column(Date, nullable=True)
    gorev: Mapped[str | None] = mapped_column(String(120), nullable=True)
    gorev_id: Mapped[int | None] = mapped_column(
        ForeignKey("personel_gorev_tanimlari.id"), nullable=True
    )
    bolum: Mapped[str | None] = mapped_column(String(120), nullable=True)
    sube: Mapped[str | None] = mapped_column(String(120), nullable=True)
    sube_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    isyeri_kodu: Mapped[str | None] = mapped_column(String(60), nullable=True)
    isyeri_sicil: Mapped[str | None] = mapped_column(String(60), nullable=True)
    sozlesme_turu: Mapped[str | None] = mapped_column(String(60), nullable=True)
    calisma_duzeni: Mapped[str | None] = mapped_column(String(60), nullable=True)
    sgk_kapsam: Mapped[str | None] = mapped_column(String(40), nullable=True, default="4/a")
    meslek_kodu: Mapped[str | None] = mapped_column(String(20), nullable=True)
    aktif: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    aciklama: Mapped[str | None] = mapped_column(String(500), nullable=True)

    personel: Mapped["Personel"] = relationship(back_populates="donemler")
    ucretler: Mapped[list["PersonelUcret"]] = relationship(
        back_populates="donem", cascade="all, delete-orphan",
        order_by="PersonelUcret.gecerli_baslangic.desc()",
    )


class PersonelUcret(Base):
    """Ücret geçmişi — zam yeni dönemlere uygulanır, geçmiş hakediş yeniden yazılmaz."""

    __tablename__ = "personel_ucretleri"
    __table_args__ = (Index("ix_personel_ucret_donem", "donem_id"),)

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    donem_id: Mapped[int] = mapped_column(ForeignKey("personel_calisma_donemleri.id"), nullable=False)
    ucret_turu: Mapped[str] = mapped_column(String(10), nullable=False, default=UCRET_NET)
    tutar: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    gecerli_baslangic: Mapped[date] = mapped_column(Date, nullable=False)
    odeme_gunu: Mapped[int | None] = mapped_column(Integer, nullable=True)
    iban: Mapped[str | None] = mapped_column(String(34), nullable=True)
    banka_adi: Mapped[str | None] = mapped_column(String(100), nullable=True)
    aciklama: Mapped[str | None] = mapped_column(String(300), nullable=True)
    olusturan: Mapped[str | None] = mapped_column(String(120), nullable=True)
    olusturma: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.now)

    donem: Mapped["PersonelCalismaDonemi"] = relationship(back_populates="ucretler")


class PersonelFotograf(Base):
    """Kart fotoğrafı — firma DB içinde; yüze tanıma / kimlik doğrulama için kullanılmaz."""

    __tablename__ = "personel_fotograflari"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    personel_id: Mapped[int] = mapped_column(
        ForeignKey("personel_kartlari.id"), nullable=False, unique=True
    )
    bicim: Mapped[str] = mapped_column(String(10), nullable=False)
    genislik: Mapped[int] = mapped_column(Integer, nullable=False)
    yukseklik: Mapped[int] = mapped_column(Integer, nullable=False)
    veri: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    kucuk: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    kaynak_adi: Mapped[str | None] = mapped_column(String(200), nullable=True)
    guncelleme: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.now)

    personel: Mapped["Personel"] = relationship(back_populates="foto")


class PersonelBelgeKategori(Base):
    __tablename__ = "personel_belge_kategorileri"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    kod: Mapped[str] = mapped_column(String(40), nullable=False, unique=True)
    ad: Mapped[str] = mapped_column(String(120), nullable=False)
    sira: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    gizlilik: Mapped[str] = mapped_column(String(20), nullable=False, default=GIZLILIK_NORMAL)
    aktif: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)


class PersonelBelgeTuru(Base):
    """Belge gerekliliği: zorunlu / koşullu / isteğe bağlı + hukuki dayanak."""

    __tablename__ = "personel_belge_turleri"
    __table_args__ = (UniqueConstraint("kod", name="uq_personel_belge_turu_kod"),)

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    kategori_id: Mapped[int] = mapped_column(ForeignKey("personel_belge_kategorileri.id"), nullable=False)
    kod: Mapped[str] = mapped_column(String(60), nullable=False)
    ad: Mapped[str] = mapped_column(String(150), nullable=False)
    sinif: Mapped[str] = mapped_column(String(20), nullable=False, default=BELGE_SINIF_ISTEGE)
    uygulanma_kosulu: Mapped[str | None] = mapped_column(String(500), nullable=True)
    hukuki_dayanak: Mapped[str | None] = mapped_column(String(300), nullable=True)
    kontrol_sorumlusu: Mapped[str | None] = mapped_column(String(120), nullable=True)
    gecerlilik_kurali: Mapped[str | None] = mapped_column(String(300), nullable=True)
    saklama_baslangic: Mapped[str | None] = mapped_column(String(80), nullable=True)
    saklama_sure_yil: Mapped[int | None] = mapped_column(Integer, nullable=True)
    saklama_dayanak: Mapped[str | None] = mapped_column(String(300), nullable=True)
    gizlilik: Mapped[str] = mapped_column(String(20), nullable=False, default=GIZLILIK_NORMAL)
    kritik_ise_baslama: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    aktif: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)


class PersonelBelge(Base):
    """Özlük belgesi üst kaydı — sürümler ayrı satırlarda tutulur."""

    __tablename__ = "personel_belgeleri"
    __table_args__ = (Index("ix_personel_belge_personel", "personel_id"),)

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    personel_id: Mapped[int] = mapped_column(ForeignKey("personel_kartlari.id"), nullable=False)
    tur_id: Mapped[int] = mapped_column(ForeignKey("personel_belge_turleri.id"), nullable=False)
    durum: Mapped[str] = mapped_column(String(30), nullable=False, default=BELGE_DURUM_EKSIK)
    gecerli_surum_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    uygulanmiyor: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    uygulanmiyor_gerekce: Mapped[str | None] = mapped_column(String(300), nullable=True)
    hukuki_saklama_engeli: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    olusturma: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.now)

    surumler: Mapped[list["PersonelBelgeSurumu"]] = relationship(
        back_populates="belge", cascade="all, delete-orphan",
        order_by="PersonelBelgeSurumu.surum_no.desc()",
        foreign_keys="PersonelBelgeSurumu.belge_id",
    )


class PersonelBelgeSurumu(Base):
    __tablename__ = "personel_belge_surumleri"
    __table_args__ = (
        UniqueConstraint("belge_id", "surum_no", name="uq_personel_belge_surum"),
        Index("ix_personel_belge_surum_hash", "dosya_hash"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    belge_id: Mapped[int] = mapped_column(ForeignKey("personel_belgeleri.id"), nullable=False)
    surum_no: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    belge_adi: Mapped[str] = mapped_column(String(200), nullable=False)
    duzenlenme_tarihi: Mapped[date | None] = mapped_column(Date, nullable=True)
    gecerlilik_tarihi: Mapped[date | None] = mapped_column(Date, nullable=True)
    yenileme_tarihi: Mapped[date | None] = mapped_column(Date, nullable=True)
    donem: Mapped[str | None] = mapped_column(String(40), nullable=True)
    belge_no: Mapped[str | None] = mapped_column(String(80), nullable=True)
    barkod: Mapped[str | None] = mapped_column(String(80), nullable=True)
    duzenleyen_kurum: Mapped[str | None] = mapped_column(String(150), nullable=True)
    aciklama: Mapped[str | None] = mapped_column(String(500), nullable=True)
    gizlilik: Mapped[str] = mapped_column(String(20), nullable=False, default=GIZLILIK_NORMAL)
    dosya_adi: Mapped[str] = mapped_column(String(200), nullable=False)
    dosya_yolu: Mapped[str] = mapped_column(String(500), nullable=False)
    dosya_uzanti: Mapped[str] = mapped_column(String(20), nullable=False)
    dosya_boyut: Mapped[int] = mapped_column(Integer, nullable=False)
    dosya_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    mime_tur: Mapped[str | None] = mapped_column(String(80), nullable=True)
    sifreli: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    yukleyen: Mapped[str | None] = mapped_column(String(120), nullable=True)
    yukleme_zamani: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.now)
    kontrol_eden: Mapped[str | None] = mapped_column(String(120), nullable=True)
    kontrol_tarihi: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    kontrol_sonucu: Mapped[str | None] = mapped_column(String(200), nullable=True)
    imha_edildi: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    imha_tarihi: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    imha_eden: Mapped[str | None] = mapped_column(String(120), nullable=True)

    belge: Mapped["PersonelBelge"] = relationship(
        back_populates="surumler", foreign_keys=[belge_id]
    )


class PersonelHakedis(Base):
    """Aylık net hakediş takibi — resmî bordro motoru değildir."""

    __tablename__ = "personel_hakedisleri"
    __table_args__ = (
        UniqueConstraint(
            "personel_id", "donem_id", "yil", "ay", "kayit_turu",
            name="uq_personel_hakedis_normal",
        ),
        Index("ix_personel_hakedis_ay", "yil", "ay"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    personel_id: Mapped[int] = mapped_column(ForeignKey("personel_kartlari.id"), nullable=False)
    donem_id: Mapped[int] = mapped_column(ForeignKey("personel_calisma_donemleri.id"), nullable=False)
    yil: Mapped[int] = mapped_column(Integer, nullable=False)
    ay: Mapped[int] = mapped_column(Integer, nullable=False)
    kayit_turu: Mapped[str] = mapped_column(String(20), nullable=False, default="NORMAL")
    kaynak_hakedis_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    temel_ucret: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False, default=0)
    ek_odeme: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False, default=0)
    fazla_mesai: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False, default=0)
    kesinti: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False, default=0)
    net_hakedis: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False, default=0)
    bordro_kaynagi: Mapped[str | None] = mapped_column(String(200), nullable=True)
    durum: Mapped[str] = mapped_column(String(20), nullable=False, default=HAKEDIS_TASLAK)
    aciklama: Mapped[str | None] = mapped_column(String(500), nullable=True)
    onaylayan: Mapped[str | None] = mapped_column(String(120), nullable=True)
    onay_tarihi: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    olusturan: Mapped[str | None] = mapped_column(String(120), nullable=True)
    olusturma: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.now)


class PersonelHesapHareketi(Base):
    """Avans, maaş ödemesi, mahsup, masraf — kasa/banka belgesine bağlanır."""

    __tablename__ = "personel_hesap_hareketleri"
    __table_args__ = (
        Index("ix_personel_hareket_personel", "personel_id"),
        Index("ix_personel_hareket_tarih", "tarih"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    personel_id: Mapped[int] = mapped_column(ForeignKey("personel_kartlari.id"), nullable=False)
    donem_id: Mapped[int | None] = mapped_column(ForeignKey("personel_calisma_donemleri.id"), nullable=True)
    hakedis_id: Mapped[int | None] = mapped_column(ForeignKey("personel_hakedisleri.id"), nullable=True)
    hareket_turu: Mapped[str] = mapped_column(String(30), nullable=False)
    tarih: Mapped[date] = mapped_column(Date, nullable=False)
    tutar: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    aciklama: Mapped[str | None] = mapped_column(String(500), nullable=True)
    # Mevcut kasa/banka belgesi bağlantısı — ikinci ödeme belgesi üretilmez
    belge_turu: Mapped[str | None] = mapped_column(String(40), nullable=True)
    belge_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    belge_no: Mapped[str | None] = mapped_column(String(60), nullable=True)
    iptal: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    iptal_tarihi: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    iptal_eden: Mapped[str | None] = mapped_column(String(120), nullable=True)
    kaynak_hareket_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    olusturan: Mapped[str | None] = mapped_column(String(120), nullable=True)
    olusturma: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.now)


class PersonelPuantaj(Base):
    __tablename__ = "personel_puantaj"
    __table_args__ = (
        Index("ix_personel_puantaj_kisi_tarih", "personel_id", "tarih"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    personel_id: Mapped[int] = mapped_column(ForeignKey("personel_kartlari.id"), nullable=False)
    donem_id: Mapped[int | None] = mapped_column(ForeignKey("personel_calisma_donemleri.id"), nullable=True)
    tarih: Mapped[date] = mapped_column(Date, nullable=False)
    tur: Mapped[str] = mapped_column(String(30), nullable=False, default=PUANTAJ_CALISMA)
    saat: Mapped[Decimal] = mapped_column(Numeric(8, 2), nullable=False, default=0)
    aciklama: Mapped[str | None] = mapped_column(String(300), nullable=True)
    izin_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    olusturan: Mapped[str | None] = mapped_column(String(120), nullable=True)
    olusturma: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.now)


class PersonelIzin(Base):
    __tablename__ = "personel_izinleri"
    __table_args__ = (Index("ix_personel_izin_kisi", "personel_id"),)

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    personel_id: Mapped[int] = mapped_column(ForeignKey("personel_kartlari.id"), nullable=False)
    donem_id: Mapped[int | None] = mapped_column(ForeignKey("personel_calisma_donemleri.id"), nullable=True)
    izin_turu: Mapped[str] = mapped_column(String(20), nullable=False, default=IZIN_YILLIK)
    durum: Mapped[str] = mapped_column(String(20), nullable=False, default=IZIN_TALEP)
    baslangic: Mapped[date] = mapped_column(Date, nullable=False)
    bitis: Mapped[date] = mapped_column(Date, nullable=False)
    gun: Mapped[Decimal] = mapped_column(Numeric(8, 2), nullable=False)
    aciklama: Mapped[str | None] = mapped_column(String(500), nullable=True)
    kural_surum: Mapped[str | None] = mapped_column(String(40), nullable=True)
    onaylayan: Mapped[str | None] = mapped_column(String(120), nullable=True)
    onay_tarihi: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    olusturan: Mapped[str | None] = mapped_column(String(120), nullable=True)
    olusturma: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.now)


class PersonelIzinHakedis(Base):
    """Yıllık izin hakediş / devir / kullanım özeti (takvim yılı başında otomatik sıfırlanmaz)."""

    __tablename__ = "personel_izin_hakedis"
    __table_args__ = (
        UniqueConstraint("personel_id", "yil", name="uq_personel_izin_hakedis_yil"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    personel_id: Mapped[int] = mapped_column(ForeignKey("personel_kartlari.id"), nullable=False)
    yil: Mapped[int] = mapped_column(Integer, nullable=False)
    hak_edilen: Mapped[Decimal] = mapped_column(Numeric(8, 2), nullable=False, default=0)
    onceki_devir: Mapped[Decimal] = mapped_column(Numeric(8, 2), nullable=False, default=0)
    kullanilan: Mapped[Decimal] = mapped_column(Numeric(8, 2), nullable=False, default=0)
    kalan: Mapped[Decimal] = mapped_column(Numeric(8, 2), nullable=False, default=0)
    esas_tarih: Mapped[date | None] = mapped_column(Date, nullable=True)
    yas: Mapped[int | None] = mapped_column(Integer, nullable=True)
    kural_surum: Mapped[str | None] = mapped_column(String(40), nullable=True)
    kural_kaynak: Mapped[str | None] = mapped_column(String(200), nullable=True)
    aciklama: Mapped[str | None] = mapped_column(String(300), nullable=True)


class PersonelSgkIslem(Base):
    """SGK / MPHB / ödeme kanıt takibi — gönderim yapılmış gibi gösterilmez."""

    __tablename__ = "personel_sgk_islemleri"
    __table_args__ = (
        Index("ix_personel_sgk_isyeri_donem", "isyeri_kodu", "donem_yil", "donem_ay"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    islem_turu: Mapped[str] = mapped_column(String(30), nullable=False)
    # MPHB gibi dönem beyanları işyeri düzeyinde tek ana kayıttır
    isyeri_kodu: Mapped[str | None] = mapped_column(String(60), nullable=True)
    isyeri_sicil: Mapped[str | None] = mapped_column(String(60), nullable=True)
    donem_yil: Mapped[int | None] = mapped_column(Integer, nullable=True)
    donem_ay: Mapped[int | None] = mapped_column(Integer, nullable=True)
    nitelik: Mapped[str | None] = mapped_column(String(20), nullable=True)  # ASIL / EK / DUZELTME
    durum: Mapped[str] = mapped_column(String(40), nullable=False, default=SGK_HAZIRLANACAK)
    personel_id: Mapped[int | None] = mapped_column(ForeignKey("personel_kartlari.id"), nullable=True)
    donem_id: Mapped[int | None] = mapped_column(ForeignKey("personel_calisma_donemleri.id"), nullable=True)
    baslangic_tarihi: Mapped[date | None] = mapped_column(Date, nullable=True)
    bildirim_tarihi: Mapped[date | None] = mapped_column(Date, nullable=True)
    son_tarih: Mapped[date | None] = mapped_column(Date, nullable=True)
    son_tarih_kural: Mapped[str | None] = mapped_column(String(80), nullable=True)
    son_tarih_kaynak: Mapped[str | None] = mapped_column(String(200), nullable=True)
    onay_no: Mapped[str | None] = mapped_column(String(80), nullable=True)
    onay_tarihi: Mapped[date | None] = mapped_column(Date, nullable=True)
    sgk_tahakkuk: Mapped[Decimal | None] = mapped_column(Numeric(18, 2), nullable=True)
    vergi_tahakkuk: Mapped[Decimal | None] = mapped_column(Numeric(18, 2), nullable=True)
    sgk_odeme_durum: Mapped[str | None] = mapped_column(String(30), nullable=True)
    vergi_odeme_durum: Mapped[str | None] = mapped_column(String(30), nullable=True)
    sgk_odeme_son_tarih: Mapped[date | None] = mapped_column(Date, nullable=True)
    vergi_odeme_son_tarih: Mapped[date | None] = mapped_column(Date, nullable=True)
    hazirlayan: Mapped[str | None] = mapped_column(String(120), nullable=True)
    aciklama: Mapped[str | None] = mapped_column(String(500), nullable=True)
    resmi_cikti_yolu: Mapped[str | None] = mapped_column(String(500), nullable=True)
    # Portal şifresi saklanmaz; bağlantı açmak bildirim göndermek sayılmaz
    entegrasyon_yok: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    olusturan: Mapped[str | None] = mapped_column(String(120), nullable=True)
    olusturma: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.now)
    guncelleme: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class PersonelSgkBaglanti(Base):
    """İşyeri dönem beyanını ilgili personel kartlarına bağlar (çoğaltmaz)."""

    __tablename__ = "personel_sgk_baglantilari"
    __table_args__ = (
        UniqueConstraint("sgk_islem_id", "personel_id", name="uq_personel_sgk_bag"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    sgk_islem_id: Mapped[int] = mapped_column(ForeignKey("personel_sgk_islemleri.id"), nullable=False)
    personel_id: Mapped[int] = mapped_column(ForeignKey("personel_kartlari.id"), nullable=False)
    donem_id: Mapped[int | None] = mapped_column(ForeignKey("personel_calisma_donemleri.id"), nullable=True)


class PersonelMevzuatParametre(Base):
    """Yürürlük tarihli sürümlü kural — süre/oran kaynak olmadan sabitlenmez."""

    __tablename__ = "personel_mevzuat_parametreleri"
    __table_args__ = (
        UniqueConstraint("kod", "surum", name="uq_personel_mevzuat_surum"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    kod: Mapped[str] = mapped_column(String(60), nullable=False)
    surum: Mapped[str] = mapped_column(String(40), nullable=False)
    kapsam: Mapped[str | None] = mapped_column(String(120), nullable=True)
    deger_json: Mapped[str] = mapped_column(Text, nullable=False)
    resmi_kaynak: Mapped[str] = mapped_column(String(300), nullable=False)
    kontrol_tarihi: Mapped[date] = mapped_column(Date, nullable=False)
    onaylayan: Mapped[str | None] = mapped_column(String(120), nullable=True)
    yururluk_baslangic: Mapped[date] = mapped_column(Date, nullable=False)
    yururluk_bitis: Mapped[date | None] = mapped_column(Date, nullable=True)
    aktif: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)


class PersonelErisimLog(Base):
    """Belge görüntüleme dahil erişim — tıbbi/adli içerik yazılmaz."""

    __tablename__ = "personel_erisim_loglari"
    __table_args__ = (Index("ix_personel_erisim_zaman", "zaman"),)

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    kullanici: Mapped[str] = mapped_column(String(120), nullable=False)
    islem: Mapped[str] = mapped_column(String(40), nullable=False)
    belge_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    surum_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    personel_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    zaman: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.now)
    ayrinti: Mapped[str | None] = mapped_column(String(200), nullable=True)


class PersonelGecmis(Base):
    __tablename__ = "personel_gecmis"
    __table_args__ = (Index("ix_personel_gecmis_kisi", "personel_id"),)

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    personel_id: Mapped[int] = mapped_column(ForeignKey("personel_kartlari.id"), nullable=False)
    alan: Mapped[str] = mapped_column(String(60), nullable=False)
    eski_deger: Mapped[str | None] = mapped_column(Text, nullable=True)
    yeni_deger: Mapped[str | None] = mapped_column(Text, nullable=True)
    kullanici: Mapped[str | None] = mapped_column(String(120), nullable=True)
    zaman: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.now)
