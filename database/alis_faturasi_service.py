from datetime import date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import selectinload

from database.database import get_session
from database.finans_service import FinansService
from database.models.cari import Cari, SatisHareketi
from database.models.alis_faturasi import AlisFaturasi, AlisFaturasiSatiri
from database.models.alis_irsaliyesi import AlisIrsaliyesi, AlisIrsaliyesiSatiri
from database.models.alis_siparisi import AlisSiparisi, AlisSiparisiSatiri
from database.satis_siparisi_service import decimal
from database.stok_service import StokService

FATURA_DURUMLARI = ("AÇIK", "KAPALI", "İPTAL")
ODEME_SEKILLERI = ("KASA ÖDEME", "GÖNDERİLEN HAVALE", "KREDİ KARTIYLA ÖDEME")


class AlisFaturasiService:
    @staticmethod
    def aktif_tedarikcileri():
        from database.alis_siparisi_service import AlisSiparisiService
        return AlisSiparisiService.aktif_tedarikcileri()

    @staticmethod
    def listele() -> list[dict[str, Any]]:
        with get_session() as session:
            faturalar = session.scalars(
                select(AlisFaturasi)
                .options(
                    selectinload(AlisFaturasi.cari),
                    selectinload(AlisFaturasi.satirlar),
                    selectinload(AlisFaturasi.siparis),
                    selectinload(AlisFaturasi.irsaliye),
                )
                .order_by(AlisFaturasi.id.desc())
            ).all()
            return [{"fatura": f, **AlisFaturasiService.toplam(f.satirlar)} for f in faturalar]

    @staticmethod
    def getir(fatura_id):
        with get_session() as session:
            return session.scalar(
                select(AlisFaturasi)
                .options(
                    selectinload(AlisFaturasi.cari),
                    selectinload(AlisFaturasi.siparis),
                    selectinload(AlisFaturasi.irsaliye),
                    selectinload(AlisFaturasi.satirlar),
                )
                .where(AlisFaturasi.id == fatura_id)
            )

    @staticmethod
    def acik_siparisler():
        with get_session() as session:
            return list(
                session.scalars(
                    select(AlisSiparisi)
                    .where(AlisSiparisi.durum != "İPTAL")
                    .options(selectinload(AlisSiparisi.cari), selectinload(AlisSiparisi.satirlar))
                    .order_by(AlisSiparisi.id.desc())
                ).all()
            )

    @staticmethod
    def acik_irsaliyeler():
        with get_session() as session:
            return list(
                session.scalars(
                    select(AlisIrsaliyesi)
                    .where(AlisIrsaliyesi.durum.in_(("AÇIK", "KISMİ FATURALANDI")))
                    .options(selectinload(AlisIrsaliyesi.cari), selectinload(AlisIrsaliyesi.satirlar))
                    .order_by(AlisIrsaliyesi.id.desc())
                ).all()
            )

    @staticmethod
    def _net_birim_maliyet(birim_fiyat: Decimal, iskonto_orani: Decimal) -> Decimal:
        return birim_fiyat - (birim_fiyat * iskonto_orani / Decimal("100"))

    @staticmethod
    def kaydet(veriler, satir_verileri, fatura_id=None):
        tarih, vade = veriler["fatura_tarihi"], veriler["vade_tarihi"]
        if tarih > date.today():
            raise ValueError("Fatura tarihi gelecek bir tarih olamaz.")
        if vade < tarih:
            raise ValueError("Vade tarihi fatura tarihinden önce olamaz.")
        if not satir_verileri:
            raise ValueError("En az bir fatura satırı ekleyin.")
        with get_session() as session:
            if fatura_id:
                fatura = session.get(AlisFaturasi, fatura_id)
                if not fatura:
                    raise ValueError("Fatura bulunamadı.")
                if fatura.durum == "İPTAL":
                    raise ValueError("İptal edilmiş fatura düzenlenemez.")
                AlisFaturasiService._baglantilari_geri_al(session, fatura.satirlar)
                StokService.fatura_girislerini_geri_al(session, fatura.fatura_no)
                FinansService.fatura_odemesini_geri_al(session, fatura.fatura_no)
                fatura.satirlar.clear()
            else:
                fatura = AlisFaturasi(fatura_no=AlisFaturasiService.fatura_no())
                session.add(fatura)
            fatura.fatura_tarihi, fatura.vade_tarihi = tarih, vade
            fatura.vade_gunu = (vade - tarih).days
            for alan in ("cari_id", "siparis_id", "irsaliye_id", "depo", "odeme_sekli", "odeme_hesabi", "aciklama", "dokuman_yolu"):
                setattr(fatura, alan, veriler.get(alan) or (("ANA DEPO" if alan == "depo" else None)))
            fatura.cari_id = int(veriler["cari_id"])
            fatura.odeme_tutari = decimal(veriler.get("odeme_tutari", 0), "Ödeme", Decimal("0"))

            cari = session.get(Cari, fatura.cari_id)
            tedarikci_adi = cari.unvan if cari else ""

            for veri in satir_verileri:
                miktar = decimal(veri["miktar"], "Miktar", Decimal("0.0001"))
                birim_fiyat = decimal(veri["birim_fiyat"], "Birim fiyat", Decimal("0"))
                iskonto_orani = decimal(veri.get("iskonto_orani", 0), "İskonto", Decimal("0"))
                irs_id, sip_id = veri.get("irsaliye_satiri_id"), veri.get("siparis_satiri_id")
                if irs_id:
                    kaynak = session.get(AlisIrsaliyesiSatiri, int(irs_id))
                    if not kaynak or miktar > kaynak.miktar - kaynak.faturalanan_miktar:
                        raise ValueError("Fatura miktarı irsaliyenin kalan miktarından büyük olamaz.")
                    kaynak.faturalanan_miktar += miktar
                    kaynak.fatura_belge_baglantisi = fatura.fatura_no
                    if kaynak.siparis_satiri_id:
                        siparis_satiri = session.get(AlisSiparisiSatiri, kaynak.siparis_satiri_id)
                        if siparis_satiri:
                            if miktar > siparis_satiri.miktar - siparis_satiri.faturalanan_miktar:
                                raise ValueError("Fatura miktarı siparişin kalan miktarından büyük olamaz.")
                            siparis_satiri.faturalanan_miktar += miktar
                            siparis_satiri.fatura_belge_baglantisi = fatura.fatura_no
                        sip_id = kaynak.siparis_satiri_id
                elif sip_id:
                    kaynak = session.get(AlisSiparisiSatiri, int(sip_id))
                    if not kaynak or miktar > kaynak.miktar - kaynak.faturalanan_miktar:
                        raise ValueError("Fatura miktarı siparişin kalan miktarından büyük olamaz.")
                    kaynak.faturalanan_miktar += miktar
                    kaynak.fatura_belge_baglantisi = fatura.fatura_no

                birim_maliyet = AlisFaturasiService._net_birim_maliyet(birim_fiyat, iskonto_orani)
                if veri.get("fifo_birim_maliyeti") not in (None, "", 0, "0"):
                    birim_maliyet = decimal(veri["fifo_birim_maliyeti"], "FIFO maliyet", Decimal("0"))

                stok_girisi = StokService.fatura_girisi(
                    session,
                    fatura.fatura_no,
                    tarih,
                    veri["urun_kodu"].strip(),
                    fatura.depo,
                    miktar,
                    birim_maliyet,
                    tedarikci=tedarikci_adi,
                    lot_no=veri.get("lot_no") or "",
                )
                fatura.satirlar.append(
                    AlisFaturasiSatiri(
                        siparis_satiri_id=sip_id,
                        irsaliye_satiri_id=irs_id,
                        urun_kodu=veri["urun_kodu"].strip(),
                        urun_adi=veri["urun_adi"].strip(),
                        barkod=veri.get("barkod") or None,
                        aciklama=veri.get("aciklama") or None,
                        lot_no=veri.get("lot_no") or None,
                        lot_girisi=stok_girisi["lot_girisi"],
                        miktar=miktar,
                        birim=veri.get("birim") or "Adet",
                        birim_fiyat=birim_fiyat,
                        iskonto_orani=iskonto_orani,
                        kdv_orani=decimal(veri.get("kdv_orani", 20), "KDV", Decimal("0")),
                        fifo_birim_maliyeti=stok_girisi["birim_maliyet"],
                    )
                )

            toplam = AlisFaturasiService.toplam(fatura.satirlar)["genel_toplam"]
            if fatura.odeme_tutari > toplam:
                raise ValueError("Ödeme tutarı fatura toplamından büyük olamaz.")
            fatura.durum = "KAPALI" if fatura.odeme_tutari >= toplam else "AÇIK"
            session.flush()

            hareket = session.scalar(select(SatisHareketi).where(SatisHareketi.belge_no == fatura.fatura_no))
            if not hareket:
                hareket = SatisHareketi(cari_id=fatura.cari_id, belge_no=fatura.fatura_no)
                session.add(hareket)
            hareket.cari_id = fatura.cari_id
            hareket.satis_tarihi = tarih
            hareket.satis_tutari = toplam
            hareket.kalan_acik_tutar = toplam - fatura.odeme_tutari

            FinansService.fatura_odemesi(
                session,
                fatura.fatura_no,
                tarih,
                fatura.odeme_tutari,
                fatura.odeme_sekli,
                fatura.odeme_hesabi,
            )
            AlisFaturasiService._durumlari_guncelle(session, fatura)
            try:
                session.flush()
            except IntegrityError as hata:
                raise ValueError("Fatura kaydedilemedi.") from hata
            return fatura

    @staticmethod
    def iptal_et(fatura_id):
        with get_session() as session:
            fatura = session.scalar(
                select(AlisFaturasi)
                .options(selectinload(AlisFaturasi.satirlar))
                .where(AlisFaturasi.id == fatura_id)
            )
            if not fatura:
                raise ValueError("Fatura bulunamadı.")
            if fatura.durum != "İPTAL":
                AlisFaturasiService._baglantilari_geri_al(session, fatura.satirlar)
                StokService.fatura_girislerini_geri_al(session, fatura.fatura_no)
                FinansService.fatura_odemesini_geri_al(session, fatura.fatura_no)
                session.execute(delete(SatisHareketi).where(SatisHareketi.belge_no == fatura.fatura_no))
                fatura.durum = "İPTAL"
                AlisFaturasiService._durumlari_guncelle(session, fatura)

    @staticmethod
    def _baglantilari_geri_al(session, satirlar):
        for satir in satirlar:
            if satir.irsaliye_satiri_id:
                kaynak = session.get(AlisIrsaliyesiSatiri, satir.irsaliye_satiri_id)
                if kaynak:
                    kaynak.faturalanan_miktar = max(Decimal("0"), kaynak.faturalanan_miktar - satir.miktar)
                    if kaynak.siparis_satiri_id:
                        siparis_satiri = session.get(AlisSiparisiSatiri, kaynak.siparis_satiri_id)
                        if siparis_satiri:
                            siparis_satiri.faturalanan_miktar = max(
                                Decimal("0"), siparis_satiri.faturalanan_miktar - satir.miktar
                            )
            elif satir.siparis_satiri_id:
                kaynak = session.get(AlisSiparisiSatiri, satir.siparis_satiri_id)
                if kaynak:
                    kaynak.faturalanan_miktar = max(Decimal("0"), kaynak.faturalanan_miktar - satir.miktar)

    @staticmethod
    def _durumlari_guncelle(session, fatura):
        from database.alis_siparisi_service import AlisSiparisiService

        siparis_id = fatura.siparis_id
        if fatura.irsaliye_id:
            belge = session.scalar(
                select(AlisIrsaliyesi)
                .options(selectinload(AlisIrsaliyesi.satirlar))
                .where(AlisIrsaliyesi.id == fatura.irsaliye_id)
            )
            if belge:
                kalan = [s.miktar - s.faturalanan_miktar for s in belge.satirlar]
                belge.durum = (
                    "FATURALANDI" if kalan and all(x <= 0 for x in kalan)
                    else "KISMİ FATURALANDI" if any(s.faturalanan_miktar > 0 for s in belge.satirlar)
                    else "AÇIK"
                )
                if not siparis_id:
                    siparis_id = belge.siparis_id
        AlisSiparisiService.durumu_guncelle(session, siparis_id)

    @staticmethod
    def toplam(satirlar):
        ara = iskonto = kdv = Decimal("0")
        for satir in satirlar:
            get = satir.get if isinstance(satir, dict) else lambda a, d=0: getattr(satir, a, d)
            miktar, fiyat = decimal(get("miktar"), "Miktar"), decimal(get("birim_fiyat"), "Birim fiyat")
            indirim = miktar * fiyat * decimal(get("iskonto_orani", 0), "İskonto") / Decimal("100")
            net = miktar * fiyat - indirim
            ara += miktar * fiyat
            iskonto += indirim
            kdv += net * decimal(get("kdv_orani", 0), "KDV") / Decimal("100")
        return {"ara_toplam": ara, "iskonto": iskonto, "kdv": kdv, "genel_toplam": ara - iskonto + kdv}

    @staticmethod
    def bakiye_ozeti(cari_id, eklenecek=Decimal("0"), vade=None, haric_fatura_no=None):
        with get_session() as session:
            hs = session.scalars(
                select(SatisHareketi).where(
                    SatisHareketi.cari_id == cari_id, SatisHareketi.kalan_acik_tutar > 0
                )
            ).all()
            faturalar = session.scalars(
                select(AlisFaturasi)
                .where(AlisFaturasi.cari_id == cari_id, AlisFaturasi.durum != "İPTAL")
                .options(selectinload(AlisFaturasi.satirlar))
            ).all()
            fatura_nolari = {f.fatura_no for f in faturalar}
            bakiye = Decimal("0")
            agirlik = Decimal("0")
            for fatura in faturalar:
                if fatura.fatura_no == haric_fatura_no:
                    continue
                acik = AlisFaturasiService.toplam(fatura.satirlar)["genel_toplam"] - fatura.odeme_tutari
                if acik > 0:
                    bakiye += acik
                    agirlik += Decimal(fatura.vade_tarihi.toordinal()) * acik
            for h in hs:
                if h.belge_no in fatura_nolari or h.belge_no == haric_fatura_no:
                    continue
                if not str(h.belge_no).startswith("AFAT-"):
                    continue
                bakiye += h.kalan_acik_tutar
                agirlik += Decimal(h.satis_tarihi.toordinal()) * h.kalan_acik_tutar
            bakiye += eklenecek
            if eklenecek > 0:
                agirlik += Decimal((vade or date.today()).toordinal()) * eklenecek
            return {"bakiye": bakiye, "ortalama_vade": date.fromordinal(int(agirlik / bakiye)) if bakiye > 0 else None}

    @staticmethod
    def otomatik_lot_no(firma_adi, tarih=None):
        onek = "".join(c for c in (firma_adi or "").upper() if c.isalnum())[:4] or "LOT"
        return f"{onek}-{(tarih or date.today()):%Y%m%d}"

    @staticmethod
    def fatura_no():
        return f"AFAT-{datetime.now():%Y%m%d%H%M%S%f}"
