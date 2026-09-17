"""İmporter tabanı."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from excel_aktarim.types import ImportTipi
from excel_aktarim.validation import DogrulamaRaporu, SatirSonuc


class BaseImporter(ABC):
    tip: ImportTipi

    def dogrula_satirlar(
        self,
        satirlar: list[dict[str, Any]],
        *,
        guncelleme_modu: str = "guncelle",
    ) -> DogrulamaRaporu:
        """guncelleme_modu: guncelle | atla | hata"""
        rapor = DogrulamaRaporu()
        for i, satir in enumerate(satirlar, start=2):
            sonuc = self.dogrula_satir(i, satir, guncelleme_modu=guncelleme_modu)
            rapor.satirlar.append(sonuc)
        rapor.ozetle()
        return rapor

    @abstractmethod
    def dogrula_satir(
        self,
        satir_no: int,
        eslenen: dict[str, Any],
        *,
        guncelleme_modu: str = "guncelle",
    ) -> SatirSonuc:
        ...

    @abstractmethod
    def uygula_satir(self, sonuc: SatirSonuc) -> dict[str, Any]:
        """Uygular; change kaydı için dict döner:
        {hedef_tablo, hedef_id, islem, onceki, sonraki, tutar?}
        """
        ...

    def geri_al_degisiklik(self, change: dict[str, Any]) -> None:
        """Varsayılan: insert soft-delete; update önceki JSON restore. Alt sınıf override edebilir."""
        raise NotImplementedError("Bu import tipi için geri alma henüz yok.")
