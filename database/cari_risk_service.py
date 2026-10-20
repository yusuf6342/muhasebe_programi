"""Cari risk ve limitleri, vade farkı oranları.

Güncel riskler kayıtlı sabit rakam değildir; her çağrıda kaynak hareketlerden hesaplanır:

* Açık hesap: carinin açık belge kalemleri (``cari_satis_hareketleri.kalan_acik_tutar > 0``) eksi
  dağıtılmamış avans. Kayıt dışı taslak belge ve kaydedilmemiş tahsilat kalem oluşturmaz.
  Alış faturası kalemleri (tedarikçiye borcumuz) müşteri riskine girmez.
* Ciro çek / ciro senet: müşteriden alınıp üçüncü kişiye ciro edilmiş, kapanışı kesinleşmemiş
  (``CIRO_EDILDI``) evrakların kalan tutarı. Vade gelmesi riski düşürmez.
* Portföy çek/senet: ciro edilmemiş, portföyde veya bankada bekleyen alınan evraklar — ayrı sınıf.
  Karşılıksız / protestolu / iade evrakta cariye geri borç yazılan tutar açık hesapta sayılır;
  aynı tutar evrak sınıfında tekrar sayılmaz, geri yazılmamış kalan evrak riskinde kalır.
* Genel Risk: açık hesap tam tutarla + ciro edilen çekler, diğer çekler ve senetler cari kartındaki
  yüzdelerle (``genel_risk_hesapla``). Brüt Toplam yüzdesiz toplamdır; muhasebe bakiyesi değişmez.

Limit veya oran kaydı hiçbir borç, tahsilat, belge, stok veya muhasebe hareketi üretmez.
"""

from __future__ import annotations

import weakref
from datetime import date, datetime
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from typing import Any, Iterable

from sqlalchemy import inspect, or_, select

KURUS = Decimal("0.01")

TUR_ACIK = "ACIK_HESAP"
TUR_CEK = "CIRO_CEK"
TUR_SENET = "CIRO_SENET"
TUR_PORTFOY = "PORTFOY"
TUR_TOPLAM = "TOPLAM"

TUR_ETIKET = {
    TUR_ACIK: "Açık Hesap",
    TUR_CEK: "Ciro Çek",
    TUR_SENET: "Ciro Senet",
    TUR_PORTFOY: "Portföy Çek/Senet",
    TUR_TOPLAM: "Genel Risk",
}
LIMITLI_TURLER = (TUR_ACIK, TUR_CEK, TUR_SENET, TUR_TOPLAM)
LIMIT_ALANLARI = {
    TUR_ACIK: ("acik_hesap_risk_limiti", "acik_hesap_limit_uygula"),
    TUR_CEK: ("cek_risk_limiti", "cek_limit_uygula"),
    TUR_SENET: ("senet_risk_limiti", "senet_limit_uygula"),
    TUR_TOPLAM: ("toplam_risk_limiti", "toplam_limit_uygula"),
}
ORAN_ALANLARI = ("vade_farki_aylik_oran", "vade_farki_yillik_oran")
DONEM_AYLIK = "AYLIK"
DONEM_YILLIK = "YILLIK"
DONEM_ETIKET = {DONEM_AYLIK: "Aylık", DONEM_YILLIK: "Yıllık"}

# Genel Risk: açık hesap tam tutarla, çek/senet bileşenleri cari kartındaki yüzdelerle.
BILESEN_ACIK = "ACIK_HESAP"
BILESEN_CIRO_CEK = "CIRO_CEKLER"
BILESEN_DIGER_CEK = "DIGER_CEKLER"
BILESEN_SENET = "SENETLER"
GENEL_BILESENLER = (BILESEN_ACIK, BILESEN_CIRO_CEK, BILESEN_DIGER_CEK, BILESEN_SENET)
BILESEN_ETIKET = {
    BILESEN_ACIK: "Açık hesap",
    BILESEN_CIRO_CEK: "Ciro edilen müşteri çekleri",
    BILESEN_DIGER_CEK: "Diğer müşteri çekleri",
    BILESEN_SENET: "Müşteri senetleri",
}
RISK_ORANI_ALANI = {
    BILESEN_CIRO_CEK: "risk_orani_ciro_cek",
    BILESEN_DIGER_CEK: "risk_orani_diger_cek",
    BILESEN_SENET: "risk_orani_senet",
}
RISK_ORANI_ALANLARI = tuple(RISK_ORANI_ALANI.values())
VARSAYILAN_RISK_ORANI = Decimal("100")
YUZ = Decimal("100")

KART_ALANLARI = tuple(a for ikili in LIMIT_ALANLARI.values() for a in ikili) + ORAN_ALANLARI + (
    "vade_farki_donem",
    "vade_farki_aciklama",
) + RISK_ORANI_ALANLARI

DURUM_TANIMSIZ = "TANIMSIZ"
DURUM_UYGUN = "UYGUN"
DURUM_DOLU = "DOLU"
DURUM_ASILDI = "ASILDI"
DURUM_ETIKET = {
    DURUM_TANIMSIZ: "Limit tanımlı değil",
    DURUM_UYGUN: "Uygun",
    DURUM_DOLU: "Limit dolu",
    DURUM_ASILDI: "Limit aşıldı",
}

POLITIKA_UYARI = "UYARI"
POLITIKA_ENGEL = "ENGEL"
POLITIKA_ANAHTAR = "risk_asim_davranisi"

IZIN_LIMIT = "cari_risk_limit_duzenleme"
IZIN_ASIM = "cari_risk_asim_onay"

KARAR_UYARI_GECILDI = "UYARI_GECILDI"
KARAR_YETKILI_GECIS = "YETKILI_GECIS"

# Alınan evrak durumları (cek_senet modeli)
_CIRO_DURUMLARI = frozenset({"CIRO_EDILDI"})
_PORTFOY_DURUMLARI = frozenset(
    {"PORTFOYDE", "BANKAYA_TAHSILE", "BANKAYA_TEMINATA", "KISMI_TAHSIL", "VADESI_GECTI"}
)
# Sorunlu evrak: cariye geri borç yazılan kısım açık hesapta, kalanı evrak riskinde kalır.
_SORUNLU_DURUMLAR = frozenset({"KARSILIKSIZ", "PROTESTO", "IADE", "HUKUKI_TAKIP"})
_GERI_BORC_DURUMLARI = frozenset({"KARSILIKSIZ", "PROTESTO", "IADE"})


def _d(deger) -> Decimal:
    if deger is None or deger == "":
        return Decimal("0")
    if isinstance(deger, Decimal):
        return deger
    try:
        return Decimal(str(deger))
    except (InvalidOperation, ValueError):
        return Decimal("0")


def _kurus(deger) -> Decimal:
    return _d(deger).quantize(KURUS, rounding=ROUND_HALF_UP)


def _kullanici() -> tuple[int | None, str | None]:
    try:
        from database.session_manager import oturum

        return oturum.user_id, (oturum.kullanici_adi or oturum.ad_soyad)
    except Exception:
        return None, None


# ─── Şema ────────────────────────────────────────────────────────────────
_HAZIR_MOTORLAR: "weakref.WeakSet" = weakref.WeakSet()


def schema_hazirla(motor=None) -> None:
    """Sürümlü geçiş: cari kart risk/oran kolonları ve geçmiş tabloları (veriye dokunmaz).

    Eski kartlarda limit denetimi kapalı başlar; mevcut limit tutarları silinmez, 0'a çevrilmez.
    """
    import database.database as veritabani

    motor = motor or veritabani.engine
    if motor is None or motor in _HAZIR_MOTORLAR:
        return
    from database.modul_sema import eksik_kolonlari_ekle, surum_uygula
    from database.models.cari_risk import CariRiskAyari, CariRiskDegisiklik, CariRiskOlayi

    def _v1(e) -> None:
        eksik_kolonlari_ekle(e, "cari_kartlar", {
            "toplam_risk_limiti": "NUMERIC(18, 2)",
            "acik_hesap_limit_uygula": "BOOLEAN NOT NULL DEFAULT 0",
            "cek_limit_uygula": "BOOLEAN NOT NULL DEFAULT 0",
            "senet_limit_uygula": "BOOLEAN NOT NULL DEFAULT 0",
            "toplam_limit_uygula": "BOOLEAN NOT NULL DEFAULT 0",
            "vade_farki_aylik_oran": "NUMERIC(9, 4)",
            "vade_farki_yillik_oran": "NUMERIC(9, 4)",
            "vade_farki_donem": "VARCHAR(10)",
            "vade_farki_aciklama": "VARCHAR(200)",
        })
        for tablo in (CariRiskDegisiklik.__table__, CariRiskOlayi.__table__, CariRiskAyari.__table__):
            tablo.create(e, checkfirst=True)

    if inspect(motor).has_table("cari_kartlar"):
        surum_uygula(motor, "cari_risk", 1, _v1)
    _HAZIR_MOTORLAR.add(motor)


def _tablo_var(session, ad: str) -> bool:
    try:
        return inspect(session.connection()).has_table(ad)
    except Exception:
        return False


def _tablolari_garanti(session) -> None:
    from database.models.cari_risk import CariRiskAyari, CariRiskDegisiklik, CariRiskOlayi

    baglanti = session.connection()
    for tablo in (CariRiskDegisiklik.__table__, CariRiskOlayi.__table__, CariRiskAyari.__table__):
        tablo.create(baglanti, checkfirst=True)


# ─── Limit durumu ────────────────────────────────────────────────────────
def limit_durumu(risk, limit, uygula: bool) -> dict[str, Any]:
    """Kalan limit = limit − risk; aşım = max(0, risk − limit). Uygulanmıyorsa sayı yok."""
    risk = _kurus(risk)
    if not uygula or limit is None:
        return {"kalan": None, "asim": None, "durum": DURUM_TANIMSIZ, "etiket": DURUM_ETIKET[DURUM_TANIMSIZ]}
    limit = _kurus(limit)
    kalan = limit - risk
    asim = max(Decimal("0.00"), risk - limit)
    if risk > limit:
        durum = DURUM_ASILDI
    elif risk == limit:
        durum = DURUM_DOLU
    else:
        durum = DURUM_UYGUN
    return {"kalan": kalan, "asim": asim, "durum": durum, "etiket": DURUM_ETIKET[durum]}


def etkin_limit(cari, tur: str = TUR_ACIK) -> Decimal | None:
    """Limit denetimi açıksa limit (0 dahil), kapalıysa None."""
    limit_alan, uygula_alan = LIMIT_ALANLARI[tur]
    if not bool(getattr(cari, uygula_alan, False)):
        return None
    deger = getattr(cari, limit_alan, None)
    return None if deger is None else _kurus(deger)


# ─── Risk kaynakları ─────────────────────────────────────────────────────
def _tedarikci_mi(cari) -> bool:
    return (getattr(cari, "cari_turu", "") or "").strip().casefold() == "tedarikçi".casefold()


def _acik_hesap(session, cari) -> tuple[Decimal, Decimal, Decimal, list[dict]]:
    """(risk, açık borç, dağıtılmamış avans, ayrıntı). Tedarikçide müşteri alacak riski yoktur."""
    from database.acik_kalem_service import AcikKalemService, para_anahtari
    from database.models.alis_faturasi import AlisFaturasi

    if _tedarikci_mi(cari):
        return Decimal("0.00"), Decimal("0.00"), Decimal("0.00"), []
    alis_nolari = set(
        session.scalars(select(AlisFaturasi.fatura_no).where(AlisFaturasi.cari_id == cari.id)).all()
    )
    borc = Decimal("0")
    detay = []
    for h in AcikKalemService.acik_kalemler(session, cari.id, yon="BORC", para_birimi=None):
        if (h.belge_no or "") in alis_nolari:
            continue
        kalan = _kurus(h.kalan_acik_tutar)
        ilk = _kurus(h.satis_tutari)
        borc += kalan
        detay.append({
            "kaynak": "Cari açık kalem",
            "kimlik": f"KALEM-{int(h.id)}",
            "belge_turu": AcikKalemService._evrak_turu(session, h),
            "belge_no": h.belge_no or "",
            "tarih": h.satis_tarihi,
            "vade": AcikKalemService._vade(session, h),
            "ilk_tutar": ilk,
            "tutar": kalan,
            "para_birimi": para_anahtari(h),
            "durum": "Kısmen Kapalı" if ilk > 0 and kalan < ilk else "Açık",
        })
    avans = sum(
        (-_kurus(h.kalan_acik_tutar)
         for h in AcikKalemService.acik_kalemler(session, cari.id, yon="AVANS", para_birimi=None)),
        Decimal("0"),
    )
    risk = max(Decimal("0"), borc - avans)
    if avans > 0:
        detay.append({
            "kaynak": "Dağıtılmamış avans",
            "kimlik": "AVANS",
            "belge_turu": "Avans / Açık Kredi",
            "belge_no": "",
            "tarih": None,
            "vade": None,
            "ilk_tutar": avans,
            "tutar": -avans,
            "para_birimi": "TRY",
            "durum": "Açık borçtan bir kez düşüldü",
        })
    return _kurus(risk), _kurus(borc), _kurus(avans), detay


def _evrak_kayitlari(session, cari_id: int) -> list[dict]:
    """Carinin alınan açık evrakları — her evrak bir kez; risk kalanı ve Genel Risk bileşeniyle.

    Sorunlu (karşılıksız/protesto/iade/hukuki takip) evrakta cariye geri borç yazılan tutar açık
    hesapta sayılır; evrakta yalnız geri yazılmamış kalan riskte kalır.
    """
    if not _tablo_var(session, "cek_senet_evraklari"):
        return []
    from database.models.cek_senet import (
        DURUM_ETIKETLERI,
        ISLEM_YONU_ALINAN,
        CekSenetEvrak,
        CekSenetHareket,
    )

    evraklar = session.scalars(
        select(CekSenetEvrak).where(
            CekSenetEvrak.cari_id == int(cari_id),
            CekSenetEvrak.islem_yonu == ISLEM_YONU_ALINAN,
            CekSenetEvrak.aktif.is_(True),
            CekSenetEvrak.durum.in_(_CIRO_DURUMLARI | _PORTFOY_DURUMLARI | _SORUNLU_DURUMLAR),
        ).order_by(CekSenetEvrak.vade_tarihi, CekSenetEvrak.id)
    ).all()
    geri_borc: dict[int, Decimal] = {}
    sorunlu_ids = [int(e.id) for e in evraklar if e.durum in _SORUNLU_DURUMLAR]
    if sorunlu_ids:
        kosullar = [
            CekSenetHareket.evrak_id.in_(sorunlu_ids),
            CekSenetHareket.yeni_durum.in_(_GERI_BORC_DURUMLARI),
            CekSenetHareket.cari_hareket_id.is_not(None),
        ]
        kolonlar = {k["name"] for k in inspect(session.connection()).get_columns("cek_senet_hareketleri")}
        if "iptal" in kolonlar:
            kosullar.append(or_(CekSenetHareket.iptal.is_(None), CekSenetHareket.iptal.is_(False)))
        for evrak_id, tutar in session.execute(
            select(CekSenetHareket.evrak_id, CekSenetHareket.tutar).where(*kosullar)
        ).all():
            geri_borc[int(evrak_id)] = geri_borc.get(int(evrak_id), Decimal("0")) + _d(tutar)
    kayitlar = []
    for e in evraklar:
        kalan = _kurus(e.kalan_tutar)
        if kalan <= 0:
            continue
        cek = "CEK" in (e.evrak_turu or "").upper()
        ciro = e.durum in _CIRO_DURUMLARI
        sorunlu = e.durum in _SORUNLU_DURUMLAR
        geri = _kurus(geri_borc.get(int(e.id), 0)) if sorunlu else Decimal("0.00")
        risk_kalan = max(Decimal("0.00"), kalan - geri)
        doviz = (e.doviz_turu or "TL").strip().upper()
        kur_eksik = doviz not in ("TL", "TRY") and (_d(e.kur) <= 0 or _d(e.tl_tutari) <= 0)
        hedef = ""
        if ciro:
            son = session.scalar(
                select(CekSenetHareket)
                .where(CekSenetHareket.evrak_id == e.id, CekSenetHareket.islem_turu == "CIRO")
                .order_by(CekSenetHareket.id.desc())
                .limit(1)
            )
            if son is not None and son.ilgili_cari_id:
                from database.models.cari import Cari

                hc = session.get(Cari, int(son.ilgili_cari_id))
                hedef = f"{hc.cari_kodu} {hc.unvan}" if hc else ""
        durum = DURUM_ETIKETLERI.get(e.durum, e.durum)
        if sorunlu and geri > 0:
            durum += f" — {geri:,.2f} TL açık hesaba geri yazıldı".replace(",", "X").replace(".", ",").replace("X", ".")
        kayitlar.append({
            "kaynak": "Çek/Senet evrakı",
            "kimlik": f"EVRAK-{int(e.id)}",
            "evrak_id": int(e.id),
            "belge_turu": ("Çek" if cek else "Senet") + (" (ciro)" if ciro else ""),
            "belge_no": e.portfoy_no or e.evrak_no or "",
            "evrak_no": e.cek_no or e.senet_no or e.evrak_no or "",
            "tarih": e.duzenleme_tarihi,
            "vade": e.vade_tarihi,
            "ilk_tutar": _kurus(e.tl_tutari),
            "acik_tutar": kalan,
            "tutar": risk_kalan,
            "geri_borc": geri,
            "para_birimi": "TRY" if not kur_eksik else doviz,
            "kur_eksik": kur_eksik,
            "durum": durum,
            "ciro_hedefi": hedef,
            "tur": (TUR_CEK if cek else TUR_SENET) if ciro else TUR_PORTFOY,
            "bilesen": (BILESEN_CIRO_CEK if ciro else BILESEN_DIGER_CEK) if cek else BILESEN_SENET,
        })
    return kayitlar


def _evrak_riskleri(session, cari_id: int, kayitlar: list[dict] | None = None) -> dict[str, list[dict]]:
    sonuc: dict[str, list[dict]] = {TUR_CEK: [], TUR_SENET: [], TUR_PORTFOY: []}
    for k in (_evrak_kayitlari(session, cari_id) if kayitlar is None else kayitlar):
        if k["tutar"] > 0 and not k["kur_eksik"]:
            sonuc[k["tur"]].append(k)
    return sonuc


def risk_oranlari(cari) -> dict[str, Decimal]:
    """Cari kartındaki bileşen yüzdeleri; kolon boşsa varsayılan %100."""
    sonuc = {}
    for bilesen, alan in RISK_ORANI_ALANI.items():
        deger = getattr(cari, alan, None)
        sonuc[bilesen] = VARSAYILAN_RISK_ORANI if deger is None else _d(deger)
    return sonuc


def genel_risk_hesapla(hamlar: dict[str, Any], oranlar: dict[str, Any]) -> dict[str, Any]:
    """Saf hesap: açık hesap tam, diğer bileşenler ``ham × oran / 100``; her bileşen kuruşa bir kez yuvarlanır.

    Brüt Toplam yüzdesiz toplamdır. Genel Risk, bileşen risklerinin toplamıdır.
    """
    satirlar = []
    brut = Decimal("0")
    genel = Decimal("0.00")
    for bilesen in GENEL_BILESENLER:
        ham = _d(hamlar.get(bilesen))
        oran = YUZ if bilesen == BILESEN_ACIK else _d(oranlar.get(bilesen, VARSAYILAN_RISK_ORANI))
        risk = _kurus(ham * oran / YUZ)
        brut += ham
        genel += risk
        satirlar.append({
            "bilesen": bilesen,
            "etiket": BILESEN_ETIKET[bilesen],
            "ham": _kurus(ham),
            "oran": None if bilesen == BILESEN_ACIK else oran,
            "risk": risk,
        })
    return {"bilesenler": satirlar, "brut": _kurus(brut), "genel_risk": _kurus(genel)}


def risk_hesapla(session, cari_id: int) -> dict[str, Any]:
    """Cari risk özeti: satırlar (Açık Hesap, Ciro Çek, Ciro Senet, Portföy, Toplam) + ayrıntılar."""
    from database.models.cari import Cari

    cari = session.get(Cari, int(cari_id))
    if cari is None:
        raise ValueError("Cari bulunamadı.")
    acik_risk, acik_borc, avans, acik_detay = _acik_hesap(session, cari)
    evrak_kayitlari = _evrak_kayitlari(session, cari.id)
    evrak = _evrak_riskleri(session, cari.id, evrak_kayitlari)
    oranlar = risk_oranlari(cari)
    hamlar = {BILESEN_ACIK: acik_risk}
    genel_detay = [
        {**k, "bilesen": BILESEN_ACIK, "oran": None, "hesaplanan": k["tutar"], "acik_tutar": k["tutar"]}
        for k in acik_detay
    ]
    eksik_kur = []
    for k in evrak_kayitlari:
        oran = oranlar[k["bilesen"]]
        if k["kur_eksik"]:
            eksik_kur.append(k)
            genel_detay.append({**k, "oran": oran, "hesaplanan": None})
            continue
        hamlar[k["bilesen"]] = hamlar.get(k["bilesen"], Decimal("0")) + k["tutar"]
        genel_detay.append({**k, "oran": oran, "hesaplanan": _kurus(k["tutar"] * oran / YUZ)})
    genel = genel_risk_hesapla(hamlar, oranlar)
    genel["oranlar"] = oranlar
    genel["detay"] = genel_detay
    genel["eksik_kur"] = eksik_kur
    riskler = {
        TUR_ACIK: acik_risk,
        TUR_CEK: _kurus(sum((r["tutar"] for r in evrak[TUR_CEK]), Decimal("0"))),
        TUR_SENET: _kurus(sum((r["tutar"] for r in evrak[TUR_SENET]), Decimal("0"))),
        TUR_PORTFOY: _kurus(sum((r["tutar"] for r in evrak[TUR_PORTFOY]), Decimal("0"))),
    }
    # Toplam limit yüzdeli Genel Risk ile karşılaştırılır; Brüt Toplam yalnız bilgi amaçlıdır.
    riskler[TUR_TOPLAM] = genel["genel_risk"]
    satirlar = {}
    for tur, risk in riskler.items():
        if tur in LIMIT_ALANLARI:
            limit_alan, uygula_alan = LIMIT_ALANLARI[tur]
            uygula = bool(getattr(cari, uygula_alan, False))
            limit = getattr(cari, limit_alan, None)
            limit = None if limit is None else _kurus(limit)
        else:
            uygula, limit = False, None
        satirlar[tur] = {
            "tur": tur,
            "etiket": TUR_ETIKET[tur],
            "risk": risk,
            "limit": limit,
            "uygula": uygula,
            "limitli": tur in LIMIT_ALANLARI,
            **limit_durumu(risk, limit, uygula),
        }
    satirlar[TUR_TOPLAM]["brut"] = genel["brut"]
    return {
        "cari_id": int(cari.id),
        "tedarikci": _tedarikci_mi(cari),
        "acik_borc": acik_borc,
        "avans": avans,
        "satirlar": satirlar,
        "detay": {TUR_ACIK: acik_detay, **evrak},
        "genel": genel,
        "zaman": datetime.now(),
    }


def risk_ozeti(cari_id: int) -> dict[str, Any]:
    from database.database import get_session

    with get_session() as session:
        return risk_hesapla(session, int(cari_id))


# ─── İşlem öncesi kontrol ────────────────────────────────────────────────
def politika_getir(session=None) -> str:
    from database.models.cari_risk import CariRiskAyari

    def _oku(s) -> str:
        if not _tablo_var(s, CariRiskAyari.__tablename__):
            return POLITIKA_UYARI
        deger = s.scalar(select(CariRiskAyari.deger).where(CariRiskAyari.anahtar == POLITIKA_ANAHTAR))
        return POLITIKA_ENGEL if (deger or "").upper() == POLITIKA_ENGEL else POLITIKA_UYARI

    if session is not None:
        return _oku(session)
    from database.database import get_session

    with get_session() as s:
        return _oku(s)


def politika_ayarla(deger: str) -> str:
    from database.access import yetki_zorunlu
    from database.database import get_session
    from database.models.cari_risk import CariRiskAyari

    yetki_zorunlu("sistem_ayarlari", IZIN_LIMIT, mesaj="Risk politikasını değiştirme yetkiniz yok.")
    deger = (deger or "").upper()
    if deger not in (POLITIKA_UYARI, POLITIKA_ENGEL):
        raise ValueError("Risk aşım davranışı UYARI veya ENGEL olmalıdır.")
    with get_session() as s:
        _tablolari_garanti(s)
        eski = politika_getir(s)
        kayit = s.get(CariRiskAyari, POLITIKA_ANAHTAR)
        if kayit is None:
            s.add(CariRiskAyari(anahtar=POLITIKA_ANAHTAR, deger=deger))
        else:
            kayit.deger = deger
        if eski != deger:
            _gecmis_yaz(s, 0, "risk_asim_davranisi", eski, deger)
    return deger


def islem_kontrolu(cari_id: int, ek_acik_hesap, *, session=None, belge_no: str | None = None) -> dict[str, Any]:
    """İşlem sonrası tahmini açık hesap riski ve Genel Riski limitlerle karşılaştırır.

    İşlem açık hesaba girer; açık hesap Genel Riske tam tutarla katıldığı için iki denetimde de etki
    aynıdır. ``belge_no`` verilirse belgenin halen açık hesapta duran kalemi (eski etki) çıkarılır,
    yeni etki eklenir; belge riske ikinci kez katılmaz. Yalnız riski artıran işlem (net etki > 0)
    denetlenir; risk azaltan tahsilat engellenmez. Açık hesap ve Genel Risk aşımı ayrı denetimdir.
    """
    ek = _kurus(ek_acik_hesap)
    if session is None:
        from database.database import get_session

        with get_session() as s:
            return islem_kontrolu(cari_id, ek, session=s, belge_no=belge_no)
    ozet = risk_hesapla(session, int(cari_id))
    eski = Decimal("0.00")
    if belge_no:
        eski = _kurus(sum(
            (d["tutar"] for d in ozet["detay"][TUR_ACIK]
             if d.get("kimlik", "").startswith("KALEM-") and (d.get("belge_no") or "") == belge_no),
            Decimal("0"),
        ))
    net = ek - eski
    asimlar = []
    if net > 0:
        for tur in (TUR_ACIK, TUR_TOPLAM):
            s = ozet["satirlar"][tur]
            if not s["uygula"] or s["limit"] is None:
                continue
            yeni = s["risk"] + net
            if yeni > s["limit"]:
                asimlar.append({
                    "tur": tur,
                    "etiket": s["etiket"],
                    "mevcut": s["risk"],
                    "etki": net,
                    "yeni": yeni,
                    "limit": s["limit"],
                    "asim": yeni - s["limit"],
                })
    return {"cari_id": int(cari_id), "etki": net, "eski_etki": eski, "asimlar": asimlar,
            "politika": politika_getir(session), "ozet": ozet}


def asim_metni(kontrol: dict) -> str:
    from tutar_bicim import tr_tutar

    satirlar = []
    for a in kontrol.get("asimlar") or []:
        satirlar.append(
            f"{a['etiket']} limiti: mevcut risk {tr_tutar(a['mevcut'])} TL + işlem etkisi "
            f"{tr_tutar(a['etki'])} TL = yeni risk {tr_tutar(a['yeni'])} TL; limit {tr_tutar(a['limit'])} TL "
            f"(aşım {tr_tutar(a['asim'])} TL)."
        )
    return "\n".join(satirlar)


def olay_kaydet(kontrol: dict, *, belge_turu: str, belge_no: str | None, karar: str,
                gerekce: str | None = None) -> int:
    """Aşıma rağmen yapılan kaydı kullanıcı, zaman ve gerekçeyle saklar."""
    from database.database import get_session
    from database.models.cari_risk import CariRiskOlayi

    kid, kadi = _kullanici()
    sayi = 0
    with get_session() as s:
        _tablolari_garanti(s)
        for a in kontrol.get("asimlar") or []:
            s.add(CariRiskOlayi(
                cari_id=int(kontrol["cari_id"]),
                belge_turu=belge_turu[:40],
                belge_no=(belge_no or "")[:50] or None,
                risk_turu=a["tur"],
                mevcut_risk=a["mevcut"],
                islem_etkisi=a["etki"],
                yeni_risk=a["yeni"],
                limit=a["limit"],
                politika=kontrol.get("politika") or POLITIKA_UYARI,
                karar=karar,
                gerekce=(gerekce or "").strip()[:300] or None,
                kullanici_id=kid,
                kullanici_adi=kadi,
                zaman=datetime.now(),
            ))
            sayi += 1
    return sayi


def olaylar(cari_id: int) -> list[dict]:
    from database.database import get_session
    from database.models.cari_risk import CariRiskOlayi

    with get_session() as s:
        if not _tablo_var(s, CariRiskOlayi.__tablename__):
            return []
        return [
            {"zaman": o.zaman, "belge_turu": o.belge_turu, "belge_no": o.belge_no or "",
             "risk_turu": TUR_ETIKET.get(o.risk_turu, o.risk_turu), "yeni_risk": _kurus(o.yeni_risk),
             "limit": _kurus(o.limit), "karar": o.karar, "gerekce": o.gerekce or "",
             "kullanici": o.kullanici_adi or ""}
            for o in s.scalars(
                select(CariRiskOlayi).where(CariRiskOlayi.cari_id == int(cari_id))
                .order_by(CariRiskOlayi.zaman.desc(), CariRiskOlayi.id.desc())
            ).all()
        ]


# ─── Kart alanları: doğrulama, yetki, geçmiş ─────────────────────────────
def oran_coz(metin) -> Decimal | None:
    """'2,50' / '2.5' / '%2,5' → Decimal('2.50') (yüzde değeri; 0,025'e çevrilmez). Boş → None."""
    if metin is None:
        return None
    if isinstance(metin, Decimal):
        return metin
    ham = str(metin).strip().replace("%", "").replace(" ", "")
    if not ham:
        return None
    if "," in ham:
        ham = ham.replace(".", "").replace(",", ".")
    try:
        deger = Decimal(ham)
    except InvalidOperation:
        raise ValueError("Oran geçerli bir sayı olmalıdır (ör. 2,50).") from None
    if not deger.is_finite():
        raise ValueError("Oran geçerli bir sayı olmalıdır (ör. 2,50).")
    return deger


def oran_metni(deger) -> str:
    """Decimal('2.5') → '2,50' (yüzde işareti etiketle ayrıca gösterilir)."""
    if deger is None or deger == "":
        return ""
    d = _d(deger).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    return f"{d:f}".replace(".", ",")


def kart_alanlarini_dogrula(veriler: dict[str, Any]) -> dict[str, Any]:
    """Risk/oran alanlarını normalize eder; hatalı girişte ValueError.

    Limit Uygula işaretliyken boş limit 0'a çevrilmez, kullanıcıdan istenir. Limitler negatif olamaz.
    """
    from tutar_bicim import tutar_coz

    sonuc: dict[str, Any] = {}
    for tur, (limit_alan, uygula_alan) in LIMIT_ALANLARI.items():
        if limit_alan not in veriler and uygula_alan not in veriler:
            continue
        uygula = bool(veriler.get(uygula_alan))
        ham = veriler.get(limit_alan)
        if ham is None or (isinstance(ham, str) and not ham.strip()):
            limit = None
        else:
            try:
                limit = _kurus(tutar_coz(ham))
            except ValueError:
                raise ValueError(f"{TUR_ETIKET[tur]} limiti geçerli bir tutar olmalıdır.") from None
            if limit < 0:
                raise ValueError(f"{TUR_ETIKET[tur]} limiti negatif olamaz.")
        if uygula and limit is None:
            raise ValueError(
                f"{TUR_ETIKET[tur]} için «Limit Uygula» işaretli ancak limit boş. "
                "Limit tutarını girin (0 TL geçerli bir limittir) veya işareti kaldırın."
            )
        sonuc[limit_alan] = limit
        sonuc[uygula_alan] = uygula
    for alan, ad in (("vade_farki_aylik_oran", "Aylık"), ("vade_farki_yillik_oran", "Yıllık")):
        if alan not in veriler:
            continue
        try:
            oran = oran_coz(veriler.get(alan))
        except ValueError:
            raise ValueError(f"{ad} vade farkı oranı geçerli bir sayı olmalıdır (ör. 2,50).") from None
        if oran is not None:
            if oran < 0:
                raise ValueError(f"{ad} vade farkı oranı negatif olamaz.")
            if oran > Decimal("1000"):
                raise ValueError(f"{ad} vade farkı oranı yüzde 1000'den büyük olamaz.")
            oran = oran.quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)
        sonuc[alan] = oran
    if "vade_farki_donem" in veriler:
        donem = (veriler.get("vade_farki_donem") or "").strip().upper() or None
        donem = {"AYLIK": DONEM_AYLIK, "YILLIK": DONEM_YILLIK, "YILLİK": DONEM_YILLIK}.get(donem, donem)
        if donem not in (None, DONEM_AYLIK, DONEM_YILLIK):
            raise ValueError("Vade farkı esas dönemi Aylık veya Yıllık olmalıdır.")
        oran_alan = "vade_farki_aylik_oran" if donem == DONEM_AYLIK else "vade_farki_yillik_oran"
        if donem and oran_alan in sonuc and sonuc[oran_alan] is None:
            raise ValueError(
                f"Esas dönem {DONEM_ETIKET[donem]} seçili; {DONEM_ETIKET[donem].lower()} oranı girin "
                "(0 kullanılabilir) veya esas dönemi boş bırakın."
            )
        sonuc["vade_farki_donem"] = donem
    if "vade_farki_aciklama" in veriler:
        sonuc["vade_farki_aciklama"] = (veriler.get("vade_farki_aciklama") or "").strip()[:200] or None
    for bilesen, alan in RISK_ORANI_ALANI.items():
        if alan in veriler:
            sonuc[alan] = risk_orani_dogrula(veriler.get(alan), BILESEN_ETIKET[bilesen])
    return sonuc


def risk_orani_dogrula(ham, ad: str = "Risk") -> Decimal:
    """0–100 arası, en fazla iki ondalık. Boş değer 0 sayılmaz; hata verir."""
    if ham is None or (isinstance(ham, str) and not ham.strip()):
        raise ValueError(f"{ad} risk yüzdesi boş bırakılamaz (0 geçerli bir yüzdedir).")
    try:
        oran = oran_coz(ham)
    except ValueError:
        raise ValueError(f"{ad} risk yüzdesi geçerli bir sayı olmalıdır (ör. 25,50).") from None
    if oran < 0 or oran > YUZ:
        raise ValueError(f"{ad} risk yüzdesi 0 ile 100 arasında olmalıdır.")
    if oran != oran.quantize(Decimal("0.01")):
        raise ValueError(f"{ad} risk yüzdesi en fazla iki ondalık olabilir.")
    return oran.quantize(Decimal("0.01"))


# ─── Vade farkı: aylık ↔ yıllık (basit nominal) ──────────────────────────
AY_SAYISI = Decimal("12")
VADE_TUTARLILIK_TOLERANSI = Decimal("0.0012")


def vade_oran_bagla(kaynak: str, ham) -> tuple[Decimal | None, Decimal | None]:
    """Son düzenlenen alan ana değerdir: aylık → yıllık = aylık × 12; yıllık → aylık = yıllık / 12.

    Dönüş (aylık, yıllık) tam hassasiyetle; boş → (None, None). Negatif/sayısal olmayan → ValueError.
    """
    oran = oran_coz(ham)
    if oran is None:
        return None, None
    if oran < 0:
        raise ValueError("Vade farkı oranı negatif olamaz.")
    if kaynak == DONEM_AYLIK:
        aylik, yillik = oran, oran * AY_SAYISI
    elif kaynak == DONEM_YILLIK:
        aylik, yillik = oran / AY_SAYISI, oran
    else:
        raise ValueError("Kaynak alan AYLIK veya YILLIK olmalıdır.")
    if yillik > Decimal("1000"):
        raise ValueError("Vade farkı oranının yıllık karşılığı yüzde 1000'den büyük olamaz.")
    return aylik, yillik


def vade_oran_metni(deger) -> str:
    """Ekranda dört ondalık: Decimal('36') → '36,0000'; boş → ''."""
    if deger is None or deger == "":
        return ""
    return f"{_d(deger).quantize(Decimal('0.0001'), rounding=ROUND_HALF_UP):f}".replace(".", ",")


def vade_oranlari_tutarli(aylik, yillik) -> bool:
    """Kayıtlı iki oran aynı nominal oranı mı gösteriyor? Yalnız biri doluysa çelişki sayılmaz."""
    if aylik is None or yillik is None:
        return True
    return abs(_d(aylik) * AY_SAYISI - _d(yillik)) <= VADE_TUTARLILIK_TOLERANSI


def _metin(deger) -> str | None:
    if deger is None:
        return None
    if isinstance(deger, bool):
        return "Evet" if deger else "Hayır"
    if isinstance(deger, Decimal):
        return f"{deger.normalize():f}"
    return str(deger)[:60]


def _esit(a, b) -> bool:
    if isinstance(a, bool) or isinstance(b, bool):
        return bool(a) == bool(b)
    if a is None or b is None:
        return (a is None or a == "") and (b is None or b == "")
    if isinstance(a, (Decimal, int, float)) or isinstance(b, (Decimal, int, float)):
        return _d(a) == _d(b)
    return str(a) == str(b)


def _gecmis_yaz(session, cari_id: int, alan: str, eski, yeni) -> None:
    from database.models.cari_risk import CariRiskDegisiklik

    kid, kadi = _kullanici()
    session.add(CariRiskDegisiklik(
        cari_id=int(cari_id), alan=alan, eski_deger=_metin(eski), yeni_deger=_metin(yeni),
        kullanici_id=kid, kullanici_adi=kadi, zaman=datetime.now(),
    ))


def kart_degisikligini_uygula(session, cari, veriler: dict[str, Any], *, yeni_kart: bool = False) -> list[str]:
    """``veriler`` içindeki risk/oran alanlarını çıkarır, doğrular, yetkiyi denetler, karta yazar
    ve değişenleri geçmişe ekler. Değişen alan adlarını döner. Hiçbir hareket üretmez."""
    ilgili = {a: veriler.pop(a) for a in list(veriler) if a in KART_ALANLARI}
    if not ilgili:
        return []
    for limit_alan, uygula_alan in LIMIT_ALANLARI.values():
        if (limit_alan in ilgili) != (uygula_alan in ilgili):
            eksik = uygula_alan if limit_alan in ilgili else limit_alan
            ilgili[eksik] = getattr(cari, eksik, None)
    temiz = kart_alanlarini_dogrula(ilgili)
    degisen = []
    for alan, yeni in temiz.items():
        eski = getattr(cari, alan, None)
        if yeni_kart:
            if alan in RISK_ORANI_ALANLARI:
                varsayilan = VARSAYILAN_RISK_ORANI
            else:
                varsayilan = False if alan.endswith("_uygula") else None
            if not _esit(varsayilan, yeni):
                degisen.append(alan)
        elif not _esit(eski, yeni):
            degisen.append(alan)
    if degisen:
        from database.access import yetki_var

        if not yetki_var(IZIN_LIMIT):
            raise PermissionError(
                "Risk limiti / vade farkı oranı değiştirme yetkiniz yok (cari_risk_limit_duzenleme)."
            )
    eskiler = {alan: getattr(cari, alan, None) for alan in degisen}
    for alan, yeni in temiz.items():
        setattr(cari, alan, yeni)
    if degisen:
        session.flush()
        _tablolari_garanti(session)
        for alan in degisen:
            _gecmis_yaz(session, int(cari.id), alan, None if yeni_kart else eskiler[alan], temiz[alan])
    return degisen


def degisiklik_gecmisi(cari_id: int, alanlar: Iterable[str] | None = None) -> list[dict]:
    from database.database import get_session
    from database.models.cari_risk import CariRiskDegisiklik

    with get_session() as s:
        if not _tablo_var(s, CariRiskDegisiklik.__tablename__):
            return []
        sorgu = select(CariRiskDegisiklik).where(CariRiskDegisiklik.cari_id == int(cari_id))
        if alanlar:
            sorgu = sorgu.where(CariRiskDegisiklik.alan.in_(list(alanlar)))
        return [
            {"zaman": k.zaman, "alan": k.alan, "eski": k.eski_deger or "", "yeni": k.yeni_deger or "",
             "kullanici": k.kullanici_adi or ""}
            for k in s.scalars(sorgu.order_by(CariRiskDegisiklik.zaman.desc(), CariRiskDegisiklik.id.desc())).all()
        ]


def vade_farki_sabitle(cari) -> dict[str, Any] | None:
    """Oranı kullanacak gelecekteki bir belgeye kopyalanacak sabit değerler (esas dönem ve oranı).

    Kart oranı sonradan değişse de belgeye kopyalanan bu değer değişmez. Hesap/borç üretmez.
    """
    donem = getattr(cari, "vade_farki_donem", None)
    if donem not in (DONEM_AYLIK, DONEM_YILLIK):
        return None
    alan = "vade_farki_aylik_oran" if donem == DONEM_AYLIK else "vade_farki_yillik_oran"
    oran = getattr(cari, alan, None)
    if oran is None:
        return None
    return {"donem": donem, "oran": _d(oran), "tarih": date.today()}
