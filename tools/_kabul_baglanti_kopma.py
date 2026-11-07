"""Bağlantı kopması / yarım kayıt / mükerrer koruma (kontrollü, deneme DB)."""
from __future__ import annotations

import json
import socket
import sys
import time
from datetime import datetime
from pathlib import Path
from urllib.parse import quote_plus

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from database.baglanti_modu import postgres_parola_al  # noqa: E402
from sqlalchemy import create_engine, text  # noqa: E402

HOST = "192.168.1.114"
FR = "cin_firma_kabul_20261105"
ETIKET = "KABULTEST-KOPMA-20261105"
SSLMODE = "verify-full"


def eng(statement_timeout_ms: int | None = None):
    pwd = quote_plus(postgres_parola_al())
    url = f"postgresql+psycopg://cin_app:{pwd}@{HOST}:5432/{FR}?sslmode={SSLMODE}"
    args = {"connect_timeout": 8}
    if statement_timeout_ms:
        args["options"] = f"-c statement_timeout={statement_timeout_ms}"
    return create_engine(url, pool_pre_ping=True, connect_args=args)


def main() -> int:
    rapor: dict = {
        "zaman": datetime.now().isoformat(timespec="seconds"),
        "makine": socket.gethostname(),
        "senaryolar": [],
    }
    e = eng()
    with e.begin() as c:
        c.execute(
            text(
                "CREATE TABLE IF NOT EXISTS kabul_kopma_test ("
                "id serial PRIMARY KEY, belge_no text UNIQUE NOT NULL, etiket text)"
            )
        )

    # A) Transaction bütünlüğü
    marker = f"{ETIKET}-TX"
    with e.connect() as c:
        before = c.execute(
            text("SELECT count(*) FROM kabul_kopma_test WHERE etiket = :a"),
            {"a": marker},
        ).scalar()
    try:
        with e.begin() as c:
            c.execute(
                text(
                    "INSERT INTO kabul_kopma_test(belge_no, etiket) VALUES (:n, :a)"
                ),
                {"n": f"TX-{int(time.time())}", "a": marker},
            )
            raise RuntimeError("bilincli_hata_rollback")
    except RuntimeError:
        pass
    with e.connect() as c:
        after = c.execute(
            text("SELECT count(*) FROM kabul_kopma_test WHERE etiket = :a"),
            {"a": marker},
        ).scalar()
    rapor["senaryolar"].append(
        {
            "ad": "transaction_rollback_yarim_kayit_yok",
            "before": before,
            "after": after,
            "durum": "GECTI" if before == after else "KALDI",
        }
    )

    # B) Unique belge_no
    no = f"UQ-{int(time.time())}"
    with e.begin() as c:
        c.execute(
            text("INSERT INTO kabul_kopma_test(belge_no, etiket) VALUES (:n, :a)"),
            {"n": no, "a": ETIKET},
        )
    mukerrer_red = False
    hata = ""
    try:
        with e.begin() as c:
            c.execute(
                text("INSERT INTO kabul_kopma_test(belge_no, etiket) VALUES (:n, :a)"),
                {"n": no, "a": ETIKET},
            )
    except Exception as exc:
        mukerrer_red = True
        hata = str(exc)[:200]
    with e.begin() as c:
        n = c.execute(
            text("SELECT count(*) FROM kabul_kopma_test WHERE belge_no = :n"),
            {"n": no},
        ).scalar()
        c.execute(text("DELETE FROM kabul_kopma_test WHERE belge_no = :n"), {"n": no})
    rapor["senaryolar"].append(
        {
            "ad": "mukerrer_belge_no_unique",
            "adet": n,
            "ikinci_red": mukerrer_red,
            "hata_ozet": hata,
            "durum": "GECTI" if mukerrer_red and n == 1 else "KALDI",
            "not": "satis_faturalari.fatura_no UNIQUE aynı korumayı sağlar",
        }
    )

    # C) statement_timeout + reconnect
    e2 = eng(statement_timeout_ms=500)
    timeout_ok = False
    try:
        with e2.connect() as c:
            c.execute(text("SELECT pg_sleep(2)"))
    except Exception as exc:
        timeout_ok = "canceling statement" in str(exc).lower() or "timeout" in str(exc).lower()
        rapor["timeout_hata"] = str(exc)[:200]
    reconnect_ok = False
    try:
        with e2.connect() as c:
            reconnect_ok = c.execute(text("SELECT 1")).scalar() == 1
    except Exception as exc:
        rapor["reconnect_hata"] = str(exc)[:200]
    e2.dispose()
    rapor["senaryolar"].append(
        {
            "ad": "statement_timeout_ve_reconnect",
            "timeout_tetiklendi": timeout_ok,
            "reconnect_ok": reconnect_ok,
            "durum": "GECTI" if timeout_ok and reconnect_ok else "KALDI",
            "not": "PG/ağ genel kapatılmadı; kontrollü timeout",
        }
    )

    # D) dispose sonrası yeni bağlantı
    e3 = eng()
    with e3.connect() as c:
        c.execute(text("SELECT 1"))
    e3.dispose()
    e4 = eng()
    with e4.connect() as c:
        ping = c.execute(text("SELECT 1")).scalar()
    e4.dispose()
    rapor["senaryolar"].append(
        {
            "ad": "dispose_sonrasi_yeni_baglanti",
            "ping": ping,
            "durum": "GECTI" if ping == 1 else "KALDI",
        }
    )

    e.dispose()
    yol = ROOT / "kurulum" / "_kabul_baglanti_kopma.json"
    yol.write_text(json.dumps(rapor, ensure_ascii=False, indent=2, default=str) + "\n", encoding="utf-8")
    print(json.dumps([(s["ad"], s["durum"]) for s in rapor["senaryolar"]], ensure_ascii=False, indent=2))
    print("YAZILDI:", yol)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
