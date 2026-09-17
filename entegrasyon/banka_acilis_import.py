"""EvoBulut banka açılış bakiyelerini Cin Muhasebe MEVDUAT acilis_bakiyesi'ne aktar.

Evo'da ayrı açılış endpoint'i yok; banka hareketlerinde
`a_ack` / açıklama içinde 'açılış' | 'acilis' | 'devir' geçen satırlar açılıştır.

İdempotent:
  - Hedef hesabın acilis_bakiyesi = Evo açılış neti (giren − çıkan)
  - İlgili EVB-BN-{a_id} hareketleri silinir (çift sayım olmasın)
"""

from __future__ import annotations

import re
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal
from typing import Any, Callable

from sqlalchemy import select

from database.database import get_session
from database.finans_service import FinansService
from database.models.finans import BankAccountMatchRule, FinansHareketi, FinansHesabi
from database.access import yazma_zorunlu
from entegrasyon.banka_eslestirme import BankAccountMatchingService
from entegrasyon.evb_import_common import _temiz, progress_log

_ACILIS_RE = re.compile(
    r"a[cç]ili[sş]|devir\s*bakiy|a[cç]ili[sş]\s*bakiy",
    re.IGNORECASE,
)


@dataclass
class BankaAcilisSonuc:
    cekilen: int = 0
    acilis_satir: int = 0
    hesap_guncellenen: int = 0
    hareket_silinen: int = 0
    hatalar: list[str] = field(default_factory=list)


def _acilis_metin_mi(metin: str) -> bool:
    t = _temiz(metin)
    if not t:
        return False
    return bool(_ACILIS_RE.search(t))


def acilis_satiri_mi(liste_satir: dict[str, Any], ana: dict[str, Any] | None = None) -> bool:
    ana = ana or {}
    for src in (
        ana.get("a_ack"),
        ana.get("a_tur_ad"),
        liste_satir.get("G.a_ack"),
        liste_satir.get("a_ack"),
        liste_satir.get("FIN_TUR.a_adi"),
    ):
        if _acilis_metin_mi(str(src or "")):
            return True
    return False


def _d(v) -> Decimal:
    s = _temiz(v).replace(",", ".")
    if not s:
        return Decimal("0")
    try:
        return Decimal(s)
    except Exception:
        return Decimal("0")


def _parse_tar(s: str) -> date | None:
    s = _temiz(s)
    if not s:
        return None
    for fmt in ("%d.%m.%Y %H:%M:%S", "%d.%m.%Y"):
        try:
            return datetime.strptime(s[:19] if len(s) > 10 else s, fmt).date()
        except ValueError:
            continue
    return None


def _evo_hareketleri_cek(client) -> list[dict]:
    tum: list[dict] = []
    gorulen: set[str] = set()
    bugun = date.today()
    for yil in range(2015, bugun.year + 1):
        bas = f"01.01.{yil}"
        son = bugun.strftime("%d.%m.%Y") if yil == bugun.year else f"31.12.{yil}"
        sayfa = 0
        while sayfa < 500:
            sat, _ = client.banka_islem_liste_sayfa(sayfa, bas_tar=bas, son_tar=son)
            if not sat:
                break
            for s in sat:
                aid = _temiz(s.get("G.a_id") or s.get("a_id"))
                if not aid or aid in gorulen:
                    continue
                gorulen.add(aid)
                tum.append(s)
            if len(sat) < 30:
                break
            sayfa += 1
    return tum


def _acilis_satirlarini_topla(client, hareketler: list[dict], progress=None) -> dict[str, dict]:
    """evo_banka_id -> {net, aids, adet}."""
    by_bank: dict[str, dict] = defaultdict(
        lambda: {"net": Decimal("0"), "aids": [], "adet": 0}
    )
    # banka -> earliest movement (for detail fallback)
    earliest: dict[str, dict] = {}

    for s in hareketler:
        bid = _temiz(s.get("G.a_banka_id"))
        aid = _temiz(s.get("G.a_id") or s.get("a_id"))
        if not bid or not aid:
            continue
        tar = _parse_tar(s.get("G.a_tarih") or "")
        cur = earliest.get(bid)
        if cur is None:
            earliest[bid] = s
        else:
            cur_tar = _parse_tar(cur.get("G.a_tarih") or "")
            if tar and (cur_tar is None or tar < cur_tar):
                earliest[bid] = s
            elif tar == cur_tar and int(aid) < int(_temiz(cur.get("G.a_id")) or "0"):
                earliest[bid] = s

        if acilis_satiri_mi(s):
            net = _d(s.get("G.a_giren")) - _d(s.get("G.a_cikan"))
            by_bank[bid]["net"] += net
            by_bank[bid]["aids"].append(aid)
            by_bank[bid]["adet"] += 1

    # Liste açıklaması boş olan bankalar: en eski hareket detayına bak
    eksik = [bid for bid in earliest if bid not in by_bank or by_bank[bid]["adet"] == 0]
    progress_log(progress, f"Detay ile açılış kontrolü: {len(eksik)} banka…")
    for i, bid in enumerate(eksik, start=1):
        s = earliest[bid]
        aid = _temiz(s.get("G.a_id"))
        try:
            det = client.banka_islem_detay(aid)
            ana = det.get("Ana") or {}
            if isinstance(ana, list):
                ana = ana[0] if ana else {}
            if acilis_satiri_mi(s, ana):
                net = _d(ana.get("a_giren") or s.get("G.a_giren")) - _d(
                    ana.get("a_cikan") or s.get("G.a_cikan")
                )
                by_bank[bid]["net"] += net
                by_bank[bid]["aids"].append(aid)
                by_bank[bid]["adet"] += 1
        except Exception as exc:  # noqa: BLE001
            progress_log(progress, f"  detay hata banka#{bid} a_id={aid}: {exc}")
        if i < len(eksik):
            import time
            from entegrasyon.evb_import_common import DETAY_BEKLE_SN

            time.sleep(DETAY_BEKLE_SN)

    return by_bank


def aktar_banka_acilis_api_den(
    *,
    creds=None,
    progress: Callable[[str], None] | None = None,
) -> BankaAcilisSonuc:
    from entegrasyon.evobulut_client import EvobulutClient, load_credentials

    yazma_zorunlu("finans_duzenleme")
    sonuc = BankaAcilisSonuc()
    client = EvobulutClient(creds or load_credentials())
    client.login()
    progress_log(progress, "Banka hareketleri çekiliyor (açılış tarama)…")
    hareketler = _evo_hareketleri_cek(client)
    sonuc.cekilen = len(hareketler)
    by_bank = _acilis_satirlarini_topla(client, hareketler, progress=progress)
    sonuc.acilis_satir = sum(v["adet"] for v in by_bank.values())
    progress_log(progress, f"Açılış satırı: {sonuc.acilis_satir} / {len(by_bank)} banka")

    with get_session() as session:
        kurallar = {
            str(k.evo_banka_id): k
            for k in session.scalars(
                select(BankAccountMatchRule).where(BankAccountMatchRule.aktif.is_(True))
            )
        }

    for bid, bil in sorted(by_bank.items(), key=lambda x: x[0]):
        if bil["adet"] <= 0:
            continue
        kural = kurallar.get(str(bid))
        if not kural:
            sonuc.hatalar.append(f"Evo banka#{bid}: eşleştirme yok, açılış atlandı ({bil['net']})")
            continue
        hesap_id = kural.finans_hesap_id or BankAccountMatchingService.mevduat_hesap_id(
            kural.banka_karti_id, "MEVDUAT"
        )
        if not hesap_id:
            sonuc.hatalar.append(f"Evo banka#{bid}: MEVDUAT hesabı yok")
            continue
        try:
            with get_session() as session:
                hesap = session.get(FinansHesabi, int(hesap_id))
                if not hesap:
                    raise ValueError("Hesap bulunamadı")
                hesap.acilis_bakiyesi = Decimal(str(bil["net"]))
                # Açılış hareketlerini sil (çift sayım)
                silinen = 0
                for aid in bil["aids"]:
                    belge = f"EVB-BN-{aid}"
                    for h in list(
                        session.scalars(
                            select(FinansHareketi).where(FinansHareketi.belge_no == belge)
                        )
                    ):
                        session.delete(h)
                        silinen += 1
                session.flush()
            sonuc.hesap_guncellenen += 1
            sonuc.hareket_silinen += silinen
            progress_log(
                progress,
                f"  Evo#{bid} açılış={bil['net']} hesap={hesap_id} "
                f"silinen_hareket={silinen} ({kural.evo_banka_adi or ''})",
            )
        except Exception as exc:  # noqa: BLE001
            sonuc.hatalar.append(f"Evo#{bid}: {exc}")

    return sonuc


def acilis_olarak_uygula(hesap_id: int, tutar: Decimal, *, giris: bool) -> None:
    """Tek hareket aktarımında açılış satırı → acilis_bakiyesi (üzerine ekle)."""
    yazma_zorunlu("finans_duzenleme")
    delta = abs(Decimal(str(tutar))) * (1 if giris else -1)
    with get_session() as session:
        hesap = session.get(FinansHesabi, int(hesap_id))
        if not hesap:
            raise ValueError("Hesap bulunamadı")
        hesap.acilis_bakiyesi = Decimal(str(hesap.acilis_bakiyesi or 0)) + delta
        session.flush()
