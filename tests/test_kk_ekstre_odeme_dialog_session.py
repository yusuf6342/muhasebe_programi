"""Ekstre Ödeme Evrakı — FinansHesabi.banka_karti lazy-load / DetachedInstanceError regresyonu.

``_odeme_hesaplari`` oturum kapandıktan sonra ORM ilişkisine dokunmamalı; banka/kasa
listeleri düz değerlerle dönmeli. Mali kayıt yazılmaz.
"""

from __future__ import annotations

import unittest
from datetime import date
from decimal import Decimal as D
from unittest.mock import patch

from sqlalchemy.orm.exc import DetachedInstanceError

from database.database import get_session
from database.finans_service import FinansService
from database.kredi_karti_ekstre_service import KrediKartiEkstreService as E
from database.models.finans import BankaKarti, FinansHesabi, KrediKartiTanimi
from kk_ekstre_ui import KkEkstreOdemeDialog, _odeme_hesaplari, _varsayilan_hesap
from tests.stok_test_ortami import StokOrtami
from tests.test_gider_kart_odeme import bugun

BUGUN = date(2026, 10, 12)
K1 = date(2026, 10, 7)


class KkEkstreOdemeDialogSessionTest(unittest.TestCase):
    def setUp(self):
        self.ort = StokOrtami("kk_ekstre_dlg")
        with get_session() as s:
            b1 = BankaKarti(banka_adi="Akbank", sube="Merkez", aktif=True)
            b2 = BankaKarti(banka_adi="Enpara", sube="Online", aktif=True)
            s.add_all([b1, b2])
            s.flush()
            mev1 = FinansHesabi(
                hesap_adi="Akbank Mevduat",
                hesap_turu="BANKA",
                alt_hesap_turu="MEVDUAT",
                banka_karti_id=b1.id,
                acilis_bakiyesi=D("1000000"),
                aktif=True,
            )
            kmh1 = FinansHesabi(
                hesap_adi="Akbank KMH",
                hesap_turu="BANKA",
                alt_hesap_turu="KMH",
                banka_karti_id=b1.id,
                acilis_bakiyesi=D("0"),
                aktif=True,
            )
            mev2 = FinansHesabi(
                hesap_adi="Enpara Vadesiz",
                hesap_turu="BANKA",
                alt_hesap_turu="MEVDUAT",
                banka_karti_id=b2.id,
                acilis_bakiyesi=D("500000"),
                aktif=True,
            )
            kk = FinansHesabi(
                hesap_adi="Akbank KK",
                hesap_turu="BANKA",
                alt_hesap_turu="KREDI_KARTI",
                banka_karti_id=b1.id,
                acilis_bakiyesi=D("0"),
                aktif=True,
            )
            kasa = FinansHesabi(
                hesap_adi="Merkez Kasa",
                hesap_turu="KASA",
                acilis_bakiyesi=D("100000"),
                aktif=True,
            )
            s.add_all([mev1, kmh1, mev2, kk, kasa])
            s.flush()
            kart = KrediKartiTanimi(
                banka_karti_id=b1.id,
                kart_adi="AXESS",
                hesap_kesim_gunu=7,
                son_odeme_gunu=12,
                kart_limiti=D("50000"),
                aktif=True,
            )
            s.add(kart)
            s.flush()
            self.banka1_id = int(b1.id)
            self.banka2_id = int(b2.id)
            self.mev1_id = int(mev1.id)
            self.mev2_id = int(mev2.id)
            self.kmh1_id = int(kmh1.id)
            self.kk_hesap_id = int(kk.id)
            self.kasa_id = int(kasa.id)
            self.kart_id = int(kart.id)

    def tearDown(self):
        self.ort.kapat()

    def test_odeme_hesaplari_banka_karti_detached_olmaz(self):
        """Eski hata: FinansService.hesaplar() sonrası h.banka_karti lazy-load."""
        try:
            banka = _odeme_hesaplari(yontem="BANKA")
            atm = _odeme_hesaplari(yontem="BANKAMATIK")
        except DetachedInstanceError as exc:
            self.fail(f"DetachedInstanceError (banka_karti lazy-load): {exc}")

        banka_idler = {r[0] for r in banka}
        self.assertIn(self.mev1_id, banka_idler)
        self.assertIn(self.mev2_id, banka_idler)
        self.assertIn(self.kmh1_id, banka_idler)
        self.assertNotIn(self.kk_hesap_id, banka_idler)  # KK hesabı kaynak değil
        self.assertNotIn(self.kasa_id, banka_idler)

        # Farklı bankalar etikette ayrılır
        etiketler = {r[0]: r[1] for r in banka}
        self.assertIn("Akbank", etiketler[self.mev1_id])
        self.assertIn("Enpara", etiketler[self.mev2_id])
        banka_adi_map = {r[0]: r[3] for r in banka}
        self.assertEqual(banka_adi_map[self.mev1_id], "Akbank")
        self.assertEqual(banka_adi_map[self.mev2_id], "Enpara")
        self.assertEqual(banka_adi_map[self.mev1_id] != banka_adi_map[self.mev2_id], True)

        # ATM / kasa
        self.assertEqual(len(atm), 1)
        self.assertEqual(atm[0][0], self.kasa_id)
        self.assertEqual(atm[0][3], "Kasa")
        self.assertIsNone(atm[0][2])

        # Düz tuple — ORM nesnesi yok
        for row in banka + atm:
            self.assertIsInstance(row[0], int)
            self.assertIsInstance(row[1], str)
            self.assertIsInstance(row[3], str)

    def test_varsayilan_hesap_kart_bankasindaki_mevduat(self):
        banka = _odeme_hesaplari(yontem="BANKA")
        idx = _varsayilan_hesap(self.kart_id, banka)
        self.assertIsNotNone(idx)
        self.assertEqual(banka[idx][0], self.mev1_id)

    def test_dialog_yontem_degisimi_banka_ve_atm_listeleri(self):
        """KkEkstreOdemeDialog açılışı + BANKA↔ATM kaynak listesi (mali yazım yok)."""
        with bugun(BUGUN):
            FinansService.kredi_karti_odeme(
                self.banka1_id,
                self.kart_id,
                self.ort.ted_id,
                date(2026, 9, 20),
                D("10000"),
                cekim_turu="TEK_CEKIM",
                taksit_sayisi=1,
            )
            ekstre = next(
                h
                for h in E.ekstreleri_hesapla(bugun=BUGUN, kredi_karti_id=self.kart_id)
                if h["kesim_tarihi"] == K1
            )
            detay = E.ekstre_detay(int(ekstre["ekstre_id"]))

        import tkinter as tk

        root = tk.Tk()
        root.withdraw()
        try:
            with patch("database.access.yetki_var", return_value=True):
                dlg = KkEkstreOdemeDialog(root, detay, yenile_cb=None)
            try:
                self.assertEqual(dlg._yontem.get(), "BANKA")
                banka_ids = [h[0] for h in dlg._hesaplar]
                self.assertIn(self.mev1_id, banka_ids)
                self.assertIn(self.mev2_id, banka_ids)
                self.assertGreaterEqual(dlg.hesap.current(), 0)

                dlg._yontem.set("BANKAMATIK")
                dlg._yontem_degisti()
                self.assertEqual([h[0] for h in dlg._hesaplar], [self.kasa_id])
                self.assertIn("kasa", (dlg._kaynak_etiket.cget("text") or "").lower())

                dlg._yontem.set("BANKA")
                dlg._yontem_degisti()
                self.assertIn(self.mev2_id, [h[0] for h in dlg._hesaplar])
                # Farklı hesap seçimi (Enpara)
                for i, row in enumerate(dlg._hesaplar):
                    if row[0] == self.mev2_id:
                        dlg.hesap.current(i)
                        break
                self.assertEqual(dlg._hesaplar[dlg.hesap.current()][0], self.mev2_id)
            finally:
                dlg.destroy()
        finally:
            root.destroy()


if __name__ == "__main__":
    unittest.main()
