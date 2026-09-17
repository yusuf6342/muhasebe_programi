"""Sütun eşleme servisi."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from sqlalchemy import select

from database.database import get_session
from excel_aktarim.models import ImportMapping
from excel_aktarim.normalize import baslik_normalize, temiz
from excel_aktarim.types import ImportTipi, getir


@dataclass
class MappingSonuc:
    esleme: dict[str, str]  # excel_baslik -> alan_kod
    otomatik: dict[str, str] = field(default_factory=dict)
    eslesmeyen_excel: list[str] = field(default_factory=list)
    eksik_zorunlu: list[str] = field(default_factory=list)


class ColumnMappingService:
    @staticmethod
    def otomatik_esle(tip: ImportTipi | str, excel_basliklar: list[str]) -> MappingSonuc:
        tip = getir(tip) if isinstance(tip, str) else tip
        esleme: dict[str, str] = {}
        otomatik: dict[str, str] = {}
        kullanilan: set[str] = set()

        # 1) kayıtlı eşleşen_basliklar
        for excel_h in excel_basliklar:
            n = baslik_normalize(excel_h)
            alan = tip.eslesen_basliklar.get(n)
            if alan and alan not in kullanilan:
                esleme[excel_h] = alan
                otomatik[excel_h] = alan
                kullanilan.add(alan)

        # 2) alan kodu / başlık normalize
        alan_norm: dict[str, str] = {}
        for a in tip.alanlar:
            alan_norm[baslik_normalize(a.kod)] = a.kod
            alan_norm[baslik_normalize(a.baslik)] = a.kod

        for excel_h in excel_basliklar:
            if excel_h in esleme:
                continue
            n = baslik_normalize(excel_h)
            alan = alan_norm.get(n)
            if alan and alan not in kullanilan:
                esleme[excel_h] = alan
                otomatik[excel_h] = alan
                kullanilan.add(alan)

        eslesmeyen = [h for h in excel_basliklar if h not in esleme]
        eslenen_alanlar = set(esleme.values())
        eksik = [a.kod for a in tip.alanlar if a.zorunlu and a.kod not in eslenen_alanlar]
        return MappingSonuc(
            esleme=esleme,
            otomatik=otomatik,
            eslesmeyen_excel=eslesmeyen,
            eksik_zorunlu=eksik,
        )

    @staticmethod
    def satir_esle(satir: dict[str, Any], esleme: dict[str, str]) -> dict[str, Any]:
        out: dict[str, Any] = {}
        for excel_h, alan in esleme.items():
            if excel_h not in satir:
                continue
            deger = satir.get(excel_h)
            if temiz(deger) == "" and deger is not True and deger is not False:
                continue
            out[alan] = deger
        return out

    @staticmethod
    def kaydet(import_tipi: str, ad: str, esleme: dict[str, str], *, varsayilan: bool = False) -> ImportMapping:
        with get_session() as session:
            if varsayilan:
                for eski in session.scalars(
                    select(ImportMapping).where(
                        ImportMapping.import_tipi == import_tipi,
                        ImportMapping.varsayilan.is_(True),
                    )
                ):
                    eski.varsayilan = False
            kayit = ImportMapping(
                import_tipi=import_tipi,
                ad=ad.strip() or "Kayıtlı eşleme",
                mapping_json=json.dumps(esleme, ensure_ascii=False),
                varsayilan=varsayilan,
                updated_at=datetime.now(),
            )
            session.add(kayit)
            session.flush()
            return kayit

    @staticmethod
    def listele(import_tipi: str) -> list[ImportMapping]:
        with get_session() as session:
            return list(
                session.scalars(
                    select(ImportMapping)
                    .where(ImportMapping.import_tipi == import_tipi)
                    .order_by(ImportMapping.varsayilan.desc(), ImportMapping.id.desc())
                )
            )

    @staticmethod
    def yukle(mapping_id: int) -> dict[str, str]:
        with get_session() as session:
            kayit = session.get(ImportMapping, mapping_id)
            if kayit is None:
                raise ValueError("Eşleme bulunamadı.")
            return json.loads(kayit.mapping_json)
