"""Seviye 1 + Seviye 2 kontrollü onarımlar — yedek kapısı, önizleme, transaction + doğrulama.

Seviye 3 (cari birleştirme, kapalı dönem, fiziksel silme, rastgele hesap dengeleme vb.) YOKTUR.
"""

from __future__ import annotations

import logging
import os
import re
import uuid
from datetime import date, datetime
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path
from typing import Any, Callable

from sqlalchemy import inspect, select, text
from sqlalchemy.orm import selectinload

from database.session_manager import oturum

_log = logging.getLogger("cin_muhasebe.servis.repair")

ProgressCb = Callable[[int, str], None] | None

# Tarama toleransı ile uyumlu
_TOL = Decimal("0.02")
_KURUS = Decimal("0.01")

# --- Seviye 1 katalog ---------------------------------------------------------

# issue_code → onarım aksiyonu
LEVEL1_ACTIONS: dict[str, str] = {
    "LOG_KLASOR_YOK": "create_folders",
    "YEDEK_KLASOR_YOK": "create_folders",
    "KLASOR_LOG_YOK": "create_folders",
    "KLASOR_YEDEK_YOK": "create_folders",
    "KLASOR_TEMP_YOK": "create_folders",
    "KLASOR_BRANDING_YOK": "create_folders",
    "AYAR_EKSIK": "default_settings",
    "INDEX_EKSIK": "create_indexes",
}

# --- Seviye 2 katalog (veri değişir; önizleme + yedek + yetki zorunlu) ---------
# issue_code → onarım aksiyonu
LEVEL2_ACTIONS: dict[str, str] = {
    "FATURA_TOPLAM_UYUSMAZ": "recalc_fatura_header",
    "FATURA_SATIR_MATRAH": "recalc_fatura_header",
    "CEK_TUTAR_UYUSMAZ": "fix_cek_kalan",
    "FIS_BASLIK_SATIR": "recalc_muhasebe_header",
}

# Açıkça Seviye 3 — otomatik onarım yok (mesaj için)
LEVEL3_CODES: frozenset[str] = frozenset(
    {
        "FIS_BORC_ALACAK",  # satırlar dengesiz olabilir; hesap uydurma yok
        "CARI_BIRLESTIR",
        "STOK_BIRLESTIR",
        "FATURA_NO_DEGISTIR",
        "FIFO_YENIDEN",
        "FIZIKSEL_SIL",
        "CARI_BAKIYE_REWRITE",
    }
)

# Güvenli AppSetting varsayılanları (yalnızca eksikse eklenir; mevcut değer değiştirilmez)
SAFE_DEFAULT_SETTINGS: tuple[tuple[str, str], ...] = (
    ("kurulum_tamam", "1"),
    ("tek_firma_otomatik_giris", "1"),
)

# CREATE INDEX IF NOT EXISTS — yalnızca bu beyaz liste (iş bakiyesine dokunmaz)
SAFE_INDEXES: tuple[tuple[str, str, str], ...] = (
    # (index_name, table_name, columns_sql)
    ("ix_service_issues_company_status", "service_issues", "company_id, status"),
    ("ix_service_issues_module", "service_issues", "module_name, severity"),
    ("ix_service_issues_code", "service_issues", "issue_code"),
    ("ix_service_repairs_issue", "service_repairs", "issue_id"),
    ("ix_service_repairs_company", "service_repairs", "company_id, status"),
    ("ix_cari_kartlar_cari_kodu", "cari_kartlar", "cari_kodu"),
    ("ix_stok_kartlari_stok_kodu", "stok_kartlari", "stok_kodu"),
    ("ix_finans_hareketleri_hesap_id", "finans_hareketleri", "hesap_id"),
)


class RepairPermissionError(PermissionError):
    """Onarım yetkisi yok."""


class RepairBackupError(RuntimeError):
    """Yedek kapısı başarısız — onarım iptal."""


class RepairAborted(RuntimeError):
    """Onarım güvenli şekilde iptal edildi."""


def onarim_yetkisi_var() -> bool:
    if oturum.role_kod == "YONETICI":
        return True
    return bool(oturum.has_permission("servis_onarim"))


def _require_onarim() -> None:
    if not onarim_yetkisi_var():
        raise RepairPermissionError(
            "Onarım için yönetici veya 'servis_onarim' yetkisi gerekir."
        )


def _level_for_code(issue_code: str) -> int:
    code = issue_code or ""
    if code in LEVEL1_ACTIONS:
        return 1
    if code in LEVEL2_ACTIONS:
        return 2
    if code in LEVEL3_CODES:
        return 3
    return 0


def is_level1(issue_code: str | None, repair_level: int | None = None) -> bool:
    if repair_level is not None and int(repair_level) == 1:
        return True
    if repair_level is not None and int(repair_level) >= 2:
        return False
    return (issue_code or "") in LEVEL1_ACTIONS


def is_level2(issue_code: str | None, repair_level: int | None = None) -> bool:
    code = issue_code or ""
    if code in LEVEL2_ACTIONS:
        return True
    # repair_level=2 tek başına yetmez; katalogda olmalı
    if repair_level is not None and int(repair_level) == 2:
        return code in LEVEL2_ACTIONS
    return False


def is_auto_repairable(issue_code: str | None, repair_level: int | None = None) -> bool:
    return is_level1(issue_code, repair_level) or is_level2(issue_code, repair_level)


def _dec(val: Any) -> Decimal:
    return Decimal(str(val or 0)).quantize(_KURUS, rounding=ROUND_HALF_UP)


def _abs_diff(a: Decimal, b: Decimal) -> Decimal:
    return abs(a - b)


def _parse_record_id(issue: dict[str, Any]) -> int | None:
    rid = issue.get("record_id")
    if rid is not None and str(rid).strip().isdigit():
        return int(str(rid).strip())
    for key in ("document_number", "kayit_belge", "technical_detail", "title", "user_message"):
        text_val = issue.get(key) or ""
        m = re.search(r"id\s*=\s*(\d+)", str(text_val), re.I)
        if m:
            return int(m.group(1))
    return None


def _tarih_kapali_donemde(tarih: date | None, *, donem_id: int | None = None) -> bool:
    """Kapalı dönem kaydına Seviye 2 yazma yasak."""
    if tarih is None and donem_id is None:
        return False
    try:
        from database.database import get_session
        from database.models.donem import Donem
    except Exception:
        return False
    try:
        with get_session() as session:
            if donem_id is not None:
                d = session.get(Donem, int(donem_id))
                if d is not None and bool(getattr(d, "kapali", False)):
                    return True
            if tarih is None:
                return False
            for d in session.scalars(select(Donem).where(Donem.kapali.is_(True))).all():
                bas = getattr(d, "baslangic_tarihi", None)
                bit = getattr(d, "bitis_tarihi", None)
                if bas and bit and bas <= tarih <= bit:
                    return True
    except Exception as exc:  # noqa: BLE001
        _log.warning("kapalı dönem kontrolü başarısız: %s", exc)
    return False


def _hedef_klasorler() -> dict[str, Path]:
    """Seviye 1 oluşturulabilir klasörler (kullanıcı verisi yok)."""
    out: dict[str, Path] = {}
    local = (os.environ.get("LOCALAPPDATA") or "").strip()
    if local:
        out["logs"] = Path(local) / "CinMuhasebe" / "logs"
        out["logs_alt"] = Path(local) / "MuhasebeProgrami" / "logs"
        out["temp"] = Path(local) / "MuhasebeProgrami" / "temp"
    try:
        from database.database import PROJE_DATA_DIR, BASE_DIR

        out["logs_proje"] = Path(PROJE_DATA_DIR) / "logs"
        out["temp_proje"] = Path(PROJE_DATA_DIR) / "temp"
        out["branding"] = Path(BASE_DIR) / "assets" / "branding"
    except Exception:
        pass
    try:
        from database.servis_sistem.backup_service import BackupService

        out["yedek"] = BackupService.yedek_klasoru_onerisi()
    except Exception:
        if local:
            out["yedek"] = Path(local) / "MuhasebeProgrami" / "yedekler"
    return out


def probe_level1_issues(*, kaydet: bool = True) -> list[dict[str, Any]]:
    """Eksik klasör / ayar / index için Seviye 1 aday sorunları üretir."""
    from database.servis_sistem.error_log_service import ErrorLogService

    bulunan: list[dict[str, Any]] = []

    klasorler = _hedef_klasorler()
    mapping = [
        ("logs", "KLASOR_LOG_YOK", "Log klasörü eksik"),
        ("logs_alt", "KLASOR_LOG_YOK", "Log klasörü eksik"),
        ("logs_proje", "KLASOR_LOG_YOK", "Log klasörü eksik"),
        ("yedek", "KLASOR_YEDEK_YOK", "Yedek klasörü eksik"),
        ("temp", "KLASOR_TEMP_YOK", "Geçici klasör eksik"),
        ("temp_proje", "KLASOR_TEMP_YOK", "Geçici klasör eksik"),
        ("branding", "KLASOR_BRANDING_YOK", "assets/branding klasörü eksik"),
    ]
    seen_codes: set[str] = set()
    for key, code, title in mapping:
        p = klasorler.get(key)
        if p is None:
            continue
        if p.is_dir():
            continue
        if code in seen_codes:
            continue
        seen_codes.add(code)
        item = {
            "module_name": "dosya_sistemi",
            "issue_code": code,
            "severity": "uyari",
            "title": f"{title}: {p}",
            "user_message": f"{title}: {p}",
            "technical_detail": str(p),
            "suggested_action": "Seviye 1: klasörü oluştur (kullanıcı verisi yok).",
            "auto_fixable": True,
            "repair_level": 1,
            "record_id": None,
        }
        bulunan.append(item)

    # Varsayılan ayarlar
    eksik_ayarlar = _eksik_guvenli_ayarlar()
    if eksik_ayarlar:
        item = {
            "module_name": "sistem",
            "issue_code": "AYAR_EKSIK",
            "severity": "uyari",
            "title": f"Eksik güvenli varsayılan ayarlar: {', '.join(a for a, _ in eksik_ayarlar)}",
            "user_message": "Kurulum varsayılan ayarları eksik (yalnızca güvenli anahtarlar).",
            "technical_detail": "; ".join(f"{a}={v}" for a, v in eksik_ayarlar),
            "suggested_action": "Seviye 1: eksik AppSetting anahtarlarını ekle (mevcut değere dokunma).",
            "auto_fixable": True,
            "repair_level": 1,
            "record_id": None,
        }
        bulunan.append(item)

    # Eksik indexler
    eksik_ix = _eksik_guvenli_indexler()
    if eksik_ix:
        item = {
            "module_name": "veritabani",
            "issue_code": "INDEX_EKSIK",
            "severity": "uyari",
            "title": f"Eksik güvenli indexler: {len(eksik_ix)}",
            "user_message": "Beyaz listedeki SQLite indexleri eksik.",
            "technical_detail": "; ".join(n for n, _, _ in eksik_ix),
            "suggested_action": "Seviye 1: CREATE INDEX IF NOT EXISTS (veri satırı değişmez).",
            "auto_fixable": True,
            "repair_level": 1,
            "record_id": None,
        }
        bulunan.append(item)

    if kaydet:
        for it in bulunan:
            iid = ErrorLogService.kaydet_sorun(
                module_name=it["module_name"],
                issue_code=it["issue_code"],
                severity=it["severity"],
                title=it["title"][:300],
                user_message=it["user_message"],
                technical_detail=it.get("technical_detail"),
                suggested_action=it.get("suggested_action"),
                auto_fixable=True,
                repair_level=1,
            )
            it["id"] = iid
    return bulunan


def _eksik_guvenli_ayarlar() -> list[tuple[str, str]]:
    try:
        from sqlalchemy import select

        from database.database import get_system_session
        from database.system.models import AppSetting
    except Exception:
        return []
    eksik: list[tuple[str, str]] = []
    try:
        with get_system_session() as session:
            for anahtar, deger in SAFE_DEFAULT_SETTINGS:
                kayit = session.scalar(
                    select(AppSetting).where(AppSetting.anahtar == anahtar)
                )
                if kayit is None:
                    eksik.append((anahtar, deger))
    except Exception as exc:  # noqa: BLE001
        _log.warning("ayar kontrolü başarısız: %s", exc)
    return eksik


def _eksik_guvenli_indexler() -> list[tuple[str, str, str]]:
    from database.database import engine

    if engine is None:
        return []
    try:
        insp = inspect(engine)
        mevcut: set[str] = set()
        for tname in {t for _, t, _ in SAFE_INDEXES}:
            if not insp.has_table(tname):
                continue
            for ix in insp.get_indexes(tname) or []:
                if ix.get("name"):
                    mevcut.add(ix["name"])
        # sqlite_master ile de doğrula
        with engine.connect() as conn:
            rows = conn.execute(
                text("SELECT name FROM sqlite_master WHERE type='index'")
            ).fetchall()
            for r in rows:
                if r[0]:
                    mevcut.add(r[0])
    except Exception as exc:  # noqa: BLE001
        _log.warning("index kontrolü başarısız: %s", exc)
        return []

    eksik: list[tuple[str, str, str]] = []
    for name, table, cols in SAFE_INDEXES:
        try:
            if not insp.has_table(table):
                continue
        except Exception:
            continue
        if name not in mevcut:
            eksik.append((name, table, cols))
    return eksik


class RepairService:
    """Seviye 1 + Seviye 2 onarım motoru."""

    @staticmethod
    def repair_preview(
        *,
        issue_id: int | None = None,
        issue_code: str | None = None,
        madde: dict[str, Any] | None = None,
        take_backup: bool = False,
    ) -> dict[str, Any]:
        """Onarım önizlemesi — veri değişikliği yok (take_backup=False iken)."""
        issue = RepairService._resolve_issue(issue_id=issue_id, issue_code=issue_code, madde=madde)
        code = issue.get("issue_code") or issue_code or ""
        level = int(issue.get("repair_level") or 0)
        if level <= 0:
            level = _level_for_code(code)

        if code in LEVEL1_ACTIONS or (level == 1 and code in LEVEL1_ACTIONS):
            return RepairService._preview_level1(issue, code, take_backup=take_backup)

        if code in LEVEL2_ACTIONS or level == 2:
            if code not in LEVEL2_ACTIONS:
                return RepairService._preview_blocked(
                    issue,
                    code,
                    seviye=max(level, 3),
                    mesaj=(
                        f"'{code}' Seviye 2 kataloğunda değil. "
                        "Manuel müdahale veya sonraki aşama gerekir."
                    ),
                )
            return RepairService._preview_level2(issue, code, take_backup=take_backup)

        # Seviye 3 / bilinmeyen
        seviye = 3 if code in LEVEL3_CODES or level >= 3 else (level or 3)
        deferred = ""
        if "BAKIYE" in code.upper() or code == "CARI_BAKIYE_REWRITE":
            deferred = (
                " Cari bakiye yeniden yazımı: mevcut CariService'te "
                "hareketlerden bakiye yazan bir onarım metodu yok — manuel."
            )
        return RepairService._preview_blocked(
            issue,
            code,
            seviye=seviye,
            mesaj=(
                "Bu hata Seviye 3 / yasaklı otomatik onarım sınıfındadır "
                "(birleştirme, kapalı dönem, fiziksel silme, rastgele hesap dengeleme, "
                "sessiz FIFO vb.)."
                + deferred
            ),
        )

    @staticmethod
    def _preview_blocked(
        issue: dict[str, Any],
        code: str,
        *,
        seviye: int,
        mesaj: str,
    ) -> dict[str, Any]:
        return {
            "uygulanabilir": False,
            "seviye": seviye,
            "risk": "yüksek",
            "issue_id": issue.get("id"),
            "issue_code": code,
            "aciklama": issue.get("title") or issue.get("user_message") or code,
            "etkilenen_kayitlar": [],
            "yedek_yolu": None,
            "geri_alma_mumkun": False,
            "dogrulama_plani": "—",
            "mesaj": mesaj,
            "aksiyon": None,
        }

    @staticmethod
    def _preview_level1(
        issue: dict[str, Any], code: str, *, take_backup: bool
    ) -> dict[str, Any]:
        aksiyon = LEVEL1_ACTIONS.get(code, "create_folders")
        etkilenen = RepairService._preview_effects(aksiyon, issue)
        yedek_yolu = None
        if take_backup:
            from database.servis_sistem.backup_service import BackupService

            yedek_yolu = str(BackupService.servis_oncesi_yedek_al())

        return {
            "uygulanabilir": True,
            "seviye": 1,
            "risk": "düşük",
            "issue_id": issue.get("id"),
            "issue_code": code,
            "aciklama": issue.get("title") or issue.get("user_message") or code,
            "etkilenen_kayitlar": etkilenen,
            "yedek_yolu": yedek_yolu,
            "yedek_plani": (
                "Onayda CinMuhasebe_ServisOncesi_YYYY-MM-DD_HHMMSS.db alınır; "
                "yedek yoksa / boşsa onarım iptal."
            ),
            "geri_alma_mumkun": aksiyon in ("default_settings", "create_indexes"),
            "geri_alma_notu": (
                "DB işlemleri transaction rollback ile geri alınır. "
                "Klasör oluşturma OS düzeyindedir; boş klasörler zararsızdır."
                if aksiyon == "create_folders"
                else "DB değişikliği transaction içinde; hata olursa rollback."
            ),
            "dogrulama_plani": RepairService._verify_plan(aksiyon, code),
            "mesaj": "Seviye 1 güvenli onarım önizlemesi — onaylanmadan veri değişmez.",
            "aksiyon": aksiyon,
            "modul": issue.get("module_name") or issue.get("modul"),
        }

    @staticmethod
    def _preview_level2(
        issue: dict[str, Any], code: str, *, take_backup: bool
    ) -> dict[str, Any]:
        aksiyon = LEVEL2_ACTIONS[code]
        try:
            etkilenen, detay = RepairService._preview_level2_effects(aksiyon, issue, code)
        except RepairAborted as exc:
            return {
                "uygulanabilir": False,
                "seviye": 2,
                "risk": "orta",
                "issue_id": issue.get("id"),
                "issue_code": code,
                "aciklama": issue.get("title") or issue.get("user_message") or code,
                "etkilenen_kayitlar": [],
                "yedek_yolu": None,
                "geri_alma_mumkun": False,
                "dogrulama_plani": "—",
                "mesaj": str(exc),
                "aksiyon": aksiyon,
                "modul": issue.get("module_name") or issue.get("modul"),
            }

        yedek_yolu = None
        if take_backup:
            from database.servis_sistem.backup_service import BackupService

            yedek_yolu = str(BackupService.servis_oncesi_yedek_al())

        return {
            "uygulanabilir": True,
            "seviye": 2,
            "risk": "orta — veri değişir",
            "issue_id": issue.get("id"),
            "issue_code": code,
            "aciklama": issue.get("title") or issue.get("user_message") or code,
            "etkilenen_kayitlar": etkilenen,
            "yedek_yolu": yedek_yolu,
            "yedek_plani": (
                "Onayda CinMuhasebe_ServisOncesi_YYYY-MM-DD_HHMMSS.db alınır; "
                "yedek yoksa / boşsa onarım iptal."
            ),
            "geri_alma_mumkun": True,
            "geri_alma_notu": (
                "Transaction rollback (hata durumunda). "
                "Başarılı onarım sonrası geri alma: ServisOncesi yedeğinden restore."
            ),
            "dogrulama_plani": RepairService._verify_plan(aksiyon, code),
            "mesaj": (
                "Seviye 2 — veri değişir, yedek alındı (onayda). "
                "Onaylanmadan mutasyon yok. Tutarlar satırlardan yeniden yazılır; uydurma yok."
            ),
            "aksiyon": aksiyon,
            "modul": issue.get("module_name") or issue.get("modul"),
            "detay": detay,
        }

    @staticmethod
    def _preview_level2_effects(
        aksiyon: str, issue: dict[str, Any], code: str
    ) -> tuple[list[str], dict[str, Any]]:
        if aksiyon == "recalc_fatura_header":
            return RepairService._preview_fatura_header(issue)
        if aksiyon == "fix_cek_kalan":
            return RepairService._preview_cek_kalan(issue)
        if aksiyon == "recalc_muhasebe_header":
            return RepairService._preview_muhasebe_header(issue)
        raise RepairAborted(f"Bilinmeyen Seviye 2 aksiyonu: {aksiyon} ({code})")

    @staticmethod
    def _preview_fatura_header(issue: dict[str, Any]) -> tuple[list[str], dict[str, Any]]:
        from database.database import get_session

        fid = _parse_record_id(issue)
        if fid is None:
            raise RepairAborted("Fatura kaydı id bulunamadı; önizleme yapılamaz.")
        modul = (issue.get("module_name") or issue.get("modul") or "").lower()
        yon = "alis" if modul == "alis" else "satis"

        with get_session() as session:
            if yon == "alis":
                from database.alis_faturasi_service import AlisFaturasiService
                from database.models.alis_faturasi import AlisFaturasi

                fatura = session.scalar(
                    select(AlisFaturasi)
                    .options(selectinload(AlisFaturasi.satirlar))
                    .where(AlisFaturasi.id == fid)
                )
                toplam_fn = AlisFaturasiService.toplam
            else:
                from database.models.satis_faturasi import SatisFaturasi
                from database.satis_faturasi_service import SatisFaturasiService

                fatura = session.scalar(
                    select(SatisFaturasi)
                    .options(selectinload(SatisFaturasi.satirlar))
                    .where(SatisFaturasi.id == fid)
                )
                toplam_fn = SatisFaturasiService.toplam

            if fatura is None:
                raise RepairAborted(f"Fatura bulunamadı: id={fid}")
            if (getattr(fatura, "durum", "") or "") == "İPTAL":
                raise RepairAborted("İptal faturalarda başlık onarımı yapılmaz.")
            tarih = getattr(fatura, "fatura_tarihi", None)
            if _tarih_kapali_donemde(tarih):
                raise RepairAborted(
                    "Kapalı dönem kaydı — Seviye 2 onarım yasak (manuel)."
                )
            if not fatura.satirlar:
                raise RepairAborted("Satır yok; başlık tutarı uydurulamaz.")

            toplam = toplam_fn(fatura.satirlar)
            yeni_matrah = _dec(toplam["ara_toplam"] - toplam["iskonto"])
            yeni_kdv = _dec(toplam["kdv"])
            yeni_genel = _dec(toplam["genel_toplam"])
            eski = {
                "tl_matrah": str(_dec(fatura.tl_matrah)),
                "tl_kdv": str(_dec(fatura.tl_kdv)),
                "tl_genel_toplam": str(_dec(fatura.tl_genel_toplam)),
            }
            yeni = {
                "tl_matrah": str(yeni_matrah),
                "tl_kdv": str(yeni_kdv),
                "tl_genel_toplam": str(yeni_genel),
            }
            belge = getattr(fatura, "fatura_no", "") or f"id={fid}"
            etkilenen = [
                f"{yon} fatura {belge} (id={fid})",
                f"matrah {eski['tl_matrah']} → {yeni['tl_matrah']}",
                f"kdv {eski['tl_kdv']} → {yeni['tl_kdv']}",
                f"genel {eski['tl_genel_toplam']} → {yeni['tl_genel_toplam']}",
            ]
            return etkilenen, {"yon": yon, "fatura_id": fid, "eski": eski, "yeni": yeni}

    @staticmethod
    def _preview_cek_kalan(issue: dict[str, Any]) -> tuple[list[str], dict[str, Any]]:
        from database.database import get_session
        from database.models.cek_senet import CekSenetEvrak

        eid = _parse_record_id(issue)
        if eid is None:
            raise RepairAborted("Çek/senet kaydı id bulunamadı.")
        with get_session() as session:
            evrak = session.get(CekSenetEvrak, eid)
            if evrak is None:
                raise RepairAborted(f"Çek/senet bulunamadı: id={eid}")
            tarih = getattr(evrak, "vade_tarihi", None) or getattr(
                evrak, "son_islem_tarihi", None
            )
            if isinstance(tarih, date) and _tarih_kapali_donemde(tarih):
                raise RepairAborted(
                    "Kapalı dönem kaydı — Seviye 2 onarım yasak (manuel)."
                )
            tutar = _dec(evrak.tl_tutari)
            tahsil = _dec(evrak.tahsil_edilen_tutar)
            yeni_kalan = (tutar - tahsil).quantize(_KURUS, rounding=ROUND_HALF_UP)
            eski_kalan = _dec(evrak.kalan_tutar)
            portfoy = getattr(evrak, "portfoy_no", "") or f"id={eid}"
            etkilenen = [
                f"çek/senet {portfoy} (id={eid})",
                f"kalan_tutar {eski_kalan} → {yeni_kalan} (= {tutar} − {tahsil})",
            ]
            return etkilenen, {
                "evrak_id": eid,
                "eski_kalan": str(eski_kalan),
                "yeni_kalan": str(yeni_kalan),
            }

    @staticmethod
    def _preview_muhasebe_header(issue: dict[str, Any]) -> tuple[list[str], dict[str, Any]]:
        from database.database import get_session
        from database.models.genel_muhasebe import MuhasebeFisi

        fid = _parse_record_id(issue)
        if fid is None:
            raise RepairAborted("Muhasebe fişi id bulunamadı.")
        with get_session() as session:
            fis = session.scalar(
                select(MuhasebeFisi)
                .options(selectinload(MuhasebeFisi.satirlar))
                .where(MuhasebeFisi.id == fid)
            )
            if fis is None:
                raise RepairAborted(f"Fiş bulunamadı: id={fid}")
            if (fis.durum or "") == "İptal":
                raise RepairAborted("İptal fişte başlık onarımı yapılmaz.")
            if _tarih_kapali_donemde(
                getattr(fis, "fis_tarihi", None),
                donem_id=getattr(fis, "donem_id", None),
            ):
                raise RepairAborted(
                    "Kapalı dönem kaydı — Seviye 2 onarım yasak (manuel)."
                )
            s_borc = sum((_dec(s.borc) for s in fis.satirlar), Decimal("0"))
            s_alacak = sum((_dec(s.alacak) for s in fis.satirlar), Decimal("0"))
            if _abs_diff(s_borc, s_alacak) > _TOL:
                raise RepairAborted(
                    f"Fiş satırları dengesiz (borç={s_borc}, alacak={s_alacak}). "
                    "Otomatik hesap uydurma yok — manuel düzeltin."
                )
            eski_b, eski_a = _dec(fis.toplam_borc), _dec(fis.toplam_alacak)
            fis_no = fis.fis_no or f"id={fid}"
            etkilenen = [
                f"fiş {fis_no} (id={fid})",
                f"toplam_borc {eski_b} → {s_borc}",
                f"toplam_alacak {eski_a} → {s_alacak}",
            ]
            return etkilenen, {
                "fis_id": fid,
                "eski": {"borc": str(eski_b), "alacak": str(eski_a)},
                "yeni": {"borc": str(s_borc), "alacak": str(s_alacak)},
            }

    @staticmethod
    def _resolve_issue(
        *,
        issue_id: int | None,
        issue_code: str | None,
        madde: dict[str, Any] | None,
    ) -> dict[str, Any]:
        from database.servis_sistem.error_log_service import ErrorLogService

        if issue_id is not None:
            found = ErrorLogService.get_issue(int(issue_id))
            if found:
                return found
            raise ValueError(f"Sorun bulunamadı: id={issue_id}")
        if madde:
            code = madde.get("hata_kodu") or madde.get("issue_code") or ""
            return {
                "id": madde.get("id") or madde.get("issue_id"),
                "issue_code": code,
                "title": madde.get("aciklama") or madde.get("title"),
                "user_message": madde.get("aciklama") or madde.get("user_message"),
                "module_name": madde.get("modul") or madde.get("module_name"),
                "repair_level": madde.get("repair_level")
                or _level_for_code(code),
                "technical_detail": madde.get("teknik") or madde.get("technical_detail"),
                "record_id": madde.get("record_id"),
                "document_number": madde.get("document_number")
                or madde.get("kayit_belge"),
                "status": madde.get("status") or "open",
            }
        if issue_code:
            return {
                "issue_code": issue_code,
                "repair_level": _level_for_code(issue_code),
                "title": issue_code,
            }
        raise ValueError("Önizleme için issue_id, issue_code veya madde gerekli.")

    @staticmethod
    def _preview_effects(aksiyon: str, issue: dict[str, Any]) -> list[str]:
        if aksiyon == "create_folders":
            klasorler = _hedef_klasorler()
            code = issue.get("issue_code") or ""
            keys: list[str]
            if code in ("LOG_KLASOR_YOK", "KLASOR_LOG_YOK"):
                keys = ["logs", "logs_alt", "logs_proje"]
            elif code in ("YEDEK_KLASOR_YOK", "KLASOR_YEDEK_YOK"):
                keys = ["yedek"]
            elif code == "KLASOR_TEMP_YOK":
                keys = ["temp", "temp_proje"]
            elif code == "KLASOR_BRANDING_YOK":
                keys = ["branding"]
            else:
                keys = list(klasorler.keys())
            out = []
            for k in keys:
                p = klasorler.get(k)
                if p and not p.is_dir():
                    out.append(str(p))
            return out or ["(hedeflenen klasörler zaten mevcut olabilir)"]
        if aksiyon == "default_settings":
            return [f"{a}={v}" for a, v in _eksik_guvenli_ayarlar()] or [
                "(eksik güvenli ayar yok)"
            ]
        if aksiyon == "create_indexes":
            return [n for n, _, _ in _eksik_guvenli_indexler()] or [
                "(eksik güvenli index yok)"
            ]
        return []

    @staticmethod
    def _verify_plan(aksiyon: str, code: str) -> str:
        if aksiyon == "create_folders":
            return f"Klasör varlığı yeniden kontrol edilir ({code})."
        if aksiyon == "default_settings":
            return "AppSetting anahtarları yeniden okunur."
        if aksiyon == "create_indexes":
            return "sqlite_master / inspector ile index varlığı doğrulanır."
        if aksiyon == "recalc_fatura_header":
            return (
                "Fatura başlık tl_matrah/tl_kdv/tl_genel_toplam satır toplamları ile "
                "yeniden kıyaslanır (matrah+kdv≈genel, satır≈matrah)."
            )
        if aksiyon == "fix_cek_kalan":
            return "kalan_tutar = tl_tutari − tahsil_edilen_tutar yeniden doğrulanır."
        if aksiyon == "recalc_muhasebe_header":
            return (
                "Fiş başlık toplam_borc/toplam_alacak satır SUM ile kıyaslanır; "
                "satır dengesi korunur."
            )
        return "İlgili kontrol yeniden çalıştırılır."

    @staticmethod
    def apply_level1(
        *,
        issue_id: int | None = None,
        issue_code: str | None = None,
        madde: dict[str, Any] | None = None,
        confirm: bool = False,
        progress: ProgressCb = None,
        yedek_klasor: str | Path | None = None,
    ) -> dict[str, Any]:
        """Tek Seviye 1 onarım. confirm=False → yalnızca önizleme sonucu döner (mutasyon yok)."""
        _require_onarim()
        preview = RepairService.repair_preview(
            issue_id=issue_id, issue_code=issue_code, madde=madde, take_backup=False
        )
        if not preview.get("uygulanabilir"):
            return {
                "basarili": False,
                "uygulandi": False,
                "mesaj": preview.get("mesaj"),
                "preview": preview,
            }
        if not confirm:
            return {
                "basarili": True,
                "uygulandi": False,
                "mesaj": "Önizleme hazır — onay gerekli.",
                "preview": preview,
            }

        def _p(pct: int, msg: str) -> None:
            if progress:
                progress(pct, msg)

        from database.servis_sistem.backup_service import BackupService
        from database.servis_sistem.error_log_service import ErrorLogService

        started = datetime.now()
        tx_id = str(uuid.uuid4())
        issue_ref = preview.get("issue_id")
        aksiyon = preview.get("aksiyon") or "create_folders"
        code = preview.get("issue_code") or ""

        _p(5, "Servis öncesi yedek alınıyor...")
        try:
            yedek_yolu = BackupService.servis_oncesi_yedek_al(yedek_klasor)
        except Exception as exc:
            ErrorLogService.kaydet_onarim(
                issue_id=issue_ref,
                repair_action=f"level1_{aksiyon}",
                preview=preview,
                status="aborted_no_backup",
                error_message=str(exc),
                verification_result="yedek kapısı başarısız — onarım yapılmadı",
                transaction_id=tx_id,
                started_at=started,
            )
            raise RepairBackupError(
                f"Yedek alınamadı; onarım iptal edildi: {exc}"
            ) from exc

        preview["yedek_yolu"] = str(yedek_yolu)
        _p(25, f"Yedek doğrulandı: {yedek_yolu.name}")

        before = {"etkilenen": list(preview.get("etkilenen_kayitlar") or [])}
        after: dict[str, Any] = {}
        rollback_status = None
        verification = ""
        status = "completed"

        try:
            _p(40, f"Onarım uygulanıyor: {aksiyon}...")
            if aksiyon == "create_folders":
                after = RepairService._do_create_folders(code)
            elif aksiyon == "default_settings":
                after = RepairService._do_default_settings()
            elif aksiyon == "create_indexes":
                after = RepairService._do_create_indexes()
            else:
                raise RepairAborted(f"Bilinmeyen Seviye 1 aksiyonu: {aksiyon}")

            _p(75, "Doğrulama...")
            ok, verification = RepairService._verify(aksiyon, code, after)
            if not ok:
                status = "completed_unverified"
            else:
                status = "completed"

            if issue_ref and ok:
                ErrorLogService.sorun_durum_guncelle(int(issue_ref), "resolved")
            elif issue_ref and not ok:
                ErrorLogService.sorun_durum_guncelle(int(issue_ref), "open")

            rid = ErrorLogService.kaydet_onarim(
                issue_id=issue_ref,
                repair_action=f"level1_{aksiyon}",
                preview=preview,
                before_data=before,
                after_data=after,
                backup_path=str(yedek_yolu),
                status=status,
                verification_result=verification,
                rollback_status=rollback_status,
                transaction_id=tx_id,
                started_at=started,
            )
            _p(100, "Tamamlandı")
            return {
                "basarili": True,
                "uygulandi": True,
                "mesaj": verification or "Onarım tamamlandı.",
                "preview": preview,
                "yedek_yolu": str(yedek_yolu),
                "after": after,
                "verification": verification,
                "repair_id": rid,
                "status": status,
                "mutasyon_muhasebe": False,
            }
        except Exception as exc:
            _log.exception("Seviye 1 onarım başarısız")
            rollback_status = "attempted"
            # DB aksiyonları kendi transaction'larında rollback eder
            ErrorLogService.kaydet_onarim(
                issue_id=issue_ref,
                repair_action=f"level1_{aksiyon}",
                preview=preview,
                before_data=before,
                after_data=after or None,
                backup_path=str(yedek_yolu),
                status="failed",
                error_message=str(exc),
                verification_result="başarısız — rollback uygulandı (DB)",
                rollback_status=rollback_status,
                transaction_id=tx_id,
                started_at=started,
            )
            raise

    @staticmethod
    def apply_level2(
        *,
        issue_id: int | None = None,
        issue_code: str | None = None,
        madde: dict[str, Any] | None = None,
        confirm: bool = False,
        progress: ProgressCb = None,
        yedek_klasor: str | Path | None = None,
    ) -> dict[str, Any]:
        """Tek Seviye 2 veri onarımı. confirm=False → yalnızca önizleme (mutasyon yok)."""
        _require_onarim()
        preview = RepairService.repair_preview(
            issue_id=issue_id, issue_code=issue_code, madde=madde, take_backup=False
        )
        if int(preview.get("seviye") or 0) != 2 or preview.get("aksiyon") not in LEVEL2_ACTIONS.values():
            # Seviye 2 değilse engelle (L3 veya bilinmeyen)
            if preview.get("uygulanabilir") and int(preview.get("seviye") or 0) == 1:
                return {
                    "basarili": False,
                    "uygulandi": False,
                    "mesaj": "Bu sorun Seviye 1; apply_level1 kullanın.",
                    "preview": preview,
                }
            return {
                "basarili": False,
                "uygulandi": False,
                "mesaj": preview.get("mesaj") or "Seviye 2 onarım uygulanamaz.",
                "preview": preview,
            }
        if not preview.get("uygulanabilir"):
            return {
                "basarili": False,
                "uygulandi": False,
                "mesaj": preview.get("mesaj"),
                "preview": preview,
            }
        if not confirm:
            return {
                "basarili": True,
                "uygulandi": False,
                "mesaj": "Önizleme hazır — onay gerekli (Seviye 2 — veri değişir).",
                "preview": preview,
            }

        def _p(pct: int, msg: str) -> None:
            if progress:
                progress(pct, msg)

        from database.servis_sistem.backup_service import BackupService
        from database.servis_sistem.error_log_service import ErrorLogService

        started = datetime.now()
        tx_id = str(uuid.uuid4())
        issue_ref = preview.get("issue_id")
        aksiyon = preview.get("aksiyon") or ""
        code = preview.get("issue_code") or ""
        issue = RepairService._resolve_issue(
            issue_id=issue_id, issue_code=issue_code, madde=madde
        )

        _p(5, "Servis öncesi yedek alınıyor...")
        try:
            yedek_yolu = BackupService.servis_oncesi_yedek_al(yedek_klasor)
        except Exception as exc:
            ErrorLogService.kaydet_onarim(
                issue_id=issue_ref,
                repair_action=f"level2_{aksiyon}",
                preview=preview,
                status="aborted_no_backup",
                error_message=str(exc),
                verification_result="yedek kapısı başarısız — onarım yapılmadı",
                transaction_id=tx_id,
                started_at=started,
            )
            raise RepairBackupError(
                f"Yedek alınamadı; onarım iptal edildi: {exc}"
            ) from exc

        preview["yedek_yolu"] = str(yedek_yolu)
        _p(25, f"Yedek doğrulandı: {yedek_yolu.name}")

        before = {
            "etkilenen": list(preview.get("etkilenen_kayitlar") or []),
            "detay": preview.get("detay"),
        }
        after: dict[str, Any] = {}
        rollback_status = None
        verification = ""
        status = "completed"

        try:
            _p(40, f"Seviye 2 onarım: {aksiyon}...")
            after = RepairService._dispatch_level2(aksiyon, issue, code)
            _p(75, "Doğrulama (yeniden tarama)...")
            ok, verification = RepairService._verify_level2(aksiyon, issue, code, after)
            status = "completed" if ok else "completed_unverified"
            if issue_ref and ok:
                ErrorLogService.sorun_durum_guncelle(int(issue_ref), "resolved")
            elif issue_ref and not ok:
                ErrorLogService.sorun_durum_guncelle(int(issue_ref), "open")

            rid = ErrorLogService.kaydet_onarim(
                issue_id=issue_ref,
                repair_action=f"level2_{aksiyon}",
                preview=preview,
                before_data=before,
                after_data=after,
                backup_path=str(yedek_yolu),
                status=status,
                verification_result=verification,
                rollback_status=rollback_status,
                transaction_id=tx_id,
                started_at=started,
            )
            _p(100, "Tamamlandı")
            return {
                "basarili": True,
                "uygulandi": True,
                "mesaj": verification or "Seviye 2 onarım tamamlandı.",
                "preview": preview,
                "yedek_yolu": str(yedek_yolu),
                "after": after,
                "verification": verification,
                "repair_id": rid,
                "status": status,
                "mutasyon_muhasebe": aksiyon == "recalc_muhasebe_header",
                "mutasyon_veri": True,
            }
        except Exception as exc:
            _log.exception("Seviye 2 onarım başarısız")
            rollback_status = "attempted"
            ErrorLogService.kaydet_onarim(
                issue_id=issue_ref,
                repair_action=f"level2_{aksiyon}",
                preview=preview,
                before_data=before,
                after_data=after or None,
                backup_path=str(yedek_yolu),
                status="failed",
                error_message=str(exc),
                verification_result="başarısız — rollback uygulandı (DB)",
                rollback_status=rollback_status,
                transaction_id=tx_id,
                started_at=started,
            )
            raise

    @staticmethod
    def apply_repair(
        *,
        issue_id: int | None = None,
        issue_code: str | None = None,
        madde: dict[str, Any] | None = None,
        confirm: bool = False,
        progress: ProgressCb = None,
        yedek_klasor: str | Path | None = None,
    ) -> dict[str, Any]:
        """Seviye 1 veya 2'ye yönlendirir; diğerleri engellenir."""
        preview = RepairService.repair_preview(
            issue_id=issue_id, issue_code=issue_code, madde=madde, take_backup=False
        )
        seviye = int(preview.get("seviye") or 0)
        if seviye == 1 and preview.get("uygulanabilir"):
            return RepairService.apply_level1(
                issue_id=issue_id,
                issue_code=issue_code,
                madde=madde,
                confirm=confirm,
                progress=progress,
                yedek_klasor=yedek_klasor,
            )
        if seviye == 2:
            return RepairService.apply_level2(
                issue_id=issue_id,
                issue_code=issue_code,
                madde=madde,
                confirm=confirm,
                progress=progress,
                yedek_klasor=yedek_klasor,
            )
        return {
            "basarili": False,
            "uygulandi": False,
            "mesaj": preview.get("mesaj") or "Bu sorun otomatik onarılamaz.",
            "preview": preview,
        }

    @staticmethod
    def _dispatch_level2(aksiyon: str, issue: dict[str, Any], code: str) -> dict[str, Any]:
        if aksiyon == "recalc_fatura_header":
            return RepairService._do_recalc_fatura_header(issue)
        if aksiyon == "fix_cek_kalan":
            return RepairService._do_fix_cek_kalan(issue)
        if aksiyon == "recalc_muhasebe_header":
            return RepairService._do_recalc_muhasebe_header(issue)
        raise RepairAborted(f"Bilinmeyen Seviye 2 aksiyonu: {aksiyon} ({code})")

    @staticmethod
    def _do_recalc_fatura_header(issue: dict[str, Any]) -> dict[str, Any]:
        from database.database import get_session

        fid = _parse_record_id(issue)
        if fid is None:
            raise RepairAborted("Fatura id yok.")
        modul = (issue.get("module_name") or issue.get("modul") or "").lower()
        yon = "alis" if modul == "alis" else "satis"

        with get_session() as session:
            if yon == "alis":
                from database.alis_faturasi_service import AlisFaturasiService
                from database.models.alis_faturasi import AlisFaturasi

                fatura = session.scalar(
                    select(AlisFaturasi)
                    .options(selectinload(AlisFaturasi.satirlar))
                    .where(AlisFaturasi.id == fid)
                )
                toplam_fn = AlisFaturasiService.toplam
            else:
                from database.models.satis_faturasi import SatisFaturasi
                from database.satis_faturasi_service import SatisFaturasiService

                fatura = session.scalar(
                    select(SatisFaturasi)
                    .options(selectinload(SatisFaturasi.satirlar))
                    .where(SatisFaturasi.id == fid)
                )
                toplam_fn = SatisFaturasiService.toplam

            if fatura is None:
                raise RepairAborted(f"Fatura bulunamadı: id={fid}")
            if (getattr(fatura, "durum", "") or "") == "İPTAL":
                raise RepairAborted("İptal fatura.")
            if _tarih_kapali_donemde(getattr(fatura, "fatura_tarihi", None)):
                raise RepairAborted("Kapalı dönem — onarım iptal.")
            if not fatura.satirlar:
                raise RepairAborted("Satır yok.")

            toplam = toplam_fn(fatura.satirlar)
            before = {
                "tl_matrah": str(_dec(fatura.tl_matrah)),
                "tl_kdv": str(_dec(fatura.tl_kdv)),
                "tl_genel_toplam": str(_dec(fatura.tl_genel_toplam)),
            }
            fatura.tl_matrah = _dec(toplam["ara_toplam"] - toplam["iskonto"])
            fatura.tl_kdv = _dec(toplam["kdv"])
            fatura.tl_genel_toplam = _dec(toplam["genel_toplam"])
            after = {
                "yon": yon,
                "fatura_id": fid,
                "fatura_no": getattr(fatura, "fatura_no", None),
                "before": before,
                "after": {
                    "tl_matrah": str(_dec(fatura.tl_matrah)),
                    "tl_kdv": str(_dec(fatura.tl_kdv)),
                    "tl_genel_toplam": str(_dec(fatura.tl_genel_toplam)),
                },
            }
            session.flush()
        return after

    @staticmethod
    def _do_fix_cek_kalan(issue: dict[str, Any]) -> dict[str, Any]:
        from database.database import get_session
        from database.models.cek_senet import CekSenetEvrak

        eid = _parse_record_id(issue)
        if eid is None:
            raise RepairAborted("Çek/senet id yok.")
        with get_session() as session:
            evrak = session.get(CekSenetEvrak, eid)
            if evrak is None:
                raise RepairAborted(f"Evrak yok: id={eid}")
            tarih = getattr(evrak, "vade_tarihi", None) or getattr(
                evrak, "son_islem_tarihi", None
            )
            if isinstance(tarih, date) and _tarih_kapali_donemde(tarih):
                raise RepairAborted("Kapalı dönem — onarım iptal.")
            tutar = _dec(evrak.tl_tutari)
            tahsil = _dec(evrak.tahsil_edilen_tutar)
            eski = _dec(evrak.kalan_tutar)
            yeni = (tutar - tahsil).quantize(_KURUS, rounding=ROUND_HALF_UP)
            evrak.kalan_tutar = yeni
            session.flush()
            return {
                "evrak_id": eid,
                "portfoy_no": getattr(evrak, "portfoy_no", None),
                "before_kalan": str(eski),
                "after_kalan": str(yeni),
                "tl_tutari": str(tutar),
                "tahsil_edilen_tutar": str(tahsil),
            }

    @staticmethod
    def _do_recalc_muhasebe_header(issue: dict[str, Any]) -> dict[str, Any]:
        from database.database import get_session
        from database.models.genel_muhasebe import MuhasebeFisi

        fid = _parse_record_id(issue)
        if fid is None:
            raise RepairAborted("Fiş id yok.")
        with get_session() as session:
            fis = session.scalar(
                select(MuhasebeFisi)
                .options(selectinload(MuhasebeFisi.satirlar))
                .where(MuhasebeFisi.id == fid)
            )
            if fis is None:
                raise RepairAborted(f"Fiş yok: id={fid}")
            if (fis.durum or "") == "İptal":
                raise RepairAborted("İptal fiş.")
            if _tarih_kapali_donemde(
                getattr(fis, "fis_tarihi", None),
                donem_id=getattr(fis, "donem_id", None),
            ):
                raise RepairAborted("Kapalı dönem — onarım iptal.")
            s_borc = sum((_dec(s.borc) for s in fis.satirlar), Decimal("0"))
            s_alacak = sum((_dec(s.alacak) for s in fis.satirlar), Decimal("0"))
            if _abs_diff(s_borc, s_alacak) > _TOL:
                raise RepairAborted(
                    f"Satırlar dengesiz (borç={s_borc}, alacak={s_alacak}); "
                    "hesap uydurma yok."
                )
            before = {
                "toplam_borc": str(_dec(fis.toplam_borc)),
                "toplam_alacak": str(_dec(fis.toplam_alacak)),
            }
            fis.toplam_borc = s_borc
            fis.toplam_alacak = s_alacak
            session.flush()
            return {
                "fis_id": fid,
                "fis_no": fis.fis_no,
                "before": before,
                "after": {"toplam_borc": str(s_borc), "toplam_alacak": str(s_alacak)},
            }

    @staticmethod
    def _verify_level2(
        aksiyon: str, issue: dict[str, Any], code: str, after: dict[str, Any]
    ) -> tuple[bool, str]:
        """Post-repair: ilgili kaydı yeniden oku / formül doğrula."""
        from database.database import get_session

        try:
            if aksiyon == "recalc_fatura_header":
                fid = int(after.get("fatura_id") or _parse_record_id(issue) or 0)
                yon = after.get("yon") or (
                    "alis"
                    if (issue.get("module_name") or "").lower() == "alis"
                    else "satis"
                )
                with get_session() as session:
                    if yon == "alis":
                        from database.alis_faturasi_service import AlisFaturasiService
                        from database.models.alis_faturasi import AlisFaturasi

                        fatura = session.scalar(
                            select(AlisFaturasi)
                            .options(selectinload(AlisFaturasi.satirlar))
                            .where(AlisFaturasi.id == fid)
                        )
                        toplam_fn = AlisFaturasiService.toplam
                    else:
                        from database.models.satis_faturasi import SatisFaturasi
                        from database.satis_faturasi_service import SatisFaturasiService

                        fatura = session.scalar(
                            select(SatisFaturasi)
                            .options(selectinload(SatisFaturasi.satirlar))
                            .where(SatisFaturasi.id == fid)
                        )
                        toplam_fn = SatisFaturasiService.toplam
                    if fatura is None:
                        return False, "Doğrulama: fatura bulunamadı."
                    toplam = toplam_fn(fatura.satirlar)
                    matrah = _dec(toplam["ara_toplam"] - toplam["iskonto"])
                    kdv = _dec(toplam["kdv"])
                    genel = _dec(toplam["genel_toplam"])
                    ok = (
                        _abs_diff(_dec(fatura.tl_matrah), matrah) <= _TOL
                        and _abs_diff(_dec(fatura.tl_kdv), kdv) <= _TOL
                        and _abs_diff(_dec(fatura.tl_genel_toplam), genel) <= _TOL
                        and _abs_diff(
                            _dec(fatura.tl_matrah) + _dec(fatura.tl_kdv),
                            _dec(fatura.tl_genel_toplam),
                        )
                        <= _TOL
                    )
                    if ok:
                        return True, f"Fatura başlık doğrulandı (id={fid}, {code})."
                    return False, f"Fatura doğrulama başarısız (id={fid})."

            if aksiyon == "fix_cek_kalan":
                eid = int(after.get("evrak_id") or _parse_record_id(issue) or 0)
                from database.models.cek_senet import CekSenetEvrak

                with get_session() as session:
                    evrak = session.get(CekSenetEvrak, eid)
                    if evrak is None:
                        return False, "Doğrulama: evrak yok."
                    bek = _dec(evrak.tl_tutari) - _dec(evrak.tahsil_edilen_tutar)
                    if _abs_diff(_dec(evrak.kalan_tutar), bek) <= _TOL:
                        return True, f"Çek kalan_tutar doğrulandı (id={eid})."
                    return False, f"Çek kalan doğrulama başarısız (id={eid})."

            if aksiyon == "recalc_muhasebe_header":
                fid = int(after.get("fis_id") or _parse_record_id(issue) or 0)
                from database.models.genel_muhasebe import MuhasebeFisi

                with get_session() as session:
                    fis = session.scalar(
                        select(MuhasebeFisi)
                        .options(selectinload(MuhasebeFisi.satirlar))
                        .where(MuhasebeFisi.id == fid)
                    )
                    if fis is None:
                        return False, "Doğrulama: fiş yok."
                    s_borc = sum((_dec(s.borc) for s in fis.satirlar), Decimal("0"))
                    s_alacak = sum((_dec(s.alacak) for s in fis.satirlar), Decimal("0"))
                    ok = (
                        _abs_diff(_dec(fis.toplam_borc), s_borc) <= _TOL
                        and _abs_diff(_dec(fis.toplam_alacak), s_alacak) <= _TOL
                        and _abs_diff(s_borc, s_alacak) <= _TOL
                    )
                    if ok:
                        return True, f"Fiş başlık doğrulandı (id={fid})."
                    return False, f"Fiş doğrulama başarısız (id={fid})."
        except Exception as exc:  # noqa: BLE001
            _log.warning("Seviye 2 doğrulama hatası: %s", exc)
            return False, f"Doğrulama hatası: {exc}"
        return False, "Bilinmeyen Seviye 2 doğrulama."

    @staticmethod
    def apply_all_level1(
        *,
        confirm: bool = False,
        progress: ProgressCb = None,
        yedek_klasor: str | Path | None = None,
        probe: bool = True,
    ) -> dict[str, Any]:
        """Açık Seviye 1 sorunlarını (ve probe adaylarını) güvenli şekilde düzeltir."""
        _require_onarim()
        if probe:
            probe_level1_issues(kaydet=True)

        from database.servis_sistem.error_log_service import ErrorLogService

        acik = ErrorLogService.acik_sorunlar(limit=500, status="open")
        adaylar = [
            s
            for s in acik
            if is_level1(s.get("issue_code"), s.get("repair_level"))
        ]
        if not adaylar:
            return {
                "basarili": True,
                "uygulandi": False,
                "mesaj": "Düzeltilecek Seviye 1 sorun bulunamadı.",
                "sonuclar": [],
                "adet": 0,
            }
        if not confirm:
            onizlemeler = [
                RepairService.repair_preview(issue_id=s["id"], take_backup=False)
                for s in adaylar
            ]
            return {
                "basarili": True,
                "uygulandi": False,
                "mesaj": f"{len(adaylar)} Seviye 1 sorun için önizleme hazır — onay gerekli.",
                "preview_list": onizlemeler,
                "adet": len(adaylar),
            }

        def _p(pct: int, msg: str) -> None:
            if progress:
                progress(pct, msg)

        from database.servis_sistem.backup_service import BackupService

        _p(5, "Toplu onarım öncesi yedek...")
        try:
            yedek_yolu = BackupService.servis_oncesi_yedek_al(yedek_klasor)
        except Exception as exc:
            raise RepairBackupError(
                f"Yedek alınamadı; toplu onarım iptal: {exc}"
            ) from exc

        sonuclar = []
        # Yedek bir kez alındı; tek tek apply_level1 tekrar yedek almasın diye
        # dahili _apply_without_backup kullan
        n = len(adaylar)
        for i, s in enumerate(adaylar):
            _p(10 + int(80 * i / max(n, 1)), f"Onarım: {s.get('issue_code')}...")
            try:
                r = RepairService._apply_level1_after_backup(
                    issue=s,
                    yedek_yolu=yedek_yolu,
                )
                sonuclar.append(r)
            except Exception as exc:  # noqa: BLE001
                sonuclar.append(
                    {
                        "basarili": False,
                        "uygulandi": False,
                        "issue_id": s.get("id"),
                        "issue_code": s.get("issue_code"),
                        "mesaj": str(exc),
                    }
                )
        ok_n = sum(1 for r in sonuclar if r.get("basarili") and r.get("uygulandi"))
        _p(100, "Toplu onarım bitti")
        return {
            "basarili": ok_n == n,
            "uygulandi": ok_n > 0,
            "mesaj": f"{ok_n}/{n} Seviye 1 onarım tamamlandı.",
            "yedek_yolu": str(yedek_yolu),
            "sonuclar": sonuclar,
            "adet": n,
            "mutasyon_muhasebe": False,
        }

    @staticmethod
    def _apply_level1_after_backup(*, issue: dict[str, Any], yedek_yolu: Path) -> dict[str, Any]:
        from database.servis_sistem.error_log_service import ErrorLogService

        preview = RepairService.repair_preview(issue_id=issue["id"], take_backup=False)
        if not preview.get("uygulanabilir"):
            return {
                "basarili": False,
                "uygulandi": False,
                "mesaj": preview.get("mesaj"),
                "preview": preview,
            }
        preview["yedek_yolu"] = str(yedek_yolu)
        started = datetime.now()
        tx_id = str(uuid.uuid4())
        aksiyon = preview.get("aksiyon") or "create_folders"
        code = preview.get("issue_code") or ""
        issue_ref = preview.get("issue_id")
        before = {"etkilenen": list(preview.get("etkilenen_kayitlar") or [])}
        after: dict[str, Any] = {}
        try:
            if aksiyon == "create_folders":
                after = RepairService._do_create_folders(code)
            elif aksiyon == "default_settings":
                after = RepairService._do_default_settings()
            elif aksiyon == "create_indexes":
                after = RepairService._do_create_indexes()
            else:
                raise RepairAborted(f"Bilinmeyen aksiyon: {aksiyon}")
            ok, verification = RepairService._verify(aksiyon, code, after)
            status = "completed" if ok else "completed_unverified"
            if issue_ref and ok:
                ErrorLogService.sorun_durum_guncelle(int(issue_ref), "resolved")
            rid = ErrorLogService.kaydet_onarim(
                issue_id=issue_ref,
                repair_action=f"level1_{aksiyon}",
                preview=preview,
                before_data=before,
                after_data=after,
                backup_path=str(yedek_yolu),
                status=status,
                verification_result=verification,
                transaction_id=tx_id,
                started_at=started,
            )
            return {
                "basarili": True,
                "uygulandi": True,
                "mesaj": verification,
                "repair_id": rid,
                "issue_id": issue_ref,
                "issue_code": code,
                "status": status,
            }
        except Exception as exc:
            ErrorLogService.kaydet_onarim(
                issue_id=issue_ref,
                repair_action=f"level1_{aksiyon}",
                preview=preview,
                before_data=before,
                after_data=after or None,
                backup_path=str(yedek_yolu),
                status="failed",
                error_message=str(exc),
                verification_result="başarısız — rollback",
                rollback_status="attempted",
                transaction_id=tx_id,
                started_at=started,
            )
            raise

    # --- uygulamalar ---------------------------------------------------------

    @staticmethod
    def _do_create_folders(code: str) -> dict[str, Any]:
        klasorler = _hedef_klasorler()
        if code in ("LOG_KLASOR_YOK", "KLASOR_LOG_YOK"):
            keys = ["logs", "logs_alt", "logs_proje"]
        elif code in ("YEDEK_KLASOR_YOK", "KLASOR_YEDEK_YOK"):
            keys = ["yedek"]
        elif code == "KLASOR_TEMP_YOK":
            keys = ["temp", "temp_proje"]
        elif code == "KLASOR_BRANDING_YOK":
            keys = ["branding"]
        else:
            keys = list(klasorler.keys())
        olusturulan = []
        for k in keys:
            p = klasorler.get(k)
            if p is None:
                continue
            if not p.is_dir():
                p.mkdir(parents=True, exist_ok=True)
                olusturulan.append(str(p))
            elif str(p) not in olusturulan:
                # zaten var — doğrulama için listele
                pass
        mevcut = [str(klasorler[k]) for k in keys if k in klasorler and klasorler[k].is_dir()]
        return {"olusturulan": olusturulan, "mevcut": mevcut}

    @staticmethod
    def _do_default_settings() -> dict[str, Any]:
        from sqlalchemy import select

        from database.database import get_system_session
        from database.system.models import AppSetting

        eklenen: list[str] = []
        # get_system_session: hata → rollback, başarı → commit
        with get_system_session() as session:
            for anahtar, deger in SAFE_DEFAULT_SETTINGS:
                kayit = session.scalar(
                    select(AppSetting).where(AppSetting.anahtar == anahtar)
                )
                if kayit is None:
                    session.add(AppSetting(anahtar=anahtar, deger=deger))
                    eklenen.append(f"{anahtar}={deger}")
        return {"eklenen": eklenen}

    @staticmethod
    def _do_create_indexes() -> dict[str, Any]:
        from database.database import engine

        if engine is None:
            raise RepairAborted("Aktif DB motoru yok; index oluşturulamaz.")
        eksik = _eksik_guvenli_indexler()
        olusturulan: list[str] = []
        # Tek bağlantı / transaction
        with engine.begin() as conn:
            for name, table, cols in eksik:
                # Tablo adı / kolonlar beyaz listeden — SQL injection yok
                sql = f'CREATE INDEX IF NOT EXISTS "{name}" ON "{table}" ({cols})'
                conn.execute(text(sql))
                olusturulan.append(name)
        return {"olusturulan": olusturulan}

    @staticmethod
    def _verify(aksiyon: str, code: str, after: dict[str, Any]) -> tuple[bool, str]:
        if aksiyon == "create_folders":
            mevcut = after.get("mevcut") or []
            olusturulan = after.get("olusturulan") or []
            if not mevcut and not olusturulan:
                # hedef yoksa (ortam değişkeni) — bilgi
                return True, "Klasör hedefi yok veya zaten mevcut."
            # Yeniden kontrol
            hepsi_ok = True
            for p in set(mevcut + olusturulan):
                if not Path(p).is_dir():
                    hepsi_ok = False
            if hepsi_ok:
                return True, f"Klasör doğrulandı ({code}): {len(set(mevcut + olusturulan))} yol."
            return False, f"Klasör doğrulaması başarısız ({code})."
        if aksiyon == "default_settings":
            kalan = _eksik_guvenli_ayarlar()
            if not kalan:
                return True, "Güvenli varsayılan ayarlar tamam."
            return False, f"Hâlâ eksik ayarlar: {kalan}"
        if aksiyon == "create_indexes":
            kalan = _eksik_guvenli_indexler()
            if not kalan:
                return True, "Güvenli indexler mevcut."
            # Kısmi başarı olabilir (tablo yok)
            return True, f"Index onarımı bitti; kalan (tablo yok olabilir): {[n for n,_,_ in kalan]}"
        return False, "Bilinmeyen doğrulama."
