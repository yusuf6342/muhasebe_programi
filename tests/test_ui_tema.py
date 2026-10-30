"""Tema tercih, uygulama ve kontrast — kabul senaryoları T01–T11, T18 (otomatik)."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import ui_tema


def _hex_rgb(h: str) -> tuple[float, float, float]:
    h = h.lstrip("#")
    return tuple(int(h[i : i + 2], 16) / 255.0 for i in (0, 2, 4))


def _rel_luminance(rgb: tuple[float, float, float]) -> float:
    def f(c: float) -> float:
        return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4

    r, g, b = (f(x) for x in rgb)
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def kontrast(hex1: str, hex2: str) -> float:
    l1, l2 = _rel_luminance(_hex_rgb(hex1)), _rel_luminance(_hex_rgb(hex2))
    a, b = max(l1, l2), min(l1, l2)
    return (a + 0.05) / (b + 0.05)


class TemaTest(unittest.TestCase):
    def test_T02_etkin_listede_gece_yok(self):
        ids = {t["id"] for t in ui_tema.etkin_temalar()}
        self.assertEqual(ids, {"klasik", "ferah", "modern", "sade"})
        self.assertNotIn("gece", ids)
        adlar = {t["ad"] for t in ui_tema.etkin_temalar()}
        self.assertEqual(adlar, {"Klasik", "Ferah", "Modern", "Sade"})

    def test_T01_T10_bilinmeyen_klasike_dus(self):
        t = ui_tema.tema_getir("yok_boyle_tema")
        self.assertEqual(t["id"], "klasik")
        self.assertEqual(ui_tema.tema_getir("gece")["id"], "klasik")  # aşama 2 seçilmez

    def test_T07_T08_tercih_kullaniciya_ozel(self):
        with tempfile.TemporaryDirectory() as tmp:
            with patch("ui_tema._tercih_yolu", return_value=Path(tmp) / "tema_u1.json"):
                ui_tema.tercih_yaz(1, "ferah")
                self.assertEqual(ui_tema.tercih_oku(1), "ferah")
            with patch("ui_tema._tercih_yolu", return_value=Path(tmp) / "tema_u2.json"):
                self.assertEqual(ui_tema.tercih_oku(2), "klasik")
                ui_tema.tercih_yaz(2, "modern")
                self.assertEqual(ui_tema.tercih_oku(2), "modern")
            with patch("ui_tema._tercih_yolu", return_value=Path(tmp) / "tema_u1.json"):
                self.assertEqual(ui_tema.tercih_oku(1), "ferah")

    def test_T10_bozuk_tercih_klasik(self):
        with tempfile.TemporaryDirectory() as tmp:
            yol = Path(tmp) / "tema_u9.json"
            yol.write_text("{", encoding="utf-8")
            with patch("ui_tema._tercih_yolu", return_value=yol):
                self.assertEqual(ui_tema.tercih_oku(9), "klasik")

    def test_T04_uygula_aktif_ve_gece_engeli(self):
        eski = ui_tema.aktif_tema_id()
        try:
            self.assertEqual(ui_tema.uygula("modern"), "modern")
            self.assertEqual(ui_tema.aktif_tema_id(), "modern")
            self.assertEqual(ui_tema.uygula("gece"), "klasik")
        finally:
            ui_tema.uygula(eski)

    def test_T03_onizleme_uygula_ayri_degil_tercih(self):
        """Önizleme kodu tercih yazmaz; yalnızca Kaydet tercih_yaz çağırır (tema_ayar_ui)."""
        eski = ui_tema.aktif_tema_id()
        with tempfile.TemporaryDirectory() as tmp:
            yol = Path(tmp) / "tema_u5.json"
            with patch("ui_tema._tercih_yolu", return_value=yol):
                # Önizleme simülasyonu: uygula çağrılmadan tercih yok
                self.assertFalse(yol.is_file())
                self.assertEqual(ui_tema.tercih_oku(5), "klasik")
                ui_tema.tercih_yaz(5, "sade")
                self.assertTrue(yol.is_file())
                veri = json.loads(yol.read_text(encoding="utf-8"))
                self.assertEqual(veri.get("tema_id"), "sade")
                self.assertIn("surum", veri)
        ui_tema.uygula(eski)

    def test_T18_kontrast_ana_metin_45(self):
        """Normal metin / açık zemin ≥ 4.5:1 hedef (WCAG referans)."""
        for tid in ("klasik", "ferah", "modern", "sade"):
            r = ui_tema.tema_getir(tid)["renkler"]
            oran = kontrast(r["METIN"], r["ACIK_BG"])
            self.assertGreaterEqual(
                oran,
                4.5,
                msg=f"{tid} METIN/ACIK_BG kontrast {oran:.2f} < 4.5",
            )
            # Ana düğme: açık yazı / lacivert
            oran2 = kontrast(r.get("METIN_ACIK", "#FFFFFF"), r["LACIVERT"])
            self.assertGreaterEqual(
                oran2,
                3.0,
                msg=f"{tid} METIN_ACIK/LACIVERT {oran2:.2f} < 3",
            )

    def test_T18_uyari_secili_vurgu_kontrast(self):
        """T18: uyarı metni ve vurgu (SARI) komşu zeminle ayırt edilebilmeli (≥3:1)."""
        for tid in ("klasik", "ferah", "modern", "sade"):
            r = ui_tema.tema_getir(tid)["renkler"]
            self.assertGreaterEqual(
                kontrast(r.get("UYARI", "#D64545"), r["ACIK_BG"]),
                3.0,
                msg=f"{tid} UYARI/ACIK_BG",
            )
            # Vurgu düğmesi: koyu yazı / sarı zemin
            self.assertGreaterEqual(
                kontrast(r.get("KOYU_LACIVERT", r["METIN"]), r["SARI"]),
                3.0,
                msg=f"{tid} KOYU_LACIVERT/SARI",
            )

    def test_T15_tekrar_uygula_tercih_dosyasi_okumaz(self):
        """Tema değişimi tercih dosyasına dokunmaz; yalnızca bellek + modül renkleri."""
        eski = ui_tema.aktif_tema_id()
        with tempfile.TemporaryDirectory() as tmp:
            yol = Path(tmp) / "tema_u77.json"
            with patch("ui_tema._tercih_yolu", return_value=yol):
                ui_tema.tercih_yaz(77, "klasik")
                mtime1 = yol.stat().st_mtime_ns
                ui_tema.uygula("ferah")
                ui_tema.uygula("modern")
                ui_tema.uygula("ferah")
                mtime2 = yol.stat().st_mtime_ns
                self.assertEqual(mtime1, mtime2)
                self.assertEqual(ui_tema.tercih_oku(77), "klasik")
        ui_tema.uygula(eski)

    def test_T23_baski_modulleri_tema_hedefi_degil(self):
        """PDF/baskı modülleri _HEDEF_MODULLER içinde olmamalı."""
        yasak = {"invoice_print", "makbuz_cikti", "teklif_print", "pdf_service"}
        for ad in ui_tema._HEDEF_MODULLER:
            self.assertFalse(any(ad.startswith(y) or y in ad for y in yasak))

    def test_T24_uygula_is_verisi_degistirmez(self):
        """Tema yalnızca renk rollerini yazar; iş sabitlerini değiştirmez."""
        import fatura_tema as ft

        once = getattr(ft, "LACIVERT", None)
        eski = ui_tema.aktif_tema_id()
        try:
            ui_tema.uygula("sade")
            self.assertIsNotNone(getattr(ft, "LACIVERT", None))
            # Uygulama sonrası da aynı türde str HEX
            self.assertTrue(str(ft.LACIVERT).startswith("#"))
        finally:
            ui_tema.uygula(eski)
            if once:
                self.assertTrue(str(ft.LACIVERT).startswith("#"))

    def test_T12_tema_yenile_veri_yuklemez(self):
        """T12: tema_yenile yalnızca menü renkleri; yenile/kart_ozet çağırmaz."""
        import inspect
        import ana_panel_ui as apu

        src = inspect.getsource(apu.AnaPanelKabuk.tema_yenile)
        for yasak in ("kart_ozet_metrikleri", "plan_getir", "stok_getir", "get_session"):
            self.assertNotIn(yasak, src)
        self.assertIn("_yenile_renk", src)
        self.assertNotIn("self.yenile(", src)

    def test_T13_stok_kart_ilk_odak_stok_adi(self):
        """T13: stok kartı açılış odağı Stok Adı yardımcısı."""
        import inspect
        import stok_ui

        self.assertTrue(hasattr(stok_ui.StokKartiDialog, "_stok_adi_odak_ver"))
        src = inspect.getsource(stok_ui.StokKartiDialog.__init__)
        self.assertIn("_stok_adi_odak_ver", src)

    def test_T16_uyari_basari_rolleri_korunur(self):
        """T16: maliyet altı / başarı anlam renkleri temalar arası sabit kalır."""
        klasik = ui_tema.tema_getir("klasik")["renkler"]
        for tid in ("ferah", "modern", "sade"):
            r = ui_tema.tema_getir(tid)["renkler"]
            self.assertEqual(r.get("UYARI"), klasik.get("UYARI"))
            self.assertEqual(r.get("BASARI"), klasik.get("BASARI"))

    def test_T17_secili_uyari_ayirt_edilebilir(self):
        """T17: seçim vurgusu (SARI) uyarı kırmızısından ayırt edilir."""
        for tid in ("klasik", "ferah", "modern", "sade"):
            r = ui_tema.tema_getir(tid)["renkler"]
            self.assertNotEqual(
                (r.get("SARI") or "").upper(),
                (r.get("UYARI") or "").upper(),
                msg=f"{tid}: seçim ve uyarı aynı renk",
            )
            self.assertGreaterEqual(
                kontrast(r.get("UYARI", "#D64545"), r.get("SARI", "#F4C542")),
                1.5,
                msg=f"{tid}: UYARI/SARI ayırt edilemiyor",
            )

    def test_T19_tema_dialog_klavye_baglari(self):
        """T19: tema diyaloğunda Enter/Esc bağları tanımlı."""
        import inspect
        import tema_ayar_ui

        src = inspect.getsource(tema_ayar_ui.tema_ayarlari_ac)
        self.assertIn("<Return>", src)
        self.assertIn("<Escape>", src)

    def test_T20_tema_dialog_minsize(self):
        """T20: diyalog 1366×768 altında erişilebilir minsize taşır."""
        import inspect
        import tema_ayar_ui

        src = inspect.getsource(tema_ayar_ui.tema_ayarlari_ac)
        self.assertIn("minsize", src)
        self.assertIn("520", src)

    def test_T22_yardimci_pencereler_stil_bagli(self):
        """T22: yardımcı pencereler ttk stil / tema rollerine bağlı (sabit #fff yığın yok)."""
        import inspect

        import ui_tema

        for zorunlu in ("stok_kart_tema", "cari_kart_tema", "fatura_tema"):
            self.assertIn(zorunlu, ui_tema._HEDEF_MODULLER)
        eski = ui_tema.aktif_tema_id()
        try:
            ui_tema.uygula("ferah")
            stil = ui_tema.aktif_palet()
            self.assertIn("METIN", stil)
            self.assertIn("ACIK_BG", stil)
            self.assertGreaterEqual(kontrast(stil["METIN"], stil["ACIK_BG"]), 4.5)
        finally:
            ui_tema.uygula(eski)
        import ui_pencere

        src = inspect.getsource(ui_pencere)
        self.assertTrue("tk_buton" in src or "Baslik.TLabel" in src or "ttk" in src)

    def test_T21_hedef_modul_envanteri(self):
        """T21: ana ekran grupları hedef listesinde; baskı yok."""
        hedefler = set(ui_tema._HEDEF_MODULLER)
        for zorunlu in ("ana_panel_tema", "fatura_tema", "satis_tema", "stok_kart_tema", "cari_kart_tema"):
            self.assertIn(zorunlu, hedefler)
        self.assertNotIn("invoice_print", hedefler)

    def test_T25_uygula_tercih_okumaz(self):
        """T25: uygula satır başına tercih/DB okumaz."""
        eski = ui_tema.aktif_tema_id()
        with patch("ui_tema.tercih_oku") as mock_oku:
            ui_tema.uygula("ferah")
            ui_tema.uygula("modern")
            mock_oku.assert_not_called()
        ui_tema.uygula(eski)


if __name__ == "__main__":
    unittest.main()
