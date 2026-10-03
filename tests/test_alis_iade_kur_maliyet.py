"""Alış iadesi: bedel ↔ FIFO stok maliyeti farkı, dövizli iade kur farkı, kısmi/tam/iptal, mükerrer koruma,
'Kaynağı Aç' ve 'Bağlı İadeler'. Her test kendi geçici veritabanında çalışır (gerçek muhasebe kancası).
"""

from __future__ import annotations

import sys
import threading
import tkinter as tk
import unittest
from datetime import date
from decimal import Decimal
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
for yol in (ROOT, ROOT / "tests"):
    if str(yol) not in sys.path:
        sys.path.insert(0, str(yol))

from sqlalchemy import func, select  # noqa: E402

from database.alis_faturasi_service import AlisFaturasiService  # noqa: E402
from database.alis_iade_faturasi_service import AlisIadeFaturasiService as S, IadeDegisti  # noqa: E402
from database.database import get_session  # noqa: E402
from database.models.cari import CariIslem  # noqa: E402
from database.models.genel_muhasebe import (  # noqa: E402
    BELGE_HATALI,
    BELGE_INCELEME,
    BELGE_MUHASEBE_DISI,
    BELGE_MUHASEBELESTIRILDI,
    KUR_FARKI_HESAPLANDI,
    KUR_FARKI_INCELEME,
    KUR_FARKI_IPTAL,
    HesapPlani,
    KurFarkiKaydi,
    MuhasebeFisi,
    MuhasebeHesapEsleme,
)
from database.models.stok import StokHareketi, StokLotu  # noqa: E402
from test_alis_iade_faturasi import _MuhasebeTaban  # noqa: E402
import test_masraf_dagitim as tmd  # noqa: E402

D = Decimal
MF, MFN, KFG, KFZ = "649.01.0001", "659.01.0001", "646.01.0001", "656.01.0001"


class _Taban(_MuhasebeTaban):
    def setUp(self):
        super().setUp()
        self._ayar("otomatik")

    # ---- kurulum yardımcıları
    def bagla(self, anahtar, kod, ad, tur):
        with get_session() as s:
            h = s.scalar(select(HesapPlani).where(HesapPlani.hesap_kodu == kod))
            if h is None:
                h = HesapPlani(firma_id=self.firma_id, hesap_kodu=kod, hesap_adi=ad, hesap_seviyesi=3,
                               hesap_turu=tur, borc_toplam=0, alacak_toplam=0, aktif=True)
                s.add(h)
                s.flush()
            e = s.scalar(select(MuhasebeHesapEsleme).where(MuhasebeHesapEsleme.anahtar == anahtar))
            if e is None:
                s.add(MuhasebeHesapEsleme(firma_id=self.firma_id, anahtar=anahtar, aciklama=ad, hesap_id=h.id,
                                          aktif=True))
            else:
                e.hesap_id, e.aktif = h.id, True

    def maliyet_farki_bagla(self, olumlu=True, olumsuz=True):
        if olumlu:
            self.bagla("alis_iade_maliyet_farki_olumlu", MF, "Alış iade olumlu maliyet farkı", "Gelir")
        if olumsuz:
            self.bagla("alis_iade_maliyet_farki_olumsuz", MFN, "Alış iade olumsuz maliyet farkı", "Gider")

    def kdv_kuru_sec(self, yontem):
        from database import muhasebe_finans_ayarlari as fa

        fa.kaydet({fa.ALIS_IADE_KDV_KURU: yontem})

    def kur_farki_bagla(self, secim="gelir_gider"):
        from database import muhasebe_finans_ayarlari as fa

        self.bagla("kur_farki_geliri", KFG, "Kambiyo Karları", "Gelir")
        self.bagla("kur_farki_gideri", KFZ, "Kambiyo Zararları", "Gider")
        fa.kaydet({fa.ALIS_IADE_KUR_FARKI: secim})

    def alis_usd(self, miktar="100", usd="10", kur="30", lot="LOT-U"):
        f = AlisFaturasiService.kaydet(
            {"fatura_tarihi": tmd.TARIH_ALIS, "vade_tarihi": tmd.TARIH_ALIS, "cari_id": self.tedarikci_id,
             "depo": "ANA DEPO", "odeme_tutari": D("0"), "para_birimi": "USD", "kur": D(kur),
             "kur_tarihi": tmd.TARIH_ALIS},
            [{"urun_kodu": "U001", "urun_adi": "U001", "miktar": D(miktar), "birim": "Adet",
              "birim_fiyat": D("0"), "birim_fiyat_doviz": D(usd), "iskonto_orani": D("0"), "kdv_orani": D("20"),
              "lot_no": lot}])
        return int(f.id), int(AlisFaturasiService.getir(f.id).satirlar[0].id)

    def iade_usd(self, ks, miktar="10", usd="10", kur="32"):
        return S.kaydet(
            {"iade_tarihi": self.T, "cari_id": self.tedarikci_id, "depo": "ANA DEPO", "para_birimi": "USD",
             "kur": D(kur), "kur_tarihi": self.T},
            [{"urun_kodu": "U001", "urun_adi": "U001", "miktar": D(miktar), "birim": "Adet",
              "birim_fiyat": D("0"), "birim_fiyat_doviz": D(usd), "iskonto_orani": D("0"), "kdv_orani": D("20"),
              "kaynak_fatura_satiri_id": ks}])

    # ---- sorgu yardımcıları
    def etkin_fis(self, kaynak_turu, kaynak_id=None) -> list[int]:
        with get_session() as s:
            q = select(MuhasebeFisi.id).where(MuhasebeFisi.kaynak_turu == kaynak_turu, MuhasebeFisi.durum != "İptal")
            if kaynak_id is not None:
                q = q.where(MuhasebeFisi.kaynak_id == int(kaynak_id))
            return list(s.scalars(q).all())

    def kf_kayitlari(self, iade_no, etkin=True) -> list[KurFarkiKaydi]:
        with get_session() as s:
            q = select(KurFarkiKaydi).where(KurFarkiKaydi.kapatma_belge_no == iade_no)
            if etkin:
                q = q.where(KurFarkiKaydi.durum != KUR_FARKI_IPTAL)
            return list(s.scalars(q.order_by(KurFarkiKaydi.id)).all())

    def cari_alacak(self, iade_no) -> Decimal:
        with get_session() as s:
            return D(str(s.scalar(select(func.coalesce(func.sum(CariIslem.alacak), 0)).where(
                CariIslem.belge_no == iade_no)) or 0))

    def lot_kalan(self, lot) -> Decimal:
        with get_session() as s:
            return D(str(s.scalar(select(StokLotu.kalan_miktar).where(StokLotu.lot_no == lot))))

    def fark(self, once: dict, sonra: dict) -> dict:
        return {k: sonra.get(k, D("0")) - once.get(k, D("0")) for k in set(once) | set(sonra)
                if sonra.get(k, D("0")) != once.get(k, D("0"))}


# ====================================================================== maliyet farkı (TL)
class MaliyetFarkiTest(_Taban):
    def test_tl_bedel_maliyetten_buyuk_fis_dengeli_cari_stok_kdv(self):
        self.maliyet_farki_bagla()
        _fid, ks = self._alis(miktar="100", fiyat="100")
        once = self._tutarli()
        iade = S.onayla(self._iade(ks, miktar="10", fiyat="120").id)
        self.assertEqual(self._durum("alis_iade", iade.id)["durum"], BELGE_MUHASEBELESTIRILDI)
        self.assertEqual(self.fark(once, self._tutarli()), {
            "320.01.0001": D("1440.00"), "153.01.0001": D("-1000.00"), "191.01.0001": D("-240.00"),
            MF: D("-200.00")})
        self.assertEqual(self.cari_alacak(iade.iade_no), D("1440.00"))
        self.assertEqual(self.lot_kalan("LOT-A"), D("90"))
        self.assertEqual(D(str(iade.satirlar[0].stok_maliyet_toplam)), D("1000.00"))
        self.assertEqual(S.maliyet_farki(iade), {"bedel": D("1200.00"), "maliyet": D("1000.00"), "fark": D("200.00")})
        self.assertEqual(self.kf_kayitlari(iade.iade_no), [])  # TL iadede kur farkı yok

    def test_tl_bedel_maliyetten_kucuk_fark_borca_iptalde_ters_kayit(self):
        self.maliyet_farki_bagla()
        _fid, ks = self._alis(miktar="100", fiyat="100")
        once = self._tutarli()
        iade = S.onayla(self._iade(ks, miktar="10", fiyat="80").id)
        self.assertEqual(self.fark(once, self._tutarli()), {
            "320.01.0001": D("960.00"), "153.01.0001": D("-1000.00"), "191.01.0001": D("-160.00"), MFN: D("200.00")})
        S.iptal_et(iade.id, "test")
        S.iptal_et(iade.id, "test")
        self.assertEqual(self.fark(once, self._tutarli()), {})
        self.assertEqual(self.lot_kalan("LOT-A"), D("100"))
        self.assertEqual(self.cari_alacak(iade.iade_no), D("0"))
        self.assertEqual(self.etkin_fis("alis_iade", iade.id), [])

    def test_esleme_eksikse_onay_yapilir_inceleme_sonra_tek_fis(self):
        _fid, ks = self._alis(miktar="100", fiyat="100")
        iade = S.onayla(self._iade(ks, miktar="10", fiyat="120").id)
        self.assertIn(iade.durum, ("AÇIK", "KAPALI"))
        d = self._durum("alis_iade", iade.id)
        self.assertEqual(d["durum"], BELGE_INCELEME)
        self.assertIn("alis_iade_maliyet_farki_olumlu", d["aciklama"])
        self.assertIn("200.00 TL olumlu", d["aciklama"])
        self.assertEqual(self.etkin_fis("alis_iade", iade.id), [])
        self.maliyet_farki_bagla()
        self._servis().muhasebelestir([self._durum_id("alis_iade", iade.id)])
        self._servis().muhasebelestir([self._durum_id("alis_iade", iade.id)])
        self.assertEqual(len(self.etkin_fis("alis_iade", iade.id)), 1)
        self.assertEqual(self._tutarli()[MF], D("-200.00"))

    def test_fark_yoksa_esleme_gerekmez(self):
        _fid, ks = self._alis(miktar="100", fiyat="100")
        iade = S.onayla(self._iade(ks, miktar="10", fiyat="100").id)
        self.assertEqual(self._durum("alis_iade", iade.id)["durum"], BELGE_MUHASEBELESTIRILDI)
        self.assertNotIn(MF, self._tutarli())


# ====================================================================== kur farkı (dövizli)
class KurFarkiTest(_Taban):
    def setUp(self):
        super().setUp()
        self.kdv_kuru_sec("iade_kuru")

    def test_kur_artisi_gider_656_maliyet_farki_ve_izlenebilirlik(self):
        self.maliyet_farki_bagla()
        self.kur_farki_bagla()
        _fid, ks = self.alis_usd(kur="30")
        once = self._tutarli()
        iade = S.onayla(self.iade_usd(ks, kur="32").id)
        s0 = iade.satirlar[0]
        self.assertEqual((s0.kaynak_para_birimi, D(str(s0.kaynak_kur)), s0.kaynak_kur_tarihi, D(str(s0.iade_kuru))),
                         ("USD", D("30"), tmd.TARIH_ALIS, D("32")))
        self.assertEqual(D(str(s0.kur_farki_tl)), D("-240.00"))
        kf = self.kf_kayitlari(iade.iade_no)
        self.assertEqual(len(kf), 1)
        self.assertEqual((kf[0].durum, D(str(kf[0].doviz_tutar)), D(str(kf[0].kaynak_tl)), D(str(kf[0].odeme_tl)),
                          D(str(kf[0].kur_farki))),
                         (KUR_FARKI_HESAPLANDI, D("120.00"), D("3600.00"), D("3840.00"), D("-240.00")))
        # İade fişi: 320 B 3840 / 153 A 3000 / 191 A 640 / fark A 200; kur farkı fişi: 656 B 240 / 320 A 240
        self.assertEqual(self.fark(once, self._tutarli()), {
            "320.01.0001": D("3600.00"), "153.01.0001": D("-3000.00"), "191.01.0001": D("-640.00"),
            MF: D("-200.00"), KFZ: D("240.00")})
        self.assertEqual(self.cari_alacak(iade.iade_no), D("3840.00"))
        self.assertEqual(len(self.etkin_fis("kur_farki", kf[0].id)), 1)
        self.assertEqual(S.kur_farki_kayitlari(iade.id)[0]["kur_farki"], D("-240.00"))
        # İptal: kur farkı kaydı iptal, iki fiş ters kayıtla kapanır; tekrar iptal etkisiz
        S.iptal_et(iade.id, "test")
        S.iptal_et(iade.id, "test")
        self.assertEqual(self.fark(once, self._tutarli()), {})
        self.assertEqual(self.kf_kayitlari(iade.iade_no), [])
        self.assertEqual([k.durum for k in self.kf_kayitlari(iade.iade_no, etkin=False)], [KUR_FARKI_IPTAL])

    def test_kur_azalisi_gelir_646(self):
        self.maliyet_farki_bagla()
        self.kur_farki_bagla()
        _fid, ks = self.alis_usd(kur="30")
        once = self._tutarli()
        iade = S.onayla(self.iade_usd(ks, kur="28").id)
        self.assertEqual(self.fark(once, self._tutarli()), {
            "320.01.0001": D("3600.00"), "153.01.0001": D("-3000.00"), "191.01.0001": D("-560.00"),
            MFN: D("200.00"), KFG: D("-240.00")})
        self.assertEqual(D(str(iade.satirlar[0].kur_farki_tl)), D("240.00"))

    def test_secenek_yoksa_kur_farki_incelemede_hesaplanmasin_muhasebe_disi(self):
        from database import muhasebe_finans_ayarlari as fa

        self.maliyet_farki_bagla()
        self.bagla("kur_farki_gideri", KFZ, "Kambiyo Zararları", "Gider")
        _fid, ks = self.alis_usd(kur="30")
        iade = S.onayla(self.iade_usd(ks, miktar="5", kur="32").id)
        kf = self.kf_kayitlari(iade.iade_no)[0]
        self.assertEqual(kf.durum, KUR_FARKI_HESAPLANDI)
        d = self._durum("kur_farki", kf.id)
        self.assertEqual(d["durum"], BELGE_INCELEME)
        self.assertIn("Alış iadesi kur farkı", d["aciklama"])
        self.assertEqual(self.etkin_fis("kur_farki"), [])
        self.assertEqual(self._durum("alis_iade", iade.id)["durum"], BELGE_MUHASEBELESTIRILDI)
        fa.kaydet({fa.ALIS_IADE_KUR_FARKI: "hesaplanmasin"})
        iade2 = S.onayla(self.iade_usd(ks, miktar="5", kur="32").id)
        kf2 = self.kf_kayitlari(iade2.iade_no)[0]
        self.assertEqual(self._durum("kur_farki", kf2.id)["durum"], BELGE_MUHASEBE_DISI)
        self.assertEqual(self.etkin_fis("kur_farki"), [])

    def test_kaynak_kuru_eksikse_tahmin_yok_inceleme(self):
        self.maliyet_farki_bagla()
        self.kur_farki_bagla()
        _fid, ks = self.alis_usd(kur="1")
        iade = S.onayla(self.iade_usd(ks, kur="32").id)
        kf = self.kf_kayitlari(iade.iade_no)[0]
        self.assertEqual((kf.durum, D(str(kf.kur_farki))), (KUR_FARKI_INCELEME, D("0")))
        self.assertIn("kaynak belge kuru yok", kf.aciklama)
        self.assertIsNone(S.getir(iade.id).satirlar[0].kur_farki_tl)
        self.assertEqual(self._durum("kur_farki", kf.id)["durum"], BELGE_INCELEME)
        self.assertEqual(self.etkin_fis("kur_farki"), [])

    def test_kismi_kismi_tam_ek_iade_engeli_iptalde_hak_doner(self):
        self.maliyet_farki_bagla()
        self.kur_farki_bagla()
        fid, ks = self.alis_usd(miktar="10", kur="30")
        once = self._tutarli()
        i1 = S.onayla(self.iade_usd(ks, miktar="4", kur="32").id)
        i2 = S.onayla(self.iade_usd(ks, miktar="6", kur="31").id)
        self.assertEqual(self.lot_kalan("LOT-U"), D("0"))
        oz = S.kaynak_iade_ozeti(fid)[0]
        self.assertEqual((oz["alinan_temel"], oz["iade_temel"], oz["kalan_temel"]), (D("10"), D("10"), D("0")))
        self.assertEqual([D(str(k.kur_farki)) for k in self.kf_kayitlari(i1.iade_no) + self.kf_kayitlari(i2.iade_no)],
                         [D("-96.00"), D("-72.00")])
        # Tam iade sonrası: kaynak alıştaki tüm döviz borcu kaynak kurla kapanır (10 × 12 USD × 30)
        self.assertEqual(self.fark(once, self._tutarli())["320.01.0001"], D("3600.00"))
        fazla = self.iade_usd(ks, miktar="1", kur="32")
        with self.assertRaises(ValueError) as ctx:
            S.onayla(fazla.id)
        self.assertIn("iade hakkı aşıldı", str(ctx.exception))
        S.iptal_et(i1.id, "test")
        self.assertEqual(S.kaynak_iade_ozeti(fid)[0]["kalan_temel"], D("4"))
        i3 = S.onayla(fazla.id)
        self.assertEqual(S.kaynak_iade_ozeti(fid)[0]["kalan_temel"], D("3"))
        self.assertEqual(len(self.kf_kayitlari(i3.iade_no)), 1)
        self.assertEqual({r["no"] for r in S.kaynaktan_iadeler(fid)}, {i1.iade_no, i2.iade_no, i3.iade_no})
        self._tutarli()

    def test_iki_kez_ve_eszamanli_onay_tek_kur_farki_tek_fis(self):
        self.maliyet_farki_bagla()
        self.kur_farki_bagla()
        _fid, ks = self.alis_usd(kur="30")
        taslak = self.iade_usd(ks, kur="32")
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
            t.join(60)
        self.assertEqual(hatalar, [])
        S.onayla(taslak.id)
        kf = self.kf_kayitlari(taslak.iade_no, etkin=False)
        self.assertEqual(len(kf), 1)
        self.assertEqual(len(self.etkin_fis("kur_farki", kf[0].id)), 1)
        self.assertEqual(len(self.etkin_fis("alis_iade", taslak.id)), 1)
        with get_session() as s:
            self.assertEqual(int(s.scalar(select(func.count()).select_from(StokHareketi).where(
                StokHareketi.belge_no == taslak.iade_no))), 1)
        self.assertEqual(self.cari_alacak(taslak.iade_no), D("3840.00"))

    def test_eszamanli_iptal_tek_ters_kayit(self):
        self.maliyet_farki_bagla()
        self.kur_farki_bagla()
        _fid, ks = self.alis_usd(kur="30")
        once = self._tutarli()
        iade = S.onayla(self.iade_usd(ks, kur="32").id)
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
            t.join(60)
        self.assertEqual(hatalar, [])
        self.assertEqual(self.fark(once, self._tutarli()), {})
        with get_session() as s:
            ters = s.scalar(select(func.count()).select_from(MuhasebeFisi).where(
                MuhasebeFisi.ters_fis_id.is_not(None)))
        self.assertEqual(int(ters), 2)  # iade fişi + kur farkı fişi, birer kez


# ====================================================================== dövizli iade KDV kuru yöntemi
class KdvKuruYontemiTest(_Taban):
    def setUp(self):
        super().setUp()
        self.maliyet_farki_bagla()
        self.kur_farki_bagla()

    def test_kaynak_alis_kuru_kdv_191_alis_kuruyla_kur_farki_kdv_haric(self):
        self.kdv_kuru_sec("kaynak_kuru")
        _fid, ks = self.alis_usd(kur="30")
        once = self._tutarli()
        iade = S.onayla(self.iade_usd(ks, kur="32").id)
        self.assertEqual((iade.kdv_kur_yontemi, D(str(iade.kdv_tl_toplam))), ("kaynak_kuru", D("600.00")))
        s0 = iade.satirlar[0]
        self.assertEqual((D(str(s0.kdv_kuru)), D(str(s0.kdv_tl))), (D("30"), D("600.00")))
        # İade fişi: 320 B 3800 / 153 A 3000 / 191 A 600 / 649 A 200; kur farkı (100 USD × 2): 656 B 200 / 320 A 200
        self.assertEqual(self.fark(once, self._tutarli()), {
            "320.01.0001": D("3600.00"), "153.01.0001": D("-3000.00"), "191.01.0001": D("-600.00"),
            MF: D("-200.00"), KFZ: D("200.00")})
        self.assertEqual(self._kalemler("alis_iade", iade.id)["320.01.0001"], (D("3800.00"), D("0")))
        kf = self.kf_kayitlari(iade.iade_no)
        self.assertEqual([(D(str(k.doviz_tutar)), D(str(k.kur_farki))) for k in kf], [(D("100.00"), D("-200.00"))])
        self.assertEqual(self.cari_alacak(iade.iade_no), D("3800.00"))
        self.assertEqual(S.belge_toplami(S.getir(iade.id))["genel_toplam"], D("3800.00"))
        self.assertEqual(self._durum("alis_iade", iade.id)["durum"], BELGE_MUHASEBELESTIRILDI)
        S.iptal_et(iade.id, "test")
        self.assertEqual(self.fark(once, self._tutarli()), {})
        self.assertEqual(self.cari_alacak(iade.iade_no), D("0"))

    def test_iade_tarihi_kuru_kdv_iade_kuruyla_kur_farki_kdv_dahil(self):
        self.kdv_kuru_sec("iade_kuru")
        _fid, ks = self.alis_usd(kur="30")
        once = self._tutarli()
        iade = S.onayla(self.iade_usd(ks, kur="32").id)
        self.assertEqual((iade.kdv_kur_yontemi, D(str(iade.kdv_tl_toplam))), ("iade_kuru", D("640.00")))
        self.assertEqual(self.fark(once, self._tutarli()), {
            "320.01.0001": D("3600.00"), "153.01.0001": D("-3000.00"), "191.01.0001": D("-640.00"),
            MF: D("-200.00"), KFZ: D("240.00")})
        self.assertEqual(self._kalemler("alis_iade", iade.id)["320.01.0001"], (D("3840.00"), D("0")))
        self.assertEqual(self.cari_alacak(iade.iade_no), D("3840.00"))

    def test_yontem_secilmemisse_onaylanir_kesin_fis_yok_secince_tek_fis(self):
        from database.muhasebe_finans_ayarlari import KDV_KURU_EKSIK_MESAJI

        _fid, ks = self.alis_usd(kur="30")
        taslak = self.iade_usd(ks, kur="32")
        self.assertEqual(S.getir(taslak.id).durum, "TASLAK")
        iade = S.onayla(taslak.id)
        self.assertIn(iade.durum, ("AÇIK", "KAPALI"))
        self.assertIsNone(iade.kdv_kur_yontemi)
        d = self._durum("alis_iade", iade.id)
        self.assertEqual(d["durum"], BELGE_INCELEME)
        self.assertIn(KDV_KURU_EKSIK_MESAJI, d["aciklama"])
        self.assertEqual(self.etkin_fis("alis_iade", iade.id), [])
        kf = self.kf_kayitlari(iade.iade_no)[0]
        self.assertEqual(self._durum("kur_farki", kf.id)["durum"], BELGE_INCELEME)
        self.assertEqual(self.etkin_fis("kur_farki"), [])
        # Stok ve cari etkisi onayda oluştu (KDV belge kuruyla)
        self.assertEqual(self.lot_kalan("LOT-U"), D("90"))
        self.assertEqual(self.cari_alacak(iade.iade_no), D("3840.00"))
        self.kdv_kuru_sec("iade_kuru")
        for _ in range(2):
            self._servis().muhasebelestir([self._durum_id("alis_iade", iade.id),
                                           self._durum_id("kur_farki", kf.id)])
        self.assertEqual(len(self.etkin_fis("alis_iade", iade.id)), 1)
        self.assertEqual(len(self.etkin_fis("kur_farki", kf.id)), 1)
        self.assertEqual(S.getir(iade.id).kdv_kur_yontemi, "iade_kuru")
        self._tutarli()

    def test_yontemsiz_onaylanan_iadeye_kaynak_kuru_sonradan_uygulanmaz(self):
        _fid, ks = self.alis_usd(kur="30")
        iade = S.onayla(self.iade_usd(ks, kur="32").id)
        self.assertEqual(self._durum("alis_iade", iade.id)["durum"], BELGE_INCELEME)
        self.kdv_kuru_sec("kaynak_kuru")
        # Elle yeniden deneme mevcut kurala göre 'Hatalı' + neden yazar; fiş tahmin edilmez
        self._servis().muhasebelestir([self._durum_id("alis_iade", iade.id)])
        d = self._durum("alis_iade", iade.id)
        self.assertEqual(d["durum"], BELGE_HATALI)
        self.assertIn("sonradan uygulanamaz", d["aciklama"])
        self.assertEqual(self.etkin_fis("alis_iade", iade.id), [])

    def test_kaynak_kuru_bilinmeyen_satirda_onay_yapilmaz(self):
        self.kdv_kuru_sec("kaynak_kuru")
        _fid, ks = self.alis_usd(kur="1")
        taslak = self.iade_usd(ks, kur="32")
        with self.assertRaises(ValueError) as ctx:
            S.onayla(taslak.id)
        self.assertIn("Kaynak alış kuru", str(ctx.exception))
        self.assertEqual(S.getir(taslak.id).durum, "TASLAK")
        self.assertEqual(self.lot_kalan("LOT-U"), D("100"))
        self.assertEqual(self.cari_alacak(taslak.iade_no), D("0"))

    def test_tl_iade_yontem_gerektirmez(self):
        _fid, ks = self._alis(miktar="100", fiyat="100")
        iade = S.onayla(self._iade(ks, miktar="10", fiyat="100").id)
        self.assertIsNone(iade.kdv_kur_yontemi)
        self.assertIsNone(iade.kdv_tl_toplam)
        self.assertEqual(self._durum("alis_iade", iade.id)["durum"], BELGE_MUHASEBELESTIRILDI)


# ====================================================================== maliyet farkı: ayrı olumlu/olumsuz eşleme
class MaliyetFarkiEslemeTest(_Taban):
    def test_olumlu_fark_yalniz_olumlu_hesaba(self):
        self.maliyet_farki_bagla(olumsuz=False)
        _fid, ks = self._alis(miktar="100", fiyat="100")
        iade = S.onayla(self._iade(ks, miktar="10", fiyat="130").id)
        self.assertEqual(self._durum("alis_iade", iade.id)["durum"], BELGE_MUHASEBELESTIRILDI)
        k = self._kalemler("alis_iade", iade.id)
        self.assertEqual(k[MF], (D("0"), D("300.00")))
        self.assertNotIn(MFN, k)

    def test_olumsuz_fark_eksik_eslemede_inceleme_sonra_tek_fis_iptal_ters(self):
        self.maliyet_farki_bagla(olumsuz=False)
        _fid, ks = self._alis(miktar="100", fiyat="100")
        once = self._tutarli()
        iade = S.onayla(self._iade(ks, miktar="10", fiyat="70").id)
        d = self._durum("alis_iade", iade.id)
        self.assertEqual(d["durum"], BELGE_INCELEME)
        self.assertIn("alis_iade_maliyet_farki_olumsuz", d["aciklama"])
        self.assertIn("300.00 TL olumsuz", d["aciklama"])
        self.assertNotIn("alis_iade_maliyet_farki_olumlu", d["aciklama"])
        self.assertEqual(self.etkin_fis("alis_iade", iade.id), [])
        self.maliyet_farki_bagla(olumlu=False)
        for _ in range(2):
            self._servis().muhasebelestir([self._durum_id("alis_iade", iade.id)])
        self.assertEqual(len(self.etkin_fis("alis_iade", iade.id)), 1)
        self.assertEqual(self._kalemler("alis_iade", iade.id)[MFN], (D("300.00"), D("0")))
        S.iptal_et(iade.id, "test")
        self.assertEqual(self.fark(once, self._tutarli()), {})
        self.assertEqual(self.etkin_fis("alis_iade", iade.id), [])

    def test_sifir_farkta_esleme_aranmaz(self):
        _fid, ks = self._alis(miktar="100", fiyat="100")
        iade = S.onayla(self._iade(ks, miktar="10", fiyat="100").id)
        self.assertEqual(self._durum("alis_iade", iade.id)["durum"], BELGE_MUHASEBELESTIRILDI)
        k = self._kalemler("alis_iade", iade.id)
        self.assertNotIn(MF, k)
        self.assertNotIn(MFN, k)

    def test_eski_tek_esleme_doluysa_tasinmaz(self):
        self.bagla("alis_iade_maliyet_farki", MF, "Eski tek eşleme", "Gelir")
        _fid, ks = self._alis(miktar="100", fiyat="100")
        iade = S.onayla(self._iade(ks, miktar="10", fiyat="120").id)
        self.assertEqual(self._durum("alis_iade", iade.id)["durum"], BELGE_INCELEME)
        self.assertEqual(self.etkin_fis("alis_iade", iade.id), [])

    def test_ekran_verisi_iki_ayri_hesap_bos_varsayilan(self):
        from database import muhasebe_finans_ayarlari as fa

        veri = fa.ekran_verisi()
        grup = next(g for g in veri["gruplar"] if g["baslik"] == "Alış iadesi")
        self.assertEqual([s["anahtar"] for s in grup["satirlar"]],
                         ["alis_iade_maliyet_farki_olumlu", "alis_iade_maliyet_farki_olumsuz"])
        self.assertTrue(all(s["hesap_kodu"] is None for s in grup["satirlar"]))
        self.assertIsNone(veri["secenekler"].get(fa.ALIS_IADE_KDV_KURU))


# ====================================================================== Kaynağı Aç / Bağlı İadeler
class KaynagiAcTest(_Taban):
    def setUp(self):
        super().setUp()
        try:
            self.root = tk.Tk()
        except tk.TclError as hata:
            super().tearDown()
            self.skipTest(f"Tk yok: {hata}")
        self.root.withdraw()
        self.mesajlar: list[str] = []
        self._mb = patch.multiple(
            "tkinter.messagebox",
            showinfo=lambda _b, m="", **_k: self.mesajlar.append(m),
            showwarning=lambda _b, m="", **_k: self.mesajlar.append(m),
            showerror=lambda _b, m="", **_k: self.mesajlar.append(f"HATA: {m}"),
            askyesno=lambda *a, **k: True)
        self._mb.start()

    def tearDown(self):
        self._mb.stop()
        try:
            self.root.destroy()
        except tk.TclError:
            pass
        super().tearDown()

    def pencere(self, iade):
        from alis_iade_ui import AlisIadeFaturasiPenceresi

        p = AlisIadeFaturasiPenceresi(self.root, iade_id=int(iade.id))
        p.withdraw()
        p.update_idletasks()
        return p

    def test_tek_kaynak_alis_faturasi_penceresinde_acilir(self):
        import alis_ui

        self.maliyet_farki_bagla()
        fid, ks = self._alis(miktar="100", fiyat="100")
        iade = S.onayla(self._iade(ks, miktar="5").id)
        p = self.pencere(iade)
        p.tablo.selection_set(p.tablo.get_children()[0])
        acilan = []

        class Sahte(alis_ui.AlisFaturasiDialog):
            def __init__(s, parent, fatura=None, **kw):
                super().__init__(parent, fatura=fatura, **kw)
                s.withdraw()
                acilan.append(s)

        with patch.object(alis_ui, "AlisFaturasiDialog", Sahte), patch.object(p, "wait_window", lambda *_a: None):
            p.kaynagi_ac()
        self.assertEqual(len(acilan), 1)
        self.assertEqual(int(acilan[0].fatura.id), fid)
        # Kaynak faturada 'Bağlı İadeler': iade görünür, kalan hak doğru, iade oradan açılır
        with patch.object(acilan[0], "wait_window", lambda *_a: None):
            bagli = acilan[0]._bagli_iadeler()
        bagli.withdraw()
        self.assertEqual([bagli.tablo.item(i, "values")[0] for i in bagli.tablo.get_children()], [iade.iade_no])
        hak = bagli.hak.item(bagli.hak.get_children()[0], "values")
        self.assertEqual(hak[3].split()[0], "95")
        bagli.tablo.selection_set(str(iade.id))
        with patch.object(bagli, "wait_window", lambda *_a: None):
            ip = bagli.iadeyi_ac()
        self.assertEqual(int(ip.iade.id), iade.id)
        for w in (ip, bagli, acilan[0], p):
            w.destroy()

    def test_coklu_kaynak_secim_listesi_ve_kaynaksiz_bilgi(self):
        self.maliyet_farki_bagla()
        fid1, ks1 = self._alis(miktar="10", fiyat="100", lot="LOT-A")
        fid2, ks2 = self._alis(miktar="10", fiyat="100", lot="LOT-B")
        iade = S.onayla(S.kaydet(
            {"iade_tarihi": self.T, "cari_id": self.tedarikci_id, "depo": "ANA DEPO"},
            [{"urun_kodu": "U001", "urun_adi": "U001", "miktar": D("6"), "birim": "Adet", "birim_fiyat": D("100"),
              "kdv_orani": D("20"), "kaynaklar": [{"kaynak_fatura_satiri_id": ks1, "miktar": D("3")},
                                                    {"kaynak_fatura_satiri_id": ks2, "miktar": D("3")}]}]).id)
        p = self.pencere(iade)
        p.tablo.selection_set(p.tablo.get_children()[0])
        secenekler, acilan = [], []

        def sec(faturalar):
            secenekler.append([f["fatura_id"] for f in faturalar])
            return faturalar[1]

        with patch.object(p, "_kaynak_fatura_sec", sec), patch.object(p, "_alis_faturasi_ac", acilan.append):
            p.kaynagi_ac()
        self.assertEqual(secenekler, [[fid1, fid2]])
        self.assertEqual(acilan, [fid2])
        p.destroy()
        # Devir satırı: alış faturası açılmaz, açıklayıcı bilgi
        from database.stok_service import StokService

        StokService.stok_girisi("U001", "ANA DEPO", "", date(2026, 1, 1), D("5"), D("90"), "DEVIR-1")
        with get_session() as s:
            lot_id = int(s.scalar(select(StokLotu.id).where(StokLotu.lot_no == "DEVIR-1")))
        devir = S.onayla(S.kaydet(
            {"iade_tarihi": self.T, "cari_id": self.tedarikci_id, "depo": "ANA DEPO"},
            [{"urun_kodu": "U001", "urun_adi": "U001", "miktar": D("1"), "birim": "Adet", "birim_fiyat": D("90"),
              "kdv_orani": D("20"), "kaynak_durumu": "DEVİR", "kaynak_lot_id": lot_id}]).id)
        p2 = self.pencere(devir)
        p2.tablo.selection_set(p2.tablo.get_children()[0])
        acilan.clear()
        with patch.object(p2, "_alis_faturasi_ac", acilan.append):
            p2.kaynagi_ac()
        self.assertEqual(acilan, [])
        self.assertIn("devir", self.mesajlar[-1].lower())
        self.assertIn("bağlı bir alış faturası yok", self.mesajlar[-1])
        p2.destroy()


if __name__ == "__main__":
    unittest.main()
