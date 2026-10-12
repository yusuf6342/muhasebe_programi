"""Satış faturası satır içi miktar / fiyat düzenleme regresyonu.

.venv\\Scripts\\python.exe -m unittest tests.test_fatura_satir_hucre_edit -v
"""

from __future__ import annotations

import sys
import tempfile
import unittest
from datetime import date
from decimal import Decimal
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker

from database.database import Base, _aktif_engine_bagla
from database.models.cari import Cari, MusteriGrubu
from database.models.donem import Donem
from database.models.finans import FinansHesabi
from database.models.firma import Firma
from database.models.stok import Depo, StokKarti
from database.session_manager import oturum


_TIK_ZAMANI = [1_000_000]


def cift_tik(w, x: int, y: int) -> None:
    """event generate <Double-1> kabul etmez; aynı noktada iki hızlı tık üretilir."""
    _TIK_ZAMANI[0] += 10_000
    t = _TIK_ZAMANI[0]
    for i in range(2):
        w.event_generate("<ButtonPress-1>", x=x, y=y, time=t + i * 80)
        w.event_generate("<ButtonRelease-1>", x=x, y=y, time=t + i * 80 + 20)


def _pragma(dbapi_conn, _):
    cur = dbapi_conn.cursor()
    cur.execute("PRAGMA foreign_keys=ON")
    cur.close()


class FaturaSatirHucreEditTest(unittest.TestCase):
    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        path = Path(self._tmpdir.name) / "hucre.db"
        eng = create_engine(
            f"sqlite:///{path.as_posix()}",
            connect_args={"check_same_thread": False},
        )
        event.listen(eng, "connect", _pragma)
        import database.models.cari  # noqa: F401
        import database.models.stok  # noqa: F401
        import database.models.satis_siparisi  # noqa: F401
        import database.models.satis_irsaliyesi  # noqa: F401
        import database.models.satis_faturasi  # noqa: F401
        import database.models.finans  # noqa: F401
        import database.models.firma  # noqa: F401
        import database.models.doviz  # noqa: F401

        Base.metadata.create_all(eng)
        Session = sessionmaker(bind=eng, autoflush=False, autocommit=False, expire_on_commit=False)
        with Session() as s:
            firma = Firma(firma_kodu="HCR", unvan="Hucre", aktif=True)
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
            s.add(FinansHesabi(hesap_adi="KASA", hesap_turu="KASA", aktif=True))
            s.add(MusteriGrubu(ad="Genel"))
            s.add(Depo(ad="ANA DEPO", aktif=True))
            s.add(Cari(cari_kodu="M001", unvan="Test Müşteri", cari_turu="Müşteri", aktif=True))
            s.add(StokKarti(stok_kodu="U001", stok_adi="Test Ürün", birim="Adet", aktif=True))
            s.commit()
        _aktif_engine_bagla(eng)
        oturum.set_company(
            company_id=1, firma_kodu="HCR", firma_unvan="Hucre", firma_uid="x", db_path=str(path)
        )

        import tkinter as tk
        from app import SatisFaturasiDialog

        self.root = tk.Tk()
        self.root.withdraw()
        self._yamalar = [
            patch("satis_personeli_ui.aktif_satis_personelleri", return_value=[]),
            patch("satis_personeli_ui.satis_personeli_degistirme_yetkisi", return_value=True),
            patch("fatura_acilis_cache.satis_personelleri", return_value=[]),
            patch("fatura_manuel_fiyat_ui.fiyat_degistirme_yetkisi", return_value=True),
            patch("fatura_manuel_fiyat_ui.maliyet_alti_kontrol", return_value=True),
        ]
        for y in self._yamalar:
            y.start()
        self.dlg = SatisFaturasiDialog(self.root)
        self.dlg.geometry("1400x800+-3000+-3000")
        self.dlg.satirlar = [
            {
                "urun_kodu": "U001",
                "urun_adi": "Test Ürün",
                "miktar": "2",
                "birim": "Adet",
                "birim_satis_fiyati": "10",
                "kdv_orani": "20",
                "iskonto_orani": "0",
                "iskonto_orani_2": "0",
                "iskonto_orani_3": "0",
                "satir_para_birimi": "TRY",
                "kur": "1",
            }
        ]
        self.dlg._satir_listesini_yenile()
        self._pompala()

    def tearDown(self):
        try:
            self.dlg.destroy()
        except Exception:
            pass
        for y in self._yamalar:
            y.stop()
        try:
            self.root.destroy()
        except Exception:
            pass
        try:
            from database.database import engine

            if engine is not None:
                engine.dispose()
        except Exception:
            pass
        try:
            self._tmpdir.cleanup()
        except Exception:
            pass

    def _pompala(self, tur: int = 6):
        for _ in range(tur):
            self.dlg.update_idletasks()
            self.dlg.update()

    def _editor_ac_ve_yaz(self, fonk, deger: str):
        fonk(self.dlg, idx=0)
        self._pompala()
        editor = getattr(self.dlg, "_satir_hucre_editor", None)
        self.assertIsNotNone(editor, "Hücre editörü açıldıktan hemen sonra kapandı")
        self.assertTrue(editor.winfo_exists())
        editor.delete(0, "end")
        editor.insert(0, deger)
        # Tk üretilen tuş olayını odaktaki pencereye yollar; paralel koşuda odak kaçabilir.
        editor.focus_force()
        self._pompala()
        self.assertEqual(self.dlg.focus_get(), editor, "Klavye odağı hücre editöründe değil")
        editor.event_generate("<Return>")
        self._pompala()

    def test_miktar_guncellenir(self):
        from fatura_satir_hucre_edit import miktar_hucre_duzenle

        self._editor_ac_ve_yaz(miktar_hucre_duzenle, "5")
        self.assertEqual(Decimal(self.dlg.satirlar[0]["miktar"]), Decimal("5"))
        self.assertEqual(self.dlg.satir_tablosu.set("0", "miktar").strip(), "5")
        # 5 x 10,00 = 50,00 + %20 KDV = 60,00
        self.assertEqual(self.dlg._hesaplanan_genel, Decimal("60.00"))

    def test_fiyat_guncellenir_ve_toplam_degisir(self):
        from fatura_satir_hucre_edit import fiyat_hucre_duzenle

        self._editor_ac_ve_yaz(fiyat_hucre_duzenle, "12,50")
        self.assertEqual(Decimal(self.dlg.satirlar[0]["birim_satis_fiyati"]), Decimal("12.50"))
        # 2 x 12,50 = 25,00 + %20 KDV = 30,00
        self.assertEqual(self.dlg._hesaplanan_genel, Decimal("30.00"))

    def test_miktar_editoru_yeniden_cizimde_kapanmaz(self):
        from fatura_satir_hucre_edit import miktar_hucre_duzenle

        miktar_hucre_duzenle(self.dlg, idx=0)
        self._pompala()
        self.dlg._fatura_satir_vurgulu_overlay_ciz()
        self._pompala()
        editor = getattr(self.dlg, "_satir_hucre_editor", None)
        self.assertIsNotNone(editor)
        self.assertTrue(editor.winfo_exists())
        self.assertTrue(editor.winfo_ismapped())

    def test_vurgulu_miktar_etiketine_tek_tik_editor_acar(self):
        import time

        self.dlg._fatura_satir_vurgulu_overlay_ciz()
        self._pompala()
        bb = self.dlg.satir_tablosu.bbox("0", "miktar")
        self.assertTrue(bb)
        etiket = next(
            (
                w
                for w in self.dlg._vurgulu_overlayler
                if int(w.place_info().get("x", -1)) == bb[0]
            ),
            None,
        )
        self.assertIsNotNone(etiket)
        etiket.event_generate("<Button-1>", x=2, y=2)
        bitis = time.time() + 1.0
        while time.time() < bitis and getattr(self.dlg, "_satir_hucre_editor", None) is None:
            self._pompala(1)
        self._pompala()
        editor = getattr(self.dlg, "_satir_hucre_editor", None)
        self.assertIsNotNone(editor)
        editor.delete(0, "end")
        editor.insert(0, "7")
        editor.focus_force()
        self._pompala()
        editor.event_generate("<Return>")
        self._pompala()
        self.assertEqual(Decimal(self.dlg.satirlar[0]["miktar"]), Decimal("7"))

    def _birim_editoru(self):
        from fatura_satir_hucre_edit import birim_hucre_duzenle

        self.dlg.satirlar[0]["miktar"] = "24"
        self.dlg._satir_listesini_yenile()
        self._pompala()
        birim_hucre_duzenle(self.dlg, idx=0)
        self._pompala()
        editor = getattr(self.dlg, "_satir_hucre_editor", None)
        self.assertIsNotNone(editor, "Tek birimli kartta birim seçici açılmadı")
        return editor

    @staticmethod
    def _koli_carpani():
        from database.stok_service import StokService
        from fatura_satir_birim_service import _stok_yukle

        return StokService.birim_carpani_bul(_stok_yukle("U001"), "Koli")

    def test_birim_listesinde_yalniz_stok_kartinin_birimleri(self):
        editor = self._birim_editoru()
        self.assertEqual(tuple(editor.cget("values")), ("Adet",))
        editor.event_generate("<Escape>")
        self._pompala()
        from database.stok_service import StokService

        with patch("database.access.yazma_zorunlu"), patch("database.user_audit.audit_document"):
            StokService.kart_birimi_ekle("U001", "Koli", Decimal("12"))
        editor = self._birim_editoru()
        self.assertEqual(tuple(editor.cget("values")), ("Adet", "Koli"))

    def test_kart_birimi_secilince_miktar_ve_fiyat_donusur_soru_sorulmaz(self):
        from database.stok_service import StokService

        with patch("database.access.yazma_zorunlu"), patch("database.user_audit.audit_document"):
            StokService.kart_birimi_ekle("U001", "Koli", Decimal("12"))
        editor = self._birim_editoru()
        editor.set("Koli")
        with patch("birim_secim_ui.simpledialog.askstring") as sor:
            editor._uygula_fn()
        self._pompala()
        sor.assert_not_called()
        satir = self.dlg.satirlar[0]
        self.assertEqual(satir["birim"], "Koli")
        # 24 Adet = 2 Koli; stok temel birimde 24 düşer, satır toplamı değişmez
        self.assertEqual(Decimal(satir["miktar"]), Decimal("2"))
        self.assertEqual(Decimal(satir["temel_miktar"]), Decimal("24"))
        self.assertEqual(Decimal(satir["birim_satis_fiyati"]), Decimal("120"))
        self.assertEqual(self.dlg._hesaplanan_genel, Decimal("288.00"))
        self.assertEqual(self._koli_carpani(), Decimal("12"))

    # --- Satır içinde tüm işlemler: Enter / sağ-sol ok, iskonto, KDV, açıklama ---

    def _bekle(self, sure: float = 0.2):
        import time

        bitis = time.time() + sure
        while time.time() < bitis:
            self._pompala(1)

    def _editor(self):
        editor = getattr(self.dlg, "_satir_hucre_editor", None)
        self.assertIsNotNone(editor, "Hücre editörü açık değil")
        return editor

    def _editor_kolonu(self) -> str:
        editor = self._editor()
        x = int(editor.place_info()["x"])
        tablo = self.dlg.satir_tablosu
        for kolon in tablo["displaycolumns"]:
            bb = tablo.bbox("0", kolon)
            if bb and bb[0] == x:
                return kolon
        self.fail(f"Editör konumu (x={x}) hiçbir kolonla eşleşmedi")

    def _odak(self):
        """Penceredeki son odak (paralel koşuda uygulama arka planda kalsa da focus_set sonucunu verir)."""
        yol = str(self.dlg.tk.call("focus", "-lastfor", str(self.dlg)))
        try:
            return self.dlg.nametowidget(yol)
        except KeyError:
            return None

    def _hedef(self):
        """Odaktaki editör; üçlü iskontoda odaktaki kutu."""
        editor = self._editor()
        kutular = getattr(editor, "kutular", None)
        if not kutular:
            return editor
        odak = self._odak()
        return odak if odak in kutular else kutular[0]

    def _tus(self, tus: str):
        hedef = self._hedef()
        hedef.focus_force()
        self._pompala()
        hedef.event_generate(tus)
        self._bekle()

    def _iskonto_kutusu(self) -> int:
        return self._editor().kutular.index(self._hedef())

    def _beklenen_sira(self):
        from fatura_satir_hucre_edit import EDITABLE_COLUMN_ORDER, kolon_duzenlenebilir_mi

        return [k for k in EDITABLE_COLUMN_ORDER if kolon_duzenlenebilir_mi(self.dlg, 0, k)]

    def test_tek_birimli_kartta_birim_hucresi_duzenlenebilir(self):
        from fatura_satir_hucre_edit import kolon_duzenlenebilir_mi

        self.assertTrue(kolon_duzenlenebilir_mi(self.dlg, 0, "birim"))
        self.dlg.satirlar[0]["irsaliye_satiri_id"] = 5
        self.assertFalse(kolon_duzenlenebilir_mi(self.dlg, 0, "birim"))

    def test_birim_etiketine_tik_secici_acar(self):
        from tkinter import ttk

        self.dlg._fatura_satir_vurgulu_overlay_ciz()
        self._pompala()
        bb = self.dlg.satir_tablosu.bbox("0", "birim")
        self.assertTrue(bb)
        etiket = next(
            (w for w in self.dlg._vurgulu_overlayler if int(w.place_info().get("x", -1)) == bb[0]),
            None,
        )
        self.assertIsNotNone(etiket, "Birim hücresinin üstünde etiket yok")
        etiket.event_generate("<Button-1>", x=2, y=2)
        self._bekle(0.5)
        self.assertIsInstance(self._editor(), ttk.Combobox)
        self.assertEqual(tuple(self._editor().cget("values")), ("Adet",))

    def test_sag_sol_ok_ve_enter_ile_satirda_gezinilir(self):
        from fatura_satir_hucre_edit import focus_editable_cell

        sira = self._beklenen_sira()
        for kolon in ("miktar", "birim", "fiyat", "para_birimi", "iskonto", "iskonto_tutar", "kdv", "aciklama"):
            self.assertIn(kolon, sira)
        focus_editable_cell(self.dlg, 0, "miktar")
        self._bekle()
        self.assertEqual(self._editor_kolonu(), "miktar")
        for kolon in sira[1:]:
            self._tus("<Right>")
            self.assertEqual(self._editor_kolonu(), kolon)
            if kolon == "iskonto":
                # üç ardışık iskonto kutusu: → ile 1 → 2 → 3, sonra sonraki kolon
                self.assertEqual(self._iskonto_kutusu(), 0)
                for kutu in (1, 2):
                    self._tus("<Right>")
                    self.assertEqual(self._editor_kolonu(), "iskonto")
                    self.assertEqual(self._iskonto_kutusu(), kutu)
        for kolon in reversed(sira[:-1]):
            self._tus("<Left>")
            self.assertEqual(self._editor_kolonu(), kolon)
            if kolon == "iskonto":
                # geri gelişte son kutudan başlar
                self.assertEqual(self._iskonto_kutusu(), 2)
                for kutu in (1, 0):
                    self._tus("<Left>")
                    self.assertEqual(self._iskonto_kutusu(), kutu)
        self._tus("<Return>")
        self.assertEqual(self._editor_kolonu(), sira[1])
        # Değer yazılan metin hücresinde ok imleci gezdirir, hücreden çıkmaz
        focus_editable_cell(self.dlg, 0, "miktar")
        self._bekle()
        editor = self._editor()
        editor.selection_clear()
        editor.icursor("end")
        self._tus("<Left>")
        self.assertEqual(self._editor_kolonu(), "miktar")
        self.assertEqual(editor.index("insert"), len(editor.get()) - 1)

    def test_tablo_secili_satirda_sag_ok_ilk_hucreyi_acar(self):
        from fatura_satir_hucre_edit import fatura_satir_hucre_etkilesim

        fatura_satir_hucre_etkilesim(self.dlg)
        tablo = self.dlg.satir_tablosu
        tablo.selection_set("0")
        tablo.focus_force()
        self._pompala()
        tablo.event_generate("<Right>")
        self._bekle()
        self.assertEqual(self._editor_kolonu(), "miktar")
        self._editor().event_generate("<Escape>")
        self._pompala()
        tablo.focus_force()
        self._pompala()
        tablo.event_generate("<Left>")
        self._bekle()
        self.assertEqual(self._editor_kolonu(), self._beklenen_sira()[-1])

    def test_iskonto_satirda_kademeli_yazilir_pencere_acilmaz(self):
        import tkinter as tk
        from fatura_satir_hucre_edit import focus_editable_cell

        focus_editable_cell(self.dlg, 0, "iskonto")
        self._bekle()
        self.assertEqual(self._editor_kolonu(), "iskonto")
        editor = self._editor()
        self.assertIsInstance(editor, tk.Widget)
        self.assertEqual(len(editor.kutular), 3, "İskonto 1 / 2 / 3 kutuları açılmadı")
        for i, deger in enumerate(("10", "5", "0")):
            self.assertEqual(self._iskonto_kutusu(), i)
            kutu = editor.kutular[i]
            kutu.delete(0, "end")
            kutu.insert(0, deger)
            self._tus("<Return>")
        satir = self.dlg.satirlar[0]
        self.assertEqual(Decimal(satir["iskonto_orani"]), Decimal("10"))
        self.assertEqual(Decimal(satir["iskonto_orani_2"]), Decimal("5"))
        self.assertFalse(
            any(isinstance(w, tk.Toplevel) for w in self.dlg.winfo_children()),
            "İskonto için ayrı pencere açıldı",
        )
        # 2 x 10 = 20; %10 → 18; %5 → 17,10; +%20 KDV = 20,52
        self.assertEqual(self.dlg._hesaplanan_genel, Decimal("20.52"))
        self.assertEqual(self._editor_kolonu(), "iskonto_tutar")

    def test_tek_kademeli_belgede_kademeli_iskonto_reddedilir(self):
        from fatura_satir_hucre_edit import focus_editable_cell

        self.dlg.TEK_KADEME_ISKONTO = True
        focus_editable_cell(self.dlg, 0, "iskonto")
        self._bekle()
        editor = self._editor()
        self.assertEqual(len(editor.kutular), 1)
        editor.kutular[0].delete(0, "end")
        editor.kutular[0].insert(0, "10+5")
        with patch("fatura_satir_hucre_edit.messagebox.showerror") as hata:
            self._tus("<Return>")
        hata.assert_called_once()
        self.assertEqual(Decimal(self.dlg.satirlar[0]["iskonto_orani"]), Decimal("0"))

    def test_kdv_satirda_secilir(self):
        from fatura_satir_hucre_edit import focus_editable_cell

        focus_editable_cell(self.dlg, 0, "kdv")
        self._bekle()
        self.assertEqual(self._editor_kolonu(), "kdv")
        self._editor().set("10")
        self._tus("<Return>")
        self.assertEqual(Decimal(self.dlg.satirlar[0]["kdv_orani"]), Decimal("10"))
        # 2 x 10 = 20 + %10 KDV = 22
        self.assertEqual(self.dlg._hesaplanan_genel, Decimal("22.00"))

    def _ikinci_satir(self):
        ikinci = dict(self.dlg.satirlar[0], miktar="4")
        self.dlg.satirlar.append(ikinci)
        self.dlg._satir_listesini_yenile()
        self._pompala()

    def _editor_satiri(self) -> int:
        editor = self._editor()
        y = int(editor.place_info()["y"])
        tablo = self.dlg.satir_tablosu
        for i in range(len(self.dlg.satirlar)):
            bb = tablo.bbox(str(i), "miktar")
            if bb and bb[1] == y:
                return i
        self.fail(f"Editör satırı (y={y}) bulunamadı")

    def test_yukari_asagi_ok_ayni_kolonda_satir_degistirir(self):
        from fatura_satir_hucre_edit import focus_editable_cell

        self._ikinci_satir()
        focus_editable_cell(self.dlg, 0, "miktar")
        self._bekle()
        editor = self._editor()
        editor.delete(0, "end")
        editor.insert(0, "3")
        self._tus("<Down>")
        self.assertEqual(Decimal(self.dlg.satirlar[0]["miktar"]), Decimal("3"))
        self.assertEqual((self._editor_satiri(), self._editor_kolonu()), (1, "miktar"))
        self._tus("<Up>")
        self.assertEqual((self._editor_satiri(), self._editor_kolonu()), (0, "miktar"))
        # Açılır liste hücresinde de ↑/↓ satır değiştirir (liste Alt+↓ ile açılır)
        focus_editable_cell(self.dlg, 0, "kdv")
        self._bekle()
        self._tus("<Down>")
        self.assertEqual((self._editor_satiri(), self._editor_kolonu()), (1, "kdv"))
        # Üçlü iskontoda ↓ değerleri yazar ve alttaki satırın iskontosuna geçer
        focus_editable_cell(self.dlg, 0, "iskonto")
        self._bekle()
        kutu = self._editor().kutular[0]
        kutu.delete(0, "end")
        kutu.insert(0, "10")
        self._tus("<Down>")
        self.assertEqual(Decimal(self.dlg.satirlar[0]["iskonto_orani"]), Decimal("10"))
        self.assertEqual(self._editor_kolonu(), "iskonto")
        self.assertEqual(self._editor_satiri(), 1)

    def test_urun_hucresine_cift_tik_ve_f2_stok_kartini_acar(self):
        from fatura_satir_hucre_edit import fatura_satir_hucre_etkilesim

        fatura_satir_hucre_etkilesim(self.dlg)
        tablo = self.dlg.satir_tablosu
        self._pompala()
        for kolon in ("urun_adi", "urun_kodu"):
            if kolon not in tablo["displaycolumns"] and tuple(tablo["displaycolumns"]) != ("#all",):
                continue
            bb = tablo.bbox("0", kolon)
            if not bb:
                continue
            with patch("stok_ui.StokKartiDialog") as kart:
                cift_tik(tablo, bb[0] + bb[2] // 2, bb[1] + bb[3] // 2)
                self._bekle()
            kart.assert_called_once()
            self.assertEqual(kart.call_args.args[1].stok_kodu, "U001")
            self.assertIsNone(getattr(self.dlg, "_satir_hucre_editor", None))
        # F2: tablo odaktayken seçili satırın stok kartı; kaydet vb. tetiklenmez
        tablo.selection_set("0")
        tablo.focus_force()
        self._pompala()
        with patch("stok_ui.StokKartiDialog") as kart, patch.object(self.dlg, "kaydet") as kaydet:
            tablo.event_generate("<F2>")
            self._bekle()
        kart.assert_called_once()
        kaydet.assert_not_called()
        # Bağlı kartı olmayan satır: kısa bilgi, hata yok
        self.dlg.satirlar[0]["urun_kodu"] = ""
        tablo.focus_force()
        self._pompala()
        with patch("stok_ui.StokKartiDialog") as kart, patch("satir_klavye.messagebox.showinfo") as bilgi:
            tablo.event_generate("<F2>")
            self._bekle()
        kart.assert_not_called()
        bilgi.assert_called_once()

    def test_ust_alanlarda_enter_ve_oklarla_gezinilir(self):
        from tkinter import ttk

        from evrak_baslik_gezinme import baslik_alanlari

        self._bekle(0.3)
        alanlar = baslik_alanlari(self.dlg)
        self.assertGreaterEqual(len(alanlar), 6, alanlar)
        for w in alanlar:
            durum = str(w.cget("state"))
            self.assertNotEqual(durum, "disabled", w)
            if not isinstance(w, ttk.Combobox):
                self.assertNotEqual(durum, "readonly", w)
        self.assertIn(self.dlg.musteri_kodu, alanlar)

        def _tus(w, tus):
            w.focus_force()
            self._pompala()
            w.event_generate(tus)
            self._bekle(0.1)
            return self._odak()

        tarih = self.dlg.girdiler["siparis_tarihi"]
        i = alanlar.index(tarih)
        self.assertIs(_tus(tarih, "<Return>"), alanlar[i + 1])
        self.assertIs(_tus(alanlar[i + 1], "<Up>"), tarih)
        self.assertIs(_tus(tarih, "<Down>"), alanlar[i + 1])
        tarih.icursor("end")
        tarih.selection_clear()
        self.assertIs(_tus(tarih, "<Right>"), alanlar[i + 1])
        alanlar[i + 1].icursor(0)
        alanlar[i + 1].selection_clear()
        self.assertIs(_tus(alanlar[i + 1], "<Left>"), tarih)
        # Metnin ortasında ← / → imleci gezdirir, alan değişmez
        tarih.icursor(2)
        tarih.selection_clear()
        self.assertIs(_tus(tarih, "<Right>"), tarih)
        # Seçim listesi (readonly) alanında ↓ alan değiştirir, liste açılmaz
        depo = self.dlg.depo
        if depo in alanlar and depo is not alanlar[-1]:
            self.assertIs(_tus(depo, "<Down>"), alanlar[alanlar.index(depo) + 1])
        # Son alanda Enter ürün giriş satırına gider
        son = alanlar[-1]
        odak = _tus(son, "<Return>")
        self.assertTrue(str(odak).startswith(str(self.dlg.satir_tablosu)), odak)

    def test_tl_satirinda_kur_hucresine_tik_mesaj_acmaz(self):
        from fatura_satir_hucre_edit import fatura_satir_hucre_etkilesim, kur_hucre_duzenle

        fatura_satir_hucre_etkilesim(self.dlg)
        tablo = self.dlg.satir_tablosu
        self._pompala()
        with patch("fatura_satir_hucre_edit.messagebox") as mb:
            kur_hucre_duzenle(self.dlg, idx=0)
            bb = tablo.bbox("0", "kur")
            if bb:
                x, y = bb[0] + bb[2] // 2, bb[1] + bb[3] // 2
                tablo.event_generate("<ButtonPress-1>", x=x, y=y)
                tablo.event_generate("<ButtonRelease-1>", x=x, y=y)
                self._bekle(0.4)
                cift_tik(tablo, x, y)
                self._bekle(0.4)
        mb.showinfo.assert_not_called()
        self.assertIsNone(getattr(self.dlg, "_satir_hucre_editor", None))

    def test_dar_pencerede_aciklama_satirda_girilir(self):
        from fatura_satir_hucre_edit import focus_editable_cell

        self.dlg.geometry("700x700+-3000+-3000")
        self._bekle()
        focus_editable_cell(self.dlg, 0, "aciklama")
        self._bekle(0.4)
        self.assertEqual(self._editor_kolonu(), "aciklama")
        editor = self._editor()
        editor.delete(0, "end")
        editor.insert(0, "Kapıya teslim")
        self._tus("<Return>")
        self.assertEqual(self.dlg.satirlar[0]["aciklama"], "Kapıya teslim")
        self.assertEqual(self.dlg.satir_tablosu.set("0", "aciklama").strip(), "Kapıya teslim")


if __name__ == "__main__":
    unittest.main()
