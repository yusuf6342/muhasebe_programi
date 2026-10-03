"""Alış faturası: onay, otomatik tedarikçi arama, yeni tedarikçi ve yeni stok kabul testleri."""

from __future__ import annotations

import sys
import tempfile
import tkinter as tk
import unittest
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import importlib
import pkgutil

import database.models

for _m in pkgutil.iter_modules(database.models.__path__):
    importlib.import_module(f"database.models.{_m.name}")

from sqlalchemy import create_engine, event, func, select, text
from sqlalchemy.orm import sessionmaker

from database.database import Base, _aktif_engine_bagla, company_db, get_session
from database.models.alis_faturasi import AlisFaturasi
from database.models.cari import Cari, SatisHareketi
from database.models.donem import Donem
from database.models.firma import Firma
from database.models.stok import Depo, StokHareketi, StokKarti
from database.session_manager import oturum

BUGUN = date.today()


def _pragma(dbapi_connection, _record):
    cur = dbapi_connection.cursor()
    cur.execute("PRAGMA foreign_keys=ON")
    cur.close()


def _pompala(w, n=6):
    for _ in range(n):
        try:
            w.update()
        except tk.TclError:
            return


class _Temel(unittest.TestCase):
    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self.db_path = Path(self._tmpdir.name) / "alis_onay.db"
        eng = create_engine(f"sqlite:///{self.db_path.as_posix()}", connect_args={"check_same_thread": False})
        event.listen(eng, "connect", _pragma)
        Base.metadata.create_all(eng)
        Session = sessionmaker(bind=eng, autoflush=False, autocommit=False, expire_on_commit=False)
        with Session() as s:
            firma = Firma(firma_kodu="AOT", unvan="Alış Onay Test", aktif=True)
            s.add(firma)
            s.flush()
            s.add(Donem(firma_id=firma.id, donem_adi=str(BUGUN.year), baslangic_tarihi=date(BUGUN.year, 1, 1),
                        bitis_tarihi=date(BUGUN.year, 12, 31), aktif=True, kapali=False, varsayilan=True))
            s.add(Depo(ad="ANA DEPO", aktif=True))
            s.add(StokKarti(stok_kodu="U001", stok_adi="Vida", birim="Adet", kdv_orani=Decimal("20"),
                            aktif=True, is_deleted=False))
            s.add(Cari(cari_kodu="T001", unvan="Çelik Ticaret", cari_turu="Tedarikçi", aktif=True))
            s.add(Cari(cari_kodu="T002", unvan="Demir A.Ş.", cari_turu="Tedarikçi", aktif=True, il="İzmir"))
            s.add(Cari(cari_kodu="T003", unvan="Demir A.Ş.", cari_turu="Tedarikçi", aktif=True, il="Ankara"))
            s.add(Cari(cari_kodu="M001", unvan="Çelik Müşteri", cari_turu="Müşteri", aktif=True))
            s.commit()
        _aktif_engine_bagla(eng)
        company_db._engine = eng
        company_db._session_factory = Session
        company_db._company_id = 97
        company_db._db_path = self.db_path
        oturum.set_user(user_id=1, kullanici_adi="k1", ad_soyad="Kullanıcı 1", role_kod="YONETICI",
                        role_ad="YONETICI", permissions=set())
        oturum.set_company(company_id=97, firma_kodu="AOT", firma_unvan="Alış Onay Test", firma_uid="aot",
                           db_path=str(self.db_path))
        with get_session() as s:
            d = s.scalar(select(Donem).limit(1))
            oturum.set_period(d.id, d.donem_adi)
            self.ids = {c.cari_kodu: c.id for c in s.scalars(select(Cari)).all()}
        self._p = patch("database.muhasebe_entegrasyon.muhasebe_hook", lambda *_a, **_k: None)
        self._p.start()
        self._eng = eng

    def tearDown(self):
        self._p.stop()
        try:
            company_db.close()
        except Exception:
            pass
        if company_db._engine is not None:
            company_db._engine.dispose()
        company_db._engine = None
        company_db._session_factory = None
        oturum.clear()
        self._tmpdir.cleanup()

    def _veriler(self, cari_kodu="T001", **ek):
        v = {"fatura_tarihi": BUGUN, "vade_tarihi": BUGUN + timedelta(days=30),
             "cari_id": self.ids[cari_kodu], "depo": "ANA DEPO"}
        v.update(ek)
        return v

    @staticmethod
    def _satir(miktar="10", fiyat="5"):
        return {"urun_kodu": "U001", "urun_adi": "Vida", "miktar": miktar, "birim": "Adet",
                "birim_fiyat": fiyat, "kdv_orani": "20"}

    def _sayimlar(self, fatura_no):
        with get_session() as s:
            stok = s.scalar(select(func.count()).select_from(StokHareketi).where(StokHareketi.belge_no == fatura_no))
            cari = list(s.scalars(select(SatisHareketi).where(SatisHareketi.belge_no == fatura_no)).all())
        return stok, cari


class AlisOnayServisTest(_Temel):
    def test_onay_hareket_uretmez_tekrar_kaydetme_cogaltmaz(self):
        from database.alis_faturasi_service import AlisFaturasiService

        f = AlisFaturasiService.kaydet(self._veriler(), [self._satir()])
        stok1, cari1 = self._sayimlar(f.fatura_no)
        self.assertEqual(len(cari1), 1)
        self.assertEqual(cari1[0].satis_tutari, Decimal("60.00"))
        # Tekrar kaydetme: hareketler yeniden kurulur, çoğalmaz
        f = AlisFaturasiService.kaydet(self._veriler(row_version=f.row_version), [self._satir()], f.id)
        f = AlisFaturasiService.kaydet(self._veriler(row_version=f.row_version), [self._satir()], f.id)
        stok2, cari2 = self._sayimlar(f.fatura_no)
        self.assertEqual((stok2, len(cari2)), (stok1, 1))
        f = AlisFaturasiService.onayla(f.id, row_version=f.row_version)
        self.assertTrue(f.onaylandi)
        self.assertIsNotNone(f.onay_tarihi)
        stok3, cari3 = self._sayimlar(f.fatura_no)
        self.assertEqual((stok3, len(cari3)), (stok1, 1))
        self.assertEqual(cari3[0].satis_tutari, f.tl_genel_toplam)
        with self.assertRaisesRegex(ValueError, "zaten onaylı"):
            AlisFaturasiService.onayla(f.id)
        with self.assertRaisesRegex(ValueError, "Onaylı alış faturası değiştirilemez"):
            AlisFaturasiService.kaydet(self._veriler(row_version=f.row_version), [self._satir("3")], f.id)
        self.assertEqual(self._sayimlar(f.fatura_no)[0], stok1)
        f = AlisFaturasiService.onay_kaldir(f.id)
        self.assertFalse(f.onaylandi)
        f = AlisFaturasiService.kaydet(self._veriler(row_version=f.row_version), [self._satir("3")], f.id)
        stok4, cari4 = self._sayimlar(f.fatura_no)
        self.assertEqual((stok4, len(cari4)), (stok1, 1))
        self.assertEqual(cari4[0].satis_tutari, Decimal("18.00"))

    def test_onay_kontrolleri(self):
        from database.alis_faturasi_service import onay_hatalari

        temel = dict(fatura_tarihi=BUGUN, vade_tarihi=BUGUN, depo="ANA DEPO")
        with get_session() as s:
            ted = s.get(Cari, self.ids["T001"])
            mus = s.get(Cari, self.ids["M001"])
        self.assertEqual(onay_hatalari(cari=ted, satirlar=[self._satir()], **temel), [])
        self.assertIn("Tedarikçi seçilmemiş.", onay_hatalari(cari=None, satirlar=[self._satir()], **temel))
        self.assertTrue(any("tedarikçi kartı değil" in h for h in onay_hatalari(cari=mus, satirlar=[self._satir()], **temel)))
        h = onay_hatalari(cari=ted, satirlar=[self._satir("0", "0")], **temel)
        self.assertTrue(any("miktar" in x for x in h) and any("birim fiyat" in x for x in h))
        h = onay_hatalari(cari=ted, satirlar=[self._satir()], para_birimi="USD", kur="0", **temel)
        self.assertTrue(any("kur" in x for x in h))
        self.assertIn("Faturada ürün satırı yok.", onay_hatalari(cari=ted, satirlar=[], **temel))

    def test_eski_veritabani_gecisi(self):
        from database import database as db

        with self._eng.begin() as c:
            c.execute(text("INSERT INTO alis_faturalari (fatura_no, fatura_tarihi, vade_gunu, vade_tarihi, cari_id, durum, depo, odeme_tutari, para_birimi, kur, kur_turu, kur_kaynagi, kur_sabitlendi, doviz_ara_toplam, tl_matrah, tl_kdv, tl_genel_toplam, tl_brut_toplam, genel_islem_orani, genel_islem_tutari, rounding_applied, rounding_version, invoice_rounding_adjustment, row_version, olusturma_tarihi, onaylandi) VALUES ('ESKI1', :t, 0, :t, :c, 'AÇIK', 'ANA DEPO', 0, 'TRY', 1, 'forex_selling', 'TCMB', 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 1, :t, 0)"),
                      {"t": BUGUN, "c": self.ids["T001"]})
            c.execute(text('ALTER TABLE "alis_faturalari" DROP COLUMN "onay_tarihi"'))
            c.execute(text('ALTER TABLE "alis_faturalari" DROP COLUMN "onaylandi"'))
        db.cari_kart_schemasini_guncelle()
        with self._eng.connect() as c:
            sutunlar = {r[1] for r in c.execute(text('PRAGMA table_info("alis_faturalari")'))}
            self.assertTrue({"onaylandi", "onay_tarihi"} <= sutunlar)
            self.assertEqual(c.execute(text("SELECT onaylandi FROM alis_faturalari WHERE fatura_no='ESKI1'")).scalar(), 0)


class AlisEkranTest(_Temel):
    def setUp(self):
        super().setUp()
        self.root = tk.Tk()
        self.root.withdraw()
        self._mb = patch("alis_ui.messagebox")
        self.mb = self._mb.start()

    def tearDown(self):
        self._mb.stop()
        try:
            self.root.destroy()
        except tk.TclError:
            pass
        super().tearDown()

    def _ac(self, fatura=None):
        from alis_ui import AlisFaturasiDialog

        d = AlisFaturasiDialog(self.root, fatura=fatura)
        try:
            d.attributes("-alpha", 0.0)
            d.geometry("1366x705+20+20")
        except tk.TclError:
            pass
        _pompala(d)
        return d

    def _yaz(self, d, metin):
        d._tedarikci_metin.set(metin)
        d._tedarikci_arama._tus(SimpleNamespace(keysym="a"))
        d._tedarikci_arama._iptal()
        d._tedarikci_arama.ara(metin, senkron=True)
        _pompala(d, 2)

    def _satir_ekle(self, d, miktar="2", fiyat="7.5"):
        idx = d._alis_fatura_urun_ekle(("U001", "Vida", "Adet", "0", "0", "Stok Kartı", "20"), None)
        d.alis_fatura_hucre_uygula(idx, "miktar", miktar)
        d.alis_fatura_hucre_uygula(idx, "fiyat", fiyat)
        return idx

    def test_otomatik_arama_turkce_klavye_fare_ve_ayni_isim(self):
        d = self._ac()
        try:
            a = d._tedarikci_arama
            for sorgu in ("çeli", "ÇELİK", "celik tic", "tic çel"):
                self._yaz(d, sorgu)
                kodlar = [c.cari_kodu for c in a.sonuclar]
                self.assertEqual(kodlar, ["T001"], sorgu)  # müşteri karışmaz
            self.assertTrue(a.acik_mi())
            a._asagi()
            self.assertEqual(a._enter(), "break")
            self.assertEqual(d._secili_tedarikci().id, self.ids["T001"])
            self.assertEqual(d.tedarikci_ad.get(), "Çelik Ticaret")
            self.assertEqual(d._tedarikci_kod_lbl.cget("text"), "T001")
            self.assertFalse(a.acik_mi())
            # Aynı isimli kartlar: ek bilgiyle ayrışır, fareyle seçilen kimlik bağlanır
            self._yaz(d, "demir")
            self.assertEqual(sorted(c.cari_kodu for c in a.sonuclar), ["T002", "T003"])
            ekler = [a.tree.item(i, "values")[2] for i in a.tree.get_children()]
            self.assertTrue(any("Ankara" in e for e in ekler) and any("İzmir" in e for e in ekler))
            hedef = next(i for i, c in enumerate(a.sonuclar) if c.cari_kodu == "T003")
            a.tree.update_idletasks()
            bbox = a.tree.bbox(str(hedef))
            y = bbox[1] + 2 if bbox else 0
            a._tik(SimpleNamespace(y=y) if bbox else None) if bbox else a.sec(hedef)
            self.assertEqual(d._secili_tedarikci().id, self.ids["T003"])
            # Ad değişirse eski kimlik bağlı kalmaz
            d._tedarikci_metin.set("Demir A.Ş. X")
            a._tus(SimpleNamespace(keysym="X"))
            self.assertIsNone(d._secili_tedarikci())
            self.assertIn("geçerli kart", d._tedarikci_kod_lbl.cget("text"))
            # Sonuç yok
            self._yaz(d, "zzqq")
            self.assertEqual(a.durum.cget("text"), "Tedarikçi bulunamadı.")
            self.assertIsNotNone(a.yeni_btn)
            self.assertEqual(a._esc(), "break")
            self.assertFalse(a.acik_mi())
            # Geç gelen eski sonuç yeni listeyi değiştirmez
            self._yaz(d, "demir")
            eski_seq = a._seq
            d._tedarikci_metin.set("çelik")
            a.ara("çelik", senkron=True)
            a.sonuc_uygula(eski_seq, "demir", [])
            self.assertEqual([c.cari_kodu for c in a.sonuclar], ["T001"])
        finally:
            d.destroy()

    def test_f10_ve_ara_listeyi_acar(self):
        d = self._ac()
        acilanlar = []

        class _Sahte(tk.Toplevel):
            def __init__(s, parent, musteriler=None, **kw):
                super().__init__(parent)
                acilanlar.append((len(musteriler or []), kw.get("ara")))
                s.result = next(c for c in musteriler if c.cari_kodu == "T002")
                s.after(10, s.destroy)

        try:
            with patch("app.MusteriSecimDialog", _Sahte):
                d._tedarikci_metin.set("dem")
                d.tedarikci_ara_btn.invoke()
                self.assertEqual(d._secili_tedarikci().id, self.ids["T002"])
                self.assertTrue(d.tedarikci_ad.bind("<F10>"))
                d.tedarikci_ad.event_generate("<Button-3>", x=5, y=5)
                _pompala(d)
            self.assertEqual(len(acilanlar), 2)
            self.assertEqual(acilanlar[0][1], "dem")
            self.assertTrue(all(n >= 3 for n, _ in acilanlar))
        finally:
            d.destroy()

    def test_yeni_tedarikci_kart_formu_ile_secilir_iptal_guvenli(self):
        import cari_kart_ui

        d = self._ac()
        try:
            self._yaz(d, "çelik")
            d._tedarikci_arama.sec(0)
            self._satir_ekle(d)
            d.girdiler["tedarikci_fatura_no"].insert(0, "TF-9")
            # İptal: kart kapatılır, seçim ve satırlar değişmez
            def _iptal():
                w = d._yeni_tedarikci_pencere
                w._kirli = False
                w.destroy()

            d.after(300, _iptal)
            with patch.object(cari_kart_ui, "messagebox"):
                self.assertIsNone(d.yeni_tedarikci_ekle())
            self.assertEqual(d._secili_tedarikci().id, self.ids["T001"])
            self.assertEqual(len(d.satirlar), 1)
            # Kaydet: mevcut tedarikçi kartı formu, yeni kart otomatik seçilir
            d._tedarikci_metin.set("Yepyeni Tedarik Ltd")
            d._tedarikci_arama._tus(SimpleNamespace(keysym="d"))

            def _kaydet():
                w = d._yeni_tedarikci_pencere
                self.assertIsInstance(w, cari_kart_ui.CariDialog)
                self.assertEqual(w.cari_turu, "Tedarikçi")
                self.assertEqual(w.degerler["unvan"].get(), "Yepyeni Tedarik Ltd")
                w.kaydet(kapat=True)

            d.after(300, _kaydet)
            with patch.object(cari_kart_ui, "messagebox"):
                yeni = d.yeni_tedarikci_ekle()
            self.assertIsNotNone(yeni)
            self.assertEqual(d._secili_tedarikci().id, yeni.id)
            self.assertEqual(d.tedarikci_ad.get(), "Yepyeni Tedarik Ltd")
            self.assertEqual(d._tedarikci_kod_lbl.cget("text"), yeni.cari_kodu)
            self.assertEqual(len(d.satirlar), 1)
            self.assertEqual(d.girdiler["tedarikci_fatura_no"].get(), "TF-9")
            with get_session() as s:
                self.assertEqual(s.get(Cari, yeni.id).cari_turu, "Tedarikçi")
        finally:
            d.destroy()

    def test_yeni_stok_olustur_satira_eklenir_iptal_ve_mukerrer(self):
        import hizli_stok_karti_ui

        d = self._ac()
        try:
            self.assertEqual(d.yeni_stok_btn.cget("text"), "Yeni Stok Oluştur (F6)")
            # İptal: kart da satır da oluşmaz
            d.after(300, lambda: next(w for w in d.winfo_children()
                                      if isinstance(w, hizli_stok_karti_ui.HizliStokKartiDialog)).destroy())
            d.yeni_stok_olustur()
            self.assertEqual(d.satirlar, [])
            with get_session() as s:
                self.assertEqual(s.scalar(select(func.count()).select_from(StokKarti)), 1)
            # Ürün adı aramadan ön doldurulur; Kaydet sonrası satıra eklenir
            d._satir_ici_giris.ac("ad", "Yeni Somun")

            def _doldur_kaydet():
                w = next(w for w in d.winfo_children() if isinstance(w, hizli_stok_karti_ui.HizliStokKartiDialog))
                self.assertEqual(w.ad.get(), "Yeni Somun")
                w.kod.delete(0, "end")
                w.kod.insert(0, "S-NEW")
                w.birim.set("Kilogram")
                w.kdv.delete(0, "end")
                w.kdv.insert(0, "10")
                w.grup.set("GENEL")
                w.barkod.delete(0, "end")
                w.barkod.insert(0, "8690000000017")
                w.alis.insert(0, "12,5")
                w._kaydet(faturaya=False)

            d.after(300, _doldur_kaydet)
            with patch.object(hizli_stok_karti_ui, "messagebox"):
                self.assertTrue(d.bind("<F6>"))
                d.yeni_stok_olustur()
                _pompala(d)
            self.assertEqual(len(d.satirlar), 1)
            s0 = d.satirlar[0]
            self.assertEqual((s0["urun_kodu"], s0["birim"]), ("S-NEW", "Kilogram"))
            self.assertEqual(Decimal(str(s0["kdv_orani"])), Decimal("10"))
            self.assertEqual(Decimal(str(s0["birim_fiyat"])), Decimal("12.5"))
            # Miktar ve fiyat düzenlenir, toplam güncellenir
            d.alis_fatura_hucre_uygula(0, "miktar", "4")
            d.alis_fatura_hucre_uygula(0, "fiyat", "10")
            self.assertEqual(d._alis_net_toplam, Decimal("44.00"))
            # Mükerrer barkod: yeni kart açılmaz, satır eklenmez
            d._satir_ici_giris.ac("barkod", "8690000000017")

            def _mukerrer():
                w = next(w for w in d.winfo_children() if isinstance(w, hizli_stok_karti_ui.HizliStokKartiDialog))
                w.kod.delete(0, "end")
                w.kod.insert(0, "S-DUP")
                w.ad.delete(0, "end")
                w.ad.insert(0, "Başka Ürün")
                w.grup.set("GENEL")
                with patch.object(w, "_mukerrer_dialog", return_value="vazgec"):
                    w._kaydet(faturaya=False)
                w.destroy()

            d.after(300, _mukerrer)
            with patch.object(hizli_stok_karti_ui, "messagebox"):
                d.yeni_stok_olustur()
            self.assertEqual(len(d.satirlar), 1)
            with get_session() as s:
                self.assertIsNone(s.scalar(select(StokKarti).where(StokKarti.stok_kodu == "S-DUP")))
        finally:
            d.destroy()

    def test_onay_akisi_kilit_ve_yeniden_acma(self):
        from database.alis_faturasi_service import AlisFaturasiService

        d = self._ac()
        try:
            self.assertEqual(d.onayla_btn.cget("text"), "Onayla")
            # Eksik tedarikçi + hatalı satır: anlaşılır uyarı, kayıt yok
            self._satir_ekle(d, miktar="1", fiyat="0")
            self.assertFalse(d.onayla())
            uyari = self.mb.showwarning.call_args[0][1]
            self.assertIn("Tedarikçi seçilmemiş", uyari)
            self.assertIn("birim fiyat", uyari)
            self.assertIsNone(d.fatura)
            # Kayıt başarısızsa onaylı görünmez
            self._yaz(d, "çelik")
            d._tedarikci_arama.sec(0)
            d.alis_fatura_hucre_uygula(0, "fiyat", "7.5")
            with patch.object(AlisFaturasiService, "kaydet", side_effect=ValueError("disk dolu")):
                self.assertFalse(d.onayla())
            self.assertIsNone(d.fatura)
            # Geçerli fatura: kaydet + onayla tek adımda
            self.assertTrue(d.onayla())
            self.assertTrue(d.fatura.onaylandi)
            self.assertEqual(d._alis_toolbar["rozet"].cget("text"), "ONAYLI")
            no = d.fatura.fatura_no
            stok1, cari1 = self._sayimlar(no)
            self.assertFalse(d.onayla())  # tekrar tık: yeni hareket yok
            self.assertEqual(self._sayimlar(no)[0], stok1)
            self.assertEqual(len(self._sayimlar(no)[1]), 1)
            fid = d.fatura.id
        finally:
            d.destroy()
        # Yeniden aç: onay ve kilit korunur
        d = self._ac(AlisFaturasiService.getir(fid))
        try:
            self.assertTrue(d._alis_kilitli())
            self.assertEqual(d._alis_toolbar["rozet"].cget("text"), "ONAYLI")
            self.assertEqual(str(d.kaydet_btn.cget("state")), "disabled")
            self.assertEqual(str(d.onayla_btn.cget("state")), "disabled")
            self.assertTrue(d.onay_kaldir_btn.winfo_manager())
            self.assertEqual(str(d.tedarikci_ad.cget("state")), "disabled")
            self.assertEqual(str(d.yeni_stok_btn.cget("state")), "disabled")
            from satir_ici_urun_giris import YENI_SATIR_IID

            self.assertFalse(d.satir_tablosu.exists(YENI_SATIR_IID))
            with self.assertRaises(ValueError):
                d.alis_fatura_hucre_uygula(0, "miktar", "9")
            with self.assertRaises(ValueError):
                d._alis_fatura_urun_ekle(("U001", "Vida", "Adet"), None)
            self.assertFalse(d.kaydet())
            d.satir_tablosu.selection_set("0")
            d.satir_sil()
            self.assertEqual(len(d.satirlar), 1)
            self.assertTrue(d._onay_bilgi_lbl.cget("text").startswith("ONAYLI"))
            # Onay kaldırma: düzenleme yeniden açılır
            self.mb.askyesno.return_value = True
            self.assertTrue(d.onay_kaldir())
            self.assertFalse(d._alis_kilitli())
            self.assertEqual(str(d.tedarikci_ad.cget("state")), "normal")
            d.alis_fatura_hucre_uygula(0, "miktar", "3")
            self.assertTrue(d.kaydet())
            stok2, cari2 = self._sayimlar(no)
            self.assertEqual((stok2, len(cari2)), (stok1, 1))
            self.assertEqual(cari2[0].satis_tutari, Decimal("27.00"))
        finally:
            d.destroy()


if __name__ == "__main__":
    unittest.main()
