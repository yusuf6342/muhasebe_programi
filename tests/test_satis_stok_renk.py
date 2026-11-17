"""Satış stok yetersizliği satır rengi — birim/talep kuralları (DB'siz)."""
from __future__ import annotations

import sys
import unittest
from decimal import Decimal
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from database.satis_stok_renk import (  # noqa: E402
    TAG_YETERSIZ,
    etiketlere_yetersiz_ekle,
    yetersiz_satir_indeksleri,
)


class SatisStokRenkTest(unittest.TestCase):
    def test_tag_adi(self):
        self.assertEqual(TAG_YETERSIZ, "stok_yetersiz")

    def test_etiket_sirasi_yetersiz_bastadir(self):
        """Tk ilk renkli etiketi kullanır; stok_yetersiz tek/cift'ten önce gelmeli."""
        self.assertEqual(
            etiketlere_yetersiz_ekle(("tek", "manuel_fiyat"), True),
            (TAG_YETERSIZ, "tek", "manuel_fiyat"),
        )
        self.assertEqual(
            etiketlere_yetersiz_ekle((TAG_YETERSIZ, "cift"), False),
            ("cift",),
        )
        self.assertEqual(etiketlere_yetersiz_ekle((), True), (TAG_YETERSIZ,))

    def test_lotlardan_satis_stok_negatif_net_sifir(self):
        """−500 + 500 neti 0 → ekran/uyarı stoğu 0 (yalnız pozitif 500 sayılmaz)."""
        from types import SimpleNamespace

        from database.satis_stok_renk import lotlardan_satis_stok

        lotlar = [
            SimpleNamespace(depo_id=1, kalan_miktar=Decimal("-500")),
            SimpleNamespace(depo_id=1, kalan_miktar=Decimal("500")),
            SimpleNamespace(depo_id=1, kalan_miktar=Decimal("0")),
        ]
        self.assertEqual(lotlardan_satis_stok(lotlar, depo_id=1), Decimal("0"))
        self.assertEqual(
            lotlardan_satis_stok(
                [SimpleNamespace(depo_id=1, kalan_miktar=Decimal("500"))], depo_id=1
            ),
            Decimal("500"),
        )

    def test_stok_5_satis_8_kirmizi(self):
        satirlar = [{"urun_kodu": "P1", "miktar": "8", "birim": "Adet"}]
        with patch(
            "database.satis_stok_renk.depo_pozitif_lot_toplamlari",
            return_value={"P1": Decimal("5")},
        ), patch("database.satis_stok_renk.get_session") as gs:
            gs.return_value.__enter__.return_value.scalars.return_value.all.return_value = []
            idx = yetersiz_satir_indeksleri(satirlar, "ANA DEPO")
        self.assertEqual(idx, {0})

    def test_stok_8_satis_8_normal(self):
        satirlar = [{"urun_kodu": "P1", "miktar": "8", "birim": "Adet"}]
        with patch(
            "database.satis_stok_renk.depo_pozitif_lot_toplamlari",
            return_value={"P1": Decimal("8")},
        ), patch("database.satis_stok_renk.get_session") as gs:
            gs.return_value.__enter__.return_value.scalars.return_value.all.return_value = []
            idx = yetersiz_satir_indeksleri(satirlar, "ANA DEPO")
        self.assertEqual(idx, set())

    def test_stok_8_satis_9_kirmizi(self):
        satirlar = [{"urun_kodu": "P1", "miktar": "9", "birim": "Adet"}]
        with patch(
            "database.satis_stok_renk.depo_pozitif_lot_toplamlari",
            return_value={"P1": Decimal("8")},
        ), patch("database.satis_stok_renk.get_session") as gs:
            gs.return_value.__enter__.return_value.scalars.return_value.all.return_value = []
            idx = yetersiz_satir_indeksleri(satirlar, "ANA DEPO")
        self.assertEqual(idx, {0})

    def test_bos_ve_sifir_boyama(self):
        satirlar = [
            {"urun_kodu": "", "miktar": "5", "birim": "Adet"},
            {"urun_kodu": "P1", "miktar": "0", "birim": "Adet"},
            {"urun_kodu": "P1", "miktar": "-1", "birim": "Adet"},
        ]
        with patch(
            "database.satis_stok_renk.depo_pozitif_lot_toplamlari",
            return_value={},
        ):
            idx = yetersiz_satir_indeksleri(satirlar, "ANA DEPO")
        self.assertEqual(idx, set())

    def test_ayni_urun_toplam_talep(self):
        """Stok 5; iki satır 3+3 → ikisi de kırmızı (aggregate)."""
        satirlar = [
            {"urun_kodu": "P1", "miktar": "3", "birim": "Adet"},
            {"urun_kodu": "P1", "miktar": "3", "birim": "Adet"},
        ]
        with patch(
            "database.satis_stok_renk.depo_pozitif_lot_toplamlari",
            return_value={"P1": Decimal("5")},
        ), patch("database.satis_stok_renk.get_session") as gs:
            gs.return_value.__enter__.return_value.scalars.return_value.all.return_value = []
            idx = yetersiz_satir_indeksleri(satirlar, "ANA DEPO")
        self.assertEqual(idx, {0, 1})

    def test_sorgu_hatasi_none(self):
        satirlar = [{"urun_kodu": "P1", "miktar": "1", "birim": "Adet"}]
        with patch(
            "database.satis_stok_renk.depo_pozitif_lot_toplamlari",
            side_effect=RuntimeError("db"),
        ):
            self.assertIsNone(yetersiz_satir_indeksleri(satirlar, "ANA DEPO"))

    def test_depo_bos_bos_set(self):
        self.assertEqual(
            yetersiz_satir_indeksleri([{"urun_kodu": "P1", "miktar": "1"}], ""),
            set(),
        )

    def test_ui_yollari_etiket_bastadir(self):
        """Canlı UI kodu stok_yetersiz'i sonda bırakmamalı."""
        import inspect

        import app as app_mod
        import hizli_satis_ui as hs

        fatura_src = inspect.getsource(app_mod.SatisFaturasiDialog._satis_stok_renk_etiket_uygula)
        self.assertIn("etiketlere_yetersiz_ekle", fatura_src)
        liste_src = inspect.getsource(app_mod.SatisFaturasiDialog._satir_listesini_yenile)
        self.assertIn("etiketlere_yetersiz_ekle", liste_src)
        sepet_src = inspect.getsource(hs.HizliSatisPencere._sepet_yenile)
        self.assertIn("etiketlere_yetersiz_ekle", sepet_src)
        iskelet_src = inspect.getsource(hs.HizliSatisPencere._iskelet_kur)
        self.assertIn('theme_use("clam")', iskelet_src)


if __name__ == "__main__":
    unittest.main()
