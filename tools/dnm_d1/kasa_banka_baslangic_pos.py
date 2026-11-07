"""Kasa/banka başlangıç (ilk hareket/DEVİR) + POS valör kapanışı.

Mevcut KASA/BANKA ham JSON üzerinden; API yazımı yok.

  .venv\\Scripts\\python.exe -m tools.dnm_d1.kasa_banka_baslangic_pos
"""

from __future__ import annotations

import json
from collections import defaultdict
from datetime import date
from decimal import Decimal
from typing import Any

from tools.dnm_d1._ortak import KAYNAK, dec, parse_tarih, yaz_kaynak
from tools.dnm_d1.donem_sabitleri import DONEM_SONU, RAPOR_ONEKI_KAYNAK
from tools.dnm_d1.kapanis_kasa_banka import _hesap_id, _yon_tutar


def _ack_devir_mi(satir: dict) -> bool:
    metin = " ".join(
        str(satir.get(k) or "")
        for k in ("G.a_ack", "a_ack", "G.a_adi", "ACK", "G.a_belge_no", "G.a_kod")
    ).upper()
    return any(x in metin for x in ("DEVİR", "DEVIR", "AÇILIŞ", "ACILIS", "AÇILIS", "BAŞLANGIÇ", "BASLANGIC"))


def _hesap_hareketleri(modul: str) -> tuple[list[dict], dict[str, str]]:
    yol = KAYNAK / f"{RAPOR_ONEKI_KAYNAK}{modul.upper()}.json"
    veri = json.loads(yol.read_text(encoding="utf-8"))
    kartlar = {
        str(k.get("id") or k.get("a_id")): str(k.get("text") or k.get("a_adi") or "")
        for k in (veri.get("kartlar") or [])
    }
    return list(veri.get("hareketler") or []), kartlar


def _baslangic_raporu(modul: str) -> dict[str, Any]:
    hareketler, kartlar = _hesap_hareketleri(modul)
    by_hesap: dict[str, list[dict]] = defaultdict(list)
    for h in hareketler:
        hid = _hesap_id(h, modul=modul)
        t = parse_tarih(h.get("G.a_tarih") or h.get("a_tarih"))
        if t is None or t > DONEM_SONU:
            continue
        by_hesap[hid].append(h)

    hesaplar = []
    for hid, rows in sorted(by_hesap.items(), key=lambda x: x[0]):
        rows_sorted = sorted(
            rows,
            key=lambda r: (
                parse_tarih(r.get("G.a_tarih") or r.get("a_tarih")) or date.min,
                str(r.get("G.a_id") or r.get("a_id") or ""),
            ),
        )
        ilk = rows_sorted[0]
        ilk_t = parse_tarih(ilk.get("G.a_tarih") or ilk.get("a_tarih"))
        giren, cikan = _yon_tutar(ilk)
        net0 = (giren or Decimal("0")) - (cikan or Decimal("0"))
        devir_satirlar = [r for r in rows_sorted if _ack_devir_mi(r)]
        # Kapanış neti
        net = Decimal("0")
        for r in rows_sorted:
            g, c = _yon_tutar(r)
            net += (g or Decimal("0")) - (c or Decimal("0"))
        hesaplar.append(
            {
                "kaynak_hesap_id": hid,
                "hesap_adi": kartlar.get(hid) or hid,
                "ilk_hareket_tarih": ilk_t.isoformat() if ilk_t else None,
                "ilk_hareket_id": str(ilk.get("G.a_id") or ilk.get("a_id") or ""),
                "ilk_hareket_ack": ilk.get("G.a_ack") or ilk.get("a_ack"),
                "ilk_hareket_net": str(net0),
                "devir_belge_adet": len(devir_satirlar),
                "devir_belgeler": [
                    {
                        "id": str(r.get("G.a_id") or r.get("a_id") or ""),
                        "tarih": (
                            parse_tarih(r.get("G.a_tarih") or r.get("a_tarih")).isoformat()
                            if parse_tarih(r.get("G.a_tarih") or r.get("a_tarih"))
                            else None
                        ),
                        "ack": r.get("G.a_ack") or r.get("a_ack"),
                        "belge_no": r.get("G.a_belge_no") or r.get("G.a_kod"),
                    }
                    for r in devir_satirlar[:20]
                ],
                "donem_ici_hareket_adet": len(rows_sorted),
                "kapanis_net": str(net),
            }
        )
    return {
        "format": f"d1-kaynak-{modul}-baslangic-v1",
        "donem_sonu_dahil": DONEM_SONU.isoformat(),
        "hesap_adet": len(hesaplar),
        "hesaplar": hesaplar,
        "olcut": "ilk_hareket_ve_ack_devir_tarama",
    }


def _pos_valor() -> dict[str, Any]:
    banka = json.loads(
        (KAYNAK / f"{RAPOR_ONEKI_KAYNAK}BANKA.json").read_text(encoding="utf-8")
    )
    pos_ids = {
        str(k["id"])
        for k in (banka.get("kartlar") or [])
        if str(k.get("a_posmu") or "0") not in {"", "0"}
    }
    kart_ad = {str(k["id"]): k.get("text") for k in (banka.get("kartlar") or [])}
    pos_gun = {
        str(k["id"]): k.get("a_posgun") for k in (banka.get("kartlar") or []) if str(k["id"]) in pos_ids
    }

    bloke: list[dict] = []
    bankaya_gecmis: list[dict] = []
    valor_bekleyen: list[dict] = []
    donem_ici_pos = 0

    for h in banka.get("hareketler") or []:
        hid = str(h.get("G.a_banka_id") or h.get("a_banka_id") or "")
        if hid not in pos_ids:
            continue
        t = parse_tarih(h.get("G.a_tarih") or h.get("a_tarih"))
        if t is None or t > DONEM_SONU:
            continue
        donem_ici_pos += 1
        vt = parse_tarih(h.get("G.a_vtarih") or h.get("a_vtarih"))
        giren, cikan = _yon_tutar(h)
        tutar = (giren or Decimal("0")) - (cikan or Decimal("0"))
        bloke_flag = str(h.get("G.a_pos_bloke") or h.get("a_pos_bloke") or "0").strip()
        kayit = {
            "kaynak_banka_id": hid,
            "hesap_adi": kart_ad.get(hid),
            "hareket_id": str(h.get("G.a_id") or h.get("a_id") or ""),
            "tarih": t.isoformat(),
            "valor_tarihi": vt.isoformat() if vt else None,
            "pos_gun": pos_gun.get(hid),
            "pos_bloke": bloke_flag,
            "tutar_net": str(tutar),
            "ack": h.get("G.a_ack") or h.get("a_ack"),
        }
        if bloke_flag not in {"", "0"}:
            bloke.append(kayit)
        if vt is None:
            continue
        if vt > DONEM_SONU:
            valor_bekleyen.append(kayit)
        else:
            bankaya_gecmis.append(kayit)

    def _sum(rows: list[dict]) -> str:
        return str(sum((dec(r["tutar_net"]) for r in rows), Decimal("0")))

    return {
        "format": "d1-kaynak-pos-valor-v1",
        "donem_sonu_dahil": DONEM_SONU.isoformat(),
        "pos_hesap_adet": len(pos_ids),
        "donem_ici_pos_hareket": donem_ici_pos,
        "bloke_adet": len(bloke),
        "bloke_toplam": _sum(bloke),
        "valor_bekleyen_adet": len(valor_bekleyen),
        "valor_bekleyen_toplam": _sum(valor_bekleyen),
        "bankaya_gecmis_adet": len(bankaya_gecmis),
        "bankaya_gecmis_toplam": _sum(bankaya_gecmis),
        "bloke": bloke,
        "valor_bekleyen": valor_bekleyen,
        "bankaya_gecmis_ornek": bankaya_gecmis[:50],
        "olcut": "G.a_vtarih_vs_31.08.2026 + G.a_pos_bloke",
        "uyari": (
            "Valor bekleyen: işlem tarihi ≤31.08.2026 ama a_vtarih > 31.08.2026. "
            "Bankaya geçmiş listesinin tamamı örneklenmiş olabilir."
        ),
    }


def main() -> int:
    kasa = _baslangic_raporu("kasa")
    banka = _baslangic_raporu("banka")
    pos = _pos_valor()
    yaz_kaynak("KASA_BASLANGIC", kasa)
    yaz_kaynak("BANKA_BASLANGIC", banka)
    yaz_kaynak("POS_VALOR", pos)
    print(
        "kasa_hesap",
        kasa["hesap_adet"],
        "banka_hesap",
        banka["hesap_adet"],
        "pos_valor_bekleyen",
        pos["valor_bekleyen_adet"],
        pos["valor_bekleyen_toplam"],
        flush=True,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
