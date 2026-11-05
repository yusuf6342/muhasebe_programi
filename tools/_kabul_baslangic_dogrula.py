"""Kabul testleri: başlangıç durumu doğrulama (şifre yazdırılmaz)."""
from __future__ import annotations

import json
import socket
import sys
from pathlib import Path
from urllib.parse import quote_plus

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from database.baglanti_modu import postgres_parola_al  # noqa: E402
from sqlalchemy import create_engine, text  # noqa: E402

HOST = "192.168.1.114"
PORT = 5432
SISTEM = "cin_sistem_deneme"
FIRMA = "cin_firma_deneme"
USER = "cin_app"
SSL = "require"

BEK = {
    "cari_kartlar": 1098,
    "stok_kartlari": 3031,
    "satis_faturalari": 9771,
    "alis_faturalari": 1080,
    "stok_hareketleri": 31909,
    "finans_hareketleri": 9819,
    "finans_hesaplari": 169,
    "satis_siparisleri": 228,
    "satis_irsaliyeleri": 10,
}


def eng(db: str):
    pwd = quote_plus(postgres_parola_al())
    url = f"postgresql+psycopg://{USER}:{pwd}@{HOST}:{PORT}/{db}?sslmode={SSL}"
    return create_engine(url, connect_args={"connect_timeout": 8})


def main() -> int:
    out: dict = {
        "makine": socket.gethostname(),
        "ip_local": socket.gethostbyname(socket.gethostname()),
    }
    # Not: pg_hba bazı kurulumlarda 'postgres' DB'sine izin vermez; deneme DB kullan.
    es0 = eng(SISTEM)
    with es0.connect() as c:
        out["pg_user"] = c.execute(text("SELECT current_user")).scalar()
        out["inet_server"] = str(c.execute(text("SELECT inet_server_addr()")).scalar())
        out["inet_client"] = str(c.execute(text("SELECT inet_client_addr()")).scalar())
        out["server_version"] = c.execute(text("SHOW server_version")).scalar()
        try:
            dbs = [
                r[0]
                for r in c.execute(
                    text(
                        "SELECT datname FROM pg_database "
                        "WHERE datname LIKE 'cin_%' ORDER BY 1"
                    )
                )
            ]
            out["cin_dbs"] = dbs
        except Exception as exc:
            out["cin_dbs_hata"] = str(exc)[:200]
    es0.dispose()

    ef = eng(FIRMA)
    with ef.connect() as c:
        out["firma_tables"] = c.execute(
            text(
                "SELECT count(*) FROM information_schema.tables "
                "WHERE table_schema='public' AND table_type='BASE TABLE'"
            )
        ).scalar()
        sayimlar = {}
        for t, exp in BEK.items():
            n = c.execute(text(f'SELECT count(*) FROM "{t}"')).scalar()
            sayimlar[t] = {"n": n, "expected": exp, "ok": n == exp}
        out["dokuz_sayim"] = sayimlar
        out["dokuz_sayim_ok"] = all(v["ok"] for v in sayimlar.values())
    ef.dispose()

    es = eng(SISTEM)
    with es.connect() as c:
        out["sistem_tables"] = c.execute(
            text(
                "SELECT count(*) FROM information_schema.tables "
                "WHERE table_schema='public' AND table_type='BASE TABLE'"
            )
        ).scalar()
        cos = c.execute(
            text(
                "SELECT id, firma_kodu, unvan, db_path, aktif "
                "FROM companies ORDER BY id"
            )
        ).mappings().all()
        out["companies"] = [dict(r) for r in cos]
    es.dispose()

    rapor_yol = ROOT / "kurulum" / "_kabul_baslangic_snapshot.json"
    rapor_yol.write_text(json.dumps(out, ensure_ascii=False, indent=2, default=str) + "\n", encoding="utf-8")
    print(json.dumps(out, ensure_ascii=False, indent=2, default=str))
    print("YAZILDI:", rapor_yol)
    return 0 if out.get("dokuz_sayim_ok") else 2


if __name__ == "__main__":
    raise SystemExit(main())
