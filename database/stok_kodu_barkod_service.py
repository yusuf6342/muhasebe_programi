"""Stok kodu → 1. barkod otomatik senkron (merkezi kural).

Kurallar:
- Stok kodu trim + yalnızca 13 rakam → barkod adayı (metin; baştaki sıfır korunur).
- Otomatik satırlar aciklama içinde AUTO_STOK_KODU işareti taşır.
- Manuel barkodlar asla silinmez / üzerine yazılmaz.
"""

from __future__ import annotations

import logging
from typing import Any, Callable

from database.stok_service import ean13_dogrula

_LOG = logging.getLogger("stok_kodu_barkod")

AUTO_MARKER = "[AUTO_STOK_KODU]"
KAYNAK_METIN = "Stok kodundan otomatik oluşturuldu"
TUR_EAN13 = "EAN-13"
TUR_EAN13_DOGRULANDI = "EAN-13 Doğrulandı"
TUR_DAHILI = "13 Haneli Dahili Barkod"


def normalize_stock_code_as_text(stock_code: Any) -> str:
    """Metin olarak normalize; sayıya çevirme, baştaki sıfırları koru."""
    if stock_code is None:
        return ""
    return str(stock_code).strip()


def is_13_digit_barcode(stock_code: Any) -> bool:
    kod = normalize_stock_code_as_text(stock_code)
    return len(kod) == 13 and kod.isdigit()


def validate_ean13_check_digit(barcode: Any) -> bool:
    return ean13_dogrula(normalize_stock_code_as_text(barcode))


def _auto_aciklama(*, ean_ok: bool) -> str:
    tur = TUR_EAN13_DOGRULANDI if ean_ok else TUR_DAHILI
    return f"{AUTO_MARKER} {tur} | {KAYNAK_METIN}"


def is_auto_from_stock_code(kayit: dict | None) -> bool:
    if not kayit:
        return False
    acik = (kayit.get("aciklama") or "") if isinstance(kayit, dict) else ""
    return AUTO_MARKER in acik


def _barkod_listesi(barkodlar) -> list[dict]:
    sonuc = []
    for b in barkodlar or []:
        if isinstance(b, dict):
            sonuc.append(dict(b))
        else:
            sonuc.append(
                {
                    "barkod": getattr(b, "barkod", "") or "",
                    "birim": getattr(b, "birim", None) or "Adet",
                    "fiyat_adi": getattr(b, "fiyat_adi", None) or "",
                    "fiyat": str(getattr(b, "fiyat", 0) or 0),
                    "aciklama": getattr(b, "aciklama", None) or "",
                }
            )
    return sonuc


def check_duplicate_barcode(
    barcode: str, *, exclude_stock_id: int | None = None
) -> dict[str, Any] | None:
    """Aktif firma DB kapsamında mükerrer barkod. Yoksa None."""
    kod = normalize_stock_code_as_text(barcode)
    if not kod:
        return None
    from sqlalchemy import select
    from sqlalchemy.orm import selectinload

    from database.database import get_session
    from database.models.stok import StokBarkod, StokBirim, StokKarti

    with get_session() as session:
        # Ana barkod alanı
        q = select(StokKarti).where(StokKarti.barkod == kod)
        if exclude_stock_id:
            q = q.where(StokKarti.id != int(exclude_stock_id))
        stok = session.scalar(q)
        if stok is not None:
            return {
                "stok_id": int(stok.id),
                "stok_kodu": stok.stok_kodu or "",
                "stok_adi": stok.stok_adi or "",
            }
        # Ek barkodlar
        qb = (
            select(StokBarkod)
            .where(StokBarkod.barkod == kod)
            .options(selectinload(StokBarkod.stok))
        )
        if exclude_stock_id:
            qb = qb.where(StokBarkod.stok_id != int(exclude_stock_id))
        kayit = session.scalar(qb)
        if kayit is not None and kayit.stok is not None:
            s = kayit.stok
            return {
                "stok_id": int(s.id),
                "stok_kodu": s.stok_kodu or "",
                "stok_adi": s.stok_adi or "",
            }
        # Birim barkodu
        q3 = select(StokBirim).where(StokBirim.birim_barkod == kod)
        if exclude_stock_id:
            q3 = q3.where(StokBirim.stok_id != int(exclude_stock_id))
        birim = session.scalar(q3)
        if birim is not None:
            s = session.get(StokKarti, birim.stok_id)
            if s is not None:
                return {
                    "stok_id": int(s.id),
                    "stok_kodu": s.stok_kodu or "",
                    "stok_adi": s.stok_adi or "",
                }
    return None


def _auto_kayit(kod: str, *, birim: str, ean_ok: bool) -> dict:
    return {
        "barkod": kod,  # metin
        "birim": (birim or "Adet").strip() or "Adet",
        "fiyat_adi": "SATIŞ FİYATI 1",
        "fiyat": "0",
        "aciklama": _auto_aciklama(ean_ok=ean_ok),
        "barkod_turu": TUR_EAN13_DOGRULANDI if ean_ok else TUR_DAHILI,
        "sira": 1,
    }


def sync_primary_barcode_from_stock_code(
    barkodlar: list | None,
    stok_kodu: Any,
    *,
    birim: str = "Adet",
    exclude_stock_id: int | None = None,
    ask_add: bool = False,
    ask_callback: Callable[[str], str | None] | None = None,
    check_duplicate: bool = True,
) -> dict[str, Any]:
    """Barkod listesini stok koduna göre senkronize et.

    Dönüş:
      barkodlar, aksiyon, uyari_ean, duplicate, ean_ok, eklendi, guncellendi, kaldirildi
    aksiyon: set|update|remove|ask|skip|duplicate|noop
    """
    kod = normalize_stock_code_as_text(stok_kodu)
    liste = _barkod_listesi(barkodlar)
    rapor = {
        "barkodlar": liste,
        "aksiyon": "noop",
        "uyari_ean": None,
        "duplicate": None,
        "ean_ok": False,
        "eklendi": False,
        "guncellendi": False,
        "kaldirildi": False,
        "atlandi_mukerrer": False,
    }

    gecerli = is_13_digit_barcode(kod)
    ean_ok = validate_ean13_check_digit(kod) if gecerli else False
    rapor["ean_ok"] = ean_ok

    # Otomatik satır indeksleri
    auto_idx = [i for i, b in enumerate(liste) if is_auto_from_stock_code(b)]

    if not gecerli:
        if auto_idx:
            # Yalnızca otomatik satırları kaldır; manuel korunur
            yeni = [b for i, b in enumerate(liste) if i not in set(auto_idx)]
            rapor["barkodlar"] = yeni
            rapor["aksiyon"] = "remove"
            rapor["kaldirildi"] = True
        return rapor

    if not ean_ok:
        rapor["uyari_ean"] = (
            "Kod 13 hanelidir ancak EAN-13 kontrol basamağı doğrulanamadı."
        )

    # Kod zaten listede mi?
    mevcut_kodlar = {
        normalize_stock_code_as_text(b.get("barkod")): i for i, b in enumerate(liste)
    }
    if kod in mevcut_kodlar:
        rapor["aksiyon"] = "skip"
        return rapor

    if check_duplicate:
        dup = check_duplicate_barcode(kod, exclude_stock_id=exclude_stock_id)
        if dup:
            rapor["aksiyon"] = "duplicate"
            rapor["duplicate"] = dup
            rapor["atlandi_mukerrer"] = True
            return rapor

    yeni_kayit = _auto_kayit(kod, birim=birim, ean_ok=ean_ok)

    # Mevcut otomatik satırları kaldırıp birincil otomatik kaydı yeniden yerleştir
    if auto_idx:
        manuel = [b for i, b in enumerate(liste) if i not in set(auto_idx)]
        liste = [yeni_kayit, *manuel]
        rapor["barkodlar"] = liste
        rapor["aksiyon"] = "update"
        rapor["guncellendi"] = True
        return rapor

    # Birinci boş mu?
    birinci = liste[0] if liste else None
    birinci_dolu = bool(
        birinci and normalize_stock_code_as_text(birinci.get("barkod"))
    )

    if not liste or not birinci_dolu:
        if liste and not birinci_dolu:
            liste[0] = yeni_kayit
        else:
            liste.insert(0, yeni_kayit)
        rapor["barkodlar"] = liste
        rapor["aksiyon"] = "set"
        rapor["eklendi"] = True
        return rapor

    # Birinci dolu (manuel) — sor veya üzerine yazma
    if ask_add and ask_callback:
        cevap = ask_callback(kod)
        if cevap == "ekle":
            liste.append(yeni_kayit)
            rapor["barkodlar"] = liste
            rapor["aksiyon"] = "set"
            rapor["eklendi"] = True
        else:
            rapor["aksiyon"] = "skip"
        return rapor

    if ask_add:
        rapor["aksiyon"] = "ask"
        return rapor

    # save/bulk: birinci doluysa mevcutlara dokunma
    rapor["aksiyon"] = "skip"
    return rapor


def sync_for_save(
    barkodlar: list | None,
    stok_kodu: Any,
    *,
    birim: str = "Adet",
    exclude_stock_id: int | None = None,
    raise_on_duplicate: bool = True,
) -> tuple[list[dict], dict[str, Any]]:
    """Kayıt öncesi senkron; mükerrerde varsayılan olarak ValueError."""
    r = sync_primary_barcode_from_stock_code(
        barkodlar,
        stok_kodu,
        birim=birim,
        exclude_stock_id=exclude_stock_id,
        ask_add=False,
        check_duplicate=True,
    )
    if r["aksiyon"] == "duplicate" and r["duplicate"] and raise_on_duplicate:
        d = r["duplicate"]
        kod = normalize_stock_code_as_text(stok_kodu)
        raise ValueError(
            f"{kod} barkodu başka bir stok kartında kullanılmaktadır.\n"
            f"Mevcut stok:\n"
            f"Stok kodu: {d.get('stok_kodu') or '—'}\n"
            f"Ürün adı: {d.get('stok_adi') or '—'}"
        )
    return r["barkodlar"], r


def bulk_sync_report() -> dict[str, int]:
    return {
        "otomatik_olusturulan": 0,
        "zaten_mevcut": 0,
        "mukerrer_atlanan": 0,
        "gecersiz_ean": 0,
    }


def apply_bulk_sync_stats(istatistik: dict[str, int], rapor: dict[str, Any]) -> None:
    """ImportSonuc sayaçlarına senkron raporunu uygula."""
    if not istatistik or not rapor:
        return
    if rapor.get("eklendi") or rapor.get("guncellendi"):
        istatistik["otomatik_olusturulan"] = int(istatistik.get("otomatik_olusturulan", 0)) + 1
    elif rapor.get("aksiyon") == "skip":
        istatistik["zaten_mevcut"] = int(istatistik.get("zaten_mevcut", 0)) + 1
    if rapor.get("atlandi_mukerrer") or rapor.get("aksiyon") == "duplicate":
        istatistik["mukerrer_atlanan"] = int(istatistik.get("mukerrer_atlanan", 0)) + 1
    if rapor.get("uyari_ean"):
        istatistik["gecersiz_ean"] = int(istatistik.get("gecersiz_ean", 0)) + 1
