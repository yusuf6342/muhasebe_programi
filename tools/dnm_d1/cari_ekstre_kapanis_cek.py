"""Cari ekstre (max 1 yıl dilimleri) → 31.08.2026 kapanış özeti.

API: Musteri/base finans_jq_listesi → veri.Devreden / Özet / Detay
Salt okuma. Ara: CARI_EKSTRE_KAPANIS.jsonl

  .venv\\Scripts\\python.exe -m tools.dnm_d1.cari_ekstre_kapanis_cek
  .venv\\Scripts\\python.exe -m tools.dnm_d1.cari_ekstre_kapanis_cek --limit 50 --yeniden
"""

from __future__ import annotations

import argparse
import hashlib
import json
import time
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

from tools.dnm_d1.donem_sabitleri import CALISMA_KOK, DONEM_SONU, RAPOR_ONEKI_KAYNAK

KOK = Path(__file__).resolve().parents[2]
KAYNAK = KOK / CALISMA_KOK / "kaynak"
JSONL = KAYNAK / f"{RAPOR_ONEKI_KAYNAK}CARI_EKSTRE_KAPANIS.jsonl"


def _dec(v: Any) -> Decimal:
    if v is None or v == "":
        return Decimal("0")
    try:
        return Decimal(str(v).strip().replace(" ", "").replace(",", "."))
    except InvalidOperation:
        return Decimal("0")


def _ozet_al(blok: Any) -> dict[str, str]:
    if isinstance(blok, list) and blok:
        b = blok[0] if isinstance(blok[0], dict) else {}
    elif isinstance(blok, dict):
        b = blok
    else:
        b = {}
    return {
        "borc": str(_dec(b.get("Borc") or b.get("borc"))),
        "alacak": str(_dec(b.get("Alacak") or b.get("alacak"))),
        "bakiye": str(_dec(b.get("Bakiye") or b.get("bakiye"))),
    }


def _dilimler(son: date = DONEM_SONU) -> list[tuple[str, str]]:
    """1 yıllık dilimler; son dilim 31.08.2026’da biter."""
    out: list[tuple[str, str]] = []
    yil = 2015
    while yil <= son.year:
        bas = date(yil, 1, 1)
        bit = date(yil, 12, 31)
        if bit > son:
            bit = son
        if bas <= son:
            out.append((bas.strftime("%d.%m.%Y"), bit.strftime("%d.%m.%Y")))
        yil += 1
    return out


def _oturum_gecersiz_mi(y: dict) -> bool:
    if y.get("status") == "OK":
        return False
    veri = y.get("veri")
    metin = json.dumps(veri, ensure_ascii=False) if veri is not None else ""
    return "Geçersiz oturum" in metin or "Token" in metin or "Login" in metin


def _cek_dilim(c, musteri_id: str, bas: str, son: str, *, yeniden_dene: bool = True) -> dict[str, Any]:
    y = c._post(
        "Musteri/base/",
        {
            "cmd": "finans_jq_listesi",
            "UID": c.uid,
            "musteri_id": str(musteri_id),
            "b_tarihi": bas,
            "s_tarihi": son,
            "tur": "-1",
        },
    )
    if _oturum_gecersiz_mi(y) and yeniden_dene:
        c.login()
        return _cek_dilim(c, musteri_id, bas, son, yeniden_dene=False)
    if y.get("status") != "OK":
        return {
            "bas": bas,
            "son": son,
            "status": y.get("status"),
            "hata": y.get("veri"),
            "devreden": None,
            "ozet": None,
            "detay_adet": 0,
        }
    veri = y.get("veri") or {}
    if not isinstance(veri, dict):
        return {
            "bas": bas,
            "son": son,
            "status": "ERR",
            "hata": veri,
            "devreden": None,
            "ozet": None,
            "detay_adet": 0,
        }
    detay = veri.get("Detay") or []
    if not isinstance(detay, list):
        detay = []
    return {
        "bas": bas,
        "son": son,
        "status": "OK",
        "devreden": _ozet_al(veri.get("Devreden")),
        "ozet": _ozet_al(veri.get("Özet") or veri.get("Ozet")),
        "detay_adet": len(detay),
        "detay_toplam_sayisi": veri.get("Detay_Toplam_Sayisi"),
    }


def _cari_kapanis(c, cid: str, *, tam_dilim: bool = False) -> dict[str, Any]:
    """31.08 kapanış: 01.09.2025–31.08.2026 penceresi Özet (1 yıl üst sınır).

    ``tam_dilim=True`` ise 2015’ten yıllık dilimleri de ekler (yavaş).
    """
    # Hariç üst sınırın 1 yıl öncesi: 2025-09-01
    kapanis_bas = "01.09.2025"
    kapanis_son = DONEM_SONU.strftime("%d.%m.%Y")
    ana = _cek_dilim(c, cid, kapanis_bas, kapanis_son)
    dilimler = [ana]
    if tam_dilim:
        for bas, son in _dilimler():
            if (bas, son) == (kapanis_bas, kapanis_son):
                continue
            dilimler.append(_cek_dilim(c, cid, bas, son))
            time.sleep(0.02)
    son_ozet = ana.get("ozet") if ana.get("status") == "OK" else None
    return {
        "kaynak_cari_id": cid,
        "donem_sonu_dahil": DONEM_SONU.isoformat(),
        "alim_zamani": datetime.now().astimezone().isoformat(timespec="seconds"),
        "kapanis_pencere": {"bas": kapanis_bas, "son": kapanis_son},
        "devreden_pencere": ana.get("devreden"),
        "son_ozet": son_ozet,
        "kapanis_bakiye": (son_ozet or {}).get("bakiye"),
        "kapanis_borc_ozet": (son_ozet or {}).get("borc"),
        "kapanis_alacak_ozet": (son_ozet or {}).get("alacak"),
        "detay_satir_adet": ana.get("detay_adet"),
        "dilimler": dilimler,
        "olcut": "finans_jq_listesi_1yil_pencere_3108",
        "uyari": (
            "Kapanış Özet.bakiyesi 01.09.2025–31.08.2026 penceresindendir. "
            "Açık kalem/vade ve dönem brüt borç/alacak için Detay satırları ayrıca işlenir."
        ),
    }


def main(argv: list[str] | None = None) -> int:
    from entegrasyon.evobulut_client import EvobulutClient, load_credentials

    p = argparse.ArgumentParser()
    p.add_argument("--limit", type=int, default=0)
    p.add_argument("--yeniden", action="store_true", help="JSONL sıfırla")
    p.add_argument("--tam-dilim", action="store_true", help="2015’ten yıllık dilimler (yavaş)")
    args = p.parse_args(argv)

    cari_yol = KAYNAK / f"{RAPOR_ONEKI_KAYNAK}CARI.json"
    cariler = json.loads(cari_yol.read_text(encoding="utf-8")).get("kayitlar") or []
    ids = [str(r.get("R.a_id")) for r in cariler if r.get("R.a_id")]
    if args.limit:
        ids = ids[: args.limit]

    KAYNAK.mkdir(parents=True, exist_ok=True)
    if args.yeniden and JSONL.is_file():
        JSONL.unlink()

    # Başarılı kapanışlar; hatalı/eksik olanlar yeniden denenecek
    basarili: dict[str, dict] = {}
    if JSONL.is_file() and not args.yeniden:
        for line in JSONL.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            try:
                o = json.loads(line)
                cid = str(o.get("kaynak_cari_id") or "")
                if cid and o.get("son_ozet") is not None:
                    basarili[cid] = o
            except json.JSONDecodeError:
                pass

    c = EvobulutClient(load_credentials())
    c.login()
    t0 = time.time()
    yeni = 0
    # Yeniden yaz: önce başarılıları koru
    tmp = JSONL.with_suffix(".jsonl.tmp")
    with tmp.open("w", encoding="utf-8") as f:
        for o in basarili.values():
            f.write(json.dumps(o, ensure_ascii=False) + "\n")
        for i, cid in enumerate(ids, 1):
            if cid in basarili:
                if i % 50 == 0:
                    print(f"atlandi_basarili {i}/{len(ids)}", flush=True)
                continue
            try:
                if i % 40 == 0:
                    c.login()  # periyodik yenileme
                kayit = _cari_kapanis(c, cid, tam_dilim=args.tam_dilim)
                f.write(json.dumps(kayit, ensure_ascii=False) + "\n")
                f.flush()
                if kayit.get("son_ozet") is not None:
                    basarili[cid] = kayit
                    yeni += 1
            except Exception as exc:  # noqa: BLE001
                f.write(
                    json.dumps(
                        {
                            "kaynak_cari_id": cid,
                            "hata": type(exc).__name__,
                            "mesaj": str(exc)[:240],
                        },
                        ensure_ascii=False,
                    )
                    + "\n"
                )
                f.flush()
            if i % 10 == 0 or i == len(ids):
                print(
                    f"ilerleme {i}/{len(ids)} yeni_ok={yeni} basarili={len(basarili)} "
                    f"gecen={time.time()-t0:.0f}s",
                    flush=True,
                )
    tmp.replace(JSONL)

    ozet = []
    for line in JSONL.read_text(encoding="utf-8").splitlines():
        if line.strip():
            ozet.append(json.loads(line))
    # Aynı cari birden fazla yazılmışsa son başarılıyı seç
    son: dict[str, dict] = {}
    for x in ozet:
        cid = str(x.get("kaynak_cari_id") or "")
        if not cid:
            continue
        if x.get("son_ozet") is not None or cid not in son:
            son[cid] = x
    ozet = list(son.values())
    tamam = sum(1 for x in ozet if x.get("son_ozet") is not None) >= len(ids)
    out = {
        "format": "d1-kaynak-cari-ekstre-kapanis-v1",
        "donem_sonu_dahil": DONEM_SONU.isoformat(),
        "adet": len(ozet),
        "hedef_cari_adet": len(ids),
        "tamam_mi": tamam,
        "cariler": ozet,
        "kapanis_durumu": "EKSTRE_DILIMLI" if tamam else "KISMI_EKSTRE",
    }
    yol = KAYNAK / f"{RAPOR_ONEKI_KAYNAK}CARI_EKSTRE_KAPANIS.json"
    ham = json.dumps(out, ensure_ascii=False, indent=2).encode("utf-8")
    yol.write_bytes(ham)
    sha = hashlib.sha256(ham).hexdigest().upper()
    yol.with_suffix(".sha256").write_text(f"{sha}  {yol.name}\n", encoding="ascii")
    print("YAZILDI", yol.name, "adet", len(ozet), "tamam", tamam, flush=True)
    return 0 if tamam else 1


if __name__ == "__main__":
    raise SystemExit(main())
