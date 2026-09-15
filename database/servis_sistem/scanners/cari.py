"""Cari modülü — salt okunur derin tarama."""

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


def scan_cari(rapor: CheckReport) -> None:
    eng = get_engine()
    if eng is None:
        rapor.ekle(
            item(
                durum=SEVERITY_KRITIK,
                modul="cari",
                hata_kodu="DB_ENGINE_YOK",
                aciklama="Cari taraması için aktif DB yok.",
            )
        )
        return
    if not has_table(eng, "cari_kartlar"):
        tablo_yok(rapor, "cari", "cari_kartlar")
        return

    # Boş / boşluk unvan
    rows = fetchall(
        eng,
        """
        SELECT id, cari_kodu, unvan FROM cari_kartlar
        WHERE unvan IS NULL OR TRIM(unvan) = ''
        LIMIT :lim
        """,
        {"lim": MAX_ORNEK},
    )
    if rows:
        for r in rows:
            rapor.ekle(
                item(
                    durum=SEVERITY_UYARI,
                    modul="cari",
                    hata_kodu="CARI_BOS_UNVAN",
                    aciklama=f"Cari ünvanı boş: kod={r['cari_kodu'] or '?'}",
                    kayit_belge=f"id={r['id']}",
                    teknik=f"cari_kartlar.id={r['id']}",
                    onerilen="Cari kartında ünvan alanını doldurun.",
                )
            )
    else:
        ok_yok(rapor, "cari", "CARI_UNVAN_OK", "Boş ünvanlı cari yok.")

    # Boş kod
    rows = fetchall(
        eng,
        """
        SELECT id, unvan FROM cari_kartlar
        WHERE cari_kodu IS NULL OR TRIM(cari_kodu) = ''
        LIMIT :lim
        """,
        {"lim": MAX_ORNEK},
    )
    if rows:
        for r in rows:
            rapor.ekle(
                item(
                    durum=SEVERITY_KRITIK,
                    modul="cari",
                    hata_kodu="CARI_BOS_KOD",
                    aciklama=f"Cari kodu boş: {r['unvan'] or '?'}",
                    kayit_belge=f"id={r['id']}",
                    onerilen="Cari kodunu düzeltin.",
                )
            )
    else:
        ok_yok(rapor, "cari", "CARI_KOD_OK", "Boş cari kodu yok.")

    # Yinelenen kod (UNIQUE olsa bile bozuk DB için)
    dups = fetchall(
        eng,
        """
        SELECT cari_kodu, COUNT(*) AS n FROM cari_kartlar
        GROUP BY cari_kodu HAVING COUNT(*) > 1
        LIMIT :lim
        """,
        {"lim": MAX_ORNEK},
    )
    if dups:
        for r in dups:
            rapor.ekle(
                item(
                    durum=SEVERITY_KRITIK,
                    modul="cari",
                    hata_kodu="CARI_DUPLICATE_KOD",
                    aciklama=f"Yinelenen cari kodu: {r['cari_kodu']} ({r['n']} kayıt)",
                    kayit_belge=str(r["cari_kodu"]),
                    teknik=f"count={r['n']}",
                    onerilen="Yinelenen kartları birleştirin veya kodları ayırın.",
                )
            )
    else:
        ok_yok(rapor, "cari", "CARI_DUPLICATE_OK", "Yinelenen cari kodu yok.")

    # Orphan cari_islemleri
    if has_table(eng, "cari_islemleri"):
        n = fetchall(
            eng,
            """
            SELECT COUNT(*) AS n FROM cari_islemleri i
            LEFT JOIN cari_kartlar c ON c.id = i.cari_id
            WHERE c.id IS NULL
            """,
        )[0]["n"]
        if n:
            ornek = fetchall(
                eng,
                """
                SELECT i.id, i.belge_no, i.cari_id FROM cari_islemleri i
                LEFT JOIN cari_kartlar c ON c.id = i.cari_id
                WHERE c.id IS NULL LIMIT :lim
                """,
                {"lim": MAX_ORNEK},
            )
            for r in ornek:
                rapor.ekle(
                    item(
                        durum=SEVERITY_KRITIK,
                        modul="cari",
                        hata_kodu="CARI_ISLEM_YETIM",
                        aciklama=f"Cari işlem yetim (cari yok): belge={r['belge_no']}",
                        kayit_belge=f"id={r['id']}",
                        teknik=f"cari_id={r['cari_id']}; toplam_yetim={n}",
                        onerilen="İşlemi geçerli cariye bağlayın veya kaydı inceleyin.",
                    )
                )
        else:
            ok_yok(rapor, "cari", "CARI_ISLEM_OK", "Yetim cari işlemi yok.")

        # karsi_cari orphan
        n2 = fetchall(
            eng,
            """
            SELECT COUNT(*) AS n FROM cari_islemleri i
            WHERE i.karsi_cari_id IS NOT NULL
              AND NOT EXISTS (SELECT 1 FROM cari_kartlar c WHERE c.id = i.karsi_cari_id)
            """,
        )[0]["n"]
        if n2:
            rapor.ekle(
                item(
                    durum=SEVERITY_UYARI,
                    modul="cari",
                    hata_kodu="CARI_KARSI_YETIM",
                    aciklama=f"Karşı cari referansı geçersiz: {n2} işlem",
                    teknik=f"count={n2}",
                    onerilen="Virman/karşı cari bağlantılarını kontrol edin.",
                )
            )
        else:
            ok_yok(rapor, "cari", "CARI_KARSI_OK", "Geçersiz karşı cari yok.")

    if has_table(eng, "cari_satis_hareketleri"):
        n = fetchall(
            eng,
            """
            SELECT COUNT(*) AS n FROM cari_satis_hareketleri h
            LEFT JOIN cari_kartlar c ON c.id = h.cari_id
            WHERE c.id IS NULL
            """,
        )[0]["n"]
        if n:
            rapor.ekle(
                item(
                    durum=SEVERITY_KRITIK,
                    modul="cari",
                    hata_kodu="CARI_SATIS_YETIM",
                    aciklama=f"Yetim cari satış hareketi: {n} kayıt",
                    teknik=f"count={n}",
                    onerilen="Hareketleri geçerli cariye bağlayın.",
                )
            )
        else:
            ok_yok(rapor, "cari", "CARI_SATIS_OK", "Yetim satış hareketi yok.")
