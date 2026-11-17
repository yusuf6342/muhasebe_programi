"""Mevduat Banka Transfer/Virman fişi — işlem yönü (diğer→sabit / sabit→diğer)."""

from __future__ import annotations

import unittest
from types import SimpleNamespace

import finans_ui


class MevduatVirmanYonTest(unittest.TestCase):
    def _dlg(self, secili_id=10, diger_id=20, yon="aktar", secili_ad="Enpara Şirketim"):
        dlg = SimpleNamespace(
            mevduat_hesap_id=secili_id,
            _secili_etiket=secili_ad,
            _hedef_map={"Akbank": diger_id},
            hedef_hesap=SimpleNamespace(get=lambda: "Akbank"),
            yon_var=SimpleNamespace(get=lambda: yon),
            YON_GONDER=finans_ui.MevduatEvrakDialog.YON_GONDER,
            YON_AKTAR=finans_ui.MevduatEvrakDialog.YON_AKTAR,
        )
        dlg._bvr_diger_etiket = finans_ui.MevduatEvrakDialog._bvr_diger_etiket.__get__(dlg)
        dlg._bvr_kaynak_hedef = finans_ui.MevduatEvrakDialog._bvr_kaynak_hedef.__get__(dlg)
        return dlg

    def test_yon_etiketleri_sabit_hesap_adi(self):
        sab = "Enpara Şirketim"
        self.assertEqual(
            f"Seçili diğer banka hesabından {sab} hesabına gönder",
            "Seçili diğer banka hesabından Enpara Şirketim hesabına gönder",
        )
        self.assertEqual(
            f"Seçili diğer banka hesabına {sab} hesabından gönder",
            "Seçili diğer banka hesabına Enpara Şirketim hesabından gönder",
        )

    def test_ilk_secenek_digerden_sabite(self):
        """İlk seçenek (aktar): diğer → sabit = Akbank → Enpara Şirketim."""
        dlg = self._dlg(yon="aktar")
        kaynak, hedef, ka, ha = dlg._bvr_kaynak_hedef()
        self.assertEqual(kaynak, 20)
        self.assertEqual(hedef, 10)
        self.assertEqual(ka, "Akbank")
        self.assertEqual(ha, "Enpara Şirketim")
        self.assertEqual(f"{ka} → {ha}", "Akbank → Enpara Şirketim")

    def test_ikinci_secenek_sabitten_digere(self):
        """İkinci seçenek (gonder): sabit → diğer = Enpara Şirketim → Akbank."""
        dlg = self._dlg(yon="gonder")
        kaynak, hedef, ka, ha = dlg._bvr_kaynak_hedef()
        self.assertEqual(kaynak, 10)
        self.assertEqual(hedef, 20)
        self.assertEqual(ka, "Enpara Şirketim")
        self.assertEqual(ha, "Akbank")
        self.assertEqual(f"{ka} → {ha}", "Enpara Şirketim → Akbank")

    def test_secili_hesap_yon_degisse_de_sabit(self):
        for yon in ("gonder", "aktar"):
            dlg = self._dlg(yon=yon)
            self.assertEqual(dlg.mevduat_hesap_id, 10)
            self.assertEqual(dlg._secili_etiket, "Enpara Şirketim")

    def test_baska_sabit_hesap_adi_etikette(self):
        dlg = self._dlg(secili_id=28, diger_id=162, yon="aktar", secili_ad="Enpara Mehmet Can Mevduat")
        dlg._hedef_map = {"Enpara Şirketim — Mevduat Hesabı": 162}
        dlg.hedef_hesap = SimpleNamespace(get=lambda: "Enpara Şirketim — Mevduat Hesabı")
        kaynak, hedef, ka, ha = dlg._bvr_kaynak_hedef()
        self.assertEqual(ka, "Enpara Şirketim — Mevduat Hesabı")
        self.assertEqual(ha, "Enpara Mehmet Can Mevduat")
        self.assertEqual(f"{ka} → {ha}", "Enpara Şirketim — Mevduat Hesabı → Enpara Mehmet Can Mevduat")


if __name__ == "__main__":
    unittest.main()
