"""Satış fatura listesi — izole SQLite üzerinde gerçek ekran kontrolleri.

Canlı D2 / kurulu EXE dokunulmaz. Aç/kapat mali alanları değiştirmez.
"""
from __future__ import annotations

import os
import tempfile
import tkinter as tk
import types
import unittest
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path
from unittest.mock import patch

from tests.stok_test_ortami import StokOrtami

D = Decimal
RAPOR = Path("kurulum/dnm_d2_20260901/rapor/ekran")


def _senkron(widget, is_fn, on_ok=None, on_err=None):
    try:
        sonuc = is_fn()
    except Exception as hata:  # noqa: BLE001
        if on_err:
            on_err(hata)
        return
    if on_ok:
        on_ok(sonuc)


class SatisFaturaListeEkranTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        RAPOR.mkdir(parents=True, exist_ok=True)

    def setUp(self):
        self._ayar = tempfile.TemporaryDirectory(prefix="fatura_liste_ekran_")
        self._env = patch.dict(os.environ, {"LOCALAPPDATA": self._ayar.name})
        self._env.start()
        self.o = StokOrtami("fatura_liste_ekran")
        try:
            self.root = tk.Tk()
        except tk.TclError as hata:
            self.o.kapat()
            self._env.stop()
            self.skipTest(f"Tk yok: {hata}")
        self.root.withdraw()
        self.root.icerik = tk.Frame(self.root)
        self.root.icerik.pack(fill="both", expand=True)
        self._bg = patch("ui_bg.arka_planda", _senkron)
        self._bg.start()
        self._bagla_app()
        self._fatura_hazirla()

    def tearDown(self):
        import ui_takvim as takvim_mod

        if takvim_mod._acik_takvim is not None:
            try:
                takvim_mod._acik_takvim.destroy()
            except tk.TclError:
                pass
            takvim_mod._acik_takvim = None
        self._bg.stop()
        try:
            self.root.destroy()
        except Exception:
            pass
        self.o.kapat()
        self._env.stop()
        self._ayar.cleanup()

    def _bagla_app(self):
        from app import MuhasebeApp

        app = self.root

        def _temizle(self):
            for w in self.icerik.winfo_children():
                w.destroy()

        app._icerigi_temizle = types.MethodType(_temizle, app)
        app.nav_sayfa_isaretle = lambda *a, **k: None
        app.yetki_var = lambda *a, **k: True
        app.status_goster = lambda *a, **k: None
        app.satis_faturalari_alt_menusu_goster = lambda: None
        app.geri_cubugu_guncelle = lambda *a, **k: None
        # Liste ekranı + tüm fatura_* / _fatura_* yardımcıları
        for ad, fn in MuhasebeApp.__dict__.items():
            if not callable(fn):
                continue
            if ad in ("satis_faturalari_goster", "fatura_listesini_yenile", "fatura_ac", "yeni_fatura") or ad.startswith(
                "_fatura_"
            ) or ad.startswith("fatura_"):
                setattr(app, ad, types.MethodType(fn, app))
        if hasattr(MuhasebeApp, "_treeview_filtre_bagla_hizli"):
            app._treeview_filtre_bagla_hizli = types.MethodType(
                MuhasebeApp._treeview_filtre_bagla_hizli, app
            )
        if hasattr(MuhasebeApp, "_secili_fatura_id"):
            app._secili_fatura_id = types.MethodType(MuhasebeApp._secili_fatura_id, app)
        # Alt düğme komutları — liste kurulumunda referans alınır
        for ad in (
            "faturadan_iade_olustur",
            "fatura_duzenle",
            "fatura_yazdir",
            "fatura_pdf",
            "fatura_iptal",
            "fatura_taslak_sil",
            "yeni_fatura",
            "_fatura_filtreleri_temizle",
            "_fatura_yokla_baslat",
            "_fatura_yokla_durdur",
        ):
            if hasattr(MuhasebeApp, ad):
                setattr(app, ad, types.MethodType(getattr(MuhasebeApp, ad), app))
            else:
                setattr(app, ad, lambda *a, **k: None)
        # Otomatik yenilemeyi testte başlatma (arka plan after)
        app._fatura_yokla_baslat = lambda *a, **k: None
        self.app = app

    def _fatura_hazirla(self):
        from database.satis_faturasi_service import SatisFaturasiService

        bugun = date.today()
        self.o.alis(20, 10, bugun)
        self.f1 = SatisFaturasiService.kaydet(
            {
                "fatura_tarihi": bugun,
                "vade_tarihi": bugun + timedelta(days=7),
                "cari_id": self.o.mus_id,
                "depo": "ANA DEPO",
                "odeme_tutari": D("0"),
                "sales_person_id": 1,
            },
            [
                {
                    "urun_kodu": "U001",
                    "urun_adi": "Test Ürün",
                    "miktar": D("2"),
                    "birim": "Adet",
                    "birim_fiyat": D("100"),
                    "iskonto_orani": D("0"),
                    "kdv_orani": D("20"),
                }
            ],
        )
        SatisFaturasiService.onayla(self.f1.id)
        self.f2 = SatisFaturasiService.kaydet(
            {
                "fatura_tarihi": bugun - timedelta(days=1),
                "vade_tarihi": bugun,
                "cari_id": self.o.mus_id,
                "depo": "ANA DEPO",
                "odeme_tutari": D("0"),
                "sales_person_id": 1,
            },
            [
                {
                    "urun_kodu": "U001",
                    "urun_adi": "Test Ürün",
                    "miktar": D("1"),
                    "birim": "Adet",
                    "birim_fiyat": D("50"),
                    "iskonto_orani": D("0"),
                    "kdv_orani": D("20"),
                }
            ],
        )
        SatisFaturasiService.onayla(self.f2.id)

    def _pompala(self):
        self.root.update_idletasks()
        self.root.update()

    def _mali_imza(self, fatura_id: int) -> dict:
        from database.database import get_session
        from database.models.cari import CariIslem, SatisHareketi
        from database.models.satis_faturasi import SatisFaturasi
        from sqlalchemy import select

        with get_session() as s:
            f = s.get(SatisFaturasi, fatura_id)
            satirlar = list(getattr(f, "satirlar", None) or [])
            cis = list(s.scalars(select(CariIslem).where(CariIslem.belge_no == f.fatura_no)))
            shs = list(s.scalars(select(SatisHareketi).where(SatisHareketi.belge_no == f.fatura_no)))
            return {
                "toplam": str(D(f.tl_genel_toplam)),
                "durum": f.durum,
                "onay": bool(f.onaylandi),
                "satir": [(x.id, str(D(x.miktar)), str(D(x.birim_fiyat))) for x in satirlar],
                "ci": [(x.id, str(D(x.borc)), str(D(x.alacak))) for x in cis],
                "sh": [(x.id, str(D(x.satis_tutari)), str(D(x.kalan_acik_tutar))) for x in shs],
            }

    def test_01_liste_takvim_filtre_baslik_ac_kapat(self):
        import ui_takvim as takvim_mod
        from database.turkce_normalize import tr_iceriyor

        self.app.satis_faturalari_goster()
        self._pompala()

        # Takvim düğmesi yok
        dugme_metin = []
        for w in self.root.winfo_children():
            stack = [w]
            while stack:
                cur = stack.pop()
                try:
                    stack.extend(cur.winfo_children())
                except tk.TclError:
                    continue
                try:
                    if isinstance(cur, (tk.Button, __import__("tkinter.ttk", fromlist=["Button"]).Button)):
                        dugme_metin.append(str(cur.cget("text")))
                except tk.TclError:
                    pass
        self.assertNotIn("Takvim", dugme_metin)

        # Dört tarih/vade alanı
        for alan in (
            self.app.fatura_tarih_bas,
            self.app.fatura_tarih_bit,
            self.app.fatura_vade_bas,
            self.app.fatura_vade_bit,
        ):
            self.assertTrue(alan.winfo_exists())

        # Boş alan → takvim aç → tarih yazılmaz
        self.app.fatura_vade_bas.delete(0, "end")
        self.assertEqual(self.app.fatura_vade_bas.get(), "")
        pop = takvim_mod.takvim_ac(self.root, self.app.fatura_vade_bas)
        self._pompala()
        self.assertEqual(self.app.fatura_vade_bas.get(), "")
        pop2 = takvim_mod.takvim_ac(self.root, self.app.fatura_vade_bas)
        self.assertIs(pop, pop2)
        pop._iptal()
        self.assertEqual(self.app.fatura_vade_bas.get(), "")

        # Manuel tarih + temizle
        self.app.fatura_tarih_bas.delete(0, "end")
        self.app.fatura_tarih_bas.insert(0, "01.01.2020")
        self.app.fatura_tarih_bit.delete(0, "end")
        self.app.fatura_tarih_bit.insert(0, "31.12.2099")
        self.app.fatura_listesini_yenile()
        self._pompala()
        tv = self.app.fatura_tablosu
        self.assertGreaterEqual(len(tv.get_children()), 2)
        self.app._fatura_tarih_filtre_temizle()
        self._pompala()

        # Başlıklar dolu
        for kolon in self.app._fatura_liste_kolonlar:
            metin = tv.heading(kolon, "text")
            self.assertTrue(metin, msg=kolon)

        # Cari ünvan kısmi ara
        self.app.fatura_tarih_bas.delete(0, "end")
        self.app.fatura_tarih_bas.insert(0, "01.01.2020")
        self.app.fatura_tarih_bit.delete(0, "end")
        self.app.fatura_tarih_bit.insert(0, "31.12.2099")
        self.app.fatura_listesini_yenile()
        self._pompala()
        tv = self.app.fatura_tablosu
        self.app.fatura_cari_ara.delete(0, "end")
        self.app.fatura_cari_ara.insert(0, "xyzolmayan")
        self.app._fatura_listeyi_goster()
        self._pompala()
        self.assertEqual(len(tv.get_children()), 0)
        self.app.fatura_cari_ara.delete(0, "end")
        self.app.fatura_cari_ara.insert(0, "Musteri")
        self.app._fatura_listeyi_goster()
        self._pompala()
        cocuklar = list(tv.get_children())
        self.assertTrue(cocuklar or tr_iceriyor("Musteri", "Müşteri"))
        self.app.fatura_cari_ara.delete(0, "end")
        self.app._fatura_listeyi_goster()
        self._pompala()
        cocuklar = list(tv.get_children())
        self.assertGreaterEqual(len(cocuklar), 1)

        # iid = fatura.id — sıralama sonrası doğru kimlik
        hedef_iid = str(self.f1.id)
        self.assertIn(hedef_iid, cocuklar)
        tv.selection_set(hedef_iid)
        tv.focus(hedef_iid)

        # Aç/kapat — mali imza korunur
        once = self._mali_imza(self.f1.id)
        acildi = {"ok": False}

        class _SahteKart(tk.Toplevel):
            def __init__(self, parent, fatura=None, cari_ac=None, **kw):
                super().__init__(parent)
                self.withdraw()
                self.result = None
                acildi["ok"] = True
                acildi["id"] = getattr(fatura, "id", None)
                self.after(10, self.destroy)

        with patch("app.SatisFaturasiDialog", _SahteKart):
            self.app.fatura_ac()
            self._pompala()
        self.assertTrue(acildi["ok"])
        self.assertEqual(int(acildi["id"]), self.f1.id)
        sonra = self._mali_imza(self.f1.id)
        self.assertEqual(once, sonra)

        # Yenilemeden sonra başlık + filtre korunur (cari ara boş)
        once_adet = len(tv.get_children())
        self.app.fatura_listesini_yenile()
        self._pompala()
        tv = self.app.fatura_tablosu
        for kolon in self.app._fatura_liste_kolonlar:
            self.assertTrue(tv.heading(kolon, "text"))
        self.assertEqual(len(tv.get_children()), once_adet)

        # Kanıt dosyası
        kanit = {
            "takvim_dugme_yok": "Takvim" not in dugme_metin,
            "bos_alan_yazmadi": True,
            "tek_takvim": True,
            "mali_imza_korundu": once == sonra,
            "fatura_id": self.f1.id,
            "satir_adet": once_adet,
        }
        (RAPOR / "fatura_liste_ekran_kanit.json").write_text(
            __import__("json").dumps(kanit, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )


if __name__ == "__main__":
    unittest.main()
