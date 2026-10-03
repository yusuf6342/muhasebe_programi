"""Nakliye gider fişi / nakliye faturası → masraf dağıtımı → ürün alış faturası bağlantıları.

Her iki kaynak türü için: evrak seçimi, alış faturasına bağlama, dağıtım, kaydetme, yeniden
açma, iki yönlü erişim, geri alma; mükerrer borç/gider olmaması ve sahipsiz taslak temizliği.
"""

from __future__ import annotations

import sys
import unittest
from datetime import date
from decimal import Decimal
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

from sqlalchemy import func, inspect, select, text  # noqa: E402

import database.models.sube  # noqa: E402,F401
import test_masraf_dagitim as tmd  # noqa: E402
from database.database import get_session  # noqa: E402

TARIH_GIDER = tmd.TARIH_GIDER
TARIH_DAGITIM = tmd.TARIH_DAGITIM
GIDER_FISI = "GIDER_FISI"
HIZMET = "HIZMET_FATURASI"


class MasrafBaglantiTest(unittest.TestCase):
    setUp = tmd.MasrafDagitimTest.setUp
    tearDown = tmd.MasrafDagitimTest.tearDown
    _alis = tmd.MasrafDagitimTest._alis
    _gider = tmd.MasrafDagitimTest._gider
    _sat = tmd.MasrafDagitimTest._sat
    _lot = tmd.MasrafDagitimTest._lot
    _veri = tmd.MasrafDagitimTest._veri

    # ------------------------------------------------------------ yardımcı
    def _kasa(self) -> int:
        from database.models.finans import FinansHesabi

        with get_session() as s:
            h = s.scalar(select(FinansHesabi).where(FinansHesabi.hesap_adi == "Merkez Kasa"))
            if h is None:
                h = FinansHesabi(hesap_adi="Merkez Kasa", hesap_turu="KASA", acilis_bakiyesi=Decimal("100000"),
                                 aktif=True)
                s.add(h)
                s.flush()
            return int(h.id)

    def _gider_fisi(self, tutar="1000", kod="NAKLIYE", aciklama="Mobilya nakliyesi") -> int:
        from database.finans_service import FinansService
        from database.models.hizmet import HizmetKarti

        with get_session() as s:
            hizmet_id = s.scalar(select(HizmetKarti.id).where(HizmetKarti.hizmet_kodu == kod))
        fis = FinansService.gider_fisi_kaydet(
            {"tarih": TARIH_GIDER, "finans_hesap_id": self._kasa(), "hizmet_id": hizmet_id,
             "tutar": Decimal(tutar), "aciklama": aciklama}
        )
        return int(fis.id)

    def _fis_veri(self, fis_id, hedefler, tutar="1000", yontem="TUTAR"):
        v = self._veri(fis_id, [fis_id], hedefler, tutar=tutar, yontem=yontem)
        v["kaynak_turu"] = GIDER_FISI
        return v

    def _tablo_sayilari(self) -> dict[str, int]:
        """Operasyon tablolarının satır sayıları (masraf dağıtımı ve genel muhasebe fişleri hariç;
        fişler _fis_sayilari ile ayrıca doğrulanır)."""
        from database.database import company_db

        motor = company_db.engine
        sonuc = {}
        with motor.connect() as c:
            for t in inspect(motor).get_table_names():
                if t.startswith(("masraf_dagitim", "muhasebe_")):
                    continue
                sonuc[t] = c.execute(text(f'SELECT COUNT(*) FROM "{t}"')).scalar()
        return sonuc

    def _fis_sayilari(self) -> dict[str, int]:
        from database.models.genel_muhasebe import MuhasebeFisi

        with get_session() as s:
            return {str(k): int(n) for k, n in s.execute(
                select(MuhasebeFisi.kaynak_turu, func.count()).group_by(MuhasebeFisi.kaynak_turu)).all()}

    def _kasa_bakiye(self) -> Decimal:
        from sqlalchemy.orm import selectinload

        from database.finans_service import FinansService
        from database.models.finans import FinansHesabi

        with get_session() as s:
            h = s.scalar(select(FinansHesabi).options(selectinload(FinansHesabi.hareketler))
                         .where(FinansHesabi.id == self._kasa()))
            return FinansService.bakiye(h)

    # ----------------------------------------------------------- evrak seçimi
    def test_gider_fisi_evrak_secimi_arama_ve_gorunmeme_nedeni(self):
        from database.masraf_dagitim_service import MasrafDagitimService
        from database.models.finans import GiderFisi

        fis_id = self._gider_fisi("750")
        with get_session() as s:
            s.add(GiderFisi(belge_no="GDF-FAIZ-1", tarih=TARIH_GIDER, gider_turu="KREDI_FAIZ",
                            tutar=Decimal("50"), durum="AÇIK"))
        belgeler = MasrafDagitimService.kaynak_belgeler()
        fisler = [b for b in belgeler if b["tur"] == GIDER_FISI]
        self.assertEqual(len(fisler), 1)
        b = fisler[0]
        self.assertEqual(b["id"], fis_id)
        self.assertEqual(b["tarih"], TARIH_GIDER)
        self.assertIn("Merkez Kasa", b["cari"])
        self.assertEqual(b["genel_toplam"], Decimal("750.00"))
        self.assertEqual(b["toplam"], Decimal("750.00"))
        self.assertEqual(b["kalan"], Decimal("750.00"))
        self.assertIn("KDV", b["kural"])
        for arama in (b["no"], "nakliye", "02.06.2026", "750", "merkez kasa", "gider fişi"):
            self.assertEqual([x["id"] for x in MasrafDagitimService.kaynak_belgeler(arama, tur=GIDER_FISI)],
                             [fis_id], arama)
        self.assertEqual(MasrafDagitimService.kaynak_belgeler("olmayan-belge"), [])
        gizli = MasrafDagitimService.kaynak_gorunmeyenler("GDF-FAIZ")
        self.assertEqual(len(gizli), 1)
        self.assertIn("Kredi faiz", gizli[0]["neden"])

        detay = MasrafDagitimService.kaynak_detay(fis_id, tur=GIDER_FISI)
        self.assertEqual([s["id"] for s in detay["satirlar"]], [fis_id])
        self.assertTrue(detay["satirlar"][0]["uygun"])

    def test_ayni_numarali_fis_ve_fatura_karismaz(self):
        from database.masraf_dagitim_service import MasrafDagitimService

        _f, alis_satir = self._alis()
        fis_id = self._gider_fisi("300")
        kaynak_id, ks = self._gider("1000")
        self.assertEqual(fis_id, kaynak_id)  # ikisi de 1 numaralı kayıt
        did = MasrafDagitimService.taslak_kaydet(self._veri(kaynak_id, ks, [alis_satir]))
        MasrafDagitimService.onayla(did)
        fis = next(b for b in MasrafDagitimService.kaynak_belgeler(tumu=True) if b["tur"] == GIDER_FISI)
        self.assertEqual(fis["onceki_dagitim"], Decimal("0"))
        self.assertEqual(fis["kalan"], Decimal("300.00"))
        self.assertEqual(MasrafDagitimService.kaynak_baglantilari(fis_id, GIDER_FISI)["dagitimlar"], [])

    # ------------------------------------------------- gider fişi uçtan uca
    def test_gider_fisi_bagla_kaydet_yeniden_ac_onayla_iki_yonlu_geri_al(self):
        from database.finans_service import FinansService
        from database.masraf_dagitim_service import MasrafDagitimService

        from database.masraf_dagitim_service import ZatenIslendi
        from database.models.alis_faturasi import AlisFaturasiSatiri
        from database.models.satis_faturasi import SatisFaturasiSatiri

        fid, alis_satir = self._alis()
        satis_id = self._sat("40")
        fis_id = self._gider_fisi("1000")
        bakiye0 = self._kasa_bakiye()

        oniz = MasrafDagitimService.onizle(self._fis_veri(fis_id, [alis_satir]))
        s0 = oniz["satirlar"][0]
        self.assertEqual((s0["eski_birim_maliyet"], s0["pay"], s0["yeni_birim_maliyet"]),
                         (Decimal("100.0000"), Decimal("1000.00"), Decimal("110.0000")))
        self.assertEqual((oniz["kaynak_toplam"], oniz["kaynak_onceki"], oniz["kaynak_kalan_sonra"]),
                         (Decimal("1000.00"), Decimal("0"), Decimal("0.00")))

        did = MasrafDagitimService.taslak_kaydet(self._fis_veri(fis_id, [alis_satir]))
        d = MasrafDagitimService.getir(did)  # yeniden açma
        self.assertEqual((d["kaynak_turu"], d["kaynak_id"], d["kaynak_satir_idler"]), (GIDER_FISI, fis_id, [fis_id]))
        self.assertEqual([(s["alis_fatura_id"], s["alis_fatura_satiri_id"], s["pay"]) for s in d["satirlar"]],
                         [(fid, alis_satir, Decimal("1000.00"))])
        self.assertEqual(Decimal(str(self._lot().birim_maliyet)), Decimal("100"))

        once = self._tablo_sayilari()
        sonuc = MasrafDagitimService.onayla(did)
        self.assertEqual((sonuc["stok_payi"], sonuc["smm_payi"]), (Decimal("600.00"), Decimal("400.00")))
        self.assertEqual(Decimal(str(self._lot().birim_maliyet)), Decimal("110"))
        # Kasa ödemesi, gider fişi, hizmet hareketi, cari/KDV kayıtları yeniden oluşmaz
        self.assertEqual(self._tablo_sayilari(), once)
        self.assertEqual(self._kasa_bakiye(), bakiye0)
        # GM: gider fişinin eksik kaydı + dağıtım fişi, birer kez
        self.assertEqual(self._fis_sayilari(), {"gider_fisi": 1, "masraf_dagitimi": 1})
        # Tekrar onay mükerrer maliyet üretmez
        with self.assertRaises(ZatenIslendi):
            MasrafDagitimService.onayla(did)
        self.assertEqual(Decimal(str(self._lot().birim_maliyet)), Decimal("110"))
        self.assertEqual(self._fis_sayilari(), {"gider_fisi": 1, "masraf_dagitimi": 1})
        with get_session() as s:
            satis = s.scalar(select(SatisFaturasiSatiri).where(SatisFaturasiSatiri.fatura_id == satis_id))
            alis = s.get(AlisFaturasiSatiri, alis_satir)
            # Satılan 40 adet: SMM 400 TL → satış satırı birim maliyeti 110
            self.assertEqual(Decimal(str(satis.fifo_birim_maliyeti)), Decimal("110"))
            # Tedarikçi fatura fiyatı değişmez, yalnız maliyet katmanı artar
            self.assertEqual(Decimal(str(alis.birim_fiyat)), Decimal("100"))
            self.assertEqual(Decimal(str(alis.fifo_birim_maliyeti)), Decimal("110"))

        # İki yönlü erişim
        alis_tarafi = MasrafDagitimService.fatura_baglantilari(fid)
        self.assertEqual(len(alis_tarafi), 1)
        self.assertEqual((alis_tarafi[0]["kaynak_turu"], alis_tarafi[0]["kaynak_id"], alis_tarafi[0]["pay"]),
                         (GIDER_FISI, fis_id, Decimal("1000.00")))
        self.assertEqual(alis_tarafi[0]["satirlar"][0]["yeni_birim_maliyet"], Decimal("110.0000"))
        kaynak_tarafi = MasrafDagitimService.kaynak_baglantilari(fis_id, GIDER_FISI)
        self.assertEqual([f["fatura_id"] for f in kaynak_tarafi["alis_faturalari"]], [fid])
        self.assertEqual(kaynak_tarafi["dagitimlar"][0]["alis_faturalari"][0]["pay"], Decimal("1000.00"))
        self.assertEqual((kaynak_tarafi["dagitilan"], kaynak_tarafi["kalan"]), (Decimal("1000.00"), Decimal("0.00")))

        # Tekrar dağıtılamaz; kaynak listede görünmez, nedeni raporlanır
        self.assertFalse([b for b in MasrafDagitimService.kaynak_belgeler() if b["tur"] == GIDER_FISI])
        self.assertIn("Tutarın tamamı", MasrafDagitimService.kaynak_gorunmeyenler()[0]["neden"])
        with self.assertRaises(ValueError):
            MasrafDagitimService.onizle(self._fis_veri(fis_id, [alis_satir], tutar="1"))
        # Bağlı gider fişi iptal edilemez
        with self.assertRaises(ValueError):
            FinansService.gider_fisi_iptal(fis_id)

        # Geri alma: maliyet ve bağlantı birlikte kalkar, mükerrer kayıt yok
        self.assertTrue(MasrafDagitimService.geri_al(did, "Yanlış fatura"))
        self.assertEqual(Decimal(str(self._lot().birim_maliyet)), Decimal("100"))
        self.assertEqual(self._tablo_sayilari(), once)
        self.assertEqual(MasrafDagitimService.fatura_baglantilari(fid), [])
        self.assertEqual(MasrafDagitimService.kaynak_baglantilari(fis_id, GIDER_FISI)["kalan"], Decimal("1000.00"))
        self.assertFalse(MasrafDagitimService.geri_al(did, "tekrar"))  # ikinci geri alma etkisiz
        self.assertEqual(Decimal(str(self._lot().birim_maliyet)), Decimal("100"))
        self.assertEqual(self._fis_sayilari(),
                         {"gider_fisi": 1, "masraf_dagitimi": 1, "masraf_dagitimi_geri": 1})
        self.assertEqual([g["islem"] for g in MasrafDagitimService.getir(did)["gecmis"]],
                         ["TASLAK OLUŞTUR", "ONAY", "GERİ AL"])
        # Kaynak tutar yeniden dağıtılabilir
        yeni = MasrafDagitimService.taslak_kaydet(self._fis_veri(fis_id, [alis_satir]))
        MasrafDagitimService.iptal_et(yeni, "test")
        FinansService.gider_fisi_iptal(fis_id)  # kilit kalktı

    # ------------------------------------------------- nakliye faturası
    def test_nakliye_faturasi_farkli_tedarikci_kismi_dagitim_ve_hedef_secimi(self):
        from database.masraf_dagitim_service import MasrafDagitimService

        f1, s1 = self._alis("U001", "100", "100", "LOT-A")
        f2, s2 = self._alis("U001", "50", "100", "LOT-B")
        kaynak_id, ks = self._gider("1000")  # nakliyeci N001, ürün tedarikçisi T001

        faturalar = MasrafDagitimService.hedef_faturalar()
        self.assertEqual({f["fatura_id"] for f in faturalar}, {f1, f2})
        self.assertEqual({f["tedarikci"] for f in faturalar}, {"Test Tedarikçi"})
        self.assertEqual([h["satir_id"] for h in MasrafDagitimService.hedef_satirlar(fatura_id=f2)], [s2])

        d1 = MasrafDagitimService.taslak_kaydet(self._veri(kaynak_id, ks, [s1], tutar="600"))
        once = self._tablo_sayilari()  # cari borç, ödeme, KDV, açık kalem satırları
        MasrafDagitimService.onayla(d1)
        self.assertEqual(self._tablo_sayilari(), once)
        oniz = MasrafDagitimService.onizle(self._veri(kaynak_id, ks, [s2], tutar="400"))
        self.assertEqual((oniz["kaynak_onceki"], oniz["kaynak_kalan_sonra"]), (Decimal("600.00"), Decimal("0.00")))
        with self.assertRaises(ValueError) as ctx:
            MasrafDagitimService.onizle(self._veri(kaynak_id, ks, [s2], tutar="400.01"))
        self.assertIn("aşamaz", str(ctx.exception))
        d2 = MasrafDagitimService.taslak_kaydet(self._veri(kaynak_id, ks, [s2], tutar="400"))
        MasrafDagitimService.onayla(d2)
        self.assertEqual(Decimal(str(self._lot("LOT-A").birim_maliyet)), Decimal("106"))
        self.assertEqual(Decimal(str(self._lot("LOT-B").birim_maliyet)), Decimal("108"))
        self.assertEqual(self._fis_sayilari(), {"hizmet_faturasi": 1, "masraf_dagitimi": 2})

        bilgi = MasrafDagitimService.kaynak_baglantilari(kaynak_id)
        self.assertEqual({f["fatura_id"] for f in bilgi["alis_faturalari"]}, {f1, f2})
        self.assertEqual(bilgi["kalan"], Decimal("0.00"))
        self.assertEqual(MasrafDagitimService.fatura_baglantilari(f2)[0]["kaynak_turu"], HIZMET)
        self.assertEqual(next(f for f in MasrafDagitimService.hedef_faturalar() if f["fatura_id"] == f1)["dagitilan"],
                         Decimal("600.00"))

        # Geri alma sırası fark etmez; maliyetler başlangıca döner
        self.assertTrue(MasrafDagitimService.geri_al(d1, "test"))
        self.assertTrue(MasrafDagitimService.geri_al(d2, "test"))
        self.assertEqual(Decimal(str(self._lot("LOT-A").birim_maliyet)), Decimal("100"))
        self.assertEqual(Decimal(str(self._lot("LOT-B").birim_maliyet)), Decimal("100"))

    def test_irsaliyeli_alis_faturasi_maliyeti_bir_kez_artar(self):
        from database.alis_faturasi_service import AlisFaturasiService
        from database.alis_irsaliyesi_service import AlisIrsaliyesiService
        from database.masraf_dagitim_service import MasrafDagitimService
        from database.models.stok import StokLotu

        irs = AlisIrsaliyesiService.kaydet(
            {"irsaliye_tarihi": date(2026, 6, 1), "cari_id": self.tedarikci_id, "aciklama": None},
            [{"urun_kodu": "U001", "urun_adi": "Test Ürün", "miktar": Decimal("10"), "birim": "Adet",
              "birim_fiyat": Decimal("100"), "iskonto_orani": Decimal("0"), "kdv_orani": Decimal("20")}],
        )
        irs_satir = AlisIrsaliyesiService.getir(int(irs.id)).satirlar[0]
        fatura = AlisFaturasiService.kaydet(
            {"fatura_tarihi": date(2026, 6, 1), "vade_tarihi": date(2026, 6, 1), "cari_id": self.tedarikci_id,
             "irsaliye_id": int(irs.id), "depo": "ANA DEPO", "odeme_tutari": Decimal("0")},
            [{"urun_kodu": "U001", "urun_adi": "Test Ürün", "miktar": Decimal("10"), "birim": "Adet",
              "birim_fiyat": Decimal("100"), "iskonto_orani": Decimal("0"), "kdv_orani": Decimal("20"),
              "irsaliye_satiri_id": irs_satir.id, "lot_no": "LOT-IRS"}],
        )
        hedefler = MasrafDagitimService.hedef_satirlar("U001")
        self.assertEqual(len(hedefler), 1)  # irsaliye ayrı stok katmanı üretmez
        self.assertEqual(hedefler[0]["fatura_id"], int(fatura.id))
        fis_id = self._gider_fisi("100")
        did = MasrafDagitimService.taslak_kaydet(self._fis_veri(fis_id, [hedefler[0]["satir_id"]], tutar="100"))
        MasrafDagitimService.onayla(did)
        with get_session() as s:
            lotlar = s.scalars(select(StokLotu)).all()
        self.assertEqual(len(lotlar), 1)
        self.assertEqual(Decimal(str(lotlar[0].birim_maliyet)), Decimal("110"))

    # ------------------------------------------------- sahipsiz bağlantı
    def test_kaynak_veya_alis_iptalinde_taslak_otomatik_iptal(self):
        from database.alis_faturasi_service import AlisFaturasiService
        from database.finans_service import FinansService
        from database.masraf_dagitim_service import MasrafDagitimService

        fid, alis_satir = self._alis()
        fis_id = self._gider_fisi("500")
        d1 = MasrafDagitimService.taslak_kaydet(self._fis_veri(fis_id, [alis_satir], tutar="500"))
        FinansService.gider_fisi_iptal(fis_id)  # yalnız taslak bağlı → iptal serbest
        d = MasrafDagitimService.getir(d1)
        self.assertEqual(d["durum"], "İPTAL EDİLDİ")
        self.assertIn("iptal", d["geri_alma_nedeni"])
        self.assertIn("OTOMATİK İPTAL", [g["islem"] for g in d["gecmis"]])

        kaynak_id, ks = self._gider("800")
        d2 = MasrafDagitimService.taslak_kaydet(self._veri(kaynak_id, ks, [alis_satir], tutar="800"))
        AlisFaturasiService.iptal_et(fid)
        self.assertEqual(MasrafDagitimService.listele(durum="TASLAK"), [])
        self.assertEqual(MasrafDagitimService.getir(d2)["durum"], "İPTAL EDİLDİ")
        self.assertEqual(MasrafDagitimService.fatura_baglantilari(fid), [])
        with get_session() as s:
            from database.models.masraf_dagitim import MasrafDagitim

            self.assertEqual(s.scalar(select(func.count()).select_from(MasrafDagitim)
                                      .where(MasrafDagitim.durum == "TASLAK")), 0)

    # ------------------------------------------------- ekran akışı
    def test_ekran_gider_fisi_sec_bagla_kaydet_yeniden_ac_ve_iki_yonlu_pencere(self):
        import tkinter as tk

        from database.masraf_dagitim_service import MasrafDagitimService
        from masraf_dagitim_ui import BagliMasraflarDialog, MasrafDagitimDialog

        fid, alis_satir = self._alis()
        fis_id = self._gider_fisi("1000")
        fis_no = MasrafDagitimService.kaynak_detay(fis_id, tur=GIDER_FISI)["no"]
        try:
            root = tk.Tk()
        except tk.TclError:
            self.skipTest("Tk yok")
        root.withdraw()
        try:
            with patch("masraf_dagitim_ui.messagebox") as mb:
                mb.askyesno.return_value = True
                d = MasrafDagitimDialog(root)
                d.withdraw()
                d.tarih.delete(0, "end")
                d.tarih.insert(0, TARIH_DAGITIM.strftime("%d.%m.%Y"))
                d.kaynak_ayarla(fis_id, tur=GIDER_FISI)
                self.assertEqual(d.kaynak_turu, GIDER_FISI)
                self.assertEqual(d.secili_kaynak, {fis_id})
                self.assertEqual(d.tutar.get(), "1000")
                d.hedef_ekle(MasrafDagitimService.hedef_satirlar(fatura_id=fid))
                self.assertTrue(d.onizle())
                self.assertEqual(d.hedef_tablo.item(str(alis_satir), "values")[-1], "110")
                self.assertIn("Dağıtım sonrası kalan", d.ozet_lbl.cget("text"))
                self.assertTrue(d.taslak_kaydet(sessiz=True))
                did = d.dagitim_id
                d.destroy()

                d2 = MasrafDagitimDialog(root, dagitim_id=did)  # kapat / yeniden aç
                d2.withdraw()
                self.assertEqual((d2.kaynak_turu, d2.kaynak["id"], d2.secili_kaynak), (GIDER_FISI, fis_id, {fis_id}))
                self.assertEqual([(h["satir_id"], h["fatura_id"]) for h in d2.hedefler], [(alis_satir, fid)])
                self.assertEqual(d2.tutar.get(), "1000")
                self.assertTrue(d2.onayla())
                self.assertEqual(d2.durum, "ONAYLANDI")
                self.assertIn("SALT OKUNUR", d2.durum_lbl.cget("text"))
                d2.destroy()

                b1 = BagliMasraflarDialog(root, alis_fatura_id=fid)
                b1.withdraw()
                satirlar = [b1.tablo.item(i, "values") for i in b1.tablo.get_children()]
                self.assertEqual(len(satirlar), 1)
                self.assertIn(fis_no, satirlar[0])
                with patch("masraf_dagitim_ui.kaynak_belge_ac") as ac:
                    b1.kaynak_ac()
                    ac.assert_called_once_with(b1, GIDER_FISI, fis_id, fis_no)
                b1.destroy()

                b2 = BagliMasraflarDialog(root, kaynak_id=fis_id, kaynak_turu=GIDER_FISI)
                b2.withdraw()
                satirlar = [b2.tablo.item(i, "values") for i in b2.tablo.get_children()]
                self.assertEqual(len(satirlar), 1)
                with patch("masraf_dagitim_ui.alis_faturasi_ac") as ac:
                    b2.fatura_ac()
                    ac.assert_called_once_with(b2, fid)
                with patch("masraf_dagitim_ui.dagitim_ac") as ac:
                    b2.dagitimi_ac()
                    ac.assert_called_once_with(b2, did)
                b2.destroy()

                d3 = MasrafDagitimDialog(root, kaynak=(GIDER_FISI, fis_id))  # nakliye belgesinden yeni dağıtım
                d3.withdraw()
                self.assertEqual(d3.kaynak_turu, GIDER_FISI)
                self.assertEqual(d3.secili_kaynak, set())  # tamamı dağıtıldı
                d3._degisti = False
                d3.destroy()
        finally:
            root.destroy()


if __name__ == "__main__":
    unittest.main()
