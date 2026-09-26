"""Satış teklifi modelleri — stok/cari/muhasebe hareketi üretmez."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import TYPE_CHECKING

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

if TYPE_CHECKING:
    from database.models.cari import Cari
    from database.models.satis_siparisi import SatisSiparisi


class SatisTeklifi(Base):
    __tablename__ = "satis_teklifleri"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    teklif_no: Mapped[str] = mapped_column(String(40), unique=True, nullable=False, index=True)
    ana_teklif_id: Mapped[int | None] = mapped_column(
        ForeignKey("satis_teklifleri.id"), nullable=True, index=True
    )
    revizyon_no: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    teklif_tarihi: Mapped[date] = mapped_column(Date, nullable=False)
    gecerlilik_tarihi: Mapped[date] = mapped_column(Date, nullable=False)
    gecerlilik_gunu: Mapped[int] = mapped_column(Integer, nullable=False, default=30)
    cari_id: Mapped[int | None] = mapped_column(ForeignKey("cari_kartlar.id"), nullable=True, index=True)
    sube_id: Mapped[int | None] = mapped_column(ForeignKey("subeler.id"), nullable=True, index=True)
    aday_musteri_adi: Mapped[str | None] = mapped_column(String(200), nullable=True)
    musteri_yetkilisi: Mapped[str | None] = mapped_column(String(120), nullable=True)
    musteri_telefon: Mapped[str | None] = mapped_column(String(40), nullable=True)
    musteri_email: Mapped[str | None] = mapped_column(String(120), nullable=True)
    satis_temsilcisi: Mapped[str | None] = mapped_column(String(120), nullable=True)
    depo: Mapped[str] = mapped_column(String(100), nullable=False, default="ANA DEPO")
    proje: Mapped[str | None] = mapped_column(String(200), nullable=True)
    konu: Mapped[str | None] = mapped_column(String(300), nullable=True)
    referans_no: Mapped[str | None] = mapped_column(String(80), nullable=True)
    durum: Mapped[str] = mapped_column(String(40), nullable=False, default="TASLAK", index=True)
    para_birimi: Mapped[str] = mapped_column(String(3), nullable=False, default="TRY")
    kur: Mapped[Decimal] = mapped_column(Numeric(18, 6), nullable=False, default=1)
    kur_tarihi: Mapped[date | None] = mapped_column(Date, nullable=True)
    kur_turu: Mapped[str] = mapped_column(String(30), nullable=False, default="forex_selling")
    kur_sabitlendi: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    fiyat_listesi: Mapped[str | None] = mapped_column(String(80), nullable=True)
    odeme_sekli: Mapped[str | None] = mapped_column(String(200), nullable=True)
    odeme_taksit: Mapped[int | None] = mapped_column(Integer, nullable=True)
    odeme_vade_gun: Mapped[int | None] = mapped_column(Integer, nullable=True)
    odeme_vade_tarihi: Mapped[date | None] = mapped_column(Date, nullable=True)
    odeme_nakit_turu: Mapped[str | None] = mapped_column(String(20), nullable=True)
    odeme_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    teslim_suresi: Mapped[str | None] = mapped_column(String(120), nullable=True)
    teslimat_sekli: Mapped[str | None] = mapped_column(String(120), nullable=True)
    teslimat_adresi: Mapped[str | None] = mapped_column(String(500), nullable=True)
    tahmini_termin: Mapped[date | None] = mapped_column(Date, nullable=True)
    oncelik: Mapped[str] = mapped_column(String(20), nullable=False, default="Normal")
    kazanma_olasiligi: Mapped[Decimal | None] = mapped_column(Numeric(7, 2), nullable=True)
    takip_tarihi: Mapped[date | None] = mapped_column(Date, nullable=True)
    red_nedeni: Mapped[str | None] = mapped_column(String(80), nullable=True)
    red_aciklama: Mapped[str | None] = mapped_column(String(500), nullable=True)
    ic_not: Mapped[str | None] = mapped_column(Text, nullable=True)
    musteri_notu: Mapped[str | None] = mapped_column(Text, nullable=True)
    satis_takip_notu: Mapped[str | None] = mapped_column(Text, nullable=True)
    ticari_sartlar: Mapped[str | None] = mapped_column(Text, nullable=True)
    genel_iskonto_orani: Mapped[Decimal] = mapped_column(Numeric(7, 2), nullable=False, default=0)
    # Snapshot toplamlar (kayıt anı)
    brut_toplam: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False, default=0)
    iskonto_toplam: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False, default=0)
    ara_toplam: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False, default=0)
    kdv_toplam: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False, default=0)
    genel_toplam: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False, default=0)
    # Uzlaşılan Net farkı (fatura ile aynı: INDIRIM / MASRAF)
    genel_islem_turu: Mapped[str | None] = mapped_column(String(20), nullable=True)
    genel_islem_orani: Mapped[Decimal] = mapped_column(Numeric(12, 6), nullable=False, default=0)
    genel_islem_tutari: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False, default=0)
    toplam_maliyet: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False, default=0)
    brut_kar: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False, default=0)
    gercek_marj: Mapped[Decimal] = mapped_column(Numeric(7, 2), nullable=False, default=0)
    # Teklif fiyatlandırma (alış + kâr + masraf dağıtımı)
    cost_source: Mapped[str] = mapped_column(String(40), nullable=False, default="SON_ALIS")
    total_purchase_cost: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False, default=0)
    profit_rate: Mapped[Decimal] = mapped_column(Numeric(9, 4), nullable=False, default=0)
    percentage_profit_amount: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False, default=0)
    fixed_profit_amount: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False, default=0)
    customer_expense_amount: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False, default=0)
    internal_expense_amount: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False, default=0)
    total_target_profit: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False, default=0)
    calculated_offer_subtotal: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False, default=0)
    actual_profit_amount: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False, default=0)
    cost_markup_rate: Mapped[Decimal] = mapped_column(Numeric(9, 4), nullable=False, default=0)
    sales_margin_rate: Mapped[Decimal] = mapped_column(Numeric(9, 4), nullable=False, default=0)
    delivery_term_type: Mapped[str | None] = mapped_column(String(60), nullable=True)
    delivery_term_days: Mapped[int | None] = mapped_column(Integer, nullable=True)
    estimated_delivery_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    delivery_term_note: Mapped[str | None] = mapped_column(String(500), nullable=True)
    delivery_term_manual: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    calculation_method: Mapped[str] = mapped_column(
        String(40), nullable=False, default="MALIYET_USTU_KAR"
    )
    calculated_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    calculated_by_user_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    yuvarlama_yontemi: Mapped[str] = mapped_column(String(20), nullable=False, default="kurus")
    # Sipariş bağlantısı
    siparis_id: Mapped[int | None] = mapped_column(
        ForeignKey("satis_siparisleri.id"), nullable=True, index=True
    )
    siparis_no: Mapped[str | None] = mapped_column(String(40), nullable=True)
    aktif: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    # Kullanıcı damgaları
    olusturma_tarihi: Mapped[datetime] = mapped_column(DateTime, default=datetime.now, nullable=False)
    created_by_user_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_by_username: Mapped[str | None] = mapped_column(String(80), nullable=True)
    created_by_full_name: Mapped[str | None] = mapped_column(String(120), nullable=True)
    updated_by_user_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    updated_by_username: Mapped[str | None] = mapped_column(String(80), nullable=True)
    updated_by_full_name: Mapped[str | None] = mapped_column(String(120), nullable=True)
    updated_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    approved_by_user_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    approved_by_full_name: Mapped[str | None] = mapped_column(String(120), nullable=True)
    approved_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    cancelled_by_user_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    cancelled_by_full_name: Mapped[str | None] = mapped_column(String(120), nullable=True)
    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    cancellation_reason: Mapped[str | None] = mapped_column(String(500), nullable=True)
    # Takip log
    pdf_olusturma: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    musteriye_gonderildi_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    cari: Mapped["Cari | None"] = relationship("Cari")
    siparis: Mapped["SatisSiparisi | None"] = relationship("SatisSiparisi")
    satirlar: Mapped[list["SatisTeklifiSatiri"]] = relationship(
        "SatisTeklifiSatiri",
        back_populates="teklif",
        cascade="all, delete-orphan",
        order_by="SatisTeklifiSatiri.sira_no",
    )
    masraflar: Mapped[list["SatisTeklifiMasraf"]] = relationship(
        "SatisTeklifiMasraf",
        back_populates="teklif",
        cascade="all, delete-orphan",
        order_by="SatisTeklifiMasraf.id",
    )
    ana_teklif: Mapped["SatisTeklifi | None"] = relationship(
        "SatisTeklifi", remote_side=[id], foreign_keys=[ana_teklif_id]
    )


class SatisTeklifiSatiri(Base):
    __tablename__ = "satis_teklifi_satirlari"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    teklif_id: Mapped[int] = mapped_column(ForeignKey("satis_teklifleri.id"), nullable=False, index=True)
    sira_no: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    urun_kodu: Mapped[str] = mapped_column(String(50), nullable=False)
    urun_adi: Mapped[str] = mapped_column(String(200), nullable=False)
    aciklama: Mapped[str | None] = mapped_column(String(500), nullable=True)
    miktar: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False)
    birim: Mapped[str] = mapped_column(String(20), nullable=False, default="Adet")
    maliyet_kaynagi: Mapped[str | None] = mapped_column(String(50), nullable=True)
    birim_maliyet: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False, default=0)
    maliyet_hesap_zamani: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    fiyat_yontemi: Mapped[str | None] = mapped_column(String(60), nullable=True)
    liste_fiyati: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False, default=0)
    teklif_fiyati: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False, default=0)
    iskonto_orani: Mapped[Decimal] = mapped_column(Numeric(7, 2), nullable=False, default=0)
    iskonto_orani_2: Mapped[Decimal] = mapped_column(Numeric(7, 2), nullable=False, default=0)
    iskonto_orani_3: Mapped[Decimal] = mapped_column(Numeric(7, 2), nullable=False, default=0)
    kdv_orani: Mapped[Decimal] = mapped_column(Numeric(7, 2), nullable=False, default=20)
    net_birim_fiyat: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False, default=0)
    satir_toplam: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False, default=0)
    kar_orani: Mapped[Decimal] = mapped_column(Numeric(7, 2), nullable=False, default=0)
    gercek_marj: Mapped[Decimal] = mapped_column(Numeric(7, 2), nullable=False, default=0)
    # Alış / dağıtım anlık görüntüsü
    purchase_unit_price: Mapped[Decimal] = mapped_column(Numeric(18, 6), nullable=False, default=0)
    purchase_currency: Mapped[str] = mapped_column(String(3), nullable=False, default="TRY")
    purchase_exchange_rate: Mapped[Decimal] = mapped_column(Numeric(18, 6), nullable=False, default=1)
    purchase_unit_price_base: Mapped[Decimal] = mapped_column(Numeric(18, 6), nullable=False, default=0)
    purchase_total_cost: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False, default=0)
    cost_source_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    supplier_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    supplier_name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    allocated_expense: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False, default=0)
    allocated_percentage_profit: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False, default=0)
    allocated_fixed_profit: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False, default=0)
    calculated_offer_unit_price: Mapped[Decimal] = mapped_column(Numeric(18, 6), nullable=False, default=0)
    manual_offer_unit_price: Mapped[Decimal | None] = mapped_column(Numeric(18, 6), nullable=True)
    final_offer_unit_price: Mapped[Decimal] = mapped_column(Numeric(18, 6), nullable=False, default=0)
    is_manual_price: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    actual_profit_amount: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False, default=0)
    actual_margin_rate: Mapped[Decimal] = mapped_column(Numeric(9, 4), nullable=False, default=0)
    opsiyonel: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    toplama_dahil: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    kabul_edildi: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    teslim_suresi: Mapped[str | None] = mapped_column(String(80), nullable=True)
    marka: Mapped[str | None] = mapped_column(String(80), nullable=True)
    varyant: Mapped[str | None] = mapped_column(String(80), nullable=True)
    hizmet_satiri: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    # Manuel / stok dışı ürün (sahte product_id yok)
    is_manual_item: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    line_type: Mapped[str] = mapped_column(String(30), nullable=False, default="STOCK_PRODUCT")
    product_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    manual_product_name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    manual_description: Mapped[str | None] = mapped_column(String(500), nullable=True)
    manual_brand: Mapped[str | None] = mapped_column(String(100), nullable=True)
    manual_model: Mapped[str | None] = mapped_column(String(100), nullable=True)
    manual_manufacturer_code: Mapped[str | None] = mapped_column(String(100), nullable=True)
    manual_barcode: Mapped[str | None] = mapped_column(String(100), nullable=True)
    unit_name_snapshot: Mapped[str | None] = mapped_column(String(30), nullable=True)
    estimated_purchase_unit_price: Mapped[Decimal | None] = mapped_column(Numeric(18, 6), nullable=True)
    delivery_term_days: Mapped[int | None] = mapped_column(Integer, nullable=True)
    estimated_delivery_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    delivery_term_note: Mapped[str | None] = mapped_column(String(300), nullable=True)
    supplier_note: Mapped[str | None] = mapped_column(String(500), nullable=True)
    customer_note: Mapped[str | None] = mapped_column(String(500), nullable=True)
    internal_note: Mapped[str | None] = mapped_column(String(500), nullable=True)
    cost_status: Mapped[str] = mapped_column(String(20), nullable=False, default="OK")
    stock_conversion_status: Mapped[str | None] = mapped_column(String(40), nullable=True)
    converted_product_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    converted_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    converted_by_user_id: Mapped[int | None] = mapped_column(Integer, nullable=True)

    teklif: Mapped["SatisTeklifi"] = relationship("SatisTeklifi", back_populates="satirlar")


class SatisTeklifiMasraf(Base):
    """Teklif masraf detayı — müşteriye yansıtılan veya iç masraf."""

    __tablename__ = "satis_teklifi_masraflar"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    teklif_id: Mapped[int] = mapped_column(ForeignKey("satis_teklifleri.id"), nullable=False, index=True)
    expense_type: Mapped[str] = mapped_column(String(40), nullable=False, default="Diger")
    description: Mapped[str | None] = mapped_column(String(300), nullable=True)
    amount: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False, default=0)
    currency: Mapped[str] = mapped_column(String(3), nullable=False, default="TRY")
    exchange_rate: Mapped[Decimal] = mapped_column(Numeric(18, 6), nullable=False, default=1)
    base_amount: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False, default=0)
    is_customer_chargeable: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_by_user_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now, nullable=False)

    teklif: Mapped["SatisTeklifi"] = relationship("SatisTeklifi", back_populates="masraflar")
