"""Örnek teklif Word/PDF çıktısı üret — tasarım doğrulama."""
from __future__ import annotations

from datetime import date
from decimal import Decimal
from pathlib import Path

from database.teklif_customer_view import (
    DEFAULT_HITAP_METNI,
    DEFAULT_SART_MADDELERI,
    MUSTERI_ONAY_BEYANI,
    CustomerQuoteLine,
    CustomerQuoteViewModel,
    FIRMA_ALT_SLOGAN,
)
from teklif_customer_html import render_customer_quote_html
from teklif_docx import render_customer_quote_docx
from teklif_print import html_to_pdf, safe_customer_export_name


def _ornek_vm(*, cok_satir: bool = False) -> CustomerQuoteViewModel:
    satirlar = [
        CustomerQuoteLine(
            sira=1,
            urun_kodu="RM-VIDA-001",
            urun_adi="Mobilya Vida Seti 4x40 mm — Paslanmaz, 100'lü paket",
            aciklama="Uzun açıklama: mutfak dolabı menteşe montajı için uygundur; renk seçenekleri mevcuttur.",
            miktar=Decimal("25"),
            birim="Paket",
            birim_fiyat=Decimal("1250.00"),
            iskonto_orani=Decimal("5"),
            net_birim_fiyat=Decimal("1187.50"),
            kdv_orani=Decimal("20"),
            kdv_hariç_toplam=Decimal("29687.50"),
            kdv_tutari=Decimal("5937.50"),
            kdv_dahil_toplam=Decimal("35625.00"),
            miktar_goster="25,00",
            birim_fiyat_goster="1.250,00",
            iskonto_goster="%5,00",
            net_goster="1.187,50",
            kdv_oran_goster="%20,00",
            kdv_hariç_goster="29.687,50",
            kdv_goster="5.937,50",
            kdv_dahil_goster="35.625,00",
        )
    ]
    if cok_satir:
        for i in range(2, 28):
            satirlar.append(
                CustomerQuoteLine(
                    sira=i,
                    urun_kodu=f"RM-{i:03d}",
                    urun_adi=f"Aksesuar kalemi {i} — örnek çok sayfalı satır",
                    miktar=Decimal("2"),
                    birim="Adet",
                    birim_fiyat=Decimal("100"),
                    net_birim_fiyat=Decimal("100"),
                    kdv_orani=Decimal("20"),
                    kdv_hariç_toplam=Decimal("200"),
                    kdv_tutari=Decimal("40"),
                    kdv_dahil_toplam=Decimal("240"),
                    miktar_goster="2,00",
                    birim_fiyat_goster="100,00",
                    iskonto_goster="—",
                    net_goster="100,00",
                    kdv_oran_goster="%20,00",
                    kdv_hariç_goster="200,00",
                    kdv_goster="40,00",
                    kdv_dahil_goster="240,00",
                )
            )
    return CustomerQuoteViewModel(
        belge_baslik="FİYAT TEKLİFİ",
        firma={
            "unvan": "RAY MOBİLYA AKSESUARLARI",
            "telefon": "0506 136 97 24",
            "adres": "Adnan Kahveci Mah. Kazım Karabekir Cad. No:52 Beylikdüzü/İstanbul",
            "email": "info@raymobilya.com",
            "web": "www.raymobilya.com",
            "vergi_dairesi": "Beylikdüzü",
            "vergi_no": "1234567890",
        },
        firma_slogan=FIRMA_ALT_SLOGAN,
        teklif_no="TKL-2026-00125",
        teklif_tarihi="17.09.2026",
        gecerlilik_tarihi="17.10.2026",
        hazirlayan="Yusuf Test",
        satis_temsilcisi="Satış Temsilcisi",
        durum="TASLAK",
        revizyon_goster="",
        musteri={
            "unvan": "Ahmet Yılmaz Mobilya Ltd. Şti.",
            "yetkili": "Ahmet Yılmaz",
            "telefon": "0532 000 00 00",
            "email": "ahmet@ornek.com",
            "vergi_dairesi": "Kadıköy",
            "vergi_no": "1112223334",
            "fatura_adresi": "Caferağa Mah. Moda Cad. No:10 Kadıköy/İstanbul",
            "teslimat_adresi": "Depo: Tuzla OSB",
        },
        satirlar=satirlar,
        ara_toplam=Decimal("29687.50"),
        iskonto_toplam=Decimal("1562.50"),
        kdv_toplam=Decimal("5937.50"),
        genel_toplam=Decimal("35625.00"),
        ara_goster="29.687,50",
        iskonto_goster="1.562,50",
        kdv_goster="5.937,50",
        kdv_haric_goster="29.687,50",
        genel_goster="35.625,00",
        para_birimi="TRY",
        para_birimi_etiket="TL",
        kdv_aciklama="Fiyatlara KDV dahil değildir.",
        hitap_metni=DEFAULT_HITAP_METNI,
        sart_maddeleri=list(DEFAULT_SART_MADDELERI),
        sart_satirlari=[
            ("Teklif geçerlilik süresi", "30 Gün"),
            ("Ödeme şekli", "Havale / EFT"),
            ("Teslim süresi", "7 Gün"),
            ("KDV", "Fiyatlara KDV dahil değildir."),
        ],
        onay_beyani=MUSTERI_ONAY_BEYANI,
        olusturma_tarih_saat="17.09.2026 12:45",
        odeme_sekli="Havale / EFT",
        termin_suresi="7 Gün",
        gecerlilik_suresi="30 Gün",
    )


def main():
    out = Path("ornek_ciktilar") / "teklif"
    out.mkdir(parents=True, exist_ok=True)
    vm = _ornek_vm()
    html = render_customer_quote_html(vm)
    html_yol = out / safe_customer_export_name(vm, "html").replace(".html", "_ornek.html")
    # keep name style
    html_yol = out / "Teklif_TKL-2026-00125_Ahmet-Yilmaz_17-09-2026.html"
    html_yol.write_text(html, encoding="utf-8")
    docx_yol = out / "Teklif_TKL-2026-00125_Ahmet-Yilmaz_17-09-2026.docx"
    render_customer_quote_docx(vm, docx_yol)
    pdf_yol = out / "Teklif_TKL-2026-00125_Ahmet-Yilmaz_17-09-2026.pdf"
    try:
        html_to_pdf(html, pdf_yol)
        pdf_ok = pdf_yol.is_file()
    except Exception as exc:
        pdf_ok = False
        print("PDF_WARN", exc)
    # çok satırlı
    vm2 = _ornek_vm(cok_satir=True)
    html2 = render_customer_quote_html(vm2)
    (out / "Teklif_cok_satir_ornek.html").write_text(html2, encoding="utf-8")
    print("HTML", html_yol, html_yol.stat().st_size)
    print("DOCX", docx_yol, docx_yol.stat().st_size)
    print("PDF", pdf_yol if pdf_ok else "FAILED", pdf_yol.stat().st_size if pdf_ok else 0)
    print("HITAP_OK", DEFAULT_HITAP_METNI[:40] in html)
    print("TITLE_OK", "FİYAT TEKLİFİ" in html)
    print("NO_COST", "maliyet" not in html.lower() and "alış" not in html.lower())


if __name__ == "__main__":
    main()
