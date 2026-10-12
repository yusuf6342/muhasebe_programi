"""GİRİŞ ekranı özeti: satış, tahsilat, ödeme takvimi / borç bakiyesi, kasa ve mevduat, tedarikçi açık borcu.

Tek hesap sonucu ana kart, bölüm ve ayrıntı listesinde ortak kullanılır. Her bölüm değeriyle birlikte
durum taşır (hazır, boş, eksik kaynak, tarihsel hesap yok, hata, yetkisiz). Para Decimal; tarih aralıkları
başlangıç dahil, bitiş günü dahil (tarih alanları saat içermez).

Kaynaklar (yeni hesap motoru yazılmadı):
* Satış: onaylı, iptal / silinmiş olmayan satış faturaları — tutar ``SatisFaturasiService.net_toplam``;
  iade: iptal olmayan satış iade faturası, cari kaydındaki tutar (yoksa iade servis toplamı).
* Tahsilat: müşteri cari kartındaki "Tahsilat" kayıtları + fatura içi tahsilat (FATURA TAHSİLATI) +
  cariye bağlanmamış POS tahsilatı; yöntem aynı belgenin kasa / banka / POS hareketinden.
* Kasa / banka: finans hareketleri (D dahil) + açılış bakiyesi.
* Cari bakiye: ``cari_bakiye_service`` formülü (CariIslem + çift kayıtsız SatisHareketi); cari listesiyle
  aynı. Fatura içi tahsilat / ödemenin cariye yansımayan tutarı yalnız "bilinen fark" notudur.
* Tedarikçi açık borcu: rapor tarihinden bağımsız, bugün itibarıyla borçlu olunan tedarikçi bakiyeleri toplamı;
  ödeme yüküne eklenmez.
* Kredi: ``BankaKrediService`` taksit kalanı ve kalan anapara; kart: kart ödeme taksitleri ekstre dönemine göre.
* Stok: ``stok_rapor_service.degerleme`` (FIFO, D itibarıyla).
* Sabit gider: ``sabit_gider_service``.
"""

from __future__ import annotations

import threading
import time
from collections import defaultdict
from datetime import date, datetime
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

from sqlalchemy import event, func, select
from sqlalchemy.orm import Session, selectinload

from database.access import yetki_var
from database.database import get_session
from database.session_manager import oturum
from database.sabit_gider_service import ay_basi, ay_ekle, ay_sonu

SIFIR = Decimal("0")
KURUS = Decimal("0.01")
TOLERANS = Decimal("0.05")

HAZIR = "hazir"
BOS = "bos"
EKSIK = "eksik_kaynak"
TARIHSEL_YOK = "tarihsel_yok"
HATA = "hata"
YETKISIZ = "yetkisiz"
DURUM_ADI = {
    HAZIR: "Hazır", BOS: "Boş", EKSIK: "Eksik kaynak", TARIHSEL_YOK: "Geçmiş bakiye hesaplanamıyor",
    HATA: "Hata", YETKISIZ: "Yetkisiz",
}
GECMIS_METNI = "Geçmiş bakiye hesaplanamıyor"

MUSTERI_TURLERI = ("Müşteri", "Musteri")
TEDARIKCI_TURLERI = ("Tedarikçi", "Tedarikci")

NAKIT, HAVALE, KART = "Nakit", "Alınan havale", "Kredi kartı"
GERCEK_YONTEMLER = (NAKIT, HAVALE, KART)
VIRMAN, MUS_TED = "Cari virman aktarımı", "Müşteriden tedarikçiye"
TEDARIKCI_ACIK = "Tedarikçi açık borcu"
CEK_ALINAN = "Alınan çek / senet"
BELIRSIZ = "Yöntemi belirlenemeyen"

TAHSILAT_FH = ("TAHSİLAT MAKBUZU", "CARİ TAHSİLAT", "ALINAN HAVALE", "POS TAHSİLAT", "FATURA TAHSİLATI")
IADE_ODEME_FH = ("ÖDEME MAKBUZU", "CARİ ÖDEME", "GÖNDERİLEN HAVALE", "SATIŞ İADE ÖDEMESİ")

KREDI, KK, KMH, SABIT, DIGER = ("kredi", "kart", "kmh", "sabit", "diger")
TAKVIM_SATIRLARI = (
    (KREDI, "Kredi taksitleri"), (KK, "Kredi kartı ödemeleri"), (KMH, "KMH ödemesi"),
    (SABIT, "Sabit gider ödemeleri"), (DIGER, "Diğer kayıtlı ödemeler"),
)
TAKVIM_ADI = dict(TAKVIM_SATIRLARI)
SUTUNLAR = ("bugun", "ay1", "ay2", "ay3", "tamami")

VERILEN_CEK_ACIK = ("PORTFOYDE", "TEDARIKCIYE_VERILDI", "KISMI_ODENDI", "VADESI_GECTI")
ALINAN_CEK_ELDE = ("PORTFOYDE", "BANKAYA_TAHSILE", "BANKAYA_TEMINATA", "KISMI_TAHSIL", "VADESI_GECTI")


def _d(v) -> Decimal:
    if v is None or v == "":
        return SIFIR
    return v if isinstance(v, Decimal) else Decimal(str(v))


def _q2(v) -> Decimal:
    return _d(v).quantize(KURUS, rounding=ROUND_HALF_UP)


def _tl(v) -> str:
    """Mesaj içi tutar: 1.234,56 TL."""
    return f"{_q2(v):,.2f}".replace(",", "X").replace(".", ",").replace("X", ".") + " TL"


# ----------------------------------------------------------------------------- değişiklik sayacı
_sayac_kilit = threading.Lock()
_degisim_sayaci = 0


@event.listens_for(Session, "after_flush")
def _yazma_sayaci(session, _ctx) -> None:
    global _degisim_sayaci
    if session.new or session.dirty or session.deleted:
        with _sayac_kilit:
            _degisim_sayaci += 1


def degisim_sayaci() -> int:
    return _degisim_sayaci


# ----------------------------------------------------------------------------- tarih ve oran
def onceki_ay_ayni_gun(d: date) -> date:
    """Önceki ayın aynı takvim günü; gün yoksa o ayın son günü (31 Mart → 28/29 Şubat)."""
    onceki = ay_ekle(ay_basi(d), -1)
    return date(onceki.year, onceki.month, min(d.day, ay_sonu(onceki).day))


def donemler(d: date) -> dict[str, tuple[date, date]]:
    p = onceki_ay_ayni_gun(d)
    return {"bugun": (d, d), "ay": (ay_basi(d), d), "onceki_gun": (p, p), "onceki_ay": (ay_basi(p), p)}


def kesimler(d: date) -> dict[str, date]:
    return {"bugun": d, "ay1": ay_sonu(d), "ay2": ay_sonu(ay_ekle(d, 1)), "ay3": ay_sonu(ay_ekle(d, 2))}


def yuzde_degisim(simdi: Decimal, onceki: Decimal) -> tuple[Decimal | None, str]:
    simdi, onceki = _d(simdi), _d(onceki)
    if onceki == 0:
        return None, "Değişim yok" if simdi == 0 else "Önceki dönem tutarı yok"
    if onceki < 0:
        return None, "Negatif karşılaştırma tabanı"
    return _q2((simdi - onceki) / onceki * 100), ""


def tahsilat_orani(tahsilat: Decimal, net_satis: Decimal) -> tuple[Decimal | None, str]:
    if _d(net_satis) <= 0:
        return None, ("Net satış sıfır; oran hesaplanmadı." if _d(net_satis) == 0
                      else "Net satış negatif; oran hesaplanmadı.")
    return _q2(_d(tahsilat) / _d(net_satis) * 100), ""


def _icinde(t: date | None, aralik: tuple[date, date]) -> bool:
    return t is not None and aralik[0] <= t <= aralik[1]


def kova_toplamlari(kalemler: list[dict], d: date) -> dict[str, Decimal]:
    """Birikimli sütunlar: vade ≤ kesim; Tamamı vadesizler dahil. Gecikmiş: vade < D."""
    k = kesimler(d)
    out = {s: SIFIR for s in SUTUNLAR}
    out.update(vadesiz=SIFIR, gecikmis=SIFIR)
    for x in kalemler:
        t = _d(x["tutar"])
        out["tamami"] += t
        v = x.get("vade")
        if v is None:
            out["vadesiz"] += t
            continue
        if v < d:
            out["gecikmis"] += t
        for s in ("bugun", "ay1", "ay2", "ay3"):
            if v <= k[s]:
                out[s] += t
    return {a: _q2(b) for a, b in out.items()}


def sutun_kalemleri(kalemler: list[dict], d: date, sutun: str) -> list[dict]:
    """Ayrıntı listesi: ekrandaki sütun toplamıyla aynı kapsam."""
    if sutun == "tamami":
        return list(kalemler)
    if sutun == "vadesiz":
        return [x for x in kalemler if x.get("vade") is None]
    if sutun == "gecikmis":
        return [x for x in kalemler if x.get("vade") is not None and x["vade"] < d]
    kesim = kesimler(d)[sutun]
    return [x for x in kalemler if x.get("vade") is not None and x["vade"] <= kesim]


def _bolum(durum: str = HAZIR, **veri) -> dict:
    veri.setdefault("uyarilar", [])
    veri.setdefault("notlar", [])
    veri["durum"] = durum
    return veri


def _kalem(kaynak: str, tutar, *, belge_no: str = "", tarih=None, cari: str = "", vade=None, aciklama: str = "",
           yontem: str = "", tahmini: bool = False, gercek_borc: bool = True, **ek) -> dict:
    return {"kaynak": kaynak, "belge_no": belge_no, "tarih": tarih, "cari": cari, "vade": vade,
            "tutar": _q2(tutar), "kalan": _q2(tutar), "aciklama": aciklama, "yontem": yontem,
            "tahmini": tahmini, "gercek_borc": gercek_borc, **ek}


# ----------------------------------------------------------------------------- yetki
def yetkiler() -> dict[str, bool]:
    from database.stok_rapor_service import maliyet_gorunur

    finans = yetki_var("finans_goruntuleme", "finans_duzenleme", "goruntuleme")
    stok = yetki_var("stok_goruntuleme", "stok_duzenleme")
    return {
        "satis": yetki_var("satis_goruntuleme", "satis_duzenleme", "goruntuleme"),
        "finans": finans,
        "cari": yetki_var("cari_goruntuleme", "cari_duzenleme", "goruntuleme") or finans,
        "stok": stok and maliyet_gorunur(),
    }


# ----------------------------------------------------------------------------- ortak yükleyiciler
class _Baglam:
    """Tek hesap turunda ortak kaynaklar (tek oturum; tekrar sorgu yok)."""

    def __init__(self, session, d: date, bugun: date, sube_id: int | None):
        from database.models.cari import Cari

        self.s = session
        self.d = d
        self.bugun = bugun
        self.sube_id = sube_id
        self.gecmis = d < bugun
        self.cariler = {}
        self.silinmis: set[int] = set()
        for i, kod, unvan, tur, silindi in session.execute(
                select(Cari.id, Cari.cari_kodu, Cari.unvan, Cari.cari_turu, Cari.is_deleted)).all():
            self.cariler[int(i)] = (kod or "", unvan or "", tur or "")
            if silindi:
                self.silinmis.add(int(i))
        self._hesaplar = None
        self._bakiye = None

    def cari_adi(self, cid) -> str:
        c = self.cariler.get(int(cid)) if cid is not None else None
        return c[1] if c else ""

    def cari_turu(self, cid) -> str:
        c = self.cariler.get(int(cid)) if cid is not None else None
        return c[2] if c else ""

    def musteri_mi(self, cid) -> bool:
        return self.cari_turu(cid) in MUSTERI_TURLERI

    def tedarikci_mi(self, cid) -> bool:
        return self.cari_turu(cid) in TEDARIKCI_TURLERI

    def hesaplar(self) -> dict[int, Any]:
        if self._hesaplar is None:
            from database.models.finans import FinansHesabi

            self._hesaplar = {int(h.id): h for h in self.s.scalars(select(FinansHesabi)).all()}
        return self._hesaplar

    def hesap_adi_haritasi(self) -> dict[str, Any]:
        return {(h.hesap_adi or "").strip().casefold(): h for h in self.hesaplar().values()}

    def finans_bakiyeleri(self) -> dict[int, Decimal]:
        """Hesap bazında D sonu bakiyesi (açılış + işaretli hareketler)."""
        if self._bakiye is None:
            from database.finans_service import FinansService
            from database.models.finans import FinansHareketi

            bak = {hid: _d(h.acilis_bakiyesi) for hid, h in self.hesaplar().items()}
            isaret: dict[str, int] = {}
            # Satır satır Numeric(18,2) dönüşümü: Finans ekranı bakiyesiyle kuruşu kuruşuna aynı sonuç
            for hid, tur, tutar in self.s.execute(
                    select(FinansHareketi.hesap_id, FinansHareketi.hareket_turu, FinansHareketi.tutar)
                    .where(FinansHareketi.tarih <= self.d)):
                if tur not in isaret:
                    isaret[tur] = FinansService.hareket_isareti(tur)
                bak[int(hid)] = bak.get(int(hid), SIFIR) + _d(tutar) * isaret[tur]
            self._bakiye = {k: _q2(v) for k, v in bak.items()}
        return self._bakiye


def hesap_sinifi(h) -> str:
    """KASA | POS | BANKA | KMH | BORC_HESABI (kredi kartı / krediler defteri)."""
    tur = (h.hesap_turu or "").upper()
    alt = (h.alt_hesap_turu or "").upper()
    if tur == "KASA":
        return "KASA"
    if alt == "POS" or (tur.startswith("KRED") and not alt):
        return "POS"
    if alt in ("KREDI_KARTI", "KREDILER"):
        return "BORC_HESABI"
    if alt == "KMH":
        return "KMH"
    return "BANKA"


def _hesap_yontemi(h) -> str | None:
    sinif = hesap_sinifi(h)
    return {"KASA": NAKIT, "POS": KART, "BANKA": HAVALE, "KMH": HAVALE}.get(sinif)


def _hesap_adindan_yontem(b: _Baglam, ad: str | None) -> str | None:
    metin = (ad or "").strip()
    if not metin:
        return None
    h = b.hesap_adi_haritasi().get(metin.casefold())
    if h is not None:
        return _hesap_yontemi(h)
    ust = metin.upper().replace("İ", "I")
    if "POS" in ust or "KART" in ust:
        return KART
    if "KASA" in ust or "NAKIT" in ust:
        return NAKIT
    if any(k in ust for k in ("KMH", "MEVDUAT", "BANKA", "HAVALE", "EFT", "A.S")):
        return HAVALE
    return None


# ----------------------------------------------------------------------------- satış
def satis_bolumu(b: _Baglam) -> dict:
    from database.belge_kdv import EKSIK as KDV_EKSIK
    from database.belge_kdv import belge_kdv, satis_faturasi_kdv
    from database.models.cari import CariIslem, SatisHareketi
    from database.models.satis_faturasi import SatisFaturasi
    from database.models.satis_iade_faturasi import SatisIadeFaturasi
    from database.satis_faturasi_service import SatisFaturasiService
    from database.satis_iade_faturasi_service import SatisIadeFaturasiService

    dn = donemler(b.d)
    bas, bit = dn["onceki_ay"][0], b.d
    uyarilar: list[str] = []
    haric = defaultdict(int)
    kalemler: list[dict] = []

    faturalar = b.s.scalars(
        select(SatisFaturasi).options(selectinload(SatisFaturasi.satirlar))
        .where(SatisFaturasi.fatura_tarihi >= bas, SatisFaturasi.fatura_tarihi <= bit)).all()
    kayitli = {bn: _d(t) for bn, t in b.s.execute(
        select(SatisHareketi.belge_no, SatisHareketi.satis_tutari)
        .where(SatisHareketi.satis_tarihi >= bas, SatisHareketi.satis_tarihi <= bit)).all()}
    for f in faturalar:
        if getattr(f, "is_deleted", False):
            haric["silinmiş"] += 1
            continue
        if (f.durum or "") == "İPTAL":
            haric["iptal"] += 1
            continue
        if not f.onaylandi:
            haric["taslak"] += 1
            continue
        if b.sube_id is not None and f.sube_id != b.sube_id:
            if f.sube_id is None:
                haric["şubesi boş"] += 1
            continue
        tutar = _d(SatisFaturasiService.net_toplam(f))
        pb = (f.para_birimi or "TRY").upper()
        aciklama = f"{pb} fatura — kayıtlı TL karşılığı (kur {_d(f.kur):f})" if pb != "TRY" else ""
        tutar = _q2(tutar)
        kdv = satis_faturasi_kdv(f)
        kdv_haric = None if kdv["durum"] == KDV_EKSIK else _q2(
            kdv["matrah"] + _d(getattr(f, "fon_ek_bedel_tutari", 0)))
        k = kayitli.get(f.fatura_no)
        if k is not None and abs(k - tutar) > TOLERANS:
            uyarilar.append(f"{f.fatura_no}: hesaplanan son tutar {_tl(tutar)}, cari kaydı {_tl(k)}.")
        kalemler.append(_kalem("Satış faturası", tutar, belge_no=f.fatura_no, tarih=f.fatura_tarihi,
                               cari=b.cari_adi(f.cari_id), aciklama=aciklama, tur="satis", kdv_haric=kdv_haric,
                               gercek_borc=False))

    iade_kayit = {bn: _d(a) for bn, a in b.s.execute(
        select(CariIslem.belge_no, func.sum(CariIslem.alacak)).where(
            CariIslem.islem_turu == "Satış İadesi", CariIslem.tarih >= bas, CariIslem.tarih <= bit)
        .group_by(CariIslem.belge_no)).all()}
    iadeler = b.s.scalars(
        select(SatisIadeFaturasi).options(selectinload(SatisIadeFaturasi.satirlar))
        .where(SatisIadeFaturasi.iade_tarihi >= bas, SatisIadeFaturasi.iade_tarihi <= bit)).all()
    for i in iadeler:
        if (i.durum or "") == "İPTAL" or getattr(i, "is_deleted", False):
            haric["iptal iade"] += 1
            continue
        if b.sube_id is not None and i.sube_id != b.sube_id:
            continue
        hesap = _q2(SatisIadeFaturasiService.toplam(i.satirlar)["genel_toplam"]
                    + SatisIadeFaturasiService.ek_fon_bedeli_toplami(i))
        tutar = iade_kayit.get(i.iade_no)
        if tutar is None:
            tutar = hesap
            uyarilar.append(f"{i.iade_no}: iadenin cari kaydı yok; iade servis toplamı kullanıldı.")
        elif abs(_q2(tutar) - hesap) > TOLERANS:
            uyarilar.append(f"{i.iade_no}: iade toplamı {_tl(hesap)}, cari kaydı {_tl(tutar)} (kayıtlı tutar esas).")
        kdv = belge_kdv(i, SatisIadeFaturasiService.toplam)
        kdv_haric = None if kdv["durum"] == KDV_EKSIK else _q2(
            kdv["matrah"] + _d(getattr(i, "fon_ek_bedel_tutari", 0)))
        kalemler.append(_kalem("Satış iadesi", -_d(tutar), belge_no=i.iade_no, tarih=i.iade_tarihi,
                               cari=b.cari_adi(i.cari_id), tur="iade",
                               kdv_haric=None if kdv_haric is None else -kdv_haric, gercek_borc=False))

    def say(aralik):
        sec = [x for x in kalemler if _icinde(x["tarih"], aralik)]
        sat = [x for x in sec if x["tur"] == "satis"]
        ida = [x for x in sec if x["tur"] == "iade"]
        kdv_bilinmeyen = sum(1 for x in sec if x["kdv_haric"] is None)
        return {
            "belge_adedi": len(sat), "satis_tutari": _q2(sum((x["tutar"] for x in sat), SIFIR)),
            "iade_adedi": len(ida), "iade_tutari": _q2(-sum((x["tutar"] for x in ida), SIFIR)),
            "net": _q2(sum((x["tutar"] for x in sec), SIFIR)),
            "kdv_haric_net": _q2(sum((x["kdv_haric"] for x in sec if x["kdv_haric"] is not None), SIFIR)),
            "kdv_bilinmeyen": kdv_bilinmeyen,
        }

    satirlar = {}
    for ad, simdi, onceki in (("bugun", "bugun", "onceki_gun"), ("ay", "ay", "onceki_ay")):
        o, p = say(dn[simdi]), say(dn[onceki])
        yuzde, mesaj = yuzde_degisim(o["net"], p["net"])
        satirlar[ad] = {**o, "onceki_net": p["net"], "fark": _q2(o["net"] - p["net"]), "yuzde": yuzde,
                        "yuzde_mesaj": mesaj, "aralik": dn[simdi], "onceki_aralik": dn[onceki],
                        "onceki": p}
    notlar = [
        f"Karşılaştırma: {dn['bugun'][0]:%d.%m.%Y} ↔ {dn['onceki_gun'][0]:%d.%m.%Y}; "
        f"{dn['ay'][0]:%d.%m.%Y}–{dn['ay'][1]:%d.%m.%Y} ↔ {dn['onceki_ay'][0]:%d.%m.%Y}–{dn['onceki_ay'][1]:%d.%m.%Y}.",
        "Tutarlar KDV dahil, indirim / masraf / yuvarlama sonrası son tutar; iade kendi tarihinde düşülür.",
    ]
    if haric:
        notlar.append("Kapsam dışı: " + ", ".join(f"{v} {k}" for k, v in sorted(haric.items())) + " belge.")
    if b.sube_id is not None and haric.get("şubesi boş"):
        uyarilar.append(f"Şubesi boş {haric['şubesi boş']} satış belgesi seçili şubeye dahil edilmedi.")
    if any(satirlar[a]["kdv_bilinmeyen"] for a in satirlar):
        notlar.append("KDV'si belirlenemeyen belgeler KDV hariç net ciroya katılmadı (Bilinen tutarlar).")
    durum = HAZIR if kalemler else BOS
    return _bolum(durum, satirlar=satirlar, kalemler=kalemler, uyarilar=uyarilar, notlar=notlar,
                  gun_devam=b.d == b.bugun)


# ----------------------------------------------------------------------------- tahsilat
def tahsilat_bolumu(b: _Baglam, net_satis: dict[str, Decimal] | None) -> dict:
    from database.models.cari import CariIslem
    from database.models.finans import CariVirmanMakbuzu, FinansHareketi, KasaMakbuzu
    from database.models.kk_cekimi import KkCekimi
    from database.models.satis_faturasi import SatisFaturasi
    from database.models.satis_iade_faturasi import SatisIadeFaturasi

    dn = donemler(b.d)
    bas, bit = dn["onceki_ay"][0], b.d
    uyarilar: list[str] = []
    notlar: list[str] = []
    hesaplar = b.hesaplar()

    islemler = b.s.execute(
        select(CariIslem.belge_no, CariIslem.cari_id, CariIslem.tarih, CariIslem.islem_turu, CariIslem.borc,
               CariIslem.alacak, CariIslem.hesap_adi)
        .where(CariIslem.tarih >= bas, CariIslem.tarih <= bit)).all()
    tum_cari_belge = {bn for bn, *_ in islemler}
    hareketler = b.s.execute(
        select(FinansHareketi.belge_no, FinansHareketi.hesap_id, FinansHareketi.tarih, FinansHareketi.hareket_turu,
               FinansHareketi.tutar, FinansHareketi.sube_id)
        .where(FinansHareketi.tarih >= bas, FinansHareketi.tarih <= bit,
               FinansHareketi.hareket_turu.in_(TAHSILAT_FH + IADE_ODEME_FH))).all()
    fh_by = defaultdict(list)
    for h in hareketler:
        fh_by[h.belge_no].append(h)
    makbuz_sube = {bn: sid for bn, sid in b.s.execute(
        select(KasaMakbuzu.belge_no, KasaMakbuzu.sube_id).where(KasaMakbuzu.tarih >= bas,
                                                                KasaMakbuzu.tarih <= bit)).all()}
    fatura_bilgi = {no: (cid, sid) for no, cid, sid in b.s.execute(
        select(SatisFaturasi.fatura_no, SatisFaturasi.cari_id, SatisFaturasi.sube_id)
        .where(SatisFaturasi.fatura_no.in_([h.belge_no for h in hareketler
                                            if h.hareket_turu == "FATURA TAHSİLATI"] or [""]))).all()}
    iade_bilgi = {no: (cid, sid) for no, cid, sid in b.s.execute(
        select(SatisIadeFaturasi.iade_no, SatisIadeFaturasi.cari_id, SatisIadeFaturasi.sube_id)
        .where(SatisIadeFaturasi.iade_no.in_([h.belge_no for h in hareketler
                                               if h.hareket_turu == "SATIŞ İADE ÖDEMESİ"] or [""]))).all()}

    # (belge, tarih, cari, yöntem, tutar, kaynak, şube)
    satirlar: list[dict] = []
    subesi_belirsiz = 0

    def sube_uygun(sid) -> bool:
        nonlocal subesi_belirsiz
        if b.sube_id is None:
            return True
        if sid is None:
            subesi_belirsiz += 1
            return False
        return int(sid) == int(b.sube_id)

    def bacaklardan(belge, tarih, cari_id, toplam, hesap_adi, isaret, kaynak, sube):
        legs = fh_by.get(belge) or []
        legs = [h for h in legs if (h.hareket_turu in TAHSILAT_FH) == (isaret > 0)]
        if legs:
            for h in legs:
                hs = hesaplar.get(int(h.hesap_id))
                yontem = KART if h.hareket_turu == "POS TAHSİLAT" else (_hesap_yontemi(hs) if hs else None)
                satirlar.append(_kalem(kaynak, isaret * _d(h.tutar), belge_no=belge, tarih=h.tarih,
                                       cari=b.cari_adi(cari_id), yontem=yontem or BELIRSIZ,
                                       aciklama=getattr(hs, "hesap_adi", "") or "", gercek_borc=False))
            fark = _q2(_d(toplam) - sum((_d(h.tutar) for h in legs), SIFIR))
            if toplam is not None and abs(fark) > TOLERANS:
                uyarilar.append(f"{belge}: cari tutarı ile kasa / banka hareketleri arasında {_tl(fark)} fark.")
            return
        yontem = _hesap_adindan_yontem(b, hesap_adi)
        satirlar.append(_kalem(kaynak, isaret * _d(toplam), belge_no=belge, tarih=tarih, cari=b.cari_adi(cari_id),
                               yontem=yontem or BELIRSIZ, aciklama=hesap_adi or "Kasa / banka hareketi yok",
                               gercek_borc=False))

    # 1) Müşteri cari tahsilatları (makbuz, havale, POS, Evo aktarımı) ve tahsilat iadeleri
    belge_top: dict[tuple[str, str], list] = {}
    for bn, cid, tarih, tur, borc, alacak, hesap_adi in islemler:
        if not b.musteri_mi(cid):
            continue
        if tur == "Tahsilat" and _d(alacak) > 0:
            anahtar = ("T", bn)
        elif tur == "Ödeme" and _d(borc) > 0:
            anahtar = ("I", bn)
        else:
            continue
        kay = belge_top.setdefault(anahtar, [tarih, cid, SIFIR, hesap_adi])
        kay[2] += _d(alacak) if anahtar[0] == "T" else _d(borc)
    cek_alinan = []
    for (tip, bn), (tarih, cid, toplam, hesap_adi) in sorted(belge_top.items(), key=lambda x: (x[1][0], x[0][1])):
        sube = makbuz_sube.get(bn)
        if sube is None:
            legs = fh_by.get(bn) or []
            sube = next((h.sube_id for h in legs if h.sube_id is not None), None)
        if not sube_uygun(sube):
            continue
        if tip == "T" and bn.startswith("ACS-"):
            cek_alinan.append(_kalem(CEK_ALINAN, toplam, belge_no=bn, tarih=tarih, cari=b.cari_adi(cid),
                                     yontem=CEK_ALINAN, gercek_borc=False))
            continue
        if tip == "T":
            bacaklardan(bn, tarih, cid, toplam, hesap_adi, 1, "Tahsilat", sube)
        else:
            bacaklardan(bn, tarih, cid, toplam, hesap_adi, -1, "Tahsilat iadesi", sube)

    # 2) Fatura içi tahsilat, iade ödemesi ve cariye bağlanmamış POS tahsilatı
    for bn, legs in fh_by.items():
        if bn in tum_cari_belge:
            continue
        for h in legs:
            hs = hesaplar.get(int(h.hesap_id))
            if h.hareket_turu == "FATURA TAHSİLATI":
                cid, sid = fatura_bilgi.get(bn, (None, h.sube_id))
                if not sube_uygun(sid if sid is not None else h.sube_id):
                    continue
                satirlar.append(_kalem("Fatura tahsilatı", h.tutar, belge_no=bn, tarih=h.tarih,
                                       cari=b.cari_adi(cid), yontem=(_hesap_yontemi(hs) if hs else None) or BELIRSIZ,
                                       aciklama=getattr(hs, "hesap_adi", ""), gercek_borc=False))
            elif h.hareket_turu == "SATIŞ İADE ÖDEMESİ":
                cid, sid = iade_bilgi.get(bn, (None, h.sube_id))
                if not sube_uygun(sid if sid is not None else h.sube_id):
                    continue
                satirlar.append(_kalem("Tahsilat iadesi", -_d(h.tutar), belge_no=bn, tarih=h.tarih,
                                       cari=b.cari_adi(cid), yontem=(_hesap_yontemi(hs) if hs else None) or BELIRSIZ,
                                       aciklama="Satış iadesi ödemesi", gercek_borc=False))
            elif h.hareket_turu == "POS TAHSİLAT" and bn not in makbuz_sube:
                if not sube_uygun(h.sube_id):
                    continue
                satirlar.append(_kalem("POS tahsilatı", h.tutar, belge_no=bn, tarih=h.tarih, yontem=KART,
                                       aciklama="Cari bağlantısı yok", gercek_borc=False))

    # 3) Cari virman (müşteriler arası; tek bacak) ve müşteriden tedarikçiye doğrudan ödeme
    virmanlar = []
    for bn, cid, tarih, tur, borc, alacak, _h in islemler:
        if tur == "Cari Virman" and _d(alacak) > 0 and b.musteri_mi(cid) and b.sube_id is None:
            virmanlar.append(_kalem(VIRMAN, alacak, belge_no=bn, tarih=tarih, cari=b.cari_adi(cid), yontem=VIRMAN,
                                    gercek_borc=False))
    mus_ted = []
    for m in b.s.scalars(select(CariVirmanMakbuzu).where(
            CariVirmanMakbuzu.tarih >= bas, CariVirmanMakbuzu.tarih <= bit)).all():
        if (m.durum or "").upper() == "IPTAL" or not sube_uygun(m.sube_id):
            continue
        mus_ted.append(_kalem(MUS_TED, m.tutar, belge_no=m.makbuz_no or m.belge_no, tarih=m.tarih,
                              cari=b.cari_adi(m.musteri_id), yontem="Cari virman makbuzu",
                              aciklama=f"Tedarikçi: {b.cari_adi(m.tedarikci_id)}", gercek_borc=False))
    if b.sube_id is None:
        for k in b.s.scalars(select(KkCekimi).where(KkCekimi.tarih >= bas, KkCekimi.tarih <= bit)).all():
            if (k.durum or "") == "İPTAL":
                continue
            mus_ted.append(_kalem(MUS_TED, k.tutar, belge_no=k.belge_no, tarih=k.tarih,
                                  cari=b.cari_adi(k.musteri_id), yontem="Müşteri kartıyla tedarikçiye çekim",
                                  aciklama=f"Tedarikçi: {b.cari_adi(k.tedarikci_id)}", gercek_borc=False))

    def say(aralik, liste, yontem=None):
        sec = [x for x in liste if _icinde(x["tarih"], aralik) and (yontem is None or x["yontem"] == yontem)]
        belgeler = {x["belge_no"] for x in sec if x["tutar"] > 0}
        return {"adet": len(belgeler), "tutar": _q2(sum((x["tutar"] for x in sec), SIFIR))}

    gercek = [x for x in satirlar if x["yontem"] in GERCEK_YONTEMLER]
    tur_satirlari = []
    for ad, liste, yontem in ((NAKIT, gercek, NAKIT), (HAVALE, gercek, HAVALE), (KART, gercek, KART),
                              (VIRMAN, virmanlar, None), (MUS_TED, mus_ted, None)):
        tur_satirlari.append({"tur": ad, "bugun": say(dn["bugun"], liste, yontem),
                              "ay": say(dn["ay"], liste, yontem)})
    toplam = {}
    for ad, simdi, onceki in (("bugun", "bugun", "onceki_gun"), ("ay", "ay", "onceki_ay")):
        o, p = say(dn[simdi], gercek), say(dn[onceki], gercek)
        yuzde, mesaj = yuzde_degisim(o["tutar"], p["tutar"])
        oran, oran_mesaj = (tahsilat_orani(o["tutar"], net_satis[ad]) if net_satis is not None
                            else (None, "Satış özeti görüntülenemiyor."))
        toplam[ad] = {**o, "onceki_adet": p["adet"], "onceki_tutar": p["tutar"], "fark": _q2(o["tutar"] - p["tutar"]),
                      "yuzde": yuzde, "yuzde_mesaj": mesaj, "oran": oran, "oran_mesaj": oran_mesaj}
    belirsiz = [x for x in satirlar if x["yontem"] == BELIRSIZ and _icinde(x["tarih"], dn["ay"])]
    if belirsiz:
        uyarilar.append(f"Yöntemi belirlenemeyen {len({x['belge_no'] for x in belirsiz})} belge "
                        f"({_tl(sum((x['tutar'] for x in belirsiz), SIFIR))}) gerçek tahsilata katılmadı.")
    cek_ay = [x for x in cek_alinan if _icinde(x["tarih"], dn["ay"])]
    if cek_ay:
        notlar.append(f"Alınan çek / senet ({len(cek_ay)} belge, {_tl(sum((x['tutar'] for x in cek_ay), SIFIR))}) "
                      "para girişi değildir; tahsil edildiğinde kasa / bankaya girer.")
    if subesi_belirsiz:
        uyarilar.append(f"Şubesi belirlenemeyen {subesi_belirsiz} tahsilat hareketi seçili şubeye dahil edilmedi "
                        "(cari tahsilat ve Evo aktarımı kayıtlarında şube alanı yok).")
    if b.sube_id is not None:
        notlar.append("Cari virman ve kartla tedarikçiye çekim kayıtlarında şube alanı olmadığından şube filtresinde "
                      "gösterilmez.")
    notlar.append("Bir makbuz birden çok yöntemle ödenmişse her yöntem satırında görünür; Gerçek tahsilat "
                  "adedi tekil belge sayısıdır. İç virman, kredi kullanımı, POS'tan bankaya aktarım ve tedarikçi "
                  "iadesi dahil edilmez. Oran önceki borçlara gelen tahsilatlar nedeniyle %100'ü aşabilir.")
    tum = gercek + [x for x in satirlar if x["yontem"] not in GERCEK_YONTEMLER] + cek_alinan + virmanlar + mus_ted
    durum = HAZIR if tum else BOS
    return _bolum(durum, turler=tur_satirlari, toplam=toplam, kalemler=satirlar, gercek=gercek,
                  virmanlar=virmanlar, mus_ted=mus_ted, cek_alinan=cek_alinan,
                  uyarilar=uyarilar, notlar=notlar)


# ----------------------------------------------------------------------------- cari bakiyeleri
def cari_bakiyeleri(b: _Baglam) -> tuple[dict[int, Decimal], list[str]]:
    """D sonu cari net bakiye (pozitif: müşteri borçlu / tedarikçiye borçluyuz).

    Formül cari listesiyle aynı. Fatura içi tahsilat / ödeme (FATURA TAHSİLATI, FATURA ÖDEMESİ, SATIŞ İADE
    ÖDEMESİ) cariye ayrı satır yazmaz; tutarı yalnızca "bilinen fark" notu olarak bildirilir.
    """
    from database.cari_bakiye_service import _DEFTER_ATLA_ONEK
    from database.models.alis_faturasi import AlisFaturasi
    from database.models.cari import CariIslem, SatisHareketi
    from database.models.finans import FinansHareketi
    from database.models.satis_faturasi import SatisFaturasi
    from database.models.satis_iade_faturasi import SatisIadeFaturasi

    d = b.d
    bak: dict[int, Decimal] = defaultdict(lambda: SIFIR)
    for cid, borc, alacak in b.s.execute(
            select(CariIslem.cari_id, func.sum(func.round(CariIslem.borc, 2)),
                   func.sum(func.round(CariIslem.alacak, 2)))
            .where(CariIslem.tarih <= d).group_by(CariIslem.cari_id)).all():
        bak[int(cid)] += _d(str(borc or 0)) - _d(str(alacak or 0))
    islem_belge = {(int(c), bn or "") for c, bn in b.s.execute(
        select(CariIslem.cari_id, CariIslem.belge_no).distinct()).all()}
    doviz = 0
    for cid, bn, t, tutar, pb in b.s.execute(
            select(SatisHareketi.cari_id, SatisHareketi.belge_no, SatisHareketi.satis_tarihi,
                   SatisHareketi.satis_tutari, SatisHareketi.para_birimi)).all():
        bn = bn or ""
        if (int(cid), bn) in islem_belge or bn.startswith(_DEFTER_ATLA_ONEK) or t is None or t > d:
            continue
        if (pb or "TRY").upper() != "TRY":
            doviz += 1
        bak[int(cid)] += _d(tutar)

    fark: dict[int, Decimal] = defaultdict(lambda: SIFIR)
    fark_belge = 0
    fh = b.s.execute(select(FinansHareketi.belge_no, FinansHareketi.hareket_turu,
                            func.sum(func.round(FinansHareketi.tutar, 2)))
                     .where(FinansHareketi.tarih <= d,
                            FinansHareketi.hareket_turu.in_(("FATURA TAHSİLATI", "FATURA ÖDEMESİ",
                                                             "SATIŞ İADE ÖDEMESİ")))
                     .group_by(FinansHareketi.belge_no, FinansHareketi.hareket_turu)).all()
    if fh:
        sat = dict(b.s.execute(select(SatisFaturasi.fatura_no, SatisFaturasi.cari_id)).all())
        alis = dict(b.s.execute(select(AlisFaturasi.fatura_no, AlisFaturasi.cari_id)).all())
        iade = dict(b.s.execute(select(SatisIadeFaturasi.iade_no, SatisIadeFaturasi.cari_id)).all())
        for bn, tur, top in fh:
            cid, isaret = {"FATURA TAHSİLATI": (sat.get(bn), -1), "FATURA ÖDEMESİ": (alis.get(bn), -1),
                           "SATIŞ İADE ÖDEMESİ": (iade.get(bn), 1)}[tur]
            if cid is not None:
                fark[int(cid)] += isaret * _d(str(top))
                fark_belge += 1
    notlar = []
    if fark:
        notlar.append(f"Bilinen fark: fatura içinde tahsil / ödeme edilen {fark_belge} belge "
                      f"({len(fark)} cari, net {_tl(sum(fark.values(), SIFIR))}) cari kartına ayrı satır "
                      f"yazmıyor. Bakiyeler cari listesiyle aynı tutuldu; tahsilat başka makbuzla da "
                      f"girilmiş olabileceğinden otomatik düzeltme yapılmadı.")
    if doviz:
        notlar.append(f"{doviz} dövizli cari hareket kayıtlı TL tutarıyla alındı (D tarihli kur değerlemesi yok).")
    return {k: _q2(v) for k, v in bak.items()}, notlar


# ----------------------------------------------------------------------------- ödeme takvimi ve borçlar
def _kredi_kalemleri(b: _Baglam) -> tuple[list[dict], Decimal, list[str]]:
    from database.banka_kredi_service import BankaKrediService
    from database.models.finans import BankaKredisi

    kalemler, borc, uyarilar = [], SIFIR, []
    for k in b.s.scalars(select(BankaKredisi).options(selectinload(BankaKredisi.taksitler))
                         .where(BankaKredisi.durum == "KULLANDIRILDI")).all():
        pb = (k.para_birimi or "TRY").upper()
        kur = SIFIR if pb != "TRY" else Decimal("1")
        if pb != "TRY":
            kur = _d(k.kur)
            if kur <= 0:
                uyarilar.append(f"{k.belge_no}: {pb} kredi için kur kaydı yok; hesaba katılmadı.")
                continue
            uyarilar.append(f"{k.belge_no}: {pb} kredi kayıtlı kullandırım kuruyla TL'ye çevrildi.")
        tahakkuk = SIFIR
        for t in k.taksitler or []:
            kalan = _d(BankaKrediService._taksit_kalan(t))
            if kalan <= 0:
                continue
            bil = BankaKrediService.taksit_bilesenleri(t)
            ana_kalan = max(SIFIR, _d(bil.get("anapara")) - _d(t.odenen_anapara))
            if t.vade_tarihi <= b.d:
                tahakkuk += max(SIFIR, kalan - ana_kalan)
            kalemler.append(_kalem(TAKVIM_ADI[KREDI], kalan * kur, belge_no=k.belge_no, vade=t.vade_tarihi,
                                   cari=k.kredi_adi, aciklama=f"Taksit {t.taksit_no}", tarih=t.vade_tarihi))
        borc += (_d(BankaKrediService._kalan_anapara(b.s, k)) + tahakkuk) * kur
    return kalemler, _q2(borc), uyarilar


def _kart_kalemleri(b: _Baglam) -> tuple[list[dict], Decimal, list[str]]:
    from database.kredi_karti_ekstre_service import KrediKartiEkstreService
    from database.models.finans import (
        KrediKartiEkstre,
        KrediKartiEkstreOdeme,
        KrediKartiOdeme,
        KrediKartiTanimi,
    )

    kartlar = {int(k.id): k for k in b.s.scalars(select(KrediKartiTanimi)).all()}
    donem: dict[tuple[int, date], dict] = {}
    for o in b.s.scalars(select(KrediKartiOdeme).options(selectinload(KrediKartiOdeme.taksitler))
                         .where(KrediKartiOdeme.durum != "İPTAL", KrediKartiOdeme.tarih <= b.d)).all():
        kart = kartlar.get(int(o.kredi_karti_id))
        if kart is None:
            continue
        for t in o.taksitler or []:
            bil = KrediKartiEkstreService.taksit_donem_bilgisi(o.tarih, t.taksit_no, kart)
            g = donem.setdefault((int(kart.id), bil["kesim_tarihi"]), {
                "son_odeme": bil["son_odeme_tarihi"], "toplam": SIFIR, "bekleyen": SIFIR, "belgeler": set()})
            g["toplam"] += _d(t.tutar)
            if (t.durum or "") != "ODENDI":
                g["bekleyen"] += _d(t.tutar)
            g["belgeler"].add(o.belge_no)
    odenen: dict[tuple[int, date], Decimal] = defaultdict(lambda: SIFIR)
    for kid, kesim, tutar in b.s.execute(
            select(KrediKartiEkstre.kredi_karti_id, KrediKartiEkstre.kesim_tarihi, KrediKartiEkstreOdeme.tutar)
            .join(KrediKartiEkstreOdeme, KrediKartiEkstreOdeme.ekstre_id == KrediKartiEkstre.id)
            .where(KrediKartiEkstreOdeme.iptal.is_(False), KrediKartiEkstreOdeme.tarih <= b.d)).all():
        odenen[(int(kid), kesim)] += _d(tutar)
    kalemler, borc = [], SIFIR
    for (kid, kesim), g in sorted(donem.items(), key=lambda x: x[1]["son_odeme"]):
        kalan = min(g["bekleyen"], max(SIFIR, g["toplam"] - odenen.get((kid, kesim), SIFIR)))
        if kalan <= 0:
            continue
        kart = kartlar[kid]
        borc += kalan
        durum = "kesime girmedi" if kesim > b.d else "ekstre"
        kalemler.append(_kalem(TAKVIM_ADI[KK], kalan, belge_no=", ".join(sorted(g["belgeler"]))[:120],
                               vade=g["son_odeme"], tarih=kesim, cari=kart.kart_adi,
                               aciklama=f"Kesim {kesim:%d.%m.%Y} ({durum})"))
    return kalemler, _q2(borc), []


def tedarikci_acik_bolumu(b: _Baglam, bakiyeler: dict[int, Decimal] | None, cari_notlari: list[str]) -> dict:
    """Bugün itibarıyla borçlu olunan tedarikçi cari bakiyeleri (cari listesi formülü).

    Alacaklı olunan tedarikçi (avans) başka tedarikçinin borcunu düşürmez; silinmiş cari katılmaz.
    """
    if bakiyeler is None:
        return _bolum(HATA, mesaj="; ".join(cari_notlari) or "Cari bakiyeleri hesaplanamadı.", tarih=b.d)
    kalemler = []
    for cid, bakiye in bakiyeler.items():
        if bakiye <= 0 or cid in b.silinmis or not b.tedarikci_mi(cid):
            continue
        kod, ad, _tur = b.cariler[cid]
        kalemler.append(_kalem(TEDARIKCI_ACIK, bakiye, belge_no=kod, tarih=b.d, cari=ad, cari_id=cid,
                               aciklama="Açık cari borç bakiyesi"))
    kalemler.sort(key=lambda x: -x["tutar"])
    notlar = ["Rapor tarihinden bağımsız, bugünün cari bakiyesidir; ödeme yüküne eklenmez. Alacaklı olunan "
              "tedarikçi bakiyesi toplam borçtan düşülmez."] + list(cari_notlari)
    if b.sube_id is not None:
        notlar.append("Cari kayıtlarında şube alanı olmadığından şube filtresi uygulanmaz.")
    return _bolum(HAZIR if kalemler else BOS, tarih=b.d, kalemler=kalemler, adet=len(kalemler),
                  toplam=_q2(sum((x["tutar"] for x in kalemler), SIFIR)), notlar=notlar)


def borc_bolumu(b: _Baglam, bakiyeler: dict[int, Decimal] | None, cari_notlari: list[str]) -> dict:
    from database.models.cek_senet import CekSenetEvrak

    uyarilar: list[str] = []
    notlar: list[str] = list(cari_notlari)
    eksik: list[str] = []
    kalemler: list[dict] = []
    satir_durum: dict[str, str] = {}
    borc: dict[str, Decimal | None] = {}

    # Kasa / banka kaynaklı borçlar (D itibarıyla; tarihsel hesaplanabilir)
    hesaplar = b.hesaplar()
    for hid, bakiye in b.finans_bakiyeleri().items():
        h = hesaplar[hid]
        sinif = hesap_sinifi(h)
        if bakiye >= 0 or sinif in ("KASA", "POS", "BORC_HESABI"):
            continue
        if sinif == "KMH":
            kalemler.append(_kalem(TAKVIM_ADI[KMH], -bakiye, belge_no=h.hesap_adi, vade=ay_sonu(b.d),
                                   cari=h.banka_adi or "", aciklama="Kullanılan KMH — planlama tarihi ay sonu",
                                   satir=KMH))
        else:
            kalemler.append(_kalem("Diğer banka borçları", -bakiye, belge_no=h.hesap_adi, vade=None,
                                   cari=h.banka_adi or "", aciklama="Eksi mevduat bakiyesi; KMH kaynağı yok",
                                   satir=DIGER))
    satir_durum[KMH] = HAZIR
    borc["kmh"] = _q2(sum((k["tutar"] for k in kalemler if k.get("satir") == KMH), SIFIR))
    borc["diger_banka"] = _q2(sum((k["tutar"] for k in kalemler if k.get("satir") == DIGER), SIFIR))
    eksi_mevduat = sum(1 for k in kalemler if k.get("satir") == DIGER)
    if eksi_mevduat:
        uyarilar.append(f"Doğrulanamayan kaynak: {eksi_mevduat} banka hesabı eksi bakiyede "
                        f"(toplam {_tl(borc['diger_banka'])}). Finans ekranındaki bakiyeyle aynıdır; KMH / kredi "
                        f"kaynağı bulunamadığı için vadesiz 'Diğer banka borçları' olarak gösterildi. Açılış "
                        f"bakiyeleri ve aktarılan hareketler kontrol edilmeli.")
    if any(k.get("satir") == KMH for k in kalemler):
        notlar.append("KMH: kullanılan tutar bu ay sonuna planlandı (yalnız gösterim tarihi); kayıtlı KMH faizi "
                      "kaynağı yok, kullanılmamış limit varlık sayılmaz.")

    def kaynak(ad, fn):
        if b.gecmis:
            satir_durum[ad] = TARIHSEL_YOK
            eksik.append(TAKVIM_ADI[ad])
            return None
        try:
            return fn()
        except Exception as hata:  # noqa: BLE001
            satir_durum[ad] = HATA
            eksik.append(TAKVIM_ADI[ad])
            uyarilar.append(f"{TAKVIM_ADI[ad]}: {hata}")
            return None

    r = kaynak(KREDI, lambda: _kredi_kalemleri(b))
    if r is not None:
        kalemler += [{**k, "satir": KREDI} for k in r[0]]
        borc["kredi"] = r[1]
        uyarilar += r[2]
        satir_durum[KREDI] = HAZIR
    else:
        borc["kredi"] = None
    r = kaynak(KK, lambda: _kart_kalemleri(b))
    if r is not None:
        kalemler += [{**k, "satir": KK} for k in r[0]]
        borc["kart"] = r[1]
        satir_durum[KK] = HAZIR
    else:
        borc["kart"] = None

    if bakiyeler is None:
        borc["musteri_avans"] = None
        eksik.append("Müşteri avansları")
    else:
        borc["musteri_avans"] = _q2(-sum((v for c, v in bakiyeler.items() if v < 0 and b.musteri_mi(c)), SIFIR))

    def sabit():
        from database import sabit_gider_service as sg

        if not sg.okuma_izni():
            satir_durum[SABIT] = YETKISIZ
            return []
        return [x for x in sg.takvim_kalemleri(b.s, b.d)]

    sabit_donemler = kaynak(SABIT, sabit) or []
    if satir_durum.get(SABIT) is None and not b.gecmis:
        satir_durum[SABIT] = HAZIR
    sabit_bagli = []
    for x in sabit_donemler:
        if x["kalan"] > 0:
            kalemler.append(_kalem(TAKVIM_ADI[SABIT], x["kalan"], belge_no=f"{x['yil']}-{x['ay']:02d}",
                                   vade=x["vade"], cari=x["plan_adi"], tahmini=x["tahmini"], gercek_borc=False,
                                   aciklama=f"{x['kategori_adi']} · dönem {x['ay']:02d}.{x['yil']}"
                                            + (" · tahmini" if x["tahmini"] else ""),
                                   satir=SABIT, kategori=x["kategori_adi"], donem_id=x["donem_id"]))
        if x["faturaya_bagli"] > 0:
            sabit_bagli.append(x)

    def cekler():
        out = []
        for e in b.s.scalars(select(CekSenetEvrak).where(CekSenetEvrak.islem_yonu == "VERILEN",
                                                         CekSenetEvrak.durum.in_(VERILEN_CEK_ACIK))).all():
            if _d(e.kalan_tutar) > 0:
                out.append(_kalem("Verilen çek / senet", e.kalan_tutar, belge_no=e.portfoy_no, vade=e.vade_tarihi,
                                  tarih=e.duzenleme_tarihi, cari=b.cari_adi(e.cari_id), satir=DIGER,
                                  aciklama=f"{e.evrak_no} · {e.durum}"))
        return out

    cek = kaynak(DIGER, cekler)
    if cek is not None:
        kalemler += cek
        satir_durum.setdefault(DIGER, HAZIR)
        borc["cek"] = _q2(sum((k["tutar"] for k in cek), SIFIR))
    else:
        borc["cek"] = None

    d = b.d
    satirlar = []
    for kod, ad in TAKVIM_SATIRLARI:
        sec = [k for k in kalemler if k.get("satir") == kod]
        satirlar.append({"kod": kod, "ad": ad, "durum": satir_durum.get(kod, HAZIR),
                         **kova_toplamlari(sec, d), "adet": len(sec)})
    toplam = kova_toplamlari(kalemler, d)
    planlanan_ek = kova_toplamlari([k for k in kalemler if not k["gercek_borc"]], d)

    borc_satirlari = [
        ("Kredi borcu (kalan anapara + vadesi gelmiş faiz)", borc.get("kredi")),
        ("Kredi kartı borcu", borc.get("kart")),
        ("KMH kullanılan tutar", borc.get("kmh")),
        ("Müşteri avansları", borc.get("musteri_avans")),
        ("Verilen çek / senet", borc.get("cek")),
        ("Diğer banka borçları", borc.get("diger_banka")),
    ]
    gercek_borc = None if any(v is None for _a, v in borc_satirlari) else _q2(
        sum((v for _a, v in borc_satirlari), SIFIR))
    bilinen_borc = _q2(sum((v for _a, v in borc_satirlari if v is not None), SIFIR))

    if toplam["vadesiz"] > 0:
        uyarilar.append(f"Vadesiz tutar {_tl(toplam['vadesiz'])} tarih sütunlarına dağıtılmadı; yalnız Tamamı'nda.")
    if any(k["tahmini"] for k in kalemler):
        notlar.append("Sabit gider ödemelerinde tahmini tutar var; ödeme yükü tahmin içerir.")
    if sabit_donemler and not b.gecmis:
        aylar = sorted({(x["yil"], x["ay"]) for x in sabit_donemler})
        notlar.append("Sabit gider planlanan aylar: " + ", ".join(f"{a:02d}.{y}" for y, a in aylar)
                      + ". Üçüncü aydan sonrası üretilmez; Tamamı kayıtlı kapsamdır.")
    if sabit_bagli:
        notlar.append("Faturası oluşmuş sabit gider dönemleri bu tabloda değil, tedarikçi açık borcunda izlenir: "
                      + ", ".join(f"{x['plan_adi']} {x['ay']:02d}.{x['yil']} ({_tl(x['faturaya_bagli'])})"
                                  for x in sabit_bagli[:5]))
    notlar.append("Tedarikçi açık cari borcu bu tabloya ve ödeme yükü toplamlarına eklenmez; ayrı başlıkta "
                  "gösterilir. Tedarikçiye verilen çek / senet 'Diğer kayıtlı ödemeler'de kalır.")
    notlar.append("Müşteriden alınıp ciro edilen çeklerin şarta bağlı riski borca eklenmez.")
    if b.gecmis:
        notlar.append("Geçmiş tarihte kredi, kart, çek ve sabit gider planı güncel durumdan hesaplanır; bu "
                      "satırlar 'Geçmiş bakiye hesaplanamıyor' olarak bırakıldı.")
    durum = HAZIR if not eksik else EKSIK
    if b.gecmis:
        durum = TARIHSEL_YOK
    return _bolum(durum, satirlar=satirlar, toplam=toplam, planlanan_ek=planlanan_ek, kalemler=kalemler,
                  borc_satirlari=borc_satirlari,
                  gercek_borc=gercek_borc, bilinen_borc=bilinen_borc, eksik=eksik, uyarilar=uyarilar,
                  notlar=notlar, sabit_donemler=sabit_donemler)


# ----------------------------------------------------------------------------- varlıklar
def _hesap_varliklari(b: _Baglam) -> tuple[Decimal, Decimal, list[dict], list[str]]:
    """Kasa ve mevduat toplamı, bankaya geçmemiş POS, kalemler ve uyarılar (D sonu bakiyeleri)."""
    uyarilar = []
    kalemler = []
    hesaplar = b.hesaplar()
    kasa_banka = SIFIR
    diger = SIFIR
    for hid, bakiye in b.finans_bakiyeleri().items():
        h = hesaplar[hid]
        sinif = hesap_sinifi(h)
        if sinif == "KASA":
            if bakiye < 0:
                uyarilar.append(f"{h.hesap_adi}: kasa bakiyesi eksi ({_tl(bakiye)}) — kayıt hatası; varlığa katılmadı.")
                continue
            kasa_banka += bakiye
            kalemler.append(_kalem("Kasa", bakiye, belge_no=h.hesap_adi, yontem="Kasa", gercek_borc=False))
        elif sinif in ("BANKA", "KMH") and bakiye > 0:
            kasa_banka += bakiye
            kalemler.append(_kalem("Banka mevduatı", bakiye, belge_no=h.hesap_adi, cari=h.banka_adi or "",
                                   yontem=sinif, gercek_borc=False))
        elif sinif == "POS" and bakiye != 0:
            if bakiye < 0:
                uyarilar.append(f"{h.hesap_adi}: POS hesabı eksi ({_tl(bakiye)}); varlığa katılmadı.")
                continue
            diger += bakiye
            kalemler.append(_kalem("Bankaya geçmemiş POS", bakiye, belge_no=h.hesap_adi, cari=h.banka_adi or "",
                                   yontem="Diğer varlık", gercek_borc=False))
    return _q2(kasa_banka), diger, kalemler, uyarilar


def likit_bolumu(b: _Baglam) -> dict:
    """Üst özetteki likit varlık kartı: yalnız kasa ve mevduat."""
    kasa_banka, _pos, kalemler, uyarilar = _hesap_varliklari(b)
    kalemler = [x for x in kalemler if x["kaynak"] in ("Kasa", "Banka mevduatı")]
    return _bolum(HAZIR if kalemler else BOS, likit=kasa_banka, kasa_banka=kasa_banka, kalemler=kalemler,
                  uyarilar=uyarilar, notlar=["Blokaj bilgisi kaynağı yok: likit tutar 'Kasa ve mevduat toplamı'dır."])


def varlik_bolumu(b: _Baglam, bakiyeler: dict[int, Decimal] | None, stok_izni: bool) -> dict:
    """Varlıklar ve finansal durum yeniden tasarlanana kadar GİRİŞ ekranında gösterilmez."""
    from database.models.cek_senet import CekSenetEvrak

    notlar, eksik = [], []
    kasa_banka, diger, kalemler, uyarilar = _hesap_varliklari(b)

    stok = None
    stok_durum = HAZIR
    stok_notlari = []
    if not stok_izni:
        stok_durum = YETKISIZ
        eksik.append("Toplam stok maliyeti")
    else:
        try:
            from database.stok_rapor_service import degerleme

            dg = degerleme(tarih=b.d)
            stok = dg["toplam_maliyet"]
            if dg["eksik_satir"] or dg["negatif_satir"]:
                stok_notlari.append(f"Stok: {dg['eksik_satir']} eksik maliyetli, {dg['negatif_satir']} negatif "
                                    "satır değere katılmadı.")
            stok_notlari.append(f"Stok değeri {dg['yontem']} ile, KDV eklenmeden.")
            if stok is None:
                stok_durum = YETKISIZ
                eksik.append("Toplam stok maliyeti")
        except Exception as hata:  # noqa: BLE001
            stok_durum = HATA
            eksik.append("Toplam stok maliyeti")
            uyarilar.append(f"Stok değerlemesi: {hata}")
    notlar += stok_notlari

    if bakiyeler is None:
        alacak = None
        eksik.append("Müşteri alacakları")
    else:
        alacak = _q2(sum((v for c, v in bakiyeler.items() if v > 0 and b.musteri_mi(c)), SIFIR))
        ted_avans = _q2(-sum((v for c, v in bakiyeler.items() if v < 0 and b.tedarikci_mi(c)), SIFIR))
        if ted_avans:
            diger += ted_avans
            kalemler.append(_kalem("Tedarikçi avansları", ted_avans, yontem="Diğer varlık", gercek_borc=False))
    cek_durum = HAZIR
    if b.gecmis:
        cek_durum = TARIHSEL_YOK
        notlar.append("Portföydeki alınan çek / senet geçmiş tarih için hesaplanmaz; diğer varlıklara katılmadı.")
    else:
        cek = SIFIR
        for e in b.s.scalars(select(CekSenetEvrak).where(CekSenetEvrak.islem_yonu == "ALINAN",
                                                         CekSenetEvrak.durum.in_(ALINAN_CEK_ELDE))).all():
            if _d(e.kalan_tutar) > 0:
                cek += _d(e.kalan_tutar)
                kalemler.append(_kalem("Portföydeki alınan çek / senet", e.kalan_tutar, belge_no=e.portfoy_no,
                                       vade=e.vade_tarihi, cari=b.cari_adi(e.cari_id), yontem="Diğer varlık",
                                       gercek_borc=False))
        diger += cek
    diger = _q2(diger)

    parcalar = {"kasa_banka": kasa_banka, "stok": stok, "alacak": alacak, "diger": diger}
    toplam = None if any(v is None for v in parcalar.values()) else _q2(sum(parcalar.values(), SIFIR))
    bilinen = _q2(sum((v for v in parcalar.values() if v is not None), SIFIR))
    notlar.append("Blokaj bilgisi kaynağı yok: likit tutar 'Kasa ve mevduat toplamı'dır; kesin kullanılabilir para "
                  "değildir. Kredi kartı ve krediler defter hesapları varlığa katılmaz.")
    notlar.append("Duran varlık, vergi ve diğer bilanço hesapları izlenen varlık kapsamı dışındadır.")
    durum = HAZIR if not eksik else EKSIK
    if cek_durum == TARIHSEL_YOK:
        durum = TARIHSEL_YOK if durum == HAZIR else durum
    return _bolum(durum, kasa_banka=kasa_banka, likit=kasa_banka, likit_etiket="Kasa ve mevduat toplamı",
                  stok=stok, stok_durum=stok_durum, alacak=alacak, diger=diger, toplam=toplam, bilinen=bilinen,
                  kalemler=kalemler, eksik=eksik, uyarilar=uyarilar, notlar=notlar, cek_durum=cek_durum)


def finansal_durum(varlik: dict, borc: dict) -> dict:
    etiketler = []
    toplam_varlik = varlik.get("toplam")
    gercek_borc = borc.get("gercek_borc")
    yuk = borc.get("toplam", {}).get("ay3") if borc.get("durum") not in (TARIHSEL_YOK, YETKISIZ, HATA) else None
    if borc.get("eksik"):
        yuk = None
    likit = varlik.get("likit")
    if borc.get("toplam", {}).get("vadesiz", SIFIR) > 0:
        etiketler.append("Vade eksik")
    if varlik.get("eksik") or borc.get("eksik"):
        etiketler.append("Eksik veri")
    if any(k.get("tahmini") for k in borc.get("kalemler", [])):
        etiketler.append("Tahmin içerir")

    def fark(a, c):
        return None if a is None or c is None else _q2(a - c)

    net = fark(toplam_varlik, gercek_borc)
    sonuc = {
        "net_varlik": net,
        "uc_ay_fark": fark(toplam_varlik, yuk),
        "likit_fark": fark(likit, yuk),
        "likit_etiket": "Kasa ve mevduat karşılama farkı",
        "toplam_varlik": toplam_varlik, "gercek_borc": gercek_borc, "uc_ay_yuk": yuk, "likit": likit,
        "bilinen_varlik": varlik.get("bilinen"), "bilinen_borc": borc.get("bilinen_borc"),
        "etiketler": etiketler,
    }
    durum = HAZIR if None not in (net, sonuc["uc_ay_fark"], sonuc["likit_fark"]) else EKSIK
    if TARIHSEL_YOK in (varlik.get("durum"), borc.get("durum")):
        durum = TARIHSEL_YOK
    notlar = ["İzlenen net varlık resmî özkaynak veya net kâr değildir; ödeme takviminin faizli taksit toplamı "
              "kullanılmaz.", "Stok ve müşteri alacağı bugün harcanabilir para değildir."]
    if durum != HAZIR:
        notlar.append("Kaynağı eksik veya geçmiş tarihte hesaplanamayan kalemler nedeniyle kesin sonuç üretilmedi; "
                      "bilinen tutarlar gösterilir.")
    return _bolum(durum, **sonuc, notlar=notlar)


# ----------------------------------------------------------------------------- ana giriş
def _sabit_donem_uret(d: date, bugun: date) -> None:
    if d != bugun:
        return
    try:
        from database import sabit_gider_service as sg

        sg.donemleri_uret(bugun)
    except Exception:  # noqa: BLE001
        pass


def _guvenli(ad: str, fn, sureler: dict, *, yetki: bool = True):
    if not yetki:
        return _bolum(YETKISIZ, mesaj="Bu bölümü görüntüleme yetkiniz yok.")
    t0 = time.perf_counter()
    try:
        return fn()
    except Exception as hata:  # noqa: BLE001
        import logging

        logging.getLogger("giris_ozet").exception("%s hesaplanamadı", ad)
        return _bolum(HATA, mesaj=str(hata) or hata.__class__.__name__)
    finally:
        sureler[ad] = round((time.perf_counter() - t0) * 1000)


def hesapla(tarih: date | None = None, sube_id: int | None = None, *, bugun: date | None = None) -> dict:
    """Tüm bölümler. Hata bir bölümle sınırlı kalır; yetkisiz bölümde tutar dönmez."""
    bugun = bugun or date.today()
    d = tarih or bugun
    if d > bugun:
        raise ValueError("Rapor tarihi gelecekte olamaz.")
    _sabit_donem_uret(d, bugun)
    y = yetkiler()
    sureler: dict[str, int] = {}
    t0 = time.perf_counter()
    with get_session() as session:
        b = _Baglam(session, d, bugun, sube_id)
        satis = _guvenli("satis", lambda: satis_bolumu(b), sureler, yetki=y["satis"])
        net = ({k: satis["satirlar"][k]["net"] for k in ("bugun", "ay")}
               if satis["durum"] in (HAZIR, BOS) else None)
        tahsilat = _guvenli("tahsilat", lambda: tahsilat_bolumu(b, net), sureler, yetki=y["finans"])
        bakiyeler, cari_notlari = None, []
        if y["finans"]:
            t1 = time.perf_counter()
            try:
                bakiyeler, cari_notlari = cari_bakiyeleri(b)
            except Exception as hata:  # noqa: BLE001
                cari_notlari = [f"Cari bakiyeleri hesaplanamadı: {hata}"]
            sureler["cari_bakiye"] = round((time.perf_counter() - t1) * 1000)
        borc = _guvenli("borc", lambda: borc_bolumu(b, bakiyeler, cari_notlari), sureler, yetki=y["finans"])
        likit = _guvenli("likit", lambda: likit_bolumu(b), sureler, yetki=y["finans"])

        def tedarikci():
            if d == bugun:
                return tedarikci_acik_bolumu(b, bakiyeler, cari_notlari)
            bb = _Baglam(session, bugun, bugun, sube_id)
            try:
                bak, notlar = cari_bakiyeleri(bb)
            except Exception as hata:  # noqa: BLE001
                bak, notlar = None, [f"Cari bakiyeleri hesaplanamadı: {hata}"]
            return tedarikci_acik_bolumu(bb, bak, notlar)

        ted = _guvenli("tedarikci_acik", tedarikci, sureler, yetki=y["finans"])
    sureler["toplam"] = round((time.perf_counter() - t0) * 1000)
    return {"tarih": d, "bugun": bugun, "sube_id": sube_id, "zaman": datetime.now(), "yetki": y,
            "satis": satis, "tahsilat": tahsilat, "borc": borc, "likit": likit, "tedarikci_acik": ted,
            "sureler": sureler}


_onbellek: dict[tuple, tuple[int, dict]] = {}
_onbellek_kilit = threading.Lock()


def _anahtar(tarih: date, sube_id) -> tuple:
    return (oturum.company_id, oturum.db_path, tarih, sube_id, oturum.user_id, oturum.role_kod,
            frozenset(oturum.permissions or ()))


def ozet(tarih: date | None = None, sube_id: int | None = None, *, zorla: bool = False,
         bugun: date | None = None) -> dict:
    """Önbellekli hesap: firma / şube / tarih / kullanıcı yetkisi anahtarlı; araya yazma girerse yeniden okunur."""
    bugun = bugun or date.today()
    d = tarih or bugun
    anahtar = _anahtar(d, sube_id)
    with _onbellek_kilit:
        kayit = _onbellek.get(anahtar)
    if kayit is not None and not zorla and kayit[0] == degisim_sayaci():
        return {**kayit[1], "onbellek": True}
    sonuc = None
    for _deneme in range(2):
        once = degisim_sayaci()
        sonuc = hesapla(d, sube_id, bugun=bugun)
        if degisim_sayaci() == once:
            break
    sonuc["veri_degisti"] = degisim_sayaci() != once
    with _onbellek_kilit:
        _onbellek[anahtar] = (degisim_sayaci(), sonuc)
    return sonuc


def onbellegi_temizle() -> None:
    with _onbellek_kilit:
        _onbellek.clear()


def subeler() -> list[tuple[int, str]]:
    from database.models.sube import Sube

    with get_session() as s:
        return [(int(i), ad) for i, ad, aktif in s.execute(
            select(Sube.id, Sube.sube_adi, Sube.aktif).order_by(Sube.id)).all() if aktif]
