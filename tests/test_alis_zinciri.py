"""Satın alma zinciri kabul testleri: sipariş → irsaliye → fatura, stok, kalan miktar, tedarikçi bakiyesi."""

from __future__ import annotations

import sys
import tempfile
import unittest
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from sqlalchemy import create_engine, event, func, select
from sqlalchemy.orm import sessionmaker

from database.database import Base, _aktif_engine_bagla, company_db, get_session
from database.models.cari import Cari
from database.models.donem import Donem
from database.models.firma import Firma
from database.models.stok import Depo, StokHareketi, StokKarti, StokLotu
from database.session_manager import oturum

BUGUN = date.today()


def _sqlite_pragma(dbapi_connection, _connection_record):
    cur = dbapi_connection.cursor()
    cur.execute("PRAGMA foreign_keys=ON")
    cur.close()


def _modelleri_yukle():
    import database.models.cari  # noqa: F401
    import database.models.stok  # noqa: F401
    import database.models.firma  # noqa: F401
    import database.models.donem  # noqa: F401
    import database.models.alis_faturasi  # noqa: F401
    import database.models.alis_iade_faturasi  # noqa: F401
    import database.models.alis_irsaliyesi  # noqa: F401
    import database.models.alis_siparisi  # noqa: F401
    import database.models.alis_masraf  # noqa: F401
    import database.models.finans  # noqa: F401
    import database.models.satis_faturasi  # noqa: F401
    import database.models.satis_iade_faturasi  # noqa: F401
    import database.models.satis_irsaliyesi  # noqa: F401
    import database.models.satis_siparisi  # noqa: F401
    import database.models.hizli_satis  # noqa: F401
    import database.models.odeme_sozu  # noqa: F401


class AlisZinciriTest(unittest.TestCase):
    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self.db_path = Path(self._tmpdir.name) / "test_alis_zinciri.db"
        eng = create_engine(f"sqlite:///{self.db_path.as_posix()}", connect_args={"check_same_thread": False})
        event.listen(eng, "connect", _sqlite_pragma)
        _modelleri_yukle()
        Base.metadata.create_all(eng)
        Session = sessionmaker(bind=eng, autoflush=False, autocommit=False, expire_on_commit=False)
        with Session() as s:
            firma = Firma(firma_kodu="AZT", unvan="Alış Zinciri Test", aktif=True)
            s.add(firma)
            s.flush()
            s.add(Donem(firma_id=firma.id, donem_adi="2026", baslangic_tarihi=date(2026, 1, 1),
                        bitis_tarihi=date(2026, 12, 31), aktif=True, kapali=False, varsayilan=True))
            s.add(Depo(ad="ANA DEPO", aktif=True))
            from database.models.finans import FinansHesabi

            s.add(FinansHesabi(hesap_adi="BANKA", hesap_turu="BANKA", acilis_bakiyesi=Decimal("1000"), aktif=True))
            s.add(StokKarti(stok_kodu="U001", stok_adi="Vida", birim="Adet", aktif=True, is_deleted=False))
            s.add(StokKarti(stok_kodu="U002", stok_adi="Somun", birim="Adet", aktif=True, is_deleted=False))
            s.add(Cari(cari_kodu="T001", unvan="Tedarikçi A", cari_turu="Tedarikçi", aktif=True))
            s.add(Cari(cari_kodu="T002", unvan="Tedarikçi B", cari_turu="Tedarikçi", aktif=True))
            s.commit()
        _aktif_engine_bagla(eng)
        company_db._engine = eng
        company_db._session_factory = Session
        company_db._company_id = 96
        company_db._db_path = self.db_path
        oturum.set_user(user_id=1, kullanici_adi="k1", ad_soyad="Kullanıcı 1", role_kod="YONETICI",
                        role_ad="YONETICI", permissions=set())
        oturum.set_company(company_id=96, firma_kodu="AZT", firma_unvan="Alış Zinciri Test", firma_uid="azt",
                           db_path=str(self.db_path))
        with get_session() as s:
            d = s.scalar(select(Donem).limit(1))
            oturum.set_period(d.id, d.donem_adi)
            self.t1 = s.scalar(select(Cari.id).where(Cari.cari_kodu == "T001"))
            self.t2 = s.scalar(select(Cari.id).where(Cari.cari_kodu == "T002"))
        self._muhasebe_patch = patch("database.muhasebe_entegrasyon.muhasebe_hook", lambda *_a, **_k: None)
        self._muhasebe_patch.start()

    def tearDown(self):
        self._muhasebe_patch.stop()
        try:
            company_db.close()
        except Exception:
            pass
        if company_db._engine is not None:
            company_db._engine.dispose()
        company_db._engine = None
        company_db._session_factory = None
        oturum.clear()
        self._tmpdir.cleanup()

    # --- yardımcılar ---
    def _siparis(self, cari_id=None, satirlar=None):
        from database.alis_siparisi_service import AlisSiparisiService

        s = AlisSiparisiService.kaydet(
            {"siparis_tarihi": BUGUN, "termin_tarihi": BUGUN + timedelta(days=7), "cari_id": cari_id or self.t1},
            satirlar or [
                {"urun_kodu": "U001", "urun_adi": "Vida", "miktar": "100", "birim": "Adet",
                 "birim_alis_fiyati": "2", "kdv_orani": "20"},
                {"urun_kodu": "U002", "urun_adi": "Somun", "miktar": "50", "birim": "Adet",
                 "birim_alis_fiyati": "1", "kdv_orani": "20"},
            ],
            [],
        )
        return AlisSiparisiService.getir(s.id)

    def _irsaliye(self, siparis, miktarlar, irsaliye_id=None):
        from database.alis_irsaliyesi_service import AlisIrsaliyesiService

        satirlar = [
            {"siparis_satiri_id": s.id, "urun_kodu": s.urun_kodu, "urun_adi": s.urun_adi,
             "miktar": str(m), "birim": s.birim, "birim_fiyat": str(s.birim_alis_fiyati), "kdv_orani": "20"}
            for s, m in zip(siparis.satirlar, miktarlar) if m
        ]
        i = AlisIrsaliyesiService.kaydet(
            {"irsaliye_tarihi": BUGUN, "cari_id": siparis.cari_id, "siparis_id": siparis.id},
            satirlar, irsaliye_id,
        )
        return AlisIrsaliyesiService.getir(i.id)

    def _fatura(self, satirlar, *, cari_id=None, siparis_id=None, irsaliye_id=None, ted_no=None,
                fatura_id=None, row_version=None):
        from database.alis_faturasi_service import AlisFaturasiService

        return AlisFaturasiService.kaydet(
            {"fatura_tarihi": BUGUN, "vade_tarihi": BUGUN + timedelta(days=30), "cari_id": cari_id or self.t1,
             "siparis_id": siparis_id, "irsaliye_id": irsaliye_id, "depo": "ANA DEPO",
             "tedarikci_fatura_no": ted_no, "row_version": row_version},
            satirlar, fatura_id,
        )

    @staticmethod
    def _fatura_satiri(kaynak, miktar, *, irsaliye=False):
        veri = {"urun_kodu": kaynak.urun_kodu, "urun_adi": kaynak.urun_adi, "miktar": str(miktar),
                "birim": kaynak.birim, "birim_fiyat": str(getattr(kaynak, "birim_fiyat", None)
                                                          or getattr(kaynak, "birim_alis_fiyati")),
                "kdv_orani": "20"}
        veri["irsaliye_satiri_id" if irsaliye else "siparis_satiri_id"] = kaynak.id
        return veri

    @staticmethod
    def _stok(kod):
        with get_session() as s:
            sid = s.scalar(select(StokKarti.id).where(StokKarti.stok_kodu == kod))
            lot = s.scalar(select(func.coalesce(func.sum(StokLotu.kalan_miktar), 0)).where(StokLotu.stok_id == sid))
            hareket = s.scalar(select(func.count()).select_from(StokHareketi).where(StokHareketi.stok_id == sid))
            return Decimal(str(lot)), int(hareket)

    @staticmethod
    def _bakiye(cari_id):
        from database.cari_service import CariService

        return Decimal(str(CariService.musteri_bakiyeleri_toplu([cari_id]).get(cari_id, 0)))

    @staticmethod
    def _siparis_satirlari(siparis_id):
        from database.alis_siparisi_service import AlisSiparisiService

        s = AlisSiparisiService.getir(siparis_id)
        return s, {x.urun_kodu: x for x in s.satirlar}

    # --- testler ---
    def test_siparis_irsaliye_tam_kismi_ve_azaltma(self):
        from database.alis_irsaliyesi_service import AlisIrsaliyesiService

        sip = self._siparis()
        irs1 = self._irsaliye(sip, [40, 50])
        sip, sat = self._siparis_satirlari(sip.id)
        self.assertEqual((sat["U001"].irsaliyelenen_miktar, sat["U002"].irsaliyelenen_miktar),
                         (Decimal("40"), Decimal("50")))
        self.assertEqual(sip.durum, "KISMİ İRSALİYELİ")
        with self.assertRaises(ValueError):
            self._irsaliye(sip, [61, 0])
        # Satır azaltma kaynağa geri yazar
        self._irsaliye(sip, [30, 50], irsaliye_id=irs1.id)
        sip, sat = self._siparis_satirlari(sip.id)
        self.assertEqual(sat["U001"].irsaliyelenen_miktar, Decimal("30"))
        # Satır silme (U002 çıkarıldı) kaynağa geri yazar
        self._irsaliye(sip, [30, 0], irsaliye_id=irs1.id)
        sip, sat = self._siparis_satirlari(sip.id)
        self.assertEqual(sat["U002"].irsaliyelenen_miktar, Decimal("0"))
        # Kalan miktar tam irsaliye
        self._irsaliye(sip, [70, 50])
        sip, sat = self._siparis_satirlari(sip.id)
        self.assertEqual(sip.durum, "İRSALİYELİ")
        self.assertEqual(AlisIrsaliyesiService.siparis_satirlari(sip.id), [])
        # İrsaliye iptali miktarı siparişe iade eder; irsaliye stok hareketi üretmez
        AlisIrsaliyesiService.iptal_et(irs1.id)
        sip, sat = self._siparis_satirlari(sip.id)
        self.assertEqual(sat["U001"].irsaliyelenen_miktar, Decimal("70"))
        self.assertEqual(self._stok("U001"), (Decimal("0"), 0))

    def test_irsaliye_fatura_kismi_ikinci_aktarim_tek_stok_girisi(self):
        from database.alis_faturasi_service import AlisFaturasiService
        from database.alis_irsaliyesi_service import AlisIrsaliyesiService

        sip = self._siparis()
        irs = self._irsaliye(sip, [100, 50])
        i1, i2 = irs.satirlar
        onceki_bakiye = self._bakiye(self.t1)
        f1 = self._fatura([self._fatura_satiri(i1, 60, irsaliye=True)], irsaliye_id=irs.id, ted_no="TF-1")
        irs = AlisIrsaliyesiService.getir(irs.id)
        self.assertEqual(irs.durum, "KISMİ FATURALANDI")
        kalanlar = {s.urun_kodu: s.miktar - s.faturalanan_miktar for s in irs.satirlar}
        self.assertEqual(kalanlar, {"U001": Decimal("40"), "U002": Decimal("50")})
        with self.assertRaises(ValueError):
            self._fatura([self._fatura_satiri(i1, 41, irsaliye=True)], irsaliye_id=irs.id)
        f2 = self._fatura(
            [self._fatura_satiri(i1, 40, irsaliye=True), self._fatura_satiri(i2, 50, irsaliye=True)],
            irsaliye_id=irs.id, ted_no="TF-2",
        )
        irs = AlisIrsaliyesiService.getir(irs.id)
        self.assertEqual(irs.durum, "FATURALANDI")
        self.assertEqual(self._stok("U001"), (Decimal("100"), 2))
        self.assertEqual(self._stok("U002"), (Decimal("50"), 1))
        sip, sat = self._siparis_satirlari(sip.id)
        self.assertEqual(sip.durum, "FATURALI")
        self.assertEqual(sat["U001"].faturalanan_miktar, Decimal("100"))
        # Tedarikçi borcu alışla artar: 60*2*1.2 + (40*2 + 50*1)*1.2 = 144 + 156
        self.assertEqual(self._bakiye(self.t1) - onceki_bakiye, Decimal("300.00"))
        # Faturalanmış irsaliye düzenlenemez / iptal edilemez
        with self.assertRaises(ValueError):
            AlisIrsaliyesiService.iptal_et(irs.id)
        with self.assertRaises(ValueError):
            self._irsaliye(sip, [10, 0], irsaliye_id=irs.id)
        # Faturayı iptal etmek irsaliyeyi silmez; kalan miktar irsaliyeye döner, stok geri alınır
        AlisFaturasiService.iptal_et(f1.id)
        irs = AlisIrsaliyesiService.getir(irs.id)
        self.assertIsNotNone(irs)
        self.assertEqual(irs.durum, "KISMİ FATURALANDI")
        self.assertEqual({s.urun_kodu: s.miktar - s.faturalanan_miktar for s in irs.satirlar},
                         {"U001": Decimal("60"), "U002": Decimal("0")})
        self.assertEqual(self._stok("U001")[0], Decimal("40"))
        self.assertEqual(self._bakiye(self.t1) - onceki_bakiye, Decimal("156.00"))
        self.assertTrue(f2.id)

    def test_dogrudan_siparisten_fatura_ve_satir_silme(self):
        sip = self._siparis()
        s1, s2 = sip.satirlar
        f = self._fatura(
            [self._fatura_satiri(s1, 30), self._fatura_satiri(s2, 50)], siparis_id=sip.id, ted_no="D-1"
        )
        sip, sat = self._siparis_satirlari(sip.id)
        self.assertEqual(sip.durum, "KISMİ FATURALI")
        self.assertEqual((sat["U001"].faturalanan_miktar, sat["U002"].faturalanan_miktar),
                         (Decimal("30"), Decimal("50")))
        # Düzenlemede satır silme + azaltma kaynağa geri yazar; stok ikiye katlanmaz
        self._fatura([self._fatura_satiri(s1, 20)], siparis_id=sip.id, ted_no="D-1",
                     fatura_id=f.id, row_version=f.row_version)
        sip, sat = self._siparis_satirlari(sip.id)
        self.assertEqual((sat["U001"].faturalanan_miktar, sat["U002"].faturalanan_miktar),
                         (Decimal("20"), Decimal("0")))
        self.assertEqual(self._stok("U001"), (Decimal("20"), 1))
        self.assertEqual(self._stok("U002")[0], Decimal("0"))
        with self.assertRaises(ValueError):
            self._fatura([self._fatura_satiri(s1, 81)], siparis_id=sip.id)

    def test_cift_kayit_tekrar_stok_ve_cari_uretmez(self):
        from database.alis_faturasi_service import AlisFaturasiService
        from database.models.cari import SatisHareketi

        sip = self._siparis()
        s1 = sip.satirlar[0]
        f = self._fatura([self._fatura_satiri(s1, 10)], siparis_id=sip.id)
        bakiye = self._bakiye(self.t1)
        for _ in range(2):
            f = self._fatura([self._fatura_satiri(s1, 10)], siparis_id=sip.id,
                             fatura_id=f.id, row_version=f.row_version)
        self.assertEqual(self._stok("U001"), (Decimal("10"), 1))
        self.assertEqual(self._bakiye(self.t1), bakiye)
        with get_session() as s:
            adet = s.scalar(select(func.count()).select_from(SatisHareketi)
                            .where(SatisHareketi.belge_no == f.fatura_no))
        self.assertEqual(adet, 1)
        # Eski sürümle kayıt (bayat ekran) reddedilir
        with self.assertRaises(ValueError):
            self._fatura([self._fatura_satiri(s1, 10)], siparis_id=sip.id, fatura_id=f.id, row_version=1)
        # İptal edilmiş fatura düzenlenemez
        AlisFaturasiService.iptal_et(f.id)
        with self.assertRaises(ValueError):
            self._fatura([self._fatura_satiri(s1, 5)], siparis_id=sip.id, fatura_id=f.id)

    def test_hatali_satir_tum_islemi_geri_alir(self):
        sip = self._siparis()
        s1, s2 = sip.satirlar
        with self.assertRaises(ValueError):
            self._fatura([self._fatura_satiri(s1, 10), self._fatura_satiri(s2, 999)], siparis_id=sip.id)
        sip, sat = self._siparis_satirlari(sip.id)
        self.assertEqual(sat["U001"].faturalanan_miktar, Decimal("0"))
        self.assertEqual(self._stok("U001"), (Decimal("0"), 0))
        self.assertEqual(self._bakiye(self.t1), Decimal("0"))

    def test_tedarikci_fatura_no_mukerrer_kontrolu(self):
        from database.alis_faturasi_service import AlisFaturasiService, MukerrerTedarikciFaturaHatasi

        satir = {"urun_kodu": "U001", "urun_adi": "Vida", "miktar": "1", "birim": "Adet",
                 "birim_fiyat": "5", "kdv_orani": "20"}
        f1 = self._fatura([satir], ted_no="ABC-100")
        self.assertEqual(AlisFaturasiService.getir(f1.id).tedarikci_fatura_no, "ABC-100")
        self.assertNotEqual(f1.fatura_no, "ABC-100")
        with self.assertRaises(MukerrerTedarikciFaturaHatasi) as ctx:
            self._fatura([satir], ted_no="abc-100")
        self.assertEqual(ctx.exception.fatura_id, f1.id)
        self.assertEqual(AlisFaturasiService.mukerrer_kontrol(self.t1, "ABC-100"), (f1.id, f1.fatura_no))
        self.assertIsNone(AlisFaturasiService.mukerrer_kontrol(self.t1, "ABC-100", haric_id=f1.id))
        # Başka tedarikçide aynı numara serbest; kendi kaydını yeniden kaydetmek serbest
        self._fatura([satir], cari_id=self.t2, ted_no="ABC-100")
        self._fatura([satir], ted_no="ABC-100", fatura_id=f1.id, row_version=f1.row_version)
        # İptal edilen faturanın numarası yeniden kullanılabilir
        AlisFaturasiService.iptal_et(f1.id)
        self._fatura([satir], ted_no="ABC-100")

    def test_tedarikci_bakiye_odeme_ve_odeme_sozu(self):
        from database.cari_service import CariService
        from database.odeme_sozu_service import VERILEN, OdemeSozuService

        satir = {"urun_kodu": "U001", "urun_adi": "Vida", "miktar": "10", "birim": "Adet",
                 "birim_fiyat": "10", "kdv_orani": "20"}
        f = self._fatura([satir], ted_no="B-1")
        self.assertEqual(self._bakiye(self.t1), Decimal("120.00"))
        OdemeSozuService.olustur(
            {"cari_id": self.t1, "yon": VERILEN, "soz_tarihi": BUGUN, "vade_tarihi": BUGUN + timedelta(days=3),
             "tutar": "50", "yontem": "Havale/EFT"},
            [(f.fatura_no, "50")],
        )
        self.assertEqual(self._bakiye(self.t1), Decimal("120.00"))
        CariService.odeme_yap(self.t1, BUGUN, "50", "Havale", "BANKA")
        self.assertEqual(self._bakiye(self.t1), Decimal("70.00"))

    def test_tedarikci_evraklari_ve_silme_korumasi(self):
        from database.alis_faturasi_service import AlisFaturasiService
        from database.deleted_record_service import ENTITY_CARI, AuditDeleteService, SoftDeleteError

        sip = self._siparis()
        irs = self._irsaliye(sip, [10, 0])
        self._fatura([self._fatura_satiri(irs.satirlar[0], 4, irsaliye=True)], irsaliye_id=irs.id, ted_no="E-1")
        evrak = AlisFaturasiService.tedarikci_evraklari(self.t1)
        self.assertEqual([i["no"] for i in evrak["irsaliye"]], [irs.irsaliye_no])
        self.assertEqual(evrak["irsaliye"][0]["kalan"], Decimal("6"))
        self.assertEqual(evrak["fatura"][0]["ted_no"], "E-1")
        self.assertEqual(evrak["fatura"][0]["irsaliye"], irs.irsaliye_no)
        self.assertEqual([s["no"] for s in evrak["siparis"]], [sip.siparis_no])
        self.assertEqual(AlisFaturasiService.tedarikci_evraklari(self.t2),
                         {"siparis": [], "talep": [], "irsaliye": [], "fatura": [], "iade": []})
        with get_session() as s:
            cari = s.get(Cari, self.t1)
            with self.assertRaises(SoftDeleteError):
                AuditDeleteService.validate_delete(ENTITY_CARI, cari, s)
            AuditDeleteService.validate_delete(ENTITY_CARI, s.get(Cari, self.t2), s)

    def test_fatura_ekrani_kayittan_sonra_acik_kalir(self):
        import tkinter as tk

        from alis_ui import ALIS_BELGE_BASLIGI, AlisFaturasiDialog

        import faulthandler
        faulthandler.dump_traceback_later(60, exit=True)
        self.addCleanup(faulthandler.cancel_dump_traceback_later)
        root = tk.Tk()
        root.withdraw()
        try:
            with get_session() as s:
                cari = s.get(Cari, self.t1)
            dlg = AlisFaturasiDialog(root, cari=cari)
            dlg.withdraw()
            self.assertTrue(dlg.title().startswith(ALIS_BELGE_BASLIGI))
            dlg.satirlar.append({"urun_kodu": "U001", "urun_adi": "Vida", "miktar": Decimal("5"),
                                 "birim": "Adet", "birim_fiyat": Decimal("2"), "birim_alis_fiyati": Decimal("2"),
                                 "iskonto_orani": 0, "kdv_orani": Decimal("20"), "barkod": "", "aciklama": ""})
            dlg._satir_listesini_yenile()
            dlg.girdiler["tedarikci_fatura_no"].insert(0, "UI-1")
            self.assertTrue(dlg._fatura_kirli_mi())
            with patch("alis_ui.messagebox.showerror") as hata:
                self.assertTrue(dlg.kaydet())
                hata.assert_not_called()
            self.assertTrue(dlg.winfo_exists())
            self.assertEqual(dlg.fatura.tedarikci_fatura_no, "UI-1")
            self.assertEqual(dlg.girdiler["fatura_no"].get(), dlg.fatura.fatura_no)
            self.assertIn(dlg.fatura.fatura_no, dlg.title())
            self.assertFalse(dlg._fatura_kirli_mi())
            self.assertEqual(dlg._cari_ozet_etiketleri["fatura"].cget("text"), "12,00 TL")
            with patch("alis_ui.messagebox.showerror") as hata:
                self.assertTrue(dlg.kaydet(), hata.call_args)
            with get_session() as s:
                self.assertEqual(s.scalar(select(func.count(StokHareketi.id))), 1)

            from invoice_print.builder import build_from_kart
            from invoice_print.html_renderer import render_invoice_html

            vm = build_from_kart(dlg)
            self.assertEqual(vm.belge_turu, "ALIŞ FATURASI")
            self.assertTrue(vm.ters_renk)
            self.assertEqual(vm.tedarikci_fatura_no, "UI-1")
            self.assertEqual(vm.musteri["unvan"], "Tedarikçi A")
            html = render_invoice_html(vm, toolbar=False, zoom_pct=100)
            for parca in ("ALIŞ FATURASI", "Tedarikçi", "UI-1", "Kayıt No", dlg.fatura.fatura_no, "Vida"):
                self.assertIn(parca, html)
            self.assertNotIn("Sayın", html)
            self.assertNotIn("Tahsil Edilen", html)
            dlg.destroy()
        finally:
            root.destroy()


if __name__ == "__main__":
    unittest.main()
