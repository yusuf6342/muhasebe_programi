"""Hızlı Satış — bellek içi sepet (Aşama 2; DB yazımı yok)."""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import ROUND_HALF_UP, Decimal
from typing import Iterable


KURUS = Decimal("0.01")
VARSAYILAN_KDV = Decimal("20")


def _d(deger, varsayilan: Decimal = Decimal("0")) -> Decimal:
    try:
        return Decimal(str(deger if deger is not None else varsayilan))
    except Exception:
        return Decimal(str(varsayilan))


def _kurus(tutar: Decimal) -> Decimal:
    return Decimal(str(tutar)).quantize(KURUS, rounding=ROUND_HALF_UP)


@dataclass
class SepetSatiri:
    stok_id: int
    stok_kodu: str
    stok_adi: str
    birim: str
    miktar: Decimal
    birim_fiyat: Decimal
    iskonto_orani: Decimal = field(default_factory=lambda: Decimal("0"))
    kdv_orani: Decimal = field(default_factory=lambda: VARSAYILAN_KDV)
    carpan: Decimal = field(default_factory=lambda: Decimal("1"))
    barkod: str | None = None

    @property
    def brut(self) -> Decimal:
        return _kurus(self.miktar * self.birim_fiyat)

    @property
    def iskonto_tutari(self) -> Decimal:
        oran = max(Decimal("0"), min(_d(self.iskonto_orani), Decimal("100")))
        return _kurus(self.brut * oran / Decimal("100"))

    @property
    def net(self) -> Decimal:
        return _kurus(self.brut - self.iskonto_tutari)

    @property
    def kdv_tutari(self) -> Decimal:
        return _kurus(self.net * _d(self.kdv_orani) / Decimal("100"))

    @property
    def satir_toplam(self) -> Decimal:
        """KDV dahil satır toplamı."""
        return _kurus(self.net + self.kdv_tutari)


class HizliSatisSepet:
    """Sıralı satır listesi; aynı stok+birim birleşir."""

    def __init__(self) -> None:
        self.satirlar: list[SepetSatiri] = []

    def temizle(self) -> None:
        self.satirlar.clear()

    def ekle(
        self,
        *,
        stok_id: int,
        stok_kodu: str,
        stok_adi: str,
        birim: str = "Adet",
        miktar: Decimal | str | float | int = 1,
        birim_fiyat: Decimal | str | float | int = 0,
        iskonto_orani: Decimal | str | float | int = 0,
        kdv_orani: Decimal | str | float | int = VARSAYILAN_KDV,
        carpan: Decimal | str | float | int = 1,
        barkod: str | None = None,
        birlestir: bool = True,
    ) -> SepetSatiri:
        miktar_d = _d(miktar, Decimal("1"))
        if miktar_d <= 0:
            raise ValueError("Miktar sıfırdan büyük olmalıdır.")
        birim_norm = (birim or "Adet").strip() or "Adet"
        kod = (stok_kodu or "").strip()

        if birlestir:
            for satir in self.satirlar:
                if satir.stok_kodu == kod and (satir.birim or "").strip() == birim_norm:
                    satir.miktar = _d(satir.miktar) + miktar_d
                    if barkod:
                        satir.barkod = barkod
                    return satir

        satir = SepetSatiri(
            stok_id=int(stok_id),
            stok_kodu=kod,
            stok_adi=(stok_adi or "").strip(),
            birim=birim_norm,
            miktar=miktar_d,
            birim_fiyat=_d(birim_fiyat),
            iskonto_orani=_d(iskonto_orani),
            kdv_orani=_d(kdv_orani, VARSAYILAN_KDV),
            carpan=_d(carpan, Decimal("1")),
            barkod=(barkod or None),
        )
        self.satirlar.append(satir)
        return satir

    def miktar_ayarla(self, index: int, miktar: Decimal | str | float | int) -> SepetSatiri | None:
        if index < 0 or index >= len(self.satirlar):
            return None
        miktar_d = _d(miktar)
        if miktar_d <= 0:
            self.satirlar.pop(index)
            return None
        self.satirlar[index].miktar = miktar_d
        return self.satirlar[index]

    def miktar_degistir(self, index: int, delta: Decimal | str | float | int) -> SepetSatiri | None:
        if index < 0 or index >= len(self.satirlar):
            return None
        return self.miktar_ayarla(index, _d(self.satirlar[index].miktar) + _d(delta))

    def fiyat_ayarla(self, index: int, birim_fiyat: Decimal | str | float | int) -> SepetSatiri | None:
        if index < 0 or index >= len(self.satirlar):
            return None
        self.satirlar[index].birim_fiyat = _d(birim_fiyat)
        return self.satirlar[index]

    def iskonto_ayarla(
        self, index: int, iskonto_orani: Decimal | str | float | int
    ) -> SepetSatiri | None:
        if index < 0 or index >= len(self.satirlar):
            return None
        oran = _d(iskonto_orani)
        if oran < 0 or oran > 100:
            raise ValueError("İskonto oranı 0–100 arasında olmalıdır.")
        self.satirlar[index].iskonto_orani = oran
        return self.satirlar[index]

    def sil(self, index: int) -> bool:
        if index < 0 or index >= len(self.satirlar):
            return False
        self.satirlar.pop(index)
        return True

    def toplamlar(self) -> dict[str, Decimal]:
        ara = iskonto = kdv = genel = Decimal("0")
        for s in self.satirlar:
            ara += s.brut
            iskonto += s.iskonto_tutari
            kdv += s.kdv_tutari
            genel += s.satir_toplam
        return {
            "ara_toplam": _kurus(ara),
            "iskonto": _kurus(iskonto),
            "kdv": _kurus(kdv),
            "genel_toplam": _kurus(genel),
        }

    def __iter__(self) -> Iterable[SepetSatiri]:
        return iter(self.satirlar)

    def __len__(self) -> int:
        return len(self.satirlar)
