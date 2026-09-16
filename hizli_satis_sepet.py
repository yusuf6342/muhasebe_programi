"""Hızlı Satış — bellek içi sepet (Aşama 2; DB yazımı yok)."""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import ROUND_HALF_UP, Decimal
from typing import Iterable


KURUS = Decimal("0.01")
# POS fiş satırı: KDV varsayılan %0; stok kartı oranı otomatik uygulanmaz.
VARSAYILAN_KDV = Decimal("0")
# Fatura UI (app.KDV_ORANLARI) ile aynı seçenekler
KDV_ORANLARI = ("0", "1", "8", "10", "18", "20")


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

    def kdv_ayarla(
        self, index: int, kdv_orani: Decimal | str | float | int
    ) -> SepetSatiri | None:
        if index < 0 or index >= len(self.satirlar):
            return None
        oran = _d(kdv_orani)
        if oran < 0 or oran > 100:
            raise ValueError("KDV oranı 0–100 arasında olmalıdır.")
        self.satirlar[index].kdv_orani = oran
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

    @staticmethod
    def _hedef_satir_genelden_fiyat(satir: SepetSatiri, hedef_satir_genel: Decimal) -> Decimal:
        """KDV dahil satır tutarından birim fiyatı geri hesaplar."""
        miktar = _d(satir.miktar)
        if miktar <= 0:
            raise ValueError("Miktarı olmayan satıra fiyat yansıtılamaz.")
        kdv = _d(satir.kdv_orani)
        isk = max(Decimal("0"), min(_d(satir.iskonto_orani), Decimal("100")))
        carpani = Decimal("1") - isk / Decimal("100")
        if carpani <= 0:
            raise ValueError("%100 iskontolu satıra fiyat yansıtılamaz.")
        net = Decimal(str(hedef_satir_genel)) / (Decimal("1") + kdv / Decimal("100"))
        fiyat = net / (miktar * carpani)
        return fiyat.quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)

    def hedef_toplam_uygula(self, hedef: Decimal | str | float | int) -> dict[str, Decimal]:
        """Genel toplamı hedef tutara getirmek için birim fiyatları orantılı ölçekler.

        Her satırın KDV dahil tutarı mevcut ağırlığa göre dağıtılır; son satıra
        kalan kuruş verilir. Boş sepet / sıfır toplam için ValueError.
        """
        hedef_d = _kurus(_d(hedef))
        if hedef_d < 0:
            raise ValueError("Hedef toplam negatif olamaz.")
        if not self.satirlar:
            raise ValueError("Sepet boş; hedef toplam uygulanamaz.")

        satir_ozet: list[tuple[int, Decimal, Decimal]] = []
        mevcut_toplam = Decimal("0")
        for i, s in enumerate(self.satirlar):
            miktar = _d(s.miktar)
            if miktar <= 0:
                continue
            satir_genel = s.satir_toplam
            satir_ozet.append((i, satir_genel, miktar))
            mevcut_toplam += satir_genel
        mevcut_toplam = _kurus(mevcut_toplam)

        if not satir_ozet:
            raise ValueError("Fiyat yansıtmak için miktarı olan en az bir satır gerekli.")

        if hedef_d == mevcut_toplam:
            return self.toplamlar()

        hedefler: dict[int, Decimal] = {}
        if mevcut_toplam > 0:
            biriken = Decimal("0")
            for i, satir_genel, _m in satir_ozet[:-1]:
                pay = _kurus(hedef_d * (satir_genel / mevcut_toplam))
                hedefler[i] = pay
                biriken += pay
            son_i = satir_ozet[-1][0]
            hedefler[son_i] = _kurus(hedef_d - biriken)
        else:
            # Tüm satırlar 0 TL ise miktara göre dağıt
            toplam_miktar = sum((m for _i, _g, m in satir_ozet), Decimal("0"))
            if toplam_miktar <= 0:
                raise ValueError("Dağıtılacak miktar yok.")
            biriken = Decimal("0")
            for i, _g, miktar in satir_ozet[:-1]:
                pay = _kurus(hedef_d * (miktar / toplam_miktar))
                hedefler[i] = pay
                biriken += pay
            son_i = satir_ozet[-1][0]
            hedefler[son_i] = _kurus(hedef_d - biriken)

        for i, hedef_satir in hedefler.items():
            if hedef_satir < 0:
                raise ValueError("Hesaplanan satır tutarı negatif olamaz.")
            yeni_fiyat = self._hedef_satir_genelden_fiyat(self.satirlar[i], hedef_satir)
            if yeni_fiyat < 0:
                raise ValueError("Hesaplanan birim fiyat negatif olamaz.")
            self.satirlar[i].birim_fiyat = yeni_fiyat

        # Kuruş farkını son satırda kapat
        yeni_genel = self.toplamlar()["genel_toplam"]
        fark = _kurus(hedef_d - yeni_genel)
        if fark != 0:
            son_i = satir_ozet[-1][0]
            son = self.satirlar[son_i]
            son_hedef = _kurus(son.satir_toplam + fark)
            if son_hedef < 0:
                raise ValueError("Yuvarlama sonrası satır tutarı negatif kaldı.")
            self.satirlar[son_i].birim_fiyat = self._hedef_satir_genelden_fiyat(son, son_hedef)

        return self.toplamlar()

    def __iter__(self) -> Iterable[SepetSatiri]:
        return iter(self.satirlar)

    def __len__(self) -> int:
        return len(self.satirlar)
