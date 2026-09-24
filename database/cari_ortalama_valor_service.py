"""Çift yönlü cari ortalama valör hesabı (borç / alacak bakiyesi).

Salt okunur: cari hareket yazmaz.
Net bakiye işareti: borç − alacak (pozitif → Borçlu, negatif → Alacaklı).
"""

from __future__ import annotations

import logging
from datetime import date
from decimal import Decimal, ROUND_HALF_UP
from typing import Any

from sqlalchemy import select

from database.database import get_session
from database.models.cari import Cari, CariIslem, SatisHareketi

logger = logging.getLogger("cari_ortalama_valor")

KURUS = Decimal("0.01")
ZERO = Decimal("0")


def _d(deger) -> Decimal:
    if deger is None:
        return ZERO
    if isinstance(deger, Decimal):
        return deger
    try:
        return Decimal(str(deger))
    except Exception:
        return ZERO


def _kurus(tutar) -> Decimal:
    return _d(tutar).quantize(KURUS, rounding=ROUND_HALF_UP)


def _yon_etiket(bakiye: Decimal) -> tuple[str, str, str]:
    """(bakiye_yonu, valor_turu, bakiye_durumu_ui)."""
    if bakiye > 0:
        return "BORCLU", "BORC", "Borçlu"
    if bakiye < 0:
        return "ALACAKLI", "ALACAK", "Alacaklı"
    return "KAPALI", "YOK", "Kapalı"


def _valor_turu_etiket(valor_turu: str) -> str:
    if valor_turu == "BORC":
        return "Borç Valörü"
    if valor_turu == "ALACAK":
        return "Alacak Valörü"
    return "Valör Yok"


def _ortalama_tarih_ve_gun(
    dilimler: list[dict[str, Any]], referans: date
) -> tuple[date | None, float, Decimal]:
    """Ağırlıklı ortalama valör tarihi + gün (gün = referans − vade; mevcut borç yolu)."""
    from database.cari_service import CariService

    toplam = ZERO
    ord_agirlik = ZERO
    for d in dilimler:
        tutar = _kurus(d.get("tutar"))
        if tutar <= 0:
            continue
        vade = (
            d.get("borc_vadesi")
            or d.get("alacak_vadesi")
            or d.get("vade")
        )
        if vade is None:
            continue
        if not isinstance(vade, date):
            continue
        toplam += tutar
        ord_agirlik += tutar * Decimal(vade.toordinal())

    if toplam <= 0:
        return None, 0.0, ZERO

    avg_ord = int((ord_agirlik / toplam).quantize(Decimal("1"), rounding=ROUND_HALF_UP))
    ortalama_tarih = date.fromordinal(avg_ord)
    gun = CariService._agirlikli_gun_ortalama(dilimler)
    return ortalama_tarih, float(gun), toplam


def _bos_sonuc(
    bakiye: Decimal,
    *,
    uyari: str | None = None,
    sebep: str | None = None,
) -> dict[str, Any]:
    yon, tur, durum = _yon_etiket(bakiye)
    return {
        "bakiye": _kurus(bakiye),
        "bakiye_yonu": yon,
        "bakiye_durumu": durum,
        "valor_turu": tur,
        "valor_turu_etiket": _valor_turu_etiket(tur),
        "ortalama_valor_tarihi": None,
        "ortalama_valor_gun": 0.0,
        "toplam_acik_tutar": ZERO,
        "acik_kalemler": [],
        "uyari": uyari,
        "hesaplama_sebep": sebep,
    }


def fifo_valor_paketi_hesapla(
    hareketler: list[SatisHareketi],
    islemler: list[CariIslem],
    *,
    cari_turu: str | None = None,
    vade_harita: dict[str, date] | None = None,
    referans: date | None = None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    """FIFO: (tam_kapanan_borç, açık_borç, kapanan_dilimler, açık_alacak).

    Borç kuyruğu ve eşleştirme mevcut ``CariService._fifo_valor_dilimleri`` ile aynıdır;
    ek olarak eşleşmeyen alacak dilimleri döner.
    """
    from database.cari_service import CariService

    bugun = referans or date.today()
    vade_harita = vade_harita or {}

    # Mevcut borç FIFO sırası: tarih, id (borç sonuçları değişmesin).
    # Aynı tarih/id çakışmasında belge_no ile deterministik kırılım.
    hareketler_sirali = sorted(
        hareketler,
        key=lambda h: (
            h.satis_tarihi or date.min,
            int(getattr(h, "id", 0) or 0),
            h.belge_no or "",
        ),
    )
    islemler_sirali = sorted(
        islemler,
        key=lambda i: (
            i.tarih or date.min,
            int(getattr(i, "id", 0) or 0),
            i.belge_no or "",
        ),
    )

    # [vade, belge_tarih, kalan, orijinal, belge_no, son_odeme_tarihi]
    kuyruk: list[list] = []
    for h in hareketler_sirali:
        tutar = _kurus(h.satis_tutari)
        if tutar <= 0:
            continue
        no = h.belge_no or ""
        if no.startswith(CariService._VALOR_BORC_HARIC_ONEK):
            continue
        vade = CariService._hareket_vade(h, vade_harita)
        kuyruk.append([vade, h.satis_tarihi, tutar, tutar, no, None])

    kapanan_dilimler: list[dict[str, Any]] = []
    acik_alacak: list[dict[str, Any]] = []
    tedarikci = (cari_turu or "").casefold().startswith("tedarik")

    if kuyruk or islemler_sirali:
        for islem in islemler_sirali:
            kalan_odeme = CariService._odeme_borc_dusurur_mu(islem, tedarikci)
            if kalan_odeme <= 0:
                continue
            kalan_odeme = _kurus(kalan_odeme)
            for dilim_satir in kuyruk:
                if kalan_odeme <= 0:
                    break
                vade, belge_tarih, kalan_dilim, _orj, borc_no, _son = dilim_satir
                if kalan_dilim <= 0:
                    continue
                if belge_tarih and islem.tarih and belge_tarih > islem.tarih:
                    continue
                dilim = min(kalan_dilim, kalan_odeme)
                dilim = _kurus(dilim)
                dilim_satir[2] = _kurus(kalan_dilim - dilim)
                dilim_satir[5] = islem.tarih
                kapanan_dilimler.append(
                    {
                        "odeme_belge_no": islem.belge_no,
                        "odeme_tarihi": islem.tarih,
                        "borc_belge_no": borc_no,
                        "borc_tarihi": belge_tarih,
                        "borc_vadesi": vade,
                        "tutar": dilim,
                        "gun": (islem.tarih - vade).days if vade and islem.tarih else 0,
                    }
                )
                kalan_odeme = _kurus(kalan_odeme - dilim)

            # Eşleşmeyen alacak dilimi (açık alacak)
            if kalan_odeme > 0:
                vade_a = islem.tarih or bugun
                acik_alacak.append(
                    {
                        "alacak_belge_no": islem.belge_no,
                        "alacak_tarihi": islem.tarih,
                        "alacak_vadesi": vade_a,
                        "tutar": kalan_odeme,
                        "gun": (bugun - vade_a).days,
                        "yon": "ALACAK",
                    }
                )

    kapanan: list[dict[str, Any]] = []
    acik_borc: list[dict[str, Any]] = []
    for vade, belge_tarih, kalan_dilim, orijinal, borc_no, son_odeme in kuyruk:
        if kalan_dilim <= 0 and son_odeme is not None:
            kapanan.append(
                {
                    "borc_belge_no": borc_no,
                    "borc_tarihi": belge_tarih,
                    "borc_vadesi": vade,
                    "kapanma_tarihi": son_odeme,
                    "tutar": orijinal,
                    "gun": (son_odeme - vade).days if vade and son_odeme else 0,
                    "yon": "BORC",
                }
            )
        elif kalan_dilim > 0:
            acik_borc.append(
                {
                    "borc_belge_no": borc_no,
                    "borc_tarihi": belge_tarih,
                    "borc_vadesi": vade,
                    "tutar": kalan_dilim,
                    "gun": (bugun - vade).days if vade else 0,
                    "yon": "BORC",
                }
            )
    return kapanan, acik_borc, kapanan_dilimler, acik_alacak


def _sonuc_olustur(
    bakiye: Decimal,
    acik_borc: list[dict[str, Any]],
    acik_alacak: list[dict[str, Any]],
    referans: date,
) -> dict[str, Any]:
    yon, tur, durum = _yon_etiket(bakiye)
    if tur == "YOK":
        return _bos_sonuc(bakiye, sebep="Bakiye kapalı")

    if tur == "BORC":
        dilimler = [d for d in acik_borc if _kurus(d.get("tutar")) > 0]
        if not dilimler:
            return _bos_sonuc(
                bakiye,
                sebep="Açık hareket yok",
                uyari="Borç bakiyesi var ancak açık borç kalemi bulunamadı.",
            )
    else:
        dilimler = [d for d in acik_alacak if _kurus(d.get("tutar")) > 0]
        if not dilimler:
            return _bos_sonuc(
                bakiye,
                sebep="Açık hareket yok",
                uyari="Alacak bakiyesi var ancak açık alacak kalemi bulunamadı.",
            )

    # Tarih eksik kalemleri ayıkla
    gecerli: list[dict[str, Any]] = []
    for d in dilimler:
        vade = d.get("borc_vadesi") or d.get("alacak_vadesi") or d.get("vade")
        if vade is None:
            continue
        gecerli.append(d)
    if not gecerli:
        return _bos_sonuc(bakiye, sebep="Tarih eksik")

    ortalama_tarih, gun, toplam_acik = _ortalama_tarih_ve_gun(gecerli, referans)
    uyari = None
    fark = abs(_kurus(abs(bakiye)) - _kurus(toplam_acik))
    if fark > KURUS:
        uyari = (
            f"Bakiye ({_kurus(bakiye)}) ile açık kalem toplamı ({_kurus(toplam_acik)}) "
            f"arasında {fark} TL fark var."
        )
        logger.warning(
            "ortalama_valor bakiye/acik uyumsuzlugu: bakiye=%s acik=%s fark=%s",
            bakiye,
            toplam_acik,
            fark,
        )

    return {
        "bakiye": _kurus(bakiye),
        "bakiye_yonu": yon,
        "bakiye_durumu": durum,
        "valor_turu": tur,
        "valor_turu_etiket": _valor_turu_etiket(tur),
        "ortalama_valor_tarihi": ortalama_tarih,
        "ortalama_valor_gun": gun,
        "toplam_acik_tutar": _kurus(toplam_acik),
        "acik_kalemler": gecerli,
        "uyari": uyari,
        "hesaplama_sebep": None,
    }


def calculate_account_average_value_date(
    cari_id: int,
    *,
    rapor_tarihi: date | None = None,
    firma_scoped: bool = True,
    session=None,
    cari_turu: str | None = None,
    bakiye: Decimal | None = None,
    fifo_paketi: tuple | None = None,
) -> dict[str, Any]:
    """Tek cari için çift yönlü ortalama valör.

    Returns dict: bakiye, bakiye_yonu, valor_turu, ortalama_valor_tarihi,
    ortalama_valor_gun, toplam_acik_tutar, acik_kalemler, uyari, ...
    """
    from database.cari_bakiye_service import net_bakiye
    from database.cari_service import CariService

    _ = firma_scoped  # şirket DB oturumu zaten firma kapsamlı
    referans = rapor_tarihi or date.today()
    kendi_session = session is None

    def _calistir(sess) -> dict[str, Any]:
        nonlocal cari_turu, bakiye, fifo_paketi
        cari = sess.get(Cari, int(cari_id))
        if cari is None:
            return _bos_sonuc(ZERO, sebep="Cari bulunamadı")
        if cari_turu is None:
            cari_turu = cari.cari_turu

        if bakiye is None:
            nb = net_bakiye(int(cari_id), session=sess)
            bakiye_l = _kurus(nb["bakiye"])
        else:
            bakiye_l = _kurus(bakiye)

        if fifo_paketi is None:
            hareketler = list(
                sess.scalars(
                    select(SatisHareketi).where(SatisHareketi.cari_id == int(cari_id))
                ).all()
            )
            islemler = list(
                sess.scalars(
                    select(CariIslem).where(CariIslem.cari_id == int(cari_id))
                ).all()
            )
            vade_harita = CariService._borc_vade_haritasi(
                sess, [h.belge_no for h in hareketler]
            )
            fifo_paketi = fifo_valor_paketi_hesapla(
                hareketler,
                islemler,
                cari_turu=cari_turu,
                vade_harita=vade_harita,
                referans=referans,
            )
        # 3 veya 4 elemanlı paket uyumu
        if len(fifo_paketi) >= 4:
            _tam, acik_borc, _dilimler, acik_alacak = (
                fifo_paketi[0],
                fifo_paketi[1],
                fifo_paketi[2],
                fifo_paketi[3],
            )
        else:
            _tam, acik_borc, _dilimler = fifo_paketi[0], fifo_paketi[1], fifo_paketi[2]
            acik_alacak = []

        return _sonuc_olustur(bakiye_l, acik_borc, acik_alacak, referans)

    if kendi_session:
        with get_session() as sess:
            return _calistir(sess)
    return _calistir(session)


def calculate_accounts_average_value_date_bulk(
    cariler: list[Cari],
    session,
    *,
    rapor_tarihi: date | None = None,
    hareket_by: dict[int, list[SatisHareketi]] | None = None,
    islem_by: dict[int, list[CariIslem]] | None = None,
    bakiyeler: dict[int, Decimal] | None = None,
) -> dict[int, dict[str, Any]]:
    """Liste için N+1'siz toplu ortalama valör."""
    from database.cari_bakiye_service import net_bakiye
    from database.cari_service import CariService

    if not cariler:
        return {}
    referans = rapor_tarihi or date.today()
    ids = [int(c.id) for c in cariler]

    if hareket_by is None:
        hareketler = list(
            session.scalars(
                select(SatisHareketi).where(SatisHareketi.cari_id.in_(ids))
            ).all()
        )
        hareket_by = {i: [] for i in ids}
        for h in hareketler:
            hareket_by.setdefault(int(h.cari_id), []).append(h)
    if islem_by is None:
        islemler = list(
            session.scalars(select(CariIslem).where(CariIslem.cari_id.in_(ids))).all()
        )
        islem_by = {i: [] for i in ids}
        for i in islemler:
            islem_by.setdefault(int(i.cari_id), []).append(i)

    tum_belge = []
    for cid in ids:
        for h in hareket_by.get(cid, []):
            tum_belge.append(h.belge_no)
    vade_harita = CariService._borc_vade_haritasi(session, tum_belge)

    sonuclar: dict[int, dict[str, Any]] = {}
    for cari in cariler:
        cid = int(cari.id)
        if bakiyeler is not None and cid in bakiyeler:
            bakiye = _kurus(bakiyeler[cid])
        else:
            bakiye = _kurus(net_bakiye(cid, session=session)["bakiye"])
        paket = fifo_valor_paketi_hesapla(
            hareket_by.get(cid, []),
            islem_by.get(cid, []),
            cari_turu=cari.cari_turu,
            vade_harita=vade_harita,
            referans=referans,
        )
        sonuclar[cid] = _sonuc_olustur(bakiye, paket[1], paket[3], referans)
    return sonuclar
