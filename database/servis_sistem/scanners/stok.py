"""Stok modülü — salt okunur derin tarama."""

from __future__ import annotations

from database.servis_sistem.scanners.common import (
    MAX_ORNEK,
    SEVERITY_KRITIK,
    SEVERITY_UYARI,
    CheckReport,
    fetchall,
    get_engine,
    has_table,
    item,
    ok_yok,
    tablo_yok,
)


def scan_stok(rapor: CheckReport) -> None:
    eng = get_engine()
    if eng is None:
        rapor.ekle(
            item(
                durum=SEVERITY_KRITIK,
                modul="stok",
                hata_kodu="DB_ENGINE_YOK",
                aciklama="Stok taraması için aktif DB yok.",
            )
        )
        return
    if not has_table(eng, "stok_kartlari"):
        tablo_yok(rapor, "stok", "stok_kartlari")
        return

    # Boş birim
    rows = fetchall(
        eng,
        """
        SELECT id, stok_kodu, stok_adi, birim FROM stok_kartlari
        WHERE COALESCE(is_deleted, 0) = 0
          AND (birim IS NULL OR TRIM(birim) = '')
        LIMIT :lim
        """,
        {"lim": MAX_ORNEK},
    )
    if rows:
        for r in rows:
            rapor.ekle(
                item(
                    durum=SEVERITY_UYARI,
                    modul="stok",
                    hata_kodu="STOK_BIRIM_EKSIK",
                    aciklama=f"Birim eksik: {r['stok_kodu']} — {r['stok_adi']}",
                    kayit_belge=f"id={r['id']}",
                    onerilen="Stok kartında birim alanını doldurun.",
                )
            )
    else:
        ok_yok(rapor, "stok", "STOK_BIRIM_OK", "Eksik birimli stok yok.")

    # Boş ad
    rows = fetchall(
        eng,
        """
        SELECT id, stok_kodu FROM stok_kartlari
        WHERE stok_adi IS NULL OR TRIM(stok_adi) = ''
        LIMIT :lim
        """,
        {"lim": MAX_ORNEK},
    )
    if rows:
        for r in rows:
            rapor.ekle(
                item(
                    durum=SEVERITY_UYARI,
                    modul="stok",
                    hata_kodu="STOK_BOS_AD",
                    aciklama=f"Stok adı boş: {r['stok_kodu']}",
                    kayit_belge=f"id={r['id']}",
                    onerilen="Stok adını doldurun.",
                )
            )
    else:
        ok_yok(rapor, "stok", "STOK_AD_OK", "Boş stok adı yok.")

    dups = fetchall(
        eng,
        """
        SELECT stok_kodu, COUNT(*) AS n FROM stok_kartlari
        GROUP BY stok_kodu HAVING COUNT(*) > 1
        LIMIT :lim
        """,
        {"lim": MAX_ORNEK},
    )
    if dups:
        for r in dups:
            rapor.ekle(
                item(
                    durum=SEVERITY_KRITIK,
                    modul="stok",
                    hata_kodu="STOK_DUPLICATE_KOD",
                    aciklama=f"Yinelenen stok kodu: {r['stok_kodu']} ({r['n']})",
                    kayit_belge=str(r["stok_kodu"]),
                    onerilen="Yinelenen stok kartlarını ayırın.",
                )
            )
    else:
        ok_yok(rapor, "stok", "STOK_DUPLICATE_OK", "Yinelenen stok kodu yok.")

    if has_table(eng, "stok_lotlari"):
        neg = fetchall(
            eng,
            """
            SELECT id, stok_id, depo_id, lot_no, kalan_miktar FROM stok_lotlari
            WHERE kalan_miktar < 0
            LIMIT :lim
            """,
            {"lim": MAX_ORNEK},
        )
        if neg:
            for r in neg:
                rapor.ekle(
                    item(
                        durum=SEVERITY_UYARI,
                        modul="stok",
                        hata_kodu="STOK_NEGATIF_LOT",
                        aciklama=f"Negatif lot stoğu: lot={r['lot_no']} miktar={r['kalan_miktar']}",
                        kayit_belge=f"id={r['id']}",
                        teknik=f"stok_id={r['stok_id']}; depo_id={r['depo_id']}",
                        onerilen="Stok hareketlerini / lot bakiyesini inceleyin (Aşama 3 onarım yok).",
                    )
                )
        else:
            ok_yok(rapor, "stok", "STOK_NEGATIF_OK", "Negatif lot stoğu yok.")

        agg = fetchall(
            eng,
            """
            SELECT stok_id, SUM(kalan_miktar) AS toplam FROM stok_lotlari
            GROUP BY stok_id HAVING SUM(kalan_miktar) < 0
            LIMIT :lim
            """,
            {"lim": MAX_ORNEK},
        )
        if agg:
            for r in agg:
                rapor.ekle(
                    item(
                        durum=SEVERITY_UYARI,
                        modul="stok",
                        hata_kodu="STOK_NEGATIF_TOPLAM",
                        aciklama=f"Stok toplam lot bakiyesi negatif: stok_id={r['stok_id']} ({r['toplam']})",
                        kayit_belge=f"id={r['stok_id']}",
                        onerilen="Lot ve hareket tutarlılığını kontrol edin.",
                    )
                )

    if has_table(eng, "stok_hareketleri"):
        n = fetchall(
            eng,
            """
            SELECT COUNT(*) AS n FROM stok_hareketleri h
            LEFT JOIN stok_kartlari s ON s.id = h.stok_id
            WHERE s.id IS NULL
            """,
        )[0]["n"]
        if n:
            rapor.ekle(
                item(
                    durum=SEVERITY_KRITIK,
                    modul="stok",
                    hata_kodu="STOK_HAREKET_YETIM",
                    aciklama=f"Yetim stok hareketi: {n} kayıt",
                    teknik=f"count={n}",
                    onerilen="Hareketleri geçerli stoğa bağlayın.",
                )
            )
        else:
            ok_yok(rapor, "stok", "STOK_HAREKET_OK", "Yetim stok hareketi yok.")
