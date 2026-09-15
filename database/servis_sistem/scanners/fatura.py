"""Fatura / belge — satış ve alış salt okunur bütünlük."""

from __future__ import annotations

from database.servis_sistem.scanners.common import (
    MAX_ORNEK,
    TOL,
    SEVERITY_KRITIK,
    SEVERITY_UYARI,
    CheckReport,
    fetchall,
    get_engine,
    has_table,
    item,
    ok_yok,
    table_columns,
    tablo_yok,
)


def scan_fatura(rapor: CheckReport, *, yon: str = "satis") -> None:
    """yon: satis | alis — her ikisi için aynı kontroller."""
    modul = "satis" if yon == "satis" else "alis"
    if yon == "satis":
        hdr, sat, no_col, del_clause = (
            "satis_faturalari",
            "satis_faturasi_satirlari",
            "fatura_no",
            "AND COALESCE(f.is_deleted, 0) = 0",
        )
    else:
        hdr, sat, no_col, del_clause = (
            "alis_faturalari",
            "alis_faturasi_satirlari",
            "fatura_no",
            "",
        )

    eng = get_engine()
    if eng is None:
        rapor.ekle(
            item(
                durum=SEVERITY_KRITIK,
                modul=modul,
                hata_kodu="DB_ENGINE_YOK",
                aciklama=f"{modul} fatura taraması için aktif DB yok.",
            )
        )
        return
    if not has_table(eng, hdr):
        tablo_yok(rapor, modul, hdr)
        return

    # Eksik cari
    rows = fetchall(
        eng,
        f"""
        SELECT f.id, f.{no_col} AS belge, f.cari_id FROM {hdr} f
        LEFT JOIN cari_kartlar c ON c.id = f.cari_id
        WHERE c.id IS NULL {del_clause}
        LIMIT :lim
        """,
        {"lim": MAX_ORNEK},
    )
    if rows:
        for r in rows:
            rapor.ekle(
                item(
                    durum=SEVERITY_KRITIK,
                    modul=modul,
                    hata_kodu="FATURA_CARI_YOK",
                    aciklama=f"Faturada cari bulunamadı: {r['belge']}",
                    kayit_belge=f"{r['belge']} / id={r['id']}",
                    teknik=f"cari_id={r['cari_id']}",
                    onerilen="Faturayı geçerli cariye bağlayın.",
                )
            )
    else:
        ok_yok(rapor, modul, "FATURA_CARI_OK", f"{hdr}: eksik cari yok.")

    if not has_table(eng, sat):
        tablo_yok(rapor, modul, sat)
        return

    # Sıfır satır (iptal hariç)
    zero = fetchall(
        eng,
        f"""
        SELECT f.id, f.{no_col} AS belge FROM {hdr} f
        LEFT JOIN {sat} s ON s.fatura_id = f.id
        WHERE COALESCE(f.durum, '') != 'İPTAL' {del_clause}
        GROUP BY f.id
        HAVING COUNT(s.id) = 0
        LIMIT :lim
        """,
        {"lim": MAX_ORNEK},
    )
    if zero:
        for r in zero:
            rapor.ekle(
                item(
                    durum=SEVERITY_UYARI,
                    modul=modul,
                    hata_kodu="FATURA_SIFIR_SATIR",
                    aciklama=f"Satırsız fatura: {r['belge']}",
                    kayit_belge=f"{r['belge']} / id={r['id']}",
                    onerilen="Faturaya satır ekleyin veya iptal edin.",
                )
            )
    else:
        ok_yok(rapor, modul, "FATURA_SATIR_OK", f"{hdr}: satırsız fatura yok.")

    # Başlık tutar tutarsızlığı: matrah + kdv ≈ genel_toplam
    if has_table(eng, hdr):
        cols = table_columns(eng, hdr)
        if {"tl_matrah", "tl_kdv", "tl_genel_toplam"}.issubset(cols):
            bad = fetchall(
                eng,
                f"""
                SELECT f.id, f.{no_col} AS belge,
                       f.tl_matrah, f.tl_kdv, f.tl_genel_toplam,
                       (COALESCE(f.tl_matrah,0) + COALESCE(f.tl_kdv,0)) AS hesap
                FROM {hdr} f
                WHERE COALESCE(f.durum, '') != 'İPTAL' {del_clause}
                  AND ABS(
                    (COALESCE(f.tl_matrah,0) + COALESCE(f.tl_kdv,0))
                    - COALESCE(f.tl_genel_toplam,0)
                  ) > :tol
                LIMIT :lim
                """,
                {"tol": TOL, "lim": MAX_ORNEK},
            )
            if bad:
                for r in bad:
                    rapor.ekle(
                        item(
                            durum=SEVERITY_UYARI,
                            modul=modul,
                            hata_kodu="FATURA_TOPLAM_UYUSMAZ",
                            aciklama=(
                                f"Fatura toplam uyuşmazlığı: {r['belge']} "
                                f"(matrah+kdv={r['hesap']} ≠ genel={r['tl_genel_toplam']})"
                            ),
                            kayit_belge=f"{r['belge']} / id={r['id']}",
                            teknik=(
                                f"matrah={r['tl_matrah']}; kdv={r['tl_kdv']}; "
                                f"genel={r['tl_genel_toplam']}"
                            ),
                            onerilen=(
                                "Seviye 2: başlık tutarlarını satırlardan yeniden hesapla "
                                "(uydurma yok)."
                            ),
                            otomatik="Evet (Seviye 2)",
                        )
                    )
            else:
                ok_yok(
                    rapor,
                    modul,
                    "FATURA_TOPLAM_OK",
                    f"{hdr}: matrah+kdv ile genel toplam tutarlı.",
                )

            sat_cols = table_columns(eng, sat)
            if "tl_tutar" in sat_cols:
                # tl_tutar genelde KDV'siz satır tutarı → matrah ile kıyasla
                mism_matrah = fetchall(
                    eng,
                    f"""
                    SELECT f.id, f.{no_col} AS belge,
                           f.tl_matrah,
                           COALESCE(SUM(s.tl_tutar), 0) AS satir_toplam
                    FROM {hdr} f
                    LEFT JOIN {sat} s ON s.fatura_id = f.id
                    WHERE COALESCE(f.durum, '') != 'İPTAL' {del_clause}
                    GROUP BY f.id
                    HAVING ABS(COALESCE(f.tl_matrah,0) - COALESCE(SUM(s.tl_tutar),0)) > :tol
                       AND COUNT(s.id) > 0
                    LIMIT :lim
                    """,
                    {"tol": TOL, "lim": MAX_ORNEK},
                )
                if mism_matrah:
                    for r in mism_matrah:
                        rapor.ekle(
                            item(
                                durum=SEVERITY_UYARI,
                                modul=modul,
                                hata_kodu="FATURA_SATIR_MATRAH",
                                aciklama=(
                                    f"Satır toplamı ≠ matrah: {r['belge']} "
                                    f"(satır={r['satir_toplam']}, matrah={r['tl_matrah']})"
                                ),
                                kayit_belge=f"{r['belge']} / id={r['id']}",
                                onerilen=(
                                    "Seviye 2: başlık matrah/kdv/genel satırlardan yeniden yazılsın."
                                ),
                                otomatik="Evet (Seviye 2)",
                            )
                        )
                else:
                    ok_yok(
                        rapor,
                        modul,
                        "FATURA_SATIR_MATRAH_OK",
                        f"{hdr}: satır toplamı ile matrah tutarlı.",
                    )
