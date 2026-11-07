"""49 pasif dahil eşleme — aktif/pasif, mükerrer, negatif testleri.

  .venv\\Scripts\\python.exe -m tools.dnm_d1.test_stok_49_pasif_dahil_esleme
"""
from __future__ import annotations

import json
from decimal import Decimal

from entegrasyon.evobulut_client import STOKJQ_KOS_AKTIF, STOKJQ_KOS_PASIF
from tools.dnm_d1.stok_49_pasif_dahil_esleme import (
    _esle_3252,
    _excel_satirlari,
    _onceki_kimlik_by_satir,
)
from tools.dnm_d1.stok_envanter_excel_devir1 import BEK_SATIR


def test_aktif_pasif_kos_ayri() -> None:
    assert "pasif^x^14" in STOKJQ_KOS_AKTIF
    assert "pasif^x^15" in STOKJQ_KOS_PASIF
    assert STOKJQ_KOS_AKTIF != STOKJQ_KOS_PASIF


def test_excel_3252() -> None:
    rows = _excel_satirlari()
    assert len(rows) == BEK_SATIR == 3252


def test_ayni_kod_farkli_kart_birlestirilmez() -> None:
    excel = [
        {
            "excel_satir": 10,
            "kod": "X1",
            "adi": "a",
            "birim": "Adet",
            "kalan": Decimal("5"),
            "birim_maliyet": Decimal("1"),
            "tutar": Decimal("5"),
        }
    ]
    kartlar = [
        {"a_id": "1", "a_kod": "X1", "ana_birim_adi": "Adet", "aktif_pasif": "Aktif"},
        {"a_id": "2", "a_kod": "X1", "ana_birim_adi": "Adet", "aktif_pasif": "Aktif"},
    ]
    out = _esle_3252(excel, kartlar, {}, {}, {})
    assert out["eslesen_adet"] == 0
    assert out["kimlik_yok"][0]["esleme_durum"] == "COKLU_KART_AYNI_KOD"


def test_pasif_pozitif_dusmez() -> None:
    excel = [
        {
            "excel_satir": 11,
            "kod": "P1",
            "adi": "pasif",
            "birim": "Adet",
            "kalan": Decimal("3"),
            "birim_maliyet": Decimal("10"),
            "tutar": Decimal("30"),
        }
    ]
    bagla = {"P1": {"kaynak_stok_id": "99", "a_pasif": "15", "a_adi": "pasif"}}
    kartlar = [
        {
            "a_id": "99",
            "a_kod": "P1",
            "ana_birim_adi": "Adet",
            "aktif_pasif": "Pasif",
            "a_pasif": "15",
        }
    ]
    out = _esle_3252(excel, kartlar, bagla, {}, {})
    assert out["eslesen_adet"] == 1
    assert out["pasif_pozitif_miktar_veya_deger"] == 1
    assert out["pasif_pozitif_karsilastirmadan_dusmedi"] is True
    assert out["eslesen"][0]["pasif_kart"] is True


def test_negatif_korundu() -> None:
    excel = [
        {
            "excel_satir": 12,
            "kod": "N1",
            "adi": "neg",
            "birim": "Adet",
            "kalan": Decimal("-2"),
            "birim_maliyet": Decimal("0"),
            "tutar": Decimal("0"),
        }
    ]
    kartlar = [
        {"a_id": "7", "a_kod": "N1", "ana_birim_adi": "Adet", "aktif_pasif": "Aktif"}
    ]
    out = _esle_3252(excel, kartlar, {}, {}, {12: "7"})
    assert out["negatif_korundu_adet"] == 1
    assert out["eslesen"][0]["negatif_korundu"] is True


def test_a_id_tekillestirme() -> None:
    """Mükerrer çalışma: aynı a_id iki kez eklenmez."""
    by_id: dict[str, dict] = {}
    for k in (
        {"a_id": "1", "a_kod": "A", "aktif_pasif": "Aktif"},
        {"a_id": "1", "a_kod": "A", "aktif_pasif": "Pasif", "a_pasif": "15"},
        {"a_id": "2", "a_kod": "B", "aktif_pasif": "Pasif", "a_pasif": "15"},
    ):
        sid = str(k["a_id"])
        if sid in by_id:
            eski = by_id[sid]
            for key, val in k.items():
                if eski.get(key) in (None, "") and val not in (None, ""):
                    eski[key] = val
            if k.get("aktif_pasif") == "Pasif":
                eski["aktif_pasif"] = "Pasif"
                eski["a_pasif"] = k.get("a_pasif") or "15"
        else:
            by_id[sid] = dict(k)
    assert len(by_id) == 2
    assert by_id["1"]["aktif_pasif"] == "Pasif"


def test_onceki_kimlik_haritasi() -> None:
    m = _onceki_kimlik_by_satir()
    assert len(m) >= 3121


def main() -> int:
    test_aktif_pasif_kos_ayri()
    test_excel_3252()
    test_ayni_kod_farkli_kart_birlestirilmez()
    test_pasif_pozitif_dusmez()
    test_negatif_korundu()
    test_a_id_tekillestirme()
    test_onceki_kimlik_haritasi()
    print(json.dumps({"ok": True, "tests": 7}, ensure_ascii=False), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
