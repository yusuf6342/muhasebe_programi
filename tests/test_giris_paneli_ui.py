"""GİRİŞ paneli ve sabit gider ekranı — geçici test veritabanında arayüz davranışı (gerçek veri kullanılmaz)."""

from __future__ import annotations

import csv
import os
import tempfile
import tkinter as tk
import unittest
from datetime import date, timedelta
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import patch

from tests.stok_test_ortami import StokOrtami

import giris_paneli_ui as gp
from ana_panel_tema import para_tr
from database import giris_ozet_service as go
from database import sabit_gider_service as sg
from database.session_manager import oturum

D = Decimal


def _senkron(widget, is_fn, on_ok=None, on_err=None):
    try:
        sonuc = is_fn()
    except Exception as hata:  # noqa: BLE001
        if on_err:
            on_err(hata)
        return
    if on_ok:
        on_ok(sonuc)


class GirisPaneliUITest(unittest.TestCase):
    def setUp(self):
        self._ayar = tempfile.TemporaryDirectory(prefix="giris_ui_ayar_")
        self._env = patch.dict(os.environ, {"LOCALAPPDATA": self._ayar.name})
        self._env.start()
        self.o = StokOrtami("giris_ui")
        go.onbellegi_temizle()
        try:
            self.kok = tk.Tk()
        except tk.TclError as hata:
            self.o.kapat()
            self._env.stop()
            self.skipTest(f"Tk yok: {hata}")
        self.kok.withdraw()
        self.kok.icerik = tk.Frame(self.kok)
        self.kok.icerik.pack(fill="both", expand=True)
        self.kok._menu_islemi = lambda k: None
        self._bg = patch("ui_bg.arka_planda", _senkron)
        self._bg.start()

    def tearDown(self):
        self._bg.stop()
        self.kok.destroy()
        self.o.kapat()
        self._env.stop()
        self._ayar.cleanup()
        go.onbellegi_temizle()

    def panel(self) -> gp.GirisPaneli:
        gp.giris_paneli_goster(self.kok)
        p = self.kok._giris_paneli
        p.yenile()
        return p

    def fatura(self, tutar):
        from database.satis_faturasi_service import SatisFaturasiService

        bugun = date.today()
        f = SatisFaturasiService.kaydet(
            {"fatura_tarihi": bugun, "vade_tarihi": bugun, "cari_id": self.o.mus_id, "depo": "ANA DEPO",
             "odeme_tutari": D("0"), "sales_person_id": 1},
            [{"urun_kodu": "U001", "urun_adi": "Test Ürün", "miktar": D("1"), "birim": "Adet",
              "birim_fiyat": D(str(tutar)), "iskonto_orani": D("0"), "kdv_orani": D("20")}])
        SatisFaturasiService.onayla(f.id)

    def _pencereler(self):
        return [w for w in self.kok.winfo_children() if isinstance(w, gp.AyrintiPenceresi)] + [
            w for w in self.kok.icerik.winfo_children()[0].winfo_children() if isinstance(w, gp.AyrintiPenceresi)]

    def test_kart_ayrinti_toplami_ve_csv(self):
        self.o.alis(10, 10, date.today() - timedelta(days=30))
        self.fatura(1000)
        p = self.panel()
        net = p._sonuc["satis"]["satirlar"]["bugun"]["net"]
        self.assertEqual(net, D("1200.00"))
        self.assertEqual(p.kartlar[0]["deger"].cget("text"), para_tr(net))
        p.kartlar[0]["cmd"]()
        pencere = self._pencereler()[-1]
        self.assertEqual(gp._toplam(pencere._kalemler), net)
        yol = os.path.join(self._ayar.name, "ayrinti.csv")
        with patch("giris_paneli_ui.filedialog.asksaveasfilename", return_value=yol), \
                patch("giris_paneli_ui.messagebox.showinfo"):
            pencere.csv_kaydet()
        with open(yol, encoding="utf-8-sig") as f:
            satirlar = list(csv.reader(f, delimiter=";"))
        self.assertEqual(satirlar[0][0], "Kaynak")
        self.assertEqual(satirlar[-1][-1], para_tr(net))
        self.assertEqual(len(satirlar), 3)

    def test_eski_cevap_ve_mukerrer_calisma(self):
        p = self.panel()
        ilk = p._sonuc
        p._istek += 1
        p._geldi(p._istek - 1, {**ilk, "satis": None})
        self.assertIs(p._sonuc, ilk)
        sayac = []
        with patch("ui_bg.arka_planda", lambda *a, **k: sayac.append(1)):
            p.yenile()
            p.yenile()
            self.assertEqual(len(sayac), 1, "Aynı parametreyle süren hesap tekrar başlatılmamalı")
            p.yenile(zorla=True)
            self.assertEqual(len(sayac), 2)
        self.assertEqual(str(p.yenile_btn.cget("state")), "disabled")

    def test_hata_eski_veriyi_korur_ve_guncel_degil_der(self):
        p = self.panel()
        ilk = p._sonuc
        with patch.object(go, "ozet", side_effect=RuntimeError("bağlantı yok")):
            p.yenile(zorla=True)
        self.assertIs(p._sonuc, ilk)
        self.assertEqual(p.bayat_lbl.cget("text"), "Güncel değil")
        self.assertEqual(str(p.yenile_btn.cget("state")), "normal")

    def test_dar_ekranda_bolumler_alt_alta(self):
        p = self.panel()
        p._boyut(SimpleNamespace(width=900))
        self.assertEqual(int(p.k_tahsilat.grid_info()["row"]), 1)
        self.assertEqual(int(p.kartlar[2]["cerceve"].grid_info()["row"]), 1)
        p._boyut(SimpleNamespace(width=1500))
        self.assertEqual(int(p.k_tahsilat.grid_info()["column"]), 1)
        self.assertEqual(int(p.kartlar[3]["cerceve"].grid_info()["column"]), 3)

    def _metinler(self, w) -> list[str]:
        out = []
        for c in w.winfo_children():
            if isinstance(c, (tk.Label, tk.Button, tk.Radiobutton)):
                out.append(c.cget("text"))
            out += self._metinler(c)
        return out

    def test_yerlesim_ve_kaldirilan_bolumler(self):
        self.o.alis(10, 50, date.today() - timedelta(days=20))
        p = self.panel()
        p._boyut(SimpleNamespace(width=1500))
        # Satışlar solda, tahsilat sağda aynı satırda; borç tablosu altında tam genişlikte, tedarikçi hemen altında
        for kutu, yer in ((p.k_satis, (0, 0)), (p.k_tahsilat, (0, 1))):
            self.assertEqual((int(kutu.grid_info()["row"]), int(kutu.grid_info()["column"])), yer)
        sira = p.k_borc.master.pack_slaves()
        self.assertEqual(sira.index(p.k_borc), sira.index(p.orta_f) + 1)
        self.assertEqual(sira.index(p.k_tedarikci), sira.index(p.k_borc) + 1)
        self.assertEqual(p.k_borc.pack_info()["fill"], "x")
        metin = " ".join(self._metinler(p.ic))
        for yok in ("Bağlı ödeme planları", "Müşteri ödeme sözü", "Beklenen tahsilat", "Varlıklar",
                    "Finansal durum", "İzlenen net varlık"):
            self.assertNotIn(yok, metin)
        for gorunum in ("takvim", "bakiye"):
            p._takvim_gorunum.set(gorunum)
            p._borc_ciz()
            borc_metni = self._metinler(p.k_borc)
            self.assertNotIn("Tedarikçi açık borcu", borc_metni)
            self.assertNotIn("Tedarikçi borç bakiyesi", borc_metni)
        # Ayrı başlık: bugünün tarihi ve 600,00 TL; ayrıntı toplamı aynı
        ted_metni = self._metinler(p.k_tedarikci)
        self.assertIn(f"Bugün itibarıyla ({gp._tarih_tr(date.today())})", ted_metni)
        self.assertIn(para_tr(D("600.00")), ted_metni)
        p._ac("x", p._sonuc["tedarikci_acik"]["kalemler"])
        self.assertEqual(gp._toplam(self._pencereler()[-1]._kalemler), D("600.00"))
        # Ödeme yükü kartı tedarikçi borcunu içermez
        self.assertEqual(p.kartlar[3]["deger"].cget("text"), para_tr(D("0.00")))
        # Rapor tarihi değişse de tedarikçi bölümü bugünü gösterir
        p.tarih_e.delete(0, "end")
        p.tarih_e.insert(0, gp._tarih_tr(date.today() - timedelta(days=40)))
        p._tarih_degisti()
        self.assertEqual(p._sonuc["tedarikci_acik"]["tarih"], date.today())
        self.assertIn(para_tr(D("600.00")), self._metinler(p.k_tedarikci))

    def test_tedarikci_borcu_yoksa_sifir(self):
        p = self.panel()
        self.assertIn(para_tr(D("0.00")), self._metinler(p.k_tedarikci))

    def test_yetkisiz_kullanici_tutar_gormez(self):
        oturum.set_user(user_id=2, kullanici_adi="satis", ad_soyad="Satış", role_kod="SATIS", role_ad="Satış",
                        permissions={"satis_goruntuleme"})
        p = self.panel()
        for i in (2, 3):
            self.assertEqual(p.kartlar[i]["deger"].cget("text"), "Yetkisiz")
            self.assertIsNone(p.kartlar[i]["cmd"])
        metinler = [w.cget("text") for w in p.k_borc.govde.winfo_children() if isinstance(w, tk.Label)]
        self.assertEqual(metinler, ["Bu bölümü görüntüleme yetkiniz yok."])
        p._takvim_gorunum.set("bakiye")
        p._borc_ciz()
        metinler = [w.cget("text") for w in p.k_borc.govde.winfo_children() if isinstance(w, tk.Label)]
        self.assertEqual(metinler, ["Bu bölümü görüntüleme yetkiniz yok."])

    def test_sabit_gider_takvimde_ve_bakiye_gorunumu(self):
        sg.plan_kaydet({"kategori": "KIRA", "ad": "Kira", "odeme_gunu": 28, "tutar": "15000",
                        "baslangic_ay": date.today(), "periyot": "AYLIK"})
        p = self.panel()
        sabit = next(r for r in p._sonuc["borc"]["satirlar"] if r["kod"] == go.SABIT)
        self.assertEqual(sabit["ay3"], D("45000.00"))
        # Plan ödeme yüküdür, gerçek borç değildir
        self.assertEqual(p._sonuc["borc"]["planlanan_ek"]["ay3"], D("45000.00"))
        self.assertEqual(p._sonuc["borc"]["gercek_borc"], D("0.00"))
        p._takvim_gorunum.set("bakiye")
        p._borc_ciz()
        p._takvim_gorunum.set("takvim")
        p._borc_ciz()

    def test_gelecek_tarih_reddedilir(self):
        p = self.panel()
        p.tarih_e.delete(0, "end")
        p.tarih_e.insert(0, gp._tarih_tr(date.today() + timedelta(days=3)))
        with patch("giris_paneli_ui.messagebox.showwarning") as uyari:
            p._tarih_degisti()
        uyari.assert_called_once()
        self.assertEqual(p.tarih_e.get(), gp._tarih_tr(date.today()))
        self.assertEqual(p._sonuc["tarih"], date.today())

    def test_eski_giris_geri_donus_anahtari(self):
        import ana_panel_ui

        with patch.dict(os.environ, {"CIN_ESKI_GIRIS": "1"}), \
                patch.object(ana_panel_ui, "eski_giris_dashboard_goster") as eski:
            ana_panel_ui.giris_dashboard_goster(self.kok)
        eski.assert_called_once()
        with patch.dict(os.environ, {"CIN_ESKI_GIRIS": ""}), patch.object(gp, "giris_paneli_goster") as yeni:
            ana_panel_ui.giris_dashboard_goster(self.kok)
        yeni.assert_called_once()


class SabitGiderEkraniTest(unittest.TestCase):
    def setUp(self):
        self.o = StokOrtami("sabit_gider_ui")
        try:
            self.kok = tk.Tk()
        except tk.TclError as hata:
            self.o.kapat()
            self.skipTest(f"Tk yok: {hata}")
        self.kok.withdraw()

    def tearDown(self):
        self.kok.destroy()
        self.o.kapat()

    def test_form_kaydeder_ve_donem_uretir(self):
        from sabit_gider_ui import PlanFormu, SabitGiderPlanlariDialog

        d = SabitGiderPlanlariDialog(self.kok)
        f = PlanFormu(d, None, d._degisti)
        f.alan["kategori"].set("Kira")
        f.alan["ad"].insert(0, "Depo kirası")
        f.alan["gun"].set(5)
        f.alan["tutar"].insert(0, "12.500,00")
        with patch("sabit_gider_ui.messagebox.showwarning") as uyari:
            f.kaydet()
        uyari.assert_not_called()
        planlar = sg.plan_listesi()
        self.assertEqual([(p["ad"], p["tutar"]) for p in planlar], [("Depo kirası", D("12500.00"))])
        self.assertEqual(len(d.tablo.get_children()), 1)
        self.assertEqual(len(sg.plan_donemleri(planlar[0]["id"])), 3)

    def test_yetkisiz_kullanici_acamaz(self):
        from sabit_gider_ui import SabitGiderPlanlariDialog

        oturum.set_user(user_id=2, kullanici_adi="satis", ad_soyad="Satış", role_kod="SATIS", role_ad="Satış",
                        permissions={"satis_goruntuleme"})
        with self.assertRaises(PermissionError):
            SabitGiderPlanlariDialog(self.kok)


if __name__ == "__main__":
    unittest.main()
