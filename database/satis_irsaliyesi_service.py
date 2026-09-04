from datetime import date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import selectinload

from database.cari_service import CariService
from database.database import get_session
from database.models.cari import Cari
from database.models.satis_irsaliyesi import SatisIrsaliyesi, SatisIrsaliyesiSatiri
from database.models.satis_siparisi import SatisSiparisi, SatisSiparisiSatiri
from database.satis_siparisi_service import decimal

IRSALIYE_DURUMLARI = ("AÇIK", "KISMİ FATURALANDI", "FATURALANDI", "İPTAL")


class SatisIrsaliyesiService:
    @staticmethod
    def iptal_et(irsaliye_id: int) -> None:
        with get_session() as session:
            irsaliye = session.get(SatisIrsaliyesi, irsaliye_id)
            if irsaliye is None:
                raise ValueError("İrsaliye bulunamadı.")
            irsaliye.durum = "İPTAL"

    @staticmethod
    def aktif_musterileri() -> list[Cari]:
        with get_session() as session:
            return list(session.scalars(select(Cari).where(Cari.aktif.is_(True)).order_by(Cari.cari_kodu)).all())

    @staticmethod
    def acik_siparisler() -> list[SatisSiparisi]:
        with get_session() as session:
            return list(session.scalars(select(SatisSiparisi).where(SatisSiparisi.durum != "İPTAL").options(selectinload(SatisSiparisi.satirlar), selectinload(SatisSiparisi.cari)).order_by(SatisSiparisi.id.desc())).all())

    @staticmethod
    def listele() -> list[dict[str, Any]]:
        with get_session() as session:
            irsaliyeler = session.scalars(select(SatisIrsaliyesi).options(selectinload(SatisIrsaliyesi.cari), selectinload(SatisIrsaliyesi.siparis), selectinload(SatisIrsaliyesi.satirlar)).order_by(SatisIrsaliyesi.id.desc())).all()
            sonuc = []
            for irsaliye in irsaliyeler:
                toplam = SatisIrsaliyesiService.toplam(irsaliye.satirlar)
                faturalanan = sum((satir.faturalanan_miktar * satir.birim_fiyat for satir in irsaliye.satirlar), Decimal("0"))
                sonuc.append({"irsaliye": irsaliye, "toplam": toplam["genel_toplam"], "faturalanan": faturalanan, "kalan": toplam["genel_toplam"] - faturalanan})
            return sonuc

    @staticmethod
    def getir(irsaliye_id: int) -> SatisIrsaliyesi | None:
        with get_session() as session:
            return session.scalar(select(SatisIrsaliyesi).options(selectinload(SatisIrsaliyesi.satirlar), selectinload(SatisIrsaliyesi.cari), selectinload(SatisIrsaliyesi.siparis)).where(SatisIrsaliyesi.id == irsaliye_id))

    @staticmethod
    def siparis_satirlari(siparis_id: int) -> list[SatisSiparisiSatiri]:
        with get_session() as session:
            siparis = session.get(SatisSiparisi, siparis_id)
            if siparis is None:
                raise ValueError("Sipariş bulunamadı.")
            return [satir for satir in siparis.satirlar if satir.miktar - satir.irsaliyelenen_miktar > 0]

    @staticmethod
    def kaydet(veriler: dict[str, Any], satir_verileri: list[dict[str, Any]], irsaliye_id: int | None = None) -> SatisIrsaliyesi:
        irsaliye_tarihi = veriler["irsaliye_tarihi"]
        if irsaliye_tarihi > date.today():
            raise ValueError("İrsaliye tarihi gelecek bir tarih olamaz.")
        with get_session() as session:
            if irsaliye_id:
                irsaliye = session.get(SatisIrsaliyesi, irsaliye_id)
                if irsaliye is None:
                    raise ValueError("İrsaliye bulunamadı.")
                if any(satir.faturalanan_miktar > 0 for satir in irsaliye.satirlar):
                    raise ValueError("Faturalanmış irsaliye satırı düzenlenemez.")
                for eski_satir in irsaliye.satirlar:
                    if eski_satir.siparis_satiri_id:
                        siparis_satiri = session.get(SatisSiparisiSatiri, eski_satir.siparis_satiri_id)
                        if siparis_satiri:
                            siparis_satiri.irsaliyelenen_miktar -= eski_satir.miktar
                irsaliye.satirlar.clear()
            else:
                irsaliye = SatisIrsaliyesi(irsaliye_no=SatisIrsaliyesiService.irsaliye_no(), durum="AÇIK")
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
                    siparis_satiri = session.get(SatisSiparisiSatiri, int(siparis_satiri_id))
                    if siparis_satiri is None:
                        raise ValueError("Bağlı sipariş satırı bulunamadı.")
                    acik = siparis_satiri.miktar - siparis_satiri.irsaliyelenen_miktar
                    if miktar > acik:
                        raise ValueError("İrsaliye miktarı siparişin açık miktarından büyük olamaz.")
                    siparis_satiri.irsaliyelenen_miktar += miktar
                irsaliye.satirlar.append(SatisIrsaliyesiSatiri(irsaliye_id=irsaliye.id if irsaliye.id else None, siparis_satiri_id=siparis_satiri_id, urun_kodu=veri["urun_kodu"], urun_adi=veri["urun_adi"], aciklama=veri.get("aciklama"), miktar=miktar, birim=veri["birim"], birim_fiyat=decimal(veri["birim_fiyat"], "Birim fiyat", Decimal("0")), iskonto_orani=decimal(veri.get("iskonto_orani", 0), "İskonto", Decimal("0")), kdv_orani=decimal(veri.get("kdv_orani", 20), "KDV", Decimal("0")), faturalanan_miktar=Decimal("0")))
            if not irsaliye.satirlar:
                raise ValueError("En az bir irsaliye satırı ekleyin.")
            SatisIrsaliyesiService._siparis_durumunu_guncelle(session, irsaliye.siparis_id)
            try:
                session.flush()
            except IntegrityError as hata:
                raise ValueError("İrsaliye kaydedilemedi.") from hata
            return irsaliye

    @staticmethod
    def _siparis_durumunu_guncelle(session, siparis_id: int | None) -> None:
        if not siparis_id:
            return
        siparis = session.get(SatisSiparisi, siparis_id)
        if siparis is None:
            return
        acik = any(satir.miktar - satir.irsaliyelenen_miktar > 0 for satir in siparis.satirlar)
        siparis.durum = "KISMİ İRSALİYELİ" if acik else "İRSALİYELENDİ"

    @staticmethod
    def faturaya_aktarilabilir_miktar(satir: SatisIrsaliyesiSatiri) -> Decimal:
        return satir.miktar - satir.faturalanan_miktar

    @staticmethod
    def faturalanan_miktar_artir(irsaliye_satiri_id: int, miktar: Decimal, belge_baglantisi: str) -> None:
        with get_session() as session:
            satir = session.get(SatisIrsaliyesiSatiri, irsaliye_satiri_id)
            if satir is None:
                raise ValueError("İrsaliye satırı bulunamadı.")
            miktar = decimal(miktar, "Faturalanan miktar", Decimal("0.0001"))
            if miktar > SatisIrsaliyesiService.faturaya_aktarilabilir_miktar(satir):
                raise ValueError("Faturalanan miktar kalan miktardan büyük olamaz.")
            satir.faturalanan_miktar += miktar
            satir.fatura_belge_baglantisi = belge_baglantisi
            irsaliye = session.get(SatisIrsaliyesi, satir.irsaliye_id)
            if irsaliye:
                irsaliye.durum = "FATURALANDI" if all(SatisIrsaliyesiService.faturaya_aktarilabilir_miktar(item) <= 0 for item in irsaliye.satirlar) else "KISMİ FATURALANDI"

    @staticmethod
    def irsaliye_no() -> str:
        return f"IRS-{datetime.now():%Y%m%d%H%M%S%f}"

    @staticmethod
    def toplam(satirlar: list[SatisIrsaliyesiSatiri]) -> dict[str, Decimal]:
        ara = Decimal("0"); iskonto = Decimal("0"); kdv = Decimal("0")
        for satir in satirlar:
            brut = satir.miktar * satir.birim_fiyat
            indirim = brut * satir.iskonto_orani / Decimal("100")
            ara += brut; iskonto += indirim; kdv += (brut - indirim) * satir.kdv_orani / Decimal("100")
        return {"ara_toplam": ara, "iskonto": iskonto, "kdv": kdv, "genel_toplam": ara - iskonto + kdv}

    @staticmethod
    def mevcut_bakiye(cari_id: int) -> Decimal:
        ozet = next((item for item in CariService.listele() if item["cari"].id == cari_id), None)
        return ozet["bakiye"] if ozet else Decimal("0")
