"""Stok Kartı üst özet kartları — sıra ve veri-başlık eşleşmesi.

Çalıştırma: python tests/test_stok_karti_ozet_sirasi.py
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

from sqlalchemy import create_engine, event, select
from sqlalchemy.orm import sessionmaker

from database.database import Base, _aktif_engine_bagla, company_db, get_session
from database.models.donem import Donem
from database.models.firma import Firma
from database.models.stok import Depo, StokHareketi, StokKarti, StokLotu
from database.session_manager import oturum
from database.stok_service import StokService


def _sqlite_pragma(dbapi_connection, _connection_record):
    cur = dbapi_connection.cursor()
    cur.execute("PRAGMA foreign_keys=ON")
    cur.close()


OZET_SIRA = (
    "Toplam Giriş",
    "Toplam Çıkış",
    "Kalan Miktar",
    "FIFO Envanter Değeri",
)


class StokKartiOzetSirasiTest(unittest.TestCase):
    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self.db_path = Path(self._tmpdir.name) / "test_ozet.db"
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
            firma = Firma(firma_kodu="OZ", unvan="Özet Test", aktif=True)
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
        company_db._company_id = 55
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
            company_id=55,
            firma_kodu="OZ",
            firma_unvan="Özet Test",
            firma_uid="oz",
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
            st = StokKarti(stok_kodu="OZ1", stok_adi="Özet Ürün", birim="Adet", aktif=True)
            s.add(st)
            s.flush()
            self.stok_id = int(st.id)
            lot = StokLotu(
                stok_id=st.id,
                depo_id=depo.id,
                lot_no="L1",
                giris_tarihi=date(2026, 1, 1),
                kalan_miktar=Decimal("70"),
                birim_maliyet=Decimal("10"),
            )
            s.add(lot)
            s.flush()
            s.add(
                StokHareketi(
                    tarih=date(2026, 1, 1),
                    hareket_turu="FATURA GİRİŞ",
                    belge_no="G1",
                    stok_id=st.id,
                    depo_id=depo.id,
                    lot_id=lot.id,
                    miktar=Decimal("100"),
                    birim_maliyet=Decimal("10"),
                    olusturma_tarihi=datetime(2026, 1, 1, 10, 0, 0),
                )
            )
            s.add(
                StokHareketi(
                    tarih=date(2026, 2, 1),
                    hareket_turu="FATURA ÇIKIŞ",
                    belge_no="C1",
                    stok_id=st.id,
                    depo_id=depo.id,
                    lot_id=lot.id,
                    miktar=Decimal("30"),
                    birim_maliyet=Decimal("10"),
                    olusturma_tarihi=datetime(2026, 2, 1, 10, 0, 0),
                )
            )

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

    def test_01_stok_ozeti_giris_cikis_kalan(self):
        o = StokService.stok_ozeti(self.stok_id)
        self.assertEqual(o["toplam_giris"], Decimal("100"))
        self.assertEqual(o["toplam_cikis"], Decimal("30"))
        self.assertEqual(o["kalan"], Decimal("70"))
        self.assertEqual(o["toplam_giris"] - o["toplam_cikis"], o["kalan"])
        self.assertEqual(o["fifo_deger"], Decimal("700"))  # 70 * 10

    def test_02_kart_sirasi_kaynak_kodda(self):
        metin = Path(ROOT / "stok_ui.py").read_text(encoding="utf-8")
        # Sıra literal olarak doğru olmalı
        beklenen = (
            '"Toplam Giriş",\n'
            '            "Toplam Çıkış",\n'
            '            "Kalan Miktar",\n'
            '            "FIFO Envanter Değeri",'
        )
        self.assertIn(beklenen, metin)
        # Eski sıra (Kalan başta) olmamalı
        eski = '("Kalan Miktar", "Toplam Giriş", "Toplam Çıkış", "FIFO Envanter Değeri")'
        self.assertNotIn(eski, metin)

    def test_03_ui_etiket_eslesmesi(self):
        """_ozeti_yenile doğru başlıklara doğru değerleri yazar."""
        import tkinter as tk

        from stok_ui import StokKartiDialog, para_goster

        root = tk.Tk()
        root.withdraw()
        try:
            # Minimal stub: sadece özet etiketleri
            dlg = object.__new__(StokKartiDialog)
            dlg.stok = type("S", (), {"id": self.stok_id, "birim": "Adet"})()
            dlg.birimler = []
            dlg.varsayilan_goruntuleme_birim = "Adet"
            dlg.alanlar = {"birim": type("E", (), {"get": lambda self: "Adet"})(), "raf_yeri": type("E", (), {"get": lambda self: ""})()}
            dlg.ozet_etiketleri = {
                b: tk.Label(root, text="") for b in OZET_SIRA
            }
            dlg.ozet_alt_etiketleri = {b: tk.Label(root, text="") for b in OZET_SIRA}
            StokKartiDialog._ozeti_yenile(dlg)
            self.assertIn("100", dlg.ozet_etiketleri["Toplam Giriş"].cget("text"))
            self.assertIn("30", dlg.ozet_etiketleri["Toplam Çıkış"].cget("text"))
            self.assertIn("70", dlg.ozet_etiketleri["Kalan Miktar"].cget("text"))
            self.assertEqual(
                dlg.ozet_etiketleri["FIFO Envanter Değeri"].cget("text"),
                para_goster(Decimal("700")),
            )
            # Sıra sabit
            self.assertEqual(tuple(dlg.ozet_etiketleri.keys()), OZET_SIRA)
        finally:
            root.destroy()

    def test_04_ekran_goruntusu_sirasi(self):
        """Tam dialog açılışında grid sütun sırası doğrulanır + ekran görüntüsü."""
        import tkinter as tk

        from stok_ui import StokKartiDialog

        root = tk.Tk()
        root.withdraw()
        stok = StokService.stok_getir(self.stok_id)
        try:
            with patch.object(StokKartiDialog, "_pencere_boyutunu_ayarla", lambda self: None):
                dlg = StokKartiDialog(root, stok=stok)
            root.update_idletasks()
            sirali = []
            for baslik in OZET_SIRA:
                fr = dlg.ozet_kartlari[baslik]["frame"]
                info = fr.grid_info()
                sirali.append((int(info["column"]), baslik))
            sirali.sort()
            self.assertEqual([b for _, b in sirali], list(OZET_SIRA))
            # Değer-başlık
            self.assertIn("100", dlg.ozet_etiketleri["Toplam Giriş"].cget("text"))
            self.assertIn("30", dlg.ozet_etiketleri["Toplam Çıkış"].cget("text"))
            self.assertIn("70", dlg.ozet_etiketleri["Kalan Miktar"].cget("text"))
            # Ekran görüntüsü
            out = Path(self._tmpdir.name) / "stok_ozet_sirasi.png"
            try:
                from PIL import ImageGrab

                dlg.update_idletasks()
                x = dlg.winfo_rootx()
                y = dlg.winfo_rooty()
                w = dlg.winfo_width()
                h = min(220, dlg.winfo_height())
                if w > 1 and h > 1:
                    img = ImageGrab.grab(bbox=(x, y, x + w, y + h))
                    img.save(out)
                    self.assertTrue(out.exists() and out.stat().st_size > 0)
            except Exception:
                # Ortam ekran yakalamayı desteklemiyorsa atla (grid testi yeterli)
                pass
            dlg.destroy()
        finally:
            root.destroy()


if __name__ == "__main__":
    unittest.main(verbosity=2)
