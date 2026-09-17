"""EvoBulut banka kartı ↔ Cin Muhasebe BankaKarti eşleştirme."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import selectinload

from database.database import get_session
from database.models.finans import BANKA_ALT_HESAP_TURLERI, BankAccountMatchRule, BankaKarti, FinansHesabi
from entegrasyon.evb_import_common import _temiz


def normalize_iban(deger: Any) -> str:
    return _temiz(deger).replace(" ", "").upper()


def normalize_banka_adi(deger: Any) -> str:
    return " ".join(_temiz(deger).casefold().split())


class BankAccountMatchingService:
    @staticmethod
    def kural_bul(evo_banka_id: str | None = None, *, iban: str | None = None) -> BankAccountMatchRule | None:
        evo_id = _temiz(evo_banka_id)
        iban_n = normalize_iban(iban) if iban else ""
        with get_session() as session:
            if evo_id:
                k = session.scalar(
                    select(BankAccountMatchRule).where(
                        BankAccountMatchRule.evo_banka_id == evo_id,
                        BankAccountMatchRule.aktif.is_(True),
                    )
                )
                if k:
                    return k
            if iban_n:
                return session.scalar(
                    select(BankAccountMatchRule).where(
                        BankAccountMatchRule.iban == iban_n,
                        BankAccountMatchRule.aktif.is_(True),
                    )
                )
        return None

    @staticmethod
    def hafizaya_yaz(
        *,
        evo_banka_id: str,
        banka_karti_id: int,
        evo_banka_adi: str | None = None,
        finans_hesap_id: int | None = None,
        alt_hesap_turu: str = "MEVDUAT",
        iban: str | None = None,
        hesap_no: str | None = None,
        guven: Decimal = Decimal("100"),
        kaynak: str = "api",
    ) -> BankAccountMatchRule:
        evo_id = _temiz(evo_banka_id)
        if not evo_id:
            raise ValueError("evo_banka_id zorunlu")
        with get_session() as session:
            kural = session.scalar(
                select(BankAccountMatchRule).where(BankAccountMatchRule.evo_banka_id == evo_id)
            )
            if kural is None:
                kural = BankAccountMatchRule(evo_banka_id=evo_id)
                session.add(kural)
            kural.evo_banka_adi = (evo_banka_adi or "").strip() or None
            kural.banka_karti_id = int(banka_karti_id)
            kural.finans_hesap_id = int(finans_hesap_id) if finans_hesap_id else None
            kural.alt_hesap_turu = (alt_hesap_turu or "MEVDUAT").upper()
            kural.iban = normalize_iban(iban) or None
            kural.hesap_no = _temiz(hesap_no) or None
            kural.guven = guven
            kural.kaynak = kaynak
            kural.aktif = True
            kural.updated_at = datetime.now()
            session.flush()
            session.refresh(kural)
            return kural

    @staticmethod
    def mevduat_hesap_id(banka_karti_id: int, alt_hesap_turu: str = "MEVDUAT") -> int | None:
        tur = (alt_hesap_turu or "MEVDUAT").upper()
        with get_session() as session:
            h = session.scalar(
                select(FinansHesabi).where(
                    FinansHesabi.banka_karti_id == int(banka_karti_id),
                    FinansHesabi.alt_hesap_turu == tur,
                    FinansHesabi.aktif.is_(True),
                )
            )
            return int(h.id) if h else None

    @staticmethod
    def finans_hesap_bul(
        *,
        evo_banka_id: str | None = None,
        iban: str | None = None,
        banka_adi: str | None = None,
        alt_hesap_turu: str = "MEVDUAT",
    ) -> dict[str, Any]:
        """Hareket aktarımı için hedef finans hesabı."""
        kural = BankAccountMatchingService.kural_bul(evo_banka_id, iban=iban)
        if kural:
            hesap_id = kural.finans_hesap_id or BankAccountMatchingService.mevduat_hesap_id(
                kural.banka_karti_id, kural.alt_hesap_turu or alt_hesap_turu
            )
            if hesap_id:
                return {
                    "modu": "hafiza",
                    "guven": kural.guven or Decimal("95"),
                    "finans_hesap_id": hesap_id,
                    "banka_karti_id": kural.banka_karti_id,
                    "evo_banka_id": kural.evo_banka_id,
                }

        # IBAN ile kart
        iban_n = normalize_iban(iban) if iban else ""
        if iban_n:
            with get_session() as session:
                kart = session.scalar(
                    select(BankaKarti).where(
                        BankaKarti.iban == iban_n,
                        BankaKarti.aktif.is_(True),
                    )
                )
                if kart:
                    hesap_id = BankAccountMatchingService.mevduat_hesap_id(kart.id, alt_hesap_turu)
                    if hesap_id:
                        return {
                            "modu": "iban",
                            "guven": Decimal("90"),
                            "finans_hesap_id": hesap_id,
                            "banka_karti_id": kart.id,
                        }

        # Ada göre
        hedef = normalize_banka_adi(banka_adi)
        if hedef:
            with get_session() as session:
                kartlar = list(
                    session.scalars(
                        select(BankaKarti)
                        .where(BankaKarti.aktif.is_(True))
                        .options(selectinload(BankaKarti.alt_hesaplar))
                    )
                )
            adaylar = []
            for kart in kartlar:
                ad = normalize_banka_adi(kart.banka_adi)
                if ad == hedef or hedef in ad or ad in hedef:
                    adaylar.append(kart)
            if len(adaylar) == 1:
                hesap_id = BankAccountMatchingService.mevduat_hesap_id(adaylar[0].id, alt_hesap_turu)
                if hesap_id:
                    return {
                        "modu": "ad",
                        "guven": Decimal("70"),
                        "finans_hesap_id": hesap_id,
                        "banka_karti_id": adaylar[0].id,
                    }
            if len(adaylar) > 1:
                return {
                    "modu": "secim_gerekli",
                    "guven": Decimal("40"),
                    "adaylar": [{"banka_karti_id": k.id, "banka_adi": k.banka_adi} for k in adaylar],
                }

        return {"modu": "bulunamadi", "guven": Decimal("0"), "finans_hesap_id": None}
