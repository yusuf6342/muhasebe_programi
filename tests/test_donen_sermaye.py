"""Dönen Sermaye Bilançosu kabul kontrolleri — yalnız geçici test veritabanı; gerçek firma verisine dokunmaz."""

from __future__ import annotations

import os
import tempfile
import unittest
from datetime import date, datetime
from decimal import Decimal
from unittest.mock import patch

from tests.stok_test_ortami import StokOrtami

from database import donen_sermaye_service as ds
from database.database import get_session

D = Decimal
GUN = date(2026, 10, 10)


def _kalemler(sonuc, taraf) -> dict[str, Decimal]:
    return {r["etiket"]: r["tutar"] for r in sonuc[taraf] if r["seviye"] == ds.KALEM}


def _ara(sonuc, taraf) -> dict[str, Decimal]:
    return {r["etiket"]: r["tutar"] for r in sonuc[taraf] if r["seviye"] == ds.ARA_TOPLAM}


class SafKurallarTest(unittest.TestCase):
    def test_ornek_tablo_850_542_308(self):
        """7. bölüm: ara toplamlar bir kez; aktif 850.000, pasif -542.000, sonuç 308.000."""
        s = ds.satir
        aktif = [
            ds.grup("k", "KASALAR", "Kasalar ara toplam", [s("Merkez Kasa", 50000), s("Mağaza Kasa", 20000)]),
            ds.grup("b", "BANKA LİKİT VARLIKLARI", "Banka varlıkları ara toplam", [
                s("Banka A Mevduat TL", 80000), s("Banka E Vadeli TL", 30000), s("Banka B KMH", -25000),
                s("Banka D POS", 10000)]),
            ds.grup("m", "MÜŞTERİLER", "Müşteriler ara toplam", [s("Müşterilerden Alacaklar", 300000),
                                                                   s("Müşterilere Borçlar", -15000)]),
            ds.grup("s", "DEMİRBAŞ DIŞI STOKLAR", "Stoklar ara toplam", [s("Stok grubu A", 250000),
                                                                           s("Stok grubu B", 150000)]),
        ]
        pasif = [
            ds.grup("bb", "BANKA LİKİT BORÇLARI", "Banka borçları ara toplam", alt_gruplar=[
                ds.grup("kr", "Kredi Borçları Ana Para", "Kredi", [s("Kredi Ana Para Banka C", -160000)]),
                ds.grup("kk", "Kredi Kartı Borçları", "Kart", [s("Kredi Kartı Banka C", -45000)])]),
            ds.grup("t", "TEDARİKÇİLER", "Tedarikçiler ara toplam", [s("Tedarikçilere Borçlar", -220000),
                                                                       s("Tedarikçilerden Alacaklar", 18000)]),
            ds.grup("c", "FİRMA ÇEK VE SENETLERİ", "Çek senet ara toplam", [s("Firma Çek Borçları", -60000),
                                                                              s("Firma Senet Borçları", -25000)]),
            ds.grup("p", "PERSONEL BORÇLARI", "Personel ara toplam", [s("Personele Borçlar", -30000)]),
            ds.grup("d", "DİĞER KISA VADELİ BORÇLAR", "Diğer borçlar ara toplam",
                    [s("Diğer kapsamdaki borçlar", -20000)]),
        ]
        r = ds.rapor_olustur(aktif, pasif)
        self.assertEqual((r["aktif_toplam"], r["pasif_toplam"], r["donen_sermaye"]),
                         (D("850000.00"), D("-542000.00"), D("308000.00")))
        ara = _ara(r, ds.AKTIF)
        self.assertEqual((ara["Kasalar ara toplam"], ara["Banka varlıkları ara toplam"],
                          ara["Müşteriler ara toplam"], ara["Stoklar ara toplam"]),
                         (D("70000.00"), D("95000.00"), D("285000.00"), D("400000.00")))
        ara = _ara(r, ds.PASIF)
        self.assertEqual((ara["Banka borçları ara toplam"], ara["Tedarikçiler ara toplam"],
                          ara["Çek senet ara toplam"]), (D("-205000.00"), D("-202000.00"), D("-85000.00")))
        self.assertEqual([x["etiket"] for x in r[ds.AKTIF] if x["seviye"] == ds.BASLIK],
                         ["KASALAR", "BANKA LİKİT VARLIKLARI", "MÜŞTERİLER", "DEMİRBAŞ DIŞI STOKLAR"])
        self.assertEqual(ds.tutar_metni(r["donen_sermaye"]), "308.000,00")
        self.assertEqual(ds.tutar_metni(r["pasif_toplam"]), "-542.000,00")

    def test_musteri_ve_tedarikci_ayri_toplamlar(self):
        """Kontrol 1-2: farklı carilerin alacak / borcu netleşmez; isim listesi ayrıntıdadır."""
        m = ds.cari_ozet_satirlari([("A", D(25000)), ("B", D(40000)), ("C", D(-7000))],
                                   "Müşterilerden Alacaklar", "Müşterilere Borçlar")
        self.assertEqual([(x["etiket"], x["tutar"]) for x in m],
                         [("Müşterilerden Alacaklar", D("65000.00")), ("Müşterilere Borçlar", D("-7000.00"))])
        t = ds.cari_ozet_satirlari([("X", D(-90000)), ("Y", D(-60000)), ("Z", D(12000))],
                                   "Tedarikçilerden Alacaklar", "Tedarikçilere Borçlar", once_arti=False)
        self.assertEqual([(x["etiket"], x["tutar"]) for x in t],
                         [("Tedarikçilere Borçlar", D("-150000.00")), ("Tedarikçilerden Alacaklar", D("12000.00"))])
        r = ds.rapor_olustur([ds.grup("m", "MÜŞTERİLER", "Müşteriler ara toplam", m)],
                             [ds.grup("t", "TEDARİKÇİLER", "Tedarikçiler ara toplam", t)])
        self.assertEqual(_ara(r, ds.AKTIF)["Müşteriler ara toplam"], D("58000.00"))
        self.assertEqual(_ara(r, ds.PASIF)["Tedarikçiler ara toplam"], D("-138000.00"))

    def test_kmh_arti_ve_eksi_hep_aktifte(self):
        """Kontrol 5: KMH +10.000 ve -25.000 iki durumda da aktifte, kendi satırında."""
        for bakiye in (D(10000), D(-25000)):
            r = ds.rapor_olustur([ds.grup("b", "BANKA", "Banka", [ds.satir("Banka B KMH", bakiye)])], [])
            self.assertEqual(_kalemler(r, ds.AKTIF), {"Banka B KMH": bakiye.quantize(D("0.01"))})
            self.assertEqual(r["pasif"], [])
            self.assertEqual(r["donen_sermaye"], bakiye)

    def test_sifir_satir_gizli_net_sifir_grup_gorunur_eksi_sifir_yok(self):
        """Kontrol 10: sıfır hesap gizli; net sıfır grup 0,00 ara toplamıyla görünür; -0,00 oluşmaz."""
        r = ds.rapor_olustur([
            ds.grup("k", "KASALAR", "Kasalar ara toplam", [ds.satir("Boş kasa", D("-0.001"))]),
            ds.grup("m", "MÜŞTERİLER", "Müşteriler ara toplam", [ds.satir("Alacak", 500), ds.satir("Borç", -500)]),
        ], [])
        self.assertNotIn("KASALAR", [x["etiket"] for x in r[ds.AKTIF]])
        self.assertEqual(_ara(r, ds.AKTIF), {"Müşteriler ara toplam": D("0.00")})
        self.assertEqual(ds.tutar_metni(D("-0.004")), "0,00")
        self.assertEqual(ds.tutar_metni(D("-1234.5")), "-1.234,50")
        self.assertEqual(ds.tutar_metni(r["aktif_toplam"]), "0,00")

    def test_kredi_yalniz_kalan_ana_para(self):
        """Kontrol 6: 24.000 taksit (18.000 ana para + 6.000 faiz/masraf) → -18.000; 4.000 ödenince -14.000."""
        taksit = [{"id": 1, "vade": date(2026, 11, 1), "anapara": D(18000), "durum": "BEKLIYOR",
                   "odenen_anapara": D(0), "odeme_tarihi": None}]
        self.assertEqual(ds.kredi_kalanlari(taksit, [], GUN), {1: D(18000)})
        odeme = [{"taksit_id": 1, "tarih": GUN, "anapara": D(4000)}]
        self.assertEqual(ds.kredi_kalanlari(taksit, odeme, GUN), {1: D(14000)})
        self.assertEqual(ds.kredi_kalanlari(taksit, odeme, date(2026, 10, 9)), {1: D(18000)},
                         "rapor tarihinden sonraki ödeme düşülmez")
        alti = [{"id": i, "vade": date(2026, 10 + i // 3, 1 + i), "anapara": D(18000), "durum": "BEKLIYOR",
                 "odenen_anapara": D(0), "odeme_tarihi": None} for i in range(6)]
        self.assertEqual(sum(ds.kredi_kalanlari(alti, [], GUN).values()), D(108000))

    def test_kredi_taksite_baglanmamis_odeme_son_vadeden_duser(self):
        taksitler = [{"id": 1, "vade": date(2026, 11, 1), "anapara": D(1000), "durum": "BEKLIYOR",
                      "odenen_anapara": D(0), "odeme_tarihi": None},
                     {"id": 2, "vade": date(2027, 11, 1), "anapara": D(1000), "durum": "BEKLIYOR",
                      "odenen_anapara": D(0), "odeme_tarihi": None},
                     {"id": 3, "vade": date(2027, 12, 1), "anapara": D(1000), "durum": "IPTAL",
                      "odenen_anapara": D(0), "odeme_tarihi": None}]
        k = ds.kredi_kalanlari(taksitler, [{"taksit_id": None, "tarih": GUN, "anapara": D(1500)}], GUN)
        self.assertEqual(k, {1: D(500), 2: D(0)})

    def test_demirbas_grubu_alt_gruplariyla_haric(self):
        """Kontrol 14: işaretli grup ve alt grupları ile kart türü 'Demirbaş' hariç; ad tahmini yok."""
        gruplar = {1: {"parent_id": None, "ad": "Demirbaş"}, 2: {"parent_id": 1, "ad": "Raf"},
                   3: {"parent_id": None, "ad": "Hırdavat"}, 4: {"parent_id": None, "ad": "DEMİRBAŞ eski"}}
        self.assertTrue(ds.demirbas_mi({"ana_grup_id": 1, "tali_grup_id": 2}, gruplar, {1}))
        self.assertTrue(ds.demirbas_mi({"ana_grup_id": None, "tali_grup_id": 2}, gruplar, {1}))
        self.assertFalse(ds.demirbas_mi({"ana_grup_id": 3}, gruplar, {1}))
        self.assertFalse(ds.demirbas_mi({"ana_grup_id": 4}, gruplar, {1}), "adı Demirbaş olan grup tahmin edilmez")
        self.assertTrue(ds.demirbas_mi({"ana_grup_id": 3, "kart_turu": "Demirbaş"}, gruplar, set()))
        self.assertEqual(ds.stok_kok_grubu({"ana_grup_id": 1, "tali_grup_id": 2}, gruplar), (1, True))
        self.assertEqual(ds.stok_kok_grubu({"ana_grup_id": 3, "tali_grup_id": 2}, gruplar), (3, False))


class DonenSermayeVeritabaniTest(unittest.TestCase):
    """Örnek tablonun ön muhasebe kayıtlarıyla kurulması (muhasebe fişi yok)."""

    def setUp(self):
        self._ayar = tempfile.TemporaryDirectory(prefix="donen_ayar_")
        self._env = patch.dict(os.environ, {"LOCALAPPDATA": self._ayar.name})
        self._env.start()
        self.o = StokOrtami("donen_sermaye")
        self._kur()

    def tearDown(self):
        self.o.kapat()
        self._env.stop()
        self._ayar.cleanup()

    def _kur(self):
        from database import giris_ozet_service as go
        from database.models.cari import Cari, CariIslem
        from database.models.cek_senet import CekSenetEvrak, CekSenetHareket
        from database.models.finans import BankaKarti, BankaKredisi, BankaKrediTaksit, FinansHesabi
        from database.models.stok import StokGrubu, StokKarti

        for tablo in (CekSenetEvrak.__table__, CekSenetHareket.__table__):
            tablo.create(self.o.engine, checkfirst=True)
        with get_session() as s:
            bk = BankaKarti(banka_adi="Banka C")
            s.add(bk)
            s.flush()
            self.bk = bk.id
            hesaplar = (("Merkez Kasa", "KASA", None, 50000), ("Mağaza Kasa", "KASA", None, 20000),
                        ("Banka A Mevduat TL", "BANKA", "MEVDUAT", 80000), ("Banka E Vadeli TL", "BANKA", "VADELI", 30000),
                        ("Banka B KMH", "BANKA", "KMH", -25000), ("Banka D POS", "BANKA", "POS", 10000),
                        ("Banka C Kredi Kartı", "BANKA", "KREDI_KARTI", 45000),
                        ("Banka C Krediler", "BANKA", "KREDILER", 200000), ("Boş Kasa", "KASA", None, 0))
            for ad, tur, alt, acilis in hesaplar:
                h = FinansHesabi(hesap_adi=ad, hesap_turu=tur, alt_hesap_turu=alt, acilis_bakiyesi=D(acilis),
                                 banka_karti_id=None if tur == "KASA" else bk.id)
                s.add(h)
                s.flush()
                if alt == "MEVDUAT":
                    self.mevduat = h.id
            for kod, tur in (("M002", "Müşteri"), ("M003", "Müşteri"), ("T002", "Tedarikçi"), ("T003", "Tedarikçi"),
                             ("P001", "Personel"), ("D001", "Ortak")):
                s.add(Cari(cari_kodu=kod, unvan=f"Cari {kod}", cari_turu=tur, aktif=True))
            k = BankaKredisi(belge_no="KRD-1", banka_karti_id=bk.id, kredi_adi="İşletme", ana_para=D(200000),
                             kullandirim_tarihi=date(2026, 9, 1), ilk_taksit_tarihi=date(2026, 11, 1))
            s.add(k)
            s.flush()
            self.kredi = k.id
            for no, vade, ana in ((1, date(2026, 11, 1), 100000), (2, date(2027, 2, 1), 60000),
                                  (3, date(2028, 4, 1), 40000)):
                t = BankaKrediTaksit(kredi_id=k.id, taksit_no=no, vade_tarihi=vade, anapara=D(ana), faiz=D(5000),
                                     masraf=D(1000))
                s.add(t)
                s.flush()
                if no == 1:
                    self.taksit1 = t.id
            for i, (tur, tutar) in enumerate((("FIRMA_CEKI", 60000), ("FIRMA_SENEDI", 25000), ("FIRMA_CEKI", 9999))):
                s.add(CekSenetEvrak(evrak_turu=tur, islem_yonu="VERILEN", evrak_no=f"E{i}", portfoy_no=f"VR{i}",
                                    duzenleme_tarihi=date(2026, 10, 1), vade_tarihi=date(2026, 12, 1),
                                    tl_tutari=D(tutar), kalan_tutar=D(tutar),
                                    durum="ODENDI" if tutar == 9999 else "TEDARIKCIYE_VERILDI"))
            grup_a = StokGrubu(kod="A", ad="Stok grubu A", seviye=1, sira_no=0, aktif=True)
            grup_b = StokGrubu(kod="B", ad="Stok grubu B", seviye=1, sira_no=0, aktif=True)
            dm = StokGrubu(kod="DMR", ad="Demirbaş", seviye=1, sira_no=0, aktif=True)
            s.add_all([grup_a, grup_b, dm])
            s.flush()
            raf = StokGrubu(kod="DMR-RAF", ad="Raf", seviye=2, parent_id=dm.id, sira_no=0, aktif=True)
            s.add(raf)
            s.flush()
            self.demirbas_grup = dm.id
            s.query(StokKarti).filter_by(stok_kodu="U001").one().ana_grup_id = grup_a.id
        u003 = self.o.urun_ekle("U003", "B ürünü")
        u002 = self.o.urun_ekle("U002", "Raf demirbaş")
        with get_session() as s:
            s.get(StokKarti, u003).ana_grup_id = grup_b.id
            s.get(StokKarti, u002).tali_grup_id = raf.id
        self.o.alis(2500, 100, date(2026, 9, 15), kod="U001")
        self.o.alis(1500, 100, date(2026, 9, 15), kod="U003")
        self.o.alis(700, 100, date(2026, 9, 15), kod="U002")

        with get_session() as s:
            cid = {c.cari_kodu: c.id for c in s.query(Cari).all()}
            t001 = go.cari_bakiyeleri(go._Baglam(s, GUN, GUN, None))[0].get(cid["T001"], D(0))

        def ci(kod, borc=0, alacak=0, tarih=GUN):
            with get_session() as s:
                s.add(CariIslem(cari_id=cid[kod], tarih=tarih, islem_turu="Açılış", belge_no=f"AC-{kod}-{tarih}",
                                borc=D(borc), alacak=D(alacak)))

        ci("T001", alacak=t001)
        ci("M001", borc=250000)
        ci("M002", borc=50000)
        ci("M003", alacak=15000)
        ci("T002", borc=220000)
        ci("T003", alacak=18000)
        ci("P001", borc=30000)
        ci("D001", alacak=20000)
        self.cid = cid

    def _hesapla(self, tarih=GUN):
        return ds.hesapla(tarih, bugun=GUN)

    def test_ornek_veriyle_tam_bilanco(self):
        """Kontrol 1-11, 14: sabit taraflar, işaretler, kredi ana para, çek senet, demirbaş, toplamlar."""
        r0 = self._hesapla()
        self.assertEqual(_kalemler(r0, ds.AKTIF)["Demirbaş"], D("70000.00"), "işaretlenmeden ad tahmini yapılmaz")
        self.assertTrue(any("grup #" in n and "işaretli değil" in n for n in r0["notlar"]))
        ds.demirbas_gruplarini_kaydet({self.demirbas_grup})
        r = self._hesapla()
        a, p = _kalemler(r, ds.AKTIF), _kalemler(r, ds.PASIF)
        self.assertEqual((a["Merkez Kasa"], a["Mağaza Kasa"]), (D("50000.00"), D("20000.00")))
        self.assertNotIn("Boş Kasa", a)
        self.assertEqual((a["Banka A Mevduat TL"], a["Banka E Vadeli TL"], a["Banka B KMH"], a["Banka D POS"]),
                         (D("80000.00"), D("30000.00"), D("-25000.00"), D("10000.00")))
        self.assertEqual((a["Müşterilerden Alacaklar"], a["Müşterilere Borçlar"]), (D("300000.00"), D("-15000.00")))
        self.assertEqual((a["Stok grubu A"], a["Stok grubu B"]), (D("250000.00"), D("150000.00")))
        self.assertNotIn("Demirbaş", a)
        self.assertEqual(p["Kredi Ana Para — Banka C"], D("-160000.00"), "yalnız 12 ay içindeki ana para")
        self.assertEqual(p["Kredi Kartı — Banka C Kredi Kartı"], D("-45000.00"))
        self.assertEqual((p["Tedarikçilere Borçlar"], p["Tedarikçilerden Alacaklar"]),
                         (D("-220000.00"), D("18000.00")))
        self.assertEqual((p["Firma Çek Borçları"], p["Firma Senet Borçları"]), (D("-60000.00"), D("-25000.00")))
        self.assertEqual(p["Personele Borçlar"], D("-30000.00"))
        self.assertEqual(p["Diğer Cari Borçlar"], D("-20000.00"))
        self.assertNotIn("Banka B KMH", p)
        self.assertEqual((r["aktif_toplam"], r["pasif_toplam"], r["donen_sermaye"]),
                         (D("850000.00"), D("-542000.00"), D("308000.00")))
        self.assertEqual(r0["donen_sermaye"] - r["donen_sermaye"], D("70000.00"), "demirbaş 70.000 hariç")
        self.assertTrue(any("uzun vadeli" in n for n in r["notlar"]))
        self.assertFalse(r["eksikler"])
        satirlar = ds.disa_aktarim_satirlari(r)
        self.assertEqual(satirlar[-1], ["", "sonuc", "DÖNEN SERMAYE", "308.000,00"])

    def test_ters_bakiyeler_taraf_degistirmez(self):
        """Kontrol 4, 7: eksi kasa / mevduat aktifte eksi; kart ve kredi ters bakiyede pasifte artı."""
        from database.models.finans import BankaKrediOdeme, FinansHareketi, FinansHesabi

        with get_session() as s:
            hesap = {h.hesap_adi: h.id for h in s.query(FinansHesabi).all()}
            s.add(FinansHareketi(hesap_id=hesap["Merkez Kasa"], tarih=GUN, hareket_turu="CARİ ÖDEME",
                                 belge_no="X1", tutar=D(60000)))
            s.add(FinansHareketi(hesap_id=hesap["Banka C Kredi Kartı"], tarih=GUN, hareket_turu="BANKA ÇIKIŞ",
                                 belge_no="X2", tutar=D(50000)))
            for no, tid in ((1, self.taksit1), (2, None)):
                s.add(BankaKrediOdeme(transaction_id=f"T{no}", kredi_id=self.kredi, taksit_id=tid,
                                      odeme_turu="TAKSIT" if tid else "ARA", odeme_tarihi=GUN,
                                      odeme_belge_no=f"KO{no}", banka_hesap_id=self.mevduat,
                                      anapara=D(100000) if tid else D(50000)))
        r = self._hesapla()
        a, p = _kalemler(r, ds.AKTIF), _kalemler(r, ds.PASIF)
        self.assertEqual(a["Merkez Kasa"], D("-10000.00"))
        self.assertEqual(p["Kredi Kartı — Banka C Kredi Kartı"], D("5000.00"), "ters bakiye pasifte artı")
        self.assertEqual(p["Kredi Ana Para — Banka C"], D("-50000.00"),
                         "ara ödeme en son vadeden düşer: 40.000 uzun vade + 10.000 ikinci taksitten")
        self.assertTrue(any("Merkez Kasa" in n and "eksi bakiyede" in n for n in r["notlar"]))

    def test_rapor_tarihi_ve_cek_durum_gecmisi(self):
        """Kontrol 10: tarih sonu bakiyesi; sonradan ödenen çek rapor tarihinde açık sayılır."""
        from database.models.cek_senet import CekSenetEvrak, CekSenetHareket

        with get_session() as s:
            e = s.query(CekSenetEvrak).filter_by(portfoy_no="VR0").one()
            e.durum, e.kalan_tutar = "ODENDI", D(0)
            s.add(CekSenetHareket(evrak_id=e.id, tarih=datetime(2026, 10, 2, 9), onceki_durum=None,
                                  yeni_durum="TEDARIKCIYE_VERILDI", islem_turu="KAYIT", tutar=D(60000)))
            s.add(CekSenetHareket(evrak_id=e.id, tarih=datetime(2026, 10, 9, 9), onceki_durum="TEDARIKCIYE_VERILDI",
                                  yeni_durum="ODENDI", islem_turu="ODEME", tutar=D(60000)))
        once = self._hesapla(date(2026, 10, 5))
        simdi = self._hesapla(GUN)
        self.assertEqual(_kalemler(once, ds.PASIF)["Firma Çek Borçları"], D("-60000.00"))
        self.assertNotIn("Firma Çek Borçları", _kalemler(simdi, ds.PASIF))
        self.assertNotIn("Müşterilerden Alacaklar", _kalemler(once, ds.AKTIF), "10.10 cari hareketi 05.10'da yok")
        eylul = self._hesapla(date(2026, 8, 31))
        self.assertNotIn("DEMİRBAŞ DIŞI STOKLAR", [x["etiket"] for x in eylul[ds.AKTIF]])
        self.assertNotIn("Kredi Ana Para — Banka C", _kalemler(eylul, ds.PASIF), "kullandırımdan önce kredi yok")

    def test_sayac_yalniz_basarili_committe_artar(self):
        """Kontrol 15 / bölüm 8: başarılı işlem sonrası açık rapor yenilenir; geri alınan işlem etki üretmez."""
        from database.models.cari import CariIslem

        once = ds.degisim_sayaci()
        try:
            with get_session() as s:
                s.add(CariIslem(cari_id=self.cid["M002"], tarih=GUN, islem_turu="Tahsilat", belge_no="RB-1",
                                borc=D(0), alacak=D(1000)))
                s.flush()
                raise RuntimeError("vazgeçildi")
        except RuntimeError:
            pass
        self.assertEqual(ds.degisim_sayaci(), once)
        r1 = self._hesapla()
        self.assertEqual(ds.degisim_sayaci(), once, "rapor hesabı yazma yapmaz")
        with get_session() as s:
            s.add(CariIslem(cari_id=self.cid["M002"], tarih=GUN, islem_turu="Tahsilat", belge_no="TH-1",
                            borc=D(0), alacak=D(1000)))
        self.assertEqual(ds.degisim_sayaci(), once + 1)
        r2 = self._hesapla()
        self.assertEqual(r1["donen_sermaye"] - r2["donen_sermaye"], D("1000.00"))

    def test_muhasebe_fisi_sonucu_degistirmez(self):
        """Kontrol 12-13: muhasebe fişi kaynak değildir; fiş eklemek / olmaması sonucu değiştirmez."""
        from database.models.genel_muhasebe import MuhasebeFisi

        from database.models.firma import Firma

        r1 = self._hesapla()
        with get_session() as s:
            firma = s.query(Firma).first()
            s.add(MuhasebeFisi(firma_id=firma.id, mali_yil=2026, fis_no="MF-1", fis_tarihi=GUN, fis_turu="MAHSUP",
                               durum="Onaylı", kaynak_turu="SATIS_FATURASI", kaynak_id=1,
                               toplam_borc=D(999999), toplam_alacak=D(999999)))
        r2 = self._hesapla()
        self.assertEqual(r1["donen_sermaye"], r2["donen_sermaye"])


if __name__ == "__main__":
    unittest.main()
