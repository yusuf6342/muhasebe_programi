"""Bütçe planı servisi — oluşturma, satır kaydı, eşit aylık dağıtım, ön muhasebe gerçekleşen.

Gerçekleşme kaynağı yalnızca Ön Muhasebe'dir; genel muhasebe ile toplanmaz.
Plan açmak / kaydetmek fatura, fiş veya stok hareketi üretmez.
"""

from __future__ import annotations

import re
from calendar import monthrange
from datetime import date, datetime
from decimal import Decimal, ROUND_DOWN, ROUND_HALF_UP
from typing import Any

from sqlalchemy import select

from database.database import Base, engine, get_session
from database.models.butce import (
    DURUM_TASLAK,
    DURUMLAR,
    OLCU_GIDER,
    OLCU_SATIS,
    OLCU_TURLERI,
    ButceEslesme,
    ButcePlan,
    ButceSatir,
)

_Q = Decimal("0.01")
_SIFIR = Decimal("0.00")
_KOD_RE = re.compile(r"^BTC-(\d{4})-(\d{4})$")

# Taslak / iptal — gerçekleşmeye dahil edilmez
_SATIS_HARIC_DURUM = frozenset({"TASLAK", "İPTAL", "IPTAL", "IPTAL EDİLDİ"})
_GIDER_HARIC_DURUM = frozenset({"TASLAK", "İPTAL", "IPTAL", "IPTAL EDİLDİ"})

KAYNAK_ON_MUHASEBE = "ON_MUHASEBE"
KAYNAK_ETIKET = "Ön Muhasebe"


def _q2(v) -> Decimal:
    return Decimal(str(v or 0)).quantize(_Q, rounding=ROUND_HALF_UP)


def _firma_id(firma_id: int | None = None) -> int:
    if firma_id is not None:
        return int(firma_id)
    try:
        from database.session_manager import oturum

        return int(oturum.company_id or 0)
    except Exception:  # noqa: BLE001
        return 0


def _kullanici() -> str | None:
    try:
        from database.session_manager import oturum

        return oturum.ad_soyad or oturum.kullanici_adi or None
    except Exception:  # noqa: BLE001
        return None


def dagit_yillik_esit(yillik: Decimal | int | float | str, ay_sayisi: int = 12) -> list[Decimal]:
    """Yıllık tutarı aylara eşit böler; kuruş artığını son aya yazar. Toplam = yıllık."""
    if ay_sayisi < 1:
        raise ValueError("ay_sayisi en az 1 olmalıdır.")
    hedef = _q2(yillik)
    if ay_sayisi == 1:
        return [hedef]
    birim = (hedef / Decimal(ay_sayisi)).quantize(_Q, rounding=ROUND_DOWN)
    aylar = [birim] * (ay_sayisi - 1)
    son = (hedef - birim * (ay_sayisi - 1)).quantize(_Q, rounding=ROUND_HALF_UP)
    aylar.append(son)
    return aylar


class ButceService:
    _schema_hazir = False

    @classmethod
    def ensure_schema(cls, eng=None) -> None:
        """create_all(checkfirst) — mevcut veriyi silmez."""
        bag = eng if eng is not None else engine
        if bag is None:
            return
        import database.models.butce  # noqa: F401

        Base.metadata.create_all(
            bind=bag,
            tables=[
                ButcePlan.__table__,
                ButceSatir.__table__,
                ButceEslesme.__table__,
            ],
        )
        cls._schema_hazir = True

    @classmethod
    def _sonraki_kod(cls, session, firma_id: int, mali_yil: int) -> str:
        """BTC-YYYY-#### — firma+yıl içinde çakışmasız (max+1)."""
        onek = f"BTC-{int(mali_yil)}-"
        max_n = 0
        for kod in session.scalars(
            select(ButcePlan.kod).where(
                ButcePlan.firma_id == firma_id,
                ButcePlan.kod.like(f"{onek}%"),
            )
        ).all():
            m = _KOD_RE.match((kod or "").strip())
            if m and int(m.group(1)) == int(mali_yil):
                max_n = max(max_n, int(m.group(2)))
        return f"{onek}{max_n + 1:04d}"

    @classmethod
    def plan_olustur(
        cls,
        ad: str,
        mali_yil: int,
        *,
        para_birimi: str = "TRY",
        firma_id: int | None = None,
        aciklama: str | None = None,
        durum: str = DURUM_TASLAK,
    ) -> dict[str, Any]:
        cls.ensure_schema()
        ad = (ad or "").strip()
        if not ad:
            raise ValueError("Bütçe adı zorunludur.")
        if durum not in DURUMLAR:
            raise ValueError(f"Geçersiz durum: {durum}")
        fid = _firma_id(firma_id)
        with get_session() as session:
            kod = cls._sonraki_kod(session, fid, int(mali_yil))
            # Eşzamanlı çakışmaya karşı kısa yeniden deneme
            for _ in range(5):
                var = session.scalar(
                    select(ButcePlan.id).where(
                        ButcePlan.firma_id == fid,
                        ButcePlan.kod == kod,
                    )
                )
                if var is None:
                    break
                kod = cls._sonraki_kod(session, fid, int(mali_yil))
            plan = ButcePlan(
                kod=kod,
                ad=ad,
                mali_yil=int(mali_yil),
                durum=durum,
                para_birimi=(para_birimi or "TRY").upper()[:3],
                firma_id=fid,
                surum=1,
                aciklama=(aciklama or None),
                olusturma=datetime.now(),
                olusturan=_kullanici(),
            )
            session.add(plan)
            session.flush()
            return cls._plan_dict(plan)

    @classmethod
    def planlari_listele(
        cls,
        *,
        firma_id: int | None = None,
        mali_yil: int | None = None,
    ) -> list[dict[str, Any]]:
        cls.ensure_schema()
        fid = _firma_id(firma_id)
        with get_session() as session:
            q = select(ButcePlan).where(ButcePlan.firma_id == fid)
            if mali_yil is not None:
                q = q.where(ButcePlan.mali_yil == int(mali_yil))
            q = q.order_by(ButcePlan.mali_yil.desc(), ButcePlan.kod.desc())
            return [cls._plan_dict(p) for p in session.scalars(q).all()]

    @classmethod
    def plan_getir(cls, plan_id: int, *, firma_id: int | None = None) -> dict[str, Any] | None:
        cls.ensure_schema()
        fid = _firma_id(firma_id)
        with get_session() as session:
            plan = session.get(ButcePlan, int(plan_id))
            if plan is None or int(plan.firma_id) != fid:
                return None
            d = cls._plan_dict(plan)
            d["satirlar"] = [
                cls._satir_dict(s)
                for s in session.scalars(
                    select(ButceSatir)
                    .where(ButceSatir.plan_id == plan.id)
                    .order_by(ButceSatir.olcu_turu, ButceSatir.kategori, ButceSatir.ay)
                ).all()
            ]
            return d

    @classmethod
    def satirlar_kaydet(
        cls,
        plan_id: int,
        satirlar: list[dict[str, Any]],
        *,
        firma_id: int | None = None,
        olcu_turu: str | None = None,
        kategori: str | None = None,
    ) -> list[dict[str, Any]]:
        """Satırları kaydet / güncelle. Aynı (olcu, kategori, ay) yeniden yazılır (idempotent).

        ``olcu_turu`` / ``kategori`` verilirse o kapsam dışındaki satırlar silinmez;
        verilen listedeki anahtarlar upsert edilir. Listede olmayan aynı kapsamdaki aylar
        silinmez (kısmi kayıt güvenli). Tam kapsama için tüm 12 ayı gönderin.
        """
        cls.ensure_schema()
        fid = _firma_id(firma_id)
        with get_session() as session:
            plan = session.get(ButcePlan, int(plan_id))
            if plan is None or int(plan.firma_id) != fid:
                raise ValueError("Bütçe planı bulunamadı.")
            kaydedilen: list[ButceSatir] = []
            for raw in satirlar:
                olcu = (raw.get("olcu_turu") or olcu_turu or "").strip().upper()
                if olcu not in OLCU_TURLERI:
                    raise ValueError(f"Geçersiz ölçü türü: {olcu}")
                kat = (raw.get("kategori") or kategori or "GENEL").strip() or "GENEL"
                ay = int(raw["ay"])
                if ay < 1 or ay > 12:
                    raise ValueError(f"Ay 1–12 olmalı: {ay}")
                tutar = _q2(raw.get("tutar"))
                aciklama = raw.get("aciklama")
                mevcut = session.scalar(
                    select(ButceSatir).where(
                        ButceSatir.plan_id == plan.id,
                        ButceSatir.olcu_turu == olcu,
                        ButceSatir.kategori == kat,
                        ButceSatir.ay == ay,
                    )
                )
                if mevcut is None:
                    mevcut = ButceSatir(
                        plan_id=plan.id,
                        olcu_turu=olcu,
                        kategori=kat,
                        ay=ay,
                        tutar=tutar,
                        aciklama=aciklama,
                    )
                    session.add(mevcut)
                else:
                    mevcut.tutar = tutar
                    if aciklama is not None:
                        mevcut.aciklama = aciklama
                kaydedilen.append(mevcut)
            plan.guncelleme = datetime.now()
            plan.guncelleyen = _kullanici()
            session.flush()
            return [cls._satir_dict(s) for s in kaydedilen]

    @classmethod
    def yillik_dagit_ve_kaydet(
        cls,
        plan_id: int,
        yillik_tutar: Decimal | int | float | str,
        *,
        olcu_turu: str = OLCU_SATIS,
        kategori: str = "GENEL",
        firma_id: int | None = None,
        aciklama: str | None = None,
    ) -> list[dict[str, Any]]:
        """Yıllık tutarı 12 aya eşit dağıtıp kaydeder (son aya kuruş)."""
        olcu = (olcu_turu or OLCU_SATIS).strip().upper()
        if olcu not in OLCU_TURLERI:
            raise ValueError(f"Geçersiz ölçü türü: {olcu}")
        aylik = dagit_yillik_esit(_q2(yillik_tutar), 12)
        satirlar = [
            {
                "olcu_turu": olcu,
                "kategori": kategori or "GENEL",
                "ay": i + 1,
                "tutar": aylik[i],
                "aciklama": aciklama,
            }
            for i in range(12)
        ]
        return cls.satirlar_kaydet(plan_id, satirlar, firma_id=firma_id)

    @classmethod
    def plan_satirlari(
        cls,
        plan_id: int,
        *,
        olcu_turu: str | None = None,
        kategori: str | None = None,
        firma_id: int | None = None,
    ) -> list[dict[str, Any]]:
        cls.ensure_schema()
        fid = _firma_id(firma_id)
        with get_session() as session:
            plan = session.get(ButcePlan, int(plan_id))
            if plan is None or int(plan.firma_id) != fid:
                return []
            q = select(ButceSatir).where(ButceSatir.plan_id == plan.id)
            if olcu_turu:
                q = q.where(ButceSatir.olcu_turu == olcu_turu.strip().upper())
            if kategori:
                q = q.where(ButceSatir.kategori == kategori)
            q = q.order_by(ButceSatir.olcu_turu, ButceSatir.kategori, ButceSatir.ay)
            return [cls._satir_dict(s) for s in session.scalars(q).all()]

    @classmethod
    def gerceklesen_on_muhasebe(
        cls,
        mali_yil: int,
        *,
        olcu_turu: str = OLCU_SATIS,
        firma_id: int | None = None,
    ) -> dict[str, Any]:
        """Ön muhasebe gerçekleşmesi — yalnız bu kaynak; genel muhasebe eklenmez.

        Eksik aylar için sıfır uydurulmaz: ``aylar`` yalnızca belge bulunan ayları içerir.
        ``bos_aylar`` listesinde veri olmayan aylar yer alır (başarı sayılmaz).
        """
        _ = _firma_id(firma_id)  # firma izolasyonu ileride çok-firma DB için
        olcu = (olcu_turu or OLCU_SATIS).strip().upper()
        yil = int(mali_yil)
        bas = date(yil, 1, 1)
        bit = date(yil, 12, 31)

        if olcu == OLCU_SATIS:
            aylar, belge_sayisi = cls._satis_aylik_net(bas, bit)
        elif olcu == OLCU_GIDER:
            aylar, belge_sayisi = cls._gider_aylik_net(bas, bit)
        else:
            # TODO: ALIS / KARLILIK / NAKIT ön muhasebe adaptörleri
            return {
                "kaynak": KAYNAK_ON_MUHASEBE,
                "kaynak_etiket": KAYNAK_ETIKET,
                "olcu_turu": olcu,
                "mali_yil": yil,
                "aylar": {},
                "bos_aylar": list(range(1, 13)),
                "belge_sayisi": 0,
                "toplam": _SIFIR,
                "durum": "DESTEKLENMIYOR",
                "mesaj": f"{olcu} için ön muhasebe gerçekleşmesi henüz bağlanmadı (TODO).",
            }

        bos = [a for a in range(1, 13) if a not in aylar]
        toplam = sum(aylar.values(), _SIFIR)
        return {
            "kaynak": KAYNAK_ON_MUHASEBE,
            "kaynak_etiket": KAYNAK_ETIKET,
            "olcu_turu": olcu,
            "mali_yil": yil,
            "aylar": {a: _q2(t) for a, t in aylar.items()},
            "bos_aylar": bos,
            "belge_sayisi": belge_sayisi,
            "toplam": _q2(toplam),
            "durum": "OK" if belge_sayisi > 0 else "VERI_YOK",
            "mesaj": (
                None
                if belge_sayisi > 0
                else "Seçilen yılda geçerli ön muhasebe belgesi yok; sıfır uydurulmadı."
            ),
        }

    @classmethod
    def karsilastirma(
        cls,
        plan_id: int,
        *,
        olcu_turu: str = OLCU_SATIS,
        kategori: str = "GENEL",
        firma_id: int | None = None,
    ) -> dict[str, Any]:
        """Yan yana: Bütçe vs Ön Muhasebe (toplama yok)."""
        plan = cls.plan_getir(plan_id, firma_id=firma_id)
        if plan is None:
            raise ValueError("Bütçe planı bulunamadı.")
        olcu = (olcu_turu or OLCU_SATIS).strip().upper()
        satirlar = [
            s
            for s in (plan.get("satirlar") or [])
            if s["olcu_turu"] == olcu and s["kategori"] == (kategori or "GENEL")
        ]
        butce_ay = {int(s["ay"]): _q2(s["tutar"]) for s in satirlar}
        ger = cls.gerceklesen_on_muhasebe(
            plan["mali_yil"], olcu_turu=olcu, firma_id=firma_id
        )
        ger_ay = ger.get("aylar") or {}
        satir_ozet = []
        for ay in range(1, 13):
            b = butce_ay.get(ay)
            g = ger_ay.get(ay)
            satir_ozet.append(
                {
                    "ay": ay,
                    "butce": b,  # plan satırı yoksa None
                    "on_muhasebe": g,  # belge yoksa None — sıfır uydurma
                    "fark": (_q2(g) - _q2(b)) if (b is not None and g is not None) else None,
                    "kaynak_etiket": KAYNAK_ETIKET,
                }
            )
        return {
            "plan": plan,
            "olcu_turu": olcu,
            "kategori": kategori or "GENEL",
            "kaynak": KAYNAK_ON_MUHASEBE,
            "kaynak_etiket": KAYNAK_ETIKET,
            "genel_muhasebe": None,  # TODO: ayrı adaptör; ön ile toplanmaz
            "satirlar": satir_ozet,
            "butce_toplam": _q2(sum(butce_ay.values(), _SIFIR)) if butce_ay else None,
            "on_muhasebe_toplam": ger.get("toplam"),
            "gerceklesen_meta": {
                "durum": ger.get("durum"),
                "belge_sayisi": ger.get("belge_sayisi"),
                "bos_aylar": ger.get("bos_aylar"),
                "mesaj": ger.get("mesaj"),
            },
        }

    # ------------------------------------------------------------------ yardımcılar

    @staticmethod
    def _plan_dict(p: ButcePlan) -> dict[str, Any]:
        return {
            "id": int(p.id),
            "kod": p.kod,
            "ad": p.ad,
            "mali_yil": int(p.mali_yil),
            "durum": p.durum,
            "para_birimi": p.para_birimi,
            "firma_id": int(p.firma_id),
            "surum": int(p.surum),
            "aciklama": p.aciklama,
            "olusturma": p.olusturma.isoformat(sep=" ", timespec="seconds") if p.olusturma else None,
            "olusturan": p.olusturan,
        }

    @staticmethod
    def _satir_dict(s: ButceSatir) -> dict[str, Any]:
        return {
            "id": int(s.id),
            "plan_id": int(s.plan_id),
            "olcu_turu": s.olcu_turu,
            "kategori": s.kategori,
            "ay": int(s.ay),
            "tutar": _q2(s.tutar),
            "aciklama": s.aciklama,
        }

    @classmethod
    def _satis_aylik_net(cls, bas: date, bit: date) -> tuple[dict[int, Decimal], int]:
        """Satış faturaları KDV hariç net (tl_matrah); taslak/iptal hariç.

        Ham SQL — ORM ilişki ağı zorunlu değil; yalnız okuma, belge üretmez.
        """
        from sqlalchemy import text

        aylar: dict[int, Decimal] = {}
        sayac = 0
        with get_session() as session:
            if not _tablo_var(session, "satis_faturalari"):
                return {}, 0
            # is_deleted / cancelled_at kolonları eski DB'de yoksa yok say
            sutunlar = _sutunlar(session, "satis_faturalari")
            silinen = "AND IFNULL(is_deleted, 0) = 0" if "is_deleted" in sutunlar else ""
            iptal_kolon = "AND cancelled_at IS NULL" if "cancelled_at" in sutunlar else ""
            sql = text(
                f"""
                SELECT fatura_tarihi, tl_matrah, durum
                FROM satis_faturalari
                WHERE fatura_tarihi >= :bas AND fatura_tarihi <= :bit
                {silinen}
                {iptal_kolon}
                """
            )
            for fatura_tarihi, tl_matrah, durum_raw in session.execute(
                sql, {"bas": bas.isoformat(), "bit": bit.isoformat()}
            ):
                durum = (durum_raw or "").strip().upper()
                durum_n = durum.replace("İ", "I")
                if durum in _SATIS_HARIC_DURUM or durum_n in {"TASLAK", "IPTAL", "IPTAL EDILDI"}:
                    continue
                if isinstance(fatura_tarihi, str):
                    ay = int(fatura_tarihi[5:7])
                else:
                    ay = int(fatura_tarihi.month)
                aylar[ay] = aylar.get(ay, _SIFIR) + _q2(tl_matrah)
                sayac += 1
        return aylar, sayac

    @classmethod
    def _gider_aylik_net(cls, bas: date, bit: date) -> tuple[dict[int, Decimal], int]:
        """Hizmet gider faturaları (tl_matrah) + gider fişleri (tutar); iptal hariç."""
        aylar: dict[int, Decimal] = {}
        sayac = 0
        with get_session() as session:
            # Hizmet alış (gider) faturaları
            try:
                from database.models.hizmet_faturasi import HizmetFaturasi

                if _tablo_var(session, "hizmet_faturalari"):
                    for f in session.scalars(
                        select(HizmetFaturasi).where(
                            HizmetFaturasi.fatura_turu == "GIDER",
                            HizmetFaturasi.fatura_tarihi >= bas,
                            HizmetFaturasi.fatura_tarihi <= bit,
                        )
                    ).all():
                        durum = (getattr(f, "durum", "") or "").strip().upper().replace("İ", "I")
                        if durum in {"TASLAK", "IPTAL", "IPTAL EDILDI"}:
                            continue
                        ay = int(f.fatura_tarihi.month)
                        aylar[ay] = aylar.get(ay, _SIFIR) + _q2(getattr(f, "tl_matrah", 0))
                        sayac += 1
            except Exception:  # noqa: BLE001
                pass
            # Gider fişleri
            try:
                from database.models.finans import GiderFisi

                if _tablo_var(session, "gider_fisleri"):
                    for g in session.scalars(
                        select(GiderFisi).where(
                            GiderFisi.tarih >= bas,
                            GiderFisi.tarih <= bit,
                        )
                    ).all():
                        durum = (getattr(g, "durum", "") or "").strip().upper().replace("İ", "I")
                        if durum in {"IPTAL", "TASLAK"}:
                            continue
                        ay = int(g.tarih.month)
                        aylar[ay] = aylar.get(ay, _SIFIR) + _q2(getattr(g, "tutar", 0))
                        sayac += 1
            except Exception:  # noqa: BLE001
                pass
        return aylar, sayac


def _tablo_var(session, ad: str) -> bool:
    try:
        bind = session.get_bind()
        from sqlalchemy import inspect as sa_inspect

        return sa_inspect(bind).has_table(ad)
    except Exception:  # noqa: BLE001
        return False


def _sutunlar(session, tablo: str) -> set[str]:
    try:
        bind = session.get_bind()
        from sqlalchemy import inspect as sa_inspect

        return {c["name"] for c in sa_inspect(bind).get_columns(tablo)}
    except Exception:  # noqa: BLE001
        return set()


def ay_araligi(yil: int, ay: int) -> tuple[date, date]:
    son = monthrange(yil, ay)[1]
    return date(yil, ay, 1), date(yil, ay, son)
