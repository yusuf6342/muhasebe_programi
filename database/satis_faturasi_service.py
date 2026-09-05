from datetime import date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import selectinload

from database.database import get_session
from database.models.cari import Cari, SatisHareketi
from database.models.satis_faturasi import SatisFaturasi, SatisFaturasiSatiri
from database.models.satis_irsaliyesi import SatisIrsaliyesi, SatisIrsaliyesiSatiri
from database.models.satis_siparisi import SatisSiparisi, SatisSiparisiSatiri
from database.satis_siparisi_service import decimal
from database.stok_service import StokService
from database.finans_service import FinansService

FATURA_DURUMLARI = ("AÇIK", "KAPALI", "İPTAL")
TAHSILAT_SEKILLERI = ("KASA TAHSİLAT", "ALINAN HAVALE", "KREDİ KARTIYLA TAHSİLAT")


class SatisFaturasiService:
    @staticmethod
    def aktif_musterileri():
        with get_session() as session:
            return list(session.scalars(select(Cari).where(Cari.aktif.is_(True)).order_by(Cari.cari_kodu)).all())

    @staticmethod
    def listele() -> list[dict[str, Any]]:
        with get_session() as session:
            faturalar = session.scalars(select(SatisFaturasi).options(
                selectinload(SatisFaturasi.cari), selectinload(SatisFaturasi.satirlar),
                selectinload(SatisFaturasi.siparis), selectinload(SatisFaturasi.irsaliye)
            ).order_by(SatisFaturasi.id.desc())).all()
            return [{"fatura": f, **SatisFaturasiService.toplam(f.satirlar)} for f in faturalar]

    @staticmethod
    def getir(fatura_id):
        with get_session() as session:
            return session.scalar(select(SatisFaturasi).options(
                selectinload(SatisFaturasi.cari), selectinload(SatisFaturasi.siparis),
                selectinload(SatisFaturasi.irsaliye), selectinload(SatisFaturasi.satirlar)
            ).where(SatisFaturasi.id == fatura_id))

    @staticmethod
    def acik_siparisler():
        with get_session() as session:
            return list(session.scalars(select(SatisSiparisi).where(SatisSiparisi.durum != "İPTAL").options(
                selectinload(SatisSiparisi.cari), selectinload(SatisSiparisi.satirlar)
            ).order_by(SatisSiparisi.id.desc())).all())

    @staticmethod
    def acik_irsaliyeler():
        with get_session() as session:
            return list(session.scalars(select(SatisIrsaliyesi).where(
                SatisIrsaliyesi.durum.in_(("AÇIK", "KISMİ FATURALANDI"))
            ).options(selectinload(SatisIrsaliyesi.cari), selectinload(SatisIrsaliyesi.satirlar)
            ).order_by(SatisIrsaliyesi.id.desc())).all())

    @staticmethod
    def kaydet(veriler, satir_verileri, fatura_id=None):
        tarih, vade = veriler["fatura_tarihi"], veriler["vade_tarihi"]
        if tarih > date.today(): raise ValueError("Fatura tarihi gelecek bir tarih olamaz.")
        if vade < tarih: raise ValueError("Vade tarihi fatura tarihinden önce olamaz.")
        if not satir_verileri: raise ValueError("En az bir fatura satırı ekleyin.")
        with get_session() as session:
            if fatura_id:
                fatura = session.get(SatisFaturasi, fatura_id)
                if not fatura: raise ValueError("Fatura bulunamadı.")
                if fatura.durum == "İPTAL": raise ValueError("İptal edilmiş fatura düzenlenemez.")
                SatisFaturasiService._baglantilari_geri_al(session, fatura.satirlar)
                StokService.fatura_cikislarini_geri_al(session, fatura.fatura_no)
                FinansService.fatura_tahsilatini_geri_al(session, fatura.fatura_no)
                fatura.satirlar.clear()
            else:
                fatura = SatisFaturasi(fatura_no=SatisFaturasiService.fatura_no())
                session.add(fatura)
            fatura.fatura_tarihi, fatura.vade_tarihi = tarih, vade
            fatura.vade_gunu = (vade - tarih).days
            for alan in ("cari_id", "siparis_id", "irsaliye_id", "depo", "tahsilat_sekli", "tahsilat_hesabi", "aciklama", "dokuman_yolu"):
                setattr(fatura, alan, veriler.get(alan) or (("ANA DEPO" if alan == "depo" else None)))
            fatura.cari_id = int(veriler["cari_id"])
            fatura.tahsilat_tutari = decimal(veriler.get("tahsilat_tutari", 0), "Tahsilat", Decimal("0"))
            for veri in satir_verileri:
                miktar = decimal(veri["miktar"], "Miktar", Decimal("0.0001"))
                irs_id, sip_id = veri.get("irsaliye_satiri_id"), veri.get("siparis_satiri_id")
                if irs_id:
                    kaynak = session.get(SatisIrsaliyesiSatiri, int(irs_id))
                    if not kaynak or miktar > kaynak.miktar - kaynak.faturalanan_miktar:
                        raise ValueError("Fatura miktarı irsaliyenin kalan miktarından büyük olamaz.")
                    kaynak.faturalanan_miktar += miktar; kaynak.fatura_belge_baglantisi = fatura.fatura_no
                elif sip_id:
                    kaynak = session.get(SatisSiparisiSatiri, int(sip_id))
                    if not kaynak or miktar > kaynak.miktar - kaynak.faturalanan_miktar:
                        raise ValueError("Fatura miktarı siparişin kalan miktarından büyük olamaz.")
                    kaynak.faturalanan_miktar += miktar; kaynak.fatura_belge_baglantisi = fatura.fatura_no
                stok_cikisi = StokService.fatura_cikisi(
                    session, fatura.fatura_no, tarih, veri["urun_kodu"].strip(),
                    fatura.depo, miktar, veri.get("lot_no") or "",
                )
                fatura.satirlar.append(SatisFaturasiSatiri(
                    siparis_satiri_id=sip_id, irsaliye_satiri_id=irs_id,
                    urun_kodu=veri["urun_kodu"].strip(), urun_adi=veri["urun_adi"].strip(),
                    barkod=veri.get("barkod") or None, aciklama=veri.get("aciklama") or None,
                    lot_no=veri.get("lot_no") or None, lot_cikisi=stok_cikisi["lot_cikisi"],
                    miktar=miktar, birim=veri.get("birim") or "Adet",
                    birim_fiyat=decimal(veri["birim_fiyat"], "Birim fiyat", Decimal("0")),
                    iskonto_orani=decimal(veri.get("iskonto_orani", 0), "İskonto", Decimal("0")),
                    kdv_orani=decimal(veri.get("kdv_orani", 20), "KDV", Decimal("0")),
                    fifo_birim_maliyeti=stok_cikisi["fifo_birim_maliyeti"],
                    son_alis_birim_maliyeti=decimal(veri.get("son_alis_birim_maliyeti", 0), "Son alış maliyeti", Decimal("0")),
                    ortalama_birim_maliyeti=decimal(veri.get("ortalama_birim_maliyeti", 0), "Ortalama maliyet", Decimal("0")),
                    agirlikli_ortalama_birim_maliyeti=decimal(veri.get("agirlikli_ortalama_birim_maliyeti", 0), "Ağırlıklı maliyet", Decimal("0")),
                ))
            toplam = SatisFaturasiService.toplam(fatura.satirlar)["genel_toplam"]
            if fatura.tahsilat_tutari > toplam: raise ValueError("Tahsilat tutarı fatura toplamından büyük olamaz.")
            fatura.durum = "KAPALI" if fatura.tahsilat_tutari >= toplam else "AÇIK"
            session.flush()
            hareket = session.scalar(select(SatisHareketi).where(SatisHareketi.belge_no == fatura.fatura_no))
            if not hareket:
                hareket = SatisHareketi(cari_id=fatura.cari_id, belge_no=fatura.fatura_no)
                session.add(hareket)
            hareket.cari_id, hareket.satis_tarihi = fatura.cari_id, tarih
            hareket.satis_tutari, hareket.kalan_acik_tutar = toplam, toplam - fatura.tahsilat_tutari
            FinansService.fatura_tahsilati(
                session, fatura.fatura_no, tarih, fatura.tahsilat_tutari,
                fatura.tahsilat_sekli, fatura.tahsilat_hesabi,
            )
            SatisFaturasiService._durumlari_guncelle(session, fatura)
            try: session.flush()
            except IntegrityError as hata: raise ValueError("Fatura kaydedilemedi.") from hata
            return fatura

    @staticmethod
    def iptal_et(fatura_id):
        with get_session() as session:
            fatura = session.scalar(select(SatisFaturasi).options(selectinload(SatisFaturasi.satirlar)).where(SatisFaturasi.id == fatura_id))
            if not fatura: raise ValueError("Fatura bulunamadı.")
            if fatura.durum != "İPTAL":
                SatisFaturasiService._baglantilari_geri_al(session, fatura.satirlar)
                StokService.fatura_cikislarini_geri_al(session, fatura.fatura_no)
                FinansService.fatura_tahsilatini_geri_al(session, fatura.fatura_no)
                session.execute(delete(SatisHareketi).where(SatisHareketi.belge_no == fatura.fatura_no))
                fatura.durum = "İPTAL"; SatisFaturasiService._durumlari_guncelle(session, fatura)

    @staticmethod
    def _baglantilari_geri_al(session, satirlar):
        for satir in satirlar:
            cls, kimlik = ((SatisIrsaliyesiSatiri, satir.irsaliye_satiri_id) if satir.irsaliye_satiri_id else (SatisSiparisiSatiri, satir.siparis_satiri_id))
            if kimlik:
                kaynak = session.get(cls, kimlik)
                if kaynak: kaynak.faturalanan_miktar = max(Decimal("0"), kaynak.faturalanan_miktar - satir.miktar)

    @staticmethod
    def _durumlari_guncelle(session, fatura):
        if fatura.irsaliye_id:
            belge = session.scalar(select(SatisIrsaliyesi).options(selectinload(SatisIrsaliyesi.satirlar)).where(SatisIrsaliyesi.id == fatura.irsaliye_id))
            if belge:
                kalan = [s.miktar - s.faturalanan_miktar for s in belge.satirlar]
                belge.durum = "FATURALANDI" if kalan and all(x <= 0 for x in kalan) else "KISMİ FATURALANDI" if any(s.faturalanan_miktar > 0 for s in belge.satirlar) else "AÇIK"
        if fatura.siparis_id and not fatura.irsaliye_id:
            belge = session.scalar(select(SatisSiparisi).options(selectinload(SatisSiparisi.satirlar)).where(SatisSiparisi.id == fatura.siparis_id))
            if belge:
                kalan = [s.miktar - s.faturalanan_miktar for s in belge.satirlar]
                belge.durum = "FATURALANDI" if kalan and all(x <= 0 for x in kalan) else "KISMİ FATURALANDI"

    @staticmethod
    def toplam(satirlar):
        ara = iskonto = kdv = Decimal("0")
        for satir in satirlar:
            get = satir.get if isinstance(satir, dict) else lambda a, d=0: getattr(satir, a, d)
            miktar, fiyat = decimal(get("miktar"), "Miktar"), decimal(get("birim_fiyat"), "Birim fiyat")
            indirim = miktar * fiyat * decimal(get("iskonto_orani", 0), "İskonto") / Decimal("100")
            net = miktar * fiyat - indirim
            ara += miktar * fiyat; iskonto += indirim; kdv += net * decimal(get("kdv_orani", 0), "KDV") / Decimal("100")
        return {"ara_toplam": ara, "iskonto": iskonto, "kdv": kdv, "genel_toplam": ara - iskonto + kdv}

    @staticmethod
    def bakiye_ozeti(cari_id, eklenecek=Decimal("0"), vade=None, haric_fatura_no=None):
        with get_session() as session:
            hs = session.scalars(select(SatisHareketi).where(SatisHareketi.cari_id == cari_id, SatisHareketi.kalan_acik_tutar > 0)).all()
            faturalar = session.scalars(select(SatisFaturasi).where(
                SatisFaturasi.cari_id == cari_id, SatisFaturasi.durum != "İPTAL"
            ).options(selectinload(SatisFaturasi.satirlar))).all()
            fatura_nolari = {f.fatura_no for f in faturalar}
            bakiye = Decimal("0"); agirlik = Decimal("0")
            for fatura in faturalar:
                if fatura.fatura_no == haric_fatura_no: continue
                acik = SatisFaturasiService.toplam(fatura.satirlar)["genel_toplam"] - fatura.tahsilat_tutari
                if acik > 0:
                    bakiye += acik; agirlik += Decimal(fatura.vade_tarihi.toordinal()) * acik
            for h in hs:
                if h.belge_no in fatura_nolari or h.belge_no == haric_fatura_no: continue
                bakiye += h.kalan_acik_tutar
                agirlik += Decimal(h.satis_tarihi.toordinal()) * h.kalan_acik_tutar
            bakiye += eklenecek
            if eklenecek > 0: agirlik += Decimal((vade or date.today()).toordinal()) * eklenecek
            return {"bakiye": bakiye, "ortalama_vade": date.fromordinal(int(agirlik / bakiye)) if bakiye > 0 else None}

    @staticmethod
    def otomatik_lot_no(firma_adi, tarih=None):
        onek = "".join(c for c in (firma_adi or "").upper() if c.isalnum())[:4] or "LOT"
        return f"{onek}-{(tarih or date.today()):%Y%m%d}"

    @staticmethod
    def fatura_no():
        return f"FAT-{datetime.now():%Y%m%d%H%M%S%f}"
