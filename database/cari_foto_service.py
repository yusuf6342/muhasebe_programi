"""Cari ve yetkili fotoğrafları — firma veritabanında küçültülmüş görüntü + önizleme.

Kaynak dosya yalnız okunur; kayıt sonrası geçici/masaüstü dosyasına bağımlılık kalmaz.
Görüntü firma veritabanı içinde saklandığından firma yedeği/geri yüklemesi fotoğrafları da kapsar.
"""

from __future__ import annotations

import io
from datetime import datetime
from pathlib import Path
from typing import Any

from sqlalchemy import select

from database.access import yazma_zorunlu
from database.database import get_session
from database.models.cari import Cari, CariFotograf, CariYetkili

CARI = "CARI"
YETKILI = "YETKILI"
SAHIP_TURLERI = (CARI, YETKILI)

MAX_KENAR = 800
KUCUK_KENAR = 256
MAX_DOSYA_BAYT = 25 * 1024 * 1024
DESTEKLENEN = {"JPEG": "JPG", "PNG": "PNG", "BMP": "BMP", "WEBP": "WEBP", "GIF": "GIF"}
DOSYA_FILTRESI = [("Görüntü dosyaları", "*.jpg *.jpeg *.png *.bmp *.webp *.gif"), ("Tüm dosyalar", "*.*")]


def _kodla(img, *, seffaf: bool) -> tuple[bytes, str]:
    tampon = io.BytesIO()
    if seffaf:
        img.save(tampon, format="PNG", optimize=True)
        return tampon.getvalue(), "PNG"
    img.convert("RGB").save(tampon, format="JPEG", quality=85, optimize=True)
    return tampon.getvalue(), "JPEG"


def goruntu_hazirla(kaynak: str | Path | bytes) -> dict[str, Any]:
    """Dosyayı doğrular, yönünü düzeltir, küçültür. Hata → ValueError (veritabanına dokunmaz)."""
    from PIL import Image, ImageOps, UnidentifiedImageError

    if isinstance(kaynak, (bytes, bytearray)):
        ham = bytes(kaynak)
        ad = None
    else:
        yol = Path(kaynak)
        if not yol.is_file():
            raise ValueError(f"Dosya bulunamadı: {yol}")
        if yol.stat().st_size > MAX_DOSYA_BAYT:
            raise ValueError("Dosya çok büyük (en fazla 25 MB).")
        ham = yol.read_bytes()
        ad = yol.name[:200]
    if not ham:
        raise ValueError("Dosya boş.")
    try:
        with Image.open(io.BytesIO(ham)) as deneme:
            bicim = (deneme.format or "").upper()
            deneme.verify()
        if bicim not in DESTEKLENEN:
            raise ValueError(
                f"Desteklenmeyen görüntü biçimi ({bicim or 'bilinmiyor'}). JPG veya PNG seçin."
            )
        with Image.open(io.BytesIO(ham)) as img:
            img.load()
            img = ImageOps.exif_transpose(img)
            seffaf = img.mode in ("RGBA", "LA", "P") and (
                img.mode != "P" or "transparency" in img.info
            )
            img = img.convert("RGBA" if seffaf else "RGB")
            img.thumbnail((MAX_KENAR, MAX_KENAR), Image.Resampling.LANCZOS)
            veri, cikti = _kodla(img, seffaf=seffaf)
            genislik, yukseklik = img.size
            kucuk_img = img.copy()
            kucuk_img.thumbnail((KUCUK_KENAR, KUCUK_KENAR), Image.Resampling.LANCZOS)
            kucuk, _ = _kodla(kucuk_img, seffaf=seffaf)
    except ValueError:
        raise
    except (UnidentifiedImageError, OSError, SyntaxError, Image.DecompressionBombError) as hata:
        raise ValueError(f"Görüntü okunamadı; dosya bozuk veya desteklenmiyor ({hata}).") from None
    return {
        "bicim": cikti,
        "genislik": int(genislik),
        "yukseklik": int(yukseklik),
        "veri": veri,
        "kucuk": kucuk,
        "kaynak_adi": ad,
    }


def _sahip_cari_id(session, sahip_turu: str, sahip_id: int) -> int:
    if sahip_turu == CARI:
        cari = session.get(Cari, int(sahip_id))
        if cari is None or getattr(cari, "is_deleted", False):
            raise ValueError("Cari kart bulunamadı.")
        return int(cari.id)
    if sahip_turu == YETKILI:
        y = session.get(CariYetkili, int(sahip_id))
        if y is None or y.is_deleted:
            raise ValueError("Yetkili bulunamadı.")
        return int(y.cari_id)
    raise ValueError("Geçersiz fotoğraf sahibi.")


def _yetki(sahip_turu: str) -> None:
    if sahip_turu == YETKILI:
        yazma_zorunlu("cari_yetkili_duzenle", "cari_duzenleme")
    else:
        yazma_zorunlu("cari_duzenleme")


class CariFotoService:
    CARI = CARI
    YETKILI = YETKILI

    @staticmethod
    def kaydet(sahip_turu: str, sahip_id: int, kaynak, *, hazir: dict | None = None) -> dict[str, Any]:
        """Yükle / değiştir. ``hazir`` verilirse (``goruntu_hazirla`` sonucu) dosya tekrar okunmaz."""
        _yetki(sahip_turu)
        foto = hazir or goruntu_hazirla(kaynak)
        with get_session() as session:
            cari_id = _sahip_cari_id(session, sahip_turu, sahip_id)
            kayit = session.scalar(select(CariFotograf).where(
                CariFotograf.sahip_turu == sahip_turu, CariFotograf.sahip_id == int(sahip_id)
            ))
            if kayit is None:
                kayit = CariFotograf(sahip_turu=sahip_turu, sahip_id=int(sahip_id))
                session.add(kayit)
            kayit.cari_id = cari_id
            for alan in ("bicim", "genislik", "yukseklik", "veri", "kucuk", "kaynak_adi"):
                setattr(kayit, alan, foto.get(alan))
            kayit.guncelleme = datetime.now()
            session.flush()
            return {"id": int(kayit.id), "cari_id": cari_id, "genislik": kayit.genislik,
                    "yukseklik": kayit.yukseklik}

    @staticmethod
    def kaldir(sahip_turu: str, sahip_id: int) -> bool:
        _yetki(sahip_turu)
        with get_session() as session:
            kayit = session.scalar(select(CariFotograf).where(
                CariFotograf.sahip_turu == sahip_turu, CariFotograf.sahip_id == int(sahip_id)
            ))
            if kayit is None:
                return False
            session.delete(kayit)
            return True

    @staticmethod
    def getir(sahip_turu: str, sahip_id: int, *, buyuk: bool = False,
              cari_id: int | None = None) -> bytes | None:
        """Önizleme (varsayılan) veya büyük görüntü. ``cari_id`` verilirse başka cariye ait görüntü dönmez."""
        if not sahip_id:
            return None
        kolon = CariFotograf.veri if buyuk else CariFotograf.kucuk
        with get_session() as session:
            satir = session.execute(
                select(kolon, CariFotograf.cari_id).where(
                    CariFotograf.sahip_turu == sahip_turu, CariFotograf.sahip_id == int(sahip_id)
                )
            ).first()
        if satir is None:
            return None
        if cari_id is not None and int(satir[1]) != int(cari_id):
            return None
        return bytes(satir[0])

    @staticmethod
    def fotolu_sahipler(sahip_turu: str, ids) -> set[int]:
        ids = [int(i) for i in ids if i]
        if not ids:
            return set()
        with get_session() as session:
            return {
                int(i) for i in session.scalars(select(CariFotograf.sahip_id).where(
                    CariFotograf.sahip_turu == sahip_turu, CariFotograf.sahip_id.in_(ids)
                )).all()
            }
