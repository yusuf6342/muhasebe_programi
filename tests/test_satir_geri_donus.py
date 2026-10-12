"""Evrak satırlarına geri dönüş: açık hücre editörü varken başka satıra tık / ok ile gezinme.

Hata: Enter ile satır sonuna gelindikten sonra (veya bir hücre açık kalmışken) başka satıra
fareyle ya da oklarla dönülemiyordu; açık editör tüm tıklamaları ve okları yutuyordu.

.venv\\Scripts\\python.exe -m pytest -p no:cacheprovider -q tests/test_satir_geri_donus.py
"""

from __future__ import annotations

import sys
import time
import unittest
from decimal import Decimal
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import tests.test_fatura_satir_hucre_edit as _hucre_testi
from satir_ici_urun_giris import veri_iidleri
from tests.test_satir_ici_urun_giris import _GirisTemel

_TIK = [5_000_000]
_KUTULU = ("birim", "para_birimi", "kdv")


def _tikla(w, x: int, y: int) -> None:
    _TIK[0] += 5_000  # çift tık sayılmasın
    w.event_generate("<ButtonPress-1>", x=x, y=y, time=_TIK[0])
    w.event_generate("<ButtonRelease-1>", x=x, y=y, time=_TIK[0] + 30)


class _SatirYardim:
    _pompala = _hucre_testi.FaturaSatirHucreEditTest._pompala

    def _bekle(self, sure: float = 0.4, dlg=None):
        dlg = dlg or self.dlg
        bitis = time.time() + sure
        while time.time() < bitis:
            dlg.update()
            time.sleep(0.01)

    def _ikinci_satir(self, dlg=None):
        dlg = dlg or self.dlg
        dlg.satirlar.append(dict(dlg.satirlar[0], miktar="4"))
        dlg._satir_listesini_yenile()
        self._bekle(0.3, dlg)

    @staticmethod
    def _editor(dlg):
        from fatura_satir_hucre_edit import acik_editor

        return acik_editor(dlg)

    def _editor_hucresi(self, dlg=None):
        dlg = dlg or self.dlg
        ed = self._editor(dlg)
        if ed is None:
            return None
        tablo = dlg.satir_tablosu
        x, y = int(ed.place_info()["x"]), int(ed.place_info()["y"])
        for iid in veri_iidleri(tablo):
            for kolon in tablo["columns"]:
                bb = tablo.bbox(iid, kolon)
                if bb and bb[1] == y and bb[0] == x:
                    return int(iid), kolon
        for iid in veri_iidleri(tablo):
            bb = tablo.bbox(iid, "miktar")
            if bb and bb[1] == y:
                return int(iid), "?"
        return "?", x, y

    def _hucreye_tikla(self, iid: str, kolon: str, dlg=None):
        """Gerçek tık gibi: hücrenin üstünde vurgulu etiket varsa tık etikete gider."""
        dlg = dlg or self.dlg
        tablo = dlg.satir_tablosu
        tablo.see(iid)
        self._pompala()
        bb = tablo.bbox(iid, kolon)
        self.assertTrue(bb, f"{iid}/{kolon} görünmüyor")
        etiket = None
        for w in getattr(dlg, "_vurgulu_overlayler", []) or []:
            try:
                bilgi = w.place_info()
                if w.winfo_ismapped() and int(bilgi["x"]) == bb[0] and int(bilgi["y"]) == bb[1]:
                    etiket = w
                    break
            except Exception:
                continue
        if etiket is not None:
            _tikla(etiket, 3, 3)
        else:
            _tikla(tablo, bb[0] + bb[2] // 2, bb[1] + bb[3] // 2)
        self._bekle(0.45, dlg)

    def _tus(self, w, tus: str, dlg=None):
        w.focus_force()
        self._pompala()
        w.event_generate(tus)
        self._bekle(0.3, dlg)

    def _yaz(self, deger: str, dlg=None):
        ed = self._editor(dlg or self.dlg)
        self.assertIsNotNone(ed)
        ed.delete(0, "end")
        ed.insert(0, deger)


class _FaturaTemel(_SatirYardim, unittest.TestCase):
    def setUp(self):
        # Gerçek mesaj kutusu testi kilitlemesin
        self._mesaj_yamalari = [
            patch(f"tkinter.messagebox.{ad}", return_value=None) for ad in ("showinfo", "showwarning", "showerror")
        ]
        self.mesajlar = [p.start() for p in self._mesaj_yamalari]
        self.addCleanup(lambda: [p.stop() for p in self._mesaj_yamalari])
        _hucre_testi.FaturaSatirHucreEditTest.setUp(self)

    tearDown = _hucre_testi.FaturaSatirHucreEditTest.tearDown


class SatisFaturasiSatirGeriDonusTest(_FaturaTemel):
    def test_acik_editor_varken_baska_satira_tik_degeri_yazar_ve_yeni_hucreyi_acar(self):
        """Ekran görüntüsündeki durum: 2. satırın açıklaması açık kalmış, 1. satıra dönülemiyordu."""
        from fatura_satir_hucre_edit import focus_editable_cell

        self._ikinci_satir()
        focus_editable_cell(self.dlg, 1, "aciklama")
        self._bekle()
        self.assertEqual(self._editor_hucresi(), (1, "aciklama"))
        self._yaz("kapıya")
        self._hucreye_tikla("0", "fiyat")
        self.assertEqual(self.dlg.satirlar[1].get("aciklama"), "kapıya")
        self.assertEqual(self.dlg.satir_tablosu.selection(), ("0",))
        self.assertEqual(self._editor_hucresi(), (0, "fiyat"))
        self._yaz("12,50")
        self._tus(self._editor(self.dlg), "<Return>")
        self.assertEqual(Decimal(self.dlg.satirlar[0]["birim_satis_fiyati"]), Decimal("12.50"))
        # Açık editör varken vurgulu (büyük yazılı) miktar etiketine tık
        focus_editable_cell(self.dlg, 1, "aciklama")
        self._bekle()
        self._hucreye_tikla("0", "miktar")
        self.assertEqual(self._editor_hucresi(), (0, "miktar"))
        self._yaz("5")
        self._tus(self._editor(self.dlg), "<Return>")
        self.assertEqual(Decimal(self.dlg.satirlar[0]["miktar"]), Decimal("5"))
        # 5 x 12,50 + 4 x 10 = 102,50 + %20 KDV = 123,00
        self.assertEqual(self.dlg._hesaplanan_genel, Decimal("123.00"))

    def test_her_kolona_tik_satiri_secer_duzenlenebilir_hucrede_editor_acar(self):
        from fatura_satir_hucre_edit import focus_editable_cell, kolon_duzenlenebilir_mi

        self._ikinci_satir()
        tablo = self.dlg.satir_tablosu
        gorunen = [k for k in tablo["displaycolumns"] if k != "#all"] or list(tablo["columns"])
        denenen = 0
        with patch("fatura_satir_hucre_edit._listeyi_ac"):
            for i, kolon in enumerate(gorunen):
                if kolon == "sec" or not tablo.bbox("0", kolon):
                    continue
                hedef, diger = ("0", 1) if i % 2 == 0 else ("1", 0)
                with self.subTest(kolon=kolon, satir=hedef):
                    focus_editable_cell(self.dlg, diger, "aciklama")
                    self._bekle(0.2)
                    self.assertEqual(self._editor_hucresi(), (diger, "aciklama"))
                    self._hucreye_tikla(hedef, kolon)
                    self.assertEqual(tablo.selection(), (hedef,))
                    hucre = self._editor_hucresi()
                    if kolon_duzenlenebilir_mi(self.dlg, int(hedef), kolon):
                        self.assertEqual(hucre, (int(hedef), kolon))
                    else:
                        self.assertIsNone(hucre, f"{kolon}: eski editör açık kaldı")
                    denenen += 1
                    ed = self._editor(self.dlg)
                    if ed is not None:
                        from fatura_satir_hucre_edit import _editor_kapat

                        _editor_kapat(self.dlg)
                        self._pompala()
        self.assertGreaterEqual(denenen, 10)

    def test_kdv_hucresine_tik_liste_acilir_editor_kapanmaz(self):
        self._ikinci_satir()
        self._hucreye_tikla("1", "kdv")
        ed = self._editor(self.dlg)
        self.assertEqual(self._editor_hucresi(), (1, "kdv"), "KDV listesi açılınca editör kapandı")
        try:
            ed.tk.call("ttk::combobox::Unpost", str(ed))
        except Exception:
            pass
        self._bekle(0.2)
        ed.set("10")
        self._tus(ed, "<Return>")
        self.assertEqual(Decimal(self.dlg.satirlar[1]["kdv_orani"]), Decimal("10"))

    def test_oklarla_giris_satirindan_ve_editorden_satirlara_donulur(self):
        self._ikinci_satir()
        tablo = self.dlg.satir_tablosu
        giris = self.dlg._satir_ici_giris
        giris.odakla()
        self._bekle(0.3)
        self.assertTrue(giris.acik_mi())
        self._tus(giris.entry, "<Up>")
        self.assertEqual(tablo.selection(), ("1",))
        self.assertTrue(str(self.dlg.focus_get() or tablo).startswith(str(tablo)))
        self._tus(tablo, "<Up>")
        self.assertEqual(tablo.selection(), ("0",))
        self._tus(tablo, "<Right>")
        self.assertEqual(self._editor_hucresi(), (0, "miktar"))
        self._tus(self._editor(self.dlg), "<Down>")
        self.assertEqual(self._editor_hucresi(), (1, "miktar"))
        self._tus(self._editor(self.dlg), "<Up>")
        self.assertEqual(self._editor_hucresi(), (0, "miktar"))
        self._tus(self._editor(self.dlg), "<Down>")
        self._tus(self._editor(self.dlg), "<Down>")
        self.assertIsNone(self._editor(self.dlg))
        self._bekle(0.2)
        self.assertTrue(giris.acik_mi(), "Son satırdan ↓ ürün giriş satırına gitmedi")

    def test_editor_acikken_tablodan_ok_once_degeri_yazar(self):
        from fatura_satir_hucre_edit import focus_editable_cell

        self._ikinci_satir()
        tablo = self.dlg.satir_tablosu
        focus_editable_cell(self.dlg, 1, "miktar")
        self._bekle()
        self._yaz("7")
        tablo.selection_set("0")
        self._tus(tablo, "<Right>")
        self.assertEqual(Decimal(self.dlg.satirlar[1]["miktar"]), Decimal("7"))
        self.assertEqual(self._editor_hucresi(), (0, "miktar"))

    def test_odak_baska_alana_gecince_editor_yazilir_ve_kapanir(self):
        from fatura_satir_hucre_edit import focus_editable_cell

        self._ikinci_satir()
        focus_editable_cell(self.dlg, 1, "miktar")
        self._bekle()
        self._yaz("6")
        self.dlg.musteri_kodu.focus_force()
        self._bekle(0.4)
        self.assertIsNone(self._editor(self.dlg))
        self.assertEqual(Decimal(self.dlg.satirlar[1]["miktar"]), Decimal("6"))
        self._hucreye_tikla("0", "aciklama")
        self.assertEqual(self._editor_hucresi(), (0, "aciklama"))

    def test_giris_satirina_tik_acik_editoru_yazar(self):
        from fatura_satir_hucre_edit import focus_editable_cell
        from satir_ici_urun_giris import YENI_SATIR_IID

        self._ikinci_satir()
        focus_editable_cell(self.dlg, 0, "miktar")
        self._bekle()
        self._yaz("9")
        tablo = self.dlg.satir_tablosu
        kolon = self.dlg._satir_ici_giris.kolonlar.get("ad")
        bb = tablo.bbox(YENI_SATIR_IID, kolon)
        self.assertTrue(bb)
        _tikla(tablo, bb[0] + 10, bb[1] + bb[3] // 2)
        self._bekle(0.3)
        self.assertEqual(Decimal(self.dlg.satirlar[0]["miktar"]), Decimal("9"))
        self.assertIsNone(self._editor(self.dlg))
        self.assertTrue(self.dlg._satir_ici_giris.acik_mi())


class KayitliSatisFaturasiTest(_SatirYardim, _GirisTemel):
    """Kaydedilmiş (AÇIK, onaysız) fatura: kayıttan sonra ve yeniden açılınca satırlar düzenlenir."""

    DEG = ("MB001", "Birim Ürün", "Adet", "0", "1", "Stok Kartı", "20", None)

    def _ac(self, **ek):
        from app import SatisFaturasiDialog

        self.root.geometry("1x1+-3000+-3000")
        self.root.deiconify()
        with patch("ui_pencere.belge_penceresini_hazirla", lambda win, **_k: {}), patch(
            "satis_personeli_ui.aktif_satis_personelleri", return_value=[]
        ), patch("fatura_acilis_cache.satis_personelleri", return_value=[]):
            dlg = SatisFaturasiDialog(self.root, **ek)
        dlg.geometry("1400x800+-3000+-3000")
        dlg.deiconify()
        self.dlg = dlg
        self._bekle(0.4)
        return dlg

    def _kaydet(self, dlg):
        with patch("app.messagebox.showerror") as hata, patch(
            "app.messagebox.askyesno", return_value=False
        ), patch("kasa_makbuz_ui.KasaMakbuzDialog"), patch.object(dlg, "_kayit_bildirimi_goster"):
            dlg.kaydet()
            self._bekle(0.3, dlg)
        self.assertFalse(hata.called, hata.call_args)

    def test_kaydedilen_acik_fatura_duzenlenir_onayli_kilitli_kalir(self):
        from database.satis_faturasi_service import SatisFaturasiService

        self._ac(cari=self._cari())
        self.dlg._satir_ici_giris.urun_ekle_fn(self.DEG, None)
        self._bekle(0.3)
        self._ikinci_satir()
        self.assertEqual(len(self.dlg.satirlar), 2)
        self._kaydet(self.dlg)
        self.assertIsNotNone(self.dlg.fatura)
        self.assertEqual(self.dlg.fatura.durum, "AÇIK")
        self.assertFalse(self.dlg.fatura.onaylandi)
        self.assertFalse(self.dlg._fatura_kilitli)
        # Kayıttan sonra aynı ekranda düzeltme
        self._hucreye_tikla("0", "miktar")
        self.assertEqual(self._editor_hucresi(), (0, "miktar"))
        self._yaz("3")
        self._tus(self._editor(self.dlg), "<Return>")
        self._kaydet(self.dlg)
        fatura_id = self.dlg.fatura.id
        self.dlg.destroy()
        # Kayıtlı AÇIK fatura yeniden açılınca (ekran görüntüsündeki RAY-00006 gibi)
        dlg = self._ac(fatura=SatisFaturasiService.getir(fatura_id))
        self.assertEqual(dlg.fatura.durum, "AÇIK")
        self.assertEqual(len(dlg.satirlar), 2)
        self.assertEqual(Decimal(dlg.satirlar[0]["miktar"]), Decimal("3"))
        self.assertFalse(dlg._fatura_kilitli)
        from fatura_satir_hucre_edit import focus_editable_cell

        focus_editable_cell(dlg, 1, "aciklama")
        self._bekle()
        self._hucreye_tikla("0", "miktar")
        self.assertEqual(self._editor_hucresi(), (0, "miktar"))
        self._yaz("8")
        self._tus(self._editor(dlg), "<Return>")
        self.assertEqual(Decimal(dlg.satirlar[0]["miktar"]), Decimal("8"))
        # Onaylı fatura: tık / ok editör açmaz
        from fatura_satir_hucre_edit import _editor_kapat

        _editor_kapat(dlg)
        dlg.fatura.onaylandi = True
        dlg._fatura_kilit_uygula()
        self.assertTrue(dlg._fatura_kilitli)
        self._hucreye_tikla("1", "miktar")
        self.assertIsNone(self._editor(dlg))
        self._tus(dlg.satir_tablosu, "<Right>")
        self.assertIsNone(self._editor(dlg))
        dlg.destroy()


class SatisIadeSatirGeriDonusTest(_FaturaTemel):
    def setUp(self):
        _hucre_testi.FaturaSatirHucreEditTest.setUp(self)
        from app import SatisIadeFaturasiDialog

        self.dlg.destroy()
        self.dlg = SatisIadeFaturasiDialog(self.root)
        self.dlg.geometry("1400x800+-3000+-3000")
        self.dlg.satirlar = [
            {
                "urun_kodu": "U001", "urun_adi": "Test Ürün", "miktar": "2", "birim": "Adet",
                "birim_satis_fiyati": "10", "kdv_orani": "20", "iskonto_orani": "0",
                "iskonto_orani_2": "0", "iskonto_orani_3": "0", "satir_para_birimi": "TRY", "kur": "1",
            }
        ]
        self.dlg._satir_listesini_yenile()
        self._bekle(0.3)

    def test_iade_satirina_tik_ve_ok(self):
        from fatura_satir_hucre_edit import focus_editable_cell

        self._ikinci_satir()
        focus_editable_cell(self.dlg, 1, "miktar")
        self._bekle()
        self.assertEqual(self._editor_hucresi(), (1, "miktar"))
        self._yaz("3")
        self._hucreye_tikla("0", "miktar")
        self.assertEqual(Decimal(self.dlg.satirlar[1]["miktar"]), Decimal("3"))
        self.assertEqual(self._editor_hucresi(), (0, "miktar"))
        self._tus(self._editor(self.dlg), "<Down>")
        self.assertEqual(self._editor_hucresi(), (1, "miktar"))
        self._tus(self._editor(self.dlg), "<Up>")
        self.assertEqual(self._editor_hucresi(), (0, "miktar"))


class MuadilEvrakSatirGeriDonusTest(_GirisTemel):
    """Ortak satır düzenleyici (SatirHucreDuzenleyici) kullanan evraklar."""

    DEG = ("MB001", "Birim Ürün", "Adet", "0", "1", "Stok Kartı", "20", None)

    def _pompala(self, d, sure=0.15):
        bitis = time.time() + sure
        while time.time() < bitis:
            d.update()
            time.sleep(0.005)

    def _kartlar(self):
        from alis_ui import AlisFaturasiDialog, AlisIrsaliyesiDialog, AlisSiparisiDialog
        from satis_irsaliyesi_ui import SatisIrsaliyesiDialog
        from satis_siparisi_ui import SatisSiparisiKarti
        from teklif_ui import TeklifDialog

        return [
            ("Alış faturası", lambda: AlisFaturasiDialog(self.root)),
            ("Alış siparişi", lambda: AlisSiparisiDialog(self.root)),
            ("Alış irsaliyesi", lambda: AlisIrsaliyesiDialog(self.root)),
            ("Satış irsaliyesi", lambda: SatisIrsaliyesiDialog(self.root)),
            ("Alınan sipariş", lambda: SatisSiparisiKarti(self.root, cari=self._cari())),
            ("Teklif", lambda: TeklifDialog(self.root)),
        ]

    def _ac(self, yap):
        self.root.geometry("1x1+-3000+-3000")
        self.root.deiconify()
        with patch("ui_pencere.belge_penceresini_hazirla", lambda win, **_k: {}):
            d = yap()
        d.geometry("1500x850+-3000+-3000")
        d.deiconify()
        self._pompala(d, 0.4)
        return d

    @staticmethod
    def _tablo(d):
        return getattr(d, "satir_tablosu", None) or d.satir_tablo

    def _tus(self, d, w, tus):
        w.focus_force()
        self._pompala(d, 0.05)
        w.event_generate(tus)
        self._pompala(d, 0.3)

    def test_her_evrakta_acik_editor_varken_tik_ve_oklar(self):
        for ad, yap in self._kartlar():
            with self.subTest(evrak=ad):
                d = self._ac(yap)
                try:
                    giris = d._satir_ici_giris
                    for _ in range(2):
                        giris.son_islem = "secim"
                        giris.urun_ekle_fn(self.DEG, None)
                    self._pompala(d, 0.3)
                    self.assertEqual(len(d.satirlar), 2, ad)
                    hucre, tablo = d._hucre, self._tablo(d)
                    iids = veri_iidleri(tablo)
                    self.assertIs(hucre.duzenlenebilir_mi(0, "miktar"), True, ad)
                    hucre.duzenle(1, "miktar")
                    self._pompala(d)
                    hucre.editor.delete(0, "end")
                    hucre.editor.insert(0, "3")
                    bb = tablo.bbox(iids[0], "miktar")
                    _tikla(tablo, bb[0] + bb[2] // 2, bb[1] + bb[3] // 2)
                    self._pompala(d, 0.45)
                    self.assertEqual(Decimal(str(d.satirlar[1]["miktar"])), Decimal("3"), ad)
                    self.assertEqual(hucre._konum, (0, "miktar"), ad)
                    self.assertIsNotNone(hucre.editor, ad)
                    iids = veri_iidleri(tablo)  # bazı evraklar yenilemede satır kimliklerini değiştirir
                    self.assertEqual(tablo.selection(), (iids[0],), ad)
                    # ↓ / ↑ editörden satır değiştirir
                    self._tus(d, hucre.editor, "<Down>")
                    self.assertEqual(hucre._konum, (1, "miktar"), ad)
                    self._tus(d, hucre.editor, "<Up>")
                    self.assertEqual(hucre._konum, (0, "miktar"), ad)
                    # Tablo odaklıyken (editör açık kalmış olsa da) → ilk hücreyi açar
                    tablo.selection_set(veri_iidleri(tablo)[1])
                    self._tus(d, tablo, "<Right>")
                    self.assertIsNotNone(
                        hucre.editor,
                        f"{ad}: konum={hucre._konum} odak={d.tk.call('focus', '-lastfor', str(d))} "
                        f"secim={tablo.selection()}",
                    )
                    self.assertEqual(hucre._konum[0], 1, ad)
                    hucre.kapat()
                    # Giriş satırından ↑ son satıra, tabloda ↑ üst satıra
                    giris.odakla()
                    self._pompala(d, 0.3)
                    iids = veri_iidleri(tablo)
                    self._tus(d, giris.entry, "<Up>")
                    self.assertEqual(tablo.selection(), (iids[-1],), ad)
                    self._tus(d, tablo, "<Up>")
                    self.assertEqual(tablo.selection(), (iids[0],), ad)
                finally:
                    d.destroy()


if __name__ == "__main__":
    unittest.main()
