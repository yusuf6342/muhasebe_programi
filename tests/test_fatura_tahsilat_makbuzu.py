"""Satış faturasından açılan tahsilat makbuzu: faturaya bağ, kalan tutar, kısmi/çoklu tahsilat,
düzenleme, iptal, onaylı fatura içeriğinin korunması, çıktı ve fatura ekranı.

Yalnız geçici test veritabanı kullanır (TahsilatMakbuzuTest kurulumu).
"""

from __future__ import annotations

import sys
import tkinter as tk
import unittest
from datetime import date
from decimal import Decimal
from io import BytesIO
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from sqlalchemy import func, select

import makbuz_cikti as mc
from database.database import get_session
from database.finans_service import FinansService
from database.models.cari import CariIslem, SatisHareketi
from database.models.finans import FinansHareketi, KasaMakbuzu, PosValorKaydi, SatisFaturaMakbuzBagi
from database.models.satis_faturasi import SatisFaturasi, SatisFaturasiSatiri
from tests import test_tahsilat_makbuzu as _servis_testi

FIRMA = mc.firma_satirlari({"unvan": "ÖRNEK TEST MOBİLYA SANAYİ VE TİCARET LTD. ŞTİ.", "il": "Ankara"})


def _fatura_ekle(s, cari_id, no, tarih, fiyat, *, onayli=True):
    toplam = (Decimal(fiyat) * Decimal("1.20")).quantize(Decimal("0.01"))
    f = SatisFaturasi(
        fatura_no=no,
        fatura_tarihi=tarih,
        vade_tarihi=tarih,
        cari_id=cari_id,
        durum="AÇIK" if onayli else "TASLAK",
        onaylandi=onayli,
        depo="ANA DEPO",
        tahsilat_tutari=Decimal("0"),
        tl_genel_toplam=toplam,
        tl_brut_toplam=toplam,
        row_version=3,
    )
    f.satirlar.append(
        SatisFaturasiSatiri(
            urun_kodu="U1", urun_adi="Masa", miktar=Decimal("1"), birim="Adet",
            birim_fiyat=Decimal(fiyat), kdv_orani=Decimal("20"),
        )
    )
    s.add(f)
    if onayli:
        s.add(SatisHareketi(cari_id=cari_id, satis_tarihi=tarih, belge_no=no,
                            satis_tutari=toplam, kalan_acik_tutar=toplam))
    s.flush()
    return f.id


def _kurulum(test):
    _servis_testi.TahsilatMakbuzuTest.setUp(test)
    with get_session() as s:
        test.eski_id = _fatura_ekle(s, test.musteri_id, "SF-2026-0001", date(2026, 6, 1), "1000")
        test.fatura_id = _fatura_ekle(s, test.musteri_id, "SF-2026-0002", date(2026, 7, 1), "500")
        test.taslak_id = _fatura_ekle(s, test.musteri_id, "SF-2026-0003", date(2026, 8, 1), "250", onayli=False)


def _makbuz(test, satirlar, fatura_id=None, **ek):
    veri = {
        "tarih": date.today(),
        "cari_id": test.musteri_id,
        "makbuz_no_otomatik": True,
        "fatura_id": test.fatura_id if fatura_id is None else fatura_id,
        "satirlar": satirlar,
    }
    veri.update(ek)
    return FinansService.kasa_tahsilat_makbuzu_kaydet(veri)


def _nakit(test, tutar):
    return {"odeme_sekli": "NAKİT / KASA", "finans_hesap_id": test.kasa_id, "tutar": tutar}


def _pos(test, tutar):
    return {"odeme_sekli": "KREDİ KARTIYLA TAHSİLAT", "finans_hesap_id": test.pos_id, "tutar": tutar,
            "kart_tipi": "KREDI_KARTI", "taksit_sayisi": 1}


def _durum(fatura_id):
    """(tahsil edilen, durum, açık borç satırının kalanı, onaylı, sürüm, satır sayısı)."""
    with get_session() as s:
        f = s.get(SatisFaturasi, fatura_id)
        h = s.scalar(select(SatisHareketi).where(SatisHareketi.belge_no == f.fatura_no))
        return (
            Decimal(str(f.tahsilat_tutari)),
            f.durum,
            Decimal(str(h.kalan_acik_tutar)) if h else None,
            f.onaylandi,
            f.row_version,
            len(f.satirlar),
        )


def _sayilar():
    with get_session() as s:
        return tuple(
            s.scalar(select(func.count()).select_from(m))
            for m in (CariIslem, FinansHareketi, PosValorKaydi, KasaMakbuzu, SatisFaturaMakbuzBagi)
        )


class FaturaTahsilatServisTest(unittest.TestCase):
    def setUp(self):
        _kurulum(self)

    def tearDown(self):
        _servis_testi.TahsilatMakbuzuTest.tearDown(self)

    def test_ozet_kayit_oncesi(self):
        oz = FinansService.fatura_tahsilat_ozeti(self.fatura_id)
        self.assertEqual((oz["fatura_no"], oz["cari_id"]), ("SF-2026-0002", self.musteri_id))
        self.assertEqual((oz["genel_toplam"], oz["tahsil_edilen"], oz["kalan"]),
                         (Decimal("600.00"), Decimal("0"), Decimal("600.00")))
        self.assertEqual(oz["makbuzlar"], [])
        taslak = FinansService.fatura_tahsilat_ozeti(self.taslak_id)
        self.assertEqual((taslak["onayli"], taslak["kalan"]), (False, Decimal("300.00")))

    def test_tam_tahsilat_once_bagli_faturayi_kapatir(self):
        bakiye_once = FinansService.cari_bakiye_ozeti(self.musteri_id)["bakiye"]
        m = _makbuz(self, [_nakit(self, "600")])
        self.assertEqual(m.makbuz_no, "MKB-00001")
        self.assertEqual(m.bagli_fatura_no, "SF-2026-0002")
        # FIFO en eski faturayı (SF-0001) değil, bağlı faturayı kapatır
        # Tam kapanış evrak durumunu değiştirmez (AÇIK kalır); ödeme durumu ayrı alandır
        self.assertEqual(_durum(self.fatura_id)[:3], (Decimal("600.00"), "AÇIK", Decimal("0.00")))
        self.assertEqual(_durum(self.eski_id)[:3], (Decimal("0.00"), "AÇIK", Decimal("1200.00")))
        self.assertEqual(FinansService.cari_bakiye_ozeti(self.musteri_id)["bakiye"], bakiye_once - 600)
        oz = FinansService.fatura_tahsilat_ozeti(self.fatura_id)
        self.assertEqual((oz["kalan"], oz["makbuz_tahsilati"], len(oz["makbuzlar"])), (0, Decimal("600.00"), 1))
        self.assertEqual(oz["makbuzlar"][0]["makbuz_no"], "MKB-00001")

    def test_kismi_ve_birden_fazla_tahsilat_toplamlari(self):
        ilk = _makbuz(self, [_nakit(self, "200"), _pos(self, "150")])
        ikinci = _makbuz(self, [_nakit(self, "100")])
        self.assertEqual(_durum(self.fatura_id)[:3], (Decimal("450.00"), "AÇIK", Decimal("150.00")))
        oz = FinansService.fatura_tahsilat_ozeti(self.fatura_id)
        self.assertEqual([x["makbuz_no"] for x in oz["makbuzlar"]], [ilk.makbuz_no, ikinci.makbuz_no])
        self.assertEqual([x["fatura_kapanan"] for x in oz["makbuzlar"]], [Decimal("350.00"), Decimal("100.00")])
        self.assertEqual((oz["tahsil_edilen"], oz["kalan"]), (Decimal("450.00"), Decimal("150.00")))
        # Makbuzlar tahsilat makbuzları listesinde de görünür
        listede = {x.id for x in FinansService.kasa_makbuz_listele("TAHSILAT")}
        self.assertTrue({ilk.id, ikinci.id} <= listede)

    def test_duzenleme_yeniden_hesaplar_cift_kayit_olmaz(self):
        m = _makbuz(self, [_nakit(self, "350")])
        once = _sayilar()
        guncel = FinansService.kasa_makbuz_guncelle(
            m.id, {"tarih": date.today(), "cari_id": self.musteri_id, "makbuz_no": m.makbuz_no,
                   "satirlar": [_nakit(self, "250")]}
        )
        self.assertEqual((guncel.makbuz_no, guncel.belge_no, guncel.bagli_fatura_id),
                         (m.makbuz_no, m.belge_no, self.fatura_id))
        self.assertEqual(_durum(self.fatura_id)[:3], (Decimal("250.00"), "AÇIK", Decimal("350.00")))
        self.assertEqual(_sayilar(), once)
        # Aynı makbuz ikinci kez kaydedilse de tahsilat bir kez işlenir
        FinansService.kasa_makbuz_guncelle(
            m.id, {"tarih": date.today(), "cari_id": self.musteri_id, "makbuz_no": m.makbuz_no,
                   "satirlar": [_nakit(self, "250")], "fatura_id": self.fatura_id}
        )
        self.assertEqual(_durum(self.fatura_id)[:3], (Decimal("250.00"), "AÇIK", Decimal("350.00")))
        self.assertEqual(_sayilar(), once)

    def test_iptal_faturayi_geri_acar(self):
        ilk = _makbuz(self, [_nakit(self, "400")])
        ikinci = _makbuz(self, [_nakit(self, "200")])
        self.assertEqual(_durum(self.fatura_id)[1], "AÇIK")
        self.assertEqual(_durum(self.fatura_id)[2], Decimal("0.00"))
        FinansService.kasa_makbuz_iptal(ikinci.id)
        self.assertEqual(_durum(self.fatura_id)[:3], (Decimal("400.00"), "AÇIK", Decimal("200.00")))
        oz = FinansService.fatura_tahsilat_ozeti(self.fatura_id)
        self.assertEqual([x["durum"] for x in oz["makbuzlar"]], ["AÇIK", "IPTAL"])
        self.assertEqual((oz["makbuz_tahsilati"], oz["kalan"]), (Decimal("400.00"), Decimal("200.00")))
        FinansService.kasa_makbuz_iptal(ilk.id)
        self.assertEqual(_durum(self.fatura_id)[:3], (Decimal("0.00"), "AÇIK", Decimal("600.00")))
        with get_session() as s:
            self.assertEqual(s.scalar(select(func.count()).select_from(CariIslem)
                                      .where(CariIslem.belge_no.in_([ilk.belge_no, ikinci.belge_no]))), 0)

    def test_kalan_asiminda_fazlasi_diger_borca_gider_iptalde_geri_doner(self):
        m = _makbuz(self, [_nakit(self, "800")])
        self.assertEqual(_durum(self.fatura_id)[2], Decimal("0.00"))
        self.assertEqual(_durum(self.eski_id)[:3], (Decimal("200.00"), "AÇIK", Decimal("1000.00")))
        self.assertEqual(FinansService.makbuz_fatura_bagi(m.id)["fatura_kapanan"], Decimal("600.00"))
        FinansService.kasa_makbuz_iptal(m.id)
        self.assertEqual(_durum(self.fatura_id)[:3], (Decimal("0.00"), "AÇIK", Decimal("600.00")))
        self.assertEqual(_durum(self.eski_id)[:3], (Decimal("0.00"), "AÇIK", Decimal("1200.00")))

    def test_onayli_faturanin_icerigi_degismez(self):
        with get_session() as s:
            f = s.get(SatisFaturasi, self.fatura_id)
            once = (f.onaylandi, f.row_version, f.tl_genel_toplam, f.updated_at, f.aciklama,
                    [(x.urun_kodu, x.miktar, x.birim_fiyat) for x in f.satirlar])
        m = _makbuz(self, [_nakit(self, "300")])
        FinansService.kasa_makbuz_guncelle(
            m.id, {"tarih": date.today(), "cari_id": self.musteri_id, "satirlar": [_nakit(self, "100")]}
        )
        FinansService.kasa_makbuz_iptal(m.id)
        with get_session() as s:
            f = s.get(SatisFaturasi, self.fatura_id)
            sonra = (f.onaylandi, f.row_version, f.tl_genel_toplam, f.updated_at, f.aciklama,
                     [(x.urun_kodu, x.miktar, x.birim_fiyat) for x in f.satirlar])
        self.assertEqual(once, sonra)

    def test_taslak_faturada_durum_degismez_kayitta_korunur(self):
        _makbuz(self, [_nakit(self, "100")], fatura_id=self.taslak_id)
        tahsil, durum, hareket, onayli, _, _ = _durum(self.taslak_id)
        self.assertEqual((tahsil, durum, hareket, onayli), (Decimal("100.00"), "TASLAK", None, False))
        self.assertEqual(_durum(self.eski_id)[0], Decimal("0.00"))
        self.assertEqual(FinansService.fatura_tahsilat_ozeti(self.taslak_id)["kalan"], Decimal("200.00"))
        # Taslak fatura yeniden kaydedilince bağlı makbuz tahsilatı silinmez
        from database.satis_faturasi_service import SatisFaturasiService

        SatisFaturasiService.kaydet(
            {"fatura_tarihi": date(2026, 8, 1), "vade_tarihi": date(2026, 8, 1), "cari_id": self.musteri_id,
             "depo": "ANA DEPO"},
            [{"urun_kodu": "U1", "urun_adi": "Masa", "miktar": "1", "birim": "Adet", "birim_fiyat": "250",
              "kdv_orani": "20"}],
            self.taslak_id,
        )
        self.assertEqual(_durum(self.taslak_id)[0], Decimal("100.00"))
        with self.assertRaisesRegex(ValueError, "bağlı tahsilat makbuzlarıyla"):
            SatisFaturasiService.kaydet(
                {"fatura_tarihi": date(2026, 8, 1), "vade_tarihi": date(2026, 8, 1), "cari_id": self.musteri_id,
                 "depo": "ANA DEPO"},
                [{"urun_kodu": "U1", "urun_adi": "Masa", "miktar": "1", "birim": "Adet", "birim_fiyat": "50",
                  "kdv_orani": "20"}],
                self.taslak_id,
                tahsilat_verileri=[{"tutar": "10", "odeme_sekli": "NAKİT / KASA", "hesap": "TEST KASA"}],
            )

    def test_engeller(self):
        with self.assertRaisesRegex(ValueError, "faturanın müşterisi"):
            _makbuz(self, [_nakit(self, "10")], cari_id=self.tedarikci_id)
        m = _makbuz(self, [_nakit(self, "10")])
        with self.assertRaisesRegex(ValueError, "fatura değiştirilemez"):
            FinansService.kasa_makbuz_guncelle(
                m.id, {"tarih": date.today(), "cari_id": self.musteri_id, "satirlar": [_nakit(self, "10")],
                       "fatura_id": self.eski_id}
            )
        with get_session() as s:
            s.get(SatisFaturasi, self.eski_id).durum = "İPTAL"
        with self.assertRaisesRegex(ValueError, "İptal edilmiş faturaya"):
            _makbuz(self, [_nakit(self, "10")], fatura_id=self.eski_id)
        # Bir makbuz yalnız bir faturaya bağlanır (veritabanı düzeyinde de)
        with self.assertRaises(Exception):
            with get_session() as s:
                s.add(SatisFaturaMakbuzBagi(makbuz_id=m.id, fatura_id=self.taslak_id, fatura_no="SF-2026-0003"))
                s.flush()

    def test_bagsiz_makbuz_eskisi_gibi_fifo(self):
        FinansService.kasa_tahsilat_makbuzu_kaydet({
            "tarih": date.today(), "cari_id": self.musteri_id, "makbuz_no_otomatik": True,
            "satirlar": [_nakit(self, "300")],
        })
        self.assertEqual(_durum(self.eski_id)[:3], (Decimal("300.00"), "AÇIK", Decimal("900.00")))
        self.assertEqual(_durum(self.fatura_id)[2], Decimal("600.00"))


class FaturaTahsilatCiktiTest(unittest.TestCase):
    def setUp(self):
        _kurulum(self)

    def tearDown(self):
        _servis_testi.TahsilatMakbuzuTest.tearDown(self)

    def test_pdf_word_ve_a4_ikili_fatura_no_icerir(self):
        bagli = _makbuz(self, [_nakit(self, "250")])
        normal = FinansService.kasa_tahsilat_makbuzu_kaydet({
            "tarih": date.today(), "cari_id": self.musteri_id, "makbuz_no_otomatik": True,
            "satirlar": [_nakit(self, "50")],
        })
        veriler = mc.makbuz_cikti_verileri([bagli.id, normal.id], FIRMA)
        self.assertEqual(veriler[0]["belge_bilgi"],
                         ("BELGE NO · BAĞLI SATIŞ FATURASI", f"{bagli.belge_no} · SF-2026-0002"))
        self.assertEqual(veriler[1]["belge_bilgi"], ("BELGE NO", normal.belge_no))
        import fitz

        for duzen, sayfa in ((mc.A5, 2), (mc.A4_IKILI, 1)):
            pdf = mc.pdf_uret(veriler, duzen)
            with fitz.open(stream=pdf, filetype="pdf") as doc:
                self.assertEqual(doc.page_count, sayfa)
                metin = "".join(p.get_text() for p in doc)
            self.assertIn("SF-2026-0002", metin)
            self.assertEqual(metin.count("TAHSİLAT MAKBUZU"), 2)
        from docx import Document

        doc = Document(BytesIO(mc.docx_uret(veriler, mc.A4_IKILI)))
        metin = "\n".join(c.text for t in doc.tables for r in t.rows for c in r.cells)
        self.assertIn("SF-2026-0002", metin)


class FaturaTahsilatEkranTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        try:
            cls.root = tk.Tk()
        except tk.TclError as hata:
            raise unittest.SkipTest(f"Tk yok: {hata}")
        cls.root.withdraw()

    @classmethod
    def tearDownClass(cls):
        cls.root.destroy()

    def setUp(self):
        _kurulum(self)
        self._yamalar = [
            patch("cari_kart_ui.cari_uyari_goster", return_value=None),
            patch.object(mc, "firma_bilgisi", return_value=FIRMA),
        ]
        for y in self._yamalar:
            y.start()

    def tearDown(self):
        for y in self._yamalar:
            y.stop()
        for w in list(self.root.winfo_children()):
            w.destroy()
        _servis_testi.TahsilatMakbuzuTest.tearDown(self)

    def _dialog(self, **ek):
        from kasa_makbuz_ui import KasaMakbuzDialog

        d = KasaMakbuzDialog(self.root, "TAHSILAT", **ek)
        d.update_idletasks()
        return d

    def test_makbuz_fatura_bilgileriyle_acilir_hareket_olusmaz(self):
        once = _sayilar()
        d = self._dialog(fatura_id=self.fatura_id)
        self.assertEqual(_sayilar(), once)
        self.assertEqual(d.secili_cari_id(), self.musteri_id)
        self.assertEqual(str(d.cari_entry.cget("state")), "disabled")
        self.assertEqual(str(d.islem_turu_cb.cget("state")), "disabled")
        self.assertEqual(d.tutar_var.get(), "600,00")
        self.assertIn("SF-2026-0002", d.aciklama_var.get())
        bilgi = d.fatura_bilgi_metni()
        self.assertIn("SF-2026-0002", bilgi)
        self.assertIn("Faturanın kalan ödenmemiş tutarı 600,00", bilgi)
        self.assertIn("ÖRNEK TEST MOBİLYA", bilgi)
        # Müşterinin güncel bakiyesi faturanın kalanından ayrı gösterilir: 1.000 açılış + 1.200 + 600 + 300 değil
        self.assertIn("2.800,00", d.bakiye_metni())
        self.assertIn("Borçlu", d.bakiye_metni())
        self.assertTrue(d.makbuz_no_var.get().startswith("MKB-"))
        d.kapat()
        self.assertEqual(_sayilar(), once)

    def test_kismi_tahsilat_kaydi_ve_asim_onayi(self):
        d = self._dialog(fatura_id=self.fatura_id)
        self.assertNotIn("CARİ VİRMAN", d.sekil_cb.cget("values"))
        d.tutar_var.set("250")
        d.sekil_var.set("NAKİT / KASA")
        d._sekil_degisti()
        d.hesap_var.set("TEST KASA")
        self.assertTrue(d.satir_ekle())
        self.assertTrue(d.kaydet())
        self.assertEqual(d.mod, "goruntule")
        self.assertEqual(_durum(self.fatura_id)[:3], (Decimal("250.00"), "AÇIK", Decimal("350.00")))
        self.assertIn("kalan ödenmemiş tutarı 350,00", d.fatura_bilgi_metni())
        # Kayıtlı bağlı makbuz: düzenlemede cari kilitli; kalanı aşan tutar onaysız kaydedilmez
        mid = d.makbuz_id
        d.kapat()
        d = self._dialog(makbuz_id=mid)
        self.assertIn("SF-2026-0002", d.fatura_bilgi_metni())
        d.duzenlemeye_gec()
        self.assertEqual(str(d.cari_entry.cget("state")), "disabled")
        d.satirlar[0]["tutar"] = Decimal("700")
        with patch("kasa_makbuz_ui.messagebox.askyesno", return_value=False) as soru:
            self.assertFalse(d.kaydet())
        self.assertIn("600,00", soru.call_args[0][1])
        self.assertEqual(_durum(self.fatura_id)[:3], (Decimal("250.00"), "AÇIK", Decimal("350.00")))
        d._kirli = False
        d.kapat()

    def test_iptal_faturada_acilmaz(self):
        with get_session() as s:
            s.get(SatisFaturasi, self.fatura_id).durum = "İPTAL"
        with self.assertRaisesRegex(ValueError, "İptal edilmiş faturaya"):
            self._dialog(fatura_id=self.fatura_id)

    def _fatura_ekrani(self, fatura_id=None):
        from app import SatisFaturasiDialog
        from database.satis_faturasi_service import SatisFaturasiService

        with patch("satis_personeli_ui.aktif_satis_personelleri", return_value=[]), patch(
            "satis_personeli_ui.satis_personeli_degistirme_yetkisi", return_value=True
        ), patch("fatura_acilis_cache.satis_personelleri", return_value=[]):
            fatura = SatisFaturasiService.getir(fatura_id) if fatura_id else None
            dlg = SatisFaturasiDialog(self.root, fatura=fatura)
        dlg.update_idletasks()
        return dlg

    def test_fatura_ekrani_dugme_panel_ve_geri_donus(self):
        ilk = _makbuz(self, [_nakit(self, "200")])
        ikinci = _makbuz(self, [_nakit(self, "150")])
        FinansService.kasa_makbuz_iptal(ikinci.id)
        dlg = self._fatura_ekrani(self.fatura_id)
        self.assertEqual(dlg._tahsilat_makbuzu_btn.cget("text"), "Tahsilat Makbuzu")
        satirlar = [dlg._bagli_makbuz_tablo.item(i, "values") for i in dlg._bagli_makbuz_tablo.get_children()]
        self.assertEqual([s[0] for s in satirlar], [ilk.makbuz_no, ikinci.makbuz_no])
        self.assertEqual([s[4] for s in satirlar], ["AÇIK", "İPTAL"])
        ozet = dlg._bagli_makbuz_ozet_lbl.cget("text")
        self.assertIn("Faturanın kalan tutarı: 400,00", ozet)
        self.assertIn("(1 makbuz)", ozet)
        with patch("kasa_makbuz_ui.KasaMakbuzDialog") as pencere:
            dlg._fatura_tahsilat_makbuzu_ac()
            self.assertEqual(pencere.call_args.kwargs["fatura_id"], self.fatura_id)
            dlg._bagli_makbuzu_ac(ilk.id)
            self.assertEqual(pencere.call_args.kwargs["makbuz_id"], ilk.id)
        # Makbuz kaydı sonrası panel yenilenir
        _makbuz(self, [_nakit(self, "100")])
        dlg._bagli_makbuzlari_yenile()
        self.assertIn("Faturanın kalan tutarı: 300,00", dlg._bagli_makbuz_ozet_lbl.cget("text"))
        dlg.destroy()

    def _yeni_fatura_doldur(self):
        from database.cari_service import CariService
        from database.models.stok import Depo, StokKarti

        with get_session() as s:
            if not s.scalar(select(Depo).where(Depo.ad == "ANA DEPO")):
                s.add(Depo(ad="ANA DEPO", aktif=True))
            if not s.scalar(select(StokKarti).where(StokKarti.stok_kodu == "U1")):
                s.add(StokKarti(stok_kodu="U1", stok_adi="Masa", birim="Adet", aktif=True))
        from database.stok_service import StokService

        StokService.stok_girisi("U1", "ANA DEPO", "", date.today(), Decimal("10"), Decimal("50"))
        dlg = self._fatura_ekrani()
        dlg._musteri_secildi_callback(CariService.getir(self.musteri_id))
        dlg.satirlar = [
            {
                "urun_kodu": "U1",
                "urun_adi": "Masa",
                "miktar": "1",
                "birim": "Adet",
                "birim_satis_fiyati": "100",
                "kdv_orani": "20",
                "iskonto_orani": "0",
                "iskonto_orani_2": "0",
                "iskonto_orani_3": "0",
                "satir_para_birimi": "TRY",
                "kur": "1",
            }
        ]
        dlg._satir_listesini_yenile()
        dlg.update_idletasks()
        return dlg

    def _mesajlari_yakala(self):
        kayit = []

        def f(tur, sonuc):
            def g(*a, **_k):
                kayit.append((tur,) + tuple(str(x) for x in a))
                return sonuc

            return g

        return kayit, [
            patch("app.messagebox.showinfo", f("info", "ok")),
            patch("app.messagebox.showwarning", f("warning", "ok")),
            patch("app.messagebox.showerror", f("error", "ok")),
            patch("app.messagebox.askyesno", f("askyesno", True)),
        ]

    def test_yeni_fatura_kaydinda_makbuz_acilir(self):
        dlg = self._yeni_fatura_doldur()
        mesajlar, yamalar = self._mesajlari_yakala()
        for y in yamalar:
            y.start()
        try:
            with patch("kasa_makbuz_ui.KasaMakbuzDialog") as pencere:
                dlg.kaydet()
        finally:
            for y in yamalar:
                y.stop()
        self.assertFalse([m for m in mesajlar if m[0] == "error"], mesajlar)
        self.assertTrue(dlg.fatura is not None and dlg.fatura.id)
        self.assertRegex(dlg.fatura.fatura_no, r"^RAY-\d{5}$")
        pencere.assert_called_once()
        self.assertEqual(pencere.call_args.kwargs["fatura_id"], dlg.fatura.id)
        dlg.destroy()

    def test_onayla_ve_yeni_faturayi_onaylar_ve_makbuz_acar(self):
        dlg = self._yeni_fatura_doldur()
        mesajlar, yamalar = self._mesajlari_yakala()
        for y in yamalar:
            y.start()
        try:
            with patch("kasa_makbuz_ui.KasaMakbuzDialog") as pencere:
                dlg.onayla_ve_yeni()
        finally:
            for y in yamalar:
                y.stop()
        self.assertFalse([m for m in mesajlar if m[0] == "error"], mesajlar)
        with get_session() as s:
            son = s.scalar(select(SatisFaturasi).order_by(SatisFaturasi.id.desc()))
            self.assertTrue(son.onaylandi)
        pencere.assert_called_once()
        self.assertEqual(pencere.call_args.kwargs["fatura_id"], son.id)

    def test_kaydedilmemis_faturada_once_kayit_uyarisi(self):
        dlg = self._fatura_ekrani()
        with patch("kasa_makbuz_ui.KasaMakbuzDialog") as pencere, patch(
            "app.messagebox.askyesno", return_value=False
        ) as soru:
            dlg._fatura_tahsilat_makbuzu_ac()
        self.assertEqual(soru.call_args[0][0], "Önce faturayı kaydedin")
        pencere.assert_not_called()
        self.assertIn("Fatura kaydedildikten sonra", dlg._bagli_makbuz_ozet_lbl.cget("text"))
        dlg.destroy()


if __name__ == "__main__":
    unittest.main()
