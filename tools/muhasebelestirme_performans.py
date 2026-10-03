"""Otomatik / sonradan muhasebeleştirme süre ölçümü (geçici veritabanında; gerçek veriye dokunmaz).

Ölçülenler:
- Satış faturası onayı (kesinleşme) süresi: otomatik vs sonradan
- Alış faturası kaydı süresi: otomatik vs sonradan
- Bekleyen evrakların toplu muhasebeleştirme süresi

Kullanım: python tools/muhasebelestirme_performans.py [adet]
"""

from __future__ import annotations

import os
import statistics
import sys
import tempfile
import time
from decimal import Decimal
from pathlib import Path

KOK = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(KOK))
sys.path.insert(0, str(KOK / "tests"))
os.environ.setdefault("MUHASEBE_DB_DIR", tempfile.mkdtemp(prefix="cin_perf_"))

import test_muhasebelestirme_ayarlari as tma  # noqa: E402


def _ozet(ad: str, sureler: list[float]) -> str:
    ms = [s * 1000 for s in sureler]
    return (f"{ad}: adet={len(ms)} ort={statistics.mean(ms):.1f} ms medyan={statistics.median(ms):.1f} ms "
            f"min={min(ms):.1f} maks={max(ms):.1f}")


def main() -> int:
    adet = int(sys.argv[1]) if len(sys.argv) > 1 else 30
    t = tma.MuhasebelestirmeAyarlariTest("test_gecis_eslesmeli_firma_otomatik_kalir")
    t.setUp()
    try:
        from database.alis_faturasi_service import AlisFaturasiService
        from database.satis_faturasi_service import SatisFaturasiService

        def alis(lot):
            bas = time.perf_counter()
            AlisFaturasiService.kaydet(
                {"fatura_tarihi": tma.tmd.TARIH_ALIS, "vade_tarihi": tma.tmd.TARIH_ALIS, "cari_id": t.tedarikci_id,
                 "depo": "ANA DEPO", "odeme_tutari": Decimal("0")},
                [{"urun_kodu": "U001", "urun_adi": "U001", "miktar": Decimal("100"), "birim": "Adet",
                  "birim_fiyat": Decimal("100"), "iskonto_orani": Decimal("0"), "kdv_orani": Decimal("20"),
                  "lot_no": lot}],
            )
            return time.perf_counter() - bas

        def satis_onay():
            sid = t._taslak_satis("1")
            bas = time.perf_counter()
            SatisFaturasiService.onayla(sid)
            return time.perf_counter() - bas

        sonuc = {}
        alis("ISINMA")
        satis_onay()  # ısınma (önbellek / ilk geçiş)
        for yontem in ("otomatik", "sonradan"):
            t._ayar(yontem)
            sonuc[f"alis_{yontem}"] = [alis(f"L-{yontem}-{i}") for i in range(adet)]
            sonuc[f"satis_{yontem}"] = [satis_onay() for _ in range(adet)]
        bekleyen = t._servis().listele(durumlar=("Bekliyor",))
        bas = time.perf_counter()
        r = t._servis().muhasebelestir([b["id"] for b in bekleyen])
        toplu = time.perf_counter() - bas

        print(f"Ölçüm: {time.strftime('%Y-%m-%d %H:%M:%S')}  (geçici DB, evrak başına 1 satır)")
        for ad, sureler in sonuc.items():
            print(_ozet(ad, sureler))
        print(f"Toplu muhasebeleştirme: {len(bekleyen)} evrak, {toplu:.2f} s "
              f"({toplu / max(len(bekleyen), 1) * 1000:.1f} ms/evrak) — başarılı {r['basarili']}, "
              f"başarısız {r['basarisiz']}, atlanan {r['atlanan']}")
    finally:
        t.tearDown()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
