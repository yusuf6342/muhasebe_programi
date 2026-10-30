"""Açık fatura kartına Excel'den kalem ekleme (Dosyadan Aktar → kalem ekle).

Üst bilgiler (cari, tarih, depo, para birimi) kartta korunur.
Dosya okumak stok/cari hareketi yazmaz; yalnız form satırlarına ekler.
"""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path
from tkinter import messagebox
from typing import Any

from excel_aktarim.mapping import ColumnMappingService
from excel_aktarim.normalize import decimal_parse, temiz
from excel_aktarim.reader import ExcelReaderService
from excel_aktarim.types import getir
from fatura_urun_aktar_service import (
    stok_kartini_coz,
    stoktan_satir_sablonu,
    urunu_faturaya_aktar,
)


def _kart_depo(dialog) -> str:
    try:
        if hasattr(dialog, "depo"):
            return (dialog.depo.get() or "").strip()
    except Exception:
        pass
    return ""


def _kart_tarih(dialog) -> str:
    g = getattr(dialog, "girdiler", None) or {}
    w = g.get("tarih")
    try:
        return (w.get() or "").strip() if w is not None else ""
    except Exception:
        return ""


def _kart_cari_kodu(dialog) -> str:
    for fn in ("_secili_musteri", "_secili_tedarikci"):
        getter = getattr(dialog, fn, None)
        if not callable(getter):
            continue
        try:
            cari = getter()
        except Exception:
            cari = None
        if cari is not None:
            return (getattr(cari, "cari_kodu", None) or "").strip()
    g = getattr(dialog, "girdiler", None) or {}
    for anahtar in ("musteri_kodu", "tedarikci_kodu"):
        w = g.get(anahtar)
        try:
            if w is not None:
                return (w.get() or "").strip()
        except Exception:
            pass
    return ""


def _kart_para_birimi(dialog) -> str:
    try:
        from fatura_urun_aktar_service import fatura_pb_ve_kur

        pb, _kur = fatura_pb_ve_kur(dialog)
        return (pb or "TRY").upper()
    except Exception:
        w = getattr(dialog, "_doviz_para_birimi", None)
        try:
            return ((w.get() if w is not None else None) or "TRY").upper()
        except Exception:
            return "TRY"


def _norm_esasi(v: str) -> str:
    t = temiz(v).lower().replace("ı", "i")
    if "dahil" in t or t in ("d", "dahil", "1", "true", "evet"):
        return "dahil"
    if "haric" in t or "hariç" in temiz(v).lower() or t in ("h", "0", "false", "hayir", "hayır"):
        return "haric"
    return t or "haric"


def _parmak(dosya: str, satir_no: int, eslenen: dict[str, Any]) -> str:
    parcalar = [
        dosya,
        str(satir_no),
        temiz(eslenen.get("urun_kodu")),
        str(eslenen.get("miktar") or ""),
        temiz(eslenen.get("birim")),
        str(eslenen.get("birim_fiyat") or ""),
        str(eslenen.get("iskonto_1") or ""),
        temiz(eslenen.get("lot")),
    ]
    return "|".join(parcalar)


def _ust_karsilastir(
    parent,
    *,
    dosya_ozet: dict[str, str],
    kart_ozet: dict[str, str],
) -> bool:
    """Farklı üst bilgi varsa kullanıcıya göster. True = devam (kart korunur)."""
    farklar: list[str] = []
    etiket = {
        "cari_kodu": "Cari",
        "tarih": "Tarih",
        "depo": "Depo",
        "para_birimi": "Para birimi",
        "fiyat_esasi": "Fiyat esası",
    }
    for anahtar, baslik in etiket.items():
        d = temiz(dosya_ozet.get(anahtar))
        k = temiz(kart_ozet.get(anahtar))
        if not d:
            continue
        if anahtar == "fiyat_esasi":
            if _norm_esasi(d) != _norm_esasi(k or "Hariç"):
                farklar.append(f"{baslik}: dosya «{d}» — kart «{k or 'Hariç'}»")
        elif anahtar == "para_birimi":
            if d.upper() != (k or "TRY").upper():
                farklar.append(f"{baslik}: dosya «{d}» — kart «{k or 'TRY'}»")
        elif d != k:
            farklar.append(f"{baslik}: dosya «{d}» — kart «{k or '(boş)'}»")

    if not farklar:
        return True

    kritik_esasi = any(f.startswith("Fiyat esası") for f in farklar)
    kritik_pb = any(f.startswith("Para birimi") for f in farklar)
    metin = (
        "Dosyadaki üst bilgiler açık faturadan farklı:\n\n"
        + "\n".join(f"• {f}" for f in farklar)
        + "\n\nKartın cari, tarih, depo ve para birimi korunur; dosya üst bilgisi yazılmaz."
    )
    if kritik_esasi or kritik_pb:
        metin += (
            "\n\nFiyat esası veya para birimi farklıyken sessiz dönüşüm yapılmaz.\n"
            "Ham tutarları kartın mevcut anlamına göre almak istiyor musunuz?"
        )
        return bool(
            messagebox.askyesno("Üst bilgi farkı", metin, parent=parent, default="no")
        )
    metin += "\n\nKalem eklemeye devam edilsin mi?"
    return bool(messagebox.askyesno("Üst bilgi farkı", metin, parent=parent))


def acik_faturaya_excel_kalem_ekle(dialog, yol: str | Path, *, yon: str = "SATIS") -> dict[str, Any]:
    """Excel satırlarını açık fatura formuna ekler. Dönüş: özet sayaçlar."""
    path = Path(yol)
    yon_u = "ALIS" if yon.upper().startswith("A") else "SATIS"
    tip_kod = "alis_fatura_excel" if yon_u == "ALIS" else "satis_fatura_excel"
    tip = getir(tip_kod)

    if getattr(dialog, "_fatura_kilitli", False):
        messagebox.showwarning(
            "Kalem ekle",
            "Onaylı faturada kalem eklemek için önce Onay Kaldır yapın.",
            parent=dialog,
        )
        return {"eklenen": 0, "atlanan": 0, "hata": "kilitli"}

    okuma = ExcelReaderService.oku(path)
    if not okuma.satirlar:
        messagebox.showinfo("Kalem ekle", "Excel'de veri satırı bulunamadı.", parent=dialog)
        return {"eklenen": 0, "atlanan": 0}

    esleme = ColumnMappingService.otomatik_esle(tip, okuma.basliklar)
    if "urun_kodu" not in esleme.esleme.values() or "miktar" not in esleme.esleme.values():
        messagebox.showerror(
            "Kalem ekle",
            "Excel'de ürün kodu/barkod ve miktar sütunları bulunamadı.\n"
            "Şablon başlıklarını kontrol edin veya sütun eşleştirme ile aktarım sihirbazını kullanın.",
            parent=dialog,
        )
        return {"eklenen": 0, "atlanan": 0, "hata": "esleme"}

    hazir: list[tuple[int, dict[str, Any]]] = []
    hatalar: list[str] = []
    dosya_ust: dict[str, str] = {}

    for i, ham in enumerate(okuma.satirlar, start=2):
        eslenen = ColumnMappingService.satir_esle(ham, esleme.esleme)
        urun = temiz(eslenen.get("urun_kodu"))
        if not urun:
            continue
        try:
            miktar = (
                decimal_parse(eslenen["miktar"], alan="Miktar")
                if temiz(eslenen.get("miktar"))
                else None
            )
            bf_ham = eslenen.get("birim_fiyat")
            bf_metin = str(bf_ham).strip() if bf_ham is not None else ""
            if bf_metin == "":
                birim_fiyat = None
            elif bf_metin in ("0", "0,0", "0.0", "0,00"):
                birim_fiyat = Decimal("0")
            else:
                birim_fiyat = decimal_parse(bf_ham, alan="Birim Fiyat")
            kdv = (
                decimal_parse(eslenen["kdv_orani"], alan="KDV")
                if temiz(eslenen.get("kdv_orani"))
                else None
            )
            iskonto = (
                decimal_parse(eslenen["iskonto_1"], alan="İskonto")
                if temiz(eslenen.get("iskonto_1"))
                else Decimal("0")
            )
        except ValueError as exc:
            hatalar.append(f"Satır {i}: {exc}")
            continue
        if miktar is None or miktar <= 0:
            hatalar.append(f"Satır {i}: miktar pozitif olmalı.")
            continue
        if birim_fiyat is None:
            hatalar.append(f"Satır {i}: birim fiyat zorunlu (açık sıfır kabul).")
            continue

        kayit = {
            "urun_kodu": urun,
            "aciklama": temiz(eslenen.get("aciklama")),
            "miktar": miktar,
            "birim": temiz(eslenen.get("birim")) or "Adet",
            "birim_fiyat": birim_fiyat,
            "iskonto_1": iskonto,
            "kdv_orani": kdv,
            "lot": temiz(eslenen.get("lot")),
            "cari_kodu": temiz(eslenen.get("cari_kodu")),
            "tarih": temiz(eslenen.get("tarih")),
            "depo": temiz(eslenen.get("depo")),
            "para_birimi": temiz(eslenen.get("para_birimi")),
            "fiyat_esasi": temiz(eslenen.get("fiyat_esasi")),
        }
        for a in ("cari_kodu", "tarih", "depo", "para_birimi", "fiyat_esasi"):
            if kayit.get(a) and a not in dosya_ust:
                dosya_ust[a] = str(kayit[a])
        hazir.append((i, kayit))

    if not hazir:
        msg = "Eklenecek geçerli kalem satırı yok."
        if hatalar:
            msg += "\n\n" + "\n".join(hatalar[:12])
        messagebox.showwarning("Kalem ekle", msg, parent=dialog)
        return {"eklenen": 0, "atlanan": 0, "hatalar": hatalar}

    kart_ozet = {
        "cari_kodu": _kart_cari_kodu(dialog),
        "tarih": _kart_tarih(dialog),
        "depo": _kart_depo(dialog),
        "para_birimi": _kart_para_birimi(dialog),
        "fiyat_esasi": "Hariç",
    }
    if not _ust_karsilastir(dialog, dosya_ozet=dosya_ust, kart_ozet=kart_ozet):
        return {"eklenen": 0, "atlanan": 0, "iptal": True}

    izler = getattr(dialog, "_dosyadan_aktar_parmak", None)
    if not isinstance(izler, set):
        izler = set()
        dialog._dosyadan_aktar_parmak = izler

    eklenen = 0
    atlanan = 0
    dialog._satir_toplu_ekleme = True
    try:
        for satir_no, kayit in hazir:
            p = _parmak(path.name, satir_no, kayit)
            if p in izler:
                atlanan += 1
                continue
            stok = stok_kartini_coz(stok_kodu=kayit["urun_kodu"])
            barkod_okunan = ""
            if stok is None:
                try:
                    from database.stok_service import StokService

                    br = StokService.barkod_ile_bul(kayit["urun_kodu"])
                except Exception:
                    br = None
                if br:
                    barkod_okunan = kayit["urun_kodu"]
                    stok = stok_kartini_coz(product_id=int(br["stok_id"]))
                    if stok is not None and not temiz(kayit.get("birim")) and br.get("birim"):
                        kayit["birim"] = br["birim"]
            if stok is None:
                hatalar.append(
                    f"Satır {satir_no}: stok bulunamadı ({kayit['urun_kodu']}). "
                    "Ad benzerliği otomatik bağlanmaz."
                )
                continue
            try:
                sablon = stoktan_satir_sablonu(
                    dialog,
                    urun_kodu=getattr(stok, "stok_kodu", None) or kayit["urun_kodu"],
                    urun_adi=kayit.get("aciklama") or "",
                    birim=kayit.get("birim"),
                    barkod=barkod_okunan,
                    miktar=kayit["miktar"],
                    birim_fiyat=kayit["birim_fiyat"],
                    kdv_orani=kayit.get("kdv_orani"),
                    product_id=int(stok.id),
                )
            except Exception as exc:  # noqa: BLE001
                hatalar.append(f"Satır {satir_no}: {exc}")
                continue
            # Excel fiyatı / iskonto / lot — stok kartı fiyatını güncellemez
            fiyat_metin = f"{kayit['birim_fiyat']:f}"
            sablon["birim_satis_fiyati"] = fiyat_metin
            sablon["birim_alis_fiyati"] = fiyat_metin
            sablon["birim_fiyat"] = fiyat_metin
            sablon["iskonto_orani"] = str(kayit.get("iskonto_1") or 0)
            if kayit.get("lot"):
                sablon["lot_no"] = kayit["lot"]
            if kayit.get("aciklama"):
                sablon["urun_adi"] = kayit["aciklama"]
            # Kart deposu korunur
            sablon["depo"] = _kart_depo(dialog) or sablon.get("depo") or ""
            try:
                idx = urunu_faturaya_aktar(
                    dialog,
                    sablon,
                    miktar_ekle=kayit["miktar"],
                    birlestir=False,
                )
            except ValueError as exc:
                hatalar.append(f"Satır {satir_no}: {exc}")
                continue
            if idx is not None and idx >= 0:
                izler.add(p)
                eklenen += 1
            else:
                atlanan += 1
    finally:
        dialog._satir_toplu_ekleme = False

    yenile = getattr(dialog, "_satir_toplu_yenile", None) or getattr(
        dialog, "_satir_listesini_yenile", None
    )
    if callable(yenile):
        try:
            yenile()
        except Exception:
            pass

    ozet = f"{eklenen} kalem eklendi."
    if atlanan:
        ozet += f" {atlanan} satır atlandı (tekrar veya birleşmeme)."
    if hatalar:
        ozet += "\n\nUyarılar:\n" + "\n".join(hatalar[:15])
        if len(hatalar) > 15:
            ozet += f"\n… +{len(hatalar) - 15} uyarı daha"
    messagebox.showinfo("Kalem ekle", ozet, parent=dialog)
    return {"eklenen": eklenen, "atlanan": atlanan, "hatalar": hatalar}
