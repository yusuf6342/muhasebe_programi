"""Ekran kontrolü: muhasebe kolonlu 13 liste, Finans İşlem Ayarları ve kart muhasebe hesabı ekranları.

Her listede: muhasebe kolonu dolu, eksik ayarlı evrak 'İnceleme gerekiyor', başarılı evrakın 'Muhasebe Fişi'
yolu evrakın kendi fişini açar. Yalıtılmış geçici veritabanında çalışır. ``MUHASEBE_EKRAN_DIZINI`` tanımlıysa
(veya C:\\CinMuhasebeBuild4\\ekran varsa) ekran görüntüleri ``muhasebe_*.png`` olarak kaydedilir.
"""

from __future__ import annotations

import os
import sys
import time
import tkinter as tk
from decimal import Decimal
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

from sqlalchemy import select  # noqa: E402

import test_muhasebe_hesap_baglantilari as thb  # noqa: E402
import test_muhasebelestirme_finans_ayarlari as tfa  # noqa: E402
from database.database import get_session  # noqa: E402
from database.models.genel_muhasebe import (  # noqa: E402
    BELGE_BEKLIYOR,
    BELGE_INCELEME,
    BELGE_MUHASEBELESTIRILDI,
)

TARIH = tfa.TARIH
D = Decimal
_agac, _buton = tfa._agac, tfa._buton


def _ekran_dizini() -> Path | None:
    yol = os.environ.get("MUHASEBE_EKRAN_DIZINI") or r"C:\CinMuhasebeBuild4\ekran"
    p = Path(yol)
    return p if p.parent.exists() else None


class _EkranTemel(thb._Temel):
    def setUp(self):
        thb._Temel.setUp(self)
        try:
            self.root = tk.Tk()
        except tk.TclError as hata:
            self.skipTest(f"Tk yok: {hata}")
        self.root.geometry("1280x760+20+20")
        self.root.title("Cin Muhasebe — ekran testi")
        self.bilgiler: list[str] = []
        self._mb = patch.multiple("tkinter.messagebox", showinfo=lambda _b, m, **_k: self.bilgiler.append(m),
                                  showerror=self._mesaj_hatasi, showwarning=lambda *a, **k: None,
                                  askyesno=lambda *a, **k: True)
        self._mb.start()
        self.acilan_fisler: list[int] = []
        self._fd = patch("genel_muhasebe_ui.FisDialog",
                         lambda _p, fis_id=None, **_k: self.acilan_fisler.append(int(fis_id)))
        self._fd.start()
        self._menu = [patch("finans_ui._finans_menu_isaretle", lambda _a: None),
                      patch("gelir_gider_ui._menu_isaretle", lambda _a: None)]
        for m in self._menu:
            m.start()
        self.app = tfa._SahteApp(self.root)

    def tearDown(self):
        for m in (*self._menu, self._fd, self._mb):
            m.stop()
        try:
            self.root.destroy()
        except tk.TclError:
            pass
        thb._Temel.tearDown(self)

    def _mesaj_hatasi(self, baslik, metin, **_k):
        raise AssertionError(f"Beklenmeyen hata penceresi: {baslik}: {metin}")

    def _ekran(self, ad: str, pencere=None) -> None:
        dizin = _ekran_dizini()
        if dizin is None:
            return
        w = pencere or self.root
        try:
            from PIL import ImageGrab

            w.deiconify()
            w.lift()
            w.attributes("-topmost", True)
            for _ in range(6):
                w.update()
                time.sleep(0.1)
            dizin.mkdir(parents=True, exist_ok=True)
            x, y = w.winfo_rootx(), w.winfo_rooty()
            ImageGrab.grab(bbox=(x, y, x + w.winfo_width(), y + w.winfo_height())).save(
                dizin / f"muhasebe_{ad}.png")
            w.attributes("-topmost", False)
        except Exception as hata:  # ekran görüntüsü alınamazsa test yine geçerli
            print(f"ekran görüntüsü alınamadı ({ad}): {hata}")

    def _fis_dogru(self, evrak: str, kaynak_id: int) -> None:
        """Son açılan fiş evrakın kendi fişi mi (kaynak eşleşmesi)."""
        d = self._durum(evrak, kaynak_id)
        self.assertEqual(self.acilan_fisler[-1], d["fis_id"])
        self.assertEqual(self._kaynak_fisi(d["fis_id"]), (evrak, int(kaynak_id)))

    @staticmethod
    def _kimlik(belge_no) -> int:
        from database.models.finans import FinansEvrakKimligi

        with get_session() as s:
            return int(s.scalar(select(FinansEvrakKimligi.id).where(FinansEvrakKimligi.belge_no == belge_no)))

    def _kolon(self, sutun="muhasebe") -> dict[str, str]:
        tablo = _agac(self.app.icerik)
        self.assertIsNotNone(tablo)
        return {iid: tablo.set(iid, sutun) for iid in tablo.get_children()}


class FaturaVeFisListeleriEkranTest(_EkranTemel):
    def test_satis_alis_hizmet_gider_iade_listeleri(self):
        import gelir_gider_ui
        import gider_fisi_ui
        from database.alis_iade_faturasi_service import AlisIadeFaturasiService
        from database.satis_iade_faturasi_service import SatisIadeFaturasiService
        from fatura_liste_pencere import DOC_ALIS, DOC_SATIS, FaturaListePencere
        from muhasebe_durum_ui import fisi_ac

        self._ayar("otomatik")
        a1, alis_satir = self._alis("U001", "100", "100", "LOT-A")
        f1 = self._sat("5")
        g1, _ = self._gider("400")
        gf = self._gider_fisi("250")
        self._ayar("sonradan")
        f2 = self._sat("3")
        si = SatisIadeFaturasiService.kaydet(
            {"iade_tarihi": TARIH, "cari_id": self.musteri_id, "kaynak_fatura_id": None, "depo": "ANA DEPO",
             "aciklama": None, "iade_odeme_tutari": 0},
            [{"urun_kodu": "U001", "urun_adi": "U001", "miktar": D("1"), "birim": "Adet", "birim_fiyat": D("200"),
              "iskonto_orani": D("0"), "kdv_orani": D("20")}])
        ai = AlisIadeFaturasiService.kaydet_ve_onayla(
            {"iade_tarihi": TARIH, "cari_id": self.tedarikci_id, "depo": "ANA DEPO"},
            [{"urun_kodu": "U001", "urun_adi": "Test Ürün", "miktar": D("2"), "birim_fiyat": D("100"),
              "kdv_orani": D("20"), "kaynak_fatura_satiri_id": alis_satir}])

        # 1-2. Satış / alış faturası listesi
        for doc, beklenen, ad in ((DOC_SATIS, {str(f1): BELGE_MUHASEBELESTIRILDI, str(f2): BELGE_BEKLIYOR}, "satis"),
                                  (DOC_ALIS, {str(a1): BELGE_MUHASEBELESTIRILDI}, "alis")):
            kart = tk.Toplevel(self.root)
            kart.withdraw()
            kart.bagli_listeden_fatura_ac = lambda *_a, **_k: None
            with patch("fatura_liste_pencere._prefs_yukle", return_value={}):
                p = FaturaListePencere(kart, document_type=doc)
            p.tarih_bas.delete(0, "end")
            p.tarih_bas.insert(0, "01.01.2026")
            p.tarih_bit.delete(0, "end")
            p.tarih_bit.insert(0, "31.12.2026")
            p.yenile()
            durumlar = {iid: p.tablo.set(iid, "muhasebe") for iid in p.tablo.get_children()}
            for iid, durum in beklenen.items():
                self.assertEqual(durumlar.get(iid), durum, ad)
            p.transient(self.root)
            p.geometry("1250x650+30+30")
            self._ekran(f"{ad}_fatura_listesi", p)
            p.destroy()
        fisi_ac(self.root, "satis_faturasi", f1)
        self._fis_dogru("satis_faturasi", f1)
        fisi_ac(self.root, "alis_faturasi", a1)
        self._fis_dogru("alis_faturasi", a1)

        # 3. Hizmet faturası
        gelir_gider_ui.hizmet_faturalari_sayfasi(self.app, "GIDER")
        self.assertEqual(self._kolon()[str(g1)], BELGE_MUHASEBELESTIRILDI)
        self._ekran("hizmet_faturasi_listesi")
        fisi_ac(self.root, "hizmet_faturasi", g1)
        self._fis_dogru("hizmet_faturasi", g1)

        # 4. Gider fişi: listedeki 'Muhasebe Fişi' düğmesi
        gider_fisi_ui.gider_fisleri_sayfasi(self.app)
        self.assertEqual(self._kolon()[str(gf)], BELGE_MUHASEBELESTIRILDI)
        _agac(self.app.icerik).selection_set(str(gf))
        _buton(self.app.icerik, "Muhasebe Fişi").invoke()
        self._fis_dogru("gider_fisi", gf)
        self._ekran("gider_fisi_listesi")

        # 5-6. Satış / alış iade listeleri (App yöntemleri sahte uygulamaya bağlanır)
        import app as app_modul

        sahte = self.app
        for ad in ("satis_iade_faturalari_goster", "iade_listesini_yenile", "alis_iade_faturalari_goster",
                   "yeni_iade", "iade_ac", "iade_iptal", "_secili_iade_id"):
            setattr(sahte, ad, getattr(app_modul.MuhasebeApp, ad).__get__(sahte))
        sahte.satis_iade_faturalari_goster()
        self.assertEqual(self._kolon()[str(si.id)], BELGE_BEKLIYOR)
        self._ekran("satis_iade_listesi")
        sahte.alis_iade_faturalari_goster()
        self.assertEqual(self._kolon()[str(ai.id)], BELGE_BEKLIYOR)
        _agac(self.app.icerik).selection_set(str(ai.id))
        _buton(self.app.icerik, "Muhasebe Fişi").invoke()
        self.assertIn("Bekliyor", self.bilgiler[-1], "fişi olmayan evrakta durum ve neden gösterilir")
        self._ekran("alis_iade_listesi")


class FinansListeleriEkranTest(_EkranTemel):
    def _hazirla(self):
        from database import muhasebe_finans_ayarlari as fa
        from database.models.finans import KrediKartiTanimi
        from database.models.genel_muhasebe import MuhasebeHesapEsleme

        self._ayar("otomatik")
        self._hesap_bagla("pos_valor_alacagi", "pos_komisyon_gideri", "sirket_kart_borcu")
        with get_session() as s:
            for e in s.scalars(select(MuhasebeHesapEsleme).where(MuhasebeHesapEsleme.anahtar == "banka")).all():
                s.delete(e)
        self.akbank = self._banka_karti("Akbank")
        self.garanti = self._banka_karti("Garanti")  # kart hesabı yok, firma varsayılanı yok → inceleme
        fa.kart_hesabi_kaydet(self.akbank["MEVDUAT"], self._hesap_ac("102.01.0002", "Akbank TL Vadesiz"))
        fa.kart_hesabi_kaydet(self.akbank["KMH"], self._hesap_ac("300.01.0001", "Akbank KMH", "Pasif"))
        with get_session() as s:
            from database.models.finans import FinansHesabi

            s.get(FinansHesabi, self.akbank["MEVDUAT"]).acilis_bakiyesi = D("50000")
            kk = KrediKartiTanimi(banka_karti_id=self.akbank["kart"], kart_adi="Şirket Kartı",
                                  kart_limiti=D("50000"), aktif=True)
            s.add(kk)
            s.flush()
            self.kk_id = int(kk.id)

    def test_virman_havale_kart_odeme_pos_listeleri_inceleme_ve_fis(self):
        import finans_ui
        from database.finans_service import FinansService

        self._hazirla()
        kasa = self._kasa()
        kby = FinansService.kasadan_bankaya_yatan(kasa, self.akbank["MEVDUAT"], TARIH, D("1000"))
        bnc = FinansService.bankadan_nakit_cekilen(self.akbank["MEVDUAT"], kasa, TARIH, D("300"))
        bvr = FinansService.banka_hesaplari_arasi_virman(self.akbank["MEVDUAT"], self.akbank["KMH"], TARIH, D("500"))
        ahv = FinansService.alinan_havale(self.akbank["MEVDUAT"], TARIH, D("250"), cari_id=self.musteri_id)
        ahv_inc = FinansService.alinan_havale(self.garanti["MEVDUAT"], TARIH, D("90"), cari_id=self.musteri_id)
        ghv = FinansService.gonderilen_havale(self.akbank["MEVDUAT"], TARIH, D("120"), cari_id=self.tedarikci_id)
        kko = FinansService.kredi_karti_odeme(self.akbank["kart"], self.kk_id, self.tedarikci_id, TARIH, D("700"))
        pos = FinansService.pos_tahsilat(self.akbank["kart"], TARIH, D("1000"), cari_id=self.musteri_id)

        # 7-8. Kasa ↔ banka virman
        finans_ui.kasadan_bankaya_yatirilan_sayfasi_goster(self.app)
        self.assertEqual(self._kolon()[kby], BELGE_MUHASEBELESTIRILDI)
        self._ekran("kasa_banka_virman_listesi")
        finans_ui._muhasebe_fisi_belge_no(self.root, "kasa_banka_virman", kby)
        self._fis_dogru("kasa_banka_virman", self._kimlik(kby))
        finans_ui.bankadan_cekilen_sayfasi_goster(self.app)
        self.assertEqual(self._kolon()[bnc], BELGE_MUHASEBELESTIRILDI)

        # 9. Bankalar arası virman
        finans_ui.bankalar_arasi_virman_sayfasi_goster(self.app)
        self.assertEqual(self._kolon()[bvr], BELGE_MUHASEBELESTIRILDI)
        self._ekran("bankalar_arasi_virman_listesi")
        finans_ui._muhasebe_fisi_belge_no(self.root, "kasa_banka_virman", bvr)
        self._fis_dogru("kasa_banka_virman", self._kimlik(bvr))

        # 10-11. Alınan / gönderilen havale: kart hesabı olmayan banka → İnceleme gerekiyor
        finans_ui.alinan_havale_sayfasi_goster(self.app)
        kolon = self._kolon()
        self.assertEqual(kolon[ahv], BELGE_MUHASEBELESTIRILDI)
        self.assertEqual(kolon[ahv_inc], BELGE_INCELEME)
        self._ekran("alinan_havale_listesi")
        finans_ui._muhasebe_fisi_belge_no(self.root, "banka_havale", ahv)
        self._fis_dogru("banka_havale", self._kimlik(ahv))
        once = len(self.acilan_fisler)
        finans_ui._muhasebe_fisi_belge_no(self.root, "banka_havale", ahv_inc)
        self.assertEqual(len(self.acilan_fisler), once, "incelemedeki evrakta fiş açılmaz")
        self.assertIn("İnceleme gerekiyor", self.bilgiler[-1])
        self.assertIn("muhasebe hesabı seçilmemiş", self.bilgiler[-1])
        finans_ui.gonderilen_havale_sayfasi_goster(self.app)
        self.assertEqual(self._kolon()[ghv], BELGE_MUHASEBELESTIRILDI)
        self._ekran("gonderilen_havale_listesi")

        # 12. Şirket kartı ile ödeme
        finans_ui.kredi_karti_odeme_sayfasi_goster(self.app)
        self.assertEqual(self._kolon()[kko["belge_no"]], BELGE_MUHASEBELESTIRILDI)
        self._ekran("sirket_karti_odeme_listesi")

        # 13. POS tahsilatı
        finans_ui.kredi_karti_pos_tahsilat_sayfasi_goster(self.app)
        self.assertEqual(self._kolon()[pos["belge_no"]], BELGE_MUHASEBELESTIRILDI)
        self._ekran("pos_tahsilat_listesi")
        from muhasebe_durum_ui import fisi_ac

        fisi_ac(self.root, "pos_tahsilat", int(pos["kayit_id"]))
        self._fis_dogru("pos_tahsilat", int(pos["kayit_id"]))

    def test_kasa_makbuzu_listesi_kolon_ve_muhasebe_fisi_dugmesi(self):
        import kasa_makbuz_ui
        from database.finans_service import FinansService

        self._ayar("otomatik")
        kasa = self._kasa()
        m = FinansService.kasa_tahsilat_makbuzu_kaydet({
            "tarih": TARIH, "cari_id": self.musteri_id, "makbuz_no_otomatik": True,
            "satirlar": [{"odeme_sekli": "NAKİT / KASA", "finans_hesap_id": kasa, "tutar": "40"}]})
        def senkron(_w, is_fn, on_ok=None, on_err=None):
            try:
                sonuc = is_fn()
            except BaseException as hata:  # noqa: BLE001
                if on_err:
                    on_err(hata)
                return
            if on_ok:
                on_ok(sonuc)

        with patch("ui_bg.arka_planda", senkron):
            kasa_makbuz_ui.kasa_makbuzlari_sayfasi(self.app)
        tablo = _agac(self.app.icerik)
        kolon = self._kolon()
        self.assertEqual(kolon.get(str(m.id)), BELGE_MUHASEBELESTIRILDI, kolon)
        tablo.selection_set(str(m.id))
        _buton(self.app.icerik, "Muhasebe Fişi").invoke()
        self._fis_dogru("kasa_makbuzu", int(m.id))
        self._ekran("kasa_makbuzu_listesi")


class AyarVeKartEkranTest(_EkranTemel):
    def test_finans_islem_ayarlari_sekmeleri_kasa_kur_farki(self):
        from muhasebelestirme_ui import FinansIslemAyarlariDialog

        self._ayar("otomatik")
        self._hesap_bagla("kur_farki_geliri")
        d = FinansIslemAyarlariDialog(self.root)
        nb = next(w for w in d.winfo_children() if w.winfo_class() == "TNotebook")
        sekmeler = [nb.tab(t, "text") for t in nb.tabs()]
        self.assertEqual(sekmeler[-3:], ["Kasa / Banka Kartları", "Kur farkı", "Alış iadesi"])
        self.assertEqual(d.hesap_var["kasa"].get(), "100.01.0001 — Kasa")
        self.assertEqual(d.hesap_var["kur_farki_geliri"].get(), "646.01.0001 — Kambiyo Karları")
        self.assertNotIn("alis_iade_maliyet_farki", d.hesap_var)
        from muhasebelestirme_ui import _HESAP_BOS

        for anahtar in ("alis_iade_maliyet_farki_olumlu", "alis_iade_maliyet_farki_olumsuz"):
            self.assertEqual(d.hesap_var[anahtar].get(), _HESAP_BOS)
        self.assertIn("alis_iade.kdv_kuru", d.secim_var)
        self.assertNotIn("Kaynak alış kuru", d.secim_var["alis_iade.kdv_kuru"].get())
        self.assertNotIn("İade tarihi kuru", d.secim_var["alis_iade.kdv_kuru"].get())
        nb.select(len(sekmeler) - 1)
        self._ekran("finans_islem_ayarlari_alis_iadesi", d)
        nb.select(len(sekmeler) - 3)
        self._ekran("finans_islem_ayarlari_kasa_banka", d)
        nb.select(len(sekmeler) - 2)
        self._ekran("finans_islem_ayarlari_kur_farki", d)
        # Kasa varsayılanı ekrandan değiştirilir ve geçmişe yazılır
        h2 = self._hesap_ac("100.01.0002", "Merkez Kasa 2")
        d2 = FinansIslemAyarlariDialog(self.root)
        d2.hesap_var["kasa"].set("100.01.0002 — Merkez Kasa 2")
        d2._kaydet()
        from database.muhasebe_entegrasyon import MuhasebeEntegrasyonService

        self.assertEqual(MuhasebeEntegrasyonService._hesap("kasa")["id"], h2)
        self.assertIn("100.01.0002", self._gecmis("esleme")[-1].detay)
        d.destroy()

    def test_kart_muhasebe_hesaplari_ekrani_secim_kaydet_ve_karsilastirma(self):
        import finans_ui
        from finans_muhasebe_hesap_ui import BakiyeKarsilastirmaDialog, KartMuhasebeHesaplariDialog

        self._ayar("otomatik")
        kart = self._banka_karti("Akbank")
        self._hesap_ac("102.01.0002", "Akbank TL Vadesiz")
        self._hesap_ac("653.01.0002", "Akbank POS Komisyon", "Gider")
        self._hesap_ac("108.01.0002", "Akbank POS Valör")
        d = KartMuhasebeHesaplariDialog(self.root, banka_karti_id=kart["kart"])
        self.assertEqual(set(d.agac.get_children()), {str(kart[a]) for a in
                                                      ("MEVDUAT", "KMH", "POS", "KREDILER", "KREDI_KARTI")})
        self.assertEqual(d.agac.set(str(kart["KMH"]), "durum"), "İnceleme gerekiyor")
        d.agac.selection_set(str(kart["MEVDUAT"]))
        d._secildi()
        self.assertTrue(all(v == d.hesap_cb["values"][0] or v.startswith("102.")
                            for v in d.hesap_cb["values"]), "mevduat kartına yalnız 102 hesapları önerilir")
        d.hesap_var.set("102.01.0002 — Akbank TL Vadesiz")
        d._kaydet()
        self.assertEqual(d.agac.set(str(kart["MEVDUAT"]), "durum"), "Kart hesabı")
        self.assertEqual(d.agac.set(str(kart["MEVDUAT"]), "hesap"), "102.01.0002 — Akbank TL Vadesiz")
        d.agac.selection_set(str(kart["POS"]))
        d._secildi()
        d.hesap_var.set("108.01.0002 — Akbank POS Valör")
        d.komisyon_var.set("653.01.0002 — Akbank POS Komisyon")
        d._kaydet()
        self.assertEqual(d.agac.set(str(kart["POS"]), "komisyon"), "653.01.0002 — Akbank POS Komisyon")
        self._ekran("kart_muhasebe_hesaplari", d)
        b = BakiyeKarsilastirmaDialog(d)
        self.assertTrue(b.agac.get_children())
        self._ekran("finans_muhasebe_karsilastirma", b)
        b.destroy()
        d.destroy()

        # Banka ana kartı ekranındaki düğme aynı ekranı karta süzülmüş açar
        from database.finans_service import FinansService

        bk = finans_ui.BankaAnaKartDialog(self.root, kart=FinansService.banka_karti_getir(kart["kart"]))
        acilan = []
        with patch("finans_muhasebe_hesap_ui.KartMuhasebeHesaplariDialog",
                   lambda _p, **k: acilan.append(k["banka_karti_id"])):
            _buton(bk, "Muhasebe Hesapları").invoke()
        self.assertEqual(acilan, [kart["kart"]])
        bk.destroy()

    def test_kasa_karti_muhasebe_hesabi_alani(self):
        import finans_ui
        from database.models.finans import FinansHesabi

        self._ayar("otomatik")
        self._hesap_ac("100.01.0002", "Şube Kasası")
        d = finans_ui.HesapDialog(self.root, "KASA")
        d.girdiler["hesap_adi"].insert(0, "Şube Kasa")
        self.assertIn("100.01.0002 — Şube Kasası", d.muhasebe_alani.cb["values"])
        self.assertFalse(any(v.startswith("102.") for v in d.muhasebe_alani.cb["values"]))
        d.muhasebe_alani.var.set("100.01.0002 — Şube Kasası")
        self._ekran("kasa_karti_muhasebe_hesabi", d)
        d.kaydet()
        with get_session() as s:
            h = s.scalar(select(FinansHesabi).where(FinansHesabi.hesap_adi == "Şube Kasa"))
            self.assertIsNotNone(h.muhasebe_hesap_id)
        self.assertIn("100.01.0002", self._gecmis("finans_kart_hesabi")[-1].detay)


if __name__ == "__main__":
    import unittest

    unittest.main()
