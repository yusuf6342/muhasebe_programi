"""Firma kredi kartı hesap ekstresi — ekran / PDF / Excel ortak veri kümesi."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path
from typing import Any

from database.kredi_karti_ekstre_service import KrediKartiEkstreService
from database.finans_service import FinansService

SIFIR = Decimal("0.00")


def _d(val) -> Decimal:
    return Decimal(str(val or 0)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def _maskeli_kart(kart) -> str:
    son4 = (getattr(kart, "son_dort_hane", None) or "").strip()
    if not son4 and getattr(kart, "kart_numarasi", None):
        no = "".join(ch for ch in str(kart.kart_numarasi) if ch.isdigit())
        son4 = no[-4:] if len(no) >= 4 else ""
    return f"****{son4}" if son4 else "****"


def _dosya_ad_parca(kart, donem_etiket: str) -> str:
    maske = _maskeli_kart(kart).replace("*", "")
    guvenli = "".join(ch if ch.isalnum() or ch in "-_" else "_" for ch in donem_etiket)
    return f"KK_Ekstre_{maske}_{guvenli}_{datetime.now().strftime('%Y%m%d_%H%M%S')}"


def rapor_verisi(
    kredi_karti_id: int,
    *,
    ekstre_id: int | None = None,
    kesim_tarihi: date | None = None,
    rapor_tarihi: date | None = None,
) -> dict[str, Any]:
    """Salt okunur ekstre raporu; faiz tahakkuku yapmaz. CVV/full PAN taşımaz."""
    KrediKartiEkstreService.schema_hazirla()
    rapor_tarihi = rapor_tarihi or date.today()
    kart = FinansService.kredi_karti_getir(int(kredi_karti_id))
    if not kart:
        raise ValueError("Kredi kartı bulunamadı.")
    banka = getattr(kart, "banka_karti", None)
    banka_adi = (
        getattr(kart, "kart_bankasi", None)
        or (getattr(banka, "banka_adi", None) if banka else None)
        or "—"
    )
    ozet = KrediKartiEkstreService.kart_borc_ozeti(int(kredi_karti_id), tarih=rapor_tarihi)
    detay = None
    if ekstre_id:
        detay = KrediKartiEkstreService.ekstre_detay(int(ekstre_id))
    elif kesim_tarihi is not None:
        for s in KrediKartiEkstreService.ekstreleri_hesapla(
            bugun=rapor_tarihi, kredi_karti_id=int(kredi_karti_id), odenenleri_dahil=True
        ):
            if s.get("kesim_tarihi") == kesim_tarihi:
                if s.get("ekstre_id"):
                    detay = KrediKartiEkstreService.ekstre_detay(int(s["ekstre_id"]))
                else:
                    detay = {
                        "ekstre_id": None,
                        "kesim_tarihi": s.get("kesim_tarihi"),
                        "donem_baslangic": s.get("donem_baslangic"),
                        "donem_bitis": s.get("donem_bitis"),
                        "son_odeme_tarihi": s.get("son_odeme_tarihi"),
                        "tl_tutar": s.get("tl_tutar") or s.get("toplam_borc"),
                        "odenen": s.get("odenen") or 0,
                        "kalan": s.get("kalan") or 0,
                        "asgari_tutar": s.get("asgari_tutar"),
                        "asgari_odenen": s.get("asgari_odenen") or 0,
                        "ekstre_durum": s.get("durum"),
                        "kesin": bool(s.get("kesin")),
                        "detay_satirlari": s.get("detay_satirlari") or [],
                        "odemeler": s.get("odemeler") or [],
                        "kart_ozeti": ozet,
                    }
                break
    if detay is None:
        # Güncel geçici özet (kesinleşmemiş)
        detay = {
            "ekstre_id": None,
            "kesim_tarihi": None,
            "donem_baslangic": None,
            "donem_bitis": None,
            "son_odeme_tarihi": None,
            "tl_tutar": ozet.get("toplam_borc"),
            "odenen": SIFIR,
            "kalan": ozet.get("toplam_borc"),
            "asgari_tutar": None,
            "asgari_odenen": SIFIR,
            "ekstre_durum": "GECICI",
            "kesin": False,
            "detay_satirlari": [],
            "odemeler": [],
            "kart_ozeti": ozet,
        }

    asgari = detay.get("asgari_tutar")
    asgari_odenen = _d(detay.get("asgari_odenen") or 0)
    kalan_asgari = None
    if asgari is None:
        asgari_metin = "Tanımlanmadı"
    else:
        asgari_d = _d(asgari)
        kalan_asgari = max(SIFIR, asgari_d - asgari_odenen)
        asgari_metin = str(asgari_d)

    hareketler = []
    for s in detay.get("detay_satirlari") or []:
        hareketler.append({
            "tarih": s.get("islem_tarihi"),
            "belge": s.get("kaynak_evrak") or "",
            "aciklama": s.get("aciklama") or "",
            "taksit_no": s.get("tek_cekim_taksit") or "",
            "plan_vadesi": s.get("plan_vadesi") or s.get("vade_tarihi"),
            "banka_vadesi": s.get("banka_vadesi") or s.get("son_odeme_tarihi"),
            "borc": _d(s.get("borc")),
            "odeme": _d(s.get("alacak")),
            "kalan": _d(s.get("etki")),
        })

    # Gelecek taksitler — dönem borcuna ikinci kez eklenmez; ayrı bilgi
    gelecek_taksitler = []
    try:
        for t in FinansService.kredi_karti_bekleyen_taksitler(
            banka_karti_id=int(kart.banka_karti_id),
            kredi_karti_id=int(kart.id),
        ):
            gelecek_taksitler.append({
                "taksit_no": t.get("taksit_no"),
                "plan_vadesi": t.get("vade_tarihi"),
                "banka_vadesi": t.get("banka_vade_tarihi") or t.get("ekstre_kesim_tarihi"),
                "tutar": _d(t.get("tutar")),
                "odenen": _d(t.get("odenen_tutar") or 0),
                "kalan": _d(t.get("tutar")) - _d(t.get("odenen_tutar") or 0),
                "durum": t.get("durum") or "BEKLIYOR",
                "belge_no": t.get("belge_no"),
            })
    except Exception:
        gelecek_taksitler = []

    pb = (ozet.get("para_birimi") or getattr(kart, "para_birimi", None) or "TRY").upper()
    donem_etiket = (
        kesim_tarihi.strftime("%Y%m%d")
        if isinstance(kesim_tarihi, date)
        else (
            detay["kesim_tarihi"].strftime("%Y%m%d")
            if isinstance(detay.get("kesim_tarihi"), date)
            else "gecici"
        )
    )
    return {
        "rapor_tarihi": rapor_tarihi,
        "banka_adi": banka_adi,
        "kart_adi": kart.kart_adi,
        "maskeli_no": _maskeli_kart(kart),
        "para_birimi": pb,
        "kesin": bool(detay.get("kesin")),
        "gecici": not bool(detay.get("kesin")),
        "kesim_tarihi": detay.get("kesim_tarihi"),
        "donem_baslangic": detay.get("donem_baslangic"),
        "donem_bitis": detay.get("donem_bitis"),
        "son_odeme_tarihi": detay.get("son_odeme_tarihi"),
        "donem_borc": _d(detay.get("tl_tutar")),
        "donem_odenen": _d(detay.get("odenen")),
        "donem_kalan": _d(detay.get("kalan")),
        "toplam_kart_borcu": _d(ozet.get("toplam_borc")),
        "gelecek_taksit_toplami": _d(ozet.get("kesilmemis")),
        "asgari_tutar": _d(asgari) if asgari is not None else None,
        "asgari_metin": asgari_metin,
        "asgari_odenen": asgari_odenen,
        "kalan_asgari": kalan_asgari,
        "limit": ozet.get("limit"),
        "limit_tanimli": bool(ozet.get("limit_tanimli")),
        "kullanilabilir": ozet.get("kullanilabilir"),
        "hareketler": hareketler,
        "odemeler": detay.get("odemeler") or [],
        "gelecek_taksitler": gelecek_taksitler,
        "dosya_kok": _dosya_ad_parca(kart, donem_etiket),
        # Hassas alan yok
        "cvv": None,
        "kart_numarasi": None,
    }


def excel_kaydet(rapor: dict, yol: str | Path) -> Path:
    from openpyxl import Workbook
    from openpyxl.styles import Font
    from openpyxl.utils import get_column_letter

    yol = Path(yol)
    wb = Workbook()
    ws = wb.active
    ws.title = "Özet"
    ws.append(["Firma Kredi Kartı Hesap Ekstresi"])
    ws["A1"].font = Font(bold=True, size=14)
    satirlar = [
        ("Rapor tarihi", rapor["rapor_tarihi"]),
        ("Banka", rapor["banka_adi"]),
        ("Kart", rapor["kart_adi"]),
        ("Kart no", rapor["maskeli_no"]),
        ("Para birimi", rapor["para_birimi"]),
        ("Kesim", rapor.get("kesim_tarihi")),
        ("Dönem", f"{rapor.get('donem_baslangic') or '—'} – {rapor.get('donem_bitis') or '—'}"),
        ("Banka son ödeme", rapor.get("son_odeme_tarihi") or "Tanımlanmadı"),
        ("Dönem borcu", float(rapor["donem_borc"])),
        ("Dönem ödenen", float(rapor["donem_odenen"])),
        ("Dönem kalan", float(rapor["donem_kalan"])),
        ("Toplam kart borcu", float(rapor["toplam_kart_borcu"])),
        ("Gelecek taksit (bilgi)", float(rapor["gelecek_taksit_toplami"])),
        ("Ekstre asgari", rapor["asgari_metin"]),
        ("Asgariye sayılan", float(rapor["asgari_odenen"])),
        (
            "Kalan asgari",
            float(rapor["kalan_asgari"]) if rapor["kalan_asgari"] is not None else "Tanımlanmadı",
        ),
        (
            "Hesaplanan kullanılabilir limit",
            float(rapor["kullanilabilir"])
            if rapor.get("limit_tanimli") and rapor.get("kullanilabilir") is not None
            else "Tanımlanmadı",
        ),
    ]
    for etiket, deger in satirlar:
        ws.append([etiket, deger])

    wh = wb.create_sheet("Hareketler")
    wh.append([
        "Tarih", "Belge/İşlem", "Açıklama", "Taksit No", "Plan Vadesi",
        "Banka Vadesi", "Borç", "Ödeme/Alacak", "Kalan",
    ])
    for h in rapor["hareketler"]:
        wh.append([
            h.get("tarih"), h.get("belge"), h.get("aciklama"), h.get("taksit_no"),
            h.get("plan_vadesi"), h.get("banka_vadesi"),
            float(h["borc"]), float(h["odeme"]), float(h["kalan"]),
        ])
    wh.auto_filter.ref = wh.dimensions
    wh.freeze_panes = "A2"

    wt = wb.create_sheet("Taksit Planı")
    wt.append(["No", "Plan Vadesi", "Banka Vadesi", "Tutar", "Ödenen", "Kalan", "Durum", "Belge"])
    for t in rapor["gelecek_taksitler"]:
        wt.append([
            t.get("taksit_no"), t.get("plan_vadesi"), t.get("banka_vadesi"),
            float(t["tutar"]), float(t["odenen"]), float(t["kalan"]),
            t.get("durum"), t.get("belge_no"),
        ])
    wt.freeze_panes = "A2"

    wf = wb.create_sheet("Faiz Detayı")
    wf.append(["Bilgi", "Değer"])
    wf.append([
        "Not",
        "Faiz tahakkuku bu raporda yapılmaz. Doğrulanmış profil yoksa tutar uydurulmaz.",
    ])

    for sheet in wb.worksheets:
        for col in range(1, sheet.max_column + 1):
            sheet.column_dimensions[get_column_letter(col)].width = 18

    yol.parent.mkdir(parents=True, exist_ok=True)
    wb.save(yol)
    return yol


def pdf_kaydet(rapor: dict, yol: str | Path) -> Path:
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4, landscape
    from reportlab.lib.units import mm
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont
    from reportlab.pdfgen import canvas as pdf_canvas

    yol = Path(yol)
    yol.parent.mkdir(parents=True, exist_ok=True)
    # Türkçe karakter: Windows Arial
    font = "Helvetica"
    try:
        pdfmetrics.registerFont(TTFont("ArialTR", "C:/Windows/Fonts/arial.ttf"))
        font = "ArialTR"
    except Exception:
        pass

    c = pdf_canvas.Canvas(str(yol), pagesize=landscape(A4))
    genislik, yukseklik = landscape(A4)
    y = yukseklik - 15 * mm

    def satir(metin, *, boyut=10, kalin=False, dx=15 * mm):
        nonlocal y
        c.setFont(font, boyut)
        c.drawString(dx, y, str(metin)[:140])
        y -= (boyut + 4)

    c.setFont(font, 14)
    c.drawString(15 * mm, y, "FİRMA KREDİ KARTI HESAP EKSTRESİ")
    y -= 8 * mm
    satir(f"{rapor['banka_adi']} / {rapor['kart_adi']} / {rapor['maskeli_no']}", boyut=11)
    satir(
        f"Rapor: {rapor['rapor_tarihi'].strftime('%d.%m.%Y')}  ·  PB: {rapor['para_birimi']}  ·  "
        f"{'Kesinleşmiş' if rapor['kesin'] else 'Geçici / güncel'}"
    )
    satir(
        f"Kesim: {rapor.get('kesim_tarihi') or '—'}  ·  "
        f"Dönem: {rapor.get('donem_baslangic') or '—'} – {rapor.get('donem_bitis') or '—'}  ·  "
        f"Banka son ödeme: {rapor.get('son_odeme_tarihi') or 'Tanımlanmadı'}"
    )
    satir(
        f"Dönem borcu: {rapor['donem_borc']}  ·  Ödenen: {rapor['donem_odenen']}  ·  "
        f"Kalan: {rapor['donem_kalan']}  ·  Toplam kart borcu: {rapor['toplam_kart_borcu']}"
    )
    satir(
        f"Asgari: {rapor['asgari_metin']}  ·  Asgariye sayılan: {rapor['asgari_odenen']}  ·  "
        f"Kalan asgari: {rapor['kalan_asgari'] if rapor['kalan_asgari'] is not None else 'Tanımlanmadı'}"
    )
    satir(f"Gelecek taksitler (bilgi, çift sayılmaz): {rapor['gelecek_taksit_toplami']}")
    y -= 3 * mm
    satir("Hareketler", boyut=11, kalin=True)
    headers = ("Tarih", "Belge", "Açıklama", "Tk", "Plan vd", "Banka vd", "Borç", "Ödeme", "Kalan")
    x0 = 12 * mm
    col_w = [22 * mm, 28 * mm, 55 * mm, 12 * mm, 22 * mm, 22 * mm, 22 * mm, 22 * mm, 22 * mm]
    c.setFillColor(colors.Color(0.05, 0.15, 0.35))
    c.rect(x0, y - 2 * mm, sum(col_w), 7 * mm, fill=1, stroke=0)
    c.setFillColor(colors.white)
    c.setFont(font, 8)
    x = x0
    for h, w in zip(headers, col_w):
        c.drawString(x + 1 * mm, y, h)
        x += w
    y -= 8 * mm
    c.setFillColor(colors.black)
    sayfa = 1

    def yeni_sayfa():
        nonlocal y, sayfa
        c.setFont(font, 8)
        c.drawRightString(genislik - 12 * mm, 8 * mm, f"Sayfa {sayfa}")
        c.showPage()
        sayfa += 1
        y = yukseklik - 15 * mm
        c.setFont(font, 9)
        c.drawString(15 * mm, y, f"{rapor['kart_adi']} / {rapor['maskeli_no']} — devam")
        y -= 10 * mm

    for h in rapor["hareketler"]:
        if y < 20 * mm:
            yeni_sayfa()
        degerler = [
            h.get("tarih").strftime("%d.%m.%Y") if hasattr(h.get("tarih"), "strftime") else str(h.get("tarih") or ""),
            str(h.get("belge") or "")[:18],
            str(h.get("aciklama") or "")[:36],
            str(h.get("taksit_no") or ""),
            h.get("plan_vadesi").strftime("%d.%m.%Y") if hasattr(h.get("plan_vadesi"), "strftime") else str(h.get("plan_vadesi") or ""),
            h.get("banka_vadesi").strftime("%d.%m.%Y") if hasattr(h.get("banka_vadesi"), "strftime") else str(h.get("banka_vadesi") or ""),
            f"{h['borc']:,.2f}",
            f"{h['odeme']:,.2f}",
            f"{h['kalan']:,.2f}",
        ]
        c.setFont(font, 7)
        x = x0
        for deger, w in zip(degerler, col_w):
            c.drawString(x + 1 * mm, y, deger)
            x += w
        y -= 5 * mm

    c.setFont(font, 8)
    c.drawRightString(genislik - 12 * mm, 8 * mm, f"Sayfa {sayfa}")
    c.save()
    return yol


def email_icin_hazirla(rapor: dict, klasor: str | Path) -> dict[str, Path]:
    """PDF (+ Excel) üretir; otomatik gönderim yapmaz."""
    klasor = Path(klasor)
    klasor.mkdir(parents=True, exist_ok=True)
    pdf_yol = pdf_kaydet(rapor, klasor / f"{rapor['dosya_kok']}.pdf")
    xlsx_yol = excel_kaydet(rapor, klasor / f"{rapor['dosya_kok']}.xlsx")
    return {"pdf": pdf_yol, "excel": xlsx_yol}
