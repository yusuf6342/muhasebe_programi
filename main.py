from database.database import Base, cari_kart_schemasini_guncelle, engine, musteri_gruplarini_hazirla

# Modelleri sisteme tanıtıyoruz
from database.models.firma import Firma
from database.models.donem import Donem
from database.models.cari import Cari, CariIslem, SatisHareketi
from database.models.satis_siparisi import SatisSiparisi, SatisSiparisiSatiri, SatisSiparisiTahsilati
from database.models.satis_irsaliyesi import SatisIrsaliyesi, SatisIrsaliyesiSatiri
from database.models.satis_faturasi import SatisFaturasi, SatisFaturasiSatiri
from database.models.satis_iade_faturasi import SatisIadeFaturasi, SatisIadeFaturasiSatiri
from database.models.alis_siparisi import AlisSiparisi, AlisSiparisiSatiri, AlisSiparisiOdemesi
from database.models.alis_irsaliyesi import AlisIrsaliyesi, AlisIrsaliyesiSatiri
from database.models.alis_faturasi import AlisFaturasi, AlisFaturasiSatiri
from database.models.alis_iade_faturasi import AlisIadeFaturasi, AlisIadeFaturasiSatiri
from database.models.stok import Depo, StokFiyati, StokHareketi, StokKarti, StokLotu
from database.models.finans import FinansHareketi, FinansHesabi
from database.models.kk_cekimi import KkCekimi
from database.stok_service import StokService
from database.finans_service import FinansService
from app import MuhasebeApp


def main():
    print("Veritabanı tabloları oluşturuluyor...")

    Base.metadata.create_all(engine)
    cari_kart_schemasini_guncelle()
    musteri_gruplarini_hazirla()
    StokService.varsayilanlari_hazirla()
    FinansService.varsayilanlari_hazirla()

    print("Tablolar başarıyla oluşturuldu!")
    print(f"Veritabanı: {engine.url}")
    app = MuhasebeApp()
    app.mainloop()


if __name__ == "__main__":
    main()
