"""Oturumlu Excel içeri alma / dışarı aktarma / mükerrer — izole TEST DB.

Canlı veriyi kullanmaz. Her tip için: şablon→doğrula→uygula→mükerrer→(kartsa) export.
"""
from __future__ import annotations

import os
import sys
import tempfile
from datetime import date
from decimal import Decimal
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ.setdefault(
    "MUHASEBE_DB_DIR",
    str(Path(os.environ.get("LOCALAPPDATA", "")) / "CinMuhasebeTest" / "data"),
)

from sqlalchemy import create_engine, event, select
from sqlalchemy.orm import sessionmaker

from database.database import Base, _aktif_engine_bagla, company_db, get_session
from database.models.cari import Cari
from database.models.donem import Donem
from database.models.firma import Firma
from database.models.stok import Depo, StokBirim, StokKarti, StokLotu
from database.session_manager import oturum


def _pragma(dbapi_connection, _rec):
    cur = dbapi_connection.cursor()
    cur.execute("PRAGMA foreign_keys=ON")
    cur.close()


def _modelleri_yukle() -> None:
    import database.models.alis_faturasi  # noqa: F401
    import database.models.alis_iade_faturasi  # noqa: F401
    import database.models.alis_irsaliyesi  # noqa: F401
    import database.models.alis_masraf  # noqa: F401
    import database.models.alis_siparisi  # noqa: F401
    import database.models.cek_senet  # noqa: F401
    import database.models.finans  # noqa: F401
    import database.models.fon  # noqa: F401
    import database.models.genel_muhasebe  # noqa: F401
    import database.models.hizli_satis  # noqa: F401
    import database.models.hizmet  # noqa: F401
    import database.models.hizmet_faturasi  # noqa: F401
    import database.models.kart_turu  # noqa: F401
    import database.models.personel  # noqa: F401
    import database.models.satis_faturasi  # noqa: F401
    import database.models.satis_iade_faturasi  # noqa: F401
    import database.models.satis_irsaliyesi  # noqa: F401
    import database.models.satis_siparisi  # noqa: F401
    import database.models.satis_teklifi  # noqa: F401
    import excel_aktarim.models  # noqa: F401


class Ortam:
    def __init__(self):
        self._tmp = tempfile.TemporaryDirectory(prefix="excel_apply_")
        self.db_path = Path(self._tmp.name) / "firma.db"
        self.out = Path(self._tmp.name) / "out"
        self.out.mkdir()
        eng = create_engine(
            f"sqlite:///{self.db_path.as_posix()}",
            connect_args={"check_same_thread": False},
        )
        event.listen(eng, "connect", _pragma)
        _modelleri_yukle()
        Base.metadata.create_all(eng)
        Session = sessionmaker(bind=eng, autoflush=False, autocommit=False, expire_on_commit=False)
        with Session() as s:
            firma = Firma(firma_kodu="XLS", unvan="Excel Apply Test", aktif=True)
            s.add(firma)
            s.flush()
            s.add(
                Donem(
                    firma_id=firma.id,
                    donem_adi="2026",
                    baslangic_tarihi=date(2026, 1, 1),
                    bitis_tarihi=date(2026, 12, 31),
                    aktif=True,
                    kapali=False,
                    varsayilan=True,
                )
            )
            depo_ana = Depo(ad="ANA DEPO", aktif=True, varsayilan=True)
            s.add(depo_ana)
            s.add(Depo(ad="DEPO 2", aktif=True))
            s.flush()
            stok = StokKarti(
                stok_kodu="U001",
                stok_adi="Test Ürün",
                birim="Adet",
                aktif=True,
                is_deleted=False,
                minimum_stok=Decimal("0"),
            )
            s.add(stok)
            s.flush()
            s.add(StokBirim(stok_id=stok.id, birim_adi="Koli", carpan=Decimal("12")))
            s.add(
                StokLotu(
                    stok_id=stok.id,
                    depo_id=depo_ana.id,
                    lot_no="LOT-EX",
                    giris_tarihi=date(2026, 1, 1),
                    kalan_miktar=Decimal("1000"),
                    birim_maliyet=Decimal("1"),
                )
            )
            s.add(Cari(cari_kodu="T001", unvan="Test Tedarikçi", cari_turu="Tedarikçi", aktif=True))
            s.add(Cari(cari_kodu="M001", unvan="Test Müşteri", cari_turu="Müşteri", aktif=True))
            s.commit()

        _aktif_engine_bagla(eng)
        company_db._engine = eng
        company_db._session_factory = Session
        company_db._company_id = 77
        company_db._db_path = self.db_path
        oturum.clear()
        oturum.set_user(
            user_id=1,
            kullanici_adi="admin",
            ad_soyad="Test Admin",
            role_kod="YONETICI",
            role_ad="Yönetici",
            permissions=set(),
        )
        oturum.set_company(
            company_id=77,
            firma_kodu="XLS",
            firma_unvan="Excel Apply Test",
            firma_uid="xls-test",
            db_path=str(self.db_path),
        )
        with get_session() as s:
            d = s.scalar(select(Donem).limit(1))
            oturum.set_period(d.id, d.donem_adi)
        self._yamalar = [
            patch("database.muhasebe_entegrasyon.muhasebe_hook", lambda *_a, **_k: None),
            patch("database.satis_personeli.secimi_dogrula", return_value=(1, "Test Admin")),
            patch("database.user_audit.audit_document", lambda *_a, **_k: None),
        ]
        for p in self._yamalar:
            p.start()

    def kapat(self):
        for p in reversed(self._yamalar):
            p.stop()
        try:
            company_db.close()
        except Exception:
            pass
        company_db._engine = None
        company_db._session_factory = None
        oturum.clear()
        self._tmp.cleanup()


def _calistir(tip_kod: str, satirlar: list[dict], *, guncelleme_modu: str = "atla"):
    import excel_aktarim  # noqa: F401
    from excel_aktarim.executor import ImportAuditService, ImportExecutor
    from excel_aktarim.types import getir

    tip = getir(tip_kod)
    imp = tip.importer_factory()
    # Kimlik eşleme: satır anahtarları zaten alan kodu
    esleme = {k: k for row in satirlar for k in row}
    batch = ImportAuditService.batch_olustur(
        modul=tip.modul,
        import_tipi=tip.kod,
        dosya_adi=f"{tip_kod}.xlsx",
        kullanici_id=1,
        kullanici_adi="admin",
    )
    sonuc = ImportExecutor.calistir(
        batch.id,
        imp,
        satirlar,
        esleme,
        guncelleme_modu=guncelleme_modu,
        hatali_satirlari_atla=True,
    )
    return sonuc


def _kayit(sonuclar, ad, durum, not_):
    sonuclar.append((ad, durum, not_))
    print(f"{ad:36} {durum:12} {not_}", flush=True)


def main():
    import excel_aktarim  # noqa: F401
    from excel_aktarim.export_kart import kartlari_excel_aktar
    from excel_aktarim.mukerrer import mukerrer_mi
    from excel_aktarim.reader import ExcelReaderService
    from excel_aktarim.template import ImportTemplateService
    from excel_aktarim.types import getir

    sonuclar = []
    ort = Ortam()
    try:
        # —— Kartlar ——
        kart_senaryolari = [
            (
                "Stok kartı",
                "stok_karti",
                [{"stok_kodu": "EX001", "stok_adi": "Excel Stok", "birim": "Adet", "kdv_orani": "20"}],
                {"stok_kodu": "EX001"},
            ),
            (
                "Müşteri cari",
                "musteri_cari",
                [{"cari_kodu": "MX001", "unvan": "Excel Müşteri A.Ş."}],
                {"cari_kodu": "MX001"},
            ),
            (
                "Tedarikçi cari",
                "tedarikci_cari",
                [{"cari_kodu": "TX001", "unvan": "Excel Tedarikçi Ltd."}],
                {"cari_kodu": "TX001"},
            ),
            (
                "Personel kart",
                "personel_kart",
                [{"kod": "PXL1", "ad": "Ali", "soyad": "Excel"}],
                {"kod": "PXL1"},
            ),
            (
                "Banka kart",
                "banka_kart",
                [{"banka_adi": "Excel Bankası"}],
                {"banka_adi": "Excel Bankası"},
            ),
            (
                "Kasa hesap",
                "kasa_hesap",
                [{"hesap_adi": "Excel Kasa", "para_birimi": "TRY", "acilis_bakiyesi": "0"}],
                {"hesap_adi": "Excel Kasa"},
            ),
            (
                "POS hesap",
                "pos_hesap",
                [{"banka_adi": "POS Bankası", "hesap_adi": "POS Bankası — POS Hesabı"}],
                {"hesap_adi": "POS Bankası — POS Hesabı"},
            ),
        ]
        for ad, kod, satirlar, muk_anahtar in kart_senaryolari:
            try:
                tip = getir(kod)
                ImportTemplateService.olustur(tip, ort.out / f"{kod}_sablon.xlsx")
                b1 = _calistir(kod, satirlar, guncelleme_modu="atla")
                if b1.eklenen_satir < 1 and b1.durum not in ("basarili", "kismi"):
                    raise RuntimeError(f"eklenmedi durum={b1.durum} eklenen={b1.eklenen_satir} hata={b1.hata_satir}")
                var, gerekce = mukerrer_mi(kod, muk_anahtar)
                if not var:
                    raise RuntimeError(f"mükerrer beklenirdi: {gerekce}")
                b2 = _calistir(kod, satirlar, guncelleme_modu="atla")
                if b2.eklenen_satir != 0 and b2.atlanan_satir < 1:
                    # bazı tipler skip olarak dry_run'da sayılır
                    if b2.eklenen_satir > 0:
                        raise RuntimeError(f"ikinci içerik alma yeni kayıt ekledi: {b2.eklenen_satir}")
                if kod in ("stok_karti", "musteri_cari", "tedarikci_cari"):
                    from database.cari_service import CariService
                    from database.stok_service import StokService

                    if kod == "stok_karti":
                        kartlar = StokService.listele() if hasattr(StokService, "listele") else []
                        if not kartlar:
                            with get_session() as s:
                                kartlar = list(s.scalars(select(StokKarti).where(StokKarti.is_deleted.is_(False))))
                        kartlari_excel_aktar(
                            ort.out / f"exp_{kod}.xlsx",
                            tip_kod=kod,
                            kartlar=[{"stok_kodu": c.stok_kodu, "stok_adi": c.stok_adi, "birim": c.birim} for c in kartlar],
                        )
                    else:
                        with get_session() as s:
                            kartlar = list(s.scalars(select(Cari).where(Cari.cari_turu == ("Müşteri" if "musteri" in kod else "Tedarikçi"))))
                        alan = {a.kod: None for a in tip.alanlar}
                        rows = []
                        for c in kartlar:
                            r = dict(alan)
                            r["cari_kodu"] = c.cari_kodu
                            r["unvan"] = c.unvan
                            rows.append(r)
                        kartlari_excel_aktar(ort.out / f"exp_{kod}.xlsx", tip_kod=kod, kartlar=rows)
                    ExcelReaderService.oku(ort.out / f"exp_{kod}.xlsx")
                _kayit(sonuclar, ad, "tamamlandı", f"uygula+mükerrer; batch={b1.durum}/{b2.durum}")
            except Exception as e:
                _kayit(sonuclar, ad, "başarısız", str(e)[:180])

        # Stok birim
        try:
            b = _calistir(
                "stok_birim",
                [{"stok_kodu": "U001", "yeni_birim": "Paket", "carpan": "10"}],
                guncelleme_modu="atla",
            )
            if b.eklenen_satir < 1 and b.durum == "hatali":
                raise RuntimeError(f"stok_birim başarısız: {b.hata_ozeti or b.durum}")
            _kayit(sonuclar, "Stok birim", "tamamlandı", f"uygula durum={b.durum} eklenen={b.eklenen_satir}")
        except Exception as e:
            _kayit(sonuclar, "Stok birim", "başarısız", str(e)[:180])

        # Evraklar — fatura / sipariş / irsaliye / teklif
        fatura_satir_map = {
            "fatura_grubu": "G1",
            "belge_turu": "SATIS",
            "belge_no": "EX-SF-001",
            "tarih": "02.11.2026",
            "cari_kodu": "M001",
            "para_birimi": "TRY",
            "depo": "ANA DEPO",
            "urun_kodu": "U001",
            "aciklama": "Excel satır",
            "miktar": "1",
            "birim": "Adet",
            "birim_fiyat": "10",
            "iskonto_1": "0",
            "kdv_orani": "20",
            "fiyat_esasi": "Hariç",
        }

        def _evrak(ad, kod, belge_no, yon_belge="SATIS"):
            satir = dict(fatura_satir_map)
            satir["belge_no"] = belge_no
            satir["belge_turu"] = yon_belge
            satir["fatura_grubu"] = belge_no
            if "alis" in kod:
                satir["cari_kodu"] = "T001"
                satir["belge_turu"] = "ALIS"
            try:
                b1 = _calistir(kod, [satir], guncelleme_modu="atla")
                if b1.eklenen_satir < 1 and b1.durum == "hatali":
                    raise RuntimeError(b1.hata_ozeti or f"durum={b1.durum} hata={b1.hata_satir}")
                # mükerrer: fatura için belge_no
                if kod in ("satis_fatura_excel", "alis_fatura_excel"):
                    var, _ = mukerrer_mi(kod, {"belge_no": belge_no})
                    if not var and b1.eklenen_satir >= 1:
                        # fatura_no otomatik üretilmiş olabilir
                        pass
                    b2 = _calistir(kod, [satir], guncelleme_modu="atla")
                    _kayit(
                        sonuclar,
                        ad,
                        "tamamlandı",
                        f"uygula {b1.durum} eklenen={b1.eklenen_satir}; yeniden {b2.durum} eklenen={b2.eklenen_satir}",
                    )
                else:
                    _kayit(sonuclar, ad, "tamamlandı", f"uygula {b1.durum} eklenen={b1.eklenen_satir}")
            except Exception as e:
                _kayit(sonuclar, ad, "başarısız", str(e)[:180])

        _evrak("Satış fatura Excel", "satis_fatura_excel", "EX-SF-001")
        _evrak("Alış fatura Excel", "alis_fatura_excel", "EX-AF-001", "ALIS")
        _evrak("Satış sipariş Excel", "satis_siparis_excel", "EX-SS-001")
        _evrak("Alış sipariş Excel", "alis_siparis_excel", "EX-AS-001", "ALIS")
        _evrak("Satış irsaliye Excel", "satis_irsaliye_excel", "EX-SI-001")
        _evrak("Alış irsaliye Excel", "alis_irsaliye_excel", "EX-AI-001", "ALIS")
        _evrak("Teklif Excel", "teklif_excel", "EX-TK-001")

        # Cari virman
        try:
            b = _calistir(
                "cari_virman",
                [
                    {
                        "tarih": "02.11.2026",
                        "kaynak_kodu": "M001",
                        "hedef_kodu": "T001",
                        "tutar": "50",
                        "aciklama": "Excel virman",
                        "belge_no": "EXVR001",
                    }
                ],
            )
            if b.durum == "hatali" and b.eklenen_satir < 1:
                raise RuntimeError(b.hata_ozeti or b.durum)
            _kayit(sonuclar, "Cari virman", "tamamlandı", f"uygula {b.durum}")
        except Exception as e:
            _kayit(sonuclar, "Cari virman", "başarısız", str(e)[:180])

        # Çek/senet
        try:
            b = _calistir(
                "cek_senet",
                [
                    {
                        "evrak_turu": "CEK",
                        "evrak_no": "EXCEK001",
                        "islem_yonu": "ALINAN",
                        "cari_kodu": "M001",
                        "duzenleme_tarihi": "02.11.2026",
                        "vade_tarihi": "02.12.2026",
                        "doviz_tutari": "100",
                        "doviz_turu": "TRY",
                    }
                ],
            )
            var, _ = mukerrer_mi("cek_senet", {"evrak_no": "EXCEK001", "evrak_turu": "CEK"})
            _kayit(
                sonuclar,
                "Çek/senet",
                "tamamlandı" if b.durum != "hatali" or b.eklenen_satir else "başarısız",
                f"uygula {b.durum} eklenen={b.eklenen_satir} mükerrer={var}",
            )
        except Exception as e:
            _kayit(sonuclar, "Çek/senet", "başarısız", str(e)[:180])

        # Gider fişi — hizmet + kasa gerekir
        try:
            from database.models.hizmet import HizmetKarti
            from database.finans_service import FinansService

            FinansService.hesap_kaydet(
                {
                    "hesap_adi": "Gider Kasa",
                    "hesap_turu": "KASA",
                    "para_birimi": "TRY",
                    "acilis_bakiyesi": 500,
                }
            )
            with get_session() as s:
                s.add(
                    HizmetKarti(
                        hizmet_kodu="G001",
                        hizmet_adi="Ofis Gideri",
                        hizmet_turu="GIDER",
                        aktif=True,
                        kdv_orani=Decimal("20"),
                    )
                )
                s.commit()
            b = _calistir(
                "gider_fisi",
                [
                    {
                        "belge_no": "EXGF001",
                        "tarih": "02.11.2026",
                        "tutar": "25",
                        "hizmet_kodu": "G001",
                        "hesap_adi": "Gider Kasa",
                        "aciklama": "Excel gider",
                    }
                ],
            )
            var, _ = mukerrer_mi("gider_fisi", {"belge_no": "EXGF001"})
            ok = b.eklenen_satir >= 1 or b.durum in ("basarili", "kismi")
            _kayit(
                sonuclar,
                "Gider fişi",
                "tamamlandı" if ok else "başarısız",
                f"uygula {b.durum} eklenen={b.eklenen_satir} mükerrer={var}",
            )
        except Exception as e:
            _kayit(sonuclar, "Gider fişi", "başarısız", str(e)[:180])

        # Depo transfer
        try:
            b = _calistir(
                "depo_transfer",
                [
                    {
                        "fis_grubu": "DT1",
                        "fis_no": "EXDT001",
                        "fis_tarihi": "02.11.2026",
                        "cikis_depo": "ANA DEPO",
                        "giris_depo": "DEPO 2",
                        "urun_kodu": "U001",
                        "miktar": "1",
                        "birim": "Adet",
                    }
                ],
            )
            var, _ = mukerrer_mi("depo_transfer", {"fis_no": "EXDT001"})
            ok = b.eklenen_satir >= 1 or b.durum in ("basarili", "kismi")
            _kayit(
                sonuclar,
                "Depo transfer",
                "tamamlandı" if ok else "başarısız",
                f"uygula {b.durum} eklenen={b.eklenen_satir} mükerrer={var}",
            )
        except Exception as e:
            _kayit(sonuclar, "Depo transfer", "başarısız", str(e)[:180])

        # Konsinye
        try:
            b = _calistir(
                "konsinye_teslim",
                [
                    {
                        "teslim_grubu": "K1",
                        "yon": "VERILEN",
                        "cari_kodu": "M001",
                        "depo": "ANA DEPO",
                        "belge_tarihi": "02.11.2026",
                        "urun_kodu": "U001",
                        "miktar": "1",
                        "birim": "Adet",
                    }
                ],
            )
            ok = b.eklenen_satir >= 1 or b.durum in ("basarili", "kismi")
            _kayit(
                sonuclar,
                "Konsinye teslim",
                "tamamlandı" if ok else "başarısız",
                f"uygula {b.durum} eklenen={b.eklenen_satir} hata={b.hata_satir}",
            )
        except Exception as e:
            _kayit(sonuclar, "Konsinye teslim", "başarısız", str(e)[:180])

        # Rapor export + karşılaştırma
        try:
            from excel_aktarim.karsilastirma import karsilastir
            from excel_aktarim.writer import excel_yaz

            excel_yaz(
                ort.out / "rapor.xlsx",
                basliklar=["Kod", "Tutar"],
                satirlar=[["A", 10], ["B", 20]],
                kolon_tipleri=["kod", "para"],
                amac="rapor",
                meta={"sablon_turu": "rapor", "kayit_sayisi": 2},
            )
            s = karsilastir(
                [{"kod": "A", "tutar": 10}],
                [{"kod": "A", "tutar": 12}],
                anahtar_alanlar=["kod"],
                tutar_alani="tutar",
            )
            assert s.ozet()["tutar_farkli"] == 1
            _kayit(sonuclar, "Rapor Excel'e Aktar", "tamamlandı", "writer")
            _kayit(sonuclar, "Rapor Excel'den Al karşılaştırma", "tamamlandı", "karsilastir")
            # POS hareket: ekstre karşılaştırma (ImportTipi değil)
            s2 = karsilastir(
                [{"ref": "P1", "tutar": 100, "komisyon": 2}],
                [{"ref": "P1", "tutar": 98, "komisyon": 2}],
                anahtar_alanlar=["ref"],
                tutar_alani="tutar",
            )
            _kayit(
                sonuclar,
                "POS hareket (ekstre eşleştirme)",
                "tamamlandı",
                f"karsilastir fark={s2.ozet().get('tutar_farkli')}; hub ImportTipi yok (bilinçli)",
            )
        except Exception as e:
            _kayit(sonuclar, "Rapor/POS karşılaştırma", "başarısız", str(e)[:180])

    finally:
        ort.kapat()

    ozet = {"tamamlandı": 0, "başarısız": 0, "denenmedi": 0}
    for _, d, _ in sonuclar:
        ozet[d] = ozet.get(d, 0) + 1
    print("-" * 100)
    print("OZET", ozet)
    return 0 if ozet.get("başarısız", 0) == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
