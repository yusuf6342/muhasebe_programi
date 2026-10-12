"""Stok kartı: ada göre arama/açma, Kaydet (mükerrer yok), kaydedilmemiş değişiklik,
yeni kartta Adet varsayılanı ve Yeni Birim (+).

Çalıştırma: .venv\\Scripts\\python.exe -m pytest tests/test_stok_karti_birim_arama.py -q
"""

from __future__ import annotations

import sys
import tempfile
import tkinter as tk
import unittest
from datetime import date
from decimal import Decimal as D
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from sqlalchemy import create_engine, event, func, select, text
from sqlalchemy.orm import sessionmaker

from database.database import Base, _aktif_engine_bagla, company_db, get_session
from database.models.donem import Donem
from database.models.firma import Firma
from database.models.stok import Depo, StokBirimKisaKod, StokKarti, StokSecenek
from database.session_manager import oturum
from database.stok_service import BirimZatenVar, StokService


def _sqlite_pragma(dbapi_connection, _connection_record):
    cur = dbapi_connection.cursor()
    cur.execute("PRAGMA foreign_keys=ON")
    cur.close()


class _TemelDB(unittest.TestCase):
    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self.db_path = Path(self._tmpdir.name) / "stok_kart.db"
        eng = create_engine(f"sqlite:///{self.db_path.as_posix()}", connect_args={"check_same_thread": False})
        event.listen(eng, "connect", _sqlite_pragma)
        import database.models.alis_faturasi  # noqa: F401
        import database.models.alis_iade_faturasi  # noqa: F401
        import database.models.alis_irsaliyesi  # noqa: F401
        import database.models.alis_masraf  # noqa: F401
        import database.models.alis_siparisi  # noqa: F401
        import database.models.cari  # noqa: F401
        import database.models.finans  # noqa: F401
        import database.models.hizli_satis  # noqa: F401
        import database.models.satis_faturasi  # noqa: F401
        import database.models.satis_iade_faturasi  # noqa: F401
        import database.models.satis_irsaliyesi  # noqa: F401
        import database.models.satis_siparisi  # noqa: F401
        import database.models.stok_sayim  # noqa: F401

        Base.metadata.create_all(eng)
        Session = sessionmaker(bind=eng, autoflush=False, autocommit=False, expire_on_commit=False)
        with Session() as s:
            firma = Firma(firma_kodu="SK", unvan="Stok Kart Test", aktif=True)
            s.add(firma)
            s.flush()
            s.add(Donem(firma_id=firma.id, donem_adi="2026", baslangic_tarihi=date(2026, 1, 1),
                        bitis_tarihi=date(2026, 12, 31), aktif=True, kapali=False, varsayilan=True))
            s.commit()
        _aktif_engine_bagla(eng)
        company_db._engine = eng
        company_db._session_factory = sessionmaker(bind=eng, autoflush=False, autocommit=False,
                                                   expire_on_commit=False)
        company_db._company_id = 56
        company_db._db_path = self.db_path
        oturum.clear()
        oturum.set_user(user_id=1, kullanici_adi="admin", ad_soyad="Admin", role_kod="YONETICI",
                        role_ad="Yönetici", permissions=set())
        oturum.set_company(company_id=56, firma_kodu="SK", firma_unvan="Stok Kart Test", firma_uid="sk",
                           db_path=str(self.db_path))
        with get_session() as s:
            d = s.scalar(select(Donem).limit(1))
            oturum.set_period(d.id, d.donem_adi)
            s.add(Depo(kod="ANA", ad="ANA DEPO", aktif=True, varsayilan=True))
            st = StokKarti(stok_kodu="OZ1", stok_adi="Özet Ürün", birim="Adet", aktif=True)
            s.add(st)
            s.flush()
            self.stok_id = int(st.id)
        self._audit = patch("database.user_audit.audit_document", return_value=None)
        self._audit.start()

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

    @staticmethod
    def _stok_sayisi(kod):
        with get_session() as s:
            return s.scalar(select(func.count()).select_from(StokKarti).where(StokKarti.stok_kodu == kod))


class BirimTanimiServisTest(_TemelDB):
    def test_yeni_birim_listeye_eklenir_kisa_kod_saklanir(self):
        ad = StokService.birim_tanimi_ekle("  Bidon  ", "BD", ("Adet", "Koli"))
        self.assertEqual(ad, "Bidon")
        liste = StokService.birim_listesi(("Koli",))
        self.assertEqual(liste[0], "Adet")
        self.assertIn("Bidon", liste)
        self.assertEqual(StokService.birim_kisa_kodlari().get("bidon"), "BD")

    def test_harf_ve_bosluk_farkli_tekrar_reddedilir(self):
        StokService.birim_tanimi_ekle("Çuval", None, ())
        for aday in ("ÇUVAL", " çuval ", "Çuval"):
            with self.subTest(aday=aday), self.assertRaises(BirimZatenVar) as ctx:
                StokService.birim_tanimi_ekle(aday, None, ())
            self.assertEqual(ctx.exception.mevcut_ad, "Çuval")
        with self.assertRaises(BirimZatenVar):
            StokService.birim_tanimi_ekle("koli", None, ("Koli",))
        with get_session() as s:
            self.assertEqual(
                s.scalar(select(func.count()).select_from(StokSecenek).where(StokSecenek.tur == "birim")), 1
            )

    def test_kisa_kod_tekrari_reddedilir(self):
        StokService.birim_tanimi_ekle("Bidon", "BD", ())
        with self.assertRaises(ValueError):
            StokService.birim_tanimi_ekle("Damacana", "bd", ())
        self.assertNotIn("Damacana", StokService.birim_listesi())

    def test_eski_veritabaninda_kisa_kod_tablosu_ilk_kullanimda_acilir(self):
        with get_session() as s:
            s.execute(text("DROP TABLE stok_birim_kisa_kodlari"))
        self.assertEqual(StokService.birim_kisa_kodlari(), {})
        StokService.birim_tanimi_ekle("Bidon", "BD", ())
        with get_session() as s:
            self.assertEqual(s.scalar(select(StokBirimKisaKod.kisa_kod)), "BD")

    def test_varsayilanlar_adet_bir_kez_olusur(self):
        StokService.varsayilanlari_hazirla()
        StokService.varsayilanlari_hazirla()
        with get_session() as s:
            adlar = list(s.scalars(select(StokSecenek.ad).where(StokSecenek.tur == "birim")))
        self.assertEqual(adlar, ["Adet"])


class EvrakBirimSecimiTest(_TemelDB):
    """Evrak satırında kartta tanımsız birim: katsayı sorulur, karta eklenir, tahmin edilmez."""

    def setUp(self):
        super().setUp()
        self._yetki = patch("database.access.yazma_zorunlu")
        self._yetki.start()

    def tearDown(self):
        self._yetki.stop()
        super().tearDown()

    @staticmethod
    def _carpan(birim):
        from fatura_satir_birim_service import _stok_yukle

        return StokService.birim_carpani_bul(_stok_yukle("OZ1"), birim)

    def test_secenekler_kart_birimiyle_baslar_genel_birimleri_icerir(self):
        from birim_secim_ui import evrak_birim_secenekleri

        secenekler = evrak_birim_secenekleri("OZ1")
        self.assertEqual(secenekler[0], "Adet")
        self.assertIn("Koli", secenekler)
        self.assertEqual(len(secenekler), len({s.casefold() for s in secenekler}))

    def test_kart_birimi_ekle_yeni_ve_pasif_kaydi_etkinlestirir(self):
        StokService.kart_birimi_ekle("OZ1", "Koli", "12")
        self.assertEqual(self._carpan("Koli"), D("12"))
        with get_session() as s:
            from database.models.stok import StokBirim

            b = s.scalar(select(StokBirim).where(StokBirim.birim_adi == "Koli"))
            b.aktif = False
        self.assertIsNone(self._carpan("Koli"))
        StokService.kart_birimi_ekle("OZ1", "koli", "6")
        self.assertEqual(self._carpan("Koli"), D("6"))
        with get_session() as s:
            from database.models.stok import StokBirim

            self.assertEqual(s.scalar(select(func.count()).select_from(StokBirim)), 1)
        with self.assertRaises(ValueError):
            StokService.kart_birimi_ekle("OZ1", "Paket", "0")

    def test_hazirla_gecersiz_katsayida_tekrar_sorar_vazgecince_eklemez(self):
        from birim_secim_ui import kart_birimini_hazirla

        with patch("birim_secim_ui.simpledialog.askstring", side_effect=["abc", "2,5"]) as sor, patch(
            "birim_secim_ui.messagebox"
        ) as mb:
            self.assertTrue(kart_birimini_hazirla(None, "OZ1", "Paket"))
        self.assertEqual(sor.call_count, 2)
        mb.showwarning.assert_called_once()
        self.assertEqual(self._carpan("Paket"), D("2.5"))
        with patch("birim_secim_ui.simpledialog.askstring", return_value=None):
            self.assertFalse(kart_birimini_hazirla(None, "OZ1", "Torba"))
        self.assertIsNone(self._carpan("Torba"))

    def test_tanimli_birim_ve_kartsiz_satir_sorulmaz(self):
        from birim_secim_ui import kart_birimini_hazirla

        with patch("birim_secim_ui.simpledialog.askstring") as sor:
            self.assertTrue(kart_birimini_hazirla(None, "OZ1", "adet"))
            self.assertTrue(kart_birimini_hazirla(None, "", "Koli"))
            self.assertTrue(kart_birimini_hazirla(None, "KARTSIZ", "Koli"))
        sor.assert_not_called()


class YeniKartMukerrerKoruma(_TemelDB):
    def test_yeni_kart_mevcut_kodun_uzerine_yazmaz(self):
        with self.assertRaises(ValueError) as ctx:
            StokService.stok_kaydi(
                {"stok_kodu": "OZ1", "stok_adi": "Başka Ürün", "birim": "Adet", "yalniz_yeni": True}, []
            )
        self.assertIn("Özet Ürün", str(ctx.exception))
        self.assertEqual(StokService.stok_getir(self.stok_id).stok_adi, "Özet Ürün")


class _EkranTemel(_TemelDB):
    def setUp(self):
        super().setUp()
        self.root = tk.Tk()
        self.root.withdraw()
        self._boyut = patch("stok_ui.StokKartiDialog._pencere_boyutunu_ayarla", lambda self: None)
        self._boyut.start()
        self._boyut_kaydet = patch("stok_ui.StokKartiDialog._pencere_boyut_kaydet", lambda self: None)
        self._boyut_kaydet.start()
        self.mb = patch("stok_ui.messagebox").start()
        self.mb.askyesno.return_value = True

    def tearDown(self):
        patch.stopall()
        try:
            self.root.destroy()
        except tk.TclError:
            pass
        super().tearDown()

    def _kartlar(self):
        from stok_ui import StokKartiDialog

        return [w for w in self.root.winfo_children() if isinstance(w, StokKartiDialog) and w.winfo_exists()]

    def _yeni(self, **kw):
        from stok_ui import StokKartiDialog

        dlg = StokKartiDialog(self.root, **kw)
        self.root.update_idletasks()
        return dlg

    @staticmethod
    def _gorunur(dlg):
        # Pencereyi gösteren boyut ayarı testte yamalı ve gizli ana pencereye bağlı kart çizilmez;
        # açılır liste yalnız görünür kutuda açılır.
        dlg.master.geometry("+-3000+-3000")
        dlg.master.deiconify()
        dlg.geometry("1400x900+-3000+-3000")
        dlg.deiconify()
        dlg.update()
        return dlg


class StokKartiEkranTest(_EkranTemel):
    def test_yeni_kart_adet_varsayilan_ve_degisiklik_yokken_sormadan_kapanir(self):
        dlg = self._yeni()
        self.assertEqual(dlg.alanlar["birim"].get(), "Adet")
        self.assertEqual([b["birim_adi"] for b in dlg.birimler], ["Adet"])
        degerler = list(dlg.alanlar["birim"].cget("values"))
        self.assertIn("Koli", degerler)
        self.assertEqual(degerler[0], "Adet")
        dlg._kapat_istegi()
        self.mb.askyesnocancel.assert_not_called()
        self.assertFalse(self._kartlar())

    def test_kaydedilmemis_degisiklikte_sorar_iptalde_kartta_kalir(self):
        dlg = self._yeni()
        dlg.alanlar["stok_adi"].set("Yazılan Ad")
        self.mb.askyesnocancel.return_value = None
        dlg._kapat_istegi()
        self.mb.askyesnocancel.assert_called_once()
        self.assertTrue(dlg.winfo_exists())

    def test_kaydet_yeni_olusturur_tekrar_tik_mukerrer_acmaz(self):
        dlg = self._yeni()
        dlg.alanlar["stok_kodu"].set("YK1")
        dlg.alanlar["stok_adi"].set("Yeni Kart Ürünü")
        self.assertTrue(dlg.kaydet())
        self.assertIn("oluşturuldu", self.mb.showinfo.call_args.args[1])
        self.assertTrue(dlg.kaydet())
        self.assertIn("güncellendi", self.mb.showinfo.call_args.args[1])
        self.assertEqual(self._stok_sayisi("YK1"), 1)
        dlg._kaydediliyor = True
        self.assertFalse(dlg.kaydet())
        dlg._kaydediliyor = False
        dlg._kapat_istegi()
        self.mb.askyesnocancel.assert_not_called()

    def test_yeni_kart_mevcut_kodla_kaydedilmez(self):
        dlg = self._yeni()
        dlg.alanlar["stok_kodu"].set("OZ1")
        dlg.alanlar["stok_adi"].set("Üzerine Yazma Denemesi")
        self.assertFalse(dlg.kaydet())
        self.mb.showerror.assert_called()
        self.assertEqual(StokService.stok_getir(self.stok_id).stok_adi, "Özet Ürün")

    def test_zorunlu_alan_eksik_mesaji(self):
        dlg = self._yeni()
        dlg.alanlar["stok_kodu"].set("YK2")
        self.assertFalse(dlg.kaydet())
        self.assertIn("Stok Adı", self.mb.showwarning.call_args.args[1])
        self.assertEqual(self._stok_sayisi("YK2"), 0)

    def test_ada_gore_arama_secilen_kaydi_kendi_kartinda_acar(self):
        dlg = self._yeni()
        dlg.alanlar["stok_adi"].set("öz")
        dlg._stok_adi_ara_calistir()
        etiket = "OZ1 — Özet Ürün"
        self.assertIn(etiket, dlg.alanlar["stok_adi"].cget("values"))
        dlg.alanlar["stok_adi"].set(etiket)
        self.mb.askyesnocancel.return_value = False
        dlg._stok_adi_secildi()
        self.assertFalse(dlg.winfo_exists())
        kartlar = self._kartlar()
        self.assertEqual(len(kartlar), 1)
        self.assertEqual(kartlar[0].stok.id, self.stok_id)
        self.assertEqual(kartlar[0].alanlar["stok_adi"].get(), "Özet Ürün")
        self.assertEqual(kartlar[0].alanlar["stok_kodu"].get(), "OZ1")

    def test_secilmeyen_yazilan_ad_yeni_kart_adi_olarak_kalir(self):
        dlg = self._yeni()
        dlg.alanlar["stok_adi"].set("Öz Yeni Ürün")
        dlg._stok_adi_ara_calistir()
        dlg._stok_adi_secildi()
        self.assertTrue(dlg.winfo_exists())
        self.assertEqual(dlg.alanlar["stok_adi"].get(), "Öz Yeni Ürün")
        self.assertIsNone(dlg.stok)

    def test_ad_kutusunda_yazinca_stok_listesi_acilir_secilen_kart_acilir(self):
        with get_session() as s:
            s.add(StokKarti(stok_kodu="MS1", stok_adi="Masa Kırmızı Büyük", birim="Adet", aktif=True))
        dlg = self._gorunur(self._yeni())
        arama = dlg._stok_ad_arama
        dlg.alanlar["stok_adi"].set("kırmızı masa")
        arama.ara(senkron=True)
        self.assertTrue(arama.acik_mi(), "Stok adı yazılınca liste açılmadı")
        self.assertEqual([k.stok_kodu for k in arama.sonuclar], ["MS1"])
        self.assertEqual(arama.tree.item("0", "values")[1], "Masa Kırmızı Büyük")
        # Yeni ürün adı yazarken Enter mevcut kartı açmaz; seçim ↓ ile yapılır
        self.assertEqual(arama.secili, -1)
        self.assertIsNone(arama._enter())
        self.assertTrue(dlg.winfo_exists())
        arama._asagi()
        self.assertEqual(arama._enter(), "break")
        self.assertFalse(dlg.winfo_exists())
        self.mb.askyesnocancel.assert_not_called()
        kartlar = self._kartlar()
        self.assertEqual(len(kartlar), 1)
        self.assertEqual(kartlar[0].alanlar["stok_adi"].get(), "Masa Kırmızı Büyük")
        self.assertEqual(kartlar[0].alanlar["stok_kodu"].get(), "MS1")

    def test_ad_listesi_bulunamadi_mesaji_ve_mevcut_kartta_ad_degismeden_acilmaz(self):
        dlg = self._gorunur(self._yeni())
        dlg.alanlar["stok_adi"].set("zzz yok")
        dlg._stok_ad_arama.ara(senkron=True)
        self.assertTrue(dlg._stok_ad_arama.acik_mi())
        self.assertIn("bulunamadı", dlg._stok_ad_arama.durum.cget("text"))
        dlg._stok_ad_arama.kapat()
        mevcut = self._gorunur(self._yeni(stok=StokService.stok_getir(self.stok_id)))
        mevcut._stok_ad_arama._tus()
        self.assertFalse(mevcut._stok_ad_arama.acik_mi())

    def test_mevcut_kartta_yeni_butonu_bos_kart_acar_yeniden_adlandirmaz(self):
        dlg = self._yeni(stok=StokService.stok_getir(self.stok_id))
        dlg.stok_alan_yeni("stok_adi")
        self.assertFalse(dlg.winfo_exists())
        kartlar = self._kartlar()
        self.assertEqual(len(kartlar), 1)
        self.assertIsNone(kartlar[0].stok)
        self.assertEqual(kartlar[0].alanlar["stok_adi"].get(), "")
        self.assertEqual(StokService.stok_getir(self.stok_id).stok_adi, "Özet Ürün")

    def test_yeni_kartta_ana_birim_degisince_temel_kayit_degisir(self):
        dlg = self._yeni()
        dlg.alanlar["birim"].set("Kg")
        dlg._yeni_kart_ana_birimi_esitle()
        self.assertEqual([(b["birim_adi"], b["carpan"]) for b in dlg.birimler], [("Kg", "1")])
        self.assertEqual(dlg.varsayilan_satis_birim, "Kg")

    def test_mevcut_kart_kayitli_birimini_korur(self):
        with get_session() as s:
            s.get(StokKarti, self.stok_id).birim = "Paket"
        dlg = self._yeni(stok=StokService.stok_getir(self.stok_id))
        self.assertEqual(dlg.alanlar["birim"].get(), "Paket")
        self.assertNotIn("Koli", dlg.alanlar["birim"].cget("values"))

    def test_yeni_birim_dialog_katsayi_sormadan_alternatif_eklemez(self):
        from stok_ui import YeniBirimDialog

        kart = self._yeni()
        dlg = YeniBirimDialog(kart, ana_birim="Adet", ana_secilebilir=True)
        dlg.ad.insert(0, "Bidon")
        dlg.kullanim.set("alternatif")
        dlg._kullanim_degisti()
        dlg._tamam()
        self.assertIsNone(dlg.result)
        self.assertIn("Katsayı tahmin edilmez", self.mb.showwarning.call_args.args[1])
        self.assertNotIn("Bidon", StokService.birim_listesi())
        dlg.carpan.insert(0, "20")
        dlg._tamam()
        self.assertEqual(dlg.result, {"birim_adi": "Bidon", "kullanim": "alternatif", "carpan": "20"})
        self.assertIn("Bidon", StokService.birim_listesi())

    def test_yeni_birim_karta_eklenir_ve_secilir(self):
        kart = self._yeni()

        class _Sahte:
            def __init__(self, parent, **_kw):
                self.result = sahte_sonuc

        sahte_sonuc = {"birim_adi": "Bidon", "kullanim": "alternatif", "carpan": "20"}
        with patch("stok_ui.YeniBirimDialog", _Sahte), patch.object(kart, "wait_window", lambda _w: None):
            kart._yeni_birim_ekle()
        self.assertIn(("Bidon", "20"), [(b["birim_adi"], b["carpan"]) for b in kart.birimler])
        secili = kart.birim_tablo.selection()
        self.assertTrue(secili)
        self.assertEqual(kart.birim_tablo.item(secili[0], "values")[0], "Bidon")

        sahte_sonuc = {"birim_adi": "Litre", "kullanim": "ana", "carpan": None}
        with patch("stok_ui.YeniBirimDialog", _Sahte), patch.object(kart, "wait_window", lambda _w: None):
            kart._yeni_birim_ekle()
        self.assertEqual(kart.alanlar["birim"].get(), "Litre")
        self.assertEqual(kart.birimler[0]["birim_adi"], "Litre")


class EtiketKurallariTest(_EkranTemel):
    def test_etiket_barkod_durumu(self):
        from stok_barkod_ui import etiket_barkod_durumu

        self.assertIn("tanımlı değil", etiket_barkod_durumu(""))
        self.assertIn("karakter", etiket_barkod_durumu("ÇAY-01"))
        self.assertIn("kontrol basamağı", etiket_barkod_durumu("8690000000001"))
        self.assertIsNone(etiket_barkod_durumu("0000000000000"))
        self.assertIsNone(etiket_barkod_durumu("8690000000005"))
        self.assertIsNone(etiket_barkod_durumu("ABC-123"))

    def test_bastaki_sifirlar_korunur_ean13_kontrolu(self):
        from stok_barkod_ui import etiket_barkod_durumu

        self.assertIsNone(etiket_barkod_durumu("0012345678905"))
        self.assertIn("kontrol basamağı", etiket_barkod_durumu("0012345678900"))
        self.assertIn("tanımlı değil", etiket_barkod_durumu("   "))
        self.assertIn("karakter", etiket_barkod_durumu("ŞEKER1"))
        dlg = self._yeni(stok=StokService.stok_getir(self.stok_id))
        dlg.barkodlar = [{"barkod": "0012345678905", "birim": "Adet"}]
        dlg._etiket_durumu_guncelle()
        self.assertEqual(str(dlg.etiket_btn.cget("state")), "normal")
        gecerli, neden = dlg._etiket_kayitlari()
        self.assertIsNone(neden)
        self.assertEqual(gecerli[0]["barkod"], "0012345678905")

    def test_barkodsuz_kartta_dugme_kapali_ve_tiklamada_neden_soyler(self):
        dlg = self._yeni(stok=StokService.stok_getir(self.stok_id))
        dlg.barkodlar = []
        dlg._etiket_durumu_guncelle()
        self.assertEqual(str(dlg.etiket_btn.cget("state")), "disabled")
        self.assertIn("tanımlı değil", dlg.etiket_neden_lbl.cget("text"))
        with patch("stok_barkod_ui.EtiketYazdirDialog") as dialog:
            dlg._barkod_etiket_yazdir()
        dialog.assert_not_called()
        self.assertIn("tanımlı değil", self.mb.showwarning.call_args.args[1])

    def test_kartta_gecerli_barkod_yoksa_dugme_kapali_neden_yazar(self):
        dlg = self._yeni(stok=StokService.stok_getir(self.stok_id))
        dlg.barkodlar = [{"barkod": "8690000000001", "birim": "Adet"}]
        dlg._etiket_durumu_guncelle()
        self.assertEqual(str(dlg.etiket_btn.cget("state")), "disabled")
        self.assertIn("kontrol basamağı", dlg.etiket_neden_lbl.cget("text"))

        dlg.barkodlar = [{"barkod": "0000000000000", "birim": "Adet"}]
        dlg._etiket_durumu_guncelle()
        self.assertEqual(str(dlg.etiket_btn.cget("state")), "normal")
        self.assertEqual(dlg.etiket_neden_lbl.cget("text"), "")
        gecerli, _neden = dlg._etiket_kayitlari()
        self.assertEqual(gecerli[0]["barkod"], "0000000000000")

    def test_etiket_dialog_barkod_secimi_ve_adet(self):
        from stok_barkod_ui import EtiketYazdirDialog

        etiketler = [
            {"barkod": "0000000000000", "stok_kodu": "OZ1", "stok_adi": "Özet Ürün", "birim": "Adet", "fiyat": 5},
            {"barkod": "8690000000005", "stok_kodu": "OZ1", "stok_adi": "Özet Ürün", "birim": "Koli", "fiyat": 50},
        ]
        with patch("stok_barkod_ui.messagebox") as mb, \
                patch("stok_barkod_ui.etiket_dosyasi_ac", return_value=(None, 58, 40)) as ac:
            dlg = EtiketYazdirDialog(self.root, etiketler)
            self.assertEqual(len(dlg.barkod_cb.cget("values")), 2)
            self.assertTrue(dlg.onizleme.find_all())
            dlg.adet.set("0")
            dlg.yazdir()
            mb.showwarning.assert_called_once()
            ac.assert_not_called()
            dlg.barkod_cb.current(1)
            dlg.adet.set("3")
            dlg.yazdir()
        ac.assert_called_once_with([etiketler[1]], 3)
        self.assertTrue(dlg.yazdirildi)

    def test_etiket_dosyasi_tarayicida_acilir(self):
        from stok_barkod_ui import etiket_dosyasi_ac

        et = {"barkod": "0012345678905", "stok_kodu": "OZ1", "stok_adi": "Özet Ürün", "birim": "Adet", "fiyat": 5}
        with patch("stok_barkod_ui.webbrowser.open") as ac, \
                patch("stok_barkod_ui.etiket_ayarlarini_yukle", return_value={"genislik_mm": 50, "yukseklik_mm": 30}):
            dosya, en, boy = etiket_dosyasi_ac([et], 2)
        ac.assert_called_once()
        self.assertEqual((en, boy), (50.0, 30.0))
        self.assertIn("0012345678905", dosya.read_text(encoding="utf-8"))

    def test_tek_barkodda_secim_notu_yok(self):
        from stok_barkod_ui import EtiketYazdirDialog

        et = {"barkod": "0012345678905", "stok_kodu": "OZ1", "stok_adi": "Özet Ürün", "birim": "Adet", "fiyat": 5}
        with patch("stok_barkod_ui.messagebox"):
            dlg = EtiketYazdirDialog(self.root, [et])
            self.assertEqual(len(dlg.barkod_cb.cget("values")), 1)
            self.assertEqual(dlg.secili()["barkod"], "0012345678905")
            dlg.destroy()


class KartGrupVeHareketEkranTest(_EkranTemel):
    def test_grup_yeni_ekle_ust_secimi_ister_ve_ustune_bagli_acar(self):
        from database.stok_grup_service import SEVIYE_ANA, SEVIYE_TALI, StokGrupService

        kart = self._yeni()
        cagrilar = []

        class _SahteGrup:
            def __init__(self, parent, **kw):
                cagrilar.append(kw)
                self.result = None

        with patch("stok_grup_ui.StokGrupDialog", _SahteGrup), patch.object(kart, "wait_window", lambda _w: None):
            kart.grup_alanlari["ana"].set("")
            kart._grup_yeni_ekle("tali")
            self.assertIn("Ana Grup", self.mb.showwarning.call_args.args[1])
            kart.grup_alanlari["tali"].set("")
            kart._grup_yeni_ekle("alt")
            self.assertIn("Tali Grup", self.mb.showwarning.call_args.args[1])
            self.assertEqual(cagrilar, [])

            kart._grup_yeni_ekle("ana")
            self.assertEqual(cagrilar[-1], {"seviye": SEVIYE_ANA, "parent_id": None, "seviye_sabit": True})

            ana = StokGrupService.ekle(seviye=SEVIYE_ANA, kod="MOB", ad="Mobilya")
            kart._grup_id_map["ana"]["MOB — Mobilya"] = ana["id"]
            kart.grup_alanlari["ana"].set("MOB — Mobilya")
            kart._grup_yeni_ekle("tali")
            self.assertEqual(
                cagrilar[-1], {"seviye": SEVIYE_TALI, "parent_id": ana["id"], "seviye_sabit": True}
            )

    def test_yeni_kartta_hareket_paneli_sekmelerin_altinda_bos(self):
        kart = self._yeni()
        self.assertEqual(len(kart._dikey_bolme.panes()), 2)
        sekme_adlari = [kart.sekmeler.tab(i, "text").strip() for i in range(kart.sekmeler.index("end"))]
        self.assertEqual(
            sekme_adlari, ["Genel", "Barkod & Birimler", "Fiyat & Maliyet", "Depo & Stok", "Notlar", "Fonlar"]
        )
        self.assertEqual(str(kart.hareket_tablo.winfo_toplevel()), str(kart))
        self.assertEqual(kart.hareket_tablo.get_children(), ())


class GrupYeniEkleTest(_TemelDB):
    def test_ayni_ust_altinda_harf_bosluk_farkli_tekrar_reddedilir(self):
        from database.stok_grup_service import SEVIYE_ANA, SEVIYE_TALI, StokGrupService

        ana = StokGrupService.ekle(seviye=SEVIYE_ANA, kod="MOB", ad="Mobilya")
        StokGrupService.ekle(seviye=SEVIYE_TALI, kod="IC", ad="İç Mekân", parent_id=ana["id"])
        for kod, ad in (("DIS", "  iç   mekân "), ("ic", "Başka Ad")):
            with self.subTest(kod=kod, ad=ad), self.assertRaises(ValueError):
                StokGrupService.ekle(seviye=SEVIYE_TALI, kod=kod, ad=ad, parent_id=ana["id"])
        ana2 = StokGrupService.ekle(seviye=SEVIYE_ANA, kod="BAH", ad="Bahçe")
        StokGrupService.ekle(seviye=SEVIYE_TALI, kod="IC", ad="İç Mekân", parent_id=ana2["id"])

    def test_ana_seviyede_harf_bosluk_farkli_tekrar_reddedilir(self):
        from database.stok_grup_service import SEVIYE_ANA, SEVIYE_TALI, StokGrupService

        ana = StokGrupService.ekle(seviye=SEVIYE_ANA, kod="AG", ad="Ana  Grup")
        with self.assertRaises(ValueError):
            StokGrupService.ekle(seviye=SEVIYE_ANA, kod="AG2", ad="ana grup")
        StokGrupService.ekle(seviye=SEVIYE_TALI, kod="AGT", ad="ana grup", parent_id=ana["id"])

    def test_seviye_sabit_dialog_seviye_ve_ustu_kilitler(self):
        from database.stok_grup_service import SEVIYE_ANA, SEVIYE_TALI, StokGrupService
        from stok_grup_ui import StokGrupDialog

        ana = StokGrupService.ekle(seviye=SEVIYE_ANA, kod="MOB", ad="Mobilya")
        root = tk.Tk()
        root.withdraw()
        try:
            dlg = StokGrupDialog(root, seviye=SEVIYE_TALI, parent_id=ana["id"], seviye_sabit=True)
            self.assertEqual(dlg.title(), "Yeni Tali Grup")
            self.assertEqual(str(dlg.seviye_cb.cget("state")), "disabled")
            self.assertEqual(str(dlg.ust_cb.cget("state")), "disabled")
            dlg.destroy()
        finally:
            root.destroy()


class StoklarHubTest(unittest.TestCase):
    def test_stok_karti_ve_stok_listesi_ayri(self):
        import stoklar_ui

        anahtarlar = {a: b for b, _ac, a in stoklar_ui.STOKLAR_HUB_KARTLARI}
        self.assertEqual(anahtarlar["kart"], "STOK KARTI")
        self.assertNotIn("liste", anahtarlar)
        listeler = dict(stoklar_ui.RAPOR_GRUPLARI)["Stok Listeleri"]
        self.assertIn(("liste", "STOK LİSTESİ"), [(a, b) for b, _ac, a in listeler])

        from unittest.mock import MagicMock

        app = MagicMock()
        komutlar = stoklar_ui._hub_komutlar(app)
        self.assertIs(komutlar["kart"], app.yeni_stok)
        self.assertIs(komutlar["liste"], app.stok_kartlari_goster)
        self.assertIs(stoklar_ui._rapor_komutlar(app)["liste"], app.stok_kartlari_goster)


if __name__ == "__main__":
    unittest.main()
