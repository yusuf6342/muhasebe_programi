"""Alınan Sipariş — ekran bilgilendirme: Depolar Toplamı + Stok Durumu.

Fiziksel stok: aynı firma DB'sindeki **tüm depoların** net lot toplamı (seçili depoya
daralmaz). Kullanılabilir: fiziksel − diğer açık satış siparişleri (bu sipariş hariç;
rezervasyon modeli yok — stok raporlarıyla aynı kural).

Durum: ``Var`` veya ``N eksik`` (Kısmi/Yok yerine). Aynı ürün satırları stoku sırayla
paylaşır. Stok/cari hareket üretmez. PDF/yazıcıya taşınmaz.
"""
from __future__ import annotations

from decimal import Decimal, ROUND_HALF_UP
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import selectinload

from database.database import get_session
from database.models.stok import StokHareketi, StokKarti, StokLotu

DURUM_VAR = "Var"
DURUM_KISMI = "Kısmi"  # geriye dönük; yeni etiketler «N eksik»
DURUM_YOK = "Yok"
DURUM_BOS = ""

RENK_UYARI_BG = "#FFE4E4"
RENK_UYARI_FG = "#7F1D1D"

SIFIR = Decimal("0")
_MIKTAR_Q = Decimal("0.0001")


def _d(v) -> Decimal:
    try:
        return Decimal(str(v or 0))
    except Exception:
        return SIFIR


def _miktar_metin(v: Decimal) -> str:
    """Ondalıkları koru; Türkçe ondalık ayracı (2,5)."""
    q = _d(v).quantize(_MIKTAR_Q, rounding=ROUND_HALF_UP)
    s = f"{q:f}".rstrip("0").rstrip(".")
    if not s:
        s = "0"
    return s.replace(".", ",")


def eksik_etiketi(eksik: Decimal) -> str:
    e = _d(eksik)
    if e <= 0:
        return DURUM_VAR
    return f"{_miktar_metin(e)} eksik"


def durum_etiketi(s_temel: Decimal, q_temel: Decimal) -> str:
    """S = kullanılabilir stok (temel), Q = karşılanacak (temel)."""
    if q_temel is None or _d(q_temel) <= 0:
        return DURUM_BOS
    q = _d(q_temel)
    s = max(_d(s_temel), SIFIR)
    return eksik_etiketi(q - s)


def uyari_durumu_mu(durum: str | None) -> bool:
    d = (durum or "").strip()
    if not d:
        return False
    if d in (DURUM_KISMI, DURUM_YOK):
        return True
    return "eksik" in d.casefold()


def net_lot_toplamlari(urun_kodlari: list[str] | tuple[str, ...] | set[str]) -> dict[str, Decimal]:
    """Ürün kodu → tüm depolardaki net lot kalan toplamı (tek sorgu)."""
    kodlar = sorted({(k or "").strip() for k in (urun_kodlari or []) if (k or "").strip()})
    if not kodlar:
        return {}
    with get_session() as session:
        rows = session.execute(
            select(
                StokKarti.stok_kodu,
                func.coalesce(func.sum(StokLotu.kalan_miktar), 0),
            )
            .select_from(StokKarti)
            .outerjoin(StokLotu, StokLotu.stok_id == StokKarti.id)
            .where(StokKarti.stok_kodu.in_(kodlar))
            .group_by(StokKarti.stok_kodu)
        ).all()
        sonuc = {str(kod): _d(top) for kod, top in rows}
        for kod in kodlar:
            sonuc.setdefault(kod, SIFIR)
        return sonuc


def hareket_imza(urun_kodlari: list[str] | tuple[str, ...] | set[str]) -> tuple[int, str]:
    """İzlenen ürünler için hafif DB imzası: (max hareket id, net lot toplamı)."""
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
        net = session.scalar(
            select(func.coalesce(func.sum(StokLotu.kalan_miktar), 0)).where(
                StokLotu.stok_id.in_(ids)
            )
        )
        return (int(max_hid or 0), str(_d(net)))


def _temel_miktar_kart(veri: dict[str, Any], kart: Any | None) -> Decimal:
    from database.stok_service import StokService

    miktar = _d(veri.get("miktar"))
    if miktar <= 0:
        return SIFIR
    if kart is None:
        return miktar
    birim = (veri.get("birim") or getattr(kart, "birim", None) or "Adet").strip() or "Adet"
    try:
        carpan = StokService.birim_carpani_kesin(kart, birim)
    except Exception:
        carpan = Decimal("1")
    return (miktar * _d(carpan)).quantize(Decimal("0.000001"))


def _karsilanacak_temel(veri: dict[str, Any], kart: Any | None) -> Decimal:
    """Kalan sevk ihtiyacı (temel birim): max(0, miktar − max(irsaliye, fatura))."""
    from database.stok_service import StokService

    miktar = _d(veri.get("miktar"))
    sevk = max(
        _d(veri.get("irsaliyelenen")),
        _d(veri.get("irsaliyelenen_miktar")),
        _d(veri.get("faturalanan")),
        _d(veri.get("faturalanan_miktar")),
    )
    kalan = miktar - sevk
    if kalan <= 0:
        return SIFIR
    if kart is None:
        return kalan
    birim = (veri.get("birim") or getattr(kart, "birim", None) or "Adet").strip() or "Adet"
    try:
        carpan = StokService.birim_carpani_kesin(kart, birim)
    except Exception:
        carpan = Decimal("1")
    return (kalan * _d(carpan)).quantize(Decimal("0.000001"))


def _temelden_satir_birimine(temel: Decimal, veri: dict[str, Any], kart: Any | None) -> Decimal:
    from database.stok_service import StokService

    if kart is None:
        return _d(temel)
    birim = (veri.get("birim") or getattr(kart, "birim", None) or "Adet").strip() or "Adet"
    try:
        carpan = _d(StokService.birim_carpani_kesin(kart, birim))
    except Exception:
        carpan = Decimal("1")
    if carpan <= 0:
        return _d(temel)
    return (_d(temel) / carpan).quantize(_MIKTAR_Q, rounding=ROUND_HALF_UP)


def _bekleyen_satis_temel(
    session,
    kod_kart: dict[str, Any],
    *,
    siparis_id: int | None,
) -> dict[str, Decimal]:
    """Ürün kodu → diğer açık satış siparişlerinin açık miktarı (temel). Bu sipariş hariç."""
    from database.models.satis_siparisi import SatisSiparisi, SatisSiparisiSatiri
    from database.stok_service import StokService
    from database.stok_uyari_service import SATIS_SIPARIS_HARIC

    q = (
        select(SatisSiparisiSatiri, SatisSiparisi.id)
        .join(SatisSiparisi, SatisSiparisi.id == SatisSiparisiSatiri.siparis_id)
        .where(SatisSiparisi.durum.notin_(SATIS_SIPARIS_HARIC))
    )
    if siparis_id is not None:
        q = q.where(SatisSiparisi.id != int(siparis_id))
    sonuc: dict[str, Decimal] = {}
    for sat, _sid in session.execute(q).all():
        kod = (sat.urun_kodu or "").strip()
        if not kod or kod not in kod_kart:
            continue
        kart = kod_kart[kod]
        acik = _d(sat.miktar) - max(_d(sat.irsaliyelenen_miktar), _d(sat.faturalanan_miktar))
        if acik <= 0:
            continue
        try:
            carpan = _d(StokService.birim_carpani_kesin(kart, sat.birim or kart.birim))
        except Exception:
            carpan = Decimal("1")
        sonuc[kod] = sonuc.get(kod, SIFIR) + acik * carpan
    return sonuc


def satir_stok_bilgileri(
    satirlar: list[dict[str, Any]],
    *,
    stok_map: dict[str, Decimal] | None = None,
    siparis_id: int | None = None,
) -> list[dict[str, Any]]:
    """Her satır için durum + depolar toplamı (satır biriminde).

    Aynı ürün stoku satır sırasıyla paylaşılır. ``stok_map`` verilirse DB lot
    sorgusu atlanır (test); bekleyen yine DB'den okunur — testte siparis_id=None
    ve boş bekleyen için stok_map yeter.
    """
    if not satirlar:
        return []
    kodlar = sorted(
        {(v.get("urun_kodu") or "").strip() for v in satirlar if (v.get("urun_kodu") or "").strip()}
    )
    with get_session() as session:
        kartlar = {
            k.stok_kodu: k
            for k in session.scalars(
                select(StokKarti)
                .where(StokKarti.stok_kodu.in_(kodlar))
                .options(selectinload(StokKarti.birimler))
            ).all()
        } if kodlar else {}

        if stok_map is not None:
            fiziksel = {k: _d(v) for k, v in stok_map.items()}
            for kod in kodlar:
                fiziksel.setdefault(kod, SIFIR)
            bekleyen = {kod: SIFIR for kod in kodlar}
        else:
            fiziksel = {kod: SIFIR for kod in kodlar}
            if kartlar:
                ids = [int(k.id) for k in kartlar.values()]
                id_to_kod = {int(k.id): k.stok_kodu for k in kartlar.values()}
                for sid, top in session.execute(
                    select(
                        StokLotu.stok_id,
                        func.coalesce(func.sum(StokLotu.kalan_miktar), 0),
                    )
                    .where(StokLotu.stok_id.in_(ids))
                    .group_by(StokLotu.stok_id)
                ).all():
                    kod = id_to_kod.get(int(sid))
                    if kod:
                        fiziksel[kod] = _d(top)
            bekleyen = _bekleyen_satis_temel(session, kartlar, siparis_id=siparis_id)

        kullanilabilir0: dict[str, Decimal] = {}
        kalan_kul: dict[str, Decimal] = {}
        for kod in kodlar:
            fiz = fiziksel.get(kod, SIFIR)
            bek = bekleyen.get(kod, SIFIR)
            ku = fiz - bek
            kullanilabilir0[kod] = ku
            kalan_kul[kod] = ku

        sonuc: list[dict[str, Any]] = []
        for veri in satirlar:
            kod = (veri.get("urun_kodu") or "").strip()
            kart = kartlar.get(kod)
            q = _karsilanacak_temel(veri, kart) if kod else SIFIR
            fiz = fiziksel.get(kod, SIFIR) if kod else SIFIR
            ku0 = kullanilabilir0.get(kod, SIFIR) if kod else SIFIR
            toplam_goster = _temelden_satir_birimine(fiz, veri, kart) if kod else SIFIR
            toplam_metin = _miktar_metin(toplam_goster) if kod else ""

            if not kod or q <= 0:
                sonuc.append(
                    {
                        "durum": DURUM_BOS,
                        "depolar_toplami": toplam_metin,
                        "depolar_toplami_deger": toplam_goster,
                        "fiziksel_temel": fiz,
                        "kullanilabilir_temel": ku0,
                        "aciklama": "",
                    }
                )
                continue

            kullan = max(kalan_kul.get(kod, SIFIR), SIFIR)
            alinan = min(q, kullan)
            eksik = q - alinan
            kalan_kul[kod] = kullan - alinan
            durum = eksik_etiketi(eksik)

            aciklama = ""
            if fiz != ku0:
                aciklama = (
                    f"Fiziksel {_miktar_metin(_temelden_satir_birimine(fiz, veri, kart))} · "
                    f"kullanılabilir {_miktar_metin(_temelden_satir_birimine(ku0, veri, kart))} "
                    f"(diğer siparişler düşüldü; bu sipariş iki kez düşülmedi)"
                )

            sonuc.append(
                {
                    "durum": durum,
                    "depolar_toplami": toplam_metin,
                    "depolar_toplami_deger": toplam_goster,
                    "fiziksel_temel": fiz,
                    "kullanilabilir_temel": ku0,
                    "aciklama": aciklama,
                }
            )
        return sonuc


def satir_durumlari(
    satirlar: list[dict[str, Any]],
    *,
    stok_map: dict[str, Decimal] | None = None,
    siparis_id: int | None = None,
) -> list[str]:
    """Geriye dönük: yalnız durum etiketleri."""
    return [
        b["durum"]
        for b in satir_stok_bilgileri(
            satirlar, stok_map=stok_map, siparis_id=siparis_id
        )
    ]
