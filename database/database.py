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
        "tc_kimlik": "VARCHAR(11)",
        "musteri_grubu": "VARCHAR(100)",
        "ozel_notlar": "VARCHAR(1000)",
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
