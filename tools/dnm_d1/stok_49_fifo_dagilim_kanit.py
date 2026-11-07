"""49 FIFO stok-ID dağılımı — değer OK / fark / doğrulanmayan / sıfır(11).

Hareket gir_fiyat bazını kanıtlar; maliyet uydurmaz / kart doldurmaz.
LOT ve birim çarpan gözlemleri ayrı.

  .venv\\Scripts\\python.exe -m tools.dnm_d1.stok_49_fifo_dagilim_kanit
"""
from __future__ import annotations

import json
from collections import Counter
from datetime import datetime
from decimal import Decimal
from pathlib import Path

from tools.dnm_d1._ortak import CALISMA, KAYNAK, yaz_json
from tools.dnm_d1.donem_sabitleri import RAPOR_ONEKI_KAYNAK
from tools.dnm_d1.stok_envanter_excel_devir1 import tr_dec

FIFO = KAYNAK / f"{RAPOR_ONEKI_KAYNAK}DOGRULAMA_STOK_49_FIFO_HAREKET_KATMAN.json"
LOT = KAYNAK / f"{RAPOR_ONEKI_KAYNAK}DOGRULAMA_LOT_KATMAN_DEVAM.json"
BELGE = KAYNAK / f"{RAPOR_ONEKI_KAYNAK}BELGE_SATIR.jsonl"
HRK = KAYNAK / f"{RAPOR_ONEKI_KAYNAK}STOK_HAREKET_49_PASIF.jsonl"
OUT = KAYNAK / f"{RAPOR_ONEKI_KAYNAK}DOGRULAMA_STOK_49_FIFO_DAGILIM_KANIT.json"
OZET = CALISMA / "STOK_49_FIFO_DAGILIM_KANIT_OZET.json"


def _belge_satir_fiyat(sid: str, fat_id: str) -> dict | None:
    if not BELGE.is_file() or not fat_id or fat_id == "0":
        return None
    with BELGE.open(encoding="utf-8") as f:
        for line in f:
            if not line.strip():
                continue
            o = json.loads(line)
            if str(o.get("kaynak_belge_id")) != fat_id:
                continue
            for i, s in enumerate(o.get("satirlar") or []):
                if str(s.get("stok_id") or s.get("a_stok_id") or "") != sid:
                    continue
                return {
                    "belge_id": fat_id,
                    "satir_index": i,
                    "miktar": s.get("miktar"),
                    "birim_fiyat": s.get("birim_fiyat"),
                    "tutar": s.get("tutar"),
                    "birim": s.get("birim"),
                    "seri_lot": bool(s.get("seri_lot")),
                }
    return None


def _analiz_fark(x: dict) -> dict:
    """Değer farkı hipotezi — uydurma maliyet yok; gözlem."""
    ex = tr_dec(x.get("excel_tutar")) or Decimal("0")
    kat = tr_dec(x.get("katman_deger")) or Decimal("0")
    kalan = tr_dec(x.get("excel_kalan")) or Decimal("0")
    bm = tr_dec(x.get("excel_birim_maliyet"))
    oran = (kat / ex) if ex else None
    katmanlar = x.get("katmanlar") or []
    gir_fiyat = tr_dec(katmanlar[0]["birim_maliyet"]) if katmanlar else None
    gozlem = []
    hipotez = None
    # Hipotez: hareket gir_fiyat = satır tutarı (excel tutar ile eşit), birim değil
    if gir_fiyat is not None and ex and abs(gir_fiyat - ex) <= Decimal("0.02"):
        if kalan and oran is not None and abs(oran - kalan) <= Decimal("0.02"):
            hipotez = "HAREKET_GIR_FIYAT_SATIR_TUTARI_GORUNUYOR"
            gozlem.append(
                f"gir_fiyat≈excel_tutar ({gir_fiyat}); katman=gir_fiyat×kalan → oran≈kalan ({oran})"
            )
            gozlem.append(
                "Doğru birim maliyet belirsiz; excel_bm×kalan=excel_tutar ise excel birim kanıtı "
                f"(bm={bm}) — kart/ortalama doldurulmadı"
            )
    if hipotez is None and oran is not None and kalan and abs(oran - kalan) <= Decimal("0.05"):
        hipotez = "OLASI_FIYAT_BAZI_CARPAN_KALAN"
        gozlem.append(f"katman/excel oran≈kalan ({oran})")
    if hipotez is None:
        hipotez = "DEGER_FARK_NEDENI_ACIK_DEGIL"
        gozlem.append("Birim çarpan / LOT / belge satır fiyatı ayrıca kanıtlanmalı")
    # belge satır
    fat = str(katmanlar[0].get("belge_id") or "") if katmanlar else ""
    bel = _belge_satir_fiyat(str(x["kaynak_stok_id"]), fat)
    return {
        "hipotez": hipotez,
        "oran_katman_excel": str(oran) if oran is not None else None,
        "excel_kalan": str(kalan),
        "excel_birim_maliyet": str(bm) if bm is not None else None,
        "hareket_gir_fiyat_ilk_katman": str(gir_fiyat) if gir_fiyat is not None else None,
        "belge_satir_kanit": bel,
        "gozlem": gozlem,
        "maliyet_uydurma_yok": True,
        "kart_ortalama_doldurma_yok": True,
    }


def main() -> int:
    ham = json.loads(FIFO.read_text(encoding="utf-8"))
    lot = json.loads(LOT.read_text(encoding="utf-8")) if LOT.is_file() else {}
    lot_ids = set()
    for x in lot.get("kalan_ornek") or []:
        sid = str(x.get("stok_id") or x.get("kaynak_stok_id") or "")
        if sid:
            lot_ids.add(sid)

    gruplar = {
        "deger_ok": [],
        "deger_fark": [],
        "dogrulanamadi": [],
        "tuketildi_veya_sifir_11": [],
    }
    for x in ham.get("kayitlar") or []:
        d = x.get("durum")
        row = {
            "kaynak_stok_id": x["kaynak_stok_id"],
            "kod": x.get("kod"),
            "excel_satir": x.get("excel_satir"),
            "excel_kalan": x.get("excel_kalan"),
            "excel_tutar": x.get("excel_tutar"),
            "excel_birim_maliyet": x.get("excel_birim_maliyet"),
            "katman_adet": x.get("katman_adet"),
            "katman_kalan_toplam": x.get("katman_kalan_toplam"),
            "katman_deger": x.get("katman_deger"),
            "miktar_ok": x.get("miktar_ok"),
            "deger_ok": x.get("deger_ok"),
            "eksik_belge": x.get("eksik_belge"),
            "lot_durum": x.get("lot", {}).get("durum"),
            "lot_onceki_kayit": x.get("lot", {}).get("onceki_kayit_adet"),
            "in_lot_devam_ornek": str(x["kaynak_stok_id"]) in lot_ids,
        }
        if d == "FIFO_HAREKET_KATMAN_DEGER_OK":
            row["aciklama"] = "Hareket gir_fiyat×kalan ≈ excel tutar; miktar OK"
            gruplar["deger_ok"].append(row)
        elif d == "FIFO_HAREKET_KATMAN_MIKTAR_OK_DEGER_FARK":
            row["fiyat_bazi"] = _analiz_fark(x)
            gruplar["deger_fark"].append(row)
        elif d == "FIFO_HAREKET_KATMAN_KURULDU_DOGRULANMADI":
            row["aciklama"] = (
                "Katman kuruldu ama miktar/değer bandı dışı veya hassasiyet; "
                "ham hareket korunur"
            )
            row["fiyat_bazi"] = _analiz_fark(x)
            gruplar["dogrulanamadi"].append(row)
        elif d == "FIFO_TUKETILDI_VEYA_SIFIR":
            row["aciklama"] = (
                "Excel kalan 0 (veya tüketildi); katman boş — 11 stok bu gruptadır. "
                "Negatif değil; açılış katmanı gerekmez / sıfır kalan"
            )
            gruplar["tuketildi_veya_sifir_11"].append(row)

    # 38 katman = deger_ok + fark + dogrulanamadi (20+15+3)
    katmanli = (
        len(gruplar["deger_ok"])
        + len(gruplar["deger_fark"])
        + len(gruplar["dogrulanamadi"])
    )
    out = {
        "format": "d1-stok-49-fifo-dagilim-kanit-v1",
        "zaman": datetime.now().astimezone().isoformat(timespec="seconds"),
        "ozet": {
            "toplam_49": 49,
            "katman_kuruldu_38": katmanli,
            "deger_ok_20": len(gruplar["deger_ok"]),
            "deger_fark_15": len(gruplar["deger_fark"]),
            "dogrulanamadi_3": len(gruplar["dogrulanamadi"]),
            "tuketildi_veya_sifir_11": len(gruplar["tuketildi_veya_sifir_11"]),
            "dagilim_38": "20+15+3",
            "diger_11": "FIFO_TUKETILDI_VEYA_SIFIR (excel kalan 0)",
        },
        "hipotez_say": dict(
            Counter(
                r.get("fiyat_bazi", {}).get("hipotez")
                for r in gruplar["deger_fark"] + gruplar["dogrulanamadi"]
                if r.get("fiyat_bazi")
            )
        ),
        "lot": {
            "seri_lot_list_katman_maliyet": "BEKLIYOR (kaynak listede yok)",
            "49_lot_bekliyor": sum(
                1
                for g in gruplar.values()
                for r in g
                if (r.get("lot_durum") or "").startswith("BEKLIYOR")
            ),
            "maliyet_uydurma_yok": True,
        },
        "gruplar": gruplar,
        "kural": {
            "maliyet_uydurma_yok": True,
            "kart_ortalama_doldurma_yok": True,
            "yeniden_maliyet_hesabi_yok": True,
            "stok_kimlik_yeniden_toplanmadi": True,
        },
        "k05": False,
    }
    yaz_json(OUT, out)
    ozet = {
        "zaman": out["zaman"],
        **out["ozet"],
        "hipotez_say": out["hipotez_say"],
        "k05": False,
        "kanit": str(OUT.relative_to(CALISMA)).replace("\\", "/"),
    }
    yaz_json(OZET, ozet)
    print(json.dumps(ozet, ensure_ascii=False, indent=2), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
