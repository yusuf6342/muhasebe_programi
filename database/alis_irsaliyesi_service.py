from datetime import date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import selectinload

from database.cari_service import CariService
from database.database import get_session
from database.models.cari import Cari
from database.models.alis_irsaliyesi import AlisIrsaliyesi, AlisIrsaliyesiSatiri
from database.models.alis_siparisi import AlisSiparisi, AlisSiparisiSatiri
from database.satis_siparisi_service import decimal

IRSALIYE_DURUMLARI = ("AÇIK", "KISMİ FATURALANDI", "FATURALANDI", "İPTAL")


class AlisIrsaliyesiService:
    @staticmethod
    def _siparis_durumunu_guncelle(session, siparis_id: int | None) -> None:
        if not siparis_id:
            return
        from database.alis_siparisi_service import AlisSiparisiService
        AlisSiparisiService.durumu_guncelle(session, siparis_id)

    @staticmethod
    def iptal_et(irsaliye_id: int) -> None:
        with get_session() as session:
            irsaliye = session.scalar(
                select(AlisIrsaliyesi)
                .options(selectinload(AlisIrsaliyesi.satirlar))
                .where(AlisIrsaliyesi.id == irsaliye_id)
            )
            if irsaliye is None:
                raise ValueError("İrsaliye bulunamadı.")
            if irsaliye.durum == "İPTAL":
                return
            if any(satir.faturalanan_miktar > 0 for satir in irsaliye.satirlar):
                raise ValueError("Faturalanmış irsaliye iptal edilemez.")
            for satir in irsaliye.satirlar:
                if satir.siparis_satiri_id:
                    siparis_satiri = session.get(AlisSiparisiSatiri, satir.siparis_satiri_id)
                    if siparis_satiri:
                        siparis_satiri.irsaliyelenen_miktar = max(
                            Decimal("0"), siparis_satiri.irsaliyelenen_miktar - satir.miktar
                        )
            irsaliye.durum = "İPTAL"
            AlisIrsaliyesiService._siparis_durumunu_guncelle(session, irsaliye.siparis_id)

    @staticmethod
    def aktif_tedarikcileri() -> list[Cari]:
        from database.alis_siparisi_service import AlisSiparisiService
        return AlisSiparisiService.aktif_tedarikcileri()

    @staticmethod
    def acik_siparisler() -> list[AlisSiparisi]:
        with get_session() as session:
            return list(
                session.scalars(
                    select(AlisSiparisi)
                    .where(AlisSiparisi.durum != "İPTAL")
                    .options(selectinload(AlisSiparisi.satirlar), selectinload(AlisSiparisi.cari))
                    .order_by(AlisSiparisi.id.desc())
                ).all()
            )

    @staticmethod
    def listele() -> list[dict[str, Any]]:
        with get_session() as session:
            irsaliyeler = session.scalars(
                select(AlisIrsaliyesi)
                .options(
                    selectinload(AlisIrsaliyesi.cari),
                    selectinload(AlisIrsaliyesi.siparis),
                    selectinload(AlisIrsaliyesi.satirlar),
                )
                .order_by(AlisIrsaliyesi.id.desc())
            ).all()
            sonuc = []
            for irsaliye in irsaliyeler:
                toplam = AlisIrsaliyesiService.toplam(irsaliye.satirlar)
                faturalanan = sum(
                    (satir.faturalanan_miktar * satir.birim_fiyat for satir in irsaliye.satirlar),
                    Decimal("0"),
                )
                sonuc.append({
                    "irsaliye": irsaliye,
                    "toplam": toplam["genel_toplam"],
                    "faturalanan": faturalanan,
                    "kalan": toplam["genel_toplam"] - faturalanan,
                })
            return sonuc

    @staticmethod
    def getir(irsaliye_id: int) -> AlisIrsaliyesi | None:
        with get_session() as session:
            return session.scalar(
                select(AlisIrsaliyesi)
                .options(
                    selectinload(AlisIrsaliyesi.satirlar),
                    selectinload(AlisIrsaliyesi.cari),
                    selectinload(AlisIrsaliyesi.siparis),
                )
                .where(AlisIrsaliyesi.id == irsaliye_id)
            )

    @staticmethod
    def siparis_satirlari(siparis_id: int) -> list[AlisSiparisiSatiri]:
        with get_session() as session:
            siparis = session.get(AlisSiparisi, siparis_id)
            if siparis is None:
                raise ValueError("Sipariş bulunamadı.")
            return [satir for satir in siparis.satirlar if satir.miktar - satir.irsaliyelenen_miktar > 0]

    @staticmethod
    def kaydet(
        veriler: dict[str, Any],
        satir_verileri: list[dict[str, Any]],
        irsaliye_id: int | None = None,
    ) -> AlisIrsaliyesi:
        irsaliye_tarihi = veriler["irsaliye_tarihi"]
        if irsaliye_tarihi > date.today():
            raise ValueError("İrsaliye tarihi gelecek bir tarih olamaz.")
        with get_session() as session:
            if irsaliye_id:
                irsaliye = session.get(AlisIrsaliyesi, irsaliye_id)
                if irsaliye is None:
                    raise ValueError("İrsaliye bulunamadı.")
                if any(satir.faturalanan_miktar > 0 for satir in irsaliye.satirlar):
                    raise ValueError("Faturalanmış irsaliye satırı düzenlenemez.")
                for eski_satir in irsaliye.satirlar:
                    if eski_satir.siparis_satiri_id:
                        siparis_satiri = session.get(AlisSiparisiSatiri, eski_satir.siparis_satiri_id)
                        if siparis_satiri:
                            siparis_satiri.irsaliyelenen_miktar -= eski_satir.miktar
                irsaliye.satirlar.clear()
            else:
                ozel_no = (veriler.get("irsaliye_no") or "").strip()
                irsaliye = AlisIrsaliyesi(
                    irsaliye_no=ozel_no or AlisIrsaliyesiService.irsaliye_no(),
                    durum="AÇIK",
                )
                session.add(irsaliye)
            irsaliye.irsaliye_tarihi = irsaliye_tarihi
            irsaliye.cari_id = int(veriler["cari_id"])
            irsaliye.siparis_id = veriler.get("siparis_id")
            irsaliye.aciklama = veriler.get("aciklama")
            irsaliye.ayrintili_notlar = veriler.get("ayrintili_notlar")
            for veri in satir_verileri:
                miktar = decimal(veri["miktar"], "İrsaliye miktarı", Decimal("0.0001"))
                siparis_satiri_id = veri.get("siparis_satiri_id")
                if siparis_satiri_id:
                    siparis_satiri = session.get(AlisSiparisiSatiri, int(siparis_satiri_id))
                    if siparis_satiri is None:
                        raise ValueError("Bağlı sipariş satırı bulunamadı.")
                    acik = siparis_satiri.miktar - siparis_satiri.irsaliyelenen_miktar
                    if miktar > acik:
                        raise ValueError("İrsaliye miktarı siparişin açık miktarından büyük olamaz.")
                    siparis_satiri.irsaliyelenen_miktar += miktar
                irsaliye.satirlar.append(
                    AlisIrsaliyesiSatiri(
                        irsaliye_id=irsaliye.id if irsaliye.id else None,
                        siparis_satiri_id=siparis_satiri_id,
                        urun_kodu=veri["urun_kodu"],
                        urun_adi=veri["urun_adi"],
                        aciklama=veri.get("aciklama"),
                        miktar=miktar,
                        birim=veri["birim"],
                        birim_fiyat=decimal(veri["birim_fiyat"], "Birim fiyat", Decimal("0")),
                        iskonto_orani=decimal(veri.get("iskonto_orani", 0), "İskonto", Decimal("0")),
                        kdv_orani=decimal(veri.get("kdv_orani", 20), "KDV", Decimal("0")),
                        faturalanan_miktar=Decimal("0"),
                    )
                )
            if not irsaliye.satirlar:
                raise ValueError("En az bir irsaliye satırı ekleyin.")
            AlisIrsaliyesiService._siparis_durumunu_guncelle(session, irsaliye.siparis_id)
            try:
                session.flush()
            except IntegrityError as hata:
                raise ValueError("İrsaliye kaydedilemedi.") from hata
            return irsaliye

    @staticmethod
    def faturaya_aktarilabilir_miktar(satir: AlisIrsaliyesiSatiri) -> Decimal:
        return satir.miktar - satir.faturalanan_miktar

    @staticmethod
    def faturalanan_miktar_artir(irsaliye_satiri_id: int, miktar: Decimal, belge_baglantisi: str) -> None:
        with get_session() as session:
            satir = session.get(AlisIrsaliyesiSatiri, irsaliye_satiri_id)
            if satir is None:
                raise ValueError("İrsaliye satırı bulunamadı.")
            miktar = decimal(miktar, "Faturalanan miktar", Decimal("0.0001"))
            if miktar > AlisIrsaliyesiService.faturaya_aktarilabilir_miktar(satir):
                raise ValueError("Faturalanan miktar kalan miktardan büyük olamaz.")
            satir.faturalanan_miktar += miktar
            satir.fatura_belge_baglantisi = belge_baglantisi
            irsaliye = session.get(AlisIrsaliyesi, satir.irsaliye_id)
            if irsaliye:
                irsaliye.durum = (
                    "FATURALANDI"
                    if all(AlisIrsaliyesiService.faturaya_aktarilabilir_miktar(item) <= 0 for item in irsaliye.satirlar)
                    else "KISMİ FATURALANDI"
                )

    @staticmethod
    def irsaliye_no() -> str:
        return f"AIRS-{datetime.now():%Y%m%d%H%M%S%f}"

    @staticmethod
    def toplam(satirlar: list[AlisIrsaliyesiSatiri]) -> dict[str, Decimal]:
        ara = Decimal("0")
        iskonto = Decimal("0")
        kdv = Decimal("0")
        for satir in satirlar:
            brut = satir.miktar * satir.birim_fiyat
            indirim = brut * satir.iskonto_orani / Decimal("100")
            ara += brut
            iskonto += indirim
            kdv += (brut - indirim) * satir.kdv_orani / Decimal("100")
        return {"ara_toplam": ara, "iskonto": iskonto, "kdv": kdv, "genel_toplam": ara - iskonto + kdv}

    @staticmethod
    def mevcut_bakiye(cari_id: int) -> Decimal:
        ozet = next((item for item in CariService.listele() if item["cari"].id == cari_id), None)
        return ozet["bakiye"] if ozet else Decimal("0")
