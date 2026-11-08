"""D2 gerçek bakiye aktarımı (evo_devir → PG D2 hedef).

Kesim: 07.11.2026 gün sonu bakiyeleri açılış olarak yazılır.
49 pasif stok: kaynak_stok_id engeli. Mükerrer: ImportBatch haritası.

  .venv\\Scripts\\python.exe -m tools.dnm_d2.d2_gercek_aktar onizle
  .venv\\Scripts\\python.exe -m tools.dnm_d2.d2_gercek_aktar aktar
  .venv\\Scripts\\python.exe -m tools.dnm_d2.d2_gercek_aktar mutabakat
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

from tools.dnm_d2.donem_sabitleri import CALISMA_KOK

KOK = Path(__file__).resolve().parents[2]
CALISMA = KOK / CALISMA_KOK
KAYNAK = CALISMA / "kaynak"
DEVIR = "07.11.2026"


def _son_dosya(onek: str) -> Path:
    adaylar = sorted(KAYNAK.glob(f"{onek}*.json"), key=lambda p: p.stat().st_mtime, reverse=True)
    if not adaylar:
        raise SystemExit(f"Kaynak yok: {KAYNAK / (onek + '*.json')}")
    return adaylar[0]


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("komut", choices=("onizle", "aktar", "mutabakat"))
    a = p.parse_args()

    sys.stdout.reconfigure(encoding="utf-8")

    anlik = _son_dosya("evo_anlik_")
    bakiye = _son_dosya("evo_guncel_bakiye_")
    # Hareketler boşsa yenile (stokjq sonrası ws boş kalabiliyor)
    ham = json.loads(anlik.read_text(encoding="utf-8-sig"))
    if not ham.get("kasa_hareketleri") or not ham.get("banka_hareketleri"):
        from tools.dnm_d2 import d2_anlik_hareket_yenile as hy

        sys.argv = ["d2_anlik_hareket_yenile", str(anlik)]
        if hy.main() != 0:
            return 2
    else:
        from tools.dnm_d2 import d2_anlik_finans_tamamla as ft

        sys.argv = ["d2_anlik_finans_tamamla", str(anlik)]
        if ft.main() != 0:
            return 2

    from types import SimpleNamespace

    from entegrasyon.evo_devir import aktarim as ev

    bilgi = {
        "kod": "DNM_D2",
        "unvan": "DNM – RAY MOBİLYA AKSESUARLAR ETÜD (D2)",
        "yol": "pg:cin_firma_dnm_d2_20260901",
    }
    if a.komut != "onizle":
        from tools.dnm_d2.d2_baglanti_gecis import d2_yap
        from tools.dnm_d2.d2_pg_oturum import d2_pg_oturum_ac

        print(json.dumps(d2_yap(), ensure_ascii=False), flush=True)
        bilgi = d2_pg_oturum_ac()
        print(f"Firma: {bilgi['unvan']} ({bilgi['kod']}) {bilgi['yol']}", flush=True)

    args = SimpleNamespace(
        anlik=str(anlik),
        bakiye=str(bakiye),
        devir=DEVIR,
        batch=None,
        veri=None,
        unvan=bilgi["unvan"],
        rapor=None,
    )

    if a.komut == "onizle":
        sonuc = ev.onizle(args)
    elif a.komut == "aktar":
        sonuc = ev.aktar(args)
    else:
        sonuc = ev.mutabakat(args)

    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    rapor_yol = CALISMA / "rapor" / f"D2_{a.komut.upper()}_{stamp}.json"
    rapor_yol.parent.mkdir(parents=True, exist_ok=True)
    metin = json.dumps(sonuc, ensure_ascii=False, indent=1, default=str)
    rapor_yol.write_text(metin, encoding="utf-8")
    ozet = {
        "zaman": datetime.now().astimezone().isoformat(timespec="seconds"),
        "komut": a.komut,
        "devir": DEVIR,
        "anlik": anlik.name,
        "bakiye": bakiye.name,
        "rapor": str(rapor_yol.relative_to(KOK)).replace("\\", "/"),
        "firma": bilgi["kod"],
        "hedef": bilgi["yol"],
        "mali_yazim": a.komut == "aktar",
    }
    if isinstance(sonuc, dict):
        for k in ("batch", "durum", "satir", "sure_sn"):
            if k in sonuc:
                ozet[k] = sonuc[k]
    (CALISMA / f"D2_GERCEK_{a.komut.upper()}_OZET.json").write_text(
        json.dumps(ozet, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(metin[:4000])
    if len(metin) > 4000:
        print(f"... (tam rapor: {rapor_yol})")
    print(json.dumps(ozet, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
