"""KDV raporu — Genel Muhasebe paketinden bağımsız, alış/satış belgelerinden.

Kaynak yalnızca KDV taşıyan ticari belgelerdir: satış / alış faturası, satış / alış iade faturası ve
hizmet faturası (gelir / gider). İrsaliye KDV taşımaz; hızlı satış doğrudan satış faturası üretir;
siparişten veya irsaliyeden kesilen fatura tek belgedir — bu yüzden dönüşümler iki kez sayılmaz.

Tutarlar belgede saklanan TL değerleridir (kayıt anındaki kur); bugünün kuruyla yeniden
değerleme yapılmaz. KDV hesabı yeniden kurulmaz: belge başlığındaki ``tl_kdv`` / ``tl_genel_toplam``
ve belge servislerinin ``toplam`` fonksiyonları kullanılır (muhasebe entegrasyonuyla aynı kural).

Rapor salt okunurdur. Tek yazma işlemi yetkili kullanıcının girdiği devreden KDV kaydıdır
(``kdv_devreden_kayitlari``); program beyanname vermez, vergi kaydı oluşturmaz.
"""

from __future__ import annotations

import calendar
from collections import defaultdict
from datetime import date, datetime
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

from sqlalchemy import inspect, select, text
from sqlalchemy.orm import selectinload

from database.access import yetki_var, yetki_zorunlu
from database.database import get_session
from database.session_manager import oturum
from database.turkce_normalize import turkce_normalize

SIFIR = Decimal("0")
KURUS = Decimal("0.01")
KURUS_YUVARLAMA_SINIRI = Decimal("0.05")

SATIS = "SATIS"
SATIS_IADE = "SATIS_IADE"
ALIS = "ALIS"
ALIS_IADE = "ALIS_IADE"
HIZMET_GELIR = "HIZMET_GELIR"
HIZMET_GIDER = "HIZMET_GIDER"

TUR_ADI = {
    SATIS: "Satış faturası",
    SATIS_IADE: "Satış iade faturası",
    HIZMET_GELIR: "Hizmet faturası (gelir)",
    ALIS: "Alış faturası",
    ALIS_IADE: "Alış iade faturası",
    HIZMET_GIDER: "Hizmet faturası (gider)",
}
HESAPLANAN = "Hesaplanan"
INDIRILECEK = "İndirilecek"
YON = {SATIS: HESAPLANAN, SATIS_IADE: HESAPLANAN, HIZMET_GELIR: HESAPLANAN,
       ALIS: INDIRILECEK, ALIS_IADE: INDIRILECEK, HIZMET_GIDER: INDIRILECEK}
IADE_TURLERI = frozenset({SATIS_IADE, ALIS_IADE})
GM_KAYNAK = {SATIS: "satis_faturasi", SATIS_IADE: "satis_iade", ALIS: "alis_faturasi",
             ALIS_IADE: "alis_iade", HIZMET_GELIR: "hizmet_faturasi", HIZMET_GIDER: "hizmet_faturasi"}

INDIRILEBILIRLIK_YOK = "Belirtilmemiş"
ORANSIZ = "Oranlara dağıtılmamış fark"
EK_FON = "Ek fon bedeli"
BELIRSIZ = "KDV belirlenemedi"

# Uyarı sınıfları (kaynak bağlantısı ile KDV hesabı ayrı değerlendirilir)
S_KAYNAK = "İade kaynak bağlantısı eksik"
S_KDV_YOK = "KDV belirlenemedi"
S_KDV_FARK = "Kayıtlı KDV satırlardan farklı"
S_MATRAH_FARK = "Genel indirim / masraf matrah farkı"
S_KUR = "Kur bilgisi eksik"
S_MUKERRER = "Olası mükerrer belge"
S_FON = "Ek fon ayrıntısı eksik"
S_OZEL = "Özel KDV işlemi eksik / desteklenmiyor"
SORUN_SINIFLARI = (S_KDV_YOK, S_KDV_FARK, S_MATRAH_FARK, S_KAYNAK, S_KUR, S_MUKERRER, S_FON, S_OZEL)
S_INDIRILEBILIRLIK = "Alış KDV indirilebilirliği belirtilmemiş"

GORUNTULEME_YETKISI = "kdv_rapor_goruntuleme"
DEVREDEN_YETKISI = "kdv_devreden_duzenleme"

DEVREDEN_KAYNAKLARI = ("Verilen beyanname", "Mali müşavir bildirimi", "Açılış / devir", "Diğer")

ON_HESAP = "Ön hesap"
EKSIK_ON_HESAP = "Eksik veriye dayalı ön hesap"

DESTEKLENMEYEN_NOTU = (
    "Özel işlem bilgisi (tevkifat, istisna, özel matrah, ihraç kayıtlı, iade hakkı doğuran) belge bazında "
    "'KDV Bilgisi' ile girilir; girilmemiş belge 'Belirtilmemiş' kalır ve kayıtlı KDV'siyle gösterilir. "
    "Kısmi tevkifatta satıcı tarafında tevkif edilen KDV (alıcının beyan edeceği) hesaplanan KDV'den ayrı, "
    "alıcı tarafında sorumlu sıfatıyla beyan edilecek KDV (KDV-2) ayrı satırdır. Özel matrah, ihraç kayıtlı "
    "ve iade hakkı doğuran işlemler için hesap kuralı yoktur: tutarları ayrı gösterilir, ön hesaba katılmaz. "
    "%0 oranlı satırlar kendiliğinden istisna sayılmaz."
)
INDIRILEBILIRLIK_NOTU = (
    "Alış KDV'si indirilebilirlik bilgisine göre ayrılır: 'İndirilecek' girilenler kesin indirilecek KDV'dir; "
    "KKEG / maliyete eklenecek olanlar indirilemez; bilgisi girilmemiş alış KDV'si 'Belirtilmemiş' olarak "
    "ayrı gösterilir ve kesin indirilecek KDV'ye katılmaz."
)
KAYNAK_NOTU = (
    "Kaynak: alış / satış / iade / hizmet faturalarında saklanan TL matrah ve KDV. Genel Muhasebe fişi "
    "olmayan geçerli belgeler dahildir; taslak, iptal ve silinmiş belgeler dahil edilmez. İrsaliye ve "
    "hızlı satış ayrı KDV belgesi değildir (faturaya dönüşen işlem tek kez sayılır)."
)
KUR_NOTU = (
    "Dövizli belgelerde kayıt anında saklanan TL karşılıkları kullanılır; bugünün kuruyla yeniden "
    "hesaplanmaz. Kuru kayıtlı olmayan dövizli belge 'Eksik / belirsiz' bölümünde gösterilir."
)
SALT_OKUNUR_NOTU = (
    "Rapor salt okunurdur; açmak veya dışa aktarmak belge, cari, stok ya da muhasebe kaydı oluşturmaz. "
    "Program beyanname vermez ve vergi kaydı oluşturmaz."
)


# ----------------------------------------------------------------------------- yardımcılar
def _d(v) -> Decimal:
    if v is None or v == "":
        return SIFIR
    return v if isinstance(v, Decimal) else Decimal(str(v))


def _q2(v) -> Decimal:
    return _d(v).quantize(KURUS, rounding=ROUND_HALF_UP)


def _oran(v) -> Decimal:
    return _d(v).quantize(KURUS, rounding=ROUND_HALF_UP)


def oran_metni(oran: Decimal | None) -> str:
    if oran is None:
        return "—"
    o = _d(oran).normalize()
    return f"%{o:f}".replace(".", ",")


def ay_sonu(yil: int, ay: int) -> date:
    return date(yil, ay, calendar.monthrange(yil, ay)[1])


def _ay_anahtari(t: date) -> tuple[int, int]:
    return (t.year, t.month)


def _sonraki_ay(y: int, m: int) -> tuple[int, int]:
    return (y + 1, 1) if m == 12 else (y, m + 1)


def _aylar(bas: tuple[int, int], bit: tuple[int, int]) -> list[tuple[int, int]]:
    sonuc, cur = [], bas
    while cur <= bit:
        sonuc.append(cur)
        cur = _sonraki_ay(*cur)
    return sonuc


def donem_metni(y: int, m: int) -> str:
    return f"{y}-{m:02d}"


def tam_ay_mi(bas: date, bit: date) -> bool:
    return bas.day == 1 and bas.year == bit.year and bas.month == bit.month and bit == ay_sonu(bit.year, bit.month)


def goruntuleme_yetkisi_var() -> bool:
    return yetki_var(GORUNTULEME_YETKISI)


def devreden_yetkisi_var() -> bool:
    return yetki_var(DEVREDEN_YETKISI)


def _yetki() -> None:
    yetki_zorunlu(GORUNTULEME_YETKISI, mesaj="KDV raporunu görüntüleme yetkiniz yok.")


def _tablo_var(session, ad: str) -> bool:
    return inspect(session.connection()).has_table(ad)


def _kur_sorunu(pb: str | None, kur) -> str | None:
    pb = (pb or "TRY").upper()
    if pb in ("TRY", "TL"):
        return None
    k = _d(kur)
    if k <= 0 or k == 1:
        return f"{pb} belgede kur kayıtlı değil (kur: {k}); TL karşılığı güvenilir değil."
    return None


# ----------------------------------------------------------------------------- belge okuma
def _kirilim(satirlar, toplam_fn) -> dict[Decimal, list[Decimal]]:
    """KDV oranı → [matrah, kdv]; her oran grubu belge servisinin kendi toplam fonksiyonuyla."""
    gruplar: dict[Decimal, list] = defaultdict(list)
    for s in satirlar:
        gruplar[_oran(getattr(s, "kdv_orani", 0))].append(s)
    sonuc = {}
    for oran, grup in gruplar.items():
        t = toplam_fn(grup)
        sonuc[oran] = [_q2(_d(t["ara_toplam"]) - _d(t["iskonto"])), _q2(t["kdv"])]
    return sonuc


def _baslik_tutarlari(f, toplam_fn, bilgiler: list[str]) -> dict:
    """Belgenin doğrulanmış matrah / KDV'si — muhasebe aktarımıyla aynı kaynak (``database.belge_kdv``)."""
    from database.belge_kdv import belge_kdv

    k = belge_kdv(f, toplam_fn)
    bilgiler.extend(k["notlar"])
    return k


def _belge(tur, f, *, no, tarih, matrah, kdv, kirilim, durum, sorunlar, ek_fon=(), ek_no=None,
           bilgiler=None, kdv_durum=None) -> dict:
    """Belge kaydı: oran kırılımı belge toplamıyla uzlaştırılır; fark gizlenmez, ayrı satır olur.

    ``sorunlar``: (sınıf, metin) çiftleri. ``kdv_durum``: ``belge_kdv`` sonucu (EKSIK ise KDV tahmin
    edilmez; belge toplamı 'KDV belirlenemedi' parçası olarak ayrı tutulur ve KDV toplamlarına girmez).
    """
    from database.belge_kdv import EKSIK

    sorunlar = list(sorunlar)
    bilgiler = list(bilgiler or [])
    belirsiz_brut = SIFIR
    if kdv_durum is not None and kdv_durum["durum"] == EKSIK:
        belirsiz_brut = _q2(kdv_durum["genel"])
        sorunlar.append((S_KDV_YOK, kdv_durum["sorun"]))
        parcalar = [{"oran": None, "tip": BELIRSIZ, "matrah": SIFIR, "kdv": SIFIR}]
        toplam_matrah = toplam_kdv = SIFIR
    else:
        parcalar = [{"oran": o, "tip": "Oran", "matrah": m, "kdv": k} for o, (m, k) in sorted(kirilim.items())]
        for e in ek_fon:
            parcalar.append({"oran": e["oran"], "tip": EK_FON, "matrah": e["matrah"], "kdv": e["kdv"]})
        sm = sum((p["matrah"] for p in parcalar), SIFIR)
        sk = sum((p["kdv"] for p in parcalar), SIFIR)
        toplam_matrah = _q2(matrah + sum((e["matrah"] for e in ek_fon), SIFIR))
        toplam_kdv = _q2(kdv + sum((e["kdv"] for e in ek_fon), SIFIR))
        fm, fk = toplam_matrah - sm, toplam_kdv - sk
        if fm or fk:
            parcalar.append({"oran": None, "tip": ORANSIZ, "matrah": fm, "kdv": fk})
            if fk:
                sorunlar.append((S_KDV_FARK, f"Kayıtlı KDV satırlardan hesaplanandan {fk:+.2f} TL farklı; "
                                             "fark oranlara dağıtılmadı."))
            if fm and not fk and abs(fm) <= KURUS_YUVARLAMA_SINIRI:
                bilgiler.append(
                    "Kuruş yuvarlama farkı (en çok 0,05 TL) matrahta ayrı satır olarak gösterildi; KDV değişmedi.")
            elif fm:
                sorunlar.append((S_MATRAH_FARK, (
                    f"Genel indirim / masraf / yuvarlama matrah farkı {fm:+.2f} TL KDV oranlarına dağıtılmamış "
                    "(belgedeki KDV değişmemiş).")))
    cari = getattr(f, "cari", None)
    pb = (getattr(f, "para_birimi", None) or "TRY").upper()
    if k := _kur_sorunu(pb, getattr(f, "kur", 1)):
        sorunlar.append((S_KUR, k))
    from database.belge_kdv import DURUM_ADI, KAYITLI

    return {
        "tur": tur, "tur_adi": TUR_ADI[tur], "yon": YON[tur], "iade": tur in IADE_TURLERI,
        "id": int(f.id), "no": no, "ek_no": ek_no or "", "tarih": tarih,
        "cari_id": getattr(f, "cari_id", None),
        "cari": (getattr(cari, "unvan", None) or "") if cari is not None else "",
        "cari_kodu": (getattr(cari, "cari_kodu", None) or "") if cari is not None else "",
        "para_birimi": pb, "kur": _d(getattr(f, "kur", 1) or 1),
        "durum": durum, "matrah": toplam_matrah, "kdv": toplam_kdv, "toplam": toplam_matrah + toplam_kdv,
        "parcalar": parcalar, "sorunlar": [m for _, m in sorunlar], "siniflar": [s for s, _ in sorunlar],
        "bilgiler": bilgiler, "belirsiz_brut": belirsiz_brut,
        "kdv_durum": DURUM_ADI[(kdv_durum or {}).get("durum") or KAYITLI],
        "indirilebilirlik": INDIRILEBILIRLIK_YOK if YON[tur] == INDIRILECEK else "",
        "indirilebilirlik_kod": None, "islem_turu": None, "islem_adi": INDIRILEBILIRLIK_YOK,
        "tevkifat": (None, None), "kaynak_id": getattr(f, "kaynak_fatura_id", None),
        "gm_kaynak": GM_KAYNAK[tur],
    }


def _sorun_ekle(b: dict, sinif: str, metin: str) -> None:
    b["sorunlar"].append(metin)
    b["siniflar"].append(sinif)


def _fon_ek_bedelleri(session, kaynak_turu: str, idler: list[int]) -> dict[int, list[dict]]:
    """Belgede saklanan ek fon bedelleri (muhasebe fişindeki ek KDV'yle aynı kaynak)."""
    if not idler:
        return {}
    try:
        from database.fon_service import tablolar_var
        from database.models.fon import FonBelgeEkBedeli
    except Exception:  # noqa: BLE001
        return {}
    if not tablolar_var(session):
        return {}
    sonuc: dict[int, list[dict]] = defaultdict(list)
    for i in range(0, len(idler), 500):
        for k in session.scalars(select(FonBelgeEkBedeli).where(
                FonBelgeEkBedeli.kaynak_turu == kaynak_turu, FonBelgeEkBedeli.belge_id.in_(idler[i:i + 500]))):
            if _d(k.tutar) <= 0:
                continue
            sonuc[int(k.belge_id)].append({"oran": _oran(k.kdv_orani), "matrah": _q2(k.tutar), "kdv": _q2(k.kdv)})
    return sonuc


def _ek_fon(f, kayitlar: list[dict], sorunlar: list[str]) -> list[dict]:
    tutar, kdv = _q2(getattr(f, "fon_ek_bedel_tutari", 0)), _q2(getattr(f, "fon_ek_bedel_kdv", 0))
    if kayitlar:
        return kayitlar
    if tutar or kdv:
        sorunlar.append((S_FON, "Ek fon bedeli belge başlığında var ama fon ayrıntı kaydı yok; oran bilinmiyor."))
        return [{"oran": None, "matrah": tutar, "kdv": kdv}]
    return []


def belgeleri_topla(session, bas: date, bit: date) -> tuple[list[dict], dict[str, dict[str, int]]]:
    """Tarih aralığındaki KDV'ye esas belgeler ve dahil edilmeyen (taslak / iptal / silinmiş) sayıları."""
    from database.alis_faturasi_service import AlisFaturasiService
    from database.alis_iade_faturasi_service import AlisIadeFaturasiService
    from database.hizmet_faturasi_service import HizmetFaturasiService
    from database.models.alis_faturasi import AlisFaturasi
    from database.models.alis_iade_faturasi import AlisIadeFaturasi
    from database.models.hizmet_faturasi import HizmetFaturasi
    from database.models.satis_faturasi import SatisFaturasi
    from database.models.satis_iade_faturasi import SatisIadeFaturasi
    from database.satis_faturasi_service import SatisFaturasiService
    from database.satis_iade_faturasi_service import SatisIadeFaturasiService

    belgeler: list[dict] = []
    haric: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))

    def say(tur, neden):
        haric[TUR_ADI[tur]][neden] += 1

    # Satış faturası: onaylı ve iptal/silinmiş olmayan (muhasebe entegrasyonuyla aynı kural)
    satislar = list(session.scalars(
        select(SatisFaturasi).options(selectinload(SatisFaturasi.satirlar), selectinload(SatisFaturasi.cari))
        .where(SatisFaturasi.fatura_tarihi >= bas, SatisFaturasi.fatura_tarihi <= bit)
        .order_by(SatisFaturasi.fatura_tarihi, SatisFaturasi.id)))
    gecerli = []
    for f in satislar:
        if getattr(f, "is_deleted", False):
            say(SATIS, "Silinmiş")
        elif (f.durum or "").upper() == "İPTAL":
            say(SATIS, "İptal")
        elif not f.onaylandi:
            say(SATIS, "Taslak / onaysız")
        else:
            gecerli.append(f)
    fon = _fon_ek_bedelleri(session, "SATIS_FATURASI", [int(f.id) for f in gecerli])
    for f in gecerli:
        sorunlar: list[tuple[str, str]] = []
        bilgiler: list[str] = []
        k = _baslik_tutarlari(f, SatisFaturasiService.toplam, bilgiler)
        belgeler.append(_belge(
            SATIS, f, no=f.fatura_no, tarih=f.fatura_tarihi, matrah=k["matrah"], kdv=k["kdv"],
            kirilim=_kirilim(f.satirlar, SatisFaturasiService.toplam), durum=f.durum or "",
            sorunlar=sorunlar, ek_fon=_ek_fon(f, fon.get(int(f.id), []), sorunlar), bilgiler=bilgiler,
            kdv_durum=k))

    # Satış iadesi
    iadeler = list(session.scalars(
        select(SatisIadeFaturasi).options(selectinload(SatisIadeFaturasi.satirlar),
                                          selectinload(SatisIadeFaturasi.cari))
        .where(SatisIadeFaturasi.iade_tarihi >= bas, SatisIadeFaturasi.iade_tarihi <= bit)
        .order_by(SatisIadeFaturasi.iade_tarihi, SatisIadeFaturasi.id)))
    gecerli = []
    for f in iadeler:
        if (f.durum or "").upper() == "İPTAL":
            say(SATIS_IADE, "İptal")
        else:
            gecerli.append(f)
    fon = _fon_ek_bedelleri(session, "SATIS_IADE", [int(f.id) for f in gecerli])
    for f in gecerli:
        sorunlar, bilgiler = [], []
        t = SatisIadeFaturasiService.toplam(f.satirlar)
        _iade_kaynak_durumu(SATIS_IADE, f, sorunlar, bilgiler)
        belgeler.append(_belge(
            SATIS_IADE, f, no=f.iade_no, tarih=f.iade_tarihi, matrah=_q2(t["ara_toplam"] - t["iskonto"]),
            kdv=_q2(t["kdv"]), kirilim=_kirilim(f.satirlar, SatisIadeFaturasiService.toplam),
            durum=f.durum or "", sorunlar=sorunlar, ek_fon=_ek_fon(f, fon.get(int(f.id), []), sorunlar),
            bilgiler=bilgiler))

    # Alış faturası: kayıtla stok ve cari etkisi oluşur; onay yalnızca kilittir (iptal hariç hepsi dahil)
    for f in session.scalars(
            select(AlisFaturasi).options(selectinload(AlisFaturasi.satirlar), selectinload(AlisFaturasi.cari))
            .where(AlisFaturasi.fatura_tarihi >= bas, AlisFaturasi.fatura_tarihi <= bit)
            .order_by(AlisFaturasi.fatura_tarihi, AlisFaturasi.id)):
        if (f.durum or "").upper() == "İPTAL":
            say(ALIS, "İptal")
            continue
        sorunlar, bilgiler = [], []
        k = _baslik_tutarlari(f, AlisFaturasiService.toplam, bilgiler)
        durum = (f.durum or "") + ("" if f.onaylandi else " · Onaysız")
        belgeler.append(_belge(
            ALIS, f, no=f.fatura_no, tarih=f.fatura_tarihi, matrah=k["matrah"], kdv=k["kdv"],
            kirilim=_kirilim(f.satirlar, AlisFaturasiService.toplam), durum=durum, sorunlar=sorunlar,
            ek_no=f.tedarikci_fatura_no, bilgiler=bilgiler, kdv_durum=k))

    # Alış iadesi: taslak ve iptal hariç; dövizli iadede KDV onayda yazılan TL tutarıdır
    for f in session.scalars(
            select(AlisIadeFaturasi).options(selectinload(AlisIadeFaturasi.satirlar),
                                             selectinload(AlisIadeFaturasi.cari))
            .where(AlisIadeFaturasi.iade_tarihi >= bas, AlisIadeFaturasi.iade_tarihi <= bit)
            .order_by(AlisIadeFaturasi.iade_tarihi, AlisIadeFaturasi.id)):
        d = (f.durum or "").upper()
        if d in ("İPTAL", "TASLAK"):
            say(ALIS_IADE, "İptal" if d == "İPTAL" else "Taslak / onaysız")
            continue
        sorunlar, bilgiler = [], []
        t = AlisIadeFaturasiService.belge_toplami(f)
        kirilim = _kirilim(f.satirlar, AlisIadeFaturasiService.toplam)
        if f.kdv_tl_toplam is not None and all(s.kdv_tl is not None for s in f.satirlar):
            for oran in kirilim:
                kirilim[oran][1] = _q2(sum((_d(s.kdv_tl) for s in f.satirlar
                                            if _oran(s.kdv_orani) == oran), SIFIR))
        elif (f.para_birimi or "TRY").upper() not in ("TRY", "TL") and f.kdv_tl_toplam is None:
            sorunlar.append((S_KUR, "Dövizli iadede KDV TL karşılığı yöntemi kayıtlı değil; belge kuruyla hesaplandı."))
        _iade_kaynak_durumu(ALIS_IADE, f, sorunlar, bilgiler)
        belgeler.append(_belge(
            ALIS_IADE, f, no=f.iade_no, tarih=f.iade_tarihi, matrah=_q2(t["ara_toplam"] - t["iskonto"]),
            kdv=_q2(t["kdv"]), kirilim=kirilim, durum=f.durum or "", sorunlar=sorunlar, bilgiler=bilgiler))

    # Hizmet faturası: gelir hesaplanan, gider indirilecek tarafı
    def hizmet_toplam(satirlar):
        t = HizmetFaturasiService.toplam(satirlar)
        return {k: _q2(v) for k, v in t.items()}

    for f in session.scalars(
            select(HizmetFaturasi).options(selectinload(HizmetFaturasi.satirlar), selectinload(HizmetFaturasi.cari))
            .where(HizmetFaturasi.fatura_tarihi >= bas, HizmetFaturasi.fatura_tarihi <= bit)
            .order_by(HizmetFaturasi.fatura_tarihi, HizmetFaturasi.id)):
        tur = HIZMET_GELIR if (f.fatura_turu or "").upper() == "GELIR" else HIZMET_GIDER
        if (f.durum or "").upper() == "İPTAL":
            say(tur, "İptal")
            continue
        sorunlar, bilgiler = [], []
        k = _baslik_tutarlari(f, hizmet_toplam, bilgiler)
        belgeler.append(_belge(
            tur, f, no=f.fatura_no, tarih=f.fatura_tarihi, matrah=k["matrah"], kdv=k["kdv"],
            kirilim=_kirilim(f.satirlar, hizmet_toplam), durum=f.durum or "", sorunlar=sorunlar,
            bilgiler=bilgiler, kdv_durum=k))

    _mukerrer_kontrol(session, belgeler)
    _ozel_bilgileri_uygula(session, belgeler)
    belgeler.sort(key=lambda b: (b["tarih"], b["tur"], b["no"]))
    return belgeler, {k: dict(v) for k, v in haric.items()}


def _mukerrer_kontrol(session, belgeler: list[dict]) -> None:
    """Olası mükerrer KDV: aynı tedarikçi belge no'lu birden çok alış; aynı irsaliyeden birden çok satış."""
    from database.models.alis_faturasi import AlisFaturasi
    from database.models.satis_faturasi import SatisFaturasi

    alislar = {b["id"]: b for b in belgeler if b["tur"] == ALIS and b["ek_no"].strip()}
    if alislar:
        anahtarlar = defaultdict(list)
        for fid, cari_id, no in session.execute(
                select(AlisFaturasi.id, AlisFaturasi.cari_id, AlisFaturasi.tedarikci_fatura_no)
                .where(AlisFaturasi.tedarikci_fatura_no.is_not(None), AlisFaturasi.durum != "İPTAL")):
            if (no or "").strip():
                anahtarlar[(cari_id, turkce_normalize(no.strip()))].append(fid)
        for b in alislar.values():
            digerleri = [i for i in anahtarlar.get((b["cari_id"], turkce_normalize(b["ek_no"].strip())), [])
                         if i != b["id"]]
            if digerleri:
                _sorun_ekle(b, S_MUKERRER,
                            f"Aynı tedarikçi belge no ({b['ek_no']}) başka alış faturasında da var; olası mükerrer KDV.")
    satislar = {b["id"]: b for b in belgeler if b["tur"] == SATIS}
    if satislar:
        irs = defaultdict(list)
        for fid, irs_id in session.execute(
                select(SatisFaturasi.id, SatisFaturasi.irsaliye_id).where(
                    SatisFaturasi.irsaliye_id.is_not(None), SatisFaturasi.durum != "İPTAL",
                    SatisFaturasi.is_deleted.is_(False), SatisFaturasi.onaylandi.is_(True))):
            irs[irs_id].append(fid)
        for irs_id, idler in irs.items():
            if len(idler) < 2:
                continue
            for fid in idler:
                if fid in satislar:
                    _sorun_ekle(satislar[fid], S_MUKERRER,
                                "Aynı irsaliyeden birden çok onaylı satış faturası var (kısmi faturalama olabilir); "
                                "mükerrer KDV olup olmadığını kontrol edin.")


KAYNAKSIZ_SATIS = "Kaynak satış faturası belirtilmemiş iade."
KAYNAKSIZ_ALIS = "Kaynak alış faturası belirtilmemiş iade."


def _iade_kaynak_durumu(tur: str, f, sorunlar: list, bilgiler: list) -> None:
    """İadenin kaynak belge bağlantısı (KDV hesabından ayrı değerlendirilir; iade her durumda raporda).

    Satırlardaki kayıtlı kaynaksız kararı (satış iadesinde ``kaynak_yok_onay``, alış iadesinde DEVİR /
    KAYNAKSIZ / BAŞKA TEDARİKÇİ) gerekçeli kaynaksız iadedir: uyarı değil bilgi olarak gösterilir.
    """
    if f.kaynak_fatura_id:
        return
    satirlar = list(f.satirlar)
    bagli = {int(s.kaynak_fatura_satiri_id) for s in satirlar if getattr(s, "kaynak_fatura_satiri_id", None)}
    if tur == SATIS_IADE:
        kararli = [s for s in satirlar if not s.kaynak_fatura_satiri_id and getattr(s, "kaynak_yok_onay", None)]
        acik = [s for s in satirlar if not s.kaynak_fatura_satiri_id and not getattr(s, "kaynak_yok_onay", None)]
        metin = KAYNAKSIZ_SATIS
    else:
        from database.alis_iade_faturasi_service import BASKA_TEDARIKCI, DEVIR, KAYNAKSIZ

        kararli = [s for s in satirlar if not s.kaynak_fatura_satiri_id
                   and getattr(s, "kaynak_durumu", None) in (DEVIR, KAYNAKSIZ, BASKA_TEDARIKCI)]
        acik = [s for s in satirlar if not s.kaynak_fatura_satiri_id and s not in kararli]
        metin = KAYNAKSIZ_ALIS
    if satirlar and not acik and not bagli:
        gerekce = "; ".join(sorted({(getattr(s, "kaynak_yok_gerekce", None) or getattr(s, "kaynak_gerekce", None)
                                     or "").strip() for s in kararli} - {""}))
        bilgiler.append("Kaynaksız iade — satırlarda gerekçeli karar kayıtlı" + (f" ({gerekce})." if gerekce else "."))
        return
    if bagli and not acik:
        sorunlar.append((S_KAYNAK, metin[:-1] + " (başlıkta); satırlar kaynak satırlara bağlı — 'Kaynak Bağla' ile "
                                               "başlık bağlantısı düzeltilebilir."))
        return
    sorunlar.append((S_KAYNAK, metin))


# ----------------------------------------------------------------------------- özel KDV bilgisi
DESTEKLENMEYEN_ISLEMLER = frozenset({"OZEL_MATRAH", "IHRAC_KAYITLI", "IADE_HAKKI", "TEVKIFAT_EKSIK"})


def _ozel_bilgileri_uygula(session, belgeler: list[dict]) -> None:
    """``kdv_belge_bilgileri`` kaydını belgeye işler. Kaydı olmayan belge 'Belirtilmemiş' kalır.

    İadede kendi kaydı yoksa kaynak faturanın bilgisi kullanılır (iade, kaynağıyla aynı yönde düzeltilir).
    """
    from database.kdv_belge_bilgi_service import bilgi_turu, bilgileri_oku
    from database.models.kdv_belge_bilgisi import (
        INDIRILEBILIRLIK_SECENEKLERI,
        ISLEM_TURLERI,
        ISTISNA,
        TEVKIFAT,
    )

    anahtarlar = {(bilgi_turu(b["tur"]), b["id"]) for b in belgeler}
    for b in belgeler:
        if b["iade"] and b["kaynak_id"]:
            anahtarlar.add((SATIS if b["tur"] == SATIS_IADE else ALIS, int(b["kaynak_id"])))
    bilgiler = bilgileri_oku(session, anahtarlar)
    for b in belgeler:
        k = bilgiler.get((bilgi_turu(b["tur"]), b["id"]))
        kaynak = (bilgiler.get((SATIS if b["tur"] == SATIS_IADE else ALIS, int(b["kaynak_id"])))
                  if b["iade"] and b["kaynak_id"] else None)
        if b["iade"] and k is not None and k.kaynak_yok_nedeni and S_KAYNAK in b["siniflar"]:
            for i in reversed([i for i, s in enumerate(b["siniflar"]) if s == S_KAYNAK]):
                del b["siniflar"][i], b["sorunlar"][i]
            b["bilgiler"].append(f"Kaynaksız iade — kayıtlı neden: {k.kaynak_yok_nedeni}")
        ind = getattr(k, "indirilebilirlik", None) or getattr(kaynak, "indirilebilirlik", None)
        islem = getattr(k, "islem_turu", None) or getattr(kaynak, "islem_turu", None)
        kaynakli = k if getattr(k, "islem_turu", None) else kaynak
        if b["yon"] == INDIRILECEK:
            b["indirilebilirlik_kod"] = ind
            b["indirilebilirlik"] = INDIRILEBILIRLIK_SECENEKLERI.get(ind, INDIRILEBILIRLIK_YOK)
        b["islem_turu"] = islem
        b["islem_adi"] = ISLEM_TURLERI.get(islem, INDIRILEBILIRLIK_YOK)
        if islem == TEVKIFAT:
            pay, payda = getattr(kaynakli, "tevkifat_pay", None), getattr(kaynakli, "tevkifat_payda", None)
            if pay and payda:
                b["tevkifat"] = (int(pay), int(payda))
                b["islem_adi"] = f"{b['islem_adi']} {pay}/{payda}"
            else:
                b["islem_turu"] = "TEVKIFAT_EKSIK"
                _sorun_ekle(b, S_OZEL, "Tevkifatlı işaretli ama tevkifat oranı girilmemiş; KDV ön hesaba katılmadı.")
        elif islem == ISTISNA:
            kod = getattr(kaynakli, "istisna_kodu", None)
            if kod:
                b["islem_adi"] = f"{b['islem_adi']} ({kod})"
            if b["kdv"]:
                _sorun_ekle(b, S_OZEL, f"İstisna işaretli belgede {b['kdv']:.2f} TL KDV var; belgeyi kontrol edin.")
        elif islem in DESTEKLENMEYEN_ISLEMLER:
            _sorun_ekle(b, S_OZEL, f"{b['islem_adi']}: hesap kuralı tanımlı değil; KDV ayrı gösterildi, ön hesaba "
                                   "katılmadı.")


def _dagilim(b: dict, kdv: Decimal) -> dict[str, Decimal]:
    """Bir KDV tutarının rapor kalemlerine dağılımı (belge yönü ve özel işlem bilgisine göre).

    Hesaplanan tarafı: ``beyan`` (satıcının hesapladığı), ``tevkifat`` (alıcının beyan edeceği kısım),
    ``desteklenmeyen``. Alış tarafı: ``kesin`` / ``belirsiz`` / ``indirilemez`` / ``desteklenmeyen`` ve
    tevkifatlı alışta sorumlu sıfatıyla beyan edilecek ``kdv2``.
    """
    from database.models.kdv_belge_bilgisi import INDIRILECEK as IND, KKEG, MALIYET

    if b["islem_turu"] in DESTEKLENMEYEN_ISLEMLER:
        return {"desteklenmeyen": kdv}
    tev = SIFIR
    if b["tevkifat"][0]:
        pay, payda = b["tevkifat"]
        tev = _q2(kdv * Decimal(pay) / Decimal(payda))
    if b["yon"] == HESAPLANAN:
        return {"beyan": kdv - tev, "tevkifat": tev}
    ind = b["indirilebilirlik_kod"]
    anahtar = "kesin" if ind == IND else ("indirilemez" if ind in (KKEG, MALIYET) else "belirsiz")
    return {anahtar: kdv, "kdv2": tev}


# ----------------------------------------------------------------------------- filtre ve özet
def _filtrele(belgeler: list[dict], *, cari=None, belge_turu=None, kdv_orani=None, durum=None) -> list[dict]:
    aranan = turkce_normalize(str(cari).strip()) if cari and str(cari).strip() else ""
    oran = None
    if kdv_orani not in (None, "", "TUMU"):
        oran = "ORANSIZ" if kdv_orani == "ORANSIZ" else _oran(kdv_orani)
    sonuc = []
    for b in belgeler:
        if belge_turu not in (None, "", "TUMU") and b["tur"] != belge_turu:
            continue
        if aranan and aranan not in turkce_normalize(f"{b['cari_kodu']} {b['cari']}"):
            continue
        if durum == "SORUNLU" and not b["sorunlar"]:
            continue
        if durum == "SORUNSUZ" and b["sorunlar"]:
            continue
        if oran == "ORANSIZ" and not any(p["oran"] is None for p in b["parcalar"]):
            continue
        if isinstance(oran, Decimal) and not any(p["oran"] == oran for p in b["parcalar"]):
            continue
        sonuc.append(b)
    return sonuc


def _parca_uygun(p, kdv_orani) -> bool:
    if kdv_orani in (None, "", "TUMU"):
        return True
    if kdv_orani == "ORANSIZ":
        return p["oran"] is None
    return p["oran"] == _oran(kdv_orani)


KALEMLER = ("beyan", "tevkifat", "kesin", "belirsiz", "indirilemez", "desteklenmeyen", "kdv2")


def _toplamlar(belgeler: list[dict], kdv_orani=None) -> dict[str, Decimal]:
    """Tür toplamları ve kalemler. İadeler eksi yönde, yalnızca bir kez.

    ``net_hesaplanan``: satıcının hesapladığı KDV (tevkif edilen kısım ve desteklenmeyen özel işlemler
    hariç). ``net_kesin_indirilecek``: indirilebilirliği 'İndirilecek' girilmiş alış KDV'si.
    ``net_alis_kdv``: bütün alış KDV'si (muhasebe karşılaştırması bununla yapılır).
    """
    t = defaultdict(lambda: SIFIR)
    for b in belgeler:
        isaret = -1 if b["iade"] else 1
        for p in b["parcalar"]:
            if not _parca_uygun(p, kdv_orani):
                continue
            t[f"{b['tur']}_matrah"] += p["matrah"]
            t[f"{b['tur']}_kdv"] += p["kdv"]
            taraf = "h" if b["yon"] == HESAPLANAN else "i"
            for kalem, tutar in _dagilim(b, p["kdv"]).items():
                t[f"{taraf}_{kalem}"] += isaret * tutar
            if b["islem_turu"] == "ISTISNA":
                t[f"{taraf}_istisna_matrah"] += isaret * p["matrah"]
    hes = t[f"{SATIS}_kdv"] + t[f"{HIZMET_GELIR}_kdv"]
    hes_iade = t[f"{SATIS_IADE}_kdv"]
    ind = t[f"{ALIS}_kdv"] + t[f"{HIZMET_GIDER}_kdv"]
    ind_iade = t[f"{ALIS_IADE}_kdv"]
    for tur in TUR_ADI:
        t[f"{tur}_matrah"] += SIFIR
        t[f"{tur}_kdv"] += SIFIR
    for taraf in ("h", "i"):
        for kalem in (*KALEMLER, "istisna_matrah"):
            t[f"{taraf}_{kalem}"] += SIFIR
    return {**t, "hesaplanan": hes, "hesaplanan_iade": hes_iade, "brut_hesaplanan": hes - hes_iade,
            "net_hesaplanan": t["h_beyan"], "tevkifat_satis": t["h_tevkifat"],
            "desteklenmeyen_hesaplanan": t["h_desteklenmeyen"],
            "indirilecek": ind, "indirilecek_iade": ind_iade, "net_alis_kdv": ind - ind_iade,
            "net_kesin_indirilecek": t["i_kesin"], "net_belirsiz": t["i_belirsiz"],
            "net_indirilemez": t["i_indirilemez"], "desteklenmeyen_alis": t["i_desteklenmeyen"],
            "kdv2": t["i_kdv2"],
            "belirsiz_brut": sum((b["belirsiz_brut"] for b in belgeler), SIFIR)}


def _ozet_satirlari(belgeler: list[dict], kdv_orani=None) -> list[dict]:
    t = _toplamlar(belgeler, kdv_orani)
    adet = defaultdict(int)
    for b in belgeler:
        adet[b["tur"]] += 1

    def satir(bolum, kalem, tur, etiket=None, durum=""):
        return {"bolum": bolum, "kalem": kalem, "adet": adet.get(tur, 0) if tur else "",
                "matrah": t[f"{tur}_matrah"] if tur else "", "kdv": t[f"{tur}_kdv"] if tur else "",
                "durum": durum, "_etiket": etiket}

    def kalem(bolum, ad, tutar, durum="", etiket=None, adet_=""):
        return {"bolum": bolum, "kalem": ad, "adet": adet_, "matrah": "", "kdv": tutar, "durum": durum,
                "_etiket": etiket}

    def say(kosul):
        return sum(1 for b in belgeler if kosul(b)) or ""

    h, a = "Hesaplanan KDV", "Alış KDV"
    rows = [
        satir(h, "Satış faturaları", SATIS),
        satir(h, "Hizmet faturaları (gelir)", HIZMET_GELIR),
        satir(h, "Satış iadeleri (−)", SATIS_IADE),
        kalem(h, "Toplam hesaplanan KDV (belgelerdeki)", t["brut_hesaplanan"]),
    ]
    if t["tevkifat_satis"]:
        rows.append(kalem(h, "Tevkif edilen KDV — alıcının beyan edeceği (−)", t["tevkifat_satis"],
                          adet_=say(lambda b: b["yon"] == HESAPLANAN and b["tevkifat"][0])))
    if t["desteklenmeyen_hesaplanan"]:
        rows.append(kalem(h, "Desteklenmeyen özel işlem KDV'si (ön hesaba katılmadı)",
                          t["desteklenmeyen_hesaplanan"], "Ayrı gösterilir", "uyari",
                          say(lambda b: b["yon"] == HESAPLANAN and b["islem_turu"] in DESTEKLENMEYEN_ISLEMLER)))
    rows.append(kalem(h, "Net hesaplanan KDV", t["net_hesaplanan"], etiket="toplam"))
    if t["h_istisna_matrah"]:
        rows.append({"bolum": h, "kalem": "İstisna işaretli işlemlerin matrahı (bilgi)", "adet": "",
                     "matrah": t["h_istisna_matrah"], "kdv": "", "durum": "", "_etiket": None})
    rows += [
        satir(a, "Alış faturaları", ALIS),
        satir(a, "Hizmet faturaları (gider)", HIZMET_GIDER),
        satir(a, "Alış iadeleri (−)", ALIS_IADE),
        kalem(a, "Net alış KDV (tümü)", t["net_alis_kdv"]),
        kalem(a, "Kesin indirilecek KDV", t["net_kesin_indirilecek"], "İndirilebilirliği girilmiş", "toplam",
              say(lambda b: b["yon"] == INDIRILECEK and b["indirilebilirlik_kod"] == "INDIRILECEK")),
        kalem(a, f"İndirilebilirliği belirtilmemiş alış KDV'si (kesin indirilecek değil)", t["net_belirsiz"],
              INDIRILEBILIRLIK_YOK, "uyari" if t["net_belirsiz"] else None,
              say(lambda b: b["yon"] == INDIRILECEK and not b["indirilebilirlik_kod"]
                  and b["islem_turu"] not in DESTEKLENMEYEN_ISLEMLER)),
    ]
    if t["net_indirilemez"]:
        rows.append(kalem(a, "İndirilemeyen KDV (KKEG / maliyete eklenecek)", t["net_indirilemez"],
                          adet_=say(lambda b: b["indirilebilirlik_kod"] in ("KKEG", "MALIYET"))))
    if t["desteklenmeyen_alis"]:
        rows.append(kalem(a, "Desteklenmeyen özel işlem KDV'si (ön hesaba katılmadı)", t["desteklenmeyen_alis"],
                          "Ayrı gösterilir", "uyari"))
    if t["kdv2"]:
        rows.append(kalem(a, "Sorumlu sıfatıyla beyan edilecek KDV (tevkifatlı alış, KDV-2)", t["kdv2"],
                          "Ayrı beyan", adet_=say(lambda b: b["yon"] == INDIRILECEK and b["tevkifat"][0])))
    if t["belirsiz_brut"]:
        rows.append({"bolum": "Eksik bilgi", "adet": say(lambda b: b["belirsiz_brut"]),
                     "kalem": "KDV'si belirlenemeyen belgeler — belge toplamı (KDV dahil; KDV tahmin edilmedi)",
                     "matrah": t["belirsiz_brut"], "kdv": "", "durum": BELIRSIZ, "_etiket": "uyari"})
    return rows


def _oran_satirlari(belgeler: list[dict], kdv_orani=None) -> list[dict]:
    g: dict[tuple, dict] = {}
    for b in belgeler:
        for p in b["parcalar"]:
            if not _parca_uygun(p, kdv_orani):
                continue
            anahtar = (b["yon"], p["oran"] is None, p["oran"] or SIFIR, p["tip"])
            r = g.setdefault(anahtar, {
                "yon": b["yon"], "oran": oran_metni(p["oran"]), "tip": p["tip"],
                "satis_matrah": SIFIR, "satis_kdv": SIFIR, "iade_matrah": SIFIR, "iade_kdv": SIFIR,
                "_etiket": "uyari" if p["tip"] == ORANSIZ else None})
            if b["iade"]:
                r["iade_matrah"] += p["matrah"]
                r["iade_kdv"] += p["kdv"]
            else:
                r["satis_matrah"] += p["matrah"]
                r["satis_kdv"] += p["kdv"]
    rows = []
    for anahtar in sorted(g, key=lambda a: (a[0] != HESAPLANAN, a[1], a[2], a[3])):
        r = g[anahtar]
        r["net_matrah"] = r["satis_matrah"] - r["iade_matrah"]
        r["net_kdv"] = r["satis_kdv"] - r["iade_kdv"]
        rows.append(r)
    return rows


def _belge_satiri(b: dict) -> dict:
    oranlar = sorted({p["oran"] for p in b["parcalar"] if p["oran"] is not None})
    return {
        "tarih": b["tarih"], "tur_adi": b["tur_adi"], "no": b["no"], "ek_no": b["ek_no"], "cari": b["cari"],
        "yon": b["yon"], "matrah": b["matrah"], "oranlar": ", ".join(oran_metni(o) for o in oranlar) or "—",
        "kdv": b["kdv"], "toplam": b["toplam"] if not b["belirsiz_brut"] else b["belirsiz_brut"],
        "para_birimi": b["para_birimi"], "durum": b["durum"],
        "kdv_durum": b["kdv_durum"], "islem": b["islem_adi"],
        "indirilebilirlik": b["indirilebilirlik"], "sinif": "; ".join(dict.fromkeys(b["siniflar"])),
        "sorun": "; ".join(b["sorunlar"]), "not": "; ".join(b["bilgiler"]),
        "tur": b["tur"], "id": b["id"], "_etiket": "uyari" if b["sorunlar"] else None,
    }


def _eksik_satirlari(belgeler: list[dict], haric: dict) -> list[dict]:
    """Uyarılar sınıfa göre gruplu: her belge satırında no, tarih, cari, tür, tutar ve eksik bilgi."""
    rows = []
    sira = {s: i for i, s in enumerate(SORUN_SINIFLARI)}
    kayitlar = [(sinif, metin, b) for b in belgeler for sinif, metin in zip(b["siniflar"], b["sorunlar"])]
    kayitlar.sort(key=lambda x: (sira.get(x[0], 99), x[2]["tarih"], x[2]["no"]))
    for sinif, metin, b in kayitlar:
        rows.append({"sinif": sinif, "tarih": b["tarih"], "tur_adi": b["tur_adi"], "no": b["no"], "cari": b["cari"],
                     "tutar": b["belirsiz_brut"] or b["toplam"], "kdv": b["kdv"], "sorun": metin,
                     "tur": b["tur"], "id": b["id"], "_etiket": "uyari"})
    bilgi = defaultdict(lambda: defaultdict(int))
    for b in belgeler:
        for n in b["bilgiler"]:
            bilgi[b["tur_adi"]][n] += 1
    belirsiz = [b for b in belgeler if b["yon"] == INDIRILECEK and not b["indirilebilirlik_kod"] and b["kdv"]]
    if belirsiz:
        rows.append({"sinif": S_INDIRILEBILIRLIK, "tarih": "", "tur_adi": "", "no": "", "cari": "",
                     "tutar": "", "kdv": sum((b["kdv"] * (-1 if b["iade"] else 1) for b in belirsiz), SIFIR),
                     "sorun": f"{len(belirsiz)} alış tarafı belgede indirilebilirlik girilmemiş; bu KDV kesin "
                              "indirilecek KDV'ye katılmadı ('KDV Bilgisi' ile girilebilir).",
                     "tur": "", "id": None, "_etiket": "uyari"})
    for tur_adi, notlar in sorted(bilgi.items()):
        for n, adet in sorted(notlar.items()):
            rows.append({"sinif": "Bilgi", "tarih": "", "tur_adi": tur_adi, "no": "", "cari": "", "tutar": "",
                         "kdv": "", "sorun": f"Bilgi — {adet} belgede: {n}", "tur": "", "id": None,
                         "_etiket": "soluk"})
    for tur_adi, nedenler in sorted(haric.items()):
        for neden, adet in sorted(nedenler.items()):
            rows.append({"sinif": "Dahil edilmedi", "tarih": "", "tur_adi": tur_adi, "no": "", "cari": "",
                         "tutar": "", "kdv": "", "sorun": f"{adet} belge dahil edilmedi ({neden}).", "tur": "",
                         "id": None, "_etiket": "soluk"})
    return rows


def uyari_siniflari(belgeler: list[dict]) -> list[dict]:
    """Uyarı sınıfı başına belge sayısı ve etkilenen KDV / tutar (sınıflandırma özeti)."""
    sayac: dict[str, dict] = {}
    for b in belgeler:
        for sinif in dict.fromkeys(b["siniflar"]):
            r = sayac.setdefault(sinif, {"sinif": sinif, "belge": 0, "kdv": SIFIR, "tutar": SIFIR})
            r["belge"] += 1
            r["kdv"] += b["kdv"]
            r["tutar"] += b["belirsiz_brut"] or b["toplam"]
    sira = {s: i for i, s in enumerate(SORUN_SINIFLARI)}
    return sorted(sayac.values(), key=lambda r: sira.get(r["sinif"], 99))


# ----------------------------------------------------------------------------- devreden KDV
def _devreden_tablosu_var(session) -> bool:
    return _tablo_var(session, "kdv_devreden_kayitlari")


def _devreden_tablo_hazirla() -> None:
    """Tablo yoksa oluşturur (tekrar çalıştırılabilir); mevcut veride önce doğrulanmış yedek alınır."""
    import database.database as veritabani
    from database.models.kdv_devreden import KdvDevredenKaydi

    motor = getattr(veritabani.company_db, "_engine", None) or veritabani.engine
    if inspect(motor).has_table(KdvDevredenKaydi.__tablename__):
        return

    def calistir() -> None:
        KdvDevredenKaydi.__table__.create(bind=motor, checkfirst=True)

    db_yolu = getattr(veritabani.company_db, "_db_path", None)
    if not db_yolu:
        calistir()
        return
    from database.gecis_guvenligi import guvenli_gecis, yedek_onayi

    if yedek_onayi(db_yolu) is not None:
        calistir()
    else:
        guvenli_gecis(db_yolu, calistir, gerekli=True, etiket="kdv_devreden_gecis")


def _aktif_devredenler(session) -> dict[tuple[int, int], Any]:
    if not _devreden_tablosu_var(session):
        return {}
    from database.models.kdv_devreden import DURUM_AKTIF, KdvDevredenKaydi

    kayitlar = {}
    for k in session.scalars(select(KdvDevredenKaydi).where(KdvDevredenKaydi.durum == DURUM_AKTIF)
                             .order_by(KdvDevredenKaydi.id)):
        kayitlar[(int(k.yil), int(k.ay))] = k
    return kayitlar


def devreden_kayitlari(yil: int | None = None) -> list[dict]:
    """Bütün devreden kayıtları (geçmiş / iptal edilenler dahil), en yeni dönem önce."""
    _yetki()
    with get_session() as session:
        if not _devreden_tablosu_var(session):
            return []
        from database.models.kdv_devreden import KdvDevredenKaydi

        q = select(KdvDevredenKaydi).order_by(KdvDevredenKaydi.yil.desc(), KdvDevredenKaydi.ay.desc(),
                                              KdvDevredenKaydi.id.desc())
        if yil:
            q = q.where(KdvDevredenKaydi.yil == int(yil))
        return [{"id": k.id, "donem": donem_metni(k.yil, k.ay), "yil": k.yil, "ay": k.ay, "tutar": _q2(k.tutar),
                 "kaynak": k.kaynak, "aciklama": k.aciklama, "kesinlesti": bool(k.kesinlesti),
                 "durum": k.durum, "kullanici": k.kullanici or "", "tarih": k.olusturma_tarihi,
                 "iptal_gerekcesi": k.iptal_gerekcesi or "", "iptal_eden": k.iptal_eden or "",
                 "_etiket": "soluk" if k.durum != "AKTIF" else None}
                for k in session.scalars(q)]


def devreden_kaydet(yil: int, ay: int, tutar, *, kaynak: str, aciklama: str, kesinlesti: bool = False,
                    degisiklik_gerekcesi: str | None = None) -> int:
    """Dönemin önceki dönemden devreden KDV'sini kaydeder.

    Aynı dönemde aktif kayıt varsa silinmez: ``IPTAL`` olur ve yeni kayıt aktifleşir. Kesinleşmiş kayıt
    ancak değişiklik gerekçesiyle değiştirilebilir.
    """
    yetki_zorunlu(DEVREDEN_YETKISI, mesaj="Devreden KDV kaydetme yetkiniz yok.")
    yil, ay = int(yil), int(ay)
    if not 1 <= ay <= 12 or not 2000 <= yil <= 2100:
        raise ValueError("Geçerli bir yıl ve ay seçin.")
    tutar = _q2(tutar)
    if tutar < 0:
        raise ValueError("Devreden KDV negatif olamaz.")
    kaynak = (kaynak or "").strip()
    aciklama = (aciklama or "").strip()
    if not kaynak:
        raise ValueError("Devreden tutarın kaynağını seçin.")
    if not aciklama:
        raise ValueError("Açıklama zorunludur (ör. hangi beyanname / bildirim).")
    gerekce = (degisiklik_gerekcesi or "").strip()
    _devreden_tablo_hazirla()
    from database.models.kdv_devreden import DURUM_AKTIF, DURUM_IPTAL, KdvDevredenKaydi

    kullanici = oturum.ad_soyad or oturum.kullanici_adi or ""
    with get_session() as session:
        mevcut = session.scalars(select(KdvDevredenKaydi).where(
            KdvDevredenKaydi.yil == yil, KdvDevredenKaydi.ay == ay, KdvDevredenKaydi.durum == DURUM_AKTIF)).all()
        for m in mevcut:
            if m.kesinlesti and not gerekce:
                raise ValueError(
                    f"{donem_metni(yil, ay)} için kesinleşmiş devreden kaydı var ({_q2(m.tutar)} TL). "
                    "Değiştirmek için değişiklik gerekçesi girin.")
        for m in mevcut:
            m.durum = DURUM_IPTAL
            m.iptal_gerekcesi = gerekce or "Yeni kayıtla değiştirildi."
            m.iptal_eden = kullanici
            m.iptal_tarihi = datetime.now()
        kayit = KdvDevredenKaydi(yil=yil, ay=ay, tutar=tutar, kaynak=kaynak, aciklama=aciklama,
                                 kesinlesti=bool(kesinlesti), durum=DURUM_AKTIF, kullanici=kullanici)
        session.add(kayit)
        session.flush()
        kid = int(kayit.id)
    try:
        from database.user_audit import audit_document

        audit_document("KDV_DEVREDEN_KAYIT", modul="rapor", kayit_id=str(kid), belge_no=donem_metni(yil, ay))
    except Exception:  # noqa: BLE001
        pass
    return kid


def devreden_iptal(kayit_id: int, gerekce: str) -> None:
    yetki_zorunlu(DEVREDEN_YETKISI, mesaj="Devreden KDV kaydını değiştirme yetkiniz yok.")
    gerekce = (gerekce or "").strip()
    if not gerekce:
        raise ValueError("İptal gerekçesi zorunludur.")
    from database.models.kdv_devreden import DURUM_AKTIF, DURUM_IPTAL, KdvDevredenKaydi

    with get_session() as session:
        if not _devreden_tablosu_var(session):
            raise ValueError("Kayıt bulunamadı.")
        k = session.get(KdvDevredenKaydi, int(kayit_id))
        if k is None or k.durum != DURUM_AKTIF:
            raise ValueError("Aktif kayıt bulunamadı.")
        k.durum = DURUM_IPTAL
        k.iptal_gerekcesi = gerekce
        k.iptal_eden = oturum.ad_soyad or oturum.kullanici_adi or ""
        k.iptal_tarihi = datetime.now()


# ----------------------------------------------------------------------------- dönem özeti
def _aylik_ozet(session, bas: date, bit: date) -> tuple[list[dict], list[str]]:
    """Takvim ayı bazında net hesaplanan / alış KDV ve devreden zinciri (filtresiz, tüm belgeler).

    Devreden: o ay için kayıt varsa kayıt esastır (önceki ayın ön hesabına eklenmez); yoksa önceki ayın
    ön hesap devri kullanılır. Kayıt ile önceki ayın ön hesabı farklıysa uyarı verilir, kayıt değişmez.
    """
    ilk, son = _ay_anahtari(bas), _ay_anahtari(bit)
    kayitlar = _aktif_devredenler(session)
    onceki = [a for a in kayitlar if a < ilk]
    baslangic = max(onceki) if onceki else ilk
    zincir = _aylar(baslangic, son)
    belgeler, _ = belgeleri_topla(session, date(*baslangic, 1), ay_sonu(*son))
    aylik = defaultdict(list)
    for b in belgeler:
        aylik[_ay_anahtari(b["tarih"])].append(b)

    rows, notlar = [], []
    devir: Decimal | None = None
    for ym in zincir:
        bl = aylik.get(ym, [])
        t = _toplamlar(bl)
        kayit = kayitlar.get(ym)
        nedenler, uyari = [], ""
        if kayit is not None:
            giris = _q2(kayit.tutar)
            kaynak = f"Kayıt: {kayit.kaynak}" + (" (kesinleşmiş)" if kayit.kesinlesti else "")
            if devir is not None and devir != giris:
                uyari = (f"Önceki ayın ön hesap devri {devir:.2f} TL, kayıtlı devreden {giris:.2f} TL "
                         f"(fark {devir - giris:+.2f}); önceki dönem değişmiş olabilir. Kayıt kendiliğinden "
                         "değiştirilmedi.")
        elif devir is not None:
            giris, kaynak = devir, "Önceki ayın ön hesabı"
        else:
            giris, kaynak = SIFIR, "Kayıt yok (0 alındı)"
            nedenler.append("devreden KDV kaydı yok")
        etkilenen = {b["id"]: b for b in bl if b["sorunlar"]}
        belirsizler = [b for b in bl if b["yon"] == INDIRILECEK and not b["indirilebilirlik_kod"] and b["kdv"]]
        if belirsizler:
            nedenler.append(f"{len(belirsizler)} alış belgesinde indirilebilirlik belirtilmemiş "
                            f"({t['net_belirsiz']:.2f} TL ayrı gösterildi)")
        for b in belirsizler:
            etkilenen.setdefault(b["id"], b)
        sinif_sayilari = defaultdict(int)
        for b in bl:
            for s in dict.fromkeys(b["siniflar"]):
                sinif_sayilari[s] += 1
        for s in SORUN_SINIFLARI:
            if sinif_sayilari.get(s):
                nedenler.append(f"{s}: {sinif_sayilari[s]} belge")
        # Ön hesap yalnız bilinen tutarlarla: belirsiz alış KDV'si kesin indirilecek sayılmaz
        fark = t["net_hesaplanan"] - t["net_kesin_indirilecek"] - giris
        odenecek, devreden = (fark, SIFIR) if fark > 0 else (SIFIR, -fark)
        alt_fark = fark - t["net_belirsiz"]
        devir = devreden
        if ym < ilk:
            continue
        durum = EKSIK_ON_HESAP if nedenler else ON_HESAP
        rows.append({
            "donem": donem_metni(*ym), "belge": len(bl), "etkilenen": len(etkilenen),
            "net_hesaplanan": t["net_hesaplanan"], "kesin_indirilecek": t["net_kesin_indirilecek"],
            "belirsiz_alis": t["net_belirsiz"], "indirilemez": t["net_indirilemez"],
            "belirsiz_brut": t["belirsiz_brut"], "tevkifat": t["tevkifat_satis"], "kdv2": t["kdv2"],
            "net_indirilecek": t["net_kesin_indirilecek"], "devreden_giris": giris, "devreden_kaynak": kaynak,
            "odenecek": odenecek, "devreden": devreden,
            "alt_odenecek": alt_fark if alt_fark > 0 else SIFIR, "alt_devreden": -alt_fark if alt_fark < 0 else SIFIR,
            "durum": durum, "neden": "; ".join(nedenler), "uyari": uyari,
            "_etiket": "uyari" if (uyari or nedenler) else None,
        })
        if uyari:
            notlar.append(f"{donem_metni(*ym)}: {uyari}")
    return rows, notlar


# ----------------------------------------------------------------------------- GM karşılaştırma
def gm_aktif(session=None) -> bool:
    """Firma ayarında Genel Muhasebe kullanılıyor mu (GM servisleri çağrılmadan, düz okuma)."""
    def oku(s) -> bool:
        if not _tablo_var(s, "muhasebe_muhasebelestirme_ayarlari"):
            return False
        row = s.execute(text(
            "SELECT gm_kullan FROM muhasebe_muhasebelestirme_ayarlari WHERE evrak_turu = '*' "
            "ORDER BY id LIMIT 1")).first()
        return bool(row and row[0])

    if session is not None:
        return oku(session)
    with get_session() as s:
        return oku(s)


GM_KAPALI_MESAJI = (
    "Genel Muhasebe bu firmada kullanılmıyor; muhasebe karşılaştırması kullanılamaz. Temel KDV raporu "
    "belgelerden hazırlanır ve bundan etkilenmez."
)


DUZELTME_ONEKI = "kdv_duz_"


def kdv_hesap_kodlari(session) -> tuple[str, str]:
    """Eşleştirilmiş hesaplanan / indirilecek KDV hesap kodları (yoksa 391 / 191)."""
    from database.models.genel_muhasebe import HesapPlani, MuhasebeHesapEsleme

    esleme = {}
    if _tablo_var(session, "muhasebe_hesap_eslemeleri"):
        for anahtar, kod in session.execute(
                select(MuhasebeHesapEsleme.anahtar, HesapPlani.hesap_kodu)
                .join(HesapPlani, HesapPlani.id == MuhasebeHesapEsleme.hesap_id)
                .where(MuhasebeHesapEsleme.anahtar.in_(("hesaplanan_kdv", "indirilecek_kdv")),
                       MuhasebeHesapEsleme.aktif.is_(True))):
            esleme[anahtar] = kod or ""
    return esleme.get("hesaplanan_kdv") or "391", esleme.get("indirilecek_kdv") or "191"


def kdv_tarafi(kod: str, h_kod: str, i_kod: str) -> str | None:
    kod = kod or ""
    if kod.startswith(h_kod) or kod.startswith("391"):
        return HESAPLANAN
    if kod.startswith(i_kod) or kod.startswith("191"):
        return INDIRILECEK
    return None


def fis_kdv(satirlar, h_kod: str, i_kod: str) -> dict[str, Decimal]:
    """Fiş satırlarındaki KDV: hesaplanan alacak − borç, indirilecek borç − alacak."""
    t = {HESAPLANAN: SIFIR, INDIRILECEK: SIFIR}
    for s in satirlar:
        yon = kdv_tarafi(s.hesap_kodu, h_kod, i_kod)
        if yon == HESAPLANAN:
            t[yon] += _d(s.alacak) - _d(s.borc)
        elif yon == INDIRILECEK:
            t[yon] += _d(s.borc) - _d(s.alacak)
    return t


def belge_fisleri(session, belgeler: list[dict]) -> dict[tuple[str, int], dict]:
    """Belgeye bağlı etkin ana fiş ve KDV düzeltme fişi (tarihi ne olursa olsun)."""
    from database.models.genel_muhasebe import MuhasebeFisi

    sonuc: dict[tuple[str, int], dict] = {}
    turler = defaultdict(list)
    for b in belgeler:
        turler[b["gm_kaynak"]].append(b["id"])
    for kt, idler in turler.items():
        for i in range(0, len(idler), 500):
            for fis in session.scalars(
                    select(MuhasebeFisi).options(selectinload(MuhasebeFisi.satirlar))
                    .where(MuhasebeFisi.kaynak_turu.in_((kt, DUZELTME_ONEKI + kt)),
                           MuhasebeFisi.kaynak_id.in_(idler[i:i + 500]))):
                r = sonuc.setdefault((kt, int(fis.kaynak_id)), {"ana": None, "duzeltme": None})
                r["ana" if fis.kaynak_turu == kt else "duzeltme"] = fis
    return sonuc


def _gm_karsilastirma(session, bas: date, bit: date, belgeler: list[dict]) -> dict:
    """Belge KDV'si ile GM KDV hesapları; iki toplam ayrı gösterilir, birbirine eklenmez."""
    from database.models.genel_muhasebe import MuhasebeFisi, MuhasebeFisiSatiri
    from database.muhasebe_service import defterde_kalan_fis

    if not all(_tablo_var(session, t) for t in ("muhasebe_fisleri", "muhasebe_fis_satirlari")):
        return {"aktif": True, "satirlar": [], "ozet": [], "mesaj": "Genel Muhasebe tabloları henüz oluşmamış."}

    h_kod, i_kod = kdv_hesap_kodlari(session)

    def tarafi(kod: str) -> str | None:
        return kdv_tarafi(kod, h_kod, i_kod)

    fisler_belge = belge_fisleri(session, belgeler)

    rows: list[dict] = []
    eslesen: set[int] = set()
    no_fisli: dict[str, dict] = {}
    for b in belgeler:
        beklenen = b["kdv"] * (-1 if b["iade"] else 1)
        bf = fisler_belge.get((b["gm_kaynak"], b["id"])) or {}
        fis = bf.get("ana")
        duz = bf.get("duzeltme")
        if duz is not None and duz.durum != "İptal":
            eslesen.add(int(duz.id))
        temel = {"tarih": b["tarih"], "belge": f"{b['tur_adi']} {b['no']}", "cari": b["cari"],
                 "belge_kdv": beklenen, "tur": b["tur"], "id": b["id"]}
        if fis is None:
            rows.append({**temel, "kategori": "Muhasebeleşmemiş belge", "fis_no": "", "fis_tarihi": "",
                         "gm_kdv": SIFIR, "fark": beklenen, "aciklama": "Belgeye bağlı muhasebe fişi yok."})
            no_fisli[b["no"]] = b
            continue
        eslesen.add(int(fis.id))
        if fis.durum == "Taslak" or (fis.durum == "İptal" and fis.ters_fis_id is None):
            rows.append({**temel, "kategori": "Muhasebeleşmemiş belge", "fis_no": fis.fis_no,
                         "fis_tarihi": fis.fis_tarihi, "gm_kdv": SIFIR, "fark": beklenen,
                         "aciklama": f"Fiş deftere işlenmemiş ({fis.durum})."})
            continue
        gm = fis_kdv(fis.satirlar, h_kod, i_kod)[b["yon"]]
        if duz is not None and duz.durum != "İptal":
            gm += fis_kdv(duz.satirlar, h_kod, i_kod)[b["yon"]]
        if b["belirsiz_brut"]:
            rows.append({**temel, "kategori": "Belge KDV'si belirlenemedi", "fis_no": fis.fis_no,
                         "fis_tarihi": fis.fis_tarihi, "gm_kdv": gm, "fark": SIFIR,
                         "aciklama": "Belgenin KDV'si doğrulanamadı; fişteki tutar karşılaştırılamadı.",
                         "fis_id": int(fis.id)})
            continue
        aciklamalar = []
        if not (bas <= fis.fis_tarihi <= bit):
            aciklamalar.append(f"Fiş tarihi dönem dışında ({fis.fis_tarihi:%d.%m.%Y}).")
        if gm != beklenen:
            aciklamalar.append(f"Fişteki KDV {gm:.2f}, belgenin doğrulanmış KDV'si {beklenen:.2f} "
                               "(Hatalı Fişler listesinden düzeltme önizlemesi alınabilir).")
        if aciklamalar:
            rows.append({**temel, "kategori": "Tutar / dönem farkı", "fis_no": fis.fis_no,
                         "fis_tarihi": fis.fis_tarihi, "gm_kdv": gm, "fark": beklenen - gm,
                         "aciklama": " ".join(aciklamalar), "fis_id": int(fis.id)})

    # Dönemdeki defter KDV satırları
    gm_top = {HESAPLANAN: SIFIR, INDIRILECEK: SIFIR}
    fisler: dict[int, Any] = {}
    kdv_satirlari: dict[int, list] = defaultdict(list)
    belge_nolari = {b["no"]: b for b in belgeler}
    q = (select(MuhasebeFisiSatiri, MuhasebeFisi)
         .join(MuhasebeFisi, MuhasebeFisi.id == MuhasebeFisiSatiri.fis_id)
         .where(MuhasebeFisi.fis_tarihi >= bas, MuhasebeFisi.fis_tarihi <= bit, defterde_kalan_fis()))
    for s, fis in session.execute(q):
        yon = tarafi(s.hesap_kodu)
        if yon is None:
            continue
        tutar = (_d(s.alacak) - _d(s.borc)) if yon == HESAPLANAN else (_d(s.borc) - _d(s.alacak))
        gm_top[yon] += tutar
        fisler[int(fis.id)] = fis
        kdv_satirlari[int(fis.id)].append((yon, tutar))
    for fid, fis in sorted(fisler.items(), key=lambda x: (x[1].fis_tarihi, x[0])):
        if fid in eslesen:
            continue
        for yon in (HESAPLANAN, INDIRILECEK):
            tutar = sum((t for y, t in kdv_satirlari[fid] if y == yon), SIFIR)
            if not tutar:
                continue
            b = belge_nolari.get(fis.belge_no or "")
            if b is not None and b["no"] not in no_fisli:
                kategori, aciklama = "Olası mükerrer fiş", "Belge kendi fişiyle zaten muhasebeleşmiş; aynı belge no'lu ikinci fiş."
            elif b is not None:
                kategori, aciklama = "Olası mükerrer fiş", "Belge no eşleşiyor ama fiş belgeye bağlı değil."
            else:
                kategori = "Belge dışı muhasebe hareketi"
                aciklama = fis.aciklama or ""
                if fis.durum == "İptal" or fis.kaynak_turu is None and fis.belge_no:
                    aciklama = (aciklama + " (iptal / ters kayıt olabilir)").strip()
            rows.append({"kategori": kategori, "tarih": fis.fis_tarihi, "belge": fis.belge_no or "",
                         "cari": "", "fis_no": fis.fis_no, "fis_tarihi": fis.fis_tarihi, "belge_kdv": SIFIR,
                         "gm_kdv": tutar, "fark": -tutar, "aciklama": f"{yon} KDV. {aciklama}".strip(),
                         "tur": "", "id": None, "fis_id": fid})

    t = _toplamlar(belgeler)
    ozet = [
        {"kalem": "Hesaplanan KDV (belgelerdeki, net)", "belge": t["brut_hesaplanan"], "gm": gm_top[HESAPLANAN],
         "fark": t["brut_hesaplanan"] - gm_top[HESAPLANAN], "hesap": h_kod},
        {"kalem": "Alış KDV (tümü, net)", "belge": t["net_alis_kdv"], "gm": gm_top[INDIRILECEK],
         "fark": t["net_alis_kdv"] - gm_top[INDIRILECEK], "hesap": i_kod},
    ]
    for r in rows:
        r["_etiket"] = "uyari"
    return {"aktif": True, "satirlar": rows, "ozet": ozet, "mesaj": ""}


# ----------------------------------------------------------------------------- ana rapor
def rapor(bas: date, bit: date, *, cari=None, belge_turu=None, kdv_orani=None, durum=None) -> dict:
    """KDV raporu. Belge toplamları GM açık / kapalı olsa da aynıdır; karşılaştırma ayrı bölümdür."""
    _yetki()
    if bas is None or bit is None:
        raise ValueError("Başlangıç ve bitiş tarihi seçin.")
    if bas > bit:
        raise ValueError("Başlangıç tarihi bitiş tarihinden sonra olamaz.")
    with get_session() as session:
        tum, haric = belgeleri_topla(session, bas, bit)
        secili = _filtrele(tum, cari=cari, belge_turu=belge_turu, kdv_orani=kdv_orani, durum=durum)
        aylik, aylik_notlar = _aylik_ozet(session, bas, bit)
        aktif = gm_aktif(session)
        gm = _gm_karsilastirma(session, bas, bit, tum) if aktif else {
            "aktif": False, "satirlar": [], "ozet": [], "mesaj": GM_KAPALI_MESAJI}

    filtreli = any(v not in (None, "", "TUMU") for v in (cari, belge_turu, kdv_orani, durum))
    tam_ay = tam_ay_mi(bas, bit)
    notlar = [KAYNAK_NOTU, INDIRILEBILIRLIK_NOTU, DESTEKLENMEYEN_NOTU, KUR_NOTU]
    if not tam_ay:
        notlar.append("Seçilen aralık bir takvim ayı değil: aralık toplamları aylık beyan değildir. "
                      "Ödenecek / devreden ön hesabı yalnızca 'Dönem özeti' sekmesinde takvim ayı bazında verilir.")
    if filtreli:
        notlar.append("Filtre uygulandı: Özet, oran ve belge bölümleri yalnızca filtreye uyan belgeleri "
                      "gösterir. Dönem özeti ve muhasebe karşılaştırması filtresiz tüm belgelerle hesaplanır.")
    notlar.append("Ödenecek / devreden yalnızca ön hesaptır ve yalnız bilinen tutarlarla hesaplanır: "
                  "indirilebilirliği belirtilmemiş alış KDV'si ayrı sütundadır ('Belirtilmemişler indirilirse' "
                  f"sütunu karşılaştırma içindir). Eksik bilgi varsa ay '{EKSIK_ON_HESAP}' olarak işaretlenir; "
                  "bilgiler tamamlanıp rapor yenilendiğinde yeniden hesaplanır.")
    notlar.extend(aylik_notlar)
    if not aktif:
        notlar.append(GM_KAPALI_MESAJI)
    notlar.append(SALT_OKUNUR_NOTU)

    belge_rows = [_belge_satiri(b) for b in secili]
    t = _toplamlar(secili, kdv_orani)
    if belge_rows:
        belge_rows.append({"tarih": "", "tur_adi": "TOPLAM (iadeler dahil, işaretsiz)", "no": "", "ek_no": "",
                           "cari": "", "yon": "", "matrah": sum((b["matrah"] for b in secili), SIFIR),
                           "oranlar": "", "kdv": sum((b["kdv"] for b in secili), SIFIR),
                           "toplam": sum((b["toplam"] for b in secili), SIFIR), "para_birimi": "", "durum": "",
                           "indirilebilirlik": "", "kdv_durum": "", "islem": "", "sinif": "", "sorun": "",
                           "not": "", "tur": "", "id": None, "_etiket": "toplam", "_sabit": True})
    eksik = _eksik_satirlari(secili, haric)
    return {
        "bas": bas, "bit": bit, "tam_ay": tam_ay, "filtreli": filtreli, "gm_aktif": aktif,
        "ozet": _ozet_satirlari(secili, kdv_orani),
        "oranlar": _oran_satirlari(secili, kdv_orani),
        "belgeler": belge_rows,
        "eksik": eksik,
        "siniflar": uyari_siniflari(secili),
        "aylik": aylik,
        "gm": gm["satirlar"], "gm_ozet": gm["ozet"], "gm_mesaj": gm["mesaj"],
        "toplamlar": t, "belge_sayisi": len(secili),
        "sorunlu_sayisi": sum(1 for b in secili if b["sorunlar"]),
        "haric": haric,
        "notlar": notlar,
    }


def belge_satirlari(tur: str, belge_id: int) -> list[dict]:
    """Belgenin satırları: her satırın matrah / KDV'si belge servisinin toplam fonksiyonuyla."""
    _yetki()
    from database.alis_faturasi_service import AlisFaturasiService
    from database.alis_iade_faturasi_service import AlisIadeFaturasiService
    from database.hizmet_faturasi_service import HizmetFaturasiService
    from database.models.alis_faturasi import AlisFaturasi
    from database.models.alis_iade_faturasi import AlisIadeFaturasi
    from database.models.hizmet_faturasi import HizmetFaturasi
    from database.models.satis_faturasi import SatisFaturasi
    from database.models.satis_iade_faturasi import SatisIadeFaturasi
    from database.satis_faturasi_service import SatisFaturasiService
    from database.satis_iade_faturasi_service import SatisIadeFaturasiService

    harita = {
        SATIS: (SatisFaturasi, SatisFaturasiService.toplam),
        SATIS_IADE: (SatisIadeFaturasi, SatisIadeFaturasiService.toplam),
        ALIS: (AlisFaturasi, AlisFaturasiService.toplam),
        ALIS_IADE: (AlisIadeFaturasi, AlisIadeFaturasiService.toplam),
        HIZMET_GELIR: (HizmetFaturasi, HizmetFaturasiService.toplam),
        HIZMET_GIDER: (HizmetFaturasi, HizmetFaturasiService.toplam),
    }
    if tur not in harita:
        return []
    model, fn = harita[tur]
    with get_session() as session:
        f = session.get(model, int(belge_id))
        if f is None:
            return []
        rows = []
        for i, s in enumerate(f.satirlar, 1):
            t = fn([s])
            matrah = _q2(_d(t["ara_toplam"]) - _d(t["iskonto"]))
            kdv = _q2(getattr(s, "kdv_tl", None)) if getattr(s, "kdv_tl", None) is not None else _q2(t["kdv"])
            rows.append({
                "sira": i, "kod": getattr(s, "urun_kodu", None) or getattr(s, "hizmet_kodu", "") or "",
                "ad": getattr(s, "urun_adi", None) or getattr(s, "hizmet_adi", "") or "",
                "miktar": _d(s.miktar), "birim": s.birim or "", "birim_fiyat": _d(s.birim_fiyat),
                "iskonto": _d(getattr(s, "iskonto_orani", 0)), "kdv_orani": oran_metni(_oran(s.kdv_orani)),
                "matrah": matrah, "kdv": kdv, "toplam": matrah + kdv,
            })
        return rows
