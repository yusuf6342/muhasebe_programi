"""Genel muhasebe fişi — borç/alacak salt okunur."""

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
    tablo_yok,
)


def scan_muhasebe(rapor: CheckReport) -> None:
    eng = get_engine()
    if eng is None:
        rapor.ekle(
            item(
                durum=SEVERITY_KRITIK,
                modul="muhasebe",
                hata_kodu="DB_ENGINE_YOK",
                aciklama="Muhasebe taraması için aktif DB yok.",
            )
        )
        return
    if not has_table(eng, "muhasebe_fisleri"):
        tablo_yok(rapor, "muhasebe", "muhasebe_fisleri")
        return

    # Başlık borç ≠ alacak (Kesinleşmiş)
    dengesiz = fetchall(
        eng,
        """
        SELECT id, fis_no, toplam_borc, toplam_alacak, durum
        FROM muhasebe_fisleri
        WHERE durum = 'Kesinleşmiş'
          AND ABS(COALESCE(toplam_borc,0) - COALESCE(toplam_alacak,0)) > :tol
        LIMIT :lim
        """,
        {"tol": TOL, "lim": MAX_ORNEK},
    )
    if dengesiz:
        for r in dengesiz:
            rapor.ekle(
                item(
                    durum=SEVERITY_KRITIK,
                    modul="muhasebe",
                    hata_kodu="FIS_BORC_ALACAK",
                    aciklama=(
                        f"Dengesiz kesinleşmiş fiş: {r['fis_no']} "
                        f"(borç={r['toplam_borc']}, alacak={r['toplam_alacak']})"
                    ),
                    kayit_belge=f"{r['fis_no']} / id={r['id']}",
                    onerilen="Fiş satırlarını dengeleyin (Seviye 3 — otomatik hesap uydurma yok).",
                )
            )
    else:
        ok_yok(rapor, "muhasebe", "FIS_DENGE_OK", "Kesinleşmiş fişlerde borç=alacak.")

    # Taslaklarda da büyük fark (uyarı)
    taslak = fetchall(
        eng,
        """
        SELECT id, fis_no, toplam_borc, toplam_alacak
        FROM muhasebe_fisleri
        WHERE durum = 'Taslak'
          AND ABS(COALESCE(toplam_borc,0) - COALESCE(toplam_alacak,0)) > :tol
        LIMIT :lim
        """,
        {"tol": TOL, "lim": MAX_ORNEK},
    )
    if taslak:
        for r in taslak:
            rapor.ekle(
                item(
                    durum=SEVERITY_UYARI,
                    modul="muhasebe",
                    hata_kodu="FIS_TASLAK_DENGESIZ",
                    aciklama=f"Dengesiz taslak fiş: {r['fis_no']}",
                    kayit_belge=f"{r['fis_no']} / id={r['id']}",
                    teknik=f"borc={r['toplam_borc']}; alacak={r['toplam_alacak']}",
                    onerilen="Kesinleştirmeden önce dengeleyin.",
                )
            )

    if has_table(eng, "muhasebe_fis_satirlari"):
        # Başlık vs satır toplamı
        mism = fetchall(
            eng,
            """
            SELECT f.id, f.fis_no, f.toplam_borc, f.toplam_alacak,
                   COALESCE(SUM(s.borc),0) AS s_borc,
                   COALESCE(SUM(s.alacak),0) AS s_alacak
            FROM muhasebe_fisleri f
            LEFT JOIN muhasebe_fis_satirlari s ON s.fis_id = f.id
            WHERE f.durum != 'İptal'
            GROUP BY f.id
            HAVING ABS(COALESCE(f.toplam_borc,0) - COALESCE(SUM(s.borc),0)) > :tol
                OR ABS(COALESCE(f.toplam_alacak,0) - COALESCE(SUM(s.alacak),0)) > :tol
            LIMIT :lim
            """,
            {"tol": TOL, "lim": MAX_ORNEK},
        )
        if mism:
            for r in mism:
                rapor.ekle(
                    item(
                        durum=SEVERITY_UYARI,
                        modul="muhasebe",
                        hata_kodu="FIS_BASLIK_SATIR",
                        aciklama=f"Fiş başlık/satır toplamı uyuşmaz: {r['fis_no']}",
                        kayit_belge=f"{r['fis_no']} / id={r['id']}",
                        teknik=(
                            f"hdr borc/alacak={r['toplam_borc']}/{r['toplam_alacak']}; "
                            f"satır={r['s_borc']}/{r['s_alacak']}"
                        ),
                        onerilen=(
                            "Seviye 2: başlığı satır SUM ile eşitle "
                            "(satırlar dengesizse otomatik yok)."
                        ),
                        otomatik="Evet (Seviye 2)",
                    )
                )
        else:
            ok_yok(rapor, "muhasebe", "FIS_SATIR_OK", "Fiş başlık ve satır toplamları tutarlı.")

        # Çift taraflı satır
        cift = fetchall(
            eng,
            """
            SELECT s.id, s.fis_id, s.hesap_kodu, s.borc, s.alacak
            FROM muhasebe_fis_satirlari s
            WHERE COALESCE(s.borc,0) > 0 AND COALESCE(s.alacak,0) > 0
            LIMIT :lim
            """,
            {"lim": MAX_ORNEK},
        )
        if cift:
            for r in cift:
                rapor.ekle(
                    item(
                        durum=SEVERITY_UYARI,
                        modul="muhasebe",
                        hata_kodu="FIS_CIFT_TARAF",
                        aciklama=f"Satırda hem borç hem alacak: hesap={r['hesap_kodu']}",
                        kayit_belge=f"id={r['id']}",
                        teknik=f"fis_id={r['fis_id']}; borc={r['borc']}; alacak={r['alacak']}",
                        onerilen="Satırı tek taraflı olacak şekilde düzeltin.",
                    )
                )
        else:
            ok_yok(rapor, "muhasebe", "FIS_CIFT_OK", "Çift taraflı fiş satırı yok.")
