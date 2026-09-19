"""Stok hareketleri — Giriş/Çıkış/Kalan + satır FIFO kalan değeri.

Çalıştırma: python tests/test_stok_hareket_fifo_ekstre.py
"""

from __future__ import annotations

import sys
import tempfile
import unittest
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker

from sqlalchemy import select

from database.database import Base, _aktif_engine_bagla, company_db, get_session
from database.fiyatli_stok_ekstresi_service import FifoKatmanMotoru, FiyatliStokEkstreService
from database.models.donem import Donem
from database.models.firma import Firma
from database.models.stok import Depo, StokHareketi, StokKarti
from database.session_manager import oturum


def _sqlite_pragma(dbapi_connection, _connection_record):
    cur = dbapi_connection.cursor()
    cur.execute("PRAGMA foreign_keys=ON")
    cur.close()


class FifoKatmanMotoruTest(unittest.TestCase):
    def test_01_devir_giris_fifo_deger(self):
        """Devir 50@10 + giriş 20@12 → kalan 70, FIFO 740."""
        m = FifoKatmanMotoru()
        m.giris(Decimal("50"), Decimal("10"))
        m.giris(Decimal("20"), Decimal("12"))
        self.assertEqual(m.lot_miktar(), Decimal("70"))
        self.assertEqual(m.fifo_deger(), Decimal("740"))

    def test_02_kismi_fifo_cikis(self):
        """60 çıkış: eski 50 tamamen + yeni lottan 10 → kalan 10, değer 120."""
        m = FifoKatmanMotoru()
        m.giris(Decimal("50"), Decimal("10"))
        m.giris(Decimal("20"), Decimal("12"))
        cost, unc = m.cikis(Decimal("60"))
        self.assertEqual(unc, Decimal("0"))
        self.assertEqual(cost, Decimal("50") * 10 + Decimal("10") * 12)
        self.assertEqual(m.lot_miktar(), Decimal("10"))
        self.assertEqual(m.fifo_deger(), Decimal("120"))

    def test_03_negatif_stok_uydurma_yok(self):
        m = FifoKatmanMotoru()
        m.giris(Decimal("5"), Decimal("10"))
        cost, unc = m.cikis(Decimal("8"))
        self.assertEqual(cost, Decimal("50"))
        self.assertEqual(unc, Decimal("3"))
        self.assertEqual(m.fifo_deger(), Decimal("0"))
        self.assertEqual(m.negatif_acik, Decimal("3"))


class StokHareketFifoEkstreTest(unittest.TestCase):
    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self.db_path = Path(self._tmpdir.name) / "test_fifo_hareket.db"
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
            firma = Firma(firma_kodu="FIFO", unvan="FIFO Test", aktif=True)
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
        company_db._company_id = 92
        company_db._db_path = self.db_path

        oturum.clear()
        oturum.set_user(
            user_id=1,
            kullanici_adi="admin",
            ad_soyad="Test Admin",
            role_kod="YONETICI",
            role_ad="Yönetici",
            permissions=set(),
        )
        oturum.set_company(
            company_id=92,
            firma_kodu="FIFO",
            firma_unvan="FIFO Test",
            firma_uid="fifo-test",
            db_path=str(self.db_path),
        )
        with get_session() as s:
            d = s.scalar(select(Donem).limit(1))
            if d:
                oturum.set_period(d.id, d.donem_adi)

        self._audit = patch("database.user_audit.audit_document", return_value=None)
        self._audit.start()
        self._izin = patch(
            "database.fiyatli_stok_ekstresi_service.maliyet_izinli", return_value=True
        )
        self._izin.start()

        with get_session() as s:
            depo = Depo(kod="ANA", ad="ANA DEPO", aktif=True, varsayilan=True)
            sube = Depo(kod="SUB", ad="ŞUBE", aktif=True, varsayilan=False)
            s.add(depo)
            s.add(sube)
            s.flush()
            st = StokKarti(stok_kodu="FIFO1", stok_adi="FIFO Ürün", birim="Adet", aktif=True)
            s.add(st)
            s.flush()
            self.stok_id = st.id
            self.depo_id = depo.id
            self.sube_id = sube.id
            s.add(
                StokHareketi(
                    tarih=date(2025, 12, 1),
                    hareket_turu="GİRİŞ",
                    belge_no="DEV-50",
                    stok_id=st.id,
                    depo_id=depo.id,
                    miktar=Decimal("50"),
                    birim_maliyet=Decimal("10"),
                    olusturma_tarihi=datetime(2025, 12, 1, 8, 0, 0),
                )
            )
            s.add(
                StokHareketi(
                    tarih=date(2026, 2, 1),
                    hareket_turu="GİRİŞ",
                    belge_no="G-20",
                    stok_id=st.id,
                    depo_id=depo.id,
                    miktar=Decimal("20"),
                    birim_maliyet=Decimal("12"),
                    olusturma_tarihi=datetime(2026, 2, 1, 9, 0, 0),
                )
            )
            s.add(
                StokHareketi(
                    tarih=date(2026, 3, 1),
                    hareket_turu="ÇIKIŞ",
                    belge_no="C-60",
                    stok_id=st.id,
                    depo_id=depo.id,
                    miktar=Decimal("60"),
                    birim_maliyet=Decimal("0"),
                    olusturma_tarihi=datetime(2026, 3, 1, 10, 0, 0),
                )
            )
            s.add(
                StokHareketi(
                    tarih=date(2026, 4, 1),
                    hareket_turu="GİRİŞ",
                    belge_no="AYNI-1",
                    stok_id=st.id,
                    depo_id=depo.id,
                    miktar=Decimal("5"),
                    birim_maliyet=Decimal("8"),
                    olusturma_tarihi=datetime(2026, 4, 1, 12, 0, 0),
                )
            )
            s.add(
                StokHareketi(
                    tarih=date(2026, 4, 1),
                    hareket_turu="GİRİŞ",
                    belge_no="AYNI-2",
                    stok_id=st.id,
                    depo_id=depo.id,
                    miktar=Decimal("3"),
                    birim_maliyet=Decimal("9"),
                    olusturma_tarihi=datetime(2026, 4, 1, 12, 0, 0),
                )
            )
            s.add(
                StokHareketi(
                    tarih=date(2026, 5, 1),
                    hareket_turu="TRANSFER ÇIKIŞ",
                    belge_no="TR-X",
                    stok_id=st.id,
                    depo_id=depo.id,
                    miktar=Decimal("2"),
                    birim_maliyet=Decimal("8"),
                    olusturma_tarihi=datetime(2026, 5, 1, 8, 0, 0),
                )
            )
            s.add(
                StokHareketi(
                    tarih=date(2026, 5, 1),
                    hareket_turu="TRANSFER GİRİŞ",
                    belge_no="TR-X",
                    stok_id=st.id,
                    depo_id=sube.id,
                    miktar=Decimal("2"),
                    birim_maliyet=Decimal("8"),
                    olusturma_tarihi=datetime(2026, 5, 1, 8, 0, 1),
                )
            )
            s.commit()

    def tearDown(self):
        self._audit.stop()
        self._izin.stop()
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

    def test_04_ekstre_fifo_senaryo(self):
        r = FiyatliStokEkstreService.hareket_ekstresi(
            self.stok_id,
            baslangic=date(2026, 1, 1),
            bitis=date(2026, 3, 31),
            depo_adi="ANA DEPO",
        )
        self.assertEqual(r["satirlar"][0]["hareket_turu"], "DEVRİ")
        self.assertEqual(r["satirlar"][0]["kalan"], Decimal("50"))
        self.assertEqual(r["satirlar"][0]["kalan_deger"], Decimal("500"))

        giris = next(s for s in r["satirlar"] if s["belge_no"] == "G-20")
        self.assertEqual(giris["giren"], Decimal("20"))
        self.assertEqual(giris["cikan"], Decimal("0"))
        self.assertEqual(giris["kalan"], Decimal("70"))
        self.assertEqual(giris["kalan_deger"], Decimal("740"))

        cikis = next(s for s in r["satirlar"] if s["belge_no"] == "C-60")
        self.assertEqual(cikis["cikan"], Decimal("60"))
        self.assertEqual(cikis["giren"], Decimal("0"))
        self.assertEqual(cikis["kalan"], Decimal("10"))
        self.assertEqual(cikis["kalan_deger"], Decimal("120"))
        self.assertEqual(r["ozet"]["kalan_miktar"], Decimal("10"))
        self.assertEqual(r["ozet"]["fifo_kalan_degeri"], Decimal("120"))

    def test_05_ayni_tarih_deterministik(self):
        r1 = FiyatliStokEkstreService.hareket_ekstresi(
            self.stok_id, baslangic=date(2026, 4, 1), bitis=date(2026, 4, 1), depo_adi="ANA DEPO"
        )
        r2 = FiyatliStokEkstreService.hareket_ekstresi(
            self.stok_id, baslangic=date(2026, 4, 1), bitis=date(2026, 4, 1), depo_adi="ANA DEPO"
        )
        belgeler1 = [s["belge_no"] for s in r1["satirlar"] if s["satir_turu"] == "hareket"]
        belgeler2 = [s["belge_no"] for s in r2["satirlar"] if s["satir_turu"] == "hareket"]
        self.assertEqual(belgeler1, belgeler2)
        self.assertEqual(belgeler1[:2], ["AYNI-1", "AYNI-2"])

    def test_06_transfer_depo_izolasyon(self):
        ana = FiyatliStokEkstreService.hareket_ekstresi(
            self.stok_id,
            baslangic=date(2026, 1, 1),
            bitis=date(2026, 12, 31),
            depo_adi="ANA DEPO",
        )
        sube = FiyatliStokEkstreService.hareket_ekstresi(
            self.stok_id,
            baslangic=date(2026, 1, 1),
            bitis=date(2026, 12, 31),
            depo_adi="ŞUBE",
        )
        tum = FiyatliStokEkstreService.hareket_ekstresi(
            self.stok_id,
            baslangic=date(2026, 1, 1),
            bitis=date(2026, 12, 31),
        )
        # Şube: sadece transfer giriş 2
        self.assertEqual(sube["ozet"]["giren_miktar"], Decimal("2"))
        self.assertEqual(sube["ozet"]["kalan_miktar"], Decimal("2"))
        # Şirket toplamı: transfer net sıfır etkisi (çıkış+giriş)
        self.assertEqual(
            tum["ozet"]["kalan_miktar"],
            ana["ozet"]["kalan_miktar"] + sube["ozet"]["kalan_miktar"],
        )

    def test_07_ust_ozet_mutabakat(self):
        r = FiyatliStokEkstreService.hareket_ekstresi(
            self.stok_id, baslangic=date(2026, 1, 1), bitis=date(2026, 12, 31)
        )
        son = r["satirlar"][-1]
        self.assertEqual(son["kalan"], r["ozet"]["kalan_miktar"])
        self.assertEqual(son["kalan_deger"], r["ozet"]["fifo_kalan_degeri"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
