"""İzole kabul test DB kopyaları oluştur (cin_*_deneme üzerine yazmaz).

Hedef adlar:
  cin_sistem_kabul_20261105
  cin_firma_kabul_20261105

RAY001 db_path kopyada yalnız firma kabul DB'sine yönlendirilir.
"""
from __future__ import annotations

import json
import sys
from datetime import datetime
from pathlib import Path
from urllib.parse import quote_plus

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from database.baglanti_modu import (  # noqa: E402
    BaglantiAyari,
    CalismaKipi,
    PostgresBaglanti,
    ayari_kaydet,
    postgres_parola_al,
)
from sqlalchemy import create_engine, text  # noqa: E402

HOST = "192.168.1.114"
PORT = 5432
USER = "cin_app"
SSL = "require"
SRC_SYS = "cin_sistem_deneme"
SRC_FR = "cin_firma_deneme"
DST_SYS = "cin_sistem_kabul_20261105"
DST_FR = "cin_firma_kabul_20261105"
STAMP = "20261105"


def _url(db: str) -> str:
    pwd = quote_plus(postgres_parola_al())
    return f"postgresql+psycopg://{USER}:{pwd}@{HOST}:{PORT}/{db}?sslmode={SSL}"


def _exists(dbname: str) -> bool:
    eng = create_engine(_url(SRC_SYS), isolation_level="AUTOCOMMIT", connect_args={"connect_timeout": 8})
    try:
        with eng.connect() as c:
            n = c.execute(
                text("SELECT 1 FROM pg_database WHERE datname = :d"),
                {"d": dbname},
            ).scalar()
            return bool(n)
    finally:
        eng.dispose()


def _clone(src: str, dst: str) -> dict:
    """TEMPLATE ile kopyala. Önce hedef yok olmalı; varsa atlanır."""
    if _exists(dst):
        return {"db": dst, "durum": "zaten_var", "kaynak": src}
    eng = create_engine(_url(SRC_SYS), isolation_level="AUTOCOMMIT", connect_args={"connect_timeout": 15})
    try:
        with eng.connect() as c:
            # Bağlantıları kes (template için)
            c.execute(
                text(
                    "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
                    "WHERE datname = :d AND pid <> pg_backend_pid()"
                ),
                {"d": src},
            )
            c.execute(text(f'CREATE DATABASE "{dst}" TEMPLATE "{src}" OWNER {USER}'))
        return {"db": dst, "durum": "olusturuldu", "kaynak": src}
    finally:
        eng.dispose()


def _ray_yonlendir() -> dict:
    eng = create_engine(_url(DST_SYS), connect_args={"connect_timeout": 8})
    try:
        with eng.begin() as c:
            before = c.execute(
                text(
                    "SELECT id, firma_kodu, db_path, aktif FROM companies ORDER BY id"
                )
            ).mappings().all()
            c.execute(
                text(
                    "UPDATE companies SET db_path = :p WHERE firma_kodu = 'RAY001'"
                ),
                {"p": f"pg:{DST_FR}"},
            )
            # Diğerleri kilitli kalsın
            c.execute(
                text(
                    "UPDATE companies SET aktif = false "
                    "WHERE firma_kodu <> 'RAY001'"
                )
            )
            after = c.execute(
                text(
                    "SELECT id, firma_kodu, db_path, aktif FROM companies ORDER BY id"
                )
            ).mappings().all()
        return {
            "before": [dict(r) for r in before],
            "after": [dict(r) for r in after],
        }
    finally:
        eng.dispose()


def _profil_yaz() -> dict:
    """İzole DENEME profil klasörü + baglanti_ayari.json (günlük ayarı değiştirmez)."""
    profil = Path(os_local_appdata()) / f"CinMuhasebeKabulDeneme_{STAMP}"
    program = profil / "program"
    data = profil / "data"
    program.mkdir(parents=True, exist_ok=True)
    data.mkdir(parents=True, exist_ok=True)

    ayar = BaglantiAyari(
        kipi=CalismaKipi.YEREL_AG_POSTGRES.value,
        postgres=PostgresBaglanti(
            host=HOST,
            port=PORT,
            sistem_db=DST_SYS,
            kullanici=USER,
            sslmode=SSL,
            ortam="DENEME",
            firma_db=DST_FR,
            terminal_kimligi=f"KABUL-{STAMP}",
        ),
    )
    yol = ayari_kaydet(ayar, program_dir=program)
    # veri_konumu — SQLite fallback kullanılmasın diye boş izole data
    (program / "veri_konumu.txt").write_text(str(data) + "\n", encoding="utf-8")
    # DENEME işaret dosyası
    (program / "DENEME_ORTAMI.txt").write_text(
        f"KABUL DENEME {STAMP}\n{DST_SYS} / {DST_FR}\n{datetime.now().isoformat()}\n",
        encoding="utf-8",
    )
    return {"profil": str(profil), "baglanti_ayari": str(yol), "data": str(data)}


def os_local_appdata() -> str:
    import os

    return os.environ.get("LOCALAPPDATA") or str(Path.home() / "AppData" / "Local")


def main() -> int:
    out: dict = {
        "zaman": datetime.now().isoformat(timespec="seconds"),
        "src": {"sistem": SRC_SYS, "firma": SRC_FR},
        "dst": {"sistem": DST_SYS, "firma": DST_FR},
    }
    # Kaynak deneme DB'lerinin hâlâ var olduğunu doğrula
    if not _exists(SRC_SYS) or not _exists(SRC_FR):
        out["hata"] = "kaynak deneme DB yok"
        print(json.dumps(out, ensure_ascii=False, indent=2))
        return 2

    out["klon_sistem"] = _clone(SRC_SYS, DST_SYS)
    out["klon_firma"] = _clone(SRC_FR, DST_FR)
    out["ray_yonlendirme"] = _ray_yonlendir()
    out["profil"] = _profil_yaz()

    # Kaynak deneme DB bozulmadı mı?
    eng = create_engine(_url(SRC_SYS), connect_args={"connect_timeout": 8})
    with eng.connect() as c:
        ray = c.execute(
            text(
                "SELECT firma_kodu, db_path, aktif FROM companies WHERE firma_kodu='RAY001'"
            )
        ).mappings().one()
        out["kaynak_deneme_ray"] = dict(ray)
    eng.dispose()

    yol = ROOT / "kurulum" / "_kabul_izolasyon.json"
    yol.write_text(json.dumps(out, ensure_ascii=False, indent=2, default=str) + "\n", encoding="utf-8")
    print(json.dumps(out, ensure_ascii=False, indent=2, default=str))
    print("YAZILDI:", yol)
    ok = (
        out["klon_sistem"]["durum"] in ("olusturuldu", "zaten_var")
        and out["klon_firma"]["durum"] in ("olusturuldu", "zaten_var")
        and out["kaynak_deneme_ray"].get("db_path") == f"pg:{SRC_FR}"
    )
    return 0 if ok else 3


if __name__ == "__main__":
    raise SystemExit(main())
