"""Rapor Excel karşılaştırma — bakiyeyi değiştirmez; geçici sonuç üretir."""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from typing import Any


def _anahtar(satir: dict[str, Any], alanlar: list[str]) -> tuple:
    degerler = []
    for a in alanlar:
        v = satir.get(a)
        if v is None:
            degerler.append("")
        else:
            degerler.append(str(v).strip().casefold())
    return tuple(degerler)


def _tutar(satir: dict[str, Any], alan: str | None) -> Decimal | None:
    if not alan:
        return None
    v = satir.get(alan)
    if v is None or v == "":
        return None
    if isinstance(v, Decimal):
        return v
    try:
        metin = str(v).strip().replace(" ", "")
        if "," in metin and "." in metin:
            if metin.rfind(",") > metin.rfind("."):
                metin = metin.replace(".", "").replace(",", ".")
            else:
                metin = metin.replace(",", "")
        elif "," in metin:
            metin = metin.replace(".", "").replace(",", ".")
        return Decimal(metin)
    except (InvalidOperation, ValueError):
        return None


@dataclass
class KarsilastirmaSonucu:
    eslesen: list[dict[str, Any]] = field(default_factory=list)
    sadece_program: list[dict[str, Any]] = field(default_factory=list)
    sadece_excel: list[dict[str, Any]] = field(default_factory=list)
    tutar_farkli: list[dict[str, Any]] = field(default_factory=list)
    belirsiz: list[dict[str, Any]] = field(default_factory=list)
    tolerans: Decimal = Decimal("0")

    def ozet(self) -> dict[str, int]:
        return {
            "eslesen": len(self.eslesen),
            "sadece_program": len(self.sadece_program),
            "sadece_excel": len(self.sadece_excel),
            "tutar_farkli": len(self.tutar_farkli),
            "belirsiz": len(self.belirsiz),
        }


def karsilastir(
    program_satirlari: list[dict[str, Any]],
    excel_satirlari: list[dict[str, Any]],
    *,
    anahtar_alanlar: list[str],
    tutar_alani: str | None = None,
    tolerans: Decimal | float | int | str = 0,
) -> KarsilastirmaSonucu:
    """Program ve Excel satırlarını anahtar alanlara göre karşılaştır.

    Aynı anahtara birden fazla satır düşerse belirsiz sayılır (otomatik çift kapatma yok).
    """
    if not anahtar_alanlar:
        raise ValueError("Karşılaştırma anahtarı seçilmelidir.")
    tol = Decimal(str(tolerans or 0))
    sonuc = KarsilastirmaSonucu(tolerans=tol)

    prog_map: dict[tuple, list[dict[str, Any]]] = {}
    for s in program_satirlari:
        prog_map.setdefault(_anahtar(s, anahtar_alanlar), []).append(s)
    excel_map: dict[tuple, list[dict[str, Any]]] = {}
    for s in excel_satirlari:
        excel_map.setdefault(_anahtar(s, anahtar_alanlar), []).append(s)

    tum_anahtarlar = set(prog_map) | set(excel_map)
    for key in tum_anahtarlar:
        p_list = prog_map.get(key) or []
        e_list = excel_map.get(key) or []
        if len(p_list) > 1 or len(e_list) > 1:
            sonuc.belirsiz.append(
                {
                    "anahtar": key,
                    "program_adet": len(p_list),
                    "excel_adet": len(e_list),
                    "program": p_list,
                    "excel": e_list,
                    "gerekce": "Aynı anahtarda birden fazla satır — kullanıcı seçimi gerekir.",
                }
            )
            continue
        if p_list and not e_list:
            sonuc.sadece_program.append({"anahtar": key, "program": p_list[0]})
            continue
        if e_list and not p_list:
            sonuc.sadece_excel.append({"anahtar": key, "excel": e_list[0]})
            continue
        p, e = p_list[0], e_list[0]
        if tutar_alani:
            pt, et = _tutar(p, tutar_alani), _tutar(e, tutar_alani)
            if pt is not None and et is not None and abs(pt - et) > tol:
                sonuc.tutar_farkli.append(
                    {
                        "anahtar": key,
                        "program": p,
                        "excel": e,
                        "program_tutar": pt,
                        "excel_tutar": et,
                        "fark": pt - et,
                    }
                )
                continue
        sonuc.eslesen.append({"anahtar": key, "program": p, "excel": e})
    return sonuc
