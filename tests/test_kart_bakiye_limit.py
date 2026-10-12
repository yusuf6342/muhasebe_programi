"""Kart bakiyesi / limit düzeltmesi — talimatın kabul kontrolleri (K1–K10) ve talimattaki örnek tutarlar.

Yalnız geçici test veritabanı (StokOrtami); gerçek firma verisine dokunmaz. Kart: kesim günü 7, son ödeme 12;
bugün 12.10.2026 kabul edilir.
"""

from __future__ import annotations

import sqlite3
import tempfile
import unittest
from datetime import date
from decimal import Decimal as D
from pathlib import Path
from unittest.mock import MagicMock, patch

from sqlalchemy import create_engine, func, inspect, select

from tests.stok_test_ortami import StokOrtami
from tests.test_gider_kart_odeme import bugun

from database import kart_bakiye_gecis as kbg
from database import kart_bakiye_onarim as onarim
from database import odeme_takvimi_service as ots
from database.database import get_session
from database.finans_service import FinansService
from database.kredi_karti_ekstre_service import KrediKartiEkstreService as E
from database.models.finans import (
    BankaKarti,
    FinansHareketi,
    FinansHesabi,
    GiderFisi,
    KartBakiyeOnarimGunlugu,
    KrediKartiEkstre,
    KrediKartiEkstreOdeme,
    KrediKartiEkstreOdemeTaksit,
    KrediKartiOdeme,
    KrediKartiOdemeTaksit,
    KrediKartiTanimi,
)
from database.muhasebe_entegrasyon import (
    DESTEKLENMEYEN_EVRAKLAR,
    EVRAKLAR,
    MuhasebeEntegrasyonService as H,
)

BUGUN = date(2026, 10, 12)
K1, K2, K3 = date(2026, 10, 7), date(2026, 11, 7), date(2026, 12, 7)


class KartBakiyeLimitTest(unittest.TestCase):
    def setUp(self):
        self.ort = StokOrtami("kart_bakiye")
        with get_session() as s:
            banka = BankaKarti(banka_adi="Akbank", sube="Merkez", aktif=True)
            s.add(banka)
            s.flush()
            mev = FinansHesabi(hesap_adi="Akbank Mevduat", hesap_turu="BANKA", alt_hesap_turu="MEVDUAT",
                               banka_karti_id=banka.id, acilis_bakiyesi=D("1000000"), aktif=True)
            kk = FinansHesabi(hesap_adi="Akbank Kredi Kartı", hesap_turu="BANKA", alt_hesap_turu="KREDI_KARTI",
                              banka_karti_id=banka.id, acilis_bakiyesi=D("0"), aktif=True)
            kasa = FinansHesabi(hesap_adi="Merkez Kasa", hesap_turu="KASA", acilis_bakiyesi=D("100000"), aktif=True)
            s.add_all([mev, kk, kasa])
            s.flush()
            kart = KrediKartiTanimi(banka_karti_id=banka.id, kart_adi="TİCARİ AXESS", hesap_kesim_gunu=7,
                                    son_odeme_gunu=12, kart_limiti=D("50000"), aktif=True)
            s.add(kart)
            s.flush()
            self.banka_id, self.mev_id, self.kk_id, self.kasa_id = banka.id, mev.id, kk.id, kasa.id
            self.kart_id = kart.id
        self._n = 0

    def tearDown(self):
        self.ort.kapat()

    # ------------------------------------------------------------------ yardımcılar
    def anahtar(self) -> str:
        self._n += 1
        return f"kb-{self._n}"

    def harca(self, tutar, tarih=date(2026, 9, 20), n=1) -> str:
        with bugun(BUGUN):
            return FinansService.kredi_karti_odeme(
                self.banka_id, self.kart_id, self.ort.ted_id, tarih, tutar,
                cekim_turu="TAKSITLI" if n > 1 else "TEK_CEKIM", taksit_sayisi=n)["belge_no"]

    def ekstre(self, kesim=K1) -> dict:
        with bugun(BUGUN):
            return next(h for h in E.ekstreleri_hesapla(bugun=BUGUN, kredi_karti_id=self.kart_id)
                        if h["kesim_tarihi"] == kesim)

    def ode(self, tutar, kesim=K1, tarih=BUGUN, hesap=None, anahtar=None) -> dict:
        eid = self.ekstre(kesim)["ekstre_id"]
        with bugun(BUGUN):
            return E.odeme_yap(ekstre_id=eid, tutar=tutar, tarih=tarih, finans_hesap_id=hesap or self.mev_id,
                               istek_anahtari=anahtar or self.anahtar())

    def iptal(self, belge, neden="Hatalı ödeme", tarih=BUGUN):
        with bugun(BUGUN):
            return E.odeme_iptal(belge, neden, tarih=tarih)

    def ozet(self, tarih=None) -> dict:
        with bugun(BUGUN):
            return E.kart_borc_ozeti(self.kart_id, tarih=tarih)

    def bakiye(self, hesap_id) -> D:
        with get_session() as s:
            return D(str(FinansService.bakiye(s.get(FinansHesabi, hesap_id)))).quantize(D("0.01"))

    def limit(self, deger):
        with get_session() as s:
            s.get(KrediKartiTanimi, self.kart_id).kart_limiti = deger

    def hareketler(self, hesap_id) -> list[tuple[str, D]]:
        with get_session() as s:
            return [(h.hareket_turu, D(str(h.tutar))) for h in s.scalars(
                select(FinansHareketi).where(FinansHareketi.hesap_id == hesap_id)
                .order_by(FinansHareketi.id)).all()]

    def taksit_durumlari(self, belge) -> list[str]:
        with get_session() as s:
            ko = s.scalar(select(KrediKartiOdeme).where(KrediKartiOdeme.belge_no == belge))
            return [t.durum for t in s.scalars(select(KrediKartiOdemeTaksit).where(
                KrediKartiOdemeTaksit.odeme_id == ko.id).order_by(KrediKartiOdemeTaksit.taksit_no)).all()]

    def baglar(self, belge) -> list[tuple[D, bool]]:
        with get_session() as s:
            o = s.scalar(select(KrediKartiEkstreOdeme).where(KrediKartiEkstreOdeme.belge_no == belge))
            return [(D(str(b.tutar)), bool(b.iptal)) for b in s.scalars(select(KrediKartiEkstreOdemeTaksit).where(
                KrediKartiEkstreOdemeTaksit.ekstre_odeme_id == o.id).order_by(KrediKartiEkstreOdemeTaksit.id))]

    # ------------------------------------------------------------------ K1–K3: ödeme, işaret, limit
    def test_k1_k3_ekstre_odeme_bakiye_isareti_ve_limit(self):
        self.harca("30000")
        self.assertEqual(self.bakiye(self.kk_id), D("30000.00"))
        self.assertEqual(FinansService.varlik_bakiyesi(self.bakiye(self.kk_id), alt_tur="KREDI_KARTI"),
                         D("-30000.00"))
        oz = self.ozet()
        self.assertEqual((oz["toplam_borc"], oz["kullanilan"], oz["kullanilabilir"]),
                         (D("30000.00"), D("30000.00"), D("20000.00")))
        self.assertEqual(self.ekstre()["kalan"], D("30000.00"))

        sonuc = self.ode("10000")
        self.assertTrue(sonuc["belge_no"].startswith("KKE"))
        self.assertEqual(self.bakiye(self.kk_id), D("20000.00"))
        self.assertEqual(self.bakiye(self.mev_id), D("990000.00"))
        self.assertEqual(FinansService.varlik_bakiyesi(self.bakiye(self.kk_id), alt_tur="KREDI_KARTI"),
                         D("-20000.00"))
        oz = self.ozet()
        self.assertEqual((oz["kullanilan"], oz["kullanilabilir"]), (D("20000.00"), D("30000.00")))
        self.assertEqual(FinansService.kredi_karti_kullanilan(self.kart_id), D("20000.00"))
        e = self.ekstre()
        self.assertEqual((e["odenen"], e["kalan"], e["ekstre_durum"]), (D("10000.00"), D("20000.00"), "KISMI"))
        self.assertEqual(e["kart_ozeti"]["kullanilabilir"], D("30000.00"))

    def test_limit_kontrolu_ortak_hesaptan(self):
        self.harca("30000")
        with self.assertRaisesRegex(ValueError, "Kart limiti yetersiz"):
            self.harca("20000.01")
        self.harca("20000")
        self.assertEqual(self.ozet()["kullanilabilir"], D("0.00"))
        self.ode("5000")
        self.harca("5000")

    def test_limit_sifir_veya_bos_tanimsiz(self):
        from database.kredi_karti_ekstre_service import limit_tanimli

        self.assertFalse(limit_tanimli(None))
        self.limit(D("0"))
        self.harca("70000")
        oz = self.ozet()
        self.assertFalse(oz["limit_tanimli"])
        self.assertIsNone(oz["limit"])
        self.assertIsNone(oz["kullanilabilir"])
        self.assertEqual(oz["kullanilan"], D("70000.00"))

    # ------------------------------------------------------------------ K4: taksitler ve gelecek dönem
    def test_k4_uc_taksit_kismi_ve_tam_odeme(self):
        belge = self.harca("12000", n=3)
        self.assertEqual(self.ozet()["kullanilabilir"], D("38000.00"))
        self.assertEqual([self.ekstre(k)["kalan"] for k in (K1, K2, K3)], [D("4000.00")] * 3)

        self.ode("4000")
        self.assertEqual(self.taksit_durumlari(belge), ["ODENDI", "BEKLIYOR", "BEKLIYOR"])
        oz = self.ozet()
        self.assertEqual((oz["toplam_borc"], oz["kullanilabilir"]), (D("8000.00"), D("42000.00")))
        self.assertEqual(self.ekstre(K2)["kalan"], D("4000.00"))
        self.assertEqual(self.ekstre(K3)["kalan"], D("4000.00"))

        self.ode("4000", kesim=K2)
        self.ode("4000", kesim=K3)
        self.assertEqual(self.taksit_durumlari(belge), ["ODENDI"] * 3)
        oz = self.ozet()
        self.assertEqual((oz["toplam_borc"], oz["kullanilabilir"]), (D("0.00"), D("50000.00")))
        self.assertEqual(self.bakiye(self.kk_id), D("0.00"))

    # ------------------------------------------------------------------ K5: takvim penceresi dışı borç
    def test_k5_pencere_disi_taksit_kullanilan_limitte(self):
        self.harca("24000", n=24)
        v = ots.hesapla(BUGUN)
        kart = [k for a in v["aylar"] for k in a["kalemler"] if k["tur"] == ots.TUR_KART]
        self.assertLessEqual(len(kart), 4)
        self.assertLess(sum((k["kalan"] for k in kart), D("0")), D("24000"))
        oz = self.ozet()
        self.assertEqual((oz["kullanilan"], oz["kullanilabilir"]), (D("24000.00"), D("26000.00")))
        self.assertEqual(self.bakiye(self.kk_id), D("24000.00"))

    # ------------------------------------------------------------------ AXESS 07.10 örneği: kısmi ödemeler
    def test_axess_10000_ve_17773_81_kismi_odeme_ve_iptal(self):
        self.limit(D("600000"))
        a = self.harca("77750", tarih=date(2026, 9, 9), n=7)
        b = self.harca("150000", tarih=date(2026, 9, 17), n=9)
        self.assertEqual(self.bakiye(self.kk_id), D("227750.00"))
        self.assertEqual(self.ekstre()["tl_tutar"], D("27773.81"))
        self.assertEqual(self.ozet()["kullanilabilir"], D("372250.00"))

        o1 = self.ode("10000", tarih=date(2026, 10, 7))
        self.assertEqual(self.taksit_durumlari(a)[0], "BEKLIYOR")
        self.assertEqual(self.baglar(o1["belge_no"]), [(D("10000.00"), False)])
        self.assertEqual(self.ekstre()["kalan"], D("17773.81"))

        o2 = self.ode("17773.81", tarih=date(2026, 10, 7))
        self.assertEqual(self.taksit_durumlari(a)[0], "ODENDI")
        self.assertEqual(self.taksit_durumlari(b)[0], "ODENDI")
        self.assertEqual(self.taksit_durumlari(a)[1:], ["BEKLIYOR"] * 6)
        self.assertEqual(self.baglar(o2["belge_no"]), [(D("1107.14"), False), (D("16666.67"), False)])
        e = self.ekstre()
        self.assertEqual((e["kalan"], e["ekstre_durum"]), (D("0.00"), "ODENDI"))
        self.assertEqual(self.bakiye(self.kk_id), D("199976.19"))
        oz = self.ozet()
        self.assertEqual((oz["kullanilan"], oz["kullanilabilir"]), (D("199976.19"), D("400023.81")))
        self.assertEqual(self.bakiye(self.mev_id), D("972226.19"))

        self.iptal(o2["belge_no"], "Banka dekontu tutmadı", tarih=date(2026, 10, 10))
        self.assertEqual(self.taksit_durumlari(a)[0], "BEKLIYOR")
        self.assertEqual(self.taksit_durumlari(b)[0], "BEKLIYOR")
        self.assertEqual(self.baglar(o2["belge_no"]), [(D("1107.14"), True), (D("16666.67"), True)])
        self.assertEqual(self.baglar(o1["belge_no"]), [(D("10000.00"), False)])
        self.assertEqual(self.ekstre()["kalan"], D("17773.81"))
        self.assertEqual(self.bakiye(self.kk_id), D("217750.00"))
        self.assertEqual(self.bakiye(self.mev_id), D("990000.00"))
        # tarihli görünüm: iptal edilen ödeme ödeme ile iptal tarihi arasında geçerlidir
        self.assertEqual(self.ozet(date(2026, 10, 9))["kullanilan"], D("199976.19"))
        self.assertEqual(self.ozet(date(2026, 10, 10))["kullanilan"], D("217750.00"))
        self.assertEqual(self.ozet(date(2026, 10, 6))["kullanilan"], D("227750.00"))

    # ------------------------------------------------------------------ K6: iptal ve çift etki
    def test_k6_iptal_ters_hareket_mukerrer_yok_muhasebe_bir_kez(self):
        self.harca("30000")
        kayit = MagicMock()
        with patch("database.muhasebe_entegrasyon.muhasebe_hook", kayit):
            o1 = self.ode("10000", anahtar="ayni-istek")
            tekrar = self.ode("10000", anahtar="ayni-istek")
            self.assertTrue(tekrar["mevcut"])
            self.assertEqual(tekrar["belge_no"], o1["belge_no"])
            with get_session() as s:
                self.assertEqual(s.scalar(select(func.count(KrediKartiEkstreOdeme.id))), 1)
            self.assertEqual(self.bakiye(self.kk_id), D("20000.00"))
            self.assertEqual([c.args[0] for c in kayit.call_args_list], ["kk_ekstre_odeme_fisi"])

            with self.assertRaisesRegex(ValueError, "nedeni"):
                self.iptal(o1["belge_no"], "  ")
            self.iptal(o1["belge_no"], "Yanlış ekstre")
            with self.assertRaisesRegex(ValueError, "zaten iptal"):
                self.iptal(o1["belge_no"], "İkinci kez")
        self.assertEqual([c.args[0] for c in kayit.call_args_list],
                         ["kk_ekstre_odeme_fisi", "kk_ekstre_odeme_iptal"])
        self.assertEqual(kayit.call_args_list[1].args[2], "Yanlış ekstre")
        self.assertEqual(self.hareketler(self.kk_id), [
            ("KK ÖDEME", D("30000.00")), ("KK EKSTRE ÖDEME", D("10000.00")),
            ("KK EKSTRE ÖDEME İPTAL", D("10000.00"))])
        self.assertEqual(self.bakiye(self.kk_id), D("30000.00"))
        self.assertEqual(self.bakiye(self.mev_id), D("1000000.00"))
        with get_session() as s:
            o = s.scalar(select(KrediKartiEkstreOdeme))
            self.assertEqual((o.iptal, o.iptal_nedeni, o.iptal_kullanici, o.iptal_islem_tarihi),
                             (True, "Yanlış ekstre", "Test Admin", BUGUN))
        # yenileme ikinci etki üretmez
        self.ekstre()
        self.ekstre()
        self.assertEqual(self.ekstre()["kalan"], D("30000.00"))
        self.assertEqual(self.bakiye(self.kk_id), D("30000.00"))

    def test_muhasebe_fisi_kart_borcu_borc_banka_alacak(self):
        self.assertIn("kk_ekstre_odeme", EVRAKLAR)
        self.assertFalse(any("ekstre" in ad.lower() and "taksit ödemesi" in ad.lower()
                             for ad, _ in DESTEKLENMEYEN_EVRAKLAR))
        self.harca("30000")
        o = self.ode("10000")
        with patch.object(H, "_finans_karsiligi_ayarli", staticmethod(lambda h, s: {"id": h.hesap_adi})):
            with get_session() as s:
                fis = H._plan_kk_ekstre_odeme(s, o["odeme_id"])
        self.assertEqual([(r["hesap_id"], r["borc"], r["alacak"]) for r in fis["satirlar"]],
                         [("Akbank Kredi Kartı", D("10000.00"), D("0")), ("Akbank Mevduat", D("0"), D("10000.00"))])
        self.iptal(o["belge_no"])
        with get_session() as s:
            self.assertIsNone(H._plan_kk_ekstre_odeme(s, o["odeme_id"]))

    def test_odeme_hesabi_zorunlu_ve_tur_kontrolu(self):
        self.harca("30000")
        eid = self.ekstre()["ekstre_id"]
        with bugun(BUGUN):
            with self.assertRaisesRegex(ValueError, "hesabını seçin"):
                E.odeme_yap(ekstre_id=eid, tutar="100", tarih=BUGUN)
            with self.assertRaisesRegex(ValueError, "yalnız kasa"):
                E.odeme_yap(ekstre_id=eid, tutar="100", tarih=BUGUN, finans_hesap_id=self.kk_id)
            with self.assertRaisesRegex(ValueError, "büyük olamaz"):
                E.odeme_yap(ekstre_id=eid, tutar="30000.02", tarih=BUGUN, finans_hesap_id=self.mev_id)
        self.ode("1000", hesap=self.kasa_id)
        self.assertEqual(self.bakiye(self.kasa_id), D("99000.00"))
        self.assertEqual(self.bakiye(self.kk_id), D("29000.00"))

    # ------------------------------------------------------------------ D1: kasadan / virmanla karta ödeme
    def test_d1_kasadan_ve_virmanla_karta_odeme_ekstreden(self):
        self.harca("30000")
        eid = self.ekstre()["ekstre_id"]
        with bugun(BUGUN):
            with self.assertRaisesRegex(ValueError, "[Ee]kstre"):
                FinansService.kasadan_bankaya_yatan(self.kasa_id, self.kk_id, BUGUN, "1000")
            b1 = FinansService.kasadan_bankaya_yatan(self.kasa_id, self.kk_id, BUGUN, "4000", ekstre_id=eid,
                                                     istek_anahtari="kby-1")
            with self.assertRaises(ValueError):
                FinansService.kasadan_bankaya_yatan(self.kasa_id, self.kk_id, BUGUN, "4000", ekstre_id=eid,
                                                    belge_no=b1)
            b2 = FinansService.banka_hesaplari_arasi_virman(self.mev_id, self.kk_id, BUGUN, "6000", ekstre_id=eid,
                                                            istek_anahtari="vir-1")
        self.assertTrue(b1.startswith("KKE") and b2.startswith("KKE"))
        turler = {t for t, _ in self.hareketler(self.kk_id)}
        self.assertEqual(turler, {"KK ÖDEME", "KK EKSTRE ÖDEME"})
        self.assertEqual(self.bakiye(self.kk_id), D("20000.00"))
        self.assertEqual(self.bakiye(self.kasa_id), D("96000.00"))
        self.assertEqual(self.bakiye(self.mev_id), D("994000.00"))
        self.assertEqual(self.ekstre()["kalan"], D("20000.00"))
        with get_session() as s:
            self.assertEqual(sorted(o.kaynak for o in s.scalars(select(KrediKartiEkstreOdeme))),
                             ["KASADAN_BANKAYA", "VIRMAN"])

    # ------------------------------------------------------------------ K7–K8: eksik son ödeme / kesim
    def test_k7_k8_eksik_son_odeme_kaydedilir_tamamlaninca_duzelir(self):
        with get_session() as s:
            s.get(KrediKartiTanimi, self.kart_id).son_odeme_gunu = None
        self.harca("30000", tarih=date(2026, 8, 20))
        e = self.ekstre(date(2026, 9, 7))
        self.assertIsNone(e["son_odeme_tarihi"])
        self.assertEqual((e["ekstre_durum"], e["durum"]), ("EKSIK_BILGI", "EKSIK_BILGI"))
        self.assertEqual(self.ozet()["kullanilan"], D("30000.00"))
        v = ots.hesapla(BUGUN)
        self.assertTrue(any(x["tur"] == ots.TUR_KART and "Son ödeme" in x["neden"] for x in v["eksikler"]))
        tum = [k for k in v["gecmis"] + [k for a in v["aylar"] for k in a["kalemler"]] if k["tur"] == ots.TUR_KART]
        self.assertTrue(tum and not any(k.get("gecikmis") for k in tum))

        o = self.ode("10000", kesim=date(2026, 9, 7))
        self.assertTrue(o["belge_no"].startswith("KKE"))
        hareket = len(self.hareketler(self.kk_id))
        with get_session() as s:
            s.get(KrediKartiTanimi, self.kart_id).son_odeme_gunu = 12
        e = self.ekstre(date(2026, 9, 7))
        self.assertEqual(e["son_odeme_tarihi"], date(2026, 9, 12))
        self.assertEqual(e["ekstre_durum"], "GECIKMIS")
        self.assertEqual(len(self.hareketler(self.kk_id)), hareket)
        with get_session() as s:
            self.assertEqual(s.scalar(select(func.count(KrediKartiEkstreOdeme.id))), 1)

    # ------------------------------------------------------------------ K9–K10: geçmiş kayıt tarayıcısı
    def _eski_kayitlar(self):
        self.harca("30000")
        self.ode("5000")
        eid = self.ekstre()["ekstre_id"]
        with get_session() as s:
            s.add(KrediKartiEkstreOdeme(ekstre_id=eid, belge_no="KKE-ESKI-1", tarih=BUGUN, tutar=D("3000"),
                                        hesap_turu="MEVDUAT", finans_hesap_id=self.mev_id,
                                        finans_belge_no="KKE-ESKI-1"))
            s.add(FinansHareketi(hesap_id=self.mev_id, tarih=BUGUN, hareket_turu="KK EKSTRE ÖDEME",
                                 belge_no="KKE-ESKI-1", tutar=D("3000")))
            s.add(GiderFisi(belge_no="GF-ESKI-1", tarih=BUGUN, gider_turu="HIZMET", tutar=D("2000"),
                            finans_hesap_id=self.kk_id))
            s.add(FinansHareketi(hesap_id=self.kk_id, tarih=BUGUN, hareket_turu="GİDER FİŞİ",
                                 belge_no="GF-ESKI-1", tutar=D("2000")))
            s.add(FinansHareketi(hesap_id=self.kk_id, tarih=BUGUN, hareket_turu="KASADAN BANKAYA YATAN",
                                 belge_no="KBY-ESKI-1", tutar=D("1000")))
            s.add(FinansHareketi(hesap_id=self.kk_id, tarih=BUGUN, hareket_turu="KK İADE",
                                 belge_no="IADE-1", tutar=D("500")))
            s.add(FinansHesabi(hesap_adi="KREDİ KARTI POS", hesap_turu="KREDİ KARTI", alt_hesap_turu="",
                               acilis_bakiyesi=D("0"), aktif=True))

    def test_k9_k10_tarayici_kuru_uygula_tekrar_geri_al(self):
        self._eski_kayitlar()
        # 30000 − 5000 (gerçek ödeme) − 2000 (yanlış yön gider) + 1000 (düz giriş) − 500 (iade)
        self.assertEqual(self.bakiye(self.kk_id), D("23500.00"))
        kuru = onarim.tara()
        self.assertEqual(kuru["ozet"], {"kesin": 2, "belirsiz": 1, "hatali_hesap": 1})
        self.assertEqual(sorted((k["sinif"], k["tutar"]) for k in kuru["kesin"]),
                         [(onarim.SINIF_EKSIK_KART, D("3000.00")), (onarim.SINIF_GIDER_FISI, D("2000.00"))])
        self.assertEqual(kuru["belirsiz"][0]["sinif"], onarim.SINIF_KARTA_GIRIS)
        self.assertNotIn("IADE-1", {k["belge_no"] for k in kuru["kesin"] + kuru["belirsiz"]})
        self.assertEqual(self.bakiye(self.kk_id), D("23500.00"))

        sonuc = onarim.uygula()
        self.assertEqual(sonuc["uygulanan"], 2)
        self.assertTrue(sonuc["yedek_yolu"] and Path(sonuc["yedek_yolu"]).is_file())
        # −3000 eksik kart hareketi, gider yönü −2000 → +2000
        self.assertEqual(self.bakiye(self.kk_id), D("24500.00"))
        with get_session() as s:
            gunluk = s.scalars(select(KartBakiyeOnarimGunlugu).order_by(KartBakiyeOnarimGunlugu.id)).all()
            self.assertEqual([(g.bakiye_once, g.bakiye_sonra) for g in gunluk],
                             [(D("23500.00"), D("20500.00")), (D("20500.00"), D("24500.00"))])
            self.assertTrue(all(g.kullanici == "Test Admin" and g.yedek_yolu for g in gunluk))

        tekrar = onarim.uygula()
        self.assertEqual(tekrar["uygulanan"], 0)
        self.assertEqual(self.bakiye(self.kk_id), D("24500.00"))

        geri = onarim.geri_al(sonuc["onarim_kodu"])
        self.assertEqual(geri["geri_alinan"], 2)
        self.assertEqual(self.bakiye(self.kk_id), D("23500.00"))
        self.assertEqual(onarim.tara()["ozet"]["kesin"], 2)

    # ------------------------------------------------------------------ şema geçişi
    def test_gecis_eski_semada_son_odeme_bos_olabilir_veri_korunur(self):
        from database.database import Base

        with tempfile.TemporaryDirectory(prefix="kb_gecis_", ignore_cleanup_errors=True) as d:
            yol = Path(d) / "eski.db"
            motor = create_engine(f"sqlite:///{yol.as_posix()}")
            try:
                Base.metadata.create_all(motor)
                c = sqlite3.connect(yol)
                ddl = c.execute("select sql from sqlite_master where name='kredi_karti_ekstreleri'").fetchone()[0]
                self.assertIn("son_odeme_tarihi DATE,", ddl)
                c.executescript(
                    "DROP TABLE kredi_karti_ekstre_odeme_taksitleri; DROP TABLE kart_bakiye_onarim_gunlugu;"
                    "DROP INDEX ux_kk_ekstre_odeme_istek; ALTER TABLE kredi_karti_ekstre_odemeleri DROP COLUMN "
                    "istek_anahtari; ALTER TABLE kredi_karti_ekstreleri RENAME TO eski_tmp;"
                    + ddl.replace("son_odeme_tarihi DATE,", "son_odeme_tarihi DATE NOT NULL,") + ";"
                    "DROP TABLE eski_tmp;"
                    "INSERT INTO kredi_karti_tanimlari (id, banka_karti_id, kart_adi, kart_limiti, aktif) "
                    "VALUES (1, 1, 'K', 0, 1);"
                    "INSERT INTO kredi_karti_ekstreleri (kredi_karti_id, kesim_tarihi, donem_baslangic, donem_bitis,"
                    " son_odeme_tarihi, durum, toplam_borc, odenen, kalan, para_birimi, kesin, olusturma) VALUES"
                    " (1, '2026-09-07', '2026-08-08', '2026-09-07', '2026-09-12', 'ODENDI', 100.5, 100.5, 0, 'TRY',"
                    " 1, '2026-09-07 00:00:00'),"
                    " (1, '2026-10-07', '2026-09-08', '2026-10-07', '2026-10-12', 'KISMI', 27773.81, 10000, "
                    "17773.81, 'TRY', 1, '2026-10-07 00:00:00');")
                c.commit()
                c.close()
                ins = inspect(motor)
                self.assertFalse(next(k for k in ins.get_columns("kredi_karti_ekstreleri")
                                      if k["name"] == "son_odeme_tarihi")["nullable"])
                self.assertTrue(kbg._eksik_var(motor))

                kbg.schema_hazirla(motor)

                ins = inspect(motor)
                self.assertTrue(next(k for k in ins.get_columns("kredi_karti_ekstreleri")
                                     if k["name"] == "son_odeme_tarihi")["nullable"])
                self.assertTrue(ins.has_table("kredi_karti_ekstre_odeme_taksitleri"))
                self.assertIn("istek_anahtari", {k["name"] for k in ins.get_columns("kredi_karti_ekstre_odemeleri")})
                self.assertFalse(kbg._eksik_var(motor))
                c = sqlite3.connect(yol)
                self.assertEqual(c.execute("select count(*), round(sum(toplam_borc), 2), round(sum(kalan), 2) "
                                           "from kredi_karti_ekstreleri").fetchone(), (2, 27874.31, 17773.81))
                c.execute("update kredi_karti_ekstreleri set son_odeme_tarihi = null where id = 1")
                self.assertEqual(c.execute("PRAGMA integrity_check").fetchone()[0], "ok")
                c.close()
                # ikinci çalıştırma bir şey yapmaz
                kbg._HAZIR.discard(motor)
                kbg.schema_hazirla(motor)
            finally:
                motor.dispose()

    def test_ekstre_eksik_bilgi_durumu_gecikmis_veya_zamaninda_sayilmaz(self):
        self.assertEqual(E._durum_hesapla(D("100"), D("0"), None, bugun=BUGUN, kesin=True), "EKSIK_BILGI")
        self.assertEqual(E._durum_hesapla(D("100"), D("100"), None, bugun=BUGUN, kesin=True), "ODENDI")
        with get_session() as s:
            self.assertIsNotNone(s.get(KrediKartiTanimi, self.kart_id))
        self.assertEqual(KrediKartiEkstre.__table__.c.son_odeme_tarihi.nullable, True)


if __name__ == "__main__":
    unittest.main()
