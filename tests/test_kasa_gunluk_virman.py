"""Kasa talimatı 10.11.2026 — izole sayısal kabul (gerçek D2'ye yazılmaz).

NAKİT dünden 1.000, YÇ 400; bugün 500 tahsilat, 200 ödeme, 100 bankaya,
300 NAKİT→YÇ virman. Beklenen satırlar ve dış akış talimattaki tablodur.
"""

from __future__ import annotations

import time
import unittest
from datetime import date, timedelta
from decimal import Decimal as D

from database.database import get_session
from database.finans_service import FinansService
from database.models.finans import BankaKarti, FinansHareketi, FinansHesabi
from tests.stok_test_ortami import StokOrtami

BUGUN = date(2026, 11, 10)


class KasaGunlukVirmanKabulTest(unittest.TestCase):
    def setUp(self):
        self.ort = StokOrtami("kasa_gunluk_virman")
        with get_session() as s:
            banka = BankaKarti(banka_adi="Test Banka", sube="Merkez", aktif=True)
            s.add(banka)
            s.flush()
            mev = FinansHesabi(
                hesap_adi="Test Mevduat",
                hesap_turu="BANKA",
                alt_hesap_turu="MEVDUAT",
                banka_karti_id=banka.id,
                acilis_bakiyesi=D("0"),
                aktif=True,
            )
            nakit = FinansHesabi(
                hesap_adi="NAKİT",
                hesap_turu="KASA",
                acilis_bakiyesi=D("1000"),
                aktif=True,
            )
            yc = FinansHesabi(
                hesap_adi="YÇ",
                hesap_turu="KASA",
                acilis_bakiyesi=D("400"),
                aktif=True,
            )
            s.add_all([mev, nakit, yc])
            s.flush()
            self.mev_id = mev.id
            self.nakit_id = nakit.id
            self.yc_id = yc.id

    def tearDown(self):
        self.ort.kapat()

    def _hareket(self, hesap_id, tur, tutar, belge):
        with get_session() as s:
            s.add(
                FinansHareketi(
                    hesap_id=hesap_id,
                    tarih=BUGUN,
                    hareket_turu=tur,
                    belge_no=belge,
                    tutar=tutar,
                    aciklama="izole kabul",
                )
            )

    def test_sayisal_kabul_ornek(self):
        self._hareket(self.nakit_id, "TAHSİLAT MAKBUZU", D("500"), "TMK-TEST-1")
        self._hareket(self.nakit_id, "ÖDEME MAKBUZU", D("200"), "OMK-TEST-1")
        kby = FinansService.kasadan_bankaya_yatan(
            self.nakit_id, self.mev_id, BUGUN, D("100"), aciklama="bankaya 100"
        )
        self.assertTrue(str(kby).startswith("KBY-"))
        kvr = FinansService.kasalar_arasi_virman(
            self.nakit_id, self.yc_id, BUGUN, D("300"), aciklama="virman 300"
        )
        self.assertTrue(str(kvr).startswith("KVR-"))

        ozet = FinansService.kasa_gunluk_ozet(BUGUN)
        by_ad = {s["ad"]: s for s in ozet["satirlar"]}
        n = by_ad["NAKİT"]
        y = by_ad["YÇ"]

        self.assertEqual(n["devir"], D("1000"))
        self.assertEqual(n["tahsilat"], D("500"))
        self.assertEqual(n["odeme"], D("600"))  # 200 + 100 + 300
        self.assertEqual(n["bakiye"], D("900"))

        self.assertEqual(y["devir"], D("400"))
        self.assertEqual(y["tahsilat"], D("300"))
        self.assertEqual(y["odeme"], D("0"))
        self.assertEqual(y["bakiye"], D("700"))

        self.assertEqual(ozet["toplam_devir"], D("1400"))
        self.assertEqual(ozet["dis_giris"], D("500"))
        self.assertEqual(ozet["dis_cikis"], D("300"))  # 200 + 100; virman ayıklı
        self.assertEqual(ozet["toplam_bakiye"], D("1600"))

        # Banka: yalnızca 100 giriş
        mev = FinansService.hesap_getir(self.mev_id)
        self.assertEqual(FinansService.bakiye(mev), D("100"))

        # Ertesi gün: devirler 900/700, günlük 0
        ertesi = BUGUN + timedelta(days=1)
        o2 = FinansService.kasa_gunluk_ozet(ertesi)
        by2 = {s["ad"]: s for s in o2["satirlar"]}
        self.assertEqual(by2["NAKİT"]["devir"], D("900"))
        self.assertEqual(by2["YÇ"]["devir"], D("700"))
        self.assertEqual(by2["NAKİT"]["tahsilat"], D("0"))
        self.assertEqual(by2["NAKİT"]["odeme"], D("0"))
        self.assertEqual(by2["YÇ"]["tahsilat"], D("0"))
        self.assertEqual(by2["YÇ"]["odeme"], D("0"))

    def test_virman_ayni_kasa_ve_yetersiz_bakiye(self):
        with self.assertRaises(ValueError):
            FinansService.kasalar_arasi_virman(self.nakit_id, self.nakit_id, BUGUN, D("10"))
        with self.assertRaises(ValueError):
            FinansService.kasalar_arasi_virman(self.nakit_id, self.yc_id, BUGUN, D("5000"))

    def test_kby_cift_bacak_tek_belge(self):
        from sqlalchemy import select

        no = FinansService.kasadan_bankaya_yatan(
            self.nakit_id, self.mev_id, BUGUN, D("50")
        )
        with get_session() as s:
            hareketler = list(
                s.scalars(select(FinansHareketi).where(FinansHareketi.belge_no == no)).all()
            )
        self.assertEqual(len(hareketler), 2)
        turler = {h.hareket_turu for h in hareketler}
        self.assertIn("KASADAN BANKAYA (KASA)", turler)
        self.assertIn("KASADAN BANKAYA YATAN", turler)

    def test_hareket_ozet_getir_kimlik(self):
        self._hareket(self.nakit_id, "TAHSİLAT MAKBUZU", D("10"), "TMK-ID-1")
        from sqlalchemy import select

        with get_session() as s:
            h = s.scalars(
                select(FinansHareketi).where(FinansHareketi.belge_no == "TMK-ID-1")
            ).first()
            hid = h.id
        ozet = FinansService.hareket_ozet_getir(hid)
        self.assertEqual(ozet["belge_no"], "TMK-ID-1")
        self.assertEqual(ozet["hareket_turu"], "TAHSİLAT MAKBUZU")

    def test_ozet_servis_hiz(self):
        # Servis katmanı ölçümü (UI değil); kabul hedefini aşmamalı
        times = []
        for _ in range(5):
            t0 = time.perf_counter()
            FinansService.kasa_gunluk_ozet(BUGUN)
            times.append((time.perf_counter() - t0) * 1000)
        self.assertLess(sorted(times)[len(times) // 2], 2000)

    def test_kasa_ekran_acilisi_hiz(self):
        """İzole Tk: Kasalar sayfası açılış medyanı ≤ 2 sn (kurulu EXE ölçümü değil)."""
        import tkinter as tk
        from tkinter import ttk
        from unittest.mock import patch

        import finans_ui

        try:
            root = tk.Tk()
        except tk.TclError as hata:
            self.skipTest(f"Tk yok: {hata}")
        root.withdraw()
        try:
            root.attributes("-alpha", 0.0)
        except tk.TclError:
            pass

        class _App(tk.Tk):
            pass

        # Mevcut root'u app kabuğu gibi kullan
        app = root
        app.icerik = ttk.Frame(app)
        app.icerik.pack(fill="both", expand=True)

        def _temizle():
            for w in app.icerik.winfo_children():
                w.destroy()

        app._icerigi_temizle = _temizle  # type: ignore[attr-defined]
        times = []
        try:
            with patch("finans_ui._finans_menu_isaretle", lambda _a: None), patch(
                "finans_ui.finans_menusu_goster", lambda _a: None
            ):
                for _ in range(5):
                    app._icerigi_temizle()
                    t0 = time.perf_counter()
                    finans_ui.kasalar_sayfasi_goster(app)
                    app.update_idletasks()
                    app.update()
                    times.append((time.perf_counter() - t0) * 1000)
        finally:
            try:
                root.destroy()
            except tk.TclError:
                pass
        medyan = sorted(times)[len(times) // 2]
        self.assertLess(
            medyan,
            2000,
            f"Kasa UI açılış medyanı {medyan:.1f} ms (ölçümler={times})",
        )


if __name__ == "__main__":
    unittest.main()
