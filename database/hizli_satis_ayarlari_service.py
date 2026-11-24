"""Hızlı Satış başlangıç müşterisi — firma DB'de kalıcı, makineler arası ortak.

Ayar kurulum klasöründe tutulmaz; soft-delete / pasif cariler satışa atanmaz.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, ForeignKey, Integer, String, select
from sqlalchemy.orm import Mapped, mapped_column

from database.database import Base, get_session

MOD_BOS = "BOS"
MOD_ATANAN = "ATANAN"
MODLAR = (MOD_BOS, MOD_ATANAN)

AYAR_YETKILERI = ("sistem_ayarlari", "firma_yonetme")


class HizliSatisBaslangicAyari(Base):
    """Firma başına tek satır: başlangıç modu + cari kimliği."""

    __tablename__ = "hizli_satis_baslangic_ayarlari"

    firma_id: Mapped[int] = mapped_column(
        ForeignKey("firmalar.id"), primary_key=True, autoincrement=False
    )
    baslangic_mod: Mapped[str] = mapped_column(String(12), nullable=False, default=MOD_BOS)
    baslangic_cari_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    guncelleyen_kullanici_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    guncelleyen_kullanici_adi: Mapped[str | None] = mapped_column(String(80), nullable=True)
    guncelleme_tarihi: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.now, nullable=False
    )


_SCHEMA_HAZIR: set[str] = set()


def schema_hazirla(engine=None) -> None:
    from database.database import engine as global_engine

    eng = engine or global_engine
    if eng is None:
        return
    anahtar = str(eng.url)
    if anahtar in _SCHEMA_HAZIR:
        return
    import database.models.firma  # noqa: F401

    HizliSatisBaslangicAyari.__table__.create(eng, checkfirst=True)
    _SCHEMA_HAZIR.add(anahtar)


def _firma_id(session) -> int:
    from database.donem_service import DonemService

    return int(DonemService._yerel_firma_id(session))


def _bos_ayar() -> dict[str, Any]:
    return {
        "baslangic_mod": MOD_BOS,
        "baslangic_cari_id": None,
        "cari_kodu": "",
        "cari_unvan": "",
        "kayit_var": False,
        "uyari": None,
    }


def _cari_satista_uygun_mu(cari) -> tuple[bool, str | None]:
    if cari is None:
        return False, "Kayıtlı başlangıç müşterisi bulunamadı."
    if getattr(cari, "is_deleted", False):
        return False, "Kayıtlı başlangıç müşterisi silinmiş."
    if not bool(getattr(cari, "aktif", True)):
        return False, "Kayıtlı başlangıç müşterisi pasif."
    from database.cari_service import CariService

    try:
        uygunlar = {int(c.id) for c in CariService.aktif_evrak_carileri()}
        if int(cari.id) not in uygunlar:
            return False, "Kayıtlı başlangıç müşterisi satışta kullanılamıyor."
    except Exception:
        tur = (getattr(cari, "cari_turu", None) or "").strip()
        if tur and "müşteri" not in tur.casefold() and "musteri" not in tur.casefold():
            if "her" not in tur.casefold():
                return False, "Kayıtlı başlangıç müşterisi satışta kullanılamıyor."
    return True, None


def ayar_oku(*, session=None) -> dict[str, Any]:
    """Firma ayarını oku. Kayıt yoksa BOS (müşteri boş)."""
    schema_hazirla()
    from database.models.cari import Cari

    def _oku(s) -> dict[str, Any]:
        fid = _firma_id(s)
        satir = s.get(HizliSatisBaslangicAyari, fid)
        if satir is None:
            return _bos_ayar()
        mod = (satir.baslangic_mod or MOD_BOS).strip().upper()
        if mod not in MODLAR:
            mod = MOD_BOS
        out = {
            "baslangic_mod": mod,
            "baslangic_cari_id": int(satir.baslangic_cari_id)
            if satir.baslangic_cari_id
            else None,
            "cari_kodu": "",
            "cari_unvan": "",
            "kayit_var": True,
            "uyari": None,
        }
        if mod == MOD_ATANAN and out["baslangic_cari_id"]:
            cari = s.get(Cari, int(out["baslangic_cari_id"]))
            uygun, uyari = _cari_satista_uygun_mu(cari)
            if cari is not None:
                out["cari_kodu"] = (cari.cari_kodu or "").strip()
                out["cari_unvan"] = (cari.unvan or "").strip()
            if not uygun:
                out["uyari"] = uyari
                out["baslangic_cari_id"] = out["baslangic_cari_id"]  # id korunur; UI uyarır
        return out

    if session is not None:
        return _oku(session)
    with get_session() as s:
        return _oku(s)


def ayar_kaydet(*, baslangic_mod: str, baslangic_cari_id: int | None) -> dict[str, Any]:
    """Firma başlangıç ayarını kaydet. ATANAN modda geçerli cari zorunlu."""
    from database.access import yazma_zorunlu
    from database.models.cari import Cari
    from database.session_manager import oturum

    yazma_zorunlu(*AYAR_YETKILERI, mesaj="Hızlı Satış ayarlarını değiştirme yetkiniz yok.")
    schema_hazirla()
    mod = (baslangic_mod or "").strip().upper()
    if mod not in MODLAR:
        raise ValueError("Başlangıç modu BOS veya ATANAN olmalıdır.")
    cari_id = int(baslangic_cari_id) if baslangic_cari_id else None
    if mod == MOD_BOS:
        cari_id = None
    elif not cari_id:
        raise ValueError("Atanmış müşteri modu için geçerli bir müşteri seçin.")

    with get_session() as s:
        if mod == MOD_ATANAN:
            cari = s.get(Cari, int(cari_id))
            uygun, uyari = _cari_satista_uygun_mu(cari)
            if not uygun:
                raise ValueError(uyari or "Seçilen müşteri geçersiz.")
        fid = _firma_id(s)
        satir = s.get(HizliSatisBaslangicAyari, fid)
        if satir is None:
            satir = HizliSatisBaslangicAyari(firma_id=fid, baslangic_mod=mod)
            s.add(satir)
        satir.baslangic_mod = mod
        satir.baslangic_cari_id = cari_id
        satir.guncelleyen_kullanici_id = oturum.user_id
        satir.guncelleyen_kullanici_adi = oturum.kullanici_adi or oturum.ad_soyad
        satir.guncelleme_tarihi = datetime.now()
        s.flush()
        return ayar_oku(session=s)


def bos_musteri_ozeti() -> dict[str, Any]:
    return {
        "id": 0,
        "cari_kodu": "",
        "unvan": "",
        "musteri_grubu": None,
        "satis_fiyat_listesi": None,
        "acik_hesap_risk_limiti": None,
        "bakiye": None,
        "uyari_notu": None,
    }


def baslangic_musteri_coz() -> dict[str, Any]:
    """Yeni satış için müşteri özeti.

    Dönüş:
      ozet: cari_ozet_dict veya boş müşteri dict (id=0)
      uyari: str | None — geçersiz atanmış müşteri vb.
      mod: BOS | ATANAN
    """
    from hizli_satis_musteri import cari_ozet_coz

    ayar = ayar_oku()
    mod = ayar["baslangic_mod"]
    if mod != MOD_ATANAN:
        return {
            "ozet": bos_musteri_ozeti(),
            "uyari": None,
            "mod": MOD_BOS,
        }
    cid = ayar.get("baslangic_cari_id")
    if not cid or ayar.get("uyari"):
        return {
            "ozet": bos_musteri_ozeti(),
            "uyari": ayar.get("uyari")
            or "Kayıtlı başlangıç müşterisi kullanılamıyor; müşteri alanı boş bırakıldı.",
            "mod": MOD_ATANAN,
        }
    ozet = cari_ozet_coz(int(cid))
    if not ozet or int(ozet.get("id") or 0) <= 0:
        return {
            "ozet": bos_musteri_ozeti(),
            "uyari": "Kayıtlı başlangıç müşterisi okunamadı; müşteri alanı boş bırakıldı.",
            "mod": MOD_ATANAN,
        }
    return {"ozet": ozet, "uyari": None, "mod": MOD_ATANAN}
