"""Hızlı Satış sepet satırı yardımcıları — birim seçimi, fiyat listesi, stok hareketleri.

Yeni formül icat edilmez:
- birim/katsayı → stok kartı (``StokService.birim_carpani_bul``)
- birim değişimi → ``fatura_satir_birim_service.birim_degistir`` (fatura ekranlarıyla aynı politika)
- birim fiyatı → ``StokService.birim_fiyati_getir`` (birime özel / oto×katsayı), yoksa temel×katsayı
- döviz → ``fatura_satir_birim_service.fiyat_cevir``
- hareketler → ``StokHareketi`` (stok_id) + belge→cari eşlemesi (``FiyatliStokEkstreService``)
"""

from __future__ import annotations

from datetime import date
from decimal import ROUND_HALF_UP, Decimal
from types import SimpleNamespace
from typing import Any

from sqlalchemy import select

from database.database import get_session
from database.models.stok import StokHareketi, StokKarti
from database.stok_service import (
    ESKI_FIYAT_ESLEME,
    SATIS_FIYAT_ADLARI,
    BirimDonusumHatasi,
    StokService,
    birim_anahtari,
)

KURUS = Decimal("0.01")
FIYAT_HASSASIYET = Decimal("0.0001")
KDV_METINLERI = {"HARIC": "KDV hariç", "DAHIL": "KDV dahil"}
KDV_BELIRSIZ_METNI = "KDV durumu belirtilmemiş"
HAREKET_LIMITI = 500


def kdv_durumu_normalle(deger) -> str | None:
    d = (str(deger or "")).strip().upper().replace("İ", "I").replace("Ç", "C")
    if d in ("HARIC", "KDV HARIC"):
        return "HARIC"
    if d in ("DAHIL", "KDV DAHIL"):
        return "DAHIL"
    return None


def kdv_dahilden_net(fiyat, kdv_orani) -> Decimal:
    """KDV dahil birim fiyattan satır motorunun beklediği KDV hariç birim fiyat."""
    k = _d(kdv_orani)
    if k < 0:
        raise ValueError("KDV oranı negatif olamaz.")
    return (_d(fiyat) / (Decimal("1") + k / Decimal("100"))).quantize(
        FIYAT_HASSASIYET, rounding=ROUND_HALF_UP
    )


def _d(deger, varsayilan: str = "0") -> Decimal:
    try:
        return Decimal(str(deger if deger is not None else varsayilan))
    except Exception:
        return Decimal(varsayilan)


def fiyat_adi_normalle(fiyat_adi: str | None) -> str:
    ad = (fiyat_adi or "SATIŞ FİYATI 1").strip().upper()
    return ESKI_FIYAT_ESLEME.get(ad, ad).upper()


# —— Birim ——


def satis_birim_secenekleri(stok_kodu: str) -> list[dict[str, Any]]:
    """Stok kartında kayıtlı, satışta kullanılabilir birimler.

    Her öğe: {birim, carpan, kullanilabilir, sebep, ana}. Pasif veya satışa kapalı
    birimler listelenmez; katsayısı eksik/geçersiz olan birim nedeniyle gösterilir,
    seçtirilmez. Serbest/genel birim eklenmez.
    """
    kod = (stok_kodu or "").strip()
    if not kod:
        return []
    with get_session() as session:
        from sqlalchemy.orm import selectinload

        stok = session.scalar(
            select(StokKarti)
            .where(StokKarti.stok_kodu == kod)
            .options(selectinload(StokKarti.birimler))
        )
        if stok is None:
            return []
        ana = (stok.birim or "Adet").strip() or "Adet"
        sonuc: list[dict[str, Any]] = [
            {"birim": ana, "carpan": Decimal("1"), "kullanilabilir": True, "sebep": "", "ana": True}
        ]
        gorulen = {birim_anahtari(ana)}
        for b in stok.birimler or []:
            ad = (b.birim_adi or "").strip()
            if not ad or birim_anahtari(ad) in gorulen:
                continue
            if getattr(b, "aktif", True) is False:
                continue
            if getattr(b, "satis_kullanilabilir", True) is False:
                continue
            gorulen.add(birim_anahtari(ad))
            carpan = _d(getattr(b, "carpan", None))
            if carpan <= 0:
                sonuc.append(
                    {
                        "birim": ad,
                        "carpan": None,
                        "kullanilabilir": False,
                        "sebep": "Katsayı tanımsız veya geçersiz — Stok Kartı > Birimler",
                        "ana": False,
                    }
                )
                continue
            sonuc.append(
                {"birim": ad, "carpan": carpan, "kullanilabilir": True, "sebep": "", "ana": False}
            )
        return sonuc


def birim_degisimi_hesapla(
    *,
    stok_kodu: str,
    eski_birim: str,
    yeni_birim: str,
    miktar,
    referans_fiyat,
    fiyat_adi: str | None,
) -> dict[str, Any]:
    """Satır birimi değişince yeni miktar / birim fiyat / katsayı.

    Politika fatura ekranlarıyla aynıdır: aynı fiziksel miktar yeni birimde ifade
    edilir; fiyat önce birime özel kayıtlı fiyattan, yoksa katsayıyla çevrilerek gelir.
    Kartta tanımsız / satışa kapalı / katsayısız birim ``ValueError``.
    """
    from fatura_satir_birim_service import birim_degistir

    secenek = next(
        (
            s
            for s in satis_birim_secenekleri(stok_kodu)
            if birim_anahtari(s["birim"]) == birim_anahtari(yeni_birim)
        ),
        None,
    )
    if secenek is None:
        raise ValueError(
            f"«{yeni_birim}» birimi bu stok kartında satış birimi olarak tanımlı değil."
        )
    if not secenek["kullanilabilir"]:
        raise ValueError(f"«{yeni_birim}» birimi kullanılamaz: {secenek['sebep']}")

    musteri = SimpleNamespace(
        satis_fiyat_listesi=fiyat_adi_normalle(fiyat_adi), musteri_grubu=None
    )
    satir = {
        "urun_kodu": stok_kodu,
        "birim": eski_birim,
        "miktar": str(miktar),
        "birim_satis_fiyati": str(referans_fiyat),
        "manuel_fiyat": False,
    }
    try:
        guncel = birim_degistir(satir, secenek["birim"], musteri=musteri, manuel_fiyat_modu="yeniden")
    except BirimDonusumHatasi as hata:
        raise ValueError(str(hata)) from hata
    if guncel is None:
        raise ValueError("Birim değişikliği yapılamadı.")
    yeni_miktar = _d(guncel.get("miktar"))
    if yeni_miktar <= 0:
        raise ValueError("Dönüştürülen miktar sıfır olamaz.")
    return {
        "birim": secenek["birim"],
        "miktar": yeni_miktar,
        "birim_fiyat": _d(guncel.get("birim_satis_fiyati")).quantize(FIYAT_HASSASIYET),
        "carpan": secenek["carpan"],
        "temel_miktar": _d(guncel.get("temel_miktar")),
    }


# —— Fiyat listesi ——


def _fiyat_sira_anahtari(ad: str) -> tuple:
    u = (ad or "").strip().upper()
    if u in SATIS_FIYAT_ADLARI:
        return (0, SATIS_FIYAT_ADLARI.index(u), u)
    if u.startswith("ALIŞ"):
        return (2, 0, u)
    return (1, 0, u)


def fiyat_secenekleri(
    stok_kodu: str,
    satir_birimi: str,
    *,
    fiyat_degistirme_izni: bool,
    maliyet_izni: bool,
    aktif_liste: str | None = None,
    tarih: date | None = None,
    satir_kdv_orani=None,
) -> list[dict[str, Any]]:
    """Stok kartında kayıtlı tüm fiyat türleri ve satıra uygulanacak karşılıkları.

    Kart fiyatları ana birimdedir. Satır motoru birim fiyatı KDV hariç kabul edip
    KDV'yi üstüne ekler; bu yüzden ``uygulanacak`` her zaman KDV hariç TL/satır
    birimidir. KDV anlamı ``StokFiyati.kdv_durumu``ndan okunur: DAHIL ise satır KDV
    oranıyla ayrıştırılır; kayıtsızsa (eski kayıtlar) ``kdv_durumu=None`` ve
    ``kdv_onay_gerekli=True`` döner — çağıran kullanıcıya sormadan uygulamaz.
    Satır birimi farklıysa birime özel kayıtlı fiyat; yoksa katsayıyla çevrilmiş
    fiyat önerilir. Döviz fiyatı TL'ye mevcut kur servisiyle çevrilir.
    Kullanılamayan seçenek ``kullanilabilir=False`` + ``sebep`` taşır.
    """
    from fatura_satir_birim_service import _stok_yukle, fiyat_cevir, para_birimi_normalle

    stok = _stok_yukle(stok_kodu)
    if stok is None:
        return []
    ana = (getattr(stok, "birim", None) or "Adet").strip() or "Adet"
    birim = (satir_birimi or ana).strip() or ana
    ayni_birim = birim_anahtari(birim) == birim_anahtari(ana)
    carpan = StokService.birim_carpani_bul(stok, birim, ana)
    aktif = fiyat_adi_normalle(aktif_liste) if aktif_liste else None

    sonuc: list[dict[str, Any]] = []
    for f in sorted(getattr(stok, "fiyatlar", None) or [], key=lambda x: _fiyat_sira_anahtari(x.fiyat_adi)):
        ad = (f.fiyat_adi or "").strip()
        ad_u = fiyat_adi_normalle(ad)
        alis = ad_u.startswith("ALIŞ")
        pb = para_birimi_normalle(getattr(f, "para_birimi", None))
        tutar = _d(f.tutar)
        kdv_durumu = kdv_durumu_normalle(getattr(f, "kdv_durumu", None))
        kayit = {
            "fiyat_adi": ad,
            "tutar": tutar,
            "birim": ana,
            "para_birimi": pb,
            "kdv_durumu": kdv_durumu,
            "kdv": KDV_METINLERI.get(kdv_durumu or "", KDV_BELIRSIZ_METNI),
            "kdv_onay_gerekli": kdv_durumu is None,
            "satir_birimi": birim,
            "uygulanacak": None,
            "kaynak": "",
            "kullanilabilir": True,
            "sebep": "",
            "aktif_liste": bool(aktif and ad_u == aktif),
        }
        if alis and not maliyet_izni:
            kayit.update(tutar=None, kullanilabilir=False, sebep="Alış/maliyet fiyatı görme yetkisi yok")
            sonuc.append(kayit)
            continue
        if tutar <= 0:
            kayit.update(kullanilabilir=False, sebep="Fiyat tanımsız (0)")
            sonuc.append(kayit)
            continue

        fiyat: Decimal | None
        if ayni_birim:
            fiyat = tutar
            kayit["kaynak"] = "Kart fiyatı"
        elif carpan is None:
            fiyat = None
            kayit.update(kullanilabilir=False, sebep=f"«{birim}» için katsayı tanımsız")
        else:
            fiyat = None
            if ad_u in SATIS_FIYAT_ADLARI or alis:
                try:
                    fiyat = StokService.birim_fiyati_getir(stok, birim, fiyat_adi=ad_u, alis=alis)
                except Exception:
                    fiyat = None
            if fiyat is not None and fiyat > 0:
                kayit["kaynak"] = f"{birim} birim fiyatı"
            else:
                fiyat = (tutar * carpan).quantize(FIYAT_HASSASIYET, rounding=ROUND_HALF_UP)
                kayit["kaynak"] = f"{ana} fiyatı × {carpan.normalize():f}"

        if fiyat is not None and kayit["kullanilabilir"]:
            try:
                fiyat_tl = fiyat_cevir(fiyat, pb, "TRY", tarih=tarih)
            except ValueError as hata:
                kayit.update(kullanilabilir=False, sebep=f"Kur bulunamadı ({hata})")
                fiyat_tl = None
            if fiyat_tl is not None:
                fiyat_tl = Decimal(str(fiyat_tl)).quantize(FIYAT_HASSASIYET)
                if pb != "TRY":
                    kayit["kaynak"] = f"{kayit['kaynak']} · {pb}→TL".strip(" ·")
                if kdv_durumu == "DAHIL":
                    if satir_kdv_orani in (None, ""):
                        kayit.update(kullanilabilir=False, sebep="Satır KDV oranı bilinmiyor; KDV ayrıştırılamaz")
                    else:
                        kayit["uygulanacak"] = kdv_dahilden_net(fiyat_tl, satir_kdv_orani)
                        kayit["kaynak"] = (
                            f"{kayit['kaynak']} · KDV dahil → net (%{_d(satir_kdv_orani).normalize():f})"
                        ).strip(" ·")
                else:
                    kayit["uygulanacak"] = fiyat_tl
                kayit["uygulanacak_ham"] = fiyat_tl

        if kayit["kullanilabilir"] and not fiyat_degistirme_izni:
            kayit.update(kullanilabilir=False, sebep="Satır fiyatı değiştirme yetkiniz yok")
        sonuc.append(kayit)
    return sonuc


# —— Stok hareketleri ——


def _belge_satir_ozeti(satirlar: list, stok_kodu: str) -> dict[str, Any] | None:
    from database.fiyatli_stok_ekstresi_service import _net_birim

    eslesen = [s for s in satirlar if (getattr(s, "urun_kodu", None) or "").strip() == stok_kodu]
    if not eslesen:
        return None
    birimler = {(getattr(s, "birim", None) or "").strip() for s in eslesen}
    net_fiyatlar = [_net_birim(s) for s in eslesen]
    tutar = Decimal("0")
    tutar_var = True
    for s, net in zip(eslesen, net_fiyatlar):
        if net is None:
            tutar_var = False
            continue
        tutar += (_d(getattr(s, "miktar", 0)) * net).quantize(KURUS, rounding=ROUND_HALF_UP)
    tek_birim = len(birimler) == 1
    miktar = sum((_d(getattr(s, "miktar", 0)) for s in eslesen), Decimal("0")) if tek_birim else None
    fiyatlar = {n for n in net_fiyatlar if n is not None}
    return {
        "miktar": miktar,
        "birim": next(iter(birimler)) if tek_birim else "çeşitli",
        "birim_fiyat": next(iter(fiyatlar)) if len(fiyatlar) == 1 and tek_birim else None,
        "tutar": tutar if tutar_var else None,
    }


IRSALIYE_HAREKETLERI = {
    "İRSALİYE ÇIKIŞ": "SATIS",
    "İRSALİYE İADE GİRİŞ": "IADE",
}


def _irsaliye_cari_haritasi(session, anahtarlar: set[tuple[str, str]]) -> dict[tuple[str, str], dict]:
    """(hareket türü, belge no) → irsaliye belgesinin cari kimliği.

    İade irsaliyesi kendi belgesinin ``cari_id``sini taşır (iade oluşturulurken kaynak
    irsaliyeden kimlikle kopyalanır). Belge türü harekete uymuyorsa veya cari bağı yoksa
    eşleme yapılmaz — isim benzerliği kullanılmaz.
    """
    if not anahtarlar:
        return {}
    from database.models.cari import Cari
    from database.models.satis_irsaliyesi import SatisIrsaliyesi, SatisIrsaliyesiSatiri

    belge_nolari = {bn for _, bn in anahtarlar}
    sonuc: dict[tuple[str, str], dict] = {}
    for irs in session.scalars(
        select(SatisIrsaliyesi).where(SatisIrsaliyesi.irsaliye_no.in_(belge_nolari))
    ).all():
        if getattr(irs, "is_deleted", False):
            continue
        iade = (getattr(irs, "belge_turu", None) or "").strip().upper() == "IADE"
        tur = "İRSALİYE İADE GİRİŞ" if iade else "İRSALİYE ÇIKIŞ"
        if (tur, irs.irsaliye_no) not in anahtarlar:
            continue
        cari = session.get(Cari, int(irs.cari_id)) if irs.cari_id else None
        sonuc[(tur, irs.irsaliye_no)] = {
            "belge_turu": "İrsaliye İadesi" if iade else "Satış İrsaliyesi",
            "cari_id": int(cari.id) if cari else None,
            "cari_kodu": (cari.cari_kodu or "").strip() if cari else "",
            "cari_adi": (cari.unvan or "").strip() if cari else "",
            "_satirlar": list(
                session.scalars(
                    select(SatisIrsaliyesiSatiri).where(SatisIrsaliyesiSatiri.irsaliye_id == irs.id)
                ).all()
            ),
        }
    return sonuc


TUM_TARIHLER_BASLANGIC = date(1900, 1, 1)


def hareket_donem_secenekleri() -> list[dict[str, Any]]:
    """Stok hareketleri penceresi için dönem seçenekleri (aktif dönem ilk, tüm tarihler son)."""
    from database.fiyatli_stok_ekstresi_service import _aktif_donem_tarihleri

    bugun = date.today()
    vb, ve = _aktif_donem_tarihleri()
    secenekler: list[dict[str, Any]] = [
        {"etiket": f"Aktif dönem ({vb:%d.%m.%Y}–{ve:%d.%m.%Y})", "baslangic": vb, "bitis": ve}
    ]
    try:
        from database.donem_service import DonemService

        for d in DonemService.listele():
            bas, bit = d.get("baslangic_tarihi"), d.get("bitis_tarihi")
            if not bas or not bit or (bas, min(bit, bugun)) == (vb, ve):
                continue
            secenekler.append(
                {
                    "etiket": f"{d.get('donem_adi') or 'Dönem'} ({bas:%d.%m.%Y}–{bit:%d.%m.%Y})",
                    "baslangic": bas,
                    "bitis": min(bit, bugun) if bas <= bugun else bit,
                }
            )
    except Exception:  # noqa: BLE001 — dönem tablosu yoksa yalnız aktif/tüm
        pass
    secenekler.append(
        {"etiket": "Tüm tarihler", "baslangic": TUM_TARIHLER_BASLANGIC, "bitis": max(bugun, ve)}
    )
    return secenekler


def stok_hareketleri(
    stok_id: int,
    *,
    cari_id: int | None,
    baslangic: date | None = None,
    bitis: date | None = None,
    limit: int = HAREKET_LIMITI,
) -> dict[str, Any]:
    """Seçili stokun hareketleri; ``cari_id`` verilirse yalnızca o müşteriyle olanlar.

    Filtre kimliklerle yapılır (``StokHareketi.stok_id`` + belge başlığı ``cari_id``;
    irsaliye ve iade irsaliyesi kendi belgesinin ``cari_id``si). Cari bağı belirlenemeyen
    hareket müşteri görünümüne girmez. Varsayılan tarih aralığı aktif dönemdir; önceki
    dönemler için ``baslangic``/``bitis`` verilir. Sıralama: tarih ↓, kayıt zamanı ↓,
    hareket id ↓ (aynı belgede lot bölünmesi tek satırda toplanır). Salt okunur.
    """
    from database.fiyatli_stok_ekstresi_service import (
        _ETIKET,
        FiyatliStokEkstreService,
        _aktif_donem_tarihleri,
    )

    if not stok_id:
        raise ValueError("Stok seçilmedi.")
    if baslangic is None or bitis is None:
        vb, ve = _aktif_donem_tarihleri()
        baslangic = baslangic or vb
        bitis = bitis or ve
    if baslangic > bitis:
        raise ValueError("Başlangıç tarihi bitiş tarihinden sonra olamaz.")
    maliyet_ok = FiyatliStokEkstreService.maliyet_gorunsun_mu()

    with get_session() as session:
        stok = session.get(StokKarti, int(stok_id))
        if stok is None or getattr(stok, "is_deleted", False):
            raise ValueError("Stok kartı bulunamadı veya silinmiş.")
        stok_kodu = (stok.stok_kodu or "").strip()
        ana = (stok.birim or "Adet").strip() or "Adet"
        hareketler = list(
            session.scalars(
                select(StokHareketi)
                .where(
                    StokHareketi.stok_id == int(stok_id),
                    StokHareketi.tarih >= baslangic,
                    StokHareketi.tarih <= bitis,
                )
                .order_by(
                    StokHareketi.tarih.desc(),
                    StokHareketi.olusturma_tarihi.desc(),
                    StokHareketi.id.desc(),
                )
            ).all()
        )
        belge_map = FiyatliStokEkstreService._belge_cari_haritasi(session, hareketler)
        irs_map = _irsaliye_cari_haritasi(
            session,
            {
                (h.hareket_turu, (h.belge_no or "").strip())
                for h in hareketler
                if (h.hareket_turu or "") in IRSALIYE_HAREKETLERI and (h.belge_no or "").strip()
            },
        )

        gruplar: dict[tuple[str, str, date], dict[str, Any]] = {}
        sira: list[tuple[str, str, date]] = []
        for h in hareketler:
            tur = h.hareket_turu or ""
            bn = (h.belge_no or "").strip()
            meta = belge_map.get((tur, bn)) or irs_map.get((tur, bn)) or {}
            if cari_id is not None and meta.get("cari_id") != int(cari_id):
                continue
            anahtar = (tur, bn, h.tarih)
            g = gruplar.get(anahtar)
            if g is None:
                g = {
                    "hareket_id": int(h.id),
                    "tarih": h.tarih,
                    "zaman": h.olusturma_tarihi,
                    "hareket_turu": tur,
                    "belge_no": bn,
                    "belge_turu": meta.get("belge_turu") or _ETIKET.get(tur, tur.title()),
                    "cari_id": meta.get("cari_id"),
                    "cari": " — ".join(
                        x for x in (meta.get("cari_kodu") or "", meta.get("cari_adi") or "") if x
                    ),
                    "yon": FiyatliStokEkstreService._yon(tur),
                    "temel_miktar": Decimal("0"),
                    "_satirlar": meta.get("_satirlar") or [],
                }
                gruplar[anahtar] = g
                sira.append(anahtar)
            g["temel_miktar"] += _d(h.miktar)

        satirlar: list[dict[str, Any]] = []
        for anahtar in sira[: max(1, int(limit))]:
            g = gruplar[anahtar]
            ozet = _belge_satir_ozeti(g.pop("_satirlar"), stok_kodu)
            gizli = (not maliyet_ok) and g["hareket_turu"] in ("FATURA GİRİŞ", "ALIŞ İADE ÇIKIŞ")
            if ozet and ozet["miktar"] is not None:
                miktar, birim = ozet["miktar"], ozet["birim"]
            else:
                miktar, birim = g["temel_miktar"], ana
            zaman = g.pop("zaman")
            g.update(
                saat=zaman.strftime("%H:%M") if zaman else "",
                miktar=miktar,
                birim=birim,
                birim_fiyat=None if gizli or not ozet else ozet["birim_fiyat"],
                tutar=None if gizli or not ozet else ozet["tutar"],
                para_birimi="TL",
                fiyat_notu="Yetki yok" if gizli else ("" if ozet else "Belge satırı yok"),
            )
            satirlar.append(g)

        return {
            "stok_id": int(stok.id),
            "stok_kodu": stok_kodu,
            "stok_adi": stok.stok_adi,
            "ana_birim": ana,
            "baslangic": baslangic,
            "bitis": bitis,
            "cari_id": cari_id,
            "satirlar": satirlar,
            "toplam_kayit": len(sira),
            "kesildi": len(sira) > len(satirlar),
        }
