"""EvoBulut banka kartlarını Cin Muhasebe BankaKarti olarak aktar + eşleştir.

Evo banka_listesi alanları (dokümantasyon):
  id, text, a_dov_id, DOV_Kodu, a_posmu, a_posgun, a_muh_kom_hid, a_kod

Yerel model: BankaKarti + 5 alt FinansHesabi (MEVDUAT/KMH/POS/KK/KREDILER).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any

from sqlalchemy import select

from database.database import get_session
from database.finans_service import FinansService
from database.models.finans import BankAccountMatchRule, BankaKarti
from entegrasyon.banka_eslestirme import (
    BankAccountMatchingService,
    normalize_banka_adi,
    normalize_iban,
)
from entegrasyon.evb_import_common import ImportSonuc, _temiz


def map_evo_banka_kart(satir: dict[str, Any]) -> dict[str, Any]:
    evo_id = _temiz(satir.get("id") or satir.get("a_id") or satir.get("banka_id"))
    ad = _temiz(satir.get("text") or satir.get("a_adi") or satir.get("banka_adi") or satir.get("BANKA"))
    kod = _temiz(satir.get("a_kod"))
    doviz = _temiz(satir.get("DOV_Kodu") or satir.get("DOV_Sembol") or "TL")
    posmu = _temiz(satir.get("a_posmu")) in {"1", "true", "True", "E", "e"}
    try:
        posgun = int(_temiz(satir.get("a_posgun") or "1") or "1")
    except ValueError:
        posgun = 1
    iban = normalize_iban(satir.get("a_iban") or satir.get("IBAN") or satir.get("iban"))
    hesap_no = _temiz(satir.get("a_hesap_no") or satir.get("hesap_no") or satir.get("HESAP_NO") or kod)
    sube = _temiz(satir.get("a_sube") or satir.get("a_sube_adi") or satir.get("SUBE") or satir.get("sube"))
    notlar = []
    if doviz and doviz.upper() not in {"TL", "TRY"}:
        notlar.append(f"Döviz: {doviz}")
    if posmu:
        notlar.append("POS hesap")
    if kod and kod not in {"", "-"}:
        notlar.append(f"Evo kod: {kod}")
    notlar.append(f"Evo id: {evo_id}")
    return {
        "evo_banka_id": evo_id,
        "banka_adi": ad[:100] if ad else f"Evo Banka {evo_id}",
        "sube": sube[:100] if sube else None,
        "hesap_no": hesap_no[:50] if hesap_no else None,
        "iban": iban[:34] if iban else None,
        "pos_valor_gun": max(0, posgun),
        "aciklama": " | ".join(notlar)[:500],
        "aktif": True,
        "doviz": doviz,
        "posmu": posmu,
    }


@dataclass
class BankaKartKarsilastirma:
    evo_adet: int = 0
    yerel_adet: int = 0
    eslesen: list[dict] = field(default_factory=list)
    sadece_evo: list[dict] = field(default_factory=list)
    sadece_yerel: list[dict] = field(default_factory=list)


def karsilastir(evo_satirlar: list[dict], yerel_kartlar: list[BankaKarti] | None = None) -> BankaKartKarsilastirma:
    if yerel_kartlar is None:
        yerel_kartlar = FinansService.banka_kartlari(aktif_only=False)
    rapor = BankaKartKarsilastirma(evo_adet=len(evo_satirlar), yerel_adet=len(yerel_kartlar))
    yerel_by_ad = {normalize_banka_adi(k.banka_adi): k for k in yerel_kartlar}
    yerel_by_iban = {normalize_iban(k.iban): k for k in yerel_kartlar if k.iban}
    eslesen_yerel_ids: set[int] = set()

    with get_session() as session:
        kurallar = {
            k.evo_banka_id: k
            for k in session.scalars(select(BankAccountMatchRule).where(BankAccountMatchRule.aktif.is_(True)))
        }

    for ham in evo_satirlar:
        m = map_evo_banka_kart(ham)
        evo_id = m["evo_banka_id"]
        kart = None
        yontem = None
        if evo_id and evo_id in kurallar:
            kid = kurallar[evo_id].banka_karti_id
            kart = next((x for x in yerel_kartlar if x.id == kid), None)
            yontem = "evo_id"
        if kart is None and m.get("iban") and m["iban"] in yerel_by_iban:
            kart = yerel_by_iban[m["iban"]]
            yontem = "iban"
        if kart is None:
            ad = normalize_banka_adi(m["banka_adi"])
            if ad in yerel_by_ad:
                kart = yerel_by_ad[ad]
                yontem = "ad"
        if kart is not None:
            eslesen_yerel_ids.add(kart.id)
            rapor.eslesen.append(
                {
                    "evo_id": evo_id,
                    "evo_adi": m["banka_adi"],
                    "yerel_id": kart.id,
                    "yerel_adi": kart.banka_adi,
                    "yontem": yontem,
                }
            )
        else:
            rapor.sadece_evo.append({"evo_id": evo_id, "evo_adi": m["banka_adi"], "doviz": m.get("doviz")})

    for k in yerel_kartlar:
        if k.id not in eslesen_yerel_ids:
            rapor.sadece_yerel.append({"yerel_id": k.id, "yerel_adi": k.banka_adi, "iban": k.iban})
    return rapor


def aktar_satirlari(satirlar: list[dict[str, Any]], *, guncelle: bool = True) -> ImportSonuc:
    """Evo banka kartlarını yerelde oluştur / güncelle ve eşleştirme yaz."""
    sonuc = ImportSonuc(cekilen=len(satirlar))
    for ham in satirlar:
        try:
            m = map_evo_banka_kart(ham)
            evo_id = m["evo_banka_id"]
            if not evo_id:
                sonuc.hatalar.append("Evo banka id yok")
                continue

            mevcut = BankAccountMatchingService.kural_bul(evo_id)
            kart_id = None
            if mevcut:
                kart_id = mevcut.banka_karti_id
            else:
                # ada / iban ile bul
                eslesen = karsilastir([ham]).eslesen
                if eslesen:
                    kart_id = eslesen[0]["yerel_id"]

            if kart_id and not guncelle:
                sonuc.atlanan += 1
                BankAccountMatchingService.hafizaya_yaz(
                    evo_banka_id=evo_id,
                    banka_karti_id=kart_id,
                    evo_banka_adi=m["banka_adi"],
                    iban=m.get("iban"),
                    hesap_no=m.get("hesap_no"),
                    kaynak="api",
                )
                continue

            veriler = {
                "banka_adi": m["banka_adi"],
                "sube": m.get("sube"),
                "hesap_no": m.get("hesap_no"),
                "iban": m.get("iban"),
                "aciklama": m.get("aciklama"),
                "pos_valor_gun": m.get("pos_valor_gun", 1),
                "aktif": True,
            }
            if kart_id:
                veriler["kart_id"] = kart_id
                kart = FinansService.banka_karti_kaydet(veriler)
                sonuc.atlanan += 1  # güncelleme sayacı yok; atlanan≈güncellenen
            else:
                kart = FinansService.banka_karti_kaydet(veriler)
                sonuc.olusturulan += 1

            hesap_id = BankAccountMatchingService.mevduat_hesap_id(kart.id, "MEVDUAT")
            BankAccountMatchingService.hafizaya_yaz(
                evo_banka_id=evo_id,
                banka_karti_id=kart.id,
                evo_banka_adi=m["banka_adi"],
                finans_hesap_id=hesap_id,
                alt_hesap_turu="MEVDUAT",
                iban=m.get("iban"),
                hesap_no=m.get("hesap_no"),
                guven=Decimal("100"),
                kaynak="api",
            )
        except Exception as exc:  # noqa: BLE001
            sonuc.hatalar.append(f"{_temiz(ham.get('text') or ham.get('id'))}: {exc}")
    return sonuc


def aktar_api_den(*, guncelle: bool = True, creds=None) -> tuple[ImportSonuc, BankaKartKarsilastirma]:
    from entegrasyon.evobulut_client import EvobulutClient, load_credentials

    client = EvobulutClient(creds or load_credentials())
    client.login()
    satirlar = client.banka_kart_listesi()
    once = karsilastir(satirlar)
    sonuc = aktar_satirlari(satirlar, guncelle=guncelle)
    sonra = karsilastir(satirlar)
    return sonuc, sonra if sonra.evo_adet else once
