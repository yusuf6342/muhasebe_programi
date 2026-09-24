"""Çift yönlü cari ortalama valör — talimat §9 birim testleri.

Çalıştırma: python -m unittest tests.test_cari_ortalama_valor -v
"""

from __future__ import annotations

import sys
import tempfile
import unittest
from datetime import date
from decimal import Decimal
from pathlib import Path
from unittest.mock import MagicMock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from sqlalchemy import create_engine, event, select
from sqlalchemy.orm import sessionmaker

from database.database import Base, _aktif_engine_bagla, company_db, get_session
from database.models.cari import Cari, CariIslem, SatisHareketi
from database.models.donem import Donem
from database.models.firma import Firma
from database.session_manager import oturum
from database.cari_ortalama_valor_service import (
    calculate_account_average_value_date,
    fifo_valor_paketi_hesapla,
)
from database.cari_service import CariService


def _sqlite_pragma(dbapi_connection, _connection_record):
    cur = dbapi_connection.cursor()
    cur.execute("PRAGMA foreign_keys=ON")
    cur.close()


def _mock_hareket(hid, tarih, belge, tutar, kalan=None):
    h = MagicMock()
    h.id = hid
    h.satis_tarihi = tarih
    h.belge_no = belge
    h.satis_tutari = Decimal(str(tutar))
    h.kalan_acik_tutar = Decimal(str(kalan if kalan is not None else tutar))
    return h


def _mock_islem(iid, tarih, belge, alacak=0, borc=0, tur="Tahsilat"):
    i = MagicMock()
    i.id = iid
    i.tarih = tarih
    i.belge_no = belge
    i.alacak = Decimal(str(alacak))
    i.borc = Decimal(str(borc))
    i.islem_turu = tur
    return i


class OrtalamaValorBirimTest(unittest.TestCase):
    """FIFO / ağırlıklı ortalama — DB'siz mock hareketler."""

    def test_01_alacak_bakiyesi_ortalama_tarih(self):
        """10000@10.10.2026 + 5000@20.10.2026 → ~13.10.2026."""
        rapor = date(2026, 10, 13)
        # Borç yok; iki açık alacak (eşleşmeyen tahsilat)
        islemler = [
            _mock_islem(1, date(2026, 10, 10), "THS-1", alacak=10000),
            _mock_islem(2, date(2026, 10, 20), "THS-2", alacak=5000),
        ]
        _tam, acik_b, _dil, acik_a = fifo_valor_paketi_hesapla(
            [], islemler, cari_turu="Müşteri", referans=rapor
        )
        self.assertEqual(acik_b, [])
        self.assertEqual(len(acik_a), 2)
        from database.cari_ortalama_valor_service import _sonuc_olustur

        sonuc = _sonuc_olustur(Decimal("-15000"), acik_b, acik_a, rapor)
        self.assertEqual(sonuc["bakiye_yonu"], "ALACAKLI")
        self.assertEqual(sonuc["valor_turu"], "ALACAK")
        self.assertIsNotNone(sonuc["ortalama_valor_tarihi"])
        self.assertEqual(sonuc["ortalama_valor_tarihi"], date(2026, 10, 13))
        # Gün ≈ 0 (yuvarlanmış tarih ile aynı gün; ağırlıklı gün küsuratı olabilir)
        self.assertAlmostEqual(sonuc["ortalama_valor_gun"], 0.0, delta=1.0)

    def test_02_borc_yalniz_degismeyen_gun(self):
        """Borçlu hesapta açık borç valörü = eski _agirlikli_gun_ortalama."""
        referans = date(2026, 10, 20)
        hareketler = [
            _mock_hareket(1, date(2026, 10, 1), "SF-1", 1000),
            _mock_hareket(2, date(2026, 10, 10), "SF-2", 2000),
        ]
        _tam, acik, _dil, _al = fifo_valor_paketi_hesapla(
            hareketler, [], cari_turu="Müşteri", referans=referans
        )
        eski = CariService._agirlikli_gun_ortalama(acik)
        from database.cari_ortalama_valor_service import _sonuc_olustur

        sonuc = _sonuc_olustur(Decimal("3000"), acik, _al, referans)
        self.assertEqual(sonuc["valor_turu"], "BORC")
        self.assertAlmostEqual(sonuc["ortalama_valor_gun"], eski, places=6)
        # 1000*19 + 2000*10 = 19000+20000=39000 / 3000 = 13
        self.assertAlmostEqual(sonuc["ortalama_valor_gun"], 13.0, places=4)

    def test_03_tam_kapanan_haric(self):
        hareketler = [_mock_hareket(1, date(2026, 9, 1), "SF-1", 500)]
        islemler = [_mock_islem(1, date(2026, 9, 15), "THS-1", alacak=500)]
        _tam, acik_b, dilimler, acik_a = fifo_valor_paketi_hesapla(
            hareketler, islemler, cari_turu="Müşteri", referans=date(2026, 10, 1)
        )
        self.assertEqual(acik_b, [])
        self.assertEqual(acik_a, [])
        self.assertTrue(_tam or dilimler)

    def test_04_kismi_odeme_kalan_agirlik(self):
        hareketler = [_mock_hareket(1, date(2026, 10, 1), "SF-1", 1000)]
        islemler = [_mock_islem(1, date(2026, 10, 5), "THS-1", alacak=400)]
        _tam, acik_b, _dil, _al = fifo_valor_paketi_hesapla(
            hareketler, islemler, cari_turu="Müşteri", referans=date(2026, 10, 11)
        )
        self.assertEqual(len(acik_b), 1)
        self.assertEqual(acik_b[0]["tutar"], Decimal("600.00"))
        self.assertEqual(acik_b[0]["gun"], 10)  # 11.10 − 01.10

    def test_05_bakiye_sifir_valor_yok(self):
        from database.cari_ortalama_valor_service import _sonuc_olustur

        sonuc = _sonuc_olustur(Decimal("0"), [], [], date(2026, 10, 1))
        self.assertEqual(sonuc["valor_turu"], "YOK")
        self.assertIsNone(sonuc["ortalama_valor_tarihi"])
        self.assertEqual(sonuc["ortalama_valor_gun"], 0.0)

    def test_06_deterministik_siralama(self):
        # Aynı tarihte iki borç; id sırası sonucu belirler
        h1 = [_mock_hareket(2, date(2026, 10, 1), "SF-B", 100),
              _mock_hareket(1, date(2026, 10, 1), "SF-A", 100)]
        h2 = list(reversed(h1))
        islem = [_mock_islem(1, date(2026, 10, 2), "THS-1", alacak=100)]
        r1 = fifo_valor_paketi_hesapla(h1, islem, cari_turu="Müşteri", referans=date(2026, 10, 5))
        r2 = fifo_valor_paketi_hesapla(h2, islem, cari_turu="Müşteri", referans=date(2026, 10, 5))
        # Kalan açık borç aynı belge olmalı (id=1 önce kapanır)
        self.assertEqual(r1[1][0]["borc_belge_no"], r2[1][0]["borc_belge_no"])
        self.assertEqual(r1[1][0]["tutar"], r2[1][0]["tutar"])

    def test_07_eksik_vade_islem_tarihi(self):
        h = _mock_hareket(1, date(2026, 10, 5), "SF-X", 250)
        _tam, acik, _d, _a = fifo_valor_paketi_hesapla(
            [h], [], cari_turu="Müşteri", vade_harita={}, referans=date(2026, 10, 15)
        )
        self.assertEqual(acik[0]["borc_vadesi"], date(2026, 10, 5))
        self.assertEqual(acik[0]["gun"], 10)


class OrtalamaValorDbTest(unittest.TestCase):
    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self.db_path = Path(self._tmpdir.name) / "valor.db"
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
        import database.models.satis_faturasi  # noqa: F401
        import database.models.satis_iade_faturasi  # noqa: F401
        import database.models.satis_irsaliyesi  # noqa: F401
        import database.models.satis_siparisi  # noqa: F401
        import database.models.stok  # noqa: F401

        Base.metadata.create_all(eng)
        Session = sessionmaker(
            bind=eng, autoflush=False, autocommit=False, expire_on_commit=False
        )
        with Session() as s:
            firma = Firma(firma_kodu="VAL", unvan="Valor Test", aktif=True)
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
        company_db._session_factory = Session
        company_db._company_id = 1
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
            company_id=1,
            firma_kodu="VAL",
            firma_unvan="Valor",
            firma_uid="val",
            db_path=str(self.db_path),
        )
        with get_session() as s:
            d = s.scalar(select(Donem).limit(1))
            if d:
                oturum.set_period(d.id, d.donem_adi)

        with get_session() as s:
            m = Cari(
                cari_kodu="M-HAKAN",
                unvan="Hakan Çevik",
                cari_turu="Müşteri",
                aktif=True,
            )
            t = Cari(
                cari_kodu="T-ALACAK",
                unvan="Alacaklı Tedarikçi",
                cari_turu="Tedarikçi",
                aktif=True,
            )
            m2 = Cari(
                cari_kodu="M-BORC",
                unvan="Borçlu Müşteri",
                cari_turu="Müşteri",
                aktif=True,
            )
            s.add_all([m, t, m2])
            s.flush()
            self.alacakli_id = int(m.id)
            self.tedarikci_id = int(t.id)
            self.borclu_id = int(m2.id)
            # Hakan: açılış alacak + tahsilat (borç yok) → alacaklı
            s.add(
                CariIslem(
                    cari_id=m.id,
                    tarih=date(2026, 10, 10),
                    islem_turu="Açılış",
                    belge_no="ACL-H1",
                    borc=Decimal("0"),
                    alacak=Decimal("10000"),
                )
            )
            s.add(
                CariIslem(
                    cari_id=m.id,
                    tarih=date(2026, 10, 20),
                    islem_turu="Tahsilat",
                    belge_no="THS-H2",
                    borc=Decimal("0"),
                    alacak=Decimal("5000"),
                )
            )
            # Tedarikçi alacaklı: fazla ödeme benzeri alacak
            s.add(
                CariIslem(
                    cari_id=t.id,
                    tarih=date(2026, 9, 1),
                    islem_turu="Ödeme",
                    belge_no="ODM-T1",
                    borc=Decimal("0"),
                    alacak=Decimal("800"),
                )
            )
            # Borçlu müşteri: açık fatura borcu
            s.add(
                SatisHareketi(
                    cari_id=m2.id,
                    satis_tarihi=date(2026, 10, 1),
                    belge_no="SF-B1",
                    satis_tutari=Decimal("1200"),
                    kalan_acik_tutar=Decimal("1200"),
                )
            )
            s.commit()

    def tearDown(self):
        oturum.clear()
        try:
            self._tmpdir.cleanup()
        except Exception:
            pass

    def test_08_hakan_alacak_valor_dolu(self):
        rapor = date(2026, 10, 13)
        sonuc = calculate_account_average_value_date(
            self.alacakli_id, rapor_tarihi=rapor
        )
        self.assertEqual(sonuc["bakiye_yonu"], "ALACAKLI")
        self.assertEqual(sonuc["valor_turu"], "ALACAK")
        self.assertIsNotNone(sonuc["ortalama_valor_tarihi"])
        self.assertEqual(sonuc["ortalama_valor_tarihi"], date(2026, 10, 13))
        self.assertNotEqual(sonuc["ortalama_valor_gun"], None)
        # Kart özeti de aynı alanı doldurmalı
        metrik = CariService.kart_ozet_metrikleri(self.alacakli_id)
        self.assertEqual(metrik["valor_turu"], "ALACAK")
        self.assertNotEqual(float(metrik["bakiye_ortalama_valor_gun"]), 0.0)

    def test_09_tedarikci_alacak_valor(self):
        sonuc = calculate_account_average_value_date(
            self.tedarikci_id, rapor_tarihi=date(2026, 9, 11)
        )
        self.assertEqual(sonuc["bakiye_yonu"], "ALACAKLI")
        self.assertEqual(sonuc["valor_turu"], "ALACAK")
        self.assertIsNotNone(sonuc["ortalama_valor_tarihi"])

    def test_10_borclu_kart_ozet(self):
        metrik = CariService.kart_ozet_metrikleri(self.borclu_id)
        self.assertEqual(metrik["bakiye_yonu"], "BORCLU")
        self.assertEqual(metrik["valor_turu"], "BORC")
        self.assertIsNotNone(metrik.get("ortalama_valor_tarihi"))
        # Gün = bugün − vade (gelecek vadede negatif olabilir)
        self.assertNotEqual(metrik.get("bakiye_ortalama_valor_gun"), None)

    def test_11_firma_izolasyonu_ayri_cari(self):
        """Aynı kodlu başka cari hareketi karışmamalı (ayrı id)."""
        with get_session() as s:
            diger = Cari(
                cari_kodu="M-HAKAN-2",
                unvan="Başka Hakan",
                cari_turu="Müşteri",
                aktif=True,
            )
            s.add(diger)
            s.flush()
            diger_id = int(diger.id)
            s.add(
                CariIslem(
                    cari_id=diger_id,
                    tarih=date(2026, 1, 1),
                    islem_turu="Tahsilat",
                    belge_no="THS-DIGER",
                    borc=Decimal("0"),
                    alacak=Decimal("99999"),
                )
            )
            s.commit()
        a = calculate_account_average_value_date(
            self.alacakli_id, rapor_tarihi=date(2026, 10, 13)
        )
        b = calculate_account_average_value_date(
            diger_id, rapor_tarihi=date(2026, 10, 13)
        )
        self.assertEqual(a["toplam_acik_tutar"], Decimal("15000.00"))
        self.assertEqual(b["toplam_acik_tutar"], Decimal("99999.00"))
        self.assertNotEqual(a["ortalama_valor_tarihi"], b["ortalama_valor_tarihi"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
