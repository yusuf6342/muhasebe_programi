"""Üretim servisi — reçete, emir, hızlı üretim (sarf + mamul).

Paket üretiminden bağımsız. Stok hareketleri: ÜRETİM SARF / ÜRETİM GİRİŞ.
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import selectinload

from database.access import yazma_zorunlu
from database.database import Base, engine, get_session
from database.models.stok import Depo, StokHareketi, StokKarti, StokLotu
from database.models.uretim import (
    UretimEmri,
    UretimEmriPlanSatir,
    UretimMamulGiris,
    UretimRecete,
    UretimReceteSatir,
    UretimRezervasyon,
    UretimSarfFisi,
    UretimSarfSatir,
)
from database.satis_siparisi_service import decimal
from database.stok_service import StokService

URETIM_SARF = "ÜRETİM SARF"
URETIM_GIRIS = "ÜRETİM GİRİŞ"


def brut_ihtiyac(net: Decimal, fire_orani: Decimal) -> Decimal:
    """Net / (1 - fire). Fire 0–0.9999."""
    net = decimal(net, "Net", Decimal("0"))
    fire = decimal(fire_orani, "Fire", Decimal("0"))
    if fire < 0 or fire >= 1:
        raise ValueError("Fire oranı 0 ile 1 arasında olmalıdır (örn. %2 → 0,02).")
    if fire == 0:
        return net.quantize(Decimal("0.000001"))
    return (net / (Decimal("1") - fire)).quantize(Decimal("0.000001"))


def plan_satir_miktari(
    recete_brut: Decimal,
    planlanan: Decimal,
    esas: Decimal,
) -> Decimal:
    """Reçete brüt × plan / esas çıktı."""
    esas = decimal(esas, "Esas", Decimal("0.000001"))
    if esas <= 0:
        raise ValueError("Reçete esas miktarı sıfırdan büyük olmalıdır.")
    return (
        decimal(recete_brut, "Brüt", Decimal("0"))
        * decimal(planlanan, "Plan", Decimal("0"))
        / esas
    ).quantize(Decimal("0.000001"))


class UretimService:
    _schema_hazir = False

    @classmethod
    def ensure_schema(cls, eng=None) -> None:
        bag = eng if eng is not None else engine
        if bag is None:
            return
        import database.models.uretim  # noqa: F401

        Base.metadata.create_all(
            bind=bag,
            tables=[
                UretimRecete.__table__,
                UretimReceteSatir.__table__,
                UretimEmri.__table__,
                UretimEmriPlanSatir.__table__,
                UretimSarfFisi.__table__,
                UretimSarfSatir.__table__,
                UretimMamulGiris.__table__,
                UretimRezervasyon.__table__,
            ],
        )
        # Hareket türlerini stok listelerine ekle (idempotent)
        from database import stok_service as ss

        if URETIM_GIRIS not in ss.GIRIS_HAREKETLERI:
            ss.GIRIS_HAREKETLERI = tuple(ss.GIRIS_HAREKETLERI) + (URETIM_GIRIS,)
        if URETIM_SARF not in ss.CIKIS_HAREKETLERI:
            ss.CIKIS_HAREKETLERI = tuple(ss.CIKIS_HAREKETLERI) + (URETIM_SARF,)
        cls._schema_hazir = True

    @staticmethod
    def emir_no() -> str:
        UretimService.ensure_schema()
        with get_session() as session:
            n = session.scalar(select(func.count()).select_from(UretimEmri)) or 0
        return f"UE-{date.today():%Y%m%d}-{int(n) + 1:04d}"

    @staticmethod
    def fis_no(onek: str) -> str:
        UretimService.ensure_schema()
        with get_session() as session:
            if onek == "US":
                n = session.scalar(select(func.count()).select_from(UretimSarfFisi)) or 0
            else:
                n = session.scalar(select(func.count()).select_from(UretimMamulGiris)) or 0
        return f"{onek}-{date.today():%Y%m%d}-{int(n) + 1:04d}"

    @staticmethod
    def recete_listesi(*, durum: str | None = None) -> list[dict[str, Any]]:
        UretimService.ensure_schema()
        with get_session() as session:
            q = (
                select(UretimRecete)
                .where(UretimRecete.is_deleted.is_(False))
                .options(selectinload(UretimRecete.satirlar))
                .order_by(UretimRecete.recete_kodu, UretimRecete.surum.desc())
            )
            if durum:
                q = q.where(UretimRecete.durum == durum)
            sonuc = []
            for r in session.scalars(q).all():
                sonuc.append(
                    {
                        "id": int(r.id),
                        "recete_kodu": r.recete_kodu,
                        "mamul_stok_kodu": r.mamul_stok_kodu,
                        "esas_miktar": r.esas_miktar,
                        "cikti_birimi": r.cikti_birimi,
                        "surum": int(r.surum),
                        "durum": r.durum,
                        "satir_adet": len(r.satirlar or []),
                        "aciklama": r.aciklama,
                    }
                )
            return sonuc

    @staticmethod
    def recete_getir(recete_id: int) -> dict[str, Any] | None:
        UretimService.ensure_schema()
        with get_session() as session:
            r = session.scalar(
                select(UretimRecete)
                .where(UretimRecete.id == int(recete_id), UretimRecete.is_deleted.is_(False))
                .options(selectinload(UretimRecete.satirlar))
            )
            if r is None:
                return None
            return {
                "id": int(r.id),
                "recete_kodu": r.recete_kodu,
                "mamul_stok_id": int(r.mamul_stok_id),
                "mamul_stok_kodu": r.mamul_stok_kodu,
                "esas_miktar": r.esas_miktar,
                "cikti_birimi": r.cikti_birimi,
                "surum": int(r.surum),
                "durum": r.durum,
                "aciklama": r.aciklama,
                "satirlar": [
                    {
                        "id": int(s.id),
                        "sira": int(s.sira),
                        "malzeme_stok_id": int(s.malzeme_stok_id),
                        "malzeme_stok_kodu": s.malzeme_stok_kodu,
                        "birim": s.birim,
                        "net_miktar": s.net_miktar,
                        "fire_orani": s.fire_orani,
                        "brut_miktar": brut_ihtiyac(s.net_miktar, s.fire_orani),
                        "kaynak_depo": s.kaynak_depo,
                        "aciklama": s.aciklama,
                    }
                    for s in (r.satirlar or [])
                ],
            }

    @staticmethod
    def recete_kaydet(veriler: dict[str, Any], satirlar: list[dict[str, Any]]) -> dict[str, Any]:
        yazma_zorunlu("stok_duzenleme", "yeni_kayit")
        UretimService.ensure_schema()
        kod = (veriler.get("recete_kodu") or "").strip()
        mamul_kod = (veriler.get("mamul_stok_kodu") or "").strip()
        if not kod:
            raise ValueError("Reçete kodu zorunludur.")
        if not mamul_kod:
            raise ValueError("Mamul stok kodu zorunludur.")
        if not satirlar:
            raise ValueError("En az bir malzeme satırı ekleyin.")
        esas = decimal(veriler.get("esas_miktar") or 1, "Esas miktar", Decimal("0.000001"))
        if esas <= 0:
            raise ValueError("Esas miktar pozitif olmalıdır.")

        with get_session() as session:
            mamul = session.scalar(
                select(StokKarti).where(
                    StokKarti.stok_kodu == mamul_kod, StokKarti.is_deleted.is_(False)
                )
            )
            if mamul is None:
                raise ValueError(f"Mamul stok bulunamadı: {mamul_kod}")

            # Döngü: mamul kendisini malzeme olarak kullanamaz
            for s in satirlar:
                if (s.get("malzeme_stok_kodu") or "").strip() == mamul_kod:
                    raise ValueError("Reçete mamulü kendi malzemesi olamaz.")

            rid = veriler.get("id")
            if rid:
                recete = session.get(UretimRecete, int(rid))
                if recete is None or recete.is_deleted:
                    raise ValueError("Reçete bulunamadı.")
                if recete.durum == "AKTIF":
                    raise ValueError(
                        "Aktif reçete yerinde değiştirilemez. Yeni sürüm oluşturun."
                    )
                recete.satirlar.clear()
            else:
                son_surum = session.scalar(
                    select(func.max(UretimRecete.surum)).where(
                        UretimRecete.recete_kodu == kod,
                        UretimRecete.is_deleted.is_(False),
                    )
                )
                surum = int(veriler.get("surum") or ((son_surum or 0) + 1))
                recete = UretimRecete(
                    recete_kodu=kod,
                    surum=surum,
                    durum=(veriler.get("durum") or "TASLAK").upper(),
                )
                session.add(recete)

            recete.mamul_stok_id = int(mamul.id)
            recete.mamul_stok_kodu = mamul.stok_kodu
            recete.esas_miktar = esas
            recete.cikti_birimi = (veriler.get("cikti_birimi") or mamul.birim or "Adet").strip()
            recete.aciklama = (veriler.get("aciklama") or "").strip() or None
            recete.updated_at = datetime.now()
            if veriler.get("durum"):
                recete.durum = str(veriler["durum"]).upper()

            for i, s in enumerate(satirlar, start=1):
                mkod = (s.get("malzeme_stok_kodu") or "").strip()
                malzeme = session.scalar(
                    select(StokKarti).where(
                        StokKarti.stok_kodu == mkod, StokKarti.is_deleted.is_(False)
                    )
                )
                if malzeme is None:
                    raise ValueError(f"Malzeme stok bulunamadı: {mkod}")
                net = decimal(s.get("net_miktar") or 0, "Net miktar", Decimal("0"))
                fire = decimal(s.get("fire_orani") or 0, "Fire", Decimal("0"))
                if fire > 1:
                    fire = fire / Decimal("100")  # %2 → 0.02
                _ = brut_ihtiyac(net, fire)  # doğrula
                recete.satirlar.append(
                    UretimReceteSatir(
                        sira=i,
                        malzeme_stok_id=int(malzeme.id),
                        malzeme_stok_kodu=malzeme.stok_kodu,
                        birim=(s.get("birim") or malzeme.birim or "Adet").strip(),
                        net_miktar=net,
                        fire_orani=fire,
                        kaynak_depo=(s.get("kaynak_depo") or "").strip() or None,
                        aciklama=(s.get("aciklama") or "").strip() or None,
                    )
                )
            session.flush()
            rid = int(recete.id)
        return UretimService.recete_getir(rid) or {"id": rid}

    @staticmethod
    def recete_aktiflestir(recete_id: int) -> dict[str, Any]:
        yazma_zorunlu("stok_duzenleme")
        UretimService.ensure_schema()
        with get_session() as session:
            r = session.get(UretimRecete, int(recete_id))
            if r is None or r.is_deleted:
                raise ValueError("Reçete bulunamadı.")
            if not r.satirlar:
                raise ValueError("Satırsız reçete aktifleştirilemez.")
            # Aynı kodun diğer aktiflerini pasifle
            diger = session.scalars(
                select(UretimRecete).where(
                    UretimRecete.recete_kodu == r.recete_kodu,
                    UretimRecete.id != r.id,
                    UretimRecete.durum == "AKTIF",
                    UretimRecete.is_deleted.is_(False),
                )
            ).all()
            for d in diger:
                d.durum = "PASIF"
            r.durum = "AKTIF"
            r.updated_at = datetime.now()
            session.flush()
            rid = int(r.id)
        return UretimService.recete_getir(rid) or {"id": rid}

    @staticmethod
    def _aktif_rezervasyonlar(
        *,
        stok_kodu: str | None = None,
        depo: str | None = None,
        emir_id: int | None = None,
        haric_emir_id: int | None = None,
    ) -> Decimal:
        """Aktif rezervasyon toplamı (aynı emrin rezervasyonu ikinci kez düşülmesin diye haric)."""
        with get_session() as session:
            q = select(func.coalesce(func.sum(UretimRezervasyon.miktar), 0)).where(
                UretimRezervasyon.durum == "AKTIF"
            )
            if stok_kodu:
                q = q.where(UretimRezervasyon.malzeme_stok_kodu == stok_kodu)
            if depo:
                q = q.where(UretimRezervasyon.depo == depo)
            if emir_id is not None:
                q = q.where(UretimRezervasyon.emir_id == int(emir_id))
            if haric_emir_id is not None:
                q = q.where(UretimRezervasyon.emir_id != int(haric_emir_id))
            return decimal(session.scalar(q) or 0, "R", Decimal("0"))

    @staticmethod
    def ihtiyac_hesapla(
        recete_id: int,
        planlanan_miktar,
        *,
        depo: str = "ANA DEPO",
        emir_id: int | None = None,
    ) -> list[dict]:
        UretimService.ensure_schema()
        recete = UretimService.recete_getir(int(recete_id))
        if not recete:
            raise ValueError("Reçete bulunamadı.")
        plan = decimal(planlanan_miktar, "Planlanan", Decimal("0.000001"))
        if plan <= 0:
            raise ValueError("Planlanan miktar pozitif olmalıdır.")
        esas = decimal(recete["esas_miktar"], "Esas", Decimal("1"))
        satirlar = []
        for s in recete["satirlar"]:
            brut = brut_ihtiyac(s["net_miktar"], s["fire_orani"])
            gereken = plan_satir_miktari(brut, plan, esas)
            depo_adi = (s.get("kaynak_depo") or depo or "ANA DEPO").strip()
            lotlar = StokService.lotlar(s["malzeme_stok_kodu"], depo_adi) or []
            mevcut = sum(
                (decimal(getattr(l, "kalan_miktar", 0), "M", Decimal("0")) for l in lotlar),
                Decimal("0"),
            )
            baska_rez = UretimService._aktif_rezervasyonlar(
                stok_kodu=s["malzeme_stok_kodu"],
                depo=depo_adi,
                haric_emir_id=emir_id,
            )
            bu_rez = (
                UretimService._aktif_rezervasyonlar(
                    stok_kodu=s["malzeme_stok_kodu"],
                    depo=depo_adi,
                    emir_id=emir_id,
                )
                if emir_id
                else Decimal("0")
            )
            # Kullanılabilir: fiziksel − diğer emir rezervleri (bu emrin rezervi ikinci kez düşülmez)
            kullanilabilir = max(Decimal("0"), mevcut - baska_rez)
            maliyetler = StokService.maliyetler(s["malzeme_stok_kodu"], depo_adi) or {}
            fifo = decimal(maliyetler.get("fifo") or 0, "F", Decimal("0"))
            satirlar.append(
                {
                    "malzeme_stok_kodu": s["malzeme_stok_kodu"],
                    "birim": s["birim"],
                    "gereken": gereken,
                    "mevcut": mevcut,
                    "baska_rezervasyon": baska_rez,
                    "bu_emir_rezervasyon": bu_rez,
                    "kullanilabilir": kullanilabilir,
                    "eksik": max(Decimal("0"), gereken - kullanilabilir),
                    "tahmini_maliyet": (gereken * fifo).quantize(Decimal("0.01")),
                    "kaynak_depo": depo_adi,
                    "fire_orani": s["fire_orani"],
                }
            )
        return satirlar

    @staticmethod
    def rezervasyon_yap(emir_id: int) -> dict[str, Any]:
        """Mevcut kullanılabilir stoğu emre ayırır; muhasebe/stok hareketi yok."""
        yazma_zorunlu("stok_duzenleme", "yeni_kayit")
        UretimService.ensure_schema()
        with get_session() as session:
            emir = session.get(UretimEmri, int(emir_id))
            if emir is None or emir.is_deleted:
                raise ValueError("Üretim emri bulunamadı.")
            if emir.durum in ("KAPALI", "IPTAL"):
                raise ValueError("Kapalı/iptal emre rezervasyon yapılamaz.")
            ihtiyac = UretimService.ihtiyac_hesapla(
                int(emir.recete_id),
                emir.planlanan_miktar,
                depo=emir.kaynak_depo,
                emir_id=int(emir.id),
            )
            olusan = []
            for s in ihtiyac:
                kod = s["malzeme_stok_kodu"]
                depo = s["kaynak_depo"]
                gereken = decimal(s["gereken"], "G", Decimal("0"))
                bu = decimal(s["bu_emir_rezervasyon"], "B", Decimal("0"))
                kalan_ihtiyac = max(Decimal("0"), gereken - bu)
                ayrilacak = min(kalan_ihtiyac, decimal(s["kullanilabilir"], "K", Decimal("0")))
                if ayrilacak <= 0:
                    continue
                # Aynı stok+depo aktif satırı güncelle
                mevcut = session.scalar(
                    select(UretimRezervasyon).where(
                        UretimRezervasyon.emir_id == int(emir.id),
                        UretimRezervasyon.malzeme_stok_kodu == kod,
                        UretimRezervasyon.depo == depo,
                        UretimRezervasyon.durum == "AKTIF",
                    )
                )
                if mevcut:
                    mevcut.miktar = decimal(mevcut.miktar, "M", Decimal("0")) + ayrilacak
                    mevcut.updated_at = datetime.now()
                else:
                    session.add(
                        UretimRezervasyon(
                            emir_id=int(emir.id),
                            malzeme_stok_kodu=kod,
                            depo=depo,
                            miktar=ayrilacak,
                            durum="AKTIF",
                        )
                    )
                olusan.append({"stok": kod, "depo": depo, "miktar": ayrilacak})
            session.flush()
            return {
                "emir_id": int(emir.id),
                "emir_no": emir.emir_no,
                "rezervasyonlar": olusan,
                "not": "Rezervasyon stok hareketi veya muhasebe fişi oluşturmaz.",
            }

    @staticmethod
    def rezervasyon_serbest(emir_id: int) -> dict[str, Any]:
        yazma_zorunlu("stok_duzenleme", "yeni_kayit")
        UretimService.ensure_schema()
        with get_session() as session:
            kayitlar = list(
                session.scalars(
                    select(UretimRezervasyon).where(
                        UretimRezervasyon.emir_id == int(emir_id),
                        UretimRezervasyon.durum == "AKTIF",
                    )
                ).all()
            )
            for r in kayitlar:
                r.durum = "SERBEST"
                r.updated_at = datetime.now()
            session.flush()
            return {"emir_id": int(emir_id), "serbest_adet": len(kayitlar)}

    @staticmethod
    def emir_listesi(*, limit: int = 100) -> list[dict[str, Any]]:
        UretimService.ensure_schema()
        with get_session() as session:
            q = (
                select(UretimEmri)
                .where(UretimEmri.is_deleted.is_(False))
                .order_by(UretimEmri.tarih.desc(), UretimEmri.id.desc())
                .limit(limit)
            )
            return [
                {
                    "id": int(e.id),
                    "emir_no": e.emir_no,
                    "tarih": e.tarih,
                    "mamul_stok_kodu": e.mamul_stok_kodu,
                    "planlanan_miktar": e.planlanan_miktar,
                    "uretilen_miktar": e.uretilen_miktar,
                    "birim": e.birim,
                    "durum": e.durum,
                    "maliyet_durumu": e.maliyet_durumu,
                    "uretim_bicimi": e.uretim_bicimi,
                    "kaynak_depo": e.kaynak_depo,
                    "mamul_depo": e.mamul_depo,
                }
                for e in session.scalars(q).all()
            ]

    @staticmethod
    def emir_olustur(veriler: dict[str, Any]) -> dict[str, Any]:
        yazma_zorunlu("stok_duzenleme", "yeni_kayit")
        UretimService.ensure_schema()
        rid = int(veriler["recete_id"])
        plan = decimal(veriler.get("planlanan_miktar") or 0, "Plan", Decimal("0.000001"))
        if plan <= 0:
            raise ValueError("Planlanan miktar pozitif olmalıdır.")
        recete = UretimService.recete_getir(rid)
        if not recete:
            raise ValueError("Reçete bulunamadı.")
        if recete["durum"] != "AKTIF":
            raise ValueError("Yalnızca aktif reçete ile emir açılır.")

        kaynak = (veriler.get("kaynak_depo") or "ANA DEPO").strip()
        mamul_depo = (veriler.get("mamul_depo") or kaynak).strip()
        tarih = veriler.get("tarih") or date.today()
        if isinstance(tarih, str):
            from fatura_belge_aktarim.normalize import tarih_tr

            tarih = tarih_tr(tarih) or date.today()

        ihtiyac = UretimService.ihtiyac_hesapla(rid, plan, depo=kaynak)
        tahmini = sum((s["tahmini_maliyet"] for s in ihtiyac), Decimal("0"))

        with get_session() as session:
            emir = UretimEmri(
                emir_no=(veriler.get("emir_no") or "").strip() or UretimService.emir_no(),
                tarih=tarih,
                uretim_bicimi=(veriler.get("uretim_bicimi") or "HIZLI").upper(),
                recete_id=rid,
                recete_surum=int(recete["surum"]),
                mamul_stok_id=int(recete["mamul_stok_id"]),
                mamul_stok_kodu=recete["mamul_stok_kodu"],
                planlanan_miktar=plan,
                birim=recete["cikti_birimi"],
                kaynak_depo=kaynak,
                mamul_depo=mamul_depo,
                durum="PLANLANDI",
                maliyet_durumu="TAHMINI",
                tahmini_maliyet=tahmini,
                aciklama=(veriler.get("aciklama") or "").strip() or None,
            )
            session.add(emir)
            session.flush()
            for i, s in enumerate(recete["satirlar"], start=1):
                brut = brut_ihtiyac(s["net_miktar"], s["fire_orani"])
                gereken = plan_satir_miktari(brut, plan, recete["esas_miktar"])
                emir.plan_satirlari.append(
                    UretimEmriPlanSatir(
                        sira=i,
                        malzeme_stok_id=int(s["malzeme_stok_id"]),
                        malzeme_stok_kodu=s["malzeme_stok_kodu"],
                        birim=s["birim"],
                        plan_miktar=gereken,
                        fire_orani=s["fire_orani"],
                        kaynak_depo=s.get("kaynak_depo") or kaynak,
                        aciklama=s.get("aciklama"),
                    )
                )
            session.flush()
            eid = int(emir.id)
            eno = emir.emir_no
        return {"id": eid, "emir_no": eno, "tahmini_maliyet": tahmini, "ihtiyac": ihtiyac}

    @staticmethod
    def _uretim_sarf(
        session,
        *,
        belge_no: str,
        tarih: date,
        stok_kodu: str,
        depo_adi: str,
        miktar: Decimal,
    ) -> dict[str, Any]:
        stok = session.scalar(select(StokKarti).where(StokKarti.stok_kodu == stok_kodu))
        depo = session.scalar(select(Depo).where(Depo.ad == depo_adi))
        if not stok:
            raise ValueError(f"{stok_kodu} stok kartı yok.")
        if not depo:
            raise ValueError(f"{depo_adi} deposu yok.")
        miktar = decimal(miktar, "Sarf", Decimal("0.0001"))
        lotlar = list(
            session.scalars(
                select(StokLotu)
                .where(
                    StokLotu.stok_id == stok.id,
                    StokLotu.depo_id == depo.id,
                    StokLotu.kalan_miktar > 0,
                )
                .order_by(StokLotu.giris_tarihi, StokLotu.id)
            ).all()
        )
        mevcut = sum((lot.kalan_miktar for lot in lotlar), Decimal("0"))
        if mevcut < miktar:
            raise ValueError(
                f"{stok.stok_adi} / {depo.ad} yetersiz. Mevcut: {mevcut}, gereken: {miktar}"
            )
        kalan, maliyet, kullanilan = miktar, Decimal("0"), []
        for lot in lotlar:
            if kalan <= 0:
                break
            cikan = min(kalan, lot.kalan_miktar)
            lot.kalan_miktar -= cikan
            kalan -= cikan
            maliyet += cikan * lot.birim_maliyet
            kullanilan.append(f"{lot.lot_no}:{cikan}")
            session.add(
                StokHareketi(
                    tarih=tarih,
                    hareket_turu=URETIM_SARF,
                    belge_no=belge_no,
                    stok_id=stok.id,
                    depo_id=depo.id,
                    lot_id=lot.id,
                    miktar=cikan,
                    birim_maliyet=lot.birim_maliyet,
                )
            )
        return {
            "lot_cikisi": ", ".join(kullanilan),
            "fifo_birim_maliyeti": (maliyet / miktar) if miktar else Decimal("0"),
            "tutar": maliyet.quantize(Decimal("0.01")),
            "stok_id": int(stok.id),
        }

    @staticmethod
    def _uretim_giris(
        session,
        *,
        belge_no: str,
        tarih: date,
        stok_kodu: str,
        depo_adi: str,
        miktar: Decimal,
        birim_maliyet: Decimal,
        lot_no: str = "",
    ) -> dict[str, Any]:
        # Mevcut fatura girişini kullan; hareket türünü üretim olarak yaz
        stok = session.scalar(select(StokKarti).where(StokKarti.stok_kodu == stok_kodu))
        depo = session.scalar(select(Depo).where(Depo.ad == depo_adi))
        if not stok or not depo:
            raise ValueError("Mamul stok veya depo bulunamadı.")
        miktar = decimal(miktar, "Giriş", Decimal("0.0001"))
        maliyet = decimal(birim_maliyet, "Maliyet", Decimal("0"))
        temel = (lot_no or "").strip() or StokService.otomatik_lot_no("URETIM", tarih)
        lot_adi, sira = temel, 1
        while session.scalar(
            select(StokLotu).where(
                StokLotu.stok_id == stok.id,
                StokLotu.depo_id == depo.id,
                StokLotu.lot_no == lot_adi,
            )
        ):
            sira += 1
            lot_adi = f"{temel}-{sira}"
        lot = StokLotu(
            stok_id=stok.id,
            depo_id=depo.id,
            lot_no=lot_adi,
            tedarikci="ÜRETİM",
            giris_tarihi=tarih,
            kalan_miktar=miktar,
            birim_maliyet=maliyet,
        )
        session.add(lot)
        session.flush()
        session.add(
            StokHareketi(
                tarih=tarih,
                hareket_turu=URETIM_GIRIS,
                belge_no=belge_no,
                stok_id=stok.id,
                depo_id=depo.id,
                lot_id=lot.id,
                miktar=miktar,
                birim_maliyet=maliyet,
            )
        )
        return {"lot_girisi": lot_adi, "birim_maliyet": maliyet}

    @staticmethod
    def hizli_uret(emir_id: int) -> dict[str, Any]:
        """Plan satırlarının tamamını sarf eder, planlanan mamulü stoğa alır (tek işlem)."""
        yazma_zorunlu("stok_duzenleme", "yeni_kayit")
        UretimService.ensure_schema()
        with get_session() as session:
            emir = session.scalar(
                select(UretimEmri)
                .where(UretimEmri.id == int(emir_id), UretimEmri.is_deleted.is_(False))
                .options(selectinload(UretimEmri.plan_satirlari))
            )
            if emir is None:
                raise ValueError("Üretim emri bulunamadı.")
            if emir.durum in ("KAPALI", "IPTAL"):
                raise ValueError(f"Emir {emir.durum}; hızlı üretim yapılamaz.")
            if emir.uretilen_miktar and emir.uretilen_miktar > 0:
                raise ValueError("Bu emirde zaten mamul girişi var; mükerrer üretim engellendi.")

            tarih = emir.tarih or date.today()
            sarf_no = UretimService.fis_no("US")
            mamul_no = UretimService.fis_no("UM")
            # Aynı transaction içinde numaraları sabitle — count yarışını azalt
            sarf = UretimSarfFisi(
                fis_no=sarf_no,
                emir_id=int(emir.id),
                tarih=tarih,
                depo=emir.kaynak_depo,
            )
            session.add(sarf)
            session.flush()

            toplam_sarf = Decimal("0")
            for ps in emir.plan_satirlari:
                depo = (ps.kaynak_depo or emir.kaynak_depo or "ANA DEPO").strip()
                sonuc = UretimService._uretim_sarf(
                    session,
                    belge_no=sarf_no,
                    tarih=tarih,
                    stok_kodu=ps.malzeme_stok_kodu,
                    depo_adi=depo,
                    miktar=ps.plan_miktar,
                )
                tutar = sonuc["tutar"]
                toplam_sarf += tutar
                sarf.satirlar.append(
                    UretimSarfSatir(
                        malzeme_stok_id=int(ps.malzeme_stok_id),
                        malzeme_stok_kodu=ps.malzeme_stok_kodu,
                        miktar=ps.plan_miktar,
                        birim=ps.birim,
                        birim_maliyet=sonuc["fifo_birim_maliyeti"],
                        tutar=tutar,
                        lot_cikisi=sonuc["lot_cikisi"],
                    )
                )
            sarf.toplam_maliyet = toplam_sarf

            miktar = decimal(emir.planlanan_miktar, "Miktar", Decimal("0.0001"))
            birim_maliyet = (
                (toplam_sarf / miktar).quantize(Decimal("0.0001")) if miktar else Decimal("0")
            )
            giris = UretimService._uretim_giris(
                session,
                belge_no=mamul_no,
                tarih=tarih,
                stok_kodu=emir.mamul_stok_kodu,
                depo_adi=emir.mamul_depo,
                miktar=miktar,
                birim_maliyet=birim_maliyet,
                lot_no=f"UE{emir.emir_no}",
            )
            session.add(
                UretimMamulGiris(
                    fis_no=mamul_no,
                    emir_id=int(emir.id),
                    tarih=tarih,
                    mamul_stok_id=int(emir.mamul_stok_id),
                    mamul_stok_kodu=emir.mamul_stok_kodu,
                    miktar=miktar,
                    birim=emir.birim,
                    depo=emir.mamul_depo,
                    birim_maliyet=birim_maliyet,
                    toplam_maliyet=toplam_sarf,
                    parti_no=emir.emir_no,
                    lot_girisi=giris["lot_girisi"],
                )
            )
            emir.uretilen_miktar = miktar
            emir.gercek_maliyet = toplam_sarf
            emir.durum = "KAPALI"
            emir.maliyet_durumu = "GECICI"
            emir.updated_at = datetime.now()
            # Rezervasyonlar tüketildi (stok zaten sarf ile çıktı)
            for rez in session.scalars(
                select(UretimRezervasyon).where(
                    UretimRezervasyon.emir_id == int(emir.id),
                    UretimRezervasyon.durum == "AKTIF",
                )
            ).all():
                rez.durum = "TUKETILDI"
                rez.updated_at = datetime.now()
            session.flush()
            return {
                "emir_id": int(emir.id),
                "emir_no": emir.emir_no,
                "sarf_fis_no": sarf_no,
                "mamul_fis_no": mamul_no,
                "uretilen_miktar": miktar,
                "toplam_maliyet": toplam_sarf,
                "birim_maliyet": birim_maliyet,
                "lot_girisi": giris["lot_girisi"],
                "maliyet_durumu": emir.maliyet_durumu,
            }

    @staticmethod
    def maliyet_kesinlestir(emir_id: int) -> dict[str, Any]:
        """GECICI → KESIN. Fiziksel kapalı emirde bekleyen gider yoksa kesinleşir.

        İlk sürüm: ek gider/işçilik faturası bağlı değilse KESIN; varsa uyarı ile engel.
        """
        yazma_zorunlu("stok_duzenleme", "yeni_kayit")
        UretimService.ensure_schema()
        with get_session() as session:
            emir = session.get(UretimEmri, int(emir_id))
            if emir is None or emir.is_deleted:
                raise ValueError("Üretim emri bulunamadı.")
            if emir.durum != "KAPALI":
                raise ValueError("Yalnız kapalı emirde maliyet kesinleştirilebilir.")
            durum = (emir.maliyet_durumu or "").upper()
            if durum == "KESIN":
                return {
                    "emir_id": int(emir.id),
                    "emir_no": emir.emir_no,
                    "maliyet_durumu": "KESIN",
                    "zaten_kesin": True,
                }
            if durum not in {"GECICI", "TAHMINI"}:
                raise ValueError(f"Maliyet durumu {emir.maliyet_durumu}; kesinleştirilemez.")
            # Bekleyen üretim gideri bağlantısı (varsa) — tablo yoksa atla
            bekleyen = 0
            try:
                from sqlalchemy import text as _text

                bekleyen = int(
                    session.scalar(
                        _text(
                            "SELECT COUNT(1) FROM uretim_gider_dagitimlari "
                            "WHERE emir_id=:eid AND durum IN ('BEKLIYOR','TASLAK')"
                        ),
                        {"eid": int(emir.id)},
                    )
                    or 0
                )
            except Exception:
                bekleyen = 0
            if bekleyen > 0:
                raise ValueError(
                    f"{bekleyen} bekleyen üretim gider dağıtımı var; önce tamamlayın."
                )
            emir.maliyet_durumu = "KESIN"
            emir.updated_at = datetime.now()
            session.flush()
            return {
                "emir_id": int(emir.id),
                "emir_no": emir.emir_no,
                "maliyet_durumu": "KESIN",
                "gercek_maliyet": emir.gercek_maliyet,
                "zaten_kesin": False,
            }

    @staticmethod
    def kismi_uret(emir_id: int, miktar: Decimal) -> dict[str, Any]:
        """Kısmi mamul girişi: plan oranında sarf + mamul; emir AÇIK kalır (GECICI)."""
        yazma_zorunlu("stok_duzenleme", "yeni_kayit")
        UretimService.ensure_schema()
        hedef = decimal(miktar, "Üretim miktarı", Decimal("0.0001"))
        if hedef <= 0:
            raise ValueError("Kısmi üretim miktarı pozitif olmalı.")
        with get_session() as session:
            emir = session.scalar(
                select(UretimEmri)
                .where(UretimEmri.id == int(emir_id), UretimEmri.is_deleted.is_(False))
                .options(selectinload(UretimEmri.plan_satirlari))
            )
            if emir is None:
                raise ValueError("Üretim emri bulunamadı.")
            if emir.durum in ("KAPALI", "IPTAL"):
                raise ValueError(f"Emir {emir.durum}; kısmi üretim yapılamaz.")
            plan = decimal(emir.planlanan_miktar or 0, "Plan", Decimal("0"))
            if plan <= 0:
                raise ValueError("Planlanan miktar yok.")
            uretilen = decimal(emir.uretilen_miktar or 0, "Üretilen", Decimal("0"))
            kalan = plan - uretilen
            if hedef > kalan:
                raise ValueError(f"Kalan plan {kalan}; {hedef} aşılamaz.")
            oran = (hedef / plan).quantize(Decimal("0.00000001"))
            tarih = emir.tarih or date.today()
            sarf_no = UretimService.fis_no("US")
            mamul_no = UretimService.fis_no("UM")
            sarf = UretimSarfFisi(
                fis_no=sarf_no, emir_id=int(emir.id), tarih=tarih, depo=emir.kaynak_depo
            )
            session.add(sarf)
            session.flush()
            toplam_sarf = Decimal("0")
            for ps in emir.plan_satirlari:
                mik = (decimal(ps.plan_miktar or 0, "P", Decimal("0")) * oran).quantize(
                    Decimal("0.0001")
                )
                if mik <= 0:
                    continue
                depo = (ps.kaynak_depo or emir.kaynak_depo or "ANA DEPO").strip()
                sonuc = UretimService._uretim_sarf(
                    session,
                    belge_no=sarf_no,
                    tarih=tarih,
                    stok_kodu=ps.malzeme_stok_kodu,
                    depo_adi=depo,
                    miktar=mik,
                )
                tutar = sonuc["tutar"]
                toplam_sarf += tutar
                sarf.satirlar.append(
                    UretimSarfSatir(
                        malzeme_stok_id=int(ps.malzeme_stok_id),
                        malzeme_stok_kodu=ps.malzeme_stok_kodu,
                        miktar=mik,
                        birim=ps.birim,
                        birim_maliyet=sonuc["fifo_birim_maliyeti"],
                        tutar=tutar,
                        lot_cikisi=sonuc["lot_cikisi"],
                    )
                )
            sarf.toplam_maliyet = toplam_sarf
            birim_maliyet = (
                (toplam_sarf / hedef).quantize(Decimal("0.0001")) if hedef else Decimal("0")
            )
            giris = UretimService._uretim_giris(
                session,
                belge_no=mamul_no,
                tarih=tarih,
                stok_kodu=emir.mamul_stok_kodu,
                depo_adi=emir.mamul_depo,
                miktar=hedef,
                birim_maliyet=birim_maliyet,
                lot_no=f"UE{emir.emir_no}-{uretilen + hedef}",
            )
            session.add(
                UretimMamulGiris(
                    fis_no=mamul_no,
                    emir_id=int(emir.id),
                    tarih=tarih,
                    mamul_stok_id=int(emir.mamul_stok_id),
                    mamul_stok_kodu=emir.mamul_stok_kodu,
                    miktar=hedef,
                    birim=emir.birim,
                    depo=emir.mamul_depo,
                    birim_maliyet=birim_maliyet,
                    toplam_maliyet=toplam_sarf,
                    parti_no=f"{emir.emir_no}-{uretilen + hedef}",
                    lot_girisi=giris["lot_girisi"],
                )
            )
            emir.uretilen_miktar = uretilen + hedef
            emir.gercek_maliyet = decimal(emir.gercek_maliyet or 0, "G", Decimal("0")) + toplam_sarf
            emir.maliyet_durumu = "GECICI"
            if emir.uretilen_miktar >= plan:
                emir.durum = "KAPALI"
                for rez in session.scalars(
                    select(UretimRezervasyon).where(
                        UretimRezervasyon.emir_id == int(emir.id),
                        UretimRezervasyon.durum == "AKTIF",
                    )
                ).all():
                    rez.durum = "TUKETILDI"
                    rez.updated_at = datetime.now()
            else:
                emir.durum = "URETIMDE"
                # Kısmi: rezervasyonu oransal azalt
                for rez in session.scalars(
                    select(UretimRezervasyon).where(
                        UretimRezervasyon.emir_id == int(emir.id),
                        UretimRezervasyon.durum == "AKTIF",
                    )
                ).all():
                    eski = decimal(rez.miktar or 0, "R", Decimal("0"))
                    rez.miktar = max(Decimal("0"), (eski * (1 - oran)).quantize(Decimal("0.0001")))
                    rez.updated_at = datetime.now()
            emir.updated_at = datetime.now()
            session.flush()
            return {
                "emir_id": int(emir.id),
                "emir_no": emir.emir_no,
                "uretilen_miktar": emir.uretilen_miktar,
                "bu_giris": hedef,
                "toplam_maliyet": toplam_sarf,
                "maliyet_durumu": emir.maliyet_durumu,
                "durum": emir.durum,
                "sarf_fis_no": sarf_no,
                "mamul_fis_no": mamul_no,
            }
