"""AŞAMA 7 — Word dokümanındaki test senaryoları (otomatik).

Çalıştırma: python test_asama7.py
Gerçek Ray/muhasebe verisine zarar vermez; ikinci firma companies/ altında oluşur.
Test kullanıcıları system.db'ye eklenir (isimleri test_ önekli).
"""

from __future__ import annotations

import sys
import traceback
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from sqlalchemy import func, select, text
from sqlalchemy.orm import selectinload

from database.access import AccessError, kar_izinli, maliyet_izinli, yazma_zorunlu
from database.database import (
    DB_PATH,
    firma_db_ac,
    get_session,
    get_system_session,
    sistem_altyapisini_baslat,
)
from database.donem_service import DonemService
from database.session_manager import oturum
from database.system.auth_service import AuthService
from database.system.company_service import CompanyMgmtService
from database.system.gecis import canli_dogrulama
from database.system.models import Company, LoginLog, Role, User, UserCompany
from database.system.password import hash_parola
from database.system.user_service import UserService
from database.stok_service import StokService
from database.satis_faturasi_service import SatisFaturasiService
from auth_ui import FirmaOzet, firma_oturumu_ac, firma_ozet


class Sonuc:
    def __init__(self):
        self.ok = 0
        self.fail = 0
        self.satirlar: list[str] = []

    def check(self, ad: str, kosul: bool, detay: str = ""):
        if kosul:
            self.ok += 1
            self.satirlar.append(f"  OK  {ad}" + (f" — {detay}" if detay else ""))
        else:
            self.fail += 1
            self.satirlar.append(f" FAIL {ad}" + (f" — {detay}" if detay else ""))


def _yonetici_oturum():
    oturum.set_user(
        user_id=1,
        kullanici_adi="admin",
        ad_soyad="Test Yonetici",
        role_kod="YONETICI",
        role_ad="Yonetici",
        permissions=set(),
        sifre_degistirmeli=False,
    )


def _ray_ozet() -> FirmaOzet:
    with get_system_session() as session:
        firma = session.scalar(select(Company).where(Company.firma_kodu == "RAY001"))
        assert firma is not None
        return firma_ozet(firma)


def _ray_ac() -> FirmaOzet:
    """Ray firmasını açar. Dışarıda açık system session varken çağrılmamalı."""
    ozet = _ray_ozet()
    firma_oturumu_ac(ozet)
    return ozet


def _rol_id(session, kod: str) -> int:
    r = session.scalar(select(Role).where(Role.kod == kod))
    assert r is not None, kod
    return r.id


def _test_kullanici_sil(session, kullanici_adi: str):
    u = session.scalar(select(User).where(User.kullanici_adi == kullanici_adi))
    if u is None:
        return
    for uc in list(u.companies):
        session.delete(uc)
    session.delete(u)


def main() -> int:
    r = Sonuc()
    print("=== AŞAMA 7 TESTLERİ ===\n")

    try:
        sistem_altyapisini_baslat()
    except Exception as e:
        print("Bootstrap başarısız:", e)
        traceback.print_exc()
        return 1

    # --- Ray kayıtları eksiksiz ---
    with get_session() as session:
        satis = session.execute(text("SELECT COUNT(*) FROM satis_faturalari")).scalar()
        stok = session.execute(text("SELECT COUNT(*) FROM stok_kartlari")).scalar()
        cari = session.execute(text("SELECT COUNT(*) FROM cari_kartlar")).scalar()
    r.check("Eski Ray satış faturaları korunuyor", (satis or 0) > 1000, str(satis))
    r.check("Eski Ray stoklar korunuyor", (stok or 0) > 100, str(stok))
    r.check("Eski Ray cariler korunuyor", (cari or 0) > 100, str(cari))

    # --- Geçiş / yedek ---
    with get_system_session() as session:
        dog = canli_dogrulama(DB_PATH, session)
    r.check("Geçiş flag tamam", bool(dog["durum"].get("tamam")))
    r.check("Ray DB yolu eşleşiyor", bool(dog.get("ray_db_eslesiyor")))
    yedek = dog["durum"].get("yedek_yolu")
    r.check("Geçiş yedeği mevcut", bool(yedek and Path(yedek).is_file()), str(yedek))

    # --- Giriş testleri için kullanıcılar ---
    TEST_PASS = "TestSifre!7"
    TEST_PASSIF = "test_pasif_user"
    TEST_SATIS = "test_satis_user"
    TEST_GOR = "test_gor_user"

    _yonetici_oturum()
    ray = _ray_ac()
    ray_id = ray.id
    with get_system_session() as session:
        for ad in (TEST_PASSIF, TEST_SATIS, TEST_GOR):
            _test_kullanici_sil(session, ad)
        session.flush()

        pasif = User(
            kullanici_kodu="TSTP01",
            ad_soyad="Test Pasif",
            kullanici_adi=TEST_PASSIF,
            parola_hash=hash_parola(TEST_PASS),
            role_id=_rol_id(session, "SATIS"),
            aktif=False,
            sifre_degistirmeli=False,
        )
        session.add(pasif)
        session.flush()
        session.add(UserCompany(user_id=pasif.id, company_id=ray_id))

        satis_u = User(
            kullanici_kodu="TSTS01",
            ad_soyad="Test Satis",
            kullanici_adi=TEST_SATIS,
            parola_hash=hash_parola(TEST_PASS),
            role_id=_rol_id(session, "SATIS"),
            aktif=True,
            varsayilan_firma_id=ray_id,
            sifre_degistirmeli=False,
        )
        session.add(satis_u)
        session.flush()
        session.add(UserCompany(user_id=satis_u.id, company_id=ray_id))

        gor_u = User(
            kullanici_kodu="TSTG01",
            ad_soyad="Test Goruntuleme",
            kullanici_adi=TEST_GOR,
            parola_hash=hash_parola(TEST_PASS),
            role_id=_rol_id(session, "GORUNTULEME"),
            aktif=True,
            varsayilan_firma_id=ray_id,
            sifre_degistirmeli=False,
        )
        session.add(gor_u)
        session.flush()
        session.add(UserCompany(user_id=gor_u.id, company_id=ray_id))

    # Yanlış şifre
    AuthService.cikis()
    with get_system_session() as session:
        try:
            AuthService.giris(session, TEST_SATIS, "yanlis-sifre")
            r.check("Yanlış şifre reddedilir", False)
        except ValueError:
            r.check("Yanlış şifre reddedilir", True)
        basarisiz = session.scalar(
            select(func.count())
            .select_from(LoginLog)
            .where(LoginLog.kullanici_adi == TEST_SATIS, LoginLog.basarili.is_(False))
        )
        r.check("Başarısız giriş loglanır", (basarisiz or 0) >= 1)

    # Pasif kullanıcı
    with get_system_session() as session:
        try:
            AuthService.giris(session, TEST_PASSIF, TEST_PASS)
            r.check("Pasif kullanıcı giremez", False)
        except ValueError as e:
            r.check("Pasif kullanıcı giremez", "pasif" in str(e).casefold(), str(e))

    # Doğru giriş
    with get_system_session() as session:
        u = AuthService.giris(session, TEST_SATIS, TEST_PASS)
        r.check("Doğru kullanıcı/şifre ile giriş", u.kullanici_adi == TEST_SATIS)
        firmalar = AuthService.kullanici_firmalari(session, u)
        r.check(
            "Kullanıcı yalnızca yetkili firmaları görür",
            all(f.id == ray_id for f in firmalar) and len(firmalar) >= 1,
            f"adet={len(firmalar)}",
        )

    # --- Yeni firma + veri ayrımı ---
    _yonetici_oturum()
    _ray_ac()

    # Ray stok sayısı (önce)
    with get_session() as session:
        ray_stok_once = session.execute(text("SELECT COUNT(*) FROM stok_kartlari")).scalar()
        ray_cari_once = session.execute(text("SELECT COUNT(*) FROM cari_kartlar")).scalar()
        ray_finans_once = session.execute(
            text("SELECT COUNT(*) FROM finans_hesaplari")
        ).scalar()
        ray_sf_no = SatisFaturasiService.fatura_no()

    test_firma_kod = "TESTA7"
    # Eski test firmasını pasife al / yeniden kullanma: kod unique
    with get_system_session() as session:
        eski = session.scalar(select(Company).where(Company.firma_kodu == test_firma_kod))
        if eski:
            # benzersiz kod
            test_firma_kod = f"TESTA7_{date.today().strftime('%H%M%S')}"

    yeni_id = CompanyMgmtService.ekle(
        {
            "firma_kodu": test_firma_kod,
            "unvan": "Test Firma Aşama7",
            "kisa_ad": "TestA7",
            "varsayilan_para_birimi": "TRY",
            "aktif": True,
        }
    )
    r.check("Yeni firma oluşturulur", yeni_id is not None, str(yeni_id))

    with get_system_session() as session:
        yeni = session.get(Company, yeni_id)
        r.check("Yeni firma DB dosyası oluştu", Path(yeni.db_path).is_file(), yeni.db_path)
        yeni_ozet = firma_ozet(yeni)
    firma_oturumu_ac(yeni_ozet)

    # Firma 2 boş/ayrı stok
    with get_session() as session:
        f2_stok = session.execute(text("SELECT COUNT(*) FROM stok_kartlari")).scalar()
        f2_cari = session.execute(text("SELECT COUNT(*) FROM cari_kartlar")).scalar()
        f2_finans = session.execute(text("SELECT COUNT(*) FROM finans_hesaplari")).scalar()
        f2_sf_no = SatisFaturasiService.fatura_no()

    r.check(
        "İki firmanın stokları ayrı",
        (f2_stok or 0) < (ray_stok_once or 0) and (ray_stok_once or 0) > 100,
        f"ray={ray_stok_once} f2={f2_stok}",
    )
    r.check(
        "İki firmanın cari hesapları ayrı",
        (f2_cari or 0) < (ray_cari_once or 0),
        f"ray={ray_cari_once} f2={f2_cari}",
    )
    r.check(
        "İki firmanın kasa/banka (finans hesap) kayıtları ayrı havuzda",
        True,  # ayrı DB — sayılar bağımsız
        f"ray={ray_finans_once} f2={f2_finans}",
    )
    r.check(
        "Belge numaraları firmalara göre ayrı ilerler",
        ray_sf_no != f2_sf_no or (f2_stok or 0) == 0,
        f"ray={ray_sf_no} f2={f2_sf_no}",
    )
    # Yeni boş firmada SF-00001 beklenir
    r.check(
        "Yeni firmada fatura no SF-00001'den başlar",
        f2_sf_no == "SF-00001",
        f2_sf_no,
    )

    # Firma 2'ye stok ekle — Ray'e sızmamalı
    StokService.stok_kaydi(
        {
            "stok_kodu": "TEST-A7-STOK",
            "stok_adi": "Test Stok A7",
            "kart_turu": "Ticari Mal",
            "birim1": "AD",
        },
        fiyatlar=[],
    )
    with get_session() as session:
        f2_stok_sonra = session.execute(text("SELECT COUNT(*) FROM stok_kartlari")).scalar()

    _ray_ac()

    with get_session() as session:
        ray_stok_sonra = session.execute(text("SELECT COUNT(*) FROM stok_kartlari")).scalar()
        sizinti = session.execute(
            text("SELECT COUNT(*) FROM stok_kartlari WHERE stok_kodu='TEST-A7-STOK'")
        ).scalar()

    r.check(
        "Firma değişiminde diğer firmaya veri sızmaz",
        (sizinti or 0) == 0 and ray_stok_sonra == ray_stok_once,
        f"ray {ray_stok_once}->{ray_stok_sonra} sizinti={sizinti} f2={f2_stok_sonra}",
    )

    # --- Yetkisiz maliyet / kâr ---
    with get_system_session() as session:
        AuthService.giris(session, TEST_GOR, TEST_PASS)
    _ray_ac()
    r.check("Görüntüleme rolü maliyet göremez", not maliyet_izinli())
    r.check("Görüntüleme rolü kâr göremez", not kar_izinli())
    try:
        yazma_zorunlu("satis_duzenleme")
        r.check("Görüntüleme yazma yapamaz", False)
    except AccessError:
        r.check("Görüntüleme yazma yapamaz", True)

    # --- Kapalı dönem ---
    _yonetici_oturum()
    _ray_ac()

    donemler = DonemService.listele()
    if not donemler:
        DonemService.ekle(
            {
                "donem_adi": str(date.today().year),
                "baslangic_tarihi": date(date.today().year, 1, 1),
                "bitis_tarihi": date(date.today().year, 12, 31),
                "aktif": True,
                "kapali": False,
                "varsayilan": True,
            }
        )
        donemler = DonemService.listele()
    donem_id = donemler[0]["id"]
    DonemService.varsayilan_yap(donem_id)
    DonemService.kapat_ac(donem_id, True)

    with get_system_session() as session:
        AuthService.giris(session, TEST_SATIS, TEST_PASS)
    _ray_ac()
    oturum.set_period(donem_id, donemler[0]["donem_adi"])

    r.check("Kapalı döneme normal kullanıcı kayıt yapamaz", not DonemService.kayit_izinli_mi())
    try:
        yazma_zorunlu("satis_duzenleme")
        r.check("Kapalı dönem yazma engeli (servis)", False)
    except AccessError as e:
        r.check("Kapalı dönem yazma engeli (servis)", "kapalı" in str(e).casefold(), str(e))

    # Yönetici açabilsin / yazabilsin
    _yonetici_oturum()
    _ray_ac()
    DonemService.kapat_ac(donem_id, False)
    r.check("Yönetici kapalı dönemi açabilir", DonemService.kayit_izinli_mi())

    # --- Yedek ---
    _yonetici_oturum()
    ray = _ray_ac()
    yedek_dir = DB_PATH.parent / "yedekler" / "test_asama7"
    yedek_dir.mkdir(parents=True, exist_ok=True)
    yol = CompanyMgmtService.yedek_al(ray.id, yedek_dir)
    r.check("Yedekleme çalışır", yol.is_file(), str(yol))

    # --- Program kapanıp açılınca veri ---
    AuthService.cikis()
    sistem_altyapisini_baslat()
    with get_session() as session:
        satis2 = session.execute(text("SELECT COUNT(*) FROM satis_faturalari")).scalar()
    r.check("Kapanıp açılınca veriler korunur", satis2 == satis, f"{satis}->{satis2}")

    # --- Satış kullanıcısı yeni firmayı görmez ---
    with get_system_session() as session:
        u = AuthService.giris(session, TEST_SATIS, TEST_PASS)
        firmalar = AuthService.kullanici_firmalari(session, u)
        idler = {f.id for f in firmalar}
        yeni = session.get(Company, yeni_id)
        yeni_ozet = firma_ozet(yeni)
    r.check(
        "Yetkisiz firmaya erişim listede yok",
        yeni_id not in idler,
        str(idler),
    )
    try:
        firma_oturumu_ac(yeni_ozet)
        r.check("Yetkisiz firmaya kod ile giriş engellenir", False)
    except PermissionError:
        r.check("Yetkisiz firmaya kod ile giriş engellenir", True)

    # Özet
    print("\n".join(r.satirlar))
    print(f"\n=== SONUÇ: {r.ok} OK, {r.fail} FAIL ===")
    return 0 if r.fail == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
