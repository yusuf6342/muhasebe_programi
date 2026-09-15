"""Kasa / banka (finans) — salt okunur."""

from __future__ import annotations

from decimal import Decimal

from database.servis_sistem.scanners.common import (
    MAX_FINANS_BAKIYE_ORNEK,
    MAX_ORNEK,
    TOL,
    SEVERITY_INFO,
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


def scan_finans(rapor: CheckReport) -> None:
    eng = get_engine()
    if eng is None:
        rapor.ekle(
            item(
                durum=SEVERITY_KRITIK,
                modul="finans",
                hata_kodu="DB_ENGINE_YOK",
                aciklama="Finans taraması için aktif DB yok.",
            )
        )
        return
    if not has_table(eng, "finans_hesaplari"):
        tablo_yok(rapor, "finans", "finans_hesaplari")
        return

    # Yetim hareket
    if has_table(eng, "finans_hareketleri"):
        n = fetchall(
            eng,
            """
            SELECT COUNT(*) AS n FROM finans_hareketleri h
            LEFT JOIN finans_hesaplari a ON a.id = h.hesap_id
            WHERE a.id IS NULL
            """,
        )[0]["n"]
        if n:
            for r in fetchall(
                eng,
                """
                SELECT h.id, h.belge_no, h.hesap_id FROM finans_hareketleri h
                LEFT JOIN finans_hesaplari a ON a.id = h.hesap_id
                WHERE a.id IS NULL LIMIT :lim
                """,
                {"lim": MAX_ORNEK},
            ):
                rapor.ekle(
                    item(
                        durum=SEVERITY_KRITIK,
                        modul="finans",
                        hata_kodu="FINANS_HAREKET_YETIM",
                        aciklama=f"Yetim finans hareketi: {r['belge_no']}",
                        kayit_belge=f"id={r['id']}",
                        teknik=f"hesap_id={r['hesap_id']}; toplam={n}",
                        onerilen="Hareketi geçerli hesaba bağlayın.",
                    )
                )
        else:
            ok_yok(rapor, "finans", "FINANS_HAREKET_OK", "Yetim finans hareketi yok.")

        # Bakiye = acilis + işaretli hareketler (bilgi: ayrı saklanan bakiye yok)
        # Tutarsızlık: aynı belge_no + hesap için aşırı tekrar (özet)
        rapor.ekle(
            item(
                durum=SEVERITY_INFO,
                modul="finans",
                hata_kodu="FINANS_BAKIYE_MODEL",
                aciklama=(
                    "Hesap bakiyesi ayrı kolon olarak saklanmıyor; "
                    "açılış + hareketlerden hesaplanır. Makbuz satır kontrolleri aşağıda."
                ),
                onerilen="Makbuz ve hareket tutarlılığına bakın.",
            )
        )

        # Örnek: hareket tutarı 0 veya negatif (bilgi/uyarı)
        sifir = fetchall(
            eng,
            """
            SELECT id, belge_no, tutar FROM finans_hareketleri
            WHERE tutar IS NULL OR tutar = 0
            LIMIT :lim
            """,
            {"lim": MAX_ORNEK},
        )
        if sifir:
            rapor.ekle(
                item(
                    durum=SEVERITY_UYARI,
                    modul="finans",
                    hata_kodu="FINANS_SIFIR_HAREKET",
                    aciklama=f"Sıfır tutarlı finans hareketi: {len(sifir)} örnek (limit)",
                    teknik="; ".join(f"id={r['id']}" for r in sifir[:10]),
                    onerilen="Sıfır tutarlı hareketleri inceleyin.",
                )
            )
        else:
            ok_yok(rapor, "finans", "FINANS_SIFIR_OK", "Sıfır tutarlı hareket yok.")

    # Kasa makbuz satır toplamı
    if has_table(eng, "kasa_makbuzlari") and has_table(eng, "kasa_makbuz_satirlari"):
        bad = fetchall(
            eng,
            """
            SELECT m.id, m.belge_no, m.tutar AS baslik,
                   COALESCE(SUM(s.tutar), 0) AS satir
            FROM kasa_makbuzlari m
            LEFT JOIN kasa_makbuz_satirlari s ON s.makbuz_id = m.id
            WHERE COALESCE(m.durum, '') = 'AÇIK'
            GROUP BY m.id
            HAVING ABS(COALESCE(m.tutar,0) - COALESCE(SUM(s.tutar),0)) > :tol
               AND COUNT(s.id) > 0
            LIMIT :lim
            """,
            {"tol": TOL, "lim": MAX_ORNEK},
        )
        if bad:
            for r in bad:
                rapor.ekle(
                    item(
                        durum=SEVERITY_UYARI,
                        modul="finans",
                        hata_kodu="KASA_MAKBUZ_TOPLAM",
                        aciklama=(
                            f"Makbuz satır toplamı uyuşmuyor: {r['belge_no']} "
                            f"(başlık={r['baslik']}, satır={r['satir']})"
                        ),
                        kayit_belge=f"{r['belge_no']} / id={r['id']}",
                        onerilen="Makbuz satırlarını kontrol edin.",
                    )
                )
        else:
            ok_yok(rapor, "finans", "KASA_MAKBUZ_OK", "Açık makbuz satır toplamları tutarlı.")

        # Makbuz cari orphan (FK yok)
        n = fetchall(
            eng,
            """
            SELECT COUNT(*) AS n FROM kasa_makbuzlari m
            WHERE m.cari_id IS NOT NULL
              AND NOT EXISTS (SELECT 1 FROM cari_kartlar c WHERE c.id = m.cari_id)
            """,
        )[0]["n"]
        if n:
            rapor.ekle(
                item(
                    durum=SEVERITY_UYARI,
                    modul="finans",
                    hata_kodu="KASA_MAKBUZ_CARI_YETIM",
                    aciklama=f"Makbuzda geçersiz cari: {n} kayıt",
                    teknik=f"count={n}",
                    onerilen="Makbuz cari bağlantılarını düzeltin.",
                )
            )
        else:
            ok_yok(rapor, "finans", "KASA_MAKBUZ_CARI_OK", "Makbuz cari referansları geçerli.")

    # Hesap açılış + hareketlerden türetilmiş bakiye örnek özeti (salt bilgi)
    if has_table(eng, "finans_hesaplari") and has_table(eng, "finans_hareketleri"):
        try:
            from database.finans_service import FinansService

            hesaplar = fetchall(
                eng,
                "SELECT id, hesap_adi, acilis_bakiyesi FROM finans_hesaplari "
                f"WHERE aktif = 1 LIMIT {int(MAX_FINANS_BAKIYE_ORNEK)}",
            )
            ornek = []
            for h in hesaplar[:30]:
                har = fetchall(
                    eng,
                    "SELECT tutar, hareket_turu FROM finans_hareketleri WHERE hesap_id = :hid",
                    {"hid": h["id"]},
                )

                class _H:
                    pass

                obj = _H()
                obj.acilis_bakiyesi = Decimal(str(h["acilis_bakiyesi"] or 0))
                obj.hareketler = []
                for x in har:
                    m = _H()
                    m.tutar = Decimal(str(x["tutar"] or 0))
                    m.hareket_turu = x["hareket_turu"]
                    obj.hareketler.append(m)
                bakiye = FinansService.bakiye(obj)
                ornek.append(f"{h['hesap_adi']}={bakiye}")
            rapor.ekle(
                item(
                    durum=SEVERITY_INFO,
                    modul="finans",
                    hata_kodu="FINANS_BAKIYE_ORNEK",
                    aciklama=f"Örnek hesap bakiyeleri hesaplandı ({len(ornek)} hesap).",
                    teknik="; ".join(ornek[:15]),
                )
            )
        except Exception as exc:  # noqa: BLE001
            rapor.ekle(
                item(
                    durum=SEVERITY_INFO,
                    modul="finans",
                    hata_kodu="FINANS_BAKIYE_ATLANDI",
                    aciklama="Bakiye örnek hesabı atlandı.",
                    teknik=str(exc),
                )
            )
