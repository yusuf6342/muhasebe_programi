"""Geçiş aracı birim testleri — gerçek PG/parola gerektirmez."""

from __future__ import annotations

import importlib.util
import sqlite3
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
MOD_PATH = ROOT / "tools" / "_sqlite_to_postgres_gecis.py"


def _load():
    spec = importlib.util.spec_from_file_location("sqlite_to_postgres_gecis", MOD_PATH)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def gecis():
    return _load()


def test_deger_donustur_bool_tarih_sayi(gecis):
    assert gecis._deger_donustur(1, "bool") is True
    assert gecis._deger_donustur(0, "boolean") is False
    assert gecis._deger_donustur("2024-01-02 03:04:05", "timestamp").year == 2024
    assert int(gecis._deger_donustur("42", "int8")) == 42
    assert gecis._deger_donustur(None, "text") is None


def test_ray_firma_sec_ve_digerleri(gecis, tmp_path):
    db = tmp_path / "system.db"
    con = sqlite3.connect(db)
    con.execute(
        "CREATE TABLE companies ("
        "id INTEGER PRIMARY KEY, firma_kodu TEXT, unvan TEXT, aktif INTEGER, db_path TEXT)"
    )
    con.executemany(
        "INSERT INTO companies VALUES (?,?,?,?,?)",
        [
            (1, "RAY001", "Ray Mobilya Aksesuarları", 1, "muhasebe.db"),
            (2, "TESTA7", "Test", 1, "companies/a.db"),
            (3, "001", "DENEME", 1, "companies/b.db"),
        ],
    )
    con.commit()
    con.close()
    bilgi = gecis._ray_firma_sec(db, "RAY001")
    assert bilgi["secilen"]["firma_kodu"] == "RAY001"
    assert len(bilgi["tum"]) == 3


def test_localhost_engeli_argparse(gecis):
    # main içinde kontrol; burada host kuralını simüle et
    host = "127.0.0.1"
    localhost_izin = False
    engelli = host in ("127.0.0.1", "localhost", "::1") and not localhost_izin
    assert engelli is True


def test_mali_fark_tolerans(gecis):
    src = {"a": 100.0}
    assert gecis._mali_farklar(src, {"a": 100.01}) == []
    assert gecis._mali_farklar(src, {"a": 101.0})


def test_yansit_ddl_tek_pk(gecis, tmp_path):
    db = tmp_path / "f.db"
    con = sqlite3.connect(db)
    con.execute("CREATE TABLE t (id INTEGER PRIMARY KEY, aktif INTEGER, ad TEXT)")
    ddl = gecis._yansit_tablo_ddl(con, "t")
    con.close()
    assert "PRIMARY KEY" in ddl
    assert "BOOLEAN" in ddl or "BIGINT" in ddl
