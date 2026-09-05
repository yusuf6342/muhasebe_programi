from database.database import Base, cari_kart_schemasini_guncelle, engine, musteri_gruplarini_hazirla

# Modelleri sisteme tanıtıyoruz
from database.models.firma import Firma
from database.models.donem import Donem
from database.models.cari import Cari, SatisHareketi
from database.models.satis_siparisi import SatisSiparisi, SatisSiparisiSatiri, SatisSiparisiTahsilati
from database.models.satis_irsaliyesi import SatisIrsaliyesi, SatisIrsaliyesiSatiri
from database.models.satis_faturasi import SatisFaturasi, SatisFaturasiSatiri
from database.models.stok import Depo, StokFiyati, StokHareketi, StokKarti, StokLotu
from database.models.finans import FinansHareketi, FinansHesabi
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
