"""Üç seviyeli stok grubu servisi (Ana → Tali → Alt)."""

from __future__ import annotations

import logging
import re
from datetime import datetime
from typing import Any

from sqlalchemy import func, or_, select

from database.access import yazma_zorunlu, yetki_zorunlu
from database.database import get_session
from database.models.stok import StokGrubu, StokKarti, StokSecenek
from database.user_audit import audit_document

logger = logging.getLogger(__name__)

SEVIYE_ANA = 1
SEVIYE_TALI = 2
SEVIYE_ALT = 3
SEVIYE_ADLARI = {1: "Ana Grup", 2: "Tali Grup", 3: "Alt Grup"}


def _norm(metin: str | None) -> str:
    return (metin or "").strip()


def _kod_uret(ad: str) -> str:
    temiz = re.sub(r"[^A-Za-z0-9ÇĞİÖŞÜçğıöşü]+", "", (ad or "").upper())
    return (temiz[:20] or "GRUP")


def _grup_dict(g: StokGrubu, *, yol: str | None = None, stok_adet: int | None = None, cocuk_adet: int | None = None) -> dict:
    return {
        "id": int(g.id),
        "kod": g.kod or "",
        "ad": g.ad or "",
        "seviye": int(g.seviye),
        "seviye_adi": SEVIYE_ADLARI.get(int(g.seviye), str(g.seviye)),
        "parent_id": int(g.parent_id) if g.parent_id else None,
        "aciklama": g.aciklama or "",
        "sira_no": int(g.sira_no or 0),
        "aktif": bool(g.aktif),
        "yol": yol or "",
        "stok_adet": stok_adet,
        "cocuk_adet": cocuk_adet,
        "etiket": f"{(g.kod or '').strip()} — {(g.ad or '').strip()}".strip(" —"),
    }


class StokGrupService:
    @staticmethod
    def yol_metni(ana=None, tali=None, alt=None) -> str:
        parcalar = []
        for g in (ana, tali, alt):
            if g is None:
                continue
            ad = getattr(g, "ad", None) or (g.get("ad") if isinstance(g, dict) else None)
            if ad:
                parcalar.append(str(ad).strip())
        return " / ".join(parcalar)

    @staticmethod
    def _parent_seviye_kontrol(seviye: int, parent: StokGrubu | None) -> None:
        if seviye == SEVIYE_ANA:
            if parent is not None:
                raise ValueError("Ana grubun üst grubu olamaz.")
            return
        if parent is None:
            raise ValueError(f"{SEVIYE_ADLARI[seviye]} için üst grup zorunludur.")
        if seviye == SEVIYE_TALI and int(parent.seviye) != SEVIYE_ANA:
            raise ValueError("Tali grup yalnızca bir Ana Gruba bağlanabilir.")
        if seviye == SEVIYE_ALT and int(parent.seviye) != SEVIYE_TALI:
            raise ValueError("Alt grup yalnızca bir Tali Gruba bağlanabilir.")

    @staticmethod
    def _mukerrer_kontrol(session, *, seviye: int, parent_id: int | None, kod: str, ad: str, haric_id: int | None = None):
        q = select(StokGrubu).where(StokGrubu.seviye == seviye)
        if parent_id is None:
            q = q.where(StokGrubu.parent_id.is_(None))
        else:
            q = q.where(StokGrubu.parent_id == parent_id)
        if haric_id:
            q = q.where(StokGrubu.id != haric_id)
        for g in session.scalars(q).all():
            if (g.kod or "").casefold() == kod.casefold():
                raise ValueError(f"Aynı üst altında «{g.kod}» kodlu grup zaten var.")
            if (g.ad or "").casefold() == ad.casefold():
                raise ValueError(f"Aynı üst altında «{g.ad}» adlı grup zaten var.")

    @staticmethod
    def getir(grup_id: int) -> dict | None:
        with get_session() as session:
            g = session.get(StokGrubu, int(grup_id))
            if g is None:
                return None
            return _grup_dict(g, yol=StokGrupService._yol_session(session, g))

    @staticmethod
    def _yol_session(session, g: StokGrubu) -> str:
        parcalar = [g.ad]
        cur = g
        while cur.parent_id:
            cur = session.get(StokGrubu, cur.parent_id)
            if cur is None:
                break
            parcalar.insert(0, cur.ad)
        return " / ".join(p for p in parcalar if p)

    @staticmethod
    def listele(*, seviye: int | None = None, parent_id: int | None = None, aktif_only: bool = True, arama: str = "") -> list[dict]:
        yetki_zorunlu("stok_goruntuleme", "goruntuleme")
        with get_session() as session:
            q = select(StokGrubu).order_by(StokGrubu.sira_no, StokGrubu.ad)
            if seviye is not None:
                q = q.where(StokGrubu.seviye == int(seviye))
            if parent_id is not None:
                q = q.where(StokGrubu.parent_id == int(parent_id))
            if aktif_only:
                q = q.where(StokGrubu.aktif.is_(True))
            arama_n = _norm(arama)
            kayitlar = list(session.scalars(q).all())
            if arama_n:
                a = arama_n.casefold()
                kayitlar = [
                    g
                    for g in kayitlar
                    if a in (g.kod or "").casefold()
                    or a in (g.ad or "").casefold()
                    or a in (g.aciklama or "").casefold()
                ]
            return [_grup_dict(g, yol=StokGrupService._yol_session(session, g)) for g in kayitlar]

    @staticmethod
    def agac(*, aktif_only: bool = False, arama: str = "") -> list[dict]:
        """Açılır ağaç için hiyerarşik liste."""
        yetki_zorunlu("stok_goruntuleme", "goruntuleme")
        with get_session() as session:
            q = select(StokGrubu).order_by(StokGrubu.sira_no, StokGrubu.ad)
            if aktif_only:
                q = q.where(StokGrubu.aktif.is_(True))
            tum = list(session.scalars(q).all())
            by_parent: dict[int | None, list[StokGrubu]] = {}
            for g in tum:
                by_parent.setdefault(g.parent_id, []).append(g)

            arama_n = _norm(arama).casefold()

            def eslesir(g: StokGrubu) -> bool:
                if not arama_n:
                    return True
                return (
                    arama_n in (g.kod or "").casefold()
                    or arama_n in (g.ad or "").casefold()
                    or arama_n in (g.aciklama or "").casefold()
                )

            def cocuk_eslesir(g: StokGrubu) -> bool:
                if eslesir(g):
                    return True
                return any(cocuk_eslesir(c) for c in by_parent.get(g.id, []))

            def dugum(g: StokGrubu, yol_ust: str) -> dict | None:
                if arama_n and not cocuk_eslesir(g):
                    return None
                yol = f"{yol_ust} / {g.ad}" if yol_ust else (g.ad or "")
                cocuklar = []
                for c in by_parent.get(g.id, []):
                    d = dugum(c, yol)
                    if d is not None:
                        cocuklar.append(d)
                stok_adet = StokGrupService._stok_sayisi_session(session, g.id, g.seviye)
                return {
                    **_grup_dict(g, yol=yol, stok_adet=stok_adet, cocuk_adet=len(by_parent.get(g.id, []))),
                    "cocuklar": cocuklar,
                }

            kokler = []
            for g in by_parent.get(None, []):
                d = dugum(g, "")
                if d is not None:
                    kokler.append(d)
            return kokler

    @staticmethod
    def _stok_sayisi_session(session, grup_id: int, seviye: int) -> int:
        kolon = {SEVIYE_ANA: StokKarti.ana_grup_id, SEVIYE_TALI: StokKarti.tali_grup_id, SEVIYE_ALT: StokKarti.alt_grup_id}.get(
            int(seviye)
        )
        if kolon is None:
            return 0
        return int(
            session.scalar(
                select(func.count())
                .select_from(StokKarti)
                .where(
                    kolon == int(grup_id),
                    or_(StokKarti.is_deleted.is_(False), StokKarti.is_deleted.is_(None)),
                )
            )
            or 0
        )

    @staticmethod
    def detay(grup_id: int) -> dict:
        yetki_zorunlu("stok_goruntuleme", "goruntuleme")
        with get_session() as session:
            g = session.get(StokGrubu, int(grup_id))
            if g is None:
                raise ValueError("Grup bulunamadı.")
            parent = session.get(StokGrubu, g.parent_id) if g.parent_id else None
            cocuk = int(
                session.scalar(
                    select(func.count()).select_from(StokGrubu).where(StokGrubu.parent_id == g.id)
                )
                or 0
            )
            stok = StokGrupService._stok_sayisi_session(session, g.id, g.seviye)
            return {
                **_grup_dict(g, yol=StokGrupService._yol_session(session, g), stok_adet=stok, cocuk_adet=cocuk),
                "ust_grup": _grup_dict(parent) if parent else None,
            }

    @staticmethod
    def ekle(
        *,
        seviye: int,
        kod: str,
        ad: str,
        parent_id: int | None = None,
        aciklama: str | None = None,
        sira_no: int = 0,
        aktif: bool = True,
    ) -> dict:
        yazma_zorunlu("stok_duzenleme", "stok_grup_yonetme", "yeni_kayit")
        seviye = int(seviye)
        if seviye not in (SEVIYE_ANA, SEVIYE_TALI, SEVIYE_ALT):
            raise ValueError("Geçersiz grup seviyesi.")
        kod_n = _norm(kod).upper()
        ad_n = _norm(ad)
        if not kod_n:
            raise ValueError("Grup kodu zorunludur.")
        if not ad_n:
            raise ValueError("Grup adı zorunludur.")
        with get_session() as session:
            parent = session.get(StokGrubu, int(parent_id)) if parent_id else None
            StokGrupService._parent_seviye_kontrol(seviye, parent)
            pid = int(parent.id) if parent else None
            StokGrupService._mukerrer_kontrol(
                session, seviye=seviye, parent_id=pid, kod=kod_n, ad=ad_n
            )
            g = StokGrubu(
                kod=kod_n,
                ad=ad_n,
                seviye=seviye,
                parent_id=pid,
                aciklama=_norm(aciklama) or None,
                sira_no=int(sira_no or 0),
                aktif=bool(aktif),
                olusturma_tarihi=datetime.now(),
            )
            session.add(g)
            session.flush()
            # Geriye uyum: ana grubu StokSecenek rapor_grubu'na da ekle
            if seviye == SEVIYE_ANA:
                mevcut = session.scalar(
                    select(StokSecenek).where(
                        StokSecenek.tur == "rapor_grubu",
                        func.lower(StokSecenek.ad) == ad_n.casefold(),
                    )
                )
                if not mevcut:
                    session.add(StokSecenek(tur="rapor_grubu", ad=ad_n))
            audit_document(
                "stok_grup_olustur",
                modul="stok",
                kayit_id=str(g.id),
                yeni={"kod": kod_n, "ad": ad_n, "seviye": seviye, "parent_id": pid},
            )
            return _grup_dict(g, yol=StokGrupService._yol_session(session, g))

    @staticmethod
    def guncelle(grup_id: int, **alanlar) -> dict:
        yazma_zorunlu("stok_duzenleme", "stok_grup_yonetme", "duzenleme")
        with get_session() as session:
            g = session.get(StokGrubu, int(grup_id))
            if g is None:
                raise ValueError("Grup bulunamadı.")
            eski = {"kod": g.kod, "ad": g.ad, "aciklama": g.aciklama, "sira_no": g.sira_no, "aktif": g.aktif}
            kod_n = _norm(alanlar.get("kod", g.kod)).upper()
            ad_n = _norm(alanlar.get("ad", g.ad))
            if not kod_n or not ad_n:
                raise ValueError("Grup kodu ve adı zorunludur.")
            StokGrupService._mukerrer_kontrol(
                session,
                seviye=int(g.seviye),
                parent_id=g.parent_id,
                kod=kod_n,
                ad=ad_n,
                haric_id=g.id,
            )
            g.kod = kod_n
            g.ad = ad_n
            if "aciklama" in alanlar:
                g.aciklama = _norm(alanlar.get("aciklama")) or None
            if "sira_no" in alanlar:
                g.sira_no = int(alanlar.get("sira_no") or 0)
            if "aktif" in alanlar:
                g.aktif = bool(alanlar.get("aktif"))
            g.guncelleme_tarihi = datetime.now()
            session.flush()
            StokGrupService._stok_yollarini_guncelle(session, g)
            audit_document(
                "stok_grup_guncelle",
                modul="stok",
                kayit_id=str(g.id),
                eski=eski,
                yeni={"kod": g.kod, "ad": g.ad, "aciklama": g.aciklama, "sira_no": g.sira_no, "aktif": g.aktif},
            )
            return _grup_dict(g, yol=StokGrupService._yol_session(session, g))

    @staticmethod
    def _stok_yollarini_guncelle(session, g: StokGrubu) -> None:
        """Grup adı/kod değişince bağlı stokların rapor_grubu yolunu tazele."""
        kolon = {
            SEVIYE_ANA: StokKarti.ana_grup_id,
            SEVIYE_TALI: StokKarti.tali_grup_id,
            SEVIYE_ALT: StokKarti.alt_grup_id,
        }.get(int(g.seviye))
        if kolon is None:
            return
        for stok in session.scalars(select(StokKarti).where(kolon == g.id)).all():
            stok.rapor_grubu = StokGrupService._stok_yol_session(session, stok) or stok.rapor_grubu

    @staticmethod
    def _stok_yol_session(session, stok: StokKarti) -> str:
        ana = session.get(StokGrubu, stok.ana_grup_id) if stok.ana_grup_id else None
        tali = session.get(StokGrubu, stok.tali_grup_id) if stok.tali_grup_id else None
        alt = session.get(StokGrubu, stok.alt_grup_id) if stok.alt_grup_id else None
        return StokGrupService.yol_metni(ana, tali, alt)

    @staticmethod
    def tasi(grup_id: int, yeni_parent_id: int) -> dict:
        yazma_zorunlu("stok_duzenleme", "stok_grup_yonetme", "duzenleme")
        with get_session() as session:
            g = session.get(StokGrubu, int(grup_id))
            if g is None:
                raise ValueError("Grup bulunamadı.")
            if int(g.seviye) == SEVIYE_ANA:
                raise ValueError("Ana grup taşınamaz.")
            parent = session.get(StokGrubu, int(yeni_parent_id))
            if parent is None:
                raise ValueError("Hedef üst grup bulunamadı.")
            StokGrupService._parent_seviye_kontrol(int(g.seviye), parent)
            stok_adet = StokGrupService._stok_sayisi_session(session, g.id, g.seviye)
            eski_parent = g.parent_id
            StokGrupService._mukerrer_kontrol(
                session,
                seviye=int(g.seviye),
                parent_id=parent.id,
                kod=g.kod,
                ad=g.ad,
                haric_id=g.id,
            )
            g.parent_id = parent.id
            g.guncelleme_tarihi = datetime.now()
            session.flush()
            # Tali taşındıysa alt gruplu stokların ana_grup_id'sini güncelle
            if int(g.seviye) == SEVIYE_TALI:
                for stok in session.scalars(
                    select(StokKarti).where(StokKarti.tali_grup_id == g.id)
                ).all():
                    stok.ana_grup_id = parent.id
                    stok.rapor_grubu = StokGrupService._stok_yol_session(session, stok)
            elif int(g.seviye) == SEVIYE_ALT:
                tali = parent
                ana = session.get(StokGrubu, tali.parent_id) if tali.parent_id else None
                for stok in session.scalars(
                    select(StokKarti).where(StokKarti.alt_grup_id == g.id)
                ).all():
                    stok.tali_grup_id = tali.id
                    stok.ana_grup_id = ana.id if ana else None
                    stok.rapor_grubu = StokGrupService._stok_yol_session(session, stok)
            audit_document(
                "stok_grup_tasi",
                modul="stok",
                kayit_id=str(g.id),
                eski={"parent_id": eski_parent, "stok_adet": stok_adet},
                yeni={"parent_id": parent.id},
            )
            return _grup_dict(g, yol=StokGrupService._yol_session(session, g), stok_adet=stok_adet)

    @staticmethod
    def pasife_al(grup_id: int, *, altlari_da: bool | None = None) -> dict:
        yazma_zorunlu("stok_duzenleme", "stok_grup_yonetme", "duzenleme")
        with get_session() as session:
            g = session.get(StokGrubu, int(grup_id))
            if g is None:
                raise ValueError("Grup bulunamadı.")
            cocuklar = list(session.scalars(select(StokGrubu).where(StokGrubu.parent_id == g.id)).all())
            if cocuklar and altlari_da is None:
                raise ValueError(
                    f"Bu grubun {len(cocuklar)} alt kaydı var. "
                    "Alt grupları da pasife almak için onay gerekir."
                )
            g.aktif = False
            g.guncelleme_tarihi = datetime.now()
            pasif_idler = [g.id]
            if altlari_da:
                kuyruk = list(cocuklar)
                while kuyruk:
                    c = kuyruk.pop()
                    c.aktif = False
                    c.guncelleme_tarihi = datetime.now()
                    pasif_idler.append(c.id)
                    kuyruk.extend(
                        session.scalars(select(StokGrubu).where(StokGrubu.parent_id == c.id)).all()
                    )
            audit_document(
                "stok_grup_pasife",
                modul="stok",
                kayit_id=str(g.id),
                yeni={"pasif_idler": pasif_idler, "altlari_da": bool(altlari_da)},
            )
            return {"pasif_adet": len(pasif_idler)}

    @staticmethod
    def sil(grup_id: int) -> None:
        yazma_zorunlu("stok_duzenleme", "stok_grup_yonetme", "silme")
        with get_session() as session:
            g = session.get(StokGrubu, int(grup_id))
            if g is None:
                raise ValueError("Grup bulunamadı.")
            cocuk = int(
                session.scalar(
                    select(func.count()).select_from(StokGrubu).where(StokGrubu.parent_id == g.id)
                )
                or 0
            )
            if cocuk:
                raise ValueError(
                    f"«{g.kod} / {g.ad}» silinemez; altında {cocuk} grup var. "
                    "Önce alt grupları taşıyın veya silin."
                )
            stok = StokGrupService._stok_sayisi_session(session, g.id, g.seviye)
            if stok:
                raise ValueError(
                    f"«{g.kod} / {g.ad}» silinemez; {stok} stok kartı bağlı. "
                    "Önce stokları taşıyın veya grubu pasife alın."
                )
            eski = {"kod": g.kod, "ad": g.ad, "seviye": g.seviye}
            session.delete(g)
            session.flush()
            audit_document("stok_grup_sil", modul="stok", kayit_id=str(grup_id), eski=eski)

    @staticmethod
    def hiyerarsi_dogrula(ana_id: int | None, tali_id: int | None, alt_id: int | None) -> dict:
        """Stok kaydı öncesi üç seviyenin tutarlılığını doğrular."""
        with get_session() as session:
            ana = session.get(StokGrubu, int(ana_id)) if ana_id else None
            tali = session.get(StokGrubu, int(tali_id)) if tali_id else None
            alt = session.get(StokGrubu, int(alt_id)) if alt_id else None
            if tali and not ana:
                raise ValueError("Tali grup seçildiyse Ana Grup zorunludur.")
            if alt and not tali:
                raise ValueError("Alt grup seçildiyse Tali Grup zorunludur.")
            if ana and int(ana.seviye) != SEVIYE_ANA:
                raise ValueError("Seçilen Ana Grup geçersiz seviyede.")
            if tali:
                if int(tali.seviye) != SEVIYE_TALI:
                    raise ValueError("Seçilen Tali Grup geçersiz seviyede.")
                if ana and tali.parent_id != ana.id:
                    raise ValueError("Tali grup seçilen Ana Gruba bağlı değil.")
            if alt:
                if int(alt.seviye) != SEVIYE_ALT:
                    raise ValueError("Seçilen Alt Grup geçersiz seviyede.")
                if tali and alt.parent_id != tali.id:
                    raise ValueError("Alt grup seçilen Tali Gruba bağlı değil.")
            # Pasif uyarı bilgisi
            pasifler = [g.ad for g in (ana, tali, alt) if g is not None and not g.aktif]
            return {
                "ana_grup_id": ana.id if ana else None,
                "tali_grup_id": tali.id if tali else None,
                "alt_grup_id": alt.id if alt else None,
                "rapor_grubu": StokGrupService.yol_metni(ana, tali, alt) or None,
                "pasif_uyari": pasifler,
            }

    @staticmethod
    def stoklara_ata(stok_idler: list[int], *, ana_id=None, tali_id=None, alt_id=None) -> dict:
        yazma_zorunlu("stok_duzenleme", "stok_grup_yonetme", "duzenleme")
        dog = StokGrupService.hiyerarsi_dogrula(ana_id, tali_id, alt_id)
        with get_session() as session:
            adet = 0
            for sid in stok_idler or []:
                stok = session.get(StokKarti, int(sid))
                if stok is None or getattr(stok, "is_deleted", False):
                    continue
                stok.ana_grup_id = dog["ana_grup_id"]
                stok.tali_grup_id = dog["tali_grup_id"]
                stok.alt_grup_id = dog["alt_grup_id"]
                stok.rapor_grubu = dog["rapor_grubu"]
                if dog["rapor_grubu"]:
                    mevcut = session.scalar(
                        select(StokSecenek).where(
                            StokSecenek.tur == "rapor_grubu",
                            func.lower(StokSecenek.ad) == dog["rapor_grubu"].casefold(),
                        )
                    )
                    if not mevcut:
                        # Yol çok uzun olabilir; ana grubu seçenek olarak tut
                        ana = session.get(StokGrubu, dog["ana_grup_id"]) if dog["ana_grup_id"] else None
                        if ana:
                            var2 = session.scalar(
                                select(StokSecenek).where(
                                    StokSecenek.tur == "rapor_grubu",
                                    func.lower(StokSecenek.ad) == (ana.ad or "").casefold(),
                                )
                            )
                            if not var2:
                                session.add(StokSecenek(tur="rapor_grubu", ad=ana.ad))
                adet += 1
            session.flush()
            audit_document(
                "stok_grup_toplu_ata",
                modul="stok",
                kayit_id=",".join(str(i) for i in (stok_idler or [])[:20]),
                yeni={**dog, "adet": adet},
            )
            return {"adet": adet, **dog}

    @staticmethod
    def migration_rapor_grubundan() -> dict[str, Any]:
        """Mevcut düz rapor_grubu değerlerini Ana Grup olarak dönüştür."""
        with get_session() as session:
            once_grup = int(session.scalar(select(func.count()).select_from(StokGrubu)) or 0)
            once_bagli = int(
                session.scalar(
                    select(func.count())
                    .select_from(StokKarti)
                    .where(StokKarti.ana_grup_id.is_not(None))
                )
                or 0
            )
            # Distinct rapor_grubu
            degerler = [
                d
                for d in session.scalars(
                    select(StokKarti.rapor_grubu)
                    .where(StokKarti.rapor_grubu.is_not(None), StokKarti.rapor_grubu != "")
                    .distinct()
                ).all()
                if d
            ]
            # StokSecenek'teki rapor grupları
            secenekler = list(
                session.scalars(
                    select(StokSecenek.ad).where(StokSecenek.tur == "rapor_grubu")
                ).all()
            )
            adlar = []
            gorulen = set()
            for ad in list(degerler) + list(secenekler):
                a = _norm(ad)
                if not a:
                    continue
                # Yol ise yalnızca ilk parçayı ana grup yap
                ilk = a.split("/")[0].strip() if "/" in a else a
                key = ilk.casefold()
                if key in gorulen:
                    continue
                gorulen.add(key)
                adlar.append(ilk)

            olusan = 0
            eslesen = 0
            for ad in adlar:
                mevcut = session.scalar(
                    select(StokGrubu).where(
                        StokGrubu.seviye == SEVIYE_ANA,
                        func.lower(StokGrubu.ad) == ad.casefold(),
                    )
                )
                if mevcut is None:
                    kod = _kod_uret(ad)
                    # kod çakışması
                    i = 1
                    baz = kod
                    while session.scalar(
                        select(StokGrubu).where(
                            StokGrubu.seviye == SEVIYE_ANA,
                            func.lower(StokGrubu.kod) == kod.casefold(),
                        )
                    ):
                        i += 1
                        kod = f"{baz}{i}"
                    mevcut = StokGrubu(
                        kod=kod,
                        ad=ad,
                        seviye=SEVIYE_ANA,
                        parent_id=None,
                        aktif=True,
                        sira_no=0,
                        olusturma_tarihi=datetime.now(),
                    )
                    session.add(mevcut)
                    session.flush()
                    olusan += 1
                # Stokları bağla (henüz ana_grup_id yoksa)
                for stok in session.scalars(
                    select(StokKarti).where(
                        StokKarti.ana_grup_id.is_(None),
                        or_(
                            func.lower(StokKarti.rapor_grubu) == ad.casefold(),
                            StokKarti.rapor_grubu.ilike(f"{ad} /%"),
                        ),
                    )
                ).all():
                    stok.ana_grup_id = mevcut.id
                    # Tali/alt yoksa rapor_grubu ana ad olarak kalsın veya yol ise olduğu gibi
                    if not (stok.rapor_grubu or "").strip():
                        stok.rapor_grubu = ad
                    eslesen += 1
            session.flush()
            sonra_grup = int(session.scalar(select(func.count()).select_from(StokGrubu)) or 0)
            sonra_bagli = int(
                session.scalar(
                    select(func.count())
                    .select_from(StokKarti)
                    .where(StokKarti.ana_grup_id.is_not(None))
                )
                or 0
            )
            rapor = {
                "once_grup": once_grup,
                "sonra_grup": sonra_grup,
                "olusan_ana_grup": olusan,
                "once_bagli_stok": once_bagli,
                "sonra_bagli_stok": sonra_bagli,
                "eslesen_stok": eslesen,
                "kaynak_ad_adet": len(adlar),
            }
            logger.info("stok_grup_migration %s", rapor)
            return rapor

    @staticmethod
    def ozet_rapor(*, ana_id=None, tali_id=None, alt_id=None) -> list[dict]:
        """Grup bazlı stok adedi / miktar / FIFO değer özeti."""
        yetki_zorunlu("stok_goruntuleme", "goruntuleme")
        from decimal import Decimal
        from database.models.stok import StokLotu

        with get_session() as session:
            q = select(StokKarti).where(
                or_(StokKarti.is_deleted.is_(False), StokKarti.is_deleted.is_(None))
            )
            if alt_id:
                q = q.where(StokKarti.alt_grup_id == int(alt_id))
            elif tali_id:
                q = q.where(StokKarti.tali_grup_id == int(tali_id))
            elif ana_id:
                q = q.where(StokKarti.ana_grup_id == int(ana_id))
            stoklar = list(session.scalars(q).all())
            # Grupla: en spesifik seviye
            buckets: dict[tuple, dict] = {}
            for stok in stoklar:
                ana = session.get(StokGrubu, stok.ana_grup_id) if stok.ana_grup_id else None
                tali = session.get(StokGrubu, stok.tali_grup_id) if stok.tali_grup_id else None
                alt = session.get(StokGrubu, stok.alt_grup_id) if stok.alt_grup_id else None
                key = (
                    ana.id if ana else 0,
                    tali.id if tali else 0,
                    alt.id if alt else 0,
                )
                if key not in buckets:
                    buckets[key] = {
                        "ana": ana.ad if ana else "—",
                        "tali": tali.ad if tali else "—",
                        "alt": alt.ad if alt else "—",
                        "yol": StokGrupService.yol_metni(ana, tali, alt) or "(grup yok)",
                        "stok_adet": 0,
                        "miktar": Decimal("0"),
                        "fifo_deger": Decimal("0"),
                    }
                b = buckets[key]
                b["stok_adet"] += 1
                lotlar = session.scalars(
                    select(StokLotu).where(StokLotu.stok_id == stok.id)
                ).all()
                for lot in lotlar:
                    b["miktar"] += Decimal(str(lot.kalan_miktar or 0))
                    b["fifo_deger"] += Decimal(str(lot.kalan_miktar or 0)) * Decimal(
                        str(lot.birim_maliyet or 0)
                    )
            satirlar = sorted(buckets.values(), key=lambda x: x["yol"].casefold())
            for s in satirlar:
                s["miktar"] = f"{s['miktar']:f}".rstrip("0").rstrip(".")
                s["fifo_deger"] = float(s["fifo_deger"])
            return satirlar
