from datetime import date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import selectinload

from database.cari_service import CariService
from database.database import get_session
from database.models.cari import Cari
from database.models.alis_siparisi import (
    AlisSiparisi,
    AlisSiparisiOdemesi,
    AlisSiparisiSatiri,
)
from database.satis_siparisi_service import decimal

SIPARIS_DURUMLARI = ("AÇIK", "KISMİ İRSALİYELİ", "İRSALİYELİ", "KISMİ FATURALI", "FATURALI", "İPTAL")
ODEME_SEKILLERI = ("NAKİT / KASA", "GİDEN HAVALE", "KREDİ KARTI")


class AlisSiparisiService:
    @staticmethod
    def durumu_guncelle(session, siparis_id: int | None) -> None:
        if not siparis_id:
            return
        siparis = session.scalar(
            select(AlisSiparisi)
            .options(selectinload(AlisSiparisi.satirlar))
            .where(AlisSiparisi.id == siparis_id)
        )
        if siparis is None or siparis.durum == "İPTAL":
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
    def aktif_tedarikcileri() -> list[Cari]:
        return CariService.aktif_tedarikciler()

    @staticmethod
    def listele() -> list[dict[str, Any]]:
        with get_session() as session:
            siparisler = session.scalars(
                select(AlisSiparisi)
                .options(
                    selectinload(AlisSiparisi.satirlar),
                    selectinload(AlisSiparisi.odemeler),
                    selectinload(AlisSiparisi.cari),
                )
                .order_by(AlisSiparisi.id.desc())
            ).all()
            sonuc = []
            for siparis in siparisler:
                toplam = AlisSiparisiService.siparis_toplami(siparis.satirlar)
                odeme = sum((item.tutar for item in siparis.odemeler), Decimal("0"))
                sonuc.append({
                    "siparis": siparis,
                    "tedarikci": siparis.cari,
                    "toplam": toplam["genel_toplam"],
                    "odeme": odeme,
                    "kalan": toplam["genel_toplam"] - odeme,
                })
            return sonuc

    @staticmethod
    def getir(siparis_id: int) -> AlisSiparisi | None:
        with get_session() as session:
            return session.scalar(
                select(AlisSiparisi)
                .options(
                    selectinload(AlisSiparisi.satirlar),
                    selectinload(AlisSiparisi.odemeler),
                    selectinload(AlisSiparisi.cari),
                )
                .where(AlisSiparisi.id == siparis_id)
            )

    @staticmethod
    def kaydet(
        veriler: dict[str, Any],
        satir_verileri: list[dict[str, Any]],
        odeme_verileri: list[dict[str, Any]],
        siparis_id: int | None = None,
    ) -> AlisSiparisi:
        siparis_tarihi = veriler["siparis_tarihi"]
        termin_tarihi = veriler["termin_tarihi"]
        if siparis_tarihi > date.today():
            raise ValueError("Sipariş tarihi gelecek bir tarih olamaz.")
        if termin_tarihi < siparis_tarihi:
            raise ValueError("Termin tarihi sipariş tarihinden önce olamaz.")
        with get_session() as session:
            if siparis_id:
                siparis = session.get(AlisSiparisi, siparis_id)
                if siparis is None:
                    raise ValueError("Sipariş bulunamadı.")
                siparis.satirlar.clear()
                siparis.odemeler.clear()
            else:
                ozel_no = (veriler.get("siparis_no") or "").strip()
                siparis = AlisSiparisi(
                    siparis_no=ozel_no or AlisSiparisiService.siparis_no(),
                    durum="AÇIK",
                )
                session.add(siparis)
            siparis.siparis_tarihi = siparis_tarihi
            siparis.termin_tarihi = termin_tarihi
            siparis.cari_id = int(veriler["cari_id"])
            siparis.aciklama = veriler.get("aciklama")
            if siparis.durum == "İPTAL" and not siparis_id:
                siparis.durum = "AÇIK"
            for veri in satir_verileri:
                satir = AlisSiparisiSatiri(
                    urun_kodu=veri["urun_kodu"],
                    urun_adi=veri["urun_adi"],
                    aciklama=veri.get("aciklama"),
                    miktar=decimal(veri["miktar"], "Miktar", Decimal("0.0001")),
                    birim=veri["birim"],
                    birim_alis_fiyati=decimal(veri["birim_alis_fiyati"], "Birim alış fiyatı", Decimal("0")),
                    iskonto_orani=decimal(veri.get("iskonto_orani", 0), "İskonto oranı", Decimal("0")),
                    kdv_orani=decimal(veri.get("kdv_orani", 20), "KDV oranı", Decimal("0")),
                )
                satir.irsaliyelenen_miktar = decimal(
                    veri.get("irsaliyelenen_miktar", 0), "İrsaliyelenen miktar", Decimal("0")
                )
                satir.faturalanan_miktar = decimal(
                    veri.get("faturalanan_miktar", 0), "Faturalanan miktar", Decimal("0")
                )
                siparis.satirlar.append(satir)
            toplam = AlisSiparisiService.siparis_toplami(siparis.satirlar)
            odeme_toplam = Decimal("0")
            for veri in odeme_verileri:
                tutar = decimal(veri["tutar"], "Ödeme tutarı", Decimal("0"))
                odeme_toplam += tutar
                siparis.odemeler.append(
                    AlisSiparisiOdemesi(
                        odeme_tarihi=veri["odeme_tarihi"],
                        tutar=tutar,
                        odeme_sekli=veri["odeme_sekli"],
                        hesap=veri.get("hesap"),
                        aciklama=veri.get("aciklama"),
                    )
                )
            if odeme_toplam > toplam["genel_toplam"]:
                raise ValueError("Toplam ödeme sipariş toplamından büyük olamaz.")
            try:
                session.flush()
            except IntegrityError as hata:
                raise ValueError("Sipariş kaydedilemedi.") from hata
            return siparis

    @staticmethod
    def iptal_et(siparis_id: int) -> None:
        with get_session() as session:
            siparis = session.get(AlisSiparisi, siparis_id)
            if siparis is None:
                raise ValueError("Sipariş bulunamadı.")
            siparis.durum = "İPTAL"

    @staticmethod
    def siparis_no() -> str:
        return f"ASIP-{datetime.now():%Y%m%d%H%M%S%f}"

    @staticmethod
    def siparis_toplami(satirlar: list[AlisSiparisiSatiri]) -> dict[str, Decimal]:
        ara = Decimal("0")
        iskonto = Decimal("0")
        kdv = Decimal("0")
        for satir in satirlar:
            brut = satir.miktar * satir.birim_alis_fiyati
            indirim = brut * satir.iskonto_orani / Decimal("100")
            net = brut - indirim
            ara += brut
            iskonto += indirim
            kdv += net * satir.kdv_orani / Decimal("100")
        net = ara - iskonto
        return {
            "ara_toplam": ara,
            "iskonto": iskonto,
            "kdv": kdv,
            "genel_toplam": net + kdv,
            "net": net,
        }

    @staticmethod
    def tahmini_bakiye(cari_id: int, siparis_toplami: Decimal, odeme: Decimal) -> Decimal:
        ozet = next((item for item in CariService.listele() if item["cari"].id == cari_id), None)
        return (ozet["bakiye"] if ozet else Decimal("0")) + siparis_toplami - odeme
