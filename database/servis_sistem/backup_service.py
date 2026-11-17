"""Yedekleme servisi — SQLite dosya kopyası veya PostgreSQL pg_dump.

Hedefler: Bu Bilgisayar / USB Bellek / Google Drive.
Google Drive klasörüne kopya, bulut senkronu doğrulanmadan «yükleme tamamlandı» sayılmaz.
Aktarım başarısızsa yerel hazır yedek korunur.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import time
from datetime import datetime
from pathlib import Path
from typing import Callable

from database.session_manager import oturum
from database.system.company_service import CompanyMgmtService

ProgressCb = Callable[[str, float | None], None]

HEDEF_BU_BILGISAYAR = "bu_bilgisayar"
HEDEF_USB = "usb"
HEDEF_GOOGLE_DRIVE = "google_drive"

HEDEF_ETIKET = {
    HEDEF_BU_BILGISAYAR: "Bu Bilgisayar",
    HEDEF_USB: "USB Bellek",
    HEDEF_GOOGLE_DRIVE: "Google Drive",
}


class BackupService:
    """Sistem → Yedek Al — bağlantı kipine göre SQLite veya PostgreSQL."""

    @staticmethod
    def yedek_al(hedef_klasor: str | Path | None = None) -> Path:
        """Geriye uyum: klasöre yedek; sonuç klasör veya tek dosya yolu."""
        sonuc = BackupService.yedek_al_gelismis(
            HEDEF_BU_BILGISAYAR, hedef_klasor=hedef_klasor
        )
        if not sonuc.get("ok"):
            raise RuntimeError(sonuc.get("mesaj") or "Yedek alınamadı.")
        return Path(sonuc["sonuc_yolu"])

    @staticmethod
    def yedek_al_gelismis(
        hedef_turu: str,
        *,
        hedef_klasor: str | Path | None = None,
        progress: ProgressCb | None = None,
    ) -> dict:
        """Tam yedek akışı. Başarısız aktarımda yerel_yedek korunur."""
        if oturum.company_id is None:
            raise ValueError("Aktif firma seçili değil; yedek alınamaz.")
        if not oturum.has_permission("yedek_alma") and oturum.role_kod != "YONETICI":
            raise PermissionError("Yedek alma yetkiniz yok.")

        def _p(msg: str, pct: float | None = None) -> None:
            if progress:
                progress(msg, pct)

        hedef_turu = (hedef_turu or HEDEF_BU_BILGISAYAR).strip().lower()
        if hedef_turu not in HEDEF_ETIKET:
            raise ValueError(f"Geçersiz hedef: {hedef_turu}")

        from database.baglanti_modu import ayari_yukle

        ayar = ayari_yukle()
        damga = datetime.now().strftime("%Y%m%d_%H%M%S")
        yerel_kok = BackupService.yedek_klasoru_onerisi() / f"YEDEK_{damga}"
        yerel_kok.mkdir(parents=True, exist_ok=True)

        sonuc: dict = {
            "ok": False,
            "hedef_turu": hedef_turu,
            "hedef_etiket": HEDEF_ETIKET[hedef_turu],
            "yerel_yedek": str(yerel_kok),
            "sonuc_yolu": str(yerel_kok),
            "kipi": ayar.kipi,
            "bulut_durum": "uygulanmaz",
            "aktarim_ok": False,
            "mesaj": "",
            "dosyalar": [],
        }

        try:
            _p("Yedek hazırlanıyor…", 5)
            if ayar.ag_mi:
                hazir = BackupService._pg_yedek_hazirla(yerel_kok, ayar, _p)
            else:
                hazir = BackupService._sqlite_yedek_hazirla(yerel_kok, _p)
            sonuc["dosyalar"] = hazir.get("dosyalar") or []
            sonuc["dogrulama"] = hazir.get("dogrulama") or {}
            if not hazir.get("ok"):
                sonuc["mesaj"] = hazir.get("mesaj") or "Yedek hazırlanamadı."
                return sonuc

            _p("Yerel yedek doğrulandı.", 55)
            hedef_kok = BackupService._hedef_kok_coz(
                hedef_turu, hedef_klasor=hedef_klasor, damga=damga
            )
            sonuc["hedef_kok"] = str(hedef_kok)

            if hedef_turu == HEDEF_BU_BILGISAYAR and Path(hedef_kok).resolve() == yerel_kok.resolve():
                sonuc["ok"] = True
                sonuc["aktarim_ok"] = True
                sonuc["sonuc_yolu"] = str(yerel_kok)
                sonuc["mesaj"] = f"Yedek alındı (Bu Bilgisayar):\n{yerel_kok}"
                _p("Tamam.", 100)
                BackupService._audit(str(yerel_kok))
                return sonuc

            _p(f"{HEDEF_ETIKET[hedef_turu]} konumuna kopyalanıyor…", 60)
            try:
                BackupService._klasor_kopyala(yerel_kok, Path(hedef_kok), _p)
                BackupService._kopya_dogrula(yerel_kok, Path(hedef_kok))
                sonuc["aktarim_ok"] = True
                sonuc["sonuc_yolu"] = str(hedef_kok)
            except Exception as exc:  # noqa: BLE001
                sonuc["ok"] = False
                sonuc["aktarim_ok"] = False
                sonuc["sonuc_yolu"] = str(yerel_kok)
                sonuc["mesaj"] = (
                    f"Hedefe aktarım başarısız: {exc}\n"
                    f"Yerel yedek korundu:\n{yerel_kok}"
                )
                if hedef_turu == HEDEF_GOOGLE_DRIVE:
                    sonuc["bulut_durum"] = "basarisiz"
                _p("Aktarım başarısız — yerel yedek duruyor.", None)
                return sonuc

            if hedef_turu == HEDEF_GOOGLE_DRIVE:
                _p("Google Drive bulut senkronu kontrol ediliyor…", 85)
                bulut = BackupService._google_drive_senkron_dogrula(Path(hedef_kok), _p)
                sonuc["bulut_durum"] = bulut["durum"]
                sonuc["bulut_ayrinti"] = bulut.get("ayrinti")
                sonuc["bulut_yukleme_tamam"] = bulut["durum"] == "tamamlandi"
                # Yerel Drive klasörüne kopya başarılı → veri güvende; bulut ayrı bayrak
                sonuc["ok"] = True
                if sonuc["bulut_yukleme_tamam"]:
                    sonuc["mesaj"] = (
                        f"Yedek Google Drive'a yüklendi (senkron doğrulandı):\n{hedef_kok}\n"
                        f"Yerel kopya: {yerel_kok}"
                    )
                else:
                    sonuc["mesaj"] = (
                        f"Yerel Google Drive klasörüne kopyalandı; bulut yüklemesi "
                        f"doğrulanmadı ({bulut.get('ayrinti') or bulut['durum']}).\n"
                        f"Durum: yükleme tamamlandı DEĞİL — Drive istemcisinden kontrol edin.\n"
                        f"Drive yolu: {hedef_kok}\n"
                        f"Yerel yedek korundu: {yerel_kok}"
                    )
                _p(sonuc["mesaj"].split("\n")[0], 100)
                BackupService._audit(str(hedef_kok))
                return sonuc

            sonuc["ok"] = True
            sonuc["mesaj"] = (
                f"Yedek alındı ({HEDEF_ETIKET[hedef_turu]}):\n{hedef_kok}\n"
                f"Yerel kopya: {yerel_kok}"
            )
            _p("Tamam.", 100)
            BackupService._audit(str(hedef_kok))
            return sonuc
        except Exception as exc:  # noqa: BLE001
            sonuc["ok"] = False
            sonuc["sonuc_yolu"] = str(yerel_kok) if yerel_kok.exists() else ""
            sonuc["mesaj"] = f"Yedek hatası: {exc}"
            if yerel_kok.exists():
                sonuc["mesaj"] += f"\nYerel hazırlık klasörü: {yerel_kok}"
            return sonuc

    @staticmethod
    def _audit(yeni_deger: str) -> None:
        try:
            from database.system.auth_service import AuthService
            from database.database import get_system_session

            with get_system_session() as session:
                AuthService.audit(
                    session,
                    "yedekleme",
                    modul="servis",
                    kayit_id=str(oturum.company_id or ""),
                    yeni_deger=yeni_deger,
                )
        except Exception:
            pass

    @staticmethod
    def _sqlite_yedek_hazirla(yerel_kok: Path, _p: ProgressCb) -> dict:
        _p("SQLite firma yedeği kopyalanıyor…", 20)
        db_yol = CompanyMgmtService.yedek_al(int(oturum.company_id), yerel_kok)
        BackupService.dogrula_yedek(db_yol)
        # Bağlantı / ayar kopyaları
        BackupService._ek_dosyalari_kopyala(yerel_kok)
        bilgi = {
            "format": "cin-yedek-sqlite-v1",
            "zaman": datetime.now().isoformat(timespec="seconds"),
            "firma_db": str(db_yol),
            "boyut": db_yol.stat().st_size,
        }
        (yerel_kok / "YEDEK_BILGI.json").write_text(
            json.dumps(bilgi, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        return {
            "ok": True,
            "dosyalar": [str(db_yol)],
            "dogrulama": {"integrity": "ok", "boyut": db_yol.stat().st_size},
        }

    @staticmethod
    def _pg_yedek_hazirla(yerel_kok: Path, ayar, _p: ProgressCb) -> dict:
        from database.baglanti_modu import postgres_parola_al

        pwd = postgres_parola_al()
        if not pwd:
            return {
                "ok": False,
                "mesaj": "PostgreSQL parolası yok (keyring / MUHASEBE_PG_PASSWORD).",
            }
        pg_bin = Path(r"C:\Program Files\PostgreSQL\17\bin")
        pg_dump = pg_bin / "pg_dump.exe"
        pg_restore = pg_bin / "pg_restore.exe"
        if not pg_dump.is_file():
            return {"ok": False, "mesaj": f"pg_dump bulunamadı: {pg_dump}"}

        pg = ayar.postgres
        sistem_db = pg.sistem_db
        firma_db = pg.firma_db
        if not firma_db:
            return {"ok": False, "mesaj": "Aktif firma PostgreSQL veritabanı adı yok."}

        db_dir = yerel_kok / "01_veritabani"
        db_dir.mkdir(parents=True, exist_ok=True)
        env = {**os.environ, "PGPASSWORD": pwd}
        dosyalar: list[str] = []
        dogrulama: dict = {"dumps": []}

        for i, db in enumerate((sistem_db, firma_db)):
            _p(f"pg_dump: {db}", 15 + i * 20)
            hedef = db_dir / f"{db}.dump"
            r = subprocess.run(
                [
                    str(pg_dump),
                    "-h",
                    pg.host,
                    "-p",
                    str(pg.port),
                    "-U",
                    pg.kullanici,
                    "-d",
                    db,
                    "-Fc",
                    "-f",
                    str(hedef),
                ],
                capture_output=True,
                text=True,
                env=env,
                timeout=1800,
            )
            if r.returncode != 0 or not hedef.is_file() or hedef.stat().st_size <= 0:
                return {
                    "ok": False,
                    "mesaj": f"pg_dump başarısız ({db}): {(r.stderr or r.stdout or '')[:300]}",
                }
            liste_ok = False
            liste_satir = 0
            if pg_restore.is_file():
                lr = subprocess.run(
                    [str(pg_restore), "-l", str(hedef)],
                    capture_output=True,
                    text=True,
                    timeout=180,
                )
                liste_ok = lr.returncode == 0
                liste_satir = len((lr.stdout or "").splitlines())
            if not liste_ok:
                return {
                    "ok": False,
                    "mesaj": f"Dump doğrulama (pg_restore -l) başarısız: {db}",
                }
            dosyalar.append(str(hedef))
            dogrulama["dumps"].append(
                {
                    "db": db,
                    "boyut": hedef.stat().st_size,
                    "liste_satir": liste_satir,
                    "liste_ok": True,
                }
            )

        _p("Ayar ve ek dosyalar…", 50)
        BackupService._ek_dosyalari_kopyala(yerel_kok)
        bilgi = {
            "format": "cin-yedek-pg-v1",
            "zaman": datetime.now().isoformat(timespec="seconds"),
            "pg_host": pg.host,
            "pg_port": pg.port,
            "pg_kullanici": pg.kullanici,
            "sistem_db": sistem_db,
            "firma_db": firma_db,
            "dumps": dogrulama["dumps"],
            "not": "Ham PostgreSQL data klasörü kopyalanmadı; pg_dump -Fc kullanıldı. Parola yok.",
        }
        (yerel_kok / "YEDEK_BILGI.json").write_text(
            json.dumps(bilgi, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        (yerel_kok / "GERI_YUKLEME.txt").write_text(
            "\n".join(
                [
                    "PostgreSQL geri yükleme (ayrı test DB'de deneyin; canlıyı ezmeyin)",
                    f"1) CREATE DATABASE {sistem_db}; CREATE DATABASE {firma_db};",
                    f"2) pg_restore -d {sistem_db} --no-owner 01_veritabani/{sistem_db}.dump",
                    f"3) pg_restore -d {firma_db} --no-owner 01_veritabani/{firma_db}.dump",
                    "4) baglanti_ayari.json ve sertifikayı EXE yanına koyun",
                ]
            ),
            encoding="utf-8",
        )
        return {"ok": True, "dosyalar": dosyalar, "dogrulama": dogrulama}

    @staticmethod
    def _ek_dosyalari_kopyala(yerel_kok: Path) -> None:
        ek = yerel_kok / "02_ayar_ve_ek"
        ek.mkdir(parents=True, exist_ok=True)
        adaylar: list[Path] = []
        try:
            from database.database import program_klasoru

            adaylar.append(program_klasoru() / "baglanti_ayari.json")
        except Exception:
            pass
        local = Path(os.environ.get("LOCALAPPDATA") or "") / "CinMuhasebe"
        if local.is_dir():
            adaylar.extend(local.rglob("baglanti_ayari.json"))
        ca = Path(os.environ.get("APPDATA") or "") / "postgresql" / "root.crt"
        if ca.is_file():
            shutil.copy2(ca, ek / "postgresql_root.crt")
        seen: set[str] = set()
        for i, p in enumerate(adaylar):
            if not p.is_file():
                continue
            key = str(p.resolve()).lower()
            if key in seen:
                continue
            seen.add(key)
            shutil.copy2(p, ek / f"baglanti_ayari_{i}.json")

    @staticmethod
    def _hedef_kok_coz(
        hedef_turu: str,
        *,
        hedef_klasor: str | Path | None,
        damga: str,
    ) -> Path:
        if hedef_klasor:
            kok = Path(hedef_klasor)
            if kok.exists() and kok.is_file():
                raise ValueError("Hedef bir klasör olmalıdır.")
            # Kullanıcı üst klasör seçtiyse alt YEDEK_ damgası aç
            if kok.name.startswith("YEDEK_"):
                return kok
            return kok / f"YEDEK_{damga}"

        if hedef_turu == HEDEF_BU_BILGISAYAR:
            return BackupService.yedek_klasoru_onerisi() / f"YEDEK_{damga}"

        if hedef_turu == HEDEF_USB:
            suruculer = BackupService.usb_suruculeri()
            if not suruculer:
                raise ValueError("Takılı USB bellek bulunamadı.")
            # Tek USB varsa onu kullan; birden fazlaysa ilkini (UI seçtirir)
            return Path(suruculer[0]["yol"]) / "CinMuhasebe_Yedekler" / f"YEDEK_{damga}"

        if hedef_turu == HEDEF_GOOGLE_DRIVE:
            gd = BackupService.google_drive_klasoru_bul()
            if gd is None:
                raise ValueError(
                    "Google Drive klasörü bulunamadı (G:\\Drive'ım veya Google Drive)."
                )
            return gd / "CinMuhasebe_Yedekler" / f"YEDEK_{damga}"

        raise ValueError(hedef_turu)

    @staticmethod
    def _klasor_kopyala(src: Path, dst: Path, _p: ProgressCb) -> None:
        dst.parent.mkdir(parents=True, exist_ok=True)
        if dst.exists():
            raise ValueError(f"Hedef zaten var: {dst}")
        # copytree; büyük dosyalarda ara durum
        dosyalar = [p for p in src.rglob("*") if p.is_file()]
        toplam = max(len(dosyalar), 1)
        for i, f in enumerate(dosyalar):
            rel = f.relative_to(src)
            hedef = dst / rel
            hedef.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(f, hedef)
            if i % 5 == 0 or i + 1 == toplam:
                _p(f"Kopyalanıyor ({i + 1}/{toplam}): {rel}", 60 + 20 * (i + 1) / toplam)

    @staticmethod
    def _kopya_dogrula(src: Path, dst: Path) -> None:
        for f in src.rglob("*"):
            if not f.is_file():
                continue
            rel = f.relative_to(src)
            h = dst / rel
            if not h.is_file():
                raise ValueError(f"Hedefte eksik: {rel}")
            if h.stat().st_size != f.stat().st_size:
                raise ValueError(f"Boyut uyuşmuyor: {rel}")

    @staticmethod
    def _sha256(path: Path) -> str:
        h = hashlib.sha256()
        with path.open("rb") as f:
            for chunk in iter(lambda: f.read(1024 * 1024), b""):
                h.update(chunk)
        return h.hexdigest().upper()

    @staticmethod
    def _google_drive_senkron_dogrula(hedef_kok: Path, _p: ProgressCb) -> dict:
        """Bulut yüklemesini doğrulamaya çalışır; emin değilse tamamlandi demez."""
        if not hedef_kok.is_dir():
            return {"durum": "basarisiz", "ayrinti": "Hedef klasör yok"}

        # Boyut stabilitesi
        def _boyut() -> int:
            return sum(p.stat().st_size for p in hedef_kok.rglob("*") if p.is_file())

        onceki = -1
        stabil = 0
        for _ in range(12):
            b = _boyut()
            if b == onceki and b > 0:
                stabil += 1
                if stabil >= 3:
                    break
            else:
                stabil = 0
                onceki = b
            _p("Drive klasörü yazılıyor / senkron bekleniyor…", None)
            time.sleep(1.0)

        # Geçici yükleme artıkları
        artik = list(hedef_kok.rglob("*.tmp")) + list(hedef_kok.rglob("~*"))
        if artik:
            return {
                "durum": "dogrulanamadi",
                "ayrinti": f"Geçici dosya var: {artik[0].name}",
            }

        # Cloud Filter / placeholder bayrakları (yükleme sırasında değişebilir)
        try:
            import ctypes

            GetFileAttributesW = ctypes.windll.kernel32.GetFileAttributesW
            GetFileAttributesW.argtypes = [ctypes.c_wchar_p]
            GetFileAttributesW.restype = ctypes.c_uint32
            INVALID = 0xFFFFFFFF
            RECALL_ON_DATA_ACCESS = 0x00400000
            RECALL_ON_OPEN = 0x00040000
            for f in hedef_kok.rglob("*"):
                if not f.is_file():
                    continue
                attr = GetFileAttributesW(str(f))
                if attr == INVALID:
                    continue
                if attr & (RECALL_ON_DATA_ACCESS | RECALL_ON_OPEN):
                    return {
                        "durum": "dogrulanamadi",
                        "ayrinti": f"Dosya bulut yer tutucu / henüz yerelde değil: {f.name}",
                    }
        except Exception as exc:  # noqa: BLE001
            return {
                "durum": "dogrulanamadi",
                "ayrinti": f"Öznitelik okunamadı: {exc}",
            }

        # DriveFS süreci yoksa senkron iddia edilemez
        try:
            r = subprocess.run(
                [
                    "powershell",
                    "-NoProfile",
                    "-Command",
                    "Get-Process GoogleDrive* , DriveFS* -ErrorAction SilentlyContinue | Select-Object -First 1 -ExpandProperty ProcessName",
                ],
                capture_output=True,
                text=True,
                timeout=20,
            )
            proc = (r.stdout or "").strip()
        except Exception:
            proc = ""
        if not proc:
            return {
                "durum": "dogrulanamadi",
                "ayrinti": "Google Drive istemci süreci görülmedi; bulut yüklemesi doğrulanamadı",
            }

        # Desteklenen kesin API yok: yerel kopya + stabil + istemci var ≠ bulut tamam
        return {
            "durum": "dogrulanamadi",
            "ayrinti": (
                "Yerel Drive klasörüne kopya doğrulandı; Google Drive bulut "
                "yükleme tamam sinyali bu ortamda kesin doğrulanamıyor"
            ),
        }

    @staticmethod
    def google_drive_klasoru_bul() -> Path | None:
        adaylar = [
            Path(r"G:\Drive'ım"),
            Path(os.path.expanduser(r"~\Google Drive")),
            Path(os.path.expanduser(r"~\GoogleDrive")),
            Path(r"G:\My Drive"),
        ]
        # Ortam / bilinen kökler
        for root in (Path("G:/"), Path(os.path.expanduser("~"))):
            if not root.exists():
                continue
            try:
                for p in root.iterdir():
                    n = p.name.lower()
                    if p.is_dir() and (
                        "drive" in n and ("ım" in p.name or "im" in n or "my" in n)
                    ):
                        adaylar.append(p)
            except OSError:
                pass
        for a in adaylar:
            try:
                if a.is_dir():
                    return a
            except OSError:
                continue
        return None

    @staticmethod
    def usb_suruculeri() -> list[dict]:
        """Çıkarılabilir (USB) sürücüler."""
        liste: list[dict] = []
        try:
            r = subprocess.run(
                [
                    "powershell",
                    "-NoProfile",
                    "-Command",
                    "Get-CimInstance Win32_LogicalDisk | "
                    "Where-Object { $_.DriveType -eq 2 } | "
                    "Select-Object DeviceID,VolumeName,Size,FreeSpace | ConvertTo-Json -Compress",
                ],
                capture_output=True,
                text=True,
                timeout=30,
            )
            raw = (r.stdout or "").strip()
            if not raw:
                return liste
            data = json.loads(raw)
            if isinstance(data, dict):
                data = [data]
            for d in data:
                did = (d.get("DeviceID") or "").strip()
                if not did:
                    continue
                liste.append(
                    {
                        "yol": did + "\\",
                        "ad": d.get("VolumeName") or did,
                        "bos": int(d.get("FreeSpace") or 0),
                        "toplam": int(d.get("Size") or 0),
                    }
                )
        except Exception:
            pass
        return liste

    @staticmethod
    def yedek_klasoru_onerisi() -> Path:
        local = (os.environ.get("LOCALAPPDATA") or "").strip()
        if local:
            yol = Path(local) / "CinMuhasebe" / "yedekler"
        else:
            from database.database import PROJE_DATA_DIR

            yol = PROJE_DATA_DIR / "yedekler"
        yol.mkdir(parents=True, exist_ok=True)
        return yol

    @staticmethod
    def servis_oncesi_yedek_adi(damga: datetime | None = None) -> str:
        d = damga or datetime.now()
        return f"CinMuhasebe_ServisOncesi_{d.strftime('%Y-%m-%d_%H%M%S')}.db"

    @staticmethod
    def dogrula_yedek(yol: Path) -> Path:
        """Dosya var ve boyut > 0; aksi halde ValueError."""
        p = Path(yol)
        if not p.is_file():
            raise ValueError(f"Yedek dosyası oluşmadı: {p}")
        size = p.stat().st_size
        if size <= 0:
            raise ValueError(f"Yedek dosyası boş (0 bayt): {p}")
        return p

    @staticmethod
    def geri_yukle_dogrula(
        yedek_yolu: str | Path,
        *,
        hedef_kopya: str | Path | None = None,
    ) -> dict:
        """Yedeği geçici kopyaya açıp okunabilirliğini doğrular (SQLite).

        Canlı firma DB'sine yazmaz / üzerine yazmaz.
        """
        import sqlite3
        import tempfile

        kaynak = BackupService.dogrula_yedek(Path(yedek_yolu))
        if hedef_kopya is None:
            tmp = Path(tempfile.gettempdir()) / "cin_devir_yedek_test"
            tmp.mkdir(parents=True, exist_ok=True)
            hedef = tmp / f"restore_check_{datetime.now().strftime('%Y%m%d_%H%M%S')}.db"
        else:
            hedef = Path(hedef_kopya)
            hedef.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(kaynak, hedef)
        for ek in ("-wal", "-shm"):
            k = Path(str(kaynak) + ek)
            if k.is_file():
                shutil.copy2(k, Path(str(hedef) + ek))

        sayimlar: dict[str, int] = {}
        with sqlite3.connect(f"file:{hedef}?mode=ro", uri=True) as conn:
            ok = conn.execute("PRAGMA integrity_check").fetchone()
            if not ok or str(ok[0]).lower() != "ok":
                raise ValueError(f"Yedek integrity_check başarısız: {ok}")
            tablolar = [
                r[0]
                for r in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
                ).fetchall()
            ]
            for ad in (
                "cari_kartlar",
                "cari_satis_hareketleri",
                "finans_hesaplari",
                "finans_hareketleri",
                "stok_kartlari",
                "donemler",
                "devir_isleri",
                "devir_eslesmeler",
            ):
                if ad in tablolar:
                    sayimlar[ad] = int(
                        conn.execute(f'SELECT COUNT(*) FROM "{ad}"').fetchone()[0]
                    )
        return {
            "yedek": str(kaynak),
            "kopya": str(hedef),
            "boyut": kaynak.stat().st_size,
            "integrity": "ok",
            "tablo_sayisi": len(tablolar),
            "sayimlar": sayimlar,
            "canli_db_degismedi": True,
        }

    @staticmethod
    def servis_oncesi_yedek_al(hedef_klasor: str | Path | None = None) -> Path:
        """Onarım öncesi yedek — bağlantı kipine göre."""
        from database.baglanti_modu import ayari_yukle

        ayar = ayari_yukle()
        if ayar.ag_mi:
            sonuc = BackupService.yedek_al_gelismis(
                HEDEF_BU_BILGISAYAR, hedef_klasor=hedef_klasor
            )
            if not sonuc.get("ok"):
                raise RuntimeError(sonuc.get("mesaj") or "Servis öncesi yedek alınamadı.")
            return Path(sonuc["sonuc_yolu"])

        if oturum.company_id is None:
            raise ValueError("Aktif firma seçili değil; servis öncesi yedek alınamaz.")

        from database.system.models import Company
        from database.database import firma_db_yolu_coz, get_system_session

        company_id = int(oturum.company_id)
        klasor = Path(hedef_klasor) if hedef_klasor else BackupService.yedek_klasoru_onerisi()
        klasor.mkdir(parents=True, exist_ok=True)

        with get_system_session() as session:
            f = session.get(Company, company_id)
            if f is None:
                raise ValueError("Firma bulunamadı; yedek alınamaz.")
            kaynak = firma_db_yolu_coz(f.db_path) or Path(f.db_path)
            if not kaynak.is_file():
                raise FileNotFoundError(f"Firma veritabanı dosyası yok: {kaynak}")

            hedef = klasor / BackupService.servis_oncesi_yedek_adi()
            if hedef.exists():
                hedef = klasor / (
                    f"CinMuhasebe_ServisOncesi_"
                    f"{datetime.now().strftime('%Y-%m-%d_%H%M%S_%f')}.db"
                )

            shutil.copy2(kaynak, hedef)
            for ek in ("-wal", "-shm"):
                k = Path(str(kaynak) + ek)
                if k.is_file():
                    shutil.copy2(k, Path(str(hedef) + ek))

            try:
                from database.system.auth_service import AuthService

                AuthService.audit(
                    session,
                    "servis_oncesi_yedekleme",
                    modul="servis",
                    kayit_id=str(company_id),
                    yeni_deger=str(hedef),
                )
            except Exception:
                pass

        return BackupService.dogrula_yedek(hedef)
