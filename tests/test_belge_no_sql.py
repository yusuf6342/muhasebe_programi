"""belge_no_sql SQLite yolu."""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from sqlalchemy import text
from sqlalchemy.orm import sessionmaker

from database.belge_no_sql import max_sayisal_kuyruk
from database.engine_factory import sqlite_engine


class BelgeNoSqlTest(unittest.TestCase):
    def test_max_kuyruk_sqlite(self):
        with tempfile.TemporaryDirectory() as td:
            eng = sqlite_engine(Path(td) / "t.db")
            with eng.begin() as c:
                c.execute(text("CREATE TABLE satis_faturalari (fatura_no TEXT)"))
                c.execute(
                    text(
                        "INSERT INTO satis_faturalari (fatura_no) VALUES "
                        "('RAY-00003'), ('RAY-00001'), ('RAY-X')"
                    )
                )
            Session = sessionmaker(bind=eng)
            with Session() as s:
                self.assertEqual(
                    max_sayisal_kuyruk(
                        s, tablo="satis_faturalari", kolon="fatura_no", onek="RAY-"
                    ),
                    3,
                )
            eng.dispose()


if __name__ == "__main__":
    unittest.main()
