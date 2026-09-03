from database.database import Base, engine

# Modelleri sisteme tanıtıyoruz
from database.models.firma import Firma
from database.models.donem import Donem


def main():
    print("Veritabanı tabloları oluşturuluyor...")

    Base.metadata.create_all(engine)

    print("Tablolar başarıyla oluşturuldu!")
    print(f"Veritabanı: {engine.url}")


if __name__ == "__main__":
    main()
