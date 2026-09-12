"""EvoBulut Gelir/Gider → yerel cari defter + hizmet faturaları.

API: POST /GelirGider/base  cmd=jq_list|sql
  a_tur_id 40 = Gider, 41 = Gelir
  G.a_giren / G.a_cikan tutarlar; Kalan / Kapatilan açık-kapama

Yerel belge: EVB-GG-{a_id} (+ kapama EVB-GGK-{a_id})
Hizmet fatura no: aynı EVB-GG-{a_id} (Gelir/Gider fatura listelerinde görünür)
"""

from __future__ import annotations

import re
import time
import unicodedata
from datetime import date
from decimal import Decimal
from typing import Any, Callable

from sqlalchemy import select

from database.cari_service import CariService
from database.database import SessionLocal, get_session
from database.hizmet_faturasi_service import HizmetFaturasiService
from database.hizmet_service import HizmetService
from database.models.cari import Cari, CariIslem

# CLI bootstrap
from database.models.alis_siparisi import AlisSiparisi  # noqa: F401
from database.models.alis_irsaliyesi import AlisIrsaliyesi  # noqa: F401
from database.models.alis_faturasi import AlisFaturasi  # noqa: F401
from database.models.satis_siparisi import SatisSiparisi  # noqa: F401
from database.models.satis_irsaliyesi import SatisIrsaliyesi  # noqa: F401
from database.models.satis_faturasi import SatisFaturasi  # noqa: F401

from entegrasyon.evb_import_common import (
    DETAY_BEKLE_SN,
    ImportSonuc,
    _decimal,
    _tarih,
    _temiz,
    progress_log,
)

BELGE_ONEK = "EVB-GG-"
HIZMET_KOD_GIDER = "EVB-GIDER"
HIZMET_KOD_GELIR = "EVB-GELIR"


def _normalize_unvan(metin: str) -> str:
    s = unicodedata.normalize("NFKD", str(metin or "").strip())
    s = "".join(c for c in s if not unicodedata.combining(c))
    s = s.casefold().replace("ı", "i")
    return re.sub(r"\s+", " ", s).strip()


def _yerel_cari_indeks() -> tuple[dict[str, Cari], dict[str, list[Cari]]]:
    with SessionLocal() as session:
        cariler = list(session.scalars(select(Cari)).all())
        by_kod = {c.cari_kodu.strip(): c for c in cariler if (c.cari_kodu or "").strip()}
        by_unvan: dict[str, list[Cari]] = {}
        for c in cariler:
            key = _normalize_unvan(c.unvan)
            if key:
                by_unvan.setdefault(key, []).append(c)
        return by_kod, by_unvan


def _evb_cari_haritasi(client) -> dict[str, dict[str, str]]:
    """EvoBulut R.a_id → {kod, unvan}."""
    from entegrasyon.cari_import import map_evobulut_api_satir

    harita: dict[str, dict[str, str]] = {}
    for satir in client.tum_carileri_cek():
        eid = _temiz(satir.get("R.a_id") or satir.get("a_id"))
        if not eid:
            continue
        mapped = map_evobulut_api_satir(satir)
        harita[eid] = {
            "kod": _temiz(mapped.get("cari_kodu")),
            "unvan": _temiz(mapped.get("unvan")),
        }
    return harita


def _cari_esle(
    *,
    evb_cari_id: str,
    cari_adi: str,
    evb_map: dict[str, dict[str, str]],
    by_kod: dict[str, Cari],
    by_unvan: dict[str, list[Cari]],
) -> Cari | None:
    meta = evb_map.get(evb_cari_id) or {}
    kod = meta.get("kod") or ""
    if kod and kod in by_kod:
        return by_kod[kod]
    for aday in (meta.get("unvan") or "", cari_adi):
        m = re.search(r"\(([A-Za-z0-9._\-]+)\)\s*$", aday or "")
        if m:
            k2 = m.group(1).strip()
            if k2 in by_kod:
                return by_kod[k2]
        key = _normalize_unvan(aday)
        if not key:
            continue
        adaylar = by_unvan.get(key) or []
        if len(adaylar) == 1:
            return adaylar[0]
        temiz_ad = re.sub(r"\([^)]*\)\s*$", "", aday or "").strip()
        key2 = _normalize_unvan(temiz_ad)
        adaylar2 = by_unvan.get(key2) or []
        if len(adaylar2) == 1:
            return adaylar2[0]
    return None


def _tur_ve_tutar(liste: dict, ana: dict) -> tuple[str, Decimal]:
    tur_id = _temiz(ana.get("a_tur_id") or liste.get("G.a_tur_id") or liste.get("a_tur_id"))
    tur_adi = _temiz(
        ana.get("a_tur_ad") or liste.get("FIN_TUR.a_adi") or liste.get("a_tur_ad")
    ).casefold()
    giren = _decimal(ana.get("a_giren") or liste.get("G.a_giren"), Decimal("0")) or Decimal("0")
    cikan = _decimal(ana.get("a_cikan") or liste.get("G.a_cikan"), Decimal("0")) or Decimal("0")

    if tur_id == "41" or tur_adi.startswith("gelir"):
        tutar = giren if giren > 0 else cikan
        return "GELIR", tutar
    if tur_id == "40" or tur_adi.startswith("gider"):
        tutar = cikan if cikan > 0 else giren
        return "GIDER", tutar
    if giren > 0 and cikan <= 0:
        return "GELIR", giren
    if cikan > 0 and giren <= 0:
        return "GIDER", cikan
    raise ValueError(f"Gelir/Gider türü belirsiz tur_id={tur_id!r} tur_adi={tur_adi!r}")


def evb_hizmet_kartlarini_hazirla() -> None:
    """EvoBulut aktarımı için genel gelir/gider hizmet kartlarını oluşturur."""
    from database.models.hizmet import HizmetKarti

    with get_session() as session:
        gider = session.scalar(
            select(HizmetKarti).where(HizmetKarti.hizmet_kodu == HIZMET_KOD_GIDER)
        )
        gelir = session.scalar(
            select(HizmetKarti).where(HizmetKarti.hizmet_kodu == HIZMET_KOD_GELIR)
        )
    if gider is None:
        HizmetService.kaydet(
            {
                "hizmet_kodu": HIZMET_KOD_GIDER,
                "hizmet_adi": "EvoBulut Gider",
                "hizmet_turu": "GIDER",
                "gider_sinifi": "ISLETME",
                "birim": "Adet",
                "kdv_orani": 0,
                "alis_fiyati": 0,
                "satis_fiyati": 0,
            }
        )
    if gelir is None:
        HizmetService.kaydet(
            {
                "hizmet_kodu": HIZMET_KOD_GELIR,
                "hizmet_adi": "EvoBulut Gelir",
                "hizmet_turu": "GELIR",
                "birim": "Adet",
                "kdv_orani": 0,
                "alis_fiyati": 0,
                "satis_fiyati": 0,
            }
        )


def _odeme_tutari(tutar: Decimal, kalan: Decimal | None, kapatilan: Decimal | None) -> Decimal:
    if kapatilan is not None:
        odeme = max(Decimal("0"), kapatilan.quantize(Decimal("0.01")))
        return min(odeme, tutar)
    if kalan is not None:
        kalan_q = max(Decimal("0"), kalan.quantize(Decimal("0.01")))
        return max(Decimal("0"), (tutar - kalan_q).quantize(Decimal("0.01")))
    return Decimal("0")


def _hizmet_faturasi_yaz(
    *,
    belge: str,
    tur: str,
    tarih: date,
    cari_id: int,
    tutar: Decimal,
    aciklama: str,
    kalan: Decimal | None,
    kapatilan: Decimal | None,
) -> bool:
    """Hizmet faturası oluşturur. True = yeni yazıldı. Cari deftere dokunmaz."""
    fatura_no = belge[:30]
    if HizmetFaturasiService.fatura_no_var_mi(fatura_no):
        return False

    odeme = _odeme_tutari(tutar, kalan, kapatilan)
    hizmet_kodu = HIZMET_KOD_GELIR if tur == "GELIR" else HIZMET_KOD_GIDER
    HizmetFaturasiService.kaydet(
        {
            "fatura_no": fatura_no,
            "fatura_turu": tur,
            "fatura_tarihi": tarih,
            "vade_tarihi": tarih,
            "cari_id": cari_id,
            "odeme_tutari": odeme,
            "aciklama": aciklama,
        },
        [
            {
                "hizmet_kodu": hizmet_kodu,
                "hizmet_adi": aciklama[:200] or ("EvoBulut Gelir" if tur == "GELIR" else "EvoBulut Gider"),
                "aciklama": aciklama[:500] or None,
                "miktar": Decimal("1"),
                "birim": "Adet",
                "birim_fiyat": tutar,
                "iskonto_orani": Decimal("0"),
                "kdv_orani": Decimal("0"),
            }
        ],
        cari_etkisi=False,
        finans_yaz=False,
    )
    return True


def mevcut_cari_islemlerden_fatura_senkron(
    progress: Callable[[str], None] | None = None,
) -> ImportSonuc:
    """Daha önce yalnız cariye yazılmış EVB-GG kayıtlarından hizmet faturası üretir."""
    evb_hizmet_kartlarini_hazirla()
    sonuc = ImportSonuc()
    with get_session() as session:
        islemler = list(
            session.scalars(
                select(CariIslem)
                .where(
                    CariIslem.belge_no.like(f"{BELGE_ONEK}%"),
                    ~CariIslem.belge_no.like("EVB-GGK-%"),
                    CariIslem.islem_turu.in_(("Gelir", "Gider")),
                )
                .order_by(CariIslem.tarih, CariIslem.id)
            ).all()
        )
        kapama_map: dict[str, Decimal] = {}
        for kap in session.scalars(
            select(CariIslem).where(CariIslem.belge_no.like("EVB-GGK-%"))
        ).all():
            aid = (kap.belge_no or "").replace("EVB-GGK-", "", 1)
            tut = Decimal(str(kap.alacak or 0)) + Decimal(str(kap.borc or 0))
            kapama_map[aid] = tut.quantize(Decimal("0.01"))
        paketler = [
            {
                "belge": islem.belge_no,
                "tur": "GELIR" if islem.islem_turu == "Gelir" else "GIDER",
                "tarih": islem.tarih,
                "cari_id": islem.cari_id,
                "tutar": (
                    Decimal(str(islem.borc or 0))
                    if islem.islem_turu == "Gelir"
                    else Decimal(str(islem.alacak or 0))
                ).quantize(Decimal("0.01")),
                "aciklama": (islem.aciklama or islem.islem_turu or "")[:500],
                "aid": (islem.belge_no or "").replace(BELGE_ONEK, "", 1),
            }
            for islem in islemler
        ]
        sonuc.cekilen = len(paketler)

    for i, p in enumerate(paketler, start=1):
        try:
            if p["tutar"] <= 0:
                sonuc.atlanan += 1
                continue
            kapatilan = kapama_map.get(p["aid"])
            kalan = None
            if kapatilan is not None:
                kalan = max(Decimal("0"), (p["tutar"] - kapatilan).quantize(Decimal("0.01")))
            yazildi = _hizmet_faturasi_yaz(
                belge=p["belge"],
                tur=p["tur"],
                tarih=p["tarih"],
                cari_id=p["cari_id"],
                tutar=p["tutar"],
                aciklama=p["aciklama"],
                kalan=kalan,
                kapatilan=kapatilan,
            )
            if yazildi:
                sonuc.olusturulan += 1
            else:
                sonuc.atlanan += 1
        except Exception as exc:  # noqa: BLE001
            sonuc.hatalar.append(f"{p['belge']}: {exc}")
            sonuc.atlanan += 1
        if i % 50 == 0:
            progress_log(
                progress,
                f"Fatura senkron {i}/{len(paketler)} +{sonuc.olusturulan}",
            )
    progress_log(
        progress,
        f"Fatura senkron bitti: +{sonuc.olusturulan} atlanan={sonuc.atlanan}",
    )
    return sonuc


def _tek_kayit(
    client,
    liste_satir: dict[str, Any],
    *,
    evb_map: dict[str, dict[str, str]],
    by_kod: dict[str, Cari],
    by_unvan: dict[str, list[Cari]],
    sonuc: ImportSonuc,
    progress: Callable[[str], None] | None,
) -> bool:
    """True = detay API çağrıldı (rate limit için)."""
    aid = _temiz(liste_satir.get("G.a_id") or liste_satir.get("a_id"))
    if not aid:
        raise ValueError("Gelir/Gider a_id yok")
    belge = f"{BELGE_ONEK}{aid}"[:50]
    cari_var = CariService.islem_belge_var_mi(belge)
    fatura_var = HizmetFaturasiService.fatura_no_var_mi(belge[:30])
    if cari_var and fatura_var:
        sonuc.atlanan += 1
        return False

    tarih = _tarih(liste_satir.get("G.a_tarih") or liste_satir.get("a_tarih"))
    ana: dict[str, Any] = {}
    api = False
    try:
        tur, tutar = _tur_ve_tutar(liste_satir, ana)
        kalan = _decimal(liste_satir.get("Kalan"), None)
        kapatilan = _decimal(liste_satir.get("Kapatilan"), None)
    except ValueError:
        detay = client.gelir_gider_detay(aid)
        ana = detay.get("Ana") or {}
        api = True
        tarih = tarih or _tarih(ana.get("a_tarih"))
        tur, tutar = _tur_ve_tutar(liste_satir, ana)
        kalan = _decimal(ana.get("a_tutar_kalan") or liste_satir.get("Kalan"), None)
        kapatilan = _decimal(ana.get("a_tutar_kapanan") or liste_satir.get("Kapatilan"), None)

    if not tarih:
        raise ValueError(f"Gelir/Gider {aid}: tarih yok")
    if tarih > date.today():
        tarih = date.today()
    if tutar <= 0:
        raise ValueError(f"Gelir/Gider {aid}: tutar yok")

    evb_cari = _temiz(
        ana.get("a_cari_id") or liste_satir.get("G.a_cari_id") or liste_satir.get("a_cari_id")
    )
    cari_adi = _temiz(
        ana.get("a_cari_ad") or liste_satir.get("CARI_ADI") or liste_satir.get("a_cari_ad")
    )
    cari = _cari_esle(
        evb_cari_id=evb_cari,
        cari_adi=cari_adi,
        evb_map=evb_map,
        by_kod=by_kod,
        by_unvan=by_unvan,
    )
    if cari is None and cari_adi:
        kod_aday = ""
        m = re.search(r"\(([A-Za-z0-9._\-]+)\)\s*$", cari_adi)
        if m:
            kod_aday = m.group(1).strip()
        if not kod_aday:
            kod_aday = f"EVB{evb_cari}" if evb_cari else f"GG{aid}"
        kod_aday = kod_aday[:20]
        unvan = re.sub(r"\([^)]*\)\s*$", "", cari_adi).strip() or cari_adi
        cari_turu = "Tedarikçi" if tur == "GIDER" else "Müşteri"
        try:
            from entegrasyon.cari_import import kaydet_veya_guncelle

            kaydet_veya_guncelle(
                {
                    "cari_kodu": kod_aday,
                    "unvan": unvan[:200],
                    "cari_turu": cari_turu,
                    "aktif": True,
                }
            )
            yeni = CariService.kod_ile_getir(kod_aday)
            if yeni is not None:
                by_kod[kod_aday] = yeni
                key = _normalize_unvan(yeni.unvan)
                if key:
                    by_unvan.setdefault(key, []).append(yeni)
                cari = yeni
        except Exception:
            cari = None
    if cari is None:
        raise ValueError(f"Cari eşleşmedi evb_id={evb_cari!r} ad={cari_adi[:40]!r}")

    ack = _temiz(ana.get("a_ack") or liste_satir.get("G.a_ack") or "")
    aciklama = (ack or f"EvoBulut {tur} #{aid}")[:500]

    yeni = False
    if not cari_var:
        CariService.gelir_gider_fisi_ekle(
            cari.id,
            tarih,
            tur=tur,
            tutar=tutar,
            belge_no=belge,
            aciklama=aciklama,
            kalan_acik=kalan,
            kapatilan=kapatilan,
        )
        yeni = True

    if not fatura_var:
        if _hizmet_faturasi_yaz(
            belge=belge,
            tur=tur,
            tarih=tarih,
            cari_id=cari.id,
            tutar=tutar,
            aciklama=aciklama,
            kalan=kalan,
            kapatilan=kapatilan,
        ):
            yeni = True

    if yeni:
        sonuc.olusturulan += 1
        progress_log(progress, f"GG {aid} {tur} -> {cari.cari_kodu}")
    else:
        sonuc.atlanan += 1
    return api


def aktar_api_den(
    *,
    max_adet: int | None = None,
    ara: str = "",
    bas_tar: str = "",
    son_tar: str = "",
    progress: Callable[[str], None] | None = None,
    mevcutlari_senkron: bool = True,
) -> ImportSonuc:
    from entegrasyon.evobulut_client import EvobulutClient, load_credentials

    evb_hizmet_kartlarini_hazirla()
    if mevcutlari_senkron:
        progress_log(progress, "Mevcut EVB-GG cari kayıtları faturalara senkron…")
        mevcut_cari_islemlerden_fatura_senkron(progress=progress)

    client = EvobulutClient(load_credentials())
    client.login()
    progress_log(progress, "Gelir/Gider listesi çekiliyor…")
    satirlar = client.tum_gelir_giderleri_cek(ara=ara, bas_tar=bas_tar, son_tar=son_tar)
    if max_adet is not None:
        satirlar = satirlar[: max(0, int(max_adet))]
    sonuc = ImportSonuc(cekilen=len(satirlar))
    progress_log(progress, f"Gelir/Gider kayıt: {len(satirlar)}; cari haritası…")
    evb_map = _evb_cari_haritasi(client)
    by_kod, by_unvan = _yerel_cari_indeks()

    for i, satir in enumerate(satirlar, start=1):
        try:
            api = _tek_kayit(
                client,
                satir,
                evb_map=evb_map,
                by_kod=by_kod,
                by_unvan=by_unvan,
                sonuc=sonuc,
                progress=progress,
            )
            if api:
                time.sleep(DETAY_BEKLE_SN)
        except Exception as exc:  # noqa: BLE001
            aid = _temiz(satir.get("G.a_id") or satir.get("a_id")) or "?"
            sonuc.hatalar.append(f"{aid}: {exc}")
            sonuc.atlanan += 1
            progress_log(progress, f"! GG {aid}: {exc}")
        if i % 25 == 0:
            progress_log(
                progress,
                f"İlerleme {i}/{len(satirlar)} +{sonuc.olusturulan} atlanan={sonuc.atlanan}",
            )
    return sonuc
