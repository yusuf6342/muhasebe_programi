"""Cari açılış bakiyesinin anlamı: cari kayıt yönü ve muhasebe karşılığı.

Kaynak yön firma defterindeki cari hesaba göredir (EvoBulut ``Bakiye : N (B|A)`` aynı):
  B = cari borçlu (cari bize borçlu), A = cari alacaklı (biz cariye borçluyuz).

Programın cari açık kalem kuralı müşteri ve tedarikçide "belge yönü"dür: müşteride satış faturası,
tedarikçide alış faturası pozitif açık kalemdir (defterde borç sütunu); tahsilat / tedarikçi ödemesi
bunları kapatır, artanı avans (negatif kalem) olur. Bu yüzden:

  Müşteri  B → pozitif kalem (açık alacağımız)      muhasebe: 120 Alıcılar BORÇ
  Müşteri  A → avans kalemi                         muhasebe: belirsiz (340 alınan avans / iade borcu)
  Tedarikçi A → pozitif kalem (açık borcumuz)       muhasebe: 320 Satıcılar ALACAK
  Tedarikçi B → avans kalemi                        muhasebe: 159 Verilen Sipariş Avansları BORÇ yalnız
                                                    gerçek avans olduğu açıkça onaylanırsa; aksi halde belirsiz

"Alacak" kelimesi tek başına avans sayılmaz. Belirsiz kayıt cari tarafta yönüyle yazılır, muhasebe
karşılığı tahmin edilmez: önizlemede "İnceleme gerekiyor" olarak açıklanır.
"""

from __future__ import annotations

from dataclasses import dataclass

CARI_BORCLU = "B"
CARI_ALACAKLI = "A"
INCELEME = "İnceleme gerekiyor"
BELIRLI = "Belirli"
AVANS_ETIKETI = "[AVANS]"


@dataclass(frozen=True)
class AcilisAnlami:
    cari_turu: str
    yon: str
    kalem_borc: bool
    hesap_anahtari: str | None
    hesap_kodu: str | None
    muhasebe_yonu: str | None
    aciklama: str

    @property
    def belirli(self) -> bool:
        return self.hesap_anahtari is not None

    @property
    def durum(self) -> str:
        return BELIRLI if self.belirli else INCELEME

    @property
    def muhasebe_metni(self) -> str:
        if not self.belirli:
            return f"{INCELEME}: {self.aciklama}"
        return f"{self.hesap_kodu} {self.muhasebe_yonu}"


def _tur(cari_turu: str | None) -> str:
    t = (cari_turu or "").strip().casefold()
    if t.startswith("tedarik"):
        return "Tedarikçi"
    if t.startswith("müşteri") or t.startswith("musteri"):
        return "Müşteri"
    return (cari_turu or "").strip() or "?"


def acilis_anlami(cari_turu: str | None, yon: str, *, avans_onayli: bool = False) -> AcilisAnlami:
    """``yon``: firma defterine göre B (cari borçlu) / A (cari alacaklı)."""
    y = (yon or "").strip().upper()[:1]
    if y not in (CARI_BORCLU, CARI_ALACAKLI):
        raise ValueError("Açılış yönü B (cari borçlu) veya A (cari alacaklı) olmalıdır.")
    tur = _tur(cari_turu)
    if tur == "Müşteri":
        if y == CARI_BORCLU:
            return AcilisAnlami(tur, y, True, "musteriler", "120", "BORÇ", "Müşterinin bize borcu")
        return AcilisAnlami(tur, y, False, None, None, None,
                            "Müşteri alacaklı: alınan avans mı, iade/fazla tahsilat borcu mu belirlenemedi")
    if tur == "Tedarikçi":
        if y == CARI_ALACAKLI:
            return AcilisAnlami(tur, y, True, "tedarikciler", "320", "ALACAK", "Tedarikçiye borcumuz")
        if avans_onayli:
            return AcilisAnlami(tur, y, False, "verilen_siparis_avanslari", "159", "BORÇ",
                                "Tedarikçiye verilen sipariş avansı (onaylı)")
        return AcilisAnlami(tur, y, False, None, None, None,
                            "Tedarikçi borçlu: gerçek avans mı, iade/fazla ödeme alacağı mı belirlenemedi")
    return AcilisAnlami(tur, y, y == CARI_BORCLU, None, None, None,
                        f"Cari türü '{tur}': açılışın muhasebe karşılığı belirlenemedi")


def kayitli_acilis_anlami(cari_turu: str | None, borc, alacak, aciklama: str | None = None) -> AcilisAnlami:
    """Kayıtlı 'Açılış' cari hareketinin (borç/alacak sütunu programın kalem yönündedir) anlamı."""
    tur = _tur(cari_turu)
    kalem_borc = (borc or 0) > 0
    if tur == "Tedarikçi":
        yon = CARI_ALACAKLI if kalem_borc else CARI_BORCLU
    else:
        yon = CARI_BORCLU if kalem_borc else CARI_ALACAKLI
    return acilis_anlami(cari_turu, yon, avans_onayli=AVANS_ETIKETI in (aciklama or ""))


__all__ = [
    "AVANS_ETIKETI",
    "AcilisAnlami",
    "BELIRLI",
    "CARI_ALACAKLI",
    "CARI_BORCLU",
    "INCELEME",
    "acilis_anlami",
    "kayitli_acilis_anlami",
]
