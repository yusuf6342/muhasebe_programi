"""Belge önizleme / yazdırma — kasa makbuz, gider fişi ve diğer finans evrakları."""

from __future__ import annotations

import html
import tempfile
import tkinter as tk
import webbrowser
from pathlib import Path
from tkinter import messagebox, ttk


def _para(tutar) -> str:
    return f"{float(tutar or 0):,.2f} TL".replace(",", "X").replace(".", ",").replace("X", ".")


def _tarih(t) -> str:
    return t.strftime("%d.%m.%Y") if t else ""


def belge_html(baslik: str, alanlar: list[tuple[str, str]], dipnot: str | None = None) -> str:
    satirlar = "".join(
        f"<tr><th>{html.escape(etiket)}</th><td>{html.escape(str(deger or '—'))}</td></tr>"
        for etiket, deger in alanlar
    )
    dip = f"<p class='dip'>{html.escape(dipnot)}</p>" if dipnot else ""
    return f"""<!DOCTYPE html>
<html lang="tr">
<head>
<meta charset="utf-8"/>
<title>{html.escape(baslik)}</title>
<style>
  body {{ font-family: 'Segoe UI', Tahoma, sans-serif; margin: 24px; color: #111; }}
  .toolbar {{ margin-bottom: 16px; }}
  .toolbar button {{ padding: 6px 14px; font-size: 14px; cursor: pointer; }}
  h1 {{ font-size: 20px; margin: 0 0 16px; }}
  table {{ border-collapse: collapse; width: 100%; max-width: 640px; }}
  th, td {{ border-bottom: 1px solid #ccc; padding: 8px 10px; text-align: left; vertical-align: top; }}
  th {{ width: 38%; color: #444; font-weight: 600; }}
  .dip {{ margin-top: 24px; color: #555; font-size: 12px; }}
  @media print {{
    .toolbar {{ display: none; }}
    body {{ margin: 12mm; }}
  }}
</style>
</head>
<body>
  <div class="toolbar">
    <button type="button" onclick="window.print()">Yazdır</button>
  </div>
  <h1>{html.escape(baslik)}</h1>
  <table>{satirlar}</table>
  {dip}
</body>
</html>
"""


def belgeyi_yazdir(baslik: str, alanlar: list[tuple[str, str]], parent=None, dipnot: str | None = None):
    """HTML önizlemeyi tarayıcıda açar (window.print)."""
    klasor = Path(tempfile.gettempdir()) / "muhasebe_belge"
    klasor.mkdir(exist_ok=True)
    guvenli = "".join(c if c.isalnum() or c in "-_" else "_" for c in baslik)[:40] or "belge"
    dosya = klasor / f"{guvenli}.html"
    dosya.write_text(belge_html(baslik, alanlar, dipnot=dipnot), encoding="utf-8")
    webbrowser.open(dosya.as_uri())
    if parent is not None:
        messagebox.showinfo(
            "Yazdırma",
            "Belge tarayıcıda açıldı.\nYazdır iletişim kutusu için Yazdır düğmesine basın veya Ctrl+P kullanın.",
            parent=parent,
        )


class BelgeOnizlemeDialog(tk.Toplevel):
    """Salt okunur belge kartı + Yazdır."""

    def __init__(
        self,
        parent,
        baslik: str,
        alanlar: list[tuple[str, str]],
        *,
        dipnot: str | None = None,
        geometry: str = "520x420",
    ):
        super().__init__(parent)
        self.baslik = baslik
        self.alanlar = list(alanlar)
        self.dipnot = dipnot
        self.title(baslik)
        self.geometry(geometry)
        self.minsize(460, 360)
        self.transient(parent)
        self.grab_set()

        govde = ttk.Frame(self, padding=14)
        govde.pack(fill="both", expand=True)
        ttk.Label(govde, text=baslik, style="Baslik.TLabel").pack(anchor="w", pady=(0, 10))

        tablo = ttk.Frame(govde)
        tablo.pack(fill="both", expand=True)
        tablo.columnconfigure(1, weight=1)
        for i, (etiket, deger) in enumerate(self.alanlar):
            ttk.Label(tablo, text=f"{etiket}:", foreground="#444").grid(
                row=i, column=0, sticky="nw", padx=(0, 10), pady=4
            )
            ttk.Label(tablo, text=str(deger or "—"), wraplength=340).grid(
                row=i, column=1, sticky="nw", pady=4
            )

        if dipnot:
            ttk.Label(govde, text=dipnot, foreground="#666", wraplength=460).pack(
                anchor="w", pady=(12, 0)
            )

        alt = ttk.Frame(self, padding=(14, 8))
        alt.pack(fill="x", side="bottom")
        ttk.Button(alt, text="Kapat", command=self.destroy).pack(side="right")
        ttk.Button(alt, text="Yazdır", width=12, command=self.yazdir).pack(side="right", padx=(0, 8))

    def yazdir(self):
        belgeyi_yazdir(self.baslik, self.alanlar, parent=self, dipnot=self.dipnot)


def kasa_makbuz_onizle(parent, belge_no: str) -> bool:
    from database.finans_service import FinansService

    makbuz = FinansService.kasa_makbuz_belge_no_ile(belge_no)
    if not makbuz:
        return False
    tahsilat = (makbuz.makbuz_turu or "").upper() == "TAHSILAT"
    baslik = "Tahsilat Makbuzu" if tahsilat else "Ödeme Makbuzu"
    cari = getattr(makbuz, "cari", None)
    cari_yazi = f"{cari.cari_kodu} — {cari.unvan}" if cari else "—"
    kasa = makbuz.finans_hesap.hesap_adi if makbuz.finans_hesap else "—"
    alanlar = [
        ("Belge no", makbuz.belge_no),
        ("Tür", "Tahsilat" if tahsilat else "Ödeme"),
        ("Tarih", _tarih(makbuz.tarih)),
        ("Cari", cari_yazi),
        ("Kasa", kasa),
        ("Tutar", _para(makbuz.tutar)),
        ("Makbuz no", makbuz.makbuz_no or "—"),
        ("Durum", makbuz.durum or "—"),
        ("Açıklama", makbuz.aciklama or "—"),
    ]
    dialog = BelgeOnizlemeDialog(parent, baslik, alanlar)
    if dialog.winfo_exists():
        parent.wait_window(dialog)
    return True


def gider_fisi_onizle(parent, belge_no: str) -> bool:
    from database.finans_service import FinansService
    from database.models.hizmet import gider_sinifi_etiket

    fis = FinansService.gider_fisi_belge_no_ile(belge_no)
    if not fis:
        return False
    hiz = getattr(fis, "hizmet", None)
    if hiz:
        hizmet_yazi = f"{hiz.hizmet_kodu} — {hiz.hizmet_adi}"
        sinif = gider_sinifi_etiket(hiz.gider_sinifi)
        if sinif:
            hizmet_yazi = f"{hizmet_yazi} ({sinif})"
    else:
        hizmet_yazi = "—"
    hesap = fis.finans_hesap
    if hesap:
        if (hesap.hesap_turu or "").upper() == "KASA":
            hesap_yazi = f"Kasa — {hesap.hesap_adi}"
        else:
            hesap_yazi = hesap.hesap_adi
    else:
        hesap_yazi = "—"
    alanlar = [
        ("Belge no", fis.belge_no),
        ("Tarih", _tarih(fis.tarih)),
        ("Ödeme hesabı", hesap_yazi),
        ("Gider hizmeti", hizmet_yazi),
        ("Tutar", _para(fis.tutar)),
        ("Durum", fis.durum or "—"),
        ("Bağlı belge", fis.bagli_belge_no or "—"),
        ("Açıklama", fis.aciklama or "—"),
    ]
    dialog = BelgeOnizlemeDialog(parent, "Gider Fişi", alanlar)
    if dialog.winfo_exists():
        parent.wait_window(dialog)
    return True


def cari_islem_onizle(parent, belge_no: str, tur: str = "") -> bool:
    from database.cari_service import CariService

    kayitlar = CariService.islemler_belge_no_ile(belge_no)
    if not kayitlar:
        return False
    if belge_no.startswith("VRM-") or (tur or "").casefold() in ("cari virman", "virman"):
        kaynak = next((i for i in kayitlar if float(i.alacak or 0) > 0), kayitlar[0])
        hedef = next((i for i in kayitlar if float(i.borc or 0) > 0), None)
        kaynak_cari = getattr(kaynak, "cari", None)
        hedef_cari = getattr(hedef, "cari", None) if hedef else None
        alanlar = [
            ("Belge no", belge_no),
            ("Tür", "Cari Virman"),
            ("Tarih", _tarih(kaynak.tarih)),
            (
                "Kaynak cari",
                f"{kaynak_cari.cari_kodu} — {kaynak_cari.unvan}" if kaynak_cari else "—",
            ),
            (
                "Hedef cari",
                f"{hedef_cari.cari_kodu} — {hedef_cari.unvan}" if hedef_cari else "—",
            ),
            ("Tutar", _para(kaynak.alacak or kaynak.borc)),
            ("Açıklama", kaynak.aciklama or "—"),
        ]
        baslik = "Cari Virman"
    else:
        islem = kayitlar[0]
        cari = getattr(islem, "cari", None)
        tutar = islem.alacak if float(islem.alacak or 0) else islem.borc
        alanlar = [
            ("Belge no", islem.belge_no),
            ("Tür", islem.islem_turu or tur or "—"),
            ("Tarih", _tarih(islem.tarih)),
            ("Cari", f"{cari.cari_kodu} — {cari.unvan}" if cari else "—"),
            ("Hesap", islem.hesap_adi or "—"),
            ("Tutar", _para(tutar)),
            ("Borç", _para(islem.borc) if float(islem.borc or 0) else "—"),
            ("Alacak", _para(islem.alacak) if float(islem.alacak or 0) else "—"),
            ("Açıklama", islem.aciklama or "—"),
        ]
        baslik = islem.islem_turu or "Cari İşlem"
    dialog = BelgeOnizlemeDialog(parent, baslik, alanlar)
    if dialog.winfo_exists():
        parent.wait_window(dialog)
    return True


def finans_belge_ac(parent, tur: str, belge_no: str) -> bool:
    """
    Finans / kasa / banka / cari fişlerini açar.
    True = işlendi (açıldı). False = bu belge türü burada karşılanmıyor.
    """
    belge_no = (belge_no or "").strip()
    tur = (tur or "").strip()
    if not belge_no:
        return False

    if belge_no.startswith("KKC-") or tur == "KK Çekimi":
        from app import KkCekimiDialog

        dialog = KkCekimiDialog(parent, belge_no=belge_no)
        if dialog.winfo_exists():
            parent.wait_window(dialog)
        return True

    if belge_no.startswith("AHV-"):
        from finans_ui import HavaleFisDialog

        dialog = HavaleFisDialog(parent, tur="ahv", belge_no=belge_no)
        if dialog.winfo_exists():
            parent.wait_window(dialog)
        return True

    if belge_no.startswith("GHV-"):
        from finans_ui import HavaleFisDialog

        dialog = HavaleFisDialog(parent, tur="ghv", belge_no=belge_no)
        if dialog.winfo_exists():
            parent.wait_window(dialog)
        return True

    if belge_no.startswith("POS-"):
        from finans_ui import BankaIslemPosTahsilatDialog

        dialog = BankaIslemPosTahsilatDialog(parent, belge_no=belge_no)
        if dialog.winfo_exists():
            parent.wait_window(dialog)
        return True

    if belge_no.startswith("KKO-"):
        from finans_ui import BankaIslemKkOdemeDialog

        dialog = BankaIslemKkOdemeDialog(parent, belge_no=belge_no)
        if dialog.winfo_exists():
            parent.wait_window(dialog)
        return True

    if belge_no.startswith("KBY-"):
        from finans_ui import KasadanBankayaYatirDialog

        dialog = KasadanBankayaYatirDialog(parent, belge_no=belge_no)
        if dialog.winfo_exists():
            parent.wait_window(dialog)
        return True

    if belge_no.startswith("BNC-"):
        from finans_ui import BankadanCekilenDialog

        dialog = BankadanCekilenDialog(parent, belge_no=belge_no)
        if dialog.winfo_exists():
            parent.wait_window(dialog)
        return True

    if belge_no.startswith("BVR-"):
        from finans_ui import BankalarArasiVirmanDialog

        dialog = BankalarArasiVirmanDialog(parent, belge_no=belge_no)
        if dialog.winfo_exists():
            parent.wait_window(dialog)
        return True

    if belge_no.startswith(("TMK-", "OMK-")) or tur.upper() in (
        "TAHSİLAT MAKBUZU",
        "ÖDEME MAKBUZU",
        "TAHSILAT MAKBUZU",
        "ODEME MAKBUZU",
    ):
        if kasa_makbuz_onizle(parent, belge_no):
            return True
        messagebox.showinfo(
            "Belge",
            f"{belge_no} makbuzu bulunamadı.",
            parent=parent,
        )
        return True

    if belge_no.startswith("GDF-") or tur.upper() in ("GİDER FİŞİ", "GIDER FISI"):
        if gider_fisi_onizle(parent, belge_no):
            return True
        messagebox.showinfo(
            "Belge",
            f"{belge_no} gider fişi bulunamadı.",
            parent=parent,
        )
        return True

    if belge_no.startswith(("THS-", "ODM-", "VRM-")) or tur in (
        "Tahsilat",
        "Ödeme",
        "Cari Virman",
        "CARİ TAHSİLAT",
        "CARİ ÖDEME",
    ):
        if cari_islem_onizle(parent, belge_no, tur=tur):
            return True
        messagebox.showinfo(
            "Belge",
            f"{belge_no} ({tur}) için kayıt bulunamadı.",
            parent=parent,
        )
        return True

    return False


def hareket_belgeyi_ac(parent, tur: str, belge_no: str) -> bool:
    """Cari/kasa hareket satırından belge aç — finans + fatura/iade."""
    belge_no = (belge_no or "").strip()
    tur = (tur or "").strip()
    if not belge_no:
        return False

    if finans_belge_ac(parent, tur, belge_no):
        return True

    from database.database import get_session
    from sqlalchemy import select

    def _id_bul(model, alan_adi, deger):
        with get_session() as session:
            kayit = session.scalar(select(model).where(getattr(model, alan_adi) == deger))
            return kayit.id if kayit else None

    if belge_no.startswith("IAD-") or tur == "Satış İadesi":
        from app import SatisIadeFaturasiDialog
        from database.models.satis_iade_faturasi import SatisIadeFaturasi
        from database.satis_iade_faturasi_service import SatisIadeFaturasiService

        iade_id = _id_bul(SatisIadeFaturasi, "iade_no", belge_no)
        if not iade_id:
            return False
        iade = SatisIadeFaturasiService.getir(iade_id)
        if not iade:
            raise ValueError("Satış iade faturası bulunamadı.")
        dialog = SatisIadeFaturasiDialog(parent, iade=iade)
        parent.wait_window(dialog)
        return True

    if belge_no.startswith("AIAD-") or tur == "Alış İadesi":
        from alis_ui import AlisIadeFaturasiDialog
        from database.alis_iade_faturasi_service import AlisIadeFaturasiService
        from database.models.alis_iade_faturasi import AlisIadeFaturasi

        iade_id = _id_bul(AlisIadeFaturasi, "iade_no", belge_no)
        if not iade_id:
            return False
        iade = AlisIadeFaturasiService.getir(iade_id)
        if not iade:
            raise ValueError("Alış iade faturası bulunamadı.")
        dialog = AlisIadeFaturasiDialog(parent, iade=iade)
        parent.wait_window(dialog)
        return True

    if tur == "Alış" or belge_no.startswith(("AFAT-", "ARAY")):
        from alis_ui import AlisFaturasiDialog
        from app import CariDialog
        from database.alis_faturasi_service import AlisFaturasiService
        from database.models.alis_faturasi import AlisFaturasi

        fatura_id = _id_bul(AlisFaturasi, "fatura_no", belge_no)
        if not fatura_id:
            return False
        fatura = AlisFaturasiService.getir(fatura_id)
        if not fatura:
            raise ValueError("Alış faturası bulunamadı.")
        dialog = AlisFaturasiDialog(
            parent,
            fatura=fatura,
            cari_ac=lambda c: CariDialog(parent, c, cari_turu="Tedarikçi"),
        )
        parent.wait_window(dialog)
        return True

    if tur == "Satış" or belge_no.startswith("SRAY"):
        from app import CariDialog, SatisFaturasiDialog
        from database.models.satis_faturasi import SatisFaturasi
        from database.satis_faturasi_service import SatisFaturasiService

        fatura_id = _id_bul(SatisFaturasi, "fatura_no", belge_no)
        if not fatura_id:
            return False
        fatura = SatisFaturasiService.getir(fatura_id)
        if not fatura:
            raise ValueError("Satış faturası bulunamadı.")
        dialog = SatisFaturasiDialog(
            parent,
            fatura=fatura,
            cari_ac=lambda cari: CariDialog(parent, cari),
        )
        parent.wait_window(dialog)
        return True

    return False
