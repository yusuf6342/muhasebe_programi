from datetime import date, datetime
from decimal import Decimal, ROUND_HALF_UP
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import selectinload

from database.database import get_session
from database.models.cari import Cari, SatisHareketi
from database.models.satis_faturasi import SatisFaturasi, SatisFaturasiSatiri, SatisFaturasiTahsilati
from database.models.satis_irsaliyesi import SatisIrsaliyesi, SatisIrsaliyesiSatiri
from database.models.satis_siparisi import SatisSiparisi, SatisSiparisiSatiri
from database.satis_siparisi_service import decimal
from database.stok_service import StokService
from database.finans_service import FinansService

FATURA_DURUMLARI = ("AÇIK", "KAPALI", "İPTAL")
TAHSILAT_SEKILLERI = ("NAKİT / KASA", "GELEN HAVALE", "KREDİ KARTIYLA TAHSİLAT")


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
                selectinload(SatisFaturasi.irsaliye), selectinload(SatisFaturasi.satirlar),
                selectinload(SatisFaturasi.tahsilatlar),
            ).where(SatisFaturasi.id == fatura_id))

    @staticmethod
    def acik_siparisler(cari_id=None):
        with get_session() as session:
            statement = (
                select(SatisSiparisi)
                .where(
                    SatisSiparisi.durum.notin_(("İPTAL", "FATURALI")),
                )
                .options(
                    selectinload(SatisSiparisi.cari),
                    selectinload(SatisSiparisi.satirlar),
                )
                .order_by(SatisSiparisi.id.desc())
            )
            if cari_id is not None:
                statement = statement.where(SatisSiparisi.cari_id == int(cari_id))
            siparisler = list(session.scalars(statement).all())
            # Faturalanacak kalan miktarı olanlar
            return [
                s
                for s in siparisler
                if any(
                    (satir.miktar or 0) - (satir.faturalanan_miktar or 0) > 0
                    for satir in (s.satirlar or [])
                )
            ]

    @staticmethod
    def acik_irsaliyeler(cari_id=None, siparis_id=None):
        with get_session() as session:
            statement = (
                select(SatisIrsaliyesi)
                .where(SatisIrsaliyesi.durum.in_(("AÇIK", "KISMİ FATURALANDI")))
                .options(
                    selectinload(SatisIrsaliyesi.cari),
                    selectinload(SatisIrsaliyesi.siparis),
                    selectinload(SatisIrsaliyesi.satirlar),
                )
                .order_by(SatisIrsaliyesi.id.desc())
            )
            if cari_id is not None:
                statement = statement.where(SatisIrsaliyesi.cari_id == int(cari_id))
            if siparis_id is not None:
                statement = statement.where(SatisIrsaliyesi.siparis_id == int(siparis_id))
            return list(session.scalars(statement).all())

    @staticmethod
    def kaydet(veriler, satir_verileri, fatura_id=None, tahsilat_verileri=None):
        tarih, vade = veriler["fatura_tarihi"], veriler["vade_tarihi"]
        if tarih > date.today(): raise ValueError("Fatura tarihi gelecek bir tarih olamaz.")
        if vade < tarih: raise ValueError("Vade tarihi fatura tarihinden önce olamaz.")
        if not satir_verileri: raise ValueError("En az bir fatura satırı ekleyin.")
        tahsilat_verileri = list(tahsilat_verileri or [])
        with get_session() as session:
            if fatura_id:
                fatura = session.get(SatisFaturasi, fatura_id)
                if not fatura: raise ValueError("Fatura bulunamadı.")
                if fatura.durum == "İPTAL": raise ValueError("İptal edilmiş fatura düzenlenemez.")
                SatisFaturasiService._baglantilari_geri_al(session, fatura.satirlar)
                StokService.fatura_cikislarini_geri_al(session, fatura.fatura_no)
                FinansService.fatura_tahsilatini_geri_al(session, fatura.fatura_no)
                fatura.satirlar.clear()
                fatura.tahsilatlar.clear()
            else:
                fatura = SatisFaturasi(
                    fatura_no=(veriler.get("fatura_no") or "").strip() or SatisFaturasiService.fatura_no()
                )
                session.add(fatura)
            fatura.fatura_tarihi, fatura.vade_tarihi = tarih, vade
            fatura.vade_gunu = (vade - tarih).days
            fatura.islem_saati = (veriler.get("islem_saati") or "").strip() or datetime.now().strftime("%H:%M")
            for alan in ("cari_id", "siparis_id", "irsaliye_id", "depo", "aciklama", "dokuman_yolu"):
                setattr(fatura, alan, veriler.get(alan) or (("ANA DEPO" if alan == "depo" else None)))
            fatura.cari_id = int(veriler["cari_id"])
            for veri in satir_verileri:
                miktar = decimal(veri["miktar"], "Miktar", Decimal("0.0001"))
                irs_id, sip_id = veri.get("irsaliye_satiri_id"), veri.get("siparis_satiri_id")
                if irs_id:
                    kaynak = session.get(SatisIrsaliyesiSatiri, int(irs_id))
                    if not kaynak or miktar > kaynak.miktar - kaynak.faturalanan_miktar:
                        raise ValueError("Fatura miktarı irsaliyenin kalan miktarından büyük olamaz.")
                    kaynak.faturalanan_miktar += miktar
                    kaynak.fatura_belge_baglantisi = fatura.fatura_no
                    if kaynak.siparis_satiri_id:
                        siparis_satiri = session.get(SatisSiparisiSatiri, kaynak.siparis_satiri_id)
                        if siparis_satiri:
                            if miktar > siparis_satiri.miktar - siparis_satiri.faturalanan_miktar:
                                raise ValueError("Fatura miktarı siparişin kalan miktarından büyük olamaz.")
                            siparis_satiri.faturalanan_miktar += miktar
                            siparis_satiri.fatura_belge_baglantisi = fatura.fatura_no
                        sip_id = kaynak.siparis_satiri_id
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
                    iskonto_orani=decimal(veri.get("iskonto_orani", 0), "İskonto 1", Decimal("0")),
                    iskonto_orani_2=decimal(veri.get("iskonto_orani_2", 0), "İskonto 2", Decimal("0")),
                    iskonto_orani_3=decimal(veri.get("iskonto_orani_3", 0), "İskonto 3", Decimal("0")),
                    kdv_orani=decimal(veri.get("kdv_orani", 20), "KDV", Decimal("0")),
                    fifo_birim_maliyeti=stok_cikisi["fifo_birim_maliyeti"],
                    son_alis_birim_maliyeti=decimal(veri.get("son_alis_birim_maliyeti", 0), "Son alış maliyeti", Decimal("0")),
                    ortalama_birim_maliyeti=decimal(veri.get("ortalama_birim_maliyeti", 0), "Ortalama maliyet", Decimal("0")),
                    agirlikli_ortalama_birim_maliyeti=decimal(veri.get("agirlikli_ortalama_birim_maliyeti", 0), "Ağırlıklı maliyet", Decimal("0")),
                ))

            tahsilat_toplam = Decimal("0")
            for veri in tahsilat_verileri:
                tutar = decimal(veri["tutar"], "Tahsilat tutarı", Decimal("0.01"))
                odeme_sekli = (veri.get("odeme_sekli") or "").strip()
                hesap = (veri.get("hesap") or "").strip()
                if not odeme_sekli:
                    raise ValueError("Tahsilat ödeme şekli zorunludur.")
                if not hesap:
                    raise ValueError("Tahsilat hesabı zorunludur.")
                tahsilat_tarihi = veri.get("tahsilat_tarihi") or tarih
                if hasattr(tahsilat_tarihi, "strftime"):
                    pass
                else:
                    tahsilat_tarihi = tarih
                tahsilat_toplam += tutar
                fatura.tahsilatlar.append(
                    SatisFaturasiTahsilati(
                        tahsilat_tarihi=tahsilat_tarihi,
                        tutar=tutar,
                        odeme_sekli=odeme_sekli,
                        hesap=hesap,
                        aciklama=(veri.get("aciklama") or None),
                    )
                )

            # Eski tek alanlarla uyumluluk: özet tutar + ilk satırın şekil/hesabı
            if not tahsilat_verileri and veriler.get("tahsilat_tutari") is not None:
                tahsilat_toplam = decimal(veriler.get("tahsilat_tutari", 0), "Tahsilat", Decimal("0"))
                if tahsilat_toplam > 0:
                    sekil = (veriler.get("tahsilat_sekli") or TAHSILAT_SEKILLERI[0]).strip()
                    hesap = (veriler.get("tahsilat_hesabi") or "").strip()
                    if not hesap:
                        raise ValueError("Tahsilat hesabı zorunludur.")
                    fatura.tahsilatlar.append(
                        SatisFaturasiTahsilati(
                            tahsilat_tarihi=tarih,
                            tutar=tahsilat_toplam,
                            odeme_sekli=sekil,
                            hesap=hesap,
                            aciklama="Fatura tahsilatı",
                        )
                    )

            toplam = SatisFaturasiService.toplam(fatura.satirlar)["genel_toplam"]
            if tahsilat_toplam > toplam:
                raise ValueError("Toplam tahsilat fatura tutarını aşamaz.")
            fatura.tahsilat_tutari = tahsilat_toplam
            ilk = fatura.tahsilatlar[0] if fatura.tahsilatlar else None
            fatura.tahsilat_sekli = ilk.odeme_sekli if ilk else None
            fatura.tahsilat_hesabi = ilk.hesap if ilk else None
            fatura.durum = "KAPALI" if tahsilat_toplam >= toplam else "AÇIK"
            session.flush()
            hareket = session.scalar(select(SatisHareketi).where(SatisHareketi.belge_no == fatura.fatura_no))
            if not hareket:
                hareket = SatisHareketi(cari_id=fatura.cari_id, belge_no=fatura.fatura_no)
                session.add(hareket)
            hareket.cari_id, hareket.satis_tarihi = fatura.cari_id, tarih
            hareket.satis_tutari, hareket.kalan_acik_tutar = toplam, toplam - tahsilat_toplam
            for th in fatura.tahsilatlar:
                FinansService.fatura_tahsilati(
                    session,
                    fatura.fatura_no,
                    th.tahsilat_tarihi,
                    th.tutar,
                    th.odeme_sekli,
                    th.hesap,
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
            if satir.irsaliye_satiri_id:
                kaynak = session.get(SatisIrsaliyesiSatiri, satir.irsaliye_satiri_id)
                if kaynak:
                    kaynak.faturalanan_miktar = max(Decimal("0"), kaynak.faturalanan_miktar - satir.miktar)
                    if kaynak.siparis_satiri_id:
                        siparis_satiri = session.get(SatisSiparisiSatiri, kaynak.siparis_satiri_id)
                        if siparis_satiri:
                            siparis_satiri.faturalanan_miktar = max(
                                Decimal("0"), siparis_satiri.faturalanan_miktar - satir.miktar
                            )
            elif satir.siparis_satiri_id:
                kaynak = session.get(SatisSiparisiSatiri, satir.siparis_satiri_id)
                if kaynak:
                    kaynak.faturalanan_miktar = max(Decimal("0"), kaynak.faturalanan_miktar - satir.miktar)

    @staticmethod
    def _durumlari_guncelle(session, fatura):
        from database.satis_siparisi_service import SatisSiparisiService

        siparis_id = fatura.siparis_id
        if fatura.irsaliye_id:
            belge = session.scalar(select(SatisIrsaliyesi).options(selectinload(SatisIrsaliyesi.satirlar)).where(SatisIrsaliyesi.id == fatura.irsaliye_id))
            if belge:
                kalan = [s.miktar - s.faturalanan_miktar for s in belge.satirlar]
                belge.durum = (
                    "FATURALANDI" if kalan and all(x <= 0 for x in kalan)
                    else "KISMİ FATURALANDI" if any(s.faturalanan_miktar > 0 for s in belge.satirlar)
                    else "AÇIK"
                )
                if not siparis_id:
                    siparis_id = belge.siparis_id
        SatisSiparisiService.durumu_guncelle(session, siparis_id)

    @staticmethod
    def _satir_net(miktar, fiyat, iskonto1=0, iskonto2=0, iskonto3=0):
        """Üç kademeli (ardışık) iskonto ile net tutar."""
        brut = miktar * fiyat
        net = brut
        for sira, oran in enumerate((iskonto1, iskonto2, iskonto3), start=1):
            o = decimal(oran or 0, f"İskonto {sira}", Decimal("0"))
            if o < 0 or o > 100:
                raise ValueError(f"İskonto {sira} 0-100 arasında olmalıdır.")
            net = net * (Decimal("1") - o / Decimal("100"))
        return brut, brut - net, net

    @staticmethod
    def urun_satis_hareketleri(urun_kodu: str, cari_id: int | None = None) -> list[dict[str, Any]]:
        """Ürün satış fatura satırları (yeniden eskiye). cari_id verilirse yalnızca o müşteri."""
        urun_kodu = (urun_kodu or "").strip()
        if not urun_kodu:
            return []
        with get_session() as session:
            statement = (
                select(SatisFaturasiSatiri)
                .join(SatisFaturasi)
                .where(
                    SatisFaturasi.durum != "İPTAL",
                    SatisFaturasiSatiri.urun_kodu == urun_kodu,
                )
                .options(
                    selectinload(SatisFaturasiSatiri.fatura).selectinload(SatisFaturasi.cari),
                )
                .order_by(SatisFaturasi.fatura_tarihi.desc(), SatisFaturasiSatiri.id.desc())
            )
            if cari_id is not None:
                statement = statement.where(SatisFaturasi.cari_id == int(cari_id))
            kayitlar = []
            for satir in session.scalars(statement).all():
                miktar = Decimal(str(satir.miktar or 0))
                fiyat = Decimal(str(satir.birim_fiyat or 0))
                _, _, net_toplam = SatisFaturasiService._satir_net(
                    miktar,
                    fiyat,
                    satir.iskonto_orani,
                    getattr(satir, "iskonto_orani_2", 0) or 0,
                    getattr(satir, "iskonto_orani_3", 0) or 0,
                )
                net_birim = (net_toplam / miktar) if miktar else Decimal("0")
                cari = satir.fatura.cari if satir.fatura else None
                kayitlar.append({
                    "tarih": satir.fatura.fatura_tarihi if satir.fatura else None,
                    "belge_no": satir.fatura.fatura_no if satir.fatura else "",
                    "musteri": f"{cari.cari_kodu} - {cari.unvan}" if cari else "",
                    "miktar": miktar,
                    "birim": satir.birim or "",
                    "net_fiyat": net_birim,
                })
            return kayitlar

    @staticmethod
    def toplam(satirlar):
        ara = iskonto = kdv = Decimal("0")
        kurus = Decimal("0.01")
        for satir in satirlar:
            get = satir.get if isinstance(satir, dict) else lambda a, d=0: getattr(satir, a, d)
            miktar = decimal(get("miktar"), "Miktar")
            fiyat = decimal(get("birim_fiyat", get("birim_satis_fiyati", 0)), "Birim fiyat")
            brut, indirim, net = SatisFaturasiService._satir_net(
                miktar,
                fiyat,
                get("iskonto_orani", 0),
                get("iskonto_orani_2", 0),
                get("iskonto_orani_3", 0),
            )
            net = net.quantize(kurus, rounding=ROUND_HALF_UP)
            satir_kdv = (net * decimal(get("kdv_orani", 0), "KDV") / Decimal("100")).quantize(
                kurus, rounding=ROUND_HALF_UP
            )
            ara += brut.quantize(kurus, rounding=ROUND_HALF_UP)
            iskonto += indirim.quantize(kurus, rounding=ROUND_HALF_UP)
            kdv += satir_kdv
        ara = ara.quantize(kurus, rounding=ROUND_HALF_UP)
        iskonto = iskonto.quantize(kurus, rounding=ROUND_HALF_UP)
        kdv = kdv.quantize(kurus, rounding=ROUND_HALF_UP)
        genel = (ara - iskonto + kdv).quantize(kurus, rounding=ROUND_HALF_UP)
        return {"ara_toplam": ara, "iskonto": iskonto, "kdv": kdv, "genel_toplam": genel}

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
        """SF-00001 formatında artan satış fatura numarası."""
        onek = "SF-"
        with get_session() as session:
            numaralar = session.scalars(
                select(SatisFaturasi.fatura_no).where(SatisFaturasi.fatura_no.like(f"{onek}%"))
            ).all()
            max_sira = 0
            for no in numaralar:
                kuyruk = str(no)[len(onek):]
                if kuyruk.isdigit():
                    max_sira = max(max_sira, int(kuyruk))
            return f"{onek}{max_sira + 1:05d}"
