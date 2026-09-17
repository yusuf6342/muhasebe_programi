"""EvoBulut vs Cin Muhasebe banka bakiyesi karşılaştırması."""

from __future__ import annotations

import sys
from collections import defaultdict
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path

from sqlalchemy import select

from database.database import get_session, sistem_altyapisini_baslat
from database.finans_service import FinansService
from database.models.finans import BankAccountMatchRule, BankaKarti, FinansHareketi
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


def _parse_tar(s: str) -> date | None:
    s = _temiz(s)
    if not s:
        return None
    for fmt in ("%d.%m.%Y %H:%M:%S", "%d.%m.%Y"):
        try:
            return datetime.strptime(s[:19] if len(s) > 10 else s, fmt).date()
        except ValueError:
            continue
    return None


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
    kartlar = {str(x.get("id")): _temiz(x.get("text")) for x in client.banka_kart_listesi()}
    print(f"Evo kart: {len(kartlar)}", flush=True)

    agg: dict[str, dict] = defaultdict(
        lambda: {
            "giren": Decimal("0"),
            "cikan": Decimal("0"),
            "adet": 0,
            "son_key": None,
            "son_bak": None,
        }
    )

    bugun = date.today()
    for yil in range(2015, bugun.year + 1):
        bas = f"01.01.{yil}"
        son = bugun.strftime("%d.%m.%Y") if yil == bugun.year else f"31.12.{yil}"
        print(f"Evo hareket çekiliyor {yil}…", flush=True)
        sayfa = 0
        while sayfa < 500:
            sat, _adet = client.banka_islem_liste_sayfa(sayfa, bas_tar=bas, son_tar=son)
            if not sat:
                break
            for s in sat:
                bid = _temiz(s.get("G.a_banka_id"))
                if not bid:
                    continue
                a = agg[bid]
                a["giren"] += _d(s.get("G.a_giren"))
                a["cikan"] += _d(s.get("G.a_cikan"))
                a["adet"] += 1
                tar = _parse_tar(s.get("G.a_tarih") or "")
                aid = int(_temiz(s.get("G.a_id")) or "0")
                key = (tar or date.min, aid)
                bak = _d(s.get("R.bakiye"))
                tur = _temiz(s.get("R.bakiye_tur")).upper()
                son_bak = -bak if tur == "A" else bak
                if a["son_key"] is None or key >= a["son_key"]:
                    a["son_key"] = key
                    a["son_bak"] = son_bak
            if len(sat) < 30:
                break
            sayfa += 1

    with get_session() as session:
        kurallar = list(
            session.scalars(select(BankAccountMatchRule).where(BankAccountMatchRule.aktif.is_(True)))
        )
        kart_map = {
            k.id: k for k in session.scalars(select(BankaKarti)).all()
        }

    satirlar = []
    for k in kurallar:
        evo_id = k.evo_banka_id
        e = agg.get(evo_id, {})
        evo_net = e.get("giren", Decimal("0")) - e.get("cikan", Decimal("0"))
        evo_son = e.get("son_bak")
        evo_ref = Decimal(str(evo_son)) if evo_son is not None else evo_net

        hesap_id = k.finans_hesap_id or BankAccountMatchingService.mevduat_hesap_id(
            k.banka_karti_id, "MEVDUAT"
        )
        yerel = Decimal("0")
        acilis = Decimal("0")
        evb_adet = 0
        evb_net = Decimal("0")
        if hesap_id:
            h = FinansService.hesap_getir(hesap_id)
            if h:
                yerel = FinansService.bakiye(h)
                acilis = Decimal(str(h.acilis_bakiyesi or 0))
            with get_session() as session:
                hs = list(
                    session.scalars(
                        select(FinansHareketi).where(
                            FinansHareketi.hesap_id == hesap_id,
                            FinansHareketi.belge_no.like("EVB-BN-%"),
                        )
                    )
                )
            for hh in hs:
                evb_adet += 1
                t = Decimal(str(hh.tutar or 0))
                tur = (hh.hareket_turu or "").upper()
                if "ÇIKIŞ" in (hh.hareket_turu or "") or "CIKIS" in tur:
                    evb_net -= t
                else:
                    evb_net += t

        kart = kart_map.get(k.banka_karti_id)
        yerel_tum = yerel
        if kart is not None:
            try:
                yerel_tum = sum(FinansService.banka_bakiyeler(kart).values(), Decimal("0"))
            except Exception:
                yerel_tum = yerel

        fark_son = yerel - evo_ref
        fark_net = yerel - evo_net
        satirlar.append(
            {
                "evo_id": evo_id,
                "ad": (k.evo_banka_adi or kartlar.get(evo_id, "") or "")[:55],
                "evo_adet": int(e.get("adet") or 0),
                "evo_net": evo_net,
                "evo_son": evo_ref,
                "yerel": yerel,
                "yerel_tum": yerel_tum,
                "acilis": acilis,
                "evb_adet": evb_adet,
                "evb_net": evb_net,
                "fark_son": fark_son,
                "fark_net": fark_net,
                "fark_aktarim": yerel - evb_net - acilis,
            }
        )

    satirlar.sort(key=lambda x: abs(x["fark_son"]), reverse=True)
    out = Path("entegrasyon/_banka_bakiye_karsilastirma.txt")
    denk_son = sum(1 for s in satirlar if abs(s["fark_son"]) < Decimal("0.05"))
    denk_net = sum(1 for s in satirlar if abs(s["fark_net"]) < Decimal("0.05"))
    with out.open("w", encoding="utf-8") as f:
        f.write(
            "evo_id|ad|evo_adet|evo_son_bakiye|evo_net(giren-cikan)|yerel_mevduat|"
            "fark_vs_son|fark_vs_net|evb_adet|evb_net|acilis\n"
        )
        for s in satirlar:
            f.write(
                f"{s['evo_id']}|{s['ad']}|{s['evo_adet']}|{s['evo_son']}|{s['evo_net']}|"
                f"{s['yerel']}|{s['fark_son']}|{s['fark_net']}|{s['evb_adet']}|{s['evb_net']}|{s['acilis']}\n"
            )
        f.write(f"\nDENK_vs_son_bakiye={denk_son}/{len(satirlar)}\n")
        f.write(f"DENK_vs_net_hareket={denk_net}/{len(satirlar)}\n")
        f.write(f"TOPLAM_EVO_SON={sum((s['evo_son'] for s in satirlar), Decimal(0))}\n")
        f.write(f"TOPLAM_EVO_NET={sum((s['evo_net'] for s in satirlar), Decimal(0))}\n")
        f.write(f"TOPLAM_YEREL={sum((s['yerel'] for s in satirlar), Decimal(0))}\n")
        f.write(f"TOPLAM_FARK_SON={sum((s['fark_son'] for s in satirlar), Decimal(0))}\n")

    print(f"yazildi {out}", flush=True)
    print(f"DENK son-bakiye: {denk_son}/{len(satirlar)} | DENK net: {denk_net}/{len(satirlar)}", flush=True)
    print(
        f"TOPLAM evo_son={sum((s['evo_son'] for s in satirlar), Decimal(0))} "
        f"yerel={sum((s['yerel'] for s in satirlar), Decimal(0))} "
        f"fark={sum((s['fark_son'] for s in satirlar), Decimal(0))}",
        flush=True,
    )
    print("--- en büyük farklar (yerel - evo_son) ---", flush=True)
    for s in satirlar[:15]:
        print(
            f"{s['evo_id']:>6} fark_son={s['fark_son']:>14} "
            f"evo_son={s['evo_son']:>14} evo_net={s['evo_net']:>14} "
            f"yerel={s['yerel']:>14} evo_n={s['evo_adet']} evb_n={s['evb_adet']} {s['ad']}",
            flush=True,
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
