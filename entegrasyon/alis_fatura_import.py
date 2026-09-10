"""EvoBulut alış faturalarını (tur=30) yerel AlisFaturasi'ye aktarma.

Liste: POST fatura/base/ cmd=jq_list tur=30
Detay: POST fatura/base/ cmd=sql sql_id=…
Tam yan etki: AlisFaturasiService.kaydet (stok FATURA GİRİŞ + cari SatisHareketi)

İdempotent belge: a_sbelge_seri_no veya EVB-AF-{a_id}
Eksik stok kartları satırdan otomatik oluşturulur.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from typing import Any, Callable

from sqlalchemy import select

from database.alis_faturasi_service import AlisFaturasiService
from database.cari_service import CariService
from database.database import get_session
from database.models.alis_faturasi import AlisFaturasi
from database.models.cari import Cari
from database.models.stok import StokKarti
from database.stok_service import StokService

from database.models.satis_siparisi import SatisSiparisi  # noqa: F401
from database.models.satis_irsaliyesi import SatisIrsaliyesi  # noqa: F401
from database.models.satis_faturasi import SatisFaturasi  # noqa: F401

from entegrasyon.stok_import import kaydet_veya_guncelle

BELGE_ONEK = "EVB-AF-"
DETAY_BEKLE_SN = 1.05  # ~60 istek/dk EvoBulut limiti


@dataclass
class AlisFaturaImportSonuc:
    cekilen: int = 0
    olusturulan: int = 0
    atlanan: int = 0
    stok_eklenen: int = 0
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
    # "08.09.2026 00:00:00" veya "08.09.2026"
    for fmt in ("%d.%m.%Y %H:%M:%S", "%d.%m.%Y"):
        try:
            return datetime.strptime(metin[:19] if " " in metin else metin[:10], fmt).date()
        except ValueError:
            continue
    return None


def fatura_no_icin(liste_satir: dict, ana: dict) -> str:
    seri = _temiz(ana.get("a_sbelge_seri_no") or liste_satir.get("G.a_sbelge_seri_no"))
    if seri:
        return seri[:50]
    kod = _temiz(ana.get("a_kod") or liste_satir.get("G.a_kod"))
    if kod and kod not in {"0", ""}:
        return f"AF{kod}"[:50]
    aid = _temiz(ana.get("a_id") or liste_satir.get("G.a_id"))
    return f"{BELGE_ONEK}{aid}"[:50]


def fatura_var_mi(fatura_no: str) -> bool:
    no = _temiz(fatura_no)
    if not no:
        return False
    with get_session() as session:
        return (
            session.scalar(select(AlisFaturasi.id).where(AlisFaturasi.fatura_no == no))
            is not None
        )


def _cari_kodu(liste_satir: dict, ana: dict) -> str:
    return _temiz(
        ana.get("a_mkod")
        or liste_satir.get("TBL_REHBER.a_kod")
        or liste_satir.get("a_mkod")
    )


def _cari_bul_veya_hata(liste_satir: dict, ana: dict) -> Cari:
    kod = _cari_kodu(liste_satir, ana)
    if kod:
        cari = CariService.kod_ile_getir(kod)
        if cari:
            return cari
    # Unvan ile tek eşleşme
    unvan = _temiz(ana.get("CARI_ADI") or liste_satir.get("CARI_ADI") or ana.get("a_fcari"))
    if unvan:
        with get_session() as session:
            adaylar = list(
                session.scalars(
                    select(Cari).where(Cari.unvan == unvan)
                ).all()
            )
            if len(adaylar) == 1:
                return adaylar[0]
            # casefold
            hepsi = list(session.scalars(select(Cari)).all())
            eslesen = [
                c
                for c in hepsi
                if (c.unvan or "").casefold().strip() == unvan.casefold()
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


def _stok_garanti(line: dict[str, Any], sonuc: AlisFaturaImportSonuc) -> str:
    """Stok kodunu döner; yoksa minimal kart oluşturur."""
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


def _satir_verisi(line: dict[str, Any], sonuc: AlisFaturaImportSonuc) -> dict[str, Any]:
    kod = _stok_garanti(line, sonuc)
    miktar = _decimal(line.get("a_brm_mik"))
    if miktar is None or miktar <= 0:
        # ana birim miktarı
        miktar = _decimal(line.get("a_mik"))
    if miktar is None or miktar <= 0:
        raise ValueError(f"Geçersiz miktar stok={kod}")

    brut_fiyat = _decimal(line.get("a_brm_fiy"))
    net_satir = _decimal(line.get("a_tutar_kdvh"))  # KDV hariç satır tutarı
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


def _tek_fatura_aktar(
    client,
    liste_satir: dict[str, Any],
    sonuc: AlisFaturaImportSonuc,
) -> None:
    aid = _temiz(liste_satir.get("G.a_id") or liste_satir.get("a_id"))
    if not aid:
        raise ValueError("Fatura a_id yok")

    detay = client.fatura_detay(aid)
    ana = detay.get("Ana") or {}
    satirlar_ham = detay.get("Detay") or []
    if not satirlar_ham:
        raise ValueError(f"Fatura {aid}: satır yok")

    fatura_no = fatura_no_icin(liste_satir, ana)
    if fatura_var_mi(fatura_no):
        sonuc.atlanan += 1
        return

    cari = _cari_bul_veya_hata(liste_satir, ana)
    tarih = _tarih(ana.get("a_tarih") or liste_satir.get("G.a_tarih"))
    vade = _tarih(ana.get("a_vtarih") or liste_satir.get("G.a_vtarih")) or tarih
    if not tarih:
        raise ValueError(f"Fatura {aid}: tarih yok")
    if vade < tarih:
        vade = tarih

    # Yerelde tek varsayılan depo; EvoBulut "Ana Depo" eşlemesi
    StokService.varsayilanlari_hazirla()
    depo = "ANA DEPO"
    aciklama = _temiz(ana.get("a_ack"))[:500] or None

    satir_verileri = []
    for line in satirlar_ham:
        try:
            satir_verileri.append(_satir_verisi(line, sonuc))
        except ValueError as exc:
            # sıfır miktarlı satırları atla
            if "miktar" in str(exc).casefold():
                continue
            raise

    if not satir_verileri:
        raise ValueError(f"Fatura {aid}: geçerli satır yok")

    AlisFaturasiService.kaydet(
        {
            "fatura_no": fatura_no,
            "fatura_tarihi": tarih,
            "vade_tarihi": vade,
            "cari_id": cari.id,
            "depo": depo,
            "aciklama": aciklama,
            "odeme_tutari": 0,
        },
        satir_verileri,
    )
    sonuc.olusturulan += 1


def aktar_api_den(
    *,
    tarih_bas: str = "",
    tarih_son: str = "",
    ara: str = "",
    max_adet: int | None = None,
    progress: Callable[[str], None] | None = None,
) -> AlisFaturaImportSonuc:
    from entegrasyon.evobulut_client import EvobulutClient, load_credentials

    def log(msg: str) -> None:
        if progress:
            progress(msg)
        else:
            print(msg, flush=True)

    client = EvobulutClient(load_credentials())
    client.login()
    log("Alış fatura listesi çekiliyor (tur=30)…")
    liste = client.tum_alis_faturalari_cek(
        ara=ara, tarih_bas=tarih_bas, tarih_son=tarih_son
    )
    if max_adet is not None:
        liste = liste[: max(0, int(max_adet))]
    sonuc = AlisFaturaImportSonuc(cekilen=len(liste))
    log(f"{len(liste)} fatura; detaylar aktarılıyor (~{DETAY_BEKLE_SN:.1f}s/adet)…")

    for i, satir in enumerate(liste, start=1):
        aid = _temiz(satir.get("G.a_id") or satir.get("a_id"))
        try:
            _tek_fatura_aktar(client, satir, sonuc)
            if i % 25 == 0 or i == len(liste):
                log(
                    f"  {i}/{len(liste)} — oluşturulan={sonuc.olusturulan} "
                    f"atlanan={sonuc.atlanan} hata={len(sonuc.hatalar)}"
                )
        except Exception as exc:  # noqa: BLE001
            sonuc.hatalar.append(f"a_id={aid}: {exc}")
            sonuc.atlanan += 1
        if i < len(liste):
            time.sleep(DETAY_BEKLE_SN)

    return sonuc
