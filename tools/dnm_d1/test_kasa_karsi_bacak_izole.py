"""İzole test: kasa karşı bacak çift etki / idempotent / banka çoğalmama.

  .venv\\Scripts\\python.exe -m tools.dnm_d1.test_kasa_karsi_bacak_izole
"""

from __future__ import annotations

import copy
import json
from decimal import Decimal

from tools.dnm_d1._ortak import KAYNAK
from tools.dnm_d1.donem_sabitleri import RAPOR_ONEKI_KAYNAK
from tools.dnm_d1.kasa_banka_transfer_bacak import (
    KARSI_FLAG,
    kasa_hareketlerini_zenginlestir,
)
from tools.dnm_d1.kapanis_kasa_banka import _yon_tutar, kapanis_uret


def main() -> int:
    banka = json.loads((KAYNAK / f"{RAPOR_ONEKI_KAYNAK}BANKA.json").read_text(encoding="utf-8"))
    kasa_ham = json.loads((KAYNAK / f"{RAPOR_ONEKI_KAYNAK}KASA.json").read_text(encoding="utf-8"))

    # Ham kopya: karşı bacakları çıkar (dosya zaten zenginleşmiş olabilir)
    kasa0 = copy.deepcopy(kasa_ham)
    kasa0["hareketler"] = [h for h in kasa0["hareketler"] if not h.get(KARSI_FLAG)]
    kasa0["hareket_adet"] = len(kasa0["hareketler"])

    banka_n = len(banka["hareketler"])
    b22 = sum(1 for h in banka["hareketler"] if str(h.get("G.a_tur_id")) == "22")
    b23 = sum(1 for h in banka["hareketler"] if str(h.get("G.a_tur_id")) == "23")

    k1, o1 = kasa_hareketlerini_zenginlestir(kasa0, banka)
    k2, o2 = kasa_hareketlerini_zenginlestir(k1, banka)

    assert o2["eklenen"] == 0, "ikinci geçişte ekleme olmamalı"
    assert len(banka["hareketler"]) == banka_n, "banka çoğalmamalı"
    assert b22 == sum(1 for h in banka["hareketler"] if str(h.get("G.a_tur_id")) == "22")
    assert b23 == sum(1 for h in banka["hareketler"] if str(h.get("G.a_tur_id")) == "23")

    # Karşı bacak banka id'leri tekil
    bids = [h.get("banka_G.a_id") for h in k1["hareketler"] if h.get(KARSI_FLAG)]
    assert len(bids) == len(set(bids)), "aynı banka id iki kez kasa görünümünde"

    # NAKİT kapanış (bellekte geçici yazmadan hesap)
    # kapanis_uret dosyadan okur — dosya güncel olmalı; burada manuel net
    def net_kasa(kid: str, hareketler: list) -> tuple[Decimal, Decimal, int]:
        g = c = Decimal("0")
        n = 0
        for h in hareketler:
            if str(h.get("G.a_kasa_id")) != kid:
                continue
            gg, cc = _yon_tutar(h)
            g += gg or Decimal("0")
            c += cc or Decimal("0")
            n += 1
        return g, c, n

    g0, c0, n0 = net_kasa("1", kasa0["hareketler"])
    g1, c1, n1 = net_kasa("1", k1["hareketler"])
    assert n1 == n0 + sum(
        1
        for h in k1["hareketler"]
        if h.get(KARSI_FLAG) and str(h.get("G.a_kasa_id")) == "1"
    )
    # Çift etki yok: banka 22/23 nakit tutarları yalnız bir kez kasa netine yansır
    nakit_karsi = [h for h in k1["hareketler"] if h.get(KARSI_FLAG) and str(h.get("G.a_kasa_id")) == "1"]
    ek_g = sum((_yon_tutar(h)[0] or 0) for h in nakit_karsi)
    ek_c = sum((_yon_tutar(h)[1] or 0) for h in nakit_karsi)
    assert g1 - g0 == ek_g
    assert c1 - c0 == ek_c
    assert g1 == Decimal("3061663.09")
    assert c1 == Decimal("3059453.54")
    assert g1 - c1 == Decimal("2209.55")

    g0y, c0y, _n0y = net_kasa("2", kasa0["hareketler"])
    g1y, c1y, _n1y = net_kasa("2", k1["hareketler"])
    yc_karsi = [
        h for h in k1["hareketler"] if h.get(KARSI_FLAG) and str(h.get("G.a_kasa_id")) == "2"
    ]
    assert g1y - g0y == sum((_yon_tutar(h)[0] or 0) for h in yc_karsi)
    assert c1y - c0y == sum((_yon_tutar(h)[1] or 0) for h in yc_karsi)
    assert g1y == Decimal("1736241.5")
    assert c1y == Decimal("1733691.49")
    assert g1y - c1y == Decimal("2550.01")
    assert (g1 - c1) + (g1y - c1y) == Decimal("4759.56")
    assert len([h for h in k1["hareketler"] if h.get(KARSI_FLAG)]) == 126

    # Dosyadaki KASA_KAPANIS ile uyum (zenginleştirme sonrası)
    kap = json.loads((KAYNAK / f"{RAPOR_ONEKI_KAYNAK}KASA_KAPANIS.json").read_text(encoding="utf-8"))
    nakit = next(h for h in kap["hesaplar"] if str(h["hesap_id"]) == "1")
    yc = next(h for h in kap["hesaplar"] if str(h["hesap_id"]) == "2")
    assert Decimal(nakit["kapanis_net"]) == Decimal("2209.55")
    assert Decimal(yc["kapanis_net"]) == Decimal("2550.01")

    print(
        json.dumps(
            {
                "ok": True,
                "idempotent": True,
                "banka_degismedi": True,
                "nakit_kapanis": str(g1 - c1),
                "yc_kapanis": str(g1y - c1y),
                "toplam": str((g1 - c1) + (g1y - c1y)),
                "karsi_126": 126,
                "karsi_eklenen_birinci": o1["eklenen"],
                "karsi_eklenen_ikinci": o2["eklenen"],
                "cifte_etki_yok": True,
            },
            ensure_ascii=False,
        ),
        flush=True,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
