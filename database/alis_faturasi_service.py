from datetime import date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import selectinload

from database.database import get_session
from database.access import yazma_zorunlu
from database.finans_service import FinansService
from database.models.cari import Cari, SatisHareketi
from database.models.alis_faturasi import AlisFaturasi, AlisFaturasiSatiri
from database.models.alis_irsaliyesi import AlisIrsaliyesi, AlisIrsaliyesiSatiri
from database.models.alis_siparisi import AlisSiparisi, AlisSiparisiSatiri
from database.satis_siparisi_service import decimal
from database.doviz_service import DovizService
from database.stok_service import StokService

FATURA_DURUMLARI = ("AÇIK", "KAPALI", "İPTAL")
ODEME_SEKILLERI = ("KASA ÖDEME", "GÖNDERİLEN HAVALE", "KREDİ KARTIYLA ÖDEME")


class AlisFaturasiService:
    @staticmethod
    def aktif_tedarikcileri():
        from database.alis_siparisi_service import AlisSiparisiService
        return AlisSiparisiService.aktif_tedarikcileri()

    @staticmethod
    def urun_alis_hareketleri(urun_kodu: str) -> list[dict[str, Any]]:
        """Ürün alış fatura satırları (yeniden eskiye)."""
        urun_kodu = (urun_kodu or "").strip()
        if not urun_kodu:
            return []
        with get_session() as session:
            satirlar = session.scalars(
                select(AlisFaturasiSatiri)
                .join(AlisFaturasi)
                .where(
                    AlisFaturasi.durum != "İPTAL",
                    AlisFaturasiSatiri.urun_kodu == urun_kodu,
                )
                .options(
                    selectinload(AlisFaturasiSatiri.fatura).selectinload(AlisFaturasi.cari),
                )
                .order_by(AlisFaturasi.fatura_tarihi.desc(), AlisFaturasiSatiri.id.desc())
            ).all()
            kayitlar = []
            for satir in satirlar:
                fiyat = Decimal(str(satir.birim_fiyat or 0))
                net = AlisFaturasiService._net_birim_maliyet(
                    fiyat,
                    Decimal(str(satir.iskonto_orani or 0)),
                    getattr(satir, "iskonto_orani_2", 0) or 0,
                    getattr(satir, "iskonto_orani_3", 0) or 0,
                )
                cari = satir.fatura.cari if satir.fatura else None
                kayitlar.append({
                    "tarih": satir.fatura.fatura_tarihi if satir.fatura else None,
                    "belge_no": satir.fatura.fatura_no if satir.fatura else "",
                    "tedarikci": f"{cari.cari_kodu} - {cari.unvan}" if cari else "",
                    "miktar": Decimal(str(satir.miktar or 0)),
                    "birim": satir.birim or "",
                    "net_fiyat": net,
                })
            return kayitlar

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
    def listele_ozet(tarih_bas=None, tarih_bit=None) -> list[dict[str, Any]]:
        """Liste penceresi için hızlı özet (satır yüklemez)."""
        from sqlalchemy.orm import joinedload

        with get_session() as session:
            statement = (
                select(AlisFaturasi)
                .options(joinedload(AlisFaturasi.cari))
                .order_by(AlisFaturasi.fatura_tarihi.desc(), AlisFaturasi.id.desc())
            )
            # Soft-delete varsa hariç tut
            if hasattr(AlisFaturasi, "is_deleted"):
                from sqlalchemy import or_

                statement = statement.where(
                    or_(AlisFaturasi.is_deleted.is_(False), AlisFaturasi.is_deleted.is_(None))
                )
            if tarih_bas is not None:
                statement = statement.where(AlisFaturasi.fatura_tarihi >= tarih_bas)
            if tarih_bit is not None:
                statement = statement.where(AlisFaturasi.fatura_tarihi <= tarih_bit)
            faturalar = list(session.scalars(statement).unique().all())
            sonuc = []
            for f in faturalar:
                genel = Decimal(str(getattr(f, "tl_genel_toplam", 0) or 0))
                cari = f.cari
                sonuc.append({
                    "id": f.id,
                    "fatura_no": f.fatura_no or "",
                    "fatura_tarihi": f.fatura_tarihi,
                    "cari_kodu": (cari.cari_kodu if cari else "") or "",
                    "cari_ad": (cari.unvan if cari else "") or "",
                    "vergi_no": (getattr(cari, "vergi_no", None) or "") if cari else "",
                    "durum": f.durum or "",
                    "genel_toplam": genel,
                    "matrah": Decimal(str(getattr(f, "tl_matrah", 0) or 0)),
                    "kdv": Decimal(str(getattr(f, "tl_kdv", 0) or 0)),
                    "para_birimi": (getattr(f, "para_birimi", None) or "TRY"),
                    "olusturma_tarihi": getattr(f, "olusturma_tarihi", None),
                    "created_by_full_name": getattr(f, "created_by_full_name", None),
                    "document_type": "PURCHASE_INVOICE",
                })
            return sonuc

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
    def _net_birim_maliyet(birim_fiyat: Decimal, iskonto_orani: Decimal, iskonto2=0, iskonto3=0) -> Decimal:
        """İskonto sonrası (KDV öncesi) birim maliyet — üç kademeli."""
        from database.iskonto_hesap_service import iskonto_carpani

        return Decimal(str(birim_fiyat or 0)) * iskonto_carpani(
            iskonto_orani, iskonto2, iskonto3
        )

    @staticmethod
    def kaydet(veriler, satir_verileri, fatura_id=None):
        yazma_zorunlu("alis_fatura_duzenleme", "alis_duzenleme", "yeni_kayit")
        tarih, vade = veriler["fatura_tarihi"], veriler["vade_tarihi"]
        if tarih > date.today():
            raise ValueError("Fatura tarihi gelecek bir tarih olamaz.")
        if vade < tarih:
            raise ValueError("Vade tarihi fatura tarihinden önce olamaz.")
        if not satir_verileri:
            raise ValueError("En az bir fatura satırı ekleyin.")
        beklenen_versiyon = veriler.get("row_version")
        with get_session() as session:
            if fatura_id:
                fatura = session.get(AlisFaturasi, fatura_id)
                if not fatura:
                    raise ValueError("Fatura bulunamadı.")
                if fatura.durum == "İPTAL":
                    raise ValueError("İptal edilmiş fatura düzenlenemez.")
                mevcut_v = int(getattr(fatura, "row_version", 1) or 1)
                if beklenen_versiyon is not None and int(beklenen_versiyon) != mevcut_v:
                    raise ValueError(
                        "Bu fatura başka bir kullanıcı tarafından değiştirilmiş. "
                        "Listeyi yenileyip tekrar açın."
                    )
                AlisFaturasiService._baglantilari_geri_al(session, fatura.satirlar)
                StokService.fatura_girislerini_geri_al(session, fatura.fatura_no)
                FinansService.fatura_odemesini_geri_al(session, fatura.fatura_no)
                fatura.satirlar.clear()
                fatura.row_version = mevcut_v + 1
            else:
                fatura = AlisFaturasi(
                    fatura_no=(veriler.get("fatura_no") or "").strip() or AlisFaturasiService.fatura_no(),
                    row_version=1,
                )
                session.add(fatura)
            fatura.fatura_tarihi, fatura.vade_tarihi = tarih, vade
            fatura.vade_gunu = (vade - tarih).days
            fatura.islem_saati = (veriler.get("islem_saati") or "").strip() or datetime.now().strftime("%H:%M")
            for alan in ("cari_id", "siparis_id", "irsaliye_id", "depo", "odeme_sekli", "odeme_hesabi", "aciklama", "dokuman_yolu"):
                setattr(fatura, alan, veriler.get(alan) or (("ANA DEPO" if alan == "depo" else None)))
            fatura.cari_id = int(veriler["cari_id"])
            fatura.odeme_tutari = decimal(veriler.get("odeme_tutari", 0), "Ödeme", Decimal("0"))
            pb = (veriler.get("para_birimi") or "TRY").upper()
            kur = decimal(veriler.get("kur", 1), "Kur", Decimal("0.000001"))
            fatura.para_birimi = pb
            fatura.kur = kur
            fatura.kur_tarihi = veriler.get("kur_tarihi")
            fatura.kur_turu = veriler.get("kur_turu") or "forex_selling"
            fatura.kur_kaynagi = veriler.get("kur_kaynagi") or "TCMB"
            fatura.kur_sabitlendi = bool(veriler.get("kur_sabitlendi", pb != "TRY"))

            cari = session.get(Cari, fatura.cari_id)
            tedarikci_adi = cari.unvan if cari else ""

            for veri in satir_verileri:
                miktar = decimal(veri["miktar"], "Miktar", Decimal("0.0001"))
                birim_fiyat_doviz = decimal(
                    veri.get("birim_fiyat_doviz", veri.get("birim_fiyat", 0)),
                    "Birim fiyat",
                    Decimal("0"),
                )
                if pb != "TRY" and birim_fiyat_doviz > 0:
                    birim_fiyat = DovizService.dovizden_tle(birim_fiyat_doviz, kur, Decimal("0.0001"))
                else:
                    birim_fiyat = decimal(veri["birim_fiyat"], "Birim fiyat", Decimal("0"))
                    birim_fiyat_doviz = Decimal("0")
                iskonto_orani = decimal(veri.get("iskonto_orani", 0), "İskonto", Decimal("0"))
                iskonto_orani_2 = decimal(veri.get("iskonto_orani_2", 0), "İskonto 2", Decimal("0"))
                iskonto_orani_3 = decimal(veri.get("iskonto_orani_3", 0), "İskonto 3", Decimal("0"))
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

                birim_maliyet = AlisFaturasiService._net_birim_maliyet(
                    birim_fiyat, iskonto_orani, iskonto_orani_2, iskonto_orani_3
                )
                # Stok kartı ALIŞ FİYATI: faturadaki net iskontolu fiyat (FIFO override'dan bağımsız)
                net_alis_fiyati = birim_maliyet
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
                StokService.alis_fiyatini_guncelle(
                    session,
                    veri["urun_kodu"].strip(),
                    net_alis_fiyati,
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
                        iskonto_orani_2=iskonto_orani_2,
                        iskonto_orani_3=iskonto_orani_3,
                        kdv_orani=decimal(veri.get("kdv_orani", 20), "KDV", Decimal("0")),
                        fifo_birim_maliyeti=stok_girisi["birim_maliyet"],
                        birim_fiyat_doviz=birim_fiyat_doviz,
                        tl_birim_fiyat=birim_maliyet,
                        tl_tutar=(miktar * birim_maliyet).quantize(Decimal("0.01")),
                    )
                )

            toplam_dict = AlisFaturasiService.toplam(fatura.satirlar)
            satir_genel = toplam_dict["genel_toplam"]
            fatura.tl_matrah = toplam_dict["ara_toplam"] - toplam_dict["iskonto"]
            fatura.tl_kdv = toplam_dict["kdv"]
            fatura.tl_brut_toplam = satir_genel
            fatura.tl_genel_toplam = satir_genel
            if hasattr(fatura, "genel_islem_turu"):
                fatura.genel_islem_turu = None
                fatura.genel_islem_orani = Decimal("0")
                fatura.genel_islem_tutari = Decimal("0")
            if hasattr(fatura, "invoice_rounding_adjustment"):
                fatura.invoice_rounding_adjustment = Decimal("0.00")
            if hasattr(fatura, "rounding_applied"):
                fatura.rounding_applied = False
                fatura.rounding_target_total = None
                fatura.rounding_version = int(veriler.get("rounding_version") or 0)
            toplam = fatura.tl_genel_toplam
            if pb != "TRY":
                from database.iskonto_hesap_service import iskonto_carpani

                doviz_ara = Decimal("0")
                for satir in fatura.satirlar:
                    if satir.birim_fiyat_doviz > 0:
                        carp = iskonto_carpani(
                            satir.iskonto_orani,
                            getattr(satir, "iskonto_orani_2", 0) or 0,
                            getattr(satir, "iskonto_orani_3", 0) or 0,
                        )
                        net = satir.birim_fiyat_doviz * carp
                        doviz_ara += satir.miktar * net
                fatura.doviz_ara_toplam = doviz_ara.quantize(Decimal("0.01"))
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
            hareket.para_birimi = pb
            hareket.kur = kur if pb != "TRY" else Decimal("1")
            hareket.borc_esasi = "TL_SABIT"
            hareket.doviz_tutari = (
                Decimal(str(getattr(fatura, "doviz_ara_toplam", 0) or 0)) if pb != "TRY" else Decimal("0")
            )

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
            fid = int(fatura.id)

        from database.muhasebe_entegrasyon import muhasebe_hook

        muhasebe_hook("alis_faturasi_fisi", fid, yeniden=True)
        return AlisFaturasiService.getir(fid)

    @staticmethod
    def iptal_et(fatura_id):
        yazma_zorunlu("alis_fatura_duzenleme", "alis_duzenleme", "iptal")
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
                fid = int(fatura.id)
            else:
                return

        from database.muhasebe_entegrasyon import muhasebe_hook

        muhasebe_hook("alis_faturasi_iptal", fid)
        from database.deleted_record_service import ENTITY_ALIS_FATURA, safe_log_cancel

        safe_log_cancel(ENTITY_ALIS_FATURA, fatura_id, note="Alış faturası iptal")

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
        from decimal import ROUND_HALF_UP

        from database.iskonto_hesap_service import satir_net_brut_indirim

        ara = iskonto = kdv = Decimal("0")
        kurus = Decimal("0.01")
        for satir in satirlar:
            get = satir.get if isinstance(satir, dict) else lambda a, d=0: getattr(satir, a, d)
            miktar = decimal(get("miktar"), "Miktar")
            fiyat = decimal(get("birim_fiyat", get("birim_alis_fiyati", 0)), "Birim fiyat")
            brut, indirim, net = satir_net_brut_indirim(
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
                if not str(h.belge_no).startswith(("AFAT-", "ARAY")):
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
        """ARAY000001 formatında artan alış fatura numarası."""
        onek = "ARAY"
        with get_session() as session:
            numaralar = session.scalars(
                select(AlisFaturasi.fatura_no).where(AlisFaturasi.fatura_no.like(f"{onek}%"))
            ).all()
            max_sira = 0
            for no in numaralar:
                kuyruk = str(no)[len(onek):]
                if kuyruk.isdigit():
                    max_sira = max(max_sira, int(kuyruk))
            return f"{onek}{max_sira + 1:06d}"
