"""EvoBulut → yerel aktarım ortak yardımcılar."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from typing import Any, Callable

from sqlalchemy import select

from database.cari_service import CariService
from database.database import get_session
from database.models.cari import Cari
from database.models.stok import StokKarti
from database.stok_service import StokService
from entegrasyon.stok_import import kaydet_veya_guncelle

DETAY_BEKLE_SN = 1.05


@dataclass
class ImportSonuc:
    cekilen: int = 0
    olusturulan: int = 0
    atlanan: int = 0
    stok_eklenen: int = 0
    oto_giris: int = 0
    hatalar: list[str] = field(default_factory=list)


def _temiz(deger: Any) -> str:
    if deger is None:
        return ""
    return str(deger).strip()


def _decimal(deger: Any, varsayilan: Decimal | None = None) -> Decimal | None:
    metin = _temiz(deger).replace(" ", "").replace(",", ".")
    if not metin or metin in {"-", "—"}:
        return varsayilan
    try:
        return Decimal(metin)
    except (InvalidOperation, ValueError):
        return varsayilan


def _tarih(deger: Any) -> date | None:
    metin = _temiz(deger)
    if not metin:
        return None
    for fmt in ("%d.%m.%Y %H:%M:%S", "%d.%m.%Y"):
        try:
            return datetime.strptime(metin[:19] if " " in metin else metin[:10], fmt).date()
        except ValueError:
            continue
    return None


def _tarih_sirala_anahtar(satir: dict) -> date:
    t = _tarih(satir.get("G.a_tarih") or satir.get("a_tarih"))
    return t or date.min


def belge_no_icin(
    liste_satir: dict,
    ana: dict,
    *,
    onek: str,
    kod_onek: str = "",
) -> str:
    seri = _temiz(ana.get("a_sbelge_seri_no") or liste_satir.get("G.a_sbelge_seri_no"))
    if seri:
        return seri[:50]
    kod = _temiz(ana.get("a_kod") or liste_satir.get("G.a_kod"))
    if kod and kod not in {"0", ""} and kod_onek:
        return f"{kod_onek}{kod}"[:50]
    aid = _temiz(ana.get("a_id") or liste_satir.get("G.a_id") or liste_satir.get("a_id"))
    return f"{onek}{aid}"[:50]


def _cari_kodu(liste_satir: dict, ana: dict) -> str:
    return _temiz(
        ana.get("a_mkod")
        or liste_satir.get("TBL_REHBER.a_kod")
        or liste_satir.get("a_mkod")
        or ana.get("a_cari_kod")
    )


def cari_bul_veya_hata(liste_satir: dict, ana: dict) -> Cari:
    kod = _cari_kodu(liste_satir, ana)
    if kod:
        cari = CariService.kod_ile_getir(kod)
        if cari:
            return cari
    unvan = _temiz(
        ana.get("CARI_ADI")
        or liste_satir.get("CARI_ADI")
        or ana.get("a_fcari")
        or ana.get("a_cari_adi")
    )
    if unvan:
        with get_session() as session:
            adaylar = list(session.scalars(select(Cari).where(Cari.unvan == unvan)).all())
            if len(adaylar) == 1:
                return adaylar[0]
            hepsi = list(session.scalars(select(Cari)).all())
            eslesen = [
                c for c in hepsi if (c.unvan or "").casefold().strip() == unvan.casefold()
            ]
            if len(eslesen) == 1:
                return eslesen[0]
    raise ValueError(f"Cari bulunamadı kod={kod!r} unvan={unvan!r}")


def _stok_var_mi(kod: str) -> bool:
    with get_session() as session:
        return (
            session.scalar(select(StokKarti.id).where(StokKarti.stok_kodu == kod))
            is not None
        )


def stok_garanti(line: dict[str, Any], sonuc: ImportSonuc) -> str:
    kod = _temiz(line.get("a_kod") or line.get("a_kod1"))
    if not kod:
        raise ValueError("Satırda stok kodu yok")
    if _stok_var_mi(kod):
        return kod
    ad = _temiz(line.get("a_stok_adi")) or kod
    birim = _temiz(line.get("a_brm_adi")) or "Adet"
    fiyat = _decimal(line.get("a_brm_fiy"), Decimal("0")) or Decimal("0")
    veriler = {
        "stok_kodu": kod[:50],
        "stok_adi": ad[:200],
        "birim": birim[:20],
        "kart_turu": "Ticari Mal",
        "aktif": True,
        "barkod": kod if kod.isdigit() and 8 <= len(kod) <= 14 else None,
        "_fiyatlar": [("ALIŞ FİYATI", str(fiyat))] if fiyat > 0 else [],
    }
    durum = kaydet_veya_guncelle(veriler)
    if durum == "eklendi":
        sonuc.stok_eklenen += 1
    if not _stok_var_mi(kod):
        raise ValueError(f"Stok oluşturulamadı: {kod}")
    return kod


def satir_verisi_fatura(line: dict[str, Any], sonuc: ImportSonuc) -> dict[str, Any]:
    kod = stok_garanti(line, sonuc)
    miktar = _decimal(line.get("a_brm_mik"))
    if miktar is None or miktar <= 0:
        miktar = _decimal(line.get("a_mik"))
    if miktar is None or miktar <= 0:
        raise ValueError(f"Geçersiz miktar stok={kod}")

    brut_fiyat = _decimal(line.get("a_brm_fiy"))
    net_satir = _decimal(line.get("a_tutar_kdvh"))
    iskonto = Decimal("0")
    birim_fiyat = brut_fiyat
    if brut_fiyat is not None and brut_fiyat > 0 and net_satir is not None and miktar > 0:
        net_birim = (net_satir / miktar).quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)
        if net_birim < brut_fiyat:
            iskonto = (
                (Decimal("1") - (net_birim / brut_fiyat)) * Decimal("100")
            ).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
            birim_fiyat = brut_fiyat
        else:
            birim_fiyat = brut_fiyat
    elif net_satir is not None and miktar > 0:
        birim_fiyat = (net_satir / miktar).quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)
        iskonto = Decimal("0")
    elif birim_fiyat is None:
        birim_fiyat = Decimal("0")

    kdv = _decimal(line.get("a_kdv"), Decimal("20")) or Decimal("20")
    birim = _temiz(line.get("a_brm_adi")) or "Adet"
    ad = _temiz(line.get("a_stok_adi")) or kod

    return {
        "urun_kodu": kod,
        "urun_adi": ad[:200],
        "miktar": miktar,
        "birim": birim[:20],
        "birim_fiyat": birim_fiyat,
        "iskonto_orani": iskonto if iskonto >= 0 else Decimal("0"),
        "kdv_orani": kdv,
        "barkod": kod if kod.isdigit() and 8 <= len(kod) <= 14 else None,
        "aciklama": _temiz(line.get("a_ack"))[:500] or None,
    }


def satir_verisi_iade(line: dict[str, Any], sonuc: ImportSonuc) -> dict[str, Any]:
    sv = satir_verisi_fatura(line, sonuc)
    return {
        "urun_kodu": sv["urun_kodu"],
        "urun_adi": sv["urun_adi"],
        "miktar": sv["miktar"],
        "birim": sv["birim"],
        "birim_fiyat": sv["birim_fiyat"],
        "iskonto_orani": sv["iskonto_orani"],
        "kdv_orani": sv["kdv_orani"],
        "lot_no": None,
    }


def satir_verisi_siparis(
    line: dict[str, Any],
    sonuc: ImportSonuc,
    *,
    fiyat_alani: str,
) -> dict[str, Any]:
    """fiyat_alani: birim_satis_fiyati | birim_alis_fiyati"""
    sv = satir_verisi_fatura(line, sonuc)
    out = {
        "urun_kodu": sv["urun_kodu"],
        "urun_adi": sv["urun_adi"],
        "miktar": sv["miktar"],
        "birim": sv["birim"],
        "iskonto_orani": sv["iskonto_orani"],
        "kdv_orani": sv["kdv_orani"],
        "aciklama": sv.get("aciklama"),
    }
    out[fiyat_alani] = sv["birim_fiyat"]
    if fiyat_alani == "birim_satis_fiyati":
        out["fifo_birim_maliyeti"] = Decimal("0")
        out["son_alis_birim_maliyeti"] = Decimal("0")
        out["ortalama_birim_maliyeti"] = Decimal("0")
        out["agirlikli_ortalama_birim_maliyeti"] = Decimal("0")
    return out


def satir_verisi_irsaliye(line: dict[str, Any], sonuc: ImportSonuc) -> dict[str, Any]:
    sv = satir_verisi_fatura(line, sonuc)
    return {
        "urun_kodu": sv["urun_kodu"],
        "urun_adi": sv["urun_adi"],
        "miktar": sv["miktar"],
        "birim": sv["birim"],
        "birim_fiyat": sv["birim_fiyat"],
        "iskonto_orani": sv["iskonto_orani"],
        "kdv_orani": sv["kdv_orani"],
        "aciklama": sv.get("aciklama"),
    }


def depo_mevcut_miktar(stok_kodu: str, depo_adi: str = "ANA DEPO") -> Decimal:
    lotlar = StokService.lotlar(stok_kodu, depo_adi)
    return sum((lot.kalan_miktar for lot in lotlar), Decimal("0"))


def stok_yetersizligi_kapat(
    satirlar: list[dict[str, Any]],
    *,
    fatura_no: str,
    tarih: date,
    depo: str,
    sonuc: ImportSonuc,
) -> None:
    """Çıkış belgelerinden önce eksik stoğu EVB-OTO- girişiyle tamamlar."""
    StokService.varsayilanlari_hazirla()
    for sv in satirlar:
        kod = sv["urun_kodu"]
        miktar = Decimal(str(sv["miktar"]))
        mevcut = depo_mevcut_miktar(kod, depo)
        if mevcut >= miktar:
            continue
        gap = miktar - mevcut
        maliyet = Decimal(str(sv.get("birim_fiyat") or sv.get("birim_satis_fiyati") or 0))
        lot_no = f"EVB-OTO-{fatura_no}"[:50]
        StokService.stok_girisi(
            kod,
            depo,
            "EVO OTO",
            tarih,
            gap,
            maliyet if maliyet >= 0 else Decimal("0"),
            lot_no=lot_no,
        )
        sonuc.oto_giris += 1


def progress_log(progress: Callable[[str], None] | None, msg: str) -> None:
    if progress:
        progress(msg)
    else:
        print(msg, flush=True)
