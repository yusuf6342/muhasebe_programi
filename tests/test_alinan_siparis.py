"""Alınan sipariş uçtan uca testleri (izole geçici SQLite).

Boş kart, satır/hesap, kaydet-yeniden aç, kısmi irsaliye/fatura aktarımı, bağlı satır
kilitleri, hedef evrak iptal/silme ile kalanların geri gelmesi, liste filtre/açma ve
SATIŞ SİPARİŞ FORMU PDF/Word çıktısı.
"""

from __future__ import annotations

import re
import sys
import tempfile
import unittest
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from sqlalchemy import func, select

from database.database import get_session
from database.models.satis_siparisi import SatisSiparisi, SatisSiparisiSatiri
from database.models.stok import StokHareketi
from database.satis_siparisi_service import (
    SatisSiparisiService,
    belge_toplamlari,
    satir_hesapla,
    siparis_ilerleme,
    siparis_listesi_filtrele,
)
from tests.test_satis_irsaliyesi_akis import _EkranTemel, _IrsaliyeTemel

TARIH = date(2026, 3, 1)
UZUN_AD = "Çok Uzun Ürün Adı Şişe Ğ Ü Ö İ ı Paslanmaz Çelik Endüstriyel Tip Bağlantı Parçası " * 2


def _satir(miktar, birim="Adet", fiyat="100", **ek):
    s = {
        "urun_kodu": "MB001",
        "urun_adi": "Birim Ürün",
        "miktar": Decimal(str(miktar)),
        "birim": birim,
        "birim_satis_fiyati": Decimal(str(fiyat)),
        "kdv_orani": Decimal("20"),
    }
    s.update(ek)
    return s


class _SiparisTemel(_IrsaliyeTemel):
    def _veri(self, **ek):
        veri = {
            "siparis_tarihi": TARIH,
            "termin_tarihi": date(2026, 3, 20),
            "cari_id": self.cari_id,
            "depo": "ANA DEPO",
        }
        veri.update(ek)
        return veri

    def _kaydet(self, satirlar=None, siparis_id=None, **ek):
        return SatisSiparisiService.kaydet(self._veri(**ek), satirlar or [_satir(10, "Paket")], None, siparis_id)

    def _satir_db(self, sid) -> SatisSiparisiSatiri:
        with get_session() as session:
            return session.get(SatisSiparisiSatiri, sid)

    def _irsaliye(self, siparis, miktar):
        from database.satis_irsaliyesi_service import SatisIrsaliyesiService

        s = siparis.satirlar[0]
        return SatisIrsaliyesiService.kaydet(
            {"irsaliye_tarihi": date(2026, 3, 10), "cari_id": self.cari_id, "depo": "ANA DEPO", "siparis_id": siparis.id},
            [{
                "urun_kodu": s.urun_kodu, "urun_adi": s.urun_adi, "miktar": Decimal(str(miktar)), "birim": s.birim,
                "birim_fiyat": Decimal("100"), "kdv_orani": Decimal("20"), "siparis_satiri_id": s.id,
            }],
        )

    def _fatura(self, siparis, miktar):
        from database.satis_faturasi_service import SatisFaturasiService

        s = siparis.satirlar[0]
        return SatisFaturasiService.kaydet(
            {
                "fatura_tarihi": date(2026, 3, 10), "vade_tarihi": date(2026, 3, 10), "cari_id": self.cari_id,
                "depo": "ANA DEPO", "siparis_id": siparis.id, "odeme_tutari": Decimal("0"), "sales_person_id": 1,
            },
            [{
                "urun_kodu": s.urun_kodu, "urun_adi": s.urun_adi, "miktar": Decimal(str(miktar)), "birim": s.birim,
                "birim_fiyat": Decimal("100"), "iskonto_orani": Decimal("0"), "kdv_orani": Decimal("20"),
                "siparis_satiri_id": s.id,
            }],
        )


class AlinanSiparisServisTest(_SiparisTemel):
    def test_satir_hesabi_kademeli_iskonto_ve_kurus(self):
        h = satir_hesapla(Decimal("3"), Decimal("33.335"), 10, 5, 0, 20)
        self.assertEqual(h["net"], Decimal("85.50"))
        self.assertEqual(h["kdv"], Decimal("17.10"))
        self.assertEqual(h["toplam"], Decimal("102.60"))
        self.assertEqual(h["brut"] - h["iskonto"], h["net"])
        t = belge_toplamlari([
            {"miktar": 3, "birim_fiyat": "33.335", "iskonto_orani": 10, "iskonto_orani_2": 5, "kdv_orani": 20},
            {"miktar": 1, "birim_fiyat": "10", "kdv_orani": 0},
        ])
        self.assertEqual(t["net"], Decimal("95.50"))
        self.assertEqual(t["kdv"], Decimal("17.10"))
        self.assertEqual(t["genel_toplam"], Decimal("112.60"))

    def test_kaydet_ust_bilgiler_yeniden_ac_stok_cari_hareketi_yok(self):
        sp = self._kaydet(
            [_satir(3, "Adet", "33.335", iskonto_orani=10, iskonto_orani_2=5, iskonto_orani_3=0,
                    estimated_delivery_date=date(2026, 3, 15), aciklama="Satır notu")],
            teslimat_adresi="Organize Sanayi 5. Cad.", teslimat_il="Bursa", teslimat_ilce="Nilüfer",
            musteri_siparis_no="PO-778", teslim_kosulu="Fabrika teslim", odeme_kosulu="30 gün vadeli",
            aciklama="Genel açıklama",
        )
        self.assertEqual(sp.durum, "TASLAK")
        acik = SatisSiparisiService.getir(sp.id)
        self.assertEqual(acik.musteri_siparis_no, "PO-778")
        self.assertEqual((acik.teslimat_il, acik.teslimat_ilce), ("Bursa", "Nilüfer"))
        self.assertEqual(acik.teslim_kosulu, "Fabrika teslim")
        self.assertEqual(acik.odeme_kosulu, "30 gün vadeli")
        self.assertEqual(acik.para_birimi, "TRY")
        s = acik.satirlar[0]
        self.assertEqual((s.iskonto_orani, s.iskonto_orani_2), (Decimal("10"), Decimal("5")))
        self.assertEqual(s.estimated_delivery_date, date(2026, 3, 15))
        self.assertEqual(belge_toplamlari(acik.satirlar)["genel_toplam"], Decimal("102.60"))
        with get_session() as session:
            self.assertEqual(session.scalar(select(func.count()).select_from(StokHareketi)), 0)
        from database.models.cari import CariIslem, SatisHareketi

        with get_session() as session:
            self.assertEqual(session.scalar(select(func.count()).select_from(CariIslem)), 0)
            self.assertEqual(session.scalar(select(func.count()).select_from(SatisHareketi)), 0)

    def test_mukerrer_numara_ve_eksik_alan(self):
        self._kaydet(siparis_no="SS-TEST-1")
        with self.assertRaisesRegex(ValueError, "SS-TEST-1"):
            self._kaydet(siparis_no="SS-TEST-1")
        with self.assertRaisesRegex(ValueError, "satır"):
            SatisSiparisiService.kaydet(self._veri(), [], None)
        with get_session() as session:
            self.assertEqual(session.scalar(select(func.count()).select_from(SatisSiparisi)), 1)

    def test_doviz_kur_zorunlu_ve_aktarim_tl_fiyati(self):
        with self.assertRaisesRegex(ValueError, "kur"):
            self._kaydet(para_birimi="USD", kur=Decimal("0"))
        sp = self._kaydet([_satir(2, "Adet", "10")], para_birimi="USD", kur=Decimal("32.5"), onayla=True)
        from database.kalan_belge_service import siparis_secim_satirlari

        aday = siparis_secim_satirlari(SatisSiparisiService.getir(sp.id), hedef="fatura")[0]
        self.assertEqual(Decimal(str(aday["birim_fiyat"])), Decimal("325.0000"))

    def test_kismi_irsaliye_satir_kilidi_ve_irsaliye_silinince_geri_gelir(self):
        from database.satis_irsaliyesi_service import SatisIrsaliyesiService

        sp = self._kaydet(onayla=True)
        sid = sp.satirlar[0].id
        irs = self._irsaliye(sp, 4)
        self.assertEqual(self._satir_db(sid).irsaliyelenen_miktar, Decimal("4"))
        acik = SatisSiparisiService.getir(sp.id)
        self.assertEqual(acik.durum, "KISMİ İRSALİYELİ")
        self.assertEqual(siparis_ilerleme(acik), "KISMEN TAMAMLANDI")
        # kalan fazlası aktarılamaz
        with self.assertRaises(ValueError):
            self._irsaliye(acik, 7)
        # bağlı satır: miktar sevk altına inemez, silinemez, ürün değişemez
        with self.assertRaises(ValueError):
            self._kaydet([_satir(3, "Paket", id=sid)], siparis_id=sp.id)
        with self.assertRaisesRegex(ValueError, irs.irsaliye_no):
            self._kaydet([_satir(1, "Adet", urun_kodu="MB001", urun_adi="Yeni")], siparis_id=sp.id)
        with self.assertRaisesRegex(ValueError, "birimi"):
            self._kaydet([_satir(10, "Koli", id=sid)], siparis_id=sp.id)
        self.assertIn(irs.irsaliye_no, SatisSiparisiService.bagli_evrak_metni(sp.id))
        with self.assertRaisesRegex(ValueError, irs.irsaliye_no):
            SatisSiparisiService.sil(sp.id)
        # irsaliye silinince sevk miktarı siparişe geri döner
        SatisIrsaliyesiService.sil(irs.id)
        self.assertEqual(self._satir_db(sid).irsaliyelenen_miktar, Decimal("0"))
        self.assertEqual(SatisSiparisiService.getir(sp.id).durum, "AÇIK")
        # artık miktar azaltılabilir ve sipariş silinebilir
        self._kaydet([_satir(6, "Paket", id=sid)], siparis_id=sp.id)
        self.assertEqual(self._satir_db(sid).miktar, Decimal("6"))
        SatisSiparisiService.sil(sp.id)
        self.assertIsNone(SatisSiparisiService.getir(sp.id))

    def test_irsaliye_satiri_azaltilinca_kalan_artar(self):
        from database.satis_irsaliyesi_service import SatisIrsaliyesiService

        sp = self._kaydet(onayla=True)
        sid = sp.satirlar[0].id
        irs = self._irsaliye(sp, 6)
        s = irs.satirlar[0]
        SatisIrsaliyesiService.kaydet(
            {"irsaliye_tarihi": date(2026, 3, 10), "cari_id": self.cari_id, "depo": "ANA DEPO", "siparis_id": sp.id},
            [{"urun_kodu": s.urun_kodu, "urun_adi": s.urun_adi, "miktar": Decimal("2"), "birim": s.birim,
              "birim_fiyat": Decimal("100"), "kdv_orani": Decimal("20"), "siparis_satiri_id": sid,
              "irsaliye_satiri_id": s.id}],
            irsaliye_id=irs.id,
        )
        self.assertEqual(self._satir_db(sid).irsaliyelenen_miktar, Decimal("2"))

    def test_kismi_fatura_iptal_ve_taslak_silme_geri_alir(self):
        from database.deleted_record_service import ENTITY_SATIS_FATURA, AuditDeleteService
        from database.satis_faturasi_service import SatisFaturasiService

        sp = self._kaydet(onayla=True)
        sid = sp.satirlar[0].id
        f1 = self._fatura(sp, 3)
        self.assertEqual(self._satir_db(sid).faturalanan_miktar, Decimal("3"))
        self.assertEqual(self._satir_db(sid).irsaliyelenen_miktar, Decimal("0"), "sevk ile karışmaz")
        self.assertEqual(SatisSiparisiService.getir(sp.id).durum, "KISMİ FATURALI")
        with self.assertRaises(ValueError):
            self._fatura(SatisSiparisiService.getir(sp.id), 8)
        SatisFaturasiService.iptal_et(f1.id, sebep="test")
        self.assertEqual(self._satir_db(sid).faturalanan_miktar, Decimal("0"))
        f2 = self._fatura(SatisSiparisiService.getir(sp.id), 5)
        self.assertEqual(self._satir_db(sid).faturalanan_miktar, Decimal("5"))
        AuditDeleteService.delete_record(
            ENTITY_SATIS_FATURA, f2.id, reason="test silme", critical_confirm=f2.fatura_no
        )
        self.assertEqual(self._satir_db(sid).faturalanan_miktar, Decimal("0"))
        f3 = self._fatura(SatisSiparisiService.getir(sp.id), 10)
        self.assertEqual(SatisSiparisiService.getir(sp.id).durum, "FATURALI")
        self.assertEqual(siparis_ilerleme(SatisSiparisiService.getir(sp.id)), "TAMAMLANDI")
        self.assertTrue(f3.id)

    def test_onay_ve_onay_kaldir(self):
        sp = self._kaydet()
        SatisSiparisiService.onayla(sp.id)
        self.assertEqual(SatisSiparisiService.getir(sp.id).durum, "AÇIK")
        SatisSiparisiService.onay_kaldir(sp.id)
        self.assertEqual(SatisSiparisiService.getir(sp.id).durum, "TASLAK")
        SatisSiparisiService.onayla(sp.id)
        self._irsaliye(SatisSiparisiService.getir(sp.id), 1)
        with self.assertRaises(ValueError):
            SatisSiparisiService.onay_kaldir(sp.id)

    def test_iptal_edilen_siparis_duzenlenemez(self):
        sp = self._kaydet(onayla=True)
        SatisSiparisiService.iptal_et(sp.id, sebep="müşteri vazgeçti")
        with self.assertRaisesRegex(ValueError, "İptal|iptal"):
            self._kaydet([_satir(5, "Paket", id=sp.satirlar[0].id)], siparis_id=sp.id)

    def test_liste_filtreleri(self):
        a = self._kaydet(siparis_no="SS-A", musteri_siparis_no="REF-9", termin_tarihi=date(2026, 3, 5))
        b = self._kaydet(siparis_no="SS-B", siparis_tarihi=date(2026, 2, 1), termin_tarihi=date(2026, 12, 1), onayla=True)
        kayitlar = SatisSiparisiService.listele()
        idler = lambda ks: {k["siparis"].id for k in ks}  # noqa: E731
        self.assertEqual(idler(siparis_listesi_filtrele(kayitlar, siparis_no="ss-a")), {a.id})
        self.assertEqual(idler(siparis_listesi_filtrele(kayitlar, siparis_no="ref-9")), {a.id})
        self.assertEqual(idler(siparis_listesi_filtrele(kayitlar, baslangic=date(2026, 2, 15))), {a.id})
        self.assertEqual(idler(siparis_listesi_filtrele(kayitlar, termin_baslangic=date(2026, 6, 1))), {b.id})
        self.assertEqual(idler(siparis_listesi_filtrele(kayitlar, musteri="test müş")), {a.id, b.id})
        self.assertEqual(idler(siparis_listesi_filtrele(kayitlar, musteri="yok")), set())
        self.assertEqual(idler(siparis_listesi_filtrele(kayitlar, durum="TASLAK")), {a.id})
        self.assertEqual(idler(siparis_listesi_filtrele(kayitlar, durum="BEKLİYOR")), {b.id})
        gecikmis = self._kaydet(siparis_no="SS-G", siparis_tarihi=date.today() - timedelta(days=10),
                                termin_tarihi=date.today() - timedelta(days=2), onayla=True)
        kayitlar = SatisSiparisiService.listele()
        self.assertIn(gecikmis.id, idler(siparis_listesi_filtrele(kayitlar, durum="GECİKEN")))


class AlinanSiparisCiktiTest(_SiparisTemel):
    def _uzun_siparis(self, adet=45):
        satirlar = [
            _satir(i + 1, "Paket" if i % 3 else "Adet", "12.345", iskonto_orani=5 if i % 2 else 0,
                   urun_adi=UZUN_AD if i % 5 == 0 else f"Ürün {i + 1} ÇĞİÖŞÜ",
                   estimated_delivery_date=date(2026, 3, 25) if i % 4 == 0 else None,
                   aciklama="Satır açıklaması" if i % 7 == 0 else "")
            for i in range(adet)
        ]
        return self._kaydet(
            satirlar, musteri_siparis_no="PO-2026/15", teslimat_adresi="Atatürk Cad. No:5 Çankaya",
            teslimat_il="Ankara", teslim_kosulu="Alıcı deposunda teslim", odeme_kosulu="Peşin",
            aciklama="Ürünler paletli gönderilecek.\nİkinci satır: ığüşöç",
        )

    def test_model_tutarlari_ekranla_ayni_ve_guvenli(self):
        from database.siparis_form_view import build_siparis_form_from_record, render_siparis_form_html

        sp = self._uzun_siparis(12)
        vm = build_siparis_form_from_record(sp.id)
        t = belge_toplamlari(SatisSiparisiService.getir(sp.id).satirlar)
        self.assertEqual(vm.genel_goster, f"{t['genel_toplam']:,.2f}".replace(",", "X").replace(".", ",").replace("X", "."))
        html = render_siparis_form_html(vm)
        for beklenen in ("SATIŞ SİPARİŞ FORMU", "SİPARİŞİ HAZIRLAYAN", "MÜŞTERİ ONAYI", "PO-2026/15",
                         "Alıcı deposunda teslim", "Peşin", "Test Müşteri", "display:table-header-group",
                         "page-break-inside:avoid", "Termin", "ığüşöç"):
            self.assertIn(beklenen, html)
        for yasak in ("maliyet", "fifo", "Maliyet", "kâr"):
            self.assertNotIn(yasak, html)

    def test_eksik_kosul_uydurulmaz(self):
        from database.siparis_form_view import build_siparis_form_from_record, render_siparis_form_html

        sp = self._kaydet()
        html = render_siparis_form_html(build_siparis_form_from_record(sp.id))
        self.assertNotIn("Teslim Koşulu", html)
        self.assertNotIn("Ödeme Koşulu", html)

    def test_word_duzenlenebilir_baslik_tekrari(self):
        from docx import Document

        from invoice_print import siparis_cikti as sc

        sp = self._uzun_siparis()
        vm = sc.cikti_modeli(sp.id)
        hedef = Path(tempfile.mkdtemp()) / sc.varsayilan_dosya_adi(vm, "docx")
        self.assertRegex(hedef.name, r"^Satis_Siparisi_.+_2026-03-01\.docx$")
        sc.docx_olustur(vm, hedef)
        doc = Document(str(hedef))
        metin = "".join(doc.element.body.itertext())
        self.assertIn("SATIŞ SİPARİŞ FORMU", metin)
        self.assertIn("MÜŞTERİ ONAYI", metin)
        self.assertIn(vm.genel_goster, metin)
        self.assertIn("Ürün 2 ÇĞİÖŞÜ", metin)
        urun = next(t for t in doc.tables if t.rows[0].cells[0].text == "Sıra")
        self.assertEqual(len(urun.rows), 46)
        self.assertIn("w:tblHeader", urun.rows[0]._tr.xml)
        self.assertTrue(all("w:cantSplit" in r._tr.xml for r in urun.rows))
        self.assertEqual(len(doc.inline_shapes), 0, "görüntü değil metin")

    def test_pdf_cok_sayfa(self):
        from invoice_print import siparis_cikti as sc
        from invoice_print.pdf_service import _chrome_edge_paths

        if not _chrome_edge_paths():
            self.skipTest("Edge/Chrome yok")
        sp = self._uzun_siparis()
        vm = sc.cikti_modeli(sp.id)
        hedef = sc.pdf_olustur(vm, Path(tempfile.mkdtemp()) / "siparis.pdf")
        icerik = hedef.read_bytes()
        self.assertTrue(icerik.startswith(b"%PDF"))
        try:
            import pymupdf as fitz
        except ImportError:
            import fitz
        doc = fitz.open(str(hedef))
        try:
            self.assertGreaterEqual(doc.page_count, 2)
            son = doc[-1].get_text()
            self.assertIn(f"Sayfa {doc.page_count} / {doc.page_count}", son)
            self.assertIn("MÜŞTERİ ONAYI", son)
            self.assertIn("Sipariş No:", doc[0].get_text())
            self.assertAlmostEqual(doc[0].rect.width, 595, delta=3)
        finally:
            doc.close()


class _SiparisEkranTemel(_EkranTemel, _SiparisTemel):
    def _kart(self, **ek):
        from satis_siparisi_ui import SatisSiparisiKarti

        d = SatisSiparisiKarti(self.root, **ek)
        d.withdraw()
        return d

    def _urun_ekle(self, d, miktar="2", birim="Paket", fiyat=None, iskonto=None):
        d.urun_secildi(("MB001", "Birim Ürün", "Adet", "", "1"))
        idx = len(d.satirlar) - 1
        d.satir_hucre_uygula(idx, "miktar", miktar)
        d.satir_hucre_uygula(idx, "birim", birim)
        if fiyat is not None:
            d.satir_hucre_uygula(idx, "fiyat", fiyat)
        if iskonto is not None:
            d.satir_hucre_uygula(idx, "iskonto", iskonto)


class AlinanSiparisEkranTest(_SiparisEkranTemel):
    def test_menuden_bos_kart(self):
        d = self._kart()
        d._musteri_ata(self._cari())
        self._urun_ekle(d)
        self.assertTrue(d.kaydet(sessiz=True))
        d.destroy()
        yeni = self._kart()
        self.assertIsNone(yeni.siparis)
        self.assertIsNone(yeni.cari)
        self.assertEqual(yeni.satirlar, [])
        self.assertEqual(yeni._musteri_var.get(), "")
        self.assertEqual(yeni.girdiler["siparis_tarihi"].get(), date.today().strftime("%d.%m.%Y"))
        self.assertFalse(yeni.degisiklik_var())
        yeni.destroy()

    def test_urun_hesap_kaydet_yeniden_ac_duzenle_sil(self):
        d = self._kart()
        d._musteri_ata(self._cari())
        self.assertTrue(d.satir_tablosu.exists("__yeni__"))
        self._urun_ekle(d, "3", "Adet", fiyat="33,335", iskonto="10")
        self.assertIn("Paket", d._satir_birimleri(0))
        self._urun_ekle(d, "2", "Paket", fiyat="100")
        self.assertEqual(d.satir_tablosu.get_children()[-1], "__yeni__")
        self.assertEqual(d._toplam_lbl["kalem"].cget("text"), "2")
        self.assertEqual(d.satirlar[1]["birim"], "Paket")
        t = d.toplam_guncelle()
        beklenen = belge_toplamlari([
            {"miktar": 3, "birim_fiyat": "33.335", "iskonto_orani": 10, "kdv_orani": 20},
            {"miktar": 2, "birim_fiyat": "100", "kdv_orani": 20},
        ])
        self.assertEqual(t["genel_toplam"], beklenen["genel_toplam"])
        self.assertIn("TL", d._toplam_lbl["genel"].cget("text"))
        # hücrede miktar değişince toplam anında değişir; geri alınca eski toplam
        d.satir_hucre_uygula(1, "miktar", "5")
        self.assertNotEqual(d.toplam_guncelle()["genel_toplam"], beklenen["genel_toplam"])
        d.satir_hucre_uygula(1, "miktar", "2")
        self.assertEqual(d.toplam_guncelle()["genel_toplam"], beklenen["genel_toplam"])
        # yarım kalan arama metni kayda girmez
        d._satir_ici_giris.ac("ad", "yarım metin")
        self.assertTrue(d.kaydet(sessiz=True))
        self.assertEqual(len(d.satirlar), 2)
        self.assertTrue(d.kaydet(sessiz=True))
        sid = d.siparis.id
        d.destroy()
        with get_session() as session:
            self.assertEqual(session.scalar(select(func.count()).select_from(SatisSiparisi)), 1)
            self.assertEqual(session.scalar(select(func.count()).select_from(SatisSiparisiSatiri)), 2)
        acik = self._kart(siparis=SatisSiparisiService.getir(sid))
        self.assertEqual(acik.toplam_guncelle()["genel_toplam"], beklenen["genel_toplam"])
        self.assertFalse(acik.degisiklik_var())
        ilk_idler = [s["id"] for s in acik.satirlar]
        acik.satir_hucre_uygula(0, "miktar", "4")
        acik.satir_tablosu.selection_set("1")
        acik.satir_kaldir()
        self.assertTrue(acik.degisiklik_var())
        self.assertTrue(acik.kaydet(sessiz=True))
        acik.destroy()
        sp = SatisSiparisiService.getir(sid)
        self.assertEqual([(s.id, s.miktar) for s in sp.satirlar], [(ilk_idler[0], Decimal("4"))])

    def test_manuel_satir_ad_birim_zorunlu(self):
        d = self._kart()
        with patch("satis_siparisi_ui.simpledialog.askstring", return_value=""):
            self.assertIsNone(d.manuel_satir_ekle(""))
        self.assertEqual(d.satirlar, [])
        idx = d.manuel_satir_ekle("Özel imalat kapak")
        with self.assertRaisesRegex(ValueError, "ürün adı"):
            d.satir_hucre_uygula(idx, "ad", "")
        with self.assertRaisesRegex(ValueError, "Birim"):
            d.satir_hucre_uygula(idx, "birim", "")
        d.satir_hucre_uygula(idx, "birim", "Takım")
        self.assertIn("Takım", d._satir_birimleri(idx))
        self.assertEqual(d.satirlar[0]["urun_kodu"], "MANUEL")
        self.assertEqual(d.satirlar[0]["urun_adi"], "Özel imalat kapak")
        self.assertEqual(d.satirlar[0]["birim"], "Takım")
        self.assertTrue(d.satirlar[0]["is_manual_item"])
        d.destroy()

    def test_barkod_ayni_satiri_artirir_secim_yeni_satir(self):
        d = self._kart()
        d._musteri_ata(self._cari())
        giris = d._satir_ici_giris
        giris.son_islem = "barkod"
        d._satir_ici_urun_ekle(("MB001", "Birim Ürün", "Adet", "", "1"), None)
        d._satir_ici_urun_ekle(("MB001", "Birim Ürün", "Adet", "", "1"), None)
        giris.son_islem = "secim"
        self.assertEqual(len(d.satirlar), 1)
        self.assertEqual(d.satirlar[0]["miktar"], Decimal("2"))
        d.urun_secildi(("MB001", "Birim Ürün", "Adet", "", "1"))
        self.assertEqual(len(d.satirlar), 2)
        d._satir_ici_urun_ekle(("MB001", "Birim Ürün", "Adet", "", "1"), 0)
        self.assertEqual(len(d.satirlar), 3)
        d.satir_tablosu.selection_set("0")
        d.satir_cogalt()
        self.assertEqual(len(d.satirlar), 4)
        self.assertNotIn("id", d.satirlar[1])
        d.destroy()

    def test_eksik_musteri_kaydetmez(self):
        d = self._kart()
        self._urun_ekle(d)
        self.assertFalse(d.kaydet(sessiz=True))
        self.assertIsNone(d.siparis)
        self.assertIn("Müşteri", str(self.mesajlar[1].call_args))
        d._musteri_ata(self._cari())
        d._musteri_var.set("başka metin")
        self.assertFalse(d.kaydet(sessiz=True))
        with get_session() as session:
            self.assertEqual(session.scalar(select(func.count()).select_from(SatisSiparisi)), 0)
        d.destroy()

    def test_cift_kaydet_korumasi(self):
        d = self._kart()
        d._musteri_ata(self._cari())
        self._urun_ekle(d)
        d._kaydediliyor = True
        self.assertFalse(d.kaydet(sessiz=True))
        d._kaydediliyor = False
        self.assertTrue(d.kaydet(sessiz=True))
        with get_session() as session:
            self.assertEqual(session.scalar(select(func.count()).select_from(SatisSiparisi)), 1)
        d.destroy()

    def test_bagli_satir_kilitleri_ve_kalan_gosterimi(self):
        sp = self._kaydet(onayla=True)
        self._irsaliye(sp, 4)
        d = self._kart(siparis=SatisSiparisiService.getir(sp.id))
        degerler = d.satir_tablosu.item("0", "values")
        self.assertEqual(degerler[11:15], ("4", "0", "6", "10"))
        self.assertEqual(str(d.musteri.cget("state")), "disabled")
        self.assertEqual(str(d.btn["sil"].cget("state")), "disabled")
        self.assertEqual(d._satir_birimleri(0), ["Paket"])
        with self.assertRaisesRegex(ValueError, "altına indirilemez"):
            d.satir_hucre_uygula(0, "miktar", "3")
        with self.assertRaisesRegex(ValueError, "birimi değiştirilemez"):
            d.satir_hucre_uygula(0, "birim", "Adet")
        self.assertEqual(d.satirlar[0]["miktar"], Decimal("10"))
        self.assertFalse(d._satir_urun_degistir(0, ("MB001", "Birim Ürün", "Adet", "", "1")))
        d.satir_hucre_uygula(0, "miktar", "12")
        self.assertEqual(d.satirlar[0]["miktar"], Decimal("12"))
        d.satir_temizle()
        d.satir_tablosu.selection_set("0")
        d.satir_kaldir()
        self.assertEqual(len(d.satirlar), 1)
        self.assertIn("IRS", str(self.mesajlar[1].call_args).upper())
        d.destroy()

    def test_kapatirken_kaydetmeyi_sorar(self):
        d = self._kart()
        d._musteri_ata(self._cari())
        self._urun_ekle(d)
        with patch("satis_siparisi_ui.messagebox.askyesnocancel", return_value=None) as sor:
            d.kapat()
            self.assertTrue(sor.called)
            self.assertTrue(d.winfo_exists())
        with patch("satis_siparisi_ui.messagebox.askyesnocancel", return_value=True):
            d.kapat()
        with get_session() as session:
            self.assertEqual(session.scalar(select(func.count()).select_from(SatisSiparisi)), 1)

    def test_cikti_oncesi_kaydeder(self):
        d = self._kart()
        d._musteri_ata(self._cari())
        self._urun_ekle(d)
        with patch("siparis_cikti_ui.cikti_al") as cikti:
            d.word_kaydet()
        self.assertIsNotNone(d.siparis)
        cikti.assert_called_once_with(d, d.siparis.id, "word")
        d.destroy()

    def test_irsaliyeye_aktar_kismi_secim(self):
        sp = self._kaydet(onayla=True)
        d = self._kart(siparis=SatisSiparisiService.getir(sp.id))

        def _secim(parent, adaylar, **_k):
            secim = [dict(a) for a in adaylar]
            secim[0]["bu_belge_miktar"] = Decimal("3")
            return secim

        class _Irs:
            def __init__(self_, parent, siparis=None, satir_override=None):
                from database.satis_irsaliyesi_service import SatisIrsaliyesiService

                self_.result = SatisIrsaliyesiService.kaydet(
                    {"irsaliye_tarihi": date(2026, 3, 10), "cari_id": siparis.cari_id, "depo": "ANA DEPO",
                     "siparis_id": siparis.id},
                    satir_override,
                )

        with patch("kismi_belge_secim_ui.kismi_secim_yap", _secim), patch(
            "satis_irsaliyesi_ui.SatisIrsaliyesiDialog", _Irs
        ), patch.object(d, "wait_window"):
            d.irsaliyeye_aktar()
        self.assertEqual(d.satirlar[0]["irsaliyelenen"], Decimal("3"))
        self.assertEqual(self._satir_db(sp.satirlar[0].id).irsaliyelenen_miktar, Decimal("3"))
        d.destroy()


class AlinanSiparisListeTest(_SiparisEkranTemel):
    def _kok_olustur(self):
        import tkinter as tk

        import app as app_mod

        class _ListeKoku(tk.Tk):
            def __init__(self):
                super().__init__()
                self.geometry("1500x700+-4000+-4000")
                self.icerik = tk.Frame(self)
                self.icerik.pack(fill="both", expand=True)

            def _icerigi_temizle(self):
                for w in self.icerik.winfo_children():
                    w.destroy()

            def nav_sayfa_isaretle(self, *_a):
                pass

        for ad in (
            "satis_siparisleri_goster", "satis_siparisi_yeni_ac", "_siparis_tik_satiri", "_siparis_tik_basildi",
            "_siparis_tik_birakildi", "_siparis_sirala", "siparis_cikti", "_siparis_filtreleri",
            "siparis_listesini_yenile", "_secili_siparis_id", "siparis_ac", "yeni_siparis",
            "siparis_irsaliyeye_cevir", "siparis_faturaya_cevir", "siparis_iptal",
        ):
            setattr(_ListeKoku, ad, getattr(app_mod.MuhasebeApp, ad))
        return _ListeKoku()

    def setUp(self):
        super().setUp()
        self.a = self._kaydet(siparis_no="SS-L1", siparis_tarihi=date(2026, 3, 1))
        self.b = self._kaydet(siparis_no="SS-L2", siparis_tarihi=date(2026, 3, 2), onayla=True)
        self.root._sip_filtre = {}
        self.root.satis_siparisleri_goster()
        f = self.root._sip_filtre
        f["baslangic"].delete(0, "end")
        f["baslangic"].insert(0, "01.01.2026")
        self.root.siparis_listesini_yenile()

    def test_menu_ayrimi(self):
        from satis_ui import SATIS_HUB_KARTLARI

        anahtarlar = {k[0]: k[2] for k in SATIS_HUB_KARTLARI}
        self.assertEqual(anahtarlar["ALINAN SİPARİŞLER"], "siparis_yeni")
        self.assertEqual(anahtarlar["ALINAN SİPARİŞ LİSTESİ"], "siparis")

    def test_filtre_sirala_ve_id_ile_acar(self):
        t = self.root.siparis_tablosu
        self.assertEqual(set(t.get_children()), {str(self.a.id), str(self.b.id)})
        self.root._sip_filtre["siparis_no"].insert(0, "L2")
        self.root.siparis_listesini_yenile()
        self.assertEqual(t.get_children(), (str(self.b.id),))
        self.root._sip_filtre["siparis_no"].delete(0, "end")
        self.root._siparis_sirala("no")
        self.root._siparis_sirala("no")
        ilk = t.get_children()[0]
        self.assertEqual(ilk, str(self.b.id))
        acilan = []

        class _Kart:
            def __init__(self_, parent, siparis=None, **_k):
                acilan.append(siparis.id)

            def winfo_exists(self_):
                return False

        with patch("satis_siparisi_ui.SatisSiparisiKarti", _Kart):
            self.root.siparis_ac(int(ilk))
        self.assertEqual(acilan, [self.b.id])
        degerler = t.item(str(self.b.id), "values")
        self.assertEqual(degerler[1], "SS-L2")
        self.assertEqual(degerler[7], "AÇIK")
        self.assertEqual(degerler[8], "BEKLİYOR  ⚠ GECİKTİ", "termin (20.03.2026) bugünden önce")
        self.assertIn("gecikti", t.item(str(self.b.id), "tags"))
        self.assertNotIn("gecikti", t.item(str(self.a.id), "tags"), "TASLAK gecikmiş sayılmaz")

    def test_hatali_tarih_filtresi_mesaj(self):
        self.root._sip_filtre["termin_bitis"].insert(0, "99.99.2026")
        self.root.siparis_listesini_yenile()
        self.assertIn("Termin", str(self.mesajlar[1].call_args))


if __name__ == "__main__":
    unittest.main()
