"""Modül bazlı tanı — Aşama 3 derin salt okunur taramalar."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Callable

from database.servis_sistem.scanners import DEEP_ORDER, run_scanners
from database.servis_sistem.scanners.common import item, persist_rapor
from database.servis_sistem.system_health_service import (
    SEVERITY_INFO,
    CheckItem,
    CheckReport,
)

ProgressCb = Callable[[int, str], None] | None

# Ana menü / iş modülleri — tarama listesi
MODULLER: list[dict[str, str]] = [
    {"kod": "sistem", "ad": "Sistem / Altyapı"},
    {"kod": "veritabani", "ad": "Veritabanı"},
    {"kod": "branding", "ad": "Marka / Kaynaklar"},
    {"kod": "cari", "ad": "Cari"},
    {"kod": "stok", "ad": "Stok"},
    {"kod": "satis", "ad": "Satışlar"},
    {"kod": "alis", "ad": "Satın Alma"},
    {"kod": "finans", "ad": "Finans"},
    {"kod": "cek_senet", "ad": "Çek / Senet"},
    {"kod": "gelir_gider", "ad": "Gelir / Gider"},
    {"kod": "muhasebe", "ad": "Genel Muhasebe"},
    {"kod": "doviz", "ad": "Döviz"},
    {"kod": "evobulut", "ad": "EvoBulut Aktarım"},
    {"kod": "yedekleme", "ad": "Yedekleme"},
]


class ModuleDiagnosticService:
    @staticmethod
    def modul_listesi() -> list[dict[str, str]]:
        return list(MODULLER)

    @staticmethod
    def scan_module(
        modul_kod: str,
        progress: ProgressCb = None,
        *,
        kaydet: bool = True,
    ) -> dict[str, Any]:
        """Seçili modül derin taraması — salt okunur."""
        if progress:
            progress(10, f"{modul_kod} hazırlanıyor...")
        ad = next((m["ad"] for m in MODULLER if m["kod"] == modul_kod), modul_kod)
        rapor = CheckReport(
            baslik=f"Modül Tarama: {ad}",
            baslangic=datetime.now().strftime("%d.%m.%Y %H:%M:%S"),
            mutasyon_yapildi=False,
        )

        if progress:
            progress(30, f"{ad} taranıyor...")

        if modul_kod == "veritabani":
            from database.servis_sistem.database_integrity_service import (
                DatabaseIntegrityService,
            )

            alt = DatabaseIntegrityService.run_readonly_check(
                progress=lambda p, m: progress(30 + p * 50 // 100, m) if progress else None,
                kaydet=False,
            )
            for m in alt.get("maddeler") or []:
                rapor.ekle(CheckItem(**{k: m[k] for k in CheckItem.__dataclass_fields__ if k in m}))
        elif modul_kod == "gelir_gider":
            ModuleDiagnosticService._scan_gelir_gider(rapor)
        elif modul_kod in ("doviz", "evobulut"):
            rapor.ekle(
                item(
                    durum=SEVERITY_INFO,
                    modul=modul_kod,
                    hata_kodu="MODUL_HAFIF",
                    aciklama=f"'{ad}' için özel bütünlük kuralları henüz tanımlı değil.",
                    onerilen="Hızlı Kontrol veya ilgili iş ekranlarından doğrulayın.",
                )
            )
        elif run_scanners(modul_kod, rapor):
            pass
        else:
            rapor.ekle(
                item(
                    durum=SEVERITY_INFO,
                    modul=modul_kod,
                    hata_kodu="MODUL_TANIMSIZ",
                    aciklama=f"'{ad}' için tarayıcı eşlemesi yok.",
                )
            )

        if kaydet:
            if progress:
                progress(90, "Sorunlar kaydediliyor...")
            persist_rapor(rapor)

        rapor.ozeti_hesapla()
        if progress:
            progress(100, "Tamamlandı")
        return rapor.to_dict()

    @staticmethod
    def _scan_gelir_gider(rapor: CheckReport) -> None:
        from database.servis_sistem.scanners.common import (
            MAX_ORNEK,
            TOL,
            SEVERITY_UYARI,
            fetchall,
            get_engine,
            has_table,
            ok_yok,
            tablo_yok,
        )

        eng = get_engine()
        if eng is None or not has_table(eng, "gider_fisleri"):
            tablo_yok(rapor, "gelir_gider", "gider_fisleri")
            return
        # Sıfır / negatif tutar
        rows = fetchall(
            eng,
            """
            SELECT id, belge_no, tutar FROM gider_fisleri
            WHERE COALESCE(tutar, 0) <= 0 AND COALESCE(durum, '') != 'IPTAL'
            LIMIT :lim
            """,
            {"lim": MAX_ORNEK},
        )
        if rows:
            for r in rows:
                rapor.ekle(
                    item(
                        durum=SEVERITY_UYARI,
                        modul="gelir_gider",
                        hata_kodu="GIDER_SIFIR_TUTAR",
                        aciklama=f"Sıfır/negatif gider fişi: {r['belge_no']}",
                        kayit_belge=f"id={r['id']}",
                        teknik=f"tutar={r['tutar']}",
                        onerilen="Gider fişi tutarını kontrol edin.",
                    )
                )
        else:
            ok_yok(rapor, "gelir_gider", "GIDER_TUTAR_OK", "Sıfır tutarlı gider fişi yok.")

        # Orphan finans hesap
        n = fetchall(
            eng,
            """
            SELECT COUNT(*) AS n FROM gider_fisleri g
            WHERE g.finans_hesap_id IS NOT NULL
              AND NOT EXISTS (
                SELECT 1 FROM finans_hesaplari h WHERE h.id = g.finans_hesap_id
              )
            """,
        )[0]["n"]
        if n:
            rapor.ekle(
                item(
                    durum=SEVERITY_UYARI,
                    modul="gelir_gider",
                    hata_kodu="GIDER_HESAP_YETIM",
                    aciklama=f"Gider fişinde geçersiz finans hesabı: {n}",
                    teknik=f"count={n}",
                    onerilen="Finans hesap bağlantısını düzeltin.",
                )
            )
        else:
            ok_yok(rapor, "gelir_gider", "GIDER_HESAP_OK", "Gider fişi hesap referansları geçerli.")
        _ = TOL  # reserved for future amount checks

    @staticmethod
    def scan_all_modules(
        progress: ProgressCb = None,
        *,
        kaydet: bool = True,
        include_quick: bool = True,
    ) -> dict[str, Any]:
        """Hızlı kontrol + tüm derin modül taramaları — salt okunur."""
        from database.servis_sistem.system_health_service import SystemHealthService

        rapor = CheckReport(
            baslik="Tüm Sistem / Ayrıntılı Tarama",
            baslangic=datetime.now().strftime("%d.%m.%Y %H:%M:%S"),
            mutasyon_yapildi=False,
        )

        start_pct = 0
        if include_quick:
            def _wrap(pct: int, msg: str) -> None:
                if progress:
                    progress(min(25, pct * 25 // 100), msg)

            if progress:
                progress(5, "Hızlı kontrol...")
            hizli = SystemHealthService.run_quick_check(progress=_wrap, kaydet=False)
            for m in hizli.get("maddeler") or []:
                rapor.ekle(CheckItem(**{k: m[k] for k in CheckItem.__dataclass_fields__ if k in m}))
            start_pct = 25

        # DB integrity
        if progress:
            progress(start_pct + 5, "Veritabanı salt okunur...")
        from database.servis_sistem.database_integrity_service import DatabaseIntegrityService

        db_rap = DatabaseIntegrityService.run_readonly_check(kaydet=False)
        for m in db_rap.get("maddeler") or []:
            rapor.ekle(CheckItem(**{k: m[k] for k in CheckItem.__dataclass_fields__ if k in m}))

        mods = list(DEEP_ORDER)
        # gelir_gider ekle
        if "gelir_gider" not in mods:
            mods.append("gelir_gider")
        n = len(mods)
        for i, kod in enumerate(mods):
            if progress:
                pct = start_pct + 10 + int((i / max(n, 1)) * (85 - start_pct))
                progress(pct, f"Modül: {kod}...")
            if kod == "gelir_gider":
                ModuleDiagnosticService._scan_gelir_gider(rapor)
            else:
                run_scanners(kod, rapor)

        if kaydet:
            if progress:
                progress(92, "Sorunlar kaydediliyor...")
            persist_rapor(rapor)

        rapor.ozeti_hesapla()
        if progress:
            progress(100, "Tamamlandı")
        return rapor.to_dict()

    @staticmethod
    def repair_preview_stub(issue_id: int | None = None) -> dict[str, Any]:
        """Geriye uyumluluk — RepairService.repair_preview."""
        from database.servis_sistem.repair_service import RepairService

        if issue_id is None:
            return {
                "uygulanabilir": False,
                "mesaj": "Önizleme için bir sorun seçin (Seviye 1).",
                "issue_id": None,
                "risk": "yok",
            }
        return RepairService.repair_preview(issue_id=issue_id, take_backup=False)
