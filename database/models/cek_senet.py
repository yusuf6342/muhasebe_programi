"""Çek / Senet evrak ve hareket modelleri (Aşama 1 iskeleti)."""

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
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from database.database import Base

# Evrak türleri
EVRAK_TURU_MUSTERI_CEKI = "MUSTERI_CEKI"
EVRAK_TURU_MUSTERI_SENEDI = "MUSTERI_SENEDI"
EVRAK_TURU_FIRMA_CEKI = "FIRMA_CEKI"
EVRAK_TURU_FIRMA_SENEDI = "FIRMA_SENEDI"

EVRAK_TURLERI = (
    (EVRAK_TURU_MUSTERI_CEKI, "Müşteri Çeki"),
    (EVRAK_TURU_MUSTERI_SENEDI, "Müşteri Senedi"),
    (EVRAK_TURU_FIRMA_CEKI, "Firma Çeki"),
    (EVRAK_TURU_FIRMA_SENEDI, "Firma Senedi"),
)

# Alınan / Verilen
ISLEM_YONU_ALINAN = "ALINAN"
ISLEM_YONU_VERILEN = "VERILEN"

ISLEM_YONLERI = (
    (ISLEM_YONU_ALINAN, "Alınan"),
    (ISLEM_YONU_VERILEN, "Verilen"),
)

# Durumlar (Aşama 1 + sonraki aşamalar için sabitler)
DURUM_PORTFOYDE = "PORTFOYDE"
DURUM_BANKAYA_TAHSILE = "BANKAYA_TAHSILE"
DURUM_BANKAYA_TEMINATA = "BANKAYA_TEMINATA"
DURUM_CIRO_EDILDI = "CIRO_EDILDI"
DURUM_TEDARIKCIYE_VERILDI = "TEDARIKCIYE_VERILDI"
DURUM_TAHSIL_EDILDI = "TAHSIL_EDILDI"
DURUM_ODENDI = "ODENDI"
DURUM_KISMI_TAHSIL = "KISMI_TAHSIL"
DURUM_KISMI_ODENDI = "KISMI_ODENDI"
DURUM_KARSILIKSIZ = "KARSILIKSIZ"
DURUM_PROTESTO = "PROTESTO"
DURUM_IADE = "IADE"
DURUM_GERI_ALINDI = "GERI_ALINDI"
DURUM_IPTAL = "IPTAL"
DURUM_YENILENDI = "YENILENDI"
DURUM_HUKUKI_TAKIP = "HUKUKI_TAKIP"
DURUM_VADESI_GECTI = "VADESI_GECTI"
DURUM_KAPANDI = "KAPANDI"

DURUM_ETIKETLERI = {
    DURUM_PORTFOYDE: "Portföyde",
    DURUM_BANKAYA_TAHSILE: "Bankaya tahsile verildi",
    DURUM_BANKAYA_TEMINATA: "Bankaya teminata verildi",
    DURUM_CIRO_EDILDI: "Ciro edildi",
    DURUM_TEDARIKCIYE_VERILDI: "Tedarikçiye verildi",
    DURUM_TAHSIL_EDILDI: "Tahsil edildi",
    DURUM_ODENDI: "Ödendi",
    DURUM_KISMI_TAHSIL: "Kısmi tahsil edildi",
    DURUM_KISMI_ODENDI: "Kısmi ödendi",
    DURUM_KARSILIKSIZ: "Karşılıksız çıktı",
    DURUM_PROTESTO: "Protesto edildi",
    DURUM_IADE: "İade edildi",
    DURUM_GERI_ALINDI: "Geri alındı",
    DURUM_IPTAL: "İptal edildi",
    DURUM_YENILENDI: "Yenilendi",
    DURUM_HUKUKI_TAKIP: "Hukuki takipte",
    DURUM_VADESI_GECTI: "Vadesi geçti",
    DURUM_KAPANDI: "Kapandı",
}

# Portföy no önekleri (plan §24)
PORTFOY_ONEK = {
    (EVRAK_TURU_MUSTERI_CEKI, ISLEM_YONU_ALINAN): "ALÇ",
    (EVRAK_TURU_MUSTERI_SENEDI, ISLEM_YONU_ALINAN): "ALS",
    (EVRAK_TURU_FIRMA_CEKI, ISLEM_YONU_VERILEN): "VRÇ",
    (EVRAK_TURU_FIRMA_SENEDI, ISLEM_YONU_VERILEN): "VRS",
    (EVRAK_TURU_MUSTERI_CEKI, ISLEM_YONU_VERILEN): "VRÇ",
    (EVRAK_TURU_MUSTERI_SENEDI, ISLEM_YONU_VERILEN): "VRS",
    (EVRAK_TURU_FIRMA_CEKI, ISLEM_YONU_ALINAN): "ALÇ",
    (EVRAK_TURU_FIRMA_SENEDI, ISLEM_YONU_ALINAN): "ALS",
}


class CekSenetEvrak(Base):
    """Çek / senet ana kaydı."""

    __tablename__ = "cek_senet_evraklari"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    sube_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    cari_id: Mapped[int | None] = mapped_column(
        ForeignKey("cari_kartlar.id"), nullable=True, index=True
    )
    banka_hesabi_id: Mapped[int | None] = mapped_column(
        ForeignKey("finans_hesaplari.id"), nullable=True, index=True
    )
    kasa_id: Mapped[int | None] = mapped_column(
        ForeignKey("finans_hesaplari.id"), nullable=True
    )

    evrak_turu: Mapped[str] = mapped_column(String(30), nullable=False, index=True)
    islem_yonu: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    evrak_no: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    seri_no: Mapped[str | None] = mapped_column(String(50), nullable=True)
    portfoy_no: Mapped[str] = mapped_column(String(40), unique=True, nullable=False, index=True)

    duzenleme_tarihi: Mapped[date] = mapped_column(Date, nullable=False)
    vade_tarihi: Mapped[date] = mapped_column(Date, nullable=False, index=True)

    doviz_turu: Mapped[str] = mapped_column(String(10), nullable=False, default="TL")
    doviz_tutari: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False, default=0)
    kur: Mapped[Decimal] = mapped_column(Numeric(18, 6), nullable=False, default=1)
    tl_tutari: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False, default=0)
    tahsil_edilen_tutar: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False, default=0)
    kalan_tutar: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False, default=0)

    durum: Mapped[str] = mapped_column(
        String(30), nullable=False, default=DURUM_PORTFOYDE, index=True
    )
    bulundugu_yer: Mapped[str | None] = mapped_column(String(100), nullable=True)
    aciklama: Mapped[str | None] = mapped_column(String(500), nullable=True)
    ozel_not: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Çek alanları
    banka_adi: Mapped[str | None] = mapped_column(String(100), nullable=True)
    banka_subesi: Mapped[str | None] = mapped_column(String(100), nullable=True)
    sube_kodu: Mapped[str | None] = mapped_column(String(30), nullable=True)
    hesap_no: Mapped[str | None] = mapped_column(String(50), nullable=True)
    iban: Mapped[str | None] = mapped_column(String(34), nullable=True)
    cek_no: Mapped[str | None] = mapped_column(String(50), nullable=True)
    kesideci_adi: Mapped[str | None] = mapped_column(String(200), nullable=True)
    kesideci_vergi_tc: Mapped[str | None] = mapped_column(String(20), nullable=True)
    keside_yeri: Mapped[str | None] = mapped_column(String(100), nullable=True)
    hesap_sahibi: Mapped[str | None] = mapped_column(String(200), nullable=True)
    lehtar: Mapped[str | None] = mapped_column(String(200), nullable=True)
    teslim_eden: Mapped[str | None] = mapped_column(String(200), nullable=True)
    karekod_ref: Mapped[str | None] = mapped_column(String(100), nullable=True)

    # Senet alanları
    senet_no: Mapped[str | None] = mapped_column(String(50), nullable=True)
    borclu_adi: Mapped[str | None] = mapped_column(String(200), nullable=True)
    borclu_vergi_tc: Mapped[str | None] = mapped_column(String(20), nullable=True)
    kefil: Mapped[str | None] = mapped_column(String(200), nullable=True)
    duzenleme_yeri: Mapped[str | None] = mapped_column(String(100), nullable=True)
    odeme_yeri: Mapped[str | None] = mapped_column(String(100), nullable=True)

    referans_belge_no: Mapped[str | None] = mapped_column(String(50), nullable=True)
    proje_etiketi: Mapped[str | None] = mapped_column(String(100), nullable=True)
    masraf_merkezi: Mapped[str | None] = mapped_column(String(100), nullable=True)

    aktif: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    created_by: Mapped[str | None] = mapped_column(String(100), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=datetime.now
    )
    updated_by: Mapped[str | None] = mapped_column(String(100), nullable=True)
    updated_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    son_islem_tarihi: Mapped[date | None] = mapped_column(Date, nullable=True)

    cari = relationship("Cari", foreign_keys=[cari_id])
    hareketler: Mapped[list["CekSenetHareket"]] = relationship(
        "CekSenetHareket",
        back_populates="evrak",
        cascade="all, delete-orphan",
        order_by="CekSenetHareket.id",
    )


class CekSenetHareket(Base):
    """Evrak durum / işlem geçmişi (silinemez log — Aşama 1 iskeleti)."""

    __tablename__ = "cek_senet_hareketleri"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    evrak_id: Mapped[int] = mapped_column(
        ForeignKey("cek_senet_evraklari.id"), nullable=False, index=True
    )
    tarih: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.now)
    onceki_durum: Mapped[str | None] = mapped_column(String(30), nullable=True)
    yeni_durum: Mapped[str] = mapped_column(String(30), nullable=False)
    islem_turu: Mapped[str] = mapped_column(String(50), nullable=False)
    tutar: Mapped[Decimal | None] = mapped_column(Numeric(18, 2), nullable=True)
    aciklama: Mapped[str | None] = mapped_column(String(500), nullable=True)
    ilgili_cari_id: Mapped[int | None] = mapped_column(
        ForeignKey("cari_kartlar.id"), nullable=True
    )
    ilgili_banka_kasa_id: Mapped[int | None] = mapped_column(
        ForeignKey("finans_hesaplari.id"), nullable=True
    )
    cari_hareket_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    finans_hareket_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    muhasebe_fisi_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    kullanici: Mapped[str | None] = mapped_column(String(100), nullable=True)

    evrak: Mapped["CekSenetEvrak"] = relationship(
        "CekSenetEvrak", back_populates="hareketler"
    )
