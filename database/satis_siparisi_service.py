from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import selectinload
from sqlalchemy.exc import IntegrityError

from database.cari_service import CariService
from database.database import get_session
from database.access import yazma_zorunlu
from database.models.cari import Cari
from database.models.satis_siparisi import (
    SatisSiparisi,
    SatisSiparisiSatiri,
    SatisSiparisiTahsilati,
)

MALIYET_YONTEMLERI = (
    "FIFO",
    "SON ALIŞ FİYATI",
    "ORTALAMA ALIŞ FİYATI",
    "AĞIRLIKLI ORTALAMA ALIŞ FİYATI",
)
SIPARIS_DURUMLARI = (
    "TASLAK",
    "AÇIK",
    "KISMİ İRSALİYELİ",
    "İRSALİYELİ",
    "KISMİ FATURALI",
    "FATURALI",
    "İPTAL",
)
ODEME_SEKILLERI = ("NAKİT / KASA", "GELEN HAVALE", "KREDİ KARTIYLA TAHSİLAT")

# Fatura dönüşüm kaynağı (tek kural):
# - Doğrudan siparişten: fatura kalanı = sipariş miktarı − faturalanan_miktar (sevk zorunlu değil).
# - İrsaliyeden: fatura kalanı = irsaliye satır miktarı − faturalanan_miktar; bağlı sipariş
#   satırının faturalanan_miktar'ı da aynı tutarla artar.
# Sevk kalanı her zaman sipariş miktarı − irsaliyelenen_miktar; fatura kalanından bağımsızdır.
FATURA_KAYNAK_KURALI = "SIPARIS_VEYA_IRSALIYE_BAGIMSIZ"


def bos_metin(deger: object) -> str:
    """None / 'None' / boş → boş string (UI ve kayıt tutarlılığı)."""
    if deger is None:
        return ""
    metin = str(deger).strip()
    if not metin or metin.lower() in ("none", "null"):
        return ""
    return metin


def satir_kalanlari(miktar, irsaliyelenen=0, faturalanan=0) -> dict[str, Decimal]:
    """Satır bazında sevk ve fatura kalanları (FATURA_KAYNAK_KURALI)."""
    m = decimal(miktar or 0, "Miktar", Decimal("0"))
    sevk = decimal(irsaliyelenen or 0, "Sevk", Decimal("0"))
    fat = decimal(faturalanan or 0, "Fatura", Decimal("0"))
    return {
        "sevk_kalani": m - sevk,
        "fatura_kalani": m - fat,
    }


def decimal(deger: object, alan: str, minimum: Decimal | None = None) -> Decimal:
    try:
        if isinstance(deger, Decimal):
            sonuc = deger
        else:
            metin = str(deger).strip()
            if "," in metin:
                metin = metin.replace(".", "").replace(",", ".")
            sonuc = Decimal(metin)
    except (InvalidOperation, ValueError):
        raise ValueError(f"{alan} geçerli bir sayı olmalıdır.") from None
    if minimum is not None and sonuc < minimum:
        raise ValueError(f"{alan} {minimum} değerinden küçük olamaz.")
    return sonuc


class SatisSiparisiService:
    @staticmethod
    def durumu_guncelle(session, siparis_id: int | None) -> None:
        if not siparis_id:
            return
        siparis = session.scalar(
            select(SatisSiparisi)
            .options(selectinload(SatisSiparisi.satirlar))
            .where(SatisSiparisi.id == siparis_id)
        )
        if siparis is None or siparis.durum == "İPTAL":
            return
        if siparis.durum == "TASLAK":
            return
        if not siparis.satirlar:
            siparis.durum = "AÇIK"
            return
        if all(s.faturalanan_miktar >= s.miktar for s in siparis.satirlar):
            siparis.durum = "FATURALI"
        elif any(s.faturalanan_miktar > 0 for s in siparis.satirlar):
            siparis.durum = "KISMİ FATURALI"
        elif all(s.irsaliyelenen_miktar >= s.miktar for s in siparis.satirlar):
            siparis.durum = "İRSALİYELİ"
        elif any(s.irsaliyelenen_miktar > 0 for s in siparis.satirlar):
            siparis.durum = "KISMİ İRSALİYELİ"
        else:
            siparis.durum = "AÇIK"

    @staticmethod
    def aktif_musterileri() -> list[Cari]:
        with get_session() as session:
            return list(session.scalars(select(Cari).where(Cari.aktif.is_(True)).order_by(Cari.cari_kodu)).all())

    @staticmethod
    def listele() -> list[dict[str, Any]]:
        SatisSiparisiService.schema_hazirla()
        with get_session() as session:
            siparisler = session.scalars(
                select(SatisSiparisi)
                .options(selectinload(SatisSiparisi.satirlar), selectinload(SatisSiparisi.tahsilatlar), selectinload(SatisSiparisi.cari))
                .order_by(SatisSiparisi.id.desc())
            ).all()
            sonuc = []
            for siparis in siparisler:
                toplam = SatisSiparisiService.siparis_toplami(siparis.satirlar)
                tahsilat = sum((item.tutar for item in siparis.tahsilatlar), Decimal("0"))
                sonuc.append({"siparis": siparis, "musteri": siparis.cari, "toplam": toplam["genel_toplam"], "tahsilat": tahsilat, "kalan": toplam["genel_toplam"] - tahsilat})
            return sonuc

    @staticmethod
    def schema_hazirla() -> None:
        from sqlalchemy import inspect, text

        from database.database import engine

        import database.models.satis_siparisi  # noqa: F401

        if engine is None:
            return
        SatisSiparisi.__table__.create(engine, checkfirst=True)
        SatisSiparisiSatiri.__table__.create(engine, checkfirst=True)
        SatisSiparisiTahsilati.__table__.create(engine, checkfirst=True)
        insp = inspect(engine)
        if not insp.has_table("satis_siparisi_satirlari"):
            return
        mevcut = {c["name"] for c in insp.get_columns("satis_siparisi_satirlari")}
        eklenecekler = {
            "is_manual_item": "BOOLEAN DEFAULT 0 NOT NULL",
            "line_type": "VARCHAR(30) DEFAULT 'STOCK_PRODUCT' NOT NULL",
            "product_id": "INTEGER",
            "delivery_term_days": "INTEGER",
            "estimated_delivery_date": "DATE",
            "delivery_term_note": "VARCHAR(300)",
            "stock_pending": "BOOLEAN DEFAULT 0 NOT NULL",
        }
        eksikler = {a: t for a, t in eklenecekler.items() if a not in mevcut}
        if eksikler:
            with engine.begin() as connection:
                for alan, tip in eksikler.items():
                    connection.execute(
                        text(f'ALTER TABLE "satis_siparisi_satirlari" ADD COLUMN "{alan}" {tip}')
                    )

    @staticmethod
    def getir(siparis_id: int) -> SatisSiparisi | None:
        SatisSiparisiService.schema_hazirla()
        with get_session() as session:
            return session.scalar(
                select(SatisSiparisi)
                .options(selectinload(SatisSiparisi.satirlar), selectinload(SatisSiparisi.tahsilatlar), selectinload(SatisSiparisi.cari))
                .where(SatisSiparisi.id == siparis_id)
            )

    @staticmethod
    def kaydet(veriler: dict[str, Any], satir_verileri: list[dict[str, Any]], tahsilat_verileri: list[dict[str, Any]], siparis_id: int | None = None) -> SatisSiparisi:
        yazma_zorunlu("satis_duzenleme", "yeni_kayit")
        SatisSiparisiService.schema_hazirla()
        from database.user_audit import (
            OturumGerekli,
            audit_document,
            require_user_session,
            stamp_approve,
            stamp_create,
            stamp_update,
        )

        try:
            require_user_session()
        except OturumGerekli as exc:
            raise ValueError(str(exc)) from exc
        siparis_tarihi = veriler["siparis_tarihi"]
        termin_tarihi = veriler["termin_tarihi"]
        if siparis_tarihi > date.today():
            raise ValueError("Sipariş tarihi gelecek bir tarih olamaz.")
        if termin_tarihi < siparis_tarihi:
            raise ValueError("Termin tarihi sipariş tarihinden önce olamaz.")
        with get_session() as session:
            yeni = False
            if siparis_id:
                siparis = session.get(SatisSiparisi, siparis_id)
                if siparis is None:
                    raise ValueError("Sipariş bulunamadı.")
                siparis.satirlar.clear()
                siparis.tahsilatlar.clear()
            else:
                yeni = True
                ozel_no = (veriler.get("siparis_no") or "").strip()
                baslangic_durum = "AÇIK" if veriler.get("onayla") else "TASLAK"
                siparis = SatisSiparisi(
                    siparis_no=ozel_no or SatisSiparisiService.siparis_no(),
                    durum=baslangic_durum,
                )
                session.add(siparis)
            # Maliyet / hedef kâr sipariş UI'da yok; eski kayıt değerini koru, yoksa varsayılan.
            maliyet_yontemi = (
                bos_metin(veriler.get("maliyet_yontemi"))
                or (getattr(siparis, "maliyet_yontemi", None) if not yeni else None)
                or "FIFO"
            )
            hedef_ham = veriler.get("hedef_kar_marji", None)
            if hedef_ham in (None, ""):
                hedef_ham = getattr(siparis, "hedef_kar_marji", 0) if not yeni else 0
            hedef = decimal(hedef_ham or 0, "Hedef kâr marjı", Decimal("0"))
            if not 0 <= hedef < Decimal("100"):
                raise ValueError("Hedef kâr marjı 0 ile 99,99 arasında olmalıdır.")
            siparis.siparis_tarihi = siparis_tarihi
            siparis.termin_tarihi = termin_tarihi
            siparis.cari_id = int(veriler["cari_id"])
            siparis.maliyet_yontemi = maliyet_yontemi
            siparis.hedef_kar_marji = hedef
            siparis.aciklama = bos_metin(veriler.get("aciklama")) or None
            if veriler.get("onayla") and siparis.durum == "TASLAK":
                siparis.durum = "AÇIK"
            if siparis.durum == "İPTAL" and not siparis_id:
                siparis.durum = "AÇIK"
            for veri in satir_verileri:
                satir = SatisSiparisiSatiri(
                    urun_kodu=veri["urun_kodu"], urun_adi=veri["urun_adi"],
                    aciklama=bos_metin(veri.get("aciklama")) or None,
                    miktar=decimal(veri["miktar"], "Miktar", Decimal("0.0001")), birim=veri["birim"],
                    birim_satis_fiyati=decimal(veri["birim_satis_fiyati"], "Birim satış fiyatı", Decimal("0")),
                    iskonto_orani=decimal(veri.get("iskonto_orani", 0), "İskonto oranı", Decimal("0")),
                    kdv_orani=decimal(veri.get("kdv_orani", 20), "KDV oranı", Decimal("0")),
                    fifo_birim_maliyeti=decimal(veri.get("fifo_birim_maliyeti", 0), "FIFO maliyeti", Decimal("0")),
                    son_alis_birim_maliyeti=decimal(veri.get("son_alis_birim_maliyeti", 0), "Son alış maliyeti", Decimal("0")),
                    ortalama_birim_maliyeti=decimal(veri.get("ortalama_birim_maliyeti", 0), "Ortalama maliyeti", Decimal("0")),
                    agirlikli_ortalama_birim_maliyeti=decimal(veri.get("agirlikli_ortalama_birim_maliyeti", 0), "Ağırlıklı maliyeti", Decimal("0")),
                    is_manual_item=bool(veri.get("is_manual_item", False)),
                    line_type=(veri.get("line_type") or ("MANUAL_PRODUCT" if veri.get("is_manual_item") else "STOCK_PRODUCT")),
                    product_id=int(veri["product_id"]) if veri.get("product_id") not in (None, "") else None,
                    delivery_term_days=int(veri["delivery_term_days"]) if veri.get("delivery_term_days") not in (None, "") else None,
                    estimated_delivery_date=veri.get("estimated_delivery_date"),
                    delivery_term_note=veri.get("delivery_term_note"),
                    stock_pending=bool(veri.get("stock_pending", veri.get("is_manual_item", False))),
                )
                satir.irsaliyelenen_miktar = decimal(veri.get("irsaliyelenen_miktar", 0), "İrsaliyelenen miktar", Decimal("0"))
                satir.faturalanan_miktar = decimal(veri.get("faturalanan_miktar", 0), "Faturalanan miktar", Decimal("0"))
                siparis.satirlar.append(satir)
            toplam = SatisSiparisiService.siparis_toplami(siparis.satirlar)
            tahsilat_toplam = Decimal("0")
            for veri in tahsilat_verileri:
                tutar = decimal(veri["tutar"], "Tahsilat tutarı", Decimal("0"))
                tahsilat_toplam += tutar
                siparis.tahsilatlar.append(SatisSiparisiTahsilati(tahsilat_tarihi=veri["tahsilat_tarihi"], tutar=tutar, odeme_sekli=veri["odeme_sekli"], hesap=veri.get("hesap"), aciklama=veri.get("aciklama")))
            if tahsilat_toplam > toplam["genel_toplam"]:
                raise ValueError("Toplam tahsilat sipariş toplamından büyük olamaz.")
            if yeni:
                stamp_create(siparis)
            else:
                stamp_update(siparis)
            if veriler.get("onayla"):
                stamp_approve(siparis)
            try:
                session.flush()
            except IntegrityError as hata:
                raise ValueError("Sipariş kaydedilemedi.") from hata
            sid = int(siparis.id)
            sno = siparis.siparis_no
        audit_document(
            "SIPARIS_OLUSTUR" if yeni else "SIPARIS_DUZENLE",
            modul="satis_siparis",
            kayit_id=str(sid),
            belge_no=sno,
        )
        if veriler.get("onayla"):
            audit_document(
                "SIPARIS_ONAY",
                modul="satis_siparis",
                kayit_id=str(sid),
                belge_no=sno,
            )
        return SatisSiparisiService.getir(sid) or siparis

    @staticmethod
    def iptal_et(siparis_id: int, sebep: str | None = None) -> None:
        yazma_zorunlu("satis_duzenleme", "iptal")
        from database.user_audit import (
            OturumGerekli,
            audit_document,
            require_user_session,
            stamp_cancel,
        )

        try:
            require_user_session()
        except OturumGerekli as exc:
            raise ValueError(str(exc)) from exc
        neden = (sebep or "").strip()
        if not neden:
            raise ValueError("İptal nedeni zorunludur.")
        with get_session() as session:
            siparis = session.get(SatisSiparisi, siparis_id)
            if siparis is None:
                raise ValueError("Sipariş bulunamadı.")
            if siparis.durum == "İPTAL":
                return
            siparis.durum = "İPTAL"
            stamp_cancel(siparis, neden)
            sno = siparis.siparis_no
        from database.deleted_record_service import ENTITY_SATIS_SIPARIS, safe_log_cancel

        safe_log_cancel(ENTITY_SATIS_SIPARIS, siparis_id, note=f"Satış siparişi iptal: {neden}")
        audit_document(
            "SIPARIS_IPTAL",
            modul="satis_siparis",
            kayit_id=str(siparis_id),
            belge_no=sno,
            aciklama=neden,
        )

    @staticmethod
    def siparis_no() -> str:
        return f"SIP-{datetime.now():%Y%m%d%H%M%S%f}"

    @staticmethod
    def calculate_order_progress(satirlar) -> dict[str, Decimal]:
        """Sipariş / sevk / fatura / kalan miktar özeti (FATURA_KAYNAK_KURALI)."""
        siparis = sevk = fatura = Decimal("0")
        for s in satirlar or []:
            get = s.get if isinstance(s, dict) else lambda a, d=0: getattr(s, a, d)
            m = decimal(get("miktar", 0), "Miktar", Decimal("0"))
            ir = decimal(get("irsaliyelenen_miktar", 0), "Sevk", Decimal("0"))
            fa = decimal(get("faturalanan_miktar", 0), "Fatura", Decimal("0"))
            siparis += m
            sevk += ir
            fatura += fa
        sevk_kalani = siparis - sevk
        fatura_kalani = siparis - fatura
        return {
            "siparis_miktar": siparis,
            "sevk_miktar": sevk,
            "fatura_miktar": fatura,
            "sevk_kalani": sevk_kalani,
            "fatura_kalani": fatura_kalani,
            # Eski anahtarlar (geri uyumluluk)
            "kalan_miktar": sevk_kalani,
            "kalan_faturalanacak": fatura_kalani,
        }

    @staticmethod
    def siparis_toplami(satirlar: list[SatisSiparisiSatiri]) -> dict[str, Decimal | float]:
        ara = Decimal("0")
        iskonto = Decimal("0")
        kdv = Decimal("0")
        maliyet = Decimal("0")
        kar = Decimal("0")
        for satir in satirlar:
            brut = satir.miktar * satir.birim_satis_fiyati
            indirim = brut * satir.iskonto_orani / Decimal("100")
            net = brut - indirim
            ara += brut
            iskonto += indirim
            kdv += net * satir.kdv_orani / Decimal("100")
            birim_maliyet = SatisSiparisiService.birim_maliyeti(satir, satir.siparis.maliyet_yontemi if satir.siparis else "FIFO")
            maliyet += satir.miktar * birim_maliyet
            kar += net - satir.miktar * birim_maliyet
        net = ara - iskonto
        return {"ara_toplam": ara, "iskonto": iskonto, "kdv": kdv, "genel_toplam": net + kdv, "net": net, "maliyet": maliyet, "kar": kar, "marj": (kar / net * Decimal("100")) if net else Decimal("0")}

    @staticmethod
    def birim_maliyeti(satir: SatisSiparisiSatiri, yontem: str) -> Decimal:
        return {"FIFO": satir.fifo_birim_maliyeti, "SON ALIŞ FİYATI": satir.son_alis_birim_maliyeti, "ORTALAMA ALIŞ FİYATI": satir.ortalama_birim_maliyeti, "AĞIRLIKLI ORTALAMA ALIŞ FİYATI": satir.agirlikli_ortalama_birim_maliyeti}.get(yontem, Decimal("0"))

    @staticmethod
    def tahmini_bakiye(cari_id: int, siparis_toplami: Decimal, tahsilat: Decimal) -> Decimal:
        ozet = next((item for item in CariService.listele(hizli=True) if item["cari"].id == cari_id), None)
        return (ozet["bakiye"] if ozet else Decimal("0")) + siparis_toplami - tahsilat
