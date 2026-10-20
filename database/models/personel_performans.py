"""Ölçme / değerlendirme / kariyer / prim dönem kayıtları — standart personel kimliğine bağlı."""

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

GOREV_ALANLARI = (
    ("SATIS", "Satış"),
    ("HAZIRLAMA", "Hazırlama"),
    ("STOK", "Stok"),
    ("SEVKIYAT", "Sevkiyat"),
    ("FINANS", "Finans"),
)

IS_PLANLANDI = "PLANLANDI"
IS_BASLADI = "BASLADI"
IS_ENGELLENDI = "ENGELLENDI"
IS_KONTROL = "KONTROL_BEKLIYOR"
IS_TAMAMLANDI = "TAMAMLANDI"
IS_DURUMLARI = (
    (IS_PLANLANDI, "Planlandı"),
    (IS_BASLADI, "Başladı"),
    (IS_ENGELLENDI, "Engellendi"),
    (IS_KONTROL, "Kontrol bekliyor"),
    (IS_TAMAMLANDI, "Tamamlandı"),
)

ASAMA_SATIS = "SATIS_SAHIBI"
ASAMA_HAZIRLIK = "HAZIRLAMA"
ASAMA_KONTROL = "KONTROL"
ASAMA_TESLIM = "TESLIM"
ASAMA_TAHSILAT = "TAHSILAT_TAKIP"

KADEME_OGRENEN = "OGRENEN"
KADEME_YETKIN = "YETKIN"
KADEME_KIDEMLI = "KIDEMLI"
KADEME_UZMAN = "UZMAN_LIDER"
KADEMELER = (
    (KADEME_OGRENEN, "Öğrenen"),
    (KADEME_YETKIN, "Yetkin"),
    (KADEME_KIDEMLI, "Kıdemli"),
    (KADEME_UZMAN, "Uzman veya lider"),
)

PRIM_TASLAK = "TASLAK"
PRIM_EKSIK = "VERILER_EKSIK"
PRIM_HESAPLANDI = "HESAPLANDI"
PRIM_INCELEME = "INCELEMEDE"
PRIM_ONAYLI = "ONAYLANDI"
PRIM_BORDRO = "BORDROYA_AKTARILDI"
PRIM_ODENDI = "ODENDI"
PRIM_DURUMLARI = (
    (PRIM_TASLAK, "Taslak"),
    (PRIM_EKSIK, "Veriler eksik"),
    (PRIM_HESAPLANDI, "Hesaplandı"),
    (PRIM_INCELEME, "İncelemede"),
    (PRIM_ONAYLI, "Onaylandı"),
    (PRIM_BORDRO, "Bordroya aktarıldı"),
    (PRIM_ODENDI, "Ödendi"),
)


class PersonelGorevAtama(Base):
    __tablename__ = "personel_gorev_atamalari"
    __table_args__ = (
        Index("ix_pgorev_personel", "personel_id"),
        UniqueConstraint("personel_id", "gorev_alani", "gecerli_baslangic", name="uq_pgorev_donem"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    personel_id: Mapped[int] = mapped_column(ForeignKey("personel_kartlari.id"), nullable=False)
    donem_id: Mapped[int | None] = mapped_column(ForeignKey("personel_calisma_donemleri.id"), nullable=True)
    gorev_alani: Mapped[str] = mapped_column(String(30), nullable=False)
    rol: Mapped[str] = mapped_column(String(20), nullable=False, default="ASIL")  # ASIL / YEDEK / DESTEK
    yonetici_personel_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    gecerli_baslangic: Mapped[date] = mapped_column(Date, nullable=False)
    gecerli_bitis: Mapped[date | None] = mapped_column(Date, nullable=True)
    aktif: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    aciklama: Mapped[str | None] = mapped_column(String(300), nullable=True)


class PersonelIsKaydi(Base):
    __tablename__ = "personel_is_kayitlari"
    __table_args__ = (
        Index("ix_pis_durum", "durum"),
        Index("ix_pis_sorumlu", "sorumlu_personel_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    baslik: Mapped[str] = mapped_column(String(200), nullable=False)
    gorev_alani: Mapped[str] = mapped_column(String(30), nullable=False)
    durum: Mapped[str] = mapped_column(String(30), nullable=False, default=IS_PLANLANDI)
    sorumlu_personel_id: Mapped[int | None] = mapped_column(ForeignKey("personel_kartlari.id"), nullable=True)
    donem_id: Mapped[int | None] = mapped_column(
        ForeignKey("personel_calisma_donemleri.id"), nullable=True
    )
    takip_personel_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    destek_personel_ids: Mapped[str | None] = mapped_column(String(200), nullable=True)  # csv
    kaynak_belge_turu: Mapped[str | None] = mapped_column(String(40), nullable=True)
    kaynak_belge_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    oncelik: Mapped[int] = mapped_column(Integer, nullable=False, default=3)
    hedef_tarih: Mapped[date | None] = mapped_column(Date, nullable=True)
    hedef_saat: Mapped[str | None] = mapped_column(String(8), nullable=True)  # HH:MM
    gerceklesen_tarih: Mapped[date | None] = mapped_column(Date, nullable=True)
    is_buyuklugu: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False, default=1)
    dis_engel: Mapped[str | None] = mapped_column(String(300), nullable=True)
    aciklama: Mapped[str | None] = mapped_column(Text, nullable=True)
    olusturan: Mapped[str | None] = mapped_column(String(120), nullable=True)
    olusturma: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.now)
    guncelleyen: Mapped[str | None] = mapped_column(String(120), nullable=True)
    guncelleme: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class PersonelIsGecmis(Base):
    """İş kaydı alan geçmişi — oluşturan kullanıcı ≠ sorumlu personel."""

    __tablename__ = "personel_is_gecmis"
    __table_args__ = (Index("ix_pis_gecmis_is", "is_kaydi_id"),)

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    is_kaydi_id: Mapped[int] = mapped_column(ForeignKey("personel_is_kayitlari.id"), nullable=False)
    alan: Mapped[str] = mapped_column(String(60), nullable=False)
    eski_deger: Mapped[str | None] = mapped_column(Text, nullable=True)
    yeni_deger: Mapped[str | None] = mapped_column(Text, nullable=True)
    kullanici: Mapped[str | None] = mapped_column(String(120), nullable=True)
    zaman: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.now)


class PersonelKatkiOlay(Base):
    """Kaynak olay: firma+tür+belge+satır+aşama+sürüm benzersiz."""

    __tablename__ = "personel_katki_olaylari"
    __table_args__ = (
        UniqueConstraint(
            "kaynak_turu", "belge_id", "satir_id", "asama", "olay_surum",
            name="uq_pkatki_olay",
        ),
        Index("ix_pkatki_personel", "personel_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    personel_id: Mapped[int] = mapped_column(ForeignKey("personel_kartlari.id"), nullable=False)
    yapan_personel_id: Mapped[int] = mapped_column(Integer, nullable=False)  # işi yapan
    kaydeden_kullanici: Mapped[str | None] = mapped_column(String(120), nullable=True)
    kaynak_turu: Mapped[str] = mapped_column(String(40), nullable=False)
    belge_id: Mapped[int] = mapped_column(Integer, nullable=False)
    satir_id: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    asama: Mapped[str] = mapped_column(String(40), nullable=False)
    olay_surum: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    pay_yuzde: Mapped[Decimal] = mapped_column(Numeric(8, 4), nullable=False, default=100)
    adet: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False, default=1)
    satir_sayisi: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False, default=0)
    zorluk: Mapped[Decimal] = mapped_column(Numeric(8, 2), nullable=False, default=1)
    hatasiz: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    iptal: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    tarih: Mapped[date] = mapped_column(Date, nullable=False)
    aciklama: Mapped[str | None] = mapped_column(String(300), nullable=True)


class PersonelOlcutSurumu(Base):
    __tablename__ = "personel_olcut_surumleri"
    __table_args__ = (UniqueConstraint("kod", "surum", name="uq_polcut_surum"),)

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    kod: Mapped[str] = mapped_column(String(40), nullable=False)
    surum: Mapped[str] = mapped_column(String(40), nullable=False)
    gorev_alani: Mapped[str] = mapped_column(String(30), nullable=False)
    ad: Mapped[str] = mapped_column(String(120), nullable=False)
    agirlik: Mapped[Decimal] = mapped_column(Numeric(8, 4), nullable=False)
    hedef: Mapped[Decimal | None] = mapped_column(Numeric(18, 4), nullable=True)
    ornek_alt_sinir: Mapped[int] = mapped_column(Integer, nullable=False, default=5)
    yuksek_iyi: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    veri_kaynagi: Mapped[str | None] = mapped_column(String(120), nullable=True)
    aktif: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)


class PersonelDegerlendirme(Base):
    __tablename__ = "personel_degerlendirmeleri"
    __table_args__ = (
        UniqueConstraint("personel_id", "yil", "ay", name="uq_pdeg_ay"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    personel_id: Mapped[int] = mapped_column(ForeignKey("personel_kartlari.id"), nullable=False)
    yil: Mapped[int] = mapped_column(Integer, nullable=False)
    ay: Mapped[int] = mapped_column(Integer, nullable=False)
    gorev_sonucu: Mapped[Decimal] = mapped_column(Numeric(8, 2), nullable=False, default=0)
    kalite: Mapped[Decimal] = mapped_column(Numeric(8, 2), nullable=False, default=0)
    ekip_katkisi: Mapped[Decimal] = mapped_column(Numeric(8, 2), nullable=False, default=0)
    gelisim: Mapped[Decimal] = mapped_column(Numeric(8, 2), nullable=False, default=0)
    toplam_puan: Mapped[Decimal] = mapped_column(Numeric(8, 2), nullable=False, default=0)
    ornek_sayisi: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    kesin: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    eksik_veri: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    calisan_aciklama: Mapped[str | None] = mapped_column(Text, nullable=True)
    itiraz: Mapped[str | None] = mapped_column(Text, nullable=True)
    degerlendiren: Mapped[str | None] = mapped_column(String(120), nullable=True)
    olcut_surum: Mapped[str | None] = mapped_column(String(40), nullable=True)
    olusturma: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.now)


class PersonelGelisimPlani(Base):
    __tablename__ = "personel_gelisim_planlari"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    personel_id: Mapped[int] = mapped_column(ForeignKey("personel_kartlari.id"), nullable=False)
    baslangic: Mapped[date] = mapped_column(Date, nullable=False)
    bitis: Mapped[date] = mapped_column(Date, nullable=False)  # 90 gün
    hedef_beceri: Mapped[str] = mapped_column(String(200), nullable=False)
    egitim_destegi: Mapped[str | None] = mapped_column(String(300), nullable=True)
    uygulama_gorevi: Mapped[str | None] = mapped_column(String(300), nullable=True)
    kontrol_tarihi: Mapped[date | None] = mapped_column(Date, nullable=True)
    durum: Mapped[str] = mapped_column(String(30), nullable=False, default="AKTIF")
    sonuc: Mapped[str | None] = mapped_column(String(300), nullable=True)


class PersonelKariyerKarari(Base):
    __tablename__ = "personel_kariyer_kararlari"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    personel_id: Mapped[int] = mapped_column(ForeignKey("personel_kartlari.id"), nullable=False)
    yol: Mapped[str] = mapped_column(String(30), nullable=False, default="UZMANLIK")  # UZMANLIK / EKIP_LIDERLIGI
    kademe: Mapped[str] = mapped_column(String(30), nullable=False)
    unvan: Mapped[str | None] = mapped_column(String(120), nullable=True)
    gorev: Mapped[str | None] = mapped_column(String(120), nullable=True)
    ucret_bandi: Mapped[str | None] = mapped_column(String(80), nullable=True)
    gecerlilik: Mapped[date] = mapped_column(Date, nullable=False)
    karar_veren: Mapped[str | None] = mapped_column(String(120), nullable=True)
    eksik_kosullar: Mapped[str | None] = mapped_column(String(500), nullable=True)
    onayli: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    # Ortaklık / hisse devri bu modülden üretilmez
    ortaklik_degil: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    aciklama: Mapped[str | None] = mapped_column(String(500), nullable=True)


class PersonelPrimPolitika(Base):
    __tablename__ = "personel_prim_politikalari"
    __table_args__ = (UniqueConstraint("kod", "surum", name="uq_pprim_pol"),)

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    kod: Mapped[str] = mapped_column(String(40), nullable=False, default="VARSAYILAN")
    surum: Mapped[str] = mapped_column(String(40), nullable=False)
    gecerli_baslangic: Mapped[date] = mapped_column(Date, nullable=False)
    gecerli_bitis: Mapped[date | None] = mapped_column(Date, nullable=True)
    prim_orani: Mapped[Decimal] = mapped_column(Numeric(8, 6), nullable=False, default=Decimal("0.10"))
    guvence_tutari: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False, default=0)
    agirlik_ekip: Mapped[Decimal] = mapped_column(Numeric(8, 4), nullable=False, default=Decimal("0.50"))
    agirlik_katki: Mapped[Decimal] = mapped_column(Numeric(8, 4), nullable=False, default=Decimal("0.30"))
    agirlik_kidem: Mapped[Decimal] = mapped_column(Numeric(8, 4), nullable=False, default=Decimal("0.20"))
    butce_modu: Mapped[str] = mapped_column(String(40), nullable=False, default="ISVEREN_MALIYETI")
    aktif: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    canli_politika: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    aciklama: Mapped[str | None] = mapped_column(String(500), nullable=True)
    resmi_not: Mapped[str | None] = mapped_column(
        String(300),
        nullable=True,
        default="Örnek başlangıç önerisi — canlı ücret politikası değildir.",
    )


class PersonelPrimDonemi(Base):
    __tablename__ = "personel_prim_donemleri"
    __table_args__ = (
        UniqueConstraint("baslangic", "bitis", name="uq_pprim_donem_aralik"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    baslangic: Mapped[date] = mapped_column(Date, nullable=False)
    bitis: Mapped[date] = mapped_column(Date, nullable=False)
    durum: Mapped[str] = mapped_column(String(30), nullable=False, default=PRIM_TASLAK)
    politika_id: Mapped[int | None] = mapped_column(ForeignKey("personel_prim_politikalari.id"), nullable=True)
    politika_surum: Mapped[str | None] = mapped_column(String(40), nullable=True)
    tahsil_kar: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False, default=0)
    uygun_gider: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False, default=0)
    onceki_zarar: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False, default=0)
    yeni_zarar: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False, default=0)
    guvence: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False, default=0)
    taban_b: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False, default=0)
    prim_butcesi: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False, default=0)
    dagitilan: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False, default=0)
    dagitilmamis: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False, default=0)
    eksik_veri: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    hesaplayan: Mapped[str | None] = mapped_column(String(120), nullable=True)
    onaylayan: Mapped[str | None] = mapped_column(String(120), nullable=True)
    onay_zamani: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    hesap_surumu: Mapped[str] = mapped_column(String(40), nullable=False, default="1")
    simulasyon: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    aciklama: Mapped[str | None] = mapped_column(String(500), nullable=True)


class PersonelPrimPay(Base):
    __tablename__ = "personel_prim_paylari"
    __table_args__ = (
        UniqueConstraint("donem_id", "personel_id", name="uq_pprim_pay"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    donem_id: Mapped[int] = mapped_column(ForeignKey("personel_prim_donemleri.id"), nullable=False)
    personel_id: Mapped[int] = mapped_column(ForeignKey("personel_kartlari.id"), nullable=False)
    katilim: Mapped[Decimal] = mapped_column(Numeric(8, 4), nullable=False, default=1)
    performans: Mapped[Decimal] = mapped_column(Numeric(8, 2), nullable=False, default=0)
    kidem_katsayi: Mapped[Decimal] = mapped_column(Numeric(8, 4), nullable=False, default=1)
    ekip_payi: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False, default=0)
    katki_payi: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False, default=0)
    kidem_payi: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False, default=0)
    toplam: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False, default=0)
    hak_edilen: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False, default=0)
    odenen: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False, default=0)
    kalan: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False, default=0)
    # Standart hakediş ek ödeme bağlantısı
    hakedis_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    bordro_baglanti_id: Mapped[str | None] = mapped_column(String(80), nullable=True)


class PersonelFaturaHDonuk(Base):
    """Fatura bazında dondurulmuş H — dönem farkı hesabı için."""

    __tablename__ = "personel_fatura_h_donuk"
    __table_args__ = (
        UniqueConstraint("donem_id", "fatura_id", name="uq_pfatura_h"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    donem_id: Mapped[int] = mapped_column(ForeignKey("personel_prim_donemleri.id"), nullable=False)
    fatura_id: Mapped[int] = mapped_column(Integer, nullable=False)
    fatura_no: Mapped[str | None] = mapped_column(String(60), nullable=True)
    S: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False, default=0)
    C: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False, default=0)
    M: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False, default=0)
    F: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False, default=0)
    T: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False, default=0)
    q: Mapped[Decimal] = mapped_column(Numeric(18, 8), nullable=False, default=0)
    H: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False, default=0)
    H_once: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False, default=0)
    H_fark: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False, default=0)
    eksik_maliyet: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    eksik_tahsilat: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
