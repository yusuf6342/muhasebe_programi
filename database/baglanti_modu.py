"""Çalışma kipi: yerel tek bilgisayar (SQLite) | yerel ağ (PostgreSQL).

Ağ dosyası / OneDrive üzerinde SQLite açılmaz. LAN kipinde bağlantı kopunca
sessizce SQLite'a düşülmez; açık hata verilir.
"""

from __future__ import annotations

import json
import logging
import os
import re
from dataclasses import asdict, dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any

_LOG = logging.getLogger("baglanti_modu")

AYAR_DOSYA_ADI = "baglanti_ayari.json"
SCHEMA_SURUM = 1  # istemci/sunucu şema uyumu için (ileride migration ile artar)


class CalismaKipi(str, Enum):
    YEREL_SQLITE = "yerel_sqlite"
    YEREL_AG_POSTGRES = "yerel_ag_postgres"


class OrtamEtiketi(str, Enum):
    DENEME = "DENEME"
    GERCEK = "GERCEK"


@dataclass
class PostgresBaglanti:
    host: str = "127.0.0.1"
    port: int = 5432
    sistem_db: str = "cin_sistem"
    # Firma DB adı uygulama içinde seçilir; burada varsayılan şablon
    kullanici: str = "cin_app"
    # Parola dosyada saklanmaz; Windows Credential Manager / env ile
    sslmode: str = "require"
    ortam: str = OrtamEtiketi.DENEME.value
    firma_db: str | None = None
    terminal_kimligi: str | None = None

    def dsn_sistem(self, parola: str) -> str:
        return self._dsn(self.sistem_db, parola)

    def dsn_firma(self, parola: str, firma_db: str | None = None) -> str:
        return self._dsn(firma_db or self.firma_db or self.sistem_db, parola)

    def _dsn(self, dbname: str, parola: str) -> str:
        from urllib.parse import quote_plus

        user = quote_plus(self.kullanici)
        pwd = quote_plus(parola or "")
        host = self.host.strip() or "127.0.0.1"
        return (
            f"postgresql+psycopg://{user}:{pwd}@{host}:{int(self.port)}/{dbname}"
            f"?sslmode={quote_plus(self.sslmode)}"
        )

    def ozet(self) -> str:
        firma = self.firma_db or "(firma seçilmedi)"
        return (
            f"{self.host}:{self.port} / sistem={self.sistem_db} / "
            f"firma={firma} / ortam={self.ortam}"
        )


@dataclass
class BaglantiAyari:
    kipi: str = CalismaKipi.YEREL_SQLITE.value
    postgres: PostgresBaglanti = field(default_factory=PostgresBaglanti)
    schema_surum: int = SCHEMA_SURUM

    @property
    def ag_mi(self) -> bool:
        return self.kipi == CalismaKipi.YEREL_AG_POSTGRES.value

    def to_dict(self) -> dict[str, Any]:
        return {
            "kipi": self.kipi,
            "schema_surum": self.schema_surum,
            "postgres": asdict(self.postgres),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> BaglantiAyari:
        data = data or {}
        pg_raw = data.get("postgres") or {}
        pg = PostgresBaglanti(
            host=str(pg_raw.get("host") or "127.0.0.1"),
            port=int(pg_raw.get("port") or 5432),
            sistem_db=_db_adi_temizle(pg_raw.get("sistem_db") or "cin_sistem"),
            kullanici=str(pg_raw.get("kullanici") or "cin_app"),
            sslmode=str(pg_raw.get("sslmode") or "require"),
            ortam=str(pg_raw.get("ortam") or OrtamEtiketi.DENEME.value),
            firma_db=(str(pg_raw["firma_db"]) if pg_raw.get("firma_db") else None),
            terminal_kimligi=(
                str(pg_raw["terminal_kimligi"]) if pg_raw.get("terminal_kimligi") else None
            ),
        )
        kipi = str(data.get("kipi") or CalismaKipi.YEREL_SQLITE.value)
        if kipi not in {c.value for c in CalismaKipi}:
            kipi = CalismaKipi.YEREL_SQLITE.value
        return cls(
            kipi=kipi,
            postgres=pg,
            schema_surum=int(data.get("schema_surum") or SCHEMA_SURUM),
        )


_DB_ADI_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,62}$")


def _db_adi_temizle(ad: str) -> str:
    ad = (ad or "").strip()
    if not _DB_ADI_RE.match(ad):
        raise ValueError(f"Geçersiz veritabanı adı: {ad!r}")
    return ad


def ayar_dosya_yolu(program_dir: Path | None = None) -> Path:
    if program_dir is None:
        from database.database import program_klasoru

        program_dir = program_klasoru()
    return Path(program_dir) / AYAR_DOSYA_ADI


def ayari_yukle(program_dir: Path | None = None) -> BaglantiAyari:
    """Dosya + ortam değişkeni. MUHASEBE_BAGLANTI_KIPI=yerel_ag_postgres zorlar."""
    yol = ayar_dosya_yolu(program_dir)
    data: dict[str, Any] = {}
    if yol.is_file():
        try:
            data = json.loads(yol.read_text(encoding="utf-8-sig"))
        except (OSError, json.JSONDecodeError) as exc:
            _LOG.warning("baglanti_ayari okunamadı: %s", exc)
    ayar = BaglantiAyari.from_dict(data if isinstance(data, dict) else {})
    env_kip = (os.environ.get("MUHASEBE_BAGLANTI_KIPI") or "").strip().lower()
    if env_kip in ("yerel_ag_postgres", "postgres", "lan", "ag"):
        ayar.kipi = CalismaKipi.YEREL_AG_POSTGRES.value
    elif env_kip in ("yerel_sqlite", "sqlite", "yerel"):
        ayar.kipi = CalismaKipi.YEREL_SQLITE.value
    return ayar


def ayari_kaydet(ayar: BaglantiAyari, program_dir: Path | None = None) -> Path:
    yol = ayar_dosya_yolu(program_dir)
    yol.write_text(
        json.dumps(ayar.to_dict(), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return yol


def postgres_parola_al() -> str:
    """Parola kodda/Git'te tutulmaz. Sıra: MUHASEBE_PG_PASSWORD > keyring."""
    env = (os.environ.get("MUHASEBE_PG_PASSWORD") or "").strip()
    if env:
        return env
    try:
        import keyring

        p = keyring.get_password("CinMuhasebe", "postgres_app")
        if p:
            return p
    except Exception:
        pass
    return ""


def postgres_parola_kaydet(parola: str) -> None:
    if not parola:
        return
    try:
        import keyring

        keyring.set_password("CinMuhasebe", "postgres_app", parola)
    except Exception as exc:
        _LOG.warning("Parola keyring'e yazılamadı: %s", exc)


def baglanti_sina(ayar: BaglantiAyari, parola: str | None = None) -> dict[str, Any]:
    """PostgreSQL bağlantısını dener; SQLite kipinde yerel dosya bilgisini döner."""
    if not ayar.ag_mi:
        from database.database import DB_DIR, DB_PATH, SYSTEM_DB_PATH

        return {
            "ok": True,
            "kipi": ayar.kipi,
            "ozet": f"Yerel SQLite — {DB_DIR}",
            "system_db": str(SYSTEM_DB_PATH),
            "muhasebe_db": str(DB_PATH),
        }
    pwd = parola if parola is not None else postgres_parola_al()
    if not pwd:
        return {
            "ok": False,
            "kipi": ayar.kipi,
            "hata": "PostgreSQL parolası yok. MUHASEBE_PG_PASSWORD veya güvenli depo gerekli.",
        }
    try:
        from sqlalchemy import create_engine, text

        url = ayar.postgres.dsn_sistem(pwd)
        eng = create_engine(url, pool_pre_ping=True, connect_args={"connect_timeout": 8})
        with eng.connect() as conn:
            ver = conn.execute(text("SHOW server_version")).scalar()
            conn.execute(text("SELECT 1"))
        eng.dispose()
        return {
            "ok": True,
            "kipi": ayar.kipi,
            "ozet": ayar.postgres.ozet(),
            "server_version": ver,
            "ortam": ayar.postgres.ortam,
        }
    except Exception as exc:
        _LOG.exception("PostgreSQL bağlantı denemesi başarısız")
        return {
            "ok": False,
            "kipi": ayar.kipi,
            "ozet": ayar.postgres.ozet(),
            "hata": str(exc),
        }
