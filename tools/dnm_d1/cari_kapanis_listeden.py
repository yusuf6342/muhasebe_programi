"""Cari kart listesinden dönem sonu bakiye özeti.

ÖNEMLİ: Liste bakiyesi güncel görüntü olabilir; 31.08 resmi kapanış değildir.
Gerçek K05 için cari ekstre (finans_jq_listesi) ile borç/alacak/açık kalem gerekir.
Bu çıktı şablon doldurma iskeleti ve kimlik envanteridir; tamamlandı sayılmaz.
"""

from __future__ import annotations

import hashlib
import json
import re
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

from tools.dnm_d1.donem_sabitleri import CALISMA_KOK, DONEM_SONU, RAPOR_ONEKI_KAYNAK

KOK = Path(__file__).resolve().parents[2]
KAYNAK = KOK / CALISMA_KOK / "kaynak"

_BAKIYE = re.compile(
    r"Bakiye\s*:\s*([-\d.,]+)\s*\(([AB]?)\)",
    re.IGNORECASE,
)


def _dec(s: str) -> Decimal | None:
    try:
        return Decimal(s.replace(" ", "").replace(",", ""))
    except InvalidOperation:
        try:
            return Decimal(s.replace(" ", "").replace(".", "").replace(",", "."))
        except InvalidOperation:
            return None


def main() -> int:
    ham = json.loads((KAYNAK / f"{RAPOR_ONEKI_KAYNAK}CARI.json").read_text(encoding="utf-8"))
    kayitlar = ham.get("kayitlar") or []
    satirlar = []
    parse_yok = 0
    for r in kayitlar:
        cid = str(r.get("R.a_id") or "")
        ad = str(r.get("R.a_ad") or r.get("musteri") or "")
        tip = str(r.get("R.a_tip") or r.get("R.a_mus_tip") or "")
        text = str(r.get("text") or "")
        m = _BAKIYE.search(text)
        if not m:
            parse_yok += 1
            satirlar.append(
                {
                    "kaynak_cari_id": cid,
                    "cari_adi": ad,
                    "grup_tip": tip,
                    "para_birimi": "TL",
                    "guncel_bakiye": None,
                    "yon": None,
                    "olcut": "LISTE_BAKIYE_YOK",
                    "satir_sonucu": "VERİ BEKLENİYOR",
                    "uyari": "Liste metninde bakiye yok; sıfır varsayılmaz",
                }
            )
            continue
        tutar = _dec(m.group(1))
        yon_ham = (m.group(2) or "").upper()
        if not yon_ham and tutar == Decimal("0"):
            yon_ham = "0"  # sıfır bakiye; yön yok — sıfır kanıtlı sayısal 0
        satirlar.append(
            {
                "kaynak_cari_id": cid,
                "cari_adi": ad,
                "grup_tip": tip,
                "para_birimi": "TL",
                "guncel_liste_bakiyesi": str(tutar) if tutar is not None else None,
                "yon": yon_ham or None,  # B=borçlu, A=alacaklı, 0=sıfır
                "olcut": "GUNCEL_LISTE_BAKIYESI",
                "kapanis_3108": None,
                "donem_borc": None,
                "donem_alacak": None,
                "acik_borc": None,
                "acik_alacak": None,
                "valor_gun": None,
                "satir_sonucu": "VERİ BEKLENİYOR",
                "uyari": (
                    "Bu tutar kart listesinin güncel bakiyesidir; 31.08.2026 kapanışı değildir. "
                    "Ekstre ile dönem borç/alacak/açık kalem kurulmadan K05 açılmaz."
                ),
            }
        )

    out = {
        "format": "d1-kaynak-cari-liste-ozet-v1",
        "donem_sonu_hedef": DONEM_SONU.isoformat(),
        "adet": len(satirlar),
        "bakiye_parse_yok": parse_yok,
        "kapanis_durumu": "GUNCEL_LISTE_—_3108_DEGIL",
        "cariler": satirlar,
    }
    yol = KAYNAK / f"{RAPOR_ONEKI_KAYNAK}CARI_LISTE_OZET.json"
    ham_b = json.dumps(out, ensure_ascii=False, indent=2).encode("utf-8")
    yol.write_bytes(ham_b)
    sha = hashlib.sha256(ham_b).hexdigest().upper()
    yol.with_suffix(".sha256").write_text(f"{sha}  {yol.name}\n", encoding="ascii")
    print("YAZILDI", yol.name, "adet", len(satirlar), "parse_yok", parse_yok, flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
