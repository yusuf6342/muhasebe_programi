from urllib.parse import quote_plus
from sqlalchemy import create_engine, text
from database.baglanti_modu import postgres_parola_al

p = quote_plus(postgres_parola_al())
e = create_engine(
    f"postgresql+psycopg://cin_app:{p}@192.168.1.114:5432/"
    "cin_sistem_kabul_20261105?sslmode=require"
)
with e.connect() as c:
    print(
        dict(
            c.execute(
                text(
                    "SELECT firma_kodu, db_path FROM companies "
                    "WHERE firma_kodu='RAY001'"
                )
            )
            .mappings()
            .first()
        )
    )
e.dispose()
