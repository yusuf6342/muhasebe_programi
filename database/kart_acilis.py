"""Cari/stok Kart Açılış Tarihi — Cin Muhasebe içi.

- Normal kullanım: ilk başarılı kayıt anı (sistem) → Kart Açılış = olusturma.
- Devir ile yeni kart: Kart Açılış = ilgili planın açılış tarihi; dayanak «Devir».
  Fiili aktarım günü kullanılmaz. Sistem oluşturulma zamanı ayrıca olusturma_tarihi'nde kalır.
- Eski kayıtlarda alanlar NULL; bugünle doldurulmaz. Devir ≠ belge/hareket tarihi.
"""
from __future__ import annotations

import json
from datetime import date, datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

ISTANBUL = ZoneInfo("Europe/Istanbul")

DAYANAK_DEVIR = "Devir"

_KORUNAN_ALANLAR = (
    "olusturma_tarihi",
    "kart_acilis_tarihi",
    "kart_acilis_dayanak",
)


def kart_acilis_simdi() -> datetime:
    """Türkiye duvar saati (naive); sistem oluşturulma anı."""
    return datetime.now(ISTANBUL).replace(tzinfo=None)


def plan_acilis_datetime(plan_acilis: date | datetime | str) -> datetime:
    """Plan açılışını TR naive datetime'a çevir (gün başlangıcı)."""
    if isinstance(plan_acilis, datetime):
        dt = plan_acilis
        if dt.tzinfo is not None:
            dt = dt.astimezone(ISTANBUL).replace(tzinfo=None)
        return dt.replace(microsecond=0)
    if isinstance(plan_acilis, date) and not isinstance(plan_acilis, datetime):
        return datetime(plan_acilis.year, plan_acilis.month, plan_acilis.day)
    s = str(plan_acilis).strip()
    if not s:
        raise ValueError("Plan açılış tarihi boş.")
    if "T" in s or " " in s:
        ham = s.replace("Z", "+00:00")
        dt = datetime.fromisoformat(ham)
        if dt.tzinfo is not None:
            dt = dt.astimezone(ISTANBUL).replace(tzinfo=None)
        return dt.replace(microsecond=0)
    d = date.fromisoformat(s[:10])
    return datetime(d.year, d.month, d.day)


def yeni_kart_tarihleri(
    *,
    dayanak: str | None = None,
    plan_acilis: date | datetime | str | None = None,
) -> dict[str, Any]:
    """Yeni kart için yazılacak tarih alanları (istemci verisinden bağımsız)."""
    sistem = kart_acilis_simdi()
    if dayanak == DAYANAK_DEVIR:
        if plan_acilis is None:
            raise ValueError("Devir kart açılışı için plan açılış tarihi zorunlu.")
        return {
            "olusturma_tarihi": sistem,
            "kart_acilis_tarihi": plan_acilis_datetime(plan_acilis),
            "kart_acilis_dayanak": DAYANAK_DEVIR,
        }
    return {
        "olusturma_tarihi": sistem,
        "kart_acilis_tarihi": sistem,
        "kart_acilis_dayanak": None,
    }


def plan_acilis_devir_isten(devir_is_id: int) -> date:
    """In-app DevirIs.acilis_tarihi — kodda sabit tarih yok."""
    from database.database import get_session
    from database.models.devir import DevirIs

    with get_session() as session:
        is_ = session.get(DevirIs, int(devir_is_id))
        if is_ is None:
            raise ValueError(f"Devir işi bulunamadı: {devir_is_id}")
        acilis = is_.acilis_tarihi
        if acilis is None:
            raise ValueError(f"Devir işinde açılış tarihi yok: {devir_is_id}")
        return acilis


def plan_acilis_d2_sozlesme(yol: Path | None = None) -> datetime:
    """D2 plan dosyasından d2_acilis — sabit kod tarihi kullanılmaz."""
    if yol is None:
        kok = Path(__file__).resolve().parents[1]
        yol = kok / "kurulum" / "dnm_d2_20260901" / "plan" / "ACILIS_SOZLESME.json"
    veri = json.loads(Path(yol).read_text(encoding="utf-8-sig"))
    ham = veri.get("d2_acilis") or (veri.get("bitis_karari") or {}).get("baslangic")
    if not ham:
        raise ValueError(f"D2 açılış tarihi plan dosyasında yok: {yol}")
    return plan_acilis_datetime(ham)


def d2_haric_stok_idler(karar_yolu: Path | None = None) -> frozenset[str]:
    """49 pasif stok — D2 stok kart oluşturma/güncelleme dışı."""
    if karar_yolu is None:
        kok = Path(__file__).resolve().parents[1]
        karar_yolu = (
            kok
            / "kurulum"
            / "dnm_d1_20260831"
            / "kaynak"
            / "D1_20260831_KAYNAK_DOGRULAMA_KULLANICI_KARAR_D2_KAPSAM.json"
        )
    veri = json.loads(Path(karar_yolu).read_text(encoding="utf-8-sig"))
    ids = (veri.get("karar_2_stok49_pasif_d2_disi") or {}).get("stok_ids") or []
    return frozenset(str(x) for x in ids if str(x).strip())


def d2_stok_kart_yazimi_engelli(kaynak_stok_id: str | int | None) -> bool:
    if kaynak_stok_id is None or str(kaynak_stok_id).strip() == "":
        return False
    return str(kaynak_stok_id) in d2_haric_stok_idler()


def devir_yeni_kart_tarihleri(
    *,
    devir_is_id: int | None = None,
    plan_acilis: date | datetime | str | None = None,
) -> dict[str, Any]:
    """Devir ile oluşturulan kart: plan açılışı + sistem oluşturulma."""
    if plan_acilis is None:
        if devir_is_id is None:
            raise ValueError("devir_is_id veya plan_acilis gerekli.")
        plan_acilis = plan_acilis_devir_isten(devir_is_id)
    return yeni_kart_tarihleri(dayanak=DAYANAK_DEVIR, plan_acilis=plan_acilis)


def kart_acilis_uygula(nesne: Any, tarihler: dict[str, Any]) -> None:
    nesne.olusturma_tarihi = tarihler["olusturma_tarihi"]
    nesne.kart_acilis_tarihi = tarihler["kart_acilis_tarihi"]
    nesne.kart_acilis_dayanak = tarihler.get("kart_acilis_dayanak")


def kart_acilis_goster(dt: datetime | date | None) -> str:
    """Salt okunur UI metni; yoksa boş."""
    if dt is None:
        return ""
    if isinstance(dt, datetime):
        if getattr(dt, "tzinfo", None) is not None:
            dt = dt.astimezone(ISTANBUL).replace(tzinfo=None)
        return dt.strftime("%d.%m.%Y %H:%M:%S")
    if isinstance(dt, date):
        return dt.strftime("%d.%m.%Y")
    return ""


def kart_acilis_gosterim(nesne: Any | None) -> dict[str, str]:
    """UI: Kart Açılış (+ Devir dayanağı) ve varsa sistem oluşturulma."""
    if nesne is None:
        return {"acilis": "", "dayanak": "", "sistem": "", "etiket": "—"}
    dayanak = (getattr(nesne, "kart_acilis_dayanak", None) or "").strip()
    acilis = getattr(nesne, "kart_acilis_tarihi", None)
    if acilis is None:
        acilis = getattr(nesne, "olusturma_tarihi", None)
    sistem = getattr(nesne, "olusturma_tarihi", None)
    acilis_metin = kart_acilis_goster(acilis)
    if not acilis_metin:
        return {"acilis": "", "dayanak": "", "sistem": "", "etiket": "—"}
    etiket = acilis_metin
    if dayanak == DAYANAK_DEVIR:
        etiket = f"{acilis_metin} ({DAYANAK_DEVIR})"
    sistem_metin = ""
    if dayanak == DAYANAK_DEVIR and sistem is not None:
        sistem_metin = kart_acilis_goster(sistem)
    return {
        "acilis": acilis_metin,
        "dayanak": dayanak,
        "sistem": sistem_metin,
        "etiket": etiket,
    }


def kart_acilis_koru(veriler: dict) -> dict:
    """İstemciden gelen açılış/oluşturma yazımını engeller."""
    if not isinstance(veriler, dict):
        return veriler
    veriler = dict(veriler)
    for alan in _KORUNAN_ALANLAR:
        veriler.pop(alan, None)
    return veriler
