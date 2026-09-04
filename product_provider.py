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


product_provider: ProductProvider = EmptyProductProvider()


def search_products(query: str) -> list[ProductRecord]:
    # TODO: Sağlayıcı seçimi ve veri kaynağı önceliği burada yönetilecek.
    return product_provider.search(query)
