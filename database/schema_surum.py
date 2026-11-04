"""İstemci/sunucu şema sürümü — LAN'da uyumsuzlukta açık uyarı."""

from __future__ import annotations

from sqlalchemy import text
from sqlalchemy.engine import Engine

from database.baglanti_modu import SCHEMA_SURUM


class SchemaUyumsuzlugu(RuntimeError):
    pass


def sunucu_schema_surumu_oku(engine: Engine) -> int | None:
    with engine.connect() as conn:
        try:
            row = conn.execute(
                text(
                    "SELECT deger FROM app_settings WHERE anahtar = 'schema_surum' LIMIT 1"
                )
            ).first()
            if row and row[0] is not None and str(row[0]).strip().isdigit():
                return int(str(row[0]).strip())
        except Exception:
            pass
    return None


def schema_uyum_kontrol(engine: Engine, *, istemci: int = SCHEMA_SURUM) -> None:
    sunucu = sunucu_schema_surumu_oku(engine)
    if sunucu is None:
        return
    if sunucu != istemci:
        raise SchemaUyumsuzlugu(
            f"Şema sürümü uyuşmuyor: sunucu={sunucu}, istemci={istemci}. "
            "Aynı Cin Muhasebe sürümünü kullanın; migration yalnız yetkili süreçte."
        )


def schema_surum_yaz(engine: Engine, surum: int = SCHEMA_SURUM) -> None:
    with engine.begin() as conn:
        conn.execute(
            text("DELETE FROM app_settings WHERE anahtar = 'schema_surum'")
        )
        conn.execute(
            text(
                "INSERT INTO app_settings (anahtar, deger) VALUES ('schema_surum', :v)"
            ),
            {"v": str(surum)},
        )
