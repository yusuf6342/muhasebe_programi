"""Nakit avans — faiz valörü, yansıma sırası, kaydet+1. taksit, muhasebe."""

from __future__ import annotations

import os
import tempfile
import unittest
from datetime import date
from decimal import Decimal
from unittest.mock import patch

from sqlalchemy import select

from database.database import get_session
from database.models.finans import (
    BankaKarti,
    FinansHareketi,
    FinansHesabi,
    GiderFisi,
    KrediKartiOdeme,
    KrediKartiTanimi,
)
from database.nakit_avans_service import (
    DURUM_IPTAL,
    DURUM_KARTA,
    DURUM_PLAN,
    HAREKET_GIRIS,
    HAREKET_KART,
    NakitAvansService,
    plan_hesapla,
    schema_hazirla,
)
from tests.stok_test_ortami import StokOrtami

D = Decimal
GUN = date(2026, 11, 10)
DENEME = date(2026, 11, 17)


class NakitAvansTest(unittest.TestCase):
    def setUp(self):
        self._ayar = tempfile.TemporaryDirectory(prefix="na_ayar_")
        self._env = patch.dict(os.environ, {"LOCALAPPDATA": self._ayar.name})
        self._env.start()
        self.o = StokOrtami("nakit_avans")
        with get_session() as s:
            bk = BankaKarti(banka_adi="TEST BANKASI NA")
            s.add(bk)
            s.flush()
            self.bk = int(bk.id)
            kasa = FinansHesabi(hesap_adi="NA KASA", hesap_turu="KASA", alt_hesap_turu=None)
            mev = FinansHesabi(
                hesap_adi="NA MEVDUAT", hesap_turu="BANKA", alt_hesap_turu="MEVDUAT", banka_karti_id=bk.id
            )
            kk_h = FinansHesabi(
                hesap_adi="NA KK HESAP", hesap_turu="BANKA", alt_hesap_turu="KREDI_KARTI", banka_karti_id=bk.id
            )
            s.add_all([kasa, mev, kk_h])
            s.flush()
            self.h_kasa = int(kasa.id)
            self.h_mev = int(mev.id)
            self.h_kk = int(kk_h.id)
            kart = KrediKartiTanimi(
                banka_karti_id=bk.id,
                kart_adi="NA Test Kart",
                kart_limiti=D("50000"),
                hesap_kesim_gunu=5,
                son_odeme_gunu=15,
                bagli_hesap_id=kk_h.id,
                aktif=True,
            )
            s.add(kart)
            s.flush()
            self.kk_id = int(kart.id)
        schema_hazirla()

    def tearDown(self):
        self.o.kapat()
        self._env.stop()
        self._ayar.cleanup()

    def test_plan_anuite_anapara_toplami(self):
        plan = plan_hesapla(
            anapara=D("1000"),
            aylik_faiz_orani=D("2"),
            taksit_sayisi=3,
            kullandirim_tarihi=GUN,
        )
        self.assertEqual(len(plan), 3)
        self.assertEqual(sum((p["anapara"] for p in plan), D("0")), D("1000.00"))
        self.assertTrue(all(p["toplam"] == p["anapara"] + p["faiz"] + p["masraf"] + p["vergi"] for p in plan))

    def test_plan_1711_uc_taksit_yansima_ve_valor(self):
        """17.11.2026 → yansıma +i−1 ay, faiz valörü +i ay."""
        plan = plan_hesapla(
            anapara=D("3000"),
            aylik_faiz_orani=D("2"),
            taksit_sayisi=3,
            kullandirim_tarihi=DENEME,
        )
        beklenen = [
            (date(2026, 11, 17), date(2026, 12, 17)),
            (date(2026, 12, 17), date(2027, 1, 17)),
            (date(2027, 1, 17), date(2027, 2, 17)),
        ]
        self.assertEqual(len(plan), 3)
        for i, (yan, valor) in enumerate(beklenen):
            self.assertEqual(plan[i]["yansima_tarihi"], yan, f"taksit {i + 1} yansıma")
            self.assertEqual(plan[i]["faiz_valor_tarihi"], valor, f"taksit {i + 1} faiz valör")
        self.assertEqual(sum((p["anapara"] for p in plan), D("0")), D("3000.00"))
        self.assertGreater(plan[0]["faiz"], 0)

    def test_kaydet_birinci_taksit_ayni_gun_karta(self):
        a = NakitAvansService.kaydet(
            kredi_karti_id=self.kk_id,
            islem_tarihi=DENEME,
            anapara=D("3000"),
            hedef_hesap_id=self.h_mev,
            aylik_faiz_orani=D("2"),
            taksit_sayisi=3,
            istek_anahtari="na-1711-3",
        )
        self.assertEqual(len(a["taksitler"]), 3)
        t1, t2, t3 = a["taksitler"]
        self.assertEqual(t1["durum"], DURUM_KARTA)
        self.assertEqual(t1["yansima_tarihi"], DENEME)
        self.assertEqual(t1["faiz_valor_tarihi"], date(2026, 12, 17))
        self.assertEqual(t2["durum"], DURUM_PLAN)
        self.assertEqual(t2["yansima_tarihi"], date(2026, 12, 17))
        self.assertEqual(t2["faiz_valor_tarihi"], date(2027, 1, 17))
        self.assertEqual(t3["yansima_tarihi"], date(2027, 1, 17))
        self.assertEqual(t3["faiz_valor_tarihi"], date(2027, 2, 17))
        self.assertLess(a["kalan_anapara"], D("3000.00"))
        self.assertEqual(a["kalan_anapara"], _q2_kalan(a))

        with get_session() as s:
            giris = s.scalars(select(FinansHareketi).where(
                FinansHareketi.hareket_turu == HAREKET_GIRIS,
                FinansHareketi.belge_no == a["belge_no"],
            )).all()
            self.assertEqual(len(giris), 1)
            self.assertEqual(giris[0].tarih, DENEME)
            kart_h = s.scalars(select(FinansHareketi).where(
                FinansHareketi.hareket_turu == HAREKET_KART,
                FinansHareketi.belge_no == t1["kk_hareket_belge_no"],
            )).all()
            self.assertEqual(len(kart_h), 1)
            self.assertEqual(kart_h[0].tarih, DENEME)
            self.assertEqual(D(str(kart_h[0].tutar)), t1["toplam"])
            od = s.get(KrediKartiOdeme, int(t1["kk_odeme_id"]))
            self.assertEqual(od.kaynak_turu, "NAKIT_AVANS")
            self.assertEqual(D(str(od.tutar)), t1["toplam"])

        # Idempotent yeniden işle
        t1b = NakitAvansService.taksit_karta_isle(t1["id"], islem_anahtari=t1["islem_anahtari"])
        self.assertEqual(t1b["kk_hareket_belge_no"], t1["kk_hareket_belge_no"])

    def test_tek_cekim_giris_ve_duzenle(self):
        a = NakitAvansService.kaydet(
            kredi_karti_id=self.kk_id,
            islem_tarihi=GUN,
            anapara=D("1000"),
            hedef_hesap_id=self.h_mev,
            aylik_faiz_orani=0,
            taksit_sayisi=1,
            aciklama="tek çekim deneme",
            istek_anahtari="na-tek-1",
        )
        self.assertEqual(a["net_giris"], D("1000.00"))
        self.assertEqual(a["taksitler"][0]["durum"], DURUM_KARTA)
        tid = a["taksitler"][0]["id"]
        # Düzenle: geri al + yeniden işle (1.000 + 100 faiz + 25 masraf = 1.125)
        t = NakitAvansService.taksit_duzenle(
            tid, anapara=D("1000"), faiz=D("100"), masraf=D("25"), vergi=0
        )
        self.assertEqual(t["durum"], DURUM_KARTA)
        self.assertEqual(t["toplam"], D("1125.00"))
        with get_session() as s:
            kart_h = s.scalars(select(FinansHareketi).where(
                FinansHareketi.hareket_turu == HAREKET_KART,
                FinansHareketi.belge_no == t["kk_hareket_belge_no"],
            )).all()
            self.assertEqual(len(kart_h), 1)
            self.assertEqual(D(str(kart_h[0].tutar)), D("1125.00"))
            faiz_g = s.scalars(select(GiderFisi).where(GiderFisi.belge_no == t["faiz_gider_belge_no"])).all()
            self.assertEqual(len(faiz_g), 1)
            self.assertEqual(D(str(faiz_g[0].tutar)), D("100.00"))
            masraf_g = s.scalars(select(GiderFisi).where(GiderFisi.belge_no == t["masraf_gider_belge_no"])).all()
            self.assertEqual(D(str(masraf_g[0].tutar)), D("25.00"))

    def test_taksitli_duzenle_sil(self):
        a = NakitAvansService.kaydet(
            kredi_karti_id=self.kk_id,
            islem_tarihi=GUN,
            anapara=D("3000"),
            hedef_hesap_id=self.h_kasa,
            aylik_faiz_orani=D("1.5"),
            taksit_sayisi=3,
            istek_anahtari="na-tak-1",
        )
        self.assertEqual(len(a["taksitler"]), 3)
        self.assertEqual(a["taksitler"][0]["durum"], DURUM_KARTA)
        self.assertLess(a["kalan_anapara"], D("3000.00"))
        t1 = a["taksitler"][0]["id"]
        NakitAvansService.taksit_duzenle(t1, faiz=D("50"))
        t_yeni = NakitAvansService.getir(a["id"])["taksitler"][0]
        self.assertEqual(t_yeni["durum"], DURUM_KARTA)
        self.assertEqual(t_yeni["faiz"], D("50.00"))
        t2 = a["taksitler"][1]["id"]
        sil = NakitAvansService.taksit_sil(t2)
        self.assertEqual(sil["durum"], DURUM_IPTAL)

    def test_vadesi_gelenleri_isle_ikinci_taksit(self):
        a = NakitAvansService.kaydet(
            kredi_karti_id=self.kk_id,
            islem_tarihi=DENEME,
            anapara=D("1500"),
            hedef_hesap_id=self.h_mev,
            aylik_faiz_orani=0,
            taksit_sayisi=2,
            istek_anahtari="na-auto-2",
        )
        t1 = a["taksitler"][0]
        t2 = a["taksitler"][1]
        self.assertEqual(t1["durum"], DURUM_KARTA)
        self.assertEqual(t2["durum"], DURUM_PLAN)
        with get_session() as s:
            od = s.scalar(
                select(KrediKartiOdeme).where(KrediKartiOdeme.nakit_avans_taksit_id == t1["id"])
            )
            self.assertIsNotNone(od)
            self.assertEqual(od.kaynak_turu, "NAKIT_AVANS")
        sonuc = NakitAvansService.vadesi_gelenleri_isle(
            kredi_karti_id=self.kk_id, bugun=t2["yansima_tarihi"]
        )
        self.assertTrue(any(r.get("id") == t2["id"] for r in sonuc))
        a2 = NakitAvansService.getir(a["id"])
        self.assertEqual(a2["taksitler"][1]["durum"], DURUM_KARTA)

    def test_muhasebe_hook_tanimli(self):
        from database import muhasebe_entegrasyon as me

        self.assertIn("nakit_avans_kullandirim", me.EVRAKLAR)
        self.assertIn("nakit_avans_taksit", me.EVRAKLAR)
        self.assertIn("nakit_avans_kullandirim", me.PLANLAR)
        self.assertTrue(hasattr(me.MuhasebeEntegrasyonService, "nakit_avans_kullandirim_fisi"))
        self.assertTrue(hasattr(me.MuhasebeEntegrasyonService, "nakit_avans_taksit_fisi"))

    def test_planlanan_bekleyen_ve_takvim(self):
        from database.finans_service import FinansService
        from database.odeme_takvimi_service import hesapla

        a = NakitAvansService.kaydet(
            kredi_karti_id=self.kk_id,
            islem_tarihi=DENEME,
            anapara=D("1600"),
            hedef_hesap_id=self.h_mev,
            aylik_faiz_orani=0,
            taksit_sayisi=2,
            istek_anahtari="na-bek-2",
        )
        tid2 = a["taksitler"][1]["id"]
        self.assertEqual(a["taksitler"][0]["durum"], DURUM_KARTA)
        self.assertEqual(a["taksitler"][1]["durum"], DURUM_PLAN)
        bek = FinansService.kredi_karti_bekleyen_taksitler(self.bk, kredi_karti_id=self.kk_id)
        self.assertTrue(any(r.get("taksit_id") == tid2 and r.get("kaynak") == "NAKIT_AVANS" for r in bek))
        takvim = hesapla(bugun=DENEME)
        anahtarlar = []
        for ay in takvim["aylar"]:
            anahtarlar.extend(k["anahtar"] for k in ay["kalemler"])
        anahtarlar.extend(k["anahtar"] for k in takvim["gecmis"])
        self.assertTrue(any(f"NAKIT_AVANS:{tid2}" == k for k in anahtarlar))


def _q2_kalan(a: dict) -> Decimal:
    islenen = sum((t["anapara"] for t in a["taksitler"] if t["durum"] == DURUM_KARTA), D("0"))
    return D(str(a["anapara"])) - islenen


if __name__ == "__main__":
    unittest.main()
