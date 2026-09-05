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
