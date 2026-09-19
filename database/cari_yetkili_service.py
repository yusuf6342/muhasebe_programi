"""Cari işletme yetkilileri — CRUD, ana yetkili, doğum günü, arama."""

from __future__ import annotations

import re
from datetime import date, datetime, timedelta
from typing import Any

from sqlalchemy import or_, select
from sqlalchemy.orm import selectinload

from database.access import yetki_var, yetki_zorunlu, yazma_zorunlu
from database.database import get_session
from database.models.cari import Cari, CariYetkili
from database.turkce_normalize import turkce_normalize
from database.user_audit import audit_document

_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
_TEL_RE = re.compile(r"^[\d\s+\-().]{7,30}$")


def _norm_ad(ad: str, soyad: str) -> str:
    return turkce_normalize(f"{(ad or '').strip()} {(soyad or '').strip()}".strip())


def _yas(dogum: date | None, bugun: date | None = None) -> int | None:
    if not dogum:
        return None
    bugun = bugun or date.today()
    y = bugun.year - dogum.year
    if (bugun.month, bugun.day) < (dogum.month, dogum.day):
        y -= 1
    return max(0, y)


def _sonraki_dogum(dogum: date, bugun: date | None = None) -> date | None:
    """Bu yıl veya gelecek yıldaki bir sonraki doğum günü (29 Şubat → 28 Şubat)."""
    if not dogum:
        return None
    bugun = bugun or date.today()
    ay, gun = dogum.month, dogum.day
    for yil in (bugun.year, bugun.year + 1):
        try:
            aday = date(yil, ay, gun)
        except ValueError:
            # 29 Şubat → 28 Şubat
            aday = date(yil, ay, 28)
        if aday >= bugun:
            return aday
    return None


def _dogrula(veriler: dict[str, Any], *, hassas_izinli: bool) -> dict[str, Any]:
    ad = (veriler.get("ad") or "").strip()
    soyad = (veriler.get("soyad") or "").strip()
    if not ad or not soyad:
        raise ValueError("Ad ve soyad zorunludur.")
    email = (veriler.get("email") or "").strip() or None
    if email and not _EMAIL_RE.match(email):
        raise ValueError("E-posta biçimi geçersiz.")
    for alan in ("cep_telefonu", "telefon2", "whatsapp_telefonu", "is_telefonu"):
        tel = (veriler.get(alan) or "").strip() or None
        if tel and not _TEL_RE.match(tel):
            raise ValueError(f"{alan.replace('_', ' ').title()} biçimi geçersiz.")
        veriler[alan] = tel
    dogum = veriler.get("dogum_tarihi")
    if dogum in ("", None):
        dogum = None
    elif isinstance(dogum, str):
        for fmt in ("%d.%m.%Y", "%Y-%m-%d"):
            try:
                dogum = datetime.strptime(dogum.strip(), fmt).date()
                break
            except ValueError:
                continue
        else:
            raise ValueError("Doğum tarihi GG.AA.YYYY biçiminde olmalıdır.")
    if isinstance(dogum, date) and dogum > date.today():
        raise ValueError("Doğum tarihi gelecekte olamaz.")
    if not hassas_izinli:
        # Hassas alanları koru / temizle
        dogum = None
        veriler["ozel_notlar"] = None
        veriler["gorusme_notu"] = None
        veriler["pazarlama_izni"] = False
        veriler["kvkk_onayi"] = False
        veriler["onay_tarihi"] = None
    veriler["ad"] = ad
    veriler["soyad"] = soyad
    veriler["email"] = email
    veriler["dogum_tarihi"] = dogum
    veriler["ad_soyad_norm"] = _norm_ad(ad, soyad)
    veriler["unvan"] = (veriler.get("unvan") or "").strip() or None
    veriler["departman"] = (veriler.get("departman") or "").strip() or None
    veriler["gorev"] = (veriler.get("gorev") or "").strip() or None
    veriler["hitap"] = (veriler.get("hitap") or "").strip() or None
    veriler["iletisim_kanali"] = (veriler.get("iletisim_kanali") or "").strip() or None
    veriler["dahili"] = (veriler.get("dahili") or "").strip() or None
    veriler["adres"] = (veriler.get("adres") or "").strip() or None
    veriler["il"] = (veriler.get("il") or "").strip() or None
    veriler["ilce"] = (veriler.get("ilce") or "").strip() or None
    if hassas_izinli:
        veriler["ozel_notlar"] = (veriler.get("ozel_notlar") or "").strip() or None
        veriler["gorusme_notu"] = (veriler.get("gorusme_notu") or "").strip() or None
    veriler["ana_yetkili"] = bool(veriler.get("ana_yetkili"))
    veriler["aktif"] = bool(veriler.get("aktif", True))
    veriler["dogum_gunu_hatirlat"] = bool(veriler.get("dogum_gunu_hatirlat", True))
    veriler["pazarlama_izni"] = bool(veriler.get("pazarlama_izni"))
    veriler["kvkk_onayi"] = bool(veriler.get("kvkk_onayi"))
    return veriler


def _ozet(y: CariYetkili, *, hassas: bool = False) -> dict[str, Any]:
    d = {
        "id": y.id,
        "cari_id": y.cari_id,
        "ad": y.ad,
        "soyad": y.soyad,
        "ad_soyad": f"{y.ad} {y.soyad}".strip(),
        "unvan": y.unvan or "",
        "departman": y.departman or "",
        "gorev": y.gorev or "",
        "ana_yetkili": bool(y.ana_yetkili),
        "aktif": bool(y.aktif),
        "cep_telefonu": y.cep_telefonu or "",
        "telefon2": y.telefon2 or "",
        "whatsapp_telefonu": y.whatsapp_telefonu or "",
        "is_telefonu": y.is_telefonu or "",
        "dahili": y.dahili or "",
        "email": y.email or "",
        "hitap": y.hitap or "",
        "iletisim_kanali": y.iletisim_kanali or "",
        "adres": y.adres or "",
        "il": y.il or "",
        "ilce": y.ilce or "",
        "dogum_gunu_hatirlat": bool(y.dogum_gunu_hatirlat),
    }
    if hassas:
        d["dogum_tarihi"] = y.dogum_tarihi
        d["yas"] = _yas(y.dogum_tarihi)
        d["ozel_notlar"] = y.ozel_notlar or ""
        d["gorusme_notu"] = y.gorusme_notu or ""
        d["pazarlama_izni"] = bool(y.pazarlama_izni)
        d["kvkk_onayi"] = bool(y.kvkk_onayi)
        d["onay_tarihi"] = y.onay_tarihi
    else:
        d["dogum_tarihi"] = None
        d["yas"] = None
        d["ozel_notlar"] = ""
        d["gorusme_notu"] = ""
    return d


def _kullanici_damgasi() -> dict[str, Any]:
    try:
        from database.session_manager import oturum

        return {
            "user_id": getattr(oturum, "user_id", None),
            "username": getattr(oturum, "kullanici_adi", None) or "",
        }
    except Exception:
        return {"user_id": None, "username": ""}


class CariYetkiliService:
    @staticmethod
    def schema_hazirla() -> None:
        """cari_yetkililer tablosunu oluşturur (idempotent; veri silmez)."""
        from database.database import engine

        CariYetkili.__table__.create(engine, checkfirst=True)

    @staticmethod
    def kullanim_ozeti(yetkili_id: int) -> dict[str, Any]:
        """Gelecekteki bağlantılar için; şu an bağlı hareket yoksa boş."""
        return {
            "yetkili_id": int(yetkili_id),
            "hareket_sayisi": 0,
            "gorusme_sayisi": 0,
            "hatirlatma_sayisi": 0,
            "kullanimda": False,
        }

    @staticmethod
    def hassas_izinli() -> bool:
        return yetki_var("cari_yetkili_duzenle", "cari_duzenleme", "YONETICI") or yetki_var(
            "cari_yetkili_goruntule"
        )

    @staticmethod
    def duzenleme_izinli() -> bool:
        return yetki_var("cari_yetkili_duzenle", "cari_duzenleme")

    @staticmethod
    def listele(cari_id: int, *, pasifler_dahil: bool = False) -> list[dict[str, Any]]:
        yetki_zorunlu("cari_yetkili_goruntule", "cari_goruntuleme", "cari_duzenleme")
        hassas = CariYetkiliService.hassas_izinli()
        with get_session() as session:
            q = select(CariYetkili).where(
                CariYetkili.cari_id == int(cari_id),
                or_(CariYetkili.is_deleted.is_(False), CariYetkili.is_deleted.is_(None)),
            )
            if not pasifler_dahil:
                q = q.where(CariYetkili.aktif.is_(True))
            q = q.order_by(CariYetkili.ana_yetkili.desc(), CariYetkili.ad, CariYetkili.soyad)
            return [_ozet(y, hassas=hassas) for y in session.scalars(q).all()]

    @staticmethod
    def ana_yetkili(cari_id: int) -> dict[str, Any] | None:
        kayitlar = CariYetkiliService.listele(cari_id, pasifler_dahil=False)
        for k in kayitlar:
            if k.get("ana_yetkili"):
                return k
        return kayitlar[0] if kayitlar else None

    @staticmethod
    def ekle(cari_id: int, veriler: dict[str, Any]) -> dict[str, Any]:
        yazma_zorunlu("cari_yetkili_duzenle", "cari_duzenleme")
        hassas = CariYetkiliService.hassas_izinli()
        veri = _dogrula(dict(veriler), hassas_izinli=hassas)
        damga = _kullanici_damgasi()
        with get_session() as session:
            cari = session.get(Cari, int(cari_id))
            if cari is None or getattr(cari, "is_deleted", False):
                raise ValueError("Cari kart bulunamadı.")
            # Mükerrer kontrol
            ayni = session.scalar(
                select(CariYetkili).where(
                    CariYetkili.cari_id == int(cari_id),
                    CariYetkili.ad_soyad_norm == veri["ad_soyad_norm"],
                    or_(CariYetkili.is_deleted.is_(False), CariYetkili.is_deleted.is_(None)),
                )
            )
            if ayni is not None:
                raise ValueError("Bu ad-soyad ile yetkili zaten kayıtlı.")
            if veri["ana_yetkili"]:
                for eski in session.scalars(
                    select(CariYetkili).where(
                        CariYetkili.cari_id == int(cari_id),
                        CariYetkili.ana_yetkili.is_(True),
                        or_(CariYetkili.is_deleted.is_(False), CariYetkili.is_deleted.is_(None)),
                    )
                ).all():
                    eski.ana_yetkili = False
            kayit = CariYetkili(
                cari_id=int(cari_id),
                created_at=datetime.now(),
                updated_at=datetime.now(),
                created_by_user_id=damga["user_id"],
                created_by_username=damga["username"],
                updated_by_user_id=damga["user_id"],
                updated_by_username=damga["username"],
            )
            for k, v in veri.items():
                if hasattr(kayit, k):
                    setattr(kayit, k, v)
            session.add(kayit)
            session.flush()
            ozet = _ozet(kayit, hassas=hassas)
            audit_document(
                "cari_yetkili_ekle",
                modul="cari",
                kayit_id=str(kayit.id),
                belge_no=cari.cari_kodu,
                yeni=ozet,
            )
            return ozet

    @staticmethod
    def guncelle(yetkili_id: int, veriler: dict[str, Any]) -> dict[str, Any]:
        yazma_zorunlu("cari_yetkili_duzenle", "cari_duzenleme")
        hassas = CariYetkiliService.hassas_izinli()
        veri = _dogrula(dict(veriler), hassas_izinli=hassas)
        damga = _kullanici_damgasi()
        with get_session() as session:
            kayit = session.get(CariYetkili, int(yetkili_id))
            if kayit is None or kayit.is_deleted:
                raise ValueError("Yetkili bulunamadı.")
            eski = _ozet(kayit, hassas=hassas)
            # Mükerrer
            ayni = session.scalar(
                select(CariYetkili).where(
                    CariYetkili.cari_id == kayit.cari_id,
                    CariYetkili.ad_soyad_norm == veri["ad_soyad_norm"],
                    CariYetkili.id != kayit.id,
                    or_(CariYetkili.is_deleted.is_(False), CariYetkili.is_deleted.is_(None)),
                )
            )
            if ayni is not None:
                raise ValueError("Bu ad-soyad ile yetkili zaten kayıtlı.")
            if veri["ana_yetkili"]:
                for diger in session.scalars(
                    select(CariYetkili).where(
                        CariYetkili.cari_id == kayit.cari_id,
                        CariYetkili.ana_yetkili.is_(True),
                        CariYetkili.id != kayit.id,
                        or_(CariYetkili.is_deleted.is_(False), CariYetkili.is_deleted.is_(None)),
                    )
                ).all():
                    diger.ana_yetkili = False
            for k, v in veri.items():
                if hasattr(kayit, k):
                    setattr(kayit, k, v)
            kayit.updated_at = datetime.now()
            kayit.updated_by_user_id = damga["user_id"]
            kayit.updated_by_username = damga["username"]
            session.flush()
            yeni = _ozet(kayit, hassas=hassas)
            audit_document(
                "cari_yetkili_guncelle",
                modul="cari",
                kayit_id=str(kayit.id),
                eski=eski,
                yeni=yeni,
            )
            return yeni

    @staticmethod
    def pasife_al(yetkili_id: int) -> dict[str, Any]:
        yazma_zorunlu("cari_yetkili_duzenle", "cari_duzenleme")
        with get_session() as session:
            kayit = session.get(CariYetkili, int(yetkili_id))
            if kayit is None or kayit.is_deleted:
                raise ValueError("Yetkili bulunamadı.")
            eski = {"aktif": kayit.aktif, "ana_yetkili": kayit.ana_yetkili}
            kayit.aktif = False
            kayit.ana_yetkili = False
            kayit.updated_at = datetime.now()
            session.flush()
            audit_document(
                "cari_yetkili_pasif",
                modul="cari",
                kayit_id=str(kayit.id),
                eski=eski,
                yeni={"aktif": False},
            )
            return _ozet(kayit, hassas=CariYetkiliService.hassas_izinli())

    @staticmethod
    def sil(yetkili_id: int, *, fiziksel: bool = False) -> None:
        """Varsayılan soft-delete; fiziksel yalnızca açıkça istenirse ve kullanım yoksa."""
        yazma_zorunlu("cari_yetkili_duzenle", "cari_duzenleme")
        ozet = CariYetkiliService.kullanim_ozeti(yetkili_id)
        if fiziksel and ozet.get("kullanimda"):
            raise ValueError(
                "Bu yetkilinin geçmiş bağlantıları var; fiziksel silme yapılamaz. Pasife alın."
            )
        with get_session() as session:
            kayit = session.get(CariYetkili, int(yetkili_id))
            if kayit is None:
                raise ValueError("Yetkili bulunamadı.")
            eski = _ozet(kayit, hassas=True)
            if fiziksel:
                session.delete(kayit)
            else:
                kayit.is_deleted = True
                kayit.aktif = False
                kayit.ana_yetkili = False
                kayit.deleted_at = datetime.now()
            session.flush()
            audit_document(
                "cari_yetkili_sil",
                modul="cari",
                kayit_id=str(yetkili_id),
                eski=eski,
                yeni={"fiziksel": fiziksel, "is_deleted": True},
            )

    @staticmethod
    def dogum_gunleri(
        *,
        gun: int = 7,
        cari_turu: str | None = None,
        musteri_grubu: str | None = None,
        sadece_aktif_cari: bool = True,
        hatirlat_kapali_dahil: bool = False,
    ) -> list[dict[str, Any]]:
        """Yaklaşan doğum günleri (bugün + sonraki N gün)."""
        yetki_zorunlu("cari_yetkili_goruntule", "cari_goruntuleme", "cari_duzenleme")
        if not CariYetkiliService.hassas_izinli():
            return []
        bugun = date.today()
        bitis = bugun + timedelta(days=max(0, int(gun)))
        with get_session() as session:
            q = (
                select(CariYetkili, Cari)
                .join(Cari, Cari.id == CariYetkili.cari_id)
                .where(
                    CariYetkili.aktif.is_(True),
                    or_(CariYetkili.is_deleted.is_(False), CariYetkili.is_deleted.is_(None)),
                    or_(Cari.is_deleted.is_(False), Cari.is_deleted.is_(None)),
                    CariYetkili.dogum_tarihi.is_not(None),
                )
            )
            if not hatirlat_kapali_dahil:
                q = q.where(CariYetkili.dogum_gunu_hatirlat.is_(True))
            if sadece_aktif_cari:
                q = q.where(Cari.aktif.is_(True))
            if cari_turu:
                q = q.where(Cari.cari_turu == cari_turu)
            if musteri_grubu:
                q = q.where(Cari.musteri_grubu == musteri_grubu)
            sonuc = []
            for yetkili, cari in session.execute(q).all():
                sonraki = _sonraki_dogum(yetkili.dogum_tarihi, bugun)
                if sonraki is None or sonraki > bitis:
                    continue
                sonuc.append(
                    {
                        "yetkili_id": yetkili.id,
                        "cari_id": cari.id,
                        "cari_kodu": cari.cari_kodu,
                        "cari_unvan": cari.unvan,
                        "cari_turu": cari.cari_turu,
                        "ad_soyad": f"{yetkili.ad} {yetkili.soyad}".strip(),
                        "dogum_tarihi": yetkili.dogum_tarihi,
                        "sonraki_dogum": sonraki,
                        "gun_kaldi": (sonraki - bugun).days,
                        "cep_telefonu": yetkili.cep_telefonu or "",
                        "email": yetkili.email or "",
                        "yas": _yas(yetkili.dogum_tarihi, sonraki),
                    }
                )
            sonuc.sort(key=lambda x: (x["gun_kaldi"], x["ad_soyad"]))
            return sonuc

    @staticmethod
    def cari_ids_yetkili_arama(bloklar: list[str]) -> list[int]:
        """SearchService için: yetkili ad/telefon/email ile eşleşen cari id'leri."""
        if not bloklar:
            return []
        with get_session() as session:
            q = select(CariYetkili).where(
                CariYetkili.aktif.is_(True),
                or_(CariYetkili.is_deleted.is_(False), CariYetkili.is_deleted.is_(None)),
            )
            adaylar = list(session.scalars(q.limit(5000)).all())
            ids: list[int] = []
            for y in adaylar:
                havuz = " ".join(
                    turkce_normalize(p or "")
                    for p in (
                        y.ad,
                        y.soyad,
                        y.ad_soyad_norm,
                        y.cep_telefonu,
                        y.telefon2,
                        y.whatsapp_telefonu,
                        y.is_telefonu,
                        y.email,
                        y.unvan,
                        y.gorev,
                    )
                )
                if all(turkce_normalize(b) in havuz for b in bloklar if turkce_normalize(b)):
                    ids.append(int(y.cari_id))
            return list(dict.fromkeys(ids))
