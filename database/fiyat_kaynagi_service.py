"""Evrak satırına otomatik fiyat ve geçmiş alış fiyatları (salt okunur).

Yeni bir fiyat motoru değildir: kayıtlı alış faturası satırlarını, stok kartı
fiyatlarını (``StokService.birim_fiyati_getir``), birim katsayılarını
(``StokService._birim_carpani_zorunlu``) ve kur çevirisini
(``fatura_satir_birim_service.fiyat_cevir``) bir araya getirir.

Kurallar:
- Kaynak yalnız kaydedilmiş ve iptal edilmemiş alış faturalarıdır; iade ayrı tür.
- Fiyat tahmin edilmez: kur veya birim katsayısı eksikse sonuç ``fiyat=None`` ve uyarı.
- Hiçbir fonksiyon veri yazmaz.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP

from sqlalchemy import func, select

from database.database import get_session

DORT = Decimal("0.0001")

KAYNAK_TEDARIKCI = "SON_ALIS_TEDARIKCI"
KAYNAK_DIGER = "SON_ALIS_DIGER"
KAYNAK_KART_ALIS = "KART_ALIS"
KAYNAK_KART_SATIS = "KART_SATIS"
KAYNAK_YOK = "YOK"


def _d(deger, varsayilan: str = "0") -> Decimal:
    if deger is None or deger == "":
        return Decimal(varsayilan)
    try:
        return Decimal(str(deger).replace(",", "."))
    except (InvalidOperation, ValueError):
        return Decimal(varsayilan)


def _pb(deger) -> str:
    kod = (str(deger or "").strip() or "TRY").upper()
    return "TRY" if kod in ("TL", "TRY", "YTL") else kod


def _tarih_metni(t) -> str:
    return t.strftime("%d.%m.%Y") if t else ""


def net_iskontolu(fiyat: Decimal, i1=0, i2=0, i3=0) -> Decimal:
    n = _d(fiyat)
    for oran in (_d(i1), _d(i2), _d(i3)):
        if oran:
            n = n * (Decimal("1") - oran / Decimal("100"))
    return n.quantize(DORT, rounding=ROUND_HALF_UP)


@dataclass
class FiyatSonucu:
    fiyat: Decimal | None
    kaynak: str = KAYNAK_YOK
    aciklama: str = ""
    uyari: str | None = None
    tarih: date | None = None
    belge_no: str = ""
    tedarikci: str = ""
    baska_tedarikci: bool = False
    para_birimi: str = "TRY"
    ekler: dict = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Geçmiş alış fiyatları
# ---------------------------------------------------------------------------

def _fatura_sorgusu(urun_kodu, *, cari_id=None, tarih_bas=None, tarih_bit=None, haric_fatura_id=None):
    from database.models.alis_faturasi import AlisFaturasi, AlisFaturasiSatiri
    from database.models.cari import Cari

    q = (
        select(AlisFaturasiSatiri, AlisFaturasi, Cari.unvan)
        .join(AlisFaturasi, AlisFaturasi.id == AlisFaturasiSatiri.fatura_id)
        .join(Cari, Cari.id == AlisFaturasi.cari_id)
        .where(AlisFaturasiSatiri.urun_kodu == urun_kodu, AlisFaturasi.durum != "İPTAL")
    )
    if cari_id:
        q = q.where(AlisFaturasi.cari_id == int(cari_id))
    if tarih_bas:
        q = q.where(AlisFaturasi.fatura_tarihi >= tarih_bas)
    if tarih_bit:
        q = q.where(AlisFaturasi.fatura_tarihi <= tarih_bit)
    if haric_fatura_id:
        q = q.where(AlisFaturasi.id != int(haric_fatura_id))
    return q.order_by(
        AlisFaturasi.fatura_tarihi.desc(),
        func.coalesce(AlisFaturasi.islem_saati, "").desc(),
        AlisFaturasi.id.desc(),
        AlisFaturasiSatiri.id.desc(),
    )


def _iade_sorgusu(urun_kodu, *, cari_id=None, tarih_bas=None, tarih_bit=None):
    from database.models.alis_iade_faturasi import AlisIadeFaturasi, AlisIadeFaturasiSatiri
    from database.models.cari import Cari

    q = (
        select(AlisIadeFaturasiSatiri, AlisIadeFaturasi, Cari.unvan)
        .join(AlisIadeFaturasi, AlisIadeFaturasi.id == AlisIadeFaturasiSatiri.iade_id)
        .join(Cari, Cari.id == AlisIadeFaturasi.cari_id)
        .where(
            AlisIadeFaturasiSatiri.urun_kodu == urun_kodu,
            AlisIadeFaturasi.durum.notin_(("İPTAL", "TASLAK")),
        )
    )
    if cari_id:
        q = q.where(AlisIadeFaturasi.cari_id == int(cari_id))
    if tarih_bas:
        q = q.where(AlisIadeFaturasi.iade_tarihi >= tarih_bas)
    if tarih_bit:
        q = q.where(AlisIadeFaturasi.iade_tarihi <= tarih_bit)
    return q.order_by(
        AlisIadeFaturasi.iade_tarihi.desc(), AlisIadeFaturasi.id.desc(), AlisIadeFaturasiSatiri.id.desc()
    )


def _satir_kaydi(satir, belge, unvan, *, tur: str) -> dict:
    """Satırı belgede kaydedildiği haliyle (birim, para birimi, iskonto) döndürür."""
    pb = _pb(getattr(belge, "para_birimi", None))
    kur = _d(getattr(belge, "kur", None), "1")
    tl_fiyat = _d(satir.birim_fiyat)
    if pb != "TRY":
        brut = _d(getattr(satir, "birim_fiyat_doviz", None))
        if brut <= 0 and kur > 0:
            brut = (tl_fiyat / kur).quantize(DORT)
    else:
        brut = tl_fiyat
    i1 = _d(satir.iskonto_orani)
    i2 = _d(getattr(satir, "iskonto_orani_2", 0))
    i3 = _d(getattr(satir, "iskonto_orani_3", 0))
    tarih = belge.fatura_tarihi if tur == "ALIŞ" else belge.iade_tarihi
    belge_no = belge.fatura_no if tur == "ALIŞ" else belge.iade_no
    return {
        "tur": tur,
        "belge_id": belge.id,
        "satir_id": satir.id,
        "tarih": tarih,
        "saat": getattr(belge, "islem_saati", None) or "",
        "belge_no": belge_no,
        "tedarikci_fatura_no": getattr(belge, "tedarikci_fatura_no", None) or "",
        "cari_id": belge.cari_id,
        "tedarikci": unvan or "",
        "miktar": _d(satir.miktar),
        "birim": (satir.birim or "").strip(),
        "birim_carpani": _d(satir.birim_carpani) if satir.birim_carpani else None,
        "brut_fiyat": brut,
        "para_birimi": pb,
        "kur": kur,
        "iskonto_1": i1,
        "iskonto_2": i2,
        "iskonto_3": i3,
        "net_fiyat": net_iskontolu(brut, i1, i2, i3),
        "net_fiyat_tl": net_iskontolu(tl_fiyat, i1, i2, i3),
        "kdv_orani": _d(satir.kdv_orani),
        "kdv_durumu": "HARİÇ",
    }


def alis_fiyat_gecmisi(
    urun_kodu: str,
    *,
    cari_id: int | None = None,
    tarih_bas: date | None = None,
    tarih_bit: date | None = None,
    iade_dahil: bool = False,
    limit: int = 50,
    offset: int = 0,
) -> dict:
    """Ürünün geçmiş alış satırları (en yeni önce). ``cari_id`` verilirse yalnız o tedarikçi.

    Dönüş: {"kayitlar": [...], "toplam": int, "daha_var": bool}
    """
    kod = (urun_kodu or "").strip()
    if not kod:
        return {"kayitlar": [], "toplam": 0, "daha_var": False}
    limit = max(1, int(limit))
    offset = max(0, int(offset))
    with get_session() as session:
        fq = _fatura_sorgusu(kod, cari_id=cari_id, tarih_bas=tarih_bas, tarih_bit=tarih_bit)
        toplam = session.scalar(select(func.count()).select_from(fq.order_by(None).subquery())) or 0
        if not iade_dahil:
            satirlar = session.execute(fq.limit(limit + 1).offset(offset)).all()
            kayitlar = [_satir_kaydi(s, b, u, tur="ALIŞ") for s, b, u in satirlar]
        else:
            iq = _iade_sorgusu(kod, cari_id=cari_id, tarih_bas=tarih_bas, tarih_bit=tarih_bit)
            toplam += session.scalar(select(func.count()).select_from(iq.order_by(None).subquery())) or 0
            # İki kaynak tarih sırasıyla birleştirilir; sayfa için ilk (offset+limit+1) yeterli
            n = offset + limit + 1
            kayitlar = [_satir_kaydi(s, b, u, tur="ALIŞ") for s, b, u in session.execute(fq.limit(n)).all()]
            kayitlar += [_satir_kaydi(s, b, u, tur="İADE") for s, b, u in session.execute(iq.limit(n)).all()]
            kayitlar.sort(key=lambda k: (k["tarih"], k["saat"], k["belge_id"], k["satir_id"]), reverse=True)
            kayitlar = kayitlar[offset:offset + limit + 1]
    daha_var = len(kayitlar) > limit
    return {"kayitlar": kayitlar[:limit], "toplam": int(toplam), "daha_var": daha_var}


# ---------------------------------------------------------------------------
# Otomatik alış fiyatı
# ---------------------------------------------------------------------------

def _kart_carpani(stok, birim: str) -> Decimal:
    from database.stok_service import StokService

    return StokService._birim_carpani_zorunlu(stok, birim, getattr(stok, "birim", None) or "Adet")


def _birim_cevir(fiyat: Decimal, kaynak_carpan: Decimal, stok, hedef_birim: str, kaynak_birim: str):
    from database.stok_service import birim_anahtari

    if birim_anahtari(kaynak_birim) == birim_anahtari(hedef_birim):
        return fiyat
    hedef_c = _kart_carpani(stok, hedef_birim)
    if not kaynak_carpan or kaynak_carpan <= 0:
        kaynak_carpan = _kart_carpani(stok, kaynak_birim)
    return (fiyat / kaynak_carpan * hedef_c).quantize(DORT, rounding=ROUND_HALF_UP)


def _gecmis_fiyati_cevir(kayit: dict, stok, birim: str, belge_pb: str, belge_kur) -> tuple[Decimal | None, str | None]:
    """Geçmiş satır netini hedef birime ve belge para birimine çevirir; yapamazsa (None, uyarı)."""
    from database.stok_service import BirimDonusumHatasi

    hedef_pb = _pb(belge_pb)
    kaynak_pb = kayit["para_birimi"]
    if hedef_pb == kaynak_pb:
        fiyat = kayit["net_fiyat"]
    elif hedef_pb == "TRY":
        fiyat = kayit["net_fiyat_tl"]
    else:
        kur = _d(belge_kur)
        if kur <= 0:
            return None, f"Belge kuru ({hedef_pb}) girilmemiş; geçmiş alış fiyatı çevrilemedi."
        fiyat = (kayit["net_fiyat_tl"] / kur).quantize(DORT, rounding=ROUND_HALF_UP)
    if stok is None:
        return fiyat, None
    try:
        return _birim_cevir(fiyat, kayit["birim_carpani"], stok, birim, kayit["birim"]), None
    except BirimDonusumHatasi as hata:
        return None, str(hata)


def _kart_alis_fiyati(stok, birim, belge_pb, belge_kur, belge_tarihi, kdv_orani) -> FiyatSonucu:
    from database.stok_service import BirimDonusumHatasi, StokService
    from database.hizli_satis_satir_service import kdv_dahilden_net, kdv_durumu_normalle
    from fatura_satir_birim_service import fiyat_cevir

    kayit = next(
        (f for f in getattr(stok, "fiyatlar", None) or []
         if (f.fiyat_adi or "").strip().upper() == "ALIŞ FİYATI"),
        None,
    )
    try:
        fiyat = StokService.birim_fiyati_getir(stok, birim, alis=True)
    except Exception:
        fiyat = None
    if (fiyat is None or _d(fiyat) <= 0) and kayit is not None and _d(kayit.tutar) > 0:
        try:
            fiyat = (_d(kayit.tutar) * _kart_carpani(stok, birim)).quantize(DORT)
        except BirimDonusumHatasi as hata:
            return FiyatSonucu(None, KAYNAK_YOK, uyari=str(hata))
    if fiyat is None or _d(fiyat) <= 0:
        return FiyatSonucu(None, KAYNAK_YOK)
    fiyat = _d(fiyat)
    notlar = []
    kdv_d = kdv_durumu_normalle(getattr(kayit, "kdv_durumu", None)) if kayit is not None else None
    if kdv_d == "DAHIL":
        if kdv_orani is None:
            return FiyatSonucu(None, KAYNAK_YOK, uyari="Kart alış fiyatı KDV dahil; KDV oranı bilinmiyor.")
        fiyat = kdv_dahilden_net(fiyat, kdv_orani)
        notlar.append("KDV dahil karttan hariçe çevrildi")
    kart_pb = _pb(getattr(kayit, "para_birimi", None) if kayit is not None else "TRY")
    hedef_pb = _pb(belge_pb)
    if kart_pb != hedef_pb:
        kur = _d(belge_kur)
        if hedef_pb != "TRY" and kur <= 0:
            return FiyatSonucu(None, KAYNAK_YOK, uyari=f"Belge kuru ({hedef_pb}) girilmemiş; kart alış fiyatı çevrilemedi.")
        try:
            fiyat = fiyat_cevir(
                fiyat, kart_pb, hedef_pb,
                kurlar={hedef_pb: kur} if hedef_pb != "TRY" else None,
                tarih=belge_tarihi,
            )
        except ValueError as hata:
            return FiyatSonucu(None, KAYNAK_YOK, uyari=f"Kart alış fiyatı {kart_pb}: {hata}")
        notlar.append(f"{kart_pb}→{hedef_pb}")
    aciklama = "Stok kartı alış fiyatı" + (f" ({', '.join(notlar)})" if notlar else "")
    return FiyatSonucu(fiyat, KAYNAK_KART_ALIS, aciklama=aciklama, para_birimi=hedef_pb)


def son_alis_fiyati_getir(
    urun_kodu: str,
    birim: str,
    *,
    cari_id: int | None = None,
    belge_tarihi: date | None = None,
    belge_pb: str = "TRY",
    belge_kur=None,
    haric_fatura_id: int | None = None,
    kdv_orani=None,
) -> FiyatSonucu:
    """Alış evrakı satırı için fiyat (KDV hariç, iskontolu net, belge birimi ve para birimi).

    Öncelik: aynı tedarikçinin son alışı → başka tedarikçinin son alışı → kart alış fiyatı → boş.
    """
    from fatura_satir_birim_service import _stok_yukle

    kod = (urun_kodu or "").strip()
    if not kod:
        return FiyatSonucu(None, KAYNAK_YOK, uyari="Ürün seçilmedi.")
    birim = (birim or "").strip()
    tarih = belge_tarihi or date.today()
    stok = _stok_yukle(kod)
    if stok is not None and not birim:
        birim = stok.birim or "Adet"
    uyarilar: list[str] = []

    adaylar = []
    with get_session() as session:
        if cari_id:
            r = session.execute(
                _fatura_sorgusu(kod, cari_id=cari_id, tarih_bit=tarih, haric_fatura_id=haric_fatura_id).limit(1)
            ).first()
            if r:
                adaylar.append((r, False))
        if not adaylar:
            r = session.execute(
                _fatura_sorgusu(kod, tarih_bit=tarih, haric_fatura_id=haric_fatura_id).limit(1)
            ).first()
            if r:
                adaylar.append((r, bool(cari_id) and r[1].cari_id != int(cari_id)))
        kayitlar = [(_satir_kaydi(*r, tur="ALIŞ"), baska) for r, baska in adaylar]

    for kayit, baska in kayitlar:
        fiyat, uyari = _gecmis_fiyati_cevir(kayit, stok, birim, belge_pb, belge_kur)
        if fiyat is None:
            uyarilar.append(uyari or "")
            continue
        if not cari_id:
            ek = " · tedarikçi seçilmedi"
        elif baska:
            ek = " · başka tedarikçi"
        else:
            ek = ""
        aciklama = (
            f"Son alış {_tarih_metni(kayit['tarih'])} · {kayit['tedarikci']} · {kayit['belge_no']}{ek}"
        )
        return FiyatSonucu(
            fiyat,
            KAYNAK_DIGER if (baska or not cari_id) else KAYNAK_TEDARIKCI,
            aciklama=aciklama,
            tarih=kayit["tarih"],
            belge_no=kayit["belge_no"],
            tedarikci=kayit["tedarikci"],
            baska_tedarikci=bool(baska or not cari_id),
            para_birimi=_pb(belge_pb),
            ekler={"kayit": kayit},
        )

    if stok is not None:
        kart = _kart_alis_fiyati(stok, birim, belge_pb, belge_kur, tarih, kdv_orani)
        if kart.fiyat is not None:
            if uyarilar:
                kart.uyari = "; ".join(u for u in uyarilar if u)
            return kart
        if kart.uyari:
            uyarilar.append(kart.uyari)
    uyari = "; ".join(u for u in uyarilar if u) or None
    return FiyatSonucu(
        None, KAYNAK_YOK,
        aciklama="Geçmiş alış ve kart alış fiyatı yok; birim fiyatı girin.",
        uyari=uyari,
        para_birimi=_pb(belge_pb),
    )


# ---------------------------------------------------------------------------
# Otomatik satış fiyatı (fiyat listesi; son satış/alış fiyatı kullanılmaz)
# ---------------------------------------------------------------------------

def satis_fiyat_kaydi(urun_kodu: str, *, musteri=None):
    """``birim_satis_fiyati`` ile aynı liste seçimindeki kart fiyat kaydı (KDV durumu, PB için)."""
    from fatura_satir_birim_service import _stok_yukle, musteri_fiyat_adi
    from database.stok_service import ESKI_FIYAT_ESLEME

    stok = _stok_yukle(urun_kodu)
    if stok is None:
        return None
    hedef = (musteri_fiyat_adi(musteri) or "SATIŞ FİYATI 1").strip().upper()
    hedef = ESKI_FIYAT_ESLEME.get(hedef, hedef).upper()
    fiyatlar = list(getattr(stok, "fiyatlar", None) or [])
    for aday in (hedef, "SATIŞ FİYATI 1"):
        for f in fiyatlar:
            if (f.fiyat_adi or "").strip().upper() == aday:
                return f
    return None


def satis_kdv_haric(urun_kodu: str, fiyat, kdv_orani, *, musteri=None) -> tuple[Decimal, str | None]:
    """Fiyat listesi KDV dahil tanımlıysa satır motorunun beklediği hariç fiyata çevirir."""
    from database.hizli_satis_satir_service import kdv_dahilden_net, kdv_durumu_normalle

    deger = _d(fiyat)
    if deger <= 0:
        return deger, None
    kayit = satis_fiyat_kaydi(urun_kodu, musteri=musteri)
    if kayit is None or kdv_durumu_normalle(getattr(kayit, "kdv_durumu", None)) != "DAHIL":
        return deger, None
    if kdv_orani is None:
        return deger, "Fiyat KDV dahil tanımlı; KDV oranı bilinmediği için çevrilmedi."
    return kdv_dahilden_net(deger, kdv_orani), "KDV dahil liste fiyatı hariçe çevrildi"
