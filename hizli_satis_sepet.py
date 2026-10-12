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


FIYAT_HASSASIYET = Decimal("0.0001")


def _satir_tutarlari(miktar, fiyat, iskonto_orani, kdv_orani) -> tuple[Decimal, Decimal, Decimal]:
    """(brüt, net, kdv) — SatisFaturasiService.toplam ile aynı kuruş kuralı.

    Net = miktar × fiyat × (1 − isk) kuruşa yuvarlanır; KDV net üzerinden.
    """
    m = _d(miktar)
    p = _d(fiyat)
    oran = max(Decimal("0"), min(_d(iskonto_orani), Decimal("100")))
    ham = m * p
    brut = _kurus(ham)
    net = brut if oran == 0 else _kurus(ham * (Decimal("1") - oran / Decimal("100")))
    kdv = _kurus(net * _d(kdv_orani) / Decimal("100"))
    return brut, net, kdv


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
    # Yeni Toplam düzeltmesi öncesi birim fiyat; None → etkin fiyat referansla aynı
    referans_birim_fiyat: Decimal | None = None
    # Fiyat listesinden seçilen fiyat türü (birim değişiminde aynı tür kullanılır)
    fiyat_adi: str | None = None

    @property
    def referans_fiyat(self) -> Decimal:
        if self.referans_birim_fiyat is None:
            return _d(self.birim_fiyat)
        return _d(self.referans_birim_fiyat)

    @property
    def brut(self) -> Decimal:
        return _satir_tutarlari(self.miktar, self.birim_fiyat, self.iskonto_orani, self.kdv_orani)[0]

    @property
    def iskonto_tutari(self) -> Decimal:
        brut, net, _ = _satir_tutarlari(
            self.miktar, self.birim_fiyat, self.iskonto_orani, self.kdv_orani
        )
        return _kurus(brut - net)

    @property
    def net(self) -> Decimal:
        return _satir_tutarlari(self.miktar, self.birim_fiyat, self.iskonto_orani, self.kdv_orani)[1]

    @property
    def kdv_tutari(self) -> Decimal:
        return _satir_tutarlari(self.miktar, self.birim_fiyat, self.iskonto_orani, self.kdv_orani)[2]

    def fiyatla_toplam(self, fiyat) -> Decimal:
        """Verilen birim fiyatla KDV dahil satır toplamı."""
        _, net, kdv = _satir_tutarlari(self.miktar, fiyat, self.iskonto_orani, self.kdv_orani)
        return _kurus(net + kdv)

    @property
    def satir_toplam(self) -> Decimal:
        """KDV dahil satır toplamı (etkin fiyat)."""
        return self.fiyatla_toplam(self.birim_fiyat)

    @property
    def referans_satir_toplam(self) -> Decimal:
        """KDV dahil satır toplamı (referans fiyat)."""
        return self.fiyatla_toplam(self.referans_fiyat)


class HizliSatisSepet:
    """Sıralı satır listesi; aynı stok+birim birleşir.

    Genel Toplam = referans fiyatlarla toplam; Yeni Toplam (``hedef_toplam``)
    etkin fiyatlarla son satış tutarıdır. Gerçek sepet değişikliği (ekle/sil,
    miktar/birim/fiyat/iskonto/KDV) eski düzeltmeyi kaldırır.
    """

    def __init__(self) -> None:
        self.satirlar: list[SepetSatiri] = []
        self.hedef_toplam: Decimal | None = None
        self.son_degisiklik_duzeltme_kaldirdi = False

    def temizle(self) -> None:
        self.satirlar.clear()
        self.hedef_toplam = None
        self.son_degisiklik_duzeltme_kaldirdi = False

    @property
    def duzeltme_aktif(self) -> bool:
        return any(s.referans_birim_fiyat is not None for s in self.satirlar)

    def duzeltmeyi_kaldir(self) -> bool:
        """Etkin fiyatları referansa döndürür. Düzeltme vardıysa True."""
        vardi = self.duzeltme_aktif or self.hedef_toplam is not None
        for s in self.satirlar:
            if s.referans_birim_fiyat is not None:
                s.birim_fiyat = _d(s.referans_birim_fiyat)
                s.referans_birim_fiyat = None
        self.hedef_toplam = None
        return vardi

    def _sepet_degisti(self) -> None:
        self.son_degisiklik_duzeltme_kaldirdi = self.duzeltmeyi_kaldir()

    def referans_toplam(self) -> Decimal:
        """Genel Toplam — Yeni Toplam düzeltmesi öncesi referans tutar."""
        return _kurus(sum((s.referans_satir_toplam for s in self.satirlar), Decimal("0")))

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
        referans_birim_fiyat: Decimal | str | float | int | None = None,
        geri_yukleme: bool = False,
    ) -> SepetSatiri:
        """Satır ekler; normal eklemede eski Yeni Toplam düzeltmesi kalkar.

        ``geri_yukleme=True`` (bekleyen sepet) kayıtlı referans fiyatı ve düzeltmeyi korur.
        """
        miktar_d = _d(miktar, Decimal("1"))
        if miktar_d <= 0:
            raise ValueError("Miktar sıfırdan büyük olmalıdır.")
        birim_norm = (birim or "Adet").strip() or "Adet"
        kod = (stok_kodu or "").strip()

        if not geri_yukleme:
            self._sepet_degisti()
            referans_birim_fiyat = None

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
            referans_birim_fiyat=(
                None if referans_birim_fiyat is None else _d(referans_birim_fiyat)
            ),
        )
        self.satirlar.append(satir)
        return satir

    def miktar_ayarla(self, index: int, miktar: Decimal | str | float | int) -> SepetSatiri | None:
        if index < 0 or index >= len(self.satirlar):
            return None
        self._sepet_degisti()
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
        """Kullanıcı fiyatı / fiyat seçimi — yeni referans fiyat olur."""
        if index < 0 or index >= len(self.satirlar):
            return None
        self._sepet_degisti()
        self.satirlar[index].birim_fiyat = _d(birim_fiyat)
        self.satirlar[index].referans_birim_fiyat = None
        self.satirlar[index].fiyat_adi = None
        return self.satirlar[index]

    def birim_uygula(
        self,
        index: int,
        *,
        birim: str,
        miktar: Decimal | str | float | int,
        birim_fiyat: Decimal | str | float | int,
        carpan: Decimal | str | float | int,
    ) -> SepetSatiri | None:
        """Satır birimini değiştirir (miktar/fiyat/katsayı çağıran tarafından hesaplanır)."""
        if index < 0 or index >= len(self.satirlar):
            return None
        miktar_d = _d(miktar)
        if miktar_d <= 0:
            raise ValueError("Miktar sıfırdan büyük olmalıdır.")
        carpan_d = _d(carpan)
        if carpan_d <= 0:
            raise ValueError("Birim katsayısı sıfırdan büyük olmalıdır.")
        self._sepet_degisti()
        satir = self.satirlar[index]
        satir.birim = (birim or "Adet").strip() or "Adet"
        satir.miktar = miktar_d
        satir.birim_fiyat = _d(birim_fiyat)
        satir.carpan = carpan_d
        satir.referans_birim_fiyat = None
        return satir

    def iskonto_ayarla(
        self, index: int, iskonto_orani: Decimal | str | float | int
    ) -> SepetSatiri | None:
        if index < 0 or index >= len(self.satirlar):
            return None
        oran = _d(iskonto_orani)
        if oran < 0 or oran > 100:
            raise ValueError("İskonto oranı 0–100 arasında olmalıdır.")
        self._sepet_degisti()
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
        self._sepet_degisti()
        self.satirlar[index].kdv_orani = oran
        return self.satirlar[index]

    def sil(self, index: int) -> bool:
        if index < 0 or index >= len(self.satirlar):
            return False
        self._sepet_degisti()
        self.satirlar.pop(index)
        return True

    def toplamlar(self) -> dict[str, Decimal]:
        """Etkin fiyatlarla toplamlar; ``genel_toplam`` = son satış tutarı (Yeni Toplam).

        ``referans_toplam`` = Genel Toplam (düzeltme öncesi)."""
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
            "referans_toplam": self.referans_toplam(),
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
        return fiyat.quantize(FIYAT_HASSASIYET, rounding=ROUND_HALF_UP)

    @classmethod
    def _tam_fiyat_bul(
        cls, satir: SepetSatiri, hedef_satir_genel: Decimal, *, adim_siniri: int = 60
    ) -> Decimal | None:
        """Satır toplamını kuruşu kuruşuna ``hedef_satir_genel`` yapan birim fiyat (yoksa None)."""
        hedef = _kurus(hedef_satir_genel)
        if hedef == 0:
            return Decimal("0")
        baslangic = cls._hedef_satir_genelden_fiyat(satir, hedef)
        for k in range(adim_siniri + 1):
            for isaret in ((1,) if k == 0 else (1, -1)):
                aday = baslangic + isaret * k * FIYAT_HASSASIYET
                if aday < 0:
                    continue
                if satir.fiyatla_toplam(aday) == hedef:
                    return aday
        return None

    def hedef_toplam_uygula(self, hedef: Decimal | str | float | int) -> dict[str, Decimal]:
        """Yeni Toplamı referans satır tutarlarına orantılı dağıtır.

        Her seferinde referans fiyatlardan hesaplanır (indirim üst üste binmez);
        katsayı = Yeni Toplam / Genel Toplam; satır hedefi = referans satır × katsayı.
        Kuruş farkı en büyük referans satırdan başlayarak tam karşılanır.
        Yeni Toplam = Genel Toplam → referans fiyatlar geri gelir.
        """
        hedef_d = _kurus(_d(hedef))
        if hedef_d < 0:
            raise ValueError("Yeni toplam negatif olamaz.")
        if not self.satirlar:
            raise ValueError("Sepet boş; yeni toplam uygulanamaz.")

        referanslar = [(i, s.referans_satir_toplam) for i, s in enumerate(self.satirlar)]
        genel = _kurus(sum((r for _i, r in referanslar), Decimal("0")))

        if hedef_d == genel:
            self.duzeltmeyi_kaldir()
            return self.toplamlar()
        if genel <= 0:
            raise ValueError(
                "Genel Toplam sıfır; pozitif bir Yeni Toplam için önce geçerli "
                "referans fiyatlı ürün gerekir."
            )

        dagitilacak = [(i, r) for i, r in referanslar if r > 0]
        katsayi = hedef_d / genel
        sirali = sorted(dagitilacak, key=lambda t: (-t[1], t[0]))
        hedefler: dict[int, Decimal] = {}
        biriken = Decimal("0")
        for i, r in sirali[1:]:
            pay = _kurus(r * katsayi)
            hedefler[i] = pay
            biriken += pay
        hedefler[sirali[0][0]] = _kurus(hedef_d - biriken)

        onceki = [(s.birim_fiyat, s.referans_birim_fiyat) for s in self.satirlar]
        onceki_hedef = self.hedef_toplam
        try:
            for s in self.satirlar:
                s.birim_fiyat = s.referans_fiyat
                s.referans_birim_fiyat = None
            referans_fiyatlar = [s.birim_fiyat for s in self.satirlar]

            for i, hedef_satir in hedefler.items():
                satir = self.satirlar[i]
                if hedef_satir < 0:
                    raise ValueError("Hesaplanan satır tutarı negatif olamaz.")
                fiyat = self._tam_fiyat_bul(satir, hedef_satir)
                if fiyat is None:
                    fiyat = self._hedef_satir_genelden_fiyat(satir, hedef_satir)
                satir.birim_fiyat = fiyat

            # Kuruş farkı: önce büyük referans satırlar, satır hedefi fark kadar kaydırılır
            fark = _kurus(hedef_d - sum((s.satir_toplam for s in self.satirlar), Decimal("0")))
            if fark != 0:
                for i, _r in sirali:
                    satir = self.satirlar[i]
                    yeni_hedef = _kurus(satir.satir_toplam + fark)
                    if yeni_hedef < 0:
                        continue
                    fiyat = self._tam_fiyat_bul(satir, yeni_hedef)
                    if fiyat is not None:
                        satir.birim_fiyat = fiyat
                        fark = Decimal("0")
                        break
            if fark != 0:
                raise ValueError(
                    "Yeni Toplam satırlara kuruşu kuruşuna dağıtılamadı "
                    "(miktar/fiyat hassasiyeti). Lütfen tutarı biraz değiştirin."
                )

            for s, ref in zip(self.satirlar, referans_fiyatlar):
                s.referans_birim_fiyat = ref if _d(s.birim_fiyat) != _d(ref) else None
            if not self.duzeltme_aktif:
                self.hedef_toplam = None
            else:
                self.hedef_toplam = hedef_d
        except Exception:
            for s, (fiyat, ref) in zip(self.satirlar, onceki):
                s.birim_fiyat = fiyat
                s.referans_birim_fiyat = ref
            self.hedef_toplam = onceki_hedef
            raise
        return self.toplamlar()

    def __iter__(self) -> Iterable[SepetSatiri]:
        return iter(self.satirlar)

    def __len__(self) -> int:
        return len(self.satirlar)
