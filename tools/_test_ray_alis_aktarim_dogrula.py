"""TEST Ray: firma açılışı gibi şema güncelle + tam/kısmi aktarım, mükerrer, stok çoğalmama.

Mevcut Ray verisine dokunmadan yalnızca CURSOR_TEST_* belgeler oluşturur; sonda iptal eder.
"""
from __future__ import annotations

import os
import sys
import uuid
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ.setdefault(
    "MUHASEBE_DB_DIR",
    str(Path(os.environ.get("LOCALAPPDATA", "")) / "CinMuhasebeTest" / "data"),
)

BUGUN = date.today()
TAG = f"CURSOR_TEST_{BUGUN.strftime('%Y%m%d')}_{uuid.uuid4().hex[:8]}"


def main() -> int:
    from sqlalchemy import func, inspect, select, text

    import database.models.kart_turu  # noqa: F401
    import database.models.stok  # noqa: F401
    import database.models.cari  # noqa: F401
    import database.models.alis_siparisi  # noqa: F401
    import database.models.alis_irsaliyesi  # noqa: F401
    import database.models.alis_faturasi  # noqa: F401

    from database.alis_faturasi_service import AlisFaturasiService, MukerrerTedarikciFaturaHatasi
    from database.alis_irsaliyesi_service import AlisIrsaliyesiService
    from database.alis_siparisi_service import AlisSiparisiService
    from database.database import firma_db_ac, get_session
    from database.models.cari import Cari
    from database.models.donem import Donem
    from database.models.stok import Depo, StokHareketi, StokKarti, StokLotu
    from database.session_manager import oturum

    data = Path(os.environ["MUHASEBE_DB_DIR"])
    db_path = data / "muhasebe.db"
    print("1) firma_db_ac (normal firma açılışı yolu)", db_path)
    firma_db_ac(1, db_path)
    oturum.set_user(
        user_id=1,
        kullanici_adi="test",
        ad_soyad="Test",
        role_kod="YONETICI",
        role_ad="Yönetici",
        permissions=set(),
    )
    oturum.set_company(
        company_id=1,
        firma_kodu="RAY001",
        firma_unvan="Ray Mobilya Aksesuarları",
        firma_uid="d261e324-6176-4bbd-87af-a77265cdb87b",
        db_path=str(db_path),
    )
    with get_session() as s:
        d = s.scalar(select(Donem).where(Donem.aktif.is_(True)).limit(1)) or s.scalar(select(Donem).limit(1))
        if d:
            oturum.set_period(d.id, d.donem_adi)

    from database.database import engine

    cols = {c["name"] for c in inspect(engine).get_columns("alis_irsaliyeleri")}
    print("2) giris_depo kolonu:", "giris_depo" in cols, "(beklenen: True)")
    if "giris_depo" not in cols:
        print("FAIL: firma_db_ac sonrası giris_depo yok")
        return 2

    irs_list = AlisFaturasiService.acik_irsaliyeler()
    print("3) acik_irsaliyeler() OK, adet=", len(irs_list))

    # Depo + stok + tedarikçi (test için mevcut veya oluştur)
    with get_session() as s:
        depo = s.scalar(select(Depo).where(Depo.aktif.is_(True)).limit(1))
        if depo is None:
            depo = Depo(ad="ANA DEPO", aktif=True)
            s.add(depo)
            s.flush()
        depo_ad = depo.ad
        stok = s.scalar(select(StokKarti).where(StokKarti.stok_kodu == "CURSOR_TEST_U1"))
        if stok is None:
            stok = StokKarti(
                stok_kodu="CURSOR_TEST_U1",
                stok_adi="Cursor Test Ürün",
                birim="Adet",
                aktif=True,
                is_deleted=False,
            )
            s.add(stok)
            s.flush()
        stok_id = stok.id
        cari = s.scalar(select(Cari).where(Cari.cari_kodu == "CURSOR_TED"))
        if cari is None:
            cari = Cari(
                cari_kodu="CURSOR_TED",
                unvan="Cursor Test Tedarikçi",
                cari_turu="Tedarikçi",
                aktif=True,
            )
            s.add(cari)
            s.flush()
        cari_id = cari.id
        s.commit()

    def stok_ozet():
        with get_session() as s:
            lot = s.scalar(
                select(func.coalesce(func.sum(StokLotu.kalan_miktar), 0)).where(StokLotu.stok_id == stok_id)
            )
            har = s.scalar(
                select(func.count()).select_from(StokHareketi).where(StokHareketi.stok_id == stok_id)
            )
            return Decimal(str(lot or 0)), int(har or 0)

    onceki_lot, onceki_har = stok_ozet()
    print("4) stok öncesi lot/hareket:", onceki_lot, onceki_har)

    muhasebe_patch = patch("database.muhasebe_entegrasyon.muhasebe_hook", lambda *_a, **_k: None)
    muhasebe_patch.start()
    fatura_ids: list[int] = []
    irsaliye_ids: list[int] = []
    siparis_ids: list[int] = []
    try:
        sip = AlisSiparisiService.kaydet(
            {
                "siparis_tarihi": BUGUN,
                "termin_tarihi": BUGUN + timedelta(days=7),
                "cari_id": cari_id,
                "siparis_no": f"{TAG}-SIP",
            },
            [
                {
                    "urun_kodu": "CURSOR_TEST_U1",
                    "urun_adi": "Cursor Test Ürün",
                    "miktar": "100",
                    "birim": "Adet",
                    "birim_alis_fiyati": "2",
                    "kdv_orani": "20",
                }
            ],
            [],
        )
        sip = AlisSiparisiService.getir(sip.id)
        siparis_ids.append(sip.id)
        print("5) sipariş", sip.siparis_no, "durum", sip.durum)

        # Kısmi irsaliye 60
        sat = sip.satirlar[0]
        irs = AlisIrsaliyesiService.kaydet(
            {
                "irsaliye_tarihi": BUGUN,
                "cari_id": cari_id,
                "siparis_id": sip.id,
                "irsaliye_no": f"{TAG}-IRS",
                "giris_depo": depo_ad,
            },
            [
                {
                    "siparis_satiri_id": sat.id,
                    "urun_kodu": sat.urun_kodu,
                    "urun_adi": sat.urun_adi,
                    "miktar": "60",
                    "birim": sat.birim,
                    "birim_fiyat": str(sat.birim_alis_fiyati),
                    "kdv_orani": "20",
                }
            ],
        )
        irs = AlisIrsaliyesiService.getir(irs.id)
        irsaliye_ids.append(irs.id)
        sip = AlisSiparisiService.getir(sip.id)
        print("6) kısmi irsaliye", irs.irsaliye_no, "siparis durum", sip.durum, "irs durum", irs.durum)
        assert sip.durum in ("KISMİ İRSALİYELİ", "KISMI IRSALIYELI") or "KISM" in sip.durum.upper()

        # Kalan 40 tam irsaliye ikinci belge
        sat = AlisSiparisiService.getir(sip.id).satirlar[0]
        irs2 = AlisIrsaliyesiService.kaydet(
            {
                "irsaliye_tarihi": BUGUN,
                "cari_id": cari_id,
                "siparis_id": sip.id,
                "irsaliye_no": f"{TAG}-IRS2",
                "giris_depo": depo_ad,
            },
            [
                {
                    "siparis_satiri_id": sat.id,
                    "urun_kodu": sat.urun_kodu,
                    "urun_adi": sat.urun_adi,
                    "miktar": "40",
                    "birim": sat.birim,
                    "birim_fiyat": str(sat.birim_alis_fiyati),
                    "kdv_orani": "20",
                }
            ],
        )
        irsaliye_ids.append(irs2.id)
        sip = AlisSiparisiService.getir(sip.id)
        print("7) ikinci irsaliye sonrası siparis", sip.durum)
        # İrsaliye stok üretmez
        lot_a, har_a = stok_ozet()
        print("   stok (irsaliye sonrası, değişmemeli lot):", lot_a, har_a, "önceki", onceki_lot)
        assert lot_a == onceki_lot

        # Kısmi fatura irsaliyeden 60'ın 35'i
        irs = AlisIrsaliyesiService.getir(irs.id)
        i_sat = irs.satirlar[0]
        ted_no = f"{TAG}-TF"
        f1 = AlisFaturasiService.kaydet(
            {
                "fatura_tarihi": BUGUN,
                "vade_tarihi": BUGUN + timedelta(days=30),
                "cari_id": cari_id,
                "irsaliye_id": irs.id,
                "depo": depo_ad,
                "tedarikci_fatura_no": ted_no,
                "fatura_no": f"{TAG}-F1",
            },
            [
                {
                    "urun_kodu": i_sat.urun_kodu,
                    "urun_adi": i_sat.urun_adi,
                    "miktar": "35",
                    "birim": i_sat.birim,
                    "birim_fiyat": str(i_sat.birim_fiyat),
                    "kdv_orani": "20",
                    "irsaliye_satiri_id": i_sat.id,
                }
            ],
        )
        fatura_ids.append(f1.id)
        lot1, har1 = stok_ozet()
        print("8) kısmi fatura stok lot/har:", lot1, har1, "delta lot", lot1 - onceki_lot)
        assert lot1 - onceki_lot == Decimal("35")

        # Mükerrer
        mk = AlisFaturasiService.mukerrer_kontrol(cari_id, ted_no)
        print("9) mükerrer_kontrol", mk)
        assert mk is not None and mk[0] == f1.id
        assert AlisFaturasiService.mukerrer_kontrol(cari_id, ted_no, haric_id=f1.id) is None
        try:
            AlisFaturasiService.kaydet(
                {
                    "fatura_tarihi": BUGUN,
                    "vade_tarihi": BUGUN + timedelta(days=30),
                    "cari_id": cari_id,
                    "depo": depo_ad,
                    "tedarikci_fatura_no": ted_no.lower(),
                    "fatura_no": f"{TAG}-F_DUP",
                },
                [
                    {
                        "urun_kodu": "CURSOR_TEST_U1",
                        "urun_adi": "Cursor Test Ürün",
                        "miktar": "1",
                        "birim": "Adet",
                        "birim_fiyat": "2",
                        "kdv_orani": "20",
                    }
                ],
            )
            print("FAIL: mükerrer fatura kaydı engellenmedi")
            return 3
        except MukerrerTedarikciFaturaHatasi as e:
            print("10) mükerrer engeli OK", e.fatura_id)

        # Kalan 25 aynı irsaliyeden — stok +25, hareket çoğalmaz (2. giriş = 1 yeni hareket)
        irs = AlisIrsaliyesiService.getir(irs.id)
        i_sat = next(x for x in irs.satirlar if x.urun_kodu == "CURSOR_TEST_U1")
        f2 = AlisFaturasiService.kaydet(
            {
                "fatura_tarihi": BUGUN,
                "vade_tarihi": BUGUN + timedelta(days=30),
                "cari_id": cari_id,
                "irsaliye_id": irs.id,
                "depo": depo_ad,
                "tedarikci_fatura_no": f"{TAG}-TF2",
                "fatura_no": f"{TAG}-F2",
            },
            [
                {
                    "urun_kodu": i_sat.urun_kodu,
                    "urun_adi": i_sat.urun_adi,
                    "miktar": "25",
                    "birim": i_sat.birim,
                    "birim_fiyat": str(i_sat.birim_fiyat),
                    "kdv_orani": "20",
                    "irsaliye_satiri_id": i_sat.id,
                }
            ],
        )
        fatura_ids.append(f2.id)
        lot2, har2 = stok_ozet()
        print("11) ikinci kısmi fatura stok:", lot2, har2, "toplam delta", lot2 - onceki_lot)
        assert lot2 - onceki_lot == Decimal("60")
        # Aynı irsaliye satırı için aşırı miktar reddedilmeli
        try:
            AlisFaturasiService.kaydet(
                {
                    "fatura_tarihi": BUGUN,
                    "vade_tarihi": BUGUN + timedelta(days=30),
                    "cari_id": cari_id,
                    "irsaliye_id": irs.id,
                    "depo": depo_ad,
                    "tedarikci_fatura_no": f"{TAG}-TF3",
                    "fatura_no": f"{TAG}-F3",
                },
                [
                    {
                        "urun_kodu": i_sat.urun_kodu,
                        "urun_adi": i_sat.urun_adi,
                        "miktar": "1",
                        "birim": i_sat.birim,
                        "birim_fiyat": str(i_sat.birim_fiyat),
                        "kdv_orani": "20",
                        "irsaliye_satiri_id": i_sat.id,
                    }
                ],
            )
            print("FAIL: aşırı irsaliye aktarımı engellenmedi")
            return 4
        except ValueError as e:
            print("12) aşırı aktarım engeli OK:", str(e)[:120])

        # Yeniden kaydet (aynı fatura) stok çoğaltmamalı
        f2b = AlisFaturasiService.kaydet(
            {
                "fatura_tarihi": BUGUN,
                "vade_tarihi": BUGUN + timedelta(days=30),
                "cari_id": cari_id,
                "irsaliye_id": irs.id,
                "depo": depo_ad,
                "tedarikci_fatura_no": f"{TAG}-TF2",
                "fatura_no": f2.fatura_no,
                "row_version": f2.row_version,
            },
            [
                {
                    "urun_kodu": i_sat.urun_kodu,
                    "urun_adi": i_sat.urun_adi,
                    "miktar": "25",
                    "birim": i_sat.birim,
                    "birim_fiyat": str(i_sat.birim_fiyat),
                    "kdv_orani": "20",
                    "irsaliye_satiri_id": i_sat.id,
                }
            ],
            f2.id,
        )
        lot3, har3 = stok_ozet()
        print("13) yeniden kaydet stok (çoğalmamalı):", lot3, har3)
        assert lot3 == lot2
        print("OZET TAMAM TAG=", TAG)
        return 0
    finally:
        muhasebe_patch.stop()
        # Temizlik: faturaları iptal (stok geri), irsaliye/sipariş iptal mümkünse
        for fid in reversed(fatura_ids):
            try:
                AlisFaturasiService.iptal_et(fid)
                print("iptal fatura", fid)
            except Exception as e:
                print("iptal fatura uyarı", fid, e)
        for iid in reversed(irsaliye_ids):
            try:
                AlisIrsaliyesiService.iptal_et(iid)
                print("iptal irsaliye", iid)
            except Exception as e:
                print("iptal irsaliye uyarı", iid, e)
        lot_son, har_son = stok_ozet()
        print("14) temizlik sonrası stok:", lot_son, har_son, "hedef lot", onceki_lot)
        # Sipariş iptali serviste varsa
        for sid in siparis_ids:
            try:
                if hasattr(AlisSiparisiService, "iptal_et"):
                    AlisSiparisiService.iptal_et(sid)
                    print("iptal siparis", sid)
            except Exception as e:
                print("siparis bırakıldı", sid, e)


if __name__ == "__main__":
    raise SystemExit(main())
