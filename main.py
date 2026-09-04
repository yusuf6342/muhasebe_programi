from database.database import Base, engine

# Modelleri sisteme tanıtıyoruz
from database.models.firma import Firma
from database.models.donem import Donem
from database.models.cari import Cari, SatisHareketi
from app import MuhasebeApp


def main():
    print("Veritabanı tabloları oluşturuluyor...")

    Base.metadata.create_all(engine)

    print("Tablolar başarıyla oluşturuldu!")
    print(f"Veritabanı: {engine.url}")
    app = MuhasebeApp()
    app.mainloop()


if __name__ == "__main__":
    main()
