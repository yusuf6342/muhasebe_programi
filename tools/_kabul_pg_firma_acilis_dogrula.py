"""Salt okunur verify-full: kabul sistem+firma kimlik + RAY001 firma_db_ac.

Parola yazdırılmaz. SQLite'a düşmez.
"""
from __future__ import annotations

import json
import os
import socket
import sys
from datetime import datetime
from pathlib import Path
from urllib.parse import quote_plus

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

# MUHASEBE_BAGLANTI_KIPI'yi database importundan ONCE set etme:
# aksi halde module-level engine baslatimi + ayari_yukle dongusu asili kalabilir.
from database.baglanti_modu import (  # noqa: E402
    BaglantiAyari,
    CalismaKipi,
    PostgresBaglanti,
    postgres_parola_al,
)
import database.baglanti_modu as bm  # noqa: E402
from sqlalchemy import create_engine, text  # noqa: E402

HOST = "192.168.1.114"
USER = "cin_app"
SYS = "cin_sistem_kabul_20261105"
FR = "cin_firma_kabul_20261105"
CA = Path(os.environ.get("APPDATA", "")) / "postgresql" / "root.crt"

_AYAR = BaglantiAyari(
    kipi=CalismaKipi.YEREL_AG_POSTGRES.value,
    postgres=PostgresBaglanti(
        host=HOST,
        port=5432,
        sistem_db=SYS,
        kullanici=USER,
        sslmode="verify-full",
        ortam="DENEME",
        firma_db=FR,
        terminal_kimligi="KABUL-DIAG",
    ),
)
bm.ayari_yukle = lambda program_dir=None: _AYAR  # type: ignore

from database.database import firma_db_ac, pg_firma_tanimi_mi  # noqa: E402


def _url(db: str) -> str:
    pwd = quote_plus(postgres_parola_al())
    q = "sslmode=verify-full"
    if CA.is_file():
        q += f"&sslrootcert={quote_plus(str(CA))}"
    return f"postgresql+psycopg://{USER}:{pwd}@{HOST}:5432/{db}?{q}"


def _probe(db: str) -> dict:
    out: dict = {"db": db, "ok": False}
    if not postgres_parola_al():
        out["hata"] = "parola_yok"
        return out
    e = create_engine(_url(db), connect_args={"connect_timeout": 12})
    try:
        with e.connect() as c:
            out["server_version"] = c.execute(text("SHOW server_version")).scalar()
            out["current_user"] = c.execute(text("SELECT current_user")).scalar()
            out["current_database"] = c.execute(text("SELECT current_database()")).scalar()
            out["inet_server"] = c.execute(text("SELECT inet_server_addr()")).scalar()
            out["ssl"] = c.execute(text("SHOW ssl")).scalar()
            if db == SYS:
                ray = c.execute(
                    text(
                        "SELECT firma_kodu, db_path, aktif FROM companies "
                        "WHERE firma_kodu='RAY001'"
                    )
                ).mappings().first()
                out["ray001"] = dict(ray) if ray else None
            else:
                out["cari"] = int(
                    c.execute(text("SELECT count(*) FROM cari_kartlar")).scalar() or 0
                )
                out["stok"] = int(
                    c.execute(text("SELECT count(*) FROM stok_kartlari")).scalar() or 0
                )
            out["ok"] = True
    except Exception as exc:
        msg = str(exc)
        # parola metni yok; sınıflandır
        low = msg.lower()
        if "password authentication failed" in low:
            out["hata_sinif"] = "parola_red"
        elif "no pg_hba.conf entry" in low:
            out["hata_sinif"] = "pg_hba"
        elif "certificate" in low or "ssl" in low:
            out["hata_sinif"] = "ssl_sertifika"
        else:
            out["hata_sinif"] = "diger"
        out["hata"] = msg.split("\n")[0][:220]
    finally:
        e.dispose()
    return out


def main() -> int:
    parola_var = bool(postgres_parola_al())
    parola_len = len(postgres_parola_al()) if parola_var else 0

    rapor: dict = {
        "zaman": datetime.now().isoformat(timespec="seconds"),
        "makine": socket.gethostname(),
        "parola_var": parola_var,
        "parola_uzunluk": parola_len,
        "ca": str(CA) if CA.is_file() else None,
        "sslmode": "verify-full",
        "sistem": _probe(SYS),
        "firma": _probe(FR),
        "lenovo_not": (
            "Lenovo 192.168.1.106 parola reddi: ortak cin_app parolası değiştirilmeden "
            "önce (1) HBA hostssl 106/32, (2) aynı Credential Manager hedefi "
            "CinMuhasebe/postgres_app, (3) verify-full + root.crt, (4) kullanıcı adı cin_app. "
            "Bu terminalde parola_uzunluk ve verify-full kimlik aşağıda."
        ),
    }

    # Gerçek firma açılışı (RAY001 → pg:cin_firma_kabul)
    acilis: dict = {"ok": False}
    try:
        assert pg_firma_tanimi_mi(f"pg:{FR}")
        firma_db_ac(1, f"pg:{FR}")
        from database import database as db

        eng = db.engine
        with eng.connect() as c:
            n = int(c.execute(text("SELECT count(*) FROM cari_kartlar")).scalar() or 0)
            dbname = c.execute(text("SELECT current_database()")).scalar()
        acilis = {
            "ok": True,
            "current_database": dbname,
            "beklenen": FR,
            "cari": n,
            "eslesme": dbname == FR,
        }
    except Exception as exc:
        acilis = {"ok": False, "hata": str(exc).split("\n")[0][:300]}
    rapor["firma_db_ac_ray001"] = acilis

    # Lenovo teşhis özeti (parolasız)
    rapor["lenovo_duzeltme"] = {
        "ortak_parola_degistir": False,
        "oneriler": [
            "Ana makinede 08_pg_hba_terminal_106_izin.ps1 (192.168.1.106/32 hostssl)",
            "Lenovo'da cmdkey /generic:CinMuhasebe /user:postgres_app (keyring ile aynı hedef)",
            "%APPDATA%\\postgresql\\root.crt + baglanti sslmode=verify-full",
            "baglanti_ayari kullanici=cin_app (başka kullanıcı adı değil)",
            "Bu terminalde parola_uzunluk>0 ve sistem/firma ok=true ise sunucu parolası doğru; Lenovo tarafı istemci/HBA/SSL",
        ],
        "bu_terminal_parola_calisiyor": bool(
            rapor["sistem"].get("ok") and rapor["firma"].get("ok")
        ),
    }

    yol = ROOT / "kurulum" / "_kabul_pg_firma_acilis_dogrula.json"
    yol.write_text(json.dumps(rapor, ensure_ascii=False, indent=2, default=str) + "\n", encoding="utf-8")
    ozet = {
        "sistem_ok": rapor["sistem"].get("ok"),
        "firma_ok": rapor["firma"].get("ok"),
        "ray": (rapor["sistem"].get("ray001") or {}).get("db_path"),
        "firma_db_ac": acilis,
        "parola_uzunluk": parola_len,
        "lenovo_parola_sunucuda_ok": rapor["lenovo_duzeltme"]["bu_terminal_parola_calisiyor"],
    }
    print(json.dumps(ozet, ensure_ascii=False, indent=2, default=str))
    print("YAZILDI:", yol)
    return 0 if acilis.get("ok") and rapor["sistem"].get("ok") and rapor["firma"].get("ok") else 2


if __name__ == "__main__":
    raise SystemExit(main())
