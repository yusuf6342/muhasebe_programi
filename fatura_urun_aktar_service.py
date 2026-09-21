"""Satış faturası — ürün seçiminden satıra otomatik aktarım (ortak şablon).

Barkod ve ürün arama aynı satır birleştirme kurallarını kullanır.
Hesaplar Decimal; UI yalnızca sonucu gösterir.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from database.stok_service import StokService, decimal
from fatura_barkod_ui import (
    _musteri_fiyat,
    _satir_birlestirilebilir,
)
from fatura_satir_birim_service import birim_satis_fiyati, temel_miktar


def _d(deger, varsayilan: Decimal = Decimal("0")) -> Decimal:
    try:
        return decimal(deger if deger is not None else varsayilan, "değer", varsayilan)
    except Exception:
        return varsayilan


def birincil_barkod_al(stok) -> str:
    """Stok kartının varsayılan / birinci barkodu (stok.barkod veya ilk ek barkod)."""
    if stok is None:
        return ""
    try:
        kod = StokService._hizli_satis_birincil_barkod(stok)
    except Exception:
        kod = None
    if kod:
        return str(kod).strip()
    ana = (getattr(stok, "barkod", None) or "").strip()
    if ana:
        return ana
    for kayit in getattr(stok, "barkodlar", None) or []:
        b = (getattr(kayit, "barkod", None) or "").strip()
        if b:
            return b
    return ""


def stok_kartini_coz(
    *,
    product_id: int | None = None,
    stok_kodu: str = "",
) -> Any | None:
    """Stok kartını id veya tam stok_kodu ile yükle (barkodlar dahil)."""
    pid = product_id
    if pid is not None:
        try:
            pid = int(pid)
        except (TypeError, ValueError):
            pid = None
    if pid:
        try:
            stok = StokService.stok_getir(pid)
            if stok is not None:
                return stok
        except Exception:
            pass
    kod = (stok_kodu or "").strip()
    if not kod:
        return None
    try:
        from database.database import get_session

        with get_session() as session:
            stok = StokService._stok_yukle(session, stok_kodu=kod)
            if stok is not None:
                return stok
    except Exception:
        pass
    try:
        bulunan = StokService.stoklari_ara(kod)
        return next((s for s in bulunan if (s.stok_kodu or "").strip() == kod), None)
    except Exception:
        return None


def urun_kartindan_tanimlayicilar(
    *,
    product_id: int | None = None,
    stok_kodu: str = "",
    okutulan_barkod: str = "",
    stok=None,
) -> tuple[str, str, str]:
    """Ürün kartından (barkod, stok_kodu, stok_adi) döner.

    Eşitleme: barkodu stok koduna kopyalamaz. Taranan barkod kartta ek barkodsa
    satırda tarananı korur; aksi halde birincil barkodu kullanır.
    """
    kart = stok
    if kart is None:
        kart = stok_kartini_coz(product_id=product_id, stok_kodu=stok_kodu)
    if kart is None:
        kod = (stok_kodu or "").strip()
        return ("", kod, "")

    kod = (getattr(kart, "stok_kodu", None) or stok_kodu or "").strip()
    ad = (getattr(kart, "stok_adi", None) or "").strip()
    birincil = birincil_barkod_al(kart)
    tarama = (okutulan_barkod or "").strip()

    if tarama:
        # Taranan barkod bu karta aitse (ana veya ek) satırda onu tut
        kart_barkodlari = {birincil} if birincil else set()
        ana = (getattr(kart, "barkod", None) or "").strip()
        if ana:
            kart_barkodlari.add(ana)
        for kayit in getattr(kart, "barkodlar", None) or []:
            b = (getattr(kayit, "barkod", None) or "").strip()
            if b:
                kart_barkodlari.add(b)
        if tarama in kart_barkodlari or not birincil:
            barkod = tarama
        else:
            barkod = birincil
    else:
        barkod = birincil

    return (barkod, kod, ad)


def urun_secim_seridini_doldur(dialog, barkod: str, stok_kodu: str, stok_adi: str) -> None:
    """Ürün seçim şeridine (barkod / kod / ad) kart değerlerini yazar."""
    girdiler = getattr(dialog, "satir_girdileri", None) or {}
    for anahtar, deger in (
        ("barkod", barkod),
        ("urun_kodu", stok_kodu),
        ("urun_adi", stok_adi),
    ):
        w = girdiler.get(anahtar)
        if w is None:
            continue
        try:
            w.delete(0, "end")
            if deger:
                w.insert(0, deger)
        except Exception:
            pass


def fatura_pb_ve_kur(dialog) -> tuple[str, Decimal]:
    """Fatura başlığından satır varsayılan PB ve kur."""
    pb = "TRY"
    try:
        if hasattr(dialog, "_doviz_para_birimi"):
            pb = (dialog._doviz_para_birimi.get() or "TRY").upper()
    except Exception:
        pb = "TRY"
    if pb in ("TL", "TRY"):
        pb = "TRY"
    kur = Decimal("1")
    if pb != "TRY":
        try:
            if hasattr(dialog, "_doviz_kur"):
                kur = Decimal(str(dialog._doviz_kur.get() or "1").replace(",", "."))
        except Exception:
            kur = Decimal("1")
        if kur <= 0:
            kur = Decimal("1")
    return pb, kur


def stoktan_satir_sablonu(
    dialog,
    *,
    urun_kodu: str,
    urun_adi: str = "",
    birim: str | None = None,
    barkod: str = "",
    miktar: Decimal | None = None,
    birim_fiyat: Decimal | None = None,
    kdv_orani: Decimal | None = None,
    product_id: int | None = None,
) -> dict[str, Any]:
    """Seçilen stoktan fatura satırı sözlüğü (miktar=1 varsayılan)."""
    kod = (urun_kodu or "").strip()
    depo = ""
    try:
        depo = (dialog.depo.get() or "").strip()
    except Exception:
        depo = ""

    stok = stok_kartini_coz(product_id=product_id, stok_kodu=kod)
    barkod_metin, kod, ad_kart = urun_kartindan_tanimlayicilar(
        product_id=product_id,
        stok_kodu=kod,
        okutulan_barkod=(barkod or "").strip(),
        stok=stok,
    )
    if (barkod or "").strip() and not barkod_metin:
        # Kart çözülemediyse tarananı satırda tut (kod alanına yazma)
        barkod_metin = (barkod or "").strip()

    ana_birim = (birim or (getattr(stok, "birim", None) if stok else None) or "Adet").strip() or "Adet"
    ad = (urun_adi or "").strip() or ad_kart or kod

    musteri = None
    if hasattr(dialog, "_secili_musteri"):
        try:
            musteri = dialog._secili_musteri()
        except Exception:
            musteri = None

    if birim_fiyat is None:
        fiyat = birim_satis_fiyati(kod, ana_birim, musteri=musteri)
        if fiyat is None:
            fiyat = _musteri_fiyat(dialog, kod, Decimal("0"))
    else:
        fiyat = _d(birim_fiyat)

    if kdv_orani is None:
        from database.fatura_kdv_service import satir_kdv_belirle

        kdv_ham = getattr(stok, "kdv_orani", None) if stok else None
        kdv = satir_kdv_belirle(stok_kdv=kdv_ham)
    else:
        from database.fatura_kdv_service import satir_kdv_belirle

        kdv = satir_kdv_belirle(kaynak_kdv=kdv_orani)

    iskonto1 = Decimal("0")
    if stok is not None:
        iskonto1 = _d(getattr(stok, "iskonto_1", 0), Decimal("0"))

    miktar_ekle = miktar if miktar is not None else Decimal("1")
    pb, kur = fatura_pb_ve_kur(dialog)

    sablon: dict[str, Any] = {
        "urun_kodu": kod,
        "urun_adi": ad,
        "aciklama": "",
        "miktar": str(miktar_ekle),
        "birim": ana_birim,
        "birim_satis_fiyati": str(fiyat),
        "iskonto_orani": str(iskonto1),
        "iskonto_orani_2": "0",
        "iskonto_orani_3": "0",
        "kdv_orani": str(kdv),
        "barkod": barkod_metin,
        "lot_no": "",
        "lot_cikisi": "",
        "depo": depo,
        "satir_para_birimi": pb,
        "para_birimi": pb,
        "kur": str(kur),
        "manuel_fiyat": False,
        "irsaliyelenen_miktar": 0,
        "faturalanan_miktar": 0,
        "fifo_birim_maliyeti": "0",
        "son_alis_birim_maliyeti": "0",
        "ortalama_birim_maliyeti": "0",
        "agirlikli_ortalama_birim_maliyeti": "0",
        "temel_miktar": str(temel_miktar(miktar_ekle, ana_birim, kod)),
    }
    try:
        if depo:
            maliyetler = StokService.maliyetler(kod, depo)
            for alan, anahtar in (
                ("fifo_birim_maliyeti", "fifo"),
                ("son_alis_birim_maliyeti", "son_alis"),
                ("ortalama_birim_maliyeti", "ortalama"),
                ("agirlikli_ortalama_birim_maliyeti", "agirlikli"),
            ):
                sablon[alan] = str(maliyetler.get(anahtar, 0))
    except Exception:
        pass
    return sablon


def urunu_faturaya_aktar(
    dialog,
    sablon: dict[str, Any],
    *,
    miktar_ekle: Decimal | None = None,
    birlestir: bool = True,
) -> int:
    """Şablonu satırlara ekle veya birleştir. Dönüş: satır indeksi."""
    from fatura_barkod_ui import _satiri_vurgula

    if getattr(dialog, "_fatura_kilitli", False):
        raise ValueError("Onaylı faturada ürün eklemek için önce Onay Kaldır yapın.")

    depo = (sablon.get("depo") or "").strip()
    try:
        if not depo and hasattr(dialog, "depo"):
            depo = (dialog.depo.get() or "").strip()
            sablon["depo"] = depo
    except Exception:
        pass

    miktar_ekle = miktar_ekle if miktar_ekle is not None else _d(sablon.get("miktar"), Decimal("1"))
    if miktar_ekle <= 0:
        miktar_ekle = Decimal("1")
    sablon["miktar"] = str(miktar_ekle)
    kod = (sablon.get("urun_kodu") or "").strip()
    birim = (sablon.get("birim") or "Adet").strip()
    ek_temel = temel_miktar(miktar_ekle, birim, kod)
    sablon["temel_miktar"] = str(ek_temel)

    hedef_idx = None
    if birlestir:
        for i, mevcut in enumerate(dialog.satirlar):
            if _satir_birlestirilebilir(mevcut, sablon, depo=depo):
                hedef_idx = i
                break

    if hedef_idx is not None:
        mevcut = dialog.satirlar[hedef_idx]
        yeni_miktar = _d(mevcut.get("miktar")) + miktar_ekle
        # Stok kontrolü yalnızca Kaydet ve Onayla sırasında
        mevcut["miktar"] = str(yeni_miktar)
        mevcut["temel_miktar"] = str(
            temel_miktar(yeni_miktar, mevcut.get("birim") or birim, kod)
        )
        if not (mevcut.get("barkod") or "").strip() and sablon.get("barkod"):
            mevcut["barkod"] = sablon["barkod"]
        idx = hedef_idx
    else:
        if hasattr(dialog, "_doviz_para_birimi"):
            try:
                from doviz_fatura_panel import doviz_satir_kaydet_oncesi

                sablon = doviz_satir_kaydet_oncesi(dialog, sablon)
            except Exception:
                pass
        dialog.satirlar.append(sablon)
        idx = len(dialog.satirlar) - 1

    dialog._fatura_satirlari_hazir = True
    dialog._duzenlenen_satir = None
    dialog._satir_listesini_yenile()
    dialog._toplamlari_guncelle()
    _satiri_vurgula(dialog, idx)
    try:
        from fatura_satir_hucre_edit import satir_ilk_alana_odakla

        satir_ilk_alana_odakla(dialog, idx)
    except Exception:
        pass
    return idx


def urun_seciminden_aktar(dialog, degerler) -> int:
    """ProductSelectionDialog / stok listesi tuple → satıra aktar.

    degerler: (kod, ad, birim, stok_miktar, fiyat, kaynak?, kdv?[, product_id?])
    """
    kod = (degerler[0] or "").strip()
    if not kod:
        raise ValueError("Ürün kodu boş.")
    ad = degerler[1] if len(degerler) > 1 else ""
    birim = degerler[2] if len(degerler) > 2 else None
    fiyat = None
    if len(degerler) > 4 and str(degerler[4]).strip():
        try:
            fiyat = _d(degerler[4])
        except Exception:
            fiyat = None
    kdv = None
    if len(degerler) > 6 and degerler[6] is not None and str(degerler[6]).strip() != "":
        try:
            kdv = _d(degerler[6])
        except Exception:
            kdv = None
    product_id = None
    if len(degerler) > 7 and degerler[7] is not None and str(degerler[7]).strip() != "":
        try:
            product_id = int(degerler[7])
        except (TypeError, ValueError):
            product_id = None

    barkod, kod_kart, ad_kart = urun_kartindan_tanimlayicilar(
        product_id=product_id,
        stok_kodu=kod,
    )
    # Şeritte kısa süre doğru kart bilgilerini göster (sonra temizlenir)
    urun_secim_seridini_doldur(dialog, barkod, kod_kart or kod, ad_kart or (ad or ""))

    sablon = stoktan_satir_sablonu(
        dialog,
        urun_kodu=kod_kart or kod,
        urun_adi=ad_kart or (ad or ""),
        birim=birim,
        barkod=barkod,
        birim_fiyat=fiyat if fiyat and fiyat > 0 else None,
        kdv_orani=kdv,
        product_id=product_id,
    )
    return urunu_faturaya_aktar(dialog, sablon, miktar_ekle=Decimal("1"), birlestir=True)
