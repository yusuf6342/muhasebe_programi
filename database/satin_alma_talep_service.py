"""Satın alma talebi: kayıt, onay akışı, siparişe aktarım payları ve teslim takibi.

Talep stok, cari, KDV veya genel muhasebe hareketi üretmez. Siparişe aktarım satır
bazında ``SatinAlmaTalepSiparisBagi`` ile izlenir; pay yalnızca sipariş kaydedildiğinde
tüketilir, sipariş satırı silinir/azaltılır ya da sipariş iptal edilirse geri açılır.
Teslim miktarı sipariş satırının irsaliye/fatura sayaçlarından (büyük olanı) okunur;
irsaliye + fatura aynı malı iki kez saymaz.
"""

from __future__ import annotations

import shutil
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

from sqlalchemy import func, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import selectinload

from database.access import yazma_zorunlu, yetki_var, yetki_zorunlu
from database.database import get_session
from database.models.satin_alma_talep import (
    SatinAlmaTalep,
    SatinAlmaTalepEki,
    SatinAlmaTalepGecmisi,
    SatinAlmaTalepSatiri,
    SatinAlmaTalepSiparisBagi,
)
from database.satis_siparisi_service import decimal
from database.satin_alma_hub_service import SatinAlmaHubService
from database.session_manager import oturum
from database.turkce_normalize import turkce_normalize

DURUM_TASLAK = "TASLAK"
DURUM_GONDERILDI = "ONAYA GÖNDERİLDİ"
DURUM_ONAYLANDI = "ONAYLANDI"
DURUM_REDDEDILDI = "REDDEDİLDİ"
DURUM_IPTAL = "İPTAL"
ESKI_SIPARISE_AKTARILDI = "SİPARİŞE AKTARILDI"

GORUNUM_KISMEN_SIPARIS = "KISMEN SİPARİŞE AKTARILDI"
GORUNUM_TAMAMEN_SIPARIS = "TAMAMEN SİPARİŞE AKTARILDI"
GORUNUM_KISMEN_TESLIM = "KISMEN TESLİM ALINDI"
GORUNUM_TAMAMLANDI = "TAMAMLANDI"

DURUMLAR = (
    DURUM_TASLAK,
    DURUM_GONDERILDI,
    DURUM_ONAYLANDI,
    DURUM_REDDEDILDI,
    GORUNUM_KISMEN_SIPARIS,
    GORUNUM_TAMAMEN_SIPARIS,
    GORUNUM_KISMEN_TESLIM,
    GORUNUM_TAMAMLANDI,
    DURUM_IPTAL,
)
ONCELIKLER = ("DÜŞÜK", "NORMAL", "YÜKSEK", "ACİL")
ONAYLI_DURUMLAR = (DURUM_ONAYLANDI, ESKI_SIPARISE_AKTARILDI)
ACIK_DURUMLAR = (DURUM_TASLAK, DURUM_GONDERILDI, DURUM_ONAYLANDI, ESKI_SIPARISE_AKTARILDI)
SIFIR = Decimal("0")
EK_UZANTILARI = frozenset({
    ".pdf", ".jpg", ".jpeg", ".png", ".bmp", ".tif", ".tiff", ".doc", ".docx", ".xls", ".xlsx", ".csv",
    ".txt", ".dwg", ".dxf", ".step", ".stp", ".zip", ".msg", ".eml",
})
EK_AZAMI_BAYT = 20 * 1024 * 1024
RAPOR_ALANLARI = ("talep", "onayli", "siparis", "teslim", "iade", "net_teslim", "bekleyen_teslim", "iptal",
                  "yeniden_acilan", "kalan")


def _d(v) -> Decimal:
    if v in (None, ""):
        return SIFIR
    return v if isinstance(v, Decimal) else Decimal(str(v))


def _kullanici() -> str:
    return oturum.ad_soyad or oturum.kullanici_adi or ""


def _tarih_metni(v) -> str:
    return v.strftime("%d.%m.%Y") if v else ""


class SatinAlmaTalepService:
    _hazir_motor = None
    son_birim_uyarisi: str | None = None

    # ------------------------------------------------------------------ şema
    @staticmethod
    def schema_hazirla() -> None:
        from database.database import company_db

        motor = company_db.engine
        if motor is None or SatinAlmaTalepService._hazir_motor is motor:
            return
        SatinAlmaHubService.schema_hazirla()
        SatinAlmaTalepService.gecis_uygula(motor)
        SatinAlmaTalepService._hazir_motor = motor

    @staticmethod
    def gecis_uygula(motor) -> None:
        from database.modul_sema import eksik_kolonlari_ekle, surum_uygula

        def _v1(e) -> None:
            for tablo in (
                SatinAlmaTalep.__table__,
                SatinAlmaTalepSatiri.__table__,
                SatinAlmaTalepSiparisBagi.__table__,
                SatinAlmaTalepGecmisi.__table__,
                SatinAlmaTalepEki.__table__,
            ):
                tablo.create(e, checkfirst=True)
            eksik_kolonlari_ekle(e, "satin_alma_talepleri", {
                "departman": "VARCHAR(100)",
                "talep_nedeni": "VARCHAR(300)",
                "proje_ref": "VARCHAR(100)",
                "isteyen_kullanici_id": "INTEGER",
                "gonderen": "VARCHAR(120)",
                "gonderme_tarihi": "DATETIME",
                "onaylayan": "VARCHAR(120)",
                "onay_tarihi": "DATETIME",
                "red_nedeni": "VARCHAR(300)",
                "geri_gonderme_nedeni": "VARCHAR(300)",
                "iptal_nedeni": "VARCHAR(300)",
                "row_version": "INTEGER NOT NULL DEFAULT 1",
                "guncelleme_tarihi": "DATETIME",
            })
            eksik_kolonlari_ekle(e, "satin_alma_talep_satirlari", {
                "sira": "INTEGER",
                "stok_id": "INTEGER",
                "manuel": "BOOLEAN NOT NULL DEFAULT 0",
                "onerilen_tedarikci_id": "INTEGER",
                "ihtiyac_tarihi": "DATE",
                "tahmini_birim_fiyat": "NUMERIC(18,4)",
                "para_birimi": "VARCHAR(3)",
                "kur": "NUMERIC(18,6)",
                "fiyat_kaynagi": "VARCHAR(60)",
                "iptal_miktar": "NUMERIC(18,4) NOT NULL DEFAULT 0",
                "iptal_nedeni": "VARCHAR(300)",
            })
            with e.begin() as b:
                b.execute(text("UPDATE satin_alma_talepleri SET durum = :yeni WHERE durum = 'ONAY BEKLİYOR'"),
                          {"yeni": DURUM_GONDERILDI})
                b.execute(text("UPDATE satin_alma_talep_satirlari SET sira = id WHERE sira IS NULL"))
                b.execute(text(
                    "UPDATE satin_alma_talep_satirlari SET stok_id = "
                    "(SELECT s.id FROM stok_kartlari s WHERE s.stok_kodu = satin_alma_talep_satirlari.urun_kodu) "
                    "WHERE stok_id IS NULL AND EXISTS "
                    "(SELECT 1 FROM stok_kartlari s WHERE s.stok_kodu = satin_alma_talep_satirlari.urun_kodu)"
                ))

        def _v2(e) -> None:
            _v1(e)
            eksik_kolonlari_ekle(e, "satin_alma_talep_satirlari", {
                "yeniden_acilan_miktar": "NUMERIC(18,4) NOT NULL DEFAULT 0",
                "yeniden_acma_nedeni": "VARCHAR(300)",
            })

        surum_uygula(motor, "satin_alma_talep", 1, _v1)
        surum_uygula(motor, "satin_alma_talep", 2, _v2)

    @staticmethod
    def _tablo_var(session) -> bool:
        from sqlalchemy import inspect

        try:
            return inspect(session.connection()).has_table("satin_alma_talep_siparis_baglari")
        except Exception:  # noqa: BLE001
            return False

    # ----------------------------------------------------------- numaralama
    @staticmethod
    def _sonraki_no(session) -> str:
        onek = "TAL"
        son = session.scalar(
            select(SatinAlmaTalep.talep_no)
            .where(SatinAlmaTalep.talep_no.like(f"{onek}%"))
            .order_by(SatinAlmaTalep.talep_no.desc())
        )
        try:
            sira = int(str(son)[len(onek):]) + 1 if son else 1
        except ValueError:
            sira = 1
        return f"{onek}{sira:06d}"

    @staticmethod
    def talep_no() -> str:
        """Yeni talep için önerilen numara; kesin numara kayıt anında verilir."""
        SatinAlmaTalepService.schema_hazirla()
        with get_session() as session:
            return SatinAlmaTalepService._sonraki_no(session)

    @staticmethod
    def _gecmis(session, talep_id: int, islem: str, eski: str | None = None, yeni: str | None = None,
                detay: str | None = None) -> None:
        session.add(SatinAlmaTalepGecmisi(
            talep_id=int(talep_id), islem=islem, eski_durum=eski, yeni_durum=yeni, detay=detay,
            kullanici=_kullanici(),
        ))

    # ------------------------------------------------------ miktar hesapları
    @staticmethod
    def _satir_miktarlari(session, satirlar: list[SatinAlmaTalepSatiri], onayli: bool) -> dict[int, dict]:
        """Satır id → talep / onaylı / sipariş / teslim / iptal / kalan."""
        from database.models.alis_siparisi import AlisSiparisi, AlisSiparisiSatiri

        idler = [int(s.id) for s in satirlar]
        baglar: list[tuple] = []
        if idler and SatinAlmaTalepService._tablo_var(session):
            baglar = session.execute(
                select(SatinAlmaTalepSiparisBagi, AlisSiparisiSatiri, AlisSiparisi)
                .join(AlisSiparisiSatiri, AlisSiparisiSatiri.id == SatinAlmaTalepSiparisBagi.siparis_satiri_id)
                .join(AlisSiparisi, AlisSiparisi.id == SatinAlmaTalepSiparisBagi.siparis_id)
                .where(SatinAlmaTalepSiparisBagi.talep_satiri_id.in_(idler), AlisSiparisi.durum != "İPTAL")
                .order_by(SatinAlmaTalepSiparisBagi.id)
            ).all()
        sonuc = {
            int(s.id): {"talep": _d(s.miktar), "onayli": _d(s.miktar) if onayli else SIFIR, "siparis": SIFIR,
                        "teslim": SIFIR, "iade": SIFIR, "iptal": _d(s.iptal_miktar),
                        "yeniden_acilan": _d(getattr(s, "yeniden_acilan_miktar", 0)), "siparisler": []}
            for s in satirlar
        }
        # Sipariş satırının teslim/iade miktarı, o satıra bağlı paylara id sırasıyla dağıtılır.
        tum_baglar_satir: dict[int, list] = {}
        iade_satir: dict[int, Decimal] = {}
        if baglar:
            sip_satir_idler = {int(ss.id) for _b, ss, _s in baglar}
            for b in session.scalars(
                select(SatinAlmaTalepSiparisBagi)
                .where(SatinAlmaTalepSiparisBagi.siparis_satiri_id.in_(sip_satir_idler))
                .order_by(SatinAlmaTalepSiparisBagi.id)
            ).all():
                tum_baglar_satir.setdefault(int(b.siparis_satiri_id), []).append(b)
            iade_satir = SatinAlmaTalepService._siparis_satiri_iadeleri(session, sip_satir_idler)

        def _dagit(toplam: Decimal, ss_id: int, bag_id: int) -> Decimal:
            kalan_miktar = toplam
            for diger in tum_baglar_satir.get(ss_id, []):
                pay = min(_d(diger.miktar), max(SIFIR, kalan_miktar))
                kalan_miktar -= pay
                if int(diger.id) == bag_id:
                    return pay
            return SIFIR

        for bag, ss, sip in baglar:
            kayit = sonuc[int(bag.talep_satiri_id)]
            kayit["siparis"] += _d(bag.miktar)
            alinan = max(_d(ss.irsaliyelenen_miktar), _d(ss.faturalanan_miktar))
            payim = _dagit(alinan, int(ss.id), int(bag.id))
            iadem = min(payim, _dagit(iade_satir.get(int(ss.id), SIFIR), int(ss.id), int(bag.id)))
            kayit["teslim"] += payim
            kayit["iade"] += iadem
            kayit["siparisler"].append({
                "siparis_id": int(sip.id), "siparis_no": sip.siparis_no, "siparis_satiri_id": int(ss.id),
                "miktar": _d(bag.miktar), "teslim": payim, "iade": iadem, "durum": sip.durum,
                "termin_tarihi": sip.termin_tarihi,
            })
        for k in sonuc.values():
            k["kalan"] = max(SIFIR, k["onayli"] - k["siparis"] - k["iptal"] + k["yeniden_acilan"])
            k["net_teslim"] = max(SIFIR, k["teslim"] - k["iade"])
            k["bekleyen_teslim"] = max(SIFIR, k["siparis"] - k["teslim"])
            k["yeniden_acilabilir"] = max(SIFIR, k["iade"] - k["yeniden_acilan"])
        return sonuc

    @staticmethod
    def _siparis_satiri_iadeleri(session, sip_satir_idler: set[int]) -> dict[int, Decimal]:
        """Sipariş satırı → iptal edilmemiş alış iadelerinde geri gönderilen miktar."""
        from database.models.alis_faturasi import AlisFaturasiSatiri
        from database.models.alis_iade_faturasi import AlisIadeFaturasi, AlisIadeFaturasiSatiri
        from database.models.alis_irsaliyesi import AlisIrsaliyesiSatiri

        if not sip_satir_idler:
            return {}
        sonuc: dict[int, Decimal] = {}
        rows = session.execute(
            select(AlisIadeFaturasiSatiri.miktar, AlisFaturasiSatiri.siparis_satiri_id,
                   AlisIrsaliyesiSatiri.siparis_satiri_id)
            .join(AlisIadeFaturasi, AlisIadeFaturasi.id == AlisIadeFaturasiSatiri.iade_id)
            .join(AlisFaturasiSatiri, AlisFaturasiSatiri.id == AlisIadeFaturasiSatiri.kaynak_fatura_satiri_id)
            .outerjoin(AlisIrsaliyesiSatiri, AlisIrsaliyesiSatiri.id == AlisFaturasiSatiri.irsaliye_satiri_id)
            .where(AlisIadeFaturasi.durum.not_in(("İPTAL", "TASLAK")))
        ).all()
        for miktar, dogrudan, irsaliyeden in rows:
            ss_id = dogrudan or irsaliyeden
            if ss_id and int(ss_id) in sip_satir_idler:
                sonuc[int(ss_id)] = sonuc.get(int(ss_id), SIFIR) + _d(miktar)
        return sonuc

    @staticmethod
    def _gorunen_durum(ham: str, miktarlar: dict[int, dict]) -> str:
        if ham not in ONAYLI_DURUMLAR:
            return ham
        toplam_siparis = sum((m["siparis"] for m in miktarlar.values()), SIFIR)
        toplam_teslim = sum((m["teslim"] for m in miktarlar.values()), SIFIR)
        toplam_kalan = sum((m["kalan"] for m in miktarlar.values()), SIFIR)
        if toplam_siparis <= 0:
            return DURUM_IPTAL if miktarlar and toplam_kalan <= 0 else DURUM_ONAYLANDI
        if toplam_kalan <= 0 and toplam_teslim >= toplam_siparis:
            return GORUNUM_TAMAMLANDI
        if toplam_teslim > 0:
            return GORUNUM_KISMEN_TESLIM
        if toplam_kalan <= 0:
            return GORUNUM_TAMAMEN_SIPARIS
        return GORUNUM_KISMEN_SIPARIS

    @staticmethod
    def stok_bilgisi(urun_kodu: str, depo: str | None = None) -> dict[str, Decimal]:
        """Depodaki mevcut stok ve açık alış siparişlerinde bekleyen miktar."""
        with get_session() as session:
            return SatinAlmaTalepService._stok_bilgisi(session, urun_kodu, depo)

    @staticmethod
    def _stok_bilgisi(session, urun_kodu: str, depo: str | None) -> dict[str, Decimal]:
        from database.models.alis_siparisi import AlisSiparisi, AlisSiparisiSatiri
        from database.models.stok import Depo, StokKarti, StokLotu

        kod = (urun_kodu or "").strip()
        zaman = datetime.now()
        if not kod:
            return {"stok": SIFIR, "bekleyen": SIFIR, "toplam_stok": SIFIR, "diger_depo": SIFIR,
                    "en_yakin_termin": None, "zaman": zaman}
        stok = session.scalar(select(StokKarti).where(StokKarti.stok_kodu == kod))
        mevcut = toplam_stok = SIFIR
        if stok is not None:
            q = select(func.coalesce(func.sum(StokLotu.kalan_miktar), 0)).where(StokLotu.stok_id == stok.id)
            toplam_stok = _d(session.scalar(q))
            mevcut = toplam_stok
            if depo:
                depo_id = session.scalar(select(Depo.id).where(Depo.ad == depo))
                mevcut = _d(session.scalar(q.where(StokLotu.depo_id == depo_id))) if depo_id is not None else SIFIR
        bekleyen = SIFIR
        termin = None
        for ss, sip_termin in session.execute(
            select(AlisSiparisiSatiri, AlisSiparisi.termin_tarihi)
            .join(AlisSiparisi)
            .where(AlisSiparisiSatiri.urun_kodu == kod, AlisSiparisi.durum.notin_(("İPTAL", "FATURALI")))
        ).all():
            acik = max(SIFIR, _d(ss.miktar) - max(_d(ss.irsaliyelenen_miktar), _d(ss.faturalanan_miktar)))
            if acik > 0:
                bekleyen += acik
                if sip_termin and (termin is None or sip_termin < termin):
                    termin = sip_termin
        return {"stok": mevcut, "bekleyen": bekleyen, "toplam_stok": toplam_stok,
                "diger_depo": max(SIFIR, toplam_stok - mevcut) if depo else SIFIR,
                "en_yakin_termin": termin, "zaman": zaman}

    @staticmethod
    def depo_stoklari(urun_kodu: str) -> list[dict[str, Any]]:
        """Ürünün depo bazlı mevcut stoku (bilgi amaçlı; transfer veya rezervasyon yapılmaz)."""
        from database.models.stok import Depo, StokKarti, StokLotu

        kod = (urun_kodu or "").strip()
        if not kod:
            return []
        with get_session() as session:
            stok = session.scalar(select(StokKarti).where(StokKarti.stok_kodu == kod))
            if stok is None:
                return []
            rows = session.execute(
                select(Depo.ad, func.coalesce(func.sum(StokLotu.kalan_miktar), 0))
                .join(StokLotu, StokLotu.depo_id == Depo.id)
                .where(StokLotu.stok_id == stok.id)
                .group_by(Depo.ad).order_by(Depo.ad)
            ).all()
        return [{"depo": ad, "miktar": _d(m)} for ad, m in rows if _d(m) != 0]

    # ------------------------------------------------------------- sorgular
    @staticmethod
    def listele(
        durum: str | None = None,
        *,
        baslangic: date | None = None,
        bitis: date | None = None,
        no: str | None = None,
        isteyen: str | None = None,
        departman_depo: str | None = None,
        oncelik: str | None = None,
        stok: str | None = None,
        gorunum: str | None = None,
    ) -> list[dict[str, Any]]:
        """gorunum: None | 'onay_bekleyen' | 'geciken' | 'aktarilmamis' | 'kismen'."""
        yetki_zorunlu("alis_talep_goruntuleme", "alis_talep_duzenleme", "alis_talep_onay", "alis_goruntuleme",
                      mesaj="Satın alma taleplerini görüntüleme yetkiniz yok.")
        SatinAlmaTalepService.schema_hazirla()
        fiyat_gor = yetki_var("alis_talep_fiyat_gorme", "maliyet_gorma")
        n_no = turkce_normalize((no or "").strip())
        n_isteyen = turkce_normalize((isteyen or "").strip())
        n_dd = turkce_normalize((departman_depo or "").strip())
        n_stok = turkce_normalize((stok or "").strip())
        bugun = date.today()
        with get_session() as session:
            q = select(SatinAlmaTalep).options(selectinload(SatinAlmaTalep.satirlar)).order_by(
                SatinAlmaTalep.talep_tarihi.desc(), SatinAlmaTalep.id.desc()
            )
            if baslangic:
                q = q.where(SatinAlmaTalep.talep_tarihi >= baslangic)
            if bitis:
                q = q.where(SatinAlmaTalep.talep_tarihi <= bitis)
            if oncelik and oncelik != "Tümü":
                q = q.where(SatinAlmaTalep.oncelik == oncelik)
            if gorunum == "onay_bekleyen":
                q = q.where(SatinAlmaTalep.durum == DURUM_GONDERILDI)
            sonuc = []
            for t in session.scalars(q).all():
                if n_no and n_no not in turkce_normalize(t.talep_no):
                    continue
                if n_isteyen and n_isteyen not in turkce_normalize(t.isteyen_kullanici or ""):
                    continue
                if n_dd and n_dd not in turkce_normalize(f"{t.departman or ''} {t.depo or ''}"):
                    continue
                if n_stok and not any(
                    n_stok in turkce_normalize(f"{s.urun_kodu} {s.urun_adi}") for s in t.satirlar
                ):
                    continue
                miktarlar = SatinAlmaTalepService._satir_miktarlari(session, t.satirlar, t.durum in ONAYLI_DURUMLAR)
                gorunen = SatinAlmaTalepService._gorunen_durum(t.durum, miktarlar)
                if durum and durum != "Tümü" and gorunen != durum and t.durum != durum:
                    continue
                if gorunum == "geciken":
                    acik = t.durum in (DURUM_TASLAK, DURUM_GONDERILDI) or sum(
                        (m["kalan"] for m in miktarlar.values()), SIFIR) > 0
                    ihtiyac = min([d for d in [t.ihtiyac_tarihi] + [s.ihtiyac_tarihi for s in t.satirlar] if d],
                                  default=None)
                    if not (acik and ihtiyac and ihtiyac < bugun and t.durum in ACIK_DURUMLAR):
                        continue
                toplam_siparis = sum((m["siparis"] for m in miktarlar.values()), SIFIR)
                toplam_kalan = sum((m["kalan"] for m in miktarlar.values()), SIFIR)
                if gorunum == "aktarilmamis" and not (
                        t.durum in ONAYLI_DURUMLAR and toplam_siparis <= 0 and toplam_kalan > 0):
                    continue
                if gorunum == "kismen" and not (
                        t.durum in ONAYLI_DURUMLAR and toplam_siparis > 0 and toplam_kalan > 0):
                    continue
                tahmini = None
                if fiyat_gor and any(s.tahmini_birim_fiyat is not None for s in t.satirlar):
                    tahmini = sum(
                        (_d(s.miktar) * _d(s.tahmini_birim_fiyat) * (_d(s.kur) if (s.para_birimi or "TRY") != "TRY"
                                                                     else Decimal("1"))
                         for s in t.satirlar),
                        SIFIR,
                    ).quantize(Decimal("0.01"))
                sonuc.append({
                    "id": int(t.id),
                    "talep_no": t.talep_no,
                    "talep_tarihi": t.talep_tarihi,
                    "ihtiyac_tarihi": t.ihtiyac_tarihi,
                    "isteyen": t.isteyen_kullanici or "",
                    "departman": t.departman or "",
                    "depo": t.depo or "",
                    "oncelik": t.oncelik,
                    "durum": gorunen,
                    "ham_durum": t.durum,
                    "satir_adet": len(t.satirlar or []),
                    "tahmini_toplam": tahmini,
                    "aciklama": t.aciklama or "",
                })
            return sonuc

    @staticmethod
    def getir(talep_id: int) -> SatinAlmaTalep | None:
        SatinAlmaTalepService.schema_hazirla()
        with get_session() as session:
            return session.scalar(
                select(SatinAlmaTalep)
                .options(selectinload(SatinAlmaTalep.satirlar))
                .where(SatinAlmaTalep.id == int(talep_id))
            )

    @staticmethod
    def detay(talep_id: int) -> dict[str, Any]:
        """Form ve çıktı için başlık + satır miktarları + geçmiş + ekler."""
        from database.models.cari import Cari

        yetki_zorunlu("alis_talep_goruntuleme", "alis_talep_duzenleme", "alis_talep_onay", "alis_goruntuleme",
                      mesaj="Satın alma taleplerini görüntüleme yetkiniz yok.")
        SatinAlmaTalepService.schema_hazirla()
        fiyat_gor = yetki_var("alis_talep_fiyat_gorme", "maliyet_gorma")
        with get_session() as session:
            t = session.scalar(
                select(SatinAlmaTalep).options(selectinload(SatinAlmaTalep.satirlar))
                .where(SatinAlmaTalep.id == int(talep_id))
            )
            if t is None:
                raise ValueError("Talep bulunamadı.")
            miktarlar = SatinAlmaTalepService._satir_miktarlari(session, t.satirlar, t.durum in ONAYLI_DURUMLAR)
            kolonlar = [c.name for c in SatinAlmaTalep.__table__.columns]
            sonuc = {k: getattr(t, k) for k in kolonlar}
            sonuc["gorunen_durum"] = SatinAlmaTalepService._gorunen_durum(t.durum, miktarlar)
            tedarikci_adlari = {}
            ted_idler = {s.onerilen_tedarikci_id for s in t.satirlar if s.onerilen_tedarikci_id}
            if ted_idler:
                tedarikci_adlari = {int(c.id): c.unvan for c in session.scalars(
                    select(Cari).where(Cari.id.in_(ted_idler))).all()}
            satirlar = []
            for s in sorted(t.satirlar, key=lambda x: (x.sira or x.id, x.id)):
                m = miktarlar[int(s.id)]
                bilgi = SatinAlmaTalepService._stok_bilgisi(session, s.urun_kodu, s.depo or t.depo)
                satirlar.append({
                    "id": int(s.id), "sira": s.sira, "urun_kodu": s.urun_kodu, "urun_adi": s.urun_adi,
                    "aciklama": s.aciklama or "", "birim": s.birim, "miktar": _d(s.miktar), "depo": s.depo,
                    "stok_id": s.stok_id, "manuel": bool(s.manuel), "eslesmemis": bool(s.manuel) and not s.stok_id,
                    "onerilen_tedarikci_id": s.onerilen_tedarikci_id,
                    "onerilen_tedarikci": tedarikci_adlari.get(int(s.onerilen_tedarikci_id or 0), ""),
                    "ihtiyac_tarihi": s.ihtiyac_tarihi,
                    "tahmini_birim_fiyat": _d(s.tahmini_birim_fiyat) if fiyat_gor and s.tahmini_birim_fiyat is not None
                    else None,
                    "para_birimi": (s.para_birimi or "TRY") if fiyat_gor else None,
                    "kur": _d(s.kur) if fiyat_gor and s.kur is not None else None,
                    "fiyat_kaynagi": s.fiyat_kaynagi if fiyat_gor else None,
                    "iptal_nedeni": s.iptal_nedeni,
                    "mevcut_stok": bilgi["stok"], "bekleyen_siparis": bilgi["bekleyen"],
                    "diger_depo_stok": bilgi["diger_depo"], "bekleyen_termin": bilgi["en_yakin_termin"],
                    "stok_zamani": bilgi["zaman"],
                    "yeniden_acma_nedeni": s.yeniden_acma_nedeni,
                    "siparis_termin": min((x["termin_tarihi"] for x in m["siparisler"]
                                           if x["termin_tarihi"] and x["miktar"] > x["teslim"]), default=None),
                    **{k: m[k] for k in ("onayli", "siparis", "teslim", "iade", "net_teslim", "bekleyen_teslim",
                                         "iptal", "yeniden_acilan", "yeniden_acilabilir", "kalan", "siparisler")},
                })
            sonuc["satirlar"] = satirlar
            sonuc["fiyat_gorunur"] = fiyat_gor
            sonuc["gecmis"] = [
                {"islem": g.islem, "eski": g.eski_durum, "yeni": g.yeni_durum, "detay": g.detay,
                 "kullanici": g.kullanici, "tarih": g.tarih}
                for g in session.scalars(select(SatinAlmaTalepGecmisi).where(
                    SatinAlmaTalepGecmisi.talep_id == t.id).order_by(SatinAlmaTalepGecmisi.id)).all()
            ]
            sonuc["ekler"] = [
                {"id": int(e.id), "dosya_adi": e.dosya_adi, "ekleyen": e.ekleyen, "tarih": e.tarih}
                for e in session.scalars(select(SatinAlmaTalepEki).where(
                    SatinAlmaTalepEki.talep_id == t.id).order_by(SatinAlmaTalepEki.id)).all()
            ]
            return sonuc

    # --------------------------------------------------------------- kayıt
    @staticmethod
    def _satirlari_hazirla(session, satir_verileri: list[dict[str, Any]], varsayilan_depo: str) -> list[dict]:
        from database.models.stok import StokKarti

        hazir = []
        for sira, veri in enumerate(satir_verileri, start=1):
            kod = (veri.get("urun_kodu") or "").strip()
            ad = (veri.get("urun_adi") or "").strip()
            birim = (veri.get("birim") or "").strip()
            miktar = decimal(veri.get("miktar"), "Miktar", Decimal("0.0001"))
            stok = session.scalar(select(StokKarti).where(StokKarti.stok_kodu == kod)) if kod else None
            manuel = bool(veri.get("manuel")) or stok is None
            if manuel:
                if not ad:
                    raise ValueError(f"{sira}. satır: manuel satırda ürün adı zorunludur.")
                if not birim:
                    raise ValueError(f"{sira}. satır: manuel satırda birim zorunludur.")
                stok_id = veri.get("stok_id") if stok is not None else None
            else:
                ad = ad or stok.stok_adi
                stok_id = int(stok.id)
            fiyat = veri.get("tahmini_birim_fiyat")
            pb = (veri.get("para_birimi") or "TRY").upper()
            if pb != "TRY" and fiyat not in (None, "") and not veri.get("kur"):
                raise ValueError(f"{sira}. satır: {pb} tahmini fiyat için kur girin (TL karşılığı kurla hesaplanır).")
            hazir.append({
                "sira": sira,
                "urun_kodu": kod,
                "urun_adi": ad,
                "birim": birim or (stok.birim if stok else "Adet"),
                "miktar": miktar,
                "aciklama": (veri.get("aciklama") or "").strip() or None,
                "depo": veri.get("depo") or varsayilan_depo,
                "stok_id": stok_id,
                "manuel": manuel,
                "onerilen_tedarikci_id": veri.get("onerilen_tedarikci_id") or None,
                "ihtiyac_tarihi": veri.get("ihtiyac_tarihi"),
                "tahmini_birim_fiyat": decimal(fiyat, "Tahmini fiyat", Decimal("0")) if fiyat not in (None, "")
                else None,
                "para_birimi": pb,
                "kur": decimal(veri.get("kur") or 1, "Kur", Decimal("0.000001")) if pb != "TRY" else Decimal("1"),
                "fiyat_kaynagi": veri.get("fiyat_kaynagi") or None,
            })
        return hazir

    @staticmethod
    def kaydet(
        veriler: dict[str, Any],
        satir_verileri: list[dict[str, Any]],
        talep_id: int | None = None,
        beklenen_versiyon: int | None = None,
        tekrar_gerekcesi: str | None = None,
    ) -> int:
        """``tekrar_gerekcesi``: aynı ürün için açık talep uyarısına rağmen devam edilirse geçmişe yazılır.

        Tanımsız birimli satırlar taslakta kalabilir (``son_birim_uyarisi``); onaya gönderme,
        onay ve siparişe aktarım bu satırları reddeder.
        """
        yazma_zorunlu("alis_talep_duzenleme", "alis_duzenleme", "yeni_kayit")
        SatinAlmaTalepService.son_birim_uyarisi = None
        SatinAlmaTalepService.schema_hazirla()
        if not satir_verileri:
            raise ValueError("En az bir talep satırı girin.")
        if not veriler.get("talep_tarihi"):
            raise ValueError("Talep tarihi zorunludur.")
        if veriler.get("ihtiyac_tarihi") and veriler["ihtiyac_tarihi"] < veriler["talep_tarihi"]:
            raise ValueError("İhtiyaç tarihi talep tarihinden önce olamaz.")
        for deneme in range(3):
            try:
                with get_session() as session:
                    from database.stok_service import StokService

                    birim_sorunu = StokService.belge_birim_sorunu(
                        session, satir_verileri, "Satın alma talebi", eylem="onaylanamaz")
                    if talep_id:
                        talep = session.get(SatinAlmaTalep, int(talep_id))
                        if talep is None:
                            raise ValueError("Talep bulunamadı.")
                        if talep.durum != DURUM_TASLAK:
                            raise ValueError(
                                f"Talep '{talep.durum}' durumunda; yalnızca taslak talep düzenlenebilir. "
                                "Düzeltme için onaycı talebi taslağa geri göndermelidir."
                            )
                        if beklenen_versiyon is not None and int(beklenen_versiyon) != int(talep.row_version or 1):
                            raise ValueError("Talep başka bir kullanıcı tarafından değiştirilmiş; yeniden açın.")
                        talep.satirlar.clear()
                        session.flush()
                        talep.row_version = int(talep.row_version or 1) + 1
                        talep.guncelleme_tarihi = datetime.now()
                        islem = "GÜNCELLE"
                    else:
                        istenen = (veriler.get("talep_no") or "").strip()
                        if deneme or not istenen or session.scalar(
                            select(SatinAlmaTalep.id).where(SatinAlmaTalep.talep_no == istenen)
                        ):
                            istenen = SatinAlmaTalepService._sonraki_no(session)
                        talep = SatinAlmaTalep(
                            talep_no=istenen, durum=DURUM_TASLAK, row_version=1,
                            isteyen_kullanici=_kullanici(), isteyen_kullanici_id=oturum.user_id,
                        )
                        session.add(talep)
                        islem = "OLUŞTUR"
                    talep.talep_tarihi = veriler["talep_tarihi"]
                    talep.ihtiyac_tarihi = veriler.get("ihtiyac_tarihi")
                    talep.depo = veriler.get("depo") or "ANA DEPO"
                    talep.departman = (veriler.get("departman") or "").strip() or None
                    talep.oncelik = veriler.get("oncelik") or "NORMAL"
                    talep.talep_nedeni = (veriler.get("talep_nedeni") or "").strip() or None
                    talep.proje_ref = (veriler.get("proje_ref") or "").strip() or None
                    talep.aciklama = (veriler.get("aciklama") or "").strip() or None
                    for s in SatinAlmaTalepService._satirlari_hazirla(session, satir_verileri, talep.depo):
                        talep.satirlar.append(SatinAlmaTalepSatiri(**s))
                    session.flush()
                    SatinAlmaTalepService._gecmis(session, talep.id, islem, None, talep.durum,
                                                  f"{len(satir_verileri)} satır")
                    if (tekrar_gerekcesi or "").strip():
                        SatinAlmaTalepService._gecmis(session, talep.id, "TEKRAR TALEP GEREKÇESİ", None, None,
                                                      tekrar_gerekcesi.strip()[:500])
                    SatinAlmaTalepService.son_birim_uyarisi = str(birim_sorunu) if birim_sorunu else None
                    return int(talep.id)
            except IntegrityError:
                if talep_id or deneme == 2:
                    raise ValueError("Talep numarası alınamadı; tekrar deneyin.")
        raise ValueError("Talep kaydedilemedi.")

    @staticmethod
    def acik_talep_uyarilari(satirlar: list[dict[str, Any]], haric_talep_id: int | None = None) -> list[str]:
        """Aynı ürün için kalanı olan başka açık talepler (uyarı; engel değil)."""
        SatinAlmaTalepService.schema_hazirla()
        kodlar = {(s.get("urun_kodu") or "").strip() for s in satirlar if (s.get("urun_kodu") or "").strip()}
        if not kodlar:
            return []
        uyarilar = []
        with get_session() as session:
            adaylar = session.scalars(
                select(SatinAlmaTalepSatiri).join(SatinAlmaTalep)
                .options(selectinload(SatinAlmaTalepSatiri.talep))
                .where(SatinAlmaTalepSatiri.urun_kodu.in_(kodlar), SatinAlmaTalep.durum.in_(ACIK_DURUMLAR))
            ).all()
            for s in adaylar:
                if haric_talep_id and int(s.talep_id) == int(haric_talep_id):
                    continue
                t = s.talep
                m = SatinAlmaTalepService._satir_miktarlari(session, [s], t.durum in ONAYLI_DURUMLAR)[int(s.id)]
                acik = m["kalan"] if t.durum in ONAYLI_DURUMLAR else _d(s.miktar)
                if acik > 0:
                    uyarilar.append(f"{s.urun_kodu} {s.urun_adi}: {t.talep_no} ({t.durum}) açık {acik.normalize():f} "
                                    f"{s.birim}")
        return sorted(set(uyarilar))

    # ---------------------------------------------------------- onay akışı
    @staticmethod
    def _birim_zorunlu(session, satirlar, eylem: str) -> None:
        from database.stok_service import StokService

        sorun = StokService.belge_birim_sorunu(session, list(satirlar), "Satın alma talebi", eylem=eylem)
        if sorun is not None:
            raise sorun

    @staticmethod
    def birim_uyarisi(talep_id: int) -> str | None:
        """Taslak talepteki tanımsız birim satırları (yoksa None)."""
        from database.stok_service import StokService

        with get_session() as session:
            t = session.get(SatinAlmaTalep, int(talep_id))
            if t is None:
                return None
            sorun = StokService.belge_birim_sorunu(session, list(t.satirlar), "Satın alma talebi",
                                                   eylem="onaylanamaz")
            return str(sorun) if sorun is not None else None

    @staticmethod
    def _durum_gecisi(talep_id: int, izinli: tuple[str, ...], yeni: str, islem: str, detay: str | None,
                      guncelle=None) -> None:
        with get_session() as session:
            t = session.scalar(select(SatinAlmaTalep).options(selectinload(SatinAlmaTalep.satirlar))
                               .where(SatinAlmaTalep.id == int(talep_id)))
            if t is None:
                raise ValueError("Talep bulunamadı.")
            if t.durum == yeni:
                return
            if t.durum not in izinli:
                raise ValueError(f"Talep '{t.durum}' durumunda; bu işlem yapılamaz.")
            if guncelle:
                guncelle(session, t)
            eski = t.durum
            t.durum = yeni
            t.row_version = int(t.row_version or 1) + 1
            t.guncelleme_tarihi = datetime.now()
            SatinAlmaTalepService._gecmis(session, t.id, islem, eski, yeni, detay)

    @staticmethod
    def onaya_gonder(talep_id: int) -> None:
        yazma_zorunlu("alis_talep_duzenleme", "alis_duzenleme")
        SatinAlmaTalepService.schema_hazirla()

        def _g(session, t):
            if not t.satirlar:
                raise ValueError("Satırı olmayan talep onaya gönderilemez.")
            SatinAlmaTalepService._birim_zorunlu(session, t.satirlar, "onaya gönderilemez")
            t.gonderen = _kullanici()
            t.gonderme_tarihi = datetime.now()
            t.geri_gonderme_nedeni = None

        SatinAlmaTalepService._durum_gecisi(talep_id, (DURUM_TASLAK,), DURUM_GONDERILDI, "ONAYA GÖNDER", None, _g)

    @staticmethod
    def onayla(talep_id: int) -> None:
        yazma_zorunlu("alis_talep_onay")
        SatinAlmaTalepService.schema_hazirla()

        def _g(session, t):
            SatinAlmaTalepService._birim_zorunlu(session, t.satirlar, "onaylanamaz")
            if (
                t.isteyen_kullanici_id
                and oturum.user_id
                and int(t.isteyen_kullanici_id) == int(oturum.user_id)
                and (oturum.role_kod or "").upper() != "YONETICI"
            ):
                raise ValueError("Kendi oluşturduğunuz talebi onaylayamazsınız (yönetici hariç).")
            t.onaylayan = _kullanici()
            t.onay_tarihi = datetime.now()

        SatinAlmaTalepService._durum_gecisi(talep_id, (DURUM_GONDERILDI,), DURUM_ONAYLANDI, "ONAYLA", None, _g)

    @staticmethod
    def reddet(talep_id: int, neden: str) -> None:
        yazma_zorunlu("alis_talep_onay")
        neden = (neden or "").strip()
        if not neden:
            raise ValueError("Red nedeni zorunludur.")
        SatinAlmaTalepService.schema_hazirla()

        def _g(_s, t):
            t.red_nedeni = neden[:300]
            t.onaylayan = _kullanici()
            t.onay_tarihi = datetime.now()

        SatinAlmaTalepService._durum_gecisi(talep_id, (DURUM_GONDERILDI,), DURUM_REDDEDILDI, "REDDET", neden, _g)

    @staticmethod
    def geri_gonder(talep_id: int, neden: str) -> None:
        """Onaya gönderilmiş (veya siparişe aktarılmamış onaylı) talebi düzeltme için taslağa döndürür."""
        yazma_zorunlu("alis_talep_onay")
        neden = (neden or "").strip()
        if not neden:
            raise ValueError("Geri gönderme nedeni zorunludur.")
        SatinAlmaTalepService.schema_hazirla()

        def _g(session, t):
            m = SatinAlmaTalepService._satir_miktarlari(session, t.satirlar, True)
            if any(x["siparis"] > 0 for x in m.values()):
                raise ValueError("Siparişe aktarılmış talep taslağa geri gönderilemez.")
            t.geri_gonderme_nedeni = neden[:300]
            t.onaylayan = None
            t.onay_tarihi = None

        SatinAlmaTalepService._durum_gecisi(
            talep_id, (DURUM_GONDERILDI, DURUM_ONAYLANDI), DURUM_TASLAK, "GERİ GÖNDER", neden, _g
        )

    @staticmethod
    def iptal_et(talep_id: int, neden: str = "") -> None:
        yazma_zorunlu("alis_talep_iptal", "alis_talep_duzenleme", "alis_duzenleme", "iptal")
        SatinAlmaTalepService.schema_hazirla()

        def _g(session, t):
            m = SatinAlmaTalepService._satir_miktarlari(session, t.satirlar, True)
            if any(x["siparis"] > 0 for x in m.values()):
                raise ValueError("Siparişe aktarılmış talep iptal edilemez; kalan miktarı satır bazında iptal edin.")
            t.iptal_nedeni = (neden or "").strip()[:300] or None

        SatinAlmaTalepService._durum_gecisi(
            talep_id, (DURUM_TASLAK, DURUM_GONDERILDI, DURUM_ONAYLANDI, DURUM_REDDEDILDI), DURUM_IPTAL,
            "İPTAL", neden or None, _g,
        )

    @staticmethod
    def kalan_iptal(talep_satiri_id: int, miktar, neden: str) -> None:
        """Onaylı talebin siparişe aktarılmamış kalanını (kısmen) kapatır."""
        yazma_zorunlu("alis_talep_iptal", "alis_talep_duzenleme", "alis_talep_onay", "alis_duzenleme")
        neden = (neden or "").strip()
        if not neden:
            raise ValueError("Kalan iptal nedeni zorunludur.")
        miktar = decimal(miktar, "İptal miktarı", Decimal("0.0001"))
        SatinAlmaTalepService.schema_hazirla()
        with get_session() as session:
            s = session.get(SatinAlmaTalepSatiri, int(talep_satiri_id))
            if s is None:
                raise ValueError("Talep satırı bulunamadı.")
            t = session.get(SatinAlmaTalep, int(s.talep_id))
            if t.durum not in ONAYLI_DURUMLAR:
                raise ValueError("Kalan iptali yalnızca onaylı talepte yapılır; diğer durumlarda talebi iptal edin.")
            m = SatinAlmaTalepService._satir_miktarlari(session, [s], True)[int(s.id)]
            if miktar > m["kalan"]:
                raise ValueError(f"İptal miktarı kalan miktarı ({m['kalan'].normalize():f}) aşamaz.")
            s.iptal_miktar = _d(s.iptal_miktar) + miktar
            s.iptal_nedeni = neden[:300]
            t.row_version = int(t.row_version or 1) + 1
            SatinAlmaTalepService._gecmis(session, t.id, "KALAN İPTAL", t.durum, t.durum,
                                          f"{s.urun_kodu} {miktar.normalize():f} {s.birim}: {neden}")

    @staticmethod
    def iadeyi_yeniden_ac(talep_satiri_id: int, miktar, neden: str) -> None:
        """Tedarikçiye iade edilen miktarın bir kısmını açık kullanıcı kararıyla yeniden aktarılabilir yapar.

        Otomatik sipariş oluşturmaz; yalnızca talebin kalan (aktarılabilir) miktarını artırır.
        """
        yazma_zorunlu("alis_talep_onay", "alis_talep_duzenleme", "alis_duzenleme")
        neden = (neden or "").strip()
        if not neden:
            raise ValueError("Yeniden açma nedeni zorunludur.")
        miktar = decimal(miktar, "Yeniden açılacak miktar", Decimal("0.0001"))
        SatinAlmaTalepService.schema_hazirla()
        with get_session() as session:
            s = session.get(SatinAlmaTalepSatiri, int(talep_satiri_id))
            if s is None:
                raise ValueError("Talep satırı bulunamadı.")
            t = session.get(SatinAlmaTalep, int(s.talep_id))
            if t.durum not in ONAYLI_DURUMLAR:
                raise ValueError("Yalnızca onaylı talepte iade edilen miktar yeniden ihtiyaca açılabilir.")
            m = SatinAlmaTalepService._satir_miktarlari(session, [s], True)[int(s.id)]
            if miktar > m["yeniden_acilabilir"]:
                raise ValueError(
                    f"Yeniden açılabilir iade miktarı {m['yeniden_acilabilir'].normalize():f} {s.birim}; aşılamaz."
                )
            s.yeniden_acilan_miktar = _d(s.yeniden_acilan_miktar) + miktar
            s.yeniden_acma_nedeni = neden[:300]
            t.row_version = int(t.row_version or 1) + 1
            SatinAlmaTalepService._gecmis(session, t.id, "İADEYİ YENİDEN AÇ", t.durum, t.durum,
                                          f"{s.urun_kodu} {miktar.normalize():f} {s.birim}: {neden}")

    @staticmethod
    def sil(talep_id: int) -> None:
        """Yalnızca siparişe bağlanmamış taslak silinir; diğer durumlar kontrollü iptal ister."""
        yazma_zorunlu("alis_talep_duzenleme", "alis_duzenleme")
        yetki_zorunlu("silme", "alis_talep_onay", mesaj="Talep silmek için silme yetkiniz yok.")
        SatinAlmaTalepService.schema_hazirla()
        with get_session() as session:
            t = session.scalar(select(SatinAlmaTalep).options(selectinload(SatinAlmaTalep.satirlar))
                               .where(SatinAlmaTalep.id == int(talep_id)))
            if t is None:
                raise ValueError("Talep bulunamadı.")
            if t.durum != DURUM_TASLAK:
                raise ValueError(f"'{t.durum}' durumundaki talep silinemez; gerekçeyle iptal edin.")
            idler = [int(s.id) for s in t.satirlar]
            if idler and SatinAlmaTalepService._tablo_var(session) and session.scalar(
                select(func.count()).select_from(SatinAlmaTalepSiparisBagi)
                .where(SatinAlmaTalepSiparisBagi.talep_satiri_id.in_(idler))
            ):
                raise ValueError("Siparişe bağlı talep silinemez.")
            for model in (SatinAlmaTalepGecmisi, SatinAlmaTalepEki):
                for kayit in session.scalars(select(model).where(model.talep_id == int(t.id))).all():
                    session.delete(kayit)
            session.delete(t)

    @staticmethod
    def bagli_belgeler(talep_id: int) -> list[dict[str, Any]]:
        """Talebe bağlı alış siparişleri ve onlardan oluşan irsaliye/fatura/iade belgeleri."""
        from database.models.alis_faturasi import AlisFaturasi, AlisFaturasiSatiri
        from database.models.alis_iade_faturasi import AlisIadeFaturasi, AlisIadeFaturasiSatiri
        from database.models.alis_irsaliyesi import AlisIrsaliyesi, AlisIrsaliyesiSatiri
        from database.models.alis_siparisi import AlisSiparisi

        SatinAlmaTalepService.schema_hazirla()
        sonuc: list[dict[str, Any]] = []
        with get_session() as session:
            if not SatinAlmaTalepService._tablo_var(session):
                return []
            ss_idler = set(session.scalars(
                select(SatinAlmaTalepSiparisBagi.siparis_satiri_id)
                .join(SatinAlmaTalepSatiri, SatinAlmaTalepSatiri.id == SatinAlmaTalepSiparisBagi.talep_satiri_id)
                .where(SatinAlmaTalepSatiri.talep_id == int(talep_id))
            ).all())
            if not ss_idler:
                return []
            for sip in session.scalars(
                select(AlisSiparisi).join(SatinAlmaTalepSiparisBagi,
                                          SatinAlmaTalepSiparisBagi.siparis_id == AlisSiparisi.id)
                .where(SatinAlmaTalepSiparisBagi.siparis_satiri_id.in_(ss_idler)).distinct()
                .order_by(AlisSiparisi.id)
            ).all():
                sonuc.append({"tur": "Sipariş", "id": int(sip.id), "no": sip.siparis_no,
                              "tarih": sip.siparis_tarihi, "durum": sip.durum})
            irs_satir_idler = set()
            for irs, irs_satir_id in session.execute(
                select(AlisIrsaliyesi, AlisIrsaliyesiSatiri.id)
                .join(AlisIrsaliyesiSatiri, AlisIrsaliyesiSatiri.irsaliye_id == AlisIrsaliyesi.id)
                .where(AlisIrsaliyesiSatiri.siparis_satiri_id.in_(ss_idler)).order_by(AlisIrsaliyesi.id)
            ).all():
                irs_satir_idler.add(int(irs_satir_id))
                if not any(x["tur"] == "İrsaliye" and x["id"] == int(irs.id) for x in sonuc):
                    sonuc.append({"tur": "İrsaliye", "id": int(irs.id), "no": irs.irsaliye_no,
                                  "tarih": irs.irsaliye_tarihi, "durum": irs.durum})
            kosul = AlisFaturasiSatiri.siparis_satiri_id.in_(ss_idler)
            if irs_satir_idler:
                kosul = kosul | AlisFaturasiSatiri.irsaliye_satiri_id.in_(irs_satir_idler)
            fat_satir_idler = set()
            for fat, fat_satir_id in session.execute(
                select(AlisFaturasi, AlisFaturasiSatiri.id)
                .join(AlisFaturasiSatiri, AlisFaturasiSatiri.fatura_id == AlisFaturasi.id)
                .where(kosul).order_by(AlisFaturasi.id)
            ).all():
                fat_satir_idler.add(int(fat_satir_id))
                if not any(x["tur"] == "Fatura" and x["id"] == int(fat.id) for x in sonuc):
                    sonuc.append({"tur": "Fatura", "id": int(fat.id), "no": fat.fatura_no,
                                  "tarih": fat.fatura_tarihi, "durum": fat.durum})
            if fat_satir_idler:
                for iade in session.scalars(
                    select(AlisIadeFaturasi)
                    .join(AlisIadeFaturasiSatiri, AlisIadeFaturasiSatiri.iade_id == AlisIadeFaturasi.id)
                    .where(AlisIadeFaturasiSatiri.kaynak_fatura_satiri_id.in_(fat_satir_idler))
                    .distinct().order_by(AlisIadeFaturasi.id)
                ).all():
                    sonuc.append({"tur": "İade", "id": int(iade.id), "no": iade.iade_no,
                                  "tarih": iade.iade_tarihi, "durum": iade.durum})
        return sonuc

    @staticmethod
    def siparis_talepleri(siparis_id: int) -> list[dict[str, Any]]:
        """Alış siparişine pay aktaran talepler (sipariş kartından kaynak belgeye geçiş)."""
        SatinAlmaTalepService.schema_hazirla()
        with get_session() as session:
            if not SatinAlmaTalepService._tablo_var(session):
                return []
            rows = session.execute(
                select(SatinAlmaTalep.id, SatinAlmaTalep.talep_no, SatinAlmaTalep.talep_tarihi,
                       SatinAlmaTalep.isteyen_kullanici, SatinAlmaTalepSatiri.urun_kodu,
                       SatinAlmaTalepSatiri.birim, func.sum(SatinAlmaTalepSiparisBagi.miktar))
                .join(SatinAlmaTalepSatiri, SatinAlmaTalepSatiri.talep_id == SatinAlmaTalep.id)
                .join(SatinAlmaTalepSiparisBagi,
                      SatinAlmaTalepSiparisBagi.talep_satiri_id == SatinAlmaTalepSatiri.id)
                .where(SatinAlmaTalepSiparisBagi.siparis_id == int(siparis_id))
                .group_by(SatinAlmaTalep.id, SatinAlmaTalep.talep_no, SatinAlmaTalep.talep_tarihi,
                          SatinAlmaTalep.isteyen_kullanici, SatinAlmaTalepSatiri.urun_kodu,
                          SatinAlmaTalepSatiri.birim)
                .order_by(SatinAlmaTalep.id)
            ).all()
        return [{"id": int(r[0]), "talep_no": r[1], "tarih": r[2], "isteyen": r[3] or "", "urun_kodu": r[4],
                 "birim": r[5], "miktar": _d(r[6])} for r in rows]

    @staticmethod
    def tedarikci_talepleri(cari_id: int) -> list[dict[str, Any]]:
        """Satırında önerilen tedarikçi olan veya bu tedarikçinin siparişine bağlanan talepler."""
        from database.models.alis_siparisi import AlisSiparisi

        SatinAlmaTalepService.schema_hazirla()
        with get_session() as session:
            idler = set(session.scalars(
                select(SatinAlmaTalepSatiri.talep_id).where(SatinAlmaTalepSatiri.onerilen_tedarikci_id == int(cari_id))
            ).all())
            if SatinAlmaTalepService._tablo_var(session):
                idler |= set(session.scalars(
                    select(SatinAlmaTalepSatiri.talep_id)
                    .join(SatinAlmaTalepSiparisBagi,
                          SatinAlmaTalepSiparisBagi.talep_satiri_id == SatinAlmaTalepSatiri.id)
                    .join(AlisSiparisi, AlisSiparisi.id == SatinAlmaTalepSiparisBagi.siparis_id)
                    .where(AlisSiparisi.cari_id == int(cari_id))
                ).all())
            if not idler:
                return []
            sonuc = []
            for t in session.scalars(
                select(SatinAlmaTalep).options(selectinload(SatinAlmaTalep.satirlar))
                .where(SatinAlmaTalep.id.in_(idler)).order_by(SatinAlmaTalep.talep_tarihi.desc(),
                                                               SatinAlmaTalep.id.desc())
            ).all():
                m = SatinAlmaTalepService._satir_miktarlari(session, t.satirlar, t.durum in ONAYLI_DURUMLAR)
                sonuc.append({
                    "id": int(t.id), "talep_no": t.talep_no, "tarih": t.talep_tarihi,
                    "ihtiyac_tarihi": t.ihtiyac_tarihi, "isteyen": t.isteyen_kullanici or "",
                    "durum": SatinAlmaTalepService._gorunen_durum(t.durum, m), "satir_adet": len(t.satirlar),
                })
            return sonuc

    @staticmethod
    def durum_degistir(talep_id: int, yeni_durum: str) -> None:
        """Eski çağrılar için uyumluluk; yeni akış fonksiyonlarına yönlendirir."""
        if yeni_durum in ("ONAY BEKLİYOR", DURUM_GONDERILDI):
            SatinAlmaTalepService.onaya_gonder(talep_id)
        elif yeni_durum == DURUM_ONAYLANDI:
            SatinAlmaTalepService.onayla(talep_id)
        elif yeni_durum == DURUM_IPTAL:
            SatinAlmaTalepService.iptal_et(talep_id)
        elif yeni_durum == ESKI_SIPARISE_AKTARILDI:
            return  # durum artık satır paylarından türetilir
        else:
            raise ValueError("Geçersiz durum.")

    # ---------------------------------------------------- siparişe aktarım
    @staticmethod
    def aktarilabilir_satirlar(arama: str | None = None) -> list[dict[str, Any]]:
        """Onaylı taleplerin kalanı olan satırları (Talepten Aktar listesi)."""
        SatinAlmaTalepService.schema_hazirla()
        n = turkce_normalize((arama or "").strip())
        sonuc = []
        with get_session() as session:
            talepler = session.scalars(
                select(SatinAlmaTalep).options(selectinload(SatinAlmaTalep.satirlar))
                .where(SatinAlmaTalep.durum.in_(ONAYLI_DURUMLAR)).order_by(SatinAlmaTalep.id)
            ).all()
            for t in talepler:
                m = SatinAlmaTalepService._satir_miktarlari(session, t.satirlar, True)
                for s in sorted(t.satirlar, key=lambda x: (x.sira or x.id, x.id)):
                    k = m[int(s.id)]
                    if k["kalan"] <= 0:
                        continue
                    if n and n not in turkce_normalize(f"{t.talep_no} {s.urun_kodu} {s.urun_adi} {t.departman or ''}"):
                        continue
                    sonuc.append({
                        "talep_id": int(t.id), "talep_no": t.talep_no, "talep_satiri_id": int(s.id),
                        "urun_kodu": s.urun_kodu, "urun_adi": s.urun_adi, "aciklama": s.aciklama or "",
                        "birim": s.birim, "onayli": k["onayli"], "siparis": k["siparis"], "kalan": k["kalan"],
                        "ihtiyac_tarihi": s.ihtiyac_tarihi or t.ihtiyac_tarihi, "oncelik": t.oncelik,
                        "eslesmemis": bool(s.manuel) and not s.stok_id,
                        "onerilen_tedarikci_id": s.onerilen_tedarikci_id,
                    })
        return sonuc

    @staticmethod
    def siparis_satirlari_hazirla(miktarlar: dict[int, Any]) -> dict[str, Any]:
        """{talep_satiri_id: miktar} → alış siparişi satır sözlükleri (``talep_paylari`` ile).

        "Sipariş Oluştur" ve "Talepten Aktar" aynı fonksiyonu kullanır. Burada hiçbir
        miktar tüketilmez; tüketim sipariş kaydında olur.
        """
        from database.models.stok import StokKarti
        from database.stok_service import StokService

        yetki_zorunlu("alis_siparis_duzenleme", "alis_duzenleme")
        yetki_zorunlu("alis_talep_aktarim", "alis_talep_onay", "alis_duzenleme",
                      mesaj="Talebi siparişe aktarma yetkiniz yok.")
        SatinAlmaTalepService.schema_hazirla()
        if not miktarlar:
            raise ValueError("Aktarılacak talep satırı seçin.")
        satirlar = []
        tedarikciler = set()
        with get_session() as session:
            for sid, mik in miktarlar.items():
                miktar = decimal(mik, "Aktarım miktarı", Decimal("0.0001"))
                s = session.get(SatinAlmaTalepSatiri, int(sid))
                if s is None:
                    raise ValueError("Talep satırı bulunamadı.")
                t = session.get(SatinAlmaTalep, int(s.talep_id))
                if t.durum not in ONAYLI_DURUMLAR:
                    raise ValueError(f"{t.talep_no} onaylı değil; siparişe aktarılamaz.")
                if s.manuel and not s.stok_id:
                    raise ValueError(
                        f"{t.talep_no} / '{s.urun_adi}' manuel satır; önce bir stok kartıyla eşleştirin."
                    )
                k = SatinAlmaTalepService._satir_miktarlari(session, [s], True)[int(s.id)]
                if miktar > k["kalan"]:
                    raise ValueError(
                        f"{t.talep_no} / {s.urun_kodu}: aktarım miktarı kalan miktarı "
                        f"({k['kalan'].normalize():f} {s.birim}) aşamaz."
                    )
                stok = session.get(StokKarti, int(s.stok_id)) if s.stok_id else None
                kod = stok.stok_kodu if stok else s.urun_kodu
                if s.onerilen_tedarikci_id:
                    tedarikciler.add(int(s.onerilen_tedarikci_id))
                satirlar.append({
                    "urun_kodu": kod,
                    "urun_adi": stok.stok_adi if stok else s.urun_adi,
                    "aciklama": s.aciklama or "",
                    "miktar": miktar,
                    "birim": s.birim,
                    "birim_alis_fiyati": _d(StokService.son_alis_fiyati(kod, Decimal("0"))),
                    "iskonto_orani": Decimal("0"),
                    "kdv_orani": Decimal(str(getattr(stok, "kdv_orani", 20) or 20)),
                    "talep_paylari": [{"talep_satiri_id": int(s.id), "miktar": miktar, "talep_no": t.talep_no}],
                })
            sorun = StokService.belge_birim_sorunu(session, satirlar, "Satın alma talebi",
                                                   eylem="siparişe aktarılamaz")
            if sorun is not None:
                raise sorun
        return {"satirlar": satirlar, "onerilen_tedarikci_id": tedarikciler.pop() if len(tedarikciler) == 1 else None}

    @staticmethod
    def siparis_paylari(siparis_id: int) -> dict[int, list[dict[str, Any]]]:
        """Sipariş satırı id → bağlı talep payları (sipariş kartı yeniden açılınca korunur)."""
        with get_session() as session:
            if not SatinAlmaTalepService._tablo_var(session):
                return {}
            rows = session.execute(
                select(SatinAlmaTalepSiparisBagi, SatinAlmaTalep.talep_no)
                .join(SatinAlmaTalepSatiri, SatinAlmaTalepSatiri.id == SatinAlmaTalepSiparisBagi.talep_satiri_id)
                .join(SatinAlmaTalep, SatinAlmaTalep.id == SatinAlmaTalepSatiri.talep_id)
                .where(SatinAlmaTalepSiparisBagi.siparis_id == int(siparis_id))
                .order_by(SatinAlmaTalepSiparisBagi.id)
            ).all()
        sonuc: dict[int, list[dict[str, Any]]] = {}
        for b, no in rows:
            sonuc.setdefault(int(b.siparis_satiri_id), []).append(
                {"talep_satiri_id": int(b.talep_satiri_id), "miktar": _d(b.miktar), "talep_no": no}
            )
        return sonuc

    @staticmethod
    def siparis_baglarini_yaz(session, siparis, satir_verileri: list[dict[str, Any]]) -> None:
        """AlisSiparisiService.kaydet içinde, satırlar flush edildikten sonra çağrılır."""
        from database.models.alis_siparisi import AlisSiparisi

        paylar_var = any(v.get("talep_paylari") for v in satir_verileri)
        if not SatinAlmaTalepService._tablo_var(session):
            if paylar_var:
                raise ValueError("Talep tabloları hazır değil; sipariş kaydından önce şema hazırlanmalı.")
            return
        eski = session.scalars(
            select(SatinAlmaTalepSiparisBagi).where(SatinAlmaTalepSiparisBagi.siparis_id == int(siparis.id))
        ).all()
        eski_toplam: dict[int, Decimal] = {}
        for b in eski:
            eski_toplam[int(b.talep_satiri_id)] = eski_toplam.get(int(b.talep_satiri_id), SIFIR) + _d(b.miktar)
            session.delete(b)
        session.flush()
        if siparis.durum == "İPTAL":
            return
        yeni_toplam: dict[int, Decimal] = {}
        satirlar = list(siparis.satirlar)
        for satir, veri in zip(satirlar, satir_verileri):
            paylar = veri.get("talep_paylari") or []
            acik = _d(satir.miktar)
            for pay in paylar:
                miktar = min(_d(pay.get("miktar")), acik)
                if miktar <= 0:
                    continue
                ts = session.get(SatinAlmaTalepSatiri, int(pay["talep_satiri_id"]))
                if ts is None:
                    raise ValueError("Bağlı talep satırı bulunamadı.")
                t = session.get(SatinAlmaTalep, int(ts.talep_id))
                if t.durum not in ONAYLI_DURUMLAR:
                    raise ValueError(f"{t.talep_no} onaylı değil; siparişe bağlanamaz.")
                if ts.manuel and not ts.stok_id:
                    raise ValueError(f"{t.talep_no} / '{ts.urun_adi}' manuel satır stok kartıyla eşleştirilmemiş.")
                if (ts.birim or "").casefold() != (satir.birim or "").casefold():
                    raise ValueError(
                        f"{t.talep_no} / {ts.urun_kodu}: talep birimi ({ts.birim}) ile sipariş birimi "
                        f"({satir.birim}) aynı olmalıdır."
                    )
                session.add(SatinAlmaTalepSiparisBagi(
                    talep_satiri_id=int(ts.id), siparis_id=int(siparis.id), siparis_satiri_id=int(satir.id),
                    miktar=miktar,
                ))
                acik -= miktar
                yeni_toplam[int(ts.id)] = yeni_toplam.get(int(ts.id), SIFIR) + miktar
        session.flush()
        for ts_id in set(yeni_toplam) | set(eski_toplam):
            ts = session.get(SatinAlmaTalepSatiri, ts_id)
            if ts is None:
                continue
            t = session.get(SatinAlmaTalep, int(ts.talep_id))
            toplam_aktif = _d(session.scalar(
                select(func.coalesce(func.sum(SatinAlmaTalepSiparisBagi.miktar), 0))
                .join(AlisSiparisi, AlisSiparisi.id == SatinAlmaTalepSiparisBagi.siparis_id)
                .where(SatinAlmaTalepSiparisBagi.talep_satiri_id == ts_id, AlisSiparisi.durum != "İPTAL")
            ))
            tavan = _d(ts.miktar) + _d(ts.yeniden_acilan_miktar)
            if toplam_aktif + _d(ts.iptal_miktar) > tavan:
                kalan = max(SIFIR, tavan - _d(ts.iptal_miktar) - (toplam_aktif - yeni_toplam.get(ts_id, SIFIR)))
                raise ValueError(
                    f"{t.talep_no} / {ts.urun_kodu}: talebin kalan miktarı ({kalan.normalize():f} {ts.birim}) aşıldı."
                )
            fark = yeni_toplam.get(ts_id, SIFIR) - eski_toplam.get(ts_id, SIFIR)
            if fark > 0 and not yetki_var("alis_talep_aktarim", "alis_talep_onay", "alis_duzenleme"):
                raise ValueError("Talebi siparişe aktarma yetkiniz yok.")
            if fark:
                SatinAlmaTalepService._gecmis(
                    session, t.id, "SİPARİŞE AKTAR" if fark > 0 else "SİPARİŞTEN GERİ AÇ", t.durum, t.durum,
                    f"{siparis.siparis_no}: {ts.urun_kodu} {fark.normalize():+f} {ts.birim}",
                )

    @staticmethod
    def manuel_satiri_eslestir(talep_satiri_id: int, stok_kodu: str) -> None:
        from database.models.stok import StokKarti

        yazma_zorunlu("alis_talep_duzenleme", "alis_siparis_duzenleme", "alis_duzenleme")
        SatinAlmaTalepService.schema_hazirla()
        with get_session() as session:
            s = session.get(SatinAlmaTalepSatiri, int(talep_satiri_id))
            if s is None:
                raise ValueError("Talep satırı bulunamadı.")
            t = session.get(SatinAlmaTalep, int(s.talep_id))
            if t.durum == DURUM_IPTAL:
                raise ValueError("İptal edilmiş talep değiştirilemez.")
            stok = session.scalar(select(StokKarti).where(StokKarti.stok_kodu == (stok_kodu or "").strip()))
            if stok is None:
                raise ValueError("Stok kartı bulunamadı.")
            if SatinAlmaTalepService._tablo_var(session) and session.scalar(
                select(func.count()).select_from(SatinAlmaTalepSiparisBagi)
                .where(SatinAlmaTalepSiparisBagi.talep_satiri_id == s.id)
            ):
                raise ValueError("Siparişe aktarılmış satırın stok eşleşmesi değiştirilemez.")
            eski = f"{s.urun_kodu or '-'} {s.urun_adi}"
            s.stok_id = int(stok.id)
            s.urun_kodu = stok.stok_kodu
            if not s.aciklama:
                s.aciklama = s.urun_adi
            s.urun_adi = stok.stok_adi
            t.row_version = int(t.row_version or 1) + 1
            SatinAlmaTalepService._gecmis(session, t.id, "STOK EŞLEŞTİR", t.durum, t.durum,
                                          f"{eski} → {stok.stok_kodu} {stok.stok_adi}")

    # ------------------------------------------------------------- rapor
    @staticmethod
    def urun_bazli_rapor(baslangic: date | None = None, bitis: date | None = None, *, depo: str | None = None,
                         stok: str | None = None) -> list[dict[str, Any]]:
        """Ürün + birim bazında talep akışı. Farklı birimler ayrı satırda kalır, toplanmaz.

        ``kalan`` siparişe aktarılmamış açık ihtiyaç; ``bekleyen_teslim`` sipariş verilmiş ama teslim alınmamış.
        """
        yetki_zorunlu("alis_talep_goruntuleme", "alis_talep_duzenleme", "alis_talep_onay", "alis_rapor_goruntuleme",
                      mesaj="Satın alma talep raporu için yetkiniz yok.")
        SatinAlmaTalepService.schema_hazirla()
        toplam: dict[tuple, dict] = {}
        depo = (depo or "").strip()
        if depo in ("Tümü", "TÜMÜ"):
            depo = ""
        n_stok = turkce_normalize((stok or "").strip())
        with get_session() as session:
            q = select(SatinAlmaTalep).options(selectinload(SatinAlmaTalep.satirlar)).where(
                SatinAlmaTalep.durum != DURUM_IPTAL)
            if baslangic:
                q = q.where(SatinAlmaTalep.talep_tarihi >= baslangic)
            if bitis:
                q = q.where(SatinAlmaTalep.talep_tarihi <= bitis)
            for t in session.scalars(q).all():
                m = SatinAlmaTalepService._satir_miktarlari(session, t.satirlar, t.durum in ONAYLI_DURUMLAR)
                for s in t.satirlar:
                    if depo and (s.depo or t.depo or "") != depo:
                        continue
                    if n_stok and n_stok not in turkce_normalize(f"{s.urun_kodu or ''} {s.urun_adi}"):
                        continue
                    k = m[int(s.id)]
                    anahtar = (s.urun_kodu or "", s.urun_adi if not s.urun_kodu else "", s.birim)
                    r = toplam.setdefault(anahtar, {
                        "urun_kodu": s.urun_kodu, "urun_adi": s.urun_adi, "birim": s.birim, "talep_sayisi": 0,
                        **{a: SIFIR for a in RAPOR_ALANLARI},
                    })
                    r["talep_sayisi"] += 1
                    for alan in RAPOR_ALANLARI:
                        r[alan] += k[alan]
        return sorted(toplam.values(), key=lambda r: (r["urun_kodu"] or "", r["urun_adi"] or ""))

    # -------------------------------------------------------------- ekler
    @staticmethod
    def _ek_klasoru(talep_id: int) -> Path:
        from database.database import company_db

        kok = Path(company_db._db_path).parent if company_db._db_path else Path.cwd()
        return kok / "ekler" / "satin_alma_talep" / str(int(talep_id))

    @staticmethod
    def ek_ekle(talep_id: int, kaynak_yol: str) -> int:
        yazma_zorunlu("alis_talep_duzenleme", "alis_duzenleme")
        SatinAlmaTalepService.schema_hazirla()
        kaynak = Path(kaynak_yol)
        if not kaynak.is_file():
            raise ValueError("Dosya bulunamadı.")
        if kaynak.suffix.lower() not in EK_UZANTILARI:
            raise ValueError(
                f"'{kaynak.suffix or 'uzantısız'}' türündeki dosya eklenemez.\n"
                f"İzin verilen türler: {', '.join(sorted(EK_UZANTILARI))}"
            )
        boyut = kaynak.stat().st_size
        if boyut <= 0:
            raise ValueError("Boş dosya eklenemez.")
        if boyut > EK_AZAMI_BAYT:
            raise ValueError(
                f"Dosya çok büyük ({boyut / 1024 / 1024:.1f} MB). En fazla {EK_AZAMI_BAYT // 1024 // 1024} MB eklenebilir."
            )
        with get_session() as session:
            if session.get(SatinAlmaTalep, int(talep_id)) is None:
                raise ValueError("Talep bulunamadı; önce talebi kaydedin.")
        klasor = SatinAlmaTalepService._ek_klasoru(talep_id)
        klasor.mkdir(parents=True, exist_ok=True)
        hedef = klasor / kaynak.name
        sayac = 1
        while hedef.exists():
            hedef = klasor / f"{kaynak.stem}_{sayac}{kaynak.suffix}"
            sayac += 1
        shutil.copy2(kaynak, hedef)
        with get_session() as session:
            e = SatinAlmaTalepEki(talep_id=int(talep_id), dosya_adi=hedef.name,
                                  goreli_yol=str(hedef.relative_to(klasor.parent.parent.parent)), ekleyen=_kullanici())
            session.add(e)
            session.flush()
            SatinAlmaTalepService._gecmis(session, talep_id, "EK EKLE", None, None, hedef.name)
            return int(e.id)

    @staticmethod
    def ek_sil(ek_id: int) -> None:
        """Ek kaydını ve programın ek klasöründeki kopyasını kaldırır (kaynak dosyaya dokunmaz)."""
        yazma_zorunlu("alis_talep_duzenleme", "alis_duzenleme")
        with get_session() as session:
            e = session.get(SatinAlmaTalepEki, int(ek_id))
            if e is None:
                raise ValueError("Ek bulunamadı.")
            t = session.get(SatinAlmaTalep, int(e.talep_id))
            if t is not None and t.durum not in (DURUM_TASLAK, DURUM_REDDEDILDI):
                raise ValueError(f"'{t.durum}' durumundaki talebin eki kaldırılamaz.")
            yol = SatinAlmaTalepService._ek_klasoru(e.talep_id) / e.dosya_adi
            SatinAlmaTalepService._gecmis(session, e.talep_id, "EK SİL", None, None, e.dosya_adi)
            session.delete(e)
        try:
            yol.unlink(missing_ok=True)
        except OSError:
            pass

    @staticmethod
    def ek_yolu(ek_id: int) -> Path:
        with get_session() as session:
            e = session.get(SatinAlmaTalepEki, int(ek_id))
            if e is None:
                raise ValueError("Ek bulunamadı.")
            yol = SatinAlmaTalepService._ek_klasoru(e.talep_id) / e.dosya_adi
        if not yol.is_file():
            raise ValueError(
                f"'{e.dosya_adi}' eki kayıtlı ancak dosya diskte bulunamadı.\n"
                f"Beklenen konum: {yol}\nDosya taşınmış veya silinmiş olabilir; ek listesinden kaldırıp yeniden ekleyin."
            )
        return yol
