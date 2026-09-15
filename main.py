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





def main():

    import threading



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



    print("Veritabanı tabloları oluşturuluyor...")



    Base.metadata.create_all(db.engine)

    cari_kart_schemasini_guncelle()

    musteri_gruplarini_hazirla()

    StokService.varsayilanlari_hazirla()

    FinansService.varsayilanlari_hazirla()

    try:
        from database.muhasebe_service import MuhasebeService

        MuhasebeService.schema_hazirla()
    except Exception as e:
        print("Genel muhasebe şema uyarısı:", e)

    try:
        from database.cek_senet_service import CekSenetService

        CekSenetService.schema_hazirla()
    except Exception as e:
        print("Çek/Senet şema uyarısı:", e)



    print("Tablolar başarıyla oluşturuldu!")

    print(f"Veritabanı: {db.engine.url}")

    app = MuhasebeApp()



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
