"""Fatura görseli / PDF / UBL içe aktarım — taslak ve eşleştirme modelleri."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from sqlalchemy import Boolean, DateTime, Integer, Numeric, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from database.database import Base


class InvoiceImportDraft(Base):
    __tablename__ = "invoice_import_drafts"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    yon: Mapped[str] = mapped_column(String(20), nullable=False)  # ALIS | SATIS
    durum: Mapped[str] = mapped_column(String(40), nullable=False, default="yuklendi", index=True)
    kaynak_turu: Mapped[str | None] = mapped_column(String(40), nullable=True)  # ubl_xml|pdf_text|pdf_scan|image|zip
    belge_no: Mapped[str | None] = mapped_column(String(80), nullable=True, index=True)
    ettn: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    belge_tarihi: Mapped[str | None] = mapped_column(String(20), nullable=True)
    senaryo: Mapped[str | None] = mapped_column(String(40), nullable=True)
    fatura_tipi: Mapped[str | None] = mapped_column(String(40), nullable=True)
    para_birimi: Mapped[str | None] = mapped_column(String(10), nullable=True)
    kur: Mapped[Decimal | None] = mapped_column(Numeric(18, 6), nullable=True)
    genel_toplam: Mapped[Decimal | None] = mapped_column(Numeric(18, 4), nullable=True)
    genel_guven: Mapped[Decimal | None] = mapped_column(Numeric(5, 2), nullable=True)
    satici_unvan: Mapped[str | None] = mapped_column(String(200), nullable=True)
    satici_vkn: Mapped[str | None] = mapped_column(String(20), nullable=True, index=True)
    alici_unvan: Mapped[str | None] = mapped_column(String(200), nullable=True)
    alici_vkn: Mapped[str | None] = mapped_column(String(20), nullable=True, index=True)
    cari_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    cari_eslesme_modu: Mapped[str | None] = mapped_column(String(40), nullable=True)
    # mevcut | yeni_taslak | beklet
    yeni_cari_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    extracted_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    uyari_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    hata_mesaji: Mapped[str | None] = mapped_column(Text, nullable=True)
    linked_invoice_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    linked_invoice_tur: Mapped[str | None] = mapped_column(String(20), nullable=True)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    created_by: Mapped[str | None] = mapped_column(String(120), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.now)
    updated_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    is_deleted: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)


class InvoiceImportFile(Base):
    __tablename__ = "invoice_import_files"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    draft_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    safe_name: Mapped[str] = mapped_column(String(260), nullable=False)
    mime: Mapped[str | None] = mapped_column(String(120), nullable=True)
    size: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    storage_relpath: Mapped[str] = mapped_column(String(500), nullable=False)
    sayfa_sayisi: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.now)


class InvoiceImportLine(Base):
    __tablename__ = "invoice_import_lines"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    draft_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    sira: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    aciklama: Mapped[str | None] = mapped_column(String(500), nullable=True)
    satici_urun_kodu: Mapped[str | None] = mapped_column(String(100), nullable=True)
    alici_urun_kodu: Mapped[str | None] = mapped_column(String(100), nullable=True)
    barkod: Mapped[str | None] = mapped_column(String(100), nullable=True)
    miktar: Mapped[Decimal | None] = mapped_column(Numeric(18, 4), nullable=True)
    birim: Mapped[str | None] = mapped_column(String(30), nullable=True)
    birim_fiyat: Mapped[Decimal | None] = mapped_column(Numeric(18, 6), nullable=True)
    iskonto_orani: Mapped[Decimal | None] = mapped_column(Numeric(8, 4), nullable=True)
    kdv_orani: Mapped[Decimal | None] = mapped_column(Numeric(8, 4), nullable=True)
    satir_toplam: Mapped[Decimal | None] = mapped_column(Numeric(18, 4), nullable=True)
    match_status: Mapped[str] = mapped_column(String(40), nullable=False, default="bekliyor")
    # eslesti | yeni_stok | hizmet | gider | haric | bekliyor
    stok_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    stok_kodu: Mapped[str | None] = mapped_column(String(50), nullable=True)
    birim_carpan: Mapped[Decimal | None] = mapped_column(Numeric(18, 6), nullable=True)
    guven: Mapped[Decimal | None] = mapped_column(Numeric(5, 2), nullable=True)
    raw_json: Mapped[str | None] = mapped_column(Text, nullable=True)


class PartyMatchRule(Base):
    __tablename__ = "party_match_rules"
    __table_args__ = (UniqueConstraint("vergi_no", name="uq_party_match_vkn"),)

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    vergi_no: Mapped[str] = mapped_column(String(20), nullable=False)
    cari_id: Mapped[int] = mapped_column(Integer, nullable=False)
    unvan_ornek: Mapped[str | None] = mapped_column(String(200), nullable=True)
    guven: Mapped[Decimal | None] = mapped_column(Numeric(5, 2), nullable=True)
    aktif: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.now)
    updated_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class ProductMatchRule(Base):
    __tablename__ = "product_match_rules"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    tedarikci_cari_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    satici_urun_kodu: Mapped[str | None] = mapped_column(String(100), nullable=True, index=True)
    barkod: Mapped[str | None] = mapped_column(String(100), nullable=True, index=True)
    normalize_ad: Mapped[str | None] = mapped_column(String(200), nullable=True)
    stok_id: Mapped[int] = mapped_column(Integer, nullable=False)
    birim_carpan: Mapped[Decimal] = mapped_column(Numeric(18, 6), nullable=False, default=1)
    guven: Mapped[Decimal | None] = mapped_column(Numeric(5, 2), nullable=True)
    kaynak: Mapped[str | None] = mapped_column(String(40), nullable=True)
    aktif: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.now)
    updated_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class InvoiceImportAudit(Base):
    __tablename__ = "invoice_import_audit"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    draft_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    kullanici: Mapped[str | None] = mapped_column(String(120), nullable=True)
    aksiyon: Mapped[str] = mapped_column(String(80), nullable=False)
    onceki_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    sonraki_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.now)
