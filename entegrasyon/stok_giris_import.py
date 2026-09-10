"""EvoBulut stok miktarlarını yerel GİRİŞ hareketlerine aktarma.

EvoBulut OpenAPI'de ayrı 'stok giriş fişi' master listesi yok (`stokgc` boş).
Stok listesinde güncel miktar var: `a_kalan` (ayrıca `a_giren` / `a_cikan`).
`/StokHareket/base` cmd=list ile stok bazlı geçmiş hareket alınabilir; ancak
stok başına istek gerekir ve rate-limit (~60/dk) nedeniyle toplu aktarım
pratik değil. Bu modül cari açılış aktarımına benzer şekilde `a_kalan` > 0
olan kartlar için açılış GİRİŞ hareketi yazar.

İdempotent belge: EVB-SG-{EvoBulut a_id}
Eşleştirme: stok_kodu (= a_kod)
Depo: varsayılan ANA DEPO (StokService.varsayilanlari_hazirla)
Maliyet: a_fiyat_al (yoksa 0)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Any

from sqlalchemy import select

from database.database import get_session
from database.models.stok import StokHareketi, StokKarti
from database.stok_service import StokService

# CLI bootstrap — SatisFaturasi ilişkileri
from database.models.satis_siparisi import SatisSiparisi  # noqa: F401
from database.models.satis_irsaliyesi import SatisIrsaliyesi  # noqa: F401
from database.models.satis_faturasi import SatisFaturasi  # noqa: F401

BELGE_ONEK = "EVB-SG-"
VARSAYILAN_DEPO = "ANA DEPO"


@dataclass
class StokGirisImportSonuc:
    cekilen: int = 0
    sifir_kalan: int = 0
    olusturulan: int = 0
    atlanan: int = 0  # zaten var / eşleşmedi
    hatalar: list[str] = field(default_factory=list)


def _temiz(deger: Any) -> str:
    if deger is None:
        return ""
    return str(deger).strip()


def _miktar(deger: Any) -> Decimal | None:
    metin = _temiz(deger).replace(" ", "").replace(",", ".")
    if not metin or metin in {"-", "—"}:
        return None
    try:
        tutar = Decimal(metin)
    except (InvalidOperation, ValueError):
        return None
    return tutar


def belge_no_icin(evobulut_id: str | int) -> str:
    return f"{BELGE_ONEK}{evobulut_id}"


def belge_var_mi(belge_no: str) -> bool:
    belge = _temiz(belge_no)
    if not belge:
        return False
    with get_session() as session:
        return (
            session.scalar(select(StokHareketi.id).where(StokHareketi.belge_no == belge))
            is not None
        )


def _yerel_stok_indeks() -> dict[str, str]:
    """stok_kodu → stok_kodu (varlık kontrolü; stok_girisi kod ile çalışır)."""
    with get_session() as session:
        kodlar = session.scalars(select(StokKarti.stok_kodu)).all()
        return {(_temiz(k)): _temiz(k) for k in kodlar if _temiz(k)}


def aktar_satirlari(
    satirlar: list[dict[str, Any]],
    *,
    tarih: date | None = None,
    depo_adi: str = VARSAYILAN_DEPO,
) -> StokGirisImportSonuc:
    sonuc = StokGirisImportSonuc(cekilen=len(satirlar))
    fis_tarihi = tarih or date.today()
    StokService.varsayilanlari_hazirla()
    yerel = _yerel_stok_indeks()

    for i, satir in enumerate(satirlar, start=1):
        try:
            kalan = _miktar(satir.get("a_kalan"))
            if kalan is None or kalan <= 0:
                sonuc.sifir_kalan += 1
                continue

            evb_id = _temiz(satir.get("a_id"))
            if not evb_id:
                sonuc.hatalar.append(f"Satır {i}: EvoBulut a_id yok")
                sonuc.atlanan += 1
                continue

            belge = belge_no_icin(evb_id)
            if len(belge) > 50:
                sonuc.hatalar.append(f"Satır {i}: belge_no çok uzun ({belge})")
                sonuc.atlanan += 1
                continue
            if belge_var_mi(belge):
                sonuc.atlanan += 1
                continue

            kod = _temiz(satir.get("a_kod") or satir.get("stok_kodu"))
            if not kod or kod not in yerel:
                sonuc.hatalar.append(
                    f"Satır {i}: yerel stok yok kod={kod!r} a_id={evb_id}"
                )
                sonuc.atlanan += 1
                continue

            maliyet = _miktar(satir.get("a_fiyat_al")) or Decimal("0")
            if maliyet < 0:
                maliyet = Decimal("0")

            StokService.stok_girisi(
                stok_kodu=kod,
                depo_adi=depo_adi,
                tedarikci="EvoBulut açılış (a_kalan)",
                tarih=fis_tarihi,
                miktar=kalan,
                maliyet=maliyet,
                lot_no=belge,
            )
            sonuc.olusturulan += 1
        except Exception as exc:  # noqa: BLE001 — satır bazlı hata topla
            kod = _temiz(satir.get("a_kod") if isinstance(satir, dict) else "")
            etiket = f"Satır {i}" + (f" ({kod})" if kod else "")
            sonuc.hatalar.append(f"{etiket}: {exc}")
            sonuc.atlanan += 1
    return sonuc


def aktar_api_den(
    *,
    tarih: date | None = None,
    depo_adi: str = VARSAYILAN_DEPO,
    ara: str = "",
) -> StokGirisImportSonuc:
    from entegrasyon.evobulut_client import EvobulutClient, load_credentials

    client = EvobulutClient(load_credentials())
    client.login()
    satirlar = client.tum_stoklari_cek(ara=ara)
    return aktar_satirlari(satirlar, tarih=tarih, depo_adi=depo_adi)
