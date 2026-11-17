"""Cari kredi notu (yıldız / dolandırıcı) — firma geneli limit eşlemesi.

Açık hesap risk limitini yönetir; borç/alacak, fatura veya stok hareketi üretmez.
"""

from __future__ import annotations

from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from typing import Any

from sqlalchemy import select

KURUS = Decimal("0.01")

NOT_BOS = ""
NOT_YILDIZ = ("*", "**", "***", "****")
NOT_DOLANDIRICI = "-"
GECERLI_NOTLAR = frozenset({NOT_BOS, *NOT_YILDIZ, NOT_DOLANDIRICI})

# Firma ayarı anahtarları (cari_risk_ayarlari)
AYAR_ANAHTAR = {
    "*": "kredi_notu_limit_1",
    "**": "kredi_notu_limit_2",
    "***": "kredi_notu_limit_3",
    "****": "kredi_notu_limit_4",
}
VARSAYILAN_LIMITLER = {
    "*": Decimal("15000.00"),
    "**": Decimal("30000.00"),
    "***": Decimal("90000.00"),
    "****": Decimal("360000.00"),
}

CERCIVE_RENK = {
    NOT_BOS: None,
    "*": "#FACC15",
    "**": "#F97316",
    "***": "#22C55E",
    "****": "#14B8A6",
    NOT_DOLANDIRICI: "#EF4444",
}

NOT_ETIKET = {
    NOT_BOS: "Boş (manuel limit)",
    "*": "* — 1 yıldız",
    "**": "** — 2 yıldız",
    "***": "*** — 3 yıldız",
    "****": "**** — 4 yıldız",
    NOT_DOLANDIRICI: "- — Dolandırıcı olarak işaretli",
}


def _kurus(deger) -> Decimal:
    return Decimal(str(deger or 0)).quantize(KURUS, rounding=ROUND_HALF_UP)


def not_normalize(ham) -> str:
    """Boş / yıldız / - ; bilinmeyen eski içerik boş gibi işlenir (silinmez)."""
    if ham is None:
        return NOT_BOS
    s = str(ham).strip()
    if not s:
        return NOT_BOS
    # Klavyeden gelen yıldız / tire
    if s in GECERLI_NOTLAR:
        return s
    # "1".."4" kısayolu
    if s in {"1", "2", "3", "4"}:
        return "*" * int(s)
    # Bilinmeyen: boş gibi davran (eski içeriği burada silmeyiz)
    return NOT_BOS


def not_bilinmeyen_mi(ham) -> bool:
    if ham is None or str(ham).strip() == "":
        return False
    return str(ham).strip() not in GECERLI_NOTLAR


def cerceve_rengi(notu: str | None) -> str | None:
    n = not_normalize(notu)
    if not_bilinmeyen_mi(notu):
        return None
    return CERCIVE_RENK.get(n)


def _para_coz(ham) -> Decimal:
    from tutar_bicim import tutar_coz

    try:
        d = _kurus(tutar_coz(ham))
    except (ValueError, InvalidOperation, TypeError) as hata:
        raise ValueError("Limit tutarı geçerli bir para değeri olmalıdır.") from hata
    return d


def limitler_dogrula(limitler: dict[str, Decimal]) -> dict[str, Decimal]:
    """Dört yıldız limiti pozitif ve artan sırada olmalı."""
    temiz: dict[str, Decimal] = {}
    onceki = None
    for yildiz in NOT_YILDIZ:
        if yildiz not in limitler:
            raise ValueError(f"{yildiz} limiti eksik.")
        tutar = _kurus(limitler[yildiz])
        if tutar <= 0:
            raise ValueError(f"{yildiz} limiti pozitif olmalıdır.")
        if onceki is not None and tutar <= onceki:
            raise ValueError(
                f"Yıldız limitleri artan sırada olmalı ({yildiz} > önceki seviye)."
            )
        temiz[yildiz] = tutar
        onceki = tutar
    return temiz


def yildiz_limitlerini_getir(session=None) -> dict[str, Decimal]:
    """Firma geneli yıldız limitleri; ilk okumada varsayılanları yazar (yalnız eksik anahtar)."""
    from database.models.cari_risk import CariRiskAyari

    def _oku(s) -> dict[str, Decimal]:
        from database.cari_risk_service import _tablolari_garanti

        _tablolari_garanti(s)
        sonuc = dict(VARSAYILAN_LIMITLER)
        eksik_yaz = []
        for yildiz, anahtar in AYAR_ANAHTAR.items():
            kayit = s.get(CariRiskAyari, anahtar)
            if kayit is None or kayit.deger is None or str(kayit.deger).strip() == "":
                eksik_yaz.append((anahtar, str(VARSAYILAN_LIMITLER[yildiz])))
            else:
                try:
                    sonuc[yildiz] = _kurus(kayit.deger)
                except Exception:
                    sonuc[yildiz] = VARSAYILAN_LIMITLER[yildiz]
        for anahtar, deger in eksik_yaz:
            s.add(CariRiskAyari(anahtar=anahtar, deger=deger))
        if eksik_yaz:
            s.flush()
        return sonuc

    if session is not None:
        return _oku(session)
    from database.database import get_session

    with get_session() as s:
        return _oku(s)


def yildiz_limitlerini_kaydet(limitler: dict[str, Any]) -> dict[str, Any]:
    """Firma geneli dört limiti kaydeder; ilgili yıldızlı carilerin açık hesap limitini günceller."""
    from database.access import yetki_zorunlu
    from database.cari_risk_service import IZIN_LIMIT, _gecmis_yaz, _tablolari_garanti
    from database.database import get_session
    from database.models.cari import Cari
    from database.models.cari_risk import CariRiskAyari

    yetki_zorunlu("sistem_ayarlari", IZIN_LIMIT, mesaj="Yıldız limitlerini değiştirme yetkiniz yok.")
    ham = {}
    for y in NOT_YILDIZ:
        if y not in limitler:
            raise ValueError(f"{y} limiti girilmelidir.")
        ham[y] = _para_coz(limitler[y])
    temiz = limitler_dogrula(ham)

    with get_session() as s:
        _tablolari_garanti(s)
        eski = yildiz_limitlerini_getir(s)
        for yildiz, tutar in temiz.items():
            anahtar = AYAR_ANAHTAR[yildiz]
            kayit = s.get(CariRiskAyari, anahtar)
            if kayit is None:
                s.add(CariRiskAyari(anahtar=anahtar, deger=str(tutar)))
            else:
                kayit.deger = str(tutar)
        etkilenen = 0
        for yildiz, tutar in temiz.items():
            if eski.get(yildiz) == tutar:
                continue
            cariler = list(
                s.scalars(
                    select(Cari).where(
                        Cari.kredi_notu == yildiz,
                        Cari.is_deleted.is_(False),
                    )
                ).all()
            )
            for cari in cariler:
                eski_limit = getattr(cari, "acik_hesap_risk_limiti", None)
                if eski_limit != tutar:
                    cari.acik_hesap_risk_limiti = tutar
                    cari.acik_hesap_limit_uygula = True
                    _gecmis_yaz(
                        s,
                        int(cari.id),
                        "acik_hesap_risk_limiti",
                        eski_limit,
                        tutar,
                    )
                    etkilenen += 1
            _gecmis_yaz(s, 0, AYAR_ANAHTAR[yildiz], eski.get(yildiz), tutar)
        s.flush()
        return {"limitler": temiz, "etkilenen_hesap": etkilenen}


def hesaplanan_limit(notu: str | None, *, session=None) -> Decimal | None:
    """Not → otomatik limit. Boş → None (manuel). - → 0."""
    n = not_normalize(notu)
    if n == NOT_BOS:
        return None
    if n == NOT_DOLANDIRICI:
        return Decimal("0.00")
    limitler = yildiz_limitlerini_getir(session)
    return limitler[n]


def kart_notunu_uygula(session, cari, veriler: dict[str, Any]) -> None:
    """``veriler`` içinden kredi_notu alanlarını işler; açık hesap limitini ayarlar.

    ``kredi_notu`` yoksa dokunmaz. Bilinmeyen eski not değeri verilerde gelirse
    normalize edilmez/silinmez (yalnız geçerli seçimlerde güncellenir).
    """
    from database.cari_risk_service import _gecmis_yaz

    if "kredi_notu" not in veriler and "kredi_notu_manuel_limit" not in veriler:
        return

    ham_not = veriler.pop("kredi_notu", getattr(cari, "kredi_notu", None))
    # Kullanıcı bilinmeyen eski değeri yeniden kaydetmeye çalışıyorsa dokunma
    if ham_not is not None and str(ham_not).strip() and not_bilinmeyen_mi(ham_not):
        # Eski içeriği koru; limit zorlaması yapma
        veriler.pop("kredi_notu_manuel_limit", None)
        return

    yeni_not = not_normalize(ham_not)
    eski_not = getattr(cari, "kredi_notu", None) or NOT_BOS
    eski_not_n = not_normalize(eski_not) if not not_bilinmeyen_mi(eski_not) else NOT_BOS

    manuel = getattr(cari, "kredi_notu_manuel_limit", None)
    if "kredi_notu_manuel_limit" in veriler:
        veriler.pop("kredi_notu_manuel_limit", None)

    # İlk kez yıldız/- verilirken mevcut manuel limiti sakla
    if eski_not_n == NOT_BOS and yeni_not != NOT_BOS:
        if manuel is None:
            manuel = getattr(cari, "acik_hesap_risk_limiti", None)
            cari.kredi_notu_manuel_limit = manuel
            _gecmis_yaz(session, int(cari.id or 0) or 0, "kredi_notu_manuel_limit", None, manuel)

    if yeni_not == NOT_BOS:
        # Manuel limite dön
        geri = manuel
        cari.kredi_notu = None
        if geri is not None:
            veriler["acik_hesap_risk_limiti"] = geri
            # uygula bayrağı: önceki manuel davranışa bırak; yoksa False bırakma — mevcut uygula korunur
            if "acik_hesap_limit_uygula" not in veriler:
                veriler["acik_hesap_limit_uygula"] = bool(
                    getattr(cari, "acik_hesap_limit_uygula", False)
                )
        else:
            # Manuel yoksa alanı boşaltma (mevcut varsayılan); yalnız notu temizle
            pass
    else:
        limit = hesaplanan_limit(yeni_not, session=session)
        cari.kredi_notu = yeni_not
        veriler["acik_hesap_risk_limiti"] = limit
        veriler["acik_hesap_limit_uygula"] = True

    if (eski_not or "") != (cari.kredi_notu or ""):
        cid = int(getattr(cari, "id", 0) or 0)
        if cid:
            _gecmis_yaz(session, cid, "kredi_notu", eski_not or "", cari.kredi_notu or "")
