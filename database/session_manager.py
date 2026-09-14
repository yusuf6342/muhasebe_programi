"""Aktif kullanıcı / firma / dönem oturumu — ekranlar buradan okur."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class SessionManager:
    user_id: int | None = None
    kullanici_adi: str | None = None
    ad_soyad: str | None = None
    role_kod: str | None = None
    role_ad: str | None = None
    sifre_degistirmeli: bool = False

    company_id: int | None = None
    firma_kodu: str | None = None
    firma_unvan: str | None = None
    firma_uid: str | None = None
    db_path: str | None = None

    period_id: int | None = None
    donem_adi: str | None = None

    permissions: set[str] = field(default_factory=set)
    _extra: dict[str, Any] = field(default_factory=dict)

    def clear(self) -> None:
        self.user_id = None
        self.kullanici_adi = None
        self.ad_soyad = None
        self.role_kod = None
        self.role_ad = None
        self.sifre_degistirmeli = False
        self.company_id = None
        self.firma_kodu = None
        self.firma_unvan = None
        self.firma_uid = None
        self.db_path = None
        self.period_id = None
        self.donem_adi = None
        self.permissions.clear()
        self._extra.clear()

    def set_user(
        self,
        *,
        user_id: int,
        kullanici_adi: str,
        ad_soyad: str,
        role_kod: str,
        role_ad: str,
        permissions: set[str],
        sifre_degistirmeli: bool = False,
    ) -> None:
        self.user_id = user_id
        self.kullanici_adi = kullanici_adi
        self.ad_soyad = ad_soyad
        self.role_kod = role_kod
        self.role_ad = role_ad
        self.permissions = set(permissions)
        self.sifre_degistirmeli = sifre_degistirmeli

    def set_company(
        self,
        *,
        company_id: int,
        firma_kodu: str,
        firma_unvan: str,
        firma_uid: str,
        db_path: str,
    ) -> None:
        self.company_id = company_id
        self.firma_kodu = firma_kodu
        self.firma_unvan = firma_unvan
        self.firma_uid = firma_uid
        self.db_path = db_path

    def set_period(self, period_id: int | None, donem_adi: str | None) -> None:
        self.period_id = period_id
        self.donem_adi = donem_adi

    def has_permission(self, kod: str) -> bool:
        if self.role_kod == "YONETICI":
            return True
        return kod in self.permissions

    def require_permission(self, kod: str) -> None:
        if not self.has_permission(kod):
            raise PermissionError(f"Bu işlem için yetkiniz yok: {kod}")

    @property
    def oturum_acik(self) -> bool:
        return self.user_id is not None

    @property
    def firma_secili(self) -> bool:
        return self.company_id is not None


# Tekil oturum — uygulama boyunca ortak
oturum = SessionManager()
