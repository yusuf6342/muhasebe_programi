"""Yönetilen personel dosya arşivi — firma DB yanındaki kalıcı klasör.

EXE veya geçici dizine tek kopya bırakılmaz. Hassas dosyalar Fernet ile şifrelenir;
anahtar system.db AppSetting içinde tutulur (dosya klasörüne veya kaynak koda konmaz).
"""

from __future__ import annotations

import hashlib
import re
import secrets
from pathlib import Path

from database.database import company_db

ARSIV_KOK_ADI = "personel_arsiv"
MAX_DOSYA_BAYT = 40 * 1024 * 1024
IZINLI_UZANTI = {".pdf", ".jpg", ".jpeg", ".png", ".docx"}
MIME_IMZA = {
    b"%PDF": "application/pdf",
    b"\xff\xd8\xff": "image/jpeg",
    b"\x89PNG\r\n\x1a\n": "image/png",
    b"PK\x03\x04": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
}


def arsiv_kok() -> Path:
    if not company_db.acik or not company_db._db_path:
        raise RuntimeError("Aktif firma veritabanı yok; personel arşivi açılamaz.")
    kok = Path(company_db._db_path).resolve().parent / ARSIV_KOK_ADI
    kok.mkdir(parents=True, exist_ok=True)
    (kok / "README.txt").write_text(
        "Cin Muhasebe personel özlük arşivi.\n"
        "Bu klasör firma veritabanı ile birlikte yedeklenmeli / geri yüklenmelidir.\n"
        "Hassas dosyalar şifreli saklanır; anahtar system.db içindedir.\n",
        encoding="utf-8",
    )
    return kok


def personel_klasoru(personel_id: int) -> Path:
    firma = int(getattr(company_db, "_company_id", 0) or 0)
    yol = arsiv_kok() / f"firma_{firma}" / f"personel_{int(personel_id)}"
    yol.mkdir(parents=True, exist_ok=True)
    return yol


def guvenli_dosya_adi(ad: str) -> str:
    ad = Path(ad or "belge").name
    ad = re.sub(r"[^\w.\- ()çğıöşüÇĞİÖŞÜ]+", "_", ad, flags=re.UNICODE)
    ad = ad.strip(" ._") or "belge"
    return ad[:180]


def dosya_hash(veri: bytes) -> str:
    return hashlib.sha256(veri).hexdigest()


def uzanti_ve_tur_dogrula(yol: Path, ham: bytes) -> tuple[str, str]:
    uz = yol.suffix.lower()
    if uz not in IZINLI_UZANTI:
        raise ValueError(
            f"Desteklenmeyen uzantı ({uz or 'yok'}). "
            f"İzinli: {', '.join(sorted(IZINLI_UZANTI))}"
        )
    if not ham:
        raise ValueError("Dosya boş.")
    if len(ham) > MAX_DOSYA_BAYT:
        raise ValueError(f"Dosya çok büyük (en fazla {MAX_DOSYA_BAYT // (1024*1024)} MB).")
    mime = None
    for imza, tur in MIME_IMZA.items():
        if ham.startswith(imza):
            mime = tur
            break
    if uz in {".jpg", ".jpeg"} and mime != "image/jpeg":
        raise ValueError("Dosya uzantısı JPEG ama içerik JPEG değil.")
    if uz == ".png" and mime != "image/png":
        raise ValueError("Dosya uzantısı PNG ama içerik PNG değil.")
    if uz == ".pdf" and mime != "application/pdf":
        raise ValueError("Dosya uzantısı PDF ama içerik PDF değil.")
    if uz == ".docx" and mime and not mime.startswith("application/vnd.openxml"):
        # PK zip olabilir; DOCX makrosu çalıştırılmaz — yalnızca saklanır
        pass
    return uz, mime or "application/octet-stream"


def _hassas_anahtar() -> bytes:
    """Fernet anahtarı — system.db AppSetting; dosya klasöründe tutulmaz."""
    from sqlalchemy import select

    from database.database import SystemSessionLocal
    from database.system.models import AppSetting

    if SystemSessionLocal is None:
        raise RuntimeError("Sistem veritabanı hazır değil; hassas dosya anahtarı yok.")
    anahtar_kod = "personel_hassas_fernet_key"
    with SystemSessionLocal() as session:
        kayit = session.scalar(select(AppSetting).where(AppSetting.anahtar == anahtar_kod))
        if kayit is None or not (kayit.deger or "").strip():
            try:
                from cryptography.fernet import Fernet

                ham = Fernet.generate_key().decode("ascii")
            except Exception:
                ham = secrets.token_urlsafe(32)
            session.add(AppSetting(anahtar=anahtar_kod, deger=ham))
            session.commit()
            return ham.encode("ascii")
        return (kayit.deger or "").encode("ascii")


def sifrele(veri: bytes) -> bytes:
    from cryptography.fernet import Fernet

    return Fernet(_hassas_anahtar()).encrypt(veri)


def sifre_coz(veri: bytes) -> bytes:
    from cryptography.fernet import Fernet

    return Fernet(_hassas_anahtar()).decrypt(veri)


def dosyayi_arsive_kopyala(
    personel_id: int,
    belge_id: int,
    surum_no: int,
    kaynak: Path,
    *,
    sifreli: bool,
) -> dict:
    ham = kaynak.read_bytes()
    uz, mime = uzanti_ve_tur_dogrula(kaynak, ham)
    h = dosya_hash(ham)
    ad = guvenli_dosya_adi(kaynak.name)
    klasor = personel_klasoru(personel_id) / f"belge_{int(belge_id)}"
    klasor.mkdir(parents=True, exist_ok=True)
    hedef_ad = f"v{int(surum_no)}_{ad}"
    if sifreli and not hedef_ad.endswith(".enc"):
        hedef_ad += ".enc"
    hedef = klasor / hedef_ad
    yazilacak = sifrele(ham) if sifreli else ham
    hedef.write_bytes(yazilacak)
    return {
        "dosya_adi": ad,
        "dosya_yolu": str(hedef.resolve()),
        "dosya_uzanti": uz,
        "dosya_boyut": len(ham),
        "dosya_hash": h,
        "mime_tur": mime,
        "sifreli": bool(sifreli),
    }


def arsivden_oku(dosya_yolu: str, *, sifreli: bool) -> bytes:
    yol = Path(dosya_yolu)
    if not yol.is_file():
        raise FileNotFoundError(
            f"Özlük dosyası bulunamadı (arşiv ilişkisi bozuk olabilir): {yol}"
        )
    ham = yol.read_bytes()
    return sifre_coz(ham) if sifreli else ham
