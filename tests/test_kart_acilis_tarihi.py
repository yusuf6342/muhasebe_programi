"""Kart Açılış Tarihi: normal kayıt, Devir planı, eski NULL, 49 pasif engeli.

Çalıştırma: .venv\\Scripts\\python.exe -m pytest tests/test_kart_acilis_tarihi.py -q
"""

from __future__ import annotations

import sys
import unittest
from datetime import date, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from sqlalchemy import create_engine, inspect, text

from database.kart_acilis import (
    DAYANAK_DEVIR,
    d2_haric_stok_idler,
    d2_stok_kart_yazimi_engelli,
    kart_acilis_goster,
    kart_acilis_gosterim,
    kart_acilis_koru,
    kart_acilis_simdi,
    plan_acilis_d2_sozlesme,
    plan_acilis_datetime,
    yeni_kart_tarihleri,
)
from database.models.cari import Cari
from database.models.stok import StokKarti
from tests.stok_test_ortami import StokOrtami


class KartAcilisYardimciTest(unittest.TestCase):
    def test_goster_bos(self):
        self.assertEqual(kart_acilis_goster(None), "")

    def test_goster_tr_format(self):
        self.assertEqual(
            kart_acilis_goster(datetime(2026, 11, 7, 15, 42, 3)),
            "07.11.2026 15:42:03",
        )

    def test_koru_istemci_alanlarini_siler(self):
        v = kart_acilis_koru(
            {
                "unvan": "X",
                "olusturma_tarihi": datetime(2000, 1, 1),
                "kart_acilis_tarihi": datetime(2001, 1, 1),
                "kart_acilis_dayanak": "Devir",
            }
        )
        self.assertNotIn("olusturma_tarihi", v)
        self.assertNotIn("kart_acilis_tarihi", v)
        self.assertNotIn("kart_acilis_dayanak", v)
        self.assertEqual(v["unvan"], "X")

    def test_simdi_naive_istanbul(self):
        dt = kart_acilis_simdi()
        self.assertIsNone(dt.tzinfo)
        self.assertLess(abs((dt - datetime.now()).total_seconds()), 120)

    def test_plan_acilis_datetime_gun_basi(self):
        self.assertEqual(
            plan_acilis_datetime(date(2026, 9, 1)),
            datetime(2026, 9, 1, 0, 0, 0),
        )
        self.assertEqual(
            plan_acilis_datetime("2026-09-01T00:00:00+03:00"),
            datetime(2026, 9, 1, 0, 0, 0),
        )

    def test_d2_sozlesmeden_plan_okunur_sabit_degil(self):
        dt = plan_acilis_d2_sozlesme()
        self.assertEqual(dt.date(), date(2026, 9, 1))

    def test_devir_tarihleri_plan_ve_sistem_ayri(self):
        once = kart_acilis_simdi() - timedelta(seconds=2)
        t = yeni_kart_tarihleri(dayanak=DAYANAK_DEVIR, plan_acilis=date(2026, 9, 1))
        self.assertEqual(t["kart_acilis_tarihi"], datetime(2026, 9, 1, 0, 0, 0))
        self.assertEqual(t["kart_acilis_dayanak"], DAYANAK_DEVIR)
        self.assertGreaterEqual(t["olusturma_tarihi"], once)
        self.assertNotEqual(t["olusturma_tarihi"], t["kart_acilis_tarihi"])

    def test_gosterim_devir_etiketi(self):
        n = SimpleNamespace(
            kart_acilis_tarihi=datetime(2026, 9, 1, 0, 0, 0),
            kart_acilis_dayanak=DAYANAK_DEVIR,
            olusturma_tarihi=datetime(2026, 11, 7, 18, 0, 0),
        )
        g = kart_acilis_gosterim(n)
        self.assertIn("01.09.2026", g["etiket"])
        self.assertIn("Devir", g["etiket"])
        self.assertIn("07.11.2026", g["sistem"])

    def test_49_pasif_listesi(self):
        ids = d2_haric_stok_idler()
        self.assertEqual(len(ids), 49)
        self.assertTrue(d2_stok_kart_yazimi_engelli("10753"))
        self.assertFalse(d2_stok_kart_yazimi_engelli("999999"))

    def test_sqlite_kolon_nullable_alter_uyumlu(self):
        eng = create_engine("sqlite:///:memory:")
        with eng.begin() as conn:
            conn.execute(
                text(
                    "CREATE TABLE cari_kartlar (id INTEGER PRIMARY KEY, unvan VARCHAR(200))"
                )
            )
            conn.execute(text("INSERT INTO cari_kartlar (unvan) VALUES ('eski')"))
            conn.execute(
                text("ALTER TABLE cari_kartlar ADD COLUMN olusturma_tarihi TIMESTAMP")
            )
            conn.execute(
                text("ALTER TABLE cari_kartlar ADD COLUMN kart_acilis_tarihi TIMESTAMP")
            )
            conn.execute(
                text(
                    "ALTER TABLE cari_kartlar ADD COLUMN kart_acilis_dayanak VARCHAR(20)"
                )
            )
            row = conn.execute(
                text(
                    "SELECT olusturma_tarihi, kart_acilis_tarihi, kart_acilis_dayanak "
                    "FROM cari_kartlar WHERE unvan='eski'"
                )
            ).fetchone()
            self.assertEqual(row, (None, None, None))
        cols = {c["name"]: c for c in inspect(eng).get_columns("cari_kartlar")}
        self.assertTrue(cols["kart_acilis_tarihi"]["nullable"])
        eng.dispose()


class KartAcilisCrudTest(unittest.TestCase):
    def setUp(self):
        self.ortam = StokOrtami("kart_acilis")
        self._yaz_cari = mock.patch(
            "database.cari_service.yazma_zorunlu", return_value=None
        )
        self._yaz_stok = mock.patch(
            "database.stok_service.yazma_zorunlu", return_value=None
        )
        self._yaz_cari.start()
        self._yaz_stok.start()

    def tearDown(self):
        self._yaz_cari.stop()
        self._yaz_stok.stop()
        self.ortam.kapat()

    def test_cari_normal_ilk_kayit(self):
        from database.cari_service import CariService

        once = kart_acilis_simdi() - timedelta(seconds=2)
        cari = CariService.ekle(
            {
                "cari_kodu": "M-ACILIS-1",
                "unvan": "Açılış Test",
                "cari_turu": "Müşteri",
                "olusturma_tarihi": datetime(1999, 1, 1),
            }
        )
        self.assertIsNotNone(cari.olusturma_tarihi)
        self.assertGreaterEqual(cari.olusturma_tarihi, once)
        self.assertEqual(cari.kart_acilis_tarihi, cari.olusturma_tarihi)
        self.assertIsNone(cari.kart_acilis_dayanak)
        sabit_o = cari.olusturma_tarihi
        sabit_a = cari.kart_acilis_tarihi

        guncel = CariService.guncelle(
            cari.id,
            {
                "unvan": "Açılış Test Güncel",
                "olusturma_tarihi": datetime(2099, 12, 31),
                "kart_acilis_tarihi": datetime(2099, 12, 31),
                "kart_acilis_dayanak": "Devir",
            },
        )
        self.assertEqual(guncel.unvan, "Açılış Test Güncel")
        self.assertEqual(guncel.olusturma_tarihi, sabit_o)
        self.assertEqual(guncel.kart_acilis_tarihi, sabit_a)
        self.assertIsNone(guncel.kart_acilis_dayanak)

    def test_cari_devir_plan_acilis(self):
        from database.cari_service import CariService

        cari = CariService.ekle(
            {"cari_kodu": "M-DEVIR-1", "unvan": "Devir Cari", "cari_turu": "Müşteri"},
            plan_acilis=date(2026, 9, 1),
            kart_acilis_dayanak=DAYANAK_DEVIR,
        )
        self.assertEqual(cari.kart_acilis_dayanak, DAYANAK_DEVIR)
        self.assertEqual(cari.kart_acilis_tarihi, datetime(2026, 9, 1, 0, 0, 0))
        self.assertIsNotNone(cari.olusturma_tarihi)
        self.assertNotEqual(cari.olusturma_tarihi, cari.kart_acilis_tarihi)
        g = kart_acilis_gosterim(cari)
        self.assertIn("Devir", g["etiket"])
        self.assertIn("01.09.2026", g["etiket"])

    def test_cari_eski_null_kalir(self):
        from database.cari_service import CariService
        from database.database import get_session

        with get_session() as s:
            eski = Cari(
                cari_kodu="M-ESKI",
                unvan="Eski Cari",
                cari_turu="Müşteri",
                aktif=True,
                is_deleted=False,
            )
            s.add(eski)
            s.flush()
            eski_id = eski.id

        guncel = CariService.guncelle(eski_id, {"unvan": "Eski Cari 2"})
        self.assertIsNone(guncel.olusturma_tarihi)
        self.assertIsNone(guncel.kart_acilis_tarihi)
        self.assertEqual(kart_acilis_gosterim(guncel)["etiket"], "—")

    def test_stok_normal_ve_devir(self):
        from database.stok_service import StokService

        stok = StokService.stok_kaydi(
            {"stok_kodu": "S-ACILIS-1", "stok_adi": "Açılış Stok", "birim": "Adet"},
            [],
        )
        self.assertEqual(stok.kart_acilis_tarihi, stok.olusturma_tarihi)
        self.assertIsNone(stok.kart_acilis_dayanak)
        sabit = stok.kart_acilis_tarihi

        guncel = StokService.stok_kaydi(
            {
                "stok_id": stok.id,
                "stok_kodu": "S-ACILIS-1",
                "stok_adi": "Açılış Stok Güncel",
                "birim": "Adet",
                "kart_acilis_tarihi": datetime(2099, 1, 1),
            },
            [],
        )
        self.assertEqual(guncel.kart_acilis_tarihi, sabit)

        d = StokService.stok_kaydi(
            {"stok_kodu": "S-DEVIR-1", "stok_adi": "Devir Stok", "birim": "Adet"},
            [],
            plan_acilis="2026-09-01T00:00:00+03:00",
            kart_acilis_dayanak=DAYANAK_DEVIR,
        )
        self.assertEqual(d.kart_acilis_tarihi, datetime(2026, 9, 1, 0, 0, 0))
        self.assertEqual(d.kart_acilis_dayanak, DAYANAK_DEVIR)

    def test_stok_49_pasif_engellenir(self):
        from database.stok_service import StokService

        haric = next(iter(d2_haric_stok_idler()))
        with self.assertRaises(ValueError) as ctx:
            StokService.stok_kaydi(
                {"stok_kodu": "S-HARIC", "stok_adi": "Hariç", "birim": "Adet"},
                [],
                kaynak_stok_id=haric,
                plan_acilis=date(2026, 9, 1),
                kart_acilis_dayanak=DAYANAK_DEVIR,
            )
        self.assertIn("kapsam dışı", str(ctx.exception))

    def test_stok_eski_null_kalir(self):
        from database.database import get_session
        from database.stok_service import StokService

        with get_session() as s:
            eski = StokKarti(
                stok_kodu="S-ESKI",
                stok_adi="Eski Stok",
                birim="Adet",
                aktif=True,
                is_deleted=False,
            )
            s.add(eski)
            s.flush()
            eski_id = eski.id

        guncel = StokService.stok_kaydi(
            {
                "stok_id": eski_id,
                "stok_kodu": "S-ESKI",
                "stok_adi": "Eski Stok 2",
                "birim": "Adet",
            },
            [],
        )
        self.assertIsNone(guncel.olusturma_tarihi)
        self.assertIsNone(guncel.kart_acilis_tarihi)

    def test_sema_v5_kolonlar(self):
        from sqlalchemy import select

        from database.cari_kart_sema import schema_hazirla
        from database.database import get_session

        eng = self.ortam.engine
        with get_session() as s:
            m = s.get(Cari, self.ortam.mus_id)
            self.assertIsNone(getattr(m, "kart_acilis_tarihi", None))
            u = s.scalar(select(StokKarti).where(StokKarti.stok_kodu == "U001"))
            self.assertIsNone(getattr(u, "olusturma_tarihi", None))
        schema_hazirla(eng)
        cols = {c["name"] for c in inspect(eng).get_columns("cari_kartlar")}
        self.assertTrue(
            {"olusturma_tarihi", "kart_acilis_tarihi", "kart_acilis_dayanak"} <= cols
        )


if __name__ == "__main__":
    unittest.main()
