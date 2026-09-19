"""Satış faturası satır — miktar/birim düzenleme ve birim dönüşüm hesapları.

UI yalnızca sonucu gösterir; hesaplar burada (Decimal).
"""

from __future__ import annotations

from decimal import Decimal, InvalidOperation
from types import SimpleNamespace
from typing import Any

from database.stok_service import StokService


def miktar_metnini_coz(metin: str) -> Decimal:
    """TR/EN ondalık: 1,5 / 1.5 / 10,25. Sıfır ve negatif reddedilir."""
    ham = (metin or "").strip()
    if not ham:
        raise ValueError("Miktar boş olamaz.")
    if "," in ham and "." in ham:
        if ham.rfind(",") > ham.rfind("."):
            ham = ham.replace(".", "").replace(",", ".")
        else:
            ham = ham.replace(",", "")
    elif "," in ham:
        ham = ham.replace(".", "").replace(",", ".")
    try:
        deger = Decimal(ham)
    except (InvalidOperation, ValueError) as exc:
        raise ValueError("Geçerli bir miktar girin.") from exc
    if deger <= 0:
        raise ValueError("Miktar sıfırdan büyük olmalıdır.")
    return deger.quantize(Decimal("0.000001"))


def stok_aktif_birimleri(urun_kodu: str) -> list[str]:
    """Kart ana birimi + tanımlı aktif alternatif birimler (sıralı, tekrarsız)."""
    stok = _stok_yukle(urun_kodu)
    if stok is None:
        return ["Adet"]
    ana = (getattr(stok, "birim", None) or "Adet").strip() or "Adet"
    sonuc = [ana]
    for b in getattr(stok, "birimler", None) or []:
        if getattr(b, "aktif", True) is False:
            continue
        ad = (getattr(b, "birim_adi", None) or "").strip()
        if not ad:
            continue
        if ad.casefold() == ana.casefold():
            continue
        if ad not in sonuc:
            sonuc.append(ad)
    return sonuc


def _stok_yukle(urun_kodu: str):
    """Stok kartını birimler/fiyatlarla birlikte yükler (session dışı güvenli kopya)."""
    kod = (urun_kodu or "").strip()
    if not kod:
        return None
    try:
        from sqlalchemy.orm import selectinload
        from sqlalchemy import select
        from database.database import get_session
        from database.models.stok import StokKarti

        with get_session() as session:
            stok = session.scalar(
                select(StokKarti)
                .where(StokKarti.stok_kodu == kod)
                .options(
                    selectinload(StokKarti.birimler),
                    selectinload(StokKarti.fiyatlar),
                )
            )
            if stok is None:
                return None
            # DetachedInstanceError önlemek için değerleri kopyala
            birimler = []
            for b in stok.birimler or []:
                birimler.append(
                    SimpleNamespace(
                        birim_adi=b.birim_adi,
                        carpan=b.carpan,
                        aktif=getattr(b, "aktif", True),
                        fiyat_modu=getattr(b, "fiyat_modu", "manuel"),
                        alis_fiyati=getattr(b, "alis_fiyati", None),
                        **{
                            f"satis_{i}": getattr(b, f"satis_{i}", None)
                            for i in range(1, 11)
                        },
                    )
                )
            fiyatlar = [
                SimpleNamespace(fiyat_adi=f.fiyat_adi, tutar=f.tutar)
                for f in (stok.fiyatlar or [])
            ]
            return SimpleNamespace(
                stok_kodu=stok.stok_kodu,
                birim=stok.birim or "Adet",
                birimler=birimler,
                fiyatlar=fiyatlar,
            )
    except Exception:
        return None


def musteri_fiyat_adi(musteri) -> str | None:
    try:
        from hizli_satis_musteri import fiyat_listesi_coz

        return fiyat_listesi_coz(
            satis_fiyat_listesi=getattr(musteri, "satis_fiyat_listesi", None),
            musteri_grubu=getattr(musteri, "musteri_grubu", None),
        )
    except Exception:
        return None


def birim_satis_fiyati(
    urun_kodu: str,
    birim: str,
    *,
    musteri=None,
    varsayilan: Decimal | None = None,
) -> Decimal | None:
    """Seçilen birim için satış fiyatı (manuel birim fiyat veya oto×çarpan)."""
    stok = _stok_yukle(urun_kodu)
    if stok is None:
        return varsayilan
    fiyat_adi = musteri_fiyat_adi(musteri) or "SATIŞ FİYATI 1"
    try:
        fiyat = StokService.birim_fiyati_getir(stok, birim, fiyat_adi=fiyat_adi)
    except Exception:
        fiyat = None
    if fiyat is not None:
        return fiyat
    # Temel kart fiyatı × çarpan
    try:
        temel = StokService.satis_fiyati_adi_ile(
            urun_kodu, fiyat_adi, varsayilan=varsayilan or Decimal("0")
        )
    except Exception:
        temel = varsayilan or Decimal("0")
    ana = (getattr(stok, "birim", None) or "Adet").strip()
    carpan = StokService.birim_carpani(stok, birim, ana)
    if carpan == 1:
        return Decimal(str(temel)) if temel is not None else varsayilan
    return (Decimal(str(temel)) * carpan).quantize(Decimal("0.0001"))


def fiyat_birim_donustur(
    eski_fiyat: Decimal,
    eski_birim: str,
    yeni_birim: str,
    urun_kodu: str,
) -> Decimal:
    """Aynı mal bedeli: eski birim fiyatını yeni birime çevir."""
    stok = _stok_yukle(urun_kodu)
    ana = (getattr(stok, "birim", None) or "Adet") if stok else "Adet"
    eski_c = StokService.birim_carpani(stok or [], eski_birim, ana)
    yeni_c = StokService.birim_carpani(stok or [], yeni_birim, ana)
    if eski_c <= 0:
        eski_c = Decimal("1")
    return (Decimal(str(eski_fiyat)) * (yeni_c / eski_c)).quantize(Decimal("0.0001"))


def miktar_birim_donustur(
    eski_miktar: Decimal,
    eski_birim: str,
    yeni_birim: str,
    urun_kodu: str,
) -> Decimal:
    """Aynı fiziksel miktarı yeni birimde ifade et."""
    stok = _stok_yukle(urun_kodu)
    ana = (getattr(stok, "birim", None) or "Adet") if stok else "Adet"
    oniz = StokService.birim_donusum_onizleme(
        eski_miktar, eski_birim, yeni_birim, stok or [], ana
    )
    return Decimal(str(oniz["hedef_miktar"]))


def temel_miktar(miktar, birim: str, urun_kodu: str) -> Decimal:
    stok = _stok_yukle(urun_kodu)
    ana = (getattr(stok, "birim", None) or "Adet") if stok else "Adet"
    return StokService.temel_miktara_cevir(miktar, birim, stok or [], ana)


def birim_degistir(
    satir: dict[str, Any],
    yeni_birim: str,
    *,
    musteri=None,
    manuel_fiyat_modu: str = "yeniden",  # yeniden | koru | iptal
) -> dict[str, Any] | None:
    """Satır birimini değiştir; miktar/fiyatı tutarlı güncelle.

    manuel_fiyat_modu:
      yeniden — birim fiyatını yeni birime göre hesapla
      koru — miktarı dönüştür, birim fiyatını olduğu gibi bırak (dikkat: birim etiketli)
      iptal — None döner
    """
    if manuel_fiyat_modu == "iptal":
        return None
    kod = (satir.get("urun_kodu") or "").strip()
    eski_birim = (satir.get("birim") or "Adet").strip() or "Adet"
    yeni_birim = (yeni_birim or "").strip() or eski_birim
    if yeni_birim.casefold() == eski_birim.casefold():
        return dict(satir)

    try:
        eski_miktar = Decimal(str(satir.get("miktar") or 0))
    except Exception:
        eski_miktar = Decimal("0")
    try:
        eski_fiyat = Decimal(str(satir.get("birim_satis_fiyati") or 0))
    except Exception:
        eski_fiyat = Decimal("0")

    yeni_miktar = miktar_birim_donustur(eski_miktar, eski_birim, yeni_birim, kod)
    if yeni_miktar <= 0 and eski_miktar > 0:
        # Çok küçük dönüşüm — en az bir kuantum
        yeni_miktar = Decimal("0.000001")

    sonuc = dict(satir)
    sonuc["birim"] = yeni_birim
    sonuc["miktar"] = str(yeni_miktar)
    sonuc["temel_miktar"] = str(temel_miktar(yeni_miktar, yeni_birim, kod))

    manuel = bool(satir.get("manuel_fiyat"))
    if manuel and manuel_fiyat_modu == "koru":
        # Fiyat aynı kalır; hangi birime ait olduğu satır birimi ile işaretli
        sonuc["birim_satis_fiyati"] = str(eski_fiyat)
        sonuc["manuel_fiyat"] = True
        sonuc["manuel_fiyat_birim"] = yeni_birim
    else:
        # Önce birime özel fiyat; yoksa dönüştürülmüş fiyat
        yeni_fiyat = birim_satis_fiyati(kod, yeni_birim, musteri=musteri)
        if yeni_fiyat is None:
            yeni_fiyat = fiyat_birim_donustur(eski_fiyat, eski_birim, yeni_birim, kod)
        sonuc["birim_satis_fiyati"] = str(yeni_fiyat)
        sonuc["manuel_fiyat"] = False
        sonuc.pop("manuel_fiyat_birim", None)
    return sonuc


def satir_temel_talep(satir: dict) -> Decimal:
    """Stok kontrolü için satırın temel birim miktarı."""
    kod = (satir.get("urun_kodu") or "").strip()
    birim = (satir.get("birim") or "Adet").strip()
    try:
        m = Decimal(str(satir.get("miktar") or 0))
    except Exception:
        m = Decimal("0")
    kayitli = satir.get("temel_miktar")
    if kayitli not in (None, ""):
        try:
            return Decimal(str(kayitli))
        except Exception:
            pass
    return temel_miktar(m, birim, kod)


def satir_hesap_ozeti(
    satir: dict,
    *,
    kdv_dahil: bool = True,
) -> dict[str, Decimal]:
    """Satır brüt / iskonto / KDV matrahı / KDV / net — Decimal (UI dışı)."""
    from database.satis_faturasi_service import SatisFaturasiService

    try:
        miktar = Decimal(str(satir.get("miktar") or 0))
    except Exception:
        miktar = Decimal("0")
    try:
        fiyat = Decimal(str(satir.get("birim_satis_fiyati") or satir.get("birim_fiyat") or 0))
    except Exception:
        fiyat = Decimal("0")
    try:
        kdv_oran = Decimal(str(satir.get("kdv_orani") or 0))
    except Exception:
        kdv_oran = Decimal("0")
    brut, iskonto, matrah = SatisFaturasiService._satir_net(
        miktar,
        fiyat,
        satir.get("iskonto_orani") or 0,
        satir.get("iskonto_orani_2") or 0,
        satir.get("iskonto_orani_3") or 0,
    )
    kdv_tutar = (matrah * kdv_oran / Decimal("100")).quantize(Decimal("0.0001"))
    net = matrah + kdv_tutar if kdv_dahil else matrah
    return {
        "brut": brut,
        "iskonto": iskonto,
        "matrah": matrah,
        "kdv": kdv_tutar,
        "net": net,
        "temel": satir_temel_talep(satir),
    }
