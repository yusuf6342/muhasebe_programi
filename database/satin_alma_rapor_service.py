"""Satın Alma → Raporlar hesapları (salt okunur).

Tüm raporlar gerçekleşmiş belgelerden okunur; cari, stok veya muhasebe kaydı yazmaz.
Tek yazma yolu yeniden sipariş önerisinden taslak alış siparişi oluşturmaktır ve
bu iş mevcut ``StokUyariService.siparis_hazirla`` üzerinden (yetki ve mükerrer
kontrolüyle) yapılır.
"""
from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime
from decimal import ROUND_CEILING, ROUND_HALF_UP, Decimal
from typing import Any

from sqlalchemy import or_, select

from database.database import get_session
from database.fiyat_kaynagi_service import _d, _pb, _satir_kaydi, net_iskontolu

SIFIR = Decimal("0")
KURUS = Decimal("0.01")
DORT = Decimal("0.0001")
YUZ = Decimal("100")

SIPARIS_HARIC = ("TASLAK", "İPTAL")
IADE_HARIC = ("TASLAK", "İPTAL")
TEKLIF_HARIC = ("İPTAL",)

KDV_MALIYET_NOTU = (
    "Programda 'KDV maliyete dahil' ayarı bulunmuyor; alış KDV'si indirilecek KDV olarak "
    "izlendiğinden maliyete eklenmedi."
)
REZERVASYON_NOTU = (
    "Programda stok rezervasyonu tutulmuyor (rezerve = 0). 'Müşteri siparişlerini düş' "
    "seçiliyse bekleyen müşteri siparişleri rezervasyon gibi kullanılabilir stoktan düşülür."
)


def _kurus(x) -> Decimal:
    return _d(x).quantize(KURUS, rounding=ROUND_HALF_UP)


def _bugun(bugun: date | None) -> date:
    return bugun or date.today()


def _ara_uygun(arama: str | None, *metinler) -> bool:
    if not arama:
        return True
    from database.turkce_normalize import turkce_normalize

    hedef = turkce_normalize(" ".join(str(m or "") for m in metinler))
    return all(p in hedef for p in turkce_normalize(arama).split())


def _yuzde(onceki: Decimal | None, son: Decimal | None) -> Decimal | None:
    if onceki is None or son is None or onceki <= 0:
        return None
    return ((son - onceki) / onceki * YUZ).quantize(KURUS, rounding=ROUND_HALF_UP)


def _kart_haritasi(session, kodlar) -> dict[str, Any]:
    from sqlalchemy.orm import selectinload

    from database.models.stok import StokKarti

    kodlar = [k for k in {str(k or "") for k in kodlar} if k]
    harita: dict[str, Any] = {}
    for i in range(0, len(kodlar), 500):
        parca = kodlar[i:i + 500]
        sorgu = select(StokKarti).where(StokKarti.stok_kodu.in_(parca))
        if hasattr(StokKarti, "birimler"):
            sorgu = sorgu.options(selectinload(StokKarti.birimler))
        for k in session.scalars(sorgu):
            harita[k.stok_kodu] = k
    return harita


def _carpan(kart, birim: str | None, kayitli=None) -> Decimal | None:
    """Belge birimi → temel birim çarpanı; satırda saklıysa o kullanılır."""
    if kayitli:
        c = _d(kayitli)
        if c > 0:
            return c
    if kart is None:
        return Decimal("1") if not birim else None
    from database.stok_service import BirimDonusumHatasi, StokService

    try:
        return StokService.birim_carpani_kesin(kart, birim or kart.birim)
    except (BirimDonusumHatasi, Exception):  # noqa: BLE001
        return None


def _grup_adi(kart) -> str:
    if kart is None:
        return "(Kart yok)"
    return (getattr(kart, "rapor_grubu", None) or "").strip() or "(Grupsuz)"


# ---------------------------------------------------------------------------
# Gerçekleşmiş alış satırları
# ---------------------------------------------------------------------------

def _alis_kayitlari(session, *, urun_kodu=None, cari_id=None, bas=None, bit=None) -> list[dict]:
    """İptal edilmemiş alış faturası satırları (gerçekleşmiş alış)."""
    from database.models.alis_faturasi import AlisFaturasi, AlisFaturasiSatiri
    from database.models.cari import Cari

    q = (
        select(AlisFaturasiSatiri, AlisFaturasi, Cari.unvan)
        .join(AlisFaturasi, AlisFaturasi.id == AlisFaturasiSatiri.fatura_id)
        .join(Cari, Cari.id == AlisFaturasi.cari_id)
        .where(AlisFaturasi.durum != "İPTAL")
    )
    if urun_kodu:
        q = q.where(AlisFaturasiSatiri.urun_kodu == urun_kodu)
    if cari_id:
        q = q.where(AlisFaturasi.cari_id == int(cari_id))
    if bas:
        q = q.where(AlisFaturasi.fatura_tarihi >= bas)
    if bit:
        q = q.where(AlisFaturasi.fatura_tarihi <= bit)
    sonuc = []
    for satir, fatura, unvan in session.execute(q):
        k = _satir_kaydi(satir, fatura, unvan, tur="ALIŞ")
        k["urun_kodu"] = satir.urun_kodu
        k["urun_adi"] = satir.urun_adi
        k["kur_tarihi"] = fatura.kur_tarihi
        sonuc.append(k)
    sonuc.sort(key=lambda r: (r["tarih"], r["saat"] or "", r["belge_id"], r["satir_id"]))
    return sonuc


def _birim_cevrilmis(onceki: dict, son: dict, kart) -> tuple[Decimal | None, str | None]:
    """Önceki net fiyatı son alışın birimine çevirir; yapılamıyorsa (None, neden)."""
    from database.stok_service import birim_anahtari

    if birim_anahtari(onceki["birim"]) == birim_anahtari(son["birim"]):
        return onceki["net_fiyat"], None
    c_on = _carpan(kart, onceki["birim"], onceki.get("birim_carpani"))
    c_son = _carpan(kart, son["birim"], son.get("birim_carpani"))
    if not c_on or not c_son:
        return None, f"Birim farklı ({onceki['birim']} → {son['birim']}), çevrim yapılamadı"
    fiyat = (onceki["net_fiyat"] / c_on * c_son).quantize(DORT, rounding=ROUND_HALF_UP)
    return fiyat, f"Önceki fiyat {onceki['birim']} → {son['birim']} çevrildi (oran {c_son / c_on:.4f})"


# ---------------------------------------------------------------------------
# 1) Alış fiyatı değişim raporu
# ---------------------------------------------------------------------------

def fiyat_degisim(
    *, bas: date | None = None, bit: date | None = None, kapsam: str = "tedarikci",
    cari_id: int | None = None, arama: str = "", sadece_degisen: bool = False,
) -> dict[str, Any]:
    """Son gerçekleşmiş alışı bir önceki gerçekleşmiş alışla karşılaştırır.

    ``kapsam``: "tedarikci" → aynı tedarikçideki önceki alış; "tumu" → tüm tedarikçilerde
    önceki alış. Son alış [bas, bit] aralığında olmalı; önceki alış daha eski olabilir.
    Yalnız iptal edilmemiş alış faturaları kullanılır (taslak/sipariş/teklif fiyatı yok).
    """
    with get_session() as session:
        kayitlar = _alis_kayitlari(session, cari_id=cari_id if kapsam == "tedarikci" else None, bit=bit)
        kartlar = _kart_haritasi(session, {k["urun_kodu"] for k in kayitlar})
    gruplar: dict[tuple, list[dict]] = defaultdict(list)
    for k in kayitlar:
        anahtar = (k["urun_kodu"], k["cari_id"]) if kapsam == "tedarikci" else (k["urun_kodu"],)
        gruplar[anahtar].append(k)
    satirlar = []
    for anahtar, liste in gruplar.items():
        son = liste[-1]
        if bas and son["tarih"] < bas:
            continue
        if kapsam != "tedarikci" and cari_id and son["cari_id"] != int(cari_id):
            continue
        if not _ara_uygun(arama, son["urun_kodu"], son["urun_adi"], son["tedarikci"]):
            continue
        onceki = liste[-2] if len(liste) > 1 else None
        kart = kartlar.get(son["urun_kodu"])
        aciklama = []
        onceki_fiyat = fark = yuzde = None
        if onceki is None:
            aciklama.append("Önceki alış yok")
        elif onceki["para_birimi"] != son["para_birimi"]:
            aciklama.append(f"Para birimi farklı ({onceki['para_birimi']} → {son['para_birimi']}); karşılaştırılmadı")
        else:
            onceki_fiyat, not_ = _birim_cevrilmis(onceki, son, kart)
            if not_:
                aciklama.append(not_)
            if onceki_fiyat is not None:
                fark = son["net_fiyat"] - onceki_fiyat
                yuzde = _yuzde(onceki_fiyat, son["net_fiyat"])
                if yuzde is None:
                    aciklama.append("Önceki fiyat 0; yüzde hesaplanmadı")
        if sadece_degisen and not fark:
            continue
        satirlar.append({
            "urun_kodu": son["urun_kodu"], "urun_adi": son["urun_adi"],
            "tedarikci": son["tedarikci"],
            "onceki_tedarikci": onceki["tedarikci"] if onceki else "",
            "onceki_tarih": onceki["tarih"] if onceki else None,
            "onceki_belge": onceki["belge_no"] if onceki else "",
            "son_tarih": son["tarih"], "son_belge": son["belge_no"],
            "birim": son["birim"], "para_birimi": son["para_birimi"],
            "onceki_fiyat": onceki_fiyat if onceki_fiyat is not None else (onceki["net_fiyat"] if onceki else None),
            "son_fiyat": son["net_fiyat"],
            "fark": fark, "yuzde": yuzde,
            "aciklama": "; ".join(aciklama),
        })
    satirlar.sort(key=lambda r: (r["urun_kodu"], r["tedarikci"]))
    return {"satirlar": satirlar, "notlar": [
        "Fiyatlar iskontolar düşülmüş, KDV hariç net birim fiyattır (belge para biriminde).",
        "Taslak, iptal, sipariş ve teklif fiyatları kullanılmaz.",
    ]}


# ---------------------------------------------------------------------------
# 2) Tedarikçi fiyat karşılaştırması
# ---------------------------------------------------------------------------

def tedarikci_karsilastirma(
    urun_kodu: str, *, bas: date | None = None, bit: date | None = None,
    teklif_dahil: bool = False, cevir: bool = False, hedef_birim: str | None = None,
    bugun: date | None = None,
) -> dict[str, Any]:
    """Ürün için tedarikçi bazında son gerçekleşmiş alış ve geçmiş.

    Sıralama yalnız tüm fiyatlar aynı birim ve para birimindeyse veya ``cevir`` ile
    TL / hedef birime çevrildiğinde yapılır; çevrimde oran, kur ve kur tarihi gösterilir.
    """
    from database.models.cari import Cari
    from database.models.tedarikci_teklif import TedarikciTeklif, TedarikciTeklifSatiri

    gun0 = _bugun(bugun)
    urun_kodu = (urun_kodu or "").strip()
    with get_session() as session:
        kayitlar = _alis_kayitlari(session, urun_kodu=urun_kodu, bas=bas, bit=bit)
        kart = _kart_haritasi(session, [urun_kodu]).get(urun_kodu)
        teklifler = []
        if teklif_dahil:
            for ts, t, unvan in session.execute(
                select(TedarikciTeklifSatiri, TedarikciTeklif, Cari.unvan)
                .join(TedarikciTeklif, TedarikciTeklif.id == TedarikciTeklifSatiri.teklif_id)
                .join(Cari, Cari.id == TedarikciTeklifSatiri.cari_id)
                .where(TedarikciTeklifSatiri.urun_kodu == urun_kodu,
                       TedarikciTeklif.durum.notin_(TEKLIF_HARIC))
                .order_by(TedarikciTeklif.teklif_tarihi.desc(), TedarikciTeklif.id.desc())
            ):
                teklifler.append({
                    "kaynak": "TEKLİF", "tedarikci": unvan or "", "tarih": t.teklif_tarihi,
                    "belge_no": t.teklif_no, "durum": t.durum, "miktar": _d(ts.miktar),
                    "birim": ts.birim, "para_birimi": _pb(ts.para_birimi),
                    "net_fiyat": net_iskontolu(ts.birim_fiyat, ts.iskonto_orani),
                    "vade_gun": ts.vade_gun, "termin_gun": ts.termin_gun,
                    "nakliye": _d(ts.nakliye_tutari),
                    "gun": (gun0 - t.teklif_tarihi).days if t.teklif_tarihi else None,
                })
    hedef = hedef_birim or (kart.birim if kart else None)

    def _cevrim(k: dict) -> dict:
        c = _carpan(kart, k["birim"], k.get("birim_carpani"))
        c_hedef = _carpan(kart, hedef) if hedef else None
        kur = _d(k.get("kur"), "1") if k["para_birimi"] != "TRY" else Decimal("1")
        if not c or not c_hedef or kur <= 0:
            return {"cevrilmis_fiyat": None, "oran": None, "kur": kur,
                    "cevrim_notu": "Birim çevrimi yapılamadı"}
        oran = c_hedef / c
        fiyat_tl = (k["net_fiyat"] * kur * oran).quantize(DORT, rounding=ROUND_HALF_UP)
        return {"cevrilmis_fiyat": fiyat_tl, "oran": oran.quantize(DORT), "kur": kur,
                "cevrim_notu": f"1 {hedef} = {oran.normalize()} {k['birim']}; kur {kur}"
                               + (f" ({k['kur_tarihi'].strftime('%d.%m.%Y')})" if k.get("kur_tarihi") else "")}

    gecmis = []
    son_tedarikci: dict[int, dict] = {}
    adet: dict[int, int] = defaultdict(int)
    for k in kayitlar:
        satir = dict(k)
        satir["kaynak"] = "ALIŞ"
        satir["gun"] = (gun0 - k["tarih"]).days if k["tarih"] else None
        if cevir:
            satir.update(_cevrim(k))
        gecmis.append(satir)
        son_tedarikci[k["cari_id"]] = satir
        adet[k["cari_id"]] += 1
    ozet = []
    for cid, s in son_tedarikci.items():
        r = dict(s)
        r["alis_sayisi"] = adet[cid]
        ozet.append(r)
    anahtarlar = {(r["birim"], r["para_birimi"]) for r in ozet}
    siralanabilir = bool(ozet) and (cevir or len(anahtarlar) == 1)
    if cevir:
        siralanabilir = siralanabilir and all(r.get("cevrilmis_fiyat") is not None for r in ozet)
    if siralanabilir:
        alan = "cevrilmis_fiyat" if cevir else "net_fiyat"
        ozet.sort(key=lambda r: r[alan])
        for i, r in enumerate(ozet, 1):
            r["sira"] = i
    else:
        ozet.sort(key=lambda r: r["tedarikci"])
    gecmis.sort(key=lambda r: (r["tarih"], r["belge_id"]), reverse=True)
    notlar = ["Gerçekleşmiş alışlar iptal edilmemiş alış faturalarından okunur; teklifler ayrı listededir."]
    if ozet and not siralanabilir:
        notlar.append("Fiyatlar farklı birim veya para biriminde; ucuz/pahalı sıralaması için 'TL ve tek birime çevir' seçin.")
    if cevir:
        notlar.append(f"Çevrilmiş fiyat: TL / {hedef}, belge kuru ve belge birim oranı ile.")
    return {"urun_kodu": urun_kodu, "urun_adi": (kart.stok_adi if kart else (kayitlar[-1]["urun_adi"] if kayitlar else "")),
            "hedef_birim": hedef, "ozet": ozet, "gecmis": gecmis, "teklifler": teklifler,
            "siralanabilir": siralanabilir, "notlar": notlar}


# ---------------------------------------------------------------------------
# 3) Bekleyen alış siparişleri
# ---------------------------------------------------------------------------

def _siparis_teslimleri(session, satir_idleri: list[int]) -> dict[int, Decimal]:
    """Sipariş satırı → teslim miktarı (irsaliye + irsaliyesiz doğrudan fatura; mükerrersiz)."""
    from sqlalchemy import func

    from database.models.alis_faturasi import AlisFaturasi, AlisFaturasiSatiri
    from database.models.alis_irsaliyesi import AlisIrsaliyesi, AlisIrsaliyesiSatiri

    teslim: dict[int, Decimal] = defaultdict(lambda: SIFIR)
    for i in range(0, len(satir_idleri), 500):
        parca = satir_idleri[i:i + 500]
        for sid, m in session.execute(
            select(AlisIrsaliyesiSatiri.siparis_satiri_id, func.sum(AlisIrsaliyesiSatiri.miktar))
            .join(AlisIrsaliyesi, AlisIrsaliyesi.id == AlisIrsaliyesiSatiri.irsaliye_id)
            .where(AlisIrsaliyesiSatiri.siparis_satiri_id.in_(parca), AlisIrsaliyesi.durum != "İPTAL")
            .group_by(AlisIrsaliyesiSatiri.siparis_satiri_id)
        ):
            teslim[int(sid)] += _d(m)
        for sid, m in session.execute(
            select(AlisFaturasiSatiri.siparis_satiri_id, func.sum(AlisFaturasiSatiri.miktar))
            .join(AlisFaturasi, AlisFaturasi.id == AlisFaturasiSatiri.fatura_id)
            .where(AlisFaturasiSatiri.siparis_satiri_id.in_(parca),
                   AlisFaturasiSatiri.irsaliye_satiri_id.is_(None),
                   AlisFaturasi.durum != "İPTAL")
            .group_by(AlisFaturasiSatiri.siparis_satiri_id)
        ):
            teslim[int(sid)] += _d(m)
    return teslim


def bekleyen_siparisler(
    *, bas: date | None = None, bit: date | None = None, cari_id: int | None = None,
    arama: str = "", sadece_geciken: bool = False, bugun: date | None = None,
) -> dict[str, Any]:
    from database.models.alis_siparisi import AlisSiparisi, AlisSiparisiSatiri
    from database.models.cari import Cari

    gun0 = _bugun(bugun)
    with get_session() as session:
        q = (
            select(AlisSiparisiSatiri, AlisSiparisi, Cari.unvan)
            .join(AlisSiparisi, AlisSiparisi.id == AlisSiparisiSatiri.siparis_id)
            .join(Cari, Cari.id == AlisSiparisi.cari_id)
            .where(AlisSiparisi.durum.notin_(SIPARIS_HARIC))
        )
        if cari_id:
            q = q.where(AlisSiparisi.cari_id == int(cari_id))
        if bas:
            q = q.where(AlisSiparisi.siparis_tarihi >= bas)
        if bit:
            q = q.where(AlisSiparisi.siparis_tarihi <= bit)
        rows = list(session.execute(q.order_by(AlisSiparisi.siparis_tarihi, AlisSiparisi.id, AlisSiparisiSatiri.id)))
        teslim = _siparis_teslimleri(session, [int(r[0].id) for r in rows])
    satirlar = []
    for s, sip, unvan in rows:
        if not _ara_uygun(arama, s.urun_kodu, s.urun_adi, unvan, sip.siparis_no):
            continue
        miktar = _d(s.miktar)
        gelen = teslim.get(int(s.id), SIFIR)
        kalan = miktar - gelen
        if kalan <= 0:
            continue
        termin = sip.termin_tarihi
        gecikme = (gun0 - termin).days if termin and gun0 > termin else 0
        if sadece_geciken and gecikme <= 0:
            continue
        net = net_iskontolu(s.birim_alis_fiyati, s.iskonto_orani)
        satirlar.append({
            "siparis_id": sip.id, "tedarikci": unvan or "", "siparis_tarihi": sip.siparis_tarihi,
            "siparis_no": sip.siparis_no, "durum": sip.durum, "urun_kodu": s.urun_kodu,
            "urun_adi": s.urun_adi, "birim": s.birim, "siparis_miktari": miktar,
            "gelen": gelen, "kalan": kalan, "termin": termin,
            "gecikme": gecikme if termin else None,
            "net_fiyat": net, "kalan_tutar": _kurus(kalan * net),
            "aciklama": "" if termin else "Teslim tarihi tanımlı değil",
        })
    return {"satirlar": satirlar, "toplam_kalan_tutar": sum((r["kalan_tutar"] for r in satirlar), SIFIR),
            "notlar": [
                "Gelen miktar: iptal edilmemiş irsaliye satırları + irsaliyesiz doğrudan fatura satırları "
                "(irsaliyeden faturalanan miktar ikinci kez sayılmaz).",
                "Taslak ve iptal siparişler dahil değildir. Kalan tutar KDV hariç, iskontolu net fiyatla hesaplanır.",
            ]}


# ---------------------------------------------------------------------------
# 4) Faturası gelmeyen alış irsaliyeleri
# ---------------------------------------------------------------------------

def faturasi_gelmeyen_irsaliyeler(
    *, bas: date | None = None, bit: date | None = None, cari_id: int | None = None,
    arama: str = "", bugun: date | None = None,
) -> dict[str, Any]:
    """Faturalanmamış/kısmi faturalanmış irsaliye satırları. Hiçbir kayıt oluşturmaz."""
    from sqlalchemy import func

    from database.models.alis_faturasi import AlisFaturasi, AlisFaturasiSatiri
    from database.models.alis_irsaliyesi import AlisIrsaliyesi, AlisIrsaliyesiSatiri
    from database.models.cari import Cari

    gun0 = _bugun(bugun)
    with get_session() as session:
        q = (
            select(AlisIrsaliyesiSatiri, AlisIrsaliyesi, Cari.unvan)
            .join(AlisIrsaliyesi, AlisIrsaliyesi.id == AlisIrsaliyesiSatiri.irsaliye_id)
            .join(Cari, Cari.id == AlisIrsaliyesi.cari_id)
            .where(AlisIrsaliyesi.durum != "İPTAL")
        )
        if cari_id:
            q = q.where(AlisIrsaliyesi.cari_id == int(cari_id))
        if bas:
            q = q.where(AlisIrsaliyesi.irsaliye_tarihi >= bas)
        if bit:
            q = q.where(AlisIrsaliyesi.irsaliye_tarihi <= bit)
        rows = list(session.execute(q.order_by(AlisIrsaliyesi.irsaliye_tarihi, AlisIrsaliyesi.id, AlisIrsaliyesiSatiri.id)))
        faturalanan: dict[int, Decimal] = defaultdict(lambda: SIFIR)
        idler = [int(r[0].id) for r in rows]
        for i in range(0, len(idler), 500):
            for sid, m in session.execute(
                select(AlisFaturasiSatiri.irsaliye_satiri_id, func.sum(AlisFaturasiSatiri.miktar))
                .join(AlisFaturasi, AlisFaturasi.id == AlisFaturasiSatiri.fatura_id)
                .where(AlisFaturasiSatiri.irsaliye_satiri_id.in_(idler[i:i + 500]), AlisFaturasi.durum != "İPTAL")
                .group_by(AlisFaturasiSatiri.irsaliye_satiri_id)
            ):
                faturalanan[int(sid)] += _d(m)
    satirlar = []
    fiyatsiz = 0
    for s, irs, unvan in rows:
        if not _ara_uygun(arama, s.urun_kodu, s.urun_adi, unvan, irs.irsaliye_no):
            continue
        teslim = _d(s.miktar)
        fat = faturalanan.get(int(s.id), SIFIR)
        kalan = teslim - fat
        if kalan <= 0:
            continue
        fiyat = _d(s.birim_fiyat)
        if fiyat > 0:
            tahmini = _kurus(kalan * net_iskontolu(fiyat, s.iskonto_orani))
        else:
            tahmini = None
            fiyatsiz += 1
        satirlar.append({
            "irsaliye_id": irs.id, "tedarikci": unvan or "", "irsaliye_tarihi": irs.irsaliye_tarihi,
            "irsaliye_no": irs.irsaliye_no, "durum": irs.durum, "urun_kodu": s.urun_kodu,
            "urun_adi": s.urun_adi, "birim": s.birim, "teslim": teslim, "faturalanan": fat,
            "faturalanmamis": kalan,
            "bekleme_gun": (gun0 - irs.irsaliye_tarihi).days if irs.irsaliye_tarihi else None,
            "tahmini_tutar": tahmini,
            "aciklama": "Tahmini (KDV hariç)" if tahmini is not None else "Fiyat yok — tutar bilinmiyor",
        })
    notlar = [
        "Tahmini tutar yalnız irsaliyede fiyat varsa gösterilir; cari borç veya muhasebe kaydı değildir.",
        "Faturalanan miktar, iptal edilmemiş faturalardaki irsaliye bağlantılarından hesaplanır.",
    ]
    if fiyatsiz:
        notlar.append(f"{fiyatsiz} satırda irsaliye fiyatı yok; bu satırlar tahmini toplama katılmadı (sıfır borç sayılmadı).")
    return {"satirlar": satirlar,
            "toplam_tahmini": sum((r["tahmini_tutar"] for r in satirlar if r["tahmini_tutar"] is not None), SIFIR),
            "fiyatsiz_satir": fiyatsiz, "notlar": notlar}


# ---------------------------------------------------------------------------
# 5) Yeniden sipariş önerisi
# ---------------------------------------------------------------------------

def _taslak_siparis_miktarlari(session, kartlar: dict[str, Any]) -> dict[str, Decimal]:
    """Ürün kodu → taslak alış siparişlerindeki miktar (temel birim)."""
    from database.models.alis_siparisi import AlisSiparisi, AlisSiparisiSatiri

    toplam: dict[str, Decimal] = defaultdict(lambda: SIFIR)
    if not kartlar:
        return toplam
    for s in session.scalars(
        select(AlisSiparisiSatiri).join(AlisSiparisi, AlisSiparisi.id == AlisSiparisiSatiri.siparis_id)
        .where(AlisSiparisi.durum == "TASLAK", AlisSiparisiSatiri.urun_kodu.in_(list(kartlar)))
    ):
        c = _carpan(kartlar.get(s.urun_kodu), s.birim) or Decimal("1")
        toplam[s.urun_kodu] += _d(s.miktar) * c
    return toplam


def yeniden_siparis_onerisi(
    *, donem_gun: int = 90, hedef_gun: int = 30, musteri_siparisi_dus: bool = True,
    arama: str = "", tedarik_gun: int = 0,
) -> dict[str, Any]:
    """Azalan / tükenen ürünler için sipariş önerisi (otomatik sipariş oluşturmaz).

    hedef stok = max(minimum, günlük satış hızı × (hedef gün + tedarik süresi varsayımı))
    öneri = hedef − (satılabilir − [müşteri siparişleri]) − bekleyen alış − taslak sipariş
    """
    from database.stok_uyari_service import StokUyariService

    donem_gun = max(1, int(donem_gun or 1))
    hedef_gun = max(0, int(hedef_gun or 0))
    tedarik_gun = max(0, int(tedarik_gun or 0))
    if StokUyariService.ilk_tarama_gerekli():
        StokUyariService.toplu_degerlendir()
    veri = StokUyariService.listele({"donem_gun": donem_gun, "arama": arama or ""})
    kaynak = veri.get("satirlar", []) if isinstance(veri, dict) else list(veri or [])
    with get_session() as session:
        kartlar = _kart_haritasi(session, {r["stok_kodu"] for r in kaynak})
        taslaklar = _taslak_siparis_miktarlari(session, kartlar)
    satirlar = []
    for r in kaynak:
        kod = r["stok_kodu"]
        if not _ara_uygun(arama, kod, r.get("stok_adi"), r.get("son_tedarikci")):
            continue
        minimum = _d(r.get("minimum"))
        satilabilir = _d(r.get("satilabilir"))
        beklenen = _d(r.get("beklenen"))
        talep = _d(r.get("musteri_talebi"))
        satis = _d(r.get("donem_net_satis"))
        taslak = taslaklar.get(kod, SIFIR)
        hiz = (satis / Decimal(donem_gun)) if satis > 0 else SIFIR
        hedef = max(minimum, (hiz * Decimal(hedef_gun + tedarik_gun)))
        kullanilabilir = satilabilir - (talep if musteri_siparisi_dus else SIFIR)
        notlar = []
        if satis <= 0:
            notlar.append(f"Son {donem_gun} günde satış yok; öneri yalnız minimum stoka göre")
        if minimum <= 0 and satis <= 0:
            notlar.append("Veri yetersiz: minimum stok ve satış yok")
        if not r.get("son_alis"):
            notlar.append("Alış geçmişi yok")
        if taslak > 0:
            notlar.append(f"Taslak siparişte {taslak.normalize()} {r.get('temel_birim') or ''} var")
        oneri_temel = hedef - kullanilabilir - beklenen - taslak
        oneri_temel = oneri_temel if oneri_temel > 0 and hedef > 0 else SIFIR
        alim_birimi = r.get("alim_birimi") or r.get("temel_birim")
        carpan = _carpan(kartlar.get(kod), alim_birimi) or Decimal("1")
        oneri = (oneri_temel / carpan).to_integral_value(rounding=ROUND_CEILING) if oneri_temel > 0 else SIFIR
        son = r.get("son_alis") or {}
        satirlar.append({
            "ihtiyac_id": r.get("id"), "row_version": r.get("row_version"),
            "stok_kodu": kod, "stok_adi": r.get("stok_adi"), "depo": r.get("depo"),
            "temel_birim": r.get("temel_birim"), "fiziksel": _d(r.get("fiziksel")),
            "rezerve": _d(r.get("rezerve")), "musteri_talebi": talep,
            "kullanilabilir": kullanilabilir, "minimum": minimum,
            "donem_satis": satis, "gunluk_hiz": hiz.quantize(DORT, rounding=ROUND_HALF_UP),
            "bekleyen_alis": beklenen, "taslak_siparis": taslak, "hedef": hedef.quantize(DORT, rounding=ROUND_HALF_UP),
            "oneri": oneri, "alim_birimi": alim_birimi, "carpan": carpan,
            "son_alis_tarihi": son.get("tarih"), "son_alis_fiyati": son.get("net_fiyat"),
            "son_alis_pb": son.get("para_birimi") or "TRY",
            "son_tedarikci": r.get("son_tedarikci") or "", "tedarikci_id": r.get("tedarikci_id"),
            "tahmini_fiyat": r.get("tahmini_fiyat"),
            "veri_yetersiz": minimum <= 0 and satis <= 0,
            "aciklama": "; ".join(notlar),
        })
    tedarik_notu = (f"Tedarik süresi programda kayıtlı değil; kullanıcı varsayımı {tedarik_gun} gün hedef güne eklendi."
                    if tedarik_gun else
                    "Tedarik süresi programda kayıtlı değil ve varsayım girilmedi (0 gün); uydurulmadı.")
    return {"satirlar": satirlar, "donem_gun": donem_gun, "hedef_gun": hedef_gun, "tedarik_gun": tedarik_gun,
            "notlar": [f"Varsayımlar: satış dönemi {donem_gun} gün, hedef stok {hedef_gun} gün. "
                       "Hedef stok = max(minimum, günlük hız × (hedef gün + tedarik süresi)).",
                       tedarik_notu, REZERVASYON_NOTU,
                       "Bekleyen alış: taslak ve iptal dışındaki siparişlerin faturalanmamış kalanı. "
                       "Taslak siparişteki miktar ayrıca düşülür; aynı öneri tekrar oluşmaz.",
                       "Rapor sipariş oluşturmaz; seçilen satırlardan yetkiyle taslak alış siparişi hazırlanabilir."]}


def taslak_siparis_olustur(satirlar: list[dict], *, termin: date | None = None) -> list[dict]:
    """Seçilen öneri satırlarından taslak alış siparişi (mevcut stok uyarı servisi ile)."""
    from database.stok_uyari_service import StokUyariService

    secimler = []
    for r in satirlar:
        if not r.get("ihtiyac_id") or not r.get("tedarikci_id"):
            raise ValueError(f"{r.get('stok_kodu')}: tedarikçi bilinmiyor; önce tedarikçi seçilmeli.")
        if _d(r.get("oneri")) <= 0:
            raise ValueError(f"{r.get('stok_kodu')}: önerilen miktar yok.")
        fiyat = _d(r.get("son_alis_fiyati"))
        if (r.get("son_alis_pb") or "TRY") != "TRY":
            fiyat = SIFIR
        secimler.append({
            "ihtiyac_id": r["ihtiyac_id"], "row_version": r.get("row_version"),
            "tedarikci_id": r["tedarikci_id"], "miktar": r["oneri"], "birim": r.get("alim_birimi"),
            "fiyat": fiyat,
        })
    return StokUyariService.siparis_hazirla(secimler, termin=termin)


# ---------------------------------------------------------------------------
# 6) Tedarikçi borç ve vade raporu
# ---------------------------------------------------------------------------

def _tedarikciler(session, cari_id=None):
    from database.cari_service import CariService
    from database.models.cari import Cari

    if cari_id:
        c = session.get(Cari, int(cari_id))
        return [c] if c else []
    q = CariService._cari_turu_filtresi(select(Cari), "Tedarikçi")
    return list(session.scalars(q.order_by(Cari.unvan)))


YONTEM_BAGLI = "Faturaya bağlı"
YONTEM_FIFO = "FIFO ile hesaplandı"


def _bagli_kapatmalar(session, cari_id: int, rapor_tarihi: date) -> list:
    """Rapor tarihinde geçerli, kullanıcının belirli faturaya bağladığı (MANUEL) kapatma kayıtları.

    Rapor tarihinden sonra yapılan bağlantılar alınmaz; rapor tarihinden sonra iptal edilenler o tarihte
    geçerli olduğundan alınır.
    """
    from database.acik_kalem_service import AcikKalemService
    from database.models.cari import CariKapatma

    if not AcikKalemService._tablo_var(session):
        return []
    sinir = datetime.combine(rapor_tarihi, datetime.max.time())
    return list(session.scalars(
        select(CariKapatma).where(
            CariKapatma.cari_id == int(cari_id), CariKapatma.yontem == "MANUEL",
            CariKapatma.tarih <= rapor_tarihi,
            or_(CariKapatma.iptal.is_(False), CariKapatma.iptal_zamani > sinir))
        .order_by(CariKapatma.tarih, CariKapatma.id)))


def _fifo_tarihli(session, cari_id: int, rapor_tarihi: date) -> dict[str, Any]:
    """Rapor tarihindeki açık kalemler (tedarikçi borç ve açık fatura raporlarının ortak hesabı).

    Önce ödeme/iade/mahsubun belirli faturaya bağlandığı kapatma kayıtları uygulanır; kalan bağlantısız
    tutarlar programın mevcut FIFO kapatma yöntemiyle eşleştirilir. Kayıtlar değiştirilmez; hesap
    salt okunur kopyalar üzerinde yapılır. Rapor tarihinden sonraki fatura, ödeme, iade, mahsup ve
    bağlantılar dikkate alınmaz. Açık kalemlere kaynak cari hareketi (``_hareket``), vadenin faturadan
    gelip gelmediği (``vade_tanimli``) ve kapanış yöntemi (``kapanis``) eklenir.
    """
    from types import SimpleNamespace

    from database.cari_ortalama_valor_service import fifo_valor_paketi_hesapla
    from database.cari_service import CariService
    from database.models.cari import CariIslem, SatisHareketi

    hareketler = list(session.scalars(
        select(SatisHareketi).where(SatisHareketi.cari_id == int(cari_id), SatisHareketi.satis_tarihi <= rapor_tarihi)
        .order_by(SatisHareketi.satis_tarihi, SatisHareketi.id)))
    islemler = list(session.scalars(
        select(CariIslem).where(CariIslem.cari_id == int(cari_id), CariIslem.tarih <= rapor_tarihi)
        .order_by(CariIslem.tarih, CariIslem.id)))
    vade_harita = CariService._borc_vade_haritasi(session, [h.belge_no for h in hareketler])

    hedef_kalan = {int(h.id): _kurus(h.satis_tutari) for h in hareketler}
    hedefler = {int(h.id): h for h in hareketler}
    kaynak_kalan: dict[int, Decimal] = {int(i.id): _kurus(CariService._odeme_borc_dusurur_mu(i, True))
                                        for i in islemler}
    kaynak_idleri: dict[str, list[int]] = defaultdict(list)
    for i in islemler:
        kaynak_idleri[i.belge_no or ""].append(int(i.id))
    islem_harita = {int(i.id): i for i in islemler}
    bagli_dilimler, bagli_hedef = [], defaultdict(lambda: SIFIR)
    uygulanmayan = 0
    for k in _bagli_kapatmalar(session, cari_id, rapor_tarihi):
        hid = int(k.hedef_hareket_id)
        tutar = _kurus(k.tutar)
        kaynak = next((j for j in kaynak_idleri.get(k.kaynak_belge_no or "", []) if kaynak_kalan[j] > 0), None)
        if hid not in hedef_kalan or kaynak is None:
            uygulanmayan += 1
            continue
        tutar = min(tutar, hedef_kalan[hid], kaynak_kalan[kaynak])
        if tutar <= 0:
            continue
        hedef_kalan[hid] -= tutar
        kaynak_kalan[kaynak] -= tutar
        bagli_hedef[hid] += tutar
        h, odeme = hedefler[hid], islem_harita[kaynak]
        vade = CariService._hareket_vade(h, vade_harita)
        bagli_dilimler.append({
            "odeme_belge_no": odeme.belge_no, "odeme_tarihi": odeme.tarih, "borc_belge_no": h.belge_no or "",
            "borc_tarihi": h.satis_tarihi, "borc_vadesi": vade, "tutar": tutar,
            "gun": (odeme.tarih - vade).days if vade and odeme.tarih else 0, "yontem": YONTEM_BAGLI,
        })

    kopya_hareket = [SimpleNamespace(id=h.id, belge_no=h.belge_no, satis_tarihi=h.satis_tarihi,
                                     satis_tutari=hedef_kalan[int(h.id)], _orj=h) for h in hareketler]
    kopya_islem = [SimpleNamespace(id=i.id, belge_no=i.belge_no, tarih=i.tarih, islem_turu=i.islem_turu,
                                   alacak=kaynak_kalan[int(i.id)], borc=SIFIR) for i in islemler]
    kapanan, acik, dilimler, avanslar = fifo_valor_paketi_hesapla(
        kopya_hareket, kopya_islem, cari_turu="Tedarikçi", vade_harita=vade_harita, referans=rapor_tarihi)
    fifo_belgeler = set()
    for d in dilimler:
        d["yontem"] = YONTEM_FIFO
        fifo_belgeler.add(d["borc_belge_no"] or "")
    dilimler = bagli_dilimler + dilimler
    eslesme: dict[tuple, list] = defaultdict(list)
    for h in kopya_hareket:
        if _kurus(h.satis_tutari) > 0:
            eslesme[(h.belge_no or "", h.satis_tarihi)].append(h)
    acik_sayisi: dict[tuple, int] = defaultdict(int)
    for d in acik:
        acik_sayisi[(d["borc_belge_no"] or "", d["borc_tarihi"])] += 1
    sira: dict[tuple, int] = defaultdict(int)
    for d in acik:
        anahtar = (d["borc_belge_no"] or "", d["borc_tarihi"])
        grup = eslesme.get(anahtar) or []
        # FIFO aynı belge/tarihli kalemlerde önce eskisini kapatır; açık kalanlar grubun sonundadır.
        i = len(grup) - acik_sayisi[anahtar] + sira[anahtar]
        sira[anahtar] += 1
        kopya = grup[i] if 0 <= i < len(grup) else None
        d["_hareket"] = kopya._orj if kopya is not None else None
        d["vade_tanimli"] = (d["borc_belge_no"] or "") in vade_harita
        yontemler = []
        if kopya is not None and bagli_hedef.get(int(kopya.id)):
            yontemler.append(YONTEM_BAGLI)
        if (d["borc_belge_no"] or "") in fifo_belgeler and _kurus(d["tutar"]) < _kurus(
                kopya.satis_tutari if kopya is not None else d["tutar"]):
            yontemler.append(YONTEM_FIFO)
        d["kapanis"] = " + ".join(yontemler)
    negatif = [h for h in hareketler if _d(h.satis_tutari) < 0]
    return {"kapanan": kapanan, "acik": acik, "dilimler": dilimler, "avanslar": avanslar, "negatif": negatif,
            "bagli_uygulanmayan": uygulanmayan}


def tedarikci_borc_vade(
    *, cari_id: int | None = None, arama: str = "", bugun: date | None = None,
    sadece_bakiyeli: bool = True,
) -> dict[str, Any]:
    """Tedarikçi bazında FIFO açık kalem ve vade dağılımı; ödeme sözleri ayrı."""
    from database.cari_bakiye_service import net_bakiye
    from database.cari_service import CariService
    from database.odeme_sozu_service import OdemeSozuService

    gun0 = _bugun(bugun)
    sozler: dict[int, list[dict]] = defaultdict(list)
    try:
        for s in OdemeSozuService.liste(cari_id=cari_id, yon="VERILEN", sadece_acik=True):
            sozler[int(s["cari_id"])].append(s)
    except Exception:  # noqa: BLE001 - söz tablosu yoksa rapor yine çalışır
        sozler = defaultdict(list)
    satirlar = []
    with get_session() as session:
        for c in _tedarikciler(session, cari_id):
            if not _ara_uygun(arama, c.cari_kodu, c.unvan):
                continue
            fifo = _fifo_tarihli(session, int(c.id), gun0)
            acik, dilimler, avanslar = fifo["acik"], fifo["dilimler"], fifo["avanslar"]
            bakiye = _kurus(net_bakiye(int(c.id), session=session)["bakiye"])
            kapanan = sum((_d(d["tutar"]) for d in dilimler), SIFIR)
            acik_toplam = sum((_d(d["tutar"]) for d in acik), SIFIR)
            gecmis = sum((_d(d["tutar"]) for d in acik if d["borc_vadesi"] and d["borc_vadesi"] < gun0), SIFIR)
            bugun_t = sum((_d(d["tutar"]) for d in acik if d["borc_vadesi"] == gun0), SIFIR)
            ileri = acik_toplam - gecmis - bugun_t
            avans = sum((_d(d["tutar"]) for d in avanslar), SIFIR)
            soz = sozler.get(int(c.id), [])
            soz_toplam = sum((_d(s.get("kalan")) for s in soz), SIFIR)
            fark = bakiye - (acik_toplam - avans)
            if sadece_bakiyeli and not bakiye and not acik_toplam and not soz:
                continue
            aciklama = []
            if avans:
                aciklama.append(f"Avans/fazla ödeme {_kurus(avans)}")
            if abs(fark) > KURUS:
                aciklama.append(f"Fatura dışı hareket farkı {_kurus(fark)} (devir, mahsup, virman vb. — detaya bakın)")
            satirlar.append({
                "cari_id": int(c.id), "cari_kodu": c.cari_kodu, "tedarikci": c.unvan,
                "toplam_borc": _kurus(kapanan + acik_toplam), "kapanan": _kurus(kapanan),
                "acik": _kurus(acik_toplam), "vadesi_gecmis": _kurus(gecmis),
                "bugun": _kurus(bugun_t), "ileri_vade": _kurus(ileri), "avans": _kurus(avans),
                "bakiye": bakiye, "fark": _kurus(fark), "soz_sayisi": len(soz),
                "soz_tutari": _kurus(soz_toplam),
                "en_yakin_soz": min((s.get("vade_tarihi") for s in soz if s.get("vade_tarihi")), default=None),
                "aciklama": "; ".join(aciklama),
            })
    return {"satirlar": satirlar, "notlar": [
        "Belirli faturaya bağlanmış ödeme/iade/mahsup önce o faturayı kapatır; bağlantısız tutarlar programın "
        "mevcut yöntemiyle FIFO (en eski borçtan) düşülür. Vade fatura vade tarihidir. Geçmiş tarihte sonraki "
        "ödeme, iade, mahsup ve bağlantılar dikkate alınmaz.",
        "Ödeme sözleri ödeme değildir; borcu azaltmaz, yalnız bilgi olarak ayrı gösterilir.",
        "Bakiye ile açık kalem farkı; avans, devir, mahsup ve fatura dışı hareketlerden gelir (detayda listelenir).",
    ]}


def tedarikci_borc_detay(cari_id: int, *, bugun: date | None = None) -> dict[str, Any]:
    """Bir tedarikçinin açık kalemleri, ödeme sözleri ve bakiye farkı açıklaması."""
    from database.cari_bakiye_service import net_bakiye
    from database.cari_service import CariService
    from database.models.alis_faturasi import AlisFaturasi
    from database.models.cari import Cari, CariIslem, SatisHareketi
    from database.odeme_sozu_service import OdemeSozuService

    gun0 = _bugun(bugun)
    with get_session() as session:
        cari = session.get(Cari, int(cari_id))
        fifo = _fifo_tarihli(session, int(cari_id), gun0)
        acik, avanslar = fifo["acik"], fifo["avanslar"]
        bakiye = _kurus(net_bakiye(int(cari_id), session=session)["bakiye"])
        fatura_nolari = set(session.scalars(select(AlisFaturasi.fatura_no).where(AlisFaturasi.cari_id == int(cari_id))))
        hareketler = list(session.scalars(select(SatisHareketi).where(SatisHareketi.cari_id == int(cari_id))))
        islemler = list(session.scalars(select(CariIslem).where(CariIslem.cari_id == int(cari_id))))
    kalemler = []
    for d in acik:
        vade = d["borc_vadesi"]
        durum = "Vadesi geçmiş" if vade and vade < gun0 else ("Bugün" if vade == gun0 else "İleri vade")
        kalemler.append({
            "belge_no": d["borc_belge_no"], "tarih": d["borc_tarihi"], "vade": vade,
            "tutar": _kurus(d["tutar"]), "gun": d["gun"], "durum": durum,
            "tur": "Alış faturası" if d["borc_belge_no"] in fatura_nolari else "Fatura dışı borç (devir/açılış vb.)",
            "kapanis": d.get("kapanis") or "",
        })
    aciklama: dict[str, list[Decimal]] = defaultdict(lambda: [SIFIR, SIFIR])
    for h in hareketler:
        no = h.belge_no or ""
        tutar = _d(h.satis_tutari)
        if no in fatura_nolari and tutar > 0:
            continue
        if tutar > 0 and not no.startswith(CariService._VALOR_BORC_HARIC_ONEK):
            tur = "Fatura dışı borç (devir/açılış vb.)"
        elif tutar > 0:
            tur = f"Borç hareketi ({no.split('-')[0]}-)"
        else:
            tur = "Negatif hareket (iade/düzeltme)"
        aciklama[tur][0 if tutar > 0 else 1] += abs(tutar)
    for i in islemler:
        aciklama[f"Cari işlem: {i.islem_turu or 'Diğer'}"][0] += _d(i.borc)
        aciklama[f"Cari işlem: {i.islem_turu or 'Diğer'}"][1] += _d(i.alacak)
    try:
        sozler = OdemeSozuService.liste(cari_id=int(cari_id), yon="VERILEN", sadece_acik=True)
    except Exception:  # noqa: BLE001
        sozler = []
    return {
        "cari_id": int(cari_id), "tedarikci": cari.unvan if cari else "", "bakiye": bakiye,
        "kalemler": kalemler,
        "avanslar": [{"belge_no": a["alacak_belge_no"], "tarih": a["alacak_tarihi"], "tutar": _kurus(a["tutar"])}
                     for a in avanslar],
        "aciklama": [{"tur": k, "borc": _kurus(v[0]), "alacak": _kurus(v[1])} for k, v in sorted(aciklama.items())],
        "sozler": [{"tarih": s.get("soz_tarihi"), "vade": s.get("vade_tarihi"), "tutar": _d(s.get("tutar")),
                    "kalan": _d(s.get("kalan")), "yontem": s.get("yontem") or "", "durum": s.get("durum") or "",
                    "para_birimi": s.get("para_birimi") or "TRY"} for s in sozler],
    }


# ---------------------------------------------------------------------------
# 7) Ürün bazında gerçek alış maliyeti
# ---------------------------------------------------------------------------

def gercek_alis_maliyeti(
    *, bas: date | None = None, bit: date | None = None, cari_id: int | None = None,
    arama: str = "", gruplama: str = "urun",
) -> dict[str, Any]:
    """Net alış (iskontolar sonrası) + dağıtılmış nakliye / diğer masraflar.

    Kaynaklar: fatura masrafları (``AlisMasrafDagitim``, maliyete dahil) ve onaylı masraf
    dağıtımları (``MasrafDagitimSatiri``). Mevcut mükerrer kontrolü 'kesin' bulduğu eski
    masrafı ikinci kez saymaz; taslak dağıtımlar maliyeti 'geçici' yapar.
    """
    from database.masraf_dagitim_service import MasrafDagitimService, masraf_kategorileri
    from database.models.alis_masraf import AlisMasraf, AlisMasrafDagitim
    from database.models.masraf_dagitim import MasrafDagitim, MasrafDagitimKaynakSatiri, MasrafDagitimSatiri

    try:
        mukerrer = MasrafDagitimService.mukerrer_masraf_raporu()
    except Exception:  # noqa: BLE001
        mukerrer = []
    kesin_eski = {int(r["eski_masraf_id"]) for r in mukerrer if r.get("durum") == "kesin"}
    inceleme_fatura = {int(r["alis_fatura_id"]) for r in mukerrer if r.get("durum") != "kesin"}

    with get_session() as session:
        kayitlar = _alis_kayitlari(session, cari_id=cari_id, bas=bas, bit=bit)
        kayitlar = [k for k in kayitlar if _ara_uygun(arama, k["urun_kodu"], k["urun_adi"], k["tedarikci"])]
        kartlar = _kart_haritasi(session, {k["urun_kodu"] for k in kayitlar})
        satir_idleri = [k["satir_id"] for k in kayitlar]
        eski: dict[int, list[Decimal]] = defaultdict(lambda: [SIFIR, SIFIR])
        yeni: dict[int, list[Decimal]] = defaultdict(lambda: [SIFIR, SIFIR])
        taslak: set[int] = set()
        mukerrer_satir: set[int] = set()
        for i in range(0, len(satir_idleri), 500):
            parca = satir_idleri[i:i + 500]
            for dg, m in session.execute(
                select(AlisMasrafDagitim, AlisMasraf)
                .join(AlisMasraf, AlisMasraf.id == AlisMasrafDagitim.masraf_id)
                .where(AlisMasrafDagitim.fatura_satiri_id.in_(parca), AlisMasraf.maliyete_dahil.is_(True))
            ):
                if int(m.id) in kesin_eski:
                    mukerrer_satir.add(int(dg.fatura_satiri_id))
                    continue
                idx = 0 if "NAKLİYE" in masraf_kategorileri(m.masraf_turu, m.aciklama) else 1
                eski[int(dg.fatura_satiri_id)][idx] += _d(dg.tutar)
            dagitimlar = {}
            for ms, md in session.execute(
                select(MasrafDagitimSatiri, MasrafDagitim)
                .join(MasrafDagitim, MasrafDagitim.id == MasrafDagitimSatiri.dagitim_id)
                .where(MasrafDagitimSatiri.alis_fatura_satiri_id.in_(parca),
                       MasrafDagitim.durum.in_(("ONAYLANDI", "TASLAK")))
            ):
                if md.durum == "TASLAK":
                    taslak.add(int(ms.alis_fatura_satiri_id))
                    continue
                if md.id not in dagitimlar:
                    metin = [md.aciklama] + list(session.scalars(
                        select(MasrafDagitimKaynakSatiri.aciklama).where(MasrafDagitimKaynakSatiri.dagitim_id == md.id)))
                    dagitimlar[md.id] = "NAKLİYE" in masraf_kategorileri(*metin)
                idx = 0 if dagitimlar[md.id] else 1
                yeni[int(ms.alis_fatura_satiri_id)][idx] += _d(ms.pay)

    gruplar: dict[tuple, dict] = {}
    for k in kayitlar:
        kart = kartlar.get(k["urun_kodu"])
        c = _carpan(kart, k["birim"], k.get("birim_carpani"))
        temel = k["miktar"] * c if c else None
        net = _kurus(k["miktar"] * k["net_fiyat_tl"])
        sid = k["satir_id"]
        nakliye = eski[sid][0] + yeni[sid][0]
        diger = eski[sid][1] + yeni[sid][1]
        if gruplama == "satir":
            anahtar = (sid,)
        elif gruplama == "tedarikci":
            anahtar = (k["urun_kodu"], k["cari_id"])
        else:
            anahtar = (k["urun_kodu"],)
        g = gruplar.setdefault(anahtar, {
            "urun_kodu": k["urun_kodu"], "urun_adi": k["urun_adi"],
            "tedarikci": k["tedarikci"] if gruplama != "urun" else "",
            "belge_no": k["belge_no"] if gruplama == "satir" else "",
            "tarih": k["tarih"] if gruplama == "satir" else None,
            "temel_birim": kart.birim if kart else k["birim"],
            "miktar": SIFIR, "net_alis": SIFIR, "nakliye": SIFIR, "diger": SIFIR,
            "_gecici": False, "_mukerrer": False, "_inceleme": False, "_birim_hata": False,
        })
        if temel is None:
            g["_birim_hata"] = True
        else:
            g["miktar"] += temel
        g["net_alis"] += net
        g["nakliye"] += nakliye
        g["diger"] += diger
        g["_gecici"] |= sid in taslak
        g["_mukerrer"] |= sid in mukerrer_satir
        g["_inceleme"] |= k["belge_id"] in inceleme_fatura
    satirlar = []
    for g in gruplar.values():
        toplam = g["net_alis"] + _kurus(g["nakliye"]) + _kurus(g["diger"])
        durum = []
        if g["_gecici"]:
            durum.append("Geçici: taslak masraf dağıtımı var")
        if g["_mukerrer"]:
            durum.append("Mükerrer masraf bir kez sayıldı")
        if g["_inceleme"]:
            durum.append("Masraf mükerrer şüphesi — inceleme gerekli")
        if g["_birim_hata"]:
            durum.append("Birim çevrimi eksik")
        satirlar.append({
            **{k: v for k, v in g.items() if not k.startswith("_")},
            "nakliye": _kurus(g["nakliye"]), "diger": _kurus(g["diger"]),
            "toplam_maliyet": _kurus(toplam),
            "birim_maliyet": (toplam / g["miktar"]).quantize(DORT, rounding=ROUND_HALF_UP) if g["miktar"] > 0 else None,
            "durum": "; ".join(durum) or "Tamam",
            "eksik": bool(g["_gecici"] or g["_inceleme"] or g["_birim_hata"]),
        })
    satirlar.sort(key=lambda r: (r["urun_kodu"], r["tedarikci"], r["tarih"] or date.min))
    return {"satirlar": satirlar, "notlar": [
        "Net alış: iskontolar düşülmüş, KDV hariç TL tutar.",
        "Masraflar: fatura masrafları (maliyete dahil) ve onaylı masraf dağıtımları; taslak dağıtım tutara eklenmez, satır 'geçici' işaretlenir.",
        KDV_MALIYET_NOTU,
    ]}


# ---------------------------------------------------------------------------
# 8) Alış ve iade özeti
# ---------------------------------------------------------------------------

def alis_iade_ozeti(
    *, bas: date | None = None, bit: date | None = None, gruplama: str = "urun",
    cari_id: int | None = None, arama: str = "",
) -> dict[str, Any]:
    """Dönem alış ve alış iadesi; KDV hariç / KDV / KDV dahil ayrı. Miktarlar temel birimde."""
    from database.models.alis_iade_faturasi import AlisIadeFaturasi, AlisIadeFaturasiSatiri
    from database.models.cari import Cari

    with get_session() as session:
        alislar = _alis_kayitlari(session, cari_id=cari_id, bas=bas, bit=bit)
        q = (
            select(AlisIadeFaturasiSatiri, AlisIadeFaturasi, Cari.unvan)
            .join(AlisIadeFaturasi, AlisIadeFaturasi.id == AlisIadeFaturasiSatiri.iade_id)
            .join(Cari, Cari.id == AlisIadeFaturasi.cari_id)
            .where(AlisIadeFaturasi.durum.notin_(IADE_HARIC))
        )
        if cari_id:
            q = q.where(AlisIadeFaturasi.cari_id == int(cari_id))
        if bas:
            q = q.where(AlisIadeFaturasi.iade_tarihi >= bas)
        if bit:
            q = q.where(AlisIadeFaturasi.iade_tarihi <= bit)
        iadeler = []
        for s, iade, unvan in session.execute(q):
            k = _satir_kaydi(s, iade, unvan, tur="İADE")
            k["urun_kodu"] = s.urun_kodu
            k["urun_adi"] = s.urun_adi
            iadeler.append(k)
        kartlar = _kart_haritasi(session, {k["urun_kodu"] for k in alislar + iadeler})

    gruplar: dict[Any, dict] = {}
    birim_hata = 0
    for tur, liste in (("alis", alislar), ("iade", iadeler)):
        for k in liste:
            if not _ara_uygun(arama, k["urun_kodu"], k["urun_adi"], k["tedarikci"]):
                continue
            kart = kartlar.get(k["urun_kodu"])
            if gruplama == "grup":
                anahtar, ad1, ad2 = _grup_adi(kart), _grup_adi(kart), ""
            elif gruplama == "tedarikci":
                anahtar, ad1, ad2 = k["cari_id"], k["tedarikci"], ""
            else:
                anahtar, ad1, ad2 = k["urun_kodu"], k["urun_kodu"], k["urun_adi"]
            g = gruplar.setdefault(anahtar, {
                "anahtar": ad1, "ad": ad2, "temel_birim": (kart.birim if kart else k["birim"]) if gruplama == "urun" else "",
                "alis_miktar": SIFIR, "alis_haric": SIFIR, "alis_kdv": SIFIR,
                "iade_miktar": SIFIR, "iade_haric": SIFIR, "iade_kdv": SIFIR,
            })
            c = _carpan(kart, k["birim"], k.get("birim_carpani"))
            if c is None:
                birim_hata += 1
                c = Decimal("1")
            haric = _kurus(k["miktar"] * k["net_fiyat_tl"])
            kdv = _kurus(haric * k["kdv_orani"] / YUZ)
            g[f"{tur}_miktar"] += k["miktar"] * c
            g[f"{tur}_haric"] += haric
            g[f"{tur}_kdv"] += kdv
    satirlar = []
    for g in gruplar.values():
        g["alis_dahil"] = g["alis_haric"] + g["alis_kdv"]
        g["iade_dahil"] = g["iade_haric"] + g["iade_kdv"]
        g["net_miktar"] = g["alis_miktar"] - g["iade_miktar"]
        g["net_haric"] = g["alis_haric"] - g["iade_haric"]
        g["net_kdv"] = g["alis_kdv"] - g["iade_kdv"]
        g["net_dahil"] = g["alis_dahil"] - g["iade_dahil"]
        if gruplama != "urun":
            g["alis_miktar"] = g["iade_miktar"] = g["net_miktar"] = None
        satirlar.append(g)
    satirlar.sort(key=lambda r: str(r["anahtar"]))
    alanlar = ("alis_haric", "alis_kdv", "alis_dahil", "iade_haric", "iade_kdv", "iade_dahil",
               "net_haric", "net_kdv", "net_dahil")
    toplam = {a: sum((r[a] for r in satirlar), SIFIR) for a in alanlar}
    notlar = [
        "Tutarlar iskontolar düşülmüş satır tutarlarından TL olarak hesaplanır; KDV satır oranıyla ayrı izlenir.",
        "İptal ve taslak belgeler dahil değildir. Miktarlar stok kartı temel biriminde toplanır (ürün gruplamasında).",
    ]
    if birim_hata:
        notlar.append(f"{birim_hata} satırda birim çevrimi bulunamadı; miktar belge biriminde toplandı.")
    return {"satirlar": satirlar, "toplam": toplam, "notlar": notlar}


# ---------------------------------------------------------------------------
# 9) Tedarikçi teslimat performansı
# ---------------------------------------------------------------------------

def _siparis_teslimat_belgeleri(session, satir_idleri: list[int]) -> dict[int, list[dict]]:
    """Sipariş satırı → teslimat belgeleri (irsaliye + irsaliyesiz doğrudan fatura; ``_siparis_teslimleri`` ile aynı kapsam)."""
    from database.models.alis_faturasi import AlisFaturasi, AlisFaturasiSatiri
    from database.models.alis_irsaliyesi import AlisIrsaliyesi, AlisIrsaliyesiSatiri

    sonuc: dict[int, list[dict]] = defaultdict(list)
    for i in range(0, len(satir_idleri), 500):
        parca = satir_idleri[i:i + 500]
        for sid, m, tarih, no, bid in session.execute(
            select(AlisIrsaliyesiSatiri.siparis_satiri_id, AlisIrsaliyesiSatiri.miktar, AlisIrsaliyesi.irsaliye_tarihi,
                   AlisIrsaliyesi.irsaliye_no, AlisIrsaliyesi.id)
            .join(AlisIrsaliyesi, AlisIrsaliyesi.id == AlisIrsaliyesiSatiri.irsaliye_id)
            .where(AlisIrsaliyesiSatiri.siparis_satiri_id.in_(parca), AlisIrsaliyesi.durum != "İPTAL")
        ):
            sonuc[int(sid)].append({"tur": "İrsaliye", "tarih": tarih, "miktar": _d(m), "belge_no": no,
                                    "belge_id": int(bid)})
        for sid, m, tarih, no, bid in session.execute(
            select(AlisFaturasiSatiri.siparis_satiri_id, AlisFaturasiSatiri.miktar, AlisFaturasi.fatura_tarihi,
                   AlisFaturasi.fatura_no, AlisFaturasi.id)
            .join(AlisFaturasi, AlisFaturasi.id == AlisFaturasiSatiri.fatura_id)
            .where(AlisFaturasiSatiri.siparis_satiri_id.in_(parca), AlisFaturasiSatiri.irsaliye_satiri_id.is_(None),
                   AlisFaturasi.durum != "İPTAL")
        ):
            sonuc[int(sid)].append({"tur": "Fatura", "tarih": tarih, "miktar": _d(m), "belge_no": no,
                                    "belge_id": int(bid)})
    for liste in sonuc.values():
        liste.sort(key=lambda t: (t["tarih"] or date.min, t["belge_no"] or ""))
    return sonuc


def _agirlikli(toplam_carpim: Decimal, toplam_tutar: Decimal) -> Decimal | None:
    if toplam_tutar <= 0:
        return None
    return (toplam_carpim / toplam_tutar).quantize(Decimal("0.1"), rounding=ROUND_HALF_UP)


def tedarikci_teslimat_performansi(
    *, bas: date | None = None, bit: date | None = None, cari_id: int | None = None, arama: str = "",
    bugun: date | None = None,
) -> dict[str, Any]:
    """Sipariş teslim tarihi (termin) ile gerçekleşen teslimatların karşılaştırması. Salt okunur."""
    from database.models.alis_siparisi import AlisSiparisi, AlisSiparisiSatiri
    from database.models.cari import Cari

    gun0 = _bugun(bugun)
    with get_session() as session:
        q = (select(AlisSiparisiSatiri, AlisSiparisi, Cari.unvan)
             .join(AlisSiparisi, AlisSiparisi.id == AlisSiparisiSatiri.siparis_id)
             .join(Cari, Cari.id == AlisSiparisi.cari_id)
             .where(AlisSiparisi.durum.notin_(SIPARIS_HARIC)))
        if cari_id:
            q = q.where(AlisSiparisi.cari_id == int(cari_id))
        if bas:
            q = q.where(AlisSiparisi.siparis_tarihi >= bas)
        if bit:
            q = q.where(AlisSiparisi.siparis_tarihi <= bit)
        rows = [r for r in session.execute(q.order_by(AlisSiparisi.siparis_tarihi, AlisSiparisi.id,
                                                      AlisSiparisiSatiri.id))
                if _ara_uygun(arama, r[0].urun_kodu, r[0].urun_adi, r[2], r[1].siparis_no)]
        belgeler = _siparis_teslimat_belgeleri(session, [int(r[0].id) for r in rows])

    satirlar, teslimatlar = [], []
    ozet: dict[int, dict] = {}
    for s, sip, unvan in rows:
        miktar = _d(s.miktar)
        termin = sip.termin_tarihi
        liste = belgeler.get(int(s.id), [])
        teslim = sum((t["miktar"] for t in liste), SIFIR)
        kalan = max(SIFIR, miktar - teslim)
        kumulatif, tam_tarih, zamaninda_m = SIFIR, None, SIFIR
        gec_carpim, gec_miktar, sure_carpim = SIFIR, SIFIR, SIFIR
        for n, t in enumerate(liste, 1):
            onceki = kumulatif
            kumulatif += t["miktar"]
            if tam_tarih is None and kumulatif >= miktar > 0:
                tam_tarih = t["tarih"]
            sayilan = max(SIFIR, min(t["miktar"], miktar - onceki))
            gecikme = (t["tarih"] - termin).days if termin and t["tarih"] else None
            if gecikme is not None and gecikme <= 0:
                zamaninda_m += sayilan
            elif gecikme is not None:
                gec_carpim += t["miktar"] * gecikme
                gec_miktar += t["miktar"]
            if t["tarih"] and sip.siparis_tarihi:
                sure_carpim += t["miktar"] * (t["tarih"] - sip.siparis_tarihi).days
            teslimatlar.append({
                "tedarikci": unvan or "", "cari_id": int(sip.cari_id), "siparis_id": sip.id,
                "siparis_no": sip.siparis_no, "urun_kodu": s.urun_kodu, "urun_adi": s.urun_adi, "birim": s.birim,
                "teslimat_sira": n, "teslimat_turu": t["tur"], "belge_no": t["belge_no"], "belge_id": t["belge_id"],
                "teslim_tarihi": t["tarih"], "termin": termin, "miktar": t["miktar"], "kumulatif": kumulatif,
                "gecikme": gecikme,
                "durum": ("Teslim tarihi yok" if gecikme is None else "Zamanında" if gecikme <= 0 else "Gecikmeli"),
                "kismi": "Kısmi" if kumulatif < miktar or n > 1 else "",
            })
        if termin is None:
            durum, gecikme, degerlendir = "Teslim tarihi yok", None, False
        elif tam_tarih is not None:
            gecikme = (tam_tarih - termin).days
            durum, degerlendir = ("Zamanında tam" if gecikme <= 0 else "Gecikmeli tam"), True
        elif termin < gun0:
            gecikme = (gun0 - termin).days
            durum, degerlendir = ("Gecikmede — kısmi teslim" if teslim > 0 else "Gecikmede — teslim yok"), True
        else:
            gecikme, degerlendir = None, False
            durum = "Kısmi teslim — süresi dolmadı" if teslim > 0 else "Süresi dolmadı"
        zamaninda = degerlendir and tam_tarih is not None and gecikme is not None and gecikme <= 0
        satirlar.append({
            "tedarikci": unvan or "", "cari_id": int(sip.cari_id), "siparis_id": sip.id,
            "siparis_no": sip.siparis_no, "siparis_tarihi": sip.siparis_tarihi, "urun_kodu": s.urun_kodu,
            "urun_adi": s.urun_adi, "birim": s.birim, "siparis_miktari": miktar, "teslim": teslim, "kalan": kalan,
            "fazla": max(SIFIR, teslim - miktar), "termin": termin,
            "ilk_teslim": liste[0]["tarih"] if liste else None, "son_teslim": liste[-1]["tarih"] if liste else None,
            "tam_teslim": tam_tarih, "teslimat_sayisi": len(liste), "gecikme": gecikme, "durum": durum,
            "zamaninda_miktar": zamaninda_m if termin else None,
            "teslim_tarihleri": ", ".join(t["tarih"].strftime("%d.%m.%Y") for t in liste if t["tarih"]),
        })
        o = ozet.setdefault(int(sip.cari_id), {
            "cari_id": int(sip.cari_id), "tedarikci": unvan or "", "siparis_satiri": 0, "degerlendirilen": 0,
            "zamaninda": 0, "gecikmeli": 0, "acik_geciken": 0, "tarihsiz": 0, "suresi_dolmadi": 0,
            "kismi_satir": 0, "teslimat_sayisi": 0, "_deg_miktar": SIFIR, "_zam_miktar": SIFIR,
            "_gec_carpim": SIFIR, "_gec_miktar": SIFIR, "_sure_carpim": SIFIR, "_teslim": SIFIR, "en_cok_gecikme": None,
        })
        o["siparis_satiri"] += 1
        o["teslimat_sayisi"] += len(liste)
        o["_teslim"] += teslim
        o["_sure_carpim"] += sure_carpim
        if len(liste) > 1 or (teslim > 0 and kalan > 0):
            o["kismi_satir"] += 1
        if termin is None:
            o["tarihsiz"] += 1
            continue
        o["_gec_carpim"] += gec_carpim
        o["_gec_miktar"] += gec_miktar
        if not degerlendir:
            o["suresi_dolmadi"] += 1
            continue
        o["degerlendirilen"] += 1
        o["_deg_miktar"] += miktar
        o["_zam_miktar"] += zamaninda_m
        if zamaninda:
            o["zamaninda"] += 1
        else:
            o["gecikmeli"] += 1
            if tam_tarih is None:
                o["acik_geciken"] += 1
        if gecikme is not None and gecikme > 0:
            o["en_cok_gecikme"] = max(o["en_cok_gecikme"] or 0, gecikme)
    tedarikciler = []
    for o in ozet.values():
        o["zamaninda_oran"] = (_d(o["zamaninda"]) / o["degerlendirilen"] * YUZ).quantize(KURUS) \
            if o["degerlendirilen"] else None
        o["miktar_oran"] = (o["_zam_miktar"] / o["_deg_miktar"] * YUZ).quantize(KURUS) if o["_deg_miktar"] > 0 else None
        o["ort_gecikme"] = _agirlikli(o["_gec_carpim"], o["_gec_miktar"])
        o["ort_tedarik_suresi"] = _agirlikli(o["_sure_carpim"], o["_teslim"])
        tedarikciler.append({k: v for k, v in o.items() if not k.startswith("_")})
    tedarikciler.sort(key=lambda r: (r["zamaninda_oran"] is None, r["zamaninda_oran"] or 0))
    return {"tedarikciler": tedarikciler, "satirlar": satirlar, "teslimatlar": teslimatlar, "notlar": [
        "Teslimat: iptal edilmemiş irsaliye satırları + irsaliyesiz doğrudan fatura satırları. İrsaliyeden "
        "kesilen fatura ikinci teslimat sayılmaz. Taslak ve iptal siparişler dahil değildir.",
        "Satır zamanında sayılır: sipariş miktarının tamamı beklenen teslim tarihine (termin) kadar geldiyse. Kısmi "
        "teslimatlar 'Teslimatlar' sekmesinde her biri kendi tarihi ve gecikmesiyle ayrı değerlendirilir.",
        "Oranlara yalnız termini olan ve sonuçlanmış (tamamı gelmiş veya termini geçmiş) satırlar katılır; termini "
        "olmayan ve süresi dolmamış satırlar ayrı sayılır.",
        f"Miktar bazında zamanında oranı: termine kadar gelen miktar / sipariş miktarı. Açık gecikmede gecikme günü "
        f"{gun0:%d.%m.%Y} itibarıyladır. Ortalama gecikme, geciken teslimat miktarıyla ağırlıklıdır.",
        "Miktarlar sipariş satırının biriminde; teslim belgesi aynı satıra bağlı olduğundan aynı birim kabul edilir.",
    ]}


# ---------------------------------------------------------------------------
# 10) Satın alma talepleri takibi
# ---------------------------------------------------------------------------

def satin_alma_talep_takibi(
    *, bas: date | None = None, bit: date | None = None, arama: str = "", gorunum: str = "tumu",
    bugun: date | None = None,
) -> dict[str, Any]:
    """Talep → sipariş → teslimat akışı (satır bazında). Mevcut talep miktar hesabını kullanır; salt okunur.

    gorunum: tumu | acik | onay_bekleyen | tamamlanan.
    """
    from sqlalchemy.orm import selectinload

    from database.access import yetki_zorunlu
    from database.models.satin_alma_talep import SatinAlmaTalep
    from database.satin_alma_talep_service import (
        DURUM_GONDERILDI, DURUM_IPTAL, GORUNUM_TAMAMLANDI, ONAYLI_DURUMLAR, SatinAlmaTalepService,
    )

    yetki_zorunlu("alis_talep_goruntuleme", "alis_talep_duzenleme", "alis_talep_onay", "alis_rapor_goruntuleme",
                  mesaj="Satın alma talep takibi için yetkiniz yok.")
    SatinAlmaTalepService.schema_hazirla()
    gun0 = _bugun(bugun)
    satirlar, baglantilar = [], []
    with get_session() as session:
        q = select(SatinAlmaTalep).options(selectinload(SatinAlmaTalep.satirlar)).where(
            SatinAlmaTalep.durum != DURUM_IPTAL)
        if bas:
            q = q.where(SatinAlmaTalep.talep_tarihi >= bas)
        if bit:
            q = q.where(SatinAlmaTalep.talep_tarihi <= bit)
        talepler = list(session.scalars(q.order_by(SatinAlmaTalep.talep_tarihi, SatinAlmaTalep.id)))
        miktarlar = {t.id: SatinAlmaTalepService._satir_miktarlari(session, t.satirlar, t.durum in ONAYLI_DURUMLAR)
                     for t in talepler}
        sip_satirlari = sorted({ls["siparis_satiri_id"] for m in miktarlar.values() for k in m.values()
                                for ls in k["siparisler"]})
        teslimatlar = _siparis_teslimat_belgeleri(session, sip_satirlari)
    for t in talepler:
        m = miktarlar[t.id]
        gorunen = SatinAlmaTalepService._gorunen_durum(t.durum, m)
        if gorunum == "onay_bekleyen" and t.durum != DURUM_GONDERILDI:
            continue
        if gorunum == "tamamlanan" and gorunen != GORUNUM_TAMAMLANDI:
            continue
        for s in sorted(t.satirlar, key=lambda x: (x.sira or 0, x.id)):
            if not _ara_uygun(arama, s.urun_kodu, s.urun_adi, t.talep_no, t.isteyen_kullanici, t.departman):
                continue
            k = m[int(s.id)]
            acik = k["kalan"] + k["bekleyen_teslim"] if t.durum in ONAYLI_DURUMLAR else _d(s.miktar)
            if gorunum == "acik" and acik <= 0:
                continue
            ihtiyac = s.ihtiyac_tarihi or t.ihtiyac_tarihi
            satirlar.append({
                "talep_id": t.id, "talep_no": t.talep_no, "talep_tarihi": t.talep_tarihi,
                "isteyen": t.isteyen_kullanici or "", "departman": t.departman or "", "depo": s.depo or t.depo or "",
                "oncelik": t.oncelik, "durum": gorunen, "urun_kodu": s.urun_kodu or "MANUEL", "urun_adi": s.urun_adi,
                "birim": s.birim, "talep": k["talep"], "onayli": k["onayli"], "siparis": k["siparis"],
                "teslim": k["teslim"], "iade": k["iade"], "karsilanan": k["net_teslim"], "iptal": k["iptal"],
                "kalan": k["kalan"], "bekleyen_teslim": k["bekleyen_teslim"], "ihtiyac_tarihi": ihtiyac,
                "gecikme": (gun0 - ihtiyac).days if ihtiyac and ihtiyac < gun0 and acik > 0 else None,
                "onay_tarihi": t.onay_tarihi.date() if t.onay_tarihi else None,
                "onay_gun": (t.onay_tarihi.date() - t.talep_tarihi).days if t.onay_tarihi and t.talep_tarihi else None,
                "siparisler": ", ".join(dict.fromkeys(ls["siparis_no"] for ls in k["siparisler"])),
            })
            ortak = {"talep_id": t.id, "talep_no": t.talep_no, "urun_kodu": s.urun_kodu or "MANUEL",
                     "urun_adi": s.urun_adi, "birim": s.birim}
            for ls in k["siparisler"]:
                baglantilar.append({**ortak, "seviye": "Sipariş", "belge_turu": "Alış siparişi",
                                    "belge_no": ls["siparis_no"], "belge_id": ls["siparis_id"],
                                    "tarih": ls.get("termin_tarihi"), "tarih_turu": "Termin", "miktar": ls["miktar"],
                                    "teslim": ls["teslim"], "iade": ls["iade"], "durum": ls["durum"]})
                for tes in teslimatlar.get(int(ls["siparis_satiri_id"]), []):
                    baglantilar.append({**ortak, "seviye": "   └ Teslimat", "belge_turu": "Alış faturası"
                                        if tes["tur"] == "Fatura" else "Alış irsaliyesi",
                                        "belge_no": tes["belge_no"], "belge_id": tes["belge_id"], "tarih": tes["tarih"],
                                        "tarih_turu": "Teslim", "miktar": tes["miktar"], "teslim": None, "iade": None,
                                        "durum": f"Sipariş {ls['siparis_no']}", "_tur": tes["tur"]})
    return {"satirlar": satirlar, "baglantilar": baglantilar, "notlar": [
        "Miktarlar mevcut talep hesabından gelir: siparişe dönüşen = talep–sipariş bağlantıları; karşılanan = teslim "
        "alınan − iade (net teslim); kalan = onaylanan − siparişe dönüşen − iptal (+ yeniden açılan).",
        "Teslimat belgeleri talebe bağlı sipariş satırının irsaliyeleri ve irsaliyesiz doğrudan faturalarıdır. Bir "
        "sipariş satırı birden çok talebe bağlıysa teslimat belgesi her bağlı talepte görünür; miktar payı "
        "'Teslim' sütunundadır.",
        "İptal talepler dahil değildir. Onaylanmamış taleplerde onaylanan ve siparişe dönüşen 0 görünür.",
        "Rapor salt okunurdur; onay, sipariş aktarma ve iptal işlemleri talep ekranındaki mevcut yetkilerle yapılır.",
    ]}


# ---------------------------------------------------------------------------
# 11) Açık alış faturaları ve valör (gün)
# ---------------------------------------------------------------------------

YAS_GRUPLARI = ((1, 7, "1–7"), (8, 30, "8–30"), (31, 60, "31–60"), (61, 90, "61–90"), (91, None, "90+"))


def _yas_grubu(gun: int) -> str:
    for alt, ust, ad in YAS_GRUPLARI:
        if gun >= alt and (ust is None or gun <= ust):
            return ad
    return ""


def acik_alis_faturalari_valor(
    *, rapor_tarihi: date | None = None, cari_id: int | None = None, arama: str = "", durum: str = "tumu",
    para_birimi: str = "",
) -> dict[str, Any]:
    """Rapor tarihindeki açık alış faturaları ve valör günleri (tedarikçi borç raporuyla ortak FIFO hesabı).

    durum: tumu | gecmis | bugun | gelmemis | vadesiz. Salt okunur.
    """
    from database.models.alis_faturasi import AlisFaturasi

    gun0 = _bugun(rapor_tarihi)
    kalemler, avanslar, negatifler = [], [], []
    bagli_uygulanmayan = 0
    with get_session() as session:
        for c in _tedarikciler(session, cari_id):
            if not _ara_uygun(arama, c.cari_kodu, c.unvan):
                continue
            fifo = _fifo_tarihli(session, int(c.id), gun0)
            nolar = {d["borc_belge_no"] for d in fifo["acik"] if d["borc_belge_no"]}
            faturalar = {f.fatura_no: f for f in session.scalars(
                select(AlisFaturasi).where(AlisFaturasi.fatura_no.in_(nolar)))} if nolar else {}
            for d in fifo["acik"]:
                h = d.get("_hareket")
                f = faturalar.get(d["borc_belge_no"])
                acik_tl = _kurus(d["tutar"])
                orijinal = _kurus(h.satis_tutari) if h is not None else acik_tl
                pb = ((f.para_birimi if f else None) or (h.para_birimi if h is not None else None) or "TRY").upper()
                kur = _d(f.kur if f else (h.kur if h is not None else 1)) or Decimal("1")
                fatura_tarihi = d["borc_tarihi"]
                vade = d["borc_vadesi"] if d["vade_tanimli"] else None
                valor = (vade - gun0).days if vade else None
                if valor is None:
                    vdurum, grup = "Vade tanımlanmamış", ""
                elif valor < 0:
                    vdurum, grup = "Vadesi geçmiş", _yas_grubu(-valor)
                elif valor == 0:
                    vdurum, grup = "Bugün vadeli", "Bugün"
                else:
                    vdurum, grup = "Vadesi gelmemiş", _yas_grubu(valor)
                kalemler.append({
                    "cari_id": int(c.id), "cari_kodu": c.cari_kodu, "tedarikci": c.unvan,
                    "belge_turu": "Alış faturası" if f else "Fatura dışı borç (devir/açılış vb.)",
                    "fatura_id": f.id if f else None, "fatura_no": d["borc_belge_no"],
                    "tedarikci_fatura_no": (f.tedarikci_fatura_no if f else "") or "",
                    "fatura_tarihi": fatura_tarihi, "vade_tarihi": vade, "para_birimi": pb,
                    "kur": kur if pb != "TRY" else None,
                    "fatura_tutari": orijinal, "kapatilan": _kurus(orijinal - acik_tl), "acik": acik_tl,
                    "fatura_tutari_doviz": _kurus(orijinal / kur) if pb != "TRY" else None,
                    "acik_doviz": _kurus(acik_tl / kur) if pb != "TRY" else None,
                    "fatura_yasi": (gun0 - fatura_tarihi).days if fatura_tarihi else None,
                    "vade_gunu": (vade - fatura_tarihi).days if vade and fatura_tarihi else None,
                    "valor": valor, "durum": vdurum, "yas_grubu": grup,
                    "kapanis": d.get("kapanis") or ("" if orijinal == acik_tl else YONTEM_FIFO),
                })
            bagli_uygulanmayan += fifo.get("bagli_uygulanmayan", 0)
            for a in fifo["avanslar"]:
                avanslar.append({"cari_id": int(c.id), "tedarikci": c.unvan, "belge_no": a["alacak_belge_no"],
                                 "tarih": a["alacak_tarihi"], "tutar": _kurus(a["tutar"]), "para_birimi": "TRY",
                                 "aciklama": "Faturaya bağlanmamış ödeme / fazla ödeme (avans)"})
            for h in fifo["negatif"]:
                negatifler.append({"cari_id": int(c.id), "tedarikci": c.unvan, "belge_no": h.belge_no,
                                   "tarih": h.satis_tarihi, "tutar": _kurus(h.satis_tutari),
                                   "para_birimi": "TRY", "aciklama": "Negatif cari hareketi (açık kalem hesabına girmez)"})
    if para_birimi:
        kalemler = [k for k in kalemler if k["para_birimi"] == para_birimi.upper()]
    tum_kalemler = list(kalemler)
    if durum == "gecmis":
        kalemler = [k for k in kalemler if k["durum"] == "Vadesi geçmiş"]
    elif durum == "bugun":
        kalemler = [k for k in kalemler if k["durum"] == "Bugün vadeli"]
    elif durum == "gelmemis":
        kalemler = [k for k in kalemler if k["durum"] == "Vadesi gelmemiş"]
    elif durum == "vadesiz":
        kalemler = [k for k in kalemler if k["durum"] == "Vade tanımlanmamış"]
    kalemler.sort(key=lambda k: (k["tedarikci"], k["vade_tarihi"] or date.max, k["fatura_no"] or ""))

    def ozetle(liste: list[dict], **meta) -> dict:
        doviz = meta.get("para_birimi", "TRY") != "TRY"
        alan = "acik_doviz" if doviz else "acik"
        r = {**meta, "kalem_sayisi": len(liste), "acik_tl": _kurus(sum((k["acik"] for k in liste), SIFIR)),
             "acik_doviz": _kurus(sum((k["acik_doviz"] or SIFIR for k in liste), SIFIR)) if doviz else None}
        gruplar = {"gecmis": [k for k in liste if k["durum"] == "Vadesi geçmiş"],
                   "bugun": [k for k in liste if k["durum"] == "Bugün vadeli"],
                   "gelmemis": [k for k in liste if k["durum"] == "Vadesi gelmemiş"],
                   "vadesiz": [k for k in liste if k["durum"] == "Vade tanımlanmamış"]}
        for ad, gl in gruplar.items():
            r[f"{ad}_tutar"] = _kurus(sum((k[alan] or SIFIR for k in gl), SIFIR))
        r["gecmis_gun"] = _agirlikli(sum((k[alan] * -k["valor"] for k in gruplar["gecmis"]), SIFIR),
                                     sum((k[alan] for k in gruplar["gecmis"]), SIFIR))
        r["gelmemis_gun"] = _agirlikli(sum((k[alan] * k["valor"] for k in gruplar["gelmemis"]), SIFIR),
                                       sum((k[alan] for k in gruplar["gelmemis"]), SIFIR))
        vadeli = [k for k in liste if k["valor"] is not None]
        r["valor"] = _agirlikli(sum((k[alan] * k["valor"] for k in vadeli), SIFIR),
                                sum((k[alan] for k in vadeli), SIFIR))
        for alt, _ust, ad in YAS_GRUPLARI:
            r[f"g_{alt}"] = _kurus(sum((k[alan] for k in gruplar["gecmis"] if k["yas_grubu"] == ad), SIFIR))
            r[f"i_{alt}"] = _kurus(sum((k[alan] for k in gruplar["gelmemis"] if k["yas_grubu"] == ad), SIFIR))
        r["acik"] = r["acik_doviz"] if doviz else r["acik_tl"]
        return r

    tedarikci_ozet = []
    anahtarlar: dict[tuple, list] = defaultdict(list)
    for k in tum_kalemler:
        anahtarlar[(k["cari_id"], k["para_birimi"])].append(k)
    for (cid, pb), liste in anahtarlar.items():
        tedarikci_ozet.append(ozetle(liste, cari_id=cid, cari_kodu=liste[0]["cari_kodu"],
                                     tedarikci=liste[0]["tedarikci"], para_birimi=pb))
    tedarikci_ozet.sort(key=lambda r: (r["tedarikci"], r["para_birimi"] != "TRY", r["para_birimi"]))
    pb_toplam = [ozetle([k for k in tum_kalemler if k["para_birimi"] == pb], tedarikci="TOPLAM", para_birimi=pb)
                 for pb in sorted({k["para_birimi"] for k in tum_kalemler}, key=lambda p: (p != "TRY", p))]
    notlar = [
        f"Rapor tarihi {gun0:%d.%m.%Y}. Açık tutar, Tedarikçi Borç ve Vade raporuyla aynı hesaptır: belirli faturaya "
        "bağlanmış ödeme, alış iadesi veya mahsup önce o faturayı kapatır ('Faturaya bağlı'); bağlantısız tutarlar "
        "programın mevcut yöntemiyle en eski açık borçtan düşülür ('FIFO ile hesaplandı'). Rapor kayıtlı "
        "bağlantıları değiştirmez.",
        "Rapor tarihinden sonraki fatura, ödeme, iade, mahsup ve fatura bağlantıları hesaba katılmaz; rapor "
        "tarihinden sonra iptal edilen bağlantılar o tarihte geçerli sayılır.",
        "Fatura yaşı = rapor tarihi − fatura tarihi; anlaşılan vade = vade − fatura tarihi; valör = vade − rapor tarihi "
        "(pozitif: vadeye kalan gün, 0: bugün vadeli, negatif: gecikme).",
        "Ağırlıklı ortalamalar kalan açık tutarla hesaplanır (ilk fatura tutarıyla değil). 'Vade tanımlanmamış' kalemler "
        "açık toplama dahil, gün ortalamalarına dahil değildir; tutarı ayrı sütundadır.",
        "Programda alış faturası için taksit planı alanı yok; her açık cari kalemi kendi vadesi ve kalan tutarıyla "
        "değerlendirilir. Alış faturası cari borcu TL sabit kaydedilir: döviz faturalarda döviz karşılığı belge kuruyla "
        "(TL / belge kuru) gösterilir; her para biriminin toplamı ve ortalaması ayrı hesaplanır, TL ile toplanmaz.",
        "Ödeme sözleri faturayı kapatmaz. Faturadan önceki tarihli, faturaya eşleşmeyen ödemeler avans olarak ayrı "
        "sekmede kalır; negatif cari hareketleri de ayrı gösterilir.",
        "Geçmiş tarih sınırlaması: iptal edilen veya tutarı sonradan değiştirilen faturaların eski durumu kayıtlarda "
        "tutulmadığından, geçmiş tarihli raporda bu faturalar güncel hâliyle (iptal edilmişse hiç) görünür.",
    ]
    if bagli_uygulanmayan:
        notlar.append(f"{bagli_uygulanmayan} fatura bağlantısı rapor tarihinde kaynak ödeme/iade veya hedef fatura "
                      "bulunamadığından uygulanmadı; bu tutarlar FIFO ile değerlendirildi.")
    return {"kalemler": kalemler, "tedarikciler": tedarikci_ozet, "toplamlar": pb_toplam, "avanslar": avanslar,
            "negatifler": negatifler, "rapor_tarihi": gun0, "notlar": notlar}
