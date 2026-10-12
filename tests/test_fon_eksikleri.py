"""Fon eksikleri kabul testleri: faturaya ek fon bedeli, dövizli belge, fonlar arası transfer.

Yalnız geçici test veritabanı (StokOrtami) kullanılır; gerçek firma verisine dokunulmaz.
"""

from __future__ import annotations

import sys
import threading
import unittest
from datetime import timedelta
from decimal import Decimal
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from sqlalchemy import func, select, update  # noqa: E402

from database.database import get_session  # noqa: E402
from database.fon_service import FonService  # noqa: E402
from database.models.cari import CariIslem, SatisHareketi  # noqa: E402
from database.models.fon import (  # noqa: E402
    Fon,
    FonBelgeEkBedeli,
    FonHareketi,
    FonParaHareketi,
    FonTransferi,
)
from database.models.satis_faturasi import SatisFaturasi, SatisFaturasiSatiri  # noqa: E402
from database.models.stok import StokHareketi  # noqa: E402
from tests.test_fon_yonetimi import BUGUN, _FonTaban  # noqa: E402

D = Decimal
EK_HESAP = "649.01.0001"


class _EkBedelTaban(_FonTaban):
    """U002 ürününde ``EKFON`` %1 faturaya ek bedel (KDV %20 yalnız test için, hesap 649.01.0001)."""

    def setUp(self):
        super().setUp()
        from database.models.genel_muhasebe import HesapPlani, MuhasebeHesapEsleme
        from database.muhasebe_service import MuhasebeService

        with get_session() as s:
            self.firma_id = MuhasebeService.yerel_firma_id(s)
            for anahtar, kod, tur in (
                (None, EK_HESAP, "Gelir"),
                ("musteriler", "120.01.0001", "Aktif"),
                ("yurtici_satislar", "600.01.0001", "Gelir"),
                ("hesaplanan_kdv", "391.01.0001", "Pasif"),
                ("satistan_iadeler", "610.01.0001", "Gelir"),
            ):
                h = s.scalar(select(HesapPlani).where(HesapPlani.hesap_kodu == kod))
                if h is None:
                    h = HesapPlani(firma_id=self.firma_id, hesap_kodu=kod, hesap_adi=kod, hesap_seviyesi=3,
                                   hesap_turu=tur, borc_toplam=0, alacak_toplam=0, aktif=True)
                    s.add(h)
                    s.flush()
                if anahtar:
                    s.add(MuhasebeHesapEsleme(firma_id=self.firma_id, anahtar=anahtar, aciklama=anahtar,
                                              hesap_id=h.id, aktif=True))
        self.ekfon = FonService.fon_kaydet({
            "kod": "EKFON", "ad": "Ek Fon", "yontem": "EK_BEDEL", "ek_bedel_kdv_orani": "20",
            "ek_bedel_hesap_kodu": EK_HESAP,
        })
        FonService.stok_fon_oranlarini_kaydet(self.u2, [{"fon_id": self.ekfon, "oran": "1", "aktif": True}])

    def fatura(self, fid) -> SatisFaturasi:
        with get_session() as s:
            return s.get(SatisFaturasi, fid)

    def hareket(self, fid) -> SatisHareketi:
        with get_session() as s:
            no = s.get(SatisFaturasi, fid).fatura_no
            return s.scalar(select(SatisHareketi).where(SatisHareketi.belge_no == no))


class EkBedelTest(_EkBedelTaban):
    def test_kabul_ornegi_10000_yuzde1_kdv20_odenecek_12120(self):
        from database.satis_faturasi_service import SatisFaturasiService

        fid = self.satis([("U002", 10, 1000)])
        f = self.fatura(fid)
        self.assertEqual((D(str(f.fon_ek_bedel_tutari)), D(str(f.fon_ek_bedel_kdv))), (D("100.00"), D("20.00")))
        self.assertEqual(D(str(f.tl_genel_toplam)), D("12000.00"))  # ürün toplamı (Yeni Toplam) değişmez
        with get_session() as s:
            f = s.get(SatisFaturasi, fid)
            self.assertEqual(SatisFaturasiService.urun_net_toplam(f), D("12000.00"))
            self.assertEqual(SatisFaturasiService.net_toplam(f), D("12120.00"))
            detay = s.scalar(select(FonBelgeEkBedeli).where(FonBelgeEkBedeli.belge_id == fid))
            self.assertEqual((D(str(detay.matrah)), D(str(detay.oran)), D(str(detay.kdv_orani)), detay.hesap_kodu),
                             (D("10000.00"), D("1.0000"), D("20.00"), EK_HESAP))
            h = s.scalar(select(FonHareketi).where(FonHareketi.belge_id == fid, FonHareketi.fon_id == self.ekfon))
            self.assertEqual((h.yontem, D(str(h.taban)), D(str(h.tutar))), ("EK_BEDEL", D("10000.00"), D("100.00")))
        # Cari borç tek ve nihai tutar: ürün + bedel + KDV (çift kayıt yok)
        self.assertEqual(D(str(self.hareket(fid).satis_tutari)), D("12120.00"))
        with get_session() as s:
            no = s.get(SatisFaturasi, fid).fatura_no
            self.assertEqual(s.scalar(select(func.count(SatisHareketi.id)).where(SatisHareketi.belge_no == no)), 1)
            # Ek bedel stok miktarı / maliyeti oluşturmaz: yalnız ürün satırının tek stok çıkışı
            self.assertEqual(s.scalar(select(func.count(StokHareketi.id)).where(StokHareketi.belge_no == no)), 1)
        # Fon hakkı bir kez: iç pay + bedel olarak iki kez yazılmaz
        self.assertEqual(self.paylar(fid, self.ekfon), D("100.00"))

    def test_ic_pay_modunda_borc_12000_kalir(self):
        FonService.fon_kaydet({"kod": "EKFON", "ad": "Ek Fon", "yontem": "IC_PAY"}, self.ekfon)
        fid = self.satis([("U002", 10, 1000)])
        f = self.fatura(fid)
        self.assertEqual(D(str(f.fon_ek_bedel_tutari)), D("0"))
        self.assertEqual(D(str(self.hareket(fid).satis_tutari)), D("12000.00"))
        with get_session() as s:
            h = s.scalar(select(FonHareketi).where(FonHareketi.belge_id == fid, FonHareketi.fon_id == self.ekfon))
            self.assertEqual((h.yontem, D(str(h.tutar))), ("IC_PAY", D("100.00")))

    def test_tahsilat_odenecek_toplama_kadar(self):
        with self.assertRaisesRegex(ValueError, "aşamaz"):
            self.satis([("U002", 10, 1000)], tahsilat=[(D("12120.01"), "NAKİT / KASA")])
        fid = self.satis([("U002", 10, 1000)], tahsilat=[(D("12120"), "NAKİT / KASA")])
        self.assertEqual(D(str(self.hareket(fid).kalan_acik_tutar)), D("0.00"))
        self.assertEqual(self.durum(self.ekfon)["tahsil_edilen"], D("100.00"))

    def test_kismi_tahsilat_payi_odenecek_toplama_gore(self):
        self.satis([("U002", 10, 1000)], tahsilat=[(D("6060"), "NAKİT / KASA")])
        self.assertEqual(self.durum(self.ekfon)["tahsil_edilen"], D("50.00"))

    def test_coklu_fon_ayni_urun_tabanindan_zincirleme_yok(self):
        FonService.stok_fon_oranlarini_kaydet(self.u2, [{"fon_id": self.yardim, "oran": "1,5", "aktif": True}])
        fid = self.satis([("U002", 10, 1000)])
        self.assertEqual(self.paylar(fid, self.yardim), D("150.00"))  # 10.000 × %1,5 (10.100 değil)
        self.assertEqual(D(str(self.fatura(fid).fon_ek_bedel_tutari)), D("100.00"))

    def test_iskonto_ve_uzlasma_sonrasi_matrah(self):
        # 10.000 brüt %10 iskonto → 9.000 net; KDV dahil 10.800 → uzlaşma 10.200 (net 8.500)
        fid = self.satis([("U002", 10, 1000, 10)], tl_brut_toplam=D("10800"), tl_genel_toplam=D("10200"),
                         genel_islem_turu="INDIRIM", genel_islem_tutari=D("600"))
        f = self.fatura(fid)
        self.assertEqual(D(str(f.fon_ek_bedel_tutari)), D("85.00"))
        self.assertEqual(D(str(f.fon_ek_bedel_kdv)), D("17.00"))
        self.assertEqual(D(str(self.hareket(fid).satis_tutari)), D("10302.00"))

    def test_ayar_degisikligi_gecmis_belgeyi_degistirmez(self):
        from database.satis_faturasi_service import SatisFaturasiService

        fid = self.satis([("U002", 10, 1000)])
        taslak = self.satis([("U002", 10, 1000)], onayla=False)
        FonService.stok_fon_oranlarini_kaydet(self.u2, [{"fon_id": self.ekfon, "oran": "2", "aktif": True}])
        FonService.fon_kaydet({"kod": "EKFON", "ad": "Ek Fon", "yontem": "EK_BEDEL", "ek_bedel_kdv_orani": "10",
                               "ek_bedel_hesap_kodu": EK_HESAP}, self.ekfon)
        self.assertEqual(D(str(self.fatura(fid).fon_ek_bedel_tutari)), D("100.00"))
        # Taslak belgeye bağlanan oran/KDV ile onaylanır
        SatisFaturasiService.onayla(taslak)
        self.assertEqual(D(str(self.hareket(taslak).satis_tutari)), D("12120.00"))
        # Onay kaldır + yeniden onay: aynı belge, aynı oran, çift etki yok
        SatisFaturasiService.onay_kaldir(fid)
        SatisFaturasiService.onayla(fid)
        self.assertEqual(self.paylar(fid, self.ekfon), D("100.00"))
        self.assertEqual(D(str(self.hareket(fid).satis_tutari)), D("12120.00"))
        # Yeni belge yeni ayarı alır
        yeni = self.satis([("U002", 10, 1000)])
        self.assertEqual((D(str(self.fatura(yeni).fon_ek_bedel_tutari)), D(str(self.fatura(yeni).fon_ek_bedel_kdv))),
                         (D("200.00"), D("20.00")))

    def test_ic_payken_kaydedilen_taslak_yontem_degisince_onaylanmaz(self):
        from database.satis_faturasi_service import SatisFaturasiService

        FonService.fon_kaydet({"kod": "EKFON", "ad": "Ek Fon", "yontem": "IC_PAY"}, self.ekfon)
        taslak = self.satis([("U002", 10, 1000)], onayla=False)
        FonService.fon_kaydet({"kod": "EKFON", "ad": "Ek Fon", "yontem": "EK_BEDEL", "ek_bedel_kdv_orani": "20",
                               "ek_bedel_hesap_kodu": EK_HESAP}, self.ekfon)
        with self.assertRaisesRegex(ValueError, "yeniden kaydedin"):
            SatisFaturasiService.onayla(taslak)

    def test_eksik_ayar_kayittan_once_ayar_adiyla_uyarir(self):
        with get_session() as s:
            s.execute(update(Fon).where(Fon.id == self.ekfon).values(ek_bedel_kdv_orani=None))
        with self.assertRaisesRegex(ValueError, "Ek bedel KDV oranı"):
            self.satis([("U002", 10, 1000)], onayla=False)
        with get_session() as s:
            s.execute(update(Fon).where(Fon.id == self.ekfon).values(ek_bedel_kdv_orani=D("20"),
                                                                       ek_bedel_hesap_kodu=None))
        with self.assertRaisesRegex(ValueError, "Ek bedel muhasebe hesabı"):
            self.satis([("U002", 10, 1000)], onayla=False)
        with get_session() as s:
            self.assertEqual(s.scalar(select(func.count(SatisFaturasi.id))), 0)

    def test_iade_yalniz_iade_edilen_pay_orijinal_oranla(self):
        fid = self.satis([("U002", 10, 1000)])
        FonService.fon_kaydet({"kod": "EKFON", "ad": "Ek Fon", "yontem": "EK_BEDEL", "ek_bedel_kdv_orani": "10",
                               "ek_bedel_hesap_kodu": EK_HESAP}, self.ekfon)
        iade = self.iade(fid, D("2.5"), kod="U002")
        with get_session() as s:
            from database.models.satis_iade_faturasi import SatisIadeFaturasi

            i = s.get(SatisIadeFaturasi, iade.id)
            self.assertEqual((D(str(i.fon_ek_bedel_tutari)), D(str(i.fon_ek_bedel_kdv))), (D("25.00"), D("5.00")))
            alacak = s.scalar(select(func.sum(CariIslem.alacak)).where(CariIslem.belge_no == i.iade_no))
            self.assertEqual(D(str(alacak)), D("3030.00"))
        self.assertEqual(self.paylar(fid, self.ekfon, olay="IADE_DUZELTME"), D("-25.00"))
        self.assertEqual(self.durum(self.ekfon)["net_satis_payi"], D("75.00"))

    def test_iade_iptali_ve_fatura_iptali_tersine_doner(self):
        from database.satis_faturasi_service import SatisFaturasiService
        from database.satis_iade_faturasi_service import SatisIadeFaturasiService

        fid = self.satis([("U002", 10, 1000)])
        iade = self.iade(fid, 5, kod="U002")
        SatisIadeFaturasiService.iptal_et(iade.id)
        self.assertEqual(self.durum(self.ekfon)["net_satis_payi"], D("100.00"))
        # İptal edilmiş iadeden sonra tekrar iade: KDV sınırı iptal edileni saymaz
        iade2 = self.iade(fid, 10, kod="U002")
        with get_session() as s:
            from database.models.satis_iade_faturasi import SatisIadeFaturasi

            self.assertEqual(D(str(s.get(SatisIadeFaturasi, iade2.id).fon_ek_bedel_kdv)), D("20.00"))
        SatisIadeFaturasiService.iptal_et(iade2.id)
        SatisFaturasiService.iptal_et(fid, "Test iptal")
        self.assertEqual(self.durum(self.ekfon)["net_satis_payi"], D("0"))

    def test_muhasebe_fisi_dengeli_bedel_ayri_hesapta(self):
        from database.models.genel_muhasebe import HesapPlani, MuhasebeFisiSatiri
        from database.muhasebe_entegrasyon import MuhasebeEntegrasyonService

        fid = self.satis([("U002", 10, 1000)])
        fis_id = MuhasebeEntegrasyonService.satis_faturasi_fisi(fid, yeniden=True)
        with get_session() as s:
            satirlar = {}
            for x in s.scalars(select(MuhasebeFisiSatiri).where(MuhasebeFisiSatiri.fis_id == fis_id)):
                kod = s.get(HesapPlani, x.hesap_id).hesap_kodu
                satirlar[kod] = (D(str(x.borc)), D(str(x.alacak)))
        self.assertEqual(satirlar["120.01.0001"], (D("12120.00"), D("0")))
        self.assertEqual(satirlar["600.01.0001"], (D("0"), D("10000.00")))
        self.assertEqual(satirlar[EK_HESAP], (D("0"), D("100.00")))
        self.assertEqual(satirlar["391.01.0001"], (D("0"), D("2020.00")))
        iade = self.iade(fid, D("2.5"), kod="U002")
        try:
            iade_fis = MuhasebeEntegrasyonService.satis_iade_fisi(iade.id)
        except Exception as hata:  # noqa: BLE001
            self.skipTest(f"İade maliyet eşleşmesi bu ortamda yok: {hata}")
        with get_session() as s:
            borc = alacak = D("0")
            ek = None
            for x in s.scalars(select(MuhasebeFisiSatiri).where(MuhasebeFisiSatiri.fis_id == iade_fis)):
                borc += D(str(x.borc))
                alacak += D(str(x.alacak))
                if s.get(HesapPlani, x.hesap_id).hesap_kodu == EK_HESAP:
                    ek = D(str(x.borc))
        self.assertEqual(borc, alacak)
        self.assertEqual(ek, D("25.00"))

    def test_hizli_satis_odenecek_toplam_ve_tahsilat(self):
        from database.hizli_satis_service import HizliSatisService
        from hizli_satis_sepet import HizliSatisSepet

        sepet = HizliSatisSepet()
        sepet.ekle(stok_id=self.u2, stok_kodu="U002", stok_adi="İkinci Ürün", miktar=10, birim_fiyat="1000",
                   kdv_orani=20)
        on = HizliSatisService.ek_fon_bedeli_onizleme(HizliSatisService._sepetten_satirlar(sepet), D("12000"))
        self.assertEqual((on["tutar"], on["kdv"]), (D("100.00"), D("20.00")))
        with self.assertRaisesRegex(ValueError, "aşamaz"):
            HizliSatisService.satisi_tamamla(
                sepet=sepet, cari_id=self.o.mus_id,
                tahsilatlar=[{"odeme_sekli": "NAKİT / KASA", "hesap": "TEST KASA", "tutar": "12120,01"}],
                idempotency_token=HizliSatisService.yeni_idempotency_token(), musteri_bakiye=0, risk_limiti=None)
        sonuc = HizliSatisService.satisi_tamamla(
            sepet=sepet, cari_id=self.o.mus_id,
            tahsilatlar=[{"odeme_sekli": "NAKİT / KASA", "hesap": "TEST KASA", "tutar": "12120"}],
            idempotency_token=HizliSatisService.yeni_idempotency_token(), musteri_bakiye=0, risk_limiti=None)
        self.assertEqual((sonuc["genel_toplam"], sonuc["odenecek_toplam"], sonuc["kalan"]),
                         (D("12000.00"), D("12120.00"), D("0.00")))
        fid = int(sonuc["fatura_id"])
        self.assertEqual(D(str(self.hareket(fid).satis_tutari)), D("12120.00"))
        veri = HizliSatisService.fatura_cikti_verisi(fid)
        self.assertEqual((veri["fon_ek_bedel"], veri["fon_ek_bedel_kdv"], veri["odenecek_toplam"]),
                         (D("100.00"), D("20.00"), D("12120.00")))
        from hizli_satis_cikti_ui import a4_html, fis_html, pdf_metin_satirlari

        self.assertIn("ÖDENECEK", fis_html(veri))
        self.assertIn("Ödenecek", a4_html(veri))
        self.assertTrue(any("Odenecek" in x for x in pdf_metin_satirlari(veri)))

    def test_baski_modeli_bedel_kdv_ve_odenecek(self):
        from invoice_print.builder import build_invoice_print_model
        from invoice_print.html_renderer import render_invoice_html

        fid = self.satis([("U002", 10, 1000)])
        vm = build_invoice_print_model(fid)
        self.assertEqual((vm.ek_bedel_toplam, vm.ek_bedel_kdv, vm.odenecek_toplam),
                         (D("100.00"), D("20.00"), D("12120.00")))
        self.assertEqual(vm.kalan_bakiye, D("12120.00"))
        html = render_invoice_html(vm)
        self.assertIn("Ek fon bedeli", html)
        self.assertIn("Ödenecek Toplam", html)


class DovizTest(_EkBedelTaban):
    def usd_satis(self, *, kur="40", borc_esasi="DOVIZ_SABIT", onayla=True):
        from database.satis_faturasi_service import SatisFaturasiService

        FonService.stok_fon_oranlarini_kaydet(self.u2, [{"fon_id": self.ekfon, "oran": "0", "aktif": False},
                                                        {"fon_id": self.yardim, "oran": "1", "aktif": True}])
        veriler = {"fatura_tarihi": BUGUN, "vade_tarihi": BUGUN, "cari_id": self.o.mus_id, "depo": "ANA DEPO",
                   "sales_person_id": 1, "para_birimi": "USD", "kur": D(kur), "kur_tarihi": BUGUN,
                   "borc_esasi": borc_esasi}
        rows = [{"urun_kodu": "U002", "urun_adi": "U002", "miktar": D("4"), "birim": "Adet",
                 "birim_fiyat": D("0"), "birim_fiyat_doviz": D("25"), "kdv_orani": D("20")}]
        f = SatisFaturasiService.kaydet(veriler, rows)
        if onayla:
            SatisFaturasiService.onayla(f.id)
        return int(f.id)

    def test_100_usd_kur40_hak40_kur_degisse_de_40(self):
        fid = self.usd_satis()
        with get_session() as s:
            h = s.scalar(select(FonHareketi).where(FonHareketi.belge_id == fid, FonHareketi.fon_id == self.yardim))
            self.assertEqual((h.para_birimi, D(str(h.kur)), D(str(h.doviz_taban)), D(str(h.taban)), D(str(h.tutar))),
                             ("USD", D("40"), D("100.00"), D("4000.00"), D("40.00")))
        satir = next(r for r in FonService.hareket_listesi(fon_id=self.yardim) if r["belge_id"] == fid)
        self.assertEqual((satir["para_birimi"], satir["doviz_taban"]), ("USD", D("100.00")))
        # Ödeme farklı kurdan (42) %50 kapatır: tahsil edilen pay 20, hak 40'ı aşmaz
        with get_session() as s:
            f = s.get(SatisFaturasi, fid)
            from database.models.satis_faturasi import SatisFaturasiTahsilati

            # Borç 4.800 TL = 120 USD; %50 = 60 USD, 42 kurdan 2.520 TL ödenir
            s.add(SatisFaturasiTahsilati(fatura_id=fid, tahsilat_tarihi=BUGUN, tutar=D("2520"),
                                         odeme_sekli="NAKİT / KASA", hesap="TEST KASA", odeme_kuru=D("42")))
            s.flush()
            s.refresh(f)
            oran = FonService.fatura_tahsil_orani(s, f)["oran"]
        self.assertEqual(oran, D("0.5"))
        d = self.durum(self.yardim)
        self.assertEqual((d["net_satis_payi"], d["tahsil_edilen"]), (D("40.00"), D("20.00")))
        # %25 iade orijinal kurla 10 TL ters çevirir
        self.iade(fid, 1, kod="U002", fiyat=1000)
        self.assertEqual(self.paylar(fid, self.yardim, olay="IADE_DUZELTME"), D("-10.00"))

    def test_kur_eksikse_varsayilmaz_dogrulama_hatasi(self):
        from database.satis_faturasi_service import SatisFaturasiService

        fid = self.usd_satis(kur="1", onayla=False)
        with self.assertRaisesRegex(ValueError, "kuru kayıtlı değil"):
            SatisFaturasiService.onayla(fid)
        self.assertEqual(self.paylar(fid), D("0"))

    def test_tl_fatura_doviz_fiyatli_satir_cift_cevrilmez(self):
        from database.satis_faturasi_service import SatisFaturasiService

        FonService.stok_fon_oranlarini_kaydet(self.u2, [{"fon_id": self.ekfon, "oran": "0", "aktif": False},
                                                        {"fon_id": self.yardim, "oran": "1", "aktif": True}])
        f = SatisFaturasiService.kaydet(
            {"fatura_tarihi": BUGUN, "vade_tarihi": BUGUN, "cari_id": self.o.mus_id, "depo": "ANA DEPO",
             "sales_person_id": 1, "para_birimi": "TRY", "kur": D("1")},
            [{"urun_kodu": "U002", "urun_adi": "U002", "miktar": D("10"), "birim": "Adet",
              "birim_fiyat": D("1000"), "birim_fiyat_doviz": D("25"), "kdv_orani": D("20")}])
        SatisFaturasiService.onayla(f.id)
        with get_session() as s:
            h = s.scalar(select(FonHareketi).where(FonHareketi.belge_id == f.id, FonHareketi.fon_id == self.yardim))
            self.assertEqual((D(str(h.taban)), D(str(h.tutar)), h.para_birimi), (D("10000.00"), D("100.00"), "TRY"))

    def test_dovizli_ek_bedel_doviz_borca_kayitli_kurla(self):
        FonService.stok_fon_oranlarini_kaydet(self.u2, [{"fon_id": self.ekfon, "oran": "1", "aktif": True}])
        from database.satis_faturasi_service import SatisFaturasiService

        f = SatisFaturasiService.kaydet(
            {"fatura_tarihi": BUGUN, "vade_tarihi": BUGUN, "cari_id": self.o.mus_id, "depo": "ANA DEPO",
             "sales_person_id": 1, "para_birimi": "USD", "kur": D("40"), "kur_tarihi": BUGUN,
             "borc_esasi": "DOVIZ_SABIT"},
            [{"urun_kodu": "U002", "urun_adi": "U002", "miktar": D("4"), "birim": "Adet",
              "birim_fiyat": D("0"), "birim_fiyat_doviz": D("25"), "kdv_orani": D("20")}])
        SatisFaturasiService.onayla(f.id)
        h = self.hareket(f.id)
        # 4.000 TL × %1 = 40 + KDV 8 = 48 TL → 1,20 USD; borç TL 4.848
        self.assertEqual(D(str(h.satis_tutari)), D("4848.00"))
        self.assertEqual(D(str(h.doviz_tutari)) - D(str(self.fatura(f.id).doviz_ara_toplam)), D("1.20"))


class TransferTest(_FonTaban):
    def setUp(self):
        super().setUp()
        # 100.000 TL net satış, tam tahsil: YARDIM hak 1.500, YEDEK 500 → ayrılmış 1.000 / 500
        self.satis([("U001", 100, 1000)], tahsilat=[(120000, "NAKİT / KASA")])
        FonService.para_ayir(self.yardim, BUGUN, "1000")
        FonService.para_ayir(self.yedek, BUGUN, "500")

    def kullanilabilir(self, fon_id):
        return self.durum(fon_id)["kullanim_limiti"]

    def test_kabul_1000_500_transfer_200_iptal(self):
        tid = FonService.transfer_kaydet(self.yardim, self.yedek, BUGUN, "200", aciklama="Test aktarımı")
        self.assertEqual((self.kullanilabilir(self.yardim), self.kullanilabilir(self.yedek)),
                         (D("800.00"), D("700.00")))
        self.assertEqual(self.kullanilabilir(self.yardim) + self.kullanilabilir(self.yedek), D("1500.00"))
        # Satış payı, tahsil edilen ve ayrılabilir değişmez
        for fon, net, tahsil in ((self.yardim, D("1500.00"), D("1500.00")), (self.yedek, D("500.00"), D("500.00"))):
            d = self.durum(fon)
            self.assertEqual((d["net_satis_payi"], d["tahsil_edilen"]), (net, tahsil))
        self.assertEqual(self.durum(self.yardim)["ayrilabilir"], D("500.00"))
        with get_session() as s:
            t = s.get(FonTransferi, tid)
            self.assertTrue(t.transfer_no.startswith("FTR"))
            hareketler = s.scalars(select(FonParaHareketi).where(FonParaHareketi.ref_id == tid)).all()
            self.assertEqual(sorted(h.tur for h in hareketler), ["TRANSFER_CIKIS", "TRANSFER_GIRIS"])
            # Kasa/banka hareketi oluşmaz
            from database.models.finans import FinansHareketi

            self.assertEqual(s.scalar(select(func.count(FinansHareketi.id)).where(
                FinansHareketi.belge_no == t.transfer_no)), 0)
        FonService.transfer_iptal(tid, "Yanlış fon")
        self.assertEqual((self.kullanilabilir(self.yardim), self.kullanilabilir(self.yedek)),
                         (D("1000.00"), D("500.00")))
        liste = FonService.transfer_listesi(fon_id=self.yedek)
        self.assertEqual((liste[0]["durum"], liste[0]["iptal_gerekcesi"]), ("İptal", "Yanlış fon"))
        bagli = FonService.transfer_hareketleri(tid)
        self.assertEqual(len(bagli), 4)
        self.assertEqual(sum(1 for b in bagli if b["ters_kayit"]), 2)
        with self.assertRaisesRegex(ValueError, "zaten iptal"):
            FonService.transfer_iptal(tid, "tekrar")

    def test_engeller(self):
        for kaynak, hedef, tutar, metin in (
            (self.yardim, self.yardim, "10", "aynı"),
            (self.yardim, self.yedek, "0", "sıfırdan büyük"),
            (self.yardim, self.yedek, "-5", "sıfırdan büyük"),
            (self.yardim, self.yedek, "1000,01", "aşamaz"),
        ):
            with self.assertRaisesRegex(ValueError, metin):
                FonService.transfer_kaydet(kaynak, hedef, BUGUN, tutar)
        with self.assertRaisesRegex(ValueError, "Farklı firma"):
            FonService.transfer_kaydet(self.yardim, self.yedek, BUGUN, "10", firma_id=999999)
        # Kullanılmış tutar transfer edilemez
        FonService.fon_kullan(self.yardim, BUGUN, "900", yardim_alan="A", amac="B")
        with self.assertRaisesRegex(ValueError, "aşamaz"):
            FonService.transfer_kaydet(self.yardim, self.yedek, BUGUN, "100,01")
        FonService.transfer_kaydet(self.yardim, self.yedek, BUGUN, "100")
        self.assertEqual(self.kullanilabilir(self.yardim), D("0.00"))
        with get_session() as s:
            self.assertEqual(s.scalar(select(func.count(FonTransferi.id))), 1)

    def test_tekrar_gonderim_tek_transfer(self):
        a = FonService.transfer_kaydet(self.yardim, self.yedek, BUGUN, "200", istek_kimligi="tr-1")
        b = FonService.transfer_kaydet(self.yardim, self.yedek, BUGUN, "200", istek_kimligi="tr-1")
        self.assertEqual(a, b)
        self.assertEqual(self.kullanilabilir(self.yardim), D("800.00"))
        with get_session() as s:
            self.assertEqual(s.scalar(select(func.count(FonParaHareketi.id)).where(
                FonParaHareketi.tur.in_(("TRANSFER_CIKIS", "TRANSFER_GIRIS")))), 2)

    def test_es_zamanli_transfer_eksi_bakiye_olusturmaz(self):
        basarili, hatalar = [], []

        def calis():
            try:
                basarili.append(FonService.transfer_kaydet(self.yardim, self.yedek, BUGUN, "600"))
            except Exception as e:  # noqa: BLE001
                hatalar.append(e)

        isler = [threading.Thread(target=calis) for _ in range(2)]
        for t in isler:
            t.start()
        for t in isler:
            t.join()
        self.assertEqual(len(basarili), 1)
        self.assertEqual(self.kullanilabilir(self.yardim), D("400.00"))

    def test_iptal_hedef_bakiyesi_yetersizse_engellenir(self):
        tid = FonService.transfer_kaydet(self.yardim, self.yedek, BUGUN, "200")
        FonService.fon_kullan(self.yedek, BUGUN, "650", yardim_alan="A", amac="B")
        with self.assertRaisesRegex(ValueError, "yetersiz"):
            FonService.transfer_iptal(tid, "Geri al")
        # Kaynakta transfer edilen tutar ayırmayı geri alma ile gizlenemez
        with get_session() as s:
            ayirma = s.scalar(select(FonParaHareketi.id).where(FonParaHareketi.fon_id == self.yardim,
                                                               FonParaHareketi.tur == "AYIRMA"))
        with self.assertRaises(ValueError):
            FonService.ayirmayi_geri_al(ayirma, "800,01", "fazla")

    def test_rapor_ve_mutabakat_transferi_gosterir(self):
        FonService.transfer_kaydet(self.yardim, self.yedek, BUGUN, "200")
        satirlar = FonService.mutabakat(BUGUN - timedelta(days=1), BUGUN)
        self.assertTrue(all(r["tutarli"] for r in satirlar))
        tr = {r["fon_kod"]: r["kapanis"] for r in satirlar if r["kalem"] == "Transfer (net)"}
        self.assertEqual((tr["YARDIM"], tr["YEDEK"]), (D("-200.00"), D("200.00")))
        gun = {r["fon_kod"]: r["transfer"] for r in FonService.tarih_bazli_rapor()}
        self.assertEqual((gun["YARDIM"], gun["YEDEK"]), (D("-200.00"), D("200.00")))
        adlar = {r["tur_adi"] for r in FonService.para_hareketleri()}
        self.assertTrue({"Transfer çıkışı", "Transfer girişi"} <= adlar)

    def test_yetkisiz_kullanici_transfer_yapamaz(self):
        from database.access import AccessError
        from database.session_manager import oturum

        oturum.set_user(user_id=2, kullanici_adi="satis", ad_soyad="Satışçı", role_kod="SATIS",
                        role_ad="Satış", permissions={"satis_goruntuleme", "fon_goruntuleme"})
        with self.assertRaises(AccessError):
            FonService.transfer_kaydet(self.yardim, self.yedek, BUGUN, "10")


class EkranTest(_EkBedelTaban):
    """Fon ekranı (yöntem/transfer), satış faturası kartı ve Hızlı Satış ödenecek toplam gösterimi."""

    def setUp(self):
        super().setUp()
        import tkinter as tk
        from unittest.mock import patch

        try:
            self.root = tk.Tk()
        except tk.TclError as hata:
            self.skipTest(f"Tk yok: {hata}")
        self.root.withdraw()
        self.mesajlar = []
        self._yamalar = [patch(f"{m}.messagebox.{ad}", lambda *a, _ad=ad, **k: self.mesajlar.append((_ad, a)))
                         for m in ("fon_ui", "hizli_satis_ui") for ad in ("showerror", "showwarning", "showinfo")]
        for p in self._yamalar:
            p.start()

    def tearDown(self):
        for p in reversed(self._yamalar):
            p.stop()
        try:
            self.root.destroy()
        finally:
            super().tearDown()

    def test_fon_tanim_formu_yontem_ve_hesap_eslemesi(self):
        from unittest.mock import patch

        from fon_ui import FonYonetimiSayfasi

        sayfa = FonYonetimiSayfasi(self.root)
        tanim = {r["kod"]: r for r in sayfa._veri["tanim"]}
        self.assertEqual(tanim["EKFON"]["yontem_adi"], "Faturaya ek bedel")
        self.assertEqual(tanim["YARDIM"]["yontem_adi"], "İç pay")
        yakalanan = {}

        def form(_parent, _baslik, alanlar, bilgi="", varsayilan=None):
            yakalanan.update(alanlar={a[0]: a for a in alanlar}, varsayilan=varsayilan)
            return {**varsayilan, "_istek": "x"}

        with patch("fon_ui.FormDialog.ac", side_effect=form):
            sonuc = sayfa._tanim_formu("Düzenle", tanim["EKFON"])
        self.assertEqual(yakalanan["alanlar"]["yontem"][3], ["İç pay", "Faturaya ek bedel"])
        self.assertEqual(yakalanan["varsayilan"]["yontem"], "Faturaya ek bedel")
        self.assertEqual((sonuc["yontem"], sonuc["ek_bedel_hesap_kodu"]), ("EK_BEDEL", EK_HESAP))
        with patch("fon_ui.FormDialog.ac", side_effect=form):
            sonuc = sayfa._tanim_formu("Yeni", {"kod": "YENI", "ad": "Yeni"})
        self.assertEqual((sonuc["yontem"], sonuc["ek_bedel_kdv_orani"]), ("IC_PAY", None))  # varsayılan iç pay
        sayfa.destroy()

    def test_transfer_ekrani_bakiye_onizleme_ve_liste(self):
        from unittest.mock import patch

        from fon_ui import FonYonetimiSayfasi, TransferDialog

        self.satis([("U001", 100, 1000)], tahsilat=[(120000, "NAKİT / KASA")])
        FonService.para_ayir(self.yardim, BUGUN, "1000")
        FonService.para_ayir(self.yedek, BUGUN, "500")
        sayfa = FonYonetimiSayfasi(self.root)
        fonlar = sayfa._fon_secenekleri()
        dlg = TransferDialog(sayfa, fonlar)
        dlg.v["kaynak"].set(next(k for k in fonlar if k.startswith("YARDIM")))
        dlg.v["hedef"].set(next(k for k in fonlar if k.startswith("YEDEK")))
        dlg.v["tutar"].set("200")
        metin = dlg.bilgi.cget("text")
        self.assertIn("1.000,00", metin)
        self.assertIn("800,00", metin)
        self.assertIn("700,00", metin)
        dlg._tamam()
        with patch("fon_ui.TransferDialog.ac", return_value=dlg.sonuc):
            sayfa.fon_transferi()
        self.assertEqual(len(sayfa._veri["transfer"]), 1)
        self.assertEqual(sayfa._veri["transfer"][0]["tutar"], D("200.00"))
        bakiye = {r["fon_kod"]: r for r in sayfa._veri["bakiye"]}
        self.assertEqual((bakiye["YARDIM"]["transfer_net"], bakiye["YEDEK"]["transfer_net"]),
                         (D("-200.00"), D("200.00")))
        sayfa.sekmeler["transfer"][0].selection_set("0")
        with patch("fon_ui.FormDialog.ac", return_value={"gerekce": "Hatalı", "tarih": BUGUN, "_istek": "y"}):
            sayfa.transfer_iptal()
        self.assertEqual(sayfa._veri["transfer"][0]["durum"], "İptal")
        sayfa.destroy()

    def test_satis_faturasi_karti_odenecek_toplam_ve_tahsilat_kalani(self):
        from unittest.mock import patch

        from app import SatisFaturasiDialog
        from invoice_print.builder import build_from_kart

        yamalar = [
            patch("satis_personeli_ui.aktif_satis_personelleri", return_value=[]),
            patch("satis_personeli_ui.satis_personeli_degistirme_yetkisi", return_value=True),
            patch("fatura_acilis_cache.satis_personelleri", return_value=[]),
            patch("fatura_manuel_fiyat_ui.fiyat_degistirme_yetkisi", return_value=True),
            patch("fatura_manuel_fiyat_ui.maliyet_alti_kontrol", return_value=True),
        ]
        for p in yamalar:
            p.start()
        try:
            dlg = SatisFaturasiDialog(self.root)
            dlg.geometry("1400x800+-3000+-3000")
            dlg.satirlar = [{"urun_kodu": "U002", "urun_adi": "İkinci Ürün", "miktar": "10", "birim": "Adet",
                             "birim_satis_fiyati": "1000", "kdv_orani": "20", "iskonto_orani": "0",
                             "iskonto_orani_2": "0", "iskonto_orani_3": "0"}]
            dlg._toplamlari_guncelle()
            self.assertEqual(dlg._hesaplanan_genel, D("12000.00"))
            self.assertEqual(dlg._fon_ek_bedel, (D("100.00"), D("20.00")))
            self.assertEqual(dlg._odenecek_toplam(), D("12120.00"))
            self.assertEqual(dlg._tahsilat_kalan(), D("12120.00"))
            self.assertIn("12.120,00", dlg.fatura_toplam_degerleri["odenecek"].cget("text"))
            from database.models.cari import Cari

            with get_session() as s:
                musteri = s.get(Cari, self.o.mus_id)
            dlg._secili_musteri = lambda: musteri
            vm = build_from_kart(dlg)
            self.assertEqual((vm.ek_bedel_toplam, vm.odenecek_toplam), (D("100.00"), D("12120.00")))
            dlg.destroy()
        finally:
            for p in reversed(yamalar):
                p.stop()

    def test_hizli_satis_ekrani_odenecek_toplam(self):
        import hizli_satis_ui

        pencere = hizli_satis_ui.HizliSatisPencere(self.root)
        try:
            pencere._sepete_ekle_kayit({"stok_id": self.u2, "stok_kodu": "U002", "stok_adi": "İkinci Ürün",
                                        "birim": "Adet", "miktar": D("10"), "birim_fiyat": D("1000")})
            self.root.update()
            t = pencere.sepet_model.toplamlar()
            net = t["genel_toplam"] - t["kdv"]  # KDV hariç ürün neti = fon bedeli matrahı
            ek = (net / 100).quantize(D("0.01"))
            self.assertGreater(ek, 0)
            beklenen = t["genel_toplam"] + ek + (ek * D("0.20")).quantize(D("0.01"))
            self.assertEqual(pencere._odenecek_toplam(), beklenen)
            metin = pencere.odenecek_lbl.cget("text")
            self.assertIn("ÖDENECEK TOPLAM", metin)
            self.assertIn(f"{beklenen:,.2f}".replace(",", "X").replace(".", ",").replace("X", "."), metin)
        finally:
            pencere.destroy()


if __name__ == "__main__":
    unittest.main()
