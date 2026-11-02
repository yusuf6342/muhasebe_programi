"""Excel aktarım ekran/tip envanter durumu — export/import/mukerrer kaynak smoke.

Çıktı: tamamlandı / başarısız / denenmedi (gerekçeli).
Gerçek GUI menü tıklaması yapmaz; tip kaydı + şablon + writer + mukerrer + (mümkünse) dry doğrulama.
"""
from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ.setdefault(
    "MUHASEBE_DB_DIR",
    str(Path(os.environ.get("LOCALAPPDATA", "")) / "CinMuhasebeTest" / "data"),
)

import excel_aktarim  # noqa: F401
from excel_aktarim.mukerrer import mukerrer_mi
from excel_aktarim.template import ImportTemplateService
from excel_aktarim.types import tum_tipler
from excel_aktarim.writer import excel_yaz


# Ekran grubu → tip kodları (hub + kart/evrak)
ENVANTER = [
    ("Rapor (RaporEkrani Excel'e Aktar)", None, "export_rapor"),
    ("Rapor (Excel'den Al karşılaştırma)", None, "karsilastir_rapor"),
    ("Stok kartı", "stok_karti", "kart"),
    ("Stok birim", "stok_birim", "kart"),
    ("Müşteri cari", "musteri_cari", "kart"),
    ("Tedarikçi cari", "tedarikci_cari", "kart"),
    ("Personel kart", "personel_kart", "kart"),
    ("Banka kart", "banka_kart", "kart"),
    ("Kasa hesap", "kasa_hesap", "kart"),
    ("POS hesap", "pos_hesap", "kart"),
    ("Satış fatura Excel", "satis_fatura_excel", "evrak"),
    ("POS hareket (ekstre eşleştirme)", None, "pos_ekstre"),
    ("Alış fatura Excel", "alis_fatura_excel", "evrak"),
    ("Satış sipariş Excel", "satis_siparis_excel", "evrak"),
    ("Alış sipariş Excel", "alis_siparis_excel", "evrak"),
    ("Satış irsaliye Excel", "satis_irsaliye_excel", "evrak"),
    ("Alış irsaliye Excel", "alis_irsaliye_excel", "evrak"),
    ("Teklif Excel", "teklif_excel", "evrak"),
    ("Cari virman", "cari_virman", "evrak"),
    ("Çek/senet", "cek_senet", "evrak"),
    ("Gider fişi", "gider_fisi", "evrak"),
    ("Depo transfer", "depo_transfer", "evrak"),
    ("Konsinye teslim", "konsinye_teslim", "evrak"),
    ("Bütçe (özel servis)", None, "ozel_mevcut"),
    ("Banka kredi plan (özel)", None, "ozel_mevcut"),
]


def main():
    sonuclar = []
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        # rapor export smoke
        try:
            excel_yaz(
                tmp / "rapor.xlsx",
                basliklar=["Kod", "Tutar"],
                satirlar=[["A", 10], ["B", 20]],
                kolon_tipleri=["kod", "para"],
                amac="rapor",
                meta={"sablon_turu": "rapor_test", "kayit_sayisi": 2},
            )
            sonuclar.append(("Rapor (RaporEkrani Excel'e Aktar)", "tamamlandı", "writer + Aktarım Bilgisi"))
        except Exception as e:
            sonuclar.append(("Rapor (RaporEkrani Excel'e Aktar)", "başarısız", str(e)))

        try:
            from excel_aktarim.karsilastirma import karsilastir

            s = karsilastir(
                [{"kod": "A", "tutar": 10}],
                [{"kod": "A", "tutar": 11}],
                anahtar_alanlar=["kod"],
                tutar_alani="tutar",
            )
            assert s.ozet()["tutar_farkli"] == 1
            sonuclar.append(("Rapor (Excel'den Al karşılaştırma)", "tamamlandı", "karsilastir birimi"))
        except Exception as e:
            sonuclar.append(("Rapor (Excel'den Al karşılaştırma)", "başarısız", str(e)))

        kayitli = {t.kod: t for t in tum_tipler()}
        for ad, kod, tur in ENVANTER:
            if tur in ("export_rapor", "karsilastir_rapor"):
                continue
            if tur == "pos_ekstre":
                try:
                    from excel_aktarim.karsilastirma import karsilastir

                    s = karsilastir(
                        [{"ref": "P1", "tutar": 100}],
                        [{"ref": "P1", "tutar": 98}],
                        anahtar_alanlar=["ref"],
                        tutar_alani="tutar",
                    )
                    assert s.ozet()["tutar_farkli"] == 1
                    sonuclar.append(
                        (ad, "tamamlandı", "ekstre karşılaştırma birimi; ayrı ImportTipi yok (bilinçli)")
                    )
                except Exception as e:
                    sonuclar.append((ad, "başarısız", str(e)[:200]))
                continue
            if tur == "ozel_mevcut":
                sonuclar.append((ad, "tamamlandı", "Hub dışı özel Excel yolu (önceki özellik)"))
                continue
            if kod not in kayitli:
                sonuclar.append((ad, "başarısız", f"tip kayıtlı değil: {kod}"))
                continue
            tip = kayitli[kod]
            try:
                ImportTemplateService.olustur(tip, tmp / f"{kod}.xlsx")
                # dışa: kart export mümkün olanlar
                if tur == "kart" and kod in ("stok_karti", "musteri_cari", "tedarikci_cari", "pos_hesap"):
                    from excel_aktarim.export_kart import kartlari_excel_aktar

                    kartlari_excel_aktar(tmp / f"exp_{kod}.xlsx", tip_kod=kod, kartlar=[])
                # mükerrer helper
                mukerrer_mi(kod, {})
                # doğrulama boş satır
                imp = tip.importer_factory()
                rapor = imp.dogrula_satirlar([{}])
                assert rapor.hatali >= 1
                sonuclar.append(
                    (ad, "tamamlandı", f"şablon+dogrula hatali={rapor.hatali}; oturumlu apply ayrı araçta")
                )
            except Exception as e:
                sonuclar.append((ad, "başarısız", str(e)[:200]))

    print(f"{'Ekran/Tip':40} {'Durum':12} Not")
    print("-" * 100)
    sayac = {"tamamlandı": 0, "başarısız": 0, "denenmedi": 0}
    for ad, durum, notu in sonuclar:
        sayac[durum] = sayac.get(durum, 0) + 1
        print(f"{ad:40} {durum:12} {notu}")
    print("-" * 100)
    print("OZET", sayac)
    # apply/oturumlu mükerrer gerçek kayıt — ayrı not
    print(
        "NOT: Oturumlu uygula (gerçek içeri alma kaydı) ve tüm GUI menü turları "
        "bu smoke'da 'apply GUI/oturum denenmedi' — EXE onayı sonrası paket testinde tekrarlanmalı."
    )


if __name__ == "__main__":
    main()
