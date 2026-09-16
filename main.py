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
from database.models.cari import Cari, CariIslem, SatisHareketi
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
    PosValorKaydi,
    PosTaksitKomisyon,
    KrediKartiTanimi,
    KrediKartiOdeme,
    KrediKartiOdemeTaksit,
    BankaKredisi,
    BankaKrediTaksit,
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

from database.stok_service import StokService
from database.finans_service import FinansService
from app import MuhasebeApp


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

    progress(90, "Arayüz hazırlanıyor...")
    print("Tablolar başarıyla oluşturuldu!")
    print(f"Veritabanı: {db.engine.url}")


def main():
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
    app.mainloop()


if __name__ == "__main__":
    main()
