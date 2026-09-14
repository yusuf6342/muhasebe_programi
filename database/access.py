"""Servis seviyesi yetki ve dönem kontrolleri (AŞAMA 5).

Yetkisiz işlem yalnızca buton gizlenerek engellenmez; yazma metotları
buradan da kontrol edilir.
"""

from __future__ import annotations

from database.session_manager import oturum


class AccessError(ValueError, PermissionError):
    """Yetki veya dönem ihlali — UI'da ValueError olarak da yakalanabilir."""


def aktif_firma_zorunlu() -> None:
    from database.database import company_db

    if not oturum.firma_secili:
        raise AccessError("Aktif firma seçilmedi. Önce firmaya giriş yapın.")
    if not company_db.acik:
        raise AccessError("Firma veritabanı bağlantısı kapalı. Firmayı yeniden seçin.")


def yetki_var(*kodlar: str) -> bool:
    if oturum.role_kod == "YONETICI":
        return True
    return any(oturum.has_permission(k) for k in kodlar)


def yetki_zorunlu(*kodlar: str, mesaj: str | None = None) -> None:
    """En az bir izin kodu gerekli."""
    aktif_firma_zorunlu()
    if yetki_var(*kodlar):
        return
    ad = ", ".join(kodlar)
    raise AccessError(mesaj or f"Bu işlem için yetkiniz yok ({ad}).")


def yazma_zorunlu(*kodlar: str, mesaj: str | None = None) -> None:
    """Yazma izni + kapalı dönem kontrolü."""
    yetki_zorunlu(*kodlar, mesaj=mesaj)
    # Dönem servisi dairesel import olmasın diye gecikmeli
    from database.donem_service import DonemService

    if not DonemService.kayit_izinli_mi():
        raise AccessError(
            "Seçili çalışma dönemi kapalı. Yeni kayıt veya değişiklik yapılamaz."
        )


def maliyet_izinli() -> bool:
    return yetki_var("maliyet_gorma")


def kar_izinli() -> bool:
    return yetki_var("kar_gorma")


def maliyet_zorunlu() -> None:
    yetki_zorunlu("maliyet_gorma", mesaj="Maliyet bilgilerini görme yetkiniz yok.")


def kar_zorunlu() -> None:
    yetki_zorunlu("kar_gorma", mesaj="Kâr bilgilerini görme yetkiniz yok.")
