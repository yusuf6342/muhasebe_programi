"""Fatura/fiş (30–37) satır detayları — fatura/base cmd=sql sql_id.

Salt okuma. Ara: BELGE_SATIR.jsonl  (~10k belge; devam ettirilebilir)

  .venv\\Scripts\\python.exe -m tools.dnm_d1.belge_satir_cek
  .venv\\Scripts\\python.exe -m tools.dnm_d1.belge_satir_cek --limit 100 --yeniden
"""

from __future__ import annotations

import argparse
import json
import time
from datetime import datetime
from pathlib import Path
from typing import Any

from tools.dnm_d1._ortak import KAYNAK, oturum_gecersiz_mi, parse_tarih, yaz_kaynak
from tools.dnm_d1.donem_sabitleri import DONEM_SONU, RAPOR_ONEKI_KAYNAK

JSONL = KAYNAK / f"{RAPOR_ONEKI_KAYNAK}BELGE_SATIR.jsonl"


def _detay(c, fid: str, *, yeniden: bool = True) -> dict[str, Any]:
    y = c._post(
        "fatura/base/",
        {"cmd": "sql", "UID": c.uid, "sql_id": str(fid)},
    )
    if oturum_gecersiz_mi(y) and yeniden:
        c.login()
        return _detay(c, fid, yeniden=False)
    veri = y.get("veri") or y.get("Veri")
    blok = None
    if isinstance(veri, list) and veri:
        blok = veri[0] if isinstance(veri[0], dict) else None
    elif isinstance(veri, dict):
        blok = veri
    if not isinstance(blok, dict):
        return {
            "kaynak_belge_id": fid,
            "status": y.get("status"),
            "hata": veri,
            "satir_adet": 0,
            "satirlar": [],
            "ana": {},
        }
    ana = blok.get("Ana") or []
    ana0 = ana[0] if isinstance(ana, list) and ana else {}
    det = blok.get("Detay") or []
    if not isinstance(det, list):
        det = []
    satirlar = []
    for s in det:
        if not isinstance(s, dict):
            continue
        lot = s.get("Seri_Lot_List")
        satirlar.append(
            {
                "stok_id": s.get("a_stok_id") or s.get("a_cari_id"),  # a_stok_id tercih
                "a_stok_id": s.get("a_stok_id"),
                "stok_kod": s.get("a_stok_kod") or s.get("a_kod"),
                "stok_adi": s.get("a_stok_adi") or s.get("a_adi"),
                "miktar": s.get("a_mik") or s.get("a_brm_mik"),
                "birim": s.get("a_brm_adi") or s.get("a_brm"),
                "birim_fiyat": s.get("a_brm_fiy") or s.get("a_fiyat"),
                "tutar": s.get("a_tut") or s.get("a_tutar"),
                "kdv": s.get("a_kdv") or s.get("a_kdv_oran"),
                "depo_id": s.get("a_depo_id"),
                "ack": s.get("a_ack"),
                "seri_lot": lot if lot not in (None, "", [], {}) else None,
                "ham_keys": None,
            }
        )
    return {
        "kaynak_belge_id": fid,
        "status": "OK",
        "tur": ana0.get("a_tur") if isinstance(ana0, dict) else None,
        "tarih": (
            parse_tarih(ana0.get("a_tarih")).isoformat()
            if isinstance(ana0, dict) and parse_tarih(ana0.get("a_tarih"))
            else None
        ),
        "vade": (
            parse_tarih(ana0.get("a_vtarih")).isoformat()
            if isinstance(ana0, dict) and parse_tarih(ana0.get("a_vtarih"))
            else None
        ),
        "cari_id": ana0.get("a_cari_id") if isinstance(ana0, dict) else None,
        "belge_no": ana0.get("a_kod") if isinstance(ana0, dict) else None,
        "satir_adet": len(satirlar),
        "satirlar": satirlar,
        "ana_ozet": {
            k: ana0.get(k)
            for k in (
                "a_id",
                "a_tur",
                "a_kod",
                "a_tarih",
                "a_vtarih",
                "a_cari_id",
                "a_dov_id",
                "a_dov_kur",
                "a_genel_toplam",
                "a_ara_toplam",
                "a_kdv_toplam",
                "BELGE_TUR",
            )
            if isinstance(ana0, dict) and k in ana0
        },
        "alim_zamani": datetime.now().astimezone().isoformat(timespec="seconds"),
        "donem_sonu_dahil": DONEM_SONU.isoformat(),
    }


def _belge_ids() -> list[tuple[str, str]]:
    bel = json.loads(
        (KAYNAK / f"{RAPOR_ONEKI_KAYNAK}BELGE.json").read_text(encoding="utf-8")
    )
    out: list[tuple[str, str]] = []
    for tur, lst in (bel.get("belgeler") or {}).items():
        if not isinstance(lst, list):
            continue
        for r in lst:
            fid = r.get("G.a_id") or r.get("a_id")
            if not fid:
                continue
            t = parse_tarih(r.get("G.a_tarih") or r.get("a_tarih"))
            if t is not None and t > DONEM_SONU:
                continue
            out.append((str(fid), str(tur)))
    # tekil
    seen = set()
    uniq = []
    for fid, tur in out:
        if fid in seen:
            continue
        seen.add(fid)
        uniq.append((fid, tur))
    return uniq


def main(argv: list[str] | None = None) -> int:
    from entegrasyon.evobulut_client import EvobulutClient, load_credentials

    p = argparse.ArgumentParser()
    p.add_argument("--limit", type=int, default=0)
    p.add_argument("--yeniden", action="store_true")
    args = p.parse_args(argv)

    ids = _belge_ids()
    if args.limit:
        ids = ids[: args.limit]

    KAYNAK.mkdir(parents=True, exist_ok=True)
    if args.yeniden and JSONL.is_file():
        JSONL.unlink()

    basarili: dict[str, dict] = {}
    if JSONL.is_file() and not args.yeniden:
        for line in JSONL.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            try:
                o = json.loads(line)
                fid = str(o.get("kaynak_belge_id") or "")
                if fid and o.get("status") == "OK":
                    basarili[fid] = o
            except json.JSONDecodeError:
                pass

    c = EvobulutClient(load_credentials())
    c.login()
    t0 = time.time()
    yeni = 0
    lot_satir = 0
    tmp = JSONL.with_suffix(".jsonl.tmp")
    with tmp.open("w", encoding="utf-8") as f:
        for o in basarili.values():
            f.write(json.dumps(o, ensure_ascii=False) + "\n")
        for i, (fid, tur) in enumerate(ids, 1):
            if fid in basarili:
                continue
            try:
                if i % 50 == 0:
                    c.login()
                kayit = _detay(c, fid)
                kayit["liste_tur"] = tur
                f.write(json.dumps(kayit, ensure_ascii=False) + "\n")
                f.flush()
                if kayit.get("status") == "OK":
                    basarili[fid] = kayit
                    yeni += 1
                    for s in kayit.get("satirlar") or []:
                        if s.get("seri_lot"):
                            lot_satir += 1
            except Exception as exc:  # noqa: BLE001
                f.write(
                    json.dumps(
                        {
                            "kaynak_belge_id": fid,
                            "liste_tur": tur,
                            "hata": type(exc).__name__,
                            "mesaj": str(exc)[:200],
                        },
                        ensure_ascii=False,
                    )
                    + "\n"
                )
                f.flush()
            if i % 20 == 0 or i == len(ids):
                print(
                    f"belge_satir {i}/{len(ids)} yeni={yeni} ok={len(basarili)} "
                    f"gecen={time.time()-t0:.0f}s",
                    flush=True,
                )
            time.sleep(0.01)
    tmp.replace(JSONL)

    liste = list(basarili.values())
    satir_toplam = sum(int(x.get("satir_adet") or 0) for x in liste)
    lot_dolu = sum(
        1
        for x in liste
        for s in (x.get("satirlar") or [])
        if s.get("seri_lot")
    )
    # Özet JSON (tam satırlar jsonl'de; özet indekste)
    indeks = [
        {
            "kaynak_belge_id": x.get("kaynak_belge_id"),
            "tur": x.get("tur") or x.get("liste_tur"),
            "tarih": x.get("tarih"),
            "vade": x.get("vade"),
            "cari_id": x.get("cari_id"),
            "belge_no": x.get("belge_no"),
            "satir_adet": x.get("satir_adet"),
            "lot_satir_adet": sum(
                1 for s in (x.get("satirlar") or []) if s.get("seri_lot")
            ),
        }
        for x in liste
    ]
    out = {
        "format": "d1-kaynak-belge-satir-v1",
        "donem_sonu_dahil": DONEM_SONU.isoformat(),
        "belge_adet": len(liste),
        "hedef_belge_adet": len(ids),
        "satir_toplam": satir_toplam,
        "lot_dolu_satir_adet": lot_dolu,
        "tamam_mi": len(liste) >= len(ids),
        "jsonl": JSONL.name,
        "indeks": indeks,
        "kapanis_durumu": "BELGE_SATIR" if len(liste) >= len(ids) else "KISMI_BELGE_SATIR",
        "uyari": "Tam satır gövdesi JSONL’dedir; bu JSON indeks + sayaçtır.",
    }
    yaz_kaynak("BELGE_SATIR", out)
    print(
        "OZET belge",
        out["belge_adet"],
        "satir",
        satir_toplam,
        "lot_satir",
        lot_dolu,
        flush=True,
    )
    return 0 if out["tamam_mi"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
