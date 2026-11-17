"""Cari kredi notu — izole kabul (DOCX 08.11.2026). Gerçek D2'ye yazılmaz."""

from __future__ import annotations

import unittest
from decimal import Decimal as D

from database.cari_kredi_notu_service import (
    hesaplanan_limit,
    kart_notunu_uygula,
    not_normalize,
    yildiz_limitlerini_getir,
    yildiz_limitlerini_kaydet,
)
from database.cari_service import CariService
from database.database import get_session
from database.models.cari import Cari
from tests.stok_test_ortami import StokOrtami


class CariKrediNotuKabulTest(unittest.TestCase):
    def setUp(self):
        self.ort = StokOrtami("cari_kredi_notu")
        # Şema v6 kolonları
        from database.cari_kart_sema import schema_hazirla
        from database.cari_kart_sema import _HAZIR_MOTORLAR
        import database.database as db

        _HAZIR_MOTORLAR.discard(db.engine)
        schema_hazirla(db.engine)

    def tearDown(self):
        self.ort.kapat()

    def _cari(self, **kw) -> Cari:
        veri = {
            "unvan": kw.pop("unvan", "Test Cari KN"),
            "cari_turu": "Müşteri",
            "aktif": True,
            **kw,
        }
        return CariService.ekle(veri)

    def test_dort_yildiz_varsayilan_tutar(self):
        self.assertEqual(hesaplanan_limit("*"), D("15000.00"))
        self.assertEqual(hesaplanan_limit("**"), D("30000.00"))
        self.assertEqual(hesaplanan_limit("***"), D("90000.00"))
        self.assertEqual(hesaplanan_limit("****"), D("360000.00"))
        self.assertEqual(hesaplanan_limit("-"), D("0.00"))
        self.assertIsNone(hesaplanan_limit(""))

    def test_bos_not_mevcut_limit_degismez(self):
        cari = self._cari(acik_hesap_risk_limiti=D("22000"), acik_hesap_limit_uygula=True)
        self.assertFalse(cari.kredi_notu)
        self.assertEqual(D(str(cari.acik_hesap_risk_limiti)), D("22000"))
        yenilen = CariService.guncelle(cari.id, {"unvan": cari.unvan, "kredi_notu": ""})
        self.assertEqual(D(str(yenilen.acik_hesap_risk_limiti)), D("22000"))

    def test_manuel_22000_uc_yildiz_sonra_geri(self):
        cari = self._cari(acik_hesap_risk_limiti=D("22000"), acik_hesap_limit_uygula=True)
        cari = CariService.guncelle(cari.id, {"kredi_notu": "***"})
        self.assertEqual(cari.kredi_notu, "***")
        self.assertEqual(D(str(cari.acik_hesap_risk_limiti)), D("90000"))
        self.assertEqual(D(str(cari.kredi_notu_manuel_limit)), D("22000"))
        self.assertTrue(cari.acik_hesap_limit_uygula)
        cari = CariService.guncelle(cari.id, {"kredi_notu": ""})
        self.assertFalse(cari.kredi_notu)
        self.assertEqual(D(str(cari.acik_hesap_risk_limiti)), D("22000"))

    def test_yildiz_ayari_ilgili_carileri_gunceller(self):
        a = self._cari(unvan="A **", acik_hesap_risk_limiti=D("1000"), kredi_notu="**")
        # ekle sırasında not ayrı işlendi — yeniden uygula
        a = CariService.guncelle(a.id, {"kredi_notu": "**"})
        self.assertEqual(D(str(a.acik_hesap_risk_limiti)), D("30000"))
        bos = self._cari(unvan="Boş", acik_hesap_risk_limiti=D("5000"))
        dol = self._cari(unvan="Dolandırıcı", acik_hesap_risk_limiti=D("1"))
        dol = CariService.guncelle(dol.id, {"kredi_notu": "-"})
        self.assertEqual(D(str(dol.acik_hesap_risk_limiti)), D("0"))

        sonuc = yildiz_limitlerini_kaydet(
            {"*": "15000", "**": "45000", "***": "90000", "****": "360000"}
        )
        self.assertGreaterEqual(sonuc["etkilenen_hesap"], 1)
        with get_session() as s:
            a2 = s.get(Cari, a.id)
            b2 = s.get(Cari, bos.id)
            d2 = s.get(Cari, dol.id)
            self.assertEqual(D(str(a2.acik_hesap_risk_limiti)), D("45000"))
            self.assertEqual(D(str(b2.acik_hesap_risk_limiti)), D("5000"))
            self.assertEqual(D(str(d2.acik_hesap_risk_limiti)), D("0"))

    def test_dolandirici_sifir_sinirsiz_degil(self):
        cari = self._cari(acik_hesap_risk_limiti=D("10000"))
        cari = CariService.guncelle(cari.id, {"kredi_notu": "-"})
        self.assertEqual(cari.kredi_notu, "-")
        self.assertEqual(D(str(cari.acik_hesap_risk_limiti)), D("0"))
        self.assertTrue(cari.acik_hesap_limit_uygula)

    def test_gecersiz_not_normalize(self):
        self.assertEqual(not_normalize("3"), "***")
        self.assertEqual(not_normalize("***"), "***")
        self.assertEqual(not_normalize(""), "")

    def test_artan_sira_zorunlu(self):
        with self.assertRaises(ValueError):
            yildiz_limitlerini_kaydet(
                {"*": "50000", "**": "40000", "***": "90000", "****": "360000"}
            )


if __name__ == "__main__":
    unittest.main()
