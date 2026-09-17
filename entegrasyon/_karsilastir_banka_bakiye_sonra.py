"""Taşıma sonrası Evo vs yerel banka bakiyesi özeti."""

from __future__ import annotations

import sys
from collections import defaultdict
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path

from sqlalchemy import select

from database.database import get_session, sistem_altyapisini_baslat
from database.finans_service import FinansService
from database.models.finans import BankAccountMatchRule
from database.session_manager import oturum
from entegrasyon.banka_eslestirme import BankAccountMatchingService
from entegrasyon.evb_import_common import _temiz
from entegrasyon.evobulut_client import EvobulutClient, load_credentials


def _d(v) -> Decimal:
    s = _temiz(v).replace(",", ".")
    if not s:
        return Decimal("0")
    try:
        return Decimal(s)
    except Exception:
        return Decimal("0")


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    sistem_altyapisini_baslat()
    oturum.set_user(
        user_id=1,
        kullanici_adi="admin",
        ad_soyad="CLI",
        role_kod="YONETICI",
        role_ad="Y",
        permissions=set(),
    )

    client = EvobulutClient(load_credentials())
    client.login()

    agg: dict[str, dict] = defaultdict(
        lambda: {"giren": Decimal("0"), "cikan": Decimal("0"), "adet": 0, "ids": set()}
    )
    bugun = date.today()
    for yil in range(2015, bugun.year + 1):
        bas = f"01.01.{yil}"
        son = bugun.strftime("%d.%m.%Y") if yil == bugun.year else f"31.12.{yil}"
        print(f"Evo {yil}…", flush=True)
        sayfa = 0
        while sayfa < 500:
            sat, _ = client.banka_islem_liste_sayfa(sayfa, bas_tar=bas, son_tar=son)
            if not sat:
                break
            for s in sat:
                aid = _temiz(s.get("G.a_id") or s.get("a_id"))
                bid = _temiz(s.get("G.a_banka_id"))
                if not bid or not aid:
                    continue
                a = agg[bid]
                if aid in a["ids"]:
                    continue
                a["ids"].add(aid)
                a["giren"] += _d(s.get("G.a_giren"))
                a["cikan"] += _d(s.get("G.a_cikan"))
                a["adet"] += 1
            if len(sat) < 30:
                break
            sayfa += 1

    with get_session() as session:
        kurallar = list(
            session.scalars(select(BankAccountMatchRule).where(BankAccountMatchRule.aktif.is_(True)))
        )

    satirlar = []
    for k in kurallar:
        evo_id = str(k.evo_banka_id)
        e = agg.get(evo_id, {})
        evo_net = e.get("giren", Decimal("0")) - e.get("cikan", Decimal("0"))
        evo_adet = int(e.get("adet") or 0)
        hid = k.finans_hesap_id or BankAccountMatchingService.mevduat_hesap_id(
            k.banka_karti_id, "MEVDUAT"
        )
        yerel = Decimal("0")
        acilis = Decimal("0")
        if hid:
            h = FinansService.hesap_getir(hid)
            if h:
                yerel = FinansService.bakiye(h)
                acilis = Decimal(str(h.acilis_bakiyesi or 0))
        fark = yerel - evo_net
        satirlar.append(
            {
                "evo_id": evo_id,
                "ad": (k.evo_banka_adi or "")[:50],
                "evo_adet": evo_adet,
                "evo_net": evo_net,
                "yerel": yerel,
                "acilis": acilis,
                "fark": fark,
            }
        )

    satirlar.sort(key=lambda x: abs(x["fark"]), reverse=True)
    denk = sum(1 for s in satirlar if abs(s["fark"]) < Decimal("0.05"))
    out = Path("entegrasyon/_banka_bakiye_sonra.txt")
    with out.open("w", encoding="utf-8") as f:
        f.write("evo_id|ad|evo_adet|evo_net|yerel_mevduat|acilis|fark(yerel-evo)\n")
        for s in satirlar:
            f.write(
                f"{s['evo_id']}|{s['ad']}|{s['evo_adet']}|{s['evo_net']}|"
                f"{s['yerel']}|{s['acilis']}|{s['fark']}\n"
            )
        f.write(f"\nDENK={denk}/{len(satirlar)}\n")
        f.write(f"TOPLAM_EVO_NET={sum((s['evo_net'] for s in satirlar), Decimal(0))}\n")
        f.write(f"TOPLAM_YEREL={sum((s['yerel'] for s in satirlar), Decimal(0))}\n")
        f.write(f"TOPLAM_FARK={sum((s['fark'] for s in satirlar), Decimal(0))}\n")

    print(f"\nDENK (fark<0.05): {denk}/{len(satirlar)}", flush=True)
    print(
        f"TOPLAM evo_net={sum((s['evo_net'] for s in satirlar), Decimal(0))} "
        f"yerel={sum((s['yerel'] for s in satirlar), Decimal(0))} "
        f"fark={sum((s['fark'] for s in satirlar), Decimal(0))}",
        flush=True,
    )
    print("\n--- Farklar (yerel − Evo net giren−çıkan) ---", flush=True)
    for s in satirlar:
        durum = "DENK" if abs(s["fark"]) < Decimal("0.05") else "FARK"
        print(
            f"{durum} Evo#{s['evo_id']:>5} fark={s['fark']:>14} "
            f"evo={s['evo_net']:>14} yerel={s['yerel']:>14} n={s['evo_adet']:>4} {s['ad']}",
            flush=True,
        )
    print(f"\nDetay: {out}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
