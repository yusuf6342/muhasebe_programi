"""Firma varsayılan KDV oranı + satır KDV belirleme (Decimal).

Öncelik: kaynak belge oranı → stok kartı oranı → firma varsayılanı → %20.
Yüzde işareti yalnızca UI sunumudur; DB'ye sayısal oran yazılır.
"""

from __future__ import annotations

from decimal import Decimal, InvalidOperation
from typing import Any

from database.models.stok import KDV_ORANLARI, VARSAYILAN_KDV_ORANI

# Ayar ekranı seçenekleri (talimat); satır düzenlemede tüm KDV_ORANLARI kullanılır
FIRMA_VARSAYILAN_KDV_SECENEKLERI = ("0", "1", "10", "20")
AYAR_ANAHTAR_ON_EK = "varsayilan_kdv_orani"


def _d(deger, varsayilan: Decimal = Decimal("0")) -> Decimal:
    if deger is None or deger == "":
        return varsayilan
    if isinstance(deger, Decimal):
        return deger
    try:
        return Decimal(str(deger).replace("%", "").strip().replace(",", "."))
    except (InvalidOperation, ValueError):
        return varsayilan


def kdv_oran_metni(oran) -> str:
    """UI gösterimi: %0, %1, %10, %20 (kesilmeden).

    Not: str.rstrip('0') kullanma — '20' yanlışlıkla '2' olur.
    """
    d = _d(oran, Decimal("0"))
    if d == d.to_integral_value():
        metin = str(int(d))
    else:
        metin = format(d, "f").rstrip("0").rstrip(".") or "0"
    return f"%{metin}"


def satir_kdv_metin_sayisal(oran) -> str:
    """Form alanları için yüzdesiz sayı metni."""
    d = _d(oran, Decimal("0"))
    if d == d.to_integral_value():
        return str(int(d))
    return format(d, "f").rstrip("0").rstrip(".") or "0"


def kdv_secenek_etiketleri(secenekler=None) -> list[str]:
    kaynak = secenekler or KDV_ORANLARI
    return [kdv_oran_metni(x) for x in kaynak]


def kdv_orani_dogrula(oran, *, izinli=None) -> Decimal:
    """İzin verilen oran değilse ValueError (sessizce 0'a çevirmez)."""
    if oran is None or (isinstance(oran, str) and not str(oran).strip()):
        raise ValueError("KDV oranı boş olamaz.")
    ham = str(oran).replace("%", "").strip().replace(",", ".")
    try:
        deger = Decimal(ham)
    except (InvalidOperation, ValueError) as exc:
        raise ValueError("Geçerli bir KDV oranı girin.") from exc
    if deger < 0 or deger > 100:
        raise ValueError("KDV oranı 0–100 arasında olmalıdır.")
    izin = tuple(izinli) if izinli is not None else KDV_ORANLARI
    izin_d = {_d(x) for x in izin}
    # Tam eşleşme veya tamsayı eşdeğer (20 == 20.0)
    if deger not in izin_d and deger.to_integral_value() not in izin_d:
        liste = ", ".join(kdv_oran_metni(x) for x in izin)
        raise ValueError(f"İzin verilen KDV oranları: {liste}")
    return deger


_SCHEMA_HAZIR = False


def companies_kdv_schema_guncelle(engine=None) -> None:
    """companies.varsayilan_kdv_orani soft ALTER (idempotent). Bootstrap'ta erken çağrılmalı."""
    global _SCHEMA_HAZIR
    if _SCHEMA_HAZIR and engine is None:
        return
    from sqlalchemy import inspect, text

    from database.database import system_engine

    eng = engine or system_engine
    if eng is None:
        return
    try:
        insp = inspect(eng)
        if not insp.has_table("companies"):
            return
        cols = {c["name"] for c in insp.get_columns("companies")}
    except Exception:
        return
    with eng.begin() as conn:
        if "varsayilan_kdv_orani" not in cols:
            conn.execute(
                text(
                    'ALTER TABLE "companies" '
                    'ADD COLUMN "varsayilan_kdv_orani" NUMERIC(7, 2) DEFAULT 20'
                )
            )
        conn.execute(
            text(
                'UPDATE "companies" SET varsayilan_kdv_orani = 20 '
                "WHERE varsayilan_kdv_orani IS NULL"
            )
        )
    _SCHEMA_HAZIR = True


def _schema_hazirla() -> None:
    companies_kdv_schema_guncelle()


def firma_varsayilan_kdv_orani(company_id: int | None = None) -> Decimal:
    """Aktif (veya verilen) firmanın varsayılan KDV oranı."""
    _schema_hazirla()
    from database.database import get_system_session
    from database.session_manager import oturum
    from database.system.models import Company

    cid = company_id
    if cid is None:
        cid = getattr(oturum, "company_id", None)
    if not cid:
        return Decimal(str(VARSAYILAN_KDV_ORANI))
    try:
        with get_system_session() as session:
            f = session.get(Company, int(cid))
            if f is None:
                return Decimal(str(VARSAYILAN_KDV_ORANI))
            ham = getattr(f, "varsayilan_kdv_orani", None)
            if ham is None or ham == "":
                return Decimal(str(VARSAYILAN_KDV_ORANI))
            return _d(ham, Decimal(str(VARSAYILAN_KDV_ORANI)))
    except Exception:
        return Decimal(str(VARSAYILAN_KDV_ORANI))


def firma_varsayilan_kdv_ayarla(
    oran,
    *,
    company_id: int | None = None,
) -> Decimal:
    """Firma varsayılan KDV oranını kaydet. Dönüş: kaydedilen Decimal."""
    _schema_hazirla()
    deger = kdv_orani_dogrula(oran, izinli=FIRMA_VARSAYILAN_KDV_SECENEKLERI)
    from database.database import get_system_session
    from database.session_manager import oturum
    from database.system.models import Company

    cid = company_id if company_id is not None else getattr(oturum, "company_id", None)
    if not cid:
        raise ValueError("Aktif firma seçili değil; KDV varsayılanı kaydedilemedi.")
    with get_system_session() as session:
        f = session.get(Company, int(cid))
        if f is None:
            raise ValueError("Firma bulunamadı.")
        f.varsayilan_kdv_orani = deger
        session.commit()
    return deger


def satir_kdv_belirle(
    *,
    stok_kdv: Any = None,
    kaynak_kdv: Any = None,
    company_id: int | None = None,
) -> Decimal:
    """Yeni satır için KDV oranı.

    1) Kaynak belgede oran varsa onu koru
    2) Stok kartında oran varsa onu kullan
    3) Aksi halde firma varsayılanı
    """
    if kaynak_kdv is not None and str(kaynak_kdv).strip() != "":
        return _d(kaynak_kdv, firma_varsayilan_kdv_orani(company_id))
    if stok_kdv is not None and str(stok_kdv).strip() != "":
        return _d(stok_kdv, firma_varsayilan_kdv_orani(company_id))
    return firma_varsayilan_kdv_orani(company_id)


def satir_kdv_metin(
    *,
    stok_kdv: Any = None,
    kaynak_kdv: Any = None,
    company_id: int | None = None,
) -> str:
    """Form alanları için sayısal metin (yüzdesiz): '20'."""
    d = satir_kdv_belirle(
        stok_kdv=stok_kdv, kaynak_kdv=kaynak_kdv, company_id=company_id
    )
    return satir_kdv_metin_sayisal(d)
