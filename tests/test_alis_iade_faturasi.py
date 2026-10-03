"""Alış iade faturası: taslak → onay → iptal, kaynak kontrolü, stok/cari/muhasebe etkileri.

Talimat 12. bölüm kabul senaryoları; her test kendi geçici veritabanında çalışır.
"""

from __future__ import annotations

import sys
import threading
import unittest
from datetime import date
from decimal import Decimal
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(ROOT / "tests") not in sys.path:
    sys.path.insert(0, str(ROOT / "tests"))

from sqlalchemy import func, select  # noqa: E402

from database.access import AccessError  # noqa: E402
from database.alis_faturasi_service import AlisFaturasiService  # noqa: E402
from database.alis_iade_faturasi_service import (  # noqa: E402
    BASKA_TEDARIKCI,
    DEVIR,
    KAYNAK_YOK_MESAJI,
    KAYNAKLI,
    KAYNAKSIZ,
    AlisIadeFaturasiService as S,
    IadeDegisti,
    KaynakTercihiGerekli,
)
from database.database import get_session  # noqa: E402
from database.models.alis_iade_faturasi import (  # noqa: E402
    AlisIadeFaturasi,
    AlisIadeFaturasiSatiri,
    AlisIadeKaynakDagilimi,
)
from database.models.cari import Cari, CariIslem, SatisHareketi  # noqa: E402
from database.models.finans import FinansHareketi  # noqa: E402
from database.models.stok import Depo, StokHareketi, StokKarti, StokLotu  # noqa: E402
from database.session_manager import oturum  # noqa: E402
from database.stok_service import ALIS_IADE_CIKIS  # noqa: E402
from tests.stok_test_ortami import StokOrtami  # noqa: E402

D = Decimal
T_ALIS = date(2026, 3, 1)
T_ALIS2 = date(2026, 3, 2)
T_SATIS = date(2026, 3, 3)
T_IADE = date(2026, 3, 5)


def satir(miktar, fiyat="100", birim="Adet", kod="U001", kaynak=None, **ek):
    v = {"urun_kodu": kod, "urun_adi": "Test Ürün", "miktar": D(str(miktar)), "birim": birim,
         "birim_fiyat": D(str(fiyat)), "iskonto_orani": D("0"), "kdv_orani": D("20")}
    if kaynak:
        v["kaynak_fatura_satiri_id"] = kaynak
    v.update(ek)
    return v


class _Taban(unittest.TestCase):
    def setUp(self):
        self.o = StokOrtami(self._testMethodName[:18])

    def tearDown(self):
        self.o.kapat()

    # ---- yardımcılar
    def veri(self, depo="ANA DEPO", cari=None, tarih=T_IADE, **ek):
        v = {"iade_tarihi": tarih, "cari_id": cari or self.o.ted_id, "depo": depo, "iade_odeme_tutari": D("0")}
        v.update(ek)
        return v

    def alis(self, miktar, fiyat, lot, tarih=T_ALIS, birim="Adet", depo="ANA DEPO", cari=None):
        if cari is None:
            f = self.o.alis(miktar, fiyat, tarih, lot=lot, birim=birim, depo=depo)
        else:
            f = AlisFaturasiService.kaydet(
                {"fatura_tarihi": tarih, "vade_tarihi": tarih, "cari_id": cari, "depo": depo,
                 "odeme_tutari": D("0")},
                [{"urun_kodu": "U001", "urun_adi": "Test Ürün", "miktar": D(str(miktar)), "birim": birim,
                  "birim_fiyat": D(str(fiyat)), "iskonto_orani": D("0"), "kdv_orani": D("20"), "lot_no": lot}])
        return int(f.id), int(AlisFaturasiService.getir(f.id).satirlar[0].id)

    def lot(self, lot_no, depo="ANA DEPO") -> Decimal:
        with get_session() as s:
            depo_id = s.scalar(select(Depo.id).where(Depo.ad == depo))
            l = s.scalar(select(StokLotu).where(StokLotu.lot_no == lot_no, StokLotu.depo_id == depo_id))
            return D(str(l.kalan_miktar)) if l else D("0")

    def say(self, model, *kosul) -> int:
        with get_session() as s:
            return int(s.scalar(select(func.count()).select_from(model).where(*kosul)) or 0)

    def iade_hareketleri(self, iade_no) -> list[StokHareketi]:
        with get_session() as s:
            return list(s.scalars(select(StokHareketi).where(StokHareketi.belge_no == iade_no)).all())

    def alis_acik(self, fatura_id) -> Decimal:
        from database.acik_kalem_service import AcikKalemService

        with get_session() as s:
            no = AlisFaturasiService.getir(fatura_id).fatura_no
            h = s.scalar(select(SatisHareketi).where(SatisHareketi.belge_no == no))
            return D(str(AcikKalemService._guncel_kalan(s, h)))

    def ikinci_tedarikci(self) -> int:
        with get_session() as s:
            c = Cari(cari_kodu="T002", unvan="Diğer Tedarikçi", cari_turu="Tedarikçi", aktif=True)
            s.add(c)
            s.flush()
            return int(c.id)

    def devir_girisi(self, miktar, maliyet, lot="DEVIR-1", depo="ANA DEPO") -> int:
        from database.stok_service import StokService

        StokService.stok_girisi("U001", depo, "", date(2026, 1, 1), D(str(miktar)), D(str(maliyet)), lot)
        with get_session() as s:
            return int(s.scalar(select(StokLotu.id).where(StokLotu.lot_no == lot)))


# ====================================================================== 1
class S01BosAcilisVeTaslakTest(_Taban):
    def test_taslak_stok_cari_fis_olusturmaz_liste_ayri_ve_yeniden_acilir(self):
        _fid, ks = self.alis(10, 100, "L1")
        hareket0, cari0, finans0 = self.say(StokHareketi), self.say(CariIslem), self.say(FinansHareketi)
        iade = S.kaydet(self.veri(), [satir(3, kaynak=ks)])
        self.assertEqual(iade.durum, "TASLAK")
        self.assertTrue(iade.iade_no.startswith("AIF"))
        self.assertEqual(self.say(StokHareketi), hareket0)
        self.assertEqual(self.say(CariIslem), cari0)
        self.assertEqual(self.say(FinansHareketi), finans0)
        self.assertEqual(self.lot("L1"), D("10"))
        # Liste: ayrı sorgu, taslak görünür; tekrar açınca aynı belge ve satırlar
        liste = S.listele({"arama": iade.iade_no})
        self.assertEqual([r["iade"].id for r in liste], [iade.id])
        self.assertEqual(liste[0]["iade"].durum, "TASLAK")
        tekrar = S.getir(iade.id)
        self.assertEqual((tekrar.iade_no, len(tekrar.satirlar)), (iade.iade_no, 1))
        self.assertEqual(D(str(tekrar.satirlar[0].miktar)), D("3"))
        self.assertEqual(int(tekrar.satirlar[0].kaynak_fatura_satiri_id), ks)
        # Taslak düzenlenir; yeni numara üretilmez
        duz = S.kaydet(self.veri(aciklama="düzeltildi"), [satir(2, kaynak=ks)], iade.id)
        self.assertEqual((duz.id, duz.iade_no, duz.aciklama), (iade.id, iade.iade_no, "düzeltildi"))
        self.assertEqual(self.say(AlisIadeFaturasi), 1)


# ====================================================================== 2
class S02TemelIadeTest(_Taban):
    def test_10_alis_3_iade_stok_7_tutar_360_cari_bir_kez(self):
        fid, ks = self.alis(10, 100, "L1")
        self.assertEqual(self.alis_acik(fid), D("1200.00"))
        iade = S.kaydet_ve_onayla(self.veri(), [satir(3, kaynak=ks)])
        self.assertIn(iade.durum, ("AÇIK", "KAPALI"))
        self.assertEqual(self.lot("L1"), D("7"))
        self.assertEqual(self.o.hareket_bakiye(), D("7"))
        t = S.toplam(iade.satirlar)
        self.assertEqual((t["ara_toplam"], t["kdv"], t["genel_toplam"]), (D("300.00"), D("60.00"), D("360.00")))
        hareketler = self.iade_hareketleri(iade.iade_no)
        self.assertEqual([h.hareket_turu for h in hareketler], [ALIS_IADE_CIKIS])
        self.assertEqual(D(str(hareketler[0].miktar)), D("3"))
        self.assertEqual(D(str(iade.satirlar[0].stok_maliyet_toplam)), D("300.00"))
        self.assertEqual(self.say(CariIslem, CariIslem.belge_no == iade.iade_no), 1)
        with get_session() as s:
            ci = s.scalar(select(CariIslem).where(CariIslem.belge_no == iade.iade_no))
            self.assertEqual(D(str(ci.alacak)), D("360.00"))
        # İade alacağı tedarikçi borcunu azaltır (otomatik nakit oluşmaz)
        self.assertEqual(self.alis_acik(fid), D("840.00"))
        self.assertEqual(self.say(FinansHareketi, FinansHareketi.belge_no.like(f"{iade.iade_no}%")), 0)
        # İkinci onay tekrar etki üretmez
        S.onayla(iade.id)
        self.assertEqual(self.lot("L1"), D("7"))
        self.assertEqual(self.say(CariIslem, CariIslem.belge_no == iade.iade_no), 1)
        self.assertEqual(len(self.iade_hareketleri(iade.iade_no)), 1)
        # Satış çıkışı türü kullanılmadı
        self.assertEqual(self.o.hareket_sayisi("FATURA ÇIKIŞ"), 0)


# ====================================================================== 3
class S03BirimDonusumuTest(_Taban):
    def test_2_koli_24_adet_tutar_degismez_tanimsiz_birim_reddedilir(self):
        from database.stok_service import BirimDonusumHatasi

        _fid, ks = self.alis(30, 100, "L1")
        iade = S.kaydet_ve_onayla(self.veri(), [satir(2, fiyat="1200", birim="Koli", kaynak=ks)])
        s0 = iade.satirlar[0]
        self.assertEqual((D(str(s0.birim_carpani)), D(str(s0.temel_miktar))), (D("12"), D("24")))
        self.assertEqual(self.lot("L1"), D("6"))
        self.assertEqual(D(str(self.iade_hareketleri(iade.iade_no)[0].miktar)), D("24"))
        t = S.toplam(iade.satirlar)
        self.assertEqual((t["ara_toplam"], t["genel_toplam"]), (D("2400.00"), D("2880.00")))
        self.assertEqual(D(str(s0.stok_maliyet_toplam)), D("2400.00"))
        # Tanımsız birim sessizce 1 sayılmaz
        with self.assertRaises(BirimDonusumHatasi):
            S.kaydet(self.veri(), [satir(1, birim="Paket", kaynak=ks)])
        self.assertEqual(self.lot("L1"), D("6"))
        self.assertEqual(self.say(AlisIadeFaturasi), 1)


# ====================================================================== 4
class S04SatilmisMiktarTest(_Taban):
    def test_4_satildi_7_engellenir_6_dogru_maliyetle(self):
        _fid, ks = self.alis(10, 100, "L1")
        self.o.satis(4, 200, T_SATIS)
        taslak = S.kaydet(self.veri(), [satir(7, kaynak=ks)])
        with self.assertRaises(ValueError) as ctx:
            S.onayla(taslak.id)
        self.assertIn("stokta kalan", str(ctx.exception))
        self.assertEqual(self.lot("L1"), D("6"))
        self.assertEqual(S.getir(taslak.id).durum, "TASLAK")
        self.assertEqual(self.iade_hareketleri(taslak.iade_no), [])
        self.assertEqual(self.say(CariIslem, CariIslem.belge_no == taslak.iade_no), 0)
        iade = S.kaydet_ve_onayla(self.veri(), [satir(6, kaynak=ks)], taslak.id)
        self.assertEqual(self.lot("L1"), D("0"))
        self.assertEqual(D(str(iade.satirlar[0].stok_maliyet_toplam)), D("600.00"))
        self.assertEqual(D(str(iade.satirlar[0].fifo_birim_maliyeti)), D("100.0000"))

    def test_onceki_iadeler_hakki_azaltir(self):
        _fid, ks = self.alis(10, 100, "L1")
        S.kaydet_ve_onayla(self.veri(), [satir(4, kaynak=ks)])
        aday = S.kaynak_adaylari(self.o.ted_id, "U001", "ANA DEPO")[0]
        self.assertEqual((aday["onceki_iade_temel"], aday["hak_temel"]), (D("4"), D("6")))
        ikinci = S.kaydet(self.veri(), [satir(7, kaynak=ks)])
        with self.assertRaises(ValueError) as ctx:
            S.onayla(ikinci.id)
        self.assertIn("iade hakkı aşıldı", str(ctx.exception))
        self.assertEqual(self.lot("L1"), D("6"))
        # Aynı belgede aynı kaynağa iki satır da hakkı birlikte tüketir
        ucuncu = S.kaydet(self.veri(), [satir(4, kaynak=ks), satir(3, kaynak=ks)])
        with self.assertRaises(ValueError):
            S.onayla(ucuncu.id)
        self.assertEqual(self.lot("L1"), D("6"))


# ====================================================================== 5
class S05KaynakKatmaniTest(_Taban):
    def test_secilen_kaynagin_katmani_azalir(self):
        _fa, ka = self.alis(10, 100, "LA", tarih=T_ALIS)
        _fb, kb = self.alis(10, 150, "LB", tarih=T_ALIS2)
        iade = S.kaydet_ve_onayla(self.veri(), [satir(3, fiyat="150", kaynak=kb)])
        self.assertEqual((self.lot("LA"), self.lot("LB")), (D("10"), D("7")))
        self.assertEqual(D(str(iade.satirlar[0].stok_maliyet_toplam)), D("450.00"))
        self.assertEqual(self.o.lot_deger(), D("10") * 100 + D("7") * 150)
        dag = iade.satirlar[0].dagilimlar
        self.assertEqual([(int(d.kaynak_fatura_satiri_id), D(str(d.temel_miktar))) for d in dag], [(kb, D("3"))])
        self.assertIsNotNone(dag[0].stok_hareket_id)

    def test_birden_fazla_kaynak_alt_dagilim(self):
        _fa, ka = self.alis(10, 100, "LA", tarih=T_ALIS)
        _fb, kb = self.alis(10, 150, "LB", tarih=T_ALIS2)
        iade = S.kaydet_ve_onayla(self.veri(), [satir(5, kaynak=ka, kaynaklar=[
            {"kaynak_fatura_satiri_id": ka, "miktar": D("2")},
            {"kaynak_fatura_satiri_id": kb, "miktar": D("3")}])])
        self.assertEqual((self.lot("LA"), self.lot("LB")), (D("8"), D("7")))
        self.assertEqual(D(str(iade.satirlar[0].stok_maliyet_toplam)), D("650.00"))
        with self.assertRaises(ValueError):
            S.kaydet(self.veri(), [satir(5, kaynak=ka, kaynaklar=[
                {"kaynak_fatura_satiri_id": ka, "miktar": D("2")},
                {"kaynak_fatura_satiri_id": kb, "miktar": D("2")}])])

    def test_iptal_kaynak_kullanilamaz_ve_baska_depo_sessizce_kullanilmaz(self):
        _fa, ka = self.alis(10, 100, "LA")
        taslak = S.kaydet(self.veri(depo="DEPO 2"), [satir(3, kaynak=ka)])
        with self.assertRaises(ValueError) as ctx:
            S.onayla(taslak.id)
        self.assertIn("DEPO 2", str(ctx.exception))
        self.assertEqual(self.lot("LA"), D("10"))


# ====================================================================== 6
class S06DevirKaynaksizTest(_Taban):
    def test_devir_uyari_gerekceyle_devam_kalici_vazgecte_cikis_yok(self):
        lot_id = self.devir_girisi(5, 80)
        durum = S.urun_kaynak_durumu(self.o.ted_id, "U001", "ANA DEPO")
        self.assertEqual(durum["durum"], DEVIR)
        self.assertEqual(durum["mesaj"], KAYNAK_YOK_MESAJI)
        self.assertEqual([d["lot_id"] for d in durum["devir_lotlari"]], [lot_id])
        # Vazgeç: tercih yok → onay engellenir, çıkış yok
        taslak = S.kaydet(self.veri(), [satir(2)])
        with self.assertRaises(KaynakTercihiGerekli) as ctx:
            S.onayla(taslak.id)
        self.assertEqual(ctx.exception.satirlar, [taslak.satirlar[0].id])
        self.assertEqual(self.lot("DEVIR-1"), D("5"))
        self.assertEqual(self.iade_hareketleri(taslak.iade_no), [])
        # Devir kaynağı seçimi
        iade = S.kaydet_ve_onayla(self.veri(), [satir(2, kaynak_durumu=DEVIR, kaynak_lot_id=lot_id)], taslak.id)
        self.assertEqual(self.lot("DEVIR-1"), D("3"))
        s0 = S.getir(iade.id).satirlar[0]
        self.assertEqual((s0.kaynak_durumu, s0.kaynak_lot_id), (DEVIR, lot_id))
        self.assertEqual(s0.kaynak_onaylayan, "admin")
        self.assertIsNotNone(s0.kaynak_onay_tarihi)
        self.assertEqual(D(str(s0.stok_maliyet_toplam)), D("160.00"))

    def test_gerekceli_baglantisiz_iade_ve_degisince_gecersiz(self):
        self.devir_girisi(5, 80)
        with self.assertRaises(ValueError):
            S.kaydet(self.veri(), [satir(2, kaynak_durumu=KAYNAKSIZ)])  # gerekçe zorunlu
        taslak = S.kaydet(self.veri(), [satir(2, kaynak_durumu=KAYNAKSIZ, kaynak_gerekce="Eski sistemden")])
        s0 = taslak.satirlar[0]
        imza = s0.kaynak_onay_imza
        self.assertEqual((s0.kaynak_durumu, s0.kaynak_gerekce), (KAYNAKSIZ, "Eski sistemden"))
        self.assertEqual(S.onay_on_kontrol(taslak.id), [])
        # Miktar değişti: eski tercih geçersiz, yeniden onay ister
        degisen = S.kaydet(self.veri(), [satir(3, kaynak_durumu=KAYNAKSIZ, kaynak_gerekce="Eski sistemden",
                                                kaynak_onay_imza=imza)], taslak.id)
        self.assertIsNone(degisen.satirlar[0].kaynak_durumu)
        with self.assertRaises(KaynakTercihiGerekli):
            S.onayla(degisen.id)
        self.assertEqual(self.lot("DEVIR-1"), D("5"))
        # Depo değişince de geçersiz (imza depo içerir)
        self.assertNotEqual(imza, __import__("database.alis_iade_faturasi_service", fromlist=["x"])
                            .kaynak_imzasi("U001", D("2"), self.o.ted_id, "DEPO 2"))
        iade = S.kaydet_ve_onayla(self.veri(), [satir(2, kaynak_durumu=KAYNAKSIZ, kaynak_gerekce="Eski sistemden",
                                                      kaynak_onay_imza=imza)], taslak.id)
        self.assertEqual(self.lot("DEVIR-1"), D("3"))
        self.assertIsNone(iade.satirlar[0].kaynak_fatura_satiri_id)


# ====================================================================== 7
class S07BaskaTedarikciTest(_Taban):
    def test_baska_tedarikci_uyari_gerekceyle_sahte_baglanti_yok_stok_yetersiz_engeller(self):
        t2 = self.ikinci_tedarikci()
        _f2, k2 = self.alis(10, 100, "L2", cari=t2)
        durum = S.urun_kaynak_durumu(self.o.ted_id, "U001", "ANA DEPO")
        self.assertEqual(durum["durum"], BASKA_TEDARIKCI)
        self.assertEqual(durum["baska_tedarikciler"], ["Diğer Tedarikçi"])
        # Başka tedarikçinin alışı kaynak gösterilemez
        with self.assertRaises(ValueError) as ctx:
            S.kaydet(self.veri(), [satir(2, kaynak=k2)])
        self.assertIn("tedarikçiye ait değil", str(ctx.exception))
        iade = S.kaydet_ve_onayla(self.veri(), [satir(2, kaynak_durumu=BASKA_TEDARIKCI,
                                                      kaynak_gerekce="Tedarikçi devri")])
        s0 = iade.satirlar[0]
        self.assertIsNone(s0.kaynak_fatura_satiri_id)
        self.assertTrue(all(d.kaynak_fatura_satiri_id is None for d in s0.dagilimlar))
        self.assertEqual(self.lot("L2"), D("8"))
        # Yetersiz stok tercih olsa da engeller
        taslak = S.kaydet(self.veri(), [satir(15, kaynak_durumu=BASKA_TEDARIKCI, kaynak_gerekce="x")])
        with self.assertRaises(ValueError) as ctx:
            S.onayla(taslak.id)
        self.assertIn("Stok yetersiz", str(ctx.exception))
        self.assertEqual(self.lot("L2"), D("8"))


# ====================================================================== 8 (stok tarafı)
class S08DovizIskontoYuvarlamaTest(_Taban):
    def test_doviz_coklu_iskonto_yuvarlama_bedel_ve_maliyet_ayri(self):
        _fid, ks = self.alis(10, 100, "L1")
        iade = S.kaydet_ve_onayla(
            self.veri(para_birimi="USD", kur=D("30")),
            [satir(3, fiyat="0", kaynak=ks, birim_fiyat_doviz=D("3.3333"),
                   iskonto_orani=D("10"), iskonto_orani_2=D("5"))])
        s0 = iade.satirlar[0]
        self.assertEqual(D(str(iade.kur)), D("30"))
        self.assertEqual(D(str(s0.birim_fiyat)), D("99.9990"))
        t = S.toplam(iade.satirlar)
        # Brüt 3 × 99,999 = 299,997 → 300,00; net 299,997 × 0,90 × 0,95 = 256,497 → 256,50
        self.assertEqual(t["ara_toplam"], D("300.00"))
        self.assertEqual(t["ara_toplam"] - t["iskonto"], D("256.50"))
        self.assertEqual(t["kdv"], D("51.30"))
        self.assertEqual(t["genel_toplam"], D("307.80"))
        self.assertEqual(D(str(iade.doviz_ara_toplam)), D("8.55"))
        # İade bedeli ≠ iç stok maliyeti (FIFO 100 TL)
        self.assertEqual(D(str(s0.stok_maliyet_toplam)), D("300.00"))
        self.assertEqual(S.satir_tutarlari(s0)["net"], D("256.50"))


# ====================================================================== 10
class S10EszamanliVeHataTest(_Taban):
    def test_cift_ve_eszamanli_onay_tek_etki(self):
        _fid, ks = self.alis(10, 100, "L1")
        taslak = S.kaydet(self.veri(), [satir(3, kaynak=ks)])
        hatalar, bariyer = [], threading.Barrier(2)

        def calis():
            bariyer.wait()
            try:
                S.onayla(taslak.id)
            except IadeDegisti:
                pass
            except Exception as h:  # noqa: BLE001
                hatalar.append(h)

        th = [threading.Thread(target=calis) for _ in range(2)]
        for t in th:
            t.start()
        for t in th:
            t.join(30)
        self.assertEqual(hatalar, [])
        self.assertEqual(self.lot("L1"), D("7"))
        self.assertEqual(len(self.iade_hareketleri(taslak.iade_no)), 1)
        self.assertEqual(self.say(CariIslem, CariIslem.belge_no == taslak.iade_no), 1)

    def test_eszamanli_iptal_tek_geri_alma(self):
        _fid, ks = self.alis(10, 100, "L1")
        iade = S.kaydet_ve_onayla(self.veri(), [satir(3, kaynak=ks)])
        hatalar, bariyer = [], threading.Barrier(2)

        def calis():
            bariyer.wait()
            try:
                S.iptal_et(iade.id, "test")
            except Exception as h:  # noqa: BLE001
                hatalar.append(h)

        th = [threading.Thread(target=calis) for _ in range(2)]
        for t in th:
            t.start()
        for t in th:
            t.join(30)
        self.assertEqual(hatalar, [])
        self.assertEqual(self.lot("L1"), D("10"))
        self.assertEqual(self.o.hareket_bakiye(), D("10"))
        self.assertEqual(S.getir(iade.id).durum, "İPTAL")
        S.iptal_et(iade.id)  # ikinci iptal etkisiz
        self.assertEqual(self.lot("L1"), D("10"))

    def test_enjekte_hata_kismi_kayit_birakmaz_iptal_geri_yukler(self):
        from database.cari_service import CariService

        fid, ks = self.alis(10, 100, "L1")
        taslak = S.kaydet(self.veri(), [satir(3, kaynak=ks)])
        rv = S.getir(taslak.id).row_version
        with patch.object(CariService, "_alacak_uygula", side_effect=RuntimeError("enjekte hata")):
            with self.assertRaises(RuntimeError):
                S.onayla(taslak.id)
        sonra = S.getir(taslak.id)
        self.assertEqual((sonra.durum, sonra.row_version), ("TASLAK", rv))
        self.assertEqual(self.lot("L1"), D("10"))
        self.assertEqual(self.iade_hareketleri(taslak.iade_no), [])
        self.assertEqual(self.say(CariIslem, CariIslem.belge_no == taslak.iade_no), 0)
        self.assertEqual(self.say(AlisIadeKaynakDagilimi, AlisIadeKaynakDagilimi.lot_id.is_not(None)), 0)
        # Normal onay, sonra iptal: stok, cari, açık kalem eski hâline döner
        S.onayla(taslak.id)
        self.assertEqual(self.alis_acik(fid), D("840.00"))
        S.iptal_et(taslak.id, "hatalı iade")
        self.assertEqual(self.lot("L1"), D("10"))
        self.assertEqual(self.iade_hareketleri(taslak.iade_no), [])
        self.assertEqual(self.say(CariIslem, CariIslem.belge_no == taslak.iade_no), 0)
        self.assertEqual(self.alis_acik(fid), D("1200.00"))
        iptal = S.getir(taslak.id)
        self.assertEqual((iptal.durum, iptal.iptal_nedeni, iptal.iptal_eden), ("İPTAL", "hatalı iade", "admin"))
        # İptal edilen iade kaynak hakkını geri verir
        self.assertEqual(S.kaynak_adaylari(self.o.ted_id, "U001", "ANA DEPO")[0]["hak_temel"], D("10"))

    def test_onayli_belge_dogrudan_duzenlenemez(self):
        _fid, ks = self.alis(10, 100, "L1")
        iade = S.kaydet_ve_onayla(self.veri(), [satir(3, kaynak=ks)])
        with self.assertRaises(ValueError) as ctx:
            S.kaydet(self.veri(), [satir(2, kaynak=ks)], iade.id)
        self.assertIn("iptal edip", str(ctx.exception))
        # Yalnız açıklama değişebilir
        S.kaydet(self.veri(aciklama="not"), [satir(3, kaynak=ks)], iade.id)
        self.assertEqual(S.getir(iade.id).aciklama, "not")
        self.assertEqual(self.lot("L1"), D("7"))


# ====================================================================== 11
class S11YetkiVeBaglantiTest(_Taban):
    def test_yetkisiz_kullanici_kaydedemez_onaylayamaz(self):
        _fid, ks = self.alis(10, 100, "L1")
        taslak = S.kaydet(self.veri(), [satir(3, kaynak=ks)])
        oturum.set_user(user_id=2, kullanici_adi="izleyici", ad_soyad="İzleyici", role_kod="IZLEYICI",
                        role_ad="İzleyici", permissions={"alis_goruntule"})
        with self.assertRaises(AccessError):
            S.kaydet(self.veri(), [satir(3, kaynak=ks)])
        with self.assertRaises(AccessError):
            S.onayla(taslak.id)
        self.assertEqual(self.lot("L1"), D("10"))

    def test_kaynak_baglantilari_iki_yonlu(self):
        fid, ks = self.alis(10, 100, "L1")
        iade = S.kaydet_ve_onayla(self.veri(), [satir(3, kaynak=ks)])
        bag = S.satir_baglantilari(iade.satirlar[0].id)
        self.assertEqual(bag["kaynaklar"][0]["alis_fatura_id"], fid)
        self.assertEqual(bag["kaynaklar"][0]["kaynak_satir_id"], ks)
        self.assertEqual([h["tur"] for h in bag["hareketler"]], [ALIS_IADE_CIKIS])
        geri = S.kaynaktan_iadeler(fid)
        self.assertEqual([g["id"] for g in geri], [iade.id])

    def test_liste_filtreleri_iptal_toplamdan_haric(self):
        _fid, ks = self.alis(10, 100, "L1")
        a = S.kaydet_ve_onayla(self.veri(), [satir(1, kaynak=ks)])
        b = S.kaydet_ve_onayla(self.veri(), [satir(2, kaynak=ks)])
        S.kaydet(self.veri(), [satir(1, kaynak=ks)])
        S.iptal_et(b.id)
        tum = S.listele({})
        self.assertEqual(len(tum), 3)
        top = S.liste_toplamlari(tum)
        self.assertEqual(top["genel_toplam"], D("240.00"))  # taslak 120 + onaylı 120; iptal hariç
        self.assertEqual([r["iade"].id for r in S.listele({"durum": "İPTAL"})], [b.id])
        self.assertEqual([r["iade"].id for r in S.listele({"durum": "ONAYLI"})], [a.id])
        self.assertEqual(len(S.listele({"urun": "U001"})), 3)
        self.assertEqual(len(S.listele({"depo": "DEPO 2"})), 0)
        self.assertEqual(len(S.listele({"kaynak_durumu": KAYNAKLI})), 3)
        self.assertEqual(len(S.listele({}, limit=2)), 2)


# ====================================================================== 12
class S12RaporAyrimiVeUyariTest(_Taban):
    def test_alis_iade_cikisi_satis_smm_devir_hizi_karlilik_disi(self):
        from database.rapor_service import RaporService
        from database.satis_kar_analiz_service import KarAnalizFiltre, SatisKarAnalizService

        _fid, ks = self.alis(10, 100, "L1")
        S.kaydet_ve_onayla(self.veri(), [satir(2, kaynak=ks)])
        self.o.satis(3, 200, T_SATIS)
        self.assertEqual(self.o.hareket_sayisi(ALIS_IADE_CIKIS), 1)
        self.assertEqual(self.o.hareket_sayisi("FATURA ÇIKIŞ"), 1)
        r = RaporService.stok_devir_hizi(date(2026, 3, 1), date(2026, 3, 31))
        self.assertEqual(sum((s["cogs"] for s in r["satirlar"]), D("0")), D("300"))
        k = SatisKarAnalizService.analiz(KarAnalizFiltre(baslangic=date(2026, 3, 1), bitis=date(2026, 3, 31)))
        self.assertEqual([(x.belge_turu, x.miktar) for x in k.satirlar], [("SATIS", D("3"))])
        self.assertEqual(k.satirlar[0].toplam_maliyet, D("300"))

    def test_yalniz_iade_satilmadi_sayilir(self):
        from database.rapor_service import RaporService

        _fid, ks = self.alis(10, 100, "L1")
        S.kaydet_ve_onayla(self.veri(), [satir(3, kaynak=ks)])
        r = RaporService.stok_devir_hizi(date(2026, 3, 1), date(2026, 3, 31))
        self.assertEqual(sum((s["cogs"] for s in r["satirlar"]), D("0")), D("0"))
        u = next(s for s in RaporService.satilmayan_urunler(min_gun=0)["satirlar"] if s["stok_kodu"] == "U001")
        self.assertTrue(u["hic_satilmadi"])

    def test_stok_uyarisi_onay_ve_iptalde_guncellenir(self):
        from database.models.stok_uyari import StokIhtiyac
        from database.stok_uyari_service import NEDEN_TUKENDI

        _fid, ks = self.alis(3, 100, "L1")

        def aktif():
            with get_session() as s:
                return list(s.scalars(select(StokIhtiyac).where(StokIhtiyac.aktif.is_(True))).all())

        self.assertEqual(aktif(), [])
        iade = S.kaydet(self.veri(), [satir(3, kaynak=ks)])
        self.assertEqual(aktif(), [])  # taslak etkisiz
        S.onayla(iade.id)
        uyarilar = aktif()
        self.assertEqual(len(uyarilar), 1)
        self.assertIn(NEDEN_TUKENDI, uyarilar[0].nedenler)
        S.iptal_et(iade.id)
        self.assertEqual(aktif(), [])

    def test_eski_fatura_cikis_kayitlari_donusturulmez_ve_iptalde_geri_alinir(self):
        """Geçmiş 'FATURA ÇIKIŞ' türlü alış iadeleri olduğu gibi kalır; iptal yine çalışır."""
        _fid, ks = self.alis(10, 100, "L1")
        iade = S.kaydet_ve_onayla(self.veri(), [satir(3, kaynak=ks)])
        with get_session() as s:
            for h in s.scalars(select(StokHareketi).where(StokHareketi.belge_no == iade.iade_no)).all():
                h.hareket_turu = "FATURA ÇIKIŞ"
        self.assertEqual(self.o.hareket_bakiye(), D("7"))
        S.iptal_et(iade.id)
        self.assertEqual(self.lot("L1"), D("10"))
        self.assertEqual(self.iade_hareketleri(iade.iade_no), [])


# ====================================================================== 8-9 muhasebe / cari
import test_masraf_dagitim as tmd  # noqa: E402
import test_masraf_dagitim_baglanti as tmb  # noqa: E402
import test_muhasebelestirme_ayarlari as tma  # noqa: E402


class _MuhasebeTaban(unittest.TestCase):
    """Gerçek muhasebe kancalı ortam (yardımcılar mevcut testlerden; onların testleri devralınmaz)."""

    T = date(2026, 6, 3)
    _A = tma.MuhasebelestirmeAyarlariTest
    setUp = _A.setUp
    tearDown = _A.tearDown
    _alis = tmd.MasrafDagitimTest._alis
    _gider = tmd.MasrafDagitimTest._gider
    _gm_kur = tmd.MasrafDagitimTest._gm_kur
    _kasa = tmb.MasrafBaglantiTest._kasa
    _servis = staticmethod(_A._servis)
    _ayar = _A._ayar
    _fis_sayisi = _A._fis_sayisi
    _durum = _A._durum
    _durum_id = _A._durum_id
    _bakiyeler = _A._bakiyeler
    _tutarli = _A._tutarli

    def _iade(self, ks, miktar="10", fiyat="100", **ek):
        return S.kaydet(
            {"iade_tarihi": self.T, "cari_id": self.tedarikci_id, "depo": "ANA DEPO", **ek},
            [{"urun_kodu": "U001", "urun_adi": "U001", "miktar": D(miktar), "birim": "Adet",
              "birim_fiyat": D(fiyat), "iskonto_orani": D("0"), "kdv_orani": D("20"),
              "kaynak_fatura_satiri_id": ks}])

    def _kalemler(self, kaynak_turu, kaynak_id) -> dict[str, tuple[Decimal, Decimal]]:
        from database.models.genel_muhasebe import MuhasebeFisi, MuhasebeFisiSatiri

        with get_session() as s:
            fis = s.scalars(select(MuhasebeFisi).where(MuhasebeFisi.kaynak_turu == kaynak_turu,
                                                       MuhasebeFisi.kaynak_id == kaynak_id,
                                                       MuhasebeFisi.durum != "İPTAL")).all()
            fis = [f for f in fis if not getattr(f, "iptal_edildi", False)]
            sonuc: dict[str, tuple[Decimal, Decimal]] = {}
            for f in fis:
                for r in s.scalars(select(MuhasebeFisiSatiri).where(MuhasebeFisiSatiri.fis_id == f.id)):
                    b, a = sonuc.get(r.hesap_kodu, (D("0"), D("0")))
                    sonuc[r.hesap_kodu] = (b + D(str(r.borc)), a + D(str(r.alacak)))
            return sonuc


class S09MuhasebeTest(_MuhasebeTaban):
    def test_otomatik_tek_fis_taslakta_fis_yok_iptal_ters_kayit(self):
        self._ayar("otomatik")
        _fid, ks = self._alis(miktar="100", fiyat="100")
        taslak = self._iade(ks)
        self.assertEqual(self._fis_sayisi("alis_iade"), 0)
        S.onayla(taslak.id)
        self.assertEqual(self._fis_sayisi("alis_iade"), 1)
        self.assertEqual(self._durum("alis_iade", taslak.id)["durum"], "Muhasebeleştirildi")
        b = self._tutarli()
        self.assertEqual(b["320.01.0001"], D("1200.00") - D("12000.00"))  # alış borcu 12000 − iade 1200
        self.assertEqual(b["191.01.0001"], D("2000.00") - D("200.00"))
        S.onayla(taslak.id)
        self.assertEqual(self._fis_sayisi("alis_iade"), 1)
        S.iptal_et(taslak.id, "test")
        b2 = self._tutarli()
        self.assertEqual(b2["320.01.0001"], D("-12000.00"))
        self.assertEqual(b2["153.01.0001"], D("10000.00"))
        S.iptal_et(taslak.id)
        self.assertEqual(self._durum("alis_iade", taslak.id)["durum"], "İptal edildi")

    def test_sonradan_bekler_sonra_bir_kez_muhasebelesir(self):
        self._ayar("otomatik", alis_iade="sonradan")
        _fid, ks = self._alis(miktar="100", fiyat="100")
        iade = S.onayla(self._iade(ks).id)
        self.assertEqual(self._fis_sayisi("alis_iade"), 0)
        self.assertEqual(self._durum("alis_iade", iade.id)["durum"], "Bekliyor")
        sonuc = self._servis().muhasebelestir([self._durum_id("alis_iade", iade.id)])
        self.assertEqual(sonuc["basarili"], 1)
        self.assertEqual(self._fis_sayisi("alis_iade"), 1)
        self._servis().muhasebelestir([self._durum_id("alis_iade", iade.id)])
        self.assertEqual(self._fis_sayisi("alis_iade"), 1)
        self._tutarli()

    def test_eksik_esleme_evrak_onaylanmaz_kismi_kayit_yok(self):
        self._ayar("otomatik")
        _fid, ks = self._alis(miktar="100", fiyat="100")
        self._gm_kur(eksik=("indirilecek_kdv",))
        taslak = self._iade(ks)
        with self.assertRaises(ValueError):
            S.onayla(taslak.id)
        self.assertEqual(S.getir(taslak.id).durum, "TASLAK")
        self.assertEqual(self._fis_sayisi("alis_iade"), 0)
        with get_session() as s:
            self.assertEqual(int(s.scalar(select(func.count()).select_from(StokHareketi).where(
                StokHareketi.belge_no == taslak.iade_no))), 0)
            self.assertEqual(int(s.scalar(select(func.count()).select_from(CariIslem).where(
                CariIslem.belge_no == taslak.iade_no))), 0)

    def test_kapali_donem_onay_ve_iptal_engellenir(self):
        from database.models.donem import Donem

        self._ayar("otomatik")
        _fid, ks = self._alis(miktar="100", fiyat="100")
        iade = S.onayla(self._iade(ks).id)
        with get_session() as s:
            s.add(Donem(firma_id=self.firma_id, donem_adi="2025", baslangic_tarihi=date(2025, 1, 1),
                        bitis_tarihi=date(2025, 12, 31), aktif=False, kapali=True, varsayilan=False))
        eski = S.kaydet({"iade_tarihi": date(2025, 12, 31), "cari_id": self.tedarikci_id, "depo": "ANA DEPO"},
                        [{"urun_kodu": "U001", "urun_adi": "U001", "miktar": D("1"), "birim": "Adet",
                          "birim_fiyat": D("100"), "kdv_orani": D("20"), "kaynak_fatura_satiri_id": ks}])
        with self.assertRaises(AccessError):
            S.onayla(eski.id)
        self.assertEqual(S.getir(eski.id).durum, "TASLAK")
        # Onaylı iadenin dönemi sonradan kapanırsa iptal de engellenir
        with get_session() as s:
            d = s.scalar(select(Donem).where(Donem.donem_adi == "2025"))
            d.baslangic_tarihi, d.bitis_tarihi = date(2026, 6, 3), date(2026, 6, 3)
        with self.assertRaises(AccessError):
            S.iptal_et(iade.id)
        self.assertNotEqual(S.getir(iade.id).durum, "İPTAL")

    def test_mahsup_secimi_ve_sonradan_tahsilat(self):
        from database.acik_kalem_service import AcikKalemService

        self._ayar("otomatik")
        fid, ks = self._alis(miktar="100", fiyat="100")
        fid2, ks2 = self._alis(kod="U001", miktar="10", fiyat="100", lot="LOT-B")

        def acik(f):
            with get_session() as s:
                no = AlisFaturasiService.getir(f).fatura_no
                h = s.scalar(select(SatisHareketi).where(SatisHareketi.belge_no == no))
                return D(str(AcikKalemService._guncel_kalan(s, h)))

        # KAYNAK: yalnız kaynak alışın borcu kapanır (FIFO olsa ilk alış kapanırdı)
        iade = S.onayla(self._iade(ks2, miktar="5", mahsup_modu="KAYNAK").id)
        self.assertEqual((acik(fid), acik(fid2)), (D("12000.00"), D("600.00")))
        S.iptal_et(iade.id)
        self.assertEqual((acik(fid), acik(fid2)), (D("12000.00"), D("1200.00")))
        # AVANS: borçlar kapanmaz, açık iade alacağı kalır; sonradan tahsil edilir
        iade = S.onayla(self._iade(ks2, miktar="5", mahsup_modu="AVANS").id)
        self.assertEqual((acik(fid), acik(fid2)), (D("12000.00"), D("1200.00")))
        self._kasa()
        hesap = "Merkez Kasa"
        no1 = S.iade_tahsilati(iade.id, D("300"), self.T, hesap, "NAKİT")
        self.assertEqual(no1, f"{iade.iade_no}-T1")
        self.assertEqual(S.getir(iade.id).durum, "AÇIK")
        self.assertEqual(self._fis_sayisi("alis_iade_tahsilat"), 1)
        S.iade_tahsilati(iade.id, D("300"), self.T, hesap, "NAKİT")
        self.assertEqual(S.getir(iade.id).durum, "KAPALI")
        self.assertEqual(self._fis_sayisi("alis_iade_tahsilat"), 1)  # tek tahsil fişi, yeni toplamla
        k = self._kalemler("alis_iade_tahsilat", iade.id)
        self.assertEqual(k["100.01.0001"][0] - k["100.01.0001"][1], D("600.00"))
        with self.assertRaises(ValueError):
            S.iade_tahsilati(iade.id, D("1"), self.T, hesap)
        self._tutarli()
        S.iptal_et(iade.id)
        with get_session() as s:
            self.assertEqual(int(s.scalar(select(func.count()).select_from(FinansHareketi).where(
                FinansHareketi.belge_no.like(f"{iade.iade_no}%")))), 0)
        b = self._tutarli()
        self.assertNotIn("100.01.0001", b)


class S08MasrafDagitimliAlisTest(_MuhasebeTaban):
    def test_masraf_dagitilmis_alis_iadesinde_bedel_ve_stok_maliyeti_ayri(self):
        from database.masraf_dagitim_service import MasrafDagitimService

        self._ayar("otomatik")
        _fid, ks = self._alis(miktar="100", fiyat="100")
        kaynak_id, kss = self._gider("1000")
        MasrafDagitimService.onayla(MasrafDagitimService.taslak_kaydet(
            tmd.MasrafDagitimTest._veri(self, kaynak_id, kss, [ks])))
        iade = S.onayla(self._iade(ks, miktar="10", fiyat="100").id)
        s0 = iade.satirlar[0]
        self.assertEqual(D(str(s0.fifo_birim_maliyeti)), D("110.0000"))
        self.assertEqual(D(str(s0.stok_maliyet_toplam)), D("1100.00"))
        self.assertEqual(S.toplam(iade.satirlar)["ara_toplam"], D("1000.00"))
        lot = tmd.MasrafDagitimTest._lot(self)
        self.assertEqual(D(str(lot.kalan_miktar)), D("90"))
        self.assertEqual(D(str(lot.birim_maliyet)), D("110"))
        self._tutarli()


if __name__ == "__main__":
    unittest.main()
