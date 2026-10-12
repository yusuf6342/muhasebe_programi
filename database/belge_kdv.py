"""Belge KDV tutarı — fatura başlığı ile satırlarının doğrulanmış ortak kaynağı.

KDV raporu ve Genel Muhasebe aktarımı aynı kuralı kullanır; fatura ekranı tutarları zaten satırlardan
(belge servisinin ``toplam`` fonksiyonuyla) hesaplar, bu modül başlığın o hesapla tutarlı olup olmadığını
söyler.

Başlıktaki sıfır KDV tek başına "KDV yok" sayılmaz:

* ``KAYITLI``  — başlıkta KDV kayıtlı (normal belge); tutarlar başlıktan.
* ``SATIRDAN`` — başlıkta matrah / KDV ayrımı yok veya başlık boş (aktarılmış belge), satırların toplamı
  belgenin kayıtlı toplamını doğruluyor; KDV satırlardan, genel toplam belgedeki tutar.
* ``SIFIR``    — bütün satırlar %0 oranlı: gerçek sıfır KDV (istisna sayılmaz; yalnızca %0).
* ``EKSIK``    — satır yok ya da satır toplamı belge toplamıyla uyuşmuyor: KDV tahmin edilmez,
  belge uyarılı gösterilir ve muhasebeleştirme incelemeye düşer.
"""

from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal

SIFIR = Decimal("0")
KURUS = Decimal("0.01")

KAYITLI = "KAYITLI"
SATIRDAN = "SATIRDAN"
SIFIR_KDV = "SIFIR"
EKSIK = "EKSIK"

DURUM_ADI = {
    KAYITLI: "Başlıkta kayıtlı",
    SATIRDAN: "Satırlardan tamamlandı (aktarılmış belge)",
    SIFIR_KDV: "Gerçek %0 KDV",
    EKSIK: "KDV belirlenemedi",
}

BASLIK_BOS_NOTU = "Başlık toplamları kayıtlı değil (eski / aktarılmış kayıt); matrah ve KDV satırlardan hesaplandı."
BASLIK_AYRIM_NOTU = ("Başlıkta matrah / KDV ayrımı kayıtlı değil (aktarılmış kayıt); KDV satırlardan hesaplandı, "
                     "genel toplam belgedeki tutardır.")


def _d(v) -> Decimal:
    if v is None or v == "":
        return SIFIR
    return v if isinstance(v, Decimal) else Decimal(str(v))


def _q2(v) -> Decimal:
    return _d(v).quantize(KURUS, rounding=ROUND_HALF_UP)


def tolerans(satir_sayisi: int) -> Decimal:
    """Satır bazında kuruş yuvarlamasının belge toplamında yaratabileceği en büyük fark."""
    return max(Decimal("0.05"), KURUS * max(int(satir_sayisi), 1))


def belge_kdv(f, satir_toplam_fn, satirlar=None) -> dict:
    """Belgenin doğrulanmış (matrah, KDV, genel toplam) değeri ve durumu.

    ``satir_toplam_fn``: belge servisinin ``toplam`` fonksiyonu (çoklu iskonto, satır yuvarlaması dahil).
    Dönüş: matrah, kdv, genel, durum, notlar (bilgi), sorun (EKSIK nedeni), satir (satır toplamları).
    """
    satirlar = list(f.satirlar if satirlar is None else satirlar)
    t = {k: _q2(v) for k, v in satir_toplam_fn(satirlar).items()} if satirlar else {
        "ara_toplam": SIFIR, "iskonto": SIFIR, "kdv": SIFIR, "genel_toplam": SIFIR}
    genel = _q2(getattr(f, "tl_genel_toplam", 0))
    hk = _q2(getattr(f, "tl_kdv", 0))
    hm = _q2(getattr(f, "tl_matrah", 0))
    brut = _q2(getattr(f, "tl_brut_toplam", 0))
    sk, sg = t["kdv"], t["genel_toplam"]
    tol = tolerans(len(satirlar))
    sonuc = {"satir": t, "notlar": [], "sorun": None}

    def ver(matrah, kdv, genel_, durum, *, not_=None, sorun=None):
        sonuc.update(matrah=_q2(matrah), kdv=_q2(kdv), genel=_q2(genel_), durum=durum)
        if not_:
            sonuc["notlar"].append(not_)
        sonuc["sorun"] = sorun
        return sonuc

    if genel <= 0:
        if not satirlar or sg <= 0:
            return ver(SIFIR, SIFIR, SIFIR, KAYITLI)
        return ver(sg - sk, sk, sg, SIFIR_KDV if not sk and _hep_sifir_oran(satirlar) else SATIRDAN,
                   not_=BASLIK_BOS_NOTU)
    if hk:
        return ver(genel - hk, hk, genel, KAYITLI)
    if not satirlar:
        if hm and abs(hm - genel) <= tol:
            return ver(genel, SIFIR, genel, EKSIK,
                       sorun="Satır yok; başlıkta KDV sıfır görünüyor ama KDV oranı doğrulanamadı.")
        return ver(genel, SIFIR, genel, EKSIK,
                   sorun="Satır yok ve başlıkta KDV ayrımı kayıtlı değil; KDV belirlenemedi (tahmin edilmedi).")
    if not sk:
        if _hep_sifir_oran(satirlar):
            return ver(genel, SIFIR, genel, SIFIR_KDV)
        return ver(genel, SIFIR, genel, EKSIK,
                   sorun="Satırlarda KDV oranı var ama satır tutarları sıfır; KDV belirlenemedi.")
    # Brüt eşleşmesi yalnız genel toplamla farkı belgedeki genel indirim / masraf tutarıyla açıklanıyorsa
    islem = abs(_q2(getattr(f, "genel_islem_tutari", 0)))
    if abs(sg - genel) <= tol or (brut and islem and abs(sg - brut) <= tol
                                  and abs(abs(genel - brut) - islem) <= tol):
        return ver(genel - sk, sk, genel, SATIRDAN, not_=BASLIK_AYRIM_NOTU)
    return ver(genel, SIFIR, genel, EKSIK, sorun=(
        f"Başlıkta KDV kayıtlı değil; satırlardan hesaplanan toplam {sg:.2f} TL belge toplamı {genel:.2f} TL "
        f"ile uyuşmuyor (fark {genel - sg:+.2f}). KDV tahmin edilmedi."))


def _hep_sifir_oran(satirlar) -> bool:
    return all(_d(getattr(s, "kdv_orani", 0)) == 0 for s in satirlar)


def satis_faturasi_kdv(f) -> dict:
    from database.satis_faturasi_service import SatisFaturasiService

    return belge_kdv(f, SatisFaturasiService.toplam)


def alis_faturasi_kdv(f) -> dict:
    from database.alis_faturasi_service import AlisFaturasiService

    return belge_kdv(f, AlisFaturasiService.toplam)


def hizmet_faturasi_kdv(f) -> dict:
    from database.hizmet_faturasi_service import HizmetFaturasiService

    return belge_kdv(f, HizmetFaturasiService.toplam)


def kdv_baslik_eki(evrak: str, kaynak_id: int | None) -> str:
    """Evrak penceresi başlığı için: KDV satırlardan hesaplandıysa / belirlenemediyse kısa uyarı."""
    if not kaynak_id or evrak not in ("satis_faturasi", "alis_faturasi", "hizmet_faturasi"):
        return ""
    try:
        from database.database import get_session

        fn = {"satis_faturasi": satis_faturasi_kdv, "alis_faturasi": alis_faturasi_kdv,
              "hizmet_faturasi": hizmet_faturasi_kdv}[evrak]
        model = _model(evrak)
        with get_session() as s:
            f = s.get(model, int(kaynak_id))
            if f is None:
                return ""
            k = fn(f)
    except Exception:  # noqa: BLE001
        return ""
    if k["durum"] == EKSIK:
        return "  ·  KDV belirlenemedi (satırlar belge toplamını tutmuyor) — KDV raporu / muhasebe bekletilir"
    if k["durum"] == SATIRDAN and BASLIK_AYRIM_NOTU in k["notlar"]:
        return "  ·  KDV başlıkta kayıtlı değil, satırlardan hesaplandı"
    return ""


def _model(evrak: str):
    if evrak == "satis_faturasi":
        from database.models.satis_faturasi import SatisFaturasi

        return SatisFaturasi
    if evrak == "alis_faturasi":
        from database.models.alis_faturasi import AlisFaturasi

        return AlisFaturasi
    from database.models.hizmet_faturasi import HizmetFaturasi

    return HizmetFaturasi


def kdv_eksik_nedeni(evrak: str, f) -> str | None:
    """Muhasebeleştirme için: KDV belirlenemiyorsa neden (fiş tahmine dayandırılmaz)."""
    fn = {"satis_faturasi": satis_faturasi_kdv, "alis_faturasi": alis_faturasi_kdv,
          "hizmet_faturasi": hizmet_faturasi_kdv}.get(evrak)
    if fn is None or f is None:
        return None
    k = fn(f)
    if k["durum"] == EKSIK:
        no = getattr(f, "fatura_no", "") or ""
        return f"{no}: {k['sorun']} Belgeyi kontrol edip satırlarını / toplamını düzeltin."
    return None
