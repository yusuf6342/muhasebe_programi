"""Banka ana listesi yapı taşıma — DNM D2 kart birleştirme (idempotent).

PayTR → Yapı Kredi POS, Purlikit → Akbank Yatırım, Rönesans → Yapı Kredi Yatırım,
RSÇ World → ana listeden gizle (pasif). Aynı hesap kimlikleri korunur.
"""

from __future__ import annotations

import re
from typing import Any

from sqlalchemy import select, update
from sqlalchemy.orm import selectinload

from database.database import get_session
from database.models.finans import BankaKarti, FinansHesabi, PosValorKaydi

TASIMA_SURUM = "banka_yapi_tasima_v1"

# DNM D2 mevcut kayıt kimlikleri
PAYTR_KART_ID = 4
PAYTR_POS_HESAP_ID = 18
YAPI_KREDI_KART_ID = 3
PURLIKIT_KART_ID = 9
PURLIKIT_HESAP_ID = 43
AKBANK_KART_ID = 1
RONESANS_KART_ID = 31
RONESANS_HESAP_ID = 156
RSC_WORLD_KART_ID = 21

_POS_KAYNAK_RE = re.compile(r"\[POS_KAYNAK_KART=(\d+)\]")


def pos_kaynak_kart_id(hesap: FinansHesabi | None) -> int | None:
    """Taşınmış POS hesabındaki kaynak banka kartı kimliği (komisyon/valör için)."""
    if hesap is None:
        return None
    metin = hesap.aciklama or ""
    m = _POS_KAYNAK_RE.search(metin)
    if m:
        return int(m.group(1))
    return None


def _aciklama_etiket_ekle(mevcut: str | None, etiket: str) -> str:
    metin = (mevcut or "").strip()
    if etiket in metin:
        return metin
    return f"{metin}\n{etiket}".strip() if metin else etiket


def _kart_yukle(session, kart_id: int) -> BankaKarti | None:
    return session.scalar(
        select(BankaKarti)
        .where(BankaKarti.id == int(kart_id))
        .options(selectinload(BankaKarti.alt_hesaplar))
    )


def _hesap_yukle(session, hesap_id: int) -> FinansHesabi | None:
    return session.get(FinansHesabi, int(hesap_id))


def _kart_kabugunu_gizle(
    session,
    kart: BankaKarti,
    etiket: str,
    *,
    korunan_hesap_idler: set[int] | frozenset[int] | None = None,
) -> None:
    """Ana listeden düşür; taşınmayan kalan alt hesapları pasifleştir."""
    korunan = {int(x) for x in (korunan_hesap_idler or ())}
    kart.aktif = False
    kart.aciklama = _aciklama_etiket_ekle(kart.aciklama, etiket)
    for h in list(kart.alt_hesaplar or []):
        if int(h.id) in korunan:
            continue
        # Taşınmış hesap bellek koleksiyonunda kalsa bile hedef karta aitse dokunma
        if int(h.banka_karti_id or 0) != int(kart.id):
            continue
        h.aktif = False


def _paytr_tasi(session, rapor: dict[str, Any]) -> None:
    hedef = _kart_yukle(session, YAPI_KREDI_KART_ID)
    kaynak = _kart_yukle(session, PAYTR_KART_ID)
    hesap = _hesap_yukle(session, PAYTR_POS_HESAP_ID)
    if not hedef or not kaynak or not hesap:
        rapor["adimlar"].append(
            {
                "ad": "paytr",
                "durum": "atlandi",
                "neden": "kart/hesap bulunamadı",
            }
        )
        return

    zaten = (
        int(hesap.banka_karti_id or 0) == YAPI_KREDI_KART_ID
        and (hesap.alt_hesap_turu or "").upper() == "POS"
        and (hesap.hesap_adi or "").strip() == "PayTR"
        and bool(hesap.aktif)
        and not kaynak.aktif
    )
    if zaten:
        rapor["adimlar"].append({"ad": "paytr", "durum": "zaten_uygulandi"})
        return

    eski_kart_id = int(hesap.banka_karti_id or 0)
    hesap.banka_karti_id = YAPI_KREDI_KART_ID
    hesap.alt_hesap_turu = "POS"
    hesap.hesap_adi = "PayTR"
    hesap.banka_adi = hedef.banka_adi
    hesap.aktif = True
    hesap.aciklama = _aciklama_etiket_ekle(
        hesap.aciklama,
        f"[POS_KAYNAK_KART={PAYTR_KART_ID}] [{TASIMA_SURUM}:PayTR]",
    )
    session.flush()

    # Bekleyen / geçmiş POS valor kayıtlarını Yapı Kredi + bu POS hesabına bağla
    session.execute(
        update(PosValorKaydi)
        .where(PosValorKaydi.banka_karti_id == PAYTR_KART_ID)
        .values(banka_karti_id=YAPI_KREDI_KART_ID, pos_hesap_id=PAYTR_POS_HESAP_ID)
    )
    session.execute(
        update(PosValorKaydi)
        .where(PosValorKaydi.pos_hesap_id == PAYTR_POS_HESAP_ID)
        .values(banka_karti_id=YAPI_KREDI_KART_ID)
    )

    _kart_kabugunu_gizle(
        session,
        kaynak,
        f"[{TASIMA_SURUM}:PayTR→YK_POS:{PAYTR_POS_HESAP_ID}]",
        korunan_hesap_idler={PAYTR_POS_HESAP_ID},
    )
    # Taşınan hesabın aktifliğini garanti et (koleksiyon yan etkisi)
    hesap.aktif = True
    rapor["adimlar"].append(
        {
            "ad": "paytr",
            "durum": "tasindi",
            "hesap_id": PAYTR_POS_HESAP_ID,
            "eski_kart_id": eski_kart_id,
            "yeni_kart_id": YAPI_KREDI_KART_ID,
            "yeni_ad": "PayTR",
        }
    )


def _yatirim_tasi(
    session,
    *,
    rapor: dict[str, Any],
    ad: str,
    kaynak_kart_id: int,
    hesap_id: int,
    hedef_kart_id: int,
    yeni_ad: str,
) -> None:
    hedef = _kart_yukle(session, hedef_kart_id)
    kaynak = _kart_yukle(session, kaynak_kart_id)
    hesap = _hesap_yukle(session, hesap_id)
    if not hedef or not kaynak or not hesap:
        rapor["adimlar"].append(
            {"ad": ad, "durum": "atlandi", "neden": "kart/hesap bulunamadı"}
        )
        return

    zaten = (
        int(hesap.banka_karti_id or 0) == hedef_kart_id
        and (hesap.alt_hesap_turu or "").upper() == "VADELI"
        and (hesap.hesap_adi or "").strip() == yeni_ad
        and bool(hesap.aktif)
        and not kaynak.aktif
    )
    if zaten:
        rapor["adimlar"].append({"ad": ad, "durum": "zaten_uygulandi"})
        return

    eski_kart_id = int(hesap.banka_karti_id or 0)
    hesap.banka_karti_id = hedef_kart_id
    hesap.alt_hesap_turu = "VADELI"
    hesap.hesap_adi = yeni_ad
    hesap.banka_adi = hedef.banka_adi
    hesap.aktif = True
    hesap.aciklama = _aciklama_etiket_ekle(
        hesap.aciklama, f"[{TASIMA_SURUM}:{ad}]"
    )
    session.flush()
    _kart_kabugunu_gizle(
        session,
        kaynak,
        f"[{TASIMA_SURUM}:{ad}→{hedef_kart_id}:{hesap_id}]",
        korunan_hesap_idler={hesap_id},
    )
    hesap.aktif = True
    rapor["adimlar"].append(
        {
            "ad": ad,
            "durum": "tasindi",
            "hesap_id": hesap_id,
            "eski_kart_id": eski_kart_id,
            "yeni_kart_id": hedef_kart_id,
            "yeni_ad": yeni_ad,
        }
    )


def _rsc_gizle(session, rapor: dict[str, Any]) -> None:
    kart = _kart_yukle(session, RSC_WORLD_KART_ID)
    if not kart:
        rapor["adimlar"].append(
            {"ad": "rsc_world", "durum": "atlandi", "neden": "kart yok"}
        )
        return
    if not kart.aktif and TASIMA_SURUM in (kart.aciklama or ""):
        rapor["adimlar"].append({"ad": "rsc_world", "durum": "zaten_uygulandi"})
        return
    # Ana listeden gizle; alt hesapları (zaten boş/pasif) ve kayıt erişimini koru
    kart.aktif = False
    kart.aciklama = _aciklama_etiket_ekle(
        kart.aciklama, f"[{TASIMA_SURUM}:RSÇ_WORLD_GIZLE]"
    )
    # Alt hesapları silme / taşıma yok — yalnızca görünürlük
    rapor["adimlar"].append(
        {"ad": "rsc_world", "durum": "gizlendi", "kart_id": RSC_WORLD_KART_ID}
    )


def banka_yapi_tasima_uygula(*, session=None) -> dict[str, Any]:
    """Tek işlemde taşıma. Tekrar çalışınca aynı sonuç (idempotent)."""
    rapor: dict[str, Any] = {"surum": TASIMA_SURUM, "adimlar": [], "ok": True}

    def _calistir(s):
        _paytr_tasi(s, rapor)
        _yatirim_tasi(
            s,
            rapor=rapor,
            ad="purlikit",
            kaynak_kart_id=PURLIKIT_KART_ID,
            hesap_id=PURLIKIT_HESAP_ID,
            hedef_kart_id=AKBANK_KART_ID,
            yeni_ad="Pur Likit",
        )
        _yatirim_tasi(
            s,
            rapor=rapor,
            ad="ronesans",
            kaynak_kart_id=RONESANS_KART_ID,
            hesap_id=RONESANS_HESAP_ID,
            hedef_kart_id=YAPI_KREDI_KART_ID,
            yeni_ad="Rönesans Holding Hisse",
        )
        _rsc_gizle(s, rapor)
        s.flush()

    if session is not None:
        _calistir(session)
        return rapor

    with get_session() as s:
        _calistir(s)
    return rapor
