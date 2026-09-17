"""Cari ve stok eşleştirme."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import select

from database.cari_service import CariService
from database.database import get_session
from database.models.cari import Cari
from database.models.stok import StokKarti
from fatura_belge_aktarim.models import InvoiceImportLine, PartyMatchRule, ProductMatchRule
from fatura_belge_aktarim.normalize import normalize_text, normalize_vkn


class PartyMatchingService:
    @staticmethod
    def eslestir(vkn: str | None, unvan: str | None, *, cari_turu: str) -> dict[str, Any]:
        vkn_n = normalize_vkn(vkn)
        adaylar: list[dict[str, Any]] = []

        if vkn_n:
            with get_session() as session:
                kural = session.scalar(
                    select(PartyMatchRule).where(
                        PartyMatchRule.vergi_no == vkn_n,
                        PartyMatchRule.aktif.is_(True),
                    )
                )
                if kural:
                    cari = session.get(Cari, kural.cari_id)
                    if cari and not cari.is_deleted:
                        return {
                            "modu": "hafiza",
                            "guven": Decimal("98"),
                            "cari_id": cari.id,
                            "cari": cari,
                            "adaylar": [],
                        }
                for cari in session.scalars(select(Cari).where(Cari.is_deleted.is_(False))).all():
                    cv = normalize_vkn(cari.vergi_numarasi) or normalize_vkn(cari.tc_kimlik)
                    if cv and cv == vkn_n:
                        adaylar.append(
                            {
                                "cari_id": cari.id,
                                "cari_kodu": cari.cari_kodu,
                                "unvan": cari.unvan,
                                "guven": Decimal("95"),
                                "neden": "vergi_no",
                            }
                        )

        if not adaylar and unvan:
            hedef = normalize_text(unvan)
            for ozet in CariService.listele(cari_turu=cari_turu, hizli=True):
                cari = ozet["cari"]
                if hedef and hedef in normalize_text(cari.unvan):
                    adaylar.append(
                        {
                            "cari_id": cari.id,
                            "cari_kodu": cari.cari_kodu,
                            "unvan": cari.unvan,
                            "guven": Decimal("55"),
                            "neden": "unvan",
                        }
                    )
            adaylar = adaylar[:5]

        if len(adaylar) == 1 and adaylar[0]["guven"] >= Decimal("90"):
            return {
                "modu": "otomatik",
                "guven": adaylar[0]["guven"],
                "cari_id": adaylar[0]["cari_id"],
                "adaylar": adaylar,
            }
        if adaylar:
            return {"modu": "secim_gerekli", "guven": adaylar[0]["guven"], "cari_id": None, "adaylar": adaylar}
        return {"modu": "bulunamadi", "guven": Decimal("0"), "cari_id": None, "adaylar": []}

    @staticmethod
    def hafizaya_yaz(vergi_no: str, cari_id: int, unvan: str | None = None) -> None:
        vkn = normalize_vkn(vergi_no)
        if not vkn:
            return
        with get_session() as session:
            kural = session.scalar(select(PartyMatchRule).where(PartyMatchRule.vergi_no == vkn))
            if kural:
                kural.cari_id = cari_id
                kural.unvan_ornek = unvan
                kural.updated_at = datetime.now()
                kural.aktif = True
            else:
                session.add(
                    PartyMatchRule(
                        vergi_no=vkn,
                        cari_id=cari_id,
                        unvan_ornek=unvan,
                        guven=Decimal("100"),
                    )
                )
            session.flush()


class ProductMatchingService:
    @staticmethod
    def satir_eslestir(
        line: InvoiceImportLine,
        *,
        tedarikci_cari_id: int | None,
    ) -> dict[str, Any]:
        with get_session() as session:
            # 1) Hafıza: tedarikçi + satıcı kodu
            if tedarikci_cari_id and line.satici_urun_kodu:
                kural = session.scalar(
                    select(ProductMatchRule).where(
                        ProductMatchRule.tedarikci_cari_id == tedarikci_cari_id,
                        ProductMatchRule.satici_urun_kodu == line.satici_urun_kodu,
                        ProductMatchRule.aktif.is_(True),
                    )
                )
                if kural:
                    stok = session.get(StokKarti, kural.stok_id)
                    if stok and not stok.is_deleted:
                        return {
                            "status": "eslesti",
                            "stok_id": stok.id,
                            "stok_kodu": stok.stok_kodu,
                            "guven": Decimal("97"),
                            "birim_carpan": kural.birim_carpan,
                            "neden": "hafiza",
                        }
            # 2) Barkod
            if line.barkod:
                stok = session.scalar(
                    select(StokKarti).where(
                        StokKarti.barkod == line.barkod.strip(),
                        StokKarti.is_deleted.is_(False),
                    )
                )
                if stok:
                    return {
                        "status": "eslesti",
                        "stok_id": stok.id,
                        "stok_kodu": stok.stok_kodu,
                        "guven": Decimal("93"),
                        "birim_carpan": Decimal("1"),
                        "neden": "barkod",
                    }
            # 3) Alıcı ürün kodu = bizim stok kodu
            if line.alici_urun_kodu:
                stok = session.scalar(
                    select(StokKarti).where(
                        StokKarti.stok_kodu == line.alici_urun_kodu.strip(),
                        StokKarti.is_deleted.is_(False),
                    )
                )
                if stok:
                    return {
                        "status": "eslesti",
                        "stok_id": stok.id,
                        "stok_kodu": stok.stok_kodu,
                        "guven": Decimal("88"),
                        "birim_carpan": Decimal("1"),
                        "neden": "stok_kodu",
                    }
            # 4) Ad benzerliği
            adaylar = []
            hedef = normalize_text(line.aciklama)
            if hedef and len(hedef) >= 3:
                for stok in session.scalars(
                    select(StokKarti).where(StokKarti.is_deleted.is_(False)).limit(500)
                ):
                    if hedef in normalize_text(stok.stok_adi) or normalize_text(stok.stok_adi) in hedef:
                        adaylar.append(
                            {
                                "stok_id": stok.id,
                                "stok_kodu": stok.stok_kodu,
                                "stok_adi": stok.stok_adi,
                                "guven": Decimal("50"),
                            }
                        )
                        if len(adaylar) >= 5:
                            break
            if len(adaylar) == 1:
                a = adaylar[0]
                return {
                    "status": "eslesti",
                    "stok_id": a["stok_id"],
                    "stok_kodu": a["stok_kodu"],
                    "guven": a["guven"],
                    "birim_carpan": Decimal("1"),
                    "neden": "ad",
                    "adaylar": adaylar,
                }
            if adaylar:
                return {"status": "secim_gerekli", "guven": Decimal("45"), "adaylar": adaylar}
            return {"status": "bulunamadi", "guven": Decimal("0"), "adaylar": []}

    @staticmethod
    def hafizaya_yaz(
        *,
        tedarikci_cari_id: int | None,
        satici_urun_kodu: str | None,
        barkod: str | None,
        stok_id: int,
        birim_carpan: Decimal = Decimal("1"),
    ) -> None:
        with get_session() as session:
            session.add(
                ProductMatchRule(
                    tedarikci_cari_id=tedarikci_cari_id,
                    satici_urun_kodu=satici_urun_kodu,
                    barkod=barkod,
                    stok_id=stok_id,
                    birim_carpan=birim_carpan,
                    guven=Decimal("100"),
                    kaynak="kullanici",
                )
            )
            session.flush()
