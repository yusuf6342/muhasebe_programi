from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import Boolean, Date, DateTime, ForeignKey, Integer, Numeric, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from database.database import Base


class AlisIadeFaturasi(Base):
    __tablename__ = "alis_iade_faturalari"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    iade_no: Mapped[str] = mapped_column(String(30), unique=True, nullable=False)
    iade_tarihi: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    cari_id: Mapped[int] = mapped_column(ForeignKey("cari_kartlar.id"), nullable=False, index=True)
    sube_id: Mapped[int | None] = mapped_column(ForeignKey("subeler.id"), nullable=True, index=True)
    kaynak_fatura_id: Mapped[int | None] = mapped_column(ForeignKey("alis_faturalari.id"), nullable=True, index=True)
    # TASLAK (stok/cari/fiş yok) → AÇIK / KAPALI (onaylı; KAPALI = bedel tamamen tahsil edildi) → İPTAL.
    # Eski kayıtlar TASLAK aşaması olmadan doğrudan AÇIK/KAPALI yazılmıştır.
    durum: Mapped[str] = mapped_column(String(20), nullable=False, default="TASLAK")
    depo: Mapped[str] = mapped_column(String(100), nullable=False, default="ANA DEPO")
    iade_odeme_tutari: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False, default=0)
    iade_odeme_sekli: Mapped[str | None] = mapped_column(String(50), nullable=True)
    iade_odeme_hesabi: Mapped[str | None] = mapped_column(String(100), nullable=True)
    aciklama: Mapped[str | None] = mapped_column(Text, nullable=True)
    para_birimi: Mapped[str] = mapped_column(String(3), nullable=False, default="TRY")
    kur: Mapped[Decimal] = mapped_column(Numeric(18, 6), nullable=False, default=1)
    kur_tarihi: Mapped[date | None] = mapped_column(Date, nullable=True)
    kur_turu: Mapped[str] = mapped_column(String(30), nullable=False, default="forex_selling")
    kur_kaynagi: Mapped[str] = mapped_column(String(20), nullable=False, default="TCMB")
    kur_sabitlendi: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    doviz_ara_toplam: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False, default=0)
    olusturma_tarihi: Mapped[datetime] = mapped_column(DateTime, default=datetime.now, nullable=False)

    iade_nedeni: Mapped[str | None] = mapped_column(String(200), nullable=True)
    # FIFO: açık borçlar eskiden kapanır · KAYNAK: yalnız kaynak alışın açık kalemi · AVANS: kapatma yok
    mahsup_modu: Mapped[str | None] = mapped_column(String(20), nullable=True)
    olusturan: Mapped[str | None] = mapped_column(String(120), nullable=True)
    onaylayan: Mapped[str | None] = mapped_column(String(120), nullable=True)
    onay_tarihi: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    iptal_eden: Mapped[str | None] = mapped_column(String(120), nullable=True)
    iptal_tarihi: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    iptal_nedeni: Mapped[str | None] = mapped_column(Text, nullable=True)
    row_version: Mapped[int | None] = mapped_column(Integer, nullable=True, default=1)
    # Dövizli iadede KDV'nin TL karşılığının kuru (onayda firma ayarından yazılır): kaynak_kuru · iade_kuru.
    # NULL: TL iade veya yöntem seçilmeden onaylanmış dövizli iade (KDV belge kuruyla).
    kdv_kur_yontemi: Mapped[str | None] = mapped_column(String(20), nullable=True)
    kdv_tl_toplam: Mapped[Decimal | None] = mapped_column(Numeric(18, 2), nullable=True)

    cari = relationship("Cari")
    kaynak_fatura = relationship("AlisFaturasi")
    satirlar: Mapped[list["AlisIadeFaturasiSatiri"]] = relationship(
        "AlisIadeFaturasiSatiri", back_populates="iade", cascade="all, delete-orphan",
        order_by="AlisIadeFaturasiSatiri.id",
    )


class AlisIadeFaturasiSatiri(Base):
    __tablename__ = "alis_iade_faturasi_satirlari"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    iade_id: Mapped[int] = mapped_column(ForeignKey("alis_iade_faturalari.id"), nullable=False, index=True)
    kaynak_fatura_satiri_id: Mapped[int | None] = mapped_column(
        ForeignKey("alis_faturasi_satirlari.id"), nullable=True, index=True
    )
    urun_kodu: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    urun_adi: Mapped[str] = mapped_column(String(200), nullable=False)
    miktar: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False)
    birim: Mapped[str] = mapped_column(String(20), nullable=False)
    birim_fiyat: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False)
    iskonto_orani: Mapped[Decimal] = mapped_column(Numeric(7, 2), nullable=False, default=0)
    kdv_orani: Mapped[Decimal] = mapped_column(Numeric(7, 2), nullable=False, default=20)
    onceki_alis_fiyati: Mapped[Decimal | None] = mapped_column(Numeric(18, 4), nullable=True)
    onceki_fatura_no: Mapped[str | None] = mapped_column(String(30), nullable=True)
    fifo_birim_maliyeti: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False, default=0)
    # Belge birimi → temel birim katsayısı (kayıt anında; kart sonradan değişse de eski belge değişmez)
    birim_carpani: Mapped[Decimal | None] = mapped_column(Numeric(18, 6), nullable=True)
    lot_no: Mapped[str | None] = mapped_column(String(100), nullable=True)
    lot_cikisi: Mapped[str | None] = mapped_column(String(100), nullable=True)
    birim_fiyat_doviz: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False, default=0)

    barkod: Mapped[str | None] = mapped_column(String(50), nullable=True)
    iskonto_orani_2: Mapped[Decimal] = mapped_column(Numeric(7, 2), nullable=False, default=0)
    iskonto_orani_3: Mapped[Decimal] = mapped_column(Numeric(7, 2), nullable=False, default=0)
    temel_miktar: Mapped[Decimal | None] = mapped_column(Numeric(18, 4), nullable=True)
    # KAYNAKLI · DEVİR · KAYNAKSIZ · BAŞKA TEDARİKÇİ (boş: henüz denetlenmedi / eski kayıt)
    kaynak_durumu: Mapped[str | None] = mapped_column(String(20), nullable=True)
    kaynak_lot_id: Mapped[int | None] = mapped_column(ForeignKey("stok_lotlari.id"), nullable=True)
    kaynak_gerekce: Mapped[str | None] = mapped_column(Text, nullable=True)
    kaynak_onaylayan: Mapped[str | None] = mapped_column(String(120), nullable=True)
    kaynak_onay_tarihi: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    # Kullanıcı tercihinin verildiği ürün/miktar/tedarikçi/depo imzası; değişirse tercih geçersizdir
    kaynak_onay_imza: Mapped[str | None] = mapped_column(String(200), nullable=True)
    kaynak_birim_fiyat: Mapped[Decimal | None] = mapped_column(Numeric(18, 4), nullable=True)
    kaynak_kur: Mapped[Decimal | None] = mapped_column(Numeric(18, 6), nullable=True)
    kaynak_para_birimi: Mapped[str | None] = mapped_column(String(3), nullable=True)
    kaynak_kur_tarihi: Mapped[date | None] = mapped_column(Date, nullable=True)
    # Onay anındaki iade (belge) kuru ve satırın gerçekleşen kur farkı (+ gelir, − gider; TL)
    iade_kuru: Mapped[Decimal | None] = mapped_column(Numeric(18, 6), nullable=True)
    kur_farki_tl: Mapped[Decimal | None] = mapped_column(Numeric(18, 2), nullable=True)
    stok_maliyet_toplam: Mapped[Decimal | None] = mapped_column(Numeric(18, 2), nullable=True)
    # Satır KDV'sinin TL'ye çevrildiği kur ve TL tutarı (yalnız yöntemli dövizli iadede)
    kdv_kuru: Mapped[Decimal | None] = mapped_column(Numeric(18, 6), nullable=True)
    kdv_tl: Mapped[Decimal | None] = mapped_column(Numeric(18, 2), nullable=True)

    iade: Mapped["AlisIadeFaturasi"] = relationship("AlisIadeFaturasi", back_populates="satirlar")
    dagilimlar: Mapped[list["AlisIadeKaynakDagilimi"]] = relationship(
        "AlisIadeKaynakDagilimi", back_populates="satir", cascade="all, delete-orphan",
        order_by="AlisIadeKaynakDagilimi.id",
    )


class AlisIadeKaynakDagilimi(Base):
    """İade satırının kaynak alış satırlarına ve stok katmanlarına dağılımı (onayda yazılır)."""

    __tablename__ = "alis_iade_kaynak_dagilimlari"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    satir_id: Mapped[int] = mapped_column(
        ForeignKey("alis_iade_faturasi_satirlari.id", ondelete="CASCADE"), nullable=False, index=True
    )
    kaynak_fatura_satiri_id: Mapped[int | None] = mapped_column(
        ForeignKey("alis_faturasi_satirlari.id"), nullable=True, index=True
    )
    # Belge biriminde istenen (kullanıcı dağılımı) ve temel birimde çıkan miktar
    miktar: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False, default=0)
    temel_miktar: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False, default=0)
    lot_id: Mapped[int | None] = mapped_column(ForeignKey("stok_lotlari.id"), nullable=True, index=True)
    # İptalde hareket silinir; dağılım iz olarak kalır (yabancı anahtar yok)
    stok_hareket_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    birim_maliyet: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False, default=0)
    maliyet: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False, default=0)

    satir: Mapped["AlisIadeFaturasiSatiri"] = relationship("AlisIadeFaturasiSatiri", back_populates="dagilimlar")
