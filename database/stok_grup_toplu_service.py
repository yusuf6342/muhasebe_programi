"""Toplu stok grubu eşleştirme — önizleme, uygulama, geri alma."""

from __future__ import annotations

import logging
import uuid
from datetime import datetime
from decimal import Decimal
from typing import Any, Iterable

from sqlalchemy import and_, func, or_, select
from sqlalchemy.orm import selectinload

from database.access import yazma_zorunlu, yetki_var, yetki_zorunlu
from database.database import get_session
from database.models.stok import (
    StokBarkod,
    StokGrubu,
    StokGrupTopluIslem,
    StokGrupTopluIslemSatiri,
    StokKarti,
    StokLotu,
)
from database.session_manager import oturum
from database.stok_grup_service import StokGrupService
from database.user_audit import audit_document

logger = logging.getLogger(__name__)

POLITIKA_SADECE_GRUPSUZ = "sadece_grupsuz"
POLITIKA_DEGISTIR = "grubu_degistir"
POLITIKA_EKSIK_TAMAMLA = "eksik_tamamla"

DURUM_ESLESTIRILECEK = "eslestirilecek"
DURUM_DEGISTIRILECEK = "grubu_degistirilecek"
DURUM_DEGISIKLIK_YOK = "degisiklik_yok"
DURUM_ATLANACAK = "atlanacak"
DURUM_HATALI = "hatali"
DURUM_YETKI_YOK = "yetki_yok"


def _islem_no() -> str:
    ts = datetime.now().strftime("%Y%m%d%H%M%S")
    return f"TGE-{ts}-{uuid.uuid4().hex[:6].upper()}"


def _hiyerarsi_bozuk(session, stok: StokKarti) -> str | None:
    """Mevcut grup id'leri tutarsızsa açıklama döner."""
    ana = session.get(StokGrubu, stok.ana_grup_id) if stok.ana_grup_id else None
    tali = session.get(StokGrubu, stok.tali_grup_id) if stok.tali_grup_id else None
    alt = session.get(StokGrubu, stok.alt_grup_id) if stok.alt_grup_id else None
    if stok.tali_grup_id and not stok.ana_grup_id:
        return "Tali grup var, ana grup yok"
    if stok.alt_grup_id and not stok.tali_grup_id:
        return "Alt grup var, tali grup yok"
    if stok.ana_grup_id and ana is None:
        return "Ana grup kaydı bulunamadı"
    if stok.tali_grup_id and tali is None:
        return "Tali grup kaydı bulunamadı"
    if stok.alt_grup_id and alt is None:
        return "Alt grup kaydı bulunamadı"
    if ana and int(ana.seviye) != 1:
        return "Ana grup seviyesi hatalı"
    if tali and int(tali.seviye) != 2:
        return "Tali grup seviyesi hatalı"
    if alt and int(alt.seviye) != 3:
        return "Alt grup seviyesi hatalı"
    if tali and ana and tali.parent_id != ana.id:
        return "Tali grup seçili ana gruba bağlı değil"
    if alt and tali and alt.parent_id != tali.id:
        return "Alt grup seçili tali gruba bağlı değil"
    return None


def _eski_yol(session, stok: StokKarti) -> str:
    ana = session.get(StokGrubu, stok.ana_grup_id) if stok.ana_grup_id else None
    tali = session.get(StokGrubu, stok.tali_grup_id) if stok.tali_grup_id else None
    alt = session.get(StokGrubu, stok.alt_grup_id) if stok.alt_grup_id else None
    yol = StokGrupService.yol_metni(ana, tali, alt)
    if yol:
        return yol
    return (stok.rapor_grubu or "").strip()


def _grupsuz_mu(stok: StokKarti) -> bool:
    return not (stok.ana_grup_id or stok.tali_grup_id or stok.alt_grup_id)


class StokGrupTopluService:
    @staticmethod
    def aday_listele(
        *,
        arama: str = "",
        ad_kelimeleri: list[str] | None = None,
        ana_grup_id: int | None = None,
        tali_grup_id: int | None = None,
        alt_grup_id: int | None = None,
        marka: str = "",
        aktiflik: str = "aktif",
        stok_durumu: str = "tumu",
        grup_durumu: str = "tumu",  # tumu | gruplu | grupsuz
        limit: int = 100,
        offset: int = 0,
        id_listesi: list[int] | None = None,
    ) -> dict[str, Any]:
        yetki_zorunlu("stok_goruntuleme", "goruntuleme", "stok_grup_yonetme")
        limit = max(1, min(int(limit or 100), 500))
        offset = max(0, int(offset or 0))

        with get_session() as session:
            miktar_sub = (
                select(
                    StokLotu.stok_id.label("stok_id"),
                    func.coalesce(func.sum(StokLotu.kalan_miktar), 0).label("miktar"),
                )
                .group_by(StokLotu.stok_id)
                .subquery()
            )
            q = (
                select(StokKarti, func.coalesce(miktar_sub.c.miktar, 0).label("miktar"))
                .outerjoin(miktar_sub, miktar_sub.c.stok_id == StokKarti.id)
                .where(or_(StokKarti.is_deleted.is_(False), StokKarti.is_deleted.is_(None)))
                .options(selectinload(StokKarti.barkodlar))
            )
            if id_listesi is not None:
                if not id_listesi:
                    return {"satirlar": [], "toplam": 0, "gosterilen": 0}
                q = q.where(StokKarti.id.in_([int(i) for i in id_listesi]))

            aktiflik = (aktiflik or "aktif").lower()
            if aktiflik == "aktif":
                q = q.where(StokKarti.aktif.is_(True))
            elif aktiflik == "pasif":
                q = q.where(StokKarti.aktif.is_(False))

            if alt_grup_id:
                q = q.where(StokKarti.alt_grup_id == int(alt_grup_id))
            elif tali_grup_id:
                q = q.where(StokKarti.tali_grup_id == int(tali_grup_id))
            elif ana_grup_id:
                q = q.where(StokKarti.ana_grup_id == int(ana_grup_id))

            gd = (grup_durumu or "tumu").lower()
            if gd == "grupsuz":
                q = q.where(
                    StokKarti.ana_grup_id.is_(None),
                    StokKarti.tali_grup_id.is_(None),
                    StokKarti.alt_grup_id.is_(None),
                )
            elif gd == "gruplu":
                q = q.where(
                    or_(
                        StokKarti.ana_grup_id.is_not(None),
                        StokKarti.tali_grup_id.is_not(None),
                        StokKarti.alt_grup_id.is_not(None),
                    )
                )

            marka_n = (marka or "").strip()
            if marka_n:
                q = q.where(StokKarti.marka.ilike(f"%{marka_n}%"))

            hizli = (arama or "").strip()
            if hizli:
                ifade = f"%{hizli}%"
                barkod_alt = select(StokBarkod.stok_id).where(StokBarkod.barkod.ilike(ifade))
                q = q.where(
                    or_(
                        StokKarti.stok_kodu.ilike(ifade),
                        StokKarti.barkod.ilike(ifade),
                        StokKarti.stok_adi.ilike(ifade),
                        StokKarti.id.in_(barkod_alt),
                    )
                )

            kelimeler = [k.strip() for k in (ad_kelimeleri or []) if (k or "").strip()]
            if kelimeler:
                # OR: herhangi bir kelime ada uysun (sıra şart değil)
                kosullar = [StokKarti.stok_adi.ilike(f"%{k}%") for k in kelimeler]
                q = q.where(or_(*kosullar))

            sd = (stok_durumu or "tumu").lower()
            if sd == "var":
                q = q.where(func.coalesce(miktar_sub.c.miktar, 0) > 0)
            elif sd == "sifir":
                q = q.where(func.coalesce(miktar_sub.c.miktar, 0) == 0)
            elif sd == "eksi":
                q = q.where(func.coalesce(miktar_sub.c.miktar, 0) < 0)

            q = q.order_by(StokKarti.stok_adi)
            # Toplam için count
            count_q = select(func.count()).select_from(q.order_by(None).subquery())
            toplam = int(session.scalar(count_q) or 0)
            rows = list(session.execute(q.offset(offset).limit(limit)).all())

            # Grup ad cache
            grup_ids = set()
            for stok, _m in rows:
                for gid in (stok.ana_grup_id, stok.tali_grup_id, stok.alt_grup_id):
                    if gid:
                        grup_ids.add(int(gid))
            grup_map = {}
            if grup_ids:
                for g in session.scalars(select(StokGrubu).where(StokGrubu.id.in_(grup_ids))).all():
                    grup_map[g.id] = g

            satirlar = []
            for stok, miktar in rows:
                ana = grup_map.get(stok.ana_grup_id)
                tali = grup_map.get(stok.tali_grup_id)
                alt = grup_map.get(stok.alt_grup_id)
                barkod = stok.barkod or ""
                if not barkod and stok.barkodlar:
                    barkod = stok.barkodlar[0].barkod or ""
                bozuk = _hiyerarsi_bozuk(session, stok)
                satirlar.append(
                    {
                        "id": int(stok.id),
                        "stok_kodu": stok.stok_kodu or "",
                        "stok_adi": stok.stok_adi or "",
                        "barkod": barkod,
                        "birim": stok.birim or "",
                        "miktar": f"{Decimal(str(miktar or 0)):f}".rstrip("0").rstrip(".") or "0",
                        "ana_grup": (ana.ad if ana else "") or "",
                        "tali_grup": (tali.ad if tali else "") or "",
                        "alt_grup": (alt.ad if alt else "") or "",
                        "yol": StokGrupService.yol_metni(ana, tali, alt)
                        or (stok.rapor_grubu or ""),
                        "aktif": bool(stok.aktif),
                        "grupsuz": _grupsuz_mu(stok),
                        "uyari": bozuk or ("Pasif" if not stok.aktif else ""),
                        "ana_grup_id": stok.ana_grup_id,
                        "tali_grup_id": stok.tali_grup_id,
                        "alt_grup_id": stok.alt_grup_id,
                    }
                )
            return {"satirlar": satirlar, "toplam": toplam, "gosterilen": len(satirlar)}

    @staticmethod
    def filtre_tum_idler(**filtre_kwargs) -> list[int]:
        """Tüm filtre sonucunun id listesi (sayfalama olmadan, güvenli üst sınır)."""
        yetki_zorunlu("stok_goruntuleme", "goruntuleme", "stok_grup_yonetme")
        # Büyük seçimler için partiler halinde
        idler: list[int] = []
        offset = 0
        batch = 500
        while True:
            sonuc = StokGrupTopluService.aday_listele(
                **{**filtre_kwargs, "limit": batch, "offset": offset}
            )
            batch_ids = [s["id"] for s in sonuc["satirlar"]]
            if not batch_ids:
                break
            idler.extend(batch_ids)
            offset += batch
            if offset >= int(sonuc["toplam"] or 0) or len(idler) >= 20000:
                break
        return idler

    @staticmethod
    def onizle(
        stok_idler: list[int],
        *,
        ana_id: int | None,
        tali_id: int | None,
        alt_id: int | None,
        politika: str = POLITIKA_SADECE_GRUPSUZ,
    ) -> dict[str, Any]:
        yetki_zorunlu("stok_goruntuleme", "goruntuleme", "stok_grup_yonetme")
        if not stok_idler:
            raise ValueError("Ön izleme için en az bir stok seçin.")
        politika = (politika or POLITIKA_SADECE_GRUPSUZ).strip()
        if politika not in (
            POLITIKA_SADECE_GRUPSUZ,
            POLITIKA_DEGISTIR,
            POLITIKA_EKSIK_TAMAMLA,
        ):
            raise ValueError("Geçersiz işlem politikası.")

        # Hedef doğrulama (pasif hedef engeli)
        dog = StokGrupService.hiyerarsi_dogrula(ana_id, tali_id, alt_id)
        if not dog.get("ana_grup_id") and not dog.get("tali_grup_id") and not dog.get("alt_grup_id"):
            raise ValueError("Hedef grup seçilmedi.")
        if dog.get("pasif_uyari"):
            raise ValueError(
                "Hedef grup pasif: " + ", ".join(dog["pasif_uyari"]) + ". Aktif grup seçin."
            )
        hedef_yol = (dog.get("rapor_grubu") or "").replace(" / ", " → ")
        degistirme_yetkisi = yetki_var(
            "stok_duzenleme", "stok_grup_yonetme", "stok_grup_toplu_degistir"
        )

        with get_session() as session:
            stoklar = list(
                session.scalars(
                    select(StokKarti).where(
                        StokKarti.id.in_([int(i) for i in stok_idler]),
                        or_(StokKarti.is_deleted.is_(False), StokKarti.is_deleted.is_(None)),
                    )
                ).all()
            )
            by_id = {s.id: s for s in stoklar}
            satirlar = []
            ozet = {
                "secilen": 0,
                "guncellenecek": 0,
                "degismeyecek": 0,
                "atlanacak": 0,
                "hatali": 0,
                "yetki_yok": 0,
            }
            for sid in stok_idler:
                stok = by_id.get(int(sid))
                ozet["secilen"] += 1
                if stok is None:
                    satirlar.append(
                        {
                            "stok_id": int(sid),
                            "stok_kodu": "?",
                            "stok_adi": "(bulunamadı)",
                            "eski_yol": "",
                            "yeni_yol": hedef_yol,
                            "durum": DURUM_HATALI,
                            "aciklama": "Stok bulunamadı",
                        }
                    )
                    ozet["hatali"] += 1
                    continue
                eski_yol = _eski_yol(session, stok)
                bozuk = _hiyerarsi_bozuk(session, stok)
                if bozuk:
                    satirlar.append(
                        {
                            "stok_id": stok.id,
                            "stok_kodu": stok.stok_kodu,
                            "stok_adi": stok.stok_adi,
                            "eski_yol": eski_yol,
                            "yeni_yol": hedef_yol,
                            "durum": DURUM_HATALI,
                            "aciklama": bozuk,
                            "eski_ana_id": stok.ana_grup_id,
                            "eski_tali_id": stok.tali_grup_id,
                            "eski_alt_id": stok.alt_grup_id,
                        }
                    )
                    ozet["hatali"] += 1
                    continue

                ayni = (
                    stok.ana_grup_id == dog["ana_grup_id"]
                    and stok.tali_grup_id == dog["tali_grup_id"]
                    and stok.alt_grup_id == dog["alt_grup_id"]
                )
                if ayni:
                    satirlar.append(
                        {
                            "stok_id": stok.id,
                            "stok_kodu": stok.stok_kodu,
                            "stok_adi": stok.stok_adi,
                            "eski_yol": eski_yol,
                            "yeni_yol": hedef_yol,
                            "durum": DURUM_DEGISIKLIK_YOK,
                            "aciklama": "Zaten hedef grupta",
                            "eski_ana_id": stok.ana_grup_id,
                            "eski_tali_id": stok.tali_grup_id,
                            "eski_alt_id": stok.alt_grup_id,
                        }
                    )
                    ozet["degismeyecek"] += 1
                    continue

                gruplu = not _grupsuz_mu(stok)
                if politika == POLITIKA_SADECE_GRUPSUZ and gruplu:
                    satirlar.append(
                        {
                            "stok_id": stok.id,
                            "stok_kodu": stok.stok_kodu,
                            "stok_adi": stok.stok_adi,
                            "eski_yol": eski_yol,
                            "yeni_yol": hedef_yol,
                            "durum": DURUM_ATLANACAK,
                            "aciklama": "Politika: yalnız grupsuz",
                            "eski_ana_id": stok.ana_grup_id,
                            "eski_tali_id": stok.tali_grup_id,
                            "eski_alt_id": stok.alt_grup_id,
                        }
                    )
                    ozet["atlanacak"] += 1
                    continue

                if politika == POLITIKA_DEGISTIR and gruplu and not degistirme_yetkisi:
                    satirlar.append(
                        {
                            "stok_id": stok.id,
                            "stok_kodu": stok.stok_kodu,
                            "stok_adi": stok.stok_adi,
                            "eski_yol": eski_yol,
                            "yeni_yol": hedef_yol,
                            "durum": DURUM_YETKI_YOK,
                            "aciklama": "Mevcut grubu değiştirme yetkisi yok",
                            "eski_ana_id": stok.ana_grup_id,
                            "eski_tali_id": stok.tali_grup_id,
                            "eski_alt_id": stok.alt_grup_id,
                        }
                    )
                    ozet["yetki_yok"] += 1
                    continue

                yeni_ana = dog["ana_grup_id"]
                yeni_tali = dog["tali_grup_id"]
                yeni_alt = dog["alt_grup_id"]
                durum = DURUM_ESLESTIRILECEK if not gruplu else DURUM_DEGISTIRILECEK
                aciklama = ""

                if politika == POLITIKA_EKSIK_TAMAMLA:
                    # Mevcut doğru üstleri koru; boş seviyeyi doldur
                    if stok.ana_grup_id and stok.ana_grup_id != dog["ana_grup_id"]:
                        satirlar.append(
                            {
                                "stok_id": stok.id,
                                "stok_kodu": stok.stok_kodu,
                                "stok_adi": stok.stok_adi,
                                "eski_yol": eski_yol,
                                "yeni_yol": hedef_yol,
                                "durum": DURUM_HATALI,
                                "aciklama": "Eksik tamamlama: ana grup hedefle uyumsuz",
                                "eski_ana_id": stok.ana_grup_id,
                                "eski_tali_id": stok.tali_grup_id,
                                "eski_alt_id": stok.alt_grup_id,
                            }
                        )
                        ozet["hatali"] += 1
                        continue
                    if stok.tali_grup_id and dog["tali_grup_id"] and stok.tali_grup_id != dog["tali_grup_id"]:
                        satirlar.append(
                            {
                                "stok_id": stok.id,
                                "stok_kodu": stok.stok_kodu,
                                "stok_adi": stok.stok_adi,
                                "eski_yol": eski_yol,
                                "yeni_yol": hedef_yol,
                                "durum": DURUM_HATALI,
                                "aciklama": "Eksik tamamlama: tali grup hedefle uyumsuz",
                                "eski_ana_id": stok.ana_grup_id,
                                "eski_tali_id": stok.tali_grup_id,
                                "eski_alt_id": stok.alt_grup_id,
                            }
                        )
                        ozet["hatali"] += 1
                        continue
                    yeni_ana = stok.ana_grup_id or dog["ana_grup_id"]
                    yeni_tali = stok.tali_grup_id or dog["tali_grup_id"]
                    yeni_alt = stok.alt_grup_id or dog["alt_grup_id"]
                    if (
                        yeni_ana == stok.ana_grup_id
                        and yeni_tali == stok.tali_grup_id
                        and yeni_alt == stok.alt_grup_id
                    ):
                        satirlar.append(
                            {
                                "stok_id": stok.id,
                                "stok_kodu": stok.stok_kodu,
                                "stok_adi": stok.stok_adi,
                                "eski_yol": eski_yol,
                                "yeni_yol": hedef_yol,
                                "durum": DURUM_DEGISIKLIK_YOK,
                                "aciklama": "Eksik seviye yok",
                                "eski_ana_id": stok.ana_grup_id,
                                "eski_tali_id": stok.tali_grup_id,
                                "eski_alt_id": stok.alt_grup_id,
                            }
                        )
                        ozet["degismeyecek"] += 1
                        continue
                    durum = DURUM_ESLESTIRILECEK
                    aciklama = "Eksik seviye tamamlanacak"
                    # Yeni yol yeniden hesapla
                    ana = session.get(StokGrubu, yeni_ana) if yeni_ana else None
                    tali = session.get(StokGrubu, yeni_tali) if yeni_tali else None
                    alt = session.get(StokGrubu, yeni_alt) if yeni_alt else None
                    yeni_yol_goster = StokGrupService.yol_metni(ana, tali, alt).replace(" / ", " → ")
                else:
                    yeni_yol_goster = hedef_yol

                satirlar.append(
                    {
                        "stok_id": stok.id,
                        "stok_kodu": stok.stok_kodu,
                        "stok_adi": stok.stok_adi,
                        "eski_yol": eski_yol,
                        "yeni_yol": yeni_yol_goster,
                        "durum": durum,
                        "aciklama": aciklama or ("Pasif stok" if not stok.aktif else ""),
                        "eski_ana_id": stok.ana_grup_id,
                        "eski_tali_id": stok.tali_grup_id,
                        "eski_alt_id": stok.alt_grup_id,
                        "yeni_ana_id": yeni_ana,
                        "yeni_tali_id": yeni_tali,
                        "yeni_alt_id": yeni_alt,
                        "pasif": not stok.aktif,
                    }
                )
                ozet["guncellenecek"] += 1

            return {
                "hedef_yol": hedef_yol,
                "hedef": dog,
                "politika": politika,
                "satirlar": satirlar,
                "ozet": ozet,
            }

    @staticmethod
    def uygula(
        stok_idler: list[int],
        *,
        ana_id: int | None,
        tali_id: int | None,
        alt_id: int | None,
        politika: str = POLITIKA_SADECE_GRUPSUZ,
        onizleme_ozeti: dict | None = None,
    ) -> dict[str, Any]:
        yazma_zorunlu("stok_duzenleme", "stok_grup_yonetme", "stok_grup_toplu_eslestirme")
        onizleme = StokGrupTopluService.onizle(
            stok_idler,
            ana_id=ana_id,
            tali_id=tali_id,
            alt_id=alt_id,
            politika=politika,
        )
        # Önizleme ile UI özeti çakışmasın diye güncellenecekleri filtrele
        guncellenecek = [
            s
            for s in onizleme["satirlar"]
            if s["durum"] in (DURUM_ESLESTIRILECEK, DURUM_DEGISTIRILECEK)
        ]
        if onizleme_ozeti is not None:
            beklenen = int(onizleme_ozeti.get("guncellenecek") or 0)
            if beklenen != len(guncellenecek):
                raise ValueError(
                    "Ön izleme güncelliğini yitirdi. Lütfen Ön İzle'yi yeniden çalıştırın "
                    f"(beklenen {beklenen}, şimdi {len(guncellenecek)})."
                )
        if not guncellenecek:
            raise ValueError("Güncellenecek stok yok. Ön izleme özetine bakın.")

        islem_no = _islem_no()
        with get_session() as session:
            baslik = StokGrupTopluIslem(
                islem_no=islem_no,
                kullanici_id=oturum.user_id,
                kullanici_adi=oturum.kullanici_adi or oturum.ad_soyad,
                politika=politika,
                hedef_ana_id=onizleme["hedef"].get("ana_grup_id"),
                hedef_tali_id=onizleme["hedef"].get("tali_grup_id"),
                hedef_alt_id=onizleme["hedef"].get("alt_grup_id"),
                hedef_yol=onizleme["hedef_yol"],
                secilen_adet=onizleme["ozet"]["secilen"],
                guncellenen_adet=0,
                atlanan_adet=onizleme["ozet"]["atlanacak"] + onizleme["ozet"]["degismeyecek"],
                hatali_adet=onizleme["ozet"]["hatali"] + onizleme["ozet"]["yetki_yok"],
                durum="tamamlandi",
                olusturma_tarihi=datetime.now(),
            )
            session.add(baslik)
            session.flush()

            guncellenen = 0
            for satir in guncellenecek:
                stok = session.get(StokKarti, int(satir["stok_id"]))
                if stok is None:
                    raise ValueError(f"Stok kaydı kayboldu (id={satir['stok_id']}). İşlem geri alındı.")
                # Kayıt anında yeniden doğrula
                dog = StokGrupService.hiyerarsi_dogrula(
                    satir.get("yeni_ana_id"),
                    satir.get("yeni_tali_id"),
                    satir.get("yeni_alt_id"),
                )
                eski = {
                    "ana": stok.ana_grup_id,
                    "tali": stok.tali_grup_id,
                    "alt": stok.alt_grup_id,
                    "yol": _eski_yol(session, stok),
                }
                stok.ana_grup_id = dog["ana_grup_id"]
                stok.tali_grup_id = dog["tali_grup_id"]
                stok.alt_grup_id = dog["alt_grup_id"]
                stok.rapor_grubu = dog["rapor_grubu"]
                session.add(
                    StokGrupTopluIslemSatiri(
                        islem_id=baslik.id,
                        stok_id=stok.id,
                        stok_kodu=stok.stok_kodu,
                        eski_ana_id=eski["ana"],
                        eski_tali_id=eski["tali"],
                        eski_alt_id=eski["alt"],
                        eski_yol=eski["yol"],
                        yeni_ana_id=dog["ana_grup_id"],
                        yeni_tali_id=dog["tali_grup_id"],
                        yeni_alt_id=dog["alt_grup_id"],
                        yeni_yol=dog["rapor_grubu"],
                        durum="guncellendi",
                    )
                )
                guncellenen += 1
            baslik.guncellenen_adet = guncellenen
            session.flush()
            audit_document(
                "stok_grup_toplu_eslestir",
                modul="stok",
                kayit_id=islem_no,
                yeni={
                    "islem_no": islem_no,
                    "guncellenen": guncellenen,
                    "hedef_yol": onizleme["hedef_yol"],
                    "politika": politika,
                },
            )
            return {
                "islem_no": islem_no,
                "islem_id": int(baslik.id),
                "guncellenen": guncellenen,
                "ozet": onizleme["ozet"],
                "hedef_yol": onizleme["hedef_yol"],
            }

    @staticmethod
    def islem_gecmisi(limit: int = 30) -> list[dict]:
        yetki_zorunlu("stok_goruntuleme", "goruntuleme", "stok_grup_yonetme")
        with get_session() as session:
            kayitlar = list(
                session.scalars(
                    select(StokGrupTopluIslem)
                    .order_by(StokGrupTopluIslem.olusturma_tarihi.desc())
                    .limit(max(1, min(int(limit or 30), 100)))
                ).all()
            )
            return [
                {
                    "id": i.id,
                    "islem_no": i.islem_no,
                    "tarih": i.olusturma_tarihi.strftime("%d.%m.%Y %H:%M")
                    if i.olusturma_tarihi
                    else "",
                    "kullanici": i.kullanici_adi or "",
                    "hedef_yol": i.hedef_yol or "",
                    "politika": i.politika,
                    "secilen": i.secilen_adet,
                    "guncellenen": i.guncellenen_adet,
                    "durum": i.durum,
                    "geri_alinabilir": i.durum == "tamamlandi",
                }
                for i in kayitlar
            ]

    @staticmethod
    def geri_al(islem_id: int) -> dict[str, Any]:
        yazma_zorunlu("stok_duzenleme", "stok_grup_yonetme", "stok_grup_toplu_geri_al")
        with get_session() as session:
            islem = session.get(StokGrupTopluIslem, int(islem_id))
            if islem is None:
                raise ValueError("İşlem bulunamadı.")
            if islem.durum != "tamamlandi":
                raise ValueError(f"Bu işlem geri alınamaz (durum: {islem.durum}).")
            satirlar = list(
                session.scalars(
                    select(StokGrupTopluIslemSatiri).where(
                        StokGrupTopluIslemSatiri.islem_id == islem.id,
                        StokGrupTopluIslemSatiri.durum == "guncellendi",
                    )
                ).all()
            )
            cakisan = []
            geri = 0
            for sat in satirlar:
                stok = session.get(StokKarti, sat.stok_id)
                if stok is None:
                    cakisan.append(
                        {"stok_kodu": sat.stok_kodu, "neden": "Stok silinmiş/bulunamadı"}
                    )
                    continue
                # Çakışma: stok hâlâ bu işlemdeki yeni değerlere sahip mi?
                if (
                    stok.ana_grup_id != sat.yeni_ana_id
                    or stok.tali_grup_id != sat.yeni_tali_id
                    or stok.alt_grup_id != sat.yeni_alt_id
                ):
                    cakisan.append(
                        {
                            "stok_kodu": stok.stok_kodu,
                            "neden": "Stok sonradan başka grupla değiştirilmiş",
                            "mevcut_yol": _eski_yol(session, stok),
                        }
                    )
                    continue
                stok.ana_grup_id = sat.eski_ana_id
                stok.tali_grup_id = sat.eski_tali_id
                stok.alt_grup_id = sat.eski_alt_id
                stok.rapor_grubu = sat.eski_yol
                sat.durum = "geri_alindi"
                geri += 1
            if cakisan and geri == 0:
                raise ValueError(
                    "Hiçbir stok geri alınamadı; tümünde çakışma var.\n"
                    + "\n".join(f"- {c['stok_kodu']}: {c['neden']}" for c in cakisan[:10])
                )
            islem.durum = "geri_alindi" if not cakisan else "kismi_geri_alindi"
            islem.geri_alinma_tarihi = datetime.now()
            islem.geri_alan_kullanici = oturum.kullanici_adi or oturum.ad_soyad
            session.flush()
            audit_document(
                "stok_grup_toplu_geri_al",
                modul="stok",
                kayit_id=islem.islem_no,
                yeni={
                    "geri_alinan": geri,
                    "cakisan": len(cakisan),
                    "islem_no": islem.islem_no,
                },
            )
            return {
                "islem_no": islem.islem_no,
                "geri_alinan": geri,
                "cakisan": cakisan,
                "durum": islem.durum,
            }
