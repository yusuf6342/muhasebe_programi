from database import database as db

from database.database import (
    Base,
    cari_kart_schemasini_guncelle,
    musteri_gruplarini_hazirla,
    sistem_altyapisini_baslat,
    tedarikci_odeme_polarity_duzelt,
)

# Modelleri sisteme tanıtıyoruz
from database.models.firma import Firma
from database.models.donem import Donem
from database.models.sube import Sube  # noqa: F401
from database.models.cari import Cari, CariIslem, CariYetkili, SatisHareketi  # noqa: F401
from database.models.satis_siparisi import SatisSiparisi, SatisSiparisiSatiri, SatisSiparisiTahsilati
from database.models.satis_teklifi import SatisTeklifi, SatisTeklifiSatiri  # noqa: F401
from database.models.satis_irsaliyesi import SatisIrsaliyesi, SatisIrsaliyesiSatiri
from database.models.satis_faturasi import SatisFaturasi, SatisFaturasiSatiri, SatisFaturasiTahsilati
from database.models.satis_iade_faturasi import SatisIadeFaturasi, SatisIadeFaturasiSatiri
from database.models.alis_siparisi import AlisSiparisi, AlisSiparisiSatiri, AlisSiparisiOdemesi
from database.models.alis_irsaliyesi import AlisIrsaliyesi, AlisIrsaliyesiSatiri
from database.models.alis_faturasi import AlisFaturasi, AlisFaturasiSatiri
from database.models.alis_iade_faturasi import AlisIadeFaturasi, AlisIadeFaturasiSatiri
from database.models.stok import (
    Depo,
    DepoTransferFisi,
    DepoTransferFisiSatiri,
    StokBarkod,
    StokBirim,
    StokFiyati,
    StokFiyatGecmisi,
    StokGrubu,
    StokGrupTopluIslem,
    StokGrupTopluIslemSatiri,
    StokHareketi,
    StokKarti,
    StokLotu,
    StokPaketBilesen,
    StokPaketUretim,
    StokResmi,
    StokSecenek,
)
from database.models.finans import (
    FinansHareketi,
    FinansHesabi,
    BankaKarti,
    BankAccountMatchRule,  # noqa: F401 — create_all
    PosValorKaydi,
    PosTaksitKomisyon,
    KrediKartiTanimi,
    KrediKartiOdeme,
    KrediKartiOdemeTaksit,
    KrediKartiEkstre,
    KrediKartiEkstreOdeme,
    BankaKredisi,
    BankaKrediTaksit,
    BankaKrediOdeme,
    BankaKrediIslemGunlugu,
    BankaKrediPlanVersiyon,
    GiderFisi,
    KasaMakbuzu,
    KasaMakbuzSatiri,
)
from database.models.hizmet import HizmetKarti, HizmetHareketi
from database.models.hizmet_faturasi import HizmetFaturasi, HizmetFaturasiSatiri
from database.models.kk_cekimi import KkCekimi
from database.models.cek_senet import CekSenetEvrak, CekSenetHareket
from database.models.deleted_record import DeletedRecordLog  # noqa: F401
from database.models.doviz import DovizKuru
from database.models.genel_muhasebe import (
    HesapPlani,
    MuhasebeFisi,
    MuhasebeFisiSatiri,
    MuhasebeHesapEsleme,
    MuhasebeIslemGecmisi,
)
from excel_aktarim.models import (  # noqa: F401
    ImportBatch,
    ImportChange,
    ImportMapping,
    ImportRow,
)

from database.stok_service import StokService
from database.finans_service import FinansService
from app import MuhasebeApp


_ORNEK_VERI_ISTENDI = False


def test_ilk_acilis_sor(parent) -> bool | None:
    """Test kurulumu ilk açılışı: True=örnek veri, False=boş firma, None=çık."""
    from tkinter import messagebox

    from branding import APP_NAME

    return messagebox.askyesnocancel(
        f"{APP_NAME} — Test Kurulumu",
        "Bu bilgisayarda ilk açılış: gerçek firma verisi yok ve yüklenmeyecek.\n\n"
        f"Boş bir «{db.TEST_FIRMA_UNVAN}» oluşturulacak.\n"
        f"Veri klasörü: {db.DB_DIR}\n\n"
        "Ekranları denemek için birkaç örnek müşteri ve ürün eklensin mi?\n"
        "(Hepsi adında «ÖRNEK VERİ» yazar, kodları ORN- ile başlar.)\n\n"
        "Evet = örnek verili test firması\n"
        "Hayır = tamamen boş test firması\n"
        "İptal = programdan çık",
        parent=parent,
    )


def baslatma_adimlari(progress) -> None:
    """Veritabanı ve servis hazırlığı — splash ilerleme geri çağrısı ile."""
    progress(5, "Sistem altyapısı başlatılıyor...")
    print("Sistem altyapısı başlatılıyor (system.db)...")
    sistem_bilgi = sistem_altyapisini_baslat()
    print(f"Sistem DB: {sistem_bilgi.get('system_db')}")
    print(f"Aktif firma DB: {sistem_bilgi.get('company_db')}")

    gecis = sistem_bilgi.get("gecis") or {}
    if gecis.get("yedek_alindi"):
        print("Geçiş yedeği:", gecis.get("yedek_yolu"))
    for m in gecis.get("mesajlar") or []:
        print("Geçiş:", m)

    if sistem_bilgi.get("admin_olusturuldu"):
        print(
            "İlk yönetici oluşturuldu. Parola dosyası:",
            sistem_bilgi.get("ilk_parola_dosyasi"),
        )

    progress(25, "Veritabanı tabloları oluşturuluyor...")
    print("Veritabanı tabloları oluşturuluyor...")
    Base.metadata.create_all(db.engine)

    progress(40, "Şemalar güncelleniyor...")
    cari_kart_schemasini_guncelle()
    musteri_gruplarini_hazirla()

    progress(55, "Stok ve finans hazırlanıyor...")
    StokService.varsayilanlari_hazirla()
    FinansService.varsayilanlari_hazirla()

    if _ORNEK_VERI_ISTENDI:
        progress(62, "Örnek veri ekleniyor...")
        try:
            from database.ornek_veri import ornek_veri_ekle

            print("Örnek veri:", ornek_veri_ekle())
        except Exception as e:
            print("Örnek veri eklenemedi:", e)

    progress(70, "Genel muhasebe kontrol ediliyor...")
    try:
        from database.muhasebe_service import MuhasebeService

        MuhasebeService.schema_hazirla()
    except Exception as e:
        print("Genel muhasebe şema uyarısı:", e)

    progress(80, "Çek/senet ve denetim hazırlanıyor...")
    try:
        from database.cek_senet_service import CekSenetService

        CekSenetService.schema_hazirla()
    except Exception as e:
        print("Çek/Senet şema uyarısı:", e)

    try:
        from database.deleted_record_service import AuditDeleteService

        AuditDeleteService.schema_hazirla()
    except Exception as e:
        print("Silinen kayıtlar şema uyarısı:", e)

    try:
        from database.servis_sistem.error_log_service import ErrorLogService

        ErrorLogService.schema_hazirla()
    except Exception as e:
        print("Servis sistem şema uyarısı:", e)

    try:
        from database.hizli_satis_service import HizliSatisService

        HizliSatisService.schema_hazirla()
    except Exception as e:
        print("Hızlı Satış bekleyen şema uyarısı:", e)

    try:
        from database.banka_kredi_service import BankaKrediService

        BankaKrediService.schema_hazirla()
    except Exception as e:
        print("Banka kredileri şema uyarısı:", e)

    progress(90, "Arayüz hazırlanıyor...")
    print("Tablolar başarıyla oluşturuldu!")
    print(f"Veritabanı: {db.engine.url}")


def main():
    import sys
    import threading
    import traceback
    from tkinter import messagebox

    from branding import (
        APP_NAME,
        install_toplevel_icon_hook,
        set_windows_app_user_model_id,
        setup_branding_logging,
    )

    setup_branding_logging()
    set_windows_app_user_model_id()
    install_toplevel_icon_hook()

    print(f"Veri klasörü: {db.veri_konumu_ozeti()}")
    global _ORNEK_VERI_ISTENDI
    ilk_test_acilisi = (
        db.TEST_KURULUMU and not db.SYSTEM_DB_ONCEDEN_VAR and not db.MUHASEBE_DB_ONCEDEN_VAR
    )
    if "--ekran-testi" in sys.argv:
        from ekran_testi import calistir

        i = sys.argv.index("--ekran-testi")
        rapor = sys.argv[i + 1] if len(sys.argv) > i + 1 else "ekran_testi_raporu.txt"
        _ORNEK_VERI_ISTENDI = ilk_test_acilisi
        sys.exit(calistir(rapor, baslatma_adimlari, kayit_dene="--kayit-dene" in sys.argv))
    if ilk_test_acilisi:
        import tkinter as tk

        gecici = tk.Tk()
        gecici.withdraw()
        try:
            secim = test_ilk_acilis_sor(gecici)
        finally:
            gecici.destroy()
        if secim is None:
            return
        _ORNEK_VERI_ISTENDI = bool(secim)
    veri_uyarisi = db.baslangic_veri_uyarisi()
    if veri_uyarisi:
        import tkinter as tk

        gecici = tk.Tk()
        gecici.withdraw()
        try:
            devam = messagebox.askyesno(APP_NAME, veri_uyarisi, icon="warning", parent=gecici)
        finally:
            gecici.destroy()
        if not devam:
            return

    try:
        app = MuhasebeApp(startup_bootstrap=baslatma_adimlari)
    except Exception as exc:
        traceback.print_exc()
        try:
            messagebox.showerror(
                APP_NAME,
                f"Program başlatılırken bir hata oluştu:\n\n{exc}",
            )
        except Exception:
            print("Başlatma hatası:", exc)
        return

    if not getattr(app, "_cin_basarili", False):
        return

    def _arka_plan_bakim():
        try:
            tedarikci_odeme_polarity_duzelt()
        except Exception:
            pass
        try:
            from database.doviz_service import DovizService

            DovizService.otomatik_gunluk_cek(sessiz=True)
        except Exception:
            pass

    threading.Thread(target=_arka_plan_bakim, daemon=True).start()

    try:
        from database.database import DB_PATH, db_konum_uyari_metni

        uyari = db_konum_uyari_metni()
        if uyari:
            messagebox.showwarning(APP_NAME, uyari)
        else:
            # Bilgi amaçlı: konum LOCALAPPDATA ise sessiz; aksi halde log
            print(f"Veritabanı konumu: {DB_PATH}")
    except Exception:
        pass

    app.mainloop()


if __name__ == "__main__":
    main()
