"""Birim / liste / net fiyat gösterimi — görünüm ayarı; kayıt hassasiyetini değiştirmez.

Varsayılan: kesirli fiyatlar 4 hane (sıfırla tamamla); tam sayı ondalıksız.
Türkçe: ondalık virgül, binlik nokta. Miktar/kur/yüzde/bakiye/toplam bu modülde değil.
"""
from __future__ import annotations

import json
import logging
import os
from copy import deepcopy
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from pathlib import Path
from typing import Any, Callable

_LOG = logging.getLogger(__name__)

SIFIR = Decimal("0")
VARSAYILAN_AYAR: dict[str, Any] = {
    "ondalik_basamak": 4,
    "tam_sayida_ondalik": False,
    "sifirla_tamamla": True,
    "binlik_ayirici": True,
}

_ONIZLEME_ORNEKLER = (
    Decimal("100"),
    Decimal("100.00"),
    Decimal("12.5"),
    Decimal("0.3"),
    Decimal("0.301644"),
    Decimal("1.0734696"),
    Decimal("-12.5"),
)

_cache: dict[str, Any] | None = None
_dinleyiciler: list[Callable[[], None]] = []


def _ayar_klasoru() -> Path:
    local = (os.environ.get("LOCALAPPDATA") or "").strip()
    if local:
        p = Path(local) / "MuhasebeProgrami" / "ayarlar"
    else:
        p = Path.home() / ".cin_muhasebe" / "ayarlar"
    p.mkdir(parents=True, exist_ok=True)
    return p


def _firma_anahtar() -> str:
    try:
        from database.session_manager import oturum

        kod = (getattr(oturum, "firma_kodu", None) or "genel").strip() or "genel"
    except Exception:
        kod = "genel"
    return "".join(c if c.isalnum() or c in "-_" else "_" for c in kod)


def ayar_dosyasi() -> Path:
    return _ayar_klasoru() / f"fiyat_gorunum_{_firma_anahtar()}.json"


def _normalize_ayar(ham: dict | None) -> dict[str, Any]:
    a = dict(VARSAYILAN_AYAR)
    if not isinstance(ham, dict):
        return a
    try:
        n = int(ham.get("ondalik_basamak", a["ondalik_basamak"]))
    except (TypeError, ValueError):
        n = 4
    a["ondalik_basamak"] = max(0, min(8, n))
    a["tam_sayida_ondalik"] = bool(ham.get("tam_sayida_ondalik", a["tam_sayida_ondalik"]))
    a["sifirla_tamamla"] = bool(ham.get("sifirla_tamamla", a["sifirla_tamamla"]))
    a["binlik_ayirici"] = bool(ham.get("binlik_ayirici", a["binlik_ayirici"]))
    return a


def ayarlari_yukle(*, zorla: bool = False) -> dict[str, Any]:
    global _cache
    if _cache is not None and not zorla:
        return dict(_cache)
    yol = ayar_dosyasi()
    ham = None
    if yol.is_file():
        try:
            ham = json.loads(yol.read_text(encoding="utf-8"))
        except Exception as exc:
            _LOG.warning("fiyat görünüm ayarı okunamadı: %s", exc)
    _cache = _normalize_ayar(ham)
    return dict(_cache)


def ayarlari_kaydet(ayar: dict[str, Any]) -> dict[str, Any]:
    global _cache
    temiz = _normalize_ayar(ayar)
    yol = ayar_dosyasi()
    yol.write_text(json.dumps(temiz, ensure_ascii=False, indent=2), encoding="utf-8")
    _cache = dict(temiz)
    for fn in list(_dinleyiciler):
        try:
            fn()
        except Exception:
            _LOG.exception("fiyat görünüm dinleyici")
    return dict(temiz)


def varsayilanlara_don() -> dict[str, Any]:
    return ayarlari_kaydet(dict(VARSAYILAN_AYAR))


def dinleyici_ekle(fn: Callable[[], None]) -> None:
    if fn not in _dinleyiciler:
        _dinleyiciler.append(fn)


def dinleyici_cikar(fn: Callable[[], None]) -> None:
    try:
        _dinleyiciler.remove(fn)
    except ValueError:
        pass


def onizleme_ornekleri(ayar: dict | None = None) -> list[tuple[str, str]]:
    """(kaynak_metin, görünen) listesi."""
    a = _normalize_ayar(ayar or ayarlari_yukle())
    sonuc = []
    for d in _ONIZLEME_ORNEKLER:
        kaynak = format(d, "f").rstrip("0").rstrip(".") if "." in format(d, "f") else format(d, "f")
        kaynak_tr = kaynak.replace(".", ",")
        sonuc.append((kaynak_tr, fiyat_goster(d, ayar=a)))
    return sonuc


def _decimal(deger) -> Decimal | None:
    if deger is None:
        return None
    if isinstance(deger, Decimal):
        return deger
    if isinstance(deger, (int, float)):
        return Decimal(str(deger))
    metin = str(deger).strip()
    if not metin or metin in {"—", "-", "–"}:
        return None
    return fiyat_ayristir(metin)


def fiyat_ayristir(metin) -> Decimal | None:
    """Kullanıcı/TR metnini Decimal'e çevir. Boş → None (sıfırdan ayırt)."""
    if metin is None:
        return None
    s = str(metin).strip().replace("TL", "").replace("₺", "").strip()
    if not s:
        return None
    s = s.replace("\u2212", "-").replace("−", "-")
    # Binlik nokta + ondalık virgül: 1.234,56
    if "," in s and "." in s:
        if s.rfind(",") > s.rfind("."):
            s = s.replace(".", "").replace(",", ".")
        else:
            s = s.replace(",", "")
    elif "," in s:
        s = s.replace(",", ".")
    try:
        return Decimal(s)
    except (InvalidOperation, ValueError):
        return None


def _binlik_tr(tam_str: str) -> str:
    negatif = tam_str.startswith("-")
    t = tam_str[1:] if negatif else tam_str
    if not t.isdigit():
        return tam_str
    parcalar = []
    while t:
        parcalar.append(t[-3:])
        t = t[:-3]
    birlesik = ".".join(reversed(parcalar))
    return f"-{birlesik}" if negatif else birlesik


def fiyat_goster(deger, *, ayar: dict | None = None, bos: str = "") -> str:
    """Görünüm metni — DB/hesap değerini değiştirmez."""
    d = _decimal(deger)
    if d is None:
        return bos
    if d.is_nan() or d.is_infinite():
        return bos
    # −0 → 0
    if d == 0:
        d = SIFIR

    a = _normalize_ayar(ayar or ayarlari_yukle())
    n = int(a["ondalik_basamak"])
    tam_ondalik = bool(a["tam_sayida_ondalik"])
    tamamla = bool(a["sifirla_tamamla"])
    binlik = bool(a["binlik_ayirici"])

    integral = d == d.to_integral_value()
    if integral and not tam_ondalik:
        tam = format(int(d), "d")
        return _binlik_tr(tam) if binlik else tam

    if n <= 0:
        q = d.quantize(Decimal("1"), rounding=ROUND_HALF_UP)
        tam = format(int(q), "d")
        return _binlik_tr(tam) if binlik else tam

    q = Decimal("1").scaleb(-n)  # 10^-n
    yuvar = d.quantize(q, rounding=ROUND_HALF_UP)
    if yuvar == 0:
        yuvar = SIFIR

    # Tekrar tam sayı olduysa ve tam_sayida_ondalik kapalıysa ondalıksız
    if yuvar == yuvar.to_integral_value() and not tam_ondalik:
        tam = format(int(yuvar), "d")
        return _binlik_tr(tam) if binlik else tam

    isaret = "-" if yuvar < 0 else ""
    abs_y = abs(yuvar)
    s = f"{abs_y:f}"
    if "." in s:
        tam_k, kes = s.split(".", 1)
    else:
        tam_k, kes = s, ""
    if tamamla:
        kes = (kes + ("0" * n))[:n]
    else:
        kes = kes.rstrip("0")
        if len(kes) > n:
            # zaten quantize ile n; güvenlik
            kes = kes[:n]
    tam_g = _binlik_tr(tam_k) if binlik else tam_k
    if not kes:
        return f"{isaret}{tam_g}"
    return f"{isaret}{tam_g},{kes}"


def fiyat_kayit_degeri(girilen_metin, onceki_deger) -> Decimal | None:
    """Hücreden çıkışta: görünüm değişmediyse eski tam hassasiyeti koru."""
    if girilen_metin is None or str(girilen_metin).strip() == "":
        return None
    onceki = _decimal(onceki_deger)
    giris_norm = str(girilen_metin).strip()
    if onceki is not None and fiyat_goster(onceki) == fiyat_goster(giris_norm):
        return onceki
    # Kullanıcı görünümüyle aynı metni yazdıysa da koru
    if onceki is not None and giris_norm == fiyat_goster(onceki):
        return onceki
    return fiyat_ayristir(girilen_metin)


def fiyat_goster_pb(deger, pb: str = "TRY", *, ayar: dict | None = None, bos: str = "") -> str:
    """Birim fiyat + para birimi etiketi (çıktı/önizleme)."""
    s = fiyat_goster(deger, ayar=ayar, bos=bos)
    if not s:
        return s
    kod = (pb or "TRY").upper()
    if kod in ("TRY", "TL"):
        return f"{s} TL"
    return f"{s} {kod}"


def excel_fiyat_number_format(ayar: dict | None = None) -> str:
    """openpyxl number_format — değer sayısal kalır."""
    a = _normalize_ayar(ayar or ayarlari_yukle())
    n = int(a["ondalik_basamak"])
    if n <= 0:
        return "#,##0" if a["binlik_ayirici"] else "0"
    zeros = "0" * n
    if a["binlik_ayirici"]:
        return f"#,##0.{zeros}"
    return f"0.{zeros}"


def ayar_kopyasi() -> dict[str, Any]:
    return deepcopy(ayarlari_yukle())
