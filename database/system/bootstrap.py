"""system.db ilk kurulum: roller, izinler, yönetici, Ray Mobilya firması."""

from __future__ import annotations

import socket
import uuid
from pathlib import Path

from sqlalchemy import create_engine, event, select
from sqlalchemy.orm import Session, sessionmaker

from database.system.migration import migration_uygula, system_tablolari_olustur
from database.system.models import (
    AppSetting,
    Company,
    Permission,
    Role,
    RolePermission,
    User,
    UserCompany,
)
from database.system.password import guvenli_parola_uret, hash_parola

RAY_UNVAN = "Ray Mobilya Aksesuarları"
RAY_KOD = "RAY001"
ADMIN_KULLANICI = "admin"
ADMIN_KOD = "ADM001"

# İzin kataloğu
IZINLER: list[tuple[str, str, str]] = [
    ("goruntuleme", "Görüntüleme", "genel"),
    ("yeni_kayit", "Yeni kayıt", "genel"),
    ("duzenleme", "Düzenleme", "genel"),
    ("iptal", "İptal etme", "genel"),
    ("silme", "Silme", "genel"),
    ("yazdirma", "Yazdırma", "genel"),
    ("excel_pdf", "Excel/PDF aktarma", "genel"),
    ("maliyet_gorma", "Maliyet görme", "finans"),
    ("kar_gorma", "Kâr görme", "finans"),
    ("firma_degistirme", "Firma değiştirme", "sistem"),
    ("donem_degistirme", "Dönem değiştirme", "sistem"),
    ("yedek_alma", "Yedek alma", "sistem"),
    ("kullanici_yonetme", "Kullanıcı yönetme", "sistem"),
    ("firma_yonetme", "Firma yönetme", "sistem"),
    ("sistem_ayarlari", "Sistem ayarları", "sistem"),
    ("stok_goruntuleme", "Stok görüntüleme", "stok"),
    ("stok_duzenleme", "Stok düzenleme", "stok"),
    ("satis_goruntuleme", "Satış görüntüleme", "satis"),
    ("satis_duzenleme", "Satış düzenleme", "satis"),
    ("hizli_satis_fiyat_degistirme", "Hızlı satış fiyat değiştirme", "satis"),
    ("hizli_satis_yuksek_iskonto", "Hızlı satış yüksek iskonto", "satis"),
    ("hizli_satis_acik_hesap", "Hızlı satış açık hesap / risk aşımı", "satis"),
    ("hizli_satis_iptal", "Hızlı satış iptal / iade", "satis"),
    ("alis_goruntuleme", "Alış görüntüleme", "alis"),
    ("alis_duzenleme", "Alış düzenleme", "alis"),
    ("finans_goruntuleme", "Finans görüntüleme", "finans"),
    ("finans_duzenleme", "Finans düzenleme", "finans"),
    ("cari_goruntuleme", "Cari görüntüleme", "cari"),
    ("cari_duzenleme", "Cari düzenleme", "cari"),
    ("muhasebe_goruntuleme", "Genel muhasebe görüntüleme", "muhasebe"),
    ("muhasebe_fis_olusturma", "Muhasebe fişi oluşturma", "muhasebe"),
    ("muhasebe_fis_duzenleme", "Fiş düzenleme", "muhasebe"),
    ("muhasebe_fis_kesinlestirme", "Fiş kesinleştirme", "muhasebe"),
    ("muhasebe_fis_iptal", "Fiş iptal etme", "muhasebe"),
    ("muhasebe_mizan", "Mizan görüntüleme", "muhasebe"),
    ("muhasebe_bilanco", "Bilanço görüntüleme", "muhasebe"),
    ("muhasebe_gelir_tablosu", "Gelir tablosu görüntüleme", "muhasebe"),
    ("muhasebe_disa_aktarma", "Muhasebe rapor dışa aktarma", "muhasebe"),
    ("silinen_kayit_goruntuleme", "Silinen kayıtları görüntüleme", "sistem"),
    ("silinen_kayit_geri_yukleme", "Silinen kayıt geri yükleme", "sistem"),
    ("servis_goruntuleme", "Servis ve sistem merkezini görüntüleme", "servis"),
    ("servis_kontrol", "Servis kontrollerini çalıştırma", "servis"),
    ("servis_onarim", "Servis onarım işlemleri", "servis"),
]

# Rol → izin kodları (* = hepsi)
ROL_IZINLERI: dict[str, list[str] | str] = {
    "YONETICI": "*",
    "FINANS": [
        "goruntuleme",
        "yeni_kayit",
        "duzenleme",
        "iptal",
        "yazdirma",
        "excel_pdf",
        "maliyet_gorma",
        "kar_gorma",
        "finans_goruntuleme",
        "finans_duzenleme",
        "cari_goruntuleme",
        "cari_duzenleme",
        "stok_goruntuleme",
        "satis_goruntuleme",
        "muhasebe_goruntuleme",
        "muhasebe_fis_olusturma",
        "muhasebe_fis_duzenleme",
        "muhasebe_fis_kesinlestirme",
        "muhasebe_fis_iptal",
        "muhasebe_mizan",
        "muhasebe_bilanco",
        "muhasebe_gelir_tablosu",
        "muhasebe_disa_aktarma",
        "firma_degistirme",
        "donem_degistirme",
        "silinen_kayit_goruntuleme",
    ],
    "SATIS": [
        "goruntuleme",
        "yeni_kayit",
        "duzenleme",
        "iptal",
        "yazdirma",
        "excel_pdf",
        "satis_goruntuleme",
        "satis_duzenleme",
        "hizli_satis_fiyat_degistirme",
        "hizli_satis_yuksek_iskonto",
        "hizli_satis_acik_hesap",
        "hizli_satis_iptal",
        "cari_goruntuleme",
        "cari_duzenleme",
        "stok_goruntuleme",
        "finans_goruntuleme",
        "firma_degistirme",
        "donem_degistirme",
        "silme",
        "silinen_kayit_goruntuleme",
    ],
    "DEPO": [
        "goruntuleme",
        "yeni_kayit",
        "duzenleme",
        "yazdirma",
        "stok_goruntuleme",
        "stok_duzenleme",
        "firma_degistirme",
        "donem_degistirme",
    ],
    "GORUNTULEME": [
        "goruntuleme",
        "yazdirma",
        "excel_pdf",
        "stok_goruntuleme",
        "satis_goruntuleme",
        "alis_goruntuleme",
        "finans_goruntuleme",
        "cari_goruntuleme",
        "muhasebe_goruntuleme",
        "muhasebe_mizan",
        "muhasebe_bilanco",
        "muhasebe_gelir_tablosu",
        "muhasebe_disa_aktarma",
        "firma_degistirme",
        "donem_degistirme",
    ],
}

ROLLER: list[tuple[str, str, str]] = [
    ("YONETICI", "Yönetici", "Tüm firmalar ve modüller"),
    ("FINANS", "Finans", "Cari, kasa, banka, gelir-gider"),
    ("SATIS", "Satış", "Müşteri, sipariş, irsaliye, fatura, tahsilat"),
    ("DEPO", "Depo", "Stok, giriş-çıkış, sayım, sevkiyat"),
    ("GORUNTULEME", "Görüntüleme", "Salt okunur erişim"),
]


def _sqlite_pragma(dbapi_connection, _connection_record) -> None:
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA journal_mode=WAL")
    cursor.execute("PRAGMA busy_timeout=30000")
    cursor.execute("PRAGMA synchronous=NORMAL")
    cursor.close()


def system_engine_olustur(system_db_path: Path):
    system_db_path.parent.mkdir(parents=True, exist_ok=True)
    eng = create_engine(
        f"sqlite:///{system_db_path.resolve().as_posix()}",
        echo=False,
        connect_args={"check_same_thread": False, "timeout": 30},
    )
    event.listen(eng, "connect", _sqlite_pragma)
    return eng


def _izinleri_doldur(session: Session) -> dict[str, Permission]:
    harita: dict[str, Permission] = {}
    for kod, ad, modul in IZINLER:
        perm = session.scalar(select(Permission).where(Permission.kod == kod))
        if perm is None:
            perm = Permission(kod=kod, ad=ad, modul=modul)
            session.add(perm)
            session.flush()
        harita[kod] = perm
    return harita


def _rolleri_doldur(session: Session, izinler: dict[str, Permission]) -> dict[str, Role]:
    roller: dict[str, Role] = {}
    for kod, ad, aciklama in ROLLER:
        rol = session.scalar(select(Role).where(Role.kod == kod))
        if rol is None:
            rol = Role(kod=kod, ad=ad, aciklama=aciklama, sistem=True)
            session.add(rol)
            session.flush()
        roller[kod] = rol

        hedef = ROL_IZINLERI.get(kod, [])
        if hedef == "*":
            hedef_kodlari = list(izinler.keys())
        else:
            hedef_kodlari = list(hedef)  # type: ignore[arg-type]

        mevcut = {
            rp.permission_id
            for rp in session.scalars(
                select(RolePermission).where(RolePermission.role_id == rol.id)
            ).all()
        }
        for ikod in hedef_kodlari:
            perm = izinler[ikod]
            if perm.id not in mevcut:
                session.add(RolePermission(role_id=rol.id, permission_id=perm.id))
    return roller


def _ayar(session: Session, anahtar: str, deger: str | None = None) -> str | None:
    kayit = session.scalar(select(AppSetting).where(AppSetting.anahtar == anahtar))
    if kayit is None and deger is not None:
        session.add(AppSetting(anahtar=anahtar, deger=deger))
        return deger
    return kayit.deger if kayit else None


def _ray_firmasi_olustur(session: Session, muhasebe_db_path: Path) -> Company:
    firma = session.scalar(select(Company).where(Company.firma_kodu == RAY_KOD))
    if firma is not None:
        # Yol güncel mi?
        beklenen = str(muhasebe_db_path.resolve())
        if firma.db_path != beklenen and muhasebe_db_path.exists():
            firma.db_path = beklenen
        return firma

    # Eski lokal firmalar tablosundaki ünvana yakın eşleşme
    eski = session.scalar(
        select(Company).where(Company.unvan.ilike("%Ray Mobilya%"))
    )
    if eski is not None:
        return eski

    uid = str(uuid.uuid4())
    firma = Company(
        firma_uid=uid,
        firma_kodu=RAY_KOD,
        unvan=RAY_UNVAN,
        kisa_ad="Ray Mobilya",
        varsayilan_para_birimi="TRY",
        aktif=True,
        db_path=str(muhasebe_db_path.resolve()),
    )
    session.add(firma)
    session.flush()
    return firma


def _yonetici_olustur(
    session: Session,
    roller: dict[str, Role],
    firma: Company,
    sifre_dosyasi: Path,
) -> tuple[User, str | None]:
    """Yönetici yoksa oluştur. İlk parola dosyaya yazılır (kaynak koda gömülmez)."""
    user = session.scalar(select(User).where(User.kullanici_adi == ADMIN_KULLANICI))
    ilk_parola: str | None = None
    if user is None:
        ilk_parola = guvenli_parola_uret(12)
        user = User(
            kullanici_kodu=ADMIN_KOD,
            ad_soyad="Sistem Yöneticisi",
            kullanici_adi=ADMIN_KULLANICI,
            parola_hash=hash_parola(ilk_parola),
            role_id=roller["YONETICI"].id,
            aktif=True,
            varsayilan_firma_id=firma.id,
            sifre_degistirmeli=True,
        )
        session.add(user)
        session.flush()
        try:
            sifre_dosyasi.write_text(
                (
                    "İLK YÖNETİCİ GİRİŞ BİLGİSİ (bir kez üretildi)\n"
                    f"Kullanıcı adı: {ADMIN_KULLANICI}\n"
                    f"Parola: {ilk_parola}\n"
                    "\nİlk girişte parolayı değiştirmeniz zorunludur.\n"
                    "Bu dosyayı güvenli yere taşıyıp silin.\n"
                ),
                encoding="utf-8",
            )
        except OSError:
            pass

    link = session.scalar(
        select(UserCompany).where(
            UserCompany.user_id == user.id,
            UserCompany.company_id == firma.id,
        )
    )
    if link is None:
        session.add(UserCompany(user_id=user.id, company_id=firma.id))

    if user.varsayilan_firma_id is None:
        user.varsayilan_firma_id = firma.id
    return user, ilk_parola


def sistem_baslat(
    system_db_path: Path,
    muhasebe_db_path: Path,
    sifre_dosyasi: Path | None = None,
) -> dict:
    """
    system.db oluştur/güncelle, roller, Ray Mobilya, admin.
    Mevcut muhasebe.db içeriğine dokunmaz — yalnızca yola bağlar.
    """
    eng = system_engine_olustur(system_db_path)
    system_tablolari_olustur(eng)
    SessionLocal = sessionmaker(
        bind=eng, autoflush=False, autocommit=False, expire_on_commit=False
    )
    sifre_yolu = sifre_dosyasi or (system_db_path.parent / "ILK_YONETICI_SIFRE.txt")
    sonuc: dict = {
        "system_db": str(system_db_path.resolve()),
        "company_id": None,
        "company_db": str(muhasebe_db_path.resolve()),
        "admin_olusturuldu": False,
        "ilk_parola_dosyasi": None,
    }

    with SessionLocal() as session:
        try:
            migration_uygula(session)
            izinler = _izinleri_doldur(session)
            roller = _rolleri_doldur(session, izinler)
            firma = _ray_firmasi_olustur(session, muhasebe_db_path)
            user, ilk = _yonetici_olustur(session, roller, firma, sifre_yolu)
            _ayar(session, "son_firma_id", str(firma.id))
            _ayar(session, "tek_firma_otomatik_giris", "1")
            _ayar(session, "kurulum_tamam", "1")

            # AŞAMA 6: yedek + sayısal snapshot (idempotent)
            from database.system.gecis import gecis_calistir

            gecis_bilgi = gecis_calistir(
                session,
                muhasebe_db_path=Path(muhasebe_db_path),
            )
            session.commit()
            sonuc["company_id"] = firma.id
            sonuc["company_db"] = firma.db_path
            sonuc["admin_olusturuldu"] = ilk is not None
            if ilk is not None:
                sonuc["ilk_parola_dosyasi"] = str(sifre_yolu)
            sonuc["admin_user_id"] = user.id
            sonuc["gecis"] = {
                "yedek_alindi": gecis_bilgi.get("yedek_alindi"),
                "yedek_yolu": gecis_bilgi.get("yedek_yolu"),
                "zaten_tamam": gecis_bilgi.get("zaten_tamam"),
                "mesajlar": gecis_bilgi.get("mesajlar"),
                "uyumlu": (gecis_bilgi.get("dogrulama") or {}).get("uyumlu"),
            }
        except Exception:
            session.rollback()
            raise
        finally:
            eng.dispose()

    return sonuc


def kullanici_izinlerini_yukle(session: Session, user: User) -> set[str]:
    """Rol + kullanıcı özel izinleri birleştir."""
    izinler: set[str] = set()
    for rp in session.scalars(
        select(RolePermission).where(RolePermission.role_id == user.role_id)
    ).all():
        perm = session.get(Permission, rp.permission_id)
        if perm:
            izinler.add(perm.kod)

    for up in user.extra_permissions:
        perm = session.get(Permission, up.permission_id)
        if not perm:
            continue
        if up.izinli:
            izinler.add(perm.kod)
        else:
            izinler.discard(perm.kod)
    return izinler


def bilgisayar_adi() -> str:
    try:
        return socket.gethostname()
    except OSError:
        return ""
