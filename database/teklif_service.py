"""Teklif CRUD, durum akışı, revizyon, süre dolumu — stok/cari hareketi yok."""

from __future__ import annotations

import logging
from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Any

from sqlalchemy import or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import selectinload

from database.access import yazma_zorunlu
from database.database import get_session
from database.models.cari import Cari
from database.models.satis_teklifi import SatisTeklifi, SatisTeklifiMasraf, SatisTeklifiSatiri
from database.satis_siparisi_service import SatisSiparisiService
from database.teklif_pricing_service import QuotePricingService, _d, net_iskontolu
from database.user_audit import (
    OturumGerekli,
    audit_document,
    require_user_session,
    stamp_approve,
    stamp_cancel,
    stamp_create,
    stamp_update,
)

_LOG = logging.getLogger("teklif")

TEKLIF_DURUMLARI = (
    "TASLAK",
    "ONAY BEKLİYOR",
    "İÇ ONAYLI",
    "MÜŞTERİYE GÖNDERİLDİ",
    "GÖRÜŞÜLÜYOR",
    "REVİZE EDİLDİ",
    "KABUL EDİLDİ",
    "KISMEN KABUL",
    "REDDEDİLDİ",
    "SÜRESİ DOLDU",
    "SİPARİŞE DÖNÜŞTÜ",
    "İPTAL",
)

RED_NEDENLERI = (
    "Fiyat",
    "Termin",
    "Ürün",
    "Ödeme şartı",
    "Rakip",
    "Müşteri vazgeçti",
    "Diğer",
)

# Kaynak durum → izin verilen hedefler
DURUM_GECISLERI: dict[str, set[str]] = {
    "TASLAK": {"MÜŞTERİYE GÖNDERİLDİ", "KABUL EDİLDİ", "İPTAL"},
    "ONAY BEKLİYOR": {"İÇ ONAYLI", "TASLAK", "MÜŞTERİYE GÖNDERİLDİ", "KABUL EDİLDİ", "İPTAL"},
    "İÇ ONAYLI": {"MÜŞTERİYE GÖNDERİLDİ", "KABUL EDİLDİ", "TASLAK", "İPTAL"},
    "MÜŞTERİYE GÖNDERİLDİ": {"GÖRÜŞÜLÜYOR", "KABUL EDİLDİ", "KISMEN KABUL", "REDDEDİLDİ", "SÜRESİ DOLDU", "İPTAL"},
    "GÖRÜŞÜLÜYOR": {"KABUL EDİLDİ", "KISMEN KABUL", "REDDEDİLDİ", "REVİZE EDİLDİ", "SÜRESİ DOLDU", "İPTAL"},
    "REVİZE EDİLDİ": {"MÜŞTERİYE GÖNDERİLDİ", "KABUL EDİLDİ", "İPTAL"},
    "KABUL EDİLDİ": {"SİPARİŞE DÖNÜŞTÜ", "İPTAL"},
    "KISMEN KABUL": {"SİPARİŞE DÖNÜŞTÜ", "İPTAL"},
    "REDDEDİLDİ": {"REVİZE EDİLDİ", "İPTAL"},
    "SÜRESİ DOLDU": {"REVİZE EDİLDİ", "İPTAL"},  # uzatma = revizyon veya tarih güncelle
    "SİPARİŞE DÖNÜŞTÜ": set(),
    "İPTAL": set(),
}

KILITLI_DURUMLAR = frozenset({"KABUL EDİLDİ", "KISMEN KABUL", "SİPARİŞE DÖNÜŞTÜ", "İPTAL"})


class QuoteService:
    @staticmethod
    def schema_hazirla() -> None:
        from sqlalchemy import inspect, text

        from database.database import engine

        import database.models.cari  # noqa: F401
        import database.models.satis_siparisi  # noqa: F401
        import database.models.satis_teklifi  # noqa: F401

        if engine is None:
            return
        SatisTeklifi.__table__.create(engine, checkfirst=True)
        SatisTeklifiSatiri.__table__.create(engine, checkfirst=True)
        SatisTeklifiMasraf.__table__.create(engine, checkfirst=True)

        insp = inspect(engine)
        if insp.has_table("satis_teklifleri"):
            mevcut = {c["name"] for c in insp.get_columns("satis_teklifleri")}
            eklenecekler = {
                "cost_source": "VARCHAR(40) DEFAULT 'SON_ALIS' NOT NULL",
                "total_purchase_cost": "NUMERIC(18, 2) DEFAULT 0 NOT NULL",
                "profit_rate": "NUMERIC(9, 4) DEFAULT 0 NOT NULL",
                "percentage_profit_amount": "NUMERIC(18, 2) DEFAULT 0 NOT NULL",
                "fixed_profit_amount": "NUMERIC(18, 2) DEFAULT 0 NOT NULL",
                "customer_expense_amount": "NUMERIC(18, 2) DEFAULT 0 NOT NULL",
                "internal_expense_amount": "NUMERIC(18, 2) DEFAULT 0 NOT NULL",
                "total_target_profit": "NUMERIC(18, 2) DEFAULT 0 NOT NULL",
                "calculated_offer_subtotal": "NUMERIC(18, 2) DEFAULT 0 NOT NULL",
                "actual_profit_amount": "NUMERIC(18, 2) DEFAULT 0 NOT NULL",
                "cost_markup_rate": "NUMERIC(9, 4) DEFAULT 0 NOT NULL",
                "sales_margin_rate": "NUMERIC(9, 4) DEFAULT 0 NOT NULL",
                "delivery_term_type": "VARCHAR(60)",
                "delivery_term_days": "INTEGER",
                "estimated_delivery_date": "DATE",
                "delivery_term_note": "VARCHAR(500)",
                "delivery_term_manual": "BOOLEAN DEFAULT 0 NOT NULL",
                "calculation_method": "VARCHAR(40) DEFAULT 'MALIYET_USTU_KAR' NOT NULL",
                "calculated_at": "DATETIME",
                "calculated_by_user_id": "INTEGER",
                "yuvarlama_yontemi": "VARCHAR(20) DEFAULT 'kurus' NOT NULL",
                "tahmini_termin": "DATE",
                "genel_islem_turu": "VARCHAR(20)",
                "genel_islem_orani": "NUMERIC(12, 6) DEFAULT 0 NOT NULL",
                "genel_islem_tutari": "NUMERIC(18, 2) DEFAULT 0 NOT NULL",
                "odeme_taksit": "INTEGER",
                "odeme_vade_gun": "INTEGER",
                "odeme_vade_tarihi": "DATE",
                "odeme_nakit_turu": "VARCHAR(20)",
                "odeme_json": "TEXT",
            }
            eksikler = {a: t for a, t in eklenecekler.items() if a not in mevcut}
            if eksikler:
                with engine.begin() as connection:
                    for alan, tip in eksikler.items():
                        connection.execute(
                            text(f'ALTER TABLE "satis_teklifleri" ADD COLUMN "{alan}" {tip}')
                        )

        if insp.has_table("satis_teklifi_satirlari"):
            mevcut = {c["name"] for c in insp.get_columns("satis_teklifi_satirlari")}
            eklenecekler = {
                "purchase_unit_price": "NUMERIC(18, 6) DEFAULT 0 NOT NULL",
                "purchase_currency": "VARCHAR(3) DEFAULT 'TRY' NOT NULL",
                "purchase_exchange_rate": "NUMERIC(18, 6) DEFAULT 1 NOT NULL",
                "purchase_unit_price_base": "NUMERIC(18, 6) DEFAULT 0 NOT NULL",
                "purchase_total_cost": "NUMERIC(18, 2) DEFAULT 0 NOT NULL",
                "cost_source_date": "DATE",
                "supplier_id": "INTEGER",
                "supplier_name": "VARCHAR(200)",
                "allocated_expense": "NUMERIC(18, 4) DEFAULT 0 NOT NULL",
                "allocated_percentage_profit": "NUMERIC(18, 4) DEFAULT 0 NOT NULL",
                "allocated_fixed_profit": "NUMERIC(18, 4) DEFAULT 0 NOT NULL",
                "calculated_offer_unit_price": "NUMERIC(18, 6) DEFAULT 0 NOT NULL",
                "manual_offer_unit_price": "NUMERIC(18, 6)",
                "final_offer_unit_price": "NUMERIC(18, 6) DEFAULT 0 NOT NULL",
                "is_manual_price": "BOOLEAN DEFAULT 0 NOT NULL",
                "actual_profit_amount": "NUMERIC(18, 2) DEFAULT 0 NOT NULL",
                "actual_margin_rate": "NUMERIC(9, 4) DEFAULT 0 NOT NULL",
                "is_manual_item": "BOOLEAN DEFAULT 0 NOT NULL",
                "line_type": "VARCHAR(30) DEFAULT 'STOCK_PRODUCT' NOT NULL",
                "product_id": "INTEGER",
                "manual_product_name": "VARCHAR(200)",
                "manual_description": "VARCHAR(500)",
                "manual_brand": "VARCHAR(100)",
                "manual_model": "VARCHAR(100)",
                "manual_manufacturer_code": "VARCHAR(100)",
                "manual_barcode": "VARCHAR(100)",
                "unit_name_snapshot": "VARCHAR(30)",
                "estimated_purchase_unit_price": "NUMERIC(18, 6)",
                "delivery_term_days": "INTEGER",
                "estimated_delivery_date": "DATE",
                "delivery_term_note": "VARCHAR(300)",
                "supplier_note": "VARCHAR(500)",
                "customer_note": "VARCHAR(500)",
                "internal_note": "VARCHAR(500)",
                "cost_status": "VARCHAR(20) DEFAULT 'OK' NOT NULL",
                "stock_conversion_status": "VARCHAR(40)",
                "converted_product_id": "INTEGER",
                "converted_at": "DATETIME",
                "converted_by_user_id": "INTEGER",
            }
            eksikler = {a: t for a, t in eklenecekler.items() if a not in mevcut}
            if eksikler:
                with engine.begin() as connection:
                    for alan, tip in eksikler.items():
                        connection.execute(
                            text(
                                f'ALTER TABLE "satis_teklifi_satirlari" ADD COLUMN "{alan}" {tip}'
                            )
                        )

    @staticmethod
    def teklif_no() -> str:
        """Sonraki teklif no: TKF-00001, TKF-00002, …"""
        onek = "TKF-"
        with get_session() as session:
            numaralar = session.scalars(
                select(SatisTeklifi.teklif_no).where(SatisTeklifi.teklif_no.like(f"{onek}%"))
            ).all()
        max_sira = 0
        for no in numaralar:
            kuyruk = str(no)[len(onek) :]
            # R01 revizyon sonekini ayır (TKF-00001-R02)
            if "-R" in kuyruk:
                kuyruk = kuyruk.split("-R")[0]
            if kuyruk.isdigit():
                max_sira = max(max_sira, int(kuyruk))
        return f"{onek}{max_sira + 1:05d}"

    @staticmethod
    def gosterim_no(teklif: SatisTeklifi) -> str:
        if teklif.revizyon_no and teklif.revizyon_no > 0:
            ana = teklif.teklif_no
            if "-R" in ana:
                ana = ana.split("-R")[0]
            return f"{ana}-R{teklif.revizyon_no:02d}"
        return teklif.teklif_no

    @staticmethod
    def aktif_musterileri():
        return SatisSiparisiService.aktif_musterileri()

    @staticmethod
    def listele(
        *,
        durum: str | None = None,
        cari_id: int | None = None,
        sadece_aktif: bool = True,
        suresi_dolan: bool = False,
    ) -> list[dict[str, Any]]:
        QuoteService.schema_hazirla()
        QuoteService.expire_quotes()
        with get_session() as session:
            q = (
                select(SatisTeklifi)
                .options(selectinload(SatisTeklifi.cari), selectinload(SatisTeklifi.satirlar))
                .order_by(SatisTeklifi.id.desc())
            )
            if sadece_aktif:
                q = q.where(SatisTeklifi.aktif.is_(True))
            if durum:
                q = q.where(SatisTeklifi.durum == durum)
            if cari_id:
                q = q.where(SatisTeklifi.cari_id == int(cari_id))
            if suresi_dolan:
                q = q.where(SatisTeklifi.durum == "SÜRESİ DOLDU")
            sonuc = []
            for t in session.scalars(q).unique().all():
                sonuc.append(
                    {
                        "teklif": t,
                        "musteri": t.cari.unvan if t.cari else (t.aday_musteri_adi or ""),
                        "gosterim_no": QuoteService.gosterim_no(t),
                        "toplam": t.genel_toplam,
                        "marj": t.gercek_marj,
                    }
                )
            return sonuc

    @staticmethod
    def getir(teklif_id: int) -> SatisTeklifi | None:
        QuoteService.schema_hazirla()
        with get_session() as session:
            return session.scalar(
                select(SatisTeklifi)
                .options(
                    selectinload(SatisTeklifi.cari),
                    selectinload(SatisTeklifi.satirlar),
                    selectinload(SatisTeklifi.masraflar),
                    selectinload(SatisTeklifi.siparis),
                )
                .where(SatisTeklifi.id == int(teklif_id))
            )

    @staticmethod
    def _satirlari_yaz(teklif: SatisTeklifi, satir_verileri: list[dict]) -> None:
        teklif.satirlar.clear()
        for i, veri in enumerate(satir_verileri, start=1):
            miktar = _d(veri["miktar"], "Miktar", Decimal("0.0001"))
            fiyat = _d(veri.get("teklif_fiyati", 0), "Teklif fiyatı", Decimal("0"))
            i1 = _d(veri.get("iskonto_orani", 0))
            i2 = _d(veri.get("iskonto_orani_2", 0))
            i3 = _d(veri.get("iskonto_orani_3", 0))
            net = _d(veri.get("net_birim_fiyat") or 0)
            if net <= 0:
                net = net_iskontolu(fiyat, i1, i2, i3)
            kdv_o = _d(veri.get("kdv_orani", 20))
            ara = (net * miktar).quantize(Decimal("0.01"))
            toplam = ara + (ara * kdv_o / Decimal("100")).quantize(Decimal("0.01"))
            mal = _d(veri.get("birim_maliyet", veri.get("purchase_unit_price_base", 0)))
            purchase_base = _d(veri.get("purchase_unit_price_base", mal))
            purchase_unit = _d(veri.get("purchase_unit_price", purchase_base))
            purchase_total = _d(veri.get("purchase_total_cost") or 0)
            if purchase_total <= 0 and purchase_base > 0:
                purchase_total = (purchase_base * miktar).quantize(Decimal("0.01"))
            from database.teklif_pricing_service import kar_metrikleri

            oran, marj = kar_metrikleri(net, mal)
            final_unit = _d(veri.get("final_offer_unit_price") or fiyat)
            calc_unit = _d(veri.get("calculated_offer_unit_price") or final_unit)
            teklif.satirlar.append(
                SatisTeklifiSatiri(
                    sira_no=i,
                    urun_kodu=(veri.get("urun_kodu") or "").strip() or "OZEL",
                    urun_adi=(veri.get("urun_adi") or "").strip() or "Ürün",
                    aciklama=veri.get("aciklama") or None,
                    miktar=miktar,
                    birim=veri.get("birim") or "Adet",
                    maliyet_kaynagi=veri.get("maliyet_kaynagi"),
                    birim_maliyet=mal,
                    maliyet_hesap_zamani=veri.get("maliyet_hesap_zamani") or datetime.now(),
                    fiyat_yontemi=veri.get("fiyat_yontemi"),
                    liste_fiyati=_d(veri.get("liste_fiyati", 0)),
                    teklif_fiyati=fiyat,
                    iskonto_orani=i1,
                    iskonto_orani_2=i2,
                    iskonto_orani_3=i3,
                    kdv_orani=kdv_o,
                    net_birim_fiyat=net,
                    satir_toplam=toplam,
                    kar_orani=oran,
                    gercek_marj=marj,
                    purchase_unit_price=purchase_unit,
                    purchase_currency=(veri.get("purchase_currency") or "TRY"),
                    purchase_exchange_rate=_d(veri.get("purchase_exchange_rate", 1) or 1),
                    purchase_unit_price_base=purchase_base,
                    purchase_total_cost=purchase_total,
                    cost_source_date=veri.get("cost_source_date"),
                    supplier_id=int(veri["supplier_id"]) if veri.get("supplier_id") else None,
                    supplier_name=veri.get("supplier_name") or None,
                    allocated_expense=_d(veri.get("allocated_expense", 0)),
                    allocated_percentage_profit=_d(veri.get("allocated_percentage_profit", 0)),
                    allocated_fixed_profit=_d(veri.get("allocated_fixed_profit", 0)),
                    calculated_offer_unit_price=calc_unit,
                    manual_offer_unit_price=(
                        _d(veri["manual_offer_unit_price"])
                        if veri.get("manual_offer_unit_price") not in (None, "")
                        else None
                    ),
                    final_offer_unit_price=final_unit,
                    is_manual_price=bool(veri.get("is_manual_price", False)),
                    actual_profit_amount=_d(veri.get("actual_profit_amount", 0)),
                    actual_margin_rate=_d(veri.get("actual_margin_rate", 0)),
                    opsiyonel=bool(veri.get("opsiyonel", False)),
                    toplama_dahil=bool(veri.get("toplama_dahil", True)),
                    kabul_edildi=bool(veri.get("kabul_edildi", True)),
                    teslim_suresi=veri.get("teslim_suresi"),
                    marka=veri.get("marka"),
                    varyant=veri.get("varyant"),
                    hizmet_satiri=bool(veri.get("hizmet_satiri", False)),
                    is_manual_item=bool(veri.get("is_manual_item", veri.get("manuel", False))),
                    line_type=(
                        veri.get("line_type")
                        or (
                            "MANUAL_PRODUCT"
                            if veri.get("is_manual_item") or veri.get("manuel")
                            else "STOCK_PRODUCT"
                        )
                    ),
                    product_id=(
                        int(veri["product_id"])
                        if veri.get("product_id") not in (None, "")
                        else (
                            int(veri["stok_id"])
                            if veri.get("stok_id") not in (None, "")
                            else None
                        )
                    ),
                    manual_product_name=veri.get("manual_product_name") or (
                        (veri.get("urun_adi") or None)
                        if (veri.get("is_manual_item") or veri.get("manuel"))
                        else None
                    ),
                    manual_description=veri.get("manual_description") or veri.get("aciklama"),
                    manual_brand=veri.get("manual_brand") or veri.get("marka"),
                    manual_model=veri.get("manual_model") or veri.get("varyant"),
                    manual_manufacturer_code=veri.get("manual_manufacturer_code"),
                    manual_barcode=veri.get("manual_barcode"),
                    unit_name_snapshot=veri.get("unit_name_snapshot") or veri.get("birim"),
                    estimated_purchase_unit_price=(
                        _d(veri["estimated_purchase_unit_price"])
                        if veri.get("estimated_purchase_unit_price") not in (None, "")
                        else None
                    ),
                    delivery_term_days=(
                        int(veri["delivery_term_days"])
                        if veri.get("delivery_term_days") not in (None, "")
                        else None
                    ),
                    estimated_delivery_date=veri.get("estimated_delivery_date"),
                    delivery_term_note=veri.get("delivery_term_note"),
                    supplier_note=veri.get("supplier_note"),
                    customer_note=veri.get("customer_note"),
                    internal_note=veri.get("internal_note"),
                    cost_status=(veri.get("cost_status") or "OK"),
                    stock_conversion_status=veri.get("stock_conversion_status"),
                    converted_product_id=(
                        int(veri["converted_product_id"])
                        if veri.get("converted_product_id") not in (None, "")
                        else None
                    ),
                    converted_at=veri.get("converted_at"),
                    converted_by_user_id=(
                        int(veri["converted_by_user_id"])
                        if veri.get("converted_by_user_id") not in (None, "")
                        else None
                    ),
                )
            )

    @staticmethod
    def _masraflari_yaz(teklif: SatisTeklifi, masraflar: list[dict] | None) -> None:
        teklif.masraflar.clear()
        if not masraflar:
            return
        for veri in masraflar:
            tutar = _d(veri.get("amount", 0), "Masraf tutarı", Decimal("0"))
            kur = _d(veri.get("exchange_rate", 1) or 1)
            if kur <= 0:
                kur = Decimal("1")
            base = _d(veri.get("base_amount") or 0)
            if base <= 0:
                base = (tutar * kur).quantize(Decimal("0.01"))
            teklif.masraflar.append(
                SatisTeklifiMasraf(
                    expense_type=(veri.get("expense_type") or "Diğer").strip() or "Diğer",
                    description=(veri.get("description") or None),
                    amount=tutar,
                    currency=(veri.get("currency") or "TRY").upper(),
                    exchange_rate=kur,
                    base_amount=base,
                    is_customer_chargeable=bool(veri.get("is_customer_chargeable", True)),
                    created_by_user_id=veri.get("created_by_user_id"),
                )
            )

    @staticmethod
    def kaydet(
        veriler: dict[str, Any],
        satir_verileri: list[dict[str, Any]],
        teklif_id: int | None = None,
    ) -> SatisTeklifi:
        yazma_zorunlu("satis_duzenleme", "yeni_kayit")
        try:
            require_user_session()
        except OturumGerekli as exc:
            raise ValueError(str(exc)) from exc
        if not satir_verileri:
            raise ValueError("En az bir teklif satırı ekleyin.")
        tarih = veriler["teklif_tarihi"]
        gecerlilik = veriler["gecerlilik_tarihi"]
        if gecerlilik < tarih:
            raise ValueError("Geçerlilik tarihi teklif tarihinden önce olamaz.")
        cari_id = veriler.get("cari_id")
        aday = (veriler.get("aday_musteri_adi") or "").strip() or None
        if not cari_id and not aday:
            raise ValueError("Müşteri veya aday müşteri seçin.")

        QuoteService.schema_hazirla()
        with get_session() as session:
            yeni = False
            if teklif_id:
                teklif = session.get(SatisTeklifi, int(teklif_id))
                if not teklif:
                    raise ValueError("Teklif bulunamadı.")
                if teklif.durum in KILITLI_DURUMLAR and teklif.durum != "KISMEN KABUL":
                    raise ValueError(
                        f"{teklif.durum} durumundaki teklif düzenlenemez. Yeni revizyon oluşturun."
                    )
                if teklif.siparis_id:
                    raise ValueError("Siparişe dönüşmüş teklif düzenlenemez. Yeni revizyon oluşturun.")
                teklif.satirlar.clear()
            else:
                yeni = True
                teklif = SatisTeklifi(
                    teklif_no=(veriler.get("teklif_no") or "").strip() or QuoteService.teklif_no()
                )
                session.add(teklif)

            teklif.teklif_tarihi = tarih
            teklif.gecerlilik_tarihi = gecerlilik
            teklif.gecerlilik_gunu = int(veriler.get("gecerlilik_gunu") or (gecerlilik - tarih).days)
            teklif.cari_id = int(cari_id) if cari_id else None
            teklif.aday_musteri_adi = aday
            teklif.musteri_yetkilisi = veriler.get("musteri_yetkilisi") or None
            teklif.musteri_telefon = veriler.get("musteri_telefon") or None
            teklif.musteri_email = veriler.get("musteri_email") or None
            teklif.satis_temsilcisi = veriler.get("satis_temsilcisi") or None
            teklif.depo = veriler.get("depo") or "ANA DEPO"
            teklif.proje = veriler.get("proje") or None
            teklif.konu = veriler.get("konu") or None
            teklif.referans_no = veriler.get("referans_no") or None
            teklif.para_birimi = (veriler.get("para_birimi") or "TRY").upper()
            teklif.kur = _d(veriler.get("kur", 1), "Kur", Decimal("0.000001"))
            teklif.kur_tarihi = veriler.get("kur_tarihi")
            teklif.kur_turu = veriler.get("kur_turu") or "effective_selling"
            teklif.kur_sabitlendi = bool(veriler.get("kur_sabitlendi", False))
            teklif.fiyat_listesi = veriler.get("fiyat_listesi") or None
            teklif.odeme_sekli = veriler.get("odeme_sekli") or None
            teklif.odeme_taksit = (
                int(veriler["odeme_taksit"])
                if veriler.get("odeme_taksit") not in (None, "")
                else None
            )
            teklif.odeme_vade_gun = (
                int(veriler["odeme_vade_gun"])
                if veriler.get("odeme_vade_gun") not in (None, "")
                else None
            )
            teklif.odeme_vade_tarihi = veriler.get("odeme_vade_tarihi")
            teklif.odeme_nakit_turu = veriler.get("odeme_nakit_turu") or None
            teklif.odeme_json = veriler.get("odeme_json") or None
            teklif.teslim_suresi = veriler.get("teslim_suresi") or None
            teklif.teslimat_sekli = veriler.get("teslimat_sekli") or None
            teklif.teslimat_adresi = veriler.get("teslimat_adresi") or None
            teklif.tahmini_termin = veriler.get("tahmini_termin")
            teklif.oncelik = veriler.get("oncelik") or "Normal"
            teklif.kazanma_olasiligi = (
                _d(veriler["kazanma_olasiligi"]) if veriler.get("kazanma_olasiligi") not in (None, "") else None
            )
            teklif.takip_tarihi = veriler.get("takip_tarihi")
            teklif.ic_not = veriler.get("ic_not") or None
            teklif.musteri_notu = veriler.get("musteri_notu") or None
            teklif.satis_takip_notu = veriler.get("satis_takip_notu") or None
            teklif.ticari_sartlar = veriler.get("ticari_sartlar") or None
            teklif.genel_iskonto_orani = _d(veriler.get("genel_iskonto_orani", 0))
            # Fiyatlandırma / termin başlık alanları
            teklif.cost_source = (veriler.get("cost_source") or "SON_ALIS").upper()
            teklif.profit_rate = _d(veriler.get("profit_rate", 0))
            teklif.fixed_profit_amount = _d(veriler.get("fixed_profit_amount", 0))
            teklif.customer_expense_amount = _d(veriler.get("customer_expense_amount", 0))
            teklif.internal_expense_amount = _d(veriler.get("internal_expense_amount", 0))
            teklif.total_purchase_cost = _d(veriler.get("total_purchase_cost", 0))
            teklif.percentage_profit_amount = _d(veriler.get("percentage_profit_amount", 0))
            teklif.total_target_profit = _d(veriler.get("total_target_profit", 0))
            teklif.calculated_offer_subtotal = _d(veriler.get("calculated_offer_subtotal", 0))
            teklif.actual_profit_amount = _d(veriler.get("actual_profit_amount", 0))
            teklif.cost_markup_rate = _d(veriler.get("cost_markup_rate", 0))
            teklif.sales_margin_rate = _d(veriler.get("sales_margin_rate", 0))
            teklif.delivery_term_type = veriler.get("delivery_term_type") or None
            teklif.delivery_term_days = (
                int(veriler["delivery_term_days"])
                if veriler.get("delivery_term_days") not in (None, "")
                else None
            )
            teklif.estimated_delivery_date = veriler.get("estimated_delivery_date")
            if teklif.estimated_delivery_date is None and veriler.get("tahmini_termin"):
                teklif.estimated_delivery_date = veriler.get("tahmini_termin")
            teklif.delivery_term_note = veriler.get("delivery_term_note") or None
            teklif.delivery_term_manual = bool(veriler.get("delivery_term_manual", False))
            teklif.calculation_method = veriler.get("calculation_method") or "MALIYET_USTU_KAR"
            teklif.calculated_at = veriler.get("calculated_at")
            teklif.calculated_by_user_id = veriler.get("calculated_by_user_id")
            teklif.yuvarlama_yontemi = veriler.get("yuvarlama_yontemi") or "kurus"
            if yeni:
                teklif.durum = veriler.get("durum") or "TASLAK"
            elif veriler.get("durum") and veriler["durum"] != teklif.durum:
                QuoteService._durum_gecis_kontrol(teklif.durum, veriler["durum"])
                teklif.durum = veriler["durum"]

            QuoteService._satirlari_yaz(teklif, satir_verileri)
            QuoteService._masraflari_yaz(teklif, veriler.get("masraflar"))
            tot = QuotePricingService.satir_toplamlari(list(teklif.satirlar))
            teklif.brut_toplam = tot["brut_toplam"]
            teklif.iskonto_toplam = tot["iskonto_toplam"]
            teklif.ara_toplam = tot["ara_toplam"]
            teklif.kdv_toplam = tot["kdv_toplam"]
            # Net = Uzlaşılan (verilirse); aksi halde satır genel toplamı
            if veriler.get("genel_toplam") is not None and veriler.get("genel_toplam") != "":
                teklif.genel_toplam = _d(veriler["genel_toplam"])
            else:
                teklif.genel_toplam = tot["genel_toplam"]
            teklif.genel_islem_turu = (str(veriler.get("genel_islem_turu") or "").strip() or None)
            teklif.genel_islem_orani = _d(veriler.get("genel_islem_orani", 0))
            teklif.genel_islem_tutari = _d(veriler.get("genel_islem_tutari", 0))
            teklif.toplam_maliyet = tot["toplam_maliyet"]
            teklif.brut_kar = tot["brut_kar"]
            teklif.gercek_marj = tot["gercek_marj"]
            if not veriler.get("total_purchase_cost"):
                teklif.total_purchase_cost = tot["toplam_maliyet"]
            if not veriler.get("actual_profit_amount"):
                teklif.actual_profit_amount = tot["brut_kar"]
            if not veriler.get("sales_margin_rate"):
                teklif.sales_margin_rate = tot["gercek_marj"]
            if not veriler.get("cost_markup_rate"):
                teklif.cost_markup_rate = tot["maliyet_ustu_oran"]
            if not veriler.get("calculated_offer_subtotal"):
                teklif.calculated_offer_subtotal = tot["ara_toplam"]

            if yeni:
                stamp_create(teklif)
            else:
                stamp_update(teklif)
            try:
                session.flush()
            except IntegrityError as hata:
                raise ValueError("Teklif kaydedilemedi.") from hata
            tid = int(teklif.id)
            tno = teklif.teklif_no

        audit_document(
            "TEKLIF_OLUSTUR" if yeni else "TEKLIF_DUZENLE",
            modul="satis_teklif",
            kayit_id=str(tid),
            belge_no=tno,
        )
        return QuoteService.getir(tid)

    @staticmethod
    def _durum_gecis_kontrol(eski: str, yeni: str) -> None:
        izinli = DURUM_GECISLERI.get(eski, set())
        if yeni not in izinli and yeni != eski:
            raise ValueError(f"Durum geçişi geçersiz: {eski} → {yeni}")

    @staticmethod
    def durum_degistir(teklif_id: int, yeni_durum: str, *, gerekce: str | None = None) -> SatisTeklifi:
        yazma_zorunlu("satis_duzenleme")
        try:
            require_user_session()
        except OturumGerekli as exc:
            raise ValueError(str(exc)) from exc
        yeni_durum = (yeni_durum or "").strip().upper()
        # normalize Turkish statuses as defined
        for d in TEKLIF_DURUMLARI:
            if d.casefold() == yeni_durum.casefold() or d.upper() == yeni_durum:
                yeni_durum = d
                break
        with get_session() as session:
            teklif = session.get(SatisTeklifi, int(teklif_id))
            if not teklif:
                raise ValueError("Teklif bulunamadı.")
            QuoteService._durum_gecis_kontrol(teklif.durum, yeni_durum)
            eski = teklif.durum
            teklif.durum = yeni_durum
            if yeni_durum == "İÇ ONAYLI":
                stamp_approve(teklif)
            if yeni_durum == "MÜŞTERİYE GÖNDERİLDİ":
                teklif.musteriye_gonderildi_at = datetime.now()
            if yeni_durum in ("REDDEDİLDİ", "İPTAL"):
                stamp_cancel(teklif, gerekce or yeni_durum)
                if yeni_durum == "REDDEDİLDİ":
                    teklif.red_nedeni = gerekce
            stamp_update(teklif)
            session.flush()
            tid = int(teklif.id)
            tno = teklif.teklif_no
        audit_document(
            "TEKLIF_DURUM",
            modul="satis_teklif",
            kayit_id=str(tid),
            belge_no=tno,
            eski={"durum": eski},
            yeni={"durum": yeni_durum, "gerekce": gerekce},
        )
        return QuoteService.getir(tid)

    @staticmethod
    def expire_quotes() -> int:
        """Geçerlilik tarihi geçen açık teklifleri SÜRESİ DOLDU yapar."""
        bugun = date.today()
        acik = {
            "TASLAK",
            "ONAY BEKLİYOR",
            "İÇ ONAYLI",
            "MÜŞTERİYE GÖNDERİLDİ",
            "GÖRÜŞÜLÜYOR",
            "REVİZE EDİLDİ",
        }
        say = 0
        try:
            with get_session() as session:
                if not session.bind:
                    return 0
                from sqlalchemy import inspect as sa_inspect

                if not sa_inspect(session.bind).has_table("satis_teklifleri"):
                    return 0
                for t in session.scalars(
                    select(SatisTeklifi).where(
                        SatisTeklifi.durum.in_(acik),
                        SatisTeklifi.gecerlilik_tarihi < bugun,
                        SatisTeklifi.aktif.is_(True),
                    )
                ).all():
                    t.durum = "SÜRESİ DOLDU"
                    say += 1
                if say:
                    session.flush()
        except Exception as exc:
            _LOG.warning("expire_quotes: %s", exc)
        return say

    @staticmethod
    def gecerlilik_uzat(teklif_id: int, yeni_tarih: date) -> SatisTeklifi:
        yazma_zorunlu("satis_duzenleme")
        with get_session() as session:
            teklif = session.get(SatisTeklifi, int(teklif_id))
            if not teklif:
                raise ValueError("Teklif bulunamadı.")
            if yeni_tarih < teklif.teklif_tarihi:
                raise ValueError("Geçerlilik teklif tarihinden önce olamaz.")
            teklif.gecerlilik_tarihi = yeni_tarih
            teklif.gecerlilik_gunu = (yeni_tarih - teklif.teklif_tarihi).days
            if teklif.durum == "SÜRESİ DOLDU":
                teklif.durum = "GÖRÜŞÜLÜYOR"
            stamp_update(teklif)
            session.flush()
            tid = int(teklif.id)
        return QuoteService.getir(tid)

    @staticmethod
    def create_revision(teklif_id: int, *, sebep: str | None = None) -> SatisTeklifi:
        """Önceki sürümü değiştirmeden kopya revizyon oluşturur."""
        yazma_zorunlu("satis_duzenleme", "yeni_kayit")
        try:
            require_user_session()
        except OturumGerekli as exc:
            raise ValueError(str(exc)) from exc
        kaynak = QuoteService.getir(int(teklif_id))
        if not kaynak:
            raise ValueError("Teklif bulunamadı.")
        ana_id = kaynak.ana_teklif_id or kaynak.id
        with get_session() as session:
            max_rev = session.scalar(
                select(SatisTeklifi.revizyon_no)
                .where(or_(SatisTeklifi.id == ana_id, SatisTeklifi.ana_teklif_id == ana_id))
                .order_by(SatisTeklifi.revizyon_no.desc())
                .limit(1)
            ) or 0
            yeni_rev = int(max_rev) + 1
            ana_no = kaynak.teklif_no.split("-R")[0]
            # Eski kabul edilmiş kardeşleri kilitle — yeni revizyon açık
            for kardes in session.scalars(
                select(SatisTeklifi).where(
                    or_(SatisTeklifi.id == ana_id, SatisTeklifi.ana_teklif_id == ana_id),
                    SatisTeklifi.durum.in_(("KABUL EDİLDİ", "KISMEN KABUL")),
                )
            ).all():
                if kardes.siparis_id:
                    continue
                # Kabul edilmiş ama sipariş yoksa revizyon için REVİZE EDİLDİ işaretle
                kardes.durum = "REVİZE EDİLDİ"

            teklif = SatisTeklifi(
                teklif_no=f"{ana_no}-R{yeni_rev:02d}",
                ana_teklif_id=ana_id,
                revizyon_no=yeni_rev,
                teklif_tarihi=date.today(),
                gecerlilik_tarihi=date.today() + timedelta(days=kaynak.gecerlilik_gunu or 30),
                gecerlilik_gunu=kaynak.gecerlilik_gunu or 30,
                cari_id=kaynak.cari_id,
                aday_musteri_adi=kaynak.aday_musteri_adi,
                musteri_yetkilisi=kaynak.musteri_yetkilisi,
                musteri_telefon=kaynak.musteri_telefon,
                musteri_email=kaynak.musteri_email,
                satis_temsilcisi=kaynak.satis_temsilcisi,
                depo=kaynak.depo,
                proje=kaynak.proje,
                konu=kaynak.konu,
                referans_no=kaynak.referans_no,
                durum="TASLAK",
                para_birimi=kaynak.para_birimi,
                kur=kaynak.kur,
                kur_tarihi=kaynak.kur_tarihi,
                kur_turu=kaynak.kur_turu,
                kur_sabitlendi=kaynak.kur_sabitlendi,
                fiyat_listesi=kaynak.fiyat_listesi,
                odeme_sekli=kaynak.odeme_sekli,
                odeme_taksit=getattr(kaynak, "odeme_taksit", None),
                odeme_vade_gun=getattr(kaynak, "odeme_vade_gun", None),
                odeme_vade_tarihi=getattr(kaynak, "odeme_vade_tarihi", None),
                odeme_nakit_turu=getattr(kaynak, "odeme_nakit_turu", None),
                odeme_json=getattr(kaynak, "odeme_json", None),
                teslim_suresi=kaynak.teslim_suresi,
                teslimat_sekli=kaynak.teslimat_sekli,
                teslimat_adresi=kaynak.teslimat_adresi,
                tahmini_termin=kaynak.estimated_delivery_date or kaynak.tahmini_termin,
                oncelik=kaynak.oncelik,
                kazanma_olasiligi=kaynak.kazanma_olasiligi,
                takip_tarihi=kaynak.takip_tarihi,
                ic_not=((kaynak.ic_not or "") + (f"\nRevizyon: {sebep}" if sebep else "")).strip() or None,
                musteri_notu=kaynak.musteri_notu,
                satis_takip_notu=kaynak.satis_takip_notu,
                ticari_sartlar=kaynak.ticari_sartlar,
                genel_iskonto_orani=kaynak.genel_iskonto_orani,
                cost_source=getattr(kaynak, "cost_source", None) or "SON_ALIS",
                total_purchase_cost=getattr(kaynak, "total_purchase_cost", None) or 0,
                profit_rate=getattr(kaynak, "profit_rate", None) or 0,
                percentage_profit_amount=getattr(kaynak, "percentage_profit_amount", None) or 0,
                fixed_profit_amount=getattr(kaynak, "fixed_profit_amount", None) or 0,
                customer_expense_amount=getattr(kaynak, "customer_expense_amount", None) or 0,
                internal_expense_amount=getattr(kaynak, "internal_expense_amount", None) or 0,
                total_target_profit=getattr(kaynak, "total_target_profit", None) or 0,
                calculated_offer_subtotal=getattr(kaynak, "calculated_offer_subtotal", None) or 0,
                actual_profit_amount=getattr(kaynak, "actual_profit_amount", None) or 0,
                cost_markup_rate=getattr(kaynak, "cost_markup_rate", None) or 0,
                sales_margin_rate=getattr(kaynak, "sales_margin_rate", None) or 0,
                delivery_term_type=getattr(kaynak, "delivery_term_type", None),
                delivery_term_days=getattr(kaynak, "delivery_term_days", None),
                estimated_delivery_date=getattr(kaynak, "estimated_delivery_date", None),
                delivery_term_note=getattr(kaynak, "delivery_term_note", None),
                delivery_term_manual=bool(getattr(kaynak, "delivery_term_manual", False)),
                calculation_method=getattr(kaynak, "calculation_method", None) or "MALIYET_USTU_KAR",
                yuvarlama_yontemi=getattr(kaynak, "yuvarlama_yontemi", None) or "kurus",
            )
            session.add(teklif)
            for s in kaynak.satirlar:
                teklif.satirlar.append(
                    SatisTeklifiSatiri(
                        sira_no=s.sira_no,
                        urun_kodu=s.urun_kodu,
                        urun_adi=s.urun_adi,
                        aciklama=s.aciklama,
                        miktar=s.miktar,
                        birim=s.birim,
                        maliyet_kaynagi=s.maliyet_kaynagi,
                        birim_maliyet=s.birim_maliyet,
                        maliyet_hesap_zamani=s.maliyet_hesap_zamani,
                        fiyat_yontemi=s.fiyat_yontemi,
                        liste_fiyati=s.liste_fiyati,
                        teklif_fiyati=s.teklif_fiyati,
                        iskonto_orani=s.iskonto_orani,
                        iskonto_orani_2=s.iskonto_orani_2,
                        iskonto_orani_3=s.iskonto_orani_3,
                        kdv_orani=s.kdv_orani,
                        net_birim_fiyat=s.net_birim_fiyat,
                        satir_toplam=s.satir_toplam,
                        kar_orani=s.kar_orani,
                        gercek_marj=s.gercek_marj,
                        purchase_unit_price=getattr(s, "purchase_unit_price", None) or 0,
                        purchase_currency=getattr(s, "purchase_currency", None) or "TRY",
                        purchase_exchange_rate=getattr(s, "purchase_exchange_rate", None) or 1,
                        purchase_unit_price_base=getattr(s, "purchase_unit_price_base", None) or 0,
                        purchase_total_cost=getattr(s, "purchase_total_cost", None) or 0,
                        cost_source_date=getattr(s, "cost_source_date", None),
                        supplier_id=getattr(s, "supplier_id", None),
                        supplier_name=getattr(s, "supplier_name", None),
                        allocated_expense=getattr(s, "allocated_expense", None) or 0,
                        allocated_percentage_profit=getattr(s, "allocated_percentage_profit", None) or 0,
                        allocated_fixed_profit=getattr(s, "allocated_fixed_profit", None) or 0,
                        calculated_offer_unit_price=getattr(s, "calculated_offer_unit_price", None) or 0,
                        manual_offer_unit_price=getattr(s, "manual_offer_unit_price", None),
                        final_offer_unit_price=getattr(s, "final_offer_unit_price", None) or s.teklif_fiyati,
                        is_manual_price=bool(getattr(s, "is_manual_price", False)),
                        actual_profit_amount=getattr(s, "actual_profit_amount", None) or 0,
                        actual_margin_rate=getattr(s, "actual_margin_rate", None) or 0,
                        opsiyonel=s.opsiyonel,
                        toplama_dahil=s.toplama_dahil,
                        kabul_edildi=s.kabul_edildi,
                        teslim_suresi=s.teslim_suresi,
                        marka=s.marka,
                        varyant=s.varyant,
                        hizmet_satiri=s.hizmet_satiri,
                    )
                )
            for m in getattr(kaynak, "masraflar", None) or []:
                teklif.masraflar.append(
                    SatisTeklifiMasraf(
                        expense_type=m.expense_type,
                        description=m.description,
                        amount=m.amount,
                        currency=m.currency,
                        exchange_rate=m.exchange_rate,
                        base_amount=m.base_amount,
                        is_customer_chargeable=m.is_customer_chargeable,
                        created_by_user_id=m.created_by_user_id,
                    )
                )
            tot = QuotePricingService.satir_toplamlari(list(teklif.satirlar))
            teklif.brut_toplam = tot["brut_toplam"]
            teklif.iskonto_toplam = tot["iskonto_toplam"]
            teklif.ara_toplam = tot["ara_toplam"]
            teklif.kdv_toplam = tot["kdv_toplam"]
            teklif.genel_toplam = tot["genel_toplam"]
            teklif.toplam_maliyet = tot["toplam_maliyet"]
            teklif.brut_kar = tot["brut_kar"]
            teklif.gercek_marj = tot["gercek_marj"]
            stamp_create(teklif)
            session.flush()
            tid = int(teklif.id)
            tno = teklif.teklif_no
        audit_document(
            "TEKLIF_REVIZYON",
            modul="satis_teklif",
            kayit_id=str(tid),
            belge_no=tno,
            yeni={"kaynak_id": teklif_id, "sebep": sebep},
        )
        return QuoteService.getir(tid)

    @staticmethod
    def pasife_al(teklif_id: int, *, gerekce: str | None = None) -> None:
        yazma_zorunlu("satis_duzenleme", "iptal")
        with get_session() as session:
            teklif = session.get(SatisTeklifi, int(teklif_id))
            if not teklif:
                raise ValueError("Teklif bulunamadı.")
            if teklif.siparis_id:
                raise ValueError("Siparişe dönüşmüş teklif silinemez / pasife alınamaz.")
            teklif.aktif = False
            stamp_cancel(teklif, gerekce or "Pasife alındı")
            session.flush()

    @staticmethod
    def karsilastir(eski_id: int, yeni_id: int) -> dict[str, Any]:
        a = QuoteService.getir(eski_id)
        b = QuoteService.getir(yeni_id)
        if not a or not b:
            raise ValueError("Karşılaştırma için iki teklif gerekli.")
        a_map = {s.urun_kodu: s for s in a.satirlar}
        b_map = {s.urun_kodu: s for s in b.satirlar}
        eklenen = [kod for kod in b_map if kod not in a_map]
        silinen = [kod for kod in a_map if kod not in b_map]
        degisen = []
        for kod in set(a_map) & set(b_map):
            sa, sb = a_map[kod], b_map[kod]
            if (
                sa.miktar != sb.miktar
                or sa.teklif_fiyati != sb.teklif_fiyati
                or sa.iskonto_orani != sb.iskonto_orani
            ):
                degisen.append(
                    {
                        "urun_kodu": kod,
                        "eski_miktar": sa.miktar,
                        "yeni_miktar": sb.miktar,
                        "eski_fiyat": sa.teklif_fiyati,
                        "yeni_fiyat": sb.teklif_fiyati,
                    }
                )
        return {
            "eklenen": eklenen,
            "silinen": silinen,
            "degisen": degisen,
            "eski_toplam": a.genel_toplam,
            "yeni_toplam": b.genel_toplam,
            "eski_sart": a.ticari_sartlar,
            "yeni_sart": b.ticari_sartlar,
        }
