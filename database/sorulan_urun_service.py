"""Sorulan Ürünler servisi — aday birleştirme + talep (stok hareketi yok)."""

from __future__ import annotations

import re
import shutil
import unicodedata
import uuid
from datetime import date, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any

from sqlalchemy import inspect, select, text

from database.access import yazma_zorunlu
from database.database import Base, DB_DIR, engine, get_session
from database.models.sorulan_urun import (
    ARAMA_SONUCLARI,
    MUADIL_SECENEKLERI,
    NIYETLER,
    NIYET_ETIKET,
    TALEP_DURUM_ETIKET,
    TALEP_NEDENLERI,
    TALEP_NEDENI_ETIKET,
    TANIM_DURUM_ETIKET,
    SorulanUrunAday,
    SorulanUrunEk,
    SorulanUrunGorusme,
    SorulanUrunOlcu,
    SorulanUrunTalep,
    SorulanUrunTarihLog,
    SorulanUrunTekrar,
)
from database.session_manager import oturum


def _normalize_ad(ad: str) -> str:
    s = unicodedata.normalize("NFKC", (ad or "").strip())
    s = re.sub(r"\s+", " ", s)
    return s.casefold() or "__bos__"


def bugun_tr() -> date:
    """Türkiye günü (Europe/Istanbul)."""
    try:
        from zoneinfo import ZoneInfo

        return datetime.now(ZoneInfo("Europe/Istanbul")).date()
    except Exception:
        return date.today()


def tarih_goster(d: date | None) -> str:
    if d is None:
        return ""
    return d.strftime("%d.%m.%Y")


def tarih_coz(metin: str | None) -> date | None:
    m = (metin or "").strip()
    if not m:
        return None
    for fmt in ("%d.%m.%Y", "%Y-%m-%d", "%d/%m/%Y"):
        try:
            return datetime.strptime(m, fmt).date()
        except ValueError:
            continue
    raise ValueError(f"Geçersiz tarih: {metin}")


def etiket_neden(kod: str) -> str:
    return TALEP_NEDENI_ETIKET.get((kod or "").upper(), kod or "")


def etiket_niyet(kod: str) -> str:
    return NIYET_ETIKET.get((kod or "").upper(), kod or "")


def etiket_durum(kod: str) -> str:
    return TALEP_DURUM_ETIKET.get((kod or "").upper(), kod or "")


def etiket_tanim(kod: str) -> str:
    return TANIM_DURUM_ETIKET.get((kod or "").upper(), kod or "")


_ACIK_DURUMLAR = frozenset(
    {
        "ACIK",
        "BILGI_BEKLENIYOR",
        "ARASTIRILIYOR",
        "TEDARIKCI_BEKLENIYOR",
        "FIYAT_BEKLENIYOR",
        "MUSTERIYE_BILDIRILDI",
        "TAKIPTE",
        "SATINALMA_ARA",
        "SIPARIS_VERILDI",
        "URUN_GELDI",
        "ARAMA_BEKLIYOR",
    }
)


def _bekleme_gunu(talep: SorulanUrunTalep, *, bugun: date | None = None) -> int | None:
    """İlk sorulmadan bugüne (veya sonuç tarihine); bilinmeyen tarihte None."""
    if getattr(talep, "sorulma_tarihi_bilinmiyor", False):
        return None
    ilk = talep.talep_tarihi
    if ilk is None:
        return None
    bitis = talep.sonuc_tarihi if (talep.durum not in _ACIK_DURUMLAR and talep.sonuc_tarihi) else (bugun or bugun_tr())
    return max(0, (bitis - ilk).days)


class SorulanUrunService:
    _schema_hazir = False

    @classmethod
    def ensure_schema(cls, eng=None) -> None:
        bag = eng if eng is not None else engine
        if bag is None:
            return
        import database.models.sorulan_urun  # noqa: F401

        tablolar = [
            SorulanUrunAday.__table__,
            SorulanUrunTalep.__table__,
            SorulanUrunOlcu.__table__,
            SorulanUrunEk.__table__,
            SorulanUrunTekrar.__table__,
            SorulanUrunGorusme.__table__,
            SorulanUrunTarihLog.__table__,
        ]
        Base.metadata.create_all(bind=bag, tables=tablolar)
        cls._kolonlari_guncelle(bag)
        cls._schema_hazir = True

    @classmethod
    def _kolonlari_guncelle(cls, bag) -> None:
        """Mevcut tablolara eksik kolonları ekler (eski veriyi korur)."""
        insp = inspect(bag)
        aday_ek = {
            "ilk_tarif": "TEXT",
            "musteri_tarifi": "TEXT",
            "diger_adlar": "VARCHAR(400)",
            "urun_grubu": "VARCHAR(80)",
            "urun_grubu_aciklama": "VARCHAR(200)",
            "marka": "VARCHAR(100)",
            "model": "VARCHAR(100)",
            "uretici_kodu": "VARCHAR(100)",
            "barkod": "VARCHAR(80)",
            "urun_yazilari": "TEXT",
            "kullanim_amaci": "TEXT",
            "uyum_bilgisi": "TEXT",
            "malzeme": "VARCHAR(120)",
            "renk": "VARCHAR(80)",
            "kaplama": "VARCHAR(80)",
            "sekil": "VARCHAR(80)",
            "calisma_bicimi": "VARCHAR(120)",
            "numune_var": "BOOLEAN DEFAULT 0 NOT NULL",
            "numune_yer": "VARCHAR(200)",
            "internet_link": "VARCHAR(500)",
            "katalog_sayfa": "VARCHAR(200)",
            "tanim_durumu": "VARCHAR(30) DEFAULT 'TANIMLANAMADI' NOT NULL",
        }
        talep_ek = {
            "sorulma_saati": "VARCHAR(8)",
            "sorulma_tarihi_bilinmiyor": "BOOLEAN DEFAULT 0 NOT NULL",
            "talep_aciklama": "TEXT",
            "ihtiyac_tarihi": "DATE",
            "aciliyet": "VARCHAR(40)",
            "muadil": "VARCHAR(30) DEFAULT 'SORULMADI' NOT NULL",
            "hedef_fiyat": "NUMERIC(18, 4)",
            "sorumlu_personel": "VARCHAR(80)",
            "sonraki_takip": "DATE",
            "sonuc_tarihi": "DATE",
        }
        for tablo, ekler in (
            ("sorulan_urun_adaylari", aday_ek),
            ("sorulan_urun_talepleri", talep_ek),
        ):
            if not insp.has_table(tablo):
                continue
            mevcut = {c["name"] for c in insp.get_columns(tablo)}
            eksik = {a: t for a, t in ekler.items() if a not in mevcut}
            if not eksik:
                continue
            with bag.begin() as conn:
                for alan, tip in eksik.items():
                    conn.execute(text(f'ALTER TABLE "{tablo}" ADD COLUMN "{alan}" {tip}'))

    @staticmethod
    def _firma_id() -> int:
        fid = getattr(oturum, "company_id", None)
        if not fid:
            raise RuntimeError("Aktif firma yok.")
        return int(fid)

    @staticmethod
    def hizli_kaydet(veriler: dict[str, Any]) -> dict[str, Any]:
        """Hızlı kayıt: tarif/görsel yeterli; stok/cari zorunlu değil; hareket yok."""
        yazma_zorunlu()
        SorulanUrunService.ensure_schema()
        ad = " ".join(str(veriler.get("urun_adi") or "").split())
        tarif = (veriler.get("musteri_tarifi") or veriler.get("ilk_tarif") or "").strip()
        if not ad and not tarif and not veriler.get("fotograf_yollari"):
            raise ValueError(
                "Ürün adı/tarifi veya en az bir fotoğraf gerekli "
                "(adı bilinmeyen ürün tarif veya görselle kaydedilebilir)."
            )
        if not ad:
            ad = (tarif[:80] + "…") if len(tarif) > 80 else (tarif or "Adsız / tarifli ürün")
        neden = (veriler.get("talep_nedeni") or "CESITTE_YOK").strip().upper()
        # Türkçe etiket gelirse koda çevir
        for kod, et in TALEP_NEDENI_ETIKET.items():
            if neden == et.upper() or neden == et:
                neden = kod
                break
        if neden not in TALEP_NEDENLERI:
            neden = "CESITTE_YOK"
        niyet = (veriler.get("niyet") or "SADECE_SORDU").strip().upper()
        for kod, et in NIYET_ETIKET.items():
            if niyet == et.upper() or niyet == et:
                niyet = kod
                break
        if niyet not in NIYETLER:
            niyet = "SADECE_SORDU"
        norm = _normalize_ad(ad)
        firma = SorulanUrunService._firma_id()
        miktar = veriler.get("miktar")
        miktar_d = None
        if miktar is not None and str(miktar).strip() != "":
            miktar_d = Decimal(str(miktar))
            if miktar_d <= 0:
                raise ValueError("Miktar pozitif olmalı veya boş bırakılmalı.")

        # Sorulduğu tarih — gelecek yasak; bilinmiyor bayrağı
        bilinmiyor = bool(veriler.get("sorulma_tarihi_bilinmiyor"))
        if bilinmiyor:
            sorulma = veriler.get("talep_tarihi")  # None kalabilir
            if sorulma is None:
                sorulma = bugun_tr()  # DB NOT NULL — bayrakla raporlarda ayrılır
        else:
            raw = veriler.get("talep_tarihi") or veriler.get("sorulma_tarihi")
            if isinstance(raw, date):
                sorulma = raw
            elif raw:
                sorulma = tarih_coz(str(raw))
            else:
                sorulma = bugun_tr()
            if sorulma > bugun_tr():
                raise ValueError("Sorulduğu tarih gelecek olamaz.")
        saat = (veriler.get("sorulma_saati") or "").strip() or None
        if saat:
            try:
                datetime.strptime(saat, "%H:%M")
            except ValueError as exc:
                raise ValueError("Saat SS:DD formatında olmalı.") from exc

        with get_session() as session:
            aday = session.scalar(
                select(SorulanUrunAday).where(
                    SorulanUrunAday.firma_id == firma,
                    SorulanUrunAday.normalize_ad == norm,
                    SorulanUrunAday.arsiv.is_(False),
                )
            )
            if aday is None:
                aday = SorulanUrunAday(
                    firma_id=firma,
                    urun_adi=ad,
                    normalize_ad=norm,
                    ilk_tarif=tarif or ad,
                    musteri_tarifi=tarif or None,
                    ozellik=(veriler.get("ozellik") or None),
                    birim=(veriler.get("birim") or None),
                    marka=(veriler.get("marka") or None),
                    model=(veriler.get("model") or None),
                    urun_grubu=(veriler.get("urun_grubu") or None),
                    kullanim_amaci=(veriler.get("kullanim_amaci") or None),
                    stok_id=int(veriler["stok_id"]) if veriler.get("stok_id") else None,
                    talep_nedeni_ozet=neden,
                    tanim_durumu=(veriler.get("tanim_durumu") or "TANIMLANAMADI"),
                    olusturan=getattr(oturum, "kullanici_adi", None),
                )
                session.add(aday)
                session.flush()
            else:
                aday.guncelleme_tarihi = datetime.utcnow()
                if veriler.get("stok_id") and not aday.stok_id:
                    aday.stok_id = int(veriler["stok_id"])
                if tarif and not aday.ilk_tarif:
                    aday.ilk_tarif = tarif
                if tarif:
                    aday.musteri_tarifi = tarif

            cari_id = veriler.get("cari_id")
            musteri = (veriler.get("musteri_adi") or "").strip() or None
            telefon = (veriler.get("telefon") or "").strip() or None
            anonim = not cari_id and not musteri and not telefon
            muadil = (veriler.get("muadil") or "SORULMADI").strip().upper()
            if muadil not in MUADIL_SECENEKLERI:
                muadil = "SORULMADI"
            ihtiyac = veriler.get("ihtiyac_tarihi")
            if isinstance(ihtiyac, str):
                ihtiyac = tarih_coz(ihtiyac) if ihtiyac.strip() else None
            takip = veriler.get("sonraki_takip") or veriler.get("sonraki_arama")
            if isinstance(takip, str):
                takip = tarih_coz(takip) if takip.strip() else None
            hedef = veriler.get("hedef_fiyat")
            hedef_d = Decimal(str(hedef)) if hedef not in (None, "") else None

            talep = SorulanUrunTalep(
                firma_id=firma,
                aday_id=int(aday.id),
                talep_tarihi=sorulma,
                sorulma_saati=saat,
                sorulma_tarihi_bilinmiyor=bilinmiyor,
                cari_id=int(cari_id) if cari_id else None,
                musteri_adi=musteri,
                telefon=telefon,
                anonim=anonim,
                miktar=miktar_d,
                birim=(veriler.get("birim") or aday.birim),
                niyet=niyet,
                talep_nedeni=neden,
                talep_aciklama=(veriler.get("talep_aciklama") or None),
                ihtiyac_tarihi=ihtiyac,
                aciliyet=(veriler.get("aciliyet") or None),
                muadil=muadil,
                hedef_fiyat=hedef_d,
                sorumlu_personel=(veriler.get("sorumlu_personel") or None),
                sonraki_takip=takip,
                sonraki_arama=takip,
                kaynak=(veriler.get("kaynak") or "HIZLI"),
                notlar=(veriler.get("notlar") or None),
                olusturan=getattr(oturum, "kullanici_adi", None),
            )
            session.add(talep)
            session.flush()
            aday_id = int(aday.id)
            talep_id = int(talep.id)
            urun_adi = aday.urun_adi

        # Fotoğraflar (oturum dışında dosya kopyala)
        for yol in veriler.get("fotograf_yollari") or []:
            try:
                SorulanUrunService.ek_ekle(aday_id, yol, etiket="Diğer")
            except Exception:
                pass
        return {"aday_id": aday_id, "talep_id": talep_id, "urun_adi": urun_adi}

    @staticmethod
    def urun_ozet_listesi(
        *,
        arama: str | None = None,
        arsiv: bool = False,
        tarih_bas: date | None = None,
        tarih_bit: date | None = None,
        bilinmeyen_ayri: bool = True,
    ) -> list[dict[str, Any]]:
        """Üst liste. tarih_* sorulma tarihine uygulanır; bilinmeyenler ayrı işaretlenir."""
        SorulanUrunService.ensure_schema()
        firma = SorulanUrunService._firma_id()
        bugun = bugun_tr()
        with get_session() as session:
            q = select(SorulanUrunAday).where(
                SorulanUrunAday.firma_id == firma,
                SorulanUrunAday.arsiv.is_(bool(arsiv)),
            )
            if arama and arama.strip():
                like = f"%{arama.strip()}%"
                q = q.where(
                    SorulanUrunAday.urun_adi.ilike(like)
                    | SorulanUrunAday.musteri_tarifi.ilike(like)
                    | SorulanUrunAday.marka.ilike(like)
                    | SorulanUrunAday.model.ilike(like)
                    | SorulanUrunAday.diger_adlar.ilike(like)
                )
            adaylar = session.scalars(q.order_by(SorulanUrunAday.id.desc())).all()
            sonuc = []
            for a in adaylar:
                talepler = list(
                    session.scalars(
                        select(SorulanUrunTalep).where(
                            SorulanUrunTalep.aday_id == a.id,
                            SorulanUrunTalep.gecersiz.is_(False),
                        )
                    )
                )
                tekrarlar = {}
                for t in talepler:
                    tekrarlar[t.id] = list(
                        session.scalars(
                            select(SorulanUrunTekrar).where(SorulanUrunTekrar.talep_id == t.id)
                        )
                    )
                # Dönem filtresi — bilinmeyenler dönem toplamına dahil edilmez
                tarihli = [
                    t
                    for t in talepler
                    if not getattr(t, "sorulma_tarihi_bilinmiyor", False)
                ]
                bilinmeyen = [
                    t for t in talepler if getattr(t, "sorulma_tarihi_bilinmiyor", False)
                ]
                if tarih_bas or tarih_bit:
                    def _aralikta(t):
                        d = t.talep_tarihi
                        if tarih_bas and d < tarih_bas:
                            return False
                        if tarih_bit and d > tarih_bit:
                            return False
                        return True

                    donem_talepler = [t for t in tarihli if _aralikta(t)]
                    # Tekrar sorulmalar da dönem ölçütü olabilir
                    donem_tekrar = 0
                    for t in tarihli:
                        for tr in tekrarlar.get(t.id, []):
                            if tarih_bas and tr.tekrar_tarihi < tarih_bas:
                                continue
                            if tarih_bit and tr.tekrar_tarihi > tarih_bit:
                                continue
                            donem_tekrar += 1
                else:
                    donem_talepler = tarihli
                    donem_tekrar = sum(len(v) for v in tekrarlar.values())

                musteriler = {
                    (t.cari_id or t.musteri_adi or t.telefon)
                    for t in talepler
                    if not t.anonim and (t.cari_id or t.musteri_adi or t.telefon)
                }
                anonim_n = sum(1 for t in talepler if t.anonim)
                ilk_tarihler = [t.talep_tarihi for t in tarihli]
                son_tarihler = list(ilk_tarihler)
                for trs in tekrarlar.values():
                    son_tarihler.extend(tr.tekrar_tarihi for tr in trs)
                ilk = min(ilk_tarihler) if ilk_tarihler else None
                son = max(son_tarihler) if son_tarihler else None
                bagimsiz = len(talepler)  # her talep kaydı bağımsız
                toplam_sorulma = bagimsiz + sum(len(v) for v in tekrarlar.values())
                acik = [t for t in talepler if t.durum in _ACIK_DURUMLAR]
                beklemeler = [_bekleme_gunu(t, bugun=bugun) for t in acik]
                beklemeler = [b for b in beklemeler if b is not None]
                sonuc.append(
                    {
                        "id": int(a.id),
                        "urun_adi": a.urun_adi,
                        "tarif": (a.musteri_tarifi or a.ilk_tarif or "")[:80],
                        "ozellik": a.ozellik or "",
                        "talep_nedeni": etiket_neden(a.talep_nedeni_ozet or ""),
                        "talep_nedeni_kod": a.talep_nedeni_ozet or "",
                        "ilk_sorulma": tarih_goster(ilk),
                        "ilk_sorulma_iso": ilk.isoformat() if ilk else "",
                        "son_sorulma": tarih_goster(son),
                        "son_sorulma_iso": son.isoformat() if son else "",
                        "bagimsiz_talep": bagimsiz,
                        "toplam_sorulma": toplam_sorulma,
                        "sorulma_sayisi": toplam_sorulma,  # geriye uyum
                        "farkli_musteri": len(musteriler),
                        "anonim": anonim_n,
                        "acik_talep": len(acik),
                        "max_bekleme": max(beklemeler) if beklemeler else None,
                        "bilinmeyen_tarih": len(bilinmeyen),
                        "donem_talep": len(donem_talepler),
                        "donem_tekrar": donem_tekrar if (tarih_bas or tarih_bit) else None,
                        "tanim_durumu": etiket_tanim(getattr(a, "tanim_durumu", None) or "TANIMLANAMADI"),
                        "tedarik_durumu": a.tedarik_durumu,
                        "stok_id": a.stok_id,
                        "sorumlu": a.sorumlu_personel or "",
                        "marka": a.marka or "",
                        "model": a.model or "",
                    }
                )
            return sonuc

    @staticmethod
    def talepler(aday_id: int) -> list[dict[str, Any]]:
        SorulanUrunService.ensure_schema()
        firma = SorulanUrunService._firma_id()
        bugun = bugun_tr()
        with get_session() as session:
            rows = session.scalars(
                select(SorulanUrunTalep)
                .where(
                    SorulanUrunTalep.firma_id == firma,
                    SorulanUrunTalep.aday_id == int(aday_id),
                )
                .order_by(SorulanUrunTalep.talep_tarihi.desc(), SorulanUrunTalep.id.desc())
            ).all()
            out = []
            for t in rows:
                istenen = t.miktar
                kalan = None
                if istenen is not None:
                    kalan = max(
                        Decimal("0"),
                        Decimal(str(istenen))
                        - Decimal(str(t.karsilanan_miktar or 0))
                        - Decimal(str(t.iptal_miktar or 0)),
                    )
                tekrarlar = list(
                    session.scalars(
                        select(SorulanUrunTekrar)
                        .where(SorulanUrunTekrar.talep_id == t.id)
                        .order_by(SorulanUrunTekrar.tekrar_tarihi.desc())
                    )
                )
                son_tekrar = tekrarlar[0].tekrar_tarihi if tekrarlar else None
                bilinmiyor = bool(getattr(t, "sorulma_tarihi_bilinmiyor", False))
                out.append(
                    {
                        "id": int(t.id),
                        "tarih": (
                            "Bilinmiyor"
                            if bilinmiyor
                            else tarih_goster(t.talep_tarihi)
                        ),
                        "tarih_iso": "" if bilinmiyor else t.talep_tarihi.isoformat(),
                        "sorulma_saati": getattr(t, "sorulma_saati", None) or "",
                        "bilinmiyor": bilinmiyor,
                        "musteri": t.musteri_adi or ("Anonim" if t.anonim else ""),
                        "telefon": t.telefon or "",
                        "miktar": str(t.miktar) if t.miktar is not None else "",
                        "kalan": str(kalan) if kalan is not None else "",
                        "niyet": t.niyet,
                        "niyet_etiket": etiket_niyet(t.niyet),
                        "durum": t.durum,
                        "durum_etiket": etiket_durum(t.durum),
                        "neden": t.talep_nedeni,
                        "neden_etiket": etiket_neden(t.talep_nedeni),
                        "ihtiyac_tarihi": tarih_goster(getattr(t, "ihtiyac_tarihi", None)),
                        "son_tekrar": tarih_goster(son_tekrar),
                        "tekrar_sayisi": len(tekrarlar),
                        "bekleme_gun": _bekleme_gunu(t, bugun=bugun),
                        "sorumlu": getattr(t, "sorumlu_personel", None) or "",
                        "gecersiz": bool(t.gecersiz),
                        "anonim": bool(t.anonim),
                    }
                )
            # Gerçek tarih sırası (metin değil)
            out.sort(
                key=lambda r: (r["bilinmiyor"], r["tarih_iso"] or "", r["id"]),
                reverse=True,
            )
            return out

    @staticmethod
    def aday_getir(aday_id: int) -> dict[str, Any] | None:
        SorulanUrunService.ensure_schema()
        firma = SorulanUrunService._firma_id()
        with get_session() as session:
            a = session.get(SorulanUrunAday, int(aday_id))
            if a is None or int(a.firma_id) != firma:
                return None
            return {
                "id": int(a.id),
                "urun_adi": a.urun_adi,
                "birim": a.birim or "Adet",
                "stok_id": a.stok_id,
                "tedarik_durumu": a.tedarik_durumu,
                "ozellik": a.ozellik or "",
            }

    @staticmethod
    def satin_alma_taslagina_aktar(
        aday_idler: list[int],
        *,
        miktarlar: dict[int, Any] | None = None,
    ) -> dict[str, Any]:
        """Seçilen adayları mevcut satınalma talebi taslağına aktarır (otomatik onay yok).

        Miktar kullanıcıdan gelmeli; toplam müşteri talebi otomatik alım miktarı sayılmaz.
        Aynı aday için önceki SA bağlantısı notlarda varsa uyarı döner (ikinci aktarım için
        miktar açık verilmelidir).
        """
        yazma_zorunlu()
        from datetime import date as _date

        from database.satin_alma_talep_service import SatinAlmaTalepService

        if not aday_idler:
            raise ValueError("Aktarılacak ürün seçin.")
        miktarlar = miktarlar or {}
        satirlar: list[dict[str, Any]] = []
        baglantilar: list[dict[str, Any]] = []
        for aid in aday_idler:
            aday = SorulanUrunService.aday_getir(int(aid))
            if aday is None:
                raise ValueError(f"Aday bulunamadı: {aid}")
            mik = miktarlar.get(int(aid))
            if mik is None or str(mik).strip() == "":
                # Bilinen kalan miktar yoksa kullanıcı 1 girmek zorunda kalmasın — boş yasak
                raise ValueError(
                    f"«{aday['urun_adi']}» için satın alınacak miktarı açıkça girin "
                    "(müşteri talebi toplamı otomatik alınmaz)."
                )
            miktar_d = Decimal(str(mik))
            if miktar_d <= 0:
                raise ValueError(f"«{aday['urun_adi']}» miktarı pozitif olmalı.")
            satirlar.append(
                {
                    "urun_adi": aday["urun_adi"],
                    "urun_kodu": "",
                    "birim": aday.get("birim") or "Adet",
                    "miktar": miktar_d,
                    "manuel": True,
                    "stok_id": aday.get("stok_id"),
                    "aciklama": f"Sorulan ürün aday #{aday['id']}",
                }
            )
            baglantilar.append({"aday_id": aday["id"], "miktar": str(miktar_d)})

        talep_id = SatinAlmaTalepService.kaydet(
            {
                "talep_tarihi": _date.today(),
                "aciklama": "Sorulan Ürünler aktarımı — otomatik sipariş gönderilmedi.",
            },
            satirlar,
        )
        # Bağlantı: aday tedarik durumunu güncelle + not
        firma = SorulanUrunService._firma_id()
        with get_session() as session:
            for b in baglantilar:
                a = session.get(SorulanUrunAday, int(b["aday_id"]))
                if a is None or int(a.firma_id) != firma:
                    continue
                if a.tedarik_durumu in ("BEKLEMEDE", "ARAŞTIRILIYOR"):
                    a.tedarik_durumu = "ARAŞTIRILIYOR"
                a.guncelleme_tarihi = datetime.utcnow()
                # Takip notu olarak talep satırına değil aday özellik alanına kısa iz
                iz = f"SA_TALEP={talep_id};mik={b['miktar']}"
                eski = (a.ozellik or "").strip()
                if f"SA_TALEP={talep_id}" not in eski:
                    a.ozellik = f"{eski} | {iz}".strip(" |") if eski else iz
            session.flush()
        return {"talep_id": int(talep_id), "satir_sayisi": len(satirlar), "baglantilar": baglantilar}

    @staticmethod
    def oncelik_raporu(*, gun: int = 30, min_musteri: int = 3) -> list[dict[str, Any]]:
        """Son N günde bilinen farklı müşteri eşiğini aşan ürünler (anonim sayılmaz)."""
        from datetime import timedelta

        SorulanUrunService.ensure_schema()
        firma = SorulanUrunService._firma_id()
        bas = date.today() - timedelta(days=max(1, int(gun)))
        with get_session() as session:
            adaylar = session.scalars(
                select(SorulanUrunAday).where(
                    SorulanUrunAday.firma_id == firma,
                    SorulanUrunAday.arsiv.is_(False),
                )
            ).all()
            sonuc = []
            for a in adaylar:
                talepler = session.scalars(
                    select(SorulanUrunTalep).where(
                        SorulanUrunTalep.aday_id == a.id,
                        SorulanUrunTalep.gecersiz.is_(False),
                        SorulanUrunTalep.talep_tarihi >= bas,
                    )
                ).all()
                musteriler = {
                    (t.cari_id or t.musteri_adi or t.telefon)
                    for t in talepler
                    if not t.anonim and (t.cari_id or t.musteri_adi or t.telefon)
                }
                if len(musteriler) < int(min_musteri):
                    continue
                sonuc.append(
                    {
                        "id": int(a.id),
                        "urun_adi": a.urun_adi,
                        "farkli_musteri": len(musteriler),
                        "sorulma": len(talepler),
                        "anonim": sum(1 for t in talepler if t.anonim),
                        "tedarik_durumu": a.tedarik_durumu,
                    }
                )
            sonuc.sort(key=lambda x: (-x["farkli_musteri"], -x["sorulma"]))
            return sonuc

    @staticmethod
    def donusum_raporu(*, gun: int | None = None) -> dict[str, Any]:
        """Geçerli taleplerde satışa dönüşüm (kısmi satış dahil).

        payda = geçerli (gecersiz değil) tüm talepler; pay = en az bir miktarı
        karşılanan (karsilanan_miktar > 0) talepler. Anonim ayrı sayılır.
        """
        SorulanUrunService.ensure_schema()
        firma = SorulanUrunService._firma_id()
        bas = None
        if gun is not None:
            from datetime import timedelta

            bas = date.today() - timedelta(days=max(1, int(gun)))
        with get_session() as session:
            q = select(SorulanUrunTalep).where(
                SorulanUrunTalep.firma_id == firma,
                SorulanUrunTalep.gecersiz.is_(False),
            )
            if bas is not None:
                q = q.where(SorulanUrunTalep.talep_tarihi >= bas)
            talepler = list(session.scalars(q))
            payda = len(talepler)
            pay = sum(
                1
                for t in talepler
                if (t.karsilanan_miktar or Decimal("0")) > 0
            )
            anonim = sum(1 for t in talepler if t.anonim)
            oran = (Decimal(pay) / Decimal(payda) * 100).quantize(Decimal("0.01")) if payda else None
            return {
                "pay": pay,
                "payda": payda,
                "oran_yuzde": oran,
                "anonim": anonim,
                "bilinen": payda - anonim,
                "kismi_dahil": True,
                "etiket": (
                    f"{pay} / {payda} = %{oran}" if payda and oran is not None else "—"
                ),
            }

    @staticmethod
    def arama_sonucu_kaydet(
        talep_id: int,
        *,
        sonuc_kod: str,
        sonraki_arama: date | None = None,
        notlar: str | None = None,
        aktivite_tamamla: bool = True,
    ) -> dict[str, Any]:
        """Personel görüşme sonucunu kaydeder. Otomatik SMS/WhatsApp yok.

        «Müşteriye bildirildi» yalnızca bu kayıtla doğar; görev tamamlamak satış değildir.
        """
        yazma_zorunlu()
        SorulanUrunService.ensure_schema()
        kod = (sonuc_kod or "").strip().upper()
        if kod not in ARAMA_SONUCLARI:
            raise ValueError(
                "Geçersiz arama sonucu. "
                + ", ".join(ARAMA_SONUCLARI)
            )
        firma = SorulanUrunService._firma_id()
        with get_session() as session:
            t = session.get(SorulanUrunTalep, int(talep_id))
            if t is None or int(t.firma_id) != firma or t.gecersiz:
                raise ValueError("Talep bulunamadı.")
            onceki = (t.notlar or "").rstrip()
            satir = f"Arama sonucu: {kod}"
            if sonraki_arama:
                satir += f"; sonraki={sonraki_arama.isoformat()}"
            if notlar:
                satir += f"; {notlar.strip()}"
            t.notlar = f"{onceki}\n{satir}".strip() if onceki else satir
            t.sonraki_arama = sonraki_arama
            t.guncelleme_tarihi = datetime.utcnow()
            # Durum eşlemesi — satış tek başına doğmaz
            if kod == "SIPARISE_DONUSTU":
                t.durum = "SATISA_DONUSTU"
            elif kod == "VAZGECTI":
                t.durum = "IPTAL"
            elif kod in ("ULASILDI", "FIYAT_BEKLIYOR", "DAHA_SONRA_ARA", "ULASILAMADI"):
                t.durum = "TAKIPTE"
            session.flush()
            tid = int(t.id)
            aday_id = int(t.aday_id)

        if aktivite_tamamla and kod in ("ULASILDI", "VAZGECTI", "SIPARISE_DONUSTU"):
            try:
                from database.aktivite_service import AktiviteService

                mevcut = AktiviteService.kaynak_ile_bul(
                    kaynak_belge_tur="SORULAN_TALEP",
                    kaynak_belge_id=tid,
                    tur_kod="MUSTERI_ARAMASI",
                )
                if mevcut and mevcut["durum"] not in ("TAMAMLANDI", "IPTAL"):
                    AktiviteService.tamamla(int(mevcut["id"]), sonuc_kod=kod)
            except Exception:
                pass
        elif aktivite_tamamla and kod == "DAHA_SONRA_ARA" and sonraki_arama:
            try:
                from database.aktivite_service import AktiviteService

                mevcut = AktiviteService.kaynak_ile_bul(
                    kaynak_belge_tur="SORULAN_TALEP",
                    kaynak_belge_id=tid,
                    tur_kod="MUSTERI_ARAMASI",
                )
                if mevcut and mevcut["durum"] not in ("TAMAMLANDI", "IPTAL"):
                    AktiviteService.ertele(
                        int(mevcut["id"]),
                        yeni_tarih=sonraki_arama,
                        gerekce=f"Arama sonucu: {kod}",
                    )
            except Exception:
                pass

        talepler = SorulanUrunService.talepler(aday_id)
        durum = next((x["durum"] for x in talepler if x["id"] == tid), None)
        return {
            "talep_id": tid,
            "aday_id": aday_id,
            "sonuc": kod,
            "durum": durum,
        }

    # --- Stok geldiğinde müşteri arama görevi (Aktivite) ---

    _ACIK_TALEP_DURUMLARI = frozenset(
        {
            "ACIK",
            "TAKIPTE",
            "SATINALMA_ARA",
            "SIPARIS_VERILDI",
            "URUN_GELDI",
            "ARAMA_BEKLIYOR",
        }
    )

    @staticmethod
    def kullanilabilir_stok(stok_id: int) -> Decimal:
        """Lot kalan toplamı; stok tablosu yoksa 0 (görev üretmez, engellemez)."""
        from sqlalchemy import func

        try:
            from database.models.stok import StokLotu
        except Exception:
            return Decimal("0")
        with get_session() as session:
            deger = session.scalar(
                select(func.coalesce(func.sum(StokLotu.kalan_miktar), 0)).where(
                    StokLotu.stok_id == int(stok_id)
                )
            )
            return Decimal(str(deger or 0))

    @staticmethod
    def stok_bagla(aday_id: int, stok_id: int, *, degerlendir: bool = True) -> dict[str, Any]:
        """Adaya stok kartı bağlar; isteğe bağlı stok değerlendirmesi başlatır."""
        yazma_zorunlu()
        SorulanUrunService.ensure_schema()
        firma = SorulanUrunService._firma_id()
        with get_session() as session:
            a = session.get(SorulanUrunAday, int(aday_id))
            if a is None or int(a.firma_id) != firma:
                raise ValueError("Aday bulunamadı.")
            a.stok_id = int(stok_id)
            a.guncelleme_tarihi = datetime.utcnow()
            session.flush()
        if degerlendir:
            return SorulanUrunService.stok_geldiginde_degerlendir(stok_id=int(stok_id), aday_id=int(aday_id))
        return {"aday_id": int(aday_id), "stok_id": int(stok_id)}

    @staticmethod
    def stok_girisi_sonrasi_degerlendir(
        *,
        stok_id: int,
        olay_anahtar: str = "",
    ) -> dict[str, Any] | None:
        """Stok girişinden sonra çağrılır; hata stok kaydını bozmaz (dışarıda yakalanır)."""
        return SorulanUrunService.stok_geldiginde_degerlendir(
            stok_id=int(stok_id),
            olay_anahtar=olay_anahtar or f"STOK_GIRIS:{stok_id}",
        )

    @staticmethod
    def stok_geldiginde_degerlendir(
        *,
        stok_id: int | None = None,
        aday_id: int | None = None,
        olay_anahtar: str = "",
        mevcut_miktar: Decimal | None = None,
    ) -> dict[str, Any]:
        """Onaylı stok / manuel kontrol: açık talepler için MUSTERI_ARAMASI aktivitesi.

        - Anonim + telefonsuz talep görev üretmez.
        - Aynı talep için tekillik: SORULAN_TALEP + talep_id + MUSTERI_ARAMASI.
        - Stok sıfırsa yeni görev açılmaz; açık görev varsa 'stok yeniden kontrol' notu.
        - Satış/stok işlemini bekletmez; çağıran try/except kullanmalı.
        """
        from database.aktivite_service import AktiviteService

        SorulanUrunService.ensure_schema()
        AktiviteService.ensure_schema()
        firma = SorulanUrunService._firma_id()

        aday_ozet: list[dict[str, Any]] = []
        hedef_stok = int(stok_id) if stok_id else None
        with get_session() as session:
            aday_q = select(SorulanUrunAday).where(
                SorulanUrunAday.firma_id == firma,
                SorulanUrunAday.arsiv.is_(False),
            )
            if aday_id:
                aday_q = aday_q.where(SorulanUrunAday.id == int(aday_id))
            elif stok_id:
                aday_q = aday_q.where(SorulanUrunAday.stok_id == int(stok_id))
            else:
                raise ValueError("stok_id veya aday_id gerekli.")
            for a in session.scalars(aday_q).all():
                if hedef_stok is None and a.stok_id:
                    hedef_stok = int(a.stok_id)
                talepler = session.scalars(
                    select(SorulanUrunTalep).where(
                        SorulanUrunTalep.firma_id == firma,
                        SorulanUrunTalep.aday_id == int(a.id),
                        SorulanUrunTalep.gecersiz.is_(False),
                        SorulanUrunTalep.durum.in_(tuple(SorulanUrunService._ACIK_TALEP_DURUMLARI)),
                    )
                ).all()
                aday_ozet.append(
                    {
                        "id": int(a.id),
                        "urun_adi": a.urun_adi,
                        "talepler": [
                            {
                                "id": int(t.id),
                                "cari_id": t.cari_id,
                                "musteri_adi": t.musteri_adi,
                                "telefon": t.telefon,
                                "anonim": bool(t.anonim),
                                "miktar": t.miktar,
                                "durum": t.durum,
                            }
                            for t in talepler
                        ],
                    }
                )

        if not aday_ozet:
            return {
                "olusturulan": 0,
                "guncellenen": 0,
                "atlanan": 0,
                "neden": "bagli_aday_yok",
            }

        miktar = mevcut_miktar
        if miktar is None:
            miktar = (
                SorulanUrunService.kullanilabilir_stok(hedef_stok)
                if hedef_stok
                else Decimal("0")
            )

        olusturulan = 0
        guncellenen = 0
        atlanan = 0
        detay: list[dict[str, Any]] = []
        durum_guncelle: list[int] = []

        for aday in aday_ozet:
            for t in aday["talepler"]:
                tel = (t.get("telefon") or "").strip()
                if t.get("anonim") and not tel:
                    atlanan += 1
                    detay.append({"talep_id": t["id"], "sonuc": "anonim_iletisim_yok"})
                    continue
                if not tel and not t.get("cari_id") and not (t.get("musteri_adi") or "").strip():
                    atlanan += 1
                    detay.append({"talep_id": t["id"], "sonuc": "iletisim_yok"})
                    continue

                musteri = (t.get("musteri_adi") or "").strip() or (
                    f"Cari#{t['cari_id']}" if t.get("cari_id") else "Müşteri"
                )
                konu = f"Ara: {musteri} — {aday['urun_adi']}"
                aciklama = (
                    f"Sorulan talep #{t['id']}\n"
                    f"Ürün: {aday['urun_adi']}\n"
                    f"Talep miktarı: {t['miktar'] if t['miktar'] is not None else 'bilinmiyor'}\n"
                    f"Kullanılabilir stok: {miktar}\n"
                    f"Telefon: {tel or '—'}\n"
                    f"Stok sınırlı olabilir; tüm müşterilere yeterlilik taahhüdü yok.\n"
                    f"Olay: {olay_anahtar or 'manuel_kontrol'}"
                )

                if miktar <= 0:
                    mevcut = AktiviteService.kaynak_ile_bul(
                        kaynak_belge_tur="SORULAN_TALEP",
                        kaynak_belge_id=int(t["id"]),
                        tur_kod="MUSTERI_ARAMASI",
                    )
                    if mevcut and mevcut["durum"] not in ("TAMAMLANDI", "IPTAL"):
                        AktiviteService.kaynak_ile_kaydet_veya_guncelle(
                            {
                                "kaynak_belge_tur": "SORULAN_TALEP",
                                "kaynak_belge_id": int(t["id"]),
                                "kaynak_belge_no": f"SRT-{t['id']}",
                                "tur_kod": "MUSTERI_ARAMASI",
                                "konu": konu,
                                "cari_id": t.get("cari_id"),
                                "aciklama": aciklama
                                + "\n⚠ Stok yeniden kontrol edilmeli (miktar bitti).",
                                "durum": "BEKLEMEDE",
                                "oncelik": "NORMAL",
                            }
                        )
                        guncellenen += 1
                        detay.append({"talep_id": t["id"], "sonuc": "stok_bitti_guncelle"})
                    else:
                        atlanan += 1
                        detay.append({"talep_id": t["id"], "sonuc": "stok_yok"})
                    continue

                kayit = AktiviteService.kaynak_ile_kaydet_veya_guncelle(
                    {
                        "kaynak_belge_tur": "SORULAN_TALEP",
                        "kaynak_belge_id": int(t["id"]),
                        "kaynak_belge_no": f"SRT-{t['id']}",
                        "tur_kod": "MUSTERI_ARAMASI",
                        "konu": konu,
                        "cari_id": t.get("cari_id"),
                        "aciklama": aciklama,
                        "durum": "ACIK",
                        "oncelik": "YUKSEK",
                        "plan_tarih": date.today(),
                        "sorumlu_personel_id": None,
                    }
                )
                if kayit.get("guncellendi"):
                    guncellenen += 1
                else:
                    olusturulan += 1
                if t["durum"] in ("ACIK", "TAKIPTE", "URUN_GELDI", "SIPARIS_VERILDI"):
                    durum_guncelle.append(int(t["id"]))
                detay.append(
                    {
                        "talep_id": t["id"],
                        "aktivite_id": kayit["id"],
                        "sonuc": "guncelle" if kayit.get("guncellendi") else "olustur",
                    }
                )

        with get_session() as session:
            if miktar > 0:
                for aday in aday_ozet:
                    a = session.get(SorulanUrunAday, int(aday["id"]))
                    if a is not None and int(a.firma_id) == firma:
                        a.tedarik_durumu = "STOKTA"
                        a.guncelleme_tarihi = datetime.utcnow()
            for tid in durum_guncelle:
                trow = session.get(SorulanUrunTalep, tid)
                if trow is not None and int(trow.firma_id) == firma:
                    trow.durum = "ARAMA_BEKLIYOR"
                    trow.guncelleme_tarihi = datetime.utcnow()
            session.flush()

        return {
            "olusturulan": olusturulan,
            "guncellenen": guncellenen,
            "atlanan": atlanan,
            "mevcut_miktar": str(miktar),
            "stok_id": hedef_stok,
            "detay": detay,
        }

    # ── Ekler / fotoğraf ──────────────────────────────────────────────
    @staticmethod
    def _ek_kok(firma_id: int, aday_id: int) -> Path:
        p = Path(DB_DIR) / "sorulan_urun_ekler" / str(firma_id) / str(aday_id)
        p.mkdir(parents=True, exist_ok=True)
        return p

    @staticmethod
    def ek_ekle(
        aday_id: int,
        kaynak_yol: str | Path,
        *,
        etiket: str | None = None,
        aciklama: str | None = None,
        ana: bool = False,
    ) -> dict[str, Any]:
        """Dosyayı firma klasörüne kopyalar; geçici klasör silinse de kalır."""
        yazma_zorunlu()
        SorulanUrunService.ensure_schema()
        kaynak = Path(kaynak_yol)
        if not kaynak.is_file():
            raise ValueError(f"Dosya bulunamadı: {kaynak}")
        firma = SorulanUrunService._firma_id()
        with get_session() as session:
            a = session.get(SorulanUrunAday, int(aday_id))
            if a is None or int(a.firma_id) != firma:
                raise ValueError("Ürün bulunamadı.")
        hedef_dir = SorulanUrunService._ek_kok(firma, int(aday_id))
        uzanti = kaynak.suffix.lower() or ".bin"
        ad = f"{uuid.uuid4().hex}{uzanti}"
        hedef = hedef_dir / ad
        shutil.copy2(kaynak, hedef)
        mime = {
            ".jpg": "image/jpeg",
            ".jpeg": "image/jpeg",
            ".png": "image/png",
            ".gif": "image/gif",
            ".webp": "image/webp",
            ".pdf": "application/pdf",
            ".mp4": "video/mp4",
        }.get(uzanti, "application/octet-stream")
        onizleme = None
        if mime.startswith("image/"):
            try:
                from PIL import Image

                thumb = hedef_dir / f"thumb_{ad}.jpg"
                with Image.open(hedef) as im:
                    im.thumbnail((160, 160))
                    im.convert("RGB").save(thumb, "JPEG", quality=75)
                onizleme = str(thumb)
            except Exception:
                onizleme = None
        with get_session() as session:
            if ana:
                for e in session.scalars(
                    select(SorulanUrunEk).where(SorulanUrunEk.aday_id == int(aday_id))
                ):
                    e.ana_fotograf = False
            ek = SorulanUrunEk(
                aday_id=int(aday_id),
                dosya_yolu=str(hedef),
                orijinal_ad=kaynak.name,
                mime=mime,
                etiket=etiket or "Diğer",
                aciklama=aciklama,
                ana_fotograf=bool(ana),
                onizleme_yolu=onizleme,
            )
            session.add(ek)
            session.flush()
            return {"id": int(ek.id), "yol": str(hedef), "onizleme": onizleme}

    @staticmethod
    def ekler(aday_id: int) -> list[dict[str, Any]]:
        SorulanUrunService.ensure_schema()
        firma = SorulanUrunService._firma_id()
        with get_session() as session:
            a = session.get(SorulanUrunAday, int(aday_id))
            if a is None or int(a.firma_id) != firma:
                return []
            rows = session.scalars(
                select(SorulanUrunEk)
                .where(SorulanUrunEk.aday_id == int(aday_id))
                .order_by(SorulanUrunEk.ana_fotograf.desc(), SorulanUrunEk.id)
            ).all()
            return [
                {
                    "id": int(e.id),
                    "yol": e.dosya_yolu,
                    "onizleme": e.onizleme_yolu or e.dosya_yolu,
                    "etiket": e.etiket or "",
                    "aciklama": e.aciklama or "",
                    "ana": bool(e.ana_fotograf),
                    "orijinal": e.orijinal_ad or "",
                    "mime": e.mime or "",
                }
                for e in rows
            ]

    @staticmethod
    def tekrar_soruldu(
        talep_id: int,
        *,
        tarih: date | None = None,
        saat: str | None = None,
        notlar: str | None = None,
    ) -> dict[str, Any]:
        """Aynı talebe tarihli tekrar; miktar/bağımsız talep artmaz."""
        yazma_zorunlu()
        SorulanUrunService.ensure_schema()
        t_gun = tarih or bugun_tr()
        if t_gun > bugun_tr():
            raise ValueError("Tekrar sorulma tarihi gelecek olamaz.")
        firma = SorulanUrunService._firma_id()
        with get_session() as session:
            t = session.get(SorulanUrunTalep, int(talep_id))
            if t is None or int(t.firma_id) != firma or t.gecersiz:
                raise ValueError("Talep bulunamadı.")
            tr = SorulanUrunTekrar(
                talep_id=int(t.id),
                tekrar_tarihi=t_gun,
                tekrar_saati=(saat or None),
                notlar=notlar,
                olusturan=getattr(oturum, "kullanici_adi", None),
            )
            session.add(tr)
            t.guncelleme_tarihi = datetime.utcnow()
            session.flush()
            return {"id": int(tr.id), "talep_id": int(t.id), "tarih": tarih_goster(t_gun)}

    @staticmethod
    def sorulma_tarihi_duzelt(
        talep_id: int,
        yeni_tarih: date | str | None,
        *,
        bilinmiyor: bool = False,
        saat: str | None = None,
        notlar: str | None = None,
    ) -> dict[str, Any]:
        """Sorulma tarihini düzeltir; eski/yeni loglanır. Raporlar yeni tarihe göre."""
        yazma_zorunlu()
        SorulanUrunService.ensure_schema()
        firma = SorulanUrunService._firma_id()
        if isinstance(yeni_tarih, str):
            yeni_tarih = tarih_coz(yeni_tarih) if yeni_tarih.strip() else None
        if not bilinmiyor:
            if yeni_tarih is None:
                raise ValueError("Yeni sorulma tarihi gerekli.")
            if yeni_tarih > bugun_tr():
                raise ValueError("Sorulduğu tarih gelecek olamaz.")
        with get_session() as session:
            t = session.get(SorulanUrunTalep, int(talep_id))
            if t is None or int(t.firma_id) != firma:
                raise ValueError("Talep bulunamadı.")
            eski = (
                "BILINMIYOR"
                if getattr(t, "sorulma_tarihi_bilinmiyor", False)
                else t.talep_tarihi.isoformat()
            )
            if bilinmiyor:
                t.sorulma_tarihi_bilinmiyor = True
                # NOT NULL kolon — değer korunur ama bayrakla ayrılır
            else:
                t.sorulma_tarihi_bilinmiyor = False
                t.talep_tarihi = yeni_tarih  # type: ignore[assignment]
            if saat is not None:
                t.sorulma_saati = saat or None
            t.guncelleme_tarihi = datetime.utcnow()
            log = SorulanUrunTarihLog(
                talep_id=int(t.id),
                eski_tarih=eski,
                yeni_tarih="BILINMIYOR" if bilinmiyor else yeni_tarih.isoformat(),  # type: ignore[union-attr]
                kullanici=getattr(oturum, "kullanici_adi", None),
                notlar=notlar,
            )
            session.add(log)
            session.flush()
            return {"talep_id": int(t.id), "eski": eski, "yeni": log.yeni_tarih}

    @staticmethod
    def olcu_kaydet(aday_id: int, satirlar: list[dict[str, Any]]) -> int:
        """Ölçü tablosunu değiştirir (aday bazında). Boş değer = bilinmiyor (sıfır yazılmaz)."""
        yazma_zorunlu()
        SorulanUrunService.ensure_schema()
        firma = SorulanUrunService._firma_id()
        with get_session() as session:
            a = session.get(SorulanUrunAday, int(aday_id))
            if a is None or int(a.firma_id) != firma:
                raise ValueError("Ürün bulunamadı.")
            for eski in session.scalars(
                select(SorulanUrunOlcu).where(SorulanUrunOlcu.aday_id == int(aday_id))
            ):
                session.delete(eski)
            n = 0
            for i, s in enumerate(satirlar or []):
                ad = (s.get("olcu_adi") or "").strip()
                if not ad:
                    continue
                deger = s.get("deger")
                if deger is not None and str(deger).strip() == "":
                    deger = None
                session.add(
                    SorulanUrunOlcu(
                        aday_id=int(aday_id),
                        olcu_adi=ad,
                        deger=None if deger is None else str(deger).strip(),
                        birim=(s.get("birim") or None),
                        aciklama=(s.get("aciklama") or None),
                        kaynak=(s.get("kaynak") or "TAHMINI"),
                        sira=i,
                    )
                )
                n += 1
            session.flush()
            return n

    @staticmethod
    def olculer(aday_id: int) -> list[dict[str, Any]]:
        SorulanUrunService.ensure_schema()
        with get_session() as session:
            rows = session.scalars(
                select(SorulanUrunOlcu)
                .where(SorulanUrunOlcu.aday_id == int(aday_id))
                .order_by(SorulanUrunOlcu.sira, SorulanUrunOlcu.id)
            ).all()
            return [
                {
                    "id": int(o.id),
                    "olcu_adi": o.olcu_adi,
                    "deger": o.deger,
                    "birim": o.birim or "",
                    "aciklama": o.aciklama or "",
                    "kaynak": o.kaynak,
                }
                for o in rows
            ]

    @staticmethod
    def gorusme_ekle(aday_id: int, veriler: dict[str, Any]) -> dict[str, Any]:
        yazma_zorunlu()
        SorulanUrunService.ensure_schema()
        firma = SorulanUrunService._firma_id()
        gt = veriler.get("gorusme_tarihi") or bugun_tr()
        if isinstance(gt, str):
            gt = tarih_coz(gt)
        with get_session() as session:
            a = session.get(SorulanUrunAday, int(aday_id))
            if a is None or int(a.firma_id) != firma:
                raise ValueError("Ürün bulunamadı.")
            g = SorulanUrunGorusme(
                aday_id=int(aday_id),
                talep_id=int(veriler["talep_id"]) if veriler.get("talep_id") else None,
                gorusme_tarihi=gt,
                tedarikci=(veriler.get("tedarikci") or None),
                cevap=(veriler.get("cevap") or None),
                bulunan_kod=(veriler.get("bulunan_kod") or None),
                fiyat=Decimal(str(veriler["fiyat"])) if veriler.get("fiyat") not in (None, "") else None,
                teslim_suresi=(veriler.get("teslim_suresi") or None),
                notlar=(veriler.get("notlar") or None),
                olusturan=getattr(oturum, "kullanici_adi", None),
            )
            session.add(g)
            session.flush()
            return {"id": int(g.id)}

    @staticmethod
    def olay_gecmisi(talep_id: int) -> list[dict[str, Any]]:
        """İlk sorulma, tekrarlar, görüşmeler, sonuç — kronolojik."""
        SorulanUrunService.ensure_schema()
        firma = SorulanUrunService._firma_id()
        olaylar: list[dict[str, Any]] = []
        with get_session() as session:
            t = session.get(SorulanUrunTalep, int(talep_id))
            if t is None or int(t.firma_id) != firma:
                return []
            bilinmiyor = bool(getattr(t, "sorulma_tarihi_bilinmiyor", False))
            olaylar.append(
                {
                    "tur": "ilk_sorulma",
                    "tarih": "Bilinmiyor" if bilinmiyor else tarih_goster(t.talep_tarihi),
                    "tarih_iso": "" if bilinmiyor else t.talep_tarihi.isoformat(),
                    "aciklama": "İlk sorulma",
                }
            )
            for tr in session.scalars(
                select(SorulanUrunTekrar)
                .where(SorulanUrunTekrar.talep_id == t.id)
                .order_by(SorulanUrunTekrar.tekrar_tarihi)
            ):
                olaylar.append(
                    {
                        "tur": "tekrar",
                        "tarih": tarih_goster(tr.tekrar_tarihi),
                        "tarih_iso": tr.tekrar_tarihi.isoformat(),
                        "aciklama": tr.notlar or "Tekrar soruldu",
                    }
                )
            for g in session.scalars(
                select(SorulanUrunGorusme)
                .where(
                    (SorulanUrunGorusme.talep_id == t.id)
                    | (SorulanUrunGorusme.aday_id == t.aday_id)
                )
                .order_by(SorulanUrunGorusme.gorusme_tarihi)
            ):
                olaylar.append(
                    {
                        "tur": "gorusme",
                        "tarih": tarih_goster(g.gorusme_tarihi),
                        "tarih_iso": g.gorusme_tarihi.isoformat(),
                        "aciklama": f"{g.tedarikci or ''}: {g.cevap or g.notlar or ''}".strip(": "),
                    }
                )
            if t.sonuc_tarihi:
                olaylar.append(
                    {
                        "tur": "sonuc",
                        "tarih": tarih_goster(t.sonuc_tarihi),
                        "tarih_iso": t.sonuc_tarihi.isoformat(),
                        "aciklama": f"Sonuç: {etiket_durum(t.durum)}",
                    }
                )
        olaylar.sort(key=lambda o: (o["tarih_iso"] == "", o["tarih_iso"]))
        return olaylar

    @staticmethod
    def donem_filtre_coz(anahtar: str, bas: str | None = None, bit: str | None = None) -> tuple[date | None, date | None]:
        """Bugün / 7 / 30 / 90 / bu_ay / ozel → (bas, bit) dahil."""
        bugun = bugun_tr()
        k = (anahtar or "").strip().upper()
        if k in ("TUM", "HEPSI", ""):
            return None, None
        if k == "BUGUN":
            return bugun, bugun
        if k in ("7", "SON_7"):
            return bugun - timedelta(days=6), bugun
        if k in ("30", "SON_30"):
            return bugun - timedelta(days=29), bugun
        if k in ("90", "SON_90"):
            return bugun - timedelta(days=89), bugun
        if k in ("BU_AY", "AY"):
            return bugun.replace(day=1), bugun
        if k == "OZEL":
            return (
                tarih_coz(bas) if bas else None,
                tarih_coz(bit) if bit else None,
            )
        try:
            gun = int(k)
            return bugun - timedelta(days=max(0, gun - 1)), bugun
        except ValueError:
            return None, None

    @staticmethod
    def acik_geciken(*, min_bekleme: int = 0) -> list[dict[str, Any]]:
        SorulanUrunService.ensure_schema()
        firma = SorulanUrunService._firma_id()
        bugun = bugun_tr()
        with get_session() as session:
            rows = session.scalars(
                select(SorulanUrunTalep).where(
                    SorulanUrunTalep.firma_id == firma,
                    SorulanUrunTalep.gecersiz.is_(False),
                    SorulanUrunTalep.durum.in_(list(_ACIK_DURUMLAR)),
                )
            ).all()
            out = []
            for t in rows:
                bg = _bekleme_gunu(t, bugun=bugun)
                if bg is None:
                    continue
                if bg < int(min_bekleme):
                    continue
                a = session.get(SorulanUrunAday, t.aday_id)
                out.append(
                    {
                        "talep_id": int(t.id),
                        "urun": a.urun_adi if a else "",
                        "musteri": t.musteri_adi or ("Anonim" if t.anonim else ""),
                        "sorulma": tarih_goster(t.talep_tarihi),
                        "bekleme_gun": bg,
                        "ihtiyac": tarih_goster(getattr(t, "ihtiyac_tarihi", None)),
                        "sorumlu": getattr(t, "sorumlu_personel", None) or "",
                        "durum": etiket_durum(t.durum),
                    }
                )
            out.sort(key=lambda r: -int(r["bekleme_gun"]))
            return out

    @staticmethod
    def benzer_adaylar(metin: str, *, limit: int = 10) -> list[dict[str, Any]]:
        """Ad/tarif/marka/model/parça kodu ile öneri; otomatik birleştirmez."""
        SorulanUrunService.ensure_schema()
        q = (metin or "").strip()
        if len(q) < 2:
            return []
        firma = SorulanUrunService._firma_id()
        like = f"%{q}%"
        with get_session() as session:
            rows = session.scalars(
                select(SorulanUrunAday)
                .where(
                    SorulanUrunAday.firma_id == firma,
                    SorulanUrunAday.arsiv.is_(False),
                    (
                        SorulanUrunAday.urun_adi.ilike(like)
                        | SorulanUrunAday.musteri_tarifi.ilike(like)
                        | SorulanUrunAday.diger_adlar.ilike(like)
                        | SorulanUrunAday.marka.ilike(like)
                        | SorulanUrunAday.model.ilike(like)
                        | SorulanUrunAday.uretici_kodu.ilike(like)
                    ),
                )
                .limit(int(limit))
            ).all()
            return [
                {
                    "id": int(a.id),
                    "urun_adi": a.urun_adi,
                    "marka": a.marka or "",
                    "model": a.model or "",
                    "tarif": (a.musteri_tarifi or "")[:60],
                }
                for a in rows
            ]
