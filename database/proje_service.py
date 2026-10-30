"""Proje takip servisi — maliyet merkezi / rapor boyutu."""

from __future__ import annotations

import re
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import select

import database.database as _db
from database.database import Base, get_session
from database.models.proje import (
    DURUM_AKTIF,
    DURUMLAR,
    ORNEK_TURLER,
    Proje,
    ProjeAyar,
    ProjeBelgeBaglanti,
    ProjeCari,
)
from database.session_manager import oturum

_KOD_RE = re.compile(r"^PRJ-(\d{4})-(\d{4})$")


def _firma_id(firma_id: int | None = None) -> int:
    if firma_id is not None:
        return int(firma_id)
    if oturum.company_id is None:
        raise ValueError("Aktif firma yok.")
    return int(oturum.company_id)


def _kullanici() -> str:
    return (oturum.kullanici_adi or oturum.role_kod or "sistem")[:120]


class ProjeService:
    _schema_hazir = False

    @classmethod
    def ensure_schema(cls, eng=None) -> None:
        bag = eng if eng is not None else _db.engine
        if bag is None:
            return
        import database.models.proje  # noqa: F401

        Base.metadata.create_all(
            bind=bag,
            tables=[
                Proje.__table__,
                ProjeCari.__table__,
                ProjeBelgeBaglanti.__table__,
                ProjeAyar.__table__,
            ],
        )
        cls._schema_hazir = True

    @classmethod
    def ornek_turler(cls) -> tuple[str, ...]:
        return ORNEK_TURLER

    @classmethod
    def ayarlari_getir(cls, *, firma_id: int | None = None) -> dict[str, Any]:
        cls.ensure_schema()
        fid = _firma_id(firma_id)
        with get_session() as session:
            a = session.get(ProjeAyar, fid)
            if a is None:
                return {
                    "firma_id": fid,
                    "asama_aktif": False,
                    "coklu_dagitim": False,
                    "ortak_gider": False,
                    "hakedis": False,
                    "gorevler": False,
                }
            return {
                "firma_id": fid,
                "asama_aktif": bool(a.asama_aktif),
                "coklu_dagitim": bool(a.coklu_dagitim),
                "ortak_gider": bool(a.ortak_gider),
                "hakedis": bool(a.hakedis),
                "gorevler": bool(a.gorevler),
            }

    @classmethod
    def ayarlari_kaydet(cls, veriler: dict, *, firma_id: int | None = None) -> dict:
        cls.ensure_schema()
        fid = _firma_id(firma_id)
        with get_session() as session:
            a = session.get(ProjeAyar, fid)
            if a is None:
                a = ProjeAyar(firma_id=fid)
                session.add(a)
            for k in ("asama_aktif", "coklu_dagitim", "ortak_gider", "hakedis", "gorevler"):
                if k in veriler:
                    setattr(a, k, bool(veriler[k]))
            a.guncelleme = datetime.now()
        return cls.ayarlari_getir(firma_id=fid)

    @classmethod
    def _sonraki_kod(cls, session, firma_id: int, yil: int) -> str:
        onek = f"PRJ-{int(yil)}-"
        max_n = 0
        for kod in session.scalars(
            select(Proje.kod).where(Proje.firma_id == firma_id, Proje.kod.like(f"{onek}%"))
        ).all():
            m = _KOD_RE.match((kod or "").strip())
            if m and int(m.group(1)) == int(yil):
                max_n = max(max_n, int(m.group(2)))
        return f"{onek}{max_n + 1:04d}"

    @classmethod
    def olustur(
        cls,
        ad: str,
        *,
        kod: str | None = None,
        rapor_pb: str = "TRY",
        tur: str | None = None,
        grup: str | None = None,
        ana_musteri_id: int | None = None,
        sorumlu: str | None = None,
        baslangic: date | None = None,
        plan_bitis: date | None = None,
        hedef_gelir: Decimal | float | str = 0,
        hedef_maliyet: Decimal | float | str = 0,
        aciklama: str | None = None,
        firma_id: int | None = None,
    ) -> dict[str, Any]:
        cls.ensure_schema()
        ad = (ad or "").strip()
        if not ad:
            raise ValueError("Proje adı zorunludur.")
        fid = _firma_id(firma_id)
        pb = (rapor_pb or "TRY").upper()[:3]
        hg = Decimal(str(hedef_gelir or 0))
        hm = Decimal(str(hedef_maliyet or 0))
        with get_session() as session:
            yil = (baslangic or date.today()).year
            if kod and kod.strip():
                kullan_kod = kod.strip()[:30]
                var = session.scalar(
                    select(Proje.id).where(Proje.firma_id == fid, Proje.kod == kullan_kod)
                )
                if var is not None:
                    raise ValueError(f"Proje kodu zaten var: {kullan_kod}")
            else:
                kullan_kod = cls._sonraki_kod(session, fid, yil)
                for _ in range(5):
                    if (
                        session.scalar(
                            select(Proje.id).where(Proje.firma_id == fid, Proje.kod == kullan_kod)
                        )
                        is None
                    ):
                        break
                    kullan_kod = cls._sonraki_kod(session, fid, yil)
            p = Proje(
                firma_id=fid,
                kod=kullan_kod,
                ad=ad,
                tur=(tur or None),
                grup=(grup or None),
                ana_musteri_id=ana_musteri_id,
                sorumlu=sorumlu,
                baslangic=baslangic,
                plan_bitis=plan_bitis,
                durum=DURUM_AKTIF,
                rapor_pb=pb,
                hedef_gelir=hg,
                hedef_maliyet=hm,
                aciklama=aciklama,
                olusturma=datetime.now(),
                olusturan=_kullanici(),
            )
            session.add(p)
            session.flush()
            return cls._dict(p)

    @classmethod
    def listele(
        cls,
        *,
        firma_id: int | None = None,
        aktif_only: bool = True,
        arama: str | None = None,
    ) -> list[dict]:
        cls.ensure_schema()
        fid = _firma_id(firma_id)
        with get_session() as session:
            q = select(Proje).where(Proje.firma_id == fid)
            if aktif_only:
                q = q.where(Proje.aktif.is_(True))
            if arama:
                a = f"%{(arama or '').strip()}%"
                q = q.where(Proje.ad.like(a) | Proje.kod.like(a))
            q = q.order_by(Proje.id.desc())
            return [cls._dict(p) for p in session.scalars(q).all()]

    @classmethod
    def getir(cls, proje_id: int, *, firma_id: int | None = None) -> dict | None:
        cls.ensure_schema()
        fid = _firma_id(firma_id)
        with get_session() as session:
            p = session.get(Proje, int(proje_id))
            if p is None or int(p.firma_id) != fid:
                return None
            d = cls._dict(p)
            d["hedef_kar"] = str(Decimal(str(p.hedef_gelir or 0)) - Decimal(str(p.hedef_maliyet or 0)))
            gel = Decimal(str(p.hedef_gelir or 0))
            d["hedef_marj"] = (
                str(((gel - Decimal(str(p.hedef_maliyet or 0))) / gel * 100).quantize(Decimal("0.01")))
                if gel
                else "0"
            )
            d["baglanti_sayisi"] = sum(1 for b in (p.baglantilar or []) if b.aktif)
            return d

    @classmethod
    def guncelle(cls, proje_id: int, veriler: dict, *, firma_id: int | None = None) -> dict:
        cls.ensure_schema()
        fid = _firma_id(firma_id)
        with get_session() as session:
            p = session.get(Proje, int(proje_id))
            if p is None or int(p.firma_id) != fid:
                raise ValueError("Proje bulunamadı.")
            if "ad" in veriler and veriler["ad"]:
                p.ad = str(veriler["ad"]).strip()
            for k in (
                "kisa_ad",
                "tur",
                "grup",
                "sorumlu",
                "satis_temsilcisi",
                "aciklama",
            ):
                if k in veriler:
                    setattr(p, k, veriler[k] or None)
            if "durum" in veriler and veriler["durum"] in DURUMLAR:
                p.durum = veriler["durum"]
            if "rapor_pb" in veriler and veriler["rapor_pb"]:
                p.rapor_pb = str(veriler["rapor_pb"]).upper()[:3]
            if "ana_musteri_id" in veriler:
                p.ana_musteri_id = veriler["ana_musteri_id"]
            if "baslangic" in veriler:
                p.baslangic = veriler["baslangic"]
            if "plan_bitis" in veriler:
                p.plan_bitis = veriler["plan_bitis"]
            if "hedef_gelir" in veriler:
                p.hedef_gelir = Decimal(str(veriler["hedef_gelir"] or 0))
            if "hedef_maliyet" in veriler:
                p.hedef_maliyet = Decimal(str(veriler["hedef_maliyet"] or 0))
            if "aktif" in veriler:
                p.aktif = bool(veriler["aktif"])
            p.guncelleme = datetime.now()
            p.guncelleyen = _kullanici()
            session.flush()
            return cls._dict(p)

    @classmethod
    def belge_bagla(
        cls,
        proje_id: int,
        *,
        kaynak_tip: str,
        kaynak_id: str,
        kaynak_no: str | None = None,
        tutar_pay: Decimal | float | str | None = None,
        yuzde: Decimal | float | str | None = None,
        firma_id: int | None = None,
    ) -> dict:
        """Analitik etiket; fatura/stok/finans tutarını yeniden yazmaz."""
        cls.ensure_schema()
        fid = _firma_id(firma_id)
        with get_session() as session:
            p = session.get(Proje, int(proje_id))
            if p is None or int(p.firma_id) != fid:
                raise ValueError("Proje bulunamadı.")
            mevcut = session.scalar(
                select(ProjeBelgeBaglanti).where(
                    ProjeBelgeBaglanti.firma_id == fid,
                    ProjeBelgeBaglanti.kaynak_tip == kaynak_tip,
                    ProjeBelgeBaglanti.kaynak_id == str(kaynak_id),
                    ProjeBelgeBaglanti.proje_id == int(proje_id),
                    ProjeBelgeBaglanti.aktif.is_(True),
                )
            )
            if mevcut is not None:
                return {
                    "id": mevcut.id,
                    "yeni": False,
                    "proje_id": proje_id,
                    "kaynak_tip": kaynak_tip,
                    "kaynak_id": str(kaynak_id),
                }
            b = ProjeBelgeBaglanti(
                firma_id=fid,
                proje_id=int(proje_id),
                kaynak_tip=kaynak_tip,
                kaynak_id=str(kaynak_id),
                kaynak_no=kaynak_no,
                tutar_pay=Decimal(str(tutar_pay)) if tutar_pay is not None else None,
                yuzde=Decimal(str(yuzde)) if yuzde is not None else None,
                olusturma=datetime.now(),
                olusturan=_kullanici(),
            )
            session.add(b)
            session.flush()
            return {
                "id": b.id,
                "yeni": True,
                "proje_id": proje_id,
                "kaynak_tip": kaynak_tip,
                "kaynak_id": str(kaynak_id),
            }

    @classmethod
    def finansal_ozet(cls, proje_id: int, *, firma_id: int | None = None) -> dict:
        """Bağlı belge paylarından özet (gelir/gider motoru sonraki aşamada genişler)."""
        cls.ensure_schema()
        p = cls.getir(proje_id, firma_id=firma_id)
        if p is None:
            raise ValueError("Proje bulunamadı.")
        fid = _firma_id(firma_id)
        bagli = 0
        pay_toplam = Decimal("0")
        with get_session() as session:
            for b in session.scalars(
                select(ProjeBelgeBaglanti).where(
                    ProjeBelgeBaglanti.proje_id == int(proje_id),
                    ProjeBelgeBaglanti.firma_id == fid,
                    ProjeBelgeBaglanti.aktif.is_(True),
                )
            ).all():
                bagli += 1
                if b.tutar_pay is not None:
                    pay_toplam += Decimal(str(b.tutar_pay))
        return {
            "proje": p,
            "bagli_belge": bagli,
            "bagli_pay_toplam": str(pay_toplam),
            "hedef_gelir": p["hedef_gelir"],
            "hedef_maliyet": p["hedef_maliyet"],
            "hedef_kar": str(
                Decimal(str(p["hedef_gelir"])) - Decimal(str(p["hedef_maliyet"]))
            ),
            "not": "Tahakkuk/nakit ayrımı belge bağlama genişletmesiyle doldurulur; çift sayım yok.",
        }

    @classmethod
    def _dict(cls, p: Proje) -> dict[str, Any]:
        return {
            "id": p.id,
            "firma_id": p.firma_id,
            "kod": p.kod,
            "ad": p.ad,
            "kisa_ad": p.kisa_ad,
            "tur": p.tur,
            "grup": p.grup,
            "ana_proje_id": p.ana_proje_id,
            "ana_musteri_id": p.ana_musteri_id,
            "sorumlu": p.sorumlu,
            "satis_temsilcisi": p.satis_temsilcisi,
            "baslangic": p.baslangic,
            "plan_bitis": p.plan_bitis,
            "gercek_bitis": p.gercek_bitis,
            "durum": p.durum,
            "rapor_pb": p.rapor_pb,
            "hedef_gelir": str(p.hedef_gelir or 0),
            "hedef_maliyet": str(p.hedef_maliyet or 0),
            "aciklama": p.aciklama,
            "aktif": bool(p.aktif),
            "olusturma": p.olusturma,
            "olusturan": p.olusturan,
        }
