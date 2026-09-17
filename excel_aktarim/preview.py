"""Önizleme / dry-run."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from excel_aktarim.importers.base import BaseImporter
from excel_aktarim.mapping import ColumnMappingService
from excel_aktarim.validation import DogrulamaRaporu


@dataclass
class OnizlemeSonucu:
    rapor: DogrulamaRaporu
    ornekler: list[dict[str, Any]]


class ImportPreviewService:
    @staticmethod
    def calistir(
        importer: BaseImporter,
        ham_satirlar: list[dict[str, Any]],
        esleme: dict[str, str],
        *,
        guncelleme_modu: str = "guncelle",
        ornek_limit: int = 20,
    ) -> OnizlemeSonucu:
        eslenenler = [ColumnMappingService.satir_esle(s, esleme) for s in ham_satirlar]
        rapor = importer.dogrula_satirlar(eslenenler, guncelleme_modu=guncelleme_modu)
        ornekler = []
        for s in rapor.satirlar[:ornek_limit]:
            ornekler.append(
                {
                    "satir_no": s.satir_no,
                    "islem": s.islem if s.gecerli else "hata",
                    "ozet": s.ozet or ", ".join(s.mesajlar) or "",
                    "mesaj": "; ".join(s.mesajlar),
                    "gecerli": s.gecerli,
                }
            )
        return OnizlemeSonucu(rapor=rapor, ornekler=ornekler)
