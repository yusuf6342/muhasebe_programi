from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import selectinload
from sqlalchemy.exc import IntegrityError

from database.cari_service import CariService
from database.database import get_session
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
SIPARIS_DURUMLARI = ("AÇIK", "KISMİ İRSALİYELİ", "İRSALİYELİ", "KISMİ FATURALI", "FATURALI", "İPTAL")
ODEME_SEKILLERI = ("NAKİT / KASA", "GELEN HAVALE", "KREDİ KARTI")


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
    def getir(siparis_id: int) -> SatisSiparisi | None:
        with get_session() as session:
            return session.scalar(
                select(SatisSiparisi)
                .options(selectinload(SatisSiparisi.satirlar), selectinload(SatisSiparisi.tahsilatlar), selectinload(SatisSiparisi.cari))
                .where(SatisSiparisi.id == siparis_id)
            )

    @staticmethod
    def kaydet(veriler: dict[str, Any], satir_verileri: list[dict[str, Any]], tahsilat_verileri: list[dict[str, Any]], siparis_id: int | None = None) -> SatisSiparisi:
        siparis_tarihi = veriler["siparis_tarihi"]
        termin_tarihi = veriler["termin_tarihi"]
        if siparis_tarihi > date.today():
            raise ValueError("Sipariş tarihi gelecek bir tarih olamaz.")
        if termin_tarihi < siparis_tarihi:
            raise ValueError("Termin tarihi sipariş tarihinden önce olamaz.")
        hedef = decimal(veriler.get("hedef_kar_marji", 0), "Hedef kâr marjı")
        if not 0 <= hedef < Decimal("100"):
            raise ValueError("Hedef kâr marjı 0 ile 99,99 arasında olmalıdır.")
        with get_session() as session:
            if siparis_id:
                siparis = session.get(SatisSiparisi, siparis_id)
                if siparis is None:
                    raise ValueError("Sipariş bulunamadı.")
                siparis.satirlar.clear()
                siparis.tahsilatlar.clear()
            else:
                siparis = SatisSiparisi(siparis_no=SatisSiparisiService.siparis_no(), durum="AÇIK")
                session.add(siparis)
            siparis.siparis_tarihi = siparis_tarihi
            siparis.termin_tarihi = termin_tarihi
            siparis.cari_id = int(veriler["cari_id"])
            siparis.maliyet_yontemi = veriler["maliyet_yontemi"]
            siparis.hedef_kar_marji = hedef
            siparis.aciklama = veriler.get("aciklama")
            if siparis.durum == "İPTAL" and not siparis_id:
                siparis.durum = "AÇIK"
            for veri in satir_verileri:
                satir = SatisSiparisiSatiri(
                    urun_kodu=veri["urun_kodu"], urun_adi=veri["urun_adi"], aciklama=veri.get("aciklama"),
                    miktar=decimal(veri["miktar"], "Miktar", Decimal("0.0001")), birim=veri["birim"],
                    birim_satis_fiyati=decimal(veri["birim_satis_fiyati"], "Birim satış fiyatı", Decimal("0")),
                    iskonto_orani=decimal(veri.get("iskonto_orani", 0), "İskonto oranı", Decimal("0")),
                    kdv_orani=decimal(veri.get("kdv_orani", 20), "KDV oranı", Decimal("0")),
                    fifo_birim_maliyeti=decimal(veri.get("fifo_birim_maliyeti", 0), "FIFO maliyeti", Decimal("0")),
                    son_alis_birim_maliyeti=decimal(veri.get("son_alis_birim_maliyeti", 0), "Son alış maliyeti", Decimal("0")),
                    ortalama_birim_maliyeti=decimal(veri.get("ortalama_birim_maliyeti", 0), "Ortalama maliyeti", Decimal("0")),
                    agirlikli_ortalama_birim_maliyeti=decimal(veri.get("agirlikli_ortalama_birim_maliyeti", 0), "Ağırlıklı maliyeti", Decimal("0")),
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
            try:
                session.flush()
            except IntegrityError as hata:
                raise ValueError("Sipariş kaydedilemedi.") from hata
            return siparis

    @staticmethod
    def iptal_et(siparis_id: int) -> None:
        with get_session() as session:
            siparis = session.get(SatisSiparisi, siparis_id)
            if siparis is None:
                raise ValueError("Sipariş bulunamadı.")
            siparis.durum = "İPTAL"

    @staticmethod
    def siparis_no() -> str:
        return f"SIP-{datetime.now():%Y%m%d%H%M%S%f}"

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
        ozet = next((item for item in CariService.listele() if item["cari"].id == cari_id), None)
        return (ozet["bakiye"] if ozet else Decimal("0")) + siparis_toplami - tahsilat
