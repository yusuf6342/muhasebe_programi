"""Firma kapsamında satış fiyat listesi tanımları (kod kalıcı, ad görünen)."""

from __future__ import annotations

import logging
import re
import shutil
from datetime import datetime
from pathlib import Path
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.engine import Engine

from database.database import get_session
from database.models.stok import SatisFiyatListesi
from database.stok_service import SATIS_FIYAT_ADLARI

_KOD_RE = re.compile(r"^SATI[ŞS]\s+F[İI]YATI\s+(\d+)$", re.IGNORECASE)
_log = logging.getLogger(__name__)

# Mevcut tutarlara dokunulmaz; eski satırlar MANUEL / 0 ile açılır.
_STOK_FIYAT_EK_KOLONLAR = {
    "kdv_durumu": "VARCHAR(10)",
    "hesaplama_modu": "VARCHAR(20) DEFAULT 'MANUEL' NOT NULL",
    "satis_iskonto": "NUMERIC(8, 4) DEFAULT 0 NOT NULL",
}


def _aktif_engine() -> Engine | None:
    """`from database.database import engine` stale referansını önler (firma değişimi)."""
    import database.database as dbmod

    return getattr(dbmod, "engine", None)


def _engine_db_path(eng: Engine) -> Path | None:
    try:
        raw = getattr(eng.url, "database", None)
        if raw:
            return Path(raw).resolve()
    except Exception:
        return None
    return None


def _yedek_al(db_path: Path) -> Path | None:
    try:
        from database.database import DB_DIR

        damga = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
        hedef_dir = Path(DB_DIR) / "yedekler" / f"stok_fiyat_sema_{damga}"
        hedef_dir.mkdir(parents=True, exist_ok=True)
        hedef = hedef_dir / db_path.name
        shutil.copy2(db_path, hedef)
        for ek in ("-wal", "-shm"):
            yan = Path(str(db_path) + ek)
            if yan.is_file():
                shutil.copy2(yan, Path(str(hedef) + ek))
        (hedef_dir / "README.txt").write_text(
            "stok_fiyatlari hesaplama_modu migration öncesi yedek.\n"
            f"Kaynak: {db_path}\n"
            "Tutarlar yeniden hesaplanmaz; eksik kolonlar MANUEL/0.\n",
            encoding="utf-8",
        )
        return hedef
    except OSError as exc:
        _log.exception("stok_fiyat şema yedeği alınamadı: %s", exc)
        return None


def stok_fiyat_schemasini_guncelle(eng: Engine | None = None) -> dict[str, Any]:
    """Eksik stok_fiyatlari kolonlarını ekler; fiyat tutarlarını değiştirmez. Idempotent."""
    from sqlalchemy import inspect, text

    eng = eng or _aktif_engine()
    if eng is None:
        return {"yapildi": False, "neden": "engine_yok"}

    insp = inspect(eng)
    if not insp.has_table("stok_fiyatlari"):
        return {"yapildi": False, "neden": "tablo_yok"}

    mevcut = {s["name"] for s in insp.get_columns("stok_fiyatlari")}
    eksik = {a: t for a, t in _STOK_FIYAT_EK_KOLONLAR.items() if a not in mevcut}
    if not eksik:
        return {"yapildi": False, "neden": "zaten_guncel", "kolonlar": sorted(mevcut)}

    db_path = _engine_db_path(eng)
    yedek = _yedek_al(db_path) if db_path and db_path.is_file() else None

    with eng.begin() as conn:
        from database.dialect_utils import kolon_adlari

        canli = set(kolon_adlari(conn, "stok_fiyatlari"))
        for alan, tip in _STOK_FIYAT_EK_KOLONLAR.items():
            if alan in canli:
                continue
            conn.execute(text(f'ALTER TABLE "stok_fiyatlari" ADD COLUMN "{alan}" {tip}'))
        conn.execute(
            text(
                "UPDATE stok_fiyatlari SET hesaplama_modu = 'MANUEL' "
                "WHERE hesaplama_modu IS NULL OR TRIM(hesaplama_modu) = ''"
            )
        )
        conn.execute(
            text("UPDATE stok_fiyatlari SET satis_iskonto = 0 WHERE satis_iskonto IS NULL")
        )

    yeni = {s["name"] for s in inspect(eng).get_columns("stok_fiyatlari")}
    return {
        "yapildi": True,
        "eklenen": sorted(eksik.keys()),
        "yedek": str(yedek) if yedek else None,
        "db": str(db_path) if db_path else None,
        "kolonlar": sorted(yeni),
    }


def _kod_normalize(kod: str | None) -> str:
    return (kod or "").strip().upper()


def _dict(row: SatisFiyatListesi) -> dict[str, Any]:
    return {
        "id": int(row.id),
        "kod": row.kod,
        "ad": row.ad,
        "sira_no": int(row.sira_no or 0),
        "aktif": bool(row.aktif),
    }


class SatisFiyatListesiService:
    # Hangi SQLAlchemy engine kimliği için şema hazır (firma DB değişince yeniden)
    _hazir_engine_id: int | None = None

    @classmethod
    def ensure_schema(cls, eng: Engine | None = None) -> None:
        eng = eng or _aktif_engine()
        if eng is None:
            return
        eng_id = id(eng)
        if cls._hazir_engine_id == eng_id:
            try:
                from sqlalchemy import inspect

                if inspect(eng).has_table("stok_fiyatlari"):
                    sutunlar = {s["name"] for s in inspect(eng).get_columns("stok_fiyatlari")}
                    if "hesaplama_modu" in sutunlar and "satis_iskonto" in sutunlar:
                        SatisFiyatListesi.__table__.create(bind=eng, checkfirst=True)
                        return
            except Exception:
                _log.exception("satis_fiyat şema doğrulama")
            cls._hazir_engine_id = None

        try:
            sonuc = stok_fiyat_schemasini_guncelle(eng)
            if sonuc.get("yapildi"):
                _log.info("stok_fiyatlari şema güncellendi: %s", sonuc)
            SatisFiyatListesi.__table__.create(bind=eng, checkfirst=True)
            cls.varsayilanlari_seed()
            cls._hazir_engine_id = eng_id
        except Exception:
            cls._hazir_engine_id = None
            _log.exception(
                "satis_fiyat / stok_fiyatlari şema güncellemesi başarısız (db=%s)",
                _engine_db_path(eng),
            )
            raise

    @classmethod
    def varsayilanlari_seed(cls) -> None:
        with get_session() as session:
            mevcut = {
                _kod_normalize(r.kod): r
                for r in session.scalars(select(SatisFiyatListesi)).all()
            }
            for i, kod in enumerate(SATIS_FIYAT_ADLARI, start=1):
                if _kod_normalize(kod) in mevcut:
                    continue
                session.add(
                    SatisFiyatListesi(kod=kod, ad=kod, sira_no=i, aktif=True)
                )
            session.flush()

    @classmethod
    def listele(cls, *, aktif_only: bool = False) -> list[dict[str, Any]]:
        cls.ensure_schema()
        with get_session() as session:
            q = select(SatisFiyatListesi).order_by(
                SatisFiyatListesi.sira_no, SatisFiyatListesi.id
            )
            if aktif_only:
                q = q.where(SatisFiyatListesi.aktif.is_(True))
            return [_dict(r) for r in session.scalars(q).all()]

    @classmethod
    def kodlar(cls, *, aktif_only: bool = True) -> list[str]:
        return [r["kod"] for r in cls.listele(aktif_only=aktif_only)]

    @classmethod
    def gorunen_ad(cls, kod: str | None) -> str:
        k = (kod or "").strip()
        if not k:
            return ""
        try:
            cls.ensure_schema()
            with get_session() as session:
                row = session.scalar(
                    select(SatisFiyatListesi).where(SatisFiyatListesi.kod == k)
                )
                if row is None:
                    # case-insensitive
                    for r in session.scalars(select(SatisFiyatListesi)).all():
                        if _kod_normalize(r.kod) == _kod_normalize(k):
                            return r.ad or r.kod
                    return k
                return row.ad or row.kod
        except Exception:
            return k

    @classmethod
    def ad_haritasi(cls, *, aktif_only: bool = False) -> dict[str, str]:
        return {r["kod"]: r["ad"] for r in cls.listele(aktif_only=aktif_only)}

    @classmethod
    def _sonraki_kod(cls, session) -> str:
        max_n = 0
        for r in session.scalars(select(SatisFiyatListesi)).all():
            m = _KOD_RE.match((r.kod or "").strip())
            if m:
                max_n = max(max_n, int(m.group(1)))
        for kod in SATIS_FIYAT_ADLARI:
            m = _KOD_RE.match(kod)
            if m:
                max_n = max(max_n, int(m.group(1)))
        return f"SATIŞ FİYATI {max_n + 1}"

    @classmethod
    def ekle(cls, ad: str) -> dict[str, Any]:
        cls.ensure_schema()
        ad = (ad or "").strip()
        if not ad:
            raise ValueError("Liste adı zorunludur.")
        with get_session() as session:
            kod = cls._sonraki_kod(session)
            max_sira = session.scalar(select(func.max(SatisFiyatListesi.sira_no))) or 0
            row = SatisFiyatListesi(
                kod=kod, ad=ad, sira_no=int(max_sira) + 1, aktif=True
            )
            session.add(row)
            session.flush()
            return _dict(row)

    @classmethod
    def yeniden_adlandir(cls, kod: str, yeni_ad: str) -> dict[str, Any]:
        cls.ensure_schema()
        yeni_ad = (yeni_ad or "").strip()
        if not yeni_ad:
            raise ValueError("Yeni ad zorunludur.")
        with get_session() as session:
            row = session.scalar(
                select(SatisFiyatListesi).where(SatisFiyatListesi.kod == kod)
            )
            if row is None:
                raise ValueError(f"Liste bulunamadı: {kod}")
            row.ad = yeni_ad
            session.flush()
            return _dict(row)

    @classmethod
    def sira_ayarla(cls, kodlar_sirali: list[str]) -> None:
        """Verilen kod sırasına göre sira_no günceller (1..n)."""
        cls.ensure_schema()
        with get_session() as session:
            rows = {
                r.kod: r
                for r in session.scalars(select(SatisFiyatListesi)).all()
            }
            for i, kod in enumerate(kodlar_sirali, start=1):
                if kod in rows:
                    rows[kod].sira_no = i
            session.flush()

    @classmethod
    def bagli_cariler(cls, kod: str) -> list[dict[str, Any]]:
        """Bu listeyi varsayılan satış listesi olarak kullanan cariler."""
        from database.models.cari import Cari

        k = (kod or "").strip()
        with get_session() as session:
            cariler = session.scalars(
                select(Cari).where(Cari.satis_fiyat_listesi == k)
            ).all()
            # case-insensitive yedek
            if not cariler:
                hepsi = session.scalars(
                    select(Cari).where(Cari.satis_fiyat_listesi.is_not(None))
                ).all()
                cariler = [
                    c
                    for c in hepsi
                    if _kod_normalize(c.satis_fiyat_listesi) == _kod_normalize(k)
                ]
            return [
                {
                    "id": int(c.id),
                    "kod": c.cari_kodu,
                    "unvan": c.unvan,
                    "satis_fiyat_listesi": c.satis_fiyat_listesi,
                }
                for c in cariler
            ]

    @classmethod
    def stok_fiyat_adet(cls, kod: str) -> int:
        from database.models.stok import StokFiyati

        k = (kod or "").strip()
        with get_session() as session:
            return int(
                session.scalar(
                    select(func.count())
                    .select_from(StokFiyati)
                    .where(StokFiyati.fiyat_adi == k)
                )
                or 0
            )

    @classmethod
    def pasife_al(cls, kod: str) -> dict[str, Any]:
        cls.ensure_schema()
        with get_session() as session:
            row = session.scalar(
                select(SatisFiyatListesi).where(SatisFiyatListesi.kod == kod)
            )
            if row is None:
                raise ValueError(f"Liste bulunamadı: {kod}")
            row.aktif = False
            session.flush()
            return _dict(row)

    @classmethod
    def aktifle(cls, kod: str) -> dict[str, Any]:
        cls.ensure_schema()
        with get_session() as session:
            row = session.scalar(
                select(SatisFiyatListesi).where(SatisFiyatListesi.kod == kod)
            )
            if row is None:
                raise ValueError(f"Liste bulunamadı: {kod}")
            row.aktif = True
            session.flush()
            return _dict(row)

    @classmethod
    def cari_liste_degistir(cls, cari_id: int, yeni_kod: str) -> None:
        from database.models.cari import Cari

        yeni_kod = (yeni_kod or "").strip()
        if not yeni_kod:
            raise ValueError("Yeni liste seçilmelidir.")
        with get_session() as session:
            liste = session.scalar(
                select(SatisFiyatListesi).where(SatisFiyatListesi.kod == yeni_kod)
            )
            if liste is None or not liste.aktif:
                raise ValueError("Hedef liste aktif değil.")
            cari = session.get(Cari, int(cari_id))
            if cari is None:
                raise ValueError("Cari bulunamadı.")
            cari.satis_fiyat_listesi = yeni_kod
            session.flush()

    @classmethod
    def sil(cls, kod: str, *, zorla_pasif: bool = True) -> dict[str, Any]:
        """Kullanımda olmayan listeyi siler; kullanımda ise pasife alır.

        Dönüş: {aksiyon: 'silindi'|'pasif', kod, bagli_cari_adet, stok_fiyat_adet}
        """
        cls.ensure_schema()
        bagli = cls.bagli_cariler(kod)
        stok_adet = cls.stok_fiyat_adet(kod)
        if bagli or stok_adet:
            if not zorla_pasif:
                raise ValueError(
                    f"«{kod}» kullanılıyor (cari={len(bagli)}, stok fiyat={stok_adet}); "
                    "silinemez, pasife alınabilir."
                )
            sonuc = cls.pasife_al(kod)
            sonuc["aksiyon"] = "pasif"
            sonuc["bagli_cari_adet"] = len(bagli)
            sonuc["stok_fiyat_adet"] = stok_adet
            sonuc["bagli_cariler"] = bagli
            return sonuc
        with get_session() as session:
            row = session.scalar(
                select(SatisFiyatListesi).where(SatisFiyatListesi.kod == kod)
            )
            if row is None:
                raise ValueError(f"Liste bulunamadı: {kod}")
            bilgi = _dict(row)
            session.delete(row)
            session.flush()
            bilgi["aksiyon"] = "silindi"
            bilgi["bagli_cari_adet"] = 0
            bilgi["stok_fiyat_adet"] = 0
            return bilgi


def liste_bagli_satis_fiyati(liste_fiyat, satis_iskonto):
    """Satış = Liste × (1 − iskonto/100). Alış iskontoları kullanılmaz."""
    from decimal import ROUND_HALF_UP, Decimal

    from database.satis_siparisi_service import decimal

    liste = decimal(liste_fiyat, "Liste fiyatı", None)
    if liste is None:
        raise ValueError("Liste fiyatı boş veya geçersiz.")
    oran = decimal(satis_iskonto or "0", "Satış iskontosu", Decimal("0"))
    if oran < 0 or oran > 100:
        raise ValueError("Satış iskontosu 0–100 arasında olmalıdır.")
    return (liste * (Decimal("1") - oran / Decimal("100"))).quantize(
        Decimal("0.0001"), rounding=ROUND_HALF_UP
    )
