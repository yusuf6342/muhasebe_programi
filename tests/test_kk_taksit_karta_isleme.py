"""Firma KK taksit: kayıtta tüm taksitler kalıcı harekete; kendi tarihleri; idempotent."""
from __future__ import annotations

import unittest
from datetime import date
from decimal import Decimal as D

from sqlalchemy import select

from database.database import get_session
from database.finans_service import FinansService
from database.kk_taksit_islem_service import (
    eksik_taksit_hareketlerini_tamamla,
    vadesi_gelenleri_isle,
)
from database.models.finans import (
    BankaKarti,
    FinansHareketi,
    FinansHesabi,
    KrediKartiOdeme,
    KrediKartiTanimi,
)
from tests.stok_test_ortami import StokOrtami
from tests.test_gider_kart_odeme import bugun

BUGUN = date(2026, 11, 17)


class KkTaksitKartaIslemeTest(unittest.TestCase):
    def setUp(self):
        self.ort = StokOrtami("kk_taksit_isle")
        with get_session() as s:
            banka = BankaKarti(banka_adi="Yapı Kredi", sube="Ticari", aktif=True)
            s.add(banka)
            s.flush()
            kk = FinansHesabi(
                hesap_adi="YK Ticari KK",
                hesap_turu="BANKA",
                alt_hesap_turu="KREDI_KARTI",
                banka_karti_id=banka.id,
                acilis_bakiyesi=D("0"),
                aktif=True,
            )
            s.add(kk)
            s.flush()
            kart = KrediKartiTanimi(
                banka_karti_id=banka.id,
                kart_adi="02 YK Ticari",
                hesap_kesim_gunu=26,
                son_odeme_gunu=5,
                kart_limiti=D("500000"),
                bagli_hesap_id=kk.id,
                aktif=True,
            )
            s.add(kart)
            s.flush()
            self.banka_id = banka.id
            self.kk_hesap_id = kk.id
            self.kart_id = kart.id

    def tearDown(self):
        self.ort.kapat()

    def _ode(self, tutar, n=5, tarih=date(2026, 11, 4)):
        with bugun(BUGUN):
            return FinansService.kredi_karti_odeme(
                self.banka_id,
                self.kart_id,
                self.ort.ted_id,
                tarih,
                tutar,
                cekim_turu="TAKSITLI" if n > 1 else "TEK_CEKIM",
                taksit_sayisi=n,
            )

    def test_55000_5_taksit_hepsi_karta(self):
        r = self._ode("55000", 5)
        with get_session() as s:
            o = s.get(KrediKartiOdeme, int(r["odeme_id"]))
            durumlar = [
                (t.taksit_no, t.durum, t.tutar, t.vade_tarihi, t.kk_hareket_belge_no)
                for t in sorted(o.taksitler, key=lambda x: x.taksit_no)
            ]
            self.assertEqual(
                [
                    (n, d, tut, v)
                    for n, d, tut, v, _bel in durumlar
                ],
                [
                    (1, "KARTA_ISLENDI", D("11000.00"), date(2026, 11, 4)),
                    (2, "KARTA_ISLENDI", D("11000.00"), date(2026, 12, 4)),
                    (3, "KARTA_ISLENDI", D("11000.00"), date(2027, 1, 4)),
                    (4, "KARTA_ISLENDI", D("11000.00"), date(2027, 2, 4)),
                    (5, "KARTA_ISLENDI", D("11000.00"), date(2027, 3, 4)),
                ],
            )
            belgeler = [bel for *_rest, bel in durumlar]
            self.assertEqual(
                belgeler,
                [f"{o.belge_no}-T{i}" for i in range(1, 6)],
            )
            fh = list(
                s.scalars(
                    select(FinansHareketi).where(FinansHareketi.belge_no.in_(belgeler))
                ).all()
            )
            self.assertEqual(len(fh), 5)
            by_bel = {h.belge_no: h for h in fh}
            self.assertEqual(by_bel[f"{o.belge_no}-T1"].tarih, date(2026, 11, 4))
            self.assertEqual(by_bel[f"{o.belge_no}-T5"].tarih, date(2027, 3, 4))

        bek = FinansService.kredi_karti_bekleyen_taksitler(
            self.banka_id, kredi_karti_id=self.kart_id
        )
        omk = [b for b in bek if b.get("odeme_id") == int(r["odeme_id"])]
        self.assertEqual(omk, [])

    def test_kurus_farki_son_taksitte(self):
        r = self._ode("100.01", 3, tarih=date(2026, 1, 31))
        with get_session() as s:
            o = s.get(KrediKartiOdeme, int(r["odeme_id"]))
            tutarlar = [t.tutar for t in sorted(o.taksitler, key=lambda x: x.taksit_no)]
            self.assertEqual(tutarlar, [D("33.34"), D("33.34"), D("33.33")])
            vadeler = [t.vade_tarihi for t in sorted(o.taksitler, key=lambda x: x.taksit_no)]
            self.assertEqual(
                vadeler, [date(2026, 1, 31), date(2026, 2, 28), date(2026, 3, 31)]
            )

    def test_vadesi_gelen_idempotent(self):
        r = self._ode("3000", 3, tarih=date(2026, 10, 1))
        # Kayıtta zaten 3 hareket; tamamla / vadesi gelen ikinci kez yeni satır üretmez
        a = eksik_taksit_hareketlerini_tamamla(kredi_karti_id=self.kart_id)
        b = vadesi_gelenleri_isle(kredi_karti_id=self.kart_id, bugun=date(2026, 11, 1))
        self.assertEqual(a.get("yazilan"), 0)
        self.assertEqual(b[0].get("yazilan"), 0)
        with get_session() as s:
            o = s.get(KrediKartiOdeme, int(r["odeme_id"]))
            belgeler = [
                t.kk_hareket_belge_no
                for t in sorted(o.taksitler, key=lambda x: x.taksit_no)
            ]
            self.assertEqual(len(belgeler), 3)
            self.assertTrue(all(belgeler))
            hrs = list(
                s.scalars(
                    select(FinansHareketi).where(FinansHareketi.belge_no.in_(belgeler))
                ).all()
            )
            self.assertEqual(len(hrs), 3)
            by_bel = {h.belge_no: h for h in hrs}
            self.assertEqual(by_bel[belgeler[0]].tarih, date(2026, 10, 1))
            self.assertEqual(by_bel[belgeler[1]].tarih, date(2026, 11, 1))
            self.assertEqual(by_bel[belgeler[2]].tarih, date(2026, 12, 1))


if __name__ == "__main__":
    unittest.main()
