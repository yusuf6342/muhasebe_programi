"""Performans optimizasyonları — doğruluk ve mikro ölçüm.

Çalıştırma: python tests/test_performans_optimizasyon.py
"""

from __future__ import annotations

import sys
import tempfile
import time
import unittest
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from sqlalchemy import create_engine, event, select
from sqlalchemy.orm import sessionmaker

from database.database import Base, _aktif_engine_bagla, company_db, performans_indekslerini_hazirla
from database.models.cari import Cari, CariIslem, SatisHareketi
from database.models.donem import Donem
from database.models.firma import Firma
from database.models.stok import Depo, StokHareketi, StokKarti
from database.session_manager import oturum
from database.cari_service import CariService
from database.database import get_session


def _sqlite_pragma(dbapi_connection, _connection_record):
    cur = dbapi_connection.cursor()
    cur.execute("PRAGMA foreign_keys=ON")
    cur.close()


class PerformansOptTest(unittest.TestCase):
    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self.db_path = Path(self._tmpdir.name) / "perf.db"
        eng = create_engine(
            f"sqlite:///{self.db_path.as_posix()}",
            connect_args={"check_same_thread": False},
        )
        event.listen(eng, "connect", _sqlite_pragma)

        import database.models.alis_faturasi  # noqa: F401
        import database.models.alis_iade_faturasi  # noqa: F401
        import database.models.alis_irsaliyesi  # noqa: F401
        import database.models.alis_masraf  # noqa: F401
        import database.models.alis_siparisi  # noqa: F401
        import database.models.cari  # noqa: F401
        import database.models.donem  # noqa: F401
        import database.models.finans  # noqa: F401
        import database.models.firma  # noqa: F401
        import database.models.hizli_satis  # noqa: F401
        import database.models.satis_faturasi  # noqa: F401
        import database.models.satis_iade_faturasi  # noqa: F401
        import database.models.satis_irsaliyesi  # noqa: F401
        import database.models.satis_siparisi  # noqa: F401
        import database.models.stok  # noqa: F401
        import database.models.stok_sayim  # noqa: F401

        Base.metadata.create_all(eng)
        Session = sessionmaker(bind=eng, autoflush=False, autocommit=False, expire_on_commit=False)
        with Session() as s:
            firma = Firma(firma_kodu="PERF", unvan="Perf Test", aktif=True)
            s.add(firma)
            s.flush()
            s.add(
                Donem(
                    firma_id=firma.id,
                    donem_adi="2026",
                    baslangic_tarihi=date(2026, 1, 1),
                    bitis_tarihi=date(2026, 12, 31),
                    aktif=True,
                    kapali=False,
                    varsayilan=True,
                )
            )
            s.commit()

        _aktif_engine_bagla(eng)
        company_db._engine = eng
        company_db._session_factory = sessionmaker(
            bind=eng, autoflush=False, autocommit=False, expire_on_commit=False
        )
        company_db._company_id = 93
        company_db._db_path = self.db_path

        oturum.clear()
        oturum.set_user(
            user_id=1,
            kullanici_adi="admin",
            ad_soyad="Admin",
            role_kod="YONETICI",
            role_ad="Yönetici",
            permissions=set(),
        )
        oturum.set_company(
            company_id=93,
            firma_kodu="PERF",
            firma_unvan="Perf",
            firma_uid="perf",
            db_path=str(self.db_path),
        )
        with get_session() as s:
            d = s.scalar(select(Donem).limit(1))
            if d:
                oturum.set_period(d.id, d.donem_adi)

        self._audit = patch("database.user_audit.audit_document", return_value=None)
        self._audit.start()

        with get_session() as s:
            depo = Depo(kod="ANA", ad="ANA DEPO", aktif=True, varsayilan=True)
            s.add(depo)
            cari = Cari(
                cari_kodu="C001",
                unvan="Test Cari",
                cari_turu="MÜŞTERİ",
                aktif=True,
            )
            karsi = Cari(
                cari_kodu="C002",
                unvan="Karşı Cari",
                cari_turu="MÜŞTERİ",
                aktif=True,
            )
            s.add(cari)
            s.add(karsi)
            s.flush()
            self.cari_id = cari.id
            self.karsi_id = karsi.id
            for i in range(40):
                s.add(
                    SatisHareketi(
                        cari_id=cari.id,
                        satis_tarihi=date(2026, 1, 1 + (i % 28)),
                        belge_no=f"SF-{i+1:04d}",
                        satis_tutari=Decimal("100"),
                        kalan_acik_tutar=Decimal("100") if i % 3 else Decimal("0"),
                    )
                )
                s.add(
                    CariIslem(
                        cari_id=cari.id,
                        tarih=date(2026, 2, 1 + (i % 27)),
                        islem_turu="Tahsilat" if i % 2 == 0 else "Cari Virman",
                        belge_no=f"THS-{i+1:04d}",
                        borc=Decimal("0"),
                        alacak=Decimal("50"),
                        karsi_cari_id=self.karsi_id if i % 2 else None,
                    )
                )
            st = StokKarti(stok_kodu="S1", stok_adi="Ürün", birim="Adet", aktif=True)
            s.add(st)
            s.flush()
            self.stok_id = st.id
            for i in range(30):
                s.add(
                    StokHareketi(
                        tarih=date(2026, 3, 1 + (i % 28)),
                        hareket_turu="GİRİŞ" if i % 2 == 0 else "ÇIKIŞ",
                        belge_no=f"H-{i}",
                        stok_id=st.id,
                        depo_id=depo.id,
                        miktar=Decimal("5"),
                        birim_maliyet=Decimal("10"),
                        olusturma_tarihi=datetime(2026, 3, 1, 8, i % 60, 0),
                    )
                )
            s.commit()

    def tearDown(self):
        self._audit.stop()
        try:
            company_db.close()
        except Exception:
            pass
        try:
            if company_db._engine is not None:
                company_db._engine.dispose()
        except Exception:
            pass
        oturum.clear()
        try:
            self._tmpdir.cleanup()
        except Exception:
            pass

    def test_01_kart_ozet_tek_defter_fifo(self):
        """kart_ozet_metrikleri defter/FIFO'yu iki kez çağırmamalı."""
        calls = {"defter": 0, "fifo": 0}
        real_defter = CariService._defter
        real_fifo = CariService._fifo_valor_dilimleri

        def wrap_defter(session, cari_id):
            calls["defter"] += 1
            return real_defter(session, cari_id)

        def wrap_fifo(*a, **k):
            calls["fifo"] += 1
            return real_fifo(*a, **k)

        with patch.object(CariService, "_defter", side_effect=wrap_defter):
            with patch.object(CariService, "_fifo_valor_dilimleri", side_effect=wrap_fifo):
                m = CariService.kart_ozet_metrikleri(self.cari_id)
        self.assertIsNotNone(m)
        self.assertEqual(calls["defter"], 1)
        self.assertEqual(calls["fifo"], 1)
        self.assertGreater(len(m["hareketler"]), 0)

    def test_02_kart_ozet_bakiye_tutarli(self):
        m = CariService.kart_ozet_metrikleri(self.cari_id)
        borc = sum((Decimal(str(h.get("borc") or 0)) for h in m["hareketler"]), Decimal("0"))
        alacak = sum((Decimal(str(h.get("alacak") or 0)) for h in m["hareketler"]), Decimal("0"))
        self.assertEqual(m["toplam_borc"], borc)
        self.assertEqual(m["toplam_alacak"], alacak)
        self.assertEqual(m["bakiye"], borc - alacak)

    def test_03_hizli_listele(self):
        yavas = CariService.listele(cari_turu="Müşteri", hizli=False)
        hizli = CariService.listele(cari_turu="Müşteri", hizli=True)
        self.assertEqual(len(yavas), len(hizli))
        self.assertEqual(
            {r["cari"].id for r in yavas},
            {r["cari"].id for r in hizli},
        )

    def test_04_indeks_olusturma(self):
        from sqlalchemy import text

        performans_indekslerini_hazirla()
        with company_db._engine.connect() as conn:
            adlar = {
                r[0]
                for r in conn.execute(
                    text(
                        "SELECT name FROM sqlite_master WHERE type='index' "
                        "AND name IN ("
                        "'ix_cari_islem_cari_tarih',"
                        "'ix_satis_hareket_cari_tarih',"
                        "'ix_stok_hareket_stok_tarih_id',"
                        "'ix_cari_islem_karsi_cari'"
                        ")"
                    )
                ).fetchall()
            }
        self.assertIn("ix_cari_islem_cari_tarih", adlar)
        self.assertIn("ix_stok_hareket_stok_tarih_id", adlar)

    def test_05_mikro_sure_kart_ozet(self):
        CariService.kart_ozet_metrikleri(self.cari_id)
        t0 = time.perf_counter()
        for _ in range(5):
            CariService.kart_ozet_metrikleri(self.cari_id)
        ms = (time.perf_counter() - t0) * 1000 / 5
        print(f"\n[PERF] kart_ozet_metrikleri ort: {ms:.1f} ms")
        self.assertLess(ms, 5000)


if __name__ == "__main__":
    unittest.main(verbosity=2)
