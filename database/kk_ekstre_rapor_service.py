"""Firma kredi kartı hesap ekstresi — ekran / PDF / Excel ortak veri kümesi."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path
from typing import Any

from database.kredi_karti_ekstre_service import KrediKartiEkstreService
from database.finans_service import FinansService

SIFIR = Decimal("0.00")


def _d(val) -> Decimal:
    return Decimal(str(val or 0)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def _maskeli_kart(kart) -> str:
    son4 = (getattr(kart, "son_dort_hane", None) or "").strip()
    if not son4 and getattr(kart, "kart_numarasi", None):
        no = "".join(ch for ch in str(kart.kart_numarasi) if ch.isdigit())
        son4 = no[-4:] if len(no) >= 4 else ""
    return f"****{son4}" if son4 else "****"


def _dosya_ad_parca(kart, donem_etiket: str) -> str:
    maske = _maskeli_kart(kart).replace("*", "")
    guvenli = "".join(ch if ch.isalnum() or ch in "-_" else "_" for ch in donem_etiket)
    return f"KK_Ekstre_{maske}_{guvenli}_{datetime.now().strftime('%Y%m%d_%H%M%S')}"


def _odeme_detay_satiri(o: dict, *, ekstre_kesim: date | None, mahsup: Decimal) -> dict[str, Any]:
    return {
        "id": o.get("id"),
        "tarih": o.get("tarih"),
        "belge_no": o.get("belge_no") or "",
        "tutar": _d(o.get("tutar")),
        "mahsup": _d(mahsup),
        "ekstre_kesim_tarihi": ekstre_kesim,
        "dekont_no": o.get("dekont_no") or "",
        "aciklama": o.get("aciklama") or "",
        "kaynak": o.get("kaynak") or "",
        "iptal": bool(o.get("iptal")),
        "iptal_tarihi": o.get("iptal_tarihi"),
        "finans_hesap_id": o.get("finans_hesap_id"),
    }


def _satirdan_hareket(s: dict, *, satir_turu: str = "TAKSIT") -> dict[str, Any]:
    yansima = s.get("taksit_vade_tarihi") or s.get("yansima_tarihi") or s.get("islem_tarihi")
    return {
        "satir_turu": satir_turu,
        "kaynak_tarihi": s.get("islem_tarihi"),
        "yansima_tarihi": yansima,
        "tarih": yansima,  # sıralama / dönem: yansıma
        "vade_tarihi": s.get("taksit_vade_tarihi") or yansima,
        "belge": s.get("kaynak_evrak") or s.get("belge_no") or "",
        "aciklama": s.get("aciklama") or "",
        "taksit_no": s.get("tek_cekim_taksit") or (
            f"{s.get('taksit_no')}/{s.get('taksit_sayisi')}"
            if s.get("taksit_no")
            else ""
        ),
        "taksit_sira": s.get("taksit_no"),
        "taksit_sayisi": s.get("taksit_sayisi"),
        "ekstre_kesim_tarihi": s.get("ekstre_kesim_tarihi"),
        "son_odeme_tarihi": s.get("son_odeme_tarihi"),
        "plan_vadesi": s.get("taksit_vade_tarihi"),
        "banka_vadesi": s.get("son_odeme_tarihi"),
        "borc": _d(s.get("borc")),
        "odeme": _d(s.get("alacak")),
        "bakiye": SIFIR,  # sonra doldurulur
        "kalan": SIFIR,  # geriye uyum alias → bakiye
        "odeme_id": s.get("odeme_id"),
        "taksit_id": s.get("taksit_id"),
    }


def _yuruyen_bakiye(satirlar: list[dict], *, acilis: Decimal) -> list[dict]:
    """Kart ekranı işareti: borç eksi, ödeme/iade artı. Yeni = önceki − borç + ödeme."""
    bakiye = _d(acilis)
    out: list[dict] = []
    for s in satirlar:
        borc = _d(s.get("borc"))
        odeme = _d(s.get("odeme"))
        bakiye = _d(bakiye - borc + odeme)
        row = dict(s)
        row["bakiye"] = bakiye
        row["kalan"] = bakiye
        out.append(row)
    return out


def _onceki_devir(
    donemler: list[dict],
    *,
    kesim: date | None,
    as_of: date,
) -> tuple[Decimal, list[dict]]:
    """Önceki kesilmiş dönemlerin ``as_of`` itibarıyla kalan borcu (devir).

    Ödemeler son ödeme günü/sonrası dahil mahsup edilir; gelecek kesim taksitleri girmez.
    """
    if kesim is None:
        return SIFIR, []
    top = SIFIR
    detay: list[dict] = []
    for d in donemler:
        k = d.get("kesim_tarihi")
        if not isinstance(k, date) or k >= kesim:
            continue
        if k > as_of:
            continue
        # Dönem harcaması sabit; ödemeler as_of'a kadar
        harcama = _d(d.get("tl_tutar") or d.get("toplam_borc") or 0)
        odenen = SIFIR
        for o in d.get("odemeler") or []:
            if o.get("iptal"):
                continue
            ot = o.get("tarih")
            if isinstance(ot, date) and ot > as_of:
                continue
            odenen += _d(o.get("tutar"))
        kalan = max(SIFIR, _d(harcama - odenen))
        if kalan <= 0:
            continue
        top += kalan
        detay.append({
            "kesim_tarihi": k,
            "son_odeme_tarihi": d.get("son_odeme_tarihi"),
            "kesim_tutari": harcama,
            "odenen": odenen,
            "kalan": kalan,
        })
    return _d(top), detay


def _donem_dagilimi(kredi_karti_id: int, *, bugun: date) -> list[dict]:
    """Kesilmiş / açık / gelecek — kesim, ödenen, kalan ayrı."""
    satirlar: list[dict] = []
    for d in KrediKartiEkstreService.ekstreleri_hesapla(
        bugun=bugun, kredi_karti_id=int(kredi_karti_id), odenenleri_dahil=True
    ):
        kesim = d.get("kesim_tarihi")
        if not isinstance(kesim, date):
            continue
        kesin = bool(d.get("kesin"))
        kalan = _d(d.get("kalan"))
        if kesin and kalan <= 0 and kesim < bugun:
            durum = "Kapandı"
        elif kesin:
            durum = "Kesilmiş / açık"
        else:
            durum = "Gelecek"
        satirlar.append({
            "kesim_tarihi": kesim,
            "donem_baslangic": d.get("donem_baslangic"),
            "donem_bitis": d.get("donem_bitis") or kesim,
            "son_odeme_tarihi": d.get("son_odeme_tarihi"),
            "taksit_sayisi": len(d.get("detay_satirlari") or []),
            "kesim_tutari": _d(d.get("tl_tutar")),
            "odenen": _d(d.get("odenen")),
            "kalan": kalan,
            "planli_borc": kalan,  # geriye uyum
            "kesin": kesin,
            "durum": durum,
            "etiket": durum,
        })
    return satirlar


def rapor_verisi(
    kredi_karti_id: int,
    *,
    ekstre_id: int | None = None,
    kesim_tarihi: date | None = None,
    rapor_tarihi: date | None = None,
    mod: str = "ekstre",
    baslangic: date | None = None,
    bitis: date | None = None,
) -> dict[str, Any]:
    """Salt okunur ekstre / tarih aralığı raporu; faiz tahakkuku ve mali evrak üretmez.

    ``mod``: ``ekstre`` (varsayılan) | ``tarih_araligi``
    Dönüş yalnız düz Python değerleridir (lazy-load yok).
    """
    from sqlalchemy import select
    from sqlalchemy.orm import selectinload

    from database.database import get_session
    from database.models.finans import KrediKartiTanimi

    KrediKartiEkstreService.schema_hazirla()
    rapor_tarihi = rapor_tarihi or date.today()
    mod = (mod or "ekstre").strip().lower()
    if mod == "tarih_araligi":
        if baslangic is None or bitis is None:
            raise ValueError("İki tarih arası rapor için başlangıç ve bitiş zorunludur.")
        if baslangic > bitis:
            raise ValueError("Başlangıç tarihi bitişten sonra olamaz.")

    with get_session() as session:
        kart = session.scalar(
            select(KrediKartiTanimi)
            .where(KrediKartiTanimi.id == int(kredi_karti_id))
            .options(selectinload(KrediKartiTanimi.banka_karti))
        )
        if not kart:
            raise ValueError("Kredi kartı bulunamadı.")
        banka = kart.banka_karti
        banka_adi = (
            (getattr(banka, "banka_adi", None) if banka else None)
            or (kart.kart_bankasi or "").strip()
            or "—"
        )
        kart_adi = kart.kart_adi or ""
        banka_karti_id = int(kart.banka_karti_id) if kart.banka_karti_id else None
        para_birimi = (kart.para_birimi or "TRY").upper()
        son4 = (kart.son_dort_hane or "").strip()
        if not son4 and kart.kart_numarasi:
            no = "".join(ch for ch in str(kart.kart_numarasi) if ch.isdigit())
            son4 = no[-4:] if len(no) >= 4 else ""
        maskeli_no = f"****{son4}" if son4 else "****"
        # Güncel limit = ekran ile aynı kaynak (tarih=None → ledger + plan-only)
        ozet = KrediKartiEkstreService.kart_borc_ozeti(
            int(kredi_karti_id), session=session
        )

    tum_donemler = KrediKartiEkstreService.ekstreleri_hesapla(
        bugun=rapor_tarihi, kredi_karti_id=int(kredi_karti_id), odenenleri_dahil=True
    )

    if mod == "tarih_araligi":
        return _rapor_tarih_araligi(
            kredi_karti_id=int(kredi_karti_id),
            banka_adi=banka_adi,
            kart_adi=kart_adi,
            maskeli_no=maskeli_no,
            para_birimi=para_birimi,
            banka_karti_id=banka_karti_id,
            ozet=ozet,
            rapor_tarihi=rapor_tarihi,
            baslangic=baslangic,
            bitis=bitis,
            tum_donemler=tum_donemler,
        )

    detay = None
    if ekstre_id:
        detay = KrediKartiEkstreService.ekstre_detay(int(ekstre_id))
    elif kesim_tarihi is not None:
        for s in tum_donemler:
            if s.get("kesim_tarihi") == kesim_tarihi:
                detay = s
                break
    if detay is None:
        # En son kesilmiş dönem
        gecmis = [s for s in tum_donemler if s.get("kesim_tarihi") and s["kesim_tarihi"] <= rapor_tarihi]
        detay = gecmis[-1] if gecmis else {
            "ekstre_id": None,
            "kesim_tarihi": None,
            "donem_baslangic": None,
            "donem_bitis": None,
            "son_odeme_tarihi": None,
            "tl_tutar": SIFIR,
            "odenen": SIFIR,
            "kalan": SIFIR,
            "asgari_tutar": None,
            "asgari_odenen": SIFIR,
            "ekstre_durum": "GECICI",
            "kesin": False,
            "detay_satirlari": [],
            "odemeler": [],
        }

    kesim = detay.get("kesim_tarihi")
    kesim_tutari = _d(detay.get("tl_tutar"))
    # Devir: yeni kesime kadar gerçekleşmiş ödemeler sonrası önceki kalan
    devir_kesimde, onceki_detay = _onceki_devir(
        tum_donemler, kesim=kesim if isinstance(kesim, date) else None, as_of=kesim or rapor_tarihi
    )
    # Rapor tarihine kadar ek ödemeler (kesimden sonra) — geçmiş kesim tutarını değiştirmez
    if isinstance(kesim, date) and rapor_tarihi > kesim:
        devir_rapor, _ = _onceki_devir(tum_donemler, kesim=kesim, as_of=rapor_tarihi)
    else:
        devir_rapor = devir_kesimde

    # Bu dönem ödemeleri (çift mahsup yok — yalnız bu ekstreye bağlı)
    odeme_satirlari: list[dict] = []
    donem_odenen = SIFIR
    for o in detay.get("odemeler") or []:
        if o.get("iptal"):
            continue
        tut = _d(o.get("tutar"))
        donem_odenen += tut
        odeme_satirlari.append(
            _odeme_detay_satiri(o, ekstre_kesim=kesim if isinstance(kesim, date) else None, mahsup=tut)
        )
    # Önceki dönem mahsupları (devir hesabında kullanıldı — satırda ikinci kez borç düşülmez)
    onceki_odeme_mahsup: list[dict] = []
    if isinstance(kesim, date):
        for d in tum_donemler:
            k = d.get("kesim_tarihi")
            if not isinstance(k, date) or k >= kesim:
                continue
            for o in d.get("odemeler") or []:
                if o.get("iptal"):
                    continue
                ot = o.get("tarih")
                if not isinstance(ot, date):
                    continue
                # Devir kesiminde sayılan önceki ödemeler
                if ot <= (kesim if isinstance(kesim, date) else rapor_tarihi):
                    onceki_odeme_mahsup.append(
                        _odeme_detay_satiri(o, ekstre_kesim=k, mahsup=_d(o.get("tutar")))
                    )

    hareketler: list[dict] = []
    if devir_kesimde > 0:
        hareketler.append({
            "satir_turu": "DEVIR",
            "kaynak_tarihi": None,
            "yansima_tarihi": detay.get("donem_baslangic") or kesim,
            "tarih": detay.get("donem_baslangic") or kesim,
            "vade_tarihi": None,
            "belge": "",
            "aciklama": "Önceki dönemden devir",
            "taksit_no": "",
            "taksit_sira": None,
            "taksit_sayisi": None,
            "ekstre_kesim_tarihi": None,
            "son_odeme_tarihi": None,
            "plan_vadesi": None,
            "banka_vadesi": None,
            "borc": devir_kesimde,
            "odeme": SIFIR,
            "bakiye": SIFIR,
            "kalan": SIFIR,
            "odeme_id": None,
            "taksit_id": None,
        })
    for s in detay.get("detay_satirlari") or []:
        hareketler.append(_satirdan_hareket(s))

    # Ödemeler hareket listesinde alacak olarak (dönem ödemeleri); önceki mahsup ayrı tabloda
    for o in odeme_satirlari:
        hareketler.append({
            "satir_turu": "ODEME",
            "kaynak_tarihi": o.get("tarih"),
            "yansima_tarihi": o.get("tarih"),
            "tarih": o.get("tarih"),
            "vade_tarihi": None,
            "belge": o.get("belge_no") or "",
            "aciklama": (o.get("aciklama") or "Ekstre ödemesi")[:200],
            "taksit_no": "",
            "taksit_sira": None,
            "taksit_sayisi": None,
            "ekstre_kesim_tarihi": o.get("ekstre_kesim_tarihi"),
            "son_odeme_tarihi": detay.get("son_odeme_tarihi"),
            "plan_vadesi": None,
            "banka_vadesi": detay.get("son_odeme_tarihi"),
            "borc": SIFIR,
            "odeme": _d(o.get("mahsup")),
            "bakiye": SIFIR,
            "kalan": SIFIR,
            "odeme_id": o.get("id"),
            "taksit_id": None,
        })

    # Kesimden sonra / rapor tarihine kadar önceki borç ödemeleri → yürüyen bakiyede
    # (geçmiş kesim tutarını değiştirmez; devir satırı kesim anındaki tutarı korur)
    ekstra_odeme = max(SIFIR, _d(devir_kesimde - devir_rapor))
    if ekstra_odeme > 0:
        # Net düşüşü tek satırda gösterme; mahsup detayından kesim sonrası olanları ekle
        for o in onceki_odeme_mahsup:
            ot = o.get("tarih")
            if isinstance(kesim, date) and isinstance(ot, date) and ot > kesim and ot <= rapor_tarihi:
                hareketler.append({
                    "satir_turu": "ODEME_ONCEKI",
                    "kaynak_tarihi": ot,
                    "yansima_tarihi": ot,
                    "tarih": ot,
                    "vade_tarihi": None,
                    "belge": o.get("belge_no") or "",
                    "aciklama": f"Önceki dönem mahsubu ({_d(o.get('mahsup'))})",
                    "taksit_no": "",
                    "taksit_sira": None,
                    "taksit_sayisi": None,
                    "ekstre_kesim_tarihi": o.get("ekstre_kesim_tarihi"),
                    "son_odeme_tarihi": None,
                    "plan_vadesi": None,
                    "banka_vadesi": None,
                    "borc": SIFIR,
                    "odeme": _d(o.get("mahsup")),
                    "bakiye": SIFIR,
                    "kalan": SIFIR,
                    "odeme_id": o.get("id"),
                    "taksit_id": None,
                })

    hareketler.sort(
        key=lambda r: (
            r.get("tarih") or date.min,
            0 if r.get("satir_turu") == "DEVIR" else 1,
            str(r.get("belge") or ""),
            int(r.get("taksit_sira") or 0),
        )
    )
    # Açılış 0; devir satırı borç olarak girer (çift sayılmaz)
    hareketler = _yuruyen_bakiye(hareketler, acilis=SIFIR)
    kapanis = hareketler[-1]["bakiye"] if hareketler else SIFIR

    # Kalan ödenecek = yürüyen kapanışın borç mutlağı (eksi bakiye → pozitif kalan)
    donem_kalan = max(SIFIR, _d(-kapanis)) if kapanis < 0 else SIFIR
    _ = ekstra_odeme  # kesim sonrası önceki mahsup yürüyen bakiyede ODEME_ONCEKI satırlarıyla yansır

    asgari = detay.get("asgari_tutar")
    asgari_odenen = _d(detay.get("asgari_odenen") or 0)
    kalan_asgari = None
    if asgari is None:
        asgari_metin = "Tanımlanmadı"
    else:
        asgari_d = _d(asgari)
        kalan_asgari = max(SIFIR, asgari_d - asgari_odenen)
        asgari_metin = str(asgari_d)

    donem_etiket = (
        kesim.strftime("%Y%m%d")
        if isinstance(kesim, date)
        else "gecici"
    )
    pb = (ozet.get("para_birimi") or para_birimi or "TRY").upper()
    hesap_borc = ozet.get("hesap_borc")
    hesap_bakiyesi = None if hesap_borc is None else _d(-_d(hesap_borc))  # eksi borç

    return {
        "mod": "ekstre",
        "kapsam": (
            "Kesilmiş ekstre: dönem harcamaları + önceki dönemden devir; "
            "ödemeler ilgili ekstre mahsubunda bir kez sayılır. "
            "Kullanılan limit = kart ekranı ile aynı (ledger + plan-only)."
        ),
        "rapor_tarihi": rapor_tarihi,
        "banka_adi": banka_adi,
        "kart_adi": kart_adi,
        "maskeli_no": maskeli_no,
        "para_birimi": pb,
        "kesin": bool(detay.get("kesin")),
        "gecici": not bool(detay.get("kesin")),
        "kesim_tarihi": kesim,
        "donem_baslangic": detay.get("donem_baslangic"),
        "donem_bitis": detay.get("donem_bitis"),
        "son_odeme_tarihi": detay.get("son_odeme_tarihi"),
        "donem_borc": kesim_tutari,
        "kesim_tutari": kesim_tutari,
        "onceki_devir": devir_kesimde,
        "onceki_devir_rapor": devir_rapor,
        "onceki_devir_detay": onceki_detay,
        "donem_odenen": donem_odenen,
        "donem_kalan": donem_kalan,
        "kalan_odenecek": donem_kalan,
        "kapanis_bakiye": kapanis,
        "toplam_kart_borcu": _d(ozet.get("toplam_borc")),
        "hesap_bakiyesi": hesap_bakiyesi,
        "hesap_borc": _d(hesap_borc) if hesap_borc is not None else None,
        "kullanilan_limit": _d(ozet.get("kullanilan")),
        "gelecek_taksit_toplami": _d(ozet.get("kesilmemis")),
        "kesilmis_kalan": _d(ozet.get("kesilmis_kalan")),
        "asgari_tutar": _d(asgari) if asgari is not None else None,
        "asgari_metin": asgari_metin,
        "asgari_odenen": asgari_odenen,
        "kalan_asgari": kalan_asgari,
        "limit": ozet.get("limit"),
        "limit_tanimli": bool(ozet.get("limit_tanimli")),
        "kullanilabilir": ozet.get("kullanilabilir"),
        "hareketler": hareketler,
        "odemeler": odeme_satirlari,
        "onceki_odeme_mahsuplari": onceki_odeme_mahsup,
        "gelecek_taksitler": [],
        "gelecek_donemler": _donem_dagilimi(int(kredi_karti_id), bugun=rapor_tarihi),
        "donem_dagilimi": _donem_dagilimi(int(kredi_karti_id), bugun=rapor_tarihi),
        "dosya_kok": (
            f"KK_Ekstre_{maskeli_no.replace('*', '')}_{donem_etiket}_"
            f"{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        ),
        "cvv": None,
        "kart_numarasi": None,
    }


def _rapor_tarih_araligi(
    *,
    kredi_karti_id: int,
    banka_adi: str,
    kart_adi: str,
    maskeli_no: str,
    para_birimi: str,
    banka_karti_id: int | None,
    ozet: dict,
    rapor_tarihi: date,
    baslangic: date,
    bitis: date,
    tum_donemler: list[dict],
) -> dict[str, Any]:
    """Yansıma tarihine göre iki tarih arası hareket; açılış bakiyesi + yürüyen bakiye."""
    # Açılış: başlangıçtan önce yansıyan borç − ödemeler (kart işareti eksi borç)
    acilis_borc = SIFIR
    acilis_odeme = SIFIR
    hareketler: list[dict] = []
    for d in tum_donemler:
        for s in d.get("detay_satirlari") or []:
            y = s.get("taksit_vade_tarihi") or s.get("islem_tarihi")
            if not isinstance(y, date):
                continue
            row = _satirdan_hareket(s)
            if y < baslangic:
                acilis_borc += _d(row["borc"])
                acilis_odeme += _d(row["odeme"])
            elif baslangic <= y <= bitis:
                hareketler.append(row)
        for o in d.get("odemeler") or []:
            if o.get("iptal"):
                continue
            ot = o.get("tarih")
            if not isinstance(ot, date):
                continue
            tut = _d(o.get("tutar"))
            if ot < baslangic:
                acilis_odeme += tut
            elif baslangic <= ot <= bitis:
                hareketler.append({
                    "satir_turu": "ODEME",
                    "kaynak_tarihi": ot,
                    "yansima_tarihi": ot,
                    "tarih": ot,
                    "vade_tarihi": None,
                    "belge": o.get("belge_no") or "",
                    "aciklama": o.get("aciklama") or "Ödeme",
                    "taksit_no": "",
                    "taksit_sira": None,
                    "taksit_sayisi": None,
                    "ekstre_kesim_tarihi": d.get("kesim_tarihi"),
                    "son_odeme_tarihi": d.get("son_odeme_tarihi"),
                    "plan_vadesi": None,
                    "banka_vadesi": d.get("son_odeme_tarihi"),
                    "borc": SIFIR,
                    "odeme": tut,
                    "bakiye": SIFIR,
                    "kalan": SIFIR,
                    "odeme_id": o.get("id"),
                    "taksit_id": None,
                })

    acilis_net = _d(-(acilis_borc - acilis_odeme))  # eksi = borç
    hareketler.sort(
        key=lambda r: (
            r.get("tarih") or date.min,
            0 if r.get("satir_turu") == "ODEME" else 1,
            str(r.get("belge") or ""),
        )
    )
    baslangic_satir = [{
        "satir_turu": "ACILIS",
        "kaynak_tarihi": None,
        "yansima_tarihi": baslangic,
        "tarih": baslangic,
        "vade_tarihi": None,
        "belge": "",
        "aciklama": f"Açılış / devir ({baslangic.strftime('%d.%m.%Y')} öncesi)",
        "taksit_no": "",
        "taksit_sira": None,
        "taksit_sayisi": None,
        "ekstre_kesim_tarihi": None,
        "son_odeme_tarihi": None,
        "plan_vadesi": None,
        "banka_vadesi": None,
        "borc": max(SIFIR, -acilis_net) if acilis_net < 0 else SIFIR,
        "odeme": max(SIFIR, acilis_net) if acilis_net > 0 else SIFIR,
        "bakiye": SIFIR,
        "kalan": SIFIR,
        "odeme_id": None,
        "taksit_id": None,
    }]
    # Açılış satırı bakiyeyi kursun: acilis 0'dan başla, açılış satırı borç/ödeme taşır
    tum = _yuruyen_bakiye(baslangic_satir + hareketler, acilis=SIFIR)
    kapanis = tum[-1]["bakiye"] if tum else SIFIR
    pb = (ozet.get("para_birimi") or para_birimi or "TRY").upper()
    hesap_borc = ozet.get("hesap_borc")
    return {
        "mod": "tarih_araligi",
        "kapsam": (
            f"İki tarih arası hareket raporu: yansıma tarihi "
            f"{baslangic.strftime('%d.%m.%Y')}–{bitis.strftime('%d.%m.%Y')} (uçlar dahil). "
            "Kesilmiş ekstre raporu değildir; açılış bakiyesi aralık öncesi neti gösterir."
        ),
        "rapor_tarihi": rapor_tarihi,
        "banka_adi": banka_adi,
        "kart_adi": kart_adi,
        "maskeli_no": maskeli_no,
        "para_birimi": pb,
        "kesin": False,
        "gecici": True,
        "kesim_tarihi": None,
        "donem_baslangic": baslangic,
        "donem_bitis": bitis,
        "son_odeme_tarihi": None,
        "baslangic": baslangic,
        "bitis": bitis,
        "donem_borc": SIFIR,
        "kesim_tutari": SIFIR,
        "onceki_devir": max(SIFIR, -acilis_net),
        "onceki_devir_rapor": max(SIFIR, -acilis_net),
        "onceki_devir_detay": [],
        "donem_odenen": sum((_d(h["odeme"]) for h in hareketler), SIFIR),
        "donem_kalan": max(SIFIR, -kapanis) if kapanis < 0 else SIFIR,
        "kalan_odenecek": max(SIFIR, -kapanis) if kapanis < 0 else SIFIR,
        "kapanis_bakiye": kapanis,
        "toplam_kart_borcu": _d(ozet.get("toplam_borc")),
        "hesap_bakiyesi": None if hesap_borc is None else _d(-_d(hesap_borc)),
        "hesap_borc": _d(hesap_borc) if hesap_borc is not None else None,
        "kullanilan_limit": _d(ozet.get("kullanilan")),
        "gelecek_taksit_toplami": _d(ozet.get("kesilmemis")),
        "kesilmis_kalan": _d(ozet.get("kesilmis_kalan")),
        "asgari_tutar": None,
        "asgari_metin": "—",
        "asgari_odenen": SIFIR,
        "kalan_asgari": None,
        "limit": ozet.get("limit"),
        "limit_tanimli": bool(ozet.get("limit_tanimli")),
        "kullanilabilir": ozet.get("kullanilabilir"),
        "hareketler": tum,
        "odemeler": [],
        "onceki_odeme_mahsuplari": [],
        "gelecek_taksitler": [],
        "gelecek_donemler": _donem_dagilimi(int(kredi_karti_id), bugun=rapor_tarihi),
        "donem_dagilimi": _donem_dagilimi(int(kredi_karti_id), bugun=rapor_tarihi),
        "dosya_kok": (
            f"KK_Hareket_{maskeli_no.replace('*', '')}_"
            f"{baslangic.strftime('%Y%m%d')}_{bitis.strftime('%Y%m%d')}_"
            f"{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        ),
        "cvv": None,
        "kart_numarasi": None,
    }


def excel_kaydet(rapor: dict, yol: str | Path) -> Path:
    from openpyxl import Workbook
    from openpyxl.styles import Font
    from openpyxl.utils import get_column_letter

    yol = Path(yol)
    wb = Workbook()
    ws = wb.active
    ws.title = "Özet"
    ws.append(["Firma Kredi Kartı Hesap Ekstresi"])
    ws["A1"].font = Font(bold=True, size=14)
    satirlar = [
        ("Mod", rapor.get("mod")),
        ("Kapsam", rapor.get("kapsam")),
        ("Rapor tarihi", rapor["rapor_tarihi"]),
        ("Banka", rapor["banka_adi"]),
        ("Kart", rapor["kart_adi"]),
        ("Kart no", rapor["maskeli_no"]),
        ("Para birimi", rapor["para_birimi"]),
        ("Kesim", rapor.get("kesim_tarihi")),
        ("Dönem", f"{rapor.get('donem_baslangic') or '—'} – {rapor.get('donem_bitis') or '—'}"),
        ("Banka son ödeme", rapor.get("son_odeme_tarihi") or "Tanımlanmadı"),
        ("Kesim tutarı", float(rapor["kesim_tutari"])),
        ("Önceki dönemden devir", float(rapor.get("onceki_devir") or 0)),
        ("Dönem ödenen", float(rapor["donem_odenen"])),
        ("Kalan ödenecek", float(rapor["donem_kalan"])),
        ("Kapanış bakiyesi", float(rapor.get("kapanis_bakiye") or 0)),
        ("Hesap bakiyesi (eksi=borç)", float(rapor["hesap_bakiyesi"]) if rapor.get("hesap_bakiyesi") is not None else "—"),
        ("Kullanılan limit (ekran ile aynı)", float(rapor["kullanilan_limit"])),
        ("Kesilmiş ekstre kalan", float(rapor.get("kesilmis_kalan") or 0)),
        ("Gelecek dönem kalan (bilgi)", float(rapor["gelecek_taksit_toplami"])),
        ("Ekstre asgari", rapor["asgari_metin"]),
        (
            "Hesaplanan kullanılabilir limit",
            float(rapor["kullanilabilir"])
            if rapor.get("limit_tanimli") and rapor.get("kullanilabilir") is not None
            else "Tanımlanmadı",
        ),
    ]
    for etiket, deger in satirlar:
        ws.append([etiket, deger])

    wh = wb.create_sheet("Hareketler")
    wh.append([
        "Kaynak tarihi", "Yansıma", "Vade", "Belge", "Açıklama", "Taksit",
        "Ekstre kesim", "Son ödeme", "Borç", "Ödeme/İade", "Bakiye",
    ])
    for h in rapor["hareketler"]:
        wh.append([
            h.get("kaynak_tarihi"), h.get("yansima_tarihi") or h.get("tarih"),
            h.get("vade_tarihi"), h.get("belge"), h.get("aciklama"), h.get("taksit_no"),
            h.get("ekstre_kesim_tarihi"), h.get("son_odeme_tarihi"),
            float(h["borc"]), float(h["odeme"]), float(h.get("bakiye") if h.get("bakiye") is not None else h.get("kalan") or 0),
        ])
    wh.auto_filter.ref = wh.dimensions
    wh.freeze_panes = "A2"

    wo = wb.create_sheet("Ödemeler")
    wo.append(["Tarih", "Belge", "Tutar", "Mahsup", "Ekstre kesim", "Kaynak", "Açıklama", "İptal"])
    for o in list(rapor.get("odemeler") or []) + list(rapor.get("onceki_odeme_mahsuplari") or []):
        wo.append([
            o.get("tarih"), o.get("belge_no"), float(o.get("tutar") or 0),
            float(o.get("mahsup") or 0), o.get("ekstre_kesim_tarihi"),
            o.get("kaynak"), o.get("aciklama"), bool(o.get("iptal")),
        ])
    wo.freeze_panes = "A2"

    wd = wb.create_sheet("Dönem Dağılımı")
    wd.append([
        "Kesim", "Başlangıç", "Bitiş", "Son ödeme", "Taksit",
        "Kesim tutarı", "Ödenen", "Kalan", "Durum",
    ])
    for g in rapor.get("donem_dagilimi") or rapor.get("gelecek_donemler") or []:
        wd.append([
            g.get("kesim_tarihi"), g.get("donem_baslangic"), g.get("donem_bitis"),
            g.get("son_odeme_tarihi"), g.get("taksit_sayisi"),
            float(g.get("kesim_tutari") or g.get("planli_borc") or 0),
            float(g.get("odenen") or 0),
            float(g.get("kalan") or g.get("planli_borc") or 0),
            g.get("durum") or g.get("etiket"),
        ])
    wd.freeze_panes = "A2"

    wf = wb.create_sheet("Faiz Detayı")
    wf.append(["Bilgi", "Değer"])
    wf.append([
        "Not",
        "Faiz tahakkuku bu raporda yapılmaz. Doğrulanmış profil yoksa tutar uydurulmaz.",
    ])

    for sheet in wb.worksheets:
        for col in range(1, sheet.max_column + 1):
            sheet.column_dimensions[get_column_letter(col)].width = 18

    yol.parent.mkdir(parents=True, exist_ok=True)
    wb.save(yol)
    return yol


def pdf_kaydet(rapor: dict, yol: str | Path) -> Path:
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4, landscape
    from reportlab.lib.units import mm
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont
    from reportlab.pdfgen import canvas as pdf_canvas

    yol = Path(yol)
    yol.parent.mkdir(parents=True, exist_ok=True)
    font = "Helvetica"
    try:
        pdfmetrics.registerFont(TTFont("ArialTR", "C:/Windows/Fonts/arial.ttf"))
        font = "ArialTR"
    except Exception:
        pass

    c = pdf_canvas.Canvas(str(yol), pagesize=landscape(A4))
    genislik, yukseklik = landscape(A4)
    y = yukseklik - 15 * mm

    def satir(metin, *, boyut=10, dx=15 * mm):
        nonlocal y
        c.setFont(font, boyut)
        c.drawString(dx, y, str(metin)[:150])
        y -= (boyut + 4)

    c.setFont(font, 14)
    c.drawString(15 * mm, y, "FİRMA KREDİ KARTI HESAP EKSTRESİ")
    y -= 8 * mm
    satir(f"{rapor['banka_adi']} / {rapor['kart_adi']} / {rapor['maskeli_no']}", boyut=11)
    satir(
        f"Rapor: {rapor['rapor_tarihi'].strftime('%d.%m.%Y')}  ·  PB: {rapor['para_birimi']}  ·  "
        f"{'Kesinleşmiş' if rapor['kesin'] else 'Geçici / güncel'}  ·  Mod: {rapor.get('mod')}"
    )
    satir(
        f"Kesim: {rapor.get('kesim_tarihi') or '—'}  ·  "
        f"Dönem: {rapor.get('donem_baslangic') or '—'} – {rapor.get('donem_bitis') or '—'}  ·  "
        f"Banka son ödeme: {rapor.get('son_odeme_tarihi') or 'Tanımlanmadı'}"
    )
    satir(
        f"Kesim tutarı: {rapor['kesim_tutari']}  ·  Devir: {rapor.get('onceki_devir') or 0}  ·  "
        f"Ödenen: {rapor['donem_odenen']}  ·  Kalan: {rapor['donem_kalan']}"
    )
    satir(
        f"Kullanılan limit: {rapor['kullanilan_limit']}  ·  "
        f"Hesap bakiyesi: {rapor.get('hesap_bakiyesi') if rapor.get('hesap_bakiyesi') is not None else '—'}  ·  "
        f"Gelecek dönem kalan: {rapor['gelecek_taksit_toplami']}"
    )
    y -= 2 * mm
    satir("Hareketler", boyut=11)
    headers = ("Yansıma", "Kaynak", "Belge", "Tk", "Borç", "Ödeme", "Bakiye")
    x0 = 12 * mm
    col_w = [24 * mm, 24 * mm, 40 * mm, 28 * mm, 28 * mm, 28 * mm, 28 * mm]
    c.setFillColor(colors.Color(0.05, 0.15, 0.35))
    c.rect(x0, y - 2 * mm, sum(col_w), 7 * mm, fill=1, stroke=0)
    c.setFillColor(colors.white)
    c.setFont(font, 8)
    x = x0
    for h, w in zip(headers, col_w):
        c.drawString(x + 1 * mm, y, h)
        x += w
    y -= 8 * mm
    c.setFillColor(colors.black)
    sayfa = 1

    def _fmt_t(d):
        return d.strftime("%d.%m.%Y") if hasattr(d, "strftime") else str(d or "")

    def yeni_sayfa():
        nonlocal y, sayfa
        c.setFont(font, 8)
        c.drawRightString(genislik - 12 * mm, 8 * mm, f"Sayfa {sayfa}")
        c.showPage()
        sayfa += 1
        y = yukseklik - 15 * mm
        c.setFont(font, 9)
        c.drawString(15 * mm, y, f"{rapor['kart_adi']} / {rapor['maskeli_no']} — devam")
        y -= 10 * mm

    for h in rapor["hareketler"]:
        if y < 20 * mm:
            yeni_sayfa()
        bak = h.get("bakiye") if h.get("bakiye") is not None else h.get("kalan")
        degerler = [
            _fmt_t(h.get("yansima_tarihi") or h.get("tarih")),
            _fmt_t(h.get("kaynak_tarihi")),
            str(h.get("belge") or "")[:22],
            str(h.get("taksit_no") or "")[:16],
            f"{h['borc']:,.2f}",
            f"{h['odeme']:,.2f}",
            f"{_d(bak):,.2f}",
        ]
        c.setFont(font, 7)
        x = x0
        for deger, w in zip(degerler, col_w):
            c.drawString(x + 1 * mm, y, deger)
            x += w
        y -= 5 * mm

    c.setFont(font, 8)
    c.drawRightString(genislik - 12 * mm, 8 * mm, f"Sayfa {sayfa}")
    c.save()
    return yol


def email_icin_hazirla(rapor: dict, klasor: str | Path) -> dict[str, Path]:
    """PDF (+ Excel) üretir; otomatik gönderim yapmaz."""
    klasor = Path(klasor)
    klasor.mkdir(parents=True, exist_ok=True)
    pdf_yol = pdf_kaydet(rapor, klasor / f"{rapor['dosya_kok']}.pdf")
    xlsx_yol = excel_kaydet(rapor, klasor / f"{rapor['dosya_kok']}.xlsx")
    return {"pdf": pdf_yol, "excel": xlsx_yol}
