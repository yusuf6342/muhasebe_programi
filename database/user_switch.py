"""Aktif oturum kullanıcı değiştirme — şifre/PIN doğrulamalı."""

from __future__ import annotations

import json
import logging
import time
from datetime import datetime
from typing import Any

from sqlalchemy import inspect, select, text
from sqlalchemy.orm import selectinload

from database.database import get_system_session
from database.session_manager import oturum
from database.system.bootstrap import bilgisayar_adi, kullanici_izinlerini_yukle
from database.system.models import User
from database.system.password import hash_parola, parola_dogrula

_LOG = logging.getLogger("user_switch")

# Başarısız deneme: user_id → (count, lock_until_ts)
_FAILED: dict[int, tuple[int, float]] = {}
_MAX_FAIL = 5
_LOCK_SEC = 30


def users_pin_schema_guncelle(engine=None) -> None:
    """users.hizli_pin_hash soft ALTER (idempotent)."""
    from database.database import system_engine

    eng = engine or system_engine
    if eng is None:
        return
    insp = inspect(eng)
    if not insp.has_table("users"):
        return
    cols = {c["name"] for c in insp.get_columns("users")}
    if "hizli_pin_hash" in cols:
        return
    with eng.begin() as conn:
        conn.execute(text('ALTER TABLE "users" ADD COLUMN "hizli_pin_hash" VARCHAR(255)'))


def aktif_kullanici_secenekleri() -> list[dict[str, Any]]:
    """Oturum değişimi için aktif kullanıcı listesi (hash yok)."""
    with get_system_session() as session:
        q = (
            select(User)
            .options(selectinload(User.role), selectinload(User.companies))
            .where(User.aktif.is_(True))
            .order_by(User.ad_soyad)
        )
        sonuc = []
        cid = oturum.company_id
        for u in session.scalars(q).all():
            if u.role and u.role.kod == "YONETICI":
                pass  # yönetici her firmada görünebilir
            elif cid is not None:
                firma_idler = {uc.company_id for uc in u.companies}
                if cid not in firma_idler and u.varsayilan_firma_id != cid:
                    continue
            sonuc.append(
                {
                    "id": int(u.id),
                    "ad_soyad": u.ad_soyad,
                    "role_ad": u.role.ad if u.role else "",
                    "role_kod": u.role.kod if u.role else "",
                    "pin_tanimli": bool(getattr(u, "hizli_pin_hash", None)),
                }
            )
        return sonuc


def _lock_check(user_id: int) -> None:
    info = _FAILED.get(user_id)
    if not info:
        return
    count, until = info
    if until and time.time() < until:
        kalan = int(until - time.time()) + 1
        raise ValueError(
            f"Çok fazla hatalı deneme. Lütfen {kalan} saniye bekleyin."
        )


def _fail(user_id: int) -> None:
    count, _ = _FAILED.get(user_id, (0, 0.0))
    count += 1
    until = time.time() + _LOCK_SEC if count >= _MAX_FAIL else 0.0
    if count >= _MAX_FAIL:
        count = 0  # kilit sonrası sıfırla
    _FAILED[user_id] = (count, until)


def _clear_fail(user_id: int) -> None:
    _FAILED.pop(user_id, None)


def _audit_switch(
    *,
    basarili: bool,
    old: dict | None,
    new: dict | None,
    active_screen: str | None,
    document_type: str | None,
    document_id: int | None,
    description: str,
) -> None:
    try:
        from database.system.auth_service import AuthService

        payload = {
            "old_user_id": (old or {}).get("user_id"),
            "old_user_full_name": (old or {}).get("ad_soyad"),
            "new_user_id": (new or {}).get("user_id"),
            "new_user_full_name": (new or {}).get("ad_soyad"),
            "switch_time": datetime.now().isoformat(timespec="seconds"),
            "computer_name": bilgisayar_adi(),
            "active_screen": active_screen,
            "open_document_type": document_type,
            "open_document_id": document_id,
            "description": description,
        }
        with get_system_session() as session:
            AuthService.audit(
                session,
                "USER_SWITCH" if basarili else "USER_SWITCH_FAILED",
                modul="SESSION",
                kayit_id=str((new or old or {}).get("user_id") or ""),
                eski_deger=json.dumps(
                    {
                        "user_id": payload["old_user_id"],
                        "full_name": payload["old_user_full_name"],
                    },
                    ensure_ascii=False,
                )
                if old
                else None,
                yeni_deger=json.dumps(payload, ensure_ascii=False),
            )
            session.commit()
    except Exception as exc:
        _LOG.warning("USER_SWITCH audit yazılamadı: %s", exc)


def switch_user(
    new_user_id: int,
    credential: str,
    *,
    active_screen: str | None = None,
    document_type: str | None = None,
    document_id: int | None = None,
) -> dict[str, Any]:
    """Seçilen kullanıcının şifre veya hızlı PIN'i ile oturumu değiştir.

    credential içeriği loglanmaz. Firma/dönem korunur.
    """
    users_pin_schema_guncelle()
    if not oturum.oturum_acik:
        raise ValueError("Önce giriş yapılmalıdır.")
    uid = int(new_user_id)
    _lock_check(uid)
    cred = (credential or "").strip()
    if not cred:
        raise ValueError("Şifre veya hızlı PIN girilmelidir.")

    old_snap = {
        "user_id": oturum.user_id,
        "ad_soyad": oturum.ad_soyad,
        "kullanici_adi": oturum.kullanici_adi,
        "role_kod": oturum.role_kod,
        "role_ad": oturum.role_ad,
        "permissions": set(oturum.permissions),
    }

    with get_system_session() as session:
        kayit = session.scalar(
            select(User)
            .options(
                selectinload(User.role),
                selectinload(User.extra_permissions),
                selectinload(User.companies),
            )
            .where(User.id == uid)
        )
        if kayit is None or not kayit.aktif:
            _audit_switch(
                basarili=False,
                old=old_snap,
                new={"user_id": uid, "ad_soyad": "?"},
                active_screen=active_screen,
                document_type=document_type,
                document_id=document_id,
                description="Pasif veya bulunamayan kullanıcıya geçiş denendi.",
            )
            raise ValueError("Kullanıcı bulunamadı veya pasif.")

        pin_hash = getattr(kayit, "hizli_pin_hash", None)
        ok = parola_dogrula(cred, kayit.parola_hash)
        if not ok and pin_hash and cred.isdigit() and 4 <= len(cred) <= 6:
            ok = parola_dogrula(cred, pin_hash)
        if not ok:
            _fail(uid)
            _audit_switch(
                basarili=False,
                old=old_snap,
                new={"user_id": kayit.id, "ad_soyad": kayit.ad_soyad},
                active_screen=active_screen,
                document_type=document_type,
                document_id=document_id,
                description=(
                    f"Şifre/PIN hatalı: {old_snap.get('ad_soyad')} → {kayit.ad_soyad}"
                ),
            )
            raise ValueError("Şifre veya hızlı PIN hatalı. Kullanıcı değiştirilemedi.")

        _clear_fail(uid)
        izinler = kullanici_izinlerini_yukle(session, kayit)
        kayit.son_giris_tarihi = datetime.now()
        session.flush()
        new_snap = {
            "user_id": kayit.id,
            "ad_soyad": kayit.ad_soyad,
            "kullanici_adi": kayit.kullanici_adi,
            "role_kod": kayit.role.kod if kayit.role else "",
            "role_ad": kayit.role.ad if kayit.role else "",
            "permissions": set(izinler),
            "sifre_degistirmeli": bool(kayit.sifre_degistirmeli),
        }

    # Firma/dönem korunarak yalnızca kullanıcı alanlarını değiştir
    oturum.set_user(
        user_id=new_snap["user_id"],
        kullanici_adi=new_snap["kullanici_adi"],
        ad_soyad=new_snap["ad_soyad"],
        role_kod=new_snap["role_kod"],
        role_ad=new_snap["role_ad"],
        permissions=new_snap["permissions"],
        sifre_degistirmeli=new_snap["sifre_degistirmeli"],
    )
    _audit_switch(
        basarili=True,
        old=old_snap,
        new=new_snap,
        active_screen=active_screen,
        document_type=document_type,
        document_id=document_id,
        description=(
            f"Aktif kullanıcı {old_snap.get('ad_soyad')}’dan "
            f"{new_snap.get('ad_soyad')}’ya değiştirildi."
        ),
    )
    oturum.notify_user_changed(old_snap, new_snap)
    return new_snap


def pin_ayarla(user_id: int, pin: str, *, eski_pin_veya_sifre: str | None = None) -> None:
    """4–6 haneli PIN hash’ler. Yönetici sıfırlayabilir; kullanıcı kendi şifresiyle değiştirir."""
    users_pin_schema_guncelle()
    pin = (pin or "").strip()
    if not (pin.isdigit() and 4 <= len(pin) <= 6):
        raise ValueError("Hızlı PIN 4–6 haneli rakam olmalıdır.")
    with get_system_session() as session:
        user = session.get(User, int(user_id))
        if not user:
            raise ValueError("Kullanıcı bulunamadı.")
        self_ok = oturum.user_id == user.id
        admin_ok = oturum.role_kod == "YONETICI" or oturum.has_permission("kullanici_yonetme")
        if not (self_ok or admin_ok):
            raise PermissionError("PIN yönetimi için yetkiniz yok.")
        if self_ok and not admin_ok:
            if not eski_pin_veya_sifre:
                raise ValueError("Mevcut şifre veya PIN gerekli.")
            eski = eski_pin_veya_sifre.strip()
            ok = parola_dogrula(eski, user.parola_hash)
            if not ok and user.hizli_pin_hash:
                ok = parola_dogrula(eski, user.hizli_pin_hash)
            if not ok:
                raise ValueError("Mevcut şifre veya PIN hatalı.")
        user.hizli_pin_hash = hash_parola(pin)
        session.flush()
        session.commit()


def pin_iptal(user_id: int, *, dogrulama: str | None = None) -> None:
    users_pin_schema_guncelle()
    with get_system_session() as session:
        user = session.get(User, int(user_id))
        if not user:
            raise ValueError("Kullanıcı bulunamadı.")
        self_ok = oturum.user_id == user.id
        admin_ok = oturum.role_kod == "YONETICI" or oturum.has_permission("kullanici_yonetme")
        if not (self_ok or admin_ok):
            raise PermissionError("PIN iptali için yetkiniz yok.")
        if self_ok and not admin_ok:
            if not dogrulama or not parola_dogrula(dogrulama.strip(), user.parola_hash):
                raise ValueError("Şifre doğrulaması gerekli.")
        user.hizli_pin_hash = None
        session.flush()
        session.commit()


def pin_tanimli_mi(user_id: int) -> bool:
    users_pin_schema_guncelle()
    with get_system_session() as session:
        user = session.get(User, int(user_id))
        return bool(user and getattr(user, "hizli_pin_hash", None))


def _oturum_ayar_dosyasi():
    import json
    import os
    from pathlib import Path

    base = Path(os.environ.get("LOCALAPPDATA", str(Path.home()))) / "MuhasebeProgrami" / "ayarlar"
    base.mkdir(parents=True, exist_ok=True)
    return base / "oturum_ayarlar.json"


def ekran_kilidi_dakika_oku() -> int:
    """0=kapalı; izin verilen: 5, 10, 15, 30."""
    import json

    yol = _oturum_ayar_dosyasi()
    if not yol.exists():
        return 0
    try:
        veri = json.loads(yol.read_text(encoding="utf-8"))
        dk = int(veri.get("ekran_kilidi_dakika", 0) or 0)
    except (OSError, json.JSONDecodeError, TypeError, ValueError):
        return 0
    return dk if dk in (0, 5, 10, 15, 30) else 0


def ekran_kilidi_dakika_yaz(dakika: int) -> None:
    import json

    dk = int(dakika or 0)
    if dk not in (0, 5, 10, 15, 30):
        raise ValueError("Ekran kilidi: Kapalı, 5, 10, 15 veya 30 dakika.")
    yol = _oturum_ayar_dosyasi()
    mevcut: dict[str, Any] = {}
    if yol.exists():
        try:
            mevcut = json.loads(yol.read_text(encoding="utf-8"))
            if not isinstance(mevcut, dict):
                mevcut = {}
        except (OSError, json.JSONDecodeError):
            mevcut = {}
    mevcut["ekran_kilidi_dakika"] = dk
    yol.write_text(json.dumps(mevcut, ensure_ascii=False, indent=2), encoding="utf-8")
