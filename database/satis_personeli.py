"""Satış personeli — mevcut sistem kullanıcılarından seçim (ayrı personel tablosu yok)."""

from __future__ import annotations

from typing import Any

from database.access import yetki_var
from database.session_manager import oturum
from database.user_switch import aktif_kullanici_secenekleri


def satis_personeli_degistirme_yetkisi() -> bool:
    """Başka kullanıcıyı satış personeli olarak atayabilir mi?"""
    if not oturum.oturum_acik:
        return False
    if (oturum.role_kod or "").upper() == "YONETICI":
        return True
    return yetki_var("satis_personeli_degistirme")


def personel_etiketi(ad_soyad: str, kullanici_kodu: str = "", *, pasif: bool = False) -> str:
    ad = (ad_soyad or "").strip() or "—"
    kod = (kullanici_kodu or "").strip()
    metin = f"{ad} ({kod})" if kod else ad
    if pasif:
        metin = f"{metin} [pasif]"
    return metin


def aktif_satis_personelleri() -> list[dict[str, Any]]:
    """Firma ile ilişkili aktif kullanıcılar (satış personeli listesi)."""
    ham = aktif_kullanici_secenekleri()
    # kullanici_kodu eksikse tamamla
    from sqlalchemy import select

    from database.database import get_system_session
    from database.system.models import User

    idler = [int(u["id"]) for u in ham]
    kod_map: dict[int, str] = {}
    if idler:
        with get_system_session() as session:
            for u in session.scalars(select(User).where(User.id.in_(idler))).all():
                kod_map[int(u.id)] = u.kullanici_kodu or ""

    # Aynı ad_soyad birden fazla ise kod zorunlu (her zaman kod gösterilir)
    sonuc: list[dict[str, Any]] = []
    for u in ham:
        uid = int(u["id"])
        ad = (u.get("ad_soyad") or "").strip()
        kod = kod_map.get(uid, "")
        etiket = personel_etiketi(ad, kod)
        sonuc.append(
            {
                "id": uid,
                "ad_soyad": ad,
                "kullanici_kodu": kod,
                "etiket": etiket,
                "aktif": True,
            }
        )
    return sonuc


def personel_listesini_etiketle(
    personeller: list[dict[str, Any]],
    *,
    ekstra: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """Etiket → kayıt haritası; eski/pasif kayıt için ekstra satır eklenebilir."""
    liste = list(personeller)
    if ekstra and ekstra.get("id"):
        eid = int(ekstra["id"])
        if not any(int(p["id"]) == eid for p in liste):
            liste.append(
                {
                    "id": eid,
                    "ad_soyad": (ekstra.get("ad_soyad") or "").strip(),
                    "kullanici_kodu": ekstra.get("kullanici_kodu") or "",
                    "etiket": personel_etiketi(
                        ekstra.get("ad_soyad") or "",
                        ekstra.get("kullanici_kodu") or "",
                        pasif=True,
                    ),
                    "aktif": False,
                }
            )
    return liste


def oturum_satis_personeli() -> dict[str, Any] | None:
    if not oturum.oturum_acik or not oturum.user_id:
        return None
    uid = int(oturum.user_id)
    for p in aktif_satis_personelleri():
        if int(p["id"]) == uid:
            return p
    # Aktif listede yoksa (yetki/firma) yine de öner
    return {
        "id": uid,
        "ad_soyad": (oturum.ad_soyad or oturum.kullanici_adi or "").strip(),
        "kullanici_kodu": "",
        "etiket": personel_etiketi(oturum.ad_soyad or oturum.kullanici_adi or ""),
        "aktif": True,
    }


def secimi_dogrula(
    sales_person_id: int | None,
    *,
    izin_diger: bool | None = None,
) -> tuple[int, str]:
    """Geçerli aktif personel id + görünen ad döner; aksi halde ValueError."""
    if not sales_person_id:
        raise ValueError("Satış personeli seçimi zorunludur.")
    sid = int(sales_person_id)
    if izin_diger is None:
        izin_diger = satis_personeli_degistirme_yetkisi()
    aktifler = {int(p["id"]): p for p in aktif_satis_personelleri()}
    if sid not in aktifler:
        raise ValueError(
            "Seçilen satış personeli aktif değil veya bu firmada kullanılamaz."
        )
    if not izin_diger and oturum.user_id and sid != int(oturum.user_id):
        raise ValueError(
            "Başka bir satış personeli seçme yetkiniz yok. Yalnızca kendinizi seçebilirsiniz."
        )
    p = aktifler[sid]
    return sid, (p.get("ad_soyad") or "").strip()
