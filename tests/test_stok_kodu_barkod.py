"""Stok kodu → otomatik barkod senkron birim testleri."""

from __future__ import annotations

from unittest.mock import patch

import pytest

from database.stok_kodu_barkod_service import (
    AUTO_MARKER,
    is_13_digit_barcode,
    normalize_stock_code_as_text,
    sync_for_save,
    sync_primary_barcode_from_stock_code,
    validate_ean13_check_digit,
)
from database.stok_service import ean13_uret


def test_is_13_digit_barcode_true():
    assert is_13_digit_barcode("8691234567890") is True
    assert is_13_digit_barcode("0012345678901") is True


def test_is_13_digit_barcode_false():
    assert is_13_digit_barcode("123456789012") is False  # 12
    assert is_13_digit_barcode("12345678901234") is False  # 14
    assert is_13_digit_barcode("869123456789A") is False
    assert is_13_digit_barcode("869 1234567890") is False
    assert is_13_digit_barcode("") is False
    assert is_13_digit_barcode(None) is False


def test_leading_zeros_stay_string():
    kod = normalize_stock_code_as_text("0012345678901")
    assert kod == "0012345678901"
    assert isinstance(kod, str)
    # Sayıya çevrilmemeli
    assert kod != "12345678901"
    assert is_13_digit_barcode(kod) is True


def test_ean13_check_digit_valid_invalid():
    gecerli = ean13_uret("869123456789")
    assert len(gecerli) == 13
    assert validate_ean13_check_digit(gecerli) is True
    # Bilinçli yanlış kontrol basamağı
    bozuk = gecerli[:12] + ("0" if gecerli[12] != "0" else "1")
    assert validate_ean13_check_digit(bozuk) is False


def test_sync_sets_primary_when_empty():
    with patch(
        "database.stok_kodu_barkod_service.check_duplicate_barcode", return_value=None
    ):
        r = sync_primary_barcode_from_stock_code(
            [], "8691234567890", birim="Adet", check_duplicate=True
        )
    assert r["eklendi"] is True
    assert r["aksiyon"] == "set"
    assert r["barkodlar"][0]["barkod"] == "8691234567890"
    assert AUTO_MARKER in (r["barkodlar"][0].get("aciklama") or "")
    assert isinstance(r["barkodlar"][0]["barkod"], str)


def test_sync_does_not_overwrite_manual_first():
    manuel = [
        {
            "barkod": "1111111111111",
            "birim": "Adet",
            "fiyat_adi": "SATIŞ FİYATI 1",
            "fiyat": "0",
            "aciklama": "manuel",
        }
    ]
    with patch(
        "database.stok_kodu_barkod_service.check_duplicate_barcode", return_value=None
    ):
        r = sync_primary_barcode_from_stock_code(
            manuel, "8691234567890", birim="Adet", ask_add=False, check_duplicate=True
        )
    assert r["aksiyon"] == "skip"
    assert r["barkodlar"][0]["barkod"] == "1111111111111"
    assert len(r["barkodlar"]) == 1


def test_sync_updates_auto_when_stock_code_changes():
    eski = "8691234567890"
    yeni = ean13_uret("869123456780")
    liste = [
        {
            "barkod": eski,
            "birim": "Adet",
            "fiyat_adi": "SATIŞ FİYATI 1",
            "fiyat": "0",
            "aciklama": f"{AUTO_MARKER} EAN-13 Doğrulandı | test",
        },
        {
            "barkod": "9999999999999",
            "birim": "Adet",
            "fiyat_adi": "",
            "fiyat": "0",
            "aciklama": "manuel",
        },
    ]
    with patch(
        "database.stok_kodu_barkod_service.check_duplicate_barcode", return_value=None
    ):
        r = sync_primary_barcode_from_stock_code(
            liste, yeni, birim="Adet", check_duplicate=True
        )
    assert r["guncellendi"] is True
    assert r["barkodlar"][0]["barkod"] == yeni
    assert AUTO_MARKER in (r["barkodlar"][0].get("aciklama") or "")
    assert any(b["barkod"] == "9999999999999" for b in r["barkodlar"])


def test_sync_removes_auto_when_code_no_longer_13_digit():
    liste = [
        {
            "barkod": "8691234567890",
            "birim": "Adet",
            "fiyat_adi": "SATIŞ FİYATI 1",
            "fiyat": "0",
            "aciklama": f"{AUTO_MARKER} x",
        },
        {
            "barkod": "2222222222222",
            "birim": "Adet",
            "fiyat_adi": "",
            "fiyat": "0",
            "aciklama": "manuel",
        },
    ]
    r = sync_primary_barcode_from_stock_code(liste, "ABC-12", check_duplicate=False)
    assert r["kaldirildi"] is True
    assert r["aksiyon"] == "remove"
    assert len(r["barkodlar"]) == 1
    assert r["barkodlar"][0]["barkod"] == "2222222222222"


def test_sync_for_save_raises_on_duplicate():
    with patch(
        "database.stok_kodu_barkod_service.check_duplicate_barcode",
        return_value={"stok_id": 1, "stok_kodu": "X", "stok_adi": "Ürün"},
    ):
        with pytest.raises(ValueError, match="barkodu başka"):
            sync_for_save([], "8691234567890")


def test_sync_for_save_leading_zero_string():
    kod = "0012345678905"  # ean13_uret("001234567890")
    assert kod == ean13_uret("001234567890")
    with patch(
        "database.stok_kodu_barkod_service.check_duplicate_barcode", return_value=None
    ):
        liste, rapor = sync_for_save([], kod)
    assert liste[0]["barkod"] == kod
    assert isinstance(liste[0]["barkod"], str)
    assert liste[0]["barkod"].startswith("00")
