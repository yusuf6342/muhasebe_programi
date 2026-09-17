"""Yanlış hesaba düşen EVB-BN-* banka hareketlerini doğru MEVDUAT'a taşı.

Evo listeden a_id → a_banka_id haritası çıkarır; BankAccountMatchRule ile
hedef MEVDUAT hesabına UPDATE eder.
"""

from __future__ import annotations

import sys
from collections import Counter, defaultdict
from datetime import date
from decimal import Decimal

from sqlalchemy import select, update

from database.database import get_session, sistem_altyapisini_baslat
from database.models.finans import BankAccountMatchRule, FinansHareketi, FinansHesabi
from database.session_manager import oturum
from entegrasyon.banka_eslestirme import BankAccountMatchingService
from entegrasyon.evb_import_common import _temiz
from entegrasyon.evobulut_client import EvobulutClient, load_credentials


def _aid_banka_haritasi(client: EvobulutClient) -> dict[str, str]:
    harita: dict[str, str] = {}
    bugun = date.today()
    for yil in range(2015, bugun.year + 1):
        bas = f"01.01.{yil}"
        son = bugun.strftime("%d.%m.%Y") if yil == bugun.year else f"31.12.{yil}"
        print(f"  Evo liste {yil}…", flush=True)
        sayfa = 0
        while sayfa < 500:
            sat, _ = client.banka_islem_liste_sayfa(sayfa, bas_tar=bas, son_tar=son)
            if not sat:
                break
            for s in sat:
                aid = _temiz(s.get("G.a_id") or s.get("a_id"))
                bid = _temiz(s.get("G.a_banka_id") or s.get("a_banka_id"))
                if aid and bid:
                    harita[aid] = bid
            if len(sat) < 30:
                break
            sayfa += 1
    return harita


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

    print("Evo a_id → banka haritası…", flush=True)
    client = EvobulutClient(load_credentials())
    client.login()
    aid_banka = _aid_banka_haritasi(client)
    print(f"Harita: {len(aid_banka)} işlem", flush=True)

    # evo_banka_id → MEVDUAT hesap_id
    hedef: dict[str, int] = {}
    with get_session() as session:
        for k in session.scalars(select(BankAccountMatchRule).where(BankAccountMatchRule.aktif.is_(True))):
            hid = k.finans_hesap_id or BankAccountMatchingService.mevduat_hesap_id(
                k.banka_karti_id, "MEVDUAT"
            )
            if hid:
                hedef[str(k.evo_banka_id)] = int(hid)

    print(f"Eşleşmiş hedef hesap: {len(hedef)}", flush=True)

    tasinan = 0
    zaten_dogru = 0
    banka_yok = 0
    hedef_yok = 0
    belge_bozuk = 0
    by_banka = Counter()

    with get_session() as session:
        hareketler = list(
            session.scalars(
                select(FinansHareketi).where(FinansHareketi.belge_no.like("EVB-BN-%"))
            )
        )
        print(f"Yerel EVB-BN: {len(hareketler)}", flush=True)

        for h in hareketler:
            belge = (h.belge_no or "").strip()
            if not belge.startswith("EVB-BN-"):
                belge_bozuk += 1
                continue
            aid = belge[len("EVB-BN-") :].strip()
            if not aid:
                belge_bozuk += 1
                continue
            bid = aid_banka.get(aid)
            if not bid:
                banka_yok += 1
                continue
            yeni_hesap = hedef.get(bid)
            if not yeni_hesap:
                hedef_yok += 1
                continue
            by_banka[bid] += 1
            if int(h.hesap_id) == int(yeni_hesap):
                zaten_dogru += 1
                continue
            h.hesap_id = int(yeni_hesap)
            tasinan += 1
        session.flush()

    print(
        f"Taşınan={tasinan} zaten_doğru={zaten_dogru} "
        f"banka_id_yok={banka_yok} hedef_yok={hedef_yok} belge_bozuk={belge_bozuk}",
        flush=True,
    )

    # Yeni kart bütünlüğü: Evo adet vs yerel EVB adet (hedef MEVDUAT)
    from sqlalchemy import func

    print("\n--- Yeni kart doluluk (Evo adet vs yerel) ---", flush=True)
    evo_adet = Counter(aid_banka.values())
    with get_session() as session:
        kurallar = list(
            session.scalars(select(BankAccountMatchRule).where(BankAccountMatchRule.aktif.is_(True)))
        )
        eksik_kart = 0
        for k in sorted(kurallar, key=lambda x: str(x.evo_banka_id)):
            hid = hedef.get(str(k.evo_banka_id))
            evo_n = evo_adet.get(str(k.evo_banka_id), 0)
            yerel_n = 0
            if hid:
                yerel_n = (
                    session.scalar(
                        select(func.count())
                        .select_from(FinansHareketi)
                        .where(
                            FinansHareketi.hesap_id == hid,
                            FinansHareketi.belge_no.like("EVB-BN-%"),
                        )
                    )
                    or 0
                )
            fark = int(evo_n) - int(yerel_n)
            ok = "OK" if fark == 0 else f"eksik={fark}"
            if fark != 0:
                eksik_kart += 1
            ad = (k.evo_banka_adi or "")[:45]
            print(
                f"  Evo#{k.evo_banka_id:>5} evo={evo_n:>5} yerel={yerel_n:>5} {ok}  {ad}",
                flush=True,
            )
        print(f"\nTam dolu kart: {len(kurallar) - eksik_kart}/{len(kurallar)}", flush=True)

        kalan = (
            session.scalar(
                select(func.count())
                .select_from(FinansHareketi)
                .where(
                    FinansHareketi.hesap_id == 5,
                    FinansHareketi.belge_no.like("EVB-BN-%"),
                )
            )
            or 0
        )
        print(f"Eski AKBANK KMH (hesap 5) kalan EVB-BN: {kalan}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
