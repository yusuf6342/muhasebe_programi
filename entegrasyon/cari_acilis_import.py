"""EvoBulut cari bakiyelerini yerel açılış / dönem devir fişlerine aktarma.

EvoBulut API'de ayrı 'açılış fişi' listesi yok; cari liste satırındaki güncel
bakiye (`text`: `Bakiye : N (B|A)`) açılış fişi olarak yazılır.

Polarite (Müşteri ve Tedarikçi aynı — cari kart borç/alacak):
  EvoBulut (B) = Borç  → yerel borc = tutar  (bakiye +; cari borçlu)
  EvoBulut (A) = Alacak → yerel alacak = tutar (bakiye −; cari alacaklı)

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
from database.database import SessionLocal
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
    with SessionLocal() as session:
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

            borc = tutar if tur == "B" else Decimal("0")
            alacak = tutar if tur == "A" else Decimal("0")
            aciklama = (
                f"EvoBulut açılış bakiyesi ({tur}) — cari_id={evb_id}"
            )
            CariService.acilis_fisi_ekle(
                cari.id,
                fis_tarihi,
                borc=borc,
                alacak=alacak,
                belge_no=belge,
                aciklama=aciklama,
            )
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
