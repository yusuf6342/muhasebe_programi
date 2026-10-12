"""Satış yönetici raporları — müşteri/stok kârlılığı, çoklu dönem, performans ve özet.

Bütün satış/kâr tutarları ``SatisKarAnalizService._satirlari_yukle`` satırlarından türetilir; böylece
müşteri, stok, belge ve satır kırılımları aynı filtrede aynı genel toplamı verir. Salt okunurdur.

Kurallar:
  Net satış = KDV hariç, satır iskontoları ve fatura geneli indirim/masraf payı sonrası − iadeler
  Brüt kâr = Net satış − satılan malın maliyeti (maliyeti bilinen satırlar)
  Marj = Kâr / maliyeti bilinen net satış × 100; Maliyet üzerine kâr = Kâr / Maliyet × 100
  Eksik maliyet sıfır sayılmaz; etkilenen satır sayısı ve tutarı ayrıca verilir.
"""

from __future__ import annotations

import calendar
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal, ROUND_HALF_UP
from typing import Any, Callable, Iterable

from sqlalchemy import func, or_, select
from sqlalchemy.orm import selectinload

from database.access import kar_izinli, maliyet_izinli, yetki_zorunlu
from database.database import get_session
from database.satis_kar_analiz_service import (
    MALIYET_YONTEMLERI,
    KarAnalizFiltre,
    SatirAnaliz,
    SatisKarAnalizService,
)
from database.turkce_normalize import turkce_normalize

SIFIR = Decimal("0")
YUZ = Decimal("100")

DONEM_SECENEKLERI: tuple[tuple[str, str], ...] = (
    ("bugun", "Bugün"),
    ("dun", "Dün"),
    ("bu_hafta", "Bu hafta"),
    ("gecen_hafta", "Geçen hafta"),
    ("bu_ay", "Bu ay"),
    ("gecen_ay", "Geçen ay"),
    ("bu_yil", "Bu yıl"),
    ("gecen_yil", "Geçen yıl"),
    ("gecen_yil_ayni", "Geçen yılın aynı dönemi"),
    ("ozel", "Özel"),
)
DONEM_ADI = dict(DONEM_SECENEKLERI)

MALIYET_ALANLARI = ("maliyet", "kar", "marj", "maliyet_uzeri", "ort_maliyet", "birim_maliyet",
                    "toplam_maliyet", "maliyetli_net", "stok_deger", "tahmini_kar", "pay_kar")

TAHSILAT_TURLERI = ("tahsilat", "kk çekimi")


def _d(v) -> Decimal:
    if v is None or v == "":
        return SIFIR
    return v if isinstance(v, Decimal) else Decimal(str(v))


def _q2(v) -> Decimal:
    return _d(v).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def _oran(pay, payda) -> Decimal | None:
    payda = _d(payda)
    if payda == 0:
        return None
    return (_d(pay) / payda * YUZ).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


# ---------------------------------------------------------------------------
# Dönemler
# ---------------------------------------------------------------------------

def _yil_kaydir(t: date, yil: int) -> date:
    try:
        return t.replace(year=t.year + yil)
    except ValueError:  # 29 Şubat
        return t.replace(year=t.year + yil, day=28)


def donem_araligi(kod: str, bugun: date | None = None,
                  referans: tuple[date, date] | None = None) -> tuple[date, date]:
    """Hazır dönem → (başlangıç, bitiş). Devam eden dönemin bitişi dönem sonudur (ör. ay sonu).

    ``gecen_yil_ayni``: referans aralığın (yoksa bu ayın) bir yıl öncesi.
    """
    b = bugun or date.today()
    if kod == "bugun":
        return b, b
    if kod == "dun":
        d = b - timedelta(days=1)
        return d, d
    if kod == "bu_hafta":
        bas = b - timedelta(days=b.weekday())
        return bas, bas + timedelta(days=6)
    if kod == "gecen_hafta":
        bas = b - timedelta(days=b.weekday() + 7)
        return bas, bas + timedelta(days=6)
    if kod == "bu_ay":
        return b.replace(day=1), b.replace(day=calendar.monthrange(b.year, b.month)[1])
    if kod == "gecen_ay":
        son = b.replace(day=1) - timedelta(days=1)
        return son.replace(day=1), son
    if kod == "bu_yil":
        return date(b.year, 1, 1), date(b.year, 12, 31)
    if kod == "gecen_yil":
        return date(b.year - 1, 1, 1), date(b.year - 1, 12, 31)
    if kod == "gecen_yil_ayni":
        bas, bit = referans or donem_araligi("bu_ay", b)
        return _yil_kaydir(bas, -1), _yil_kaydir(bit, -1)
    raise ValueError(f"Bilinmeyen dönem: {kod}")


@dataclass
class Donem:
    ad: str
    bas: date
    bit: date

    def bilgi(self, bugun: date | None = None) -> dict[str, Any]:
        b = bugun or date.today()
        gun = (self.bit - self.bas).days + 1
        if self.bas > b:
            gecen, durum = 0, "Henüz başlamadı"
        elif self.bit > b:
            gecen = (b - self.bas).days + 1
            durum = f"Devam ediyor ({gecen}/{gun} gün)"
        else:
            gecen, durum = gun, "Tamamlandı"
        return {"gun_sayisi": gun, "gecen_gun": gecen, "devam_ediyor": self.bas <= b < self.bit,
                "durum": durum}


def donemleri_hazirla(donemler: Iterable) -> list[Donem]:
    out = []
    for i, d in enumerate(donemler):
        if isinstance(d, Donem):
            dd = d
        else:
            ad, bas, bit = d
            dd = Donem(ad or f"Dönem {i + 1}", bas, bit)
        if dd.bas is None or dd.bit is None:
            raise ValueError(f"{dd.ad}: başlangıç ve bitiş tarihi gerekli.")
        if dd.bit < dd.bas:
            raise ValueError(f"{dd.ad}: bitiş başlangıçtan önce olamaz.")
        out.append(dd)
    if not out:
        raise ValueError("En az bir dönem seçin.")
    return out


def degisim(deger, baz, tur: str = "tutar") -> dict[str, Any]:
    """Temel döneme göre değişim. Baz 0 veya (kâr için) negatif değerde yüzde verilmez."""
    deger, baz = _d(deger), _d(baz)
    fark = deger - baz
    if baz == 0:
        yuzde, aciklama = None, ("Değişmedi" if deger == 0 else "Temel dönem 0 — yalnız tutar farkı")
    elif tur == "kar" and (baz < 0 or deger < 0):
        yuzde, aciklama = None, "Negatif kâr — yüzde yanıltıcı, yalnız tutar farkı"
    else:
        yuzde = (fark / abs(baz) * YUZ).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        aciklama = ""
    return {"fark": fark, "yuzde": yuzde, "aciklama": aciklama}


def marj_puan_farki(marj, baz_marj) -> Decimal | None:
    if marj is None or baz_marj is None:
        return None
    return _d(marj) - _d(baz_marj)


# ---------------------------------------------------------------------------
# Yetki ve satır yükleme
# ---------------------------------------------------------------------------

def _rapor_yetkisi() -> None:
    yetki_zorunlu("satis_goruntuleme", mesaj="Satış raporlarını görüntüleme yetkiniz yok.")


def maliyet_gorunur() -> bool:
    return bool(maliyet_izinli() and kar_izinli())


def _maliyet_gizle(satirlar: list[dict]) -> list[dict]:
    for r in satirlar:
        for k in list(r):
            if k in MALIYET_ALANLARI or k.startswith(("maliyet_", "kar_", "marj_", "fark_kar_", "yuzde_kar_",
                                                      "puan_marj_", "pay_kar")):
                if k not in ("maliyet_yontemi",):
                    r[k] = None
    return satirlar


def kar_filtresi(bas: date, bit: date, filtre: dict | None = None) -> KarAnalizFiltre:
    f = filtre or {}
    yontem = f.get("maliyet_yontemi") or "FIFO"
    if yontem not in MALIYET_YONTEMLERI:
        raise ValueError(f"Desteklenmeyen maliyet yöntemi: {yontem}")
    return KarAnalizFiltre(
        baslangic=bas, bitis=bit, maliyet_yontemi=yontem,
        cari_id=f.get("cari_id") or None, depo=f.get("depo") or None, urun=f.get("urun") or None,
        marka=f.get("marka") or None, musteri_grubu=f.get("musteri_grubu") or None,
        sube_id=f.get("sube_id") or None, kanal=f.get("kanal") or None,
        stok_grup_id=f.get("stok_grup_id") or None, urun_kodu=f.get("urun_kodu") or None,
        dusuk_marj_esigi=_d(f.get("hedef_marj") if f.get("hedef_marj") not in (None, "") else 10),
        iadeleri_dahil=True,
    )


def satirlari_getir(bas: date, bit: date, filtre: dict | None = None) -> list[SatirAnaliz]:
    _rapor_yetkisi()
    return SatisKarAnalizService._satirlari_yukle(kar_filtresi(bas, bit, filtre))


# ---------------------------------------------------------------------------
# Toplama (ortak)
# ---------------------------------------------------------------------------

BOYUTLAR: dict[str, Callable[[SatirAnaliz], tuple[Any, dict]]] = {
    "musteri": lambda s: (s.cari_id or s.cari_kodu or "?",
                          {"cari_id": s.cari_id, "cari_kodu": s.cari_kodu, "unvan": s.cari_unvan,
                           "musteri_grubu": s.musteri_grubu}),
    "urun": lambda s: (s.urun_kodu,
                       {"urun_kodu": s.urun_kodu, "urun_adi": s.urun_adi, "ana_grup": s.ana_grup,
                        "tali_grup": s.tali_grup, "alt_grup": s.alt_grup, "marka": s.marka}),
    "grup": lambda s: (s.ana_grup or "(Grupsuz)", {"grup": s.ana_grup or "(Grupsuz)"}),
    "belge": lambda s: ((s.belge_turu, s.belge_id),
                        {"belge_turu": "Satış" if s.belge_turu == "SATIS" else "İade", "belge_id": s.belge_id,
                         "belge_no": s.belge_no, "tarih": s.tarih, "cari_id": s.cari_id, "unvan": s.cari_unvan,
                         "kanal": s.kanal}),
    "toplam": lambda s: ("TOPLAM", {}),
}


def _yeni_kova(meta: dict) -> dict[str, Any]:
    return {**meta, "satis": SIFIR, "iade": SIFIR, "net": SIFIR, "brut": SIFIR, "iskonto": SIFIR,
            "belge_duzeltme": SIFIR, "maliyet": SIFIR, "kar": SIFIR, "maliyetli_net": SIFIR,
            "eksik_satir": 0, "eksik_net": SIFIR, "satis_miktar": SIFIR, "iade_miktar": SIFIR,
            "_birimler": set(), "_cevrimsiz": {}, "_faturalar": set(), "_iadeler": set(),
            "_musteriler": set(), "_urunler": set(), "son_tarih": None, "kaynaksiz_iade": 0,
            "kaynakli_iade": 0, "satir_sayisi": 0}


_KOVA_ALANLARI = frozenset(_yeni_kova({}))


def topla(satirlar: Iterable[SatirAnaliz], boyut: str) -> dict[Any, dict[str, Any]]:
    anahtar_fn = BOYUTLAR[boyut]
    kovalar: dict[Any, dict[str, Any]] = {}
    for s in satirlar:
        anahtar, meta = anahtar_fn(s)
        k = kovalar.get(anahtar)
        if k is None:
            k = kovalar[anahtar] = _yeni_kova(meta)
        k["satir_sayisi"] += 1
        k["brut"] += s.brut_satis
        k["iskonto"] += s.iskonto
        k["belge_duzeltme"] += s.belge_duzeltme
        k["net"] += s.net_satis
        if s.belge_turu == "SATIS":
            k["satis"] += s.net_satis
            k["_faturalar"].add(s.belge_id)
        else:
            k["iade"] += -s.net_satis
            k["_iadeler"].add(s.belge_id)
            if s.kaynak_bagli:
                k["kaynakli_iade"] += 1
            else:
                k["kaynaksiz_iade"] += 1
        if s.temel_miktar is not None:
            if s.belge_turu == "SATIS":
                k["satis_miktar"] += s.temel_miktar
            else:
                k["iade_miktar"] += -s.temel_miktar
            k["_birimler"].add(s.temel_birim)
        else:
            k["_cevrimsiz"][s.birim] = k["_cevrimsiz"].get(s.birim, SIFIR) + s.miktar
        if s.toplam_maliyet is not None and s.brut_kar is not None:
            k["maliyet"] += s.toplam_maliyet
            k["kar"] += s.brut_kar
            k["maliyetli_net"] += s.net_satis
        else:
            k["eksik_satir"] += 1
            k["eksik_net"] += s.net_satis
        if s.cari_id:
            k["_musteriler"].add(s.cari_id)
        k["_urunler"].add(s.urun_kodu)
        if s.belge_turu == "SATIS" and (k["son_tarih"] is None or s.tarih > k["son_tarih"]):
            k["son_tarih"] = s.tarih
    return kovalar


def _miktar_metni(k: dict) -> str:
    parcalar = []
    if len(k["_birimler"]) == 1 and (k["satis_miktar"] or k["iade_miktar"]):
        parcalar.append(f"{_fmt_miktar(k['satis_miktar'] - k['iade_miktar'])} {next(iter(k['_birimler']))}")
    elif len(k["_birimler"]) > 1:
        parcalar.append("Farklı temel birimler")
    for birim, m in k["_cevrimsiz"].items():
        parcalar.append(f"{_fmt_miktar(m)} {birim} (çevrimsiz)")
    return " + ".join(parcalar)


def _fmt_miktar(m: Decimal) -> str:
    m = _d(m)
    return f"{m:.0f}" if m == m.to_integral_value() else f"{m:.3f}"


def tamamla(k: dict, toplam: dict | None = None) -> dict[str, Any]:
    """Kovadan rapor satırı: oranlar, ortalamalar, paylar ve maliyet durumu."""
    r = {a: v for a, v in k.items() if not a.startswith("_")}
    tek_birim = len(k["_birimler"]) <= 1 and not k["_cevrimsiz"]
    r["net_miktar"] = (k["satis_miktar"] - k["iade_miktar"]) if tek_birim else None
    r["birim"] = next(iter(k["_birimler"]), "") if len(k["_birimler"]) == 1 else ""
    r["miktar_metni"] = _miktar_metni(k)
    r["fatura_sayisi"] = len(k["_faturalar"])
    r["iade_sayisi"] = len(k["_iadeler"])
    r["musteri_sayisi"] = len(k["_musteriler"])
    r["urun_sayisi"] = len(k["_urunler"])
    r["ort_fatura"] = _q2(k["net"] / r["fatura_sayisi"]) if r["fatura_sayisi"] else None
    r["marj"] = _oran(k["kar"], k["maliyetli_net"])
    r["maliyet_uzeri"] = _oran(k["kar"], k["maliyet"])
    nm = r["net_miktar"]
    r["ort_fiyat"] = (k["net"] / nm).quantize(Decimal("0.0001")) if nm else None
    r["ort_maliyet"] = (k["maliyet"] / nm).quantize(Decimal("0.0001")) if nm and not k["eksik_satir"] else None
    r["toplam_iskonto"] = k["iskonto"] - k["belge_duzeltme"]
    r["iskonto_orani"] = _oran(r["toplam_iskonto"], k["brut"])
    r["iade_orani"] = _oran(k["iade"], k["satis"])
    r["maliyet_durumu"] = "Kesin" if not k["eksik_satir"] else f"Kâr eksik ({k['eksik_satir']} satır)"
    for a in ("satis", "iade", "net", "brut", "iskonto", "belge_duzeltme", "maliyet", "kar", "maliyetli_net",
              "eksik_net", "toplam_iskonto"):
        r[a] = _q2(r[a])
    if toplam is not None:
        r["pay_satis"] = _oran(k["net"], toplam["net"])
        r["pay_kar"] = _oran(k["kar"], toplam["kar"]) if _d(toplam["kar"]) > 0 else None
    return r


def satir_detaylari(satirlar: Iterable[SatirAnaliz]) -> list[dict[str, Any]]:
    out = []
    for s in sorted(satirlar, key=lambda x: (x.tarih, x.belge_no, x.satir_id or 0)):
        miktar_abs = abs(s.miktar)
        out.append({
            "belge_turu": "Satış" if s.belge_turu == "SATIS" else "İade", "_belge_turu": s.belge_turu,
            "belge_id": s.belge_id, "satir_id": s.satir_id, "belge_no": s.belge_no, "tarih": s.tarih,
            "cari_id": s.cari_id, "cari_kodu": s.cari_kodu, "unvan": s.cari_unvan, "urun_kodu": s.urun_kodu, "urun_adi": s.urun_adi,
            "miktar": s.miktar, "birim": s.birim, "temel_miktar": s.temel_miktar, "temel_birim": s.temel_birim,
            "brut": s.brut_satis, "iskonto": s.iskonto, "belge_duzeltme": s.belge_duzeltme, "net": s.net_satis,
            "net_fiyat": (abs(s.net_satis) / miktar_abs).quantize(Decimal("0.0001")) if miktar_abs else None,
            "birim_maliyet": ((abs(s.toplam_maliyet) / miktar_abs).quantize(Decimal("0.0001"))
                              if s.toplam_maliyet is not None and miktar_abs else None),
            "toplam_maliyet": s.toplam_maliyet, "kar": s.brut_kar, "marj": s.kar_marji,
            "maliyet_uzeri": s.maliyet_uzeri_kar, "maliyet_durumu": s.maliyet_durumu,
            "maliyet_kaynagi": s.maliyet_kaynagi, "maliyet_yontemi": s.maliyet_yontemi,
            "para_birimi": s.para_birimi, "kur": s.kur if s.para_birimi != "TRY" else None,
            "kur_tarihi": s.kur_tarihi if s.para_birimi != "TRY" else None,
            "kur_kaynagi": s.kur_kaynagi if s.para_birimi != "TRY" else "", "kanal": s.kanal,
            "kaynak_belge_no": s.kaynak_belge_no, "depo": s.depo,
        })
    return out


def satir_maliyet_ayrintisi(belge_turu: str, belge_id: int, satir_id: int) -> dict[str, Any]:
    """Satır maliyetinin stok kaynağı: FIFO'da tüketilen giriş katmanları ve ilgili stok hareketleri.

    İade satırında kaynak satış bağlıysa o satışın katmanları (ters çevrilen maliyet), değilse iade girişi verilir.
    """
    from database.access import maliyet_zorunlu
    from database.models.satis_faturasi import SatisFaturasi, SatisFaturasiSatiri
    from database.models.satis_iade_faturasi import SatisIadeFaturasiSatiri
    from database.models.stok import StokHareketi, StokKarti
    from database.satis_maliyet_motoru import satir_fifo_katmanlari, satis_belge_nolari

    _rapor_yetkisi()
    maliyet_zorunlu()
    with get_session() as s:
        not_ = ""
        if belge_turu == "SATIS":
            satir = s.get(SatisFaturasiSatiri, int(satir_id))
            fatura = s.get(SatisFaturasi, int(satir.fatura_id)) if satir is not None else None
        else:
            iade_satir = s.get(SatisIadeFaturasiSatiri, int(satir_id))
            satir = fatura = None
            if iade_satir is not None and getattr(iade_satir, "kaynak_fatura_satiri_id", None):
                satir = s.get(SatisFaturasiSatiri, int(iade_satir.kaynak_fatura_satiri_id))
                fatura = s.get(SatisFaturasi, int(satir.fatura_id)) if satir is not None else None
                not_ = (f"Bağlı iade: kaynak satış {fatura.fatura_no if fatura else ''} katmanları ters "
                        "çevrilir (iade kendi belge tarihinde düşülür).")
            if satir is None:
                kod = (iade_satir.urun_kodu if iade_satir is not None else "") or ""
                stok = s.scalar(select(StokKarti).where(StokKarti.stok_kodu == kod.strip()))
                iade = getattr(iade_satir, "iade", None) if iade_satir is not None else None
                no = getattr(iade, "iade_no", "") if iade is not None else ""
                hareketler = []
                if stok is not None and no:
                    hareketler = [{"hareket_id": int(h.id), "tarih": h.tarih, "hareket_turu": h.hareket_turu,
                                   "belge_no": h.belge_no, "miktar": _d(h.miktar), "birim_maliyet": _d(h.birim_maliyet)}
                                  for h in s.scalars(select(StokHareketi).where(
                                      StokHareketi.stok_id == stok.id, StokHareketi.belge_no == no)).all()]
                return {"katmanlar": [], "hareketler": hareketler, "stok_id": int(stok.id) if stok else None,
                        "not": "Kaynaksız iade: bağlı satış olmadığı için katman ters çevrilemez; iade girişinin "
                               "maliyeti ve yöntem maliyeti kaynak sütununda gösterilir."}
        if satir is None or fatura is None:
            return {"katmanlar": [], "hareketler": [], "stok_id": None, "not": "Satır bulunamadı."}
        stok = s.scalar(select(StokKarti).where(StokKarti.stok_kodu == (satir.urun_kodu or "").strip()))
        katmanlar, ek = satir_fifo_katmanlari(s, fatura, satir)
        if belge_turu != "SATIS" and katmanlar and _d(satir.miktar) > 0:
            oran = _d(iade_satir.miktar) / _d(satir.miktar)
            katmanlar = [{**k, "miktar": k["miktar"] * oran, "tutar": (k["tutar"] * oran).quantize(Decimal("0.01"))}
                         for k in katmanlar]
            if oran != 1:
                ek = (ek + " " if ek else "") + f"Kısmi iade: iade edilen pay ({oran:.4f}) ters çevrilir."
        not_ = " ".join(x for x in (not_, ek) if x)
        if not katmanlar:
            not_ = (not_ + " " if not_ else "") + "Bu satış için stok çıkış katmanı bulunamadı (maliyet eksik olabilir)."
        return {"katmanlar": katmanlar, "hareketler": [], "stok_id": int(stok.id) if stok else None,
                "belge_nolari": list(satis_belge_nolari(s, fatura, satir)), "kaynak_satir_id": int(satir.id),
                "not": not_}


def fatura_fifo_ayrintisi(fatura_id: int) -> list[dict[str, Any]]:
    """Faturanın her satırı için ayrı FIFO katmanları ve satır FIFO maliyeti (ürün toplamında birleştirilmez)."""
    from database.access import maliyet_zorunlu
    from database.models.satis_faturasi import SatisFaturasi
    from database.satis_maliyet_motoru import satir_fifo_katmanlari

    _rapor_yetkisi()
    maliyet_zorunlu()
    out = []
    with get_session() as s:
        fatura = s.get(SatisFaturasi, int(fatura_id))
        if fatura is None:
            return []
        for satir in sorted(fatura.satirlar, key=lambda x: x.id):
            katmanlar, not_ = satir_fifo_katmanlari(s, fatura, satir)
            out.append({"satir_id": int(satir.id), "urun_kodu": satir.urun_kodu, "urun_adi": satir.urun_adi,
                        "miktar": _d(satir.miktar), "birim": satir.birim, "katmanlar": katmanlar,
                        "fifo_maliyet": sum((k["tutar"] for k in katmanlar), SIFIR), "not": not_})
    return out


def yontem_notu(yontem: str) -> str:
    from database.satis_maliyet_motoru import DONEMSEL, HAREKETLI, KARSILASTIRMA_AMACLI, SON_ALIS, STANDART

    aciklama = {
        "FIFO": "satış anında stok/depo hareket sırasıyla tüketilen giriş katmanlarının maliyeti (irsaliyeli "
                "satışta irsaliye çıkış maliyeti; fatura ile irsaliye maliyeti bir kez sayılır)",
        HAREKETLI: "firma stok hareket geçmişinde satış anındaki hareketli ağırlıklı ortalama; sonraki alışlar "
                   "etkilemez",
        DONEMSEL: "satış ayının (açılış stoku + ay içi girişler) ağırlıklı ortalaması",
        SON_ALIS: "satış tarihine kadarki son maliyetli alış girişi",
        STANDART: "satış tarihinde geçerli tanımlı standart maliyet",
    }.get(yontem, "satıra kaydedilen maliyet alanı")
    ek = " — KARŞILAŞTIRMA AMAÇLI, muhasebe maliyeti değildir" if yontem in KARSILASTIRMA_AMACLI else ""
    return (f"Maliyet yöntemi: {yontem}{ek} — {aciklama}. Geçmiş satışlar bugünkü alış fiyatıyla yeniden "
            "maliyetlendirilmez; yöntem seçimi yalnız rapor hesabını değiştirir, kayıtları değiştirmez.")


def _ortak_notlar(filtre: dict | None, satirlar_eksik: int, eksik_net: Decimal) -> list[str]:
    f = filtre or {}
    notlar = [
        yontem_notu(f.get("maliyet_yontemi") or "FIFO"),
        "Tutarlar TL ve KDV hariçtir; dövizli belgeler belge kuruyla (kur tarihi/kaynağı satır ayrıntısında) "
        "çevrilmiştir, güncel kurla yeniden değerlenmez.",
        "Yalnız onaylı ve iptal edilmemiş faturalar sayılır; taslak ve iptal belgeler hariçtir. Hızlı satış "
        "kendi faturasıyla bir kez sayılır.",
        "Marj = Kâr / maliyeti bilinen net satış; Maliyet üzerine kâr = Kâr / Maliyet ayrı bir orandır.",
    ]
    if satirlar_eksik:
        notlar.append(f"Kâr eksik: {satirlar_eksik} satırda maliyet bulunamadı ({_q2(eksik_net)} TL net satış); "
                      "bu satırlar kâra ve marja katılmadı, sıfır maliyet sayılmadı.")
    return notlar


# ---------------------------------------------------------------------------
# 1–3) Müşteri / stok kârlılığı ve çoklu dönem karşılaştırması
# ---------------------------------------------------------------------------

KARS_ALANLARI = (("satis", "net", "tutar"), ("miktar", "net_miktar", "tutar"), ("kar", "kar", "kar"))


def karlilik_raporu(boyut: str, donemler: Iterable, temel: int = 0, filtre: dict | None = None,
                    bugun: date | None = None, sadece: str | None = None) -> dict[str, Any]:
    """Müşteri (``boyut="musteri"``) veya stok (``"urun"``) kârlılığı; sınırsız bağımsız dönem.

    Her dönem kendi satırlarıyla ayrı hesaplanır (çakışan dönemler birleştirilmez). İlk dönem ana
    dönemdir; ``temel`` karşılaştırmanın yapıldığı dönem indeksidir. ``sadece``: None | yeni | duran.
    """
    if boyut not in ("musteri", "urun"):
        raise ValueError("Boyut müşteri veya ürün olmalı.")
    b = bugun or date.today()
    ds = donemleri_hazirla(donemler)
    temel = min(max(int(temel or 0), 0), len(ds) - 1)
    maliyet_ok = maliyet_gorunur()

    kovalar_d: list[dict] = []
    toplamlar: list[dict] = []
    eksik_toplam, eksik_net = 0, SIFIR
    for d in ds:
        satirlar = satirlari_getir(d.bas, d.bit, filtre)
        kovalar_d.append(topla(satirlar, boyut))
        t = topla(satirlar, "toplam").get("TOPLAM") or _yeni_kova({})
        toplamlar.append(t)
        if d is ds[0]:
            eksik_toplam, eksik_net = t["eksik_satir"], t["eksik_net"]

    anahtarlar: list = []
    gorulen = set()
    for kov in kovalar_d:
        for a in kov:
            if a not in gorulen:
                gorulen.add(a)
                anahtarlar.append(a)

    satirlar_out = []
    for a in anahtarlar:
        ana_k = kovalar_d[0].get(a)
        if ana_k is None:
            meta_kaynak = next(kov[a] for kov in kovalar_d if a in kov)
            ana_k = _yeni_kova({m: v for m, v in meta_kaynak.items() if m not in _KOVA_ALANLARI})
        ana = tamamla(ana_k, toplamlar[0])
        r = dict(ana)
        var = [a in kov for kov in kovalar_d]
        r["donem_var"] = var
        if not var[temel] and any(v for i, v in enumerate(var) if i != temel):
            r["durum"] = "Yeni satış"
        elif var[temel] and not any(v for i, v in enumerate(var) if i != temel):
            r["durum"] = "Satışı durdu"
        elif not all(var):
            r["durum"] = "Yalnız: " + ", ".join(ds[i].ad for i, v in enumerate(var) if v)
        else:
            r["durum"] = ""
        tamamlanmis = [tamamla(kov[a]) if a in kov else None for kov in kovalar_d]
        baz = tamamlanmis[temel]
        for i, t in enumerate(tamamlanmis):
            r[f"satis_{i}"] = t["net"] if t else SIFIR
            r[f"miktar_{i}"] = t["net_miktar"] if t else SIFIR
            r[f"maliyet_{i}"] = t["maliyet"] if t else SIFIR
            r[f"kar_{i}"] = t["kar"] if t else SIFIR
            r[f"marj_{i}"] = t["marj"] if t else None
            if i == temel:
                continue
            aciklamalar = []
            for ad, alan, tur in KARS_ALANLARI:
                deger = t[alan] if t else SIFIR
                baz_deger = baz[alan] if baz else SIFIR
                if deger is None or baz_deger is None:
                    r[f"fark_{ad}_{i}"] = r[f"yuzde_{ad}_{i}"] = None
                    if ad == "miktar":
                        aciklamalar.append("Miktar: birimler çevrilemedi")
                    continue
                dg = degisim(deger, baz_deger, tur)
                r[f"fark_{ad}_{i}"] = dg["fark"]
                r[f"yuzde_{ad}_{i}"] = dg["yuzde"]
                if dg["aciklama"] and dg["aciklama"] != "Değişmedi":
                    aciklamalar.append(f"{ad.capitalize()}: {dg['aciklama']}")
            r[f"puan_marj_{i}"] = marj_puan_farki(t["marj"] if t else None, baz["marj"] if baz else None)
            r[f"aciklama_{i}"] = "; ".join(dict.fromkeys(aciklamalar))
        satirlar_out.append(r)

    if sadece == "yeni":
        satirlar_out = [r for r in satirlar_out if r["durum"] == "Yeni satış"]
    elif sadece == "duran":
        satirlar_out = [r for r in satirlar_out if r["durum"] == "Satışı durdu"]
    satirlar_out.sort(key=lambda r: r["net"], reverse=True)

    donem_satirlari = []
    baz_t = tamamla(toplamlar[temel])
    for i, (d, t) in enumerate(zip(ds, toplamlar)):
        tt = tamamla(t)
        bilgi = d.bilgi(b)
        gecen = bilgi["gecen_gun"] or 0
        r = {"donem": d.ad, "bas": d.bas, "bit": d.bit, **bilgi, "temel": "Temel" if i == temel else "",
             "satis": tt["satis"], "iade": tt["iade"], "net": tt["net"], "net_miktar": tt["net_miktar"],
             "miktar_metni": tt["miktar_metni"], "maliyet": tt["maliyet"], "kar": tt["kar"], "marj": tt["marj"],
             "maliyet_uzeri": tt["maliyet_uzeri"], "fatura_sayisi": tt["fatura_sayisi"],
             "eksik_satir": tt["eksik_satir"], "eksik_net": tt["eksik_net"],
             "gunluk_net": _q2(tt["net"] / gecen) if gecen else None,
             "gunluk_kar": _q2(tt["kar"] / gecen) if gecen else None}
        if i != temel:
            for ad, alan, tur in KARS_ALANLARI:
                if tt[alan] is None or baz_t[alan] is None:
                    r[f"fark_{ad}"] = r[f"yuzde_{ad}"] = None
                    continue
                dg = degisim(tt[alan], baz_t[alan], tur)
                r[f"fark_{ad}"], r[f"yuzde_{ad}"] = dg["fark"], dg["yuzde"]
                if dg["aciklama"] and dg["aciklama"] != "Değişmedi":
                    r["aciklama"] = (r.get("aciklama", "") + f" {ad.capitalize()}: {dg['aciklama']}.").strip()
            r["puan_marj"] = marj_puan_farki(tt["marj"], baz_t["marj"])
        donem_satirlari.append(r)

    tek = [r for r in satirlar_out if r["durum"]]
    notlar = _ortak_notlar(filtre, eksik_toplam, eksik_net)
    notlar.append("Her dönem bağımsız hesaplanır; çakışan dönemler birleştirilmez ve toplamları toplanmaz. "
                  f"Değişimler temel döneme ({ds[temel].ad}) göredir; marj farkı yüzde puandır.")
    notlar.append("Temel dönem değeri 0 ise veya kâr negatifse yüzde değişim gösterilmez; tutar farkı ve "
                  "açıklama verilir. Devam eden dönemlerde günlük ortalama geçen gün sayısına göredir.")
    if boyut == "urun":
        notlar.append("Miktarlar stok kartının temel birimine çevrilir; geçerli çevrimi olmayan birimler "
                      "'çevrimsiz' olarak ayrı gösterilir ve toplam miktara katılmaz.")
    sonuc = {"satirlar": satirlar_out, "donemler": donem_satirlari, "tek_donem": tek, "notlar": notlar,
             "donem_listesi": ds, "temel": temel, "boyut": boyut,
             "toplam": tamamla(toplamlar[0]), "maliyet_gorunur": maliyet_ok}
    if not maliyet_ok:
        _maliyet_gizle(satirlar_out)
        _maliyet_gizle(donem_satirlari)
        _maliyet_gizle(tek)
        sonuc["notlar"].append("Maliyet/kâr görme yetkiniz olmadığından maliyet, kâr ve marj sütunları boş.")
    return sonuc


def karlilik_detay(boyut: str, anahtar, bas: date, bit: date, filtre: dict | None = None,
                   ikinci: Any = None) -> dict[str, Any]:
    """Ayrıntı inişi: müşteri → ürün → satır veya ürün → müşteri → satır."""
    f = dict(filtre or {})
    if boyut == "musteri":
        f["cari_id"] = anahtar
        if ikinci:
            f["urun_kodu"] = ikinci
        alt = "urun"
    elif boyut == "urun":
        f["urun_kodu"] = anahtar
        if ikinci:
            f["cari_id"] = ikinci
        alt = "musteri"
    else:
        raise ValueError("Boyut müşteri veya ürün olmalı.")
    satirlar = satirlari_getir(bas, bit, f)
    toplam = topla(satirlar, "toplam").get("TOPLAM") or _yeni_kova({})
    kirilim = [tamamla(k, toplam) for k in topla(satirlar, alt).values()]
    kirilim.sort(key=lambda r: r["net"], reverse=True)
    belgeler = [tamamla(k) for k in topla(satirlar, "belge").values()]
    belgeler.sort(key=lambda r: (r["tarih"], r["belge_no"]))
    sonuc = {"kirilim": kirilim, "belgeler": belgeler, "satirlar": satir_detaylari(satirlar),
             "toplam": tamamla(toplam), "notlar": _ortak_notlar(f, toplam["eksik_satir"], toplam["eksik_net"])}
    if not maliyet_gorunur():
        for liste in (sonuc["kirilim"], sonuc["belgeler"], sonuc["satirlar"]):
            _maliyet_gizle(liste)
        _maliyet_gizle([sonuc["toplam"]])
    return sonuc


# ---------------------------------------------------------------------------
# 5) Düşük marjlı / zararına satışlar
# ---------------------------------------------------------------------------

def dusuk_marjli_satislar(bas: date, bit: date, filtre: dict | None = None, hedef_marj=10,
                          tur: str = "tumu") -> dict[str, Any]:
    """tur: tumu | zararina | hedef_alti | eksik. Ürün/grup hedef marjı alanı yoktur; tek hedef kullanılır."""
    from database.access import kar_zorunlu, maliyet_zorunlu

    maliyet_zorunlu()
    kar_zorunlu()
    hedef = _d(hedef_marj)
    out = []
    for r in satir_detaylari(s for s in satirlari_getir(bas, bit, filtre) if s.belge_turu == "SATIS"):
        if r["kar"] is None:
            durum = "Maliyeti eksik"
        elif r["kar"] < 0:
            durum = "Zararına"
        elif r["marj"] is not None and r["marj"] < hedef:
            durum = "Hedef altı"
        else:
            continue
        if tur == "zararina" and durum != "Zararına":
            continue
        if tur == "hedef_alti" and durum != "Hedef altı":
            continue
        if tur == "eksik" and durum != "Maliyeti eksik":
            continue
        r["durum"] = durum
        r["hedef_marj"] = hedef
        r["hedef_fark"] = (r["marj"] - hedef) if r["marj"] is not None else None
        out.append(r)
    out.sort(key=lambda r: (r["kar"] is None, r["kar"] if r["kar"] is not None else 0))
    notlar = [f"Hedef marj %{hedef}. Programda ürün veya stok grubu bazında hedef marj alanı bulunmadığından "
              "tek hedef uygulanır.",
              "Net fiyat ve birim maliyet belge birimi başınadır; maliyet satış anında kaydedilen değerdir.",
              "Maliyeti eksik satırlar kâr hesabına katılmaz; ayrı listelenir."]
    return {"satirlar": out, "notlar": notlar,
            "ozet": {"zararina": sum(1 for r in out if r["durum"] == "Zararına"),
                     "hedef_alti": sum(1 for r in out if r["durum"] == "Hedef altı"),
                     "eksik": sum(1 for r in out if r["durum"] == "Maliyeti eksik"),
                     "zarar_toplam": _q2(sum((r["kar"] for r in out if r["durum"] == "Zararına"), SIFIR))}}


# ---------------------------------------------------------------------------
# 6) Müşteri satış ve tahsilat performansı
# ---------------------------------------------------------------------------

def _tahsilat_mi(islem) -> bool:
    tur = (islem.islem_turu or "").casefold()
    return any(t in tur for t in TAHSILAT_TURLERI)


def _agirlikli_gun(dilimler: list[dict], alan: str = "gun") -> Decimal | None:
    toplam = sum((_d(d["tutar"]) for d in dilimler), SIFIR)
    if toplam <= 0:
        return None
    return (sum((_d(d["tutar"]) * _d(d[alan]) for d in dilimler), SIFIR) / toplam).quantize(Decimal("0.1"))


def _cari_vade_durumu(session, cari_id: int, bas: date | None, bit: date | None, bugun: date) -> dict:
    from database.cari_service import CariService

    _tam, acik_borc, dilimler, acik_alacak = CariService._fifo_valor_dilimleri(
        session, cari_id, "Müşteri", referans=bugun)
    acik = sum((_d(d["tutar"]) for d in acik_borc), SIFIR)
    vadesi_gecmis = [d for d in acik_borc if d.get("borc_vadesi") and d["borc_vadesi"] < bugun]
    donem_dilim = [d for d in dilimler if d.get("odeme_tarihi")
                   and (bas is None or d["odeme_tarihi"] >= bas) and (bit is None or d["odeme_tarihi"] <= bit)]
    for d in donem_dilim:
        d["fatura_gun"] = (d["odeme_tarihi"] - d["borc_tarihi"]).days if d.get("borc_tarihi") else 0
    return {
        "acik_alacak": _q2(acik),
        "vadesi_gecmis": _q2(sum((_d(d["tutar"]) for d in vadesi_gecmis), SIFIR)),
        "gecikme_gun": _agirlikli_gun(vadesi_gecmis),
        "gerceklesen_vade_gun": _agirlikli_gun(donem_dilim),
        "gerceklesen_tahsil_gun": _agirlikli_gun(donem_dilim, "fatura_gun"),
        "eslesen_tahsilat": _q2(sum((_d(d["tutar"]) for d in donem_dilim), SIFIR)),
        "eslesmemis_alacak": _q2(sum((_d(d["tutar"]) for d in acik_alacak), SIFIR)),
    }


def tahsilat_performansi(bas: date, bit: date, filtre: dict | None = None, bugun: date | None = None,
                         acik_bakiyeliler: bool = False) -> dict[str, Any]:
    from database.models.cari import Cari, CariIslem
    from database.odeme_sozu_service import OdemeSozuService

    b = bugun or date.today()
    f = filtre or {}
    satirlar = satirlari_getir(bas, bit, f)
    kovalar = topla(satirlar, "musteri")
    maliyet_ok = maliyet_gorunur()
    out = []
    with get_session() as session:
        tq = select(CariIslem).where(CariIslem.tarih >= bas, CariIslem.tarih <= bit, CariIslem.alacak > 0)
        if f.get("cari_id"):
            tq = tq.where(CariIslem.cari_id == int(f["cari_id"]))
        tahsilat: dict[int, Decimal] = {}
        for islem in session.scalars(tq).all():
            if _tahsilat_mi(islem):
                tahsilat[int(islem.cari_id)] = tahsilat.get(int(islem.cari_id), SIFIR) + _d(islem.alacak)
        cari_idler = {k for k in kovalar if isinstance(k, int)} | set(tahsilat)
        if acik_bakiyeliler and not f.get("cari_id"):
            from database.cari_service import CariService

            for oz in CariService.listele(cari_turu="Müşteri", hizli=True):
                if _d(oz.get("bakiye")) > 0:
                    cari_idler.add(int(oz["cari"].id))
        if f.get("cari_id"):
            cari_idler &= {int(f["cari_id"])}
        cariler = {c.id: c for c in session.scalars(select(Cari).where(Cari.id.in_(cari_idler))).all()} \
            if cari_idler else {}
        for cid in cari_idler:
            cari = cariler.get(cid)
            if cari is None or "tedarik" in (cari.cari_turu or "").casefold():
                continue
            k = kovalar.get(cid)
            t = tamamla(k) if k else None
            vade = _cari_vade_durumu(session, cid, bas, bit, b)
            out.append({"cari_id": cid, "cari_kodu": cari.cari_kodu, "unvan": cari.unvan,
                        "net": t["net"] if t else SIFIR, "kar": t["kar"] if t else None,
                        "marj": t["marj"] if t else None, "tahsilat": _q2(tahsilat.get(cid, SIFIR)), **vade})
    sozler: dict[int, dict] = {}
    for s in OdemeSozuService.liste(yon="ALINAN", sadece_acik=True, bugun=b):
        if s.get("cari_id") is None:
            continue
        o = sozler.setdefault(int(s["cari_id"]), {"soz": SIFIR, "soz_geciken": SIFIR})
        kalan = _d(s.get("kalan"))
        o["soz"] += kalan
        if s.get("vade_tarihi") and s["vade_tarihi"] < b:
            o["soz_geciken"] += kalan
    for r in out:
        o = sozler.get(r["cari_id"], {})
        r["soz"] = _q2(o.get("soz", SIFIR))
        r["soz_geciken"] = _q2(o.get("soz_geciken", SIFIR))
        r["tahsilat_orani"] = _oran(r["tahsilat"], r["net"]) if r["net"] > 0 else None
    out.sort(key=lambda r: r["vadesi_gecmis"], reverse=True)
    if not maliyet_ok:
        for r in out:
            r["kar"] = r["marj"] = None
    notlar = [
        "Net satış ve kâr dönem hareketidir; tahsilat dönem içindeki tahsilat/kredi kartı çekimi kayıtlarıdır. "
        "Dönemde alınan bir tahsilat önceki faturalara ait olabilir; satış ile karıştırılmaz.",
        f"Açık ve vadesi geçmiş alacak {b:%d.%m.%Y} itibarıyla bakiyedir (mevcut FIFO vade eşleştirmesi).",
        "Gerçekleşen vade gecikmesi: dönemde faturaya eşleşen tahsilat dilimlerinin (kısmi tahsilatlar kendi "
        "tutar ve tarihiyle) tutar ağırlıklı (tahsilat − vade) günü; tahsil süresi (tahsilat − fatura) günüdür.",
        "Eşleşmemiş alacak: hiçbir açık faturaya bağlanamayan tahsilat/avans tutarıdır, ayrı gösterilir.",
        "Ödeme sözleri tahsilat değildir; açık söz ve vadesi geçmiş söz ayrı sütundadır.",
    ]
    return {"satirlar": out, "notlar": notlar,
            "toplam": {a: _q2(sum((_d(r[a]) for r in out), SIFIR))
                       for a in ("net", "tahsilat", "acik_alacak", "vadesi_gecmis", "eslesmemis_alacak", "soz",
                                 "soz_geciken")}}


# ---------------------------------------------------------------------------
# 7) Satışı azalan ve alışverişi duran müşteriler
# ---------------------------------------------------------------------------

def son_satis_tarihleri(bugun: date, boyut: str = "musteri") -> dict[Any, date]:
    from database.models.satis_faturasi import SatisFaturasi, SatisFaturasiSatiri

    with get_session() as session:
        kosul = (SatisFaturasi.durum != "İPTAL", SatisFaturasi.onaylandi.is_(True),
                 or_(SatisFaturasi.is_deleted.is_(False), SatisFaturasi.is_deleted.is_(None)),
                 SatisFaturasi.fatura_tarihi <= bugun)
        if boyut == "musteri":
            q = select(SatisFaturasi.cari_id, func.max(SatisFaturasi.fatura_tarihi)).where(*kosul) \
                .group_by(SatisFaturasi.cari_id)
        else:
            q = select(SatisFaturasiSatiri.urun_kodu, func.max(SatisFaturasi.fatura_tarihi)) \
                .join(SatisFaturasi, SatisFaturasi.id == SatisFaturasiSatiri.fatura_id).where(*kosul) \
                .group_by(SatisFaturasiSatiri.urun_kodu)
        return {k: v for k, v in session.execute(q).all() if k is not None}


def azalan_musteriler(donem: tuple[date, date], karsilastirma: tuple[date, date], filtre: dict | None = None,
                      inaktif_gun: int = 90, dusus_esigi=20, bugun: date | None = None,
                      tur: str = "tumu") -> dict[str, Any]:
    """tur: tumu | azalan | duran | donemde_yok."""
    b = bugun or date.today()
    esik = _d(dusus_esigi)
    d1 = topla(satirlari_getir(donem[0], donem[1], filtre), "musteri")
    d2 = topla(satirlari_getir(karsilastirma[0], karsilastirma[1], filtre), "musteri")
    son = son_satis_tarihleri(b)
    out = []
    for a in list(d2) + [x for x in d1 if x not in d2]:
        k1, k2 = d1.get(a), d2.get(a)
        meta = k1 or k2
        net1 = _q2(k1["net"]) if k1 else SIFIR
        net2 = _q2(k2["net"]) if k2 else SIFIR
        dg = degisim(net1, net2)
        son_t = son.get(a) if isinstance(a, int) else None
        gun = (b - son_t).days if son_t else None
        etiketler = []
        if gun is not None and gun >= int(inaktif_gun):
            etiketler.append(f"Alışverişi durdu ({gun} gün)")
        if net2 > 0 and net1 <= 0:
            etiketler.append("Dönemde satış yok")
        elif dg["yuzde"] is not None and dg["yuzde"] <= -esik:
            etiketler.append(f"Satışı azaldı (%{dg['yuzde']})")
        if not etiketler:
            continue
        if tur == "azalan" and not any(e.startswith("Satışı azaldı") for e in etiketler):
            continue
        if tur == "duran" and not any(e.startswith("Alışverişi durdu") for e in etiketler):
            continue
        if tur == "donemde_yok" and "Dönemde satış yok" not in etiketler:
            continue
        out.append({"cari_id": meta["cari_id"], "cari_kodu": meta["cari_kodu"], "unvan": meta["unvan"],
                    "net_donem": net1, "net_kars": net2, "fark": dg["fark"], "yuzde": dg["yuzde"],
                    "aciklama": dg["aciklama"], "son_satis": son_t, "gun": gun, "durum": "; ".join(etiketler)})
    out.sort(key=lambda r: r["fark"])
    notlar = [f"Dönem {donem[0]:%d.%m.%Y}–{donem[1]:%d.%m.%Y}, karşılaştırma "
              f"{karsilastirma[0]:%d.%m.%Y}–{karsilastirma[1]:%d.%m.%Y}. Sezonluk karşılaştırma için "
              "'Geçen yılın aynı dönemi' seçilebilir.",
              f"Alışverişi durdu: son satıştan bu yana {inaktif_gun} gün ve üzeri. Satışı azaldı: net satış "
              f"%{esik} ve üzeri düştü (iadeler düşülmüş net satış)."]
    return {"satirlar": out, "notlar": notlar}


# ---------------------------------------------------------------------------
# 8) Ürün satış hızı ve stokta bekleyen sermaye
# ---------------------------------------------------------------------------

def urun_satis_hizi(bas: date, bit: date, filtre: dict | None = None, bugun: date | None = None,
                    yavas_gun: int = 180, tur: str = "tumu") -> dict[str, Any]:
    """tur: tumu | satis_yok | yavas | stoksuz_satan."""
    from database.models.stok import Depo, StokKarti
    from database.stok_service import StokService

    b = bugun or date.today()
    f = filtre or {}
    gecen = max(1, (min(bit, b) - bas).days + 1)
    kovalar = topla(satirlari_getir(bas, bit, f), "urun")
    son = son_satis_tarihleri(b, "urun")
    maliyet_ok = maliyet_gorunur()
    depo_f = turkce_normalize((f.get("depo") or "").strip())
    arama = turkce_normalize((f.get("urun") or "").strip())
    out = []
    with get_session() as session:
        depolar = {d.id: d.ad for d in session.scalars(select(Depo)).all()}
        envanter = StokService.fifo_envanter_degerleri(session)
        stok_m: dict[int, Decimal] = {}
        stok_v: dict[int, Decimal] = {}
        for (sid, did), v in envanter.items():
            if depo_f and depo_f not in turkce_normalize(depolar.get(did, "")):
                continue
            stok_m[sid] = stok_m.get(sid, SIFIR) + _d(v["miktar"])
            stok_v[sid] = stok_v.get(sid, SIFIR) + _d(v["deger"])
        grup_ad = SatisKarAnalizService._grup_adlari(session)
        kartlar = session.scalars(select(StokKarti).where(
            StokKarti.aktif.is_(True), or_(StokKarti.is_deleted.is_(False), StokKarti.is_deleted.is_(None)))).all()
        for kart in kartlar:
            if "hizmet" in (kart.kart_turu or "").casefold():
                continue
            if arama and arama not in turkce_normalize(kart.stok_kodu) and arama not in turkce_normalize(
                    kart.stok_adi or ""):
                continue
            if f.get("stok_grup_id") and int(f["stok_grup_id"]) not in {kart.ana_grup_id, kart.tali_grup_id,
                                                                       kart.alt_grup_id}:
                continue
            k = kovalar.get(kart.stok_kodu)
            t = tamamla(k) if k else None
            mevcut = stok_m.get(kart.id, SIFIR)
            net_m = (t["net_miktar"] if t else SIFIR)
            satis_var = t is not None and (net_m is None or net_m > 0)
            hiz = (net_m / gecen) if net_m and net_m > 0 else None
            yeterlilik = int(mevcut / hiz) if hiz and mevcut > 0 else None
            if t is not None and net_m is None:
                aciklama = "Birim çevrimi yok — hız hesaplanamadı"
            elif not satis_var:
                aciklama = "Dönemde satış yok — yeterlilik hesaplanamaz" if mevcut > 0 else ""
            elif mevcut <= 0:
                aciklama = "Stokta yok ama satılıyor"
            else:
                aciklama = ""
            r = {"urun_kodu": kart.stok_kodu, "urun_adi": kart.stok_adi, "birim": kart.birim or "Adet",
                 **SatisKarAnalizService._stok_meta(kart, grup_ad), "mevcut": mevcut,
                 "stok_deger": _q2(stok_v.get(kart.id, SIFIR)),
                 "satis_miktar": net_m, "net": t["net"] if t else SIFIR, "kar": t["kar"] if t else None,
                 "marj": t["marj"] if t else None,
                 "gunluk_hiz": hiz.quantize(Decimal("0.001")) if hiz else None, "yeterlilik_gun": yeterlilik,
                 "son_satis": son.get(kart.stok_kodu),
                 "son_satis_gun": (b - son[kart.stok_kodu]).days if son.get(kart.stok_kodu) else None,
                 "aciklama": aciklama}
            if tur == "satis_yok" and not (mevcut > 0 and not satis_var):
                continue
            if tur == "yavas" and not (yeterlilik is not None and yeterlilik > int(yavas_gun)):
                continue
            if tur == "stoksuz_satan" and not (mevcut <= 0 and satis_var):
                continue
            if tur == "tumu" and mevcut == 0 and not t:
                continue
            out.append(r)
    out.sort(key=lambda r: r["stok_deger"], reverse=True)
    if not maliyet_ok:
        _maliyet_gizle(out)
    notlar = [f"Satış hızı = dönem net satış miktarı (iadeler düşülmüş, temel birim) / {gecen} gün "
              "(devam eden dönemde bugüne kadar geçen gün).",
              "Yeterlilik günü = mevcut stok / günlük hız; satış hızı 0 ise hesaplanmaz.",
              "Mevcut stok ve stok maliyet değeri ortak FIFO envanter hesabından (açık FIFO katmanları) gelir; "
              "dönem kârı ayrı sütundadır, stoktaki malın değeriyle karıştırılmaz.",
              "Programda ayrı stok rezervasyonu tutulmuyor; mevcut stok fiziksel stoktur."]
    return {"satirlar": out, "notlar": notlar,
            "toplam": {"stok_deger": _q2(sum((_d(r["stok_deger"]) for r in out), SIFIR)) if maliyet_ok else None}}


# ---------------------------------------------------------------------------
# 9) İskonto ve iade analizi
# ---------------------------------------------------------------------------

def iskonto_iade_analizi(bas: date, bit: date, filtre: dict | None = None, boyut: str = "musteri") -> dict:
    if boyut not in ("musteri", "urun", "grup"):
        raise ValueError("Kırılım müşteri, ürün veya grup olmalı.")
    satirlar = satirlari_getir(bas, bit, filtre)
    toplam = topla(satirlar, "toplam").get("TOPLAM") or _yeni_kova({})
    ozet = [tamamla(k, toplam) for k in topla(satirlar, boyut).values()]
    ozet.sort(key=lambda r: r["toplam_iskonto"] + r["iade"], reverse=True)
    iadeler = [r for r in satir_detaylari(satirlar) if r["_belge_turu"] == "IADE"]
    for r in iadeler:
        r["baglanti"] = "Kaynak faturaya bağlı" if r["maliyet_kaynagi"].startswith("kaynak satış") else "Kaynaksız"
        r["miktar"] = abs(r["miktar"])
        r["net"] = abs(r["net"])
    notlar = [
        "Satır iskontoları (1-2-3) art arda uygulanır; oranlar toplanmaz. İskonto tutarı brüt − iskontolu "
        "tutardır, etkin iskonto oranı = toplam indirim / brüt.",
        "Fatura geneli indirim/masraf ve yuvarlama, muhasebe fişiyle aynı matraha göre satırlara oransal "
        "dağıtılır (Belge geneli sütunu; eksi değer indirimdir).",
        "İade tutarı KDV hariç; iade satırı kaynak fatura satırına bağlıysa bağlantı gösterilir.",
        "Programda iade nedeni alanı bulunmadığından iade nedeni raporlanmaz.",
    ]
    return {"ozet": ozet, "iadeler": iadeler, "notlar": notlar, "toplam": tamamla(toplam)}


# ---------------------------------------------------------------------------
# 10) Bekleyen satış siparişleri ve teslimat
# ---------------------------------------------------------------------------

SIPARIS_HARIC = ("TASLAK", "İPTAL", "FATURALI")
SEVK_SAYILMAYAN = ("İPTAL", "İADE")


def bekleyen_satis_siparisleri(filtre: dict | None = None, bugun: date | None = None,
                               sadece_geciken: bool = False) -> dict[str, Any]:
    from database.models.satis_faturasi import SatisFaturasi, SatisFaturasiSatiri
    from database.models.satis_irsaliyesi import SatisIrsaliyesi, SatisIrsaliyesiSatiri
    from database.models.satis_siparisi import SatisSiparisi, SatisSiparisiSatiri
    from database.models.stok import Depo, StokKarti
    from database.satis_faturasi_service import SatisFaturasiService
    from database.satis_siparisi_service import SatisSiparisiService, siparis_tl_fiyati
    from database.stok_service import StokService

    _rapor_yetkisi()
    b = bugun or date.today()
    f = filtre or {}
    arama = turkce_normalize((f.get("urun") or "").strip())
    maliyet_ok = maliyet_gorunur()
    out = []
    with get_session() as session:
        q = (select(SatisSiparisi).where(SatisSiparisi.durum.notin_(SIPARIS_HARIC))
             .options(selectinload(SatisSiparisi.satirlar), selectinload(SatisSiparisi.cari)))
        if f.get("cari_id"):
            q = q.where(SatisSiparisi.cari_id == int(f["cari_id"]))
        if f.get("sube_id"):
            q = q.where(SatisSiparisi.sube_id == int(f["sube_id"]))
        siparisler = list(session.scalars(q).all())
        satir_idleri = [s.id for sp in siparisler for s in sp.satirlar]
        sevk: dict[int, Decimal] = {}
        if satir_idleri:
            for sid, m in session.execute(
                select(SatisIrsaliyesiSatiri.siparis_satiri_id, SatisIrsaliyesiSatiri.miktar)
                .join(SatisIrsaliyesi, SatisIrsaliyesi.id == SatisIrsaliyesiSatiri.irsaliye_id)
                .where(SatisIrsaliyesiSatiri.siparis_satiri_id.in_(satir_idleri),
                       SatisIrsaliyesi.stok_cikis_yapildi.is_(True),
                       SatisIrsaliyesi.durum.notin_(SEVK_SAYILMAYAN))).all():
                sevk[int(sid)] = sevk.get(int(sid), SIFIR) + _d(m)
            for sid, m in session.execute(
                select(SatisFaturasiSatiri.siparis_satiri_id, SatisFaturasiSatiri.miktar)
                .join(SatisFaturasi, SatisFaturasi.id == SatisFaturasiSatiri.fatura_id)
                .where(SatisFaturasiSatiri.siparis_satiri_id.in_(satir_idleri),
                       SatisFaturasiSatiri.irsaliye_satiri_id.is_(None),
                       SatisFaturasi.onaylandi.is_(True), SatisFaturasi.durum != "İPTAL",
                       or_(SatisFaturasi.is_deleted.is_(False), SatisFaturasi.is_deleted.is_(None)))).all():
                sevk[int(sid)] = sevk.get(int(sid), SIFIR) + _d(m)
        kartlar = {k.stok_kodu: k for k in session.scalars(select(StokKarti)).all()}
        depolar = {d.id: d.ad for d in session.scalars(select(Depo)).all()}
        envanter = StokService.fifo_envanter_degerleri(session)
        stok: dict[tuple[int, str], Decimal] = {}
        for (sid, did), v in envanter.items():
            ad = depolar.get(did, "")
            stok[(sid, ad)] = stok.get((sid, ad), SIFIR) + _d(v["miktar"])
            stok[(sid, "")] = stok.get((sid, ""), SIFIR) + _d(v["miktar"])
        for sp in siparisler:
            for s in sp.satirlar:
                if arama and arama not in turkce_normalize(s.urun_kodu or "") and arama not in turkce_normalize(
                        s.urun_adi or ""):
                    continue
                karsilanan = max(_d(s.irsaliyelenen_miktar), _d(s.faturalanan_miktar))
                kalan = max(SIFIR, _d(s.miktar) - karsilanan)
                if kalan <= 0:
                    continue
                teslim = s.estimated_delivery_date or sp.termin_tarihi
                gecikme = (b - teslim).days if teslim and teslim < b else 0
                if sadece_geciken and not gecikme:
                    continue
                tl_fiyat = siparis_tl_fiyati(sp, s)
                _br, _isk, net_birim = SatisFaturasiService._satir_net(
                    Decimal("1"), tl_fiyat, s.iskonto_orani, s.iskonto_orani_2, s.iskonto_orani_3)
                kalan_tutar = _q2(net_birim * kalan)
                mb = _d(SatisSiparisiService.birim_maliyeti(s, sp.maliyet_yontemi or "FIFO"))
                tahmini = _q2(kalan_tutar - mb * kalan) if mb > 0 else None
                kart = kartlar.get(s.urun_kodu)
                carpan = StokService.birim_carpani_bul(kart, s.birim, kart.birim or "Adet") if kart else None
                out.append({
                    "siparis_id": sp.id, "siparis_no": sp.siparis_no, "siparis_tarihi": sp.siparis_tarihi,
                    "cari_id": sp.cari_id, "unvan": sp.cari.unvan if sp.cari else "", "durum": sp.durum,
                    "urun_kodu": s.urun_kodu, "urun_adi": s.urun_adi, "birim": s.birim,
                    "siparis_miktar": _d(s.miktar), "karsilanan": karsilanan, "sevk_edilen": sevk.get(s.id, SIFIR),
                    "sevk_bekleyen": max(SIFIR, karsilanan - sevk.get(s.id, SIFIR)), "kalan": kalan,
                    "teslim_tarihi": teslim, "gecikme": gecikme, "kalan_tutar": kalan_tutar,
                    "para_birimi": sp.para_birimi or "TRY", "tahmini_kar": tahmini,
                    "_stok_id": kart.id if kart else None, "_carpan": carpan, "_depo": sp.depo or "",
                })
    out.sort(key=lambda r: (r["teslim_tarihi"] or date.max, r["siparis_tarihi"], r["siparis_no"]))
    kalan_stok: dict[tuple[int, str], Decimal] = {}
    for r in out:
        sid, carpan = r.pop("_stok_id"), r.pop("_carpan")
        r.pop("_depo")
        if sid is None or carpan is None:
            r["stok_durumu"] = "Kontrol edilemedi (stok kartı/birim çevrimi yok)"
            continue
        anahtar = (sid, "")
        if anahtar not in kalan_stok:
            kalan_stok[anahtar] = stok.get(anahtar, SIFIR)
        ihtiyac = r["kalan"] * _d(carpan)
        mevcut = max(SIFIR, kalan_stok[anahtar])
        karsilanabilir = min(ihtiyac, mevcut)
        kalan_stok[anahtar] = mevcut - karsilanabilir
        r["karsilanabilir"] = (karsilanabilir / _d(carpan)).quantize(Decimal("0.001"))
        r["stok_durumu"] = ("Yeterli" if karsilanabilir >= ihtiyac else
                            "Kısmi" if karsilanabilir > 0 else "Yetersiz")
    if not maliyet_ok:
        for r in out:
            r["tahmini_kar"] = None
    notlar = [
        "Kalan = sipariş − irsaliye/fatura ile karşılanan (irsaliyelenen ve faturalanan miktarın büyüğü; "
        "irsaliyeden faturalanan miktar iki kez sayılmaz). Taslak, iptal ve tamamen faturalı siparişler hariç.",
        "Sevk edilen: stok çıkışı yapılmış irsaliyeler + irsaliyesiz doğrudan faturalar. Sevk bekleyen: "
        "irsaliyesi kesilmiş ama stok çıkışı yapılmamış miktar.",
        "Stok yeterliliği mevcut rezervasyon yaklaşımıyla hesaplanır: programda ayrı rezervasyon tutulmadığından "
        "fiziksel stok, teslim tarihi sırasına göre bekleyen satırlara dağıtılır.",
        "Kalan tutar KDV hariç, sipariş kuruyla TL'dir. Tahmini kâr sipariş anındaki maliyetle hesaplanır; "
        "'tahmini'dir ve gerçekleşen kâra eklenmez.",
    ]
    return {"satirlar": out, "notlar": notlar,
            "toplam": {"kalan_tutar": _q2(sum((r["kalan_tutar"] for r in out), SIFIR)),
                       "geciken": sum(1 for r in out if r["gecikme"]),
                       "tahmini_kar": (_q2(sum((r["tahmini_kar"] for r in out if r["tahmini_kar"] is not None),
                                               SIFIR)) if maliyet_ok else None)}}


# ---------------------------------------------------------------------------
# 11) Yönetici satış özeti
# ---------------------------------------------------------------------------

def _pos_komisyonu(bas: date, bit: date, belge_nolari: set[str]) -> Decimal:
    """Yalnız belge numarasıyla satış faturasına bağlanabilen POS komisyonları."""
    if not belge_nolari:
        return SIFIR
    try:
        from database.models.finans import PosValorKaydi

        with get_session() as session:
            return _d(session.scalar(select(func.coalesce(func.sum(PosValorKaydi.komisyon_tutari), 0)).where(
                PosValorKaydi.belge_no.in_(belge_nolari), PosValorKaydi.tahsilat_tarihi >= bas,
                PosValorKaydi.tahsilat_tarihi <= bit)))
    except Exception:  # noqa: BLE001
        return SIFIR


def yonetici_ozeti(donem: tuple[date, date], karsilastirma: tuple[date, date], filtre: dict | None = None,
                   bugun: date | None = None, hedef_marj=10, inaktif_gun: int = 90,
                   dusus_esigi=20) -> dict[str, Any]:
    from database.cari_service import CariService
    from database.models.cari import CariIslem

    b = bugun or date.today()
    maliyet_ok = maliyet_gorunur()
    s1 = satirlari_getir(donem[0], donem[1], filtre)
    s2 = satirlari_getir(karsilastirma[0], karsilastirma[1], filtre)
    t1 = tamamla(topla(s1, "toplam").get("TOPLAM") or _yeni_kova({}))
    t2 = tamamla(topla(s2, "toplam").get("TOPLAM") or _yeni_kova({}))

    def tahsilat_toplami(bas, bit):
        with get_session() as session:
            q = select(CariIslem).where(CariIslem.tarih >= bas, CariIslem.tarih <= bit, CariIslem.alacak > 0)
            if (filtre or {}).get("cari_id"):
                q = q.where(CariIslem.cari_id == int(filtre["cari_id"]))
            return _q2(sum((_d(i.alacak) for i in session.scalars(q).all() if _tahsilat_mi(i)), SIFIR))

    acik = gecmis = SIFIR
    with get_session() as session:
        cid_f = (filtre or {}).get("cari_id")
        for oz in CariService.listele(cari_turu="Müşteri", hizli=True):
            cid = int(oz["cari"].id)
            if cid_f and cid != int(cid_f):
                continue
            if _d(oz.get("bakiye")) <= 0:
                continue
            v = _cari_vade_durumu(session, cid, None, None, b)
            acik += v["acik_alacak"]
            gecmis += v["vadesi_gecmis"]

    tah1, tah2 = tahsilat_toplami(*donem), tahsilat_toplami(*karsilastirma)
    belge_nolari = {s.belge_no for s in s1 if s.belge_turu == "SATIS"}
    pos = _pos_komisyonu(donem[0], donem[1], belge_nolari)

    def kpi(ad, tur, d1, d2, rapor, yuzde_tur="tutar", puan=False):
        r = {"gosterge": ad, "tur": tur, "donem": d1, "karsilastirma": d2, "rapor": rapor}
        if puan:
            r["fark"] = marj_puan_farki(d1, d2)
            r["degisim"] = "puan"
        elif d2 is not None and d1 is not None:
            dg = degisim(d1, d2, yuzde_tur)
            r["fark"], r["yuzde"], r["aciklama"] = dg["fark"], dg["yuzde"], dg["aciklama"]
        return r

    H = "Dönem hareketi"
    gostergeler = [
        kpi("Net satış (KDV hariç, iade düşülmüş)", H, t1["net"], t2["net"], "musteri_kar"),
        kpi("İade tutarı", H, t1["iade"], t2["iade"], "iskonto_iade"),
        kpi("İskonto (satır + belge geneli)", H, t1["toplam_iskonto"], t2["toplam_iskonto"], "iskonto_iade"),
        kpi("Dönem tahsilatı", H, tah1, tah2, "tahsilat"),
    ]
    if maliyet_ok:
        gostergeler[1:1] = [
            kpi("Brüt kâr", H, t1["kar"], t2["kar"], "stok_kar", "kar"),
            kpi("Kâr marjı %", H, t1["marj"], t2["marj"], "stok_kar", puan=True),
        ]
        if pos > 0:
            gostergeler.append(kpi("Belgeye bağlı POS komisyonu", H, pos, None, "musteri_kar"))
            gostergeler.append(kpi("Satış katkısı (brüt kâr − bağlı POS komisyonu)", H, t1["kar"] - pos, None,
                                   "musteri_kar", "kar"))
    gostergeler += [
        {"gosterge": "Açık alacak", "tur": f"{b:%d.%m.%Y} itibarıyla bakiye", "donem": _q2(acik),
         "rapor": "tahsilat"},
        {"gosterge": "Vadesi geçmiş alacak", "tur": f"{b:%d.%m.%Y} itibarıyla bakiye", "donem": _q2(gecmis),
         "rapor": "tahsilat"},
    ]

    musteriler = [tamamla(k, topla(s1, "toplam").get("TOPLAM")) for k in topla(s1, "musteri").values()]
    musteriler.sort(key=lambda r: r["net"], reverse=True)
    urunler = [tamamla(k, topla(s1, "toplam").get("TOPLAM")) for k in topla(s1, "urun").values()]
    urunler.sort(key=lambda r: r["net"], reverse=True)
    dusuk = []
    if maliyet_ok:
        dusuk = dusuk_marjli_satislar(donem[0], donem[1], filtre, hedef_marj)["satirlar"]
    azalan = azalan_musteriler(donem, karsilastirma, filtre, inaktif_gun, dusus_esigi, b)["satirlar"]
    bekleyen = bekleyen_satis_siparisleri(filtre, b)
    gostergeler += [
        {"gosterge": "Düşük marjlı / zararına satış satırı", "tur": H, "donem": len(dusuk) if maliyet_ok else None,
         "rapor": "dusuk_marj"},
        {"gosterge": "Satışı azalan / duran müşteri", "tur": H, "donem": len(azalan), "rapor": "azalan"},
        {"gosterge": "Bekleyen sipariş tutarı (KDV hariç)", "tur": f"{b:%d.%m.%Y} itibarıyla açık",
         "donem": bekleyen["toplam"]["kalan_tutar"], "rapor": "bekleyen_siparis"},
        {"gosterge": "Bekleyen siparişlerin tahmini kârı", "tur": "Tahmini — gerçekleşen kâra eklenmez",
         "donem": bekleyen["toplam"]["tahmini_kar"], "rapor": "bekleyen_siparis"},
    ]
    if not maliyet_ok:
        _maliyet_gizle(musteriler)
        _maliyet_gizle(urunler)
    notlar = [
        f"Dönem {donem[0]:%d.%m.%Y}–{donem[1]:%d.%m.%Y}; karşılaştırma {karsilastirma[0]:%d.%m.%Y}–"
        f"{karsilastirma[1]:%d.%m.%Y}. 'Dönem hareketi' satırları dönem içi hareket, 'itibarıyla' satırları "
        "rapor tarihindeki bakiyedir.",
        "Bir göstergeye çift tıklayınca ayrıntılı rapor açılır.",
        ("Belge numarasıyla satış faturasına bağlanabilen POS komisyonu bulunmadığından satış katkısı "
         "hesaplanmadı; kargo/nakliye bedeli için belgeye bağlı alan yoktur. Keyfi dağıtım yapılmaz."
         if pos <= 0 else
         "Satış katkısı yalnız belgeye bağlı POS komisyonunu düşer; net işletme kârı değildir."),
    ] + _ortak_notlar(filtre, t1["eksik_satir"], t1["eksik_net"])[:1]
    return {"gostergeler": gostergeler, "musteriler": musteriler[:10], "urunler": urunler[:10],
            "dusuk_marj": dusuk[:20], "azalan": azalan[:20], "bekleyen": bekleyen["satirlar"][:20],
            "notlar": notlar, "maliyet_gorunur": maliyet_ok}


# ---------------------------------------------------------------------------
# Müşteri bazında yıllık / aylık satışlar
# ---------------------------------------------------------------------------

AYLAR = ("Ocak", "Şubat", "Mart", "Nisan", "Mayıs", "Haziran", "Temmuz", "Ağustos", "Eylül", "Ekim",
         "Kasım", "Aralık")
HENUZ_GELMEDI = "Henüz gelmedi"
KAPSAM_DISI = "Kapsam dışı"
AYLIK_GOSTERGELER: dict[str, tuple[str, str]] = {
    "net": ("Net satış (KDV hariç)",
            "Satır iskontoları ve fatura geneli indirim/masraf payı düşülmüş, KDV hariç satış tutarı; iadeler kendi "
            "belge tarihindeki ayda düşülür."),
    "maliyet": ("Satış maliyeti",
                "Satılan malın seçili yönteme göre maliyeti; iadeler kendi tarihinde ters çevrilir. Maliyeti "
                "bulunamayan satır sıfır sayılmaz (Eksik maliyet / Kısmi)."),
    "kar": ("Brüt satış kârı",
            "Net satış − satılan malın maliyeti; yalnız maliyeti bilinen satırlar. Genel giderler düşülmez. Maliyeti "
            "eksik satır sıfır maliyet sayılmaz; o ay 'Kısmi' veya 'Eksik maliyet' olarak işaretlenir."),
    "marj": ("Brüt kâr marjı %",
             "Brüt satış kârı / net satış × 100 (Kısmi aylarda maliyeti bilinen net satış). Aylar ve müşteriler "
             "ortalanmaz; her toplam kendi kâr ve net satışından yeniden hesaplanır. Net satış 0 veya negatifse "
             "'—'."),
    "birlikte": ("Satış + maliyet + kâr + marj",
                 "Her ay için net satış, maliyet, brüt satış kârı ve marj alt sütunları; marj toplam kâr / toplam "
                 "net satıştan hesaplanır."),
    "fatura": ("Fatura sayısı",
               "Onaylı, iptal edilmemiş satış faturası adedi (hızlı satış kendi faturasıyla bir kez); iade belgeleri "
               "sayılmaz."),
}
BIRLIKTE_ALT = (("net", "Net"), ("maliyet", "Maliyet"), ("kar", "Kâr"), ("marj", "Marj %"))
EKSIK_MALIYET = "Eksik maliyet"
MARJ_YOK = "—"


def _doviz_satirlari(satirlar: list[SatirAnaliz], pb: str) -> tuple[list[SatirAnaliz], int]:
    """Yalnız ``pb`` para birimli belgeler; TRY dışında tutarlar belge kuruyla belge dövizine geri çevrilir."""
    from dataclasses import replace

    out, kursuz = [], 0
    for s in satirlar:
        if (s.para_birimi or "TRY").upper() != pb:
            continue
        if pb == "TRY":
            out.append(s)
            continue
        kur = _d(s.kur)
        if kur <= 0:
            kursuz += 1
            continue

        def b(v):
            return None if v is None else _d(v) / kur

        out.append(replace(s, net_satis=b(s.net_satis), brut_satis=b(s.brut_satis), iskonto=b(s.iskonto),
                           belge_duzeltme=b(s.belge_duzeltme), toplam_maliyet=b(s.toplam_maliyet),
                           brut_kar=b(s.brut_kar)))
    return out, kursuz


def _gosterge_degeri(kova: dict | None, gosterge: str):
    """Hücre değeri. Maliyeti hiç bilinmeyen hücrede maliyet/kâr/marj ``EKSIK_MALIYET``; marjda net ≤ 0 ise '—'."""
    if kova is None:
        return None if gosterge == "marj" else (0 if gosterge == "fatura" else SIFIR)
    t = tamamla(kova)
    if gosterge in ("maliyet", "kar", "marj") and kova["satir_sayisi"] and \
            kova["eksik_satir"] >= kova["satir_sayisi"]:
        return EKSIK_MALIYET
    if gosterge == "marj":
        if _d(kova["net"]) <= 0 or _d(kova["maliyetli_net"]) <= 0:
            return MARJ_YOK
        return t["marj"]
    return {"net": t["net"], "maliyet": t["maliyet"], "kar": t["kar"], "fatura": t["fatura_sayisi"]}[gosterge]


def _hucre_durumu(kova: dict | None) -> str:
    if not kova or not kova["eksik_satir"]:
        return ""
    return EKSIK_MALIYET if kova["eksik_satir"] >= kova["satir_sayisi"] else "Kısmi"


def _ay_sonu(yil: int, ay: int) -> date:
    return date(yil, ay, calendar.monthrange(yil, ay)[1])


def musteri_aylik_satis(
    yil: int, *, gosterge: str = "net", karsilastirma: Iterable[int] = (), ayni_tarihe_kadar: bool = False,
    filtre: dict | None = None, para_birimi: str = "", siralama: str = "toplam", siralama_ay: int | None = None,
    satissizlar: bool = False, bugun: date | None = None,
) -> dict[str, Any]:
    """Müşteri × ay matrisi (seçilen gösterge) ve isteğe bağlı geçmiş yıl karşılaştırması. Salt okunur.

    Satırlar ortak kâr motorundan (``satirlari_getir``) gelir; toplamlar müşteri/stok kârlılığı raporlarıyla aynıdır.
    """
    from collections import defaultdict

    _rapor_yetkisi()
    if gosterge not in AYLIK_GOSTERGELER:
        raise ValueError(f"Bilinmeyen gösterge: {gosterge}")
    maliyet_ok = maliyet_gorunur()
    if gosterge in ("maliyet", "kar", "marj", "birlikte") and not maliyet_ok:
        raise ValueError("Maliyet, kâr ve marj göstergeleri için maliyet ve kâr görme yetkisi gerekir.")
    birlikte = gosterge == "birlikte"
    gk = "net" if birlikte else gosterge
    b = bugun or date.today()
    yil = int(yil)
    if yil > b.year:
        raise ValueError("Gelecek yıl seçilemez.")
    devam = yil == b.year
    son_ay = b.month if devam else 12
    kesim = b if devam else date(yil, 12, 31)
    yillar = [yil] + sorted({int(y) for y in karsilastirma if y and int(y) != yil}, reverse=True)
    pb = (para_birimi or "").upper()

    veri: dict[int, dict] = {}
    meta: dict[Any, dict] = {}
    para_birimleri: set[str] = set()
    kursuz = 0
    eksik_satirlar: list[SatirAnaliz] = []
    for y in yillar:
        bas = date(y, 1, 1)
        if y == yil:
            bit = date(y, 12, 31)
        else:
            bit = _yil_kaydir(kesim, y - yil) if (ayni_tarihe_kadar and devam) else date(y, 12, 31)
        satirlar = satirlari_getir(bas, bit, filtre)
        para_birimleri |= {(s.para_birimi or "TRY").upper() for s in satirlar}
        if pb:
            satirlar, k = _doviz_satirlari(satirlar, pb)
            kursuz += k
        if y == yil and maliyet_ok:
            eksik_satirlar = [s for s in satirlar if s.toplam_maliyet is None or s.brut_kar is None]
        aylara: dict[int, list] = defaultdict(list)
        for s in satirlar:
            aylara[s.tarih.month].append(s)
        hucre: dict[Any, dict[int, dict]] = defaultdict(dict)
        toplam_ay: dict[int, dict | None] = {}
        for ay in range(1, 13):
            for a, k in topla(aylara[ay], "musteri").items():
                hucre[a][ay] = k
                meta.setdefault(a, {m: v for m, v in k.items() if m not in _KOVA_ALANLARI})
            toplam_ay[ay] = topla(aylara[ay], "toplam").get("TOPLAM")
        veri[y] = {"hucre": hucre, "yillik": topla(satirlar, "musteri"), "toplam_ay": toplam_ay,
                   "genel": topla(satirlar, "toplam").get("TOPLAM"), "bas": bas, "bit": bit,
                   "son_ay": son_ay if y == yil else (bit.month if bit.year == y else 12)}

    if satissizlar:
        from database.cari_service import CariService

        f = filtre or {}
        grup = turkce_normalize((f.get("musteri_grubu") or "").strip())
        for c in CariService.aktif_musteriler():
            if f.get("cari_id") and int(f["cari_id"]) != int(c.id):
                continue
            if grup and turkce_normalize(c.musteri_grubu or "") != grup:
                continue
            meta.setdefault(int(c.id), {"cari_id": int(c.id), "cari_kodu": c.cari_kodu, "unvan": c.unvan,
                                        "musteri_grubu": c.musteri_grubu or ""})

    def ay_degeri(y: int, ay: int, kova, g: str | None = None) -> Any:
        if y == yil and devam and ay > son_ay:
            return HENUZ_GELMEDI
        if y != yil and ay > veri[y]["son_ay"]:
            return KAPSAM_DISI
        return _gosterge_degeri(kova, g or gk)

    def karsilastir(r: dict, ana, onceki, y: int, g: str = gk, onek: str = "") -> None:
        r[f"{onek}toplam_{y}"] = onceki
        if isinstance(ana, str) or isinstance(onceki, str):
            r[f"{onek}fark_{y}"] = r[f"{onek}yuzde_{y}"] = None
        elif g == "marj":
            r[f"{onek}fark_{y}"] = marj_puan_farki(ana, onceki)
            r[f"{onek}yuzde_{y}"] = None
        else:
            dg = degisim(ana, onceki, "kar" if g == "kar" else "tutar")
            r[f"{onek}fark_{y}"], r[f"{onek}yuzde_{y}"] = dg["fark"], dg["yuzde"]

    def eksik_aylar(y: int, hucreler: dict[int, dict]) -> str:
        gruplar: dict[str, list[str]] = {}
        for ay, k in sorted(hucreler.items()):
            d = _hucre_durumu(k)
            if d:
                gruplar.setdefault(d, []).append(AYLAR[ay - 1][:3])
        return " | ".join(f"{d}: {', '.join(a)}" for d, a in gruplar.items())

    def hucreleri_yaz(r: dict, hucreler: dict[int, dict], yk) -> None:
        for ay in range(1, 13):
            if birlikte:
                for g, _ad in BIRLIKTE_ALT:
                    r[f"ay_{ay}_{g}"] = ay_degeri(yil, ay, hucreler.get(ay), g)
            else:
                r[f"ay_{ay}"] = ay_degeri(yil, ay, hucreler.get(ay))
        if birlikte:
            for g, _ad in BIRLIKTE_ALT:
                r[f"toplam_{g}"] = _gosterge_degeri(yk, g)
        r["toplam"] = _gosterge_degeri(yk, gk)
        r["maliyet_durumu"] = eksik_aylar(yil, hucreler) if maliyet_ok else ""

    def karsilastirmalari_yaz(r: dict, onceki_k: dict[int, Any]) -> None:
        for y in yillar[1:]:
            karsilastir(r, r["toplam"], _gosterge_degeri(onceki_k.get(y), gk), y)
            if birlikte:
                r[f"kar_{y}"] = _gosterge_degeri(onceki_k.get(y), "kar")
                r[f"marj_{y}"] = _gosterge_degeri(onceki_k.get(y), "marj")

    satirlar_out: list[dict] = []
    for a, m in meta.items():
        var = any(a in veri[y]["yillik"] for y in yillar)
        if not var and not satissizlar:
            continue
        ana_h = veri[yil]["hucre"].get(a, {})
        r = {"cari_id": m.get("cari_id"), "cari_kodu": m.get("cari_kodu") or "", "unvan": m.get("unvan") or "",
             "musteri_grubu": m.get("musteri_grubu") or "", "_anahtar": a}
        yk = veri[yil]["yillik"].get(a)
        hucreleri_yaz(r, ana_h, yk)
        r["_kar"] = tamamla(yk)["kar"] if yk else SIFIR
        r["_eksik"] = bool(yk and yk["eksik_satir"])
        karsilastirmalari_yaz(r, {y: veri[y]["yillik"].get(a) for y in yillar[1:]})
        satirlar_out.append(r)

    def sayi(v):
        return v if isinstance(v, (int, Decimal)) else None

    if siralama == "unvan":
        satirlar_out.sort(key=lambda r: turkce_normalize(r["unvan"]))
    else:
        if siralama == "ay" and siralama_ay:
            ay_anahtar = f"ay_{int(siralama_ay)}" + ("_net" if birlikte else "")
            anahtar = lambda r: sayi(r.get(ay_anahtar))  # noqa: E731
        elif siralama == "kar":
            anahtar = lambda r: r["_kar"] if maliyet_ok else None  # noqa: E731
        elif siralama == "degisim" and len(yillar) > 1:
            anahtar = lambda r: sayi(r.get(f"fark_{yillar[1]}"))  # noqa: E731
        else:
            anahtar = lambda r: sayi(r["toplam"])  # noqa: E731
        satirlar_out.sort(key=lambda r: (anahtar(r) is None, -(anahtar(r) or 0), turkce_normalize(r["unvan"])))

    genel = {"cari_id": None, "cari_kodu": "", "unvan": "GENEL TOPLAM", "_sabit": True}
    hucreleri_yaz(genel, {ay: k for ay, k in veri[yil]["toplam_ay"].items() if k}, veri[yil]["genel"])
    karsilastirmalari_yaz(genel, {y: veri[y]["genel"] for y in yillar[1:]})

    kapsam = {y: f"{veri[y]['bas']:%d.%m.%Y}–{(b if (y == yil and devam) else veri[y]['bit']):%d.%m.%Y}"
                 + (" (devam ediyor)" if y == yil and devam else "") for y in yillar}
    karsilastirma_out: list[dict] = []
    if len(yillar) > 1:
        olculer = list(BIRLIKTE_ALT) if birlikte else [(gk, AYLIK_GOSTERGELER[gk][0])]

        def fark_yuzde(ana_v, v, g: str) -> tuple[Any, Any]:
            """Fark ve yüzde değişim; önceki değer 0/negatifse yüzde '—'; marj farkı yüzde puan."""
            if isinstance(ana_v, str) or isinstance(v, str) or ana_v is None or v is None:
                return None, None
            if g == "marj":
                f = marj_puan_farki(ana_v, v)
                return (f"{f:+.2f} yüzde puan".replace(".", ",") if birlikte else f), None
            fark = _d(ana_v) - _d(v)
            if _d(v) <= 0:
                return fark, MARJ_YOK
            return fark, f"%{(fark / _d(v) * YUZ):.2f}".replace(".", ",")

        for r in satirlar_out + [genel]:
            a = r.get("_anahtar")
            hucreler = {y: (veri[y]["hucre"].get(a, {}) if a is not None else
                            {ay: k for ay, k in veri[y]["toplam_ay"].items() if k}) for y in yillar}
            yillik = {y: (veri[y]["yillik"].get(a) if a is not None else veri[y]["genel"]) for y in yillar}
            ortak = {"cari_id": r["cari_id"], "cari_kodu": r["cari_kodu"], "unvan": r["unvan"]}
            for g, olcu_adi in olculer:
                ana_sira = {"satir": str(yil), "olcu": olcu_adi, "kapsam": kapsam[yil], "_yil": yil, **ortak,
                            "toplam": _gosterge_degeri(yillik[yil], g)}
                for ay in range(1, 13):
                    ana_sira[f"ay_{ay}"] = ay_degeri(yil, ay, hucreler[yil].get(ay), g)
                karsilastirma_out.append(ana_sira)
                for y in yillar[1:]:
                    sira = {"satir": str(y), "olcu": olcu_adi, "kapsam": kapsam[y], "_yil": y, **ortak,
                            "toplam": _gosterge_degeri(yillik[y], g)}
                    fark = {"satir": f"Fark ({yil} − {y})" + (" puan" if g == "marj" else ""), "olcu": olcu_adi,
                            **ortak}
                    yuzde = {"satir": "Değişim %", "olcu": olcu_adi, **ortak}
                    fark["toplam"], yuzde["toplam"] = fark_yuzde(ana_sira["toplam"], sira["toplam"], g)
                    for ay in range(1, 13):
                        v = ay_degeri(y, ay, hucreler[y].get(ay), g)
                        sira[f"ay_{ay}"] = v
                        fark[f"ay_{ay}"], yuzde[f"ay_{ay}"] = fark_yuzde(ana_sira[f"ay_{ay}"], v, g)
                    karsilastirma_out += [sira, fark] + ([] if g == "marj" else [yuzde])

    ad, esas = AYLIK_GOSTERGELER[gosterge]
    birim = pb if pb else "TL"
    yontem = (filtre or {}).get("maliyet_yontemi") or "FIFO"
    notlar = [
        f"Gösterge: {ad} — {esas}",
        *([yontem_notu(yontem)] if maliyet_ok else []),
        ("Para birimi: tüm belgeler TL karşılığıyla (belge kuruyla, güncel kurla yeniden değerlenmez)."
         if not pb else
         f"Para birimi: yalnız {pb} belgeler, {pb} tutarıyla (belge kuruyla geri çevrilmiş; maliyet satış belgesi "
         "kuruyla). Farklı para birimleri dönüştürülmeden birbirine eklenmez."),
        "Müşteri kimliği esas alınır; unvanı değişen müşteri tek satırdadır (güncel unvan). Yalnız onaylı ve iptal "
        "edilmemiş belgeler; taslaklar hariç. Hızlı satış kendi faturasıyla bir kez sayılır.",
        "Aylık toplamlar yıllık toplamla ve Müşteri Kârlılığı / Satış Kâr Analizi raporlarıyla aynı hesaptır.",
    ]
    if devam:
        notlar.append(f"{yil} devam ediyor: {AYLAR[son_ay - 1]} ayı tamamlanmadı ({b:%d.%m.%Y} itibarıyla); "
                      f"sonraki aylar '{HENUZ_GELMEDI}' — gerçekleşmiş sıfır satış değildir.")
    if len(yillar) > 1:
        if ayni_tarihe_kadar and devam:
            notlar.append(f"Karşılaştırma yılları {kesim:%d.%m} tarihine kadar alındı (önceki yılın aynı tarihi); "
                          f"sonraki aylar '{KAPSAM_DISI}'.")
        notlar.append("Fark = seçilen yıl − karşılaştırma yılı. Karşılaştırma yılı değeri 0 veya negatifse yüzde "
                      "değişim '—' gösterilir; marjda fark yüzde puandır (ör. %25 → %30 = +5 yüzde puan). İki yıl "
                      "aynı maliyet yöntemi, para birimi ve filtrelerle hesaplanır.")
        notlar.append("Kapsanan tarih aralıkları: " + "; ".join(f"{y}: {kapsam[y]}" for y in yillar) + ".")
    notlar.append("Satış yapmayan müşteriler: " + (
        "gösteriliyor (aktif müşteri kartları, gerçekleşmiş 0)." if satissizlar else
        "gizli (seçilen hiçbir yılda hareketi olmayan müşteriler listelenmez)."))
    if maliyet_ok:
        eksik_t = veri[yil]["genel"]["eksik_satir"] if veri[yil]["genel"] else 0
        if eksik_t:
            notlar.append(f"Maliyet eksik: {eksik_t} satırda maliyet bulunamadı ve sıfır sayılmadı; ilgili aylar "
                          f"'{EKSIK_MALIYET}' (hiç maliyet yok) veya 'Kısmi' (kâr kısmen hesaplandı) olarak "
                          "işaretlidir. Kayıtlar 'Eksik maliyet' sekmesinde listelenir.")
    if birlikte and len(yillar) > 1:
        notlar.append("Birlikte görünümde yıl karşılaştırması net satış, satış maliyeti, brüt satış kârı ve brüt kâr "
                      "marjı için ayrı ayrı, aynı aylar ve yıllık toplamlarla verilir.")
    if kursuz:
        notlar.append(f"{kursuz} satırda belge kuru olmadığından {pb} tutarı hesaplanamadı ve rapora alınmadı.")
    if not maliyet_ok:
        _maliyet_gizle(satirlar_out)
        _maliyet_gizle([genel])
    eksik_out = [{**d, "eksik_nedeni": d["maliyet_kaynagi"]} for d in satir_detaylari(eksik_satirlar)]
    return {"satirlar": satirlar_out + [genel], "genel": genel, "karsilastirma": karsilastirma_out,
            "eksik": eksik_out, "yillar": yillar, "yil": yil, "devam": devam, "son_ay": son_ay,
            "gosterge": gosterge, "gosterge_adi": ad, "gosterge_esasi": esas, "birim": birim,
            "maliyet_yontemi": yontem, "para_birimleri": sorted(para_birimleri), "notlar": notlar,
            "maliyet_gorunur": maliyet_ok}
