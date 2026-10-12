"""Evrak klavye / özet ortak yardımcıları: üçlü iskonto, üst alan gezinme, cari arama Enter,
Borç / Alacak özeti metinleri ve tema önbelleği (veritabanı kullanmaz)."""

from __future__ import annotations

import sys
import time
import tkinter as tk
import unittest
from datetime import date
from decimal import Decimal
from pathlib import Path
from tkinter import ttk
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from cari_borc_alacak_ozet import OZET_SATIRLARI, ozet_metinleri
from satir_klavye import iskonto_birlestir, iskonto_parcalari


class IskontoMetinTest(unittest.TestCase):
    def test_parcalar_ve_birlestirme(self):
        self.assertEqual(iskonto_parcalari("10+5"), ["10", "5", "0"])
        self.assertEqual(iskonto_parcalari(""), ["0", "0", "0"])
        self.assertEqual(iskonto_birlestir(["10", "5", "0"]), "10+5")
        self.assertEqual(iskonto_birlestir(["10", "", "5"]), "10+0+5")
        self.assertEqual(iskonto_birlestir(["0", "0", "0"]), "0")


class BorcAlacakOzetMetinTest(unittest.TestCase):
    METRIK = {
        "bakiye": Decimal("1500"),
        "bakiye_yonu": "BORCLU",
        "toplam_borc": Decimal("2000"),
        "toplam_alacak": Decimal("500"),
        "odenen_ortalama_valor_gun": 12.0,
        "bakiye_ortalama_valor_gun": 7.5,
        "valor_turu": "BORC",
        "valor_turu_etiket": "Borç Valörü",
        "ortalama_valor_tarihi": date(2026, 9, 1),
        "son_islem_tarih": date(2026, 9, 2),
    }

    def test_cari_kart_satirlari_son_islem_ve_bekleyen_yok(self):
        m = ozet_metinleri(self.METRIK)
        self.assertEqual(tuple(m), OZET_SATIRLARI)
        self.assertFalse([b for b in m if "Son" in b or "Bekleyen" in b])
        self.assertEqual(m["Toplam borç"][0], "2.000,00 TL")
        self.assertEqual(m["Toplam alacak"][0], "500,00 TL")
        self.assertEqual(m["Kalan Bakiye"][0], "1.500,00 TL")
        self.assertEqual(m["Bakiye yönü"][0], "Borçlu")
        self.assertEqual(m["Ortalama borç kapatma süresi"][0], "12.0 gün")
        self.assertEqual(m["Ortalama Valör Tarihi"][0], "01.09.2026")
        self.assertEqual(m["Ortalama Valör Gün Sayısı"][0], "7.5 gün")

    def test_tedarikci_yonu_ve_bos_metrik(self):
        m = ozet_metinleri(dict(self.METRIK, bakiye_yonu=None), tedarikci_modu=True)
        self.assertEqual(m["Bakiye yönü"][0], "Alacaklı (tedarikçiye borcumuz)")
        self.assertEqual({v[0] for v in ozet_metinleri(None).values()}, {"—"})


class _TkTemel(unittest.TestCase):
    def setUp(self):
        try:
            self.root = tk.Tk()
        except tk.TclError as hata:
            self.skipTest(f"Tk yok: {hata}")
        self.root.geometry("600x400+-3000+-3000")
        self._pompala()

    def tearDown(self):
        try:
            self.root.destroy()
        except tk.TclError:
            pass

    def _pompala(self, sure=0.1):
        bitis = time.time() + sure
        while time.time() < bitis:
            self.root.update()

    def _odak(self, w=None):
        """Penceredeki son odak (uygulama arka plandayken de focus_set sonucunu verir)."""
        return odak_widget(w or self.root)


def odak_widget(w):
    yol = str(w.tk.call("focus", "-lastfor", str(w.winfo_toplevel())))
    try:
        return w.nametowidget(yol)
    except KeyError:
        return None


class BaslikGezinmeTest(_TkTemel):
    def _kur(self):
        from evrak_baslik_gezinme import baslik_gezinme_kur

        kap = ttk.Frame(self.root)
        kap.pack(fill="both", expand=True)
        sol = ttk.LabelFrame(kap, text="Sol")
        sol.grid(row=0, column=0, sticky="n")
        sag = ttk.LabelFrame(kap, text="Sağ")
        sag.grid(row=0, column=1, sticky="n")
        a, b = ttk.Entry(sol), ttk.Entry(sol)
        a.grid(row=0, column=0)
        b.grid(row=1, column=0)
        pasif = ttk.Entry(sol, state="disabled")
        pasif.grid(row=2, column=0)
        salt = ttk.Entry(sol)
        salt.grid(row=3, column=0)
        salt.configure(state="readonly")
        secim = ttk.Combobox(sag, values=("X", "Y"), state="readonly")
        secim.grid(row=0, column=0)
        c = ttk.Entry(sag)
        c.grid(row=1, column=0)
        self.son_cagri = []
        baslik_gezinme_kur(self.root, kap, son_hedef=lambda: self.son_cagri.append(True))
        self._pompala()
        return a, b, pasif, salt, secim, c

    def _tus(self, w, tus):
        w.focus_force()
        self._pompala(0.05)
        w.event_generate(tus)
        self._pompala(0.05)
        return self._odak()

    def test_panel_sirasi_pasif_ve_salt_okunur_atlanir(self):
        from evrak_baslik_gezinme import baslik_alanlari

        a, b, pasif, salt, secim, c = self._kur()
        self.assertEqual(baslik_alanlari(self.root), [a, b, secim, c])
        self.assertIs(self._tus(a, "<Return>"), b)
        self.assertIs(self._tus(b, "<Return>"), secim)
        self.assertIs(self._tus(secim, "<Right>"), c)
        self.assertIs(self._tus(c, "<Shift-Return>"), secim)
        self.assertIs(self._tus(secim, "<Left>"), b)
        self.assertIs(self._tus(secim, "<Down>"), c)
        self._tus(c, "<Return>")
        self.assertEqual(self.son_cagri, [True])

    def test_alanin_kendi_break_donusu_gezinmeyi_durdurur(self):
        a, b, *_ = self._kur()
        a.bind("<Return>", lambda _e: "break")
        self.assertIs(self._tus(a, "<Return>"), a)
        a.bind("<Return>", lambda _e: None)
        self.assertIs(self._tus(a, "<Return>"), b)


class UcluIskontoEditorTest(_TkTemel):
    def test_enter_ile_kutular_ve_bitis(self):
        from satir_klavye import UcluIskontoEditor

        tablo = ttk.Treeview(self.root, columns=("a",), show="headings")
        tablo.pack(fill="both", expand=True)
        self._pompala()
        sonuc = []
        ed = UcluIskontoEditor(
            tablo, (10, 10, 80, 22), ["10", "0", "0"],
            on_bitir=lambda d, h: (sonuc.append((d, h)), True)[1], on_iptal=lambda: None,
        )
        self._pompala()
        k1, k2, k3 = ed.kutular
        self.assertIs(self._odak(), k1)
        k1.focus_force()
        self._pompala(0.05)
        k1.event_generate("<Return>")
        self._pompala(0.05)
        self.assertIs(self._odak(), k2)
        k2.delete(0, "end")
        k2.insert(0, "5")
        k2.focus_force()
        k2.event_generate("<Tab>")
        self._pompala(0.05)
        self.assertIs(self._odak(), k3)
        k3.focus_force()
        k3.event_generate("<Return>")
        self._pompala(0.05)
        self.assertEqual(sonuc, [(["10", "5", "0"], "ileri")])
        k3.focus_force()
        k3.event_generate("<Down>")
        self._pompala(0.05)
        self.assertEqual(sonuc[-1][1], "asagi")


class CariAramaEnterTest(_TkTemel):
    def test_cozulmemis_metinde_enter_arar_secilide_gecer(self):
        from cari_arama_alani import CariAramaAlani

        entry = ttk.Entry(self.root)
        entry.pack()
        secili = {"ad": ""}
        alan = CariAramaAlani(
            self.root, entry, cari_turu="Tedarikçi", on_secim=lambda _c: None, on_temizle=lambda: None,
            secili_ad=lambda: secili["ad"], arka_plan=False,
        )
        self._pompala()
        entry.insert(0, "Ahm")
        with patch.object(alan, "_sorgu", return_value=[SimpleNamespace(cari_kodu="T1", unvan="Ahmet", id=1)]) as sorgu:
            self.assertEqual(alan._enter(), "break")
            sorgu.assert_called_once_with("Ahm")
        alan.kapat()
        secili["ad"] = "Ahm"
        self.assertIsNone(alan._enter())
        self.assertIsNone(alan._asagi())


class TemaOnbellekTest(_TkTemel):
    def test_fatura_ve_makbuz_stili_ikinci_kez_tema_degistirmez(self):
        import fatura_tema
        import satis_tema

        stil = ttk.Style(self.root)
        fatura_tema.stil_uygula(stil, self.root)
        tema = stil.theme_use()
        with patch.object(stil, "theme_use", wraps=stil.theme_use) as izle, \
                patch.object(stil, "configure", wraps=stil.configure) as yaz:
            fatura_tema.stil_uygula(stil, self.root)
        self.assertFalse([c for c in izle.call_args_list if c.args])
        yaz.assert_not_called()
        satis_tema.stil_uygula(stil, self.root, tema_koru=True)
        self.assertEqual(stil.theme_use(), tema)
        with patch.object(stil, "configure", wraps=stil.configure) as yaz:
            satis_tema.stil_uygula(stil, self.root, tema_koru=True)
        yaz.assert_not_called()


if __name__ == "__main__":
    unittest.main()
