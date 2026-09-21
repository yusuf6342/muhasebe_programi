"""InvoicePrintViewModel — baskı için salt okunur veri modeli."""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any


@dataclass
class InvoicePrintLine:
    sira: int
    urun_kodu: str
    urun_adi: str
    aciklama: str = ""
    miktar: Decimal = Decimal("0")
    miktar_goster: str = ""
    birim: str = ""
    birim_fiyat: Decimal = Decimal("0")
    birim_fiyat_goster: str = ""
    net_birim_fiyat: Decimal = Decimal("0")
    net_birim_fiyat_goster: str = ""
    iskonto_goster: str = ""
    iskonto_tutar: Decimal = Decimal("0")
    iskonto_tutar_goster: str = ""
    kdv_orani: Decimal = Decimal("0")
    kdv_goster: str = ""
    kdv_tutar: Decimal = Decimal("0")
    kdv_tutar_goster: str = ""
    net_tutar: Decimal = Decimal("0")
    net_goster: str = ""
    satir_toplam: Decimal = Decimal("0")
    satir_toplam_goster: str = ""
    barkod: str = ""
    lot: str = ""


@dataclass
class InvoicePrintKdvSatir:
    oran: Decimal
    matrah: Decimal
    kdv: Decimal
    matrah_goster: str = ""
    kdv_goster: str = ""


@dataclass
class InvoicePrintViewModel:
    fatura_id: int | None = None
    belge_turu: str = "SATIŞ FATURASI"
    sablon_id: str = "kurumsal"
    # Firma
    firma: dict[str, Any] = field(default_factory=dict)
    logo_yolu: str | None = None
    logo_data_uri: str | None = None
    # Müşteri
    musteri: dict[str, Any] = field(default_factory=dict)
    # Üst bilgiler
    fatura_no: str = ""
    fatura_tarihi: str = ""
    islem_saati: str = ""
    vade_tarihi: str = ""
    vade_gunu: str = ""
    siparis_no: str = ""
    irsaliye_no: str = ""
    depo: str = ""
    para_birimi: str = "TRY"
    kur: str = ""
    kur_tarihi: str = ""
    odeme_sekli: str = ""
    durum: str = "TASLAK"
    onaylandi: bool = False
    filigran: str | None = None  # TASLAK / İPTAL / DAHİLİ
    # Satırlar
    satirlar: list[InvoicePrintLine] = field(default_factory=list)
    # Toplamlar (merkezi servisten)
    brut_toplam: Decimal = Decimal("0")
    satir_iskonto: Decimal = Decimal("0")
    ara_toplam: Decimal = Decimal("0")
    kdv_toplam: Decimal = Decimal("0")
    genel_toplam: Decimal = Decimal("0")
    tahsil_edilen: Decimal = Decimal("0")
    kalan_bakiye: Decimal = Decimal("0")
    tl_karsilik: Decimal | None = None
    # Fatura geneli Brüt (KDV dahil, indirim/masraf öncesi)
    fatura_brut_toplam: Decimal = Decimal("0")
    fatura_brut_goster: str = ""
    # Fatura geneli İndirim/Masraf (baskıda % yok; tutar varsa satır)
    genel_islem_turu: str = ""
    genel_islem_tutari: Decimal = Decimal("0")
    genel_islem_etiket: str = ""
    genel_islem_goster: str = ""
    brut_goster: str = ""
    iskonto_goster: str = ""
    ara_goster: str = ""
    kdv_goster: str = ""
    genel_goster: str = ""
    tahsil_goster: str = ""
    kalan_goster: str = ""
    tl_goster: str = ""
    kdv_dokum: list[InvoicePrintKdvSatir] = field(default_factory=list)
    yaziyla_toplam: str = ""
    # Not / banka
    notlar: str = ""
    banka_satirlari: list[dict[str, str]] = field(default_factory=list)
    alt_bilgi: str = ""
    # İşlemi yapan (yalnızca ad soyad — ID/rol yazdırılmaz)
    hazirlayan: str = ""
    onaylayan: str = ""
    duzenleme_tarihi: str = ""
    kaynak_siparis_olusturan: str = ""
    satis_personeli: str = ""
    # Sayfalar
    sayfalar: list[list[InvoicePrintLine]] = field(default_factory=list)
    ayarlar: dict[str, Any] = field(default_factory=dict)
    uyari: str | None = None
