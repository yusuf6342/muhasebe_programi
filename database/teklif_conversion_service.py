"""Teklif → Alınan Sipariş dönüşümü (tek transaction, çift sipariş engeli)."""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Any

from sqlalchemy import select

from database.access import yazma_zorunlu
from database.database import get_session
from database.models.satis_teklifi import SatisTeklifi
from database.satis_siparisi_service import SatisSiparisiService
from database.teklif_service import QuoteService
from database.user_audit import OturumGerekli, audit_document, require_user_session, stamp_update


class QuoteConversionService:
    @staticmethod
    def convert_to_sales_order(
        teklif_id: int,
        *,
        satir_idler: list[int] | None = None,
        sadece_kabul_edilen: bool = True,
    ) -> dict[str, Any]:
        """Tam veya kısmi dönüşüm. Başarısızsa teklif durumu değişmez."""
        yazma_zorunlu("satis_duzenleme", "yeni_kayit")
        try:
            require_user_session()
        except OturumGerekli as exc:
            raise ValueError(str(exc)) from exc

        teklif = QuoteService.getir(int(teklif_id))
        if not teklif:
            raise ValueError("Teklif bulunamadı.")
        if teklif.siparis_id:
            raise ValueError(
                f"Bu teklif zaten siparişe dönüşmüş: {teklif.siparis_no or teklif.siparis_id}"
            )
        if teklif.durum not in ("KABUL EDİLDİ", "KISMEN KABUL"):
            raise ValueError(
                f"Sipariş için teklif durumu uygun değil: {teklif.durum}. "
                "Önce müşteri kabulü gerekir."
            )
        if not teklif.cari_id:
            raise ValueError(
                "Aday müşteri siparişe dönüşmeden önce cari karta bağlanmalıdır."
            )

        # Aynı teklif ailesinde sipariş var mı?
        ana_id = teklif.ana_teklif_id or teklif.id
        with get_session() as session:
            kardes = session.scalars(
                select(SatisTeklifi).where(
                    SatisTeklifi.siparis_id.is_not(None),
                    (SatisTeklifi.id == ana_id) | (SatisTeklifi.ana_teklif_id == ana_id),
                )
            ).first()
            if kardes and int(kardes.id) != int(teklif.id):
                raise ValueError(
                    f"Bu teklif ailesinde zaten sipariş var: {kardes.siparis_no}"
                )

        satirlar = []
        for s in teklif.satirlar:
            if satir_idler is not None and s.id not in satir_idler:
                continue
            if sadece_kabul_edilen and not s.kabul_edildi:
                continue
            if s.opsiyonel and not s.toplama_dahil and not s.kabul_edildi:
                continue
            satirlar.append(
                {
                    "urun_kodu": s.urun_kodu,
                    "urun_adi": s.urun_adi,
                    "aciklama": s.aciklama,
                    "miktar": s.miktar,
                    "birim": s.birim,
                    "birim_satis_fiyati": s.teklif_fiyati,
                    "iskonto_orani": s.iskonto_orani,
                    "kdv_orani": s.kdv_orani,
                    "fifo_birim_maliyeti": s.birim_maliyet,
                    "son_alis_birim_maliyeti": s.birim_maliyet,
                    "ortalama_birim_maliyeti": s.birim_maliyet,
                    "agirlikli_ortalama_birim_maliyeti": s.birim_maliyet,
                    "is_manual_item": bool(getattr(s, "is_manual_item", False)),
                    "line_type": getattr(s, "line_type", None)
                    or (
                        "MANUAL_PRODUCT"
                        if getattr(s, "is_manual_item", False)
                        else "STOCK_PRODUCT"
                    ),
                    "product_id": getattr(s, "product_id", None),
                    "delivery_term_days": getattr(s, "delivery_term_days", None),
                    "estimated_delivery_date": getattr(s, "estimated_delivery_date", None),
                    "delivery_term_note": getattr(s, "delivery_term_note", None),
                    "stock_pending": bool(getattr(s, "is_manual_item", False))
                    and not getattr(s, "converted_product_id", None),
                }
            )
        if not satirlar:
            raise ValueError("Siparişe aktarılacak satır yok.")

        manuel_var = any(x.get("is_manual_item") for x in satirlar)
        if manuel_var:
            # UI uyarısı caller tarafında; burada audit notu
            pass

        termin = (
            getattr(teklif, "estimated_delivery_date", None)
            or teklif.tahmini_termin
            or teklif.gecerlilik_tarihi
            or date.today()
        )
        notlar = []
        if teklif.musteri_notu:
            notlar.append(teklif.musteri_notu)
        if teklif.ticari_sartlar:
            notlar.append(teklif.ticari_sartlar)
        termin_notu = getattr(teklif, "delivery_term_note", None)
        if termin_notu:
            notlar.append(f"Termin: {termin_notu}")
        termin_gun = getattr(teklif, "delivery_term_days", None)
        termin_tur = getattr(teklif, "delivery_term_type", None)
        if termin_gun is not None or termin_tur:
            parcalar = []
            if termin_tur:
                parcalar.append(str(termin_tur))
            if termin_gun is not None:
                parcalar.append(f"{termin_gun} gün")
            notlar.append("Teslim şartı: " + " / ".join(parcalar))
        notlar.append(f"Kaynak teklif: {QuoteService.gosterim_no(teklif)}")

        siparis_veri = {
            "siparis_tarihi": date.today(),
            "termin_tarihi": termin,
            "cari_id": int(teklif.cari_id),
            "maliyet_yontemi": "FIFO",
            "hedef_kar_marji": min(Decimal(str(teklif.gercek_marj or 0)), Decimal("99.99")),
            "aciklama": "\n".join(notlar),
            "durum": "AÇIK",
            "onayla": True,
        }
        # para_birimi/kur sipariş modelinde yoksa aktarma — desteklenirse eklenir
        if hasattr(SatisSiparisiService, "para_birimi_destekli"):
            siparis_veri["para_birimi"] = teklif.para_birimi
            siparis_veri["kur"] = teklif.kur
        else:
            from database.models.satis_siparisi import SatisSiparisi

            if hasattr(SatisSiparisi, "para_birimi"):
                siparis_veri["para_birimi"] = teklif.para_birimi
            if hasattr(SatisSiparisi, "kur"):
                siparis_veri["kur"] = teklif.kur

        # Önce sipariş; başarılıysa teklifi güncelle (ayrı session — sipariş servisi kendi transaction'ı)
        siparis = SatisSiparisiService.kaydet(siparis_veri, satirlar, [])
        sid = int(siparis.id)
        sno = siparis.siparis_no

        with get_session() as session:
            t = session.get(SatisTeklifi, int(teklif_id))
            if not t:
                raise ValueError("Teklif güncellenemedi.")
            if t.siparis_id:
                raise ValueError("Eşzamanlı ikinci sipariş engellendi.")
            t.siparis_id = sid
            t.siparis_no = sno
            t.durum = "SİPARİŞE DÖNÜŞTÜ"
            stamp_update(t)
            session.flush()
            tno = t.teklif_no

        audit_document(
            "TEKLIF_SIPARISE",
            modul="satis_teklif",
            kayit_id=str(teklif_id),
            belge_no=tno,
            yeni={"siparis_id": sid, "siparis_no": sno},
        )
        return {
            "teklif_id": int(teklif_id),
            "teklif_no": tno,
            "siparis_id": sid,
            "siparis_no": sno,
            "siparis": siparis,
        }
