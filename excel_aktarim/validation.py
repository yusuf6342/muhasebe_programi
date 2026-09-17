"""Satır doğrulama sonuçları."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal


Islem = Literal["insert", "update", "skip"]


@dataclass
class SatirSonuc:
    satir_no: int
    ham: dict[str, Any]
    eslenen: dict[str, Any]
    gecerli: bool = True
    islem: Islem = "insert"
    mesajlar: list[str] = field(default_factory=list)
    hedef_tablo: str | None = None
    hedef_id: int | None = None
    ozet: str = ""

    def hata_ekle(self, mesaj: str) -> None:
        self.gecerli = False
        self.mesajlar.append(mesaj)

    def uyari_ekle(self, mesaj: str) -> None:
        self.mesajlar.append(mesaj)


@dataclass
class DogrulamaRaporu:
    satirlar: list[SatirSonuc] = field(default_factory=list)
    gecerli: int = 0
    hatali: int = 0
    eklenecek: int = 0
    guncellenecek: int = 0
    atlanacak: int = 0

    def ozetle(self) -> None:
        self.gecerli = sum(1 for s in self.satirlar if s.gecerli)
        self.hatali = sum(1 for s in self.satirlar if not s.gecerli)
        self.eklenecek = sum(1 for s in self.satirlar if s.gecerli and s.islem == "insert")
        self.guncellenecek = sum(1 for s in self.satirlar if s.gecerli and s.islem == "update")
        self.atlanacak = sum(1 for s in self.satirlar if s.gecerli and s.islem == "skip")
