"""Gerçek verinin KOPYASINDA salt-okunur tarama (gerçek veritabanına yazmaz).

- Açılış geçişi gerekli mi (eksik tablo/kolon listesi)
- Hesap eşleştirmelerinin fişe uygunluğu (ana/üst, pasif, alt hesabı olan hesaplar)
- Geçmiş finans evrakları: kesin / belirsiz / karar bekliyor / muhasebeleştirilmiş / listede

    python tools/muhasebelestirme_eksik_tarama.py --veri "%LOCALAPPDATA%\\MuhasebeProgrami\\data" --cikti rapor.json
"""

from __future__ import annotations

import argparse
import importlib
import json
import os
import pkgutil
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))

from muhasebelestirme_gecis_deneme import kopyala  # noqa: E402


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--veri", required=True, type=Path)
    p.add_argument("--cikti", required=True, type=Path)
    p.add_argument("--firma", type=int, default=1)
    p.add_argument("--kullanici", type=int, default=1)
    a = p.parse_args()
    veri = a.veri.expanduser().resolve()
    kopya = Path(tempfile.mkdtemp(prefix="cin_eksik_tarama_"))
    for ad in ("muhasebe.db", "system.db"):
        kopyala(veri / ad, kopya / ad)

    os.environ["MUHASEBE_DB_DIR"] = str(kopya)
    import database.models as modeller

    for m in pkgutil.iter_modules(modeller.__path__):
        importlib.import_module(f"database.models.{m.name}")
    from sqlalchemy import create_engine

    from database.database import Base
    from database.gecis_guvenligi import sema_eksikleri

    ham = create_engine(f"sqlite:///{(kopya / 'muhasebe.db').as_posix()}")
    rapor: dict = {"kopya": str(kopya), "sema_eksikleri": sema_eksikleri(ham, Base.metadata)}
    ham.dispose()

    from hesap_bakiye_duzelt import oturum_ac

    oturum_ac(kopya, a.firma, a.kullanici)

    from database.muhasebe_entegrasyon import HesapEslemeService
    from database.muhasebelestirme_gecmis_finans import ozet
    from database.muhasebelestirme_service import MuhasebelestirmeService

    rapor["muhasebelestirme_gecisi_gerekli"] = MuhasebelestirmeService.gecis_gerekli_mi()
    bas = time.perf_counter()
    MuhasebelestirmeService.schema_hazirla()  # yalnız kopyada
    rapor["kopyada_gecis_sn"] = round(time.perf_counter() - bas, 2)

    uygunluk = HesapEslemeService.uygunluk_raporu()
    rapor["eslesme_uygunlugu"] = {
        "uygun": [r for r in uygunluk if r["durum"] == "uygun"],
        "uygunsuz": [r for r in uygunluk if r["durum"] == "uygunsuz"],
        "eksik_sayisi": sum(1 for r in uygunluk if r["durum"] == "eksik"),
    }

    bas = time.perf_counter()
    oniz = MuhasebelestirmeService.gecmis_finans_onizle()
    rapor["gecmis_onizleme_sn"] = round(time.perf_counter() - bas, 2)
    rapor["gecmis_ozet"] = ozet(oniz)
    rapor["gecmis_ornekler"] = {
        e: {k: [{x: str(v) for x, v in r.items()} for r in liste[:4]] for k, liste in kat.items() if liste}
        for e, kat in oniz.items()
    }
    nedenler: dict = {}
    for e, kat in oniz.items():
        for k in ("belirsiz", "karar_bekliyor"):
            for r in kat[k]:
                anahtar = f"{e}|{k}|{(r['neden'] or '')[:90]}"
                nedenler[anahtar] = nedenler.get(anahtar, 0) + 1
    rapor["neden_dagilimi"] = nedenler
    a.cikti.parent.mkdir(parents=True, exist_ok=True)
    a.cikti.write_text(json.dumps(rapor, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
    print(f"Yazıldı: {a.cikti}")


if __name__ == "__main__":
    main()
