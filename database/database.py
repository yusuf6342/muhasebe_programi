from pathlib import Path
from contextlib import contextmanager
from collections.abc import Generator

from sqlalchemy import create_engine, inspect, select, text
from sqlalchemy.orm import DeclarativeBase, sessionmaker


# Proje ana klasörü
BASE_DIR = Path(__file__).resolve().parent.parent

# Veritabanı klasörü
DB_DIR = BASE_DIR / "data"
DB_DIR.mkdir(exist_ok=True)

# SQLite veritabanı
DATABASE_URL = f"sqlite:///{DB_DIR / 'muhasebe.db'}"


# Veritabanı bağlantısı
engine = create_engine(
    DATABASE_URL,
    echo=False
)


# Tüm veritabanı modellerimizin temel sınıfı
class Base(DeclarativeBase):
    pass


# Veritabanı oturumu
SessionLocal = sessionmaker(
    bind=engine,
    autoflush=False,
    autocommit=False,
    expire_on_commit=False
)


@contextmanager
def get_session() -> Generator:
    session = SessionLocal()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def cari_kart_schemasini_guncelle() -> None:
    """Eksik cari alanlarını mevcut SQLite tablosuna veri kaybetmeden ekler."""
    tablo = "cari_kartlar"
    mevcut_sutunlar = {sutun["name"] for sutun in inspect(engine).get_columns(tablo)}
    eklenecekler = {
        "vergi_dairesi": "VARCHAR(100)",
        "vergi_numarasi": "VARCHAR(20)",
        "musteri_grubu": "VARCHAR(100)",
        "ozel_notlar": "VARCHAR(1000)",
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
        }
        with engine.begin() as connection:
            for alan, tip in banka_eklenecekler.items():
                if alan not in banka_sutunlar:
                    connection.execute(text(f'ALTER TABLE "{banka_tablo}" ADD COLUMN "{alan}" {tip}'))


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
