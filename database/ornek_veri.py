"""Test kurulumu için az sayıda örnek müşteri / tedarikçi / ürün.

Her kayıt ünvanında / adında açıkça "ÖRNEK VERİ" taşır ve kodları ``ORN-`` ile başlar.
Yalnız boş (test) firma veritabanına, kullanıcı ilk açılışta isterse eklenir.
"""

from __future__ import annotations

from decimal import Decimal

from sqlalchemy import func, select

ORNEK_ETIKET = "ÖRNEK VERİ"
ORNEK_KOD_ONEKI = "ORN-"
ORNEK_ACIKLAMA = "ÖRNEK VERİ — test kurulumu için otomatik eklendi; gerçek kayıt değildir."
ORNEK_DEPO = "ANA DEPO"
ORNEK_ACILIS_MIKTARI = Decimal("100")

ORNEK_CARILER = (
    ("ORN-M001", "ÖRNEK VERİ - Deneme Mobilya Ltd. Şti.", "Müşteri", "İstanbul", "Kadıköy"),
    ("ORN-M002", "ÖRNEK VERİ - Test Dekorasyon A.Ş.", "Müşteri", "Ankara", "Çankaya"),
    ("ORN-M003", "ÖRNEK VERİ - Örnek Marangoz Atölyesi", "Müşteri", "İzmir", "Bornova"),
    ("ORN-T001", "ÖRNEK VERİ - Deneme Aksesuar Tedarik", "Tedarikçi", "Bursa", "Nilüfer"),
)

# kod, ad, ana birim, alış, satış, (ek birim, çarpan)
ORNEK_URUNLER = (
    ("ORN-001", "ÖRNEK VERİ - Sunta Vidası 4x40", "Adet", "0.45", "0.90", ("Koli", "500")),
    ("ORN-002", "ÖRNEK VERİ - Menteşe 35 mm", "Adet", "12.50", "22.00", ("Paket", "10")),
    ("ORN-003", "ÖRNEK VERİ - Çekmece Rayı 45 cm", "Takım", "85.00", "140.00", None),
    ("ORN-004", "ÖRNEK VERİ - Kulp 128 mm", "Adet", "18.00", "32.50", None),
    ("ORN-005", "ÖRNEK VERİ - Kenar Bandı 22 mm", "Metre", "1.20", "2.40", None),
)


def ornek_veri_var_mi() -> bool:
    from database.database import get_session
    from database.models.cari import Cari

    with get_session() as s:
        return bool(
            s.scalar(select(func.count(Cari.id)).where(Cari.cari_kodu.like(f"{ORNEK_KOD_ONEKI}%")))
        )


def ornek_veri_ekle() -> dict[str, int]:
    """Örnek kayıtları ekler; zaten varsa hiçbir şey yapmaz (idempotent)."""
    from database.database import get_session
    from database.models.cari import Cari
    from database.models.stok import StokBirim, StokFiyati, StokKarti

    eklenen = {"cari": 0, "stok": 0}
    yeni_urunler: list[tuple[str, str]] = []
    with get_session() as s:
        mevcut_cari = set(
            s.scalars(select(Cari.cari_kodu).where(Cari.cari_kodu.like(f"{ORNEK_KOD_ONEKI}%"))).all()
        )
        mevcut_stok = set(
            s.scalars(
                select(StokKarti.stok_kodu).where(StokKarti.stok_kodu.like(f"{ORNEK_KOD_ONEKI}%"))
            ).all()
        )
        for kod, unvan, tur, il, ilce in ORNEK_CARILER:
            if kod in mevcut_cari:
                continue
            s.add(
                Cari(
                    cari_kodu=kod,
                    unvan=unvan,
                    cari_turu=tur,
                    il=il,
                    ilce=ilce,
                    adres="Örnek adres (test)",
                    telefon="0000 000 00 00",
                    ozel_notlar=ORNEK_ACIKLAMA,
                )
            )
            eklenen["cari"] += 1
        for kod, ad, birim, alis, satis, ek in ORNEK_URUNLER:
            if kod in mevcut_stok:
                continue
            kart = StokKarti(stok_kodu=kod, stok_adi=ad, birim=birim, aciklama=ORNEK_ACIKLAMA)
            kart.fiyatlar.append(StokFiyati(fiyat_adi="ALIŞ FİYATI", tutar=Decimal(alis), para_birimi="TL"))
            kart.fiyatlar.append(
                StokFiyati(fiyat_adi="SATIŞ FİYATI 1", tutar=Decimal(satis), para_birimi="TL")
            )
            if ek:
                kart.birimler.append(StokBirim(birim_adi=ek[0], carpan=Decimal(ek[1])))
            s.add(kart)
            eklenen["stok"] += 1
            yeni_urunler.append((kod, alis))
    # Satış faturası onayı stok ister; örnek ürünlere açılış girişi (yalnız yeni eklenenlere)
    if yeni_urunler:
        from datetime import date

        from database.models.stok import Depo
        from database.stok_service import StokService

        with get_session() as s:
            depo_var = s.scalar(select(Depo.id).where(Depo.ad == ORNEK_DEPO)) is not None
        if depo_var:
            for kod, alis in yeni_urunler:
                StokService._stok_girisi_kaydet(
                    kod, ORNEK_DEPO, "ÖRNEK VERİ", date.today(), ORNEK_ACILIS_MIKTARI, Decimal(alis),
                    lot_no=f"ORNEK-{kod}",
                )
    return eklenen
