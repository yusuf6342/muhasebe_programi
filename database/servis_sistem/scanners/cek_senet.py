"""Çek / senet — salt okunur durum tutarlılığı."""

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

_GECERLI_DURUMLAR = (
    "PORTFOYDE",
    "BANKAYA_TAHSILE",
    "BANKAYA_TEMINATA",
    "CIRO_EDILDI",
    "TEDARIKCIYE_VERILDI",
    "TAHSIL_EDILDI",
    "ODENDI",
    "KISMI_TAHSIL",
    "KISMI_ODENDI",
    "KARSILIKSIZ",
    "PROTESTO",
    "IADE",
    "GERI_ALINDI",
    "IPTAL",
    "YENILENDI",
    "HUKUKI_TAKIP",
    "VADESI_GECTI",
    "KAPANDI",
)

_KAPANMIS = ("TAHSIL_EDILDI", "ODENDI", "KAPANDI", "IPTAL")


def scan_cek_senet(rapor: CheckReport) -> None:
    eng = get_engine()
    if eng is None:
        rapor.ekle(
            item(
                durum=SEVERITY_KRITIK,
                modul="cek_senet",
                hata_kodu="DB_ENGINE_YOK",
                aciklama="Çek/senet taraması için aktif DB yok.",
            )
        )
        return
    if not has_table(eng, "cek_senet_evraklari"):
        tablo_yok(rapor, "cek_senet", "cek_senet_evraklari")
        return

    placeholders = ", ".join(f"'{d}'" for d in _GECERLI_DURUMLAR)
    bad_durum = fetchall(
        eng,
        f"""
        SELECT id, portfoy_no, durum FROM cek_senet_evraklari
        WHERE durum NOT IN ({placeholders})
        LIMIT :lim
        """,
        {"lim": MAX_ORNEK},
    )
    if bad_durum:
        for r in bad_durum:
            rapor.ekle(
                item(
                    durum=SEVERITY_UYARI,
                    modul="cek_senet",
                    hata_kodu="CEK_DURUM_GECERSIZ",
                    aciklama=f"Geçersiz durum: {r['portfoy_no']} → {r['durum']}",
                    kayit_belge=f"{r['portfoy_no']} / id={r['id']}",
                    onerilen="Durumu bilinen değerlere çekin.",
                )
            )
    else:
        ok_yok(rapor, "cek_senet", "CEK_DURUM_OK", "Geçersiz çek/senet durumu yok.")

    tutar = fetchall(
        eng,
        """
        SELECT id, portfoy_no, tl_tutari, tahsil_edilen_tutar, kalan_tutar
        FROM cek_senet_evraklari
        WHERE ABS(
            COALESCE(kalan_tutar,0)
            - (COALESCE(tl_tutari,0) - COALESCE(tahsil_edilen_tutar,0))
        ) > :tol
        LIMIT :lim
        """,
        {"tol": TOL, "lim": MAX_ORNEK},
    )
    if tutar:
        for r in tutar:
            bek = float(r["tl_tutari"] or 0) - float(r["tahsil_edilen_tutar"] or 0)
            rapor.ekle(
                item(
                    durum=SEVERITY_UYARI,
                    modul="cek_senet",
                    hata_kodu="CEK_TUTAR_UYUSMAZ",
                    aciklama=(
                        f"Tutar tutarsızlığı: {r['portfoy_no']} "
                        f"(kalan={r['kalan_tutar']}, beklenen={bek})"
                    ),
                    kayit_belge=f"{r['portfoy_no']} / id={r['id']}",
                    onerilen=(
                        "Seviye 2: kalan_tutar = tl_tutari − tahsil_edilen_tutar yazılsın."
                    ),
                    otomatik="Evet (Seviye 2)",
                )
            )
    else:
        ok_yok(rapor, "cek_senet", "CEK_TUTAR_OK", "Kalan tutar formülü tutarlı.")

    kapali = ", ".join(f"'{d}'" for d in _KAPANMIS)
    acik_kalan = fetchall(
        eng,
        f"""
        SELECT id, portfoy_no, durum, kalan_tutar FROM cek_senet_evraklari
        WHERE durum IN ({kapali}) AND COALESCE(kalan_tutar,0) > :tol
        LIMIT :lim
        """,
        {"tol": TOL, "lim": MAX_ORNEK},
    )
    if acik_kalan:
        for r in acik_kalan:
            rapor.ekle(
                item(
                    durum=SEVERITY_UYARI,
                    modul="cek_senet",
                    hata_kodu="CEK_KAPALI_KALAN",
                    aciklama=(
                        f"Kapalı durumda açık kalan: {r['portfoy_no']} "
                        f"({r['durum']}, kalan={r['kalan_tutar']})"
                    ),
                    kayit_belge=f"{r['portfoy_no']} / id={r['id']}",
                    onerilen="Kalan tutarı sıfırlayın veya durumu düzeltin.",
                )
            )
    else:
        ok_yok(rapor, "cek_senet", "CEK_KAPALI_OK", "Kapalı evraklarda açık kalan yok.")

    n = fetchall(
        eng,
        """
        SELECT COUNT(*) AS n FROM cek_senet_evraklari e
        WHERE e.cari_id IS NOT NULL
          AND NOT EXISTS (SELECT 1 FROM cari_kartlar c WHERE c.id = e.cari_id)
        """,
    )[0]["n"]
    if n:
        rapor.ekle(
            item(
                durum=SEVERITY_KRITIK,
                modul="cek_senet",
                hata_kodu="CEK_CARI_YETIM",
                aciklama=f"Çek/senette geçersiz cari: {n} evrak",
                teknik=f"count={n}",
                onerilen="Evrak cari bağlantısını düzeltin.",
            )
        )
    else:
        ok_yok(rapor, "cek_senet", "CEK_CARI_OK", "Çek/senet cari referansları geçerli.")
