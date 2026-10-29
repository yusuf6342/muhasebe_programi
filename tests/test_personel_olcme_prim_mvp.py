"""Ölçme / Prim MVP: H örneği (S=100000 C=70000 %50 → H=15000) ve 50/30/20 eşit 3 kişi."""

from __future__ import annotations

import os
import tempfile
import unittest
from decimal import Decimal
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("MUHASEBE_DB_DIR", tempfile.mkdtemp(prefix="cin_olcme_prim_"))

from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import sessionmaker

from database.database import Base
from database.models.personel_performans import PersonelPrimDonem, PersonelPrimPay
from database.personel_performans_sema import schema_hazirla
from database.personel_performans_service import PersonelPerformansService
from database.personel_prim_motoru import DagitimKisi, kisi_dagitimi, tahsil_kar_katkisi
from database.personel_service import PersonelService
from database.session_manager import oturum


class HFormulOrnekTest(unittest.TestCase):
    """Belge örneği: S=100.000 C=70.000 tahsilat %50 → H=15.000."""

    def test_h_ornek_15000(self):
        h = tahsil_kar_katkisi(S=100_000, C=70_000, F=100_000, T=50_000)
        self.assertEqual(h["M"], Decimal("30000.00"))
        self.assertEqual(h["H"], Decimal("15000.00"))

    def test_h_servis_tahsilat_orani(self):
        h = PersonelPerformansService.tahsil_kar_h(
            S=100_000, C=70_000, tahsilat_orani=Decimal("0.5")
        )
        self.assertEqual(h["H"], Decimal("15000.00"))


class EsitUcKisiDagitimTest(unittest.TestCase):
    """Üç eşit kişi: 50/30/20, kuruş en büyük kalan; toplam = havuz."""

    def test_50_30_20_esit_uc_kisi(self):
        butce = Decimal("10000.00")
        d = kisi_dagitimi(
            butce,
            [
                DagitimKisi(1, 0, Decimal(100), Decimal(1)),
                DagitimKisi(2, 0, Decimal(100), Decimal(1)),
                DagitimKisi(3, 0, Decimal(100), Decimal(1)),
            ],
            agirlik_ekip=Decimal("0.50"),
            agirlik_katki=Decimal("0.30"),
            agirlik_kidem=Decimal("0.20"),
        )
        self.assertEqual(len(d["kisiler"]), 3)
        self.assertEqual(d["dagitilan"], butce)
        self.assertEqual(d["dagitilmamis"], Decimal("0.00"))
        tutarlar = [s["toplam"] for s in d["kisiler"]]
        self.assertLessEqual(max(tutarlar) - min(tutarlar), Decimal("0.01"))
        self.assertEqual(sum(tutarlar, Decimal("0")), butce)
        ekip = sum((s["ekip_payi"] for s in d["kisiler"]), Decimal("0"))
        katki = sum((s["katki_payi"] for s in d["kisiler"]), Decimal("0"))
        kidem = sum((s["kidem_payi"] for s in d["kisiler"]), Decimal("0"))
        self.assertEqual(ekip + katki + kidem, butce)
        self.assertAlmostEqual(float(ekip), 5000.0, delta=0.05)
        self.assertAlmostEqual(float(katki), 3000.0, delta=0.05)
        self.assertAlmostEqual(float(kidem), 2000.0, delta=0.05)


class PrimDonemIdempotentTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp(prefix="cin_olcme_db_")
        cls.db = Path(cls.tmp) / "test.db"
        cls.engine = create_engine(f"sqlite:///{cls.db.as_posix()}", future=True)
        # Personel modellerinin metadata'ya kaydı
        import database.models.personel  # noqa: F401
        import database.models.personel_performans  # noqa: F401

        Base.metadata.create_all(cls.engine)
        schema_hazirla(cls.engine)

    def setUp(self):
        self.sf = sessionmaker(bind=self.engine, autoflush=False, expire_on_commit=False)
        self._patches = [
            patch("database.personel_service.get_session", self._session_cm),
            patch("database.personel_performans_service.get_session", self._session_cm),
            patch("database.personel_service.schema_hazirla"),
            patch("database.personel_performans_service.schema_hazirla"),
            patch("database.personel_performans_sema.schema_hazirla"),
            patch("database.access.yetki_var", return_value=True),
            patch("database.access.yetki_zorunlu"),
            patch("database.access.yazma_zorunlu"),
            patch("database.access.aktif_firma_zorunlu"),
            patch("database.donem_service.DonemService.kayit_izinli_mi", return_value=True),
        ]
        for p in self._patches:
            p.start()
        oturum.user_id = 7
        oturum.kullanici_adi = "olcme_test"
        oturum.ad_soyad = "Ölçme Test"
        oturum.role_kod = "YONETICI"
        oturum.permissions = set()
        self.pids = []
        for i, ad in enumerate(("Ali", "Veli", "Ayşe"), start=1):
            r = PersonelService.kaydet(
                {
                    "kod": f"OLC{i:02d}",
                    "ad": ad,
                    "soyad": "Test",
                    "kimlik_turu": "DIGER",
                    "calisma_durumu": "AKTIF",
                    "donem": {"giris_tarihi": "2024-01-01", "gorev": "Depo"},
                }
            )
            self.pids.append(r["id"])

    def tearDown(self):
        for p in self._patches:
            p.stop()

    def _session_cm(self):
        outer = self

        class CM:
            def __enter__(self):
                self.s = outer.sf()
                return self.s

            def __exit__(self, exc_type, exc, tb):
                try:
                    if exc_type is not None:
                        self.s.rollback()
                    else:
                        self.s.commit()
                except Exception:
                    self.s.rollback()
                    raise
                finally:
                    self.s.close()
                return False

        return CM()

    def test_hesap_idempotent_ve_bordro_stub(self):
        donem = PersonelPerformansService.prim_donem_olustur(
            2026, 10, havuz=10_000, politika_json='{"ekip":50,"katki":30,"kidem":20}'
        )
        # Aynı yıl/ay tekrar → mevcut dönemi döner
        tekrar = PersonelPerformansService.prim_donem_olustur(2026, 10, havuz=10_000)
        self.assertTrue(tekrar.get("mevcut"))
        self.assertEqual(tekrar["id"], donem["id"])

        kisiler = [
            {"personel_id": self.pids[0], "hizmet_yili": 0, "performans": 100, "katilim": 1},
            {"personel_id": self.pids[1], "hizmet_yili": 0, "performans": 100, "katilim": 1},
            {"personel_id": self.pids[2], "hizmet_yili": 0, "performans": 100, "katilim": 1},
        ]
        r1 = PersonelPerformansService.prim_hesapla(donem["id"], kisiler=kisiler)
        r2 = PersonelPerformansService.prim_hesapla(donem["id"], kisiler=kisiler)
        self.assertEqual(len(r1["paylar"]), 3)
        self.assertEqual(len(r2["paylar"]), 3)
        with self._session_cm() as s:
            n = s.scalar(
                select(func.count())
                .select_from(PersonelPrimPay)
                .where(PersonelPrimPay.donem_id == donem["id"])
            )
        self.assertEqual(n, 3)
        self.assertEqual(Decimal(str(r1["dagitilan"])), Decimal(str(r2["dagitilan"])))

        PersonelPerformansService.prim_onayla(donem["id"])
        stub = PersonelPerformansService.prim_bordroya_bagla(donem["id"])
        self.assertFalse(stub["baglandi"])
        self.assertEqual(stub["neden"], "BORDRO_BAGLANTI_MVP")

        stub2 = PersonelPerformansService.bordroya_aktar(donem["id"], yil=2026, ay=10)
        self.assertFalse(stub2["baglandi"])
        self.assertEqual(stub2["neden"], "BORDRO_BAGLANTI_MVP")

        with self._session_cm() as s:
            d = s.get(PersonelPrimDonem, donem["id"])
            self.assertEqual(d.durum, "ONAYLANDI")


if __name__ == "__main__":
    unittest.main()
