"""EvoBulut cari bakiyelerini yerel açılış / dönem devir fişlerine aktarma.

EvoBulut API'de ayrı 'açılış fişi' listesi yok; cari liste satırındaki güncel
bakiye (`text`: `Bakiye : N (B|A)`) açılış fişi olarak yazılır.

Yön: EvoBulut cari kartındaki bakiye firma defterine göredir — (B) cari borçlu, (A) cari alacaklı.
Yerel kalem yönü ve muhasebe karşılığı cari türüne göre ``database.cari_acilis_anlam`` ile belirlenir:
  Müşteri (B) → açık alacak kalemi (120 BORÇ); Tedarikçi (A) → açık borç kalemi (320 ALACAK).
  Müşteri (A) / Tedarikçi (B) → avans kalemi; muhasebe karşılığı belirsiz ("İnceleme gerekiyor").
"A" (alacak) tek başına avans sayılmaz. Açılıştan otomatik muhasebe fişi üretilmez.

İdempotent belge: EVB-ACL-{EvoBulut a_id}
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Any

from database.cari_service import CariService
from database.database import get_session
from database.models.cari import Cari
from sqlalchemy import select

# CLI bootstrap — SatisFaturasi ilişkileri
from database.models.satis_siparisi import SatisSiparisi  # noqa: F401
from database.models.satis_irsaliyesi import SatisIrsaliyesi  # noqa: F401
from database.models.satis_faturasi import SatisFaturasi  # noqa: F401

BELGE_ONEK = "EVB-ACL-"
_BAKIYE_RE = re.compile(
    r"Bakiye\s*:\s*([-\d.,]+)\s*\(([^)]*)\)",
    re.IGNORECASE,
)


@dataclass
class AcilisImportSonuc:
    cekilen: int = 0
    sifir_bakiye: int = 0
    olusturulan: int = 0
    atlanan: int = 0  # zaten var / eşleşmedi / sıfır dışı atlama
    hatalar: list[str] = field(default_factory=list)
    inceleme: list[str] = field(default_factory=list)  # muhasebe karşılığı belirsiz açılışlar


def _normalize_unvan(metin: str) -> str:
    s = unicodedata.normalize("NFKD", str(metin or "").strip())
    s = "".join(c for c in s if not unicodedata.combining(c))
    s = s.casefold().replace("ı", "i")
    return re.sub(r"\s+", " ", s).strip()


def parse_evobulut_bakiye(satir: dict[str, Any]) -> tuple[Decimal, str] | None:
    """Döner: (tutar>0, 'B'|'A') veya None (sıfır / parse yok)."""
    text = str(satir.get("text") or "")
    m = _BAKIYE_RE.search(text)
    if not m:
        return None
    ham = m.group(1).replace(" ", "").replace(",", "")
    try:
        tutar = Decimal(ham)
    except (InvalidOperation, ValueError):
        return None
    if tutar == 0:
        return None
    if tutar < 0:
        # Negatif tutar + boş tür: alacak say
        tur = (m.group(2) or "").strip().upper()
        if not tur:
            return (abs(tutar), "A")
        tutar = abs(tutar)
    tur = (m.group(2) or "").strip().upper()
    if tur.startswith("B"):
        return (tutar, "B")
    if tur.startswith("A"):
        return (tutar, "A")
    # Tür boş ama tutar ≠ 0 — atla (belirsiz)
    return None


def belge_no_icin(evobulut_id: str | int) -> str:
    return f"{BELGE_ONEK}{evobulut_id}"


def _yerel_cari_indeks() -> tuple[dict[str, Cari], dict[str, list[Cari]]]:
    with get_session() as session:
        cariler = list(session.scalars(select(Cari)).all())
        # detach: session kapanınca kullanmak için id/kod/unvan yeterli
        by_kod = {c.cari_kodu.strip(): c for c in cariler if (c.cari_kodu or "").strip()}
        by_unvan: dict[str, list[Cari]] = {}
        for c in cariler:
            key = _normalize_unvan(c.unvan)
            if key:
                by_unvan.setdefault(key, []).append(c)
        return by_kod, by_unvan


def eslestir_cari(
    satir: dict[str, Any],
    by_kod: dict[str, Cari],
    by_unvan: dict[str, list[Cari]],
) -> Cari | None:
    kod = str(satir.get("R.a_kod") or satir.get("a_kod") or "").strip()
    if kod and kod in by_kod:
        return by_kod[kod]
    resmi = str(satir.get("R.a_resmi_ad") or "").strip()
    ad = str(satir.get("R.a_ad") or satir.get("musteri") or "").strip()
    if "----" in ad:
        ad = ad.split("----", 1)[0].strip()
    for aday in (resmi, ad):
        key = _normalize_unvan(aday)
        if not key:
            continue
        adaylar = by_unvan.get(key) or []
        if len(adaylar) == 1:
            return adaylar[0]
    return None


def onizle_satirlari(satirlar: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Yazmadan önce satır başına: eşleşen cari, kaynak yön, yerel kalem, muhasebe karşılığı ve durum."""
    from database.cari_acilis_anlam import acilis_anlami

    by_kod, by_unvan = _yerel_cari_indeks()
    sonuc = []
    for i, satir in enumerate(satirlar, start=1):
        parsed = parse_evobulut_bakiye(satir)
        if parsed is None:
            continue
        tutar, tur = parsed
        evb_id = str(satir.get("R.a_id") or satir.get("a_id") or "").strip()
        cari = eslestir_cari(satir, by_kod, by_unvan)
        kayit = {"satir": i, "belge_no": belge_no_icin(evb_id) if evb_id else None, "tutar": tutar,
                 "kaynak_yon": tur, "cari_kodu": cari.cari_kodu if cari else None,
                 "cari_turu": cari.cari_turu if cari else None}
        if cari is None or not evb_id:
            kayit.update(durum="Aktarılmaz", aciklama="Cari eşleşmedi" if cari is None else "EvoBulut a_id yok")
        elif CariService.islem_belge_var_mi(kayit["belge_no"]):
            kayit.update(durum="Aktarılmaz", aciklama="Zaten aktarılmış")
        else:
            anlam = acilis_anlami(cari.cari_turu, tur)
            kayit.update(durum=anlam.durum, yerel_kalem="açık kalem" if anlam.kalem_borc else "avans",
                         muhasebe=anlam.muhasebe_metni, aciklama=anlam.aciklama)
        sonuc.append(kayit)
    return sonuc


def aktar_satirlari(
    satirlar: list[dict[str, Any]],
    *,
    tarih: date | None = None,
) -> AcilisImportSonuc:
    sonuc = AcilisImportSonuc(cekilen=len(satirlar))
    fis_tarihi = tarih or date.today()
    by_kod, by_unvan = _yerel_cari_indeks()

    for i, satir in enumerate(satirlar, start=1):
        try:
            parsed = parse_evobulut_bakiye(satir)
            if parsed is None:
                # sıfır veya belirsiz
                text = str(satir.get("text") or "")
                if _BAKIYE_RE.search(text):
                    sonuc.sifir_bakiye += 1
                else:
                    sonuc.atlanan += 1
                continue

            tutar, tur = parsed
            evb_id = str(satir.get("R.a_id") or satir.get("a_id") or "").strip()
            if not evb_id:
                sonuc.hatalar.append(f"Satır {i}: EvoBulut a_id yok")
                sonuc.atlanan += 1
                continue

            belge = belge_no_icin(evb_id)
            if CariService.islem_belge_var_mi(belge):
                sonuc.atlanan += 1
                continue

            cari = eslestir_cari(satir, by_kod, by_unvan)
            if cari is None:
                kod = str(satir.get("R.a_kod") or "").strip()
                ad = str(satir.get("R.a_ad") or satir.get("musteri") or "").strip()[:40]
                sonuc.hatalar.append(f"Satır {i}: eşleşmedi kod={kod!r} ad={ad!r}")
                sonuc.atlanan += 1
                continue

            aciklama = (
                f"EvoBulut açılış bakiyesi ({tur}) — cari_id={evb_id}"
            )
            _islem, anlam = CariService.acilis_bakiyesi_ekle(
                cari.id,
                fis_tarihi,
                tutar=tutar,
                yon=tur,
                belge_no=belge,
                aciklama=aciklama,
            )
            if not anlam.belirli:
                sonuc.inceleme.append(f"{belge} {cari.cari_kodu}: {anlam.muhasebe_metni}")
            sonuc.olusturulan += 1
        except Exception as exc:  # noqa: BLE001
            sonuc.hatalar.append(f"Satır {i}: {exc}")
            sonuc.atlanan += 1
    return sonuc


def aktar_api_den(tarih: date | None = None) -> AcilisImportSonuc:
    from entegrasyon.evobulut_client import EvobulutClient, load_credentials

    client = EvobulutClient(load_credentials())
    client.login()
    satirlar = client.tum_carileri_cek()
    return aktar_satirlari(satirlar, tarih=tarih)
