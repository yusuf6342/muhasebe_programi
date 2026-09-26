from datetime import date, datetime, time
from decimal import Decimal
from typing import TYPE_CHECKING

from sqlalchemy import Boolean, Date, DateTime, ForeignKey, Integer, Numeric, String, Text, Time
from sqlalchemy.orm import Mapped, mapped_column, relationship

from database.database import Base

if TYPE_CHECKING:
    from database.models.cari import Cari
    from database.models.satis_siparisi import SatisSiparisi


class SatisIrsaliyesi(Base):
    __tablename__ = "satis_irsaliyeleri"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    irsaliye_no: Mapped[str] = mapped_column(String(30), unique=True, nullable=False)
    irsaliye_tarihi: Mapped[date] = mapped_column(Date, nullable=False)
    cari_id: Mapped[int] = mapped_column(ForeignKey("cari_kartlar.id"), nullable=False, index=True)
    sube_id: Mapped[int | None] = mapped_column(ForeignKey("subeler.id"), nullable=True, index=True)
    siparis_id: Mapped[int | None] = mapped_column(ForeignKey("satis_siparisleri.id"), nullable=True, index=True)
    # Legacy "AÇIK" rows remain readable; new docs use TASLAK / SEVK EDİLDİ etc.
    durum: Mapped[str] = mapped_column(String(40), nullable=False, default="TASLAK")
    aciklama: Mapped[str | None] = mapped_column(Text, nullable=True)
    ayrintili_notlar: Mapped[str | None] = mapped_column(Text, nullable=True)
    olusturma_tarihi: Mapped[datetime] = mapped_column(DateTime, default=datetime.now, nullable=False)

    # Belge / depo / fiyatlandırma
    belge_turu: Mapped[str] = mapped_column(String(40), nullable=False, default="SATIS_IRSALIYESI")
    depo: Mapped[str] = mapped_column(String(100), nullable=False, default="ANA DEPO")
    is_priced: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    para_birimi: Mapped[str | None] = mapped_column(String(10), nullable=True, default="TRY")
    kur: Mapped[Decimal | None] = mapped_column(Numeric(18, 6), nullable=True, default=1)
    kur_tarihi: Mapped[date | None] = mapped_column(Date, nullable=True)

    # Sevk adresi / teslim
    sevk_adresi: Mapped[str | None] = mapped_column(String(500), nullable=True)
    sevk_il: Mapped[str | None] = mapped_column(String(80), nullable=True)
    sevk_ilce: Mapped[str | None] = mapped_column(String(80), nullable=True)
    teslim_kisi: Mapped[str | None] = mapped_column(String(120), nullable=True)
    teslim_telefon: Mapped[str | None] = mapped_column(String(40), nullable=True)

    # Lojistik
    sevkiyat_yontemi: Mapped[str | None] = mapped_column(String(80), nullable=True)
    nakliyeci: Mapped[str | None] = mapped_column(String(120), nullable=True)
    arac_plaka: Mapped[str | None] = mapped_column(String(40), nullable=True)
    sofor_adi: Mapped[str | None] = mapped_column(String(120), nullable=True)
    sofor_telefon: Mapped[str | None] = mapped_column(String(40), nullable=True)
    takip_no: Mapped[str | None] = mapped_column(String(80), nullable=True)
    paket_sayisi: Mapped[Decimal | None] = mapped_column(Numeric(18, 4), nullable=True)
    net_agirlik: Mapped[Decimal | None] = mapped_column(Numeric(18, 4), nullable=True)
    brut_agirlik: Mapped[Decimal | None] = mapped_column(Numeric(18, 4), nullable=True)

    # Tarihler
    planlanan_teslim: Mapped[date | None] = mapped_column(Date, nullable=True)
    fiili_sevk_tarihi: Mapped[date | None] = mapped_column(Date, nullable=True)
    fiili_sevk_saati: Mapped[time | None] = mapped_column(Time, nullable=True)
    fiili_teslim_tarihi: Mapped[date | None] = mapped_column(Date, nullable=True)

    # Müşteri anlık görüntü
    musteri_kodu_snap: Mapped[str | None] = mapped_column(String(50), nullable=True)
    musteri_unvan_snap: Mapped[str | None] = mapped_column(String(200), nullable=True)
    vergi_dairesi_snap: Mapped[str | None] = mapped_column(String(100), nullable=True)
    vergi_no_snap: Mapped[str | None] = mapped_column(String(40), nullable=True)

    # Notlar (iç not müşteri PDF'de yok)
    musteri_notu: Mapped[str | None] = mapped_column(Text, nullable=True)
    sevk_notu: Mapped[str | None] = mapped_column(Text, nullable=True)
    depo_notu: Mapped[str | None] = mapped_column(Text, nullable=True)
    ic_not: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Stok çıkışı — TASLAK'ta False; sevk_et sonrası True
    stok_cikis_yapildi: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    stock_posted_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    quote_id: Mapped[int | None] = mapped_column(Integer, nullable=True)

    # Kullanıcı damgaları
    created_by_user_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_by_username: Mapped[str | None] = mapped_column(String(80), nullable=True)
    created_by_full_name: Mapped[str | None] = mapped_column(String(120), nullable=True)
    updated_by_user_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    updated_by_username: Mapped[str | None] = mapped_column(String(80), nullable=True)
    updated_by_full_name: Mapped[str | None] = mapped_column(String(120), nullable=True)
    updated_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    shipped_by_user_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    shipped_by_username: Mapped[str | None] = mapped_column(String(80), nullable=True)
    shipped_by_full_name: Mapped[str | None] = mapped_column(String(120), nullable=True)
    cancelled_by_user_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    cancelled_by_full_name: Mapped[str | None] = mapped_column(String(120), nullable=True)
    cancellation_reason: Mapped[str | None] = mapped_column(String(500), nullable=True)
    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    approved_by_user_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    approved_by_full_name: Mapped[str | None] = mapped_column(String(120), nullable=True)
    approved_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    delivered_by_user_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    delivered_by_full_name: Mapped[str | None] = mapped_column(String(120), nullable=True)
    delivered_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    cari: Mapped["Cari"] = relationship("Cari")
    siparis: Mapped["SatisSiparisi | None"] = relationship("SatisSiparisi")
    satirlar: Mapped[list["SatisIrsaliyesiSatiri"]] = relationship(
        "SatisIrsaliyesiSatiri", back_populates="irsaliye", cascade="all, delete-orphan"
    )


class SatisIrsaliyesiSatiri(Base):
    __tablename__ = "satis_irsaliyesi_satirlari"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    irsaliye_id: Mapped[int] = mapped_column(ForeignKey("satis_irsaliyeleri.id"), nullable=False, index=True)
    siparis_satiri_id: Mapped[int | None] = mapped_column(
        ForeignKey("satis_siparisi_satirlari.id"), nullable=True, index=True
    )
    urun_kodu: Mapped[str] = mapped_column(String(50), nullable=False)
    urun_adi: Mapped[str] = mapped_column(String(200), nullable=False)
    aciklama: Mapped[str | None] = mapped_column(String(500), nullable=True)
    miktar: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False)
    birim: Mapped[str] = mapped_column(String(20), nullable=False)
    birim_fiyat: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False)
    iskonto_orani: Mapped[Decimal] = mapped_column(Numeric(7, 2), nullable=False, default=0)
    kdv_orani: Mapped[Decimal] = mapped_column(Numeric(7, 2), nullable=False, default=20)
    faturalanan_miktar: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False, default=0)
    fatura_belge_baglantisi: Mapped[str | None] = mapped_column(String(100), nullable=True)

    depo: Mapped[str | None] = mapped_column(String(100), nullable=True)
    lot_no: Mapped[str | None] = mapped_column(String(80), nullable=True)
    siparis_miktar: Mapped[Decimal | None] = mapped_column(Numeric(18, 4), nullable=True)
    onceki_sevk: Mapped[Decimal | None] = mapped_column(Numeric(18, 4), nullable=True)
    # faturalanacak_kalan = miktar - faturalanan_miktar (computed in service/UI)

    irsaliye: Mapped["SatisIrsaliyesi"] = relationship("SatisIrsaliyesi", back_populates="satirlar")
