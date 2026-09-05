from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class ProductRecord:
    code: str
    name: str
    unit: str
    stock: str
    default_price: str
    source: str


class ProductProvider(Protocol):
    def search(self, query: str) -> list[ProductRecord]:
        """Kod veya ürün adının herhangi bir bölümünde arama yapar."""


class EmptyProductProvider:
    def search(self, query: str) -> list[ProductRecord]:
        # TODO: Manuel stok kartı, Excel ve EvoBulut sağlayıcıları burada birleştirilecek.
        return []


class DatabaseProductProvider:
    def search(self, query: str) -> list[ProductRecord]:
        from database.stok_service import StokService

        sonuc = []
        for stok in StokService.stoklari_ara(query):
            fiyat = stok.fiyatlar[0].tutar if stok.fiyatlar else 0
            mevcut = sum((lot.kalan_miktar for lot in stok.lotlar), 0)
            sonuc.append(ProductRecord(
                code=stok.stok_kodu, name=stok.stok_adi, unit=stok.birim,
                stock=str(mevcut), default_price=str(fiyat), source="Stok Kartı",
            ))
        return sonuc


product_provider: ProductProvider = DatabaseProductProvider()


def search_products(query: str) -> list[ProductRecord]:
    return product_provider.search(query)


def search_prices(product_code: str):
    from database.stok_service import StokService
    return StokService.fiyatlar(product_code)
