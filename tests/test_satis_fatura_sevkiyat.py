"""Satış faturası sevkiyat kopyası — çoklu kaynak, kalıcı kayıt."""

from __future__ import annotations

from datetime import date

import pytest

from database.satis_faturasi_service import SatisFaturasiService


def test_sevkiyat_blok_ekle_ayni_kaynagi_gunceller_digerini_silmez():
    liste = []
    liste = SatisFaturasiService.sevkiyat_blok_ekle(
        liste, {"irsaliye_id": 10, "irsaliye_no": "SI-1", "sevk_adresi": "Adres 1"}
    )
    liste = SatisFaturasiService.sevkiyat_blok_ekle(
        liste, {"irsaliye_id": 20, "irsaliye_no": "SI-2", "sevk_adresi": "Adres 2"}
    )
    liste = SatisFaturasiService.sevkiyat_blok_ekle(
        liste, {"irsaliye_id": 10, "irsaliye_no": "SI-1", "sevk_adresi": "Adres 1b"}
    )
    assert len(liste) == 2
    assert liste[0]["sevk_adresi"] == "Adres 1b"
    assert liste[1]["sevk_adresi"] == "Adres 2"


def test_sevkiyat_irsaliyeden_alanlari_kopyalar():
    class _Ir:
        id = 5
        irsaliye_no = "SI-9"
        irsaliye_tarihi = date(2026, 3, 1)
        sevk_adresi = "Cadde 1"
        sevk_il = "İstanbul"
        sevk_ilce = "Kadıköy"
        planlanan_teslim = date(2026, 3, 5)
        teslim_kisi = "Ali"
        teslim_telefon = "555"
        sevkiyat_yontemi = "Kargo"
        nakliyeci = "Aras"
        arac_plaka = "34ABC"
        sofor_adi = "Veli"
        sofor_telefon = "556"
        takip_no = "TRK"
        sevk_notu = "Not"
        fiili_sevk_tarihi = date(2026, 3, 2)

    veri = SatisFaturasiService.sevkiyat_irsaliyeden(_Ir())
    assert veri["irsaliye_id"] == 5
    assert veri["irsaliye_no"] == "SI-9"
    assert veri["sevk_adresi"] == "Cadde 1"
    assert veri["nakliyeci"] == "Aras"
    assert veri["takip_no"] == "TRK"
