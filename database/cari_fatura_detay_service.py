"""Cari hesap hareketi → fatura ürün detayları (lazy load).

İlişki önceliği: fatura/iade ID (fatura_no / iade_no ile çözülür, sonra satırlar ID ile).
Stok hareketleri belge_no üzerinden eşlenir; yön tahmini yazılmaz — kayıt varsa gerçek tür gösterilir.
"""

from __future__ import annotations

import logging
from datetime import datetime
from decimal import Decimal, ROUND_HALF_UP
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import selectinload

from database.database import get_session
from database.session_manager import oturum

_LOG = logging.getLogger("cari_fatura_detay")

# Cari hareket "tur" değerleri / belge önekleri → belge tipi
_FATURA_TURLERI = frozenset({"Satış", "Alış", "Satış İadesi", "Alış İadesi"})

_STOK_YONU_ETIKET = {
    "satis_faturasi": "Stok Çıkışı",
    "alis_faturasi": "Stok Girişi",
    "satis_iade": "Stok Girişi",
    "alis_iade": "Stok Çıkışı",
}


def belge_tipi_coz(tur: str | None, belge_no: str | None) -> str | None:
    """Hareket türü + belge no → dahili belge tipi kodu."""
    no = (belge_no or "").strip()
    t = (tur or "").strip()
    if no.startswith("AIAD-") or t == "Alış İadesi":
        return "alis_iade"
    if no.startswith("IAD-") or t == "Satış İadesi":
        return "satis_iade"
    if no.startswith(("AFAT-", "ARAY")) or t == "Alış":
        return "alis_faturasi"
    if t == "Satış" or no.startswith("SF-"):
        return "satis_faturasi"
    if t in _FATURA_TURLERI:
        # Bilinmeyen önek ama fatura türü — satış varsay
        if t == "Alış":
            return "alis_faturasi"
        if t == "Satış":
            return "satis_faturasi"
    return None


def hareket_genisletilebilir_mi(tur: str | None, belge_no: str | None) -> bool:
    return belge_tipi_coz(tur, belge_no) is not None


def _kurus(x: Decimal) -> Decimal:
    return x.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def _satir_net(miktar, fiyat, isk1=0, isk2=0, isk3=0) -> Decimal:
    net = Decimal(str(miktar or 0)) * Decimal(str(fiyat or 0))
    for oran in (isk1, isk2, isk3):
        o = Decimal(str(oran or 0))
        if o:
            net -= net * o / Decimal("100")
    return net


def _miktar_goster(deger) -> str:
    d = Decimal(str(deger or 0))
    if d == d.to_integral_value():
        return str(int(d))
    s = f"{d:.4f}".rstrip("0").rstrip(".")
    return s.replace(".", ",")


def _para(deger) -> str:
    d = _kurus(Decimal(str(deger or 0)))
    return f"{d:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".") + " TL"


def _hata_logla(
    *,
    cari_id: int | None,
    hareket_id: Any,
    fatura_id: int | None,
    belge_turu: str | None,
    hata: BaseException,
) -> None:
    firma = None
    try:
        o = oturum()
        firma = getattr(o, "firma_id", None) or getattr(o, "aktif_firma_id", None)
    except Exception:
        pass
    _LOG.exception(
        "Fatura detay yüklenemedi | cari_id=%s hareket_id=%s fatura_id=%s belge_turu=%s firma_id=%s zaman=%s hata=%s",
        cari_id,
        hareket_id,
        fatura_id,
        belge_turu,
        firma,
        datetime.now().isoformat(timespec="seconds"),
        hata,
    )


class CariFaturaDetayService:
    """Lazy fatura satır + stok eşleme servisi."""

    @staticmethod
    def hareketlere_meta_ekle(kayitlar: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Defter satırlarına fatura_id / belge_tipi / genisletilebilir ekler (batch)."""
        if not kayitlar:
            return kayitlar

        gruplar: dict[str, set[str]] = {
            "satis_faturasi": set(),
            "alis_faturasi": set(),
            "satis_iade": set(),
            "alis_iade": set(),
        }
        for k in kayitlar:
            tip = belge_tipi_coz(k.get("tur"), k.get("belge_no"))
            if tip and k.get("belge_no"):
                gruplar[tip].add(str(k["belge_no"]).strip())

        harita: dict[tuple[str, str], dict[str, Any]] = {}
        with get_session() as session:
            if gruplar["satis_faturasi"]:
                from database.models.satis_faturasi import SatisFaturasi

                for f in session.scalars(
                    select(SatisFaturasi).where(
                        SatisFaturasi.fatura_no.in_(list(gruplar["satis_faturasi"]))
                    )
                ):
                    harita[("satis_faturasi", f.fatura_no)] = {
                        "fatura_id": int(f.id),
                        "belge_tipi": "satis_faturasi",
                        "durum": f.durum,
                        "cari_id_belge": int(f.cari_id),
                    }
            if gruplar["alis_faturasi"]:
                from database.models.alis_faturasi import AlisFaturasi

                for f in session.scalars(
                    select(AlisFaturasi).where(
                        AlisFaturasi.fatura_no.in_(list(gruplar["alis_faturasi"]))
                    )
                ):
                    harita[("alis_faturasi", f.fatura_no)] = {
                        "fatura_id": int(f.id),
                        "belge_tipi": "alis_faturasi",
                        "durum": f.durum,
                        "cari_id_belge": int(f.cari_id),
                    }
            if gruplar["satis_iade"]:
                from database.models.satis_iade_faturasi import SatisIadeFaturasi

                for f in session.scalars(
                    select(SatisIadeFaturasi).where(
                        SatisIadeFaturasi.iade_no.in_(list(gruplar["satis_iade"]))
                    )
                ):
                    harita[("satis_iade", f.iade_no)] = {
                        "fatura_id": int(f.id),
                        "belge_tipi": "satis_iade",
                        "durum": f.durum,
                        "cari_id_belge": int(f.cari_id),
                    }
            if gruplar["alis_iade"]:
                from database.models.alis_iade_faturasi import AlisIadeFaturasi

                for f in session.scalars(
                    select(AlisIadeFaturasi).where(
                        AlisIadeFaturasi.iade_no.in_(list(gruplar["alis_iade"]))
                    )
                ):
                    harita[("alis_iade", f.iade_no)] = {
                        "fatura_id": int(f.id),
                        "belge_tipi": "alis_iade",
                        "durum": f.durum,
                        "cari_id_belge": int(f.cari_id),
                    }

        for k in kayitlar:
            tip = belge_tipi_coz(k.get("tur"), k.get("belge_no"))
            no = str(k.get("belge_no") or "").strip()
            meta = harita.get((tip, no)) if tip else None
            if meta:
                # Firma ayrımı: cari karttaki cari_id ile belge cari_id uyuşmalı
                if k.get("cari_id") and meta.get("cari_id_belge") != int(k["cari_id"]):
                    k["genisletilebilir"] = False
                    k["fatura_id"] = None
                    k["belge_tipi"] = None
                    continue
                k.update(
                    {
                        "genisletilebilir": True,
                        "fatura_id": meta["fatura_id"],
                        "belge_tipi": meta["belge_tipi"],
                        "fatura_durum": meta.get("durum"),
                        "stok_yonu_etiket": _STOK_YONU_ETIKET.get(meta["belge_tipi"], ""),
                    }
                )
            elif tip:
                # Fatura türü ama kayıt bulunamadı — ikon pasif / uyarı
                k["genisletilebilir"] = False
                k["fatura_id"] = None
                k["belge_tipi"] = tip
                k["detay_uyari"] = "Bu faturaya ait ürün detayı bulunamadı"
            else:
                k["genisletilebilir"] = False
                k["fatura_id"] = None
                k["belge_tipi"] = None
        return kayitlar

    @staticmethod
    def load_invoice_details(
        fatura_id: int,
        belge_tipi: str,
        *,
        cari_id: int | None = None,
        hareket_id: Any = None,
    ) -> dict[str, Any]:
        """Tek faturanın satırları + stok eşlemesi. Lazy load için."""
        try:
            return CariFaturaDetayService._load_inner(
                int(fatura_id), belge_tipi, cari_id=cari_id
            )
        except Exception as exc:
            _hata_logla(
                cari_id=cari_id,
                hareket_id=hareket_id,
                fatura_id=fatura_id,
                belge_turu=belge_tipi,
                hata=exc,
            )
            raise ValueError(
                "Fatura ürün detayları yüklenemedi. Lütfen tekrar deneyin."
            ) from exc

    @staticmethod
    def _load_inner(
        fatura_id: int, belge_tipi: str, *, cari_id: int | None
    ) -> dict[str, Any]:
        with get_session() as session:
            belge_no = ""
            durum = ""
            para = "TRY"
            satirlar_orm: list = []
            depo_adi = ""

            if belge_tipi == "satis_faturasi":
                from database.models.satis_faturasi import SatisFaturasi

                f = session.scalar(
                    select(SatisFaturasi)
                    .where(SatisFaturasi.id == fatura_id)
                    .options(selectinload(SatisFaturasi.satirlar))
                )
                if f is None:
                    return {"satirlar": [], "uyari": "Bu faturaya ait ürün detayı bulunamadı"}
                if cari_id and int(f.cari_id) != int(cari_id):
                    return {"satirlar": [], "uyari": "Bu faturaya ait ürün detayı bulunamadı"}
                belge_no, durum, para = f.fatura_no, f.durum or "", f.para_birimi or "TRY"
                depo_adi = getattr(f, "depo", None) or ""
                satirlar_orm = list(f.satirlar or [])
            elif belge_tipi == "alis_faturasi":
                from database.models.alis_faturasi import AlisFaturasi

                f = session.scalar(
                    select(AlisFaturasi)
                    .where(AlisFaturasi.id == fatura_id)
                    .options(selectinload(AlisFaturasi.satirlar))
                )
                if f is None:
                    return {"satirlar": [], "uyari": "Bu faturaya ait ürün detayı bulunamadı"}
                if cari_id and int(f.cari_id) != int(cari_id):
                    return {"satirlar": [], "uyari": "Bu faturaya ait ürün detayı bulunamadı"}
                belge_no, durum, para = f.fatura_no, f.durum or "", f.para_birimi or "TRY"
                depo_adi = getattr(f, "depo", None) or ""
                satirlar_orm = list(f.satirlar or [])
            elif belge_tipi == "satis_iade":
                from database.models.satis_iade_faturasi import SatisIadeFaturasi

                f = session.scalar(
                    select(SatisIadeFaturasi)
                    .where(SatisIadeFaturasi.id == fatura_id)
                    .options(selectinload(SatisIadeFaturasi.satirlar))
                )
                if f is None:
                    return {"satirlar": [], "uyari": "Bu faturaya ait ürün detayı bulunamadı"}
                if cari_id and int(f.cari_id) != int(cari_id):
                    return {"satirlar": [], "uyari": "Bu faturaya ait ürün detayı bulunamadı"}
                belge_no, durum, para = f.iade_no, f.durum or "", f.para_birimi or "TRY"
                depo_adi = getattr(f, "depo", None) or ""
                satirlar_orm = list(f.satirlar or [])
            elif belge_tipi == "alis_iade":
                from database.models.alis_iade_faturasi import AlisIadeFaturasi

                f = session.scalar(
                    select(AlisIadeFaturasi)
                    .where(AlisIadeFaturasi.id == fatura_id)
                    .options(selectinload(AlisIadeFaturasi.satirlar))
                )
                if f is None:
                    return {"satirlar": [], "uyari": "Bu faturaya ait ürün detayı bulunamadı"}
                if cari_id and int(f.cari_id) != int(cari_id):
                    return {"satirlar": [], "uyari": "Bu faturaya ait ürün detayı bulunamadı"}
                belge_no, durum, para = f.iade_no, f.durum or "", f.para_birimi or "TRY"
                depo_adi = getattr(f, "depo", None) or ""
                satirlar_orm = list(f.satirlar or [])
            else:
                return {"satirlar": [], "uyari": "Bu faturaya ait ürün detayı bulunamadı"}

            # Stok hareketleri — gerçek kayıt (belge_no)
            from database.models.stok import StokHareketi, StokKarti, StokLotu, Depo

            stok_hareketleri = list(
                session.scalars(
                    select(StokHareketi).where(StokHareketi.belge_no == belge_no)
                ).all()
            )
            # stok_id → toplam miktar + türler
            stok_ozet: dict[int, dict[str, Any]] = {}
            for sh in stok_hareketleri:
                if (durum or "").upper() == "İPTAL" and "İPTAL" in (sh.hareket_turu or "").upper():
                    continue
                oz = stok_ozet.setdefault(
                    int(sh.stok_id),
                    {"miktar": Decimal("0"), "turler": set(), "lotlar": []},
                )
                oz["miktar"] += Decimal(str(sh.miktar or 0))
                oz["turler"].add(sh.hareket_turu or "")
                if sh.lot_id:
                    lot = session.get(StokLotu, sh.lot_id)
                    if lot and getattr(lot, "lot_no", None):
                        oz["lotlar"].append(str(lot.lot_no))

            kod_to_stok_id: dict[str, int] = {}
            kodlar = {(getattr(s, "urun_kodu", None) or "").strip() for s in satirlar_orm}
            kodlar.discard("")
            if kodlar:
                for sk in session.scalars(
                    select(StokKarti).where(StokKarti.stok_kodu.in_(list(kodlar)))
                ):
                    kod_to_stok_id[sk.stok_kodu] = int(sk.id)

            depo_map: dict[int, str] = {}
            if stok_hareketleri:
                for d in session.scalars(
                    select(Depo).where(
                        Depo.id.in_({int(h.depo_id) for h in stok_hareketleri})
                    )
                ):
                    depo_map[int(d.id)] = d.ad or ""

            yonu_etiket = _STOK_YONU_ETIKET.get(belge_tipi, "")
            iptal = (durum or "").upper() in ("İPTAL", "IPTAL")
            taslak = (durum or "").upper() in ("TASLAK", "AÇIK") and not stok_hareketleri
            # AÇIK onaylı olabilir — stok yoksa bilgi
            stok_yok_bilgi = ""
            if iptal:
                stok_yok_bilgi = "İptal"
            elif not stok_hareketleri:
                stok_yok_bilgi = "Stok hareketi henüz oluşmadı"

            sonuc_satirlar: list[dict[str, Any]] = []
            for sira, satir in enumerate(satirlar_orm, start=1):
                miktar = Decimal(str(getattr(satir, "miktar", 0) or 0))
                fiyat = Decimal(str(getattr(satir, "birim_fiyat", 0) or 0))
                isk1 = getattr(satir, "iskonto_orani", 0) or 0
                isk2 = getattr(satir, "iskonto_orani_2", 0) or 0
                isk3 = getattr(satir, "iskonto_orani_3", 0) or 0
                kdv_o = Decimal(str(getattr(satir, "kdv_orani", 0) or 0))
                net = getattr(satir, "tl_tutar", None)
                if net is None or Decimal(str(net or 0)) == 0:
                    net = _satir_net(miktar, fiyat, isk1, isk2, isk3)
                else:
                    net = Decimal(str(net))
                kdv_tutar = _kurus(net * kdv_o / Decimal("100"))
                brut = _kurus(net + kdv_tutar)
                isk_metin = f"{float(isk1):g}"
                if Decimal(str(isk2 or 0)) or Decimal(str(isk3 or 0)):
                    isk_metin = "+".join(
                        f"{float(x):g}" for x in (isk1, isk2, isk3) if Decimal(str(x or 0))
                    )

                kod = (getattr(satir, "urun_kodu", None) or "").strip()
                sid = kod_to_stok_id.get(kod)
                stok_miktar = None
                stok_tur = ""
                lot_stok = ""
                if sid and sid in stok_ozet:
                    stok_miktar = stok_ozet[sid]["miktar"]
                    stok_tur = ", ".join(sorted(stok_ozet[sid]["turler"]))
                    lot_stok = ", ".join(stok_ozet[sid]["lotlar"][:3])

                lot = (
                    getattr(satir, "lot_no", None)
                    or getattr(satir, "lot_cikisi", None)
                    or getattr(satir, "lot_girisi", None)
                    or lot_stok
                    or ""
                )

                yon = yonu_etiket
                if stok_tur:
                    # Gerçek hareket türünü göster (tahmin yazma)
                    yon = stok_tur
                if iptal:
                    yon = "İptal"
                elif stok_yok_bilgi and not stok_hareketleri:
                    yon = stok_yok_bilgi

                uyari_fark = ""
                if stok_miktar is not None and abs(stok_miktar - miktar) > Decimal("0.0001"):
                    uyari_fark = (
                        f"Fatura: {_miktar_goster(miktar)} / "
                        f"Stok: {_miktar_goster(stok_miktar)} / "
                        f"Fark: {_miktar_goster(stok_miktar - miktar)}"
                    )

                sonuc_satirlar.append(
                    {
                        "sira": sira,
                        "urun_kodu": kod,
                        "urun_adi": getattr(satir, "urun_adi", "") or "",
                        "aciklama": (getattr(satir, "aciklama", None) or "")[:80],
                        "miktar": miktar,
                        "miktar_goster": _miktar_goster(miktar),
                        "birim": getattr(satir, "birim", "") or "",
                        "depo": depo_adi,
                        "lot": str(lot or "")[:40],
                        "birim_fiyat": fiyat,
                        "birim_fiyat_goster": _para(fiyat),
                        "iskonto": isk_metin,
                        "kdv_orani": kdv_o,
                        "kdv_orani_goster": f"%{float(kdv_o):g}",
                        "net_tutar": net,
                        "net_goster": _para(net),
                        "kdv_tutar": kdv_tutar,
                        "kdv_goster": _para(kdv_tutar),
                        "brut_tutar": brut,
                        "brut_goster": _para(brut),
                        "para_birimi": para,
                        "stok_yonu": yon,
                        "stok_fark_uyari": uyari_fark,
                        "iade_miktar": "",
                    }
                )

            return {
                "satirlar": sonuc_satirlar,
                "belge_no": belge_no,
                "durum": durum,
                "fatura_id": fatura_id,
                "belge_tipi": belge_tipi,
                "stok_yonu_etiket": yonu_etiket,
                "uyari": (
                    "Bu faturaya ait ürün detayı bulunamadı"
                    if not sonuc_satirlar
                    else ""
                ),
            }
