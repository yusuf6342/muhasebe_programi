"""Finans İşlem Ayarları (KMH / POS / şirket kartı, çek-senet aşamaları, banka kredisi) ve liste ekranlarındaki
muhasebe durumu kolonu.

Her test yalıtılmış geçici veritabanında çalışır (gerçek firma verisine dokunulmaz).
"""

from __future__ import annotations

import sys
import tkinter as tk
import unittest
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path
from tkinter import ttk
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

from sqlalchemy import select  # noqa: E402

import database.models.sube  # noqa: E402,F401
import test_masraf_dagitim as tmd  # noqa: E402
import test_masraf_dagitim_baglanti as tmb  # noqa: E402
import test_muhasebelestirme_ayarlari as tma  # noqa: E402
from database.database import get_session  # noqa: E402
from database.models.genel_muhasebe import (  # noqa: E402
    BELGE_BEKLIYOR,
    BELGE_INCELEME,
    BELGE_IPTAL,
    BELGE_MUHASEBE_DISI,
    BELGE_MUHASEBELESTIRILDI,
)

TARIH = date(2026, 6, 5)

EK_HESAPLAR = {
    "kmh_hesabi": ("300.01.0001", "KMH Kredisi", "Pasif"),
    "pos_valor_alacagi": ("108.01.0001", "POS Valör Alacağı", "Aktif"),
    "pos_komisyon_gideri": ("780.01.0001", "POS Komisyon Gideri", "Gider"),
    "sirket_kart_borcu": ("309.01.0001", "Şirket Kredi Kartı Borcu", "Pasif"),
    "cek_portfoy": ("101.01.0001", "Portföydeki Çekler", "Aktif"),
    "cek_tahsilde": ("101.01.0002", "Tahsildeki Çekler", "Aktif"),
    "kredi_kisa_vadeli": ("300.01.0002", "Banka Kredileri (Kısa)", "Pasif"),
    "kredi_uzun_vadeli": ("400.01.0001", "Banka Kredileri (Uzun)", "Pasif"),
}


class _Temel(unittest.TestCase):
    setUp = tma.MuhasebelestirmeAyarlariTest.setUp
    tearDown = tma.MuhasebelestirmeAyarlariTest.tearDown
    _servis = staticmethod(tma.MuhasebelestirmeAyarlariTest._servis)
    _ayar = tma.MuhasebelestirmeAyarlariTest._ayar
    _fis_sayisi = tma.MuhasebelestirmeAyarlariTest._fis_sayisi
    _durum = tma.MuhasebelestirmeAyarlariTest._durum
    _durum_id = tma.MuhasebelestirmeAyarlariTest._durum_id
    _bakiyeler = tma.MuhasebelestirmeAyarlariTest._bakiyeler
    _tutarli = tma.MuhasebelestirmeAyarlariTest._tutarli
    _alis = tmd.MasrafDagitimTest._alis
    _sat = tmd.MasrafDagitimTest._sat
    _gider = tmd.MasrafDagitimTest._gider
    _kasa = tmb.MasrafBaglantiTest._kasa
    _gider_fisi = tmb.MasrafBaglantiTest._gider_fisi

    # ------------------------------------------------------------ yardımcılar
    def _hesap_bagla(self, *anahtarlar):
        """Ek hesapları açar ve eşleştirmeyi uygulama servisiyle (fişe uygunluk denetimli) bağlar."""
        from database.models.genel_muhasebe import HesapPlani
        from database.muhasebe_entegrasyon import HesapEslemeService
        from database.muhasebe_service import MuhasebeService

        MuhasebeService.esleme_sablonlarini_doldur()
        for anahtar in anahtarlar:
            kod, ad, tur = EK_HESAPLAR[anahtar]
            with get_session() as s:
                h = s.scalar(select(HesapPlani).where(HesapPlani.hesap_kodu == kod))
                if h is None:
                    h = HesapPlani(firma_id=self.firma_id, hesap_kodu=kod, hesap_adi=ad, hesap_seviyesi=3,
                                   hesap_turu=tur, borc_toplam=0, alacak_toplam=0, aktif=True)
                    s.add(h)
                    s.flush()
                hid = int(h.id)
            HesapEslemeService.kaydet(anahtar, hid)

    def _banka_karti(self, ad="Akbank", komisyon="2") -> dict[str, int]:
        from database.models.finans import BankaKarti, FinansHesabi

        with get_session() as s:
            kart = BankaKarti(banka_adi=ad, kk_komisyon_orani=Decimal(komisyon), pos_valor_gun=1, aktif=True)
            s.add(kart)
            s.flush()
            sonuc = {"kart": int(kart.id)}
            for alt in ("MEVDUAT", "KMH", "POS", "KREDILER", "KREDI_KARTI"):
                h = FinansHesabi(hesap_adi=f"{ad} {alt}", hesap_turu="BANKA", alt_hesap_turu=alt,
                                 acilis_bakiyesi=Decimal("0"), banka_karti_id=kart.id, aktif=True)
                s.add(h)
                s.flush()
                sonuc[alt] = int(h.id)
            return sonuc

    def _banka(self, ad="Ziraat Mevduat", alt="MEVDUAT") -> int:
        from database.models.finans import FinansHesabi

        with get_session() as s:
            h = s.scalar(select(FinansHesabi).where(FinansHesabi.hesap_adi == ad))
            if h is None:
                h = FinansHesabi(hesap_adi=ad, hesap_turu="BANKA", alt_hesap_turu=alt,
                                 acilis_bakiyesi=Decimal("50000"), aktif=True)
                s.add(h)
                s.flush()
            return int(h.id)

    def _durum_kaydi(self, evrak, kaynak_id):
        from database.models.genel_muhasebe import MuhasebeBelgeDurumu

        with get_session() as s:
            return s.scalar(select(MuhasebeBelgeDurumu).where(
                MuhasebeBelgeDurumu.evrak_turu == evrak, MuhasebeBelgeDurumu.kaynak_id == int(kaynak_id)))

    def _fark(self, once: dict) -> dict:
        sonra = self._tutarli()
        return {k: sonra.get(k, Decimal("0")) - once.get(k, Decimal("0"))
                for k in set(sonra) | set(once) if sonra.get(k, Decimal("0")) != once.get(k, Decimal("0"))}

    @staticmethod
    def _finans_ayar(**degerler):
        from database import muhasebe_finans_ayarlari as fa

        return fa.kaydet({k.replace("__", "."): v for k, v in degerler.items()})


# ====================================================================== ayar kaydı
class FinansAyarKaydiTest(_Temel):
    def test_gecersiz_deger_ve_bilinmeyen_anahtar_reddedilir_bos_deger_siler(self):
        from database import muhasebe_finans_ayarlari as fa

        with self.assertRaises(ValueError):
            fa.kaydet({"cek_senet.KAYIT_ALINAN": "belki"})
        with self.assertRaises(ValueError):
            fa.kaydet({"uydurma.anahtar": "evet"})
        sonuc = fa.kaydet({"cek_senet.KAYIT_ALINAN": "evet", fa.KREDI_FIS_ZAMANI: "yalniz_taksit"})
        self.assertEqual(sonuc, {"cek_senet.KAYIT_ALINAN": "evet", fa.KREDI_FIS_ZAMANI: "yalniz_taksit"})
        self.assertEqual(fa.kaydet({"cek_senet.KAYIT_ALINAN": None}), {fa.KREDI_FIS_ZAMANI: "yalniz_taksit"})
        self.assertIsNone(fa.ayar_oku("cek_senet.KAYIT_ALINAN"))

    def test_yetkisiz_kullanici_kaydedemez(self):
        from database import muhasebe_finans_ayarlari as fa
        from database.session_manager import oturum

        oturum.set_user(user_id=2, kullanici_adi="kullanici", ad_soyad="Yetkisiz", role_kod="KULLANICI",
                        role_ad="Kullanıcı", permissions=set())
        with self.assertRaises(Exception):
            fa.kaydet({"cek_senet.KAYIT_ALINAN": "evet"})

    def test_ekran_verisi_yalniz_fise_uygun_adaylari_listeler(self):
        from database import muhasebe_finans_ayarlari as fa

        self._hesap_bagla("pos_valor_alacagi")
        veri = fa.ekran_verisi()
        kodlar = {a["kod"] for a in veri["adaylar"]}
        self.assertIn("108.01.0001", kodlar)
        satirlar = {r["anahtar"]: r for g in veri["gruplar"] for r in g["satirlar"]}
        self.assertEqual(satirlar["pos_valor_alacagi"]["hesap_kodu"], "108.01.0001")
        self.assertIsNone(satirlar["pos_valor_alacagi"]["sorun"])
        self.assertEqual(satirlar["kmh_hesabi"]["sorun"], "hesap bağlı değil")


# ====================================================================== KMH / POS / şirket kartı
class PosKmhKartTest(_Temel):
    def test_kmh_havale_ayar_sonrasi_tek_fis(self):
        from database.finans_service import FinansService
        from database.models.finans import FinansEvrakKimligi

        self._ayar("otomatik")
        kmh = self._banka("Ziraat KMH", "KMH")
        no = FinansService.alinan_havale(kmh, TARIH, Decimal("250"), cari_id=self.musteri_id)
        with get_session() as s:
            kid = int(s.scalar(select(FinansEvrakKimligi.id).where(FinansEvrakKimligi.belge_no == no)))
        d = self._durum_kaydi("banka_havale", kid)
        self.assertEqual(d.durum, BELGE_INCELEME)
        self.assertIn("kmh_hesabi", d.aciklama)
        self.assertIn("Finans İşlem Ayarları", d.aciklama)
        once = self._tutarli()
        self._hesap_bagla("kmh_hesabi")
        sonuc = self._servis().muhasebelestir([d.id])
        self.assertEqual(sonuc["basarili"], 1, sonuc)
        self.assertEqual(self._fark(once), {"300.01.0001": Decimal("250"), "120.01.0001": Decimal("-250")})
        self._servis().muhasebelestir([d.id])
        self.assertEqual(self._fark(once), {"300.01.0001": Decimal("250"), "120.01.0001": Decimal("-250")},
                         "ikinci kez fiş oluşmaz")

    def test_pos_tahsilat_eksik_ayar_inceleme_sonra_tek_fis_guncelleme_ters_kayit_valor(self):
        from database.finans_service import FinansService
        from database.muhasebe_finans_ayarlari import AYAR_YERI

        self._ayar("otomatik")
        kart = self._banka_karti()
        once = self._tutarli()
        r = FinansService.pos_tahsilat(kart["kart"], TARIH, Decimal("1000"), cari_id=self.musteri_id)
        pid = int(r["kayit_id"])
        d = self._durum_kaydi("pos_tahsilat", pid)
        self.assertEqual(d.durum, BELGE_INCELEME, "eksik hesap: evrak kaydedilir, fiş tahmin edilmez")
        self.assertIn("pos_valor_alacagi", d.aciklama)
        self.assertIn(AYAR_YERI, d.aciklama)
        self.assertEqual(self._fis_sayisi("pos_tahsilat"), 0)
        self.assertEqual(self._fark(once), {})

        self._hesap_bagla("pos_valor_alacagi", "pos_komisyon_gideri")
        sonuc = self._servis().muhasebelestir([d.id])
        self.assertEqual(sonuc["basarili"], 1, sonuc)
        beklenen = {"108.01.0001": Decimal("980"), "780.01.0001": Decimal("20"), "120.01.0001": Decimal("-1000")}
        self.assertEqual(self._fark(once), beklenen)
        self.assertEqual(self._fis_sayisi("pos_tahsilat"), 1)
        self._servis().muhasebelestir([d.id])
        self.assertEqual(self._fis_sayisi("pos_tahsilat"), 1, "ikinci kez fiş oluşmaz")

        # Güncelleme: eski fiş ters kayıtla kapanır, yeni tutarla tek fiş
        r2 = FinansService.pos_tahsilat(kart["kart"], TARIH, Decimal("500"), cari_id=self.musteri_id,
                                        belge_no=r["belge_no"])
        self.assertEqual(self._fark(once), {"108.01.0001": Decimal("490"), "780.01.0001": Decimal("10"),
                                            "120.01.0001": Decimal("-500")})
        self.assertEqual(self._durum("pos_tahsilat", r2["kayit_id"])["durum"], BELGE_MUHASEBELESTIRILDI)

        # Valör aktarımı: KMH hesabı tanımsız → inceleme; bağlanınca KMH / POS valör alacağı
        FinansService.pos_valor_aktar(r2["kayit_id"])
        dv = self._durum_kaydi("pos_valor_aktarimi", r2["kayit_id"])
        self.assertEqual(dv.durum, BELGE_INCELEME)
        self.assertIn("kmh_hesabi", dv.aciklama)
        self._hesap_bagla("kmh_hesabi")
        sonuc = self._servis().muhasebelestir([dv.id])
        self.assertEqual(sonuc["basarili"], 1, sonuc)
        self.assertEqual(self._fark(once), {"300.01.0001": Decimal("490"), "780.01.0001": Decimal("10"),
                                            "120.01.0001": Decimal("-500")})

    def test_pos_sonradan_bekler_sonra_tek_fis(self):
        from database.finans_service import FinansService

        self._ayar("sonradan")
        self._hesap_bagla("pos_valor_alacagi", "pos_komisyon_gideri")
        kart = self._banka_karti()
        r = FinansService.pos_tahsilat(kart["kart"], TARIH, Decimal("1000"), cari_id=self.musteri_id)
        self.assertEqual(self._durum("pos_tahsilat", r["kayit_id"])["durum"], BELGE_BEKLIYOR)
        self.assertEqual(self._fis_sayisi("pos_tahsilat"), 0)
        did = self._durum_id("pos_tahsilat", r["kayit_id"])
        self.assertEqual(self._servis().muhasebelestir([did])["basarili"], 1)
        self._servis().muhasebelestir([did])
        self.assertEqual(self._fis_sayisi("pos_tahsilat"), 1)

    def test_sirket_karti_odeme_tek_fis(self):
        from database.finans_service import FinansService
        from database.models.finans import KrediKartiOdeme, KrediKartiTanimi

        self._ayar("otomatik")
        kart = self._banka_karti()
        with get_session() as s:
            kk = KrediKartiTanimi(banka_karti_id=kart["kart"], kart_adi="Şirket Kartı", kart_limiti=Decimal("50000"),
                                  aktif=True)
            s.add(kk)
            s.flush()
            kk_id = int(kk.id)
        once = self._tutarli()
        r = FinansService.kredi_karti_odeme(kart["kart"], kk_id, self.tedarikci_id, TARIH, Decimal("700"))
        with get_session() as s:
            ko_id = int(s.scalar(select(KrediKartiOdeme.id).where(KrediKartiOdeme.belge_no == r["belge_no"])))
        d = self._durum_kaydi("kart_odeme", ko_id)
        self.assertEqual(d.durum, BELGE_INCELEME)
        self.assertIn("sirket_kart_borcu", d.aciklama)
        self._hesap_bagla("sirket_kart_borcu")
        self.assertEqual(self._servis().muhasebelestir([d.id])["basarili"], 1)
        self._servis().muhasebelestir([d.id])
        self.assertEqual(self._fark(once), {"320.01.0001": Decimal("700"), "309.01.0001": Decimal("-700")})
        self.assertEqual(self._fis_sayisi("kart_odeme"), 1)


# ====================================================================== çek / senet
class CekSenetTest(_Temel):
    def _cek(self, no="C-1", tutar="1000") -> tuple[int, int]:
        from database.cek_senet_service import CekSenetService
        from database.models.cek_senet import CekSenetEvrak, CekSenetHareket

        CekSenetService.olustur({"islem_yonu": "ALINAN", "basit_tur": "CEK", "evrak_no": no,
                                 "duzenleme_tarihi": TARIH, "vade_tarihi": TARIH + timedelta(days=60),
                                 "tutar": tutar, "cari_id": self.musteri_id})
        with get_session() as s:
            eid = int(s.scalar(select(CekSenetEvrak.id).where(CekSenetEvrak.evrak_no == no)))
            hid = int(s.scalar(select(CekSenetHareket.id).where(
                CekSenetHareket.evrak_id == eid, CekSenetHareket.islem_turu == "KAYIT")))
        return eid, hid

    def _hareket(self, eid, tur) -> int:
        from database.models.cek_senet import CekSenetHareket

        with get_session() as s:
            return int(s.scalar(select(CekSenetHareket.id).where(
                CekSenetHareket.evrak_id == eid, CekSenetHareket.islem_turu == tur)))

    def test_asama_secenegi_yoksa_inceleme_hayirsa_muhasebe_disi_evetse_tek_fis_iptal_ters(self):
        from database.cek_senet_service import CekSenetService
        from database.muhasebe_finans_ayarlari import AYAR_YERI

        self._ayar("otomatik")
        once = self._tutarli()
        e1, h1 = self._cek("C-1")
        d1 = self._durum_kaydi("cek_senet", h1)
        self.assertEqual(d1.durum, BELGE_INCELEME)
        self.assertIn("Portföye giriş", d1.aciklama)
        self.assertIn(AYAR_YERI, d1.aciklama)
        self.assertEqual(self._fis_sayisi("cek_senet_hareketi"), 0)

        # Aşama 'fiş üretmesin': muhasebe dışı; sonraki aşama evrakı cari hesaptan alır
        self._finans_ayar(cek_senet__KAYIT_ALINAN="hayir", cek_senet__BANKAYA_TAHSILE="evet")
        self._hesap_bagla("cek_tahsilde")
        e2, h2 = self._cek("C-2", "400")
        self.assertEqual(self._durum("cek_senet", h2)["durum"], BELGE_MUHASEBE_DISI)
        CekSenetService.bankaya_ver(e2, tur="TAHSILE", banka_hesabi_id=self._banka(), tarih=TARIH)
        t2 = self._hareket(e2, "BANKAYA_TAHSILE")
        self.assertEqual(self._durum("cek_senet", t2)["durum"], BELGE_MUHASEBELESTIRILDI)
        self.assertEqual(self._fark(once), {"101.01.0002": Decimal("400"), "120.01.0001": Decimal("-400")})

        # Seçenek 'fiş üretsin' + hesap: bekleyen ilk evrak tek fişle muhasebeleşir
        self._finans_ayar(cek_senet__KAYIT_ALINAN="evet")
        self._hesap_bagla("cek_portfoy")
        self.assertEqual(self._servis().muhasebelestir([d1.id])["basarili"], 1)
        self._servis().muhasebelestir([d1.id])
        self.assertEqual(self._fis_sayisi("cek_senet_hareketi"), 2)
        self.assertEqual(self._fark(once), {"101.01.0001": Decimal("1000"), "101.01.0002": Decimal("400"),
                                            "120.01.0001": Decimal("-1400")})

        # Evrak iptali: kayıt fişi ters kayıtla kapanır
        CekSenetService.iptal(e1, aciklama="Yanlış giriş")
        self.assertEqual(self._durum("cek_senet", h1)["durum"], BELGE_IPTAL)
        self.assertEqual(self._fark(once), {"101.01.0002": Decimal("400"), "120.01.0001": Decimal("-400")})


# ====================================================================== banka kredisi
class BankaKrediTest(_Temel):
    def _kredi(self, kart, ad="İşletme Kredisi") -> int:
        from database.finans_service import FinansService

        ilk = TARIH + timedelta(days=30)
        plan = [{"taksit_no": 1, "vade_tarihi": ilk, "anapara": "6000"},
                {"taksit_no": 2, "vade_tarihi": TARIH + timedelta(days=400), "anapara": "4000"}]
        k = FinansService.banka_kredi_kullandir(kart["kart"], ad, Decimal("10000"), TARIH, ilk, taksit_sayisi=2,
                                                taksit_plani=plan)
        return int(k["id"])

    def test_kullandirim_secenek_yoksa_inceleme_oniki_ay_ayrimi_tek_fis_yalniz_taksitte_muhasebe_disi(self):
        self._ayar("otomatik")
        kart = self._banka_karti()
        once = self._tutarli()
        kid = self._kredi(kart)
        d = self._durum_kaydi("banka_kredi_kullandirim", kid)
        self.assertEqual(d.durum, BELGE_INCELEME)
        self.assertIn("Banka kredisi fiş zamanı", d.aciklama)
        self.assertEqual(self._fark(once), {})

        self._finans_ayar(kredi__fis_zamani="kullandirim_ve_taksit", kredi__vade_ayrimi="oniki_ay")
        self._hesap_bagla("kredi_kisa_vadeli", "kredi_uzun_vadeli")
        self.assertEqual(self._servis().muhasebelestir([d.id])["basarili"], 1)
        self._servis().muhasebelestir([d.id])
        self.assertEqual(self._fark(once), {"102.01.0001": Decimal("10000"), "300.01.0002": Decimal("-6000"),
                                            "400.01.0001": Decimal("-4000")})
        self.assertEqual(self._fis_sayisi("banka_kredi_kullandirim"), 1)

        self._finans_ayar(kredi__fis_zamani="yalniz_taksit")
        kid2 = self._kredi(kart, "İkinci Kredi")
        self.assertEqual(self._durum("banka_kredi_kullandirim", kid2)["durum"], BELGE_MUHASEBE_DISI)
        self.assertEqual(self._fis_sayisi("banka_kredi_kullandirim"), 1)


# ====================================================================== toplu durum + liste ekranları
class _SahteApp:
    def __init__(self, root):
        self.root = root
        self.icerik = tk.Frame(root)
        self.icerik.pack(fill="both", expand=True)

    def __getattr__(self, ad):
        return getattr(self.root, ad)

    def _icerigi_temizle(self):
        for w in self.icerik.winfo_children():
            w.destroy()

    def wait_window(self, *_a, **_k):
        return None


def _agac(widget) -> ttk.Treeview:
    for w in widget.winfo_children():
        if isinstance(w, ttk.Treeview):
            return w
        bulunan = _agac(w)
        if bulunan is not None:
            return bulunan
    return None


def _buton(widget, metin):
    for w in widget.winfo_children():
        try:
            if w.cget("text") == metin:
                return w
        except tk.TclError:
            pass
        bulunan = _buton(w, metin)
        if bulunan is not None:
            return bulunan
    return None


class ListeMuhasebeKolonuTest(_Temel):
    def setUp(self):
        _Temel.setUp(self)
        try:
            self.root = tk.Tk()
        except tk.TclError as hata:
            self.skipTest(f"Tk yok: {hata}")
        self.root.withdraw()
        self._mb = patch.multiple("tkinter.messagebox", showinfo=lambda *a, **k: None,
                                  showerror=self._mesaj_hatasi, showwarning=lambda *a, **k: None)
        self._mb.start()

    def tearDown(self):
        self._mb.stop()
        try:
            self.root.destroy()
        except tk.TclError:
            pass
        _Temel.tearDown(self)

    def _mesaj_hatasi(self, baslik, metin, **_k):
        raise AssertionError(f"Beklenmeyen hata penceresi: {baslik}: {metin}")

    def test_toplu_durum_ve_belge_no_ile_toplu_durum(self):
        from database.finans_service import FinansService
        from muhasebe_durum_ui import toplu_durum, toplu_durum_belge

        self._ayar("otomatik")
        a1, _ = self._alis("U001", "100", "100", "LOT-A")
        self._ayar("sonradan")
        a2, _ = self._alis("U001", "10", "100", "LOT-B")
        self.assertEqual(toplu_durum("alis_faturasi", [a1, a2, 999999]),
                         {a1: BELGE_MUHASEBELESTIRILDI, a2: BELGE_BEKLIYOR})
        self.assertEqual(toplu_durum("alis_faturasi", []), {})
        no = FinansService.alinan_havale(self._banka(), TARIH, Decimal("100"), cari_id=self.musteri_id)
        self.assertEqual(toplu_durum_belge("banka_havale", [no, "YOK-1"]), {no: BELGE_BEKLIYOR})

    def test_satis_fatura_listesi_kolon_dolu_siralama_sonrasi_dogru_fatura_acilir(self):
        from fatura_liste_pencere import DOC_SATIS, FaturaListePencere

        self._ayar("otomatik")
        self._alis("U001", "100", "100", "LOT-A")
        f1 = self._sat("5")
        f2 = self._sat("6")
        self._ayar("sonradan")
        f3 = self._sat("7")
        acilan = []
        kart = tk.Toplevel(self.root)
        kart.withdraw()
        kart.bagli_listeden_fatura_ac = lambda fid, document_type: acilan.append((fid, document_type))
        with patch("fatura_liste_pencere._prefs_yukle", return_value={}):
            p = FaturaListePencere(kart, document_type=DOC_SATIS)
        p.withdraw()
        p.tarih_bas.delete(0, "end")
        p.tarih_bas.insert(0, "01.01.2026")
        p.tarih_bit.delete(0, "end")
        p.tarih_bit.insert(0, "31.12.2026")
        p.yenile()
        durumlar = {iid: p.tablo.set(iid, "muhasebe") for iid in p.tablo.get_children()}
        self.assertEqual(durumlar, {str(f1): BELGE_MUHASEBELESTIRILDI, str(f2): BELGE_MUHASEBELESTIRILDI,
                                    str(f3): BELGE_BEKLIYOR})
        p._sirala("muhasebe")
        self.assertEqual(len(p.tablo.get_children()), 3)
        p.tablo.selection_set(str(f3))
        p.seciliyi_ac()
        self.assertEqual(acilan, [(f3, DOC_SATIS)])
        p._sirala("muhasebe")
        p.tablo.selection_set(str(f1))
        p.seciliyi_ac()
        self.assertEqual(acilan[-1], (f1, DOC_SATIS))
        # Filtre sonrası: yalnız aranan fatura kalır, açılan da odur
        p.no_ara.insert(0, p.tablo.set(str(f2), "no"))
        p._filtre_uygula()
        self.assertEqual(p.tablo.get_children(), (str(f2),))
        self.assertEqual(p.tablo.set(str(f2), "muhasebe"), BELGE_MUHASEBELESTIRILDI)
        p.tablo.selection_set(str(f2))
        p.seciliyi_ac()
        self.assertEqual(acilan[-1], (f2, DOC_SATIS))
        p.destroy()

    def test_alis_fatura_listesi_kolon_dolu(self):
        from fatura_liste_pencere import DOC_ALIS, FaturaListePencere

        self._ayar("otomatik")
        a1, _ = self._alis("U001", "100", "100", "LOT-A")
        kart = tk.Toplevel(self.root)
        kart.withdraw()
        acilan = []
        kart.bagli_listeden_fatura_ac = lambda fid, document_type: acilan.append(fid)
        with patch("fatura_liste_pencere._prefs_yukle", return_value={}):
            p = FaturaListePencere(kart, document_type=DOC_ALIS)
        p.withdraw()
        p.tarih_bas.delete(0, "end")
        p.tarih_bas.insert(0, "01.01.2026")
        p.yenile()
        self.assertEqual(p.tablo.set(str(a1), "muhasebe"), BELGE_MUHASEBELESTIRILDI)
        p.tablo.selection_set(str(a1))
        p.seciliyi_ac()
        self.assertEqual(acilan, [a1])
        p.destroy()

    def test_hizmet_faturasi_listesi_kolon_dolu_secilen_fatura_acilir(self):
        import gelir_gider_ui

        self._ayar("otomatik")
        g1, _ = self._gider("1000")
        self._ayar("sonradan")
        g2, _ = self._gider("300")
        app = _SahteApp(self.root)
        acilan = []

        class _Dialog:
            def __init__(self, _app, hizmet_turu=None, fatura_id=None):
                acilan.append(fatura_id)
                self.result = None

        with patch.object(gelir_gider_ui, "_menu_isaretle", lambda _a: None), \
                patch.object(gelir_gider_ui, "HizmetFaturaDialog", _Dialog):
            gelir_gider_ui.hizmet_faturalari_sayfasi(app, "GIDER")
            tablo = _agac(app.icerik)
            self.assertEqual(tablo.set(str(g1), "muhasebe"), BELGE_MUHASEBELESTIRILDI)
            self.assertEqual(tablo.set(str(g2), "muhasebe"), BELGE_BEKLIYOR)
            tablo.selection_set(str(g2))
            _buton(app.icerik, "Aç / Düzenle").invoke()
        self.assertEqual(acilan, [g2])

    def test_gider_fisi_listesi_kolon_dolu_secilen_fis_acilir(self):
        import belge_onizleme_ui
        import gider_fisi_ui
        from database.finans_service import FinansService

        self._ayar("otomatik")
        fid = self._gider_fisi("250")
        with get_session() as s:
            from database.models.finans import GiderFisi

            belge_no = s.get(GiderFisi, fid).belge_no
        app = _SahteApp(self.root)
        acilan = []
        with patch("gelir_gider_ui._menu_isaretle", lambda _a: None), \
                patch.object(belge_onizleme_ui, "gider_fisi_onizle", lambda _a, no: acilan.append(no)):
            gider_fisi_ui.gider_fisleri_sayfasi(app)
            tablo = _agac(app.icerik)
            self.assertEqual(tablo.set(str(fid), "muhasebe"), BELGE_MUHASEBELESTIRILDI)
            tablo.selection_set(str(fid))
            _buton(app.icerik, "Belgeyi Aç").invoke()
        self.assertEqual(len(FinansService.gider_fisi_listele()), 1)
        self.assertEqual(acilan, [belge_no])

    def test_pos_tahsilat_listesi_kolon_dolu(self):
        import finans_ui
        from database.finans_service import FinansService

        self._ayar("otomatik")
        self._hesap_bagla("pos_valor_alacagi", "pos_komisyon_gideri")
        kart = self._banka_karti()
        r = FinansService.pos_tahsilat(kart["kart"], TARIH, Decimal("1000"), cari_id=self.musteri_id)
        app = _SahteApp(self.root)
        with patch.object(finans_ui, "_finans_menu_isaretle", lambda _a: None):
            finans_ui.kredi_karti_pos_tahsilat_sayfasi_goster(app)
        tablo = _agac(app.icerik)
        self.assertEqual(tablo.set(r["belge_no"], "muhasebe"), BELGE_MUHASEBELESTIRILDI)


if __name__ == "__main__":
    unittest.main()
