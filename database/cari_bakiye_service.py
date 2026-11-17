"""Tek merkezî cari net bakiye hesabı (müşteri listesi + fatura Eski/Yeni).

Resmî yön: net = toplam borç − toplam alacak (CariIslem + çift kayıtsız SatisHareketi).
Taslak / iptal / soft-delete cari hareketleri CariIslem tablosuna yazılmaz; bu servis
yalnızca onaylı/bakiyeye yansıyan kayıtları kullanır.
"""

from __future__ import annotations

import logging
from datetime import date, datetime
from decimal import Decimal, ROUND_HALF_UP
from typing import Any

from sqlalchemy import func, select

from database.database import get_session
from database.models.cari import CariIslem, CariKapatma, SatisHareketi

logger = logging.getLogger("cari_bakiye")

KURUS = Decimal("0.01")

# Tablo varlık kontrolü (inspect) her listelemede tekrarlanmasın
_TABLO_VAR_ONBELLEK: dict[str, bool] = {}


def _tablo_var_mi(session, tablo_adi: str) -> bool:
    ad = (tablo_adi or "").strip()
    if not ad:
        return False
    if ad in _TABLO_VAR_ONBELLEK:
        return _TABLO_VAR_ONBELLEK[ad]
    try:
        from sqlalchemy import inspect as sa_inspect

        var = bool(sa_inspect(session.connection()).has_table(ad))
    except Exception:
        var = False
    _TABLO_VAR_ONBELLEK[ad] = var
    return var

# Defterde SatisHareketi olarak ayrıca gösterilmeyen önekler (CariIslem zaten var)
_DEFTER_ATLA_ONEK = (
    "ODM-", "VRM-", "KKC-", "THS-", "AHV-", "GHV-", "POS-", "BNC-", "KBY-", "KKO-",
    "IPT-", "FZO-", "DVF-",
)


def _d(deger) -> Decimal:
    if deger is None:
        return Decimal("0")
    if isinstance(deger, Decimal):
        return deger
    try:
        return Decimal(str(deger))
    except Exception:
        return Decimal("0")


def _kurus(tutar) -> Decimal:
    return _d(tutar).quantize(KURUS, rounding=ROUND_HALF_UP)


def _satis_hareketi_borc_alacak(
    tutar, kalan, *, defterde_kapanan: Decimal = Decimal("0")
) -> tuple[Decimal, Decimal]:
    """Çift kayıtsız SatisHareketi borç/alacak payı.

    Kapanan (tutar − kalan) alacak yazılır; fakat aynı kapanma CariIslem + CariKapatma
    ile deftere düşmüşse (TMK tahsilat makbuzu vb.) ikinci kez sayılmaz.
    """
    t = _d(tutar)
    k = _d(kalan)
    defterde = max(Decimal("0"), _d(defterde_kapanan))
    if t >= 0:
        kapanan = max(Decimal("0"), t - max(k, Decimal("0")))
        sessiz = max(Decimal("0"), kapanan - defterde)
        alacak_ek = sessiz
        if k < 0 and defterde <= 0:
            # Sessiz fazla tahsilat (defter satırı yok)
            alacak_ek += -k
        return t, alacak_ek
    # t < 0: alış/tedarikçi — alacak = -t (tam tutar).
    # Ödeme borcu yalnız CariIslem (OMK/BNC/OD…) ile netlenir.
    # Kalan düşmüş olsa bile burada "sessiz borc" yazılmaz: aksi halde aynı ödeme
    # hem CI borc hem SH sessiz borc olarak çift sayılır (D2 Yönem/Beyax/ESCAL kanıtı).
    return Decimal("0"), -t


def _defterde_kapanan_toplamlari(
    session, hareket_idler: list[int], islem_belgeleri: set[str]
) -> dict[int, Decimal]:
    """hedef_hareket_id → defterde zaten alacak yazılmış kapanma tutarı.

    1) CariKapatma (kaynak belge CariIslem'de) — klasik açık kalem tahsisi.
    2) Satış faturasına bağlı tahsilat makbuzu (SatisFaturaMakbuzBagi): bazı
       fatura-makbuz yolları kalanı düşürüp CariIslem yazar ama CariKapatma
       üretmez; fatura satırına sessiz alacak basılmasın diye bağ tutarı da
       sayılır (yalnız makbuz belgesi islem_belgeleri'nde ise). Aynı kaynak
       belgede CariKapatma varsa bağ payı tekrar eklenmez.
    """
    ids = [int(i) for i in hareket_idler if i is not None]
    sonuc: dict[int, Decimal] = {}
    if not ids or not islem_belgeleri:
        return sonuc
    has_kapatma = _tablo_var_mi(session, CariKapatma.__tablename__)

    # (hedef_id, kaynak_belge) → kapatma toplamı (bağ ile örtüşme kontrolü)
    kapatma_kaynak: dict[tuple[int, str], Decimal] = {}
    if has_kapatma:
        for bas in range(0, len(ids), 500):
            parca = ids[bas : bas + 500]
            for hid, kaynak, toplam in session.execute(
                select(
                    CariKapatma.hedef_hareket_id,
                    CariKapatma.kaynak_belge_no,
                    func.coalesce(func.sum(CariKapatma.tutar), 0),
                )
                .where(
                    CariKapatma.hedef_hareket_id.in_(parca),
                    CariKapatma.iptal.is_(False),
                    CariKapatma.kaynak_belge_no.in_(list(islem_belgeleri)),
                )
                .group_by(CariKapatma.hedef_hareket_id, CariKapatma.kaynak_belge_no)
            ):
                hid_i = int(hid)
                kaynak_s = (kaynak or "").strip()
                tut = _d(toplam)
                kapatma_kaynak[(hid_i, kaynak_s)] = tut
                sonuc[hid_i] = sonuc.get(hid_i, Decimal("0")) + tut

    try:
        from database.models.finans import KasaMakbuzu, SatisFaturaMakbuzBagi
        from database.models.satis_faturasi import SatisFaturasi

        if not _tablo_var_mi(session, SatisFaturaMakbuzBagi.__tablename__):
            return sonuc
        sh_map = {
            int(hid): (bn or "").strip()
            for hid, bn in session.execute(
                select(SatisHareketi.id, SatisHareketi.belge_no).where(
                    SatisHareketi.id.in_(ids)
                )
            ).all()
            if hid is not None
        }
        fatura_nos = {bn for bn in sh_map.values() if bn}
        if not fatura_nos:
            return sonuc
        fatura_id_to_no = {
            int(f.id): (f.fatura_no or "").strip()
            for f in session.scalars(
                select(SatisFaturasi).where(SatisFaturasi.fatura_no.in_(list(fatura_nos)))
            ).all()
        }
        no_to_sh = {bn: hid for hid, bn in sh_map.items() if bn}
        if not fatura_id_to_no:
            return sonuc
        baglar = list(
            session.scalars(
                select(SatisFaturaMakbuzBagi).where(
                    SatisFaturaMakbuzBagi.fatura_id.in_(list(fatura_id_to_no.keys()))
                )
            ).all()
        )
        if not baglar:
            return sonuc
        makbuzlar = {
            int(m.id): m
            for m in session.scalars(
                select(KasaMakbuzu).where(
                    KasaMakbuzu.id.in_([int(b.makbuz_id) for b in baglar])
                )
            ).all()
        }
        for bag in baglar:
            makbuz = makbuzlar.get(int(bag.makbuz_id))
            if makbuz is None or (makbuz.durum or "").upper() == "İPTAL":
                continue
            belge = (makbuz.belge_no or "").strip()
            if not belge or belge not in islem_belgeleri:
                continue
            fatura_no = fatura_id_to_no.get(int(bag.fatura_id)) or (bag.fatura_no or "").strip()
            hid = no_to_sh.get(fatura_no)
            if hid is None:
                continue
            pay = _d(bag.fatura_kapanan)
            if pay <= 0:
                continue
            already = kapatma_kaynak.get((int(hid), belge), Decimal("0"))
            extra = pay - already
            if extra > 0:
                sonuc[int(hid)] = sonuc.get(int(hid), Decimal("0")) + extra
    except Exception:
        logger.exception("fatura makbuz bağından defterde_kapanan okunamadı")
    return sonuc


def _as_of_date(as_of) -> date | None:
    if as_of is None:
        return None
    if isinstance(as_of, datetime):
        return as_of.date()
    if isinstance(as_of, date):
        return as_of
    return None


def _aktif_company_id(company_id: int | None) -> int | None:
    """API uyumu; cari hareket tablolarında company_id yoksa yalnızca tanı için."""
    if company_id is not None:
        try:
            return int(company_id)
        except (TypeError, ValueError):
            return None
    return None


def _hareket_dahil_mi(
    hareket_tarihi: date | None,
    *,
    as_of: date | None,
    strict_before: bool,
) -> bool:
    if as_of is None:
        return True
    t = hareket_tarihi or date.min
    if strict_before:
        return t < as_of
    return t <= as_of


def _evo_onaysiz_satis_faturasi_belgesi_mi(belge_no: str) -> bool:
    """Evo onaysız satış faturası (SAF… / EVB-SF-…) mi?

    Satış Fişi (SFŞ…), RAY vb. fiş/düzeltme belgeleri False döner — bakiyeden düşülmez.
    """
    bn = (belge_no or "").strip().upper()
    if not bn:
        return False
    if bn.startswith("SAF"):
        return True
    if bn.startswith("EVB-SF-"):
        return True
    return False


def _onaysiz_veya_kesim_sonrasi_onayli_belgeler(
    session, belge_nolari: set[str], *, as_of: date | None
) -> set[str]:
    """Onaysız Evo satış faturası veya kesim sonrası onaylı satış faturasını bakiyeden çıkar.

    Satış Fişi / sayım düzeltme / diğer fiş türleri (ör. SFŞ) bu kapsama girmez;
    Evo finans bakiyesinde sayılan fişlerin Cin SH'si korunur.
    """
    nos = {b for b in belge_nolari if b}
    if not nos:
        return set()
    try:
        from database.models.satis_faturasi import SatisFaturasi
    except Exception:
        return set()
    haric: set[str] = set()
    for bas in range(0, len(nos), 500):
        parca = list(nos)[bas : bas + 500]
        for fat in session.scalars(
            select(SatisFaturasi).where(SatisFaturasi.fatura_no.in_(parca))
        ):
            bn = (fat.fatura_no or "").strip()
            if not bn:
                continue
            if not bool(getattr(fat, "onaylandi", False)):
                # Yalnız Evo onaysız satış faturası (SAF / EVB-SF); SFŞ Satış Fişi hariç
                if _evo_onaysiz_satis_faturasi_belgesi_mi(bn):
                    haric.add(bn)
                continue
            if as_of is None:
                continue
            # Onaylı belge: geçerli onay kesimden sonraysa tarihsel 08.11 bakiyesine katma
            onay_dt = getattr(fat, "approved_at", None)
            if onay_dt is None:
                continue
            onay_gun = onay_dt.date() if isinstance(onay_dt, datetime) else onay_dt
            if isinstance(onay_gun, date) and onay_gun > as_of:
                haric.add(bn)
    return haric


def _kayitlari_topla(
    session,
    cari_id: int,
    *,
    as_of: date | None,
    strict_before: bool,
    exclude_belge_no: str | None,
    currency: str | None,
) -> list[tuple[date | None, str, Decimal, Decimal]]:
    """(tarih, belge_no, borc, alacak) — müşteri listesi ile aynı kaynak."""
    cid = int(cari_id)
    haric = (exclude_belge_no or "").strip()
    pb_filtre = (currency or "").strip().upper() or None

    islemler = list(
        session.scalars(select(CariIslem).where(CariIslem.cari_id == cid)).all()
    )
    hareketler = list(
        session.scalars(select(SatisHareketi).where(SatisHareketi.cari_id == cid)).all()
    )
    islem_belgeleri = {(i.belge_no or "") for i in islemler}
    onaysiz_haric = _onaysiz_veya_kesim_sonrasi_onayli_belgeler(
        session,
        {(h.belge_no or "").strip() for h in hareketler},
        as_of=as_of,
    )
    defterde = _defterde_kapanan_toplamlari(
        session,
        [int(h.id) for h in hareketler if getattr(h, "id", None)],
        islem_belgeleri,
    )

    kayitlar: list[tuple[date | None, str, Decimal, Decimal]] = []

    for h in hareketler:
        bn = h.belge_no or ""
        if haric and bn == haric:
            continue
        if bn in onaysiz_haric:
            continue
        if bn in islem_belgeleri or bn.startswith(_DEFTER_ATLA_ONEK):
            continue
        if not _hareket_dahil_mi(h.satis_tarihi, as_of=as_of, strict_before=strict_before):
            continue
        if pb_filtre:
            pb = (getattr(h, "para_birimi", None) or "TRY").upper()
            if pb != pb_filtre:
                continue
        # Çift kayıtsız SatisHareketi: kapanan alacak; CariIslem'li kapatmalar hariç
        borc_ek, alacak_ek = _satis_hareketi_borc_alacak(
            h.satis_tutari,
            getattr(h, "kalan_acik_tutar", None),
            defterde_kapanan=defterde.get(int(h.id), Decimal("0")),
        )
        kayitlar.append((h.satis_tarihi, bn, borc_ek, alacak_ek))

    for islem in islemler:
        bn = islem.belge_no or ""
        if haric and bn == haric:
            continue
        if not _hareket_dahil_mi(islem.tarih, as_of=as_of, strict_before=strict_before):
            continue
        if pb_filtre:
            pb = (getattr(islem, "para_birimi", None) or "TRY").upper()
            if pb != pb_filtre:
                continue
        kayitlar.append(
            (islem.tarih, bn, _d(islem.borc), _d(islem.alacak))
        )

    kayitlar.sort(key=lambda x: (x[0] or date.min, x[1] or "", str(x[2]), str(x[3])))
    return kayitlar


def net_bakiye(
    customer_id: int,
    *,
    company_id: int | None = None,
    currency: str | None = None,
    as_of_datetime: date | datetime | None = None,
    strict_before: bool = False,
    exclude_belge_no: str | None = None,
    eklenecek: Decimal | None = None,
    session=None,
    tani_log: bool = False,
) -> dict[str, Any]:
    """Müşteri listesi ile aynı formülde net cari bakiye.

    Parameters
    ----------
    customer_id
        Değişmeyen cari.id
    as_of_datetime
        None → güncel (liste bakiyesi). date/datetime → o ana kadarki hareketler.
    strict_before
        True ise yalnızca as_of tarihinden *önceki* günler (geçmiş fatura Eski Bakiye).
    exclude_belge_no
        Düzenlenen faturanın belge no'su; çift sayımı önlemek için hariç.
    eklenecek
        Bu belgenin cari etkisi (satışta borç artışı, pozitif). Yeni Bakiye = net + eklenecek.
    """
    cid = int(customer_id)
    co_id = _aktif_company_id(company_id)
    as_of = _as_of_date(as_of_datetime)
    ek = _kurus(eklenecek or 0)

    def _hesap(sess) -> dict[str, Any]:
        kayitlar = _kayitlari_topla(
            sess,
            cid,
            as_of=as_of,
            strict_before=strict_before,
            exclude_belge_no=exclude_belge_no,
            currency=currency,
        )
        toplam_borc = _kurus(sum((k[2] for k in kayitlar), Decimal("0")))
        toplam_alacak = _kurus(sum((k[3] for k in kayitlar), Decimal("0")))
        eski = _kurus(toplam_borc - toplam_alacak)
        yeni = _kurus(eski + ek)
        sonuc = {
            "customer_id": cid,
            "company_id": co_id,
            "currency": (currency or "TRY").upper(),
            "as_of": as_of,
            "strict_before": bool(strict_before),
            "exclude_belge_no": (exclude_belge_no or None),
            "hareket_sayisi": len(kayitlar),
            "toplam_borc": toplam_borc,
            "toplam_alacak": toplam_alacak,
            "bakiye": eski,  # Eski / liste net
            "eski_bakiye": eski,
            "yeni_bakiye": yeni,
            "eklenecek": ek,
        }
        if tani_log:
            logger.info(
                "cari_bakiye id=%s co=%s as_of=%s strict=%s haric=%s n=%s borc=%s alacak=%s net=%s ek=%s yeni=%s",
                cid,
                co_id,
                as_of,
                strict_before,
                exclude_belge_no,
                len(kayitlar),
                toplam_borc,
                toplam_alacak,
                eski,
                ek,
                yeni,
            )
        return sonuc

    if session is not None:
        return _hesap(session)
    with get_session() as sess:
        return _hesap(sess)


def liste_bakiyeleri(
    customer_ids: list[int],
    *,
    company_id: int | None = None,
    currency: str | None = None,
) -> dict[int, Decimal]:
    """Toplu liste bakiyesi — müşteri listesi / fatura önbelleği için.

    ``net_bakiye`` ile aynı formül; hareketler cari başına değil, parça parça toplu okunur.
    """
    _ = _aktif_company_id(company_id)
    ids = list(dict.fromkeys(int(i) for i in customer_ids if i is not None))
    if not ids:
        return {}
    pb_filtre = (currency or "").strip().upper() or None
    borclar: dict[int, Decimal] = {cid: Decimal("0") for cid in ids}
    alacaklar: dict[int, Decimal] = {cid: Decimal("0") for cid in ids}
    with get_session() as session:
        for bas in range(0, len(ids), 500):
            parca = ids[bas:bas + 500]
            islem_belgeleri: dict[int, set[str]] = {cid: set() for cid in parca}
            for cid, bn, borc, alacak, pb in session.execute(
                select(CariIslem.cari_id, CariIslem.belge_no, CariIslem.borc, CariIslem.alacak,
                       CariIslem.para_birimi).where(CariIslem.cari_id.in_(parca))
            ):
                islem_belgeleri[int(cid)].add(bn or "")
                if pb_filtre and (pb or "TRY").upper() != pb_filtre:
                    continue
                borclar[int(cid)] += _d(borc)
                alacaklar[int(cid)] += _d(alacak)
            hareket_satirlari = list(
                session.execute(
                    select(
                        SatisHareketi.id,
                        SatisHareketi.cari_id,
                        SatisHareketi.belge_no,
                        SatisHareketi.satis_tutari,
                        SatisHareketi.kalan_acik_tutar,
                        SatisHareketi.para_birimi,
                    ).where(SatisHareketi.cari_id.in_(parca))
                )
            )
            tum_belgeler = set()
            for belgeler in islem_belgeleri.values():
                tum_belgeler |= belgeler
            defterde = _defterde_kapanan_toplamlari(
                session,
                [int(r[0]) for r in hareket_satirlari],
                tum_belgeler,
            )
            for hid, cid, bn, tutar, kalan, pb in hareket_satirlari:
                bn = bn or ""
                if bn in islem_belgeleri[int(cid)] or bn.startswith(_DEFTER_ATLA_ONEK):
                    continue
                if pb_filtre and (pb or "TRY").upper() != pb_filtre:
                    continue
                b, a = _satis_hareketi_borc_alacak(
                    tutar, kalan, defterde_kapanan=defterde.get(int(hid), Decimal("0"))
                )
                borclar[int(cid)] += b
                alacaklar[int(cid)] += a
    return {cid: _kurus(_kurus(borclar[cid]) - _kurus(alacaklar[cid])) for cid in ids}


def liste_bakiyeleri_detay(
    customer_ids: list[int],
    *,
    company_id: int | None = None,
    currency: str | None = None,
) -> dict[int, dict[str, Any]]:
    """Toplu bakiye + borç/alacak toplamları (liste ekranı N+1 net_bakiye yerine)."""
    _ = _aktif_company_id(company_id)
    ids = list(dict.fromkeys(int(i) for i in customer_ids if i is not None))
    if not ids:
        return {}
    pb_filtre = (currency or "").strip().upper() or None
    borclar: dict[int, Decimal] = {cid: Decimal("0") for cid in ids}
    alacaklar: dict[int, Decimal] = {cid: Decimal("0") for cid in ids}
    with get_session() as session:
        for bas in range(0, len(ids), 500):
            parca = ids[bas : bas + 500]
            islem_belgeleri: dict[int, set[str]] = {cid: set() for cid in parca}
            # Belge seti + tutarlar: tek tarama (önceki satır satır Python toplamı)
            for cid, bn, borc, alacak, pb in session.execute(
                select(
                    CariIslem.cari_id,
                    CariIslem.belge_no,
                    CariIslem.borc,
                    CariIslem.alacak,
                    CariIslem.para_birimi,
                ).where(CariIslem.cari_id.in_(parca))
            ):
                cid_i = int(cid)
                islem_belgeleri[cid_i].add(bn or "")
                if pb_filtre and (pb or "TRY").upper() != pb_filtre:
                    continue
                borclar[cid_i] += _d(borc)
                alacaklar[cid_i] += _d(alacak)
            hareket_satirlari = list(
                session.execute(
                    select(
                        SatisHareketi.id,
                        SatisHareketi.cari_id,
                        SatisHareketi.belge_no,
                        SatisHareketi.satis_tutari,
                        SatisHareketi.kalan_acik_tutar,
                        SatisHareketi.para_birimi,
                    ).where(SatisHareketi.cari_id.in_(parca))
                )
            )
            tum_belgeler: set[str] = set()
            for belgeler in islem_belgeleri.values():
                tum_belgeler |= belgeler
            defterde = _defterde_kapanan_toplamlari(
                session,
                [int(r[0]) for r in hareket_satirlari],
                tum_belgeler,
            )
            for hid, cid, bn, tutar, kalan, pb in hareket_satirlari:
                bn = bn or ""
                cid_i = int(cid)
                if bn in islem_belgeleri[cid_i] or bn.startswith(_DEFTER_ATLA_ONEK):
                    continue
                if pb_filtre and (pb or "TRY").upper() != pb_filtre:
                    continue
                b, a = _satis_hareketi_borc_alacak(
                    tutar, kalan, defterde_kapanan=defterde.get(int(hid), Decimal("0"))
                )
                borclar[cid_i] += b
                alacaklar[cid_i] += a
    sonuc: dict[int, dict[str, Any]] = {}
    for cid in ids:
        tb = _kurus(borclar[cid])
        ta = _kurus(alacaklar[cid])
        sonuc[cid] = {
            "bakiye": _kurus(tb - ta),
            "toplam_borc": tb,
            "toplam_alacak": ta,
        }
    return sonuc


PARA_BIRIMI_TL = "TL"
# Liste özet eşiği: mutlak net ≤ bu tutar sayılardan ve toplamdan çıkar (tam 10,00 hariç)
OZET_ESIK_TL = Decimal("10.00")


def bakiye_yon_kisa(bakiye, *, tedarikci_modu: bool = False) -> str:
    """Liste sütunu yönü — tüm cari türlerinde aynı kural.

    net = toplam borç − toplam alacak.
    net > 0 → Borçlu (cari bize borçlu) · net < 0 → Alacaklı (cari bizden alacaklı).
    ``tedarikci_modu`` geriye uyumluluk için kabul edilir; yönü ters çevirmez
    (tür değişince bakiye yönü değişmemeli).
    """
    del tedarikci_modu  # yön türden bağımsız
    net = _d(bakiye)
    if net == 0:
        return "Kapalı"
    return "Borçlu" if net > 0 else "Alacaklı"


def bakiye_bilgisi(bakiye, *, tedarikci_modu: bool = False) -> dict[str, Any]:
    """Tüm cari seçim listelerinde ortak gösterim: net, mutlak tutar, yön, para birimi."""
    net = _kurus(bakiye)
    return {
        "net": net,
        "tutar": abs(net),
        "yon": bakiye_yon_kisa(net, tedarikci_modu=tedarikci_modu),
        "para_birimi": PARA_BIRIMI_TL,
    }


def filtre_bakiye_ozeti(
    bakiyeler: dict[int, Any] | list[tuple[int, Any]],
    *,
    tedarikci_modu: bool = False,
    esik: Decimal | None = None,
) -> dict[str, Any]:
    """Filtre kapsamındaki carilerin borçlu/alacaklı özeti (tek yön, tek sayım).

    Net = borç − alacak (müşteride + → Borçlu, − → Alacaklı).
    ``abs(net) <= esik`` (varsayılan 10,00 TL) hem sayıdan hem toplamdan çıkar.
    Aynı cari_id bir kez sayılır; çift rol kartı da tek kayıt olarak girer.
    """
    esik_tl = _kurus(OZET_ESIK_TL if esik is None else esik)
    if isinstance(bakiyeler, dict):
        pairs = list(bakiyeler.items())
    else:
        pairs = list(bakiyeler)

    gorulen: set[int] = set()
    borclu_say = 0
    alacakli_say = 0
    borclar = Decimal("0")
    alacaklar = Decimal("0")
    esik_alti = 0
    sifir = 0
    hatali = 0

    for cid, ham in pairs:
        try:
            kid = int(cid)
        except (TypeError, ValueError):
            hatali += 1
            continue
        if kid in gorulen:
            continue
        gorulen.add(kid)
        try:
            net = _kurus(ham)
        except Exception:
            hatali += 1
            continue
        if net == 0:
            sifir += 1
            continue
        mutlak = abs(net)
        if mutlak <= esik_tl:
            esik_alti += 1
            continue
        yon = bakiye_yon_kisa(net, tedarikci_modu=tedarikci_modu)
        if yon == "Borçlu":
            borclu_say += 1
            borclar += mutlak
        elif yon == "Alacaklı":
            alacakli_say += 1
            alacaklar += mutlak

    return {
        "borclu_sayisi": borclu_say,
        "borclar_toplami": _kurus(borclar),
        "alacakli_sayisi": alacakli_say,
        "alacaklar_toplami": _kurus(alacaklar),
        "esik": esik_tl,
        "esik_alti_sayisi": esik_alti,
        "sifir_sayisi": sifir,
        "hatali_sayisi": hatali,
        "kapsam_sayisi": len(gorulen),
        "tedarikci_modu": bool(tedarikci_modu),
        "para_birimi": PARA_BIRIMI_TL,
    }


def fatura_eski_yeni_bakiye(
    customer_id: int,
    *,
    fatura_tarihi: date | None = None,
    fatura_saati: str | None = None,
    exclude_belge_no: str | None = None,
    belge_etkisi: Decimal | None = None,
    company_id: int | None = None,
    currency: str | None = None,
    tani_log: bool = False,
) -> dict[str, Any]:
    """Fatura Eski / Yeni Bakiye — tek servis.

    Bugün / gelecek tarihli veya tarih yok: güncel liste bakiyesi (strict_before=False, as_of=None).
    Geçmiş tarih: yalnızca fatura gününden önceki hareketler.
    exclude_belge_no: düzenlemede bu belgenin kayıtlı etkisi Eski'ye girmez.
    belge_etkisi: ekrandaki güncel açık tutar (satışta +borç).
    """
    bugun = date.today()
    ft = fatura_tarihi
    strict = bool(ft is not None and ft < bugun)
    as_of = ft if strict else None

    # Saat bilgisi ileride datetime alanına bağlanabilir; şimdilik tarih kuralı yeterli
    _ = fatura_saati

    return net_bakiye(
        customer_id,
        company_id=company_id,
        currency=currency,
        as_of_datetime=as_of,
        strict_before=strict,
        exclude_belge_no=exclude_belge_no,
        eklenecek=belge_etkisi or Decimal("0"),
        tani_log=tani_log,
    )
