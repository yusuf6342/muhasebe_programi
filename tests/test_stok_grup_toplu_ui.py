"""Toplu grup ekranı: gerçek Tk yerleşimi ve seçim/ön izleme akışı.

Başsız ortamda DISPLAY tanımlı bir X sunucusuyla çalıştırın.
"""

from __future__ import annotations

import sys
import tkinter as tk
import unittest
from pathlib import Path
from tkinter import ttk
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from database.session_manager import oturum
from stok_grup_toplu_ui import stok_grup_toplu_eslestirme_goster


def children(widget):
    for child in widget.winfo_children():
        yield child
        yield from children(child)


class App(tk.Tk):
    def __init__(self, width=1366, height=768, scale=1):
        super().__init__()
        self.tk.call("tk", "scaling", 4 / 3 * scale)
        self.geometry(f"{width}x{height}+0+0")
        tk.Frame(self, height=180).pack(fill="x")
        body = tk.Frame(self)
        body.pack(fill="both", expand=True)
        tk.Frame(body, width=220).pack(side="left", fill="y")
        self.icerik = tk.Frame(body)
        self.icerik.pack(side="left", fill="both", expand=True)
        self.menu_dugmeleri = {}
        self.update()

    def _icerigi_temizle(self):
        for child in self.icerik.winfo_children():
            child.destroy()

    def sayfa_goster(self, _page):
        self._icerigi_temizle()


class TopluGrupEkraniTest(unittest.TestCase):
    def setUp(self):
        oturum.firma_unvan = "Test Firması"
        self.rows = [dict(
            id=i, stok_kodu=f"U{i}", stok_adi=f"Test Ürün {i}", barkod="",
            birim="Adet", miktar=10, ana_grup="", tali_grup="", alt_grup="",
            aktif=True, grupsuz=True, uyari="",
        ) for i in range(1, 4)]
        self.patchers = [
            patch("stok_grup_toplu_ui.StokGrupService.listele", return_value=[
                dict(id=10, kod="AYAK", ad="Ayak", etiket="AYAK — Ayak")]),
            patch("stok_grup_toplu_ui.StokGrupTopluService.aday_listele", side_effect=self._list),
            patch("stok_grup_toplu_ui.StokGrupTopluService.islem_gecmisi", return_value=[]),
            patch("stok_grup_toplu_ui.messagebox.showerror"),
            patch("stok_grup_toplu_ui.messagebox.showinfo"),
        ]
        self.mocks = [p.start() for p in self.patchers]
        self.app = None

    def tearDown(self):
        if self.app:
            self.app.destroy()
        for p in reversed(self.patchers):
            p.stop()
        oturum.clear()

    def _list(self, **kwargs):
        rows = self.rows
        if kwargs.get("id_listesi") is not None:
            rows = [r for r in rows if r["id"] in kwargs["id_listesi"]]
        return dict(satirlar=rows, toplam=len(rows), gosterilen=len(rows))

    def _open(self, **kwargs):
        if self.app:
            self.app.destroy()
        self.app = App(**kwargs)
        stok_grup_toplu_eslestirme_goster(self.app)
        self.app.update()
        self.assertFalse(self.mocks[3].called, self.mocks[3].call_args)

    def _button(self, label):
        return next(w for w in children(self.app) if isinstance(w, tk.Button) and w.cget("text") == label)

    def _table(self):
        return next(w for w in children(self.app) if isinstance(w, ttk.Treeview) and "sec" in w.cget("columns"))

    def test_01_alt_dugmeler_her_olcekte_gorunur(self):
        for width, height in ((1366, 768), (1920, 1080)):
            for scale in (1, 1.25, 1.5):
                with self.subTest(width=width, scale=scale):
                    self._open(width=width, height=height, scale=scale)
                    rects = []
                    for label in ("Ön İzle", "Gruba Aktar", "Kapat"):
                        b = self._button(label)
                        self.assertTrue(b.winfo_ismapped())
                        rect = (b.winfo_rootx(), b.winfo_rooty(), b.winfo_width(), b.winfo_height())
                        self.assertGreaterEqual(rect[0], self.app.icerik.winfo_rootx())
                        self.assertLessEqual(rect[0] + rect[2], width)
                        self.assertLessEqual(rect[1] + rect[3], height)
                        rects.append(rect)
                    for i, a in enumerate(rects):
                        for b in rects[i + 1:]:
                            self.assertFalse(a[0] < b[0]+b[2] and b[0] < a[0]+a[2]
                                             and a[1] < b[1]+b[3] and b[1] < a[1]+a[3])
                    self.assertGreater(self._table().winfo_height(), 60)
                    self.app.destroy()
                    self.app = None

    def test_02_satir_vurgusu_secim_degildir_onizleme_gecersizlesir(self):
        self._open()
        table = self._table()
        table.selection_set("1")
        x, y, width, height = table.bbox("1", "ad")
        table.event_generate("<ButtonRelease-1>", x=x+5, y=y+height//2)
        self.app.update()
        self.assertEqual(table.item("1", "values")[0], "☐")
        x, y, width, height = table.bbox("1", "sec")
        table.event_generate("<ButtonRelease-1>", x=x+width//2, y=y+height//2)
        self.app.update()
        self.assertEqual(table.item("1", "values")[0], "☑")
        targets = [w for w in children(self.app) if isinstance(w, ttk.Combobox)
                   and str(w.cget("state")) == "readonly" and w.get() == ""
                   and "AYAK — Ayak" in w.cget("values")]
        targets[0].set("AYAK — Ayak")
        targets[0].event_generate("<<ComboboxSelected>>")
        preview = dict(
            hedef_yol="Ayak", politika="sadece_grupsuz", satirlar=[],
            ozet=dict(secilen=1, guncellenecek=1, degismeyecek=0, atlanacak=0, hatali=0, yetki_yok=0),
        )
        with patch("stok_grup_toplu_ui.StokGrupTopluService.onizle", return_value=preview):
            self._button("Ön İzle").invoke()
        self.app.update()
        self.assertEqual(str(self._button("Gruba Aktar").cget("state")), "normal")
        radio = next(w for w in children(self.app) if isinstance(w, ttk.Radiobutton)
                     and w.cget("text") == "Seçilenlerin grubunu değiştir")
        radio.invoke()
        self.assertEqual(str(self._button("Gruba Aktar").cget("state")), "disabled")

    def test_03_yalniz_secili_bos_ise_tum_stoklar_gelmez(self):
        self._open()
        cb = next(w for w in children(self.app) if isinstance(w, ttk.Checkbutton)
                  and w.cget("text") == "Yalnız seçili ürünler")
        cb.invoke()
        self.assertEqual(self._table().get_children(), ())

    def test_04_sag_panel_geri_al_dugmesine_kaydirilabilir(self):
        self._open(height=768)
        button = self._button("Seçili İşlemi Geri Al")
        canvas = next(w for w in children(self.app) if isinstance(w, tk.Canvas))
        canvas.yview_moveto(1)
        self.app.update()
        self.assertGreaterEqual(button.winfo_rooty(), canvas.winfo_rooty())
        self.assertLessEqual(button.winfo_rooty()+button.winfo_height(), canvas.winfo_rooty()+canvas.winfo_height())


if __name__ == "__main__":
    unittest.main(verbosity=2)
