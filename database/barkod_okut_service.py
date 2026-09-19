"""Satış faturası barkod okutma — stok arama ve indeks (DB yazımı yok)."""

from __future__ import annotations

import re
from decimal import Decimal
from typing import Any

from sqlalchemy import select, text
from sqlalchemy.orm import selectinload

from database.database import get_session
from database.models.stok import StokBarkod, StokBirim, StokKarti
from database.stok_service import StokService

_KONTROL = re.compile(r"[\x00-\x1f\x7f]")


def barkod_temizle(ham: str | None) -> str:
    """Boşluk/kontrol karakterlerini temizler; güvenli barkod metni döner."""
    metin = (ham or "").strip()
    metin = _KONTROL.sub("", metin).strip()
    if len(metin) > 64:
        metin = metin[:64]
    return metin


def barkod_gecerli_mi(kod: str) -> bool:
    if not kod:
        return False
    if not re.sub(r"[\s\-_/]", "", kod):
        return False
    return True


def barkod_indeksleri_guncelle(engine=None) -> None:
    """stok barkod alanlarında indeks — idempotent soft migration."""
    from sqlalchemy import inspect

    from database.database import engine as default_engine

    eng = engine or default_engine
    if eng is None:
        return
    insp = inspect(eng)
    with eng.begin() as conn:
        if insp.has_table("stok_barkodlari"):
            try:
                conn.execute(
                    text(
                        'CREATE INDEX IF NOT EXISTS "ix_stok_barkodlari_barkod" '
                        'ON "stok_barkodlari" ("barkod")'
                    )
                )
            except Exception:
                pass
        if insp.has_table("stok_kartlari"):
            try:
                conn.execute(
                    text(
                        'CREATE INDEX IF NOT EXISTS "ix_stok_kartlari_barkod" '
                        'ON "stok_kartlari" ("barkod")'
                    )
                )
            except Exception:
                pass
        if insp.has_table("stok_birimleri"):
            try:
                conn.execute(
                    text(
                        'CREATE INDEX IF NOT EXISTS "ix_stok_birimleri_birim_barkod" '
                        'ON "stok_birimleri" ("birim_barkod")'
                    )
                )
            except Exception:
                pass


def _pasif_ozet(stok: StokKarti, barkod: str) -> dict[str, Any]:
    mevcut = sum((lot.kalan_miktar for lot in (stok.lotlar or [])), Decimal("0"))
    return {
        "stok_id": int(stok.id),
        "stok_kodu": stok.stok_kodu,
        "stok_adi": stok.stok_adi,
        "barkod": barkod,
        "birim": (stok.birim or "Adet").strip() or "Adet",
        "miktar": Decimal("1"),
        "birim_fiyat": Decimal("0"),
        "mevcut_stok": mevcut,
        "aktif": False,
        "satis_kapali": False,
    }


def _aktif_mi(stok: StokKarti | None) -> bool:
    if stok is None:
        return False
    if not stok.aktif:
        return False
    if bool(getattr(stok, "is_deleted", False)):
        return False
    return True


def barkod_ile_ara(barkod: str) -> dict[str, Any]:
    """Barkod araması — aktif/pasif ayrımı, çoklu eşleşme.

    Dönüş:
      {"durum": "ok"|"pasif"|"bulunamadi"|"coklu"|"satis_kapali"|"gecersiz",
       "kayit": dict|None, "liste": list[dict], "mesaj": str}
    """
    kod = barkod_temizle(barkod)
    if not barkod_gecerli_mi(kod):
        return {
            "durum": "gecersiz",
            "kayit": None,
            "liste": [],
            "mesaj": "Geçersiz barkod.",
        }

    aktif_idler: list[int] = []
    pasifler: list[dict[str, Any]] = []
    gorulen: set[int] = set()

    with get_session() as session:
        for kayit in session.scalars(
            select(StokBarkod)
            .where(StokBarkod.barkod == kod)
            .options(
                selectinload(StokBarkod.stok).selectinload(StokKarti.lotlar),
            )
        ).all():
            stok = kayit.stok
            if stok is None or int(stok.id) in gorulen:
                continue
            gorulen.add(int(stok.id))
            if _aktif_mi(stok):
                aktif_idler.append(int(stok.id))
            else:
                pasifler.append(_pasif_ozet(stok, kod))

        for stok in session.scalars(
            select(StokKarti)
            .where(StokKarti.barkod == kod)
            .options(selectinload(StokKarti.lotlar))
        ).all():
            if int(stok.id) in gorulen:
                continue
            gorulen.add(int(stok.id))
            if _aktif_mi(stok):
                aktif_idler.append(int(stok.id))
            else:
                pasifler.append(_pasif_ozet(stok, kod))

        for birim in session.scalars(
            select(StokBirim)
            .where(StokBirim.birim_barkod == kod, StokBirim.aktif.is_(True))
            .options(
                selectinload(StokBirim.stok).selectinload(StokKarti.lotlar),
            )
        ).all():
            stok = birim.stok
            if stok is None or int(stok.id) in gorulen:
                continue
            gorulen.add(int(stok.id))
            if _aktif_mi(stok):
                aktif_idler.append(int(stok.id))
            else:
                pasifler.append(_pasif_ozet(stok, kod))

    # Detaylı aktif kayıtlar (fiyat/çarpan) — mevcut indeksli arama
    aktif_kayitlar: list[dict[str, Any]] = []
    tek = StokService.barkod_ile_bul(kod)
    if tek and int(tek.get("stok_id") or 0) in aktif_idler:
        tek["aktif"] = True
        tek["satis_kapali"] = False
        aktif_kayitlar.append(tek)
        # Çokluysa diğer id'ler için de barkod_ile_bul aynı barkodda tek döner;
        # stok kodu üzerinden tamamla
        for sid in aktif_idler:
            if any(int(k["stok_id"]) == sid for k in aktif_kayitlar):
                continue
            # Nadir: aynı barkod birden fazla stokta — kod ile yükle
            with get_session() as session:
                stok = session.get(StokKarti, sid)
                if stok is None:
                    continue
                fiyat = StokService.satis_fiyati_1(stok.stok_kodu)
                mevcut = sum(
                    (lot.kalan_miktar for lot in (stok.lotlar or [])), Decimal("0")
                )
                aktif_kayitlar.append(
                    {
                        "stok_id": sid,
                        "stok_kodu": stok.stok_kodu,
                        "stok_adi": stok.stok_adi,
                        "barkod": kod,
                        "birim": (stok.birim or "Adet").strip() or "Adet",
                        "miktar": Decimal("1"),
                        "birim_fiyat": fiyat,
                        "mevcut_stok": mevcut,
                        "kdv_orani": Decimal(str(stok.kdv_orani or 20)),
                        "aktif": True,
                        "satis_kapali": False,
                    }
                )
    elif aktif_idler:
        # barkod_ile_bul None döndü ama aktif id var (edge)
        for sid in aktif_idler:
            with get_session() as session:
                stok = session.scalar(
                    select(StokKarti)
                    .where(StokKarti.id == sid)
                    .options(selectinload(StokKarti.lotlar))
                )
                if stok is None:
                    continue
                fiyat = StokService.satis_fiyati_1(stok.stok_kodu)
                mevcut = sum(
                    (lot.kalan_miktar for lot in (stok.lotlar or [])), Decimal("0")
                )
                aktif_kayitlar.append(
                    {
                        "stok_id": sid,
                        "stok_kodu": stok.stok_kodu,
                        "stok_adi": stok.stok_adi,
                        "barkod": kod,
                        "birim": (stok.birim or "Adet").strip() or "Adet",
                        "miktar": Decimal("1"),
                        "birim_fiyat": fiyat,
                        "mevcut_stok": mevcut,
                        "kdv_orani": Decimal(str(stok.kdv_orani or 20)),
                        "aktif": True,
                        "satis_kapali": False,
                    }
                )

    if len(aktif_kayitlar) > 1:
        return {
            "durum": "coklu",
            "kayit": None,
            "liste": aktif_kayitlar,
            "mesaj": "Bu barkoda birden fazla ürün bağlı. Lütfen seçin.",
        }
    if len(aktif_kayitlar) == 1:
        kayit = aktif_kayitlar[0]
        if kayit.get("satis_kapali"):
            return {
                "durum": "satis_kapali",
                "kayit": kayit,
                "liste": [],
                "mesaj": f"«{kayit.get('stok_adi')}» satışa kapalı.",
            }
        return {"durum": "ok", "kayit": kayit, "liste": [], "mesaj": ""}
    if pasifler:
        p = pasifler[0]
        return {
            "durum": "pasif",
            "kayit": p,
            "liste": pasifler,
            "mesaj": f"«{p.get('stok_adi')}» pasif — faturaya eklenemez.",
        }
    return {
        "durum": "bulunamadi",
        "kayit": None,
        "liste": [],
        "mesaj": "Bu barkoda bağlı ürün bulunamadı.",
    }


def depo_mevcut_miktar(stok_kodu: str, depo_adi: str) -> Decimal:
    """Depodaki kalan miktar (lot toplamı)."""
    try:
        lotlar = StokService.lotlar(stok_kodu, depo_adi)
    except Exception:
        return Decimal("0")
    return sum((Decimal(str(l.kalan_miktar or 0)) for l in lotlar), Decimal("0"))
