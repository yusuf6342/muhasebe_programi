import os
import shutil
from pathlib import Path
from contextlib import contextmanager
from collections.abc import Generator

from sqlalchemy import create_engine, event, inspect, select, text
from sqlalchemy.orm import DeclarativeBase, sessionmaker


# Proje ana klasörü
BASE_DIR = Path(__file__).resolve().parent.parent

# Proje içi data (eski konum / resimler / ayarlar)
PROJE_DATA_DIR = BASE_DIR / "data"
PROJE_DATA_DIR.mkdir(exist_ok=True)


def _db_dir_sec() -> Path:
    """SQLite'ı OneDrive dışında tut (LOCALAPPDATA); aksi halde proje data/.

    MUHASEBE_DB_DIR ile özel klasör verilebilir.
    """
    env = (os.environ.get("MUHASEBE_DB_DIR") or "").strip()
    if env:
        yol = Path(env)
        yol.mkdir(parents=True, exist_ok=True)
        return yol
    local = (os.environ.get("LOCALAPPDATA") or "").strip()
    if local:
        yol = Path(local) / "MuhasebeProgrami" / "data"
        yol.mkdir(parents=True, exist_ok=True)
        return yol
    return PROJE_DATA_DIR


def _eski_db_tasi(hedef_dir: Path) -> None:
    """İlk açılışta proje data/muhasebe.db → yeni konuma kopyala."""
    hedef = hedef_dir / "muhasebe.db"
    if hedef.exists():
        return
    kaynak = PROJE_DATA_DIR / "muhasebe.db"
    if not kaynak.is_file():
        return
    shutil.copy2(kaynak, hedef)
    for ek in ("-wal", "-shm"):
        k = PROJE_DATA_DIR / f"muhasebe.db{ek}"
        if k.is_file():
            shutil.copy2(k, hedef_dir / f"muhasebe.db{ek}")


def _konum_dosyasi_yaz(db_yolu: Path) -> None:
    metin = (
        "Muhasebe veritabanı konumu (OneDrive senkronu SQLite kilidine yol açmasın diye):\n"
        f"Firma operasyon DB: {db_yolu}\n"
        f"Sistem DB: {DB_DIR / 'system.db'}\n"
        f"Firma DB klasörü: {DB_DIR / 'companies'}\n"
        "\nÖzel klasör için ortam değişkeni: MUHASEBE_DB_DIR\n"
    )
    try:
        (PROJE_DATA_DIR / "VERITABANI_KONUMU.txt").write_text(metin, encoding="utf-8")
    except OSError:
        pass


DB_DIR = _db_dir_sec()
_eski_db_tasi(DB_DIR)
DB_PATH = (DB_DIR / "muhasebe.db").resolve()
SYSTEM_DB_PATH = (DB_DIR / "system.db").resolve()
COMPANIES_DIR = (DB_DIR / "companies").resolve()
COMPANIES_DIR.mkdir(parents=True, exist_ok=True)
_konum_dosyasi_yaz(DB_PATH)

# SQLite veritabanı (firma operasyon DB — varsayılan: mevcut muhasebe.db)
DATABASE_URL = f"sqlite:///{DB_PATH.as_posix()}"


def _sqlite_baglanti_ayarlari(dbapi_connection, _connection_record) -> None:
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA journal_mode=WAL")
    cursor.execute("PRAGMA busy_timeout=30000")
    cursor.execute("PRAGMA synchronous=NORMAL")
    cursor.close()


# Veritabanı bağlantısı (arka plan thread + OneDrive kilidi için timeout)
engine = create_engine(
    DATABASE_URL,
    echo=False,
    connect_args={"check_same_thread": False, "timeout": 30},
)
event.listen(engine, "connect", _sqlite_baglanti_ayarlari)


# Tüm firma (operasyon) modellerimizin temel sınıfı
class Base(DeclarativeBase):
    pass


# Veritabanı oturumu — aktif firma değişince yeniden bağlanır
SessionLocal = sessionmaker(
    bind=engine,
    autoflush=False,
    autocommit=False,
    expire_on_commit=False,
)

# Ortak sistem engine (system.db) — bootstrap sonrası doldurulur
system_engine = None
SystemSessionLocal = None

# Firma DB yöneticisi
from database.company_database import CompanyDatabase  # noqa: E402

company_db = CompanyDatabase(COMPANIES_DIR)


def _aktif_engine_bagla(yeni_engine) -> None:
    """Schema migration ve get_session geriye uyumlu kalsın diye global engine günceller."""
    global engine, SessionLocal
    if engine is not None and engine is not yeni_engine:
        try:
            engine.dispose()
        except Exception:
            pass
    engine = yeni_engine
    SessionLocal = sessionmaker(
        bind=engine,
        autoflush=False,
        autocommit=False,
        expire_on_commit=False,
    )


def firma_db_ac(company_id: int, db_path: str | Path) -> None:
    """Aktif firma operasyon DB'sini açar (öncekini kapatır).

    Aynı dosya zaten açıksa engine nesnesini korur (import edenlerin
    `from database.database import engine` referansı bozulmasın).
    """
    yol = Path(db_path).resolve()
    mevcut_yol: Path | None = None
    try:
        raw = getattr(engine.url, "database", None)
        if raw:
            mevcut_yol = Path(raw).resolve()
    except Exception:
        mevcut_yol = None

    if mevcut_yol == yol and engine is not None:
        company_db._engine = engine
        company_db._session_factory = SessionLocal
        company_db._company_id = company_id
        company_db._db_path = yol
        return

    yeni = company_db.open(company_id, yol)
    _aktif_engine_bagla(yeni)


def firma_db_kapat() -> None:
    company_db.close()


@contextmanager
def get_session() -> Generator:
    """Aktif firma operasyon oturumu. CompanyDatabase açıksa onu kullanır."""
    from database.session_manager import oturum

    if oturum.oturum_acik and not company_db.acik:
        raise RuntimeError(
            "Aktif firma veritabanı seçilmedi. Firmaya yeniden giriş yapın."
        )
    if company_db.acik:
        with company_db.get_session() as session:
            yield session
        return
    session = SessionLocal()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


@contextmanager
def get_system_session() -> Generator:
    if SystemSessionLocal is None:
        raise RuntimeError("Sistem veritabanı henüz başlatılmadı.")
    session = SystemSessionLocal()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def sistem_altyapisini_baslat() -> dict:
    """
    AŞAMA 2: system.db + roller/admin + Ray Mobilya → mevcut muhasebe.db.
    Operasyon verisine dokunmaz; yalnızca bağlar.
    """
    global system_engine, SystemSessionLocal

    from database.system.bootstrap import sistem_baslat, system_engine_olustur
    from database.session_manager import oturum

    sonuc = sistem_baslat(
        system_db_path=SYSTEM_DB_PATH,
        muhasebe_db_path=DB_PATH,
        sifre_dosyasi=DB_DIR / "ILK_YONETICI_SIFRE.txt",
    )

    system_engine = system_engine_olustur(SYSTEM_DB_PATH)
    SystemSessionLocal = sessionmaker(
        bind=system_engine,
        autoflush=False,
        autocommit=False,
        expire_on_commit=False,
    )

    company_id = sonuc["company_id"]
    company_path = Path(sonuc["company_db"])
    if company_id is not None:
        firma_db_ac(int(company_id), company_path)
        from database.system.models import Company

        with get_system_session() as session:
            firma = session.get(Company, int(company_id))
            if firma is not None:
                oturum.set_company(
                    company_id=firma.id,
                    firma_kodu=firma.firma_kodu,
                    firma_unvan=firma.unvan,
                    firma_uid=firma.firma_uid,
                    db_path=firma.db_path,
                )

    _konum_dosyasi_yaz(Path(sonuc["company_db"]))
    return sonuc


def cari_kart_schemasini_guncelle() -> None:
    """Eksik cari alanlarını mevcut SQLite tablosuna veri kaybetmeden ekler."""
    tablo = "cari_kartlar"
    mevcut_sutunlar = {sutun["name"] for sutun in inspect(engine).get_columns(tablo)}
    eklenecekler = {
        "vergi_dairesi": "VARCHAR(100)",
        "vergi_numarasi": "VARCHAR(20)",
        "tc_kimlik": "VARCHAR(11)",
        "musteri_grubu": "VARCHAR(100)",
        "ozel_notlar": "VARCHAR(1000)",
        "uyari_notu": "VARCHAR(1000)",
        "il": "VARCHAR(50)",
        "ilce": "VARCHAR(50)",
        "telefon2": "VARCHAR(30)",
        "telefon3": "VARCHAR(30)",
        "adres_tipi": "VARCHAR(40)",
        "adres2": "VARCHAR(500)",
        "il2": "VARCHAR(50)",
        "ilce2": "VARCHAR(50)",
        "adres_tipi2": "VARCHAR(40)",
        "adres3": "VARCHAR(500)",
        "il3": "VARCHAR(50)",
        "ilce3": "VARCHAR(50)",
        "adres_tipi3": "VARCHAR(40)",
        "satis_fiyat_listesi": "VARCHAR(100)",
        "alis_fiyat_listesi": "VARCHAR(100)",
        "acik_hesap_risk_limiti": "NUMERIC(18, 2)",
        "cek_risk_limiti": "NUMERIC(18, 2)",
        "senet_risk_limiti": "NUMERIC(18, 2)",
        "satis_vade_gunu": "INTEGER",
        "alis_vade_gunu": "INTEGER",
        "muhasebe_borclu_kodu": "VARCHAR(50)",
        "muhasebe_alacakli_kodu": "VARCHAR(50)",
        "muhasebe_satis_kodu": "VARCHAR(50)",
        "muhasebe_alis_kodu": "VARCHAR(50)",
        "muhasebe_kdv_satis_kodu": "VARCHAR(50)",
        "muhasebe_kdv_alis_kodu": "VARCHAR(50)",
    }
    eksikler = {
        alan: tip for alan, tip in eklenecekler.items() if alan not in mevcut_sutunlar
    }
    if not eksikler:
        pass
    else:
        with engine.begin() as connection:
            for alan, tip in eksikler.items():
                connection.execute(text(f'ALTER TABLE "{tablo}" ADD COLUMN "{alan}" {tip}'))

    # İade satırına FIFO maliyet kolonu
    iade_tablo = "satis_iade_faturasi_satirlari"
    if inspect(engine).has_table(iade_tablo):
        iade_sutunlar = {sutun["name"] for sutun in inspect(engine).get_columns(iade_tablo)}
        if "fifo_birim_maliyeti" not in iade_sutunlar:
            with engine.begin() as connection:
                connection.execute(
                    text(f'ALTER TABLE "{iade_tablo}" ADD COLUMN "fifo_birim_maliyeti" NUMERIC(18, 4) DEFAULT 0 NOT NULL')
                )

    stok_tablo = "stok_kartlari"
    if inspect(engine).has_table(stok_tablo):
        stok_sutunlar = {sutun["name"] for sutun in inspect(engine).get_columns(stok_tablo)}
        stok_eklenecekler = {
            "kart_turu": "VARCHAR(50) DEFAULT 'Ticari Mal' NOT NULL",
            "aciklama": "TEXT",
            "muhasebe_stok_kodu": "VARCHAR(50)",
            "muhasebe_alis_kodu": "VARCHAR(50)",
            "muhasebe_satis_kodu": "VARCHAR(50)",
            "muhasebe_maliyet_kodu": "VARCHAR(50)",
            "muhasebe_kdv_alis_kodu": "VARCHAR(50)",
            "muhasebe_kdv_satis_kodu": "VARCHAR(50)",
            "kdv_orani": "NUMERIC(7, 2) DEFAULT 20 NOT NULL",
            "iskonto_1": "NUMERIC(8, 4) DEFAULT 0 NOT NULL",
            "iskonto_2": "NUMERIC(8, 4) DEFAULT 0 NOT NULL",
            "iskonto_3": "NUMERIC(8, 4) DEFAULT 0 NOT NULL",
            "marka": "VARCHAR(100)",
            "model": "VARCHAR(100)",
            "fonksiyon1": "VARCHAR(100)",
            "fonksiyon2": "VARCHAR(100)",
            "renk": "VARCHAR(50)",
            "agirlik": "VARCHAR(50)",
            "birim1": "VARCHAR(30)",
            "birim2": "VARCHAR(30)",
            "birim3": "VARCHAR(30)",
            "rapor_grubu": "VARCHAR(100)",
            "raf_yeri": "VARCHAR(100)",
            "raf_omru": "DATE",
        }
        with engine.begin() as connection:
            for alan, tip in stok_eklenecekler.items():
                if alan not in stok_sutunlar:
                    connection.execute(text(f'ALTER TABLE "{stok_tablo}" ADD COLUMN "{alan}" {tip}'))

    barkod_tablo = "stok_barkodlari"
    if inspect(engine).has_table(barkod_tablo):
        barkod_sutunlar = {sutun["name"] for sutun in inspect(engine).get_columns(barkod_tablo)}
        if "fiyat_adi" not in barkod_sutunlar:
            with engine.begin() as connection:
                connection.execute(
                    text(f'ALTER TABLE "{barkod_tablo}" ADD COLUMN "fiyat_adi" VARCHAR(100)')
                )

    for fatura_tablo in ("alis_faturalari", "satis_faturalari"):
        if inspect(engine).has_table(fatura_tablo):
            sutunlar = {sutun["name"] for sutun in inspect(engine).get_columns(fatura_tablo)}
            if "islem_saati" not in sutunlar:
                with engine.begin() as connection:
                    connection.execute(
                        text(f'ALTER TABLE "{fatura_tablo}" ADD COLUMN "islem_saati" VARCHAR(8)')
                    )

    # Mevcut satış faturaları zaten hareket üretmiş sayılır (DEFAULT 1).
    if inspect(engine).has_table("satis_faturalari"):
        satis_sutunlar = {s["name"] for s in inspect(engine).get_columns("satis_faturalari")}
        if "onaylandi" not in satis_sutunlar:
            with engine.begin() as connection:
                connection.execute(
                    text(
                        'ALTER TABLE "satis_faturalari" '
                        'ADD COLUMN "onaylandi" BOOLEAN DEFAULT 1 NOT NULL'
                    )
                )

    satis_satir_tablo = "satis_faturasi_satirlari"
    if inspect(engine).has_table(satis_satir_tablo):
        satir_sutunlar = {sutun["name"] for sutun in inspect(engine).get_columns(satis_satir_tablo)}
        for alan in ("iskonto_orani_2", "iskonto_orani_3"):
            if alan not in satir_sutunlar:
                with engine.begin() as connection:
                    connection.execute(
                        text(
                            f'ALTER TABLE "{satis_satir_tablo}" '
                            f'ADD COLUMN "{alan}" NUMERIC(7, 2) DEFAULT 0 NOT NULL'
                        )
                    )

    finans_tablo = "finans_hesaplari"
    if inspect(engine).has_table(finans_tablo):
        finans_sutunlar = {sutun["name"] for sutun in inspect(engine).get_columns(finans_tablo)}
        finans_eklenecekler = {
            "banka_adi": "VARCHAR(100)",
            "sube": "VARCHAR(100)",
            "iban": "VARCHAR(34)",
            "aciklama": "VARCHAR(500)",
            "banka_karti_id": "INTEGER",
            "alt_hesap_turu": "VARCHAR(30)",
        }
        with engine.begin() as connection:
            for alan, tip in finans_eklenecekler.items():
                if alan not in finans_sutunlar:
                    connection.execute(text(f'ALTER TABLE "{finans_tablo}" ADD COLUMN "{alan}" {tip}'))

    banka_tablo = "banka_kartlari"
    if inspect(engine).has_table(banka_tablo):
        banka_sutunlar = {sutun["name"] for sutun in inspect(engine).get_columns(banka_tablo)}
        banka_eklenecekler = {
            "kk_komisyon_orani": "NUMERIC(8, 4) DEFAULT 0 NOT NULL",
            "banka_karti_komisyon_orani": "NUMERIC(8, 4) DEFAULT 0 NOT NULL",
            "pos_valor_gun": "INTEGER DEFAULT 1 NOT NULL",
            "kmh_limiti": "NUMERIC(18, 2) DEFAULT 0 NOT NULL",
        }
        with engine.begin() as connection:
            for alan, tip in banka_eklenecekler.items():
                if alan not in banka_sutunlar:
                    connection.execute(text(f'ALTER TABLE "{banka_tablo}" ADD COLUMN "{alan}" {tip}'))

    valor_tablo = "pos_valor_kayitlari"
    if inspect(engine).has_table(valor_tablo):
        valor_sutunlar = {sutun["name"] for sutun in inspect(engine).get_columns(valor_tablo)}
        if "taksit_sayisi" not in valor_sutunlar:
            with engine.begin() as connection:
                connection.execute(
                    text(
                        f'ALTER TABLE "{valor_tablo}" '
                        'ADD COLUMN "taksit_sayisi" INTEGER DEFAULT 1 NOT NULL'
                    )
                )

    kk_tablo = "kredi_karti_tanimlari"
    if inspect(engine).has_table(kk_tablo):
        kk_sutunlar = {sutun["name"] for sutun in inspect(engine).get_columns(kk_tablo)}
        kk_eklenecekler = {
            "kart_bankasi": "VARCHAR(100)",
            "kart_sahibi": "VARCHAR(100)",
            "kart_markasi": "VARCHAR(30)",
            "kart_numarasi": "VARCHAR(32)",
            "son_kullanim": "VARCHAR(7)",
            "guvenlik_kodu": "VARCHAR(4)",
        }
        with engine.begin() as connection:
            for alan, tip in kk_eklenecekler.items():
                if alan not in kk_sutunlar:
                    connection.execute(text(f'ALTER TABLE "{kk_tablo}" ADD COLUMN "{alan}" {tip}'))

    hizmet_tablo = "hizmet_kartlari"
    if inspect(engine).has_table(hizmet_tablo):
        hizmet_sutunlar = {sutun["name"] for sutun in inspect(engine).get_columns(hizmet_tablo)}
        if "gider_sinifi" not in hizmet_sutunlar:
            with engine.begin() as connection:
                connection.execute(
                    text(f'ALTER TABLE "{hizmet_tablo}" ADD COLUMN "gider_sinifi" VARCHAR(20)')
                )

    gider_fisi_tablo = "gider_fisleri"
    if inspect(engine).has_table(gider_fisi_tablo):
        gider_sutunlar = {sutun["name"] for sutun in inspect(engine).get_columns(gider_fisi_tablo)}
        if "hizmet_id" not in gider_sutunlar:
            with engine.begin() as connection:
                connection.execute(
                    text(f'ALTER TABLE "{gider_fisi_tablo}" ADD COLUMN "hizmet_id" INTEGER')
                )

    doviz_schema_guncelle()
    donem_schemasini_guncelle()
    hizli_satis_schema_hazirla()
    try:
        from database.user_audit import belge_kullanici_schema_guncelle

        belge_kullanici_schema_guncelle()
    except Exception:
        pass
    try:
        from database.teklif_service import QuoteService

        QuoteService.schema_hazirla()
    except Exception:
        pass
    try:
        from database.satis_irsaliyesi_service import SatisIrsaliyesiService

        SatisIrsaliyesiService.schema_hazirla()
    except Exception:
        pass


def donem_schemasini_guncelle() -> None:
    """donemler tablosuna kapali/varsayilan kolonları (veri kaybetmeden)."""
    if not inspect(engine).has_table("donemler"):
        return
    sutunlar = {s["name"] for s in inspect(engine).get_columns("donemler")}
    eklenecekler = {
        "kapali": "BOOLEAN DEFAULT 0 NOT NULL",
        "varsayilan": "BOOLEAN DEFAULT 0 NOT NULL",
    }
    with engine.begin() as connection:
        for alan, tip in eklenecekler.items():
            if alan not in sutunlar:
                connection.execute(text(f'ALTER TABLE "donemler" ADD COLUMN "{alan}" {tip}'))


def hizli_satis_schema_hazirla() -> None:
    """Hızlı Satış bekleyen sepet tabloları (checkfirst; stok rezervasyonu yok)."""
    try:
        from database.hizli_satis_service import HizliSatisService

        HizliSatisService.schema_hazirla()
    except Exception:
        # Firma DB henüz bağlı değilse / model import gecikmesi — main.py ayrıca çağırır
        pass


def doviz_schema_guncelle() -> None:
    """Dövizli muhasebe tabloları ve kolonları (mevcut veriyi koruyarak)."""
    insp = inspect(engine)

    if not insp.has_table("doviz_kurlari"):
        from database.models.doviz import DovizKuru  # noqa: F401

        DovizKuru.__table__.create(engine, checkfirst=True)

    def _ekle(tablo: str, kolonlar: dict[str, str]) -> None:
        if not insp.has_table(tablo):
            return
        mevcut = {s["name"] for s in insp.get_columns(tablo)}
        eksik = {a: t for a, t in kolonlar.items() if a not in mevcut}
        if not eksik:
            return
        with engine.begin() as connection:
            for alan, tip in eksik.items():
                connection.execute(text(f'ALTER TABLE "{tablo}" ADD COLUMN "{alan}" {tip}'))

    fatura_doviz = {
        "para_birimi": "VARCHAR(3) DEFAULT 'TRY' NOT NULL",
        "kur": "NUMERIC(18, 6) DEFAULT 1 NOT NULL",
        "kur_tarihi": "DATE",
        "kur_turu": "VARCHAR(30) DEFAULT 'forex_selling' NOT NULL",
        "kur_kaynagi": "VARCHAR(20) DEFAULT 'TCMB' NOT NULL",
        "kur_sabitlendi": "BOOLEAN DEFAULT 0 NOT NULL",
        "borc_esasi": "VARCHAR(20) DEFAULT 'TL_SABIT' NOT NULL",
        "doviz_ara_toplam": "NUMERIC(18, 2) DEFAULT 0 NOT NULL",
        "tl_matrah": "NUMERIC(18, 2) DEFAULT 0 NOT NULL",
        "tl_kdv": "NUMERIC(18, 2) DEFAULT 0 NOT NULL",
        "tl_genel_toplam": "NUMERIC(18, 2) DEFAULT 0 NOT NULL",
        "adres_no": "INTEGER",
        "adres_tipi": "VARCHAR(40)",
        "adres_metni": "VARCHAR(500)",
    }
    _ekle("satis_faturalari", fatura_doviz)
    _ekle(
        "alis_faturalari",
        {
            k: v
            for k, v in fatura_doviz.items()
            if k not in ("borc_esasi", "adres_no", "adres_tipi", "adres_metni")
        },
    )

    satir_doviz = {
        "birim_fiyat_doviz": "NUMERIC(18, 4) DEFAULT 0 NOT NULL",
        "tl_birim_fiyat": "NUMERIC(18, 4) DEFAULT 0 NOT NULL",
        "tl_tutar": "NUMERIC(18, 2) DEFAULT 0 NOT NULL",
    }
    _ekle("satis_faturasi_satirlari", satir_doviz)
    _ekle("alis_faturasi_satirlari", satir_doviz)

    _ekle(
        "satis_faturasi_tahsilatlari",
        {
            "kur_farki": "NUMERIC(18, 2) DEFAULT 0 NOT NULL",
            "odeme_kuru": "NUMERIC(18, 6) DEFAULT 0 NOT NULL",
        },
    )
    _ekle(
        "cari_satis_hareketleri",
        {
            "para_birimi": "VARCHAR(3) DEFAULT 'TRY' NOT NULL",
            "doviz_tutari": "NUMERIC(18, 2) DEFAULT 0 NOT NULL",
            "kur": "NUMERIC(18, 6) DEFAULT 1 NOT NULL",
            "borc_esasi": "VARCHAR(20) DEFAULT 'TL_SABIT' NOT NULL",
        },
    )
    _ekle(
        "cari_islemleri",
        {
            "para_birimi": "VARCHAR(3) DEFAULT 'TRY' NOT NULL",
            "doviz_borc": "NUMERIC(18, 2) DEFAULT 0 NOT NULL",
            "doviz_alacak": "NUMERIC(18, 2) DEFAULT 0 NOT NULL",
            "kur": "NUMERIC(18, 6) DEFAULT 1 NOT NULL",
            "borc_esasi": "VARCHAR(20) DEFAULT 'TL_SABIT' NOT NULL",
        },
    )

    _ekle("hizmet_faturalari", fatura_doviz)
    _ekle("hizmet_faturasi_satirlari", satir_doviz)
    _ekle("satis_iade_faturalari", fatura_doviz)
    _ekle("alis_iade_faturalari", {k: v for k, v in fatura_doviz.items() if k != "borc_esasi"})
    _ekle(
        "satis_iade_faturasi_satirlari",
        {"birim_fiyat_doviz": "NUMERIC(18, 4) DEFAULT 0 NOT NULL"},
    )
    _ekle(
        "alis_iade_faturasi_satirlari",
        {"birim_fiyat_doviz": "NUMERIC(18, 4) DEFAULT 0 NOT NULL"},
    )


def musteri_gruplarini_hazirla() -> None:
    from database.models.cari import MusteriGrubu

    baslangic_gruplari = (
        "PERAKENDE MÜŞTERİ",
        "MOBİLYA ATÖLYELERİ",
        "ÜRETİCİ FABRİKALAR",
        "NALBUR",
        "TESİSATÇILAR",
        "DİĞER",
    )
    mevcut_gruplar = set()
    with get_session() as session:
        mevcut_gruplar.update(session.scalars(select(MusteriGrubu.ad)).all())
        for grup_adi in baslangic_gruplari:
            if grup_adi not in mevcut_gruplar:
                session.add(MusteriGrubu(ad=grup_adi))
    perakende_cari_hazirla()


def perakende_cari_hazirla() -> None:
    """Hızlı Satış varsayılanı: PERAKENDE MÜŞTERİ cari kartı (yoksa oluşturur).

    Müşteri grubu zaten seed edilir; POS için gerçek bir cari_id gerekir.
    Yetki kontrolü yok — kurulum/seed yolu (musteri_gruplarini_hazirla ile aynı).
    """
    from database.models.cari import Cari
    from hizli_satis_musteri import (
        PERAKENDE_MUSTERI_GRUP,
        PERAKENDE_MUSTERI_KOD,
        PERAKENDE_MUSTERI_UNVAN,
        VARSAYILAN_FIYAT_LISTESI,
        varsayilan_cari_bul,
    )

    with get_session() as session:
        if varsayilan_cari_bul(session) is not None:
            return
        # Kod çakışırsa sıradaki PRK00n dene
        kod = PERAKENDE_MUSTERI_KOD
        for i in range(1, 100):
            aday = f"PRK{i:03d}"
            var = session.scalar(select(Cari).where(Cari.cari_kodu == aday))
            if var is None:
                kod = aday
                break
        else:
            return
        session.add(
            Cari(
                cari_kodu=kod,
                unvan=PERAKENDE_MUSTERI_UNVAN,
                cari_turu="Müşteri",
                musteri_grubu=PERAKENDE_MUSTERI_GRUP,
                satis_fiyat_listesi=VARSAYILAN_FIYAT_LISTESI,
                aktif=True,
                is_deleted=False,
            )
        )


def tedarikci_odeme_polarity_duzelt() -> None:
    """Tedarikçi Ödeme satırlarını alacak olarak düzelt; fazla ödemeyi FZO kredisine yaz.

    Eski kod tedarikçi ödemesini borc yazıyordu (müşteri mantığı). Defter bakiyesi
    şişiyordu. Güvenli ve tekrar çalıştırılabilir.
    """
    from datetime import date
    from decimal import Decimal

    prefix_skip = (
        "ODM-", "VRM-", "KKC-", "THS-", "AHV-", "GHV-", "POS-", "BNC-", "KBY-", "KKO-",
        "IPT-", "FZO-", "TMK-", "OMK-", "GDF-",
    )

    def _d(x) -> Decimal:
        return Decimal(str(x or 0))

    def _defter_bakiye(conn, cari_id: int) -> Decimal:
        islemler = conn.execute(
            text(
                "SELECT tarih, islem_turu, belge_no, borc, alacak "
                "FROM cari_islemleri WHERE cari_id = :cid"
            ),
            {"cid": cari_id},
        ).mappings().all()
        islem_belgeleri = {r["belge_no"] for r in islemler}
        hareketler = conn.execute(
            text(
                "SELECT satis_tarihi, belge_no, satis_tutari "
                "FROM cari_satis_hareketleri WHERE cari_id = :cid"
            ),
            {"cid": cari_id},
        ).mappings().all()
        kayitlar: list[tuple] = []
        for h in hareketler:
            bn = h["belge_no"] or ""
            if bn in islem_belgeleri or bn.startswith(prefix_skip):
                continue
            kayitlar.append((h["satis_tarihi"], bn, "SH", _d(h["satis_tutari"]), Decimal("0")))
        for i in islemler:
            kayitlar.append(
                (i["tarih"], i["belge_no"], i["islem_turu"], _d(i["borc"]), _d(i["alacak"]))
            )
        kayitlar.sort(key=lambda x: (x[0] or "", x[1] or "", x[2] or ""))
        calisan = Decimal("0")
        for _, _, _, borc, alacak in kayitlar:
            calisan += borc - alacak
        return calisan

    with engine.begin() as conn:
        # 1) Yanlış polariteli tedarikçi ödemeleri: borc → alacak
        conn.execute(
            text(
                """
                UPDATE cari_islemleri
                SET alacak = borc, borc = 0
                WHERE islem_turu = 'Ödeme'
                  AND borc > 0
                  AND alacak = 0
                  AND cari_id IN (
                      SELECT id FROM cari_kartlar WHERE cari_turu = 'Tedarikçi'
                  )
                """
            )
        )

        tedarikciler = conn.execute(
            text("SELECT id FROM cari_kartlar WHERE cari_turu = 'Tedarikçi'")
        ).scalars().all()

        bugun = date.today().isoformat()
        for cari_id in tedarikciler:
            fzo_no = f"FZO-{cari_id}"
            satirlar = conn.execute(
                text(
                    "SELECT id, belge_no, kalan_acik_tutar "
                    "FROM cari_satis_hareketleri WHERE cari_id = :cid"
                ),
                {"cid": cari_id},
            ).mappings().all()
            mevcut_fzo = next((s for s in satirlar if s["belge_no"] == fzo_no), None)
            net_acik = sum(
                (_d(s["kalan_acik_tutar"]) for s in satirlar if s["belge_no"] != fzo_no),
                Decimal("0"),
            )
            bakiye = _defter_bakiye(conn, cari_id)
            fark = (net_acik - bakiye).quantize(Decimal("0.01"))
            if fark > Decimal("0.00"):
                if mevcut_fzo is None:
                    conn.execute(
                        text(
                            """
                            INSERT INTO cari_satis_hareketleri
                            (cari_id, satis_tarihi, belge_no, satis_tutari, kalan_acik_tutar)
                            VALUES (:cid, :tarih, :belge, 0, :kalan)
                            """
                        ),
                        {"cid": cari_id, "tarih": bugun, "belge": fzo_no, "kalan": float(-fark)},
                    )
                else:
                    conn.execute(
                        text(
                            """
                            UPDATE cari_satis_hareketleri
                            SET satis_tutari = 0, kalan_acik_tutar = :kalan
                            WHERE id = :id
                            """
                        ),
                        {"id": mevcut_fzo["id"], "kalan": float(-fark)},
                    )
            elif mevcut_fzo is not None:
                conn.execute(
                    text("DELETE FROM cari_satis_hareketleri WHERE id = :id"),
                    {"id": mevcut_fzo["id"]},
                )
