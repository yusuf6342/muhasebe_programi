"""Alış faturası → stok kartı ALIŞ FİYATI (iskonto sonrası **KDV dahil** net birim).

Kurallar
--------
* Stok alış = (iskonto sonrası KDV dahil net satır tutarı) ÷ miktar
  = iskonto sonrası KDV hariç birim × (1 + satır KDV%/100).
* Belgedeki ``birim_fiyat`` KDV hariç kabul edilir (alış kaydı); KDV ikinci kez eklenmez
  (``kdv_dahil`` satır bayrağı varsa dahil fiyat olduğu gibi kullanılır).
* Ana birime ``birim_carpani`` ile çevrilir; dövizde faturanın kayıtlı kuruyla TL.
* Stok kartına ``kdv_durumu=DAHIL`` yazılır. FIFO/stok giriş maliyeti KDV hariç kalır.
* EvoBulut faturaları hariç; stok kartının Evo’dan gelmiş olması engel değildir.
* En güncel geçerli fatura kazanır; iptal/onay kaldırmada yeniden belirlenir.
"""
from __future__ import annotations

import json
from datetime import date, datetime
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path
from typing import Any

from sqlalchemy import func, select, text
from sqlalchemy.orm import Session, selectinload

from database.database import get_session
from database.models.alis_faturasi import AlisFaturasi, AlisFaturasiSatiri
from database.models.stok import StokFiyatGecmisi, StokFiyati, StokKarti

SIFIR = Decimal("0")
KAYNAK_EVO = "EVOBULUT"
KAYNAK_CIN = "CIN_MUHASEBE"
FIYAT_ADI = "ALIŞ FİYATI"
_HASSASIYET = Decimal("0.00000001")  # ara hesap
_KAYIT_Q = Decimal("0.0001")  # stok kartına yazılan

_schema_ok = False


def _d(v) -> Decimal:
    try:
        return Decimal(str(v if v not in (None, "") else 0))
    except Exception:
        return SIFIR


def _q(v, q=_KAYIT_Q) -> Decimal:
    return _d(v).quantize(q, rounding=ROUND_HALF_UP)


def schema_hazirla(bind=None) -> None:
    """Alış fatura kaynak alanları + fiyat geçmişi kaynak kolonları."""
    global _schema_ok
    from database.database import Base, engine
    from database.modul_sema import eksik_kolonlari_ekle

    bag = bind or engine
    if bag is None:
        return
    Base.metadata.create_all(
        bind=bag,
        tables=[AlisFaturasi.__table__, StokFiyatGecmisi.__table__, StokFiyati.__table__],
    )
    eksik_kolonlari_ekle(
        bag,
        "alis_faturalari",
        {
            "kaynak_sistem": "VARCHAR(40)",
            "kaynak_kimlik": "VARCHAR(80)",
        },
    )
    eksik_kolonlari_ekle(
        bag,
        "stok_fiyat_gecmisi",
        {
            "para_birimi": "VARCHAR(10)",
            "birim": "VARCHAR(30)",
            "kaynak_fatura_id": "INTEGER",
            "kaynak_satir_id": "INTEGER",
            "kaynak_fatura_no": "VARCHAR(50)",
            "aciklama": "VARCHAR(300)",
        },
    )
    _schema_ok = True


def net_birim_kdv_haric(
    birim_fiyat,
    iskonto1=0,
    iskonto2=0,
    iskonto3=0,
) -> Decimal:
    """İskonto sonrası KDV hariç birim (yuvarlamasız ara hassasiyet)."""
    from database.iskonto_hesap_service import iskonto_carpani

    return _d(birim_fiyat) * iskonto_carpani(iskonto1, iskonto2, iskonto3)


def net_birim_kdv_dahil(
    birim_fiyat,
    iskonto1=0,
    iskonto2=0,
    iskonto3=0,
    kdv_orani=0,
    *,
    kdv_dahil_giris: bool = False,
) -> Decimal:
    """İskonto sonrası KDV dahil birim (yuvarlamasız).

    ``kdv_dahil_giris=False`` (alış varsayılanı): birim KDV hariç → ×(1+KDV/100).
    ``kdv_dahil_giris=True``: birim zaten KDV dahil; KDV ikinci kez eklenmez.
    """
    from database.iskonto_hesap_service import iskonto_carpani

    isk_sonrasi = _d(birim_fiyat) * iskonto_carpani(iskonto1, iskonto2, iskonto3)
    if kdv_dahil_giris:
        return isk_sonrasi
    kdv = _d(kdv_orani)
    if kdv < 0:
        kdv = SIFIR
    return isk_sonrasi * (Decimal("1") + kdv / Decimal("100"))


def satir_net_birim_ana(
    satir: AlisFaturasiSatiri,
    fatura: AlisFaturasi,
    *,
    kdv_dahil: bool = True,
) -> Decimal | None:
    """Satır net birim → stok ana birimi, TRY.

    Varsayılan ``kdv_dahil=True``: stok kartı ALIŞ FİYATI.
    ``kdv_dahil=False``: maliyet/FIFO için KDV hariç net.
    Genel iskonto satır fiyatlarına dağıtılmışsa ikinci kez uygulanmaz.
    """
    miktar = _d(satir.miktar)
    if miktar <= 0:
        return None
    kod = (satir.urun_kodu or "").strip()
    if not kod:
        return None
    carpan = _d(getattr(satir, "birim_carpani", None) or 1)
    if carpan <= 0:
        carpan = Decimal("1")

    pb = (fatura.para_birimi or "TRY").upper()
    tl_fiyat = _d(satir.birim_fiyat)
    doviz = _d(getattr(satir, "birim_fiyat_doviz", 0) or 0)
    # TL birim boş/sıfır, döviz doluysa faturanın kayıtlı kuruyla çevir
    if tl_fiyat <= 0 and doviz > 0 and pb != "TRY":
        kur = _d(fatura.kur or 1)
        if kur <= 0:
            return None
        tl_fiyat = doviz * kur

    # Alış belgesinde birim_fiyat KDV hariç; ileride satır bayrağı olursa saygı duy
    dahil_giris = bool(getattr(satir, "kdv_dahil", False) or getattr(satir, "fiyat_kdv_dahil", False))
    if kdv_dahil:
        net = net_birim_kdv_dahil(
            tl_fiyat,
            satir.iskonto_orani,
            getattr(satir, "iskonto_orani_2", 0) or 0,
            getattr(satir, "iskonto_orani_3", 0) or 0,
            getattr(satir, "kdv_orani", 0) or 0,
            kdv_dahil_giris=dahil_giris,
        )
    else:
        if dahil_giris:
            # Dahil girilmiş fiyattan matrah ayır
            dahil = net_birim_kdv_dahil(
                tl_fiyat,
                satir.iskonto_orani,
                getattr(satir, "iskonto_orani_2", 0) or 0,
                getattr(satir, "iskonto_orani_3", 0) or 0,
                0,
                kdv_dahil_giris=True,
            )
            kdv = _d(getattr(satir, "kdv_orani", 0) or 0)
            net = dahil / (Decimal("1") + kdv / Decimal("100")) if kdv > 0 else dahil
        else:
            net = net_birim_kdv_haric(
                tl_fiyat,
                satir.iskonto_orani,
                getattr(satir, "iskonto_orani_2", 0) or 0,
                getattr(satir, "iskonto_orani_3", 0) or 0,
            )
    if net < 0:
        return None
    return net / carpan


def evo_alis_mi(fatura: AlisFaturasi) -> bool | None:
    """True=Evo, False=Cin/yerel, None=kesin değil (atla).

    Önce ``kaynak_sistem``; sonra EVB-AF / EVB-AFIS önekleri ve evo engel kimlikleri.
    Yalnızca kısa AF* / belirsiz seri → None (raporla, kullanma).
    """
    sistem = (getattr(fatura, "kaynak_sistem", None) or "").strip().upper()
    if sistem == KAYNAK_EVO:
        return True
    if sistem and sistem != KAYNAK_EVO:
        return False
    no = (fatura.fatura_no or "").strip()
    nu = no.upper()
    if nu.startswith("EVB-AF-") or nu.startswith("EVB-AFIS-") or nu.startswith("EVB-AL"):
        return True
    if nu.startswith("EVB-"):
        # Diğer EVB belge türleri alış değil; yine Evo ekosistemi — alış fiyat kaynağı olmasın
        return True
    try:
        from database.evo_belge_engel_service import evo_belge_kimlikleri

        kimlikler = evo_belge_kimlikleri(no)
        if any(k.upper().startswith("AF:") or "EVB-AF" in k.upper() for k in kimlikler):
            return True
    except Exception:
        pass
    # Yerel Cin önekleri (ARAY, SAF alış değil ama alışta ARAY vb.)
    if nu.startswith("ARAY") or nu.startswith("ALF") or nu.startswith("AFŞ") or nu.startswith("AFS"):
        return False
    # Kaynak alanı yok ve EVB değil → Cin kabul (aktif firma yerel belgeleri)
    # Belirsiz kısa kodları None bırakma: kullanıcı «yalnız EVB hariç» dedi; yereli dahil et
    return False


def _stok_girisi_var(session: Session, fatura_no: str) -> bool:
    from database.models.stok import StokHareketi

    n = session.scalar(
        select(func.count())
        .select_from(StokHareketi)
        .where(
            StokHareketi.belge_no == fatura_no,
            StokHareketi.hareket_turu == "FATURA GİRİŞ",
        )
    )
    return int(n or 0) > 0


def fatura_gecerli_kaynak_mi(session: Session, fatura: AlisFaturasi) -> tuple[bool, str]:
    if (fatura.durum or "") == "İPTAL":
        return False, "iptal"
    evo = evo_alis_mi(fatura)
    if evo is True:
        return False, "evo_bulut"
    if evo is None:
        return False, "kaynak_belirsiz"
    if getattr(fatura, "onaylandi", False):
        return True, "onayli"
    if _stok_girisi_var(session, fatura.fatura_no):
        return True, "stok_islenmis"
    return False, "taslak_islenmemis"


def _saat_anahtar(saat: str | None) -> str:
    s = (saat or "").strip()
    if len(s) >= 5 and s[2] == ":":
        return s[:8] if len(s) >= 8 else s[:5] + ":00"
    return "00:00:00"


def fatura_sira_anahtari(fatura: AlisFaturasi) -> tuple:
    """En güncel önce (desc sıralama için ters çevrilmeden tuple karşılaştırması)."""
    onay = getattr(fatura, "onay_tarihi", None) or datetime.min
    return (
        fatura.fatura_tarihi or date.min,
        _saat_anahtar(getattr(fatura, "islem_saati", None)),
        onay,
        int(fatura.id or 0),
    )


def _kaynak_gecmis_son(
    session: Session, stok_id: int
) -> StokFiyatGecmisi | None:
    return session.scalar(
        select(StokFiyatGecmisi)
        .where(
            StokFiyatGecmisi.stok_id == int(stok_id),
            StokFiyatGecmisi.fiyat_adi == FIYAT_ADI,
            StokFiyatGecmisi.kaynak_fatura_id.isnot(None),
        )
        .order_by(StokFiyatGecmisi.degisim_tarihi.desc(), StokFiyatGecmisi.id.desc())
        .limit(1)
    )


def _fatura_yeniden_mi(
    session: Session, aday: AlisFaturasi, mevcut_fatura_id: int | None
) -> bool:
    """Aday, mevcut kaynak faturadan daha yeni veya eşit mi?"""
    if not mevcut_fatura_id:
        return True
    if int(aday.id) == int(mevcut_fatura_id):
        return True
    mevcut = session.get(AlisFaturasi, int(mevcut_fatura_id))
    if mevcut is None:
        return True
    return fatura_sira_anahtari(aday) >= fatura_sira_anahtari(mevcut)


def alis_fiyatini_yaz(
    session: Session,
    *,
    stok: StokKarti,
    yeni_fiyat: Decimal,
    fatura: AlisFaturasi,
    satir: AlisFaturasiSatiri,
    zorla: bool = False,
) -> dict[str, Any]:
    """Stok ALIŞ FİYATI güncelle + geçmiş. Yeniyi ezmez (zorla=False)."""
    schema_hazirla(session.get_bind())
    yeni = _q(yeni_fiyat)
    mevcut_f = next((f for f in (stok.fiyatlar or []) if f.fiyat_adi == FIYAT_ADI), None)
    eski = _d(mevcut_f.tutar) if mevcut_f is not None else None

    son = _kaynak_gecmis_son(session, int(stok.id))
    onceki_fid = int(son.kaynak_fatura_id) if son and son.kaynak_fatura_id else None
    if not zorla and not _fatura_yeniden_mi(session, fatura, onceki_fid):
        return {
            "durum": "atlandi",
            "gerekce": "daha_guncel_kaynak_var",
            "stok_kodu": stok.stok_kodu,
            "eski": eski,
            "yeni": eski,
            "fatura_no": fatura.fatura_no,
            "satir_id": int(satir.id) if satir.id else None,
        }

    if mevcut_f is None:
        session.add(
            StokFiyati(
                stok_id=int(stok.id),
                fiyat_adi=FIYAT_ADI,
                tutar=yeni,
                para_birimi="TL",
                kdv_durumu="DAHIL",
            )
        )
    else:
        if (
            eski is not None
            and _q(eski) == yeni
            and onceki_fid == int(fatura.id)
            and (getattr(mevcut_f, "kdv_durumu", None) or "").upper() == "DAHIL"
        ):
            return {
                "durum": "ayni",
                "gerekce": "degismedi",
                "stok_kodu": stok.stok_kodu,
                "eski": eski,
                "yeni": yeni,
                "fatura_no": fatura.fatura_no,
                "satir_id": int(satir.id) if satir.id else None,
            }
        mevcut_f.tutar = yeni
        mevcut_f.kdv_durumu = "DAHIL"
        mevcut_f.para_birimi = "TL"

    gecmis = StokFiyatGecmisi(
        stok_id=int(stok.id),
        fiyat_adi=FIYAT_ADI,
        eski_tutar=eski,
        yeni_tutar=yeni,
        degisim_tarihi=datetime.now(),
    )
    # Dinamik kolonlar
    if hasattr(gecmis, "para_birimi"):
        gecmis.para_birimi = "TL"
    if hasattr(gecmis, "birim"):
        gecmis.birim = (stok.birim or "Adet")[:30]
    if hasattr(gecmis, "kaynak_fatura_id"):
        gecmis.kaynak_fatura_id = int(fatura.id)
    if hasattr(gecmis, "kaynak_satir_id"):
        gecmis.kaynak_satir_id = int(satir.id) if satir.id else None
    if hasattr(gecmis, "kaynak_fatura_no"):
        gecmis.kaynak_fatura_no = (fatura.fatura_no or "")[:50]
    if hasattr(gecmis, "aciklama"):
        gecmis.aciklama = f"Alış KDV dahil net ← {fatura.fatura_no}"[:300]
    session.add(gecmis)
    return {
        "durum": "guncellendi",
        "gerekce": "ok",
        "stok_kodu": stok.stok_kodu,
        "stok_adi": stok.stok_adi,
        "eski": eski,
        "yeni": yeni,
        "fatura_no": fatura.fatura_no,
        "fatura_id": int(fatura.id),
        "satir_id": int(satir.id) if satir.id else None,
    }


def fatura_alis_fiyatlarini_uygula(
    session: Session,
    fatura: AlisFaturasi,
    *,
    zorla: bool = False,
) -> list[dict[str, Any]]:
    """İşlenmiş faturanın satırlarından stok alış fiyatlarını güncelle."""
    schema_hazirla(session.get_bind())
    ok, neden = fatura_gecerli_kaynak_mi(session, fatura)
    rapor: list[dict[str, Any]] = []
    if not ok:
        return [
            {
                "durum": "atlandi",
                "gerekce": neden,
                "fatura_no": fatura.fatura_no,
            }
        ]

    # Aynı stok birden fazla satırda → son satır (id) kazanır
    son_satir: dict[str, AlisFaturasiSatiri] = {}
    for sat in sorted(fatura.satirlar or [], key=lambda s: int(s.id or 0)):
        kod = (sat.urun_kodu or "").strip()
        if kod:
            son_satir[kod] = sat

    kodlar = list(son_satir.keys())
    kartlar = {
        k.stok_kodu: k
        for k in session.scalars(
            select(StokKarti)
            .where(StokKarti.stok_kodu.in_(kodlar))
            .options(selectinload(StokKarti.fiyatlar))
        ).all()
    } if kodlar else {}

    for kod, sat in son_satir.items():
        kart = kartlar.get(kod)
        if kart is None:
            rapor.append(
                {
                    "durum": "atlandi",
                    "gerekce": "stok_yok",
                    "stok_kodu": kod,
                    "fatura_no": fatura.fatura_no,
                    "satir_id": int(sat.id) if sat.id else None,
                }
            )
            continue
        net = satir_net_birim_ana(sat, fatura)
        if net is None:
            rapor.append(
                {
                    "durum": "atlandi",
                    "gerekce": "net_hesaplanamadi_veya_sifir_miktar",
                    "stok_kodu": kod,
                    "fatura_no": fatura.fatura_no,
                    "satir_id": int(sat.id) if sat.id else None,
                }
            )
            continue
        rapor.append(
            alis_fiyatini_yaz(
                session,
                stok=kart,
                yeni_fiyat=net,
                fatura=fatura,
                satir=sat,
                zorla=zorla,
            )
        )
    return rapor


def stok_icin_en_guncel_kaynak(
    session: Session, stok_kodu: str
) -> tuple[AlisFaturasi, AlisFaturasiSatiri] | None:
    """Stok için en güncel geçerli (Evo hariç) alış satırı."""
    kod = (stok_kodu or "").strip()
    if not kod:
        return None
    satirlar = list(
        session.scalars(
            select(AlisFaturasiSatiri)
            .join(AlisFaturasi, AlisFaturasi.id == AlisFaturasiSatiri.fatura_id)
            .where(
                AlisFaturasiSatiri.urun_kodu == kod,
                AlisFaturasi.durum != "İPTAL",
            )
            .options(selectinload(AlisFaturasiSatiri.fatura))
            .order_by(
                AlisFaturasi.fatura_tarihi.desc(),
                AlisFaturasi.id.desc(),
                AlisFaturasiSatiri.id.desc(),
            )
        ).all()
    )
    adaylar: list[tuple[tuple, AlisFaturasi, AlisFaturasiSatiri]] = []
    for sat in satirlar:
        f = sat.fatura
        if f is None:
            continue
        ok, _ = fatura_gecerli_kaynak_mi(session, f)
        if not ok:
            continue
        if _d(sat.miktar) <= 0:
            continue
        if satir_net_birim_ana(sat, f) is None:
            continue
        adaylar.append((fatura_sira_anahtari(f) + (int(sat.id or 0),), f, sat))
    if not adaylar:
        return None
    adaylar.sort(key=lambda x: x[0], reverse=True)
    return adaylar[0][1], adaylar[0][2]


def stok_alis_fiyatini_yeniden_belirle(
    session: Session, stok_kodu: str
) -> dict[str, Any]:
    """İptal/onay kaldırma sonrası kalan geçerli kaynaktan fiyatı kur."""
    pair = stok_icin_en_guncel_kaynak(session, stok_kodu)
    if pair is None:
        return {"durum": "atlandi", "gerekce": "gecerli_kaynak_yok", "stok_kodu": stok_kodu}
    fatura, satir = pair
    kart = session.scalar(
        select(StokKarti)
        .where(StokKarti.stok_kodu == stok_kodu.strip())
        .options(selectinload(StokKarti.fiyatlar))
    )
    if kart is None:
        return {"durum": "atlandi", "gerekce": "stok_yok", "stok_kodu": stok_kodu}
    net = satir_net_birim_ana(satir, fatura)
    if net is None:
        return {"durum": "atlandi", "gerekce": "net_yok", "stok_kodu": stok_kodu}
    return alis_fiyatini_yaz(
        session, stok=kart, yeni_fiyat=net, fatura=fatura, satir=satir, zorla=True
    )


def gecmis_taramasi_uygula(*, yedek_dir: str | Path | None = None) -> dict[str, Any]:
    """Tüm geçerli Cin alışlarından stok başına en güncel net fiyatı uygula."""
    from database.access import yazma_zorunlu

    yazma_zorunlu("stok_duzenleme", "alis_fatura_duzenleme", "alis_duzenleme")
    schema_hazirla()
    yedek_yolu = None
    with get_session() as session:
        # Yedek: stok alış fiyatları
        fiyatlar = list(
            session.execute(
                select(
                    StokKarti.stok_kodu,
                    StokKarti.stok_adi,
                    StokFiyati.tutar,
                    StokFiyati.para_birimi,
                )
                .join(StokFiyati, StokFiyati.stok_id == StokKarti.id)
                .where(StokFiyati.fiyat_adi == FIYAT_ADI)
            ).all()
        )
        yedek = {
            "zaman": datetime.now().isoformat(timespec="seconds"),
            "alis_fiyatlari": [
                {
                    "stok_kodu": r[0],
                    "stok_adi": r[1],
                    "tutar": str(r[2]),
                    "para_birimi": r[3],
                }
                for r in fiyatlar
            ],
        }
        klasor = Path(yedek_dir) if yedek_dir else Path("kurulum/dnm_d2_20260901/rapor")
        klasor.mkdir(parents=True, exist_ok=True)
        yedek_yolu = klasor / f"yedek_alis_fiyat_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
        yedek_yolu.write_text(json.dumps(yedek, ensure_ascii=False, indent=2), encoding="utf-8")

        faturalar = list(
            session.scalars(
                select(AlisFaturasi)
                .where(AlisFaturasi.durum != "İPTAL")
                .options(selectinload(AlisFaturasi.satirlar))
                .order_by(AlisFaturasi.fatura_tarihi.asc(), AlisFaturasi.id.asc())
            ).all()
        )
        # Mevcut EVB-* belgelerini kaynak_sistem ile işaretle (önek + engel)
        for f in faturalar:
            if getattr(f, "kaynak_sistem", None):
                continue
            evo = evo_alis_mi(f)
            if evo is True:
                f.kaynak_sistem = KAYNAK_EVO
            elif evo is False:
                f.kaynak_sistem = KAYNAK_CIN
        session.flush()

        # Stok → en güncel (fatura, satir)
        en_guncel: dict[str, tuple[tuple, AlisFaturasi, AlisFaturasiSatiri]] = {}
        atlanan_belge: list[dict] = []
        for f in faturalar:
            ok, neden = fatura_gecerli_kaynak_mi(session, f)
            if not ok:
                atlanan_belge.append({"fatura_no": f.fatura_no, "gerekce": neden})
                continue
            # Aynı fatura içinde stok bazında son satır
            son: dict[str, AlisFaturasiSatiri] = {}
            for sat in sorted(f.satirlar or [], key=lambda s: int(s.id or 0)):
                kod = (sat.urun_kodu or "").strip()
                if kod and _d(sat.miktar) > 0:
                    son[kod] = sat
            anahtar_f = fatura_sira_anahtari(f)
            for kod, sat in son.items():
                if satir_net_birim_ana(sat, f) is None:
                    continue
                tam = anahtar_f + (int(sat.id or 0),)
                once = en_guncel.get(kod)
                if once is None or tam >= once[0]:
                    en_guncel[kod] = (tam, f, sat)

        rapor_satir: list[dict] = []
        for kod, (_a, f, sat) in sorted(en_guncel.items()):
            kart = session.scalar(
                select(StokKarti)
                .where(StokKarti.stok_kodu == kod)
                .options(selectinload(StokKarti.fiyatlar))
            )
            if kart is None:
                rapor_satir.append(
                    {"durum": "atlandi", "gerekce": "stok_yok", "stok_kodu": kod}
                )
                continue
            net = satir_net_birim_ana(sat, f)
            rapor_satir.append(
                alis_fiyatini_yaz(
                    session, stok=kart, yeni_fiyat=net, fatura=f, satir=sat, zorla=True
                )
            )
        session.flush()
        return {
            "yedek": str(yedek_yolu),
            "belge_taranan": len(faturalar),
            "belge_atlanan": atlanan_belge,
            "stok_hedef": len(en_guncel),
            "sonuclar": rapor_satir,
            "guncellenen": sum(1 for r in rapor_satir if r.get("durum") == "guncellendi"),
            "atlanan": sum(1 for r in rapor_satir if r.get("durum") != "guncellendi"),
        }
