"""Stok uyarıları performans ölçümü — gerçek firma DB'sinin GEÇİCİ KOPYASI üzerinde.

Gerçek dosya yalnızca okunur (SQLite backup API ile TEMP'e kopyalanır); ölçüm bitince kopya silinir.
Ölçülenler: ilk tarama (toplu_degerlendir), tekrar tarama (mükerrer kayıt olmamalı), listele (30/90 gün),
aktif sayısı, tek ürün–depo yeniden değerlendirme (belge kaydına eklenen gecikme).

Kullanım: .venv\\Scripts\\python.exe tools\\stok_uyari_performans.py [--db YOL]
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import sqlite3
import sys
import tempfile
import time
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

VARSAYILAN_DB = Path(os.environ.get("LOCALAPPDATA", "")) / "MuhasebeProgrami" / "data" / "muhasebe.db"
SONUC = ROOT / "inceleme" / "stoklar" / "stok_uyari_performans.json"


def _kopyala(kaynak: Path, hedef: Path) -> None:
    src = sqlite3.connect(f"file:{kaynak.as_posix()}?mode=ro", uri=True)
    dst = sqlite3.connect(str(hedef))
    try:
        src.backup(dst)
    finally:
        dst.close()
        src.close()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default=str(VARSAYILAN_DB))
    args = ap.parse_args()
    kaynak = Path(args.db)
    if not kaynak.is_file():
        print(f"Veritabanı yok: {kaynak}")
        return 2
    gecici = Path(tempfile.mkdtemp(prefix="cin_stok_uyari_perf_"))
    os.environ["MUHASEBE_DB_DIR"] = str(gecici)
    kopya = gecici / "firma.db"
    _kopyala(kaynak, kopya)

    from sqlalchemy import create_engine, event, func, select
    from sqlalchemy.orm import sessionmaker

    from database.database import Base, _aktif_engine_bagla, cari_kart_schemasini_guncelle, company_db, get_session
    from database.models.donem import Donem
    from database.session_manager import oturum
    from tests.stok_test_ortami import _modelleri_yukle, _pragma

    sonuc: dict = {"kaynak": str(kaynak), "kopya": "TEMP (ölçüm sonunda silindi)",
                   "tarih": datetime.now().isoformat(timespec="seconds")}
    engine = create_engine(f"sqlite:///{kopya.as_posix()}", connect_args={"check_same_thread": False})
    event.listen(engine, "connect", _pragma)
    try:
        _modelleri_yukle()
        Base.metadata.create_all(engine)
        Session = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)
        _aktif_engine_bagla(engine)
        company_db._engine = engine
        company_db._session_factory = Session
        company_db._company_id = 1
        company_db._db_path = kopya
        cari_kart_schemasini_guncelle()
        oturum.clear()
        oturum.set_user(user_id=1, kullanici_adi="perf", ad_soyad="Performans", role_kod="YONETICI",
                        role_ad="Yönetici", permissions=set())
        oturum.set_company(company_id=1, firma_kodu="PERF", firma_unvan="Perf", firma_uid="perf", db_path=str(kopya))
        with get_session() as s:
            d = s.scalar(select(Donem).where(Donem.aktif.is_(True)).limit(1)) or s.scalar(select(Donem).limit(1))
            if d is not None:
                oturum.set_period(d.id, d.donem_adi)

        import database.stok_service  # noqa: F401  (kancaları kaydeder)
        from database.models.stok import StokKarti
        from database.models.stok_uyari import StokIhtiyac
        from database.stok_uyari_service import StokUyariService

        with get_session() as s:
            sonuc["aktif_kart"] = s.scalar(select(func.count(StokKarti.id)).where(StokKarti.aktif.is_(True)))
            sonuc["cift"] = len(StokUyariService.tarama_ciftleri(s))

        adimlar = []
        t = time.perf_counter()
        ilk = StokUyariService.toplu_degerlendir(lambda i, n: adimlar.append((i, round(time.perf_counter() - t, 2))),
                                                 ilk_tarama=True)
        sonuc["ilk_tarama"] = {**ilk, "sure_sn": round(time.perf_counter() - t, 2), "parca_ilerleme": adimlar[:50]}
        t = time.perf_counter()
        tekrar = StokUyariService.toplu_degerlendir()
        sonuc["tekrar_tarama"] = {**tekrar, "sure_sn": round(time.perf_counter() - t, 2)}
        with get_session() as s:
            sonuc["etkin_kayit"] = s.scalar(select(func.count(StokIhtiyac.id)).where(StokIhtiyac.aktif.is_(True)))
            sonuc["toplam_kayit"] = s.scalar(select(func.count(StokIhtiyac.id)))
            ornek = s.scalar(select(StokIhtiyac).where(StokIhtiyac.aktif.is_(True)).limit(1))
            cift = (ornek.stok_id, ornek.depo_id) if ornek else None
        for gun in (30, 90):
            t = time.perf_counter()
            liste = StokUyariService.listele({"donem_gun": gun})
            sonuc[f"listele_{gun}g"] = {"satir": len(liste["satirlar"]), "sure_sn": round(time.perf_counter() - t, 2)}
        t = time.perf_counter()
        sonuc["aktif_sayisi"] = StokUyariService.aktif_sayisi()
        sonuc["aktif_sayisi_sure_sn"] = round(time.perf_counter() - t, 3)
        if cift:
            sureler = []
            for _ in range(5):
                with get_session() as s:
                    s.info["_stok_uyari_calisiyor"] = True
                    t = time.perf_counter()
                    StokUyariService.yeniden_degerlendir(s, [cift])
                    sureler.append(round((time.perf_counter() - t) * 1000, 1))
            sonuc["tek_cift_degerlendirme_ms"] = sureler
        sonuc["nedenler"] = {}
        for satir in liste["satirlar"]:
            for n in satir["nedenler"]:
                sonuc["nedenler"][n] = sonuc["nedenler"].get(n, 0) + 1
    finally:
        try:
            company_db.close()
        except Exception:  # noqa: BLE001
            pass
        company_db._engine = None
        engine.dispose()
        shutil.rmtree(gecici, ignore_errors=True)
    SONUC.parent.mkdir(parents=True, exist_ok=True)
    SONUC.write_text(json.dumps(sonuc, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    print(json.dumps({k: v for k, v in sonuc.items() if k != "ilk_tarama"}, ensure_ascii=False, indent=1, default=str))
    print("ilk_tarama:", {k: v for k, v in sonuc["ilk_tarama"].items() if k != "parca_ilerleme"})
    print("Sonuç:", SONUC)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
