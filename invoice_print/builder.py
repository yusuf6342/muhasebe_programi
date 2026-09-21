"""InvoicePrintViewModelBuilder — kayıtlı fatura / açık kart → ViewModel."""

from __future__ import annotations

import logging
from collections import defaultdict
from decimal import Decimal, ROUND_HALF_UP
from typing import Any

from database.fatura_kdv_service import kdv_oran_metni
from invoice_print.amount_to_words import amount_to_words
from invoice_print.branding import load_company_branding, logo_data_uri
from invoice_print.settings import load_print_settings
from invoice_print.view_model import (
    InvoicePrintKdvSatir,
    InvoicePrintLine,
    InvoicePrintViewModel,
)

_LOG = logging.getLogger("invoice_print.builder")
_KURUS = Decimal("0.01")


def _d(x) -> Decimal:
    return Decimal(str(x or 0))


def _para(tutar, pb: str = "TRY") -> str:
    d = _d(tutar).quantize(_KURUS, rounding=ROUND_HALF_UP)
    s = f"{d:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    pb = (pb or "TRY").upper()
    if pb in ("TRY", "TL"):
        return f"{s} TL"
    return f"{s} {pb}"


def _miktar(m) -> str:
    d = _d(m)
    if d == d.to_integral_value():
        return str(int(d))
    return f"{d:.4f}".rstrip("0").rstrip(".").replace(".", ",")


def _iskonto_goster(i1, i2, i3) -> str:
    oranlar = []
    for x in (i1, i2, i3):
        d = _d(x)
        if d:
            oranlar.append(f"%{float(d):g}")
    return "+".join(oranlar) if oranlar else "—"


def calculate_page_breaks(
    satirlar: list[InvoicePrintLine], ayarlar: dict[str, Any]
) -> list[list[InvoicePrintLine]]:
    if not satirlar:
        return [[]]
    ilk = max(1, int(ayarlar.get("ilk_sayfa_satir") or 12))
    sonraki = max(1, int(ayarlar.get("sonraki_sayfa_satir") or 22))
    sayfalar: list[list[InvoicePrintLine]] = []
    kalan = list(satirlar)
    sayfalar.append(kalan[:ilk])
    kalan = kalan[ilk:]
    while kalan:
        sayfalar.append(kalan[:sonraki])
        kalan = kalan[sonraki:]
    return sayfalar


def _kdv_dokum(satirlar_dict: list[dict], pb: str) -> list[InvoicePrintKdvSatir]:
    from database.satis_faturasi_service import SatisFaturasiService

    grup: dict[Decimal, dict[str, Decimal]] = defaultdict(
        lambda: {"matrah": Decimal("0"), "kdv": Decimal("0")}
    )
    for s in satirlar_dict:
        _, _, net = SatisFaturasiService._satir_net(
            _d(s.get("miktar")),
            _d(s.get("birim_fiyat", s.get("birim_satis_fiyati", 0))),
            s.get("iskonto_orani", 0),
            s.get("iskonto_orani_2", 0),
            s.get("iskonto_orani_3", 0),
        )
        net = net.quantize(_KURUS, rounding=ROUND_HALF_UP)
        oran = _d(s.get("kdv_orani", 0)).quantize(Decimal("0.01"))
        kdv = (net * oran / Decimal("100")).quantize(_KURUS, rounding=ROUND_HALF_UP)
        grup[oran]["matrah"] += net
        grup[oran]["kdv"] += kdv
    sonuc = []
    for oran in sorted(grup.keys()):
        m = grup[oran]["matrah"].quantize(_KURUS, rounding=ROUND_HALF_UP)
        k = grup[oran]["kdv"].quantize(_KURUS, rounding=ROUND_HALF_UP)
        sonuc.append(
            InvoicePrintKdvSatir(
                oran=oran,
                matrah=m,
                kdv=k,
                matrah_goster=_para(m, pb),
                kdv_goster=_para(k, pb),
            )
        )
    return sonuc


def _satirlari_satir_model(
    satirlar_dict: list[dict], pb: str, ayarlar: dict
) -> list[InvoicePrintLine]:
    from database.satis_faturasi_service import SatisFaturasiService

    sonuc: list[InvoicePrintLine] = []
    for i, s in enumerate(satirlar_dict, start=1):
        miktar = _d(s.get("miktar"))
        fiyat = _d(s.get("birim_fiyat", s.get("birim_satis_fiyati", 0)))
        brut, indirim, net = SatisFaturasiService._satir_net(
            miktar,
            fiyat,
            s.get("iskonto_orani", 0),
            s.get("iskonto_orani_2", 0),
            s.get("iskonto_orani_3", 0),
        )
        brut = brut.quantize(_KURUS, rounding=ROUND_HALF_UP)
        indirim = indirim.quantize(_KURUS, rounding=ROUND_HALF_UP)
        net = net.quantize(_KURUS, rounding=ROUND_HALF_UP)
        kdv_o = _d(s.get("kdv_orani", 0))
        kdv = (net * kdv_o / Decimal("100")).quantize(_KURUS, rounding=ROUND_HALF_UP)
        toplam = (net + kdv).quantize(_KURUS, rounding=ROUND_HALF_UP)
        net_birim = (
            (net / miktar).quantize(_KURUS, rounding=ROUND_HALF_UP)
            if miktar
            else Decimal("0")
        )
        acik = (s.get("aciklama") or "") if ayarlar.get("aciklama_goster", True) else ""
        lot = ""
        if ayarlar.get("lot_goster"):
            lot = str(s.get("lot_no") or s.get("lot_cikisi") or "")
        barkod = str(s.get("barkod") or "") if ayarlar.get("barkod_goster") else ""
        sonuc.append(
            InvoicePrintLine(
                sira=i,
                urun_kodu=str(s.get("urun_kodu") or "") if ayarlar.get("urun_kodu_goster", True) else "",
                urun_adi=str(s.get("urun_adi") or ""),
                aciklama=acik,
                miktar=miktar,
                miktar_goster=_miktar(miktar),
                birim=str(s.get("birim") or ""),
                birim_fiyat=fiyat,
                birim_fiyat_goster=_para(fiyat, pb),
                net_birim_fiyat=net_birim,
                net_birim_fiyat_goster=_para(net_birim, pb),
                iskonto_goster=_iskonto_goster(
                    s.get("iskonto_orani", 0),
                    s.get("iskonto_orani_2", 0),
                    s.get("iskonto_orani_3", 0),
                ),
                iskonto_tutar=indirim,
                iskonto_tutar_goster=_para(indirim, pb) if indirim else "—",
                kdv_orani=kdv_o,
                kdv_goster=kdv_oran_metni(kdv_o),
                kdv_tutar=kdv,
                kdv_tutar_goster=_para(kdv, pb),
                net_tutar=net,
                net_goster=_para(net, pb),
                satir_toplam=toplam,
                satir_toplam_goster=_para(toplam, pb),
                barkod=barkod,
                lot=lot,
            )
        )
    return sonuc


def _filigran(durum: str, onaylandi: bool, ayarlar: dict, sablon_id: str) -> str | None:
    if sablon_id == "dahili":
        return "DAHİLİ KULLANIM İÇİNDİR"
    d = (durum or "").upper()
    if d in ("İPTAL", "IPTAL"):
        return "İPTAL EDİLMİŞTİR"
    if not onaylandi or d in ("TASLAK", "AÇIK", ""):
        if ayarlar.get("taslak_filigran_goster", True):
            return "TASLAKTIR – MALİ BELGE DEĞİLDİR"
    return None


def build_from_satirlar(
    *,
    fatura_id: int | None,
    fatura_no: str,
    fatura_tarihi,
    islem_saati: str,
    vade_tarihi,
    vade_gunu,
    depo: str,
    para_birimi: str,
    kur,
    kur_tarihi,
    durum: str,
    onaylandi: bool,
    aciklama: str,
    satirlar_dict: list[dict],
    musteri: dict[str, Any],
    siparis_no: str = "",
    irsaliye_no: str = "",
    odeme_sekli: str = "",
    tahsilat_tutari=0,
    tl_genel_db: Decimal | None = None,
    tl_brut_db: Decimal | None = None,
    genel_islem_turu: str | None = None,
    genel_islem_orani=None,
    genel_islem_tutari=None,
    sablon_id: str | None = None,
    belge_turu: str = "SATIŞ FATURASI",
    hazirlayan: str = "",
    onaylayan: str = "",
    duzenleme_tarihi: str = "",
    kaynak_siparis_olusturan: str = "",
    satis_personeli: str = "",
) -> InvoicePrintViewModel:
    from database.fatura_genel_toplam_service import islem_uygula, islem_turunu_normalize, netten_islem
    from database.satis_faturasi_service import SatisFaturasiService

    ayarlar = load_print_settings()
    if sablon_id:
        ayarlar["sablon_id"] = sablon_id
    sablon = ayarlar.get("sablon_id") or "kurumsal"
    pb = (para_birimi or "TRY").upper()

    if not satirlar_dict:
        raise ValueError("Faturada en az bir ürün satırı olmalıdır.")
    if not (fatura_no or "").strip() and fatura_id is None:
        pass
    if not musteri.get("unvan") and not musteri.get("cari_kodu"):
        raise ValueError("Cari (müşteri/tedarikçi) seçilmeden fatura önizlenemez.")

    toplam = SatisFaturasiService.toplam(satirlar_dict)
    ara = toplam["ara_toplam"]
    isk = toplam["iskonto"]
    kdv = toplam["kdv"]
    satir_genel = toplam["genel_toplam"]  # Brüt (satırlardan)
    matrah = (ara - isk).quantize(_KURUS, rounding=ROUND_HALF_UP)

    brut = _d(tl_brut_db) if tl_brut_db is not None else satir_genel
    tur = islem_turunu_normalize(genel_islem_turu)
    oran = _d(genel_islem_orani or 0)
    tutar = _d(genel_islem_tutari or 0)
    if tl_genel_db is not None:
        net = _d(tl_genel_db)
        if tur or tutar or oran:
            try:
                sonuc = islem_uygula(
                    brut, islem_turu=tur, islem_orani=oran, islem_tutari=tutar, kaynak="tutar"
                )
                if abs(sonuc["net_toplam"] - net) > Decimal("0.05"):
                    sonuc = netten_islem(brut, net)
            except ValueError:
                sonuc = netten_islem(brut, net)
        elif abs(net - brut) > Decimal("0.009"):
            sonuc = netten_islem(brut, net)
        else:
            sonuc = {
                "brut_toplam": brut,
                "islem_turu": "",
                "islem_orani": Decimal("0"),
                "islem_tutari": Decimal("0"),
                "net_toplam": net,
            }
    else:
        sonuc = islem_uygula(
            brut, islem_turu=tur, islem_orani=oran, islem_tutari=tutar, kaynak="tutar"
        )
    genel = sonuc["net_toplam"]  # Baskıda Genel Toplam = Net
    islem_tur = sonuc["islem_turu"]
    islem_tutar = sonuc["islem_tutari"]
    fatura_brut = sonuc.get("brut_toplam", brut)
    islem_etiket = ""
    if islem_tur == "INDIRIM" and islem_tutar > 0:
        islem_etiket = "İndirim"
    elif islem_tur == "MASRAF" and islem_tutar > 0:
        islem_etiket = "Masraf"

    # Satır toplamları brüt ile tutarlı olmalı; net farkı işlem satırında
    satir_modelleri = _satirlari_satir_model(satirlar_dict, pb, ayarlar)
    satir_genel_sum = sum((s.satir_toplam for s in satir_modelleri), Decimal("0")).quantize(
        _KURUS, rounding=ROUND_HALF_UP
    )
    if abs(satir_genel_sum - satir_genel) > Decimal("0.05"):
        raise ValueError(
            "Fatura satırları ile genel toplam arasında fark bulundu. "
            "Lütfen faturayı kontrol edin."
        )

    tahsil = _d(tahsilat_tutari).quantize(_KURUS, rounding=ROUND_HALF_UP)
    kalan = (genel - tahsil).quantize(_KURUS, rounding=ROUND_HALF_UP)
    branding = load_company_branding()
    logo_uri = None
    if ayarlar.get("logo_goster", True):
        logo_uri = logo_data_uri(branding.get("logo_yolu"))

    banka = []
    if ayarlar.get("banka_goster", True):
        for ib in branding.get("ibanlar") or []:
            if isinstance(ib, dict) and (ib.get("iban") or ib.get("banka")):
                banka.append(
                    {
                        "banka": str(ib.get("banka") or ""),
                        "sube": str(ib.get("sube") or ""),
                        "hesap": str(ib.get("hesap") or ""),
                        "iban": str(ib.get("iban") or ""),
                        "pb": str(ib.get("pb") or pb),
                    }
                )

    def _t(x) -> str:
        if x is None:
            return ""
        if hasattr(x, "strftime"):
            return x.strftime("%d.%m.%Y")
        return str(x)

    vm = InvoicePrintViewModel(
        fatura_id=fatura_id,
        belge_turu=belge_turu,
        sablon_id=sablon,
        firma=branding,
        logo_yolu=branding.get("logo_yolu"),
        logo_data_uri=logo_uri,
        musteri=musteri,
        fatura_no=(fatura_no or "").strip() or "—",
        fatura_tarihi=_t(fatura_tarihi),
        islem_saati=(islem_saati or "").strip(),
        vade_tarihi=_t(vade_tarihi),
        vade_gunu=str(vade_gunu) if vade_gunu not in (None, "", 0, "0") else "",
        siparis_no=siparis_no or "",
        irsaliye_no=irsaliye_no or "",
        depo=depo or "",
        para_birimi=pb,
        kur=str(kur) if pb not in ("TRY", "TL") and kur else "",
        kur_tarihi=_t(kur_tarihi) if pb not in ("TRY", "TL") else "",
        odeme_sekli=odeme_sekli or "",
        durum=durum or "TASLAK",
        onaylandi=bool(onaylandi),
        filigran=_filigran(durum, onaylandi, ayarlar, sablon),
        satirlar=satir_modelleri,
        brut_toplam=ara,
        satir_iskonto=isk,
        ara_toplam=matrah,
        kdv_toplam=kdv,
        genel_toplam=genel,
        tahsil_edilen=tahsil,
        kalan_bakiye=kalan,
        fatura_brut_toplam=fatura_brut,
        fatura_brut_goster=_para(fatura_brut, pb),
        genel_islem_turu=islem_tur,
        genel_islem_tutari=islem_tutar,
        genel_islem_etiket=islem_etiket,
        genel_islem_goster=_para(islem_tutar, pb) if islem_etiket else "",
        brut_goster=_para(ara, pb),
        iskonto_goster=_para(isk, pb),
        ara_goster=_para(matrah, pb),
        kdv_goster=_para(kdv, pb),
        genel_goster=_para(genel, pb),
        tahsil_goster=_para(tahsil, pb),
        kalan_goster=_para(kalan, pb),
        kdv_dokum=_kdv_dokum(satirlar_dict, pb) if ayarlar.get("kdv_dokum_goster", True) else [],
        yaziyla_toplam=amount_to_words(genel, pb) if ayarlar.get("yaziyla_toplam_goster", True) else "",
        notlar=(aciklama or "").strip(),
        banka_satirlari=banka,
        alt_bilgi=str(branding.get("alt_bilgi") or "") if ayarlar.get("alt_bilgi_goster", True) else "",
        hazirlayan="",
        onaylayan=onaylayan or "",
        duzenleme_tarihi=duzenleme_tarihi or "",
        kaynak_siparis_olusturan=kaynak_siparis_olusturan or "",
        satis_personeli=(satis_personeli or "").strip(),
        ayarlar=ayarlar,
    )
    if pb not in ("TRY", "TL") and kur:
        vm.tl_karsilik = (genel * _d(kur)).quantize(_KURUS, rounding=ROUND_HALF_UP)
        vm.tl_goster = _para(vm.tl_karsilik, "TRY")
    vm.sayfalar = calculate_page_breaks(satir_modelleri, ayarlar)
    return vm


def build_invoice_print_model(
    invoice_id: int, *, template_id: str | None = None
) -> InvoicePrintViewModel:
    from database.satis_faturasi_service import SatisFaturasiService

    f = SatisFaturasiService.getir(int(invoice_id))
    if f is None:
        raise ValueError("Fatura bulunamadı.")
    cari = f.cari
    musteri = {
        "cari_kodu": getattr(cari, "cari_kodu", "") or "",
        "unvan": getattr(cari, "unvan", "") or "",
        "vergi_dairesi": getattr(cari, "vergi_dairesi", "") or "",
        "vergi_no": getattr(cari, "vergi_numarasi", "") or getattr(cari, "tc_kimlik", "") or "",
        "adres": (f.adres_metni or getattr(cari, "adres", "") or ""),
        "ilce": getattr(cari, "ilce", "") or "",
        "il": getattr(cari, "il", "") or "",
        "telefon": getattr(cari, "telefon", "") or getattr(cari, "cep_telefonu", "") or "",
        "email": getattr(cari, "email", "") or "",
    }
    satirlar = []
    for s in f.satirlar or []:
        satirlar.append(
            {
                "urun_kodu": s.urun_kodu,
                "urun_adi": s.urun_adi,
                "aciklama": s.aciklama,
                "miktar": s.miktar,
                "birim": s.birim,
                "birim_fiyat": s.birim_fiyat,
                "iskonto_orani": s.iskonto_orani,
                "iskonto_orani_2": s.iskonto_orani_2,
                "iskonto_orani_3": s.iskonto_orani_3,
                "kdv_orani": s.kdv_orani,
                "barkod": s.barkod,
                "lot_no": s.lot_no,
                "lot_cikisi": s.lot_cikisi,
            }
        )
    siparis_no = ""
    kaynak_siparis_olusturan = ""
    if f.siparis:
        siparis_no = getattr(f.siparis, "siparis_no", "") or ""
        from database.user_audit import display_user

        kaynak_siparis_olusturan = display_user(
            getattr(f.siparis, "created_by_full_name", None),
            getattr(f.siparis, "created_by_user_id", None),
        )
    irsaliye_no = ""
    if f.irsaliye:
        irsaliye_no = getattr(f.irsaliye, "irsaliye_no", "") or ""
    from database.user_audit import display_user, format_dt

    # Müşteri çıktısında sistem kullanıcısı gösterilmez; satış personeli ayara bağlı
    hazirlayan = ""
    onaylayan = (
        display_user(f.approved_by_full_name, f.approved_by_user_id)
        if f.approved_by_user_id or f.approved_by_full_name
        else ""
    )
    duzenleme = format_dt(f.updated_at or f.olusturma_tarihi)
    satis_personeli = (getattr(f, "sales_person_full_name", None) or "").strip()
    return build_from_satirlar(
        fatura_id=int(f.id),
        fatura_no=f.fatura_no,
        fatura_tarihi=f.fatura_tarihi,
        islem_saati=f.islem_saati or "",
        vade_tarihi=f.vade_tarihi,
        vade_gunu=f.vade_gunu,
        depo=f.depo or "",
        para_birimi=f.para_birimi or "TRY",
        kur=f.kur,
        kur_tarihi=f.kur_tarihi,
        durum=f.durum or "TASLAK",
        onaylandi=bool(f.onaylandi),
        aciklama=f.aciklama or "",
        satirlar_dict=satirlar,
        musteri=musteri,
        siparis_no=siparis_no,
        irsaliye_no=irsaliye_no,
        odeme_sekli=f.tahsilat_sekli or "",
        tahsilat_tutari=f.tahsilat_tutari or 0,
        tl_genel_db=_d(f.tl_genel_toplam) if f.tl_genel_toplam is not None else None,
        tl_brut_db=_d(getattr(f, "tl_brut_toplam", None))
        if getattr(f, "tl_brut_toplam", None) is not None
        else None,
        genel_islem_turu=getattr(f, "genel_islem_turu", None),
        genel_islem_orani=getattr(f, "genel_islem_orani", None),
        genel_islem_tutari=getattr(f, "genel_islem_tutari", None),
        sablon_id=template_id,
        hazirlayan=hazirlayan,
        onaylayan=onaylayan,
        duzenleme_tarihi=duzenleme,
        kaynak_siparis_olusturan=kaynak_siparis_olusturan,
        satis_personeli=satis_personeli,
    )


def build_from_kart(kart, *, template_id: str | None = None) -> InvoicePrintViewModel:
    """Açık SatisFaturasiDialog / AlisFaturasiDialog kartından (kayıtsız taslak dahil)."""
    from datetime import datetime

    alis = kart.__class__.__name__.startswith("Alis")
    belge_turu = (
        getattr(kart, "_print_belge_turu", None)
        or ("ALIŞ FATURASI" if alis else "SATIŞ FATURASI")
    )

    cari = None
    try:
        if hasattr(kart, "_secili_musteri"):
            cari = kart._secili_musteri()
        elif hasattr(kart, "tedarikci_map") and hasattr(kart, "tedarikci"):
            cari = kart.tedarikci_map.get(kart.tedarikci.get())
    except Exception:
        cari = None
    musteri = {
        "cari_kodu": getattr(cari, "cari_kodu", "") if cari else "",
        "unvan": getattr(cari, "unvan", "") if cari else "",
        "vergi_dairesi": getattr(cari, "vergi_dairesi", "") if cari else "",
        "vergi_no": (
            (getattr(cari, "vergi_numarasi", None) or getattr(cari, "tc_kimlik", "") or "")
            if cari
            else ""
        ),
        "adres": "",
        "ilce": getattr(cari, "ilce", "") if cari else "",
        "il": getattr(cari, "il", "") if cari else "",
        "telefon": (
            (getattr(cari, "telefon", None) or getattr(cari, "cep_telefonu", "") or "")
            if cari
            else ""
        ),
        "email": getattr(cari, "email", "") if cari else "",
    }
    try:
        if hasattr(kart, "_fatura_secili_adres"):
            adr = kart._fatura_secili_adres()
            if adr:
                musteri["adres"] = adr.get("metin") or adr.get("adres") or musteri["adres"]
                musteri["ilce"] = adr.get("ilce") or musteri["ilce"]
                musteri["il"] = adr.get("il") or musteri["il"]
    except Exception:
        pass
    if not musteri["adres"] and cari:
        musteri["adres"] = getattr(cari, "adres", "") or ""

    fatura_no = ""
    try:
        if hasattr(kart, "fatura_no_alani"):
            fatura_no = kart.fatura_no_alani.get().strip()
        elif hasattr(kart, "girdiler") and kart.girdiler.get("fatura_no"):
            fatura_no = kart.girdiler["fatura_no"].get().strip()
    except Exception:
        pass
    if not fatura_no and getattr(kart, "fatura", None):
        fatura_no = getattr(kart.fatura, "fatura_no", "") or ""

    tarih = None
    vade = None
    try:
        t_alan = "fatura_tarihi" if alis else "siparis_tarihi"
        t = kart.girdiler.get(t_alan).get().strip()
        tarih = datetime.strptime(t, "%d.%m.%Y").date() if t else None
    except Exception:
        pass
    try:
        v_alan = "vade_tarihi" if alis else "termin_tarihi"
        v = kart.girdiler.get(v_alan).get().strip()
        vade = datetime.strptime(v, "%d.%m.%Y").date() if v else None
    except Exception:
        pass

    durum = "TASLAK"
    onaylandi = False
    fatura_id = None
    tahsil = 0
    tl_genel = None
    islem_saati = ""
    vade_gunu = ""
    depo = ""
    pb = "TRY"
    kur = 1
    kur_tarihi = None
    odeme = ""
    aciklama = ""
    if getattr(kart, "fatura", None):
        f = kart.fatura
        fatura_id = getattr(f, "id", None)
        durum = f.durum or durum
        onaylandi = bool(getattr(f, "onaylandi", False))
        tahsil = getattr(f, "tahsilat_tutari", None) or getattr(f, "odeme_tutari", None) or 0
        tl_genel = f.tl_genel_toplam
        islem_saati = f.islem_saati or ""
        vade_gunu = getattr(f, "vade_gunu", "") or ""
        depo = f.depo or ""
        pb = f.para_birimi or "TRY"
        kur = f.kur
        kur_tarihi = getattr(f, "kur_tarihi", None)
        odeme = getattr(f, "tahsilat_sekli", None) or getattr(f, "odeme_sekli", None) or ""
        aciklama = f.aciklama or ""
        if not tarih:
            tarih = f.fatura_tarihi
        if not vade:
            vade = f.vade_tarihi
    try:
        if hasattr(kart, "depo") and kart.depo.get():
            depo = kart.depo.get()
    except Exception:
        pass
    try:
        if hasattr(kart, "girdiler") and kart.girdiler.get("aciklama"):
            aciklama = kart.girdiler["aciklama"].get().strip() or aciklama
    except Exception:
        pass
    try:
        if hasattr(kart, "ayrintili_notlar"):
            not_ek = kart.ayrintili_notlar.get("1.0", "end").strip()
            if not_ek:
                aciklama = f"{aciklama}\n{not_ek}".strip() if aciklama else not_ek
    except Exception:
        pass
    if hasattr(kart, "_doviz_para_birimi"):
        try:
            pb = (kart._doviz_para_birimi.get() or pb).upper()
        except Exception:
            pass
    try:
        if hasattr(kart, "girdiler") and kart.girdiler.get("islem_saati"):
            islem_saati = kart.girdiler["islem_saati"].get().strip() or islem_saati
    except Exception:
        pass

    satirlar = list(getattr(kart, "satirlar", None) or [])
    norm = []
    for s in satirlar:
        d = dict(s)
        if "birim_fiyat" not in d or d.get("birim_fiyat") in (None, ""):
            d["birim_fiyat"] = d.get(
                "birim_satis_fiyati", d.get("birim_alis_fiyati", 0)
            )
        norm.append(d)

    # Brüt her zaman satırlardan hesaplanır (ekrandaki eski Brüt PDF'ye gitmesin)
    tl_brut = None
    net_kart = getattr(kart, "_hesaplanan_genel", None)
    if net_kart is None:
        net_kart = getattr(kart, "_alis_net_toplam", None)
    if getattr(kart, "_hedef_net_toplam", None) is not None and getattr(
        kart, "_dagitim_uygulandi", False
    ):
        net_kart = kart._hedef_net_toplam
    if getattr(kart, "_alis_net_hedef", None) is not None and getattr(
        kart, "_alis_dagitim_uygulandi", False
    ):
        net_kart = kart._alis_net_hedef
    if net_kart is not None:
        tl_genel = net_kart
    islem_tur = getattr(kart, "_genel_islem_turu", None)
    if islem_tur is None:
        islem_tur = getattr(kart, "_alis_genel_islem_turu", None)
    islem_oran = getattr(kart, "_genel_islem_orani", None)
    if islem_oran is None:
        islem_oran = getattr(kart, "_alis_genel_islem_orani", None)
    islem_tutar = getattr(kart, "_genel_islem_tutari", None)
    if islem_tutar is None:
        islem_tutar = getattr(kart, "_alis_genel_islem_tutari", None)
    if islem_tur is None and getattr(kart, "fatura", None):
        fobj = kart.fatura
        islem_tur = getattr(fobj, "genel_islem_turu", None)
        islem_oran = getattr(fobj, "genel_islem_orani", None)
        islem_tutar = getattr(fobj, "genel_islem_tutari", None)

    siparis_no = ""
    irsaliye_no = ""
    try:
        if hasattr(kart, "siparis_no"):
            siparis_no = (kart.siparis_no.get() if hasattr(kart.siparis_no, "get") else str(kart.siparis_no or "")).strip()
    except Exception:
        pass
    try:
        if hasattr(kart, "irsaliye_no"):
            irsaliye_no = (kart.irsaliye_no.get() if hasattr(kart.irsaliye_no, "get") else str(kart.irsaliye_no or "")).strip()
    except Exception:
        pass

    return build_from_satirlar(
        fatura_id=int(fatura_id) if fatura_id else None,
        fatura_no=fatura_no,
        fatura_tarihi=tarih,
        islem_saati=islem_saati,
        vade_tarihi=vade,
        vade_gunu=vade_gunu,
        depo=depo,
        para_birimi=pb,
        kur=kur,
        kur_tarihi=kur_tarihi,
        durum=durum,
        onaylandi=onaylandi,
        aciklama=aciklama,
        satirlar_dict=norm,
        musteri=musteri,
        siparis_no=siparis_no,
        irsaliye_no=irsaliye_no,
        odeme_sekli=odeme,
        tahsilat_tutari=tahsil,
        tl_genel_db=_d(tl_genel) if tl_genel is not None else None,
        tl_brut_db=_d(tl_brut) if tl_brut is not None else None,
        genel_islem_turu=islem_tur,
        genel_islem_orani=islem_oran,
        genel_islem_tutari=islem_tutar,
        sablon_id=template_id,
        belge_turu=belge_turu,
        hazirlayan=_kart_hazirlayan(kart),
        onaylayan=_kart_onaylayan(kart),
        duzenleme_tarihi=_kart_duzenleme(kart),
        kaynak_siparis_olusturan=_kart_siparis_olusturan(kart),
        satis_personeli=_kart_satis_personeli(kart),
    )


def _kart_hazirlayan(kart) -> str:
    # Müşteri çıktısında sistem kullanıcısı gösterilmez
    return ""


def _kart_satis_personeli(kart) -> str:
    panel = getattr(kart, "_satis_personeli_panel", None)
    if panel and callable(panel.get("secili_id")):
        sid = panel["secili_id"]()
        if sid and panel.get("personel_map"):
            p = panel["personel_map"].get(int(sid))
            if p:
                return (p.get("ad_soyad") or "").strip()
    obj = getattr(kart, "fatura", None)
    if obj:
        return (getattr(obj, "sales_person_full_name", None) or "").strip()
    return ""


def _kart_onaylayan(kart) -> str:
    from database.user_audit import display_user

    obj = getattr(kart, "fatura", None) or getattr(kart, "siparis", None)
    if obj and (getattr(obj, "approved_by_full_name", None) or getattr(obj, "approved_by_user_id", None)):
        return display_user(obj.approved_by_full_name, obj.approved_by_user_id)
    return ""


def _kart_duzenleme(kart) -> str:
    from database.user_audit import format_dt

    obj = getattr(kart, "fatura", None) or getattr(kart, "siparis", None)
    if obj:
        return format_dt(getattr(obj, "updated_at", None) or getattr(obj, "olusturma_tarihi", None))
    return ""


def _kart_siparis_olusturan(kart) -> str:
    from database.user_audit import display_user

    sip = getattr(kart, "kaynak_siparis", None) or getattr(kart, "siparis", None)
    if sip and (getattr(sip, "created_by_full_name", None) or getattr(sip, "created_by_user_id", None)):
        return display_user(sip.created_by_full_name, sip.created_by_user_id)
    return ""
