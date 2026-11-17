"""Hızlı Satış / Satış Faturası — stok yetersizliği satır rengi (yalnız ekran).

Mevcut depo + pozitif lot + birim dönüşümü kurallarını kullanır.
Stok hareketi / kayıt / onay / PDF etkilemez. Sorgu hatasında None döner
(yanlış kırmızı üretmez).
"""
from __future__ import annotations

from decimal import Decimal
from typing import Any, Iterable

from sqlalchemy import func, select
from sqlalchemy.orm import selectinload

from database.database import get_session
from database.hizli_satis_service import depo_bul
from database.models.stok import Depo, StokHareketi, StokKarti, StokLotu
from database.stok_service import BirimDonusumHatasi, StokService

# Açık kırmızı satır zemini (ekran); çıktılara taşınmaz
RENK_UYARI_BG = "#FFE4E4"
RENK_UYARI_FG = "#7F1D1D"
RENK_SECIM_BG = "#B71C1C"
RENK_SECIM_FG = "#FFFFFF"

TAG_YETERSIZ = "stok_yetersiz"


def etiketlere_yetersiz_ekle(
    mevcut: Iterable[str] | None,
    yetersiz: bool,
) -> tuple[str, ...]:
    """Tk Treeview ilk renkli etiketi kullanır — stok_yetersiz her zaman başta olmalı."""
    etiketler = [t for t in (mevcut or ()) if t and t != TAG_YETERSIZ]
    if yetersiz:
        return (TAG_YETERSIZ, *etiketler)
    return tuple(etiketler)


def _d(v) -> Decimal:
    try:
        return Decimal(str(v or 0))
    except Exception:
        return Decimal("0")


def _satir_alanlari(ham: Any) -> tuple[str, Decimal, str]:
    """(urun_kodu, miktar, birim)."""
    if hasattr(ham, "stok_kodu"):
        kod = (getattr(ham, "stok_kodu", None) or "").strip()
        miktar = _d(getattr(ham, "miktar", 0))
        birim = (getattr(ham, "birim", None) or "").strip()
        return kod, miktar, birim
    kod = (ham.get("urun_kodu") or ham.get("stok_kodu") or "").strip()
    miktar = _d(ham.get("miktar"))
    birim = (ham.get("birim") or "").strip()
    return kod, miktar, birim


def lotlardan_satis_stok(
    lotlar: Iterable[Any] | None,
    *,
    depo_id: int | None = None,
) -> Decimal:
    """Ekran / uyarı için satış stoğu: depodaki lot neti, negatifse 0.

    Negatif + pozitif lotlar neti sıfırken yalnızca pozitifleri saymak
    (ör. −500 + 500) paneli «STOK YOK» gösterip sepeti yeşil bırakıyordu.
    Onay/FIFO hâlâ pozitif lotlardan çıkar; bu yalnızca görsel tutarlılık.
    """
    toplam = Decimal("0")
    for lot in lotlar or []:
        if depo_id is not None:
            try:
                if int(getattr(lot, "depo_id", 0) or 0) != int(depo_id):
                    continue
            except (TypeError, ValueError):
                continue
        toplam += _d(getattr(lot, "kalan_miktar", 0))
    return toplam if toplam > 0 else Decimal("0")


def depo_pozitif_lot_toplamlari(
    urun_kodlari: Iterable[str],
    depo_adi: str,
) -> dict[str, Decimal]:
    """Ürün kodu → seçili depodaki net lot (negatif net → 0).

    Eski ad korundu; negatif lotların pozitifleri «şişirmesini» engeller.
    Lotu / kartı olmayan kodlar 0. DB hatası yükseltilir (çağıran None işler).
    """
    kodlar = sorted({(k or "").strip() for k in (urun_kodlari or []) if (k or "").strip()})
    depo_adi = (depo_adi or "").strip()
    if not kodlar or not depo_adi:
        return {k: Decimal("0") for k in kodlar}
    with get_session() as session:
        depo_row = depo_bul(session, depo_adi)
        if depo_row is None:
            # Tam ad eşleşmesi (fatura combobox)
            depo_row = session.scalar(
                select(Depo).where(Depo.ad == depo_adi, Depo.aktif.is_(True))
            )
        if depo_row is None:
            return {k: Decimal("0") for k in kodlar}
        rows = session.execute(
            select(
                StokKarti.stok_kodu,
                func.coalesce(func.sum(StokLotu.kalan_miktar), 0),
            )
            .select_from(StokKarti)
            .outerjoin(
                StokLotu,
                (StokLotu.stok_id == StokKarti.id)
                & (StokLotu.depo_id == depo_row.id),
            )
            .where(StokKarti.stok_kodu.in_(kodlar))
            .group_by(StokKarti.stok_kodu)
        ).all()
        sonuc = {str(kod): max(_d(top), Decimal("0")) for kod, top in rows}
        for kod in kodlar:
            sonuc.setdefault(kod, Decimal("0"))
        return sonuc


def hareket_imza_depo(
    urun_kodlari: Iterable[str],
    depo_adi: str | None = None,
) -> tuple[int, str]:
    """İzlenen ürünler (+isteğe bağlı depo) için hafif imza."""
    kodlar = sorted({(k or "").strip() for k in (urun_kodlari or []) if (k or "").strip()})
    if not kodlar:
        return (0, "0")
    with get_session() as session:
        ids = list(
            session.scalars(select(StokKarti.id).where(StokKarti.stok_kodu.in_(kodlar))).all()
        )
        if not ids:
            return (0, "0")
        max_hid = session.scalar(
            select(func.coalesce(func.max(StokHareketi.id), 0)).where(
                StokHareketi.stok_id.in_(ids)
            )
        )
        lot_q = select(func.coalesce(func.sum(StokLotu.kalan_miktar), 0)).where(
            StokLotu.stok_id.in_(ids),
            StokLotu.kalan_miktar > 0,
        )
        depo_adi = (depo_adi or "").strip()
        if depo_adi:
            depo_row = depo_bul(session, depo_adi)
            if depo_row is None:
                depo_row = session.scalar(
                    select(Depo).where(Depo.ad == depo_adi, Depo.aktif.is_(True))
                )
            if depo_row is not None:
                lot_q = lot_q.where(StokLotu.depo_id == depo_row.id)
        net = session.scalar(lot_q)
        return (int(max_hid or 0), str(_d(net)))


def _temel_talep(ham: Any, kart: StokKarti | None) -> Decimal | None:
    """Temel birim talep; birim hatasında None (satırı boyama)."""
    kod, miktar, birim = _satir_alanlari(ham)
    if not kod or miktar <= 0:
        return Decimal("0")
    # Fatura satırında kayıtlı temel_miktar varsa onu kullan
    if isinstance(ham, dict):
        kayitli = ham.get("temel_miktar")
        if kayitli not in (None, ""):
            try:
                t = _d(kayitli)
                return t if t > 0 else Decimal("0")
            except Exception:
                pass
        carpan_kayit = ham.get("birim_carpani")
        if carpan_kayit not in (None, ""):
            try:
                return (miktar * _d(carpan_kayit)).quantize(Decimal("0.000001"))
            except Exception:
                pass
    elif hasattr(ham, "carpan"):
        try:
            c = _d(getattr(ham, "carpan", 1) or 1)
            if c > 0:
                return (miktar * c).quantize(Decimal("0.000001"))
        except Exception:
            pass
    if kart is None:
        return miktar
    birim = birim or (getattr(kart, "birim", None) or "Adet")
    try:
        carpan = StokService.birim_carpani_kesin(kart, birim)
    except BirimDonusumHatasi:
        return None
    except Exception:
        return None
    return (miktar * _d(carpan)).quantize(Decimal("0.000001"))


def yetersiz_satir_indeksleri(
    satirlar: list[Any] | tuple[Any, ...] | None,
    depo_adi: str,
) -> set[int] | None:
    """Depo stokuna göre yetersiz satır indeksleri.

    Aynı ürünün satır talepleri toplanır (mevcut stok kontrolü ile aynı).
    None = sorgu/hesap hatası → mevcut renkleri değiştirme.
    """
    satirlar = list(satirlar or [])
    depo_adi = (depo_adi or "").strip()
    if not satirlar or not depo_adi:
        return set()

    kodlar: set[str] = set()
    for ham in satirlar:
        kod, miktar, _ = _satir_alanlari(ham)
        if kod and miktar > 0:
            kodlar.add(kod)
    if not kodlar:
        return set()

    try:
        stok_map = depo_pozitif_lot_toplamlari(kodlar, depo_adi)
    except Exception:
        return None

    try:
        with get_session() as session:
            kartlar = {
                k.stok_kodu: k
                for k in session.scalars(
                    select(StokKarti)
                    .where(StokKarti.stok_kodu.in_(sorted(kodlar)))
                    .options(selectinload(StokKarti.birimler))
                ).all()
            }
            talepler: dict[str, Decimal] = {}
            satir_talep: list[tuple[int, str, Decimal | None]] = []
            for i, ham in enumerate(satirlar):
                kod, miktar, _ = _satir_alanlari(ham)
                if not kod or miktar <= 0:
                    continue
                talep = _temel_talep(ham, kartlar.get(kod))
                satir_talep.append((i, kod, talep))
                if talep is None:
                    continue
                if talep <= 0:
                    continue
                talepler[kod] = talepler.get(kod, Decimal("0")) + talep
    except Exception:
        return None

    yetersiz_kodlar = {
        kod for kod, talep in talepler.items() if _d(stok_map.get(kod)) < talep
    }
    sonuc: set[int] = set()
    for i, kod, talep in satir_talep:
        if talep is None or talep <= 0:
            continue
        if kod in yetersiz_kodlar:
            sonuc.add(i)
    return sonuc
