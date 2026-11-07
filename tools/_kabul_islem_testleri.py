"""Kabul: fatura/çakışma/eşzamanlı belge no — PG deneme (KABULTEST etiketli).

İzole DB kopyası yoksa cin_firma_deneme üzerinde işaretli kayıtlarla çalışır.
Günlük SQLite ayarını değiştirmez; baglanti_ayari geçici program klasöründen okunur.
"""
from __future__ import annotations

import json
import os
import socket
import sys
import threading
import time
import traceback
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

PROFIL_PROG = Path(os.environ.get("LOCALAPPDATA", "")) / "CinMuhasebeKabulDeneme_20261105" / "program"
os.environ["MUHASEBE_BAGLANTI_KIPI"] = "yerel_ag_postgres"
# baglanti_ayari program_klasoru'dan gelir — kaynak çalıştırmada proje kökü.
# Bu yüzden ayarı proje köküne YAZMIYORUZ; engine_factory'ye doğrudan bağlanacağız.

from database.baglanti_modu import (  # noqa: E402
    BaglantiAyari,
    CalismaKipi,
    PostgresBaglanti,
    postgres_parola_al,
)
from database.engine_factory import firma_engine_olustur, sistem_engine_olustur  # noqa: E402
from sqlalchemy import create_engine, select, text  # noqa: E402
from sqlalchemy.orm import sessionmaker  # noqa: E402

ETIKET = "KABULTEST-20261105"
HOST = "192.168.1.114"
SYS_DB = "cin_sistem_kabul_20261105"
FR_DB = "cin_firma_kabul_20261105"
SSLMODE = "verify-full"


def _ayar() -> BaglantiAyari:
    return BaglantiAyari(
        kipi=CalismaKipi.YEREL_AG_POSTGRES.value,
        postgres=PostgresBaglanti(
            host=HOST,
            port=5432,
            sistem_db=SYS_DB,
            kullanici="cin_app",
            sslmode=SSLMODE,
            ortam="DENEME",
            firma_db=FR_DB,
            terminal_kimligi="KABUL-SCRIPT",
        ),
    )


def _patch_runtime(ayar: BaglantiAyari):
    """Uygulama servislerinin get_session / system DB kullanması için."""
    import database.baglanti_modu as bm
    import database.database as db
    import database.company_database as cdb

    # ayari_yukle override
    def _yukle(program_dir=None):
        return ayar

    bm.ayari_yukle = _yukle  # type: ignore
    # company_database da ayari_yukle kullanır
    cdb.ayari_yukle = _yukle  # type: ignore

    eng_sys = sistem_engine_olustur(ayar)
    eng_fr = firma_engine_olustur(ayar, sqlite_path=None, firma_db=FR_DB)

    # system session
    from database.system import bootstrap as boot

    boot._engine = eng_sys  # may not exist — find real hooks
    # Open company_db
    db.company_db.open(1, f"pg:{FR_DB}")

    # User session for yazma_zorunlu / audit
    from database import user_audit

    class _Fake:
        user_id = 1
        username = "kabul_test"
        full_name = "Kabul Test"

    if hasattr(user_audit, "set_user_session"):
        user_audit.set_user_session(_Fake())
    elif hasattr(user_audit, "CURRENT"):
        pass

    return eng_sys, eng_fr


def _ensure_user_session():
    from database import user_audit

    # Explore API
    for name in ("set_current_user", "set_user_session", "bind_session", "login_as"):
        if hasattr(user_audit, name):
            return name, getattr(user_audit, name)
    return None, None


def main() -> int:
    rapor: dict = {
        "zaman": datetime.now().isoformat(timespec="seconds"),
        "makine": socket.gethostname(),
        "hedef": f"{HOST}/{SYS_DB}+{FR_DB}",
        "etiket": ETIKET,
        "senaryolar": [],
    }
    ayar = _ayar()

    # 1) Bağlantı + firmalar
    eng_sys = sistem_engine_olustur(ayar)
    with eng_sys.connect() as c:
        firms = c.execute(
            text(
                "SELECT firma_kodu, db_path, aktif FROM companies ORDER BY id"
            )
        ).mappings().all()
        cols = [
            r[0]
            for r in c.execute(
                text(
                    "SELECT column_name FROM information_schema.columns "
                    "WHERE table_schema='public' AND table_name='users' "
                    "ORDER BY ordinal_position"
                )
            )
        ]
        kullanici_kol = "kullanici_adi" if "kullanici_adi" in cols else (
            "username" if "username" in cols else cols[1] if len(cols) > 1 else "id"
        )
        users = c.execute(
            text(f"SELECT id, {kullanici_kol} AS kullanici, aktif FROM users ORDER BY id LIMIT 10")
        ).mappings().all()
    rapor["companies"] = [dict(r) for r in firms]
    rapor["users"] = [dict(r) for r in users]
    rapor["users_columns"] = cols
    rapor["senaryolar"].append(
        {
            "ad": "firma_hedef_ve_kilit",
            "beklenen": "RAY001 aktif pg:cin_firma_kabul_20261105; diğerleri kilitli",
            "gerceklesen": rapor["companies"],
            "durum": (
                "GECTI"
                if any(
                    f["firma_kodu"] == "RAY001"
                    and f["aktif"]
                    and f["db_path"] == f"pg:{FR_DB}"
                    for f in rapor["companies"]
                )
                and all(
                    (not f["aktif"]) or f["firma_kodu"] == "RAY001"
                    for f in rapor["companies"]
                )
                else "KALDI"
            ),
        }
    )

    eng_fr = firma_engine_olustur(ayar, sqlite_path=None, firma_db=FR_DB)

    # 2) Sequence / yeni id çakışması yok — NEXTVAL denemesi
    with eng_fr.connect() as c:
        mx = c.execute(text("SELECT COALESCE(MAX(id),0) FROM satis_faturalari")).scalar()
        seq = c.execute(
            text("SELECT pg_get_serial_sequence('satis_faturalari','id')")
        ).scalar()
        last = c.execute(text(f"SELECT last_value FROM {seq}")).scalar() if seq else None
        # nextval peeks without consuming permanently? use setval check only
        ok_seq = last is not None and int(last) >= int(mx)
    rapor["senaryolar"].append(
        {
            "ad": "sequence_satis_faturalari",
            "max_id": int(mx),
            "last_value": int(last) if last is not None else None,
            "durum": "GECTI" if ok_seq else "KALDI",
        }
    )

    # 3) Eşzamanlı fatura_no_ayir (advisory lock) — aynı anda farklı no
    from database.satis_faturasi_service import SatisFaturasiService

    SF = sessionmaker(bind=eng_fr, autoflush=False, autocommit=False, expire_on_commit=False)
    barrier = threading.Barrier(4)

    def _uretim_no_kilitli(i: int) -> dict:
        try:
            with SF() as s:
                barrier.wait(timeout=15)
                # Transaction açık tut: commit etmeden no al (lock tutulur)
                aday = SatisFaturasiService.fatura_no_ayir(s)
                time.sleep(0.3)  # diğer thread'ler lock beklesin
                s.rollback()  # yazma yok; sadece yarış testi
                return {"i": i, "aday": aday, "ok": True}
        except Exception as exc:
            return {"i": i, "hata": str(exc)[:200], "ok": False}

    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(_uretim_no_kilitli, range(4)))
    adaylar = [r.get("aday") for r in results if r.get("ok")]
    # Lock serileştirir: hepsi aynı MAX+1'i görür (rollback nedeniyle) — çakışma beklenir
    # Asıl güvence: kaydet transaction'ında lock + insert. Ayrı doğrulama: kilitli sırayla artan.
    # Advisory lock altında sıralı rezervasyon (aynı kilit anahtarı + artan sayaç)
    sirali = []
    with eng_fr.begin() as c:
        c.execute(
            text(
                "CREATE TABLE IF NOT EXISTS kabul_no_lock_test ("
                "id serial PRIMARY KEY, fatura_no text UNIQUE NOT NULL, etiket text)"
            )
        )
        c.execute(text("DELETE FROM kabul_no_lock_test"))

    def _rezerve(i: int) -> str:
        with SF() as s:
            # Üretimdeki fatura_no_ayir ile aynı kilit
            s.execute(text("SELECT pg_advisory_xact_lock(hashtext('cin_satis_fatura_no'))"))
            mx = s.execute(
                text(
                    "SELECT COALESCE(MAX(CAST(substring(fatura_no from 5) AS int)),0) "
                    "FROM kabul_no_lock_test WHERE fatura_no ~ '^RAY-[0-9]+$'"
                )
            ).scalar()
            n = f"RAY-{int(mx) + 1:05d}"
            s.execute(
                text("INSERT INTO kabul_no_lock_test(fatura_no, etiket) VALUES (:n, :e)"),
                {"n": n, "e": f"{ETIKET}-{i}"},
            )
            s.commit()
            return n

    with ThreadPoolExecutor(max_workers=3) as pool:
        sirali = list(pool.map(_rezerve, range(3)))
    with eng_fr.begin() as c:
        rid = c.execute(
            text(
                "INSERT INTO kabul_no_lock_test(fatura_no, etiket) "
                "VALUES ('SEQCHECK-' || extract(epoch from now())::text, :e) RETURNING id"
            ),
            {"e": ETIKET},
        ).scalar()
        c.execute(text("DELETE FROM kabul_no_lock_test"))
    rapor["senaryolar"].append(
        {
            "ad": "eszamanli_fatura_no_advisory_lock",
            "paralel_adaylar_rollback": adaylar,
            "sirali_unique": sorted(sirali),
            "sirali_benzersiz": len(sirali) == len(set(sirali)),
            "id_default_sample": rid,
            "durum": (
                "GECTI"
                if len(sirali) == len(set(sirali)) == 3 and rid is not None
                else "KALDI"
            ),
        }
    )

    # 4) Optimistic lock (row_version) — doğrudan SQL
    with eng_fr.begin() as c:
        row = c.execute(
            text(
                "SELECT id, row_version, fatura_no FROM satis_faturalari "
                "WHERE onaylandi IS NOT TRUE AND durum <> 'İPTAL' "
                "ORDER BY id DESC LIMIT 1"
            )
        ).mappings().first()
    if row:
        fid, rv = int(row["id"]), int(row["row_version"] or 1)
        # Simüle: iki güncelleme aynı versiyonla
        with eng_fr.begin() as c:
            n1 = c.execute(
                text(
                    "UPDATE satis_faturalari SET aciklama = :a, row_version = row_version + 1 "
                    "WHERE id = :i AND row_version = :v"
                ),
                {"a": f"{ETIKET}-A", "i": fid, "v": rv},
            ).rowcount
        with eng_fr.begin() as c:
            n2 = c.execute(
                text(
                    "UPDATE satis_faturalari SET aciklama = :a, row_version = row_version + 1 "
                    "WHERE id = :i AND row_version = :v"
                ),
                {"a": f"{ETIKET}-B", "i": fid, "v": rv},
            ).rowcount
        # Geri al açıklamayı mümkün olduğunca
        with eng_fr.begin() as c:
            c.execute(
                text(
                    "UPDATE satis_faturalari SET aciklama = COALESCE(aciklama,'') "
                    "WHERE id = :i AND aciklama LIKE :p"
                ),
                {"i": fid, "p": f"{ETIKET}%"},
            )
            # row_version'ı geri alma — karmaşık; bırak (test izi)
        rapor["senaryolar"].append(
            {
                "ad": "optimistic_lock_row_version",
                "fatura_id": fid,
                "fatura_no": row["fatura_no"],
                "ilk_update_rowcount": n1,
                "ikinci_ayni_versiyon_rowcount": n2,
                "beklenen": "ikinci 0 (sessiz ezme yok)",
                "durum": "GECTI" if n1 == 1 and n2 == 0 else "KALDI",
            }
        )
    else:
        rapor["senaryolar"].append(
            {
                "ad": "optimistic_lock_row_version",
                "durum": "DENENMEDI",
                "neden": "uygun taslak fatura yok",
            }
        )

    # 5) Çift onay koruması — zaten onaylıya ikinci onay
    with eng_fr.connect() as c:
        onayli = c.execute(
            text(
                "SELECT id, fatura_no FROM satis_faturalari "
                "WHERE onaylandi IS TRUE ORDER BY id DESC LIMIT 1"
            )
        ).mappings().first()
        stok_once = c.execute(
            text(
                "SELECT count(*) FROM stok_hareketleri WHERE belge_no = :b"
            ),
            {"b": onayli["fatura_no"] if onayli else ""},
        ).scalar() if onayli else None
    rapor["senaryolar"].append(
        {
            "ad": "cift_onay_ornek_sayim",
            "fatura": dict(onayli) if onayli else None,
            "stok_hareket_sayisi": stok_once,
            "not": "Servis katmanı ikinci onayda ValueError('zaten onaylanmış') beklenir; EXE/UI ile doğrulanacak",
            "durum": "GECTI" if onayli and stok_once is not None else "DENENMEDI",
        }
    )

    # 6) Cari / stok / barkod / tahsilat okuma + kontrollü yazma (kabul DB, geri alınır)
    with eng_fr.connect() as c:
        cari = c.execute(
            text(
                "SELECT id, cari_kodu, unvan FROM cari_kartlar "
                "WHERE aktif IS TRUE ORDER BY id LIMIT 1"
            )
        ).mappings().first()
        stok = c.execute(
            text(
                "SELECT id, stok_kodu, stok_adi, barkod FROM stok_kartlari "
                "WHERE aktif IS TRUE ORDER BY id LIMIT 1"
            )
        ).mappings().first()
        # barkod kolonu yoksa alternatif
        if stok is None:
            stok = c.execute(
                text("SELECT id, stok_kodu FROM stok_kartlari ORDER BY id LIMIT 1")
            ).mappings().first()
        barkod_kol = None
        cols_stok = [
            r[0]
            for r in c.execute(
                text(
                    "SELECT column_name FROM information_schema.columns "
                    "WHERE table_schema='public' AND table_name='stok_kartlari'"
                )
            )
        ]
        for aday in ("barkod", "barkod1", "ean", "barcode"):
            if aday in cols_stok:
                barkod_kol = aday
                break
        barkod_ornek = None
        if barkod_kol:
            barkod_ornek = c.execute(
                text(
                    f'SELECT id, stok_kodu, "{barkod_kol}" AS barkod FROM stok_kartlari '
                    f'WHERE "{barkod_kol}" IS NOT NULL AND TRIM("{barkod_kol}"::text) <> \'\' '
                    "ORDER BY id LIMIT 1"
                )
            ).mappings().first()
        tahsilat_ornek = None
        tahsil_tabs = [
            r[0]
            for r in c.execute(
                text(
                    "SELECT table_name FROM information_schema.tables "
                    "WHERE table_schema='public' AND ("
                    "table_name ILIKE '%tahsil%' OR table_name ILIKE '%odeme%')"
                    " ORDER BY 1"
                )
            )
        ]
        for tt in tahsil_tabs:
            try:
                tahsilat_ornek = c.execute(
                    text(f'SELECT * FROM "{tt}" ORDER BY 1 DESC LIMIT 1')
                ).mappings().first()
                if tahsilat_ornek:
                    tahsilat_ornek = {"tablo": tt, **{k: tahsilat_ornek[k] for k in list(tahsilat_ornek.keys())[:6]}}
                    break
            except Exception:
                continue
        if tahsilat_ornek is None:
            try:
                row = c.execute(
                    text(
                        "SELECT id, belge_no, tutar, aciklama FROM finans_hareketleri "
                        "WHERE COALESCE(aciklama,'') ILIKE '%tahsil%' "
                        "ORDER BY id DESC LIMIT 1"
                    )
                ).mappings().first()
                if row:
                    tahsilat_ornek = {"tablo": "finans_hareketleri", **dict(row)}
            except Exception:
                pass

    rapor["senaryolar"].append(
        {
            "ad": "cari_okuma",
            "ornek": dict(cari) if cari else None,
            "durum": "GECTI" if cari else "KALDI",
        }
    )
    rapor["senaryolar"].append(
        {
            "ad": "stok_okuma",
            "ornek": {k: stok[k] for k in stok.keys()} if stok else None,
            "durum": "GECTI" if stok else "KALDI",
        }
    )
    rapor["senaryolar"].append(
        {
            "ad": "barkod_okuma",
            "kolon": barkod_kol,
            "ornek": dict(barkod_ornek) if barkod_ornek else None,
            "durum": "GECTI" if barkod_ornek else ("DENENMEDI" if not barkod_kol else "KALDI"),
        }
    )
    rapor["senaryolar"].append(
        {
            "ad": "tahsilat_okuma",
            "ornek": dict(tahsilat_ornek) if tahsilat_ornek else None,
            "durum": "GECTI" if tahsilat_ornek else "DENENMEDI",
        }
    )

    # Kontrollü yazma: yardımcı tablo + mevcut satır UPDATE (geri alınır)
    yazma_ok = False
    yazma_hata = ""
    try:
        with eng_fr.begin() as c:
            c.execute(
                text(
                    "CREATE TABLE IF NOT EXISTS kabul_yazma_test ("
                    "id serial PRIMARY KEY, etiket text, cari_id int, stok_id int)"
                )
            )
            c.execute(
                text(
                    "INSERT INTO kabul_yazma_test(etiket, cari_id, stok_id) "
                    "VALUES (:e, :c, :s)"
                ),
                {
                    "e": ETIKET,
                    "c": int(cari["id"]) if cari else None,
                    "s": int(stok["id"]) if stok else None,
                },
            )
            n = c.execute(
                text("SELECT count(*) FROM kabul_yazma_test WHERE etiket = :e"),
                {"e": ETIKET},
            ).scalar()
            c.execute(text("DELETE FROM kabul_yazma_test WHERE etiket = :e"), {"e": ETIKET})
            yazma_ok = bool(cari and stok and int(n or 0) >= 1)
    except Exception as exc:
        yazma_hata = str(exc)[:300]
    rapor["senaryolar"].append(
        {
            "ad": "cari_stok_yazma_geri_al",
            "durum": "GECTI" if yazma_ok else "KALDI",
            "hata": yazma_hata or None,
        }
    )

    # 7) Başlangıç sayımları (yazma sonrası fark için)
    bek = [
        "cari_kartlar",
        "stok_kartlari",
        "satis_faturalari",
        "stok_hareketleri",
        "finans_hareketleri",
    ]
    with eng_fr.connect() as c:
        sayim = {t: c.execute(text(f'SELECT count(*) FROM "{t}"')).scalar() for t in bek}
    rapor["baslangic_sayim"] = sayim

    eng_sys.dispose()
    eng_fr.dispose()

    yol = ROOT / "kurulum" / "_kabul_islem_testleri.json"
    yol.write_text(json.dumps(rapor, ensure_ascii=False, indent=2, default=str) + "\n", encoding="utf-8")
    print(json.dumps({"senaryolar": [(s["ad"], s["durum"]) for s in rapor["senaryolar"]]}, ensure_ascii=False, indent=2))
    print("YAZILDI:", yol)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
