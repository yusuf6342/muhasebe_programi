"""Tedarikçi haftalık ödeme — N Cuma taksiti + ödeme FIFO mahsup.

* Açılış devri + tüm alış faturaları belge tarihinden N haftalık taksite bölünür (varsayılan 9).
* İlk taksit: belge Cuma ise aynı gün, değilse izleyen Cuma; kalanlar izleyen Cumalar.
* İlk N−1 taksit = round(tutar/N, 2); son taksit = kalan (toplam belge tutarına eşit).
* Ödemeler işlem tarihine göre, en eski açık vadeden FIFO mahsup edilir.
* Haftalık rapor: önceki kalan + bu hafta açık + toplam; geçmiş hafta devir/ödeme/kalan.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime, timedelta
from decimal import Decimal, ROUND_HALF_UP
from typing import Any

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from database.access import yazma_zorunlu
from database.database import get_session
from database.models.cari import CariIslem, SatisHareketi
from database.models.haftalik_odeme import CariHaftalikOdemeTaksit

# Ödeme makbuzu şekilleri (kasa_makbuz_ui ile aynı)
ODEME_YONTEM_NAKIT = "NAKIT"
ODEME_YONTEM_HAVALE = "HAVALE"
ODEME_YONTEM_KART = "KART"
ODEME_SEKIL_NAKIT = "NAKİT ÖDEME — KASA"
ODEME_SEKIL_HAVALE = "BANKA HAVALESİ / EFT / FAST — GÖNDERİLEN"
ODEME_SEKIL_KART = "KREDİ KARTIYLA ÖDEME — FİRMA KARTI"

KURUS = Decimal("0.01")
SIFIR = Decimal("0.00")
TAKSIT_ADET = 9  # varsayılan
TAKSIT_ADET_MIN = 1
TAKSIT_ADET_MAX = 52
TOLERANS = Decimal("0.005")
KAYNAK_SH = "SATIS_HAREKET"
KAYNAK_CI = "CARI_ISLEM"


def _acilis_devir_mi(islem) -> bool:
    """Evo/açılış/devir satırı mı? (belge, tür veya açıklama)."""
    tur = (getattr(islem, "islem_turu", None) or "").strip().upper()
    aciklama = (getattr(islem, "aciklama", None) or "").upper()
    belge = (getattr(islem, "belge_no", None) or "").upper()
    return (
        "AÇILIŞ" in tur
        or "ACILIS" in tur
        or "DEVİR" in tur
        or "DEVIR" in tur
        or "AÇILIŞ" in aciklama
        or "ACILIS" in aciklama
        or "DEVIR" in belge
        or "DEVIREN" in belge
        or belge.startswith("EVB-AK-")
    )


def taksit_adet_dogrula(adet) -> int:
    """Pozitif tam sayı (1–52); aksi halde ValueError."""
    try:
        if isinstance(adet, bool):
            raise ValueError
        n = int(adet)
    except (TypeError, ValueError):
        raise ValueError("Pozitif tam sayı girin") from None
    if n < TAKSIT_ADET_MIN or n > TAKSIT_ADET_MAX:
        raise ValueError("Pozitif tam sayı girin")
    return n


def _d(deger) -> Decimal:
    if deger is None or deger == "":
        return SIFIR
    if isinstance(deger, Decimal):
        return deger
    return Decimal(str(deger))


def _kurus(deger) -> Decimal:
    return _d(deger).quantize(KURUS, rounding=ROUND_HALF_UP)


def ilk_cuma(belge_tarihi: date) -> date:
    """Belge Cuma ise aynı gün; aksi halde izleyen ilk Cuma."""
    gun = belge_tarihi.weekday()
    if gun == 4:
        return belge_tarihi
    return belge_tarihi + timedelta(days=(4 - gun) % 7)


def hafta_araligi(referans: date | None = None) -> tuple[date, date]:
    ref = referans or date.today()
    pazartesi = ref - timedelta(days=ref.weekday())
    return pazartesi, pazartesi + timedelta(days=6)


def n_taksit_tutarlari(toplam: Decimal, adet: int = TAKSIT_ADET) -> list[Decimal]:
    """İlk N−1 = round(toplam/N); son taksit = kalan (toplam eşitlenir)."""
    adet = taksit_adet_dogrula(adet)
    toplam = _kurus(toplam)
    if toplam <= SIFIR:
        raise ValueError("Belge tutarı pozitif olmalıdır.")
    if adet == 1:
        return [toplam]
    birim = (toplam / Decimal(adet)).quantize(KURUS, rounding=ROUND_HALF_UP)
    ilk = [birim] * (adet - 1)
    son = _kurus(toplam - sum(ilk, SIFIR))
    if son < SIFIR:
        duz = []
        kalan = toplam
        for _ in range(adet - 1):
            t = min(birim, kalan)
            duz.append(_kurus(t))
            kalan = _kurus(kalan - t)
        duz.append(kalan)
        return duz
    sonuc = ilk + [son]
    assert sum(sonuc, SIFIR) == toplam
    return sonuc


def dokuz_taksit_tutarlari(toplam: Decimal) -> list[Decimal]:
    """Geriye dönük: varsayılan 9 taksit."""
    return n_taksit_tutarlari(toplam, TAKSIT_ADET)


def taksit_vade_tarihleri(belge_tarihi: date, adet: int = TAKSIT_ADET) -> list[date]:
    adet = taksit_adet_dogrula(adet)
    bas = ilk_cuma(belge_tarihi)
    return [bas + timedelta(days=7 * i) for i in range(adet)]


def ortalama_valor_gun(
    belge_tarihi: date, vadeler: list[date], tutarlar: list[Decimal]
) -> Decimal:
    toplam = sum((_kurus(t) for t in tutarlar), SIFIR)
    if toplam <= SIFIR:
        return SIFIR
    carpim = SIFIR
    for vade, tutar in zip(vadeler, tutarlar):
        carpim += _kurus(tutar) * Decimal((vade - belge_tarihi).days)
    return (carpim / toplam).quantize(Decimal("0.0001"))


def plan_belge(
    belge_tarihi: date, tutar: Decimal, taksit_adet: int = TAKSIT_ADET
) -> dict[str, Any]:
    adet = taksit_adet_dogrula(taksit_adet)
    tutarlar = n_taksit_tutarlari(tutar, adet)
    vadeler = taksit_vade_tarihleri(belge_tarihi, adet)
    valor = ortalama_valor_gun(belge_tarihi, vadeler, tutarlar)
    return {
        "taksit_adet": adet,
        "ortalama_valor_gun": valor,
        "taksitler": [
            {
                "taksit_no": i + 1,
                "vade_tarihi": vadeler[i],
                "planlanan_tutar": tutarlar[i],
                "yas_gun": (vadeler[i] - belge_tarihi).days,
            }
            for i in range(adet)
        ],
    }


def odemeleri_fifo_mahsup(
    taksitler: list[dict[str, Any]],
    odemeler: list[dict[str, Any]],
    *,
    as_of: date | None = None,
) -> list[dict[str, Any]]:
    """Ödemeleri tarih sırasıyla en eski açık taksitten mahsup et.

    Aynı vadede belge tarihi + kayıt kimliği ile sırala.
    Vadesi ödeme gününe kadar gelenler önce; artan sonraki açık taksitlere.
    """
    for t in taksitler:
        t["odenen_tutar"] = SIFIR
        t["kalan"] = _kurus(t["planlanan_tutar"])

    sirali = sorted(
        odemeler,
        key=lambda o: (o["tarih"], int(o.get("id") or 0), str(o.get("belge_no") or "")),
    )
    for od in sirali:
        od_tarih = od["tarih"]
        if as_of is not None and od_tarih > as_of:
            continue
        kalan_od = _kurus(od["tutar"])
        if kalan_od <= SIFIR:
            continue
        acik = [t for t in taksitler if _kurus(t["kalan"]) > TOLERANS]
        acik.sort(
            key=lambda t: (
                t["vade_tarihi"],
                t["fatura_tarihi"],
                int(t.get("kaynak_id") or 0),
                int(t["taksit_no"]),
            )
        )
        once = [t for t in acik if t["vade_tarihi"] <= od_tarih]
        sonra = [t for t in acik if t["vade_tarihi"] > od_tarih]
        for t in once + sonra:
            if kalan_od <= TOLERANS:
                break
            al = min(_kurus(t["kalan"]), kalan_od)
            t["odenen_tutar"] = _kurus(_kurus(t["odenen_tutar"]) + al)
            t["kalan"] = _kurus(_kurus(t["planlanan_tutar"]) - _kurus(t["odenen_tutar"]))
            kalan_od = _kurus(kalan_od - al)
    return taksitler


class HaftalikOdemeService:
    _hazir_motor = None

    @classmethod
    def schema_hazirla(cls, motor=None) -> None:
        import database.database as veritabani
        from sqlalchemy import inspect as sa_inspect

        motor = motor or veritabani.engine
        if motor is None:
            return
        insp = sa_inspect(motor)
        tablo = CariHaftalikOdemeTaksit.__tablename__
        if insp.has_table(tablo):
            kolonlar = {c["name"] for c in insp.get_columns(tablo)}
            if "belge_anahtar" not in kolonlar:
                with motor.begin() as conn:
                    conn.execute(text(f"DROP TABLE IF EXISTS {tablo}"))
        CariHaftalikOdemeTaksit.__table__.create(bind=motor, checkfirst=True)
        cls._hazir_motor = motor

    @staticmethod
    def _tedarikci_belgeler(session: Session, cari_id: int) -> list[dict[str, Any]]:
        """Açılış alacağı + alış faturaları (borç oluşturan belgeler)."""
        belgeler: list[dict[str, Any]] = []
        # Alış: SatisHareketi negatif
        for h in session.scalars(
            select(SatisHareketi)
            .where(
                SatisHareketi.cari_id == int(cari_id),
                SatisHareketi.satis_tutari < 0,
            )
            .order_by(SatisHareketi.satis_tarihi, SatisHareketi.id)
        ).all():
            tutar = _kurus(abs(_d(h.satis_tutari)))
            if tutar <= TOLERANS:
                continue
            belgeler.append(
                {
                    "kaynak_tur": KAYNAK_SH,
                    "kaynak_id": int(h.id),
                    "belge_anahtar": f"SH:{int(h.id)}",
                    "belge_no": (h.belge_no or "").strip() or f"SH-{h.id}",
                    "tarih": h.satis_tarihi,
                    "tutar": tutar,
                    "fatura_hareket_id": int(h.id),
                }
            )
        # Açılış / devir: CariIslem alacak (tedarikçi borcu — brüt açılış)
        for i in session.scalars(
            select(CariIslem)
            .where(
                CariIslem.cari_id == int(cari_id),
                CariIslem.alacak > 0,
            )
            .order_by(CariIslem.tarih, CariIslem.id)
        ).all():
            if not _acilis_devir_mi(i):
                continue
            # Aynı tutar alış SH ile çiftlenmesin — açılış ayrı
            tutar = _kurus(i.alacak)
            if tutar <= TOLERANS:
                continue
            belgeler.append(
                {
                    "kaynak_tur": KAYNAK_CI,
                    "kaynak_id": int(i.id),
                    "belge_anahtar": f"CI:{int(i.id)}",
                    "belge_no": (i.belge_no or "").strip() or f"ACILIS-{i.id}",
                    "tarih": i.tarih,
                    "tutar": tutar,
                    "fatura_hareket_id": None,
                }
            )
        belgeler.sort(key=lambda b: (b["tarih"], b["kaynak_id"]))
        return belgeler

    @staticmethod
    def _tedarikci_odemeler(session: Session, cari_id: int) -> list[dict[str, Any]]:
        """Tedarikçi ödemeleri — OMK/ödeme/iade + KK/Virman + açılış BORÇ (dönem öncesi mahsup).

        Evo açılışında brüt DEVIREN alacağı ile birlikte, aynı dönem öncesi yapılmış
        ödemeler ``Açılış`` BORÇ satırları olarak gelir (ör. EVB-AK-1944-58112). Bunlar
        cari bakiyeyi düşürür; plana da ödeme olarak girmelidir — aksi halde plan açık
        bakiyesi cari karttan büyük görünür (T00073: 38.040,07 TL).
        """
        odemeler = []
        # KK Çekimi + Virman Ödeme aynı belgeyi iki kez yazabilir — bir kez say.
        # Aynı OMK'nin mükerrer Ödeme satırları (T00008) cari bakiyede toplanır; planda da toplanmalı.
        kk_virman_belge: set[str] = set()
        for i in session.scalars(
            select(CariIslem)
            .where(CariIslem.cari_id == int(cari_id))
            .order_by(CariIslem.tarih, CariIslem.id)
        ).all():
            tur = (i.islem_turu or "").strip()
            borc = _kurus(i.borc)
            alacak = _kurus(i.alacak)
            tutar = SIFIR
            belge = (i.belge_no or "").strip()
            if tur in ("KK Çekimi",) and borc > TOLERANS:
                if belge and belge in kk_virman_belge:
                    continue
                tutar = borc
                if belge:
                    kk_virman_belge.add(belge)
            elif tur in ("Virman Ödeme",) and alacak > TOLERANS:
                if belge and belge in kk_virman_belge:
                    continue
                tutar = alacak
                if belge:
                    kk_virman_belge.add(belge)
            elif tur in ("Ödeme", "Odeme", "ÖDEME", "ODEME", "İade", "Iade") or (
                "Ödeme" in tur or "Odeme" in tur or "İade" in tur
            ):
                tutar = borc if borc > TOLERANS else alacak
            elif _acilis_devir_mi(i) and borc > TOLERANS:
                # Dönem öncesi / açılış mahsup ödemesi (alacak açılış belgesi değil)
                tutar = borc
            if tutar <= TOLERANS:
                continue
            odemeler.append(
                {
                    "id": int(i.id),
                    "tarih": i.tarih,
                    "tutar": tutar,
                    "belge_no": belge,
                    "aciklama": i.aciklama,
                    "islem_turu": tur,
                }
            )
        return odemeler

    @classmethod
    def planlari_yeniden_kur(
        cls, session: Session, cari_id: int, taksit_adet: int = TAKSIT_ADET
    ) -> dict[str, Any]:
        """Tüm planı silip N'li taksitleri baştan yaz; ödemeleri mahsup et."""
        adet = taksit_adet_dogrula(taksit_adet)
        cls.schema_hazirla(session.get_bind())
        eski = session.scalars(
            select(CariHaftalikOdemeTaksit).where(
                CariHaftalikOdemeTaksit.cari_id == int(cari_id)
            )
        ).all()
        for e in eski:
            session.delete(e)
        session.flush()

        belgeler = cls._tedarikci_belgeler(session, int(cari_id))
        olusturulan = []
        for b in belgeler:
            plan = plan_belge(b["tarih"], b["tutar"], adet)
            for t in plan["taksitler"]:
                session.add(
                    CariHaftalikOdemeTaksit(
                        cari_id=int(cari_id),
                        belge_anahtar=b["belge_anahtar"],
                        kaynak_tur=b["kaynak_tur"],
                        kaynak_id=int(b["kaynak_id"]),
                        fatura_hareket_id=b.get("fatura_hareket_id"),
                        belge_no=b["belge_no"],
                        fatura_tarihi=b["tarih"],
                        taksit_no=int(t["taksit_no"]),
                        taksit_adet=adet,
                        vade_tarihi=t["vade_tarihi"],
                        planlanan_tutar=_kurus(t["planlanan_tutar"]),
                        odenen_tutar=SIFIR,
                        ortalama_valor_gun=_d(plan["ortalama_valor_gun"]).quantize(
                            Decimal("0.0001")
                        ),
                    )
                )
            olusturulan.append(
                {
                    "belge_no": b["belge_no"],
                    "tutar": str(b["tutar"]),
                    "taksit_adet": adet,
                    "ortalama_valor_gun": float(plan["ortalama_valor_gun"]),
                }
            )
        session.flush()
        cls.odenenleri_mahsup_et(session, int(cari_id))
        return {
            "belge_adet": len(olusturulan),
            "taksit_adet": adet,
            "olusturulan": olusturulan,
        }

    @classmethod
    def odenenleri_mahsup_et(cls, session: Session, cari_id: int, as_of: date | None = None) -> int:
        satirlar = session.scalars(
            select(CariHaftalikOdemeTaksit)
            .where(CariHaftalikOdemeTaksit.cari_id == int(cari_id))
            .order_by(
                CariHaftalikOdemeTaksit.vade_tarihi,
                CariHaftalikOdemeTaksit.fatura_tarihi,
                CariHaftalikOdemeTaksit.kaynak_id,
                CariHaftalikOdemeTaksit.taksit_no,
            )
        ).all()
        if not satirlar:
            return 0
        taksit_dict = [
            {
                "id": int(t.id),
                "kaynak_id": int(t.kaynak_id),
                "taksit_no": int(t.taksit_no),
                "vade_tarihi": t.vade_tarihi,
                "fatura_tarihi": t.fatura_tarihi,
                "planlanan_tutar": _kurus(t.planlanan_tutar),
                "odenen_tutar": SIFIR,
                "kalan": _kurus(t.planlanan_tutar),
            }
            for t in satirlar
        ]
        odemeler = cls._tedarikci_odemeler(session, int(cari_id))
        odemeleri_fifo_mahsup(taksit_dict, odemeler, as_of=as_of)
        by_id = {t["id"]: t for t in taksit_dict}
        guncel = 0
        for row in satirlar:
            yeni = _kurus(by_id[int(row.id)]["odenen_tutar"])
            if _kurus(row.odenen_tutar) != yeni:
                row.odenen_tutar = yeni
                row.guncelleme = datetime.now()
                guncel += 1
            elif as_of is not None:
                # as_of geçici hesap — DB'ye yazma (rapor bellekte)
                pass
        return guncel

    @classmethod
    def acik_faturalar_icin_plan_olustur(
        cls, cari_id: int, taksit_adet: int = TAKSIT_ADET
    ) -> dict[str, Any]:
        yazma_zorunlu("cari_duzenleme")
        cls.schema_hazirla()
        with get_session() as session:
            sonuc = cls.planlari_yeniden_kur(
                session, int(cari_id), taksit_adet=taksit_adet
            )
            session.commit()
            return sonuc

    @classmethod
    def _taksit_dict_listesi(
        cls, session: Session, cari_id: int, as_of: date | None
    ) -> list[dict[str, Any]]:
        satirlar = session.scalars(
            select(CariHaftalikOdemeTaksit)
            .where(CariHaftalikOdemeTaksit.cari_id == int(cari_id))
            .order_by(
                CariHaftalikOdemeTaksit.vade_tarihi,
                CariHaftalikOdemeTaksit.fatura_tarihi,
                CariHaftalikOdemeTaksit.kaynak_id,
                CariHaftalikOdemeTaksit.taksit_no,
            )
        ).all()
        taksitler = [
            {
                "id": int(t.id),
                "belge_anahtar": t.belge_anahtar,
                "kaynak_tur": t.kaynak_tur,
                "kaynak_id": int(t.kaynak_id),
                "belge_no": t.belge_no,
                "fatura_tarihi": t.fatura_tarihi,
                "taksit_no": int(t.taksit_no),
                "taksit_adet": int(t.taksit_adet),
                "vade_tarihi": t.vade_tarihi,
                "planlanan_tutar": _kurus(t.planlanan_tutar),
                "odenen_tutar": SIFIR,
                "kalan": _kurus(t.planlanan_tutar),
                "ortalama_valor_gun": float(t.ortalama_valor_gun or 0),
            }
            for t in satirlar
        ]
        odemeler = cls._tedarikci_odemeler(session, int(cari_id))
        odemeleri_fifo_mahsup(taksitler, odemeler, as_of=as_of)
        return taksitler

    @classmethod
    def haftalik_rapor(
        cls,
        cari_id: int,
        *,
        referans: date | None = None,
        otomatik_plan: bool = True,
        taksit_adet: int = TAKSIT_ADET,
    ) -> dict[str, Any]:
        adet = taksit_adet_dogrula(taksit_adet)
        cls.schema_hazirla()
        if otomatik_plan:
            try:
                cls.acik_faturalar_icin_plan_olustur(int(cari_id), taksit_adet=adet)
            except Exception:
                with get_session() as session:
                    # Mevcut plan farklı adetteyse veya yoksa yeniden kur
                    mevcut = session.scalars(
                        select(CariHaftalikOdemeTaksit)
                        .where(CariHaftalikOdemeTaksit.cari_id == int(cari_id))
                        .limit(1)
                    ).first()
                    if mevcut is None or int(mevcut.taksit_adet or 0) != adet:
                        cls.planlari_yeniden_kur(
                            session, int(cari_id), taksit_adet=adet
                        )
                        session.commit()
        else:
            # otomatik_plan=False olsa bile adet değiştiyse yeniden kur
            with get_session() as session:
                mevcut = session.scalars(
                    select(CariHaftalikOdemeTaksit)
                    .where(CariHaftalikOdemeTaksit.cari_id == int(cari_id))
                    .limit(1)
                ).first()
                if mevcut is None or int(mevcut.taksit_adet or 0) != adet:
                    try:
                        cls.planlari_yeniden_kur(
                            session, int(cari_id), taksit_adet=adet
                        )
                        session.commit()
                    except Exception:
                        pass

        ref = referans or date.today()
        bas, bit = hafta_araligi(ref)
        # Seçili hafta için: mevcut/hafta içi → referans günü; geçmiş hafta → pazar
        bugun = date.today()
        if bit < bugun:
            as_of = bit
        elif bas > bugun:
            as_of = bas - timedelta(days=1)  # gelecek hafta: henüz ödeme yok say
            as_of = max(as_of, bas)  # yine de hafta başı öncesi
            as_of = bas - timedelta(days=1)
        else:
            as_of = min(ref, bit)

        with get_session() as session:
            # Kalıcı mahsup (tüm ödemeler)
            cls.odenenleri_mahsup_et(session, int(cari_id), as_of=None)
            session.commit()

            taksitler = cls._taksit_dict_listesi(session, int(cari_id), as_of=as_of)
            odemeler = cls._tedarikci_odemeler(session, int(cari_id))

            onceki = [
                t for t in taksitler if t["vade_tarihi"] < bas and t["kalan"] > TOLERANS
            ]
            bu_hafta = [
                t
                for t in taksitler
                if bas <= t["vade_tarihi"] <= bit and t["kalan"] > TOLERANS
            ]
            gelecek = [
                t for t in taksitler if t["vade_tarihi"] > bit and t["kalan"] > TOLERANS
            ]
            onceki_toplam = _kurus(sum((t["kalan"] for t in onceki), SIFIR))
            bu_hafta_toplam = _kurus(sum((t["kalan"] for t in bu_hafta), SIFIR))
            gelecek_toplam = _kurus(sum((t["kalan"] for t in gelecek), SIFIR))
            toplam_odenecek = _kurus(onceki_toplam + bu_hafta_toplam)
            cari_bakiye = _kurus(onceki_toplam + bu_hafta_toplam + gelecek_toplam)

            # Hafta geçmişi metrikleri
            onceki_gun = bas - timedelta(days=1)
            taksit_bas = cls._taksit_dict_listesi(session, int(cari_id), as_of=onceki_gun)
            hafta_basi_devri = _kurus(
                sum(
                    (t["kalan"] for t in taksit_bas if t["vade_tarihi"] < bas),
                    SIFIR,
                )
            )
            vadesi_gelen = _kurus(
                sum(
                    (
                        t["kalan"]
                        for t in taksit_bas
                        if bas <= t["vade_tarihi"] <= bit
                    ),
                    SIFIR,
                )
            )
            hafta_odemeleri = [
                o for o in odemeler if bas <= o["tarih"] <= bit and o["tarih"] <= as_of
            ]
            # Geçmiş haftada tüm hafta ödemeleri
            if bit < bugun:
                hafta_odemeleri = [o for o in odemeler if bas <= o["tarih"] <= bit]
            hafta_odeme_toplam = _kurus(
                sum((o["tutar"] for o in hafta_odemeleri), SIFIR)
            )
            hafta_sonu_kalan = _kurus(
                sum(
                    (t["kalan"] for t in taksitler if t["vade_tarihi"] <= bit),
                    SIFIR,
                )
            )
            # Önceki kalan = vade < bas (hafta sonu bakışında da aynı as_of)
            # Plan özeti
            plan_ozet: dict[str, dict] = {}
            tum = cls._taksit_dict_listesi(session, int(cari_id), as_of=as_of)
            for t in tum:
                key = t["belge_anahtar"]
                if key not in plan_ozet:
                    plan_ozet[key] = {
                        "belge_no": t["belge_no"],
                        "fatura_tarihi": t["fatura_tarihi"],
                        "taksit_adet": t["taksit_adet"],
                        "ortalama_valor_gun": t["ortalama_valor_gun"],
                        "planlanan_toplam": SIFIR,
                        "odenen_toplam": SIFIR,
                        "kalan_toplam": SIFIR,
                    }
                plan_ozet[key]["planlanan_toplam"] += t["planlanan_tutar"]
                plan_ozet[key]["odenen_toplam"] += t["odenen_tutar"]
                plan_ozet[key]["kalan_toplam"] += t["kalan"]

            def _satir(t: dict) -> dict:
                return {
                    "id": t["id"],
                    "belge_no": t["belge_no"],
                    "fatura_tarihi": t["fatura_tarihi"],
                    "taksit_no": t["taksit_no"],
                    "taksit_adet": t["taksit_adet"],
                    "vade_tarihi": t["vade_tarihi"],
                    "planlanan_tutar": t["planlanan_tutar"],
                    "odenen_tutar": t["odenen_tutar"],
                    "kalan": t["kalan"],
                    "ortalama_valor_gun": t["ortalama_valor_gun"],
                }

            # Cari kart bakiyesi ile plan mutabakatı
            from database.cari_bakiye_service import net_bakiye

            nb = net_bakiye(int(cari_id), session=session)
            cari_net = _kurus(nb.get("bakiye"))
            # Tedarikçi ekranda kalan genelde |net| (alacaklı = negatif net)
            cari_kalan_abs = _kurus(abs(cari_net))
            plan_cari_fark = _kurus(cari_bakiye - cari_kalan_abs)
            plan_belge_nos = {
                (b.get("belge_no") or "").strip()
                for b in cls._tedarikci_belgeler(session, int(cari_id))
            }
            plan_odeme_nos = {
                (o.get("belge_no") or "").strip()
                for o in odemeler
                if (o.get("belge_no") or "").strip()
            }
            plan_nos = plan_belge_nos | plan_odeme_nos
            plan_disi: list[dict[str, Any]] = []
            for i in session.scalars(
                select(CariIslem)
                .where(CariIslem.cari_id == int(cari_id))
                .order_by(CariIslem.tarih, CariIslem.id)
            ).all():
                bn = (i.belge_no or "").strip()
                if bn and bn in plan_nos:
                    continue
                b, a = _kurus(i.borc), _kurus(i.alacak)
                if b <= TOLERANS and a <= TOLERANS:
                    continue
                plan_disi.append(
                    {
                        "tarih": i.tarih,
                        "belge_no": bn,
                        "islem_turu": i.islem_turu,
                        "borc": b,
                        "alacak": a,
                        "etki": _kurus(b - a),
                        "kaynak": "CARI_ISLEM",
                    }
                )

            return {
                "taksit_adet": adet,
                "hafta_bas": bas,
                "hafta_bit": bit,
                "as_of": as_of,
                "onceki_haftalardan_kalan": onceki_toplam,
                "bu_hafta_acik_taksitler": bu_hafta_toplam,
                "bu_hafta_acik_adet": len(bu_hafta),
                "toplam_odenecek": toplam_odenecek,
                "gelecek_haftalara_kalan": gelecek_toplam,
                "cari_acik_bakiye": cari_bakiye,  # planın tüm açık taksit toplamı
                "cari_net_bakiye": cari_net,
                "cari_kalan_abs": cari_kalan_abs,
                "plan_cari_fark": plan_cari_fark,
                "plan_disi_hareketler": plan_disi,
                "hafta_basi_devri": hafta_basi_devri,
                "vadesi_gelen": vadesi_gelen,
                "hafta_odeme_toplam": hafta_odeme_toplam,
                "hafta_odemeleri": hafta_odemeleri,
                "hafta_sonu_kalan": hafta_sonu_kalan,
                "onceki_satirlar": [_satir(t) for t in onceki],
                "bu_hafta_odenecek": [_satir(t) for t in bu_hafta],
                "gecikmis": [_satir(t) for t in onceki],  # uyumluluk
                "gelecek_satirlar": [_satir(t) for t in gelecek],
                "tum_taksitler": [_satir(t) for t in tum],
                "plan_ozetleri": list(plan_ozet.values()),
                "plansiz_faturalar": [],
                "bu_hafta_toplam": bu_hafta_toplam,
                "gecikmis_toplam": onceki_toplam,
            }

    @classmethod
    def odeme_dagitim_onizle(
        cls,
        cari_id: int,
        tutar,
        odeme_tarihi: date,
        *,
        taksit_adet: int = TAKSIT_ADET,
        referans: date | None = None,
    ) -> dict[str, Any]:
        """Girilen tutarın en eski açık vadeden FIFO mahsup önizlemesi (kayıt yok)."""
        odeme = _kurus(tutar)
        if odeme <= TOLERANS:
            raise ValueError("Ödeme tutarı pozitif olmalıdır.")
        if odeme_tarihi > date.today():
            raise ValueError("Ödeme tarihi gelecek olamaz.")
        adet = taksit_adet_dogrula(taksit_adet)
        rapor = cls.haftalik_rapor(
            int(cari_id),
            referans=referans or odeme_tarihi,
            otomatik_plan=True,
            taksit_adet=adet,
        )
        acik = [
            dict(t)
            for t in (rapor.get("tum_taksitler") or [])
            if _kurus(t.get("kalan")) > TOLERANS
        ]
        acik.sort(
            key=lambda t: (
                t["vade_tarihi"],
                t["fatura_tarihi"],
                int(t.get("kaynak_id") or 0),
                int(t["taksit_no"]),
            )
        )
        once = [t for t in acik if t["vade_tarihi"] <= odeme_tarihi]
        sonra = [t for t in acik if t["vade_tarihi"] > odeme_tarihi]
        kalan_od = odeme
        dagitim: list[dict[str, Any]] = []
        for t in once + sonra:
            if kalan_od <= TOLERANS:
                break
            onceki_kalan = _kurus(t["kalan"])
            al = min(onceki_kalan, kalan_od)
            yeni_kalan = _kurus(onceki_kalan - al)
            dagitim.append(
                {
                    "taksit_id": t.get("id"),
                    "belge_no": t.get("belge_no"),
                    "taksit_no": t.get("taksit_no"),
                    "taksit_adet": t.get("taksit_adet"),
                    "vade_tarihi": t.get("vade_tarihi"),
                    "onceki_kalan": onceki_kalan,
                    "mahsup": al,
                    "kalan": yeni_kalan,
                }
            )
            kalan_od = _kurus(kalan_od - al)
        from database.finans_service import FinansService

        return {
            "cari_id": int(cari_id),
            "odeme_tarihi": odeme_tarihi,
            "odeme_tutari": odeme,
            "onerilen_tutar": _kurus(rapor.get("toplam_odenecek")),
            "hafta_bas": rapor.get("hafta_bas"),
            "hafta_bit": rapor.get("hafta_bit"),
            "makbuz_no_oneri": FinansService.makbuz_no_oner(),
            "dagitim": dagitim,
            "mahsup_toplam": _kurus(odeme - kalan_od),
            "avans": kalan_od if kalan_od > TOLERANS else SIFIR,
            "taksit_adet": adet,
        }

    @classmethod
    def odeme_yap(
        cls,
        *,
        cari_id: int,
        tutar,
        odeme_tarihi: date,
        yontem: str,
        finans_hesap_id: int | None = None,
        kredi_karti_id: int | None = None,
        taksit_sayisi: int = 1,
        ilk_taksit_tarihi: date | None = None,
        aciklama: str | None = None,
        istek_anahtari: str | None = None,
        taksit_adet: int = TAKSIT_ADET,
        referans: date | None = None,
    ) -> dict[str, Any]:
        """Tedarikçi ödeme makbuzu + haftalık FIFO mahsup (tek çağrı; idempotent)."""
        yazma_zorunlu("finans_duzenleme", "cari_duzenleme")
        from database.database import kasa_makbuz_schemasini_guncelle
        from database.finans_service import FinansService
        import database.database as veritabani

        if veritabani.engine is not None:
            kasa_makbuz_schemasini_guncelle(veritabani.engine)

        odeme = _kurus(tutar)
        if odeme <= TOLERANS:
            raise ValueError("Ödeme tutarı pozitif olmalıdır.")
        if odeme_tarihi > date.today():
            raise ValueError("Ödeme tarihi gelecek olamaz.")

        yon = (yontem or "").strip().upper()
        if yon in ("NAKIT", "NAKİT", "KASA"):
            yon = ODEME_YONTEM_NAKIT
            sekil = ODEME_SEKIL_NAKIT
            if not finans_hesap_id:
                raise ValueError("Nakit ödeme için kasa hesabı seçin.")
            satir: dict[str, Any] = {
                "odeme_sekli": sekil,
                "finans_hesap_id": int(finans_hesap_id),
                "tutar": odeme,
                "tarih": odeme_tarihi,
            }
        elif yon in ("HAVALE", "EFT", "FAST", "BANKA"):
            yon = ODEME_YONTEM_HAVALE
            sekil = ODEME_SEKIL_HAVALE
            if not finans_hesap_id:
                raise ValueError("Havale/EFT için banka hesabı seçin.")
            satir = {
                "odeme_sekli": sekil,
                "finans_hesap_id": int(finans_hesap_id),
                "tutar": odeme,
                "tarih": odeme_tarihi,
            }
        elif yon in ("KART", "KK", "KREDI_KARTI", "KREDİ_KARTI"):
            yon = ODEME_YONTEM_KART
            sekil = ODEME_SEKIL_KART
            if not kredi_karti_id:
                raise ValueError("Kredi kartı ödemesi için firma kredi kartı seçin.")
            try:
                n_taksit = int(str(taksit_sayisi or 1).strip() or "1")
            except ValueError as hata:
                raise ValueError("Kart taksit sayısı tam sayı olmalıdır.") from hata
            if n_taksit < 1:
                raise ValueError("Kart taksit sayısı en az 1 olmalıdır.")
            satir = {
                "odeme_sekli": sekil,
                "kredi_karti_id": int(kredi_karti_id),
                "tutar": odeme,
                "tarih": odeme_tarihi,
                "taksit_sayisi": n_taksit,
            }
            if ilk_taksit_tarihi is not None:
                satir["ilk_taksit_tarihi"] = ilk_taksit_tarihi
        else:
            raise ValueError("Ödeme yöntemi Nakit, Havale/EFT veya Kredi Kartı olmalıdır.")

        anahtar = (istek_anahtari or "").strip() or f"ho-odeme-{cari_id}-{uuid.uuid4().hex}"
        onizleme = cls.odeme_dagitim_onizle(
            int(cari_id),
            odeme,
            odeme_tarihi,
            taksit_adet=taksit_adet,
            referans=referans or odeme_tarihi,
        )
        acik = (aciklama or "").strip() or (
            f"Haftalık ödeme {onizleme['hafta_bas'].strftime('%d.%m.%Y')}–"
            f"{onizleme['hafta_bit'].strftime('%d.%m.%Y')}"
        )
        makbuz = FinansService.kasa_odeme_makbuzu_kaydet(
            {
                "tarih": odeme_tarihi,
                "cari_id": int(cari_id),
                "makbuz_no_otomatik": True,
                "aciklama": acik,
                "istek_anahtari": anahtar,
                "satirlar": [satir],
            }
        )
        # Makbuz kaydı CariIslem üretir; haftalık mahsup raporu yenilerken uygulanır
        rapor = cls.haftalik_rapor(
            int(cari_id),
            referans=referans or odeme_tarihi,
            otomatik_plan=True,
            taksit_adet=taksit_adet_dogrula(taksit_adet),
        )
        return {
            "makbuz_id": int(makbuz.id),
            "belge_no": makbuz.belge_no,
            "makbuz_no": makbuz.makbuz_no,
            "tutar": _kurus(makbuz.tutar),
            "tarih": makbuz.tarih,
            "yontem": yon,
            "istek_anahtari": anahtar,
            "onizleme": onizleme,
            "rapor": rapor,
        }
