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
    """Salt okunur belge kartı + Yazdır (+ isteğe bağlı Düzenle/Sil)."""

    def __init__(
        self,
        parent,
        baslik: str,
        alanlar: list[tuple[str, str]],
        *,
        dipnot: str | None = None,
        geometry: str = "520x420",
        muhasebe: tuple[str, int | None] | None = None,
        duzenle_komut=None,
        sil_komut=None,
    ):
        super().__init__(parent)
        self.baslik = baslik
        self.alanlar = list(alanlar)
        self.dipnot = dipnot
        self._deger_etiketleri: list[ttk.Label] = []
        self.title(baslik)
        if muhasebe and muhasebe[1]:
            from muhasebe_durum_ui import baslik_guncelle

            baslik_guncelle(self, baslik, *muhasebe)
        self.geometry(geometry)
        self.minsize(460, 360)
        self.transient(parent)
        self.grab_set()
        from ui_pencere import pencere_os_krom_ac

        pencere_os_krom_ac(self)

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
            deger_lbl = ttk.Label(tablo, text=str(deger or "—"), wraplength=340)
            deger_lbl.grid(row=i, column=1, sticky="nw", pady=4)
            self._deger_etiketleri.append(deger_lbl)

        if dipnot:
            ttk.Label(govde, text=dipnot, foreground="#666", wraplength=460).pack(
                anchor="w", pady=(12, 0)
            )

        alt = ttk.Frame(self, padding=(14, 8))
        alt.pack(fill="x", side="bottom")
        ttk.Button(alt, text="Kapat", command=self.destroy).pack(side="right")
        ttk.Button(alt, text="Yazdır", width=12, command=self.yazdir).pack(side="right", padx=(0, 8))
        if muhasebe and muhasebe[1]:
            from muhasebe_durum_ui import fis_dugmesi

            fis_dugmesi(alt, muhasebe[0], lambda: muhasebe[1]).pack(side="right", padx=(0, 8))
        if sil_komut:
            ttk.Button(alt, text="Sil", width=10, command=sil_komut).pack(side="right", padx=(0, 8))
        if duzenle_komut:
            ttk.Button(alt, text="Düzenle", width=10, command=duzenle_komut).pack(
                side="right", padx=(0, 8)
            )

    def alanlari_yenile(self, alanlar: list[tuple[str, str]]):
        """Detay alanlarını yerinde günceller (düzenleme sonrası)."""
        self.alanlar = list(alanlar)
        for i, (_etiket, deger) in enumerate(self.alanlar):
            if i < len(self._deger_etiketleri):
                self._deger_etiketleri[i].configure(text=str(deger or "—"))

    def yazdir(self):
        belgeyi_yazdir(self.baslik, self.alanlar, parent=self, dipnot=self.dipnot)


def kasa_makbuz_onizle(parent, belge_no: str) -> bool:
    """Makbuz çıktısı / önizleme (yeni mali hareket üretmez)."""
    from database.finans_service import FinansService

    makbuz = FinansService.kasa_makbuz_belge_no_ile(belge_no)
    if not makbuz:
        return False
    from makbuz_cikti_ui import makbuz_ciktisi_ac

    makbuz_ciktisi_ac(parent, [int(makbuz.id)], bekle=True)
    return True


def kasa_makbuz_duzenle(parent, belge_no: str) -> bool:
    """Tahsilat/ödeme makbuzunu belge kimliğiyle düzenleme ekranında açar."""
    from database.finans_service import FinansService

    makbuz = FinansService.kasa_makbuz_belge_no_ile(belge_no)
    if not makbuz:
        return False
    from kasa_makbuz_ui import KasaMakbuzDialog

    tur = (makbuz.makbuz_turu or "TAHSILAT").upper()
    dialog = KasaMakbuzDialog(parent, makbuz_turu=tur, makbuz_id=int(makbuz.id))
    try:
        dialog.lift()
        dialog.focus_force()
    except Exception:
        pass
    parent.wait_window(dialog)
    return True


def cari_virman_onizle(parent, belge_no: str) -> bool:
    """CVR-… makbuzu veya bağlı -T / -O cari evrakı: cari virman makbuzu çıktısı."""
    from database.cari_virman_makbuz_service import CariVirmanMakbuzService

    kayit = CariVirmanMakbuzService.belge_no_ile(belge_no)
    if not kayit:
        return False
    from makbuz_cikti import virman_kimligi
    from makbuz_cikti_ui import makbuz_ciktisi_ac

    makbuz_ciktisi_ac(parent, [virman_kimligi(kayit.id)], bekle=True)
    return True


def gider_fisi_onizle(parent, belge_no: str) -> bool:
    from database.finans_service import FinansService
    from database.kredi_gider_fisi_service import KrediGiderFisiService
    from database.models.hizmet import gider_sinifi_etiket

    belge_no = (belge_no or "").strip()
    if not belge_no:
        return False

    # Kredi / nakit avans: konsolide özet (faiz+masraf, hesap durumu)
    ozet = None
    try:
        ozet = KrediGiderFisiService.ozet(gider_belge_no=belge_no)
        if ozet is None:
            ozet = KrediGiderFisiService.ozet(odeme_belge_no=belge_no)
    except Exception:
        ozet = None
    if ozet and ozet.get("satirlar"):
        taksit_yazi = "—"
        if ozet.get("taksit_no"):
            taksit_yazi = f"{ozet['taksit_no']}/{ozet.get('taksit_sayisi') or '?'}"
        alanlar = [
            ("Firma", ozet.get("firma") or "—"),
            ("Banka", ozet.get("banka") or "—"),
            ("Kredi", ozet.get("kredi_adi") or "—"),
            ("Kredi belge", ozet.get("kredi_belge") or "—"),
            ("Taksit", taksit_yazi),
            ("Ödeme belgesi", ozet.get("odeme_belge_no") or "—"),
            ("Ödeme tarihi", _tarih(ozet.get("odeme_tarihi"))),
            ("Ödeme hesabı", ozet.get("odeme_hesabi") or "—"),
            ("Anapara (gider değil)", _para(ozet.get("anapara"))),
            ("Faiz gideri", _para(ozet.get("faiz"))),
            ("Masraf gideri", _para(ozet.get("masraf"))),
            ("Toplam gider", _para(ozet.get("toplam_gider"))),
            ("Muhasebe", ozet.get("muhasebe_durum_etiket") or "—"),
        ]
        for s in ozet["satirlar"]:
            hesap = s.get("muhasebe_hesap_kodu") or "—"
            if s.get("muhasebe_hesap_adi"):
                hesap = f"{hesap} — {s['muhasebe_hesap_adi']}"
            alanlar.append(
                (
                    f"{s.get('gider_turu') or 'Gider'} ({s.get('belge_no')})",
                    f"{_para(s.get('tutar'))} | {hesap} | {s.get('muhasebe_durum_etiket') or '—'}",
                )
            )
        ilk_id = ozet["satirlar"][0].get("id")
        dialog = BelgeOnizlemeDialog(
            parent,
            "Kredi / Finansman Gider Fişi",
            alanlar,
            muhasebe=("gider_fisi", ilk_id) if ilk_id else None,
        )
        if dialog.winfo_exists():
            parent.wait_window(dialog)
        return True

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
    mh_kod = getattr(fis, "muhasebe_hesap_kodu", None) or "—"
    mh_durum = KrediGiderFisiService.durum_etiket(getattr(fis, "muhasebe_durum", None))
    alanlar = [
        ("Belge no", fis.belge_no),
        ("Tarih", _tarih(fis.tarih)),
        ("Ödeme hesabı", hesap_yazi),
        ("Gider hizmeti", hizmet_yazi),
        ("Gider türü", fis.gider_turu or "—"),
        ("Tutar", _para(fis.tutar)),
        ("Durum", fis.durum or "—"),
        ("Muhasebe hesabı", mh_kod),
        ("Muhasebe durumu", mh_durum),
        ("Bağlı belge", fis.bagli_belge_no or "—"),
        ("Açıklama", fis.aciklama or "—"),
    ]
    dialog = BelgeOnizlemeDialog(parent, "Gider Fişi", alanlar, muhasebe=("gider_fisi", fis.id))
    if dialog.winfo_exists():
        parent.wait_window(dialog)
    return True


def _cari_virman_alanlari(belge_no: str) -> list[tuple[str, str]]:
    from database.cari_service import CariService

    kayit = CariService.virman_getir(belge_no)
    return [
        ("Belge no", belge_no),
        ("Tür", "Cari Virman"),
        ("Tarih", _tarih(kayit["tarih"])),
        ("Kaynak cari", f"{kayit['kaynak_kodu']} — {kayit['kaynak_unvan']}"),
        ("Hedef cari", f"{kayit['hedef_kodu']} — {kayit['hedef_unvan']}"),
        ("Tutar", _para(kayit["tutar"])),
        ("Açıklama", kayit["aciklama"] or "—"),
    ]


def _virman_listesi_yenile(parent) -> None:
    """Virman listesi / giriş paneli / cari ekranlarını mümkünse yenile."""
    kok = parent
    try:
        kok = parent.winfo_toplevel()
    except tk.TclError:
        pass
    if hasattr(kok, "virman_listesini_yenile"):
        try:
            kok.virman_listesini_yenile()
        except Exception:
            pass
    if hasattr(kok, "cari_hareketlerini_yenile"):
        try:
            kok.cari_hareketlerini_yenile()
        except Exception:
            pass
    if hasattr(kok, "ekstre_yenile"):
        try:
            kok.ekstre_yenile()
        except Exception:
            pass


def _cari_ve_pos_yenile(parent) -> None:
    """Tahsilat Sil sonrası cari kart ve POS listesini yenile."""
    _virman_listesi_yenile(parent)
    adaylar = [parent]
    try:
        adaylar.append(parent.winfo_toplevel())
    except tk.TclError:
        pass
    try:
        master = getattr(parent, "master", None)
        if master is not None:
            adaylar.append(master)
            adaylar.append(master.winfo_toplevel())
    except tk.TclError:
        pass
    gorulen = set()
    for w in adaylar:
        if w is None:
            continue
        wid = id(w)
        if wid in gorulen:
            continue
        gorulen.add(wid)
        for ad in (
            "yenile",
            "hareketleri_yenile",
            "_hareketleri_yukle",
            "listeyi_yenile",
            "_pos_islemleri_yenile",
        ):
            fn = getattr(w, ad, None)
            if callable(fn):
                try:
                    fn()
                except Exception:
                    pass


def cari_islem_onizle(parent, belge_no: str, tur: str = "") -> bool:
    from database.cari_service import CariService

    kayitlar = CariService.islemler_belge_no_ile(belge_no)
    if not kayitlar:
        return False
    duzenle_komut = None
    sil_komut = None
    dialog_ref: dict = {"dlg": None}
    if belge_no.startswith("VRM-") or (tur or "").casefold() in ("cari virman", "virman"):
        try:
            alanlar = _cari_virman_alanlari(belge_no)
        except ValueError:
            return False
        baslik = "Cari Virman"

        def duzenle_komut():
            from app import CariVirmanDialog

            dlg = dialog_ref["dlg"]
            if dlg is None or not dlg.winfo_exists():
                return
            form = CariVirmanDialog(dlg, belge_no=belge_no)
            if not form.winfo_exists():
                return
            dlg.wait_window(form)
            if not form.result:
                return
            try:
                dlg.alanlari_yenile(_cari_virman_alanlari(belge_no))
            except ValueError as hata:
                messagebox.showerror("Virman", str(hata), parent=dlg)
                dlg.destroy()
                return
            _virman_listesi_yenile(parent)

        def sil_komut():
            dlg = dialog_ref["dlg"]
            if dlg is None or not dlg.winfo_exists():
                return
            try:
                kayit = CariService.virman_getir(belge_no)
            except ValueError as hata:
                messagebox.showerror("Silinemedi", str(hata), parent=dlg)
                return
            kaynak = f"{kayit['kaynak_kodu']} — {kayit['kaynak_unvan']}"
            hedef = f"{kayit['hedef_kodu']} — {kayit['hedef_unvan']}"
            if not messagebox.askyesno(
                "Virman sil",
                (
                    f"Belge: {belge_no}\n"
                    f"Kaynak cari: {kaynak}\n"
                    f"Hedef cari: {hedef}\n"
                    f"Tutar: {_para(kayit['tutar'])}\n\n"
                    "Bu virman fişi silinsin mi?\n"
                    "Kaynak ve hedef bakiyeler geri alınır."
                ),
                parent=dlg,
            ):
                return
            try:
                CariService.virman_iptal(belge_no)
            except ValueError as hata:
                messagebox.showerror("Silinemedi", str(hata), parent=dlg)
                return
            _virman_listesi_yenile(parent)
            dlg.destroy()
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
        tur_u = (islem.islem_turu or tur or "").strip()
        if tur_u in ("Tahsilat", "Ödeme", "CARİ TAHSİLAT", "CARİ ÖDEME"):
            from database.access import yetki_var
            from database.finans_service import FinansService

            if yetki_var("finans_duzenleme", "iptal"):
                cari_id = int(islem.cari_id) if islem.cari_id else None

                def sil_komut():
                    dlg = dialog_ref["dlg"]
                    if dlg is None or not dlg.winfo_exists():
                        return
                    try:
                        hedef = FinansService.tahsilat_detay_hedef_coz(
                            belge_no, cari_id=cari_id
                        )
                    except ValueError as hata:
                        messagebox.showerror("Silinemedi", str(hata), parent=dlg)
                        return
                    no_goster = hedef.get("makbuz_no") or hedef["belge_no"]
                    if not messagebox.askyesno(
                        "Tahsilatı Sil",
                        (
                            f"Belge no: {hedef['belge_no']}\n"
                            f"Makbuz / kayıt: {no_goster}\n"
                            f"Cari: {hedef['cari']}\n"
                            f"Tarih: {_tarih(hedef['tarih'])}\n"
                            f"Tutar: {_para(hedef['tutar'])}\n"
                            f"Bağlı hesap: {hedef['hesap']}\n"
                            f"Kayıt kimliği: {hedef['tur']} #{hedef['id']}\n\n"
                            "Bu tahsilat aktif cari hareketlerden çıkarılsın mı?\n"
                            "Fatura kapamaları çözülür; aktarılmamış POS net/komisyon etkisi kaldırılır.\n"
                            "Aktarılmış veya muhasebeleştirilmiş kayıtta ters kayıt uygulanır."
                        ),
                        parent=dlg,
                    ):
                        return
                    try:
                        kwargs = {"neden": f"Tahsilat silindi {hedef['belge_no']}"}
                        if hedef["tur"] == "makbuz":
                            kwargs["makbuz_id"] = hedef["id"]
                        elif hedef["tur"] == "pos_valor":
                            kwargs["pos_valor_id"] = hedef["id"]
                        else:
                            kwargs["cari_islem_id"] = hedef["id"]
                        FinansService.tahsilat_detay_iptal(**kwargs)
                    except (ValueError, PermissionError) as hata:
                        messagebox.showerror("Silinemedi", str(hata), parent=dlg)
                        return
                    _cari_ve_pos_yenile(parent)
                    dlg.destroy()
    muhasebe = None
    try:
        from muhasebe_durum_ui import belge_no_kaynagi, cari_islem_kaynagi

        if baslik == "Cari Virman":
            muhasebe = ("cari_virman", belge_no_kaynagi("cari_virman", belge_no))
        else:
            muhasebe = cari_islem_kaynagi(kayitlar[0].id)
    except Exception:
        muhasebe = None
    dialog = BelgeOnizlemeDialog(
        parent,
        baslik,
        alanlar,
        muhasebe=muhasebe,
        duzenle_komut=duzenle_komut,
        sil_komut=sil_komut,
    )
    dialog_ref["dlg"] = dialog
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

    if belge_no.startswith("PVA-") or (tur or "").upper().startswith("POS VALÖR"):
        from finans_ui import PosAktarimBelgeDialog

        dialog = PosAktarimBelgeDialog(parent, belge_no)
        if dialog.winfo_exists():
            parent.wait_window(dialog)
        return True

    if belge_no.startswith("KKO-"):
        from finans_ui import BankaIslemKkOdemeDialog

        dialog = BankaIslemKkOdemeDialog(parent, belge_no=belge_no)
        if dialog.winfo_exists():
            parent.wait_window(dialog)
        return True

    # Nakit avans: NAV = ana evrak, NAT = karta işlenen taksit hareketi → aynı kaynak form
    if belge_no.startswith(("NAV-", "NAT-")) or (tur or "").upper().startswith("KK NAKİT AVANS"):
        from database.nakit_avans_service import NakitAvansService
        from nakit_avans_ui import NakitAvansDialog

        av = NakitAvansService.belgeden_getir(belge_no)
        if not av:
            messagebox.showinfo("Belge", f"{belge_no} nakit avans kaydı bulunamadı.", parent=parent)
            return True
        dialog = NakitAvansDialog(
            parent,
            int(av["kredi_karti_id"]),
            kart_adi=av.get("kart_adi") or "",
            avans_id=int(av["id"]),
        )
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

    if belge_no.startswith("KVR-") or tur.upper() in (
        "KASA VİRMAN GİRİŞ",
        "KASA VİRMAN ÇIKIŞ",
        "KASA VİRMAN",
    ):
        from finans_ui import KasalarArasiVirmanDialog

        dialog = KasalarArasiVirmanDialog(parent, belge_no=belge_no)
        if dialog.winfo_exists():
            parent.wait_window(dialog)
        return True

    if belge_no.startswith("CVR-"):
        if cari_virman_onizle(parent, belge_no):
            return True
        messagebox.showinfo("Belge", f"{belge_no} cari virman makbuzu bulunamadı.", parent=parent)
        return True

    if belge_no.startswith(("TMK-", "OMK-")) or tur.upper() in (
        "TAHSİLAT MAKBUZU",
        "ÖDEME MAKBUZU",
        "TAHSILAT MAKBUZU",
        "ODEME MAKBUZU",
    ):
        # Çift tık / Belgeyi Aç → gerçek makbuz kaydı (düzenleme); çıktı ayrı menüde.
        # EVB-BNC / THS eski tahsilatlar aşağıda cari_islem yoluna düşer.
        if kasa_makbuz_duzenle(parent, belge_no):
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

    if (
        belge_no.startswith(("THS-", "ODM-", "VRM-", "EVB-BNC-", "EVB-THS-", "EVB-ODM-"))
        or tur in (
            "Tahsilat",
            "Ödeme",
            "Cari Virman",
            "CARİ TAHSİLAT",
            "CARİ ÖDEME",
            "Avans kullanımı",
        )
    ):
        if cari_islem_onizle(parent, belge_no, tur=tur if tur != "Avans kullanımı" else "Ödeme"):
            return True
        messagebox.showinfo(
            "Belge",
            f"{belge_no} ({tur}) için kayıt bulunamadı.",
            parent=parent,
        )
        return True

    # Prefix tanımsız EVB / eski belgeler: hareket türü veya fiş içeriğiyle aç
    tur_u = (tur or "").strip().upper()
    dialog = None
    if tur_u in ("KASADAN BANKAYA YATAN", "KASADAN BANKAYA (KASA)"):
        from finans_ui import KasadanBankayaYatirDialog

        dialog = KasadanBankayaYatirDialog(parent, belge_no=belge_no)
    elif tur_u in ("BANKADAN NAKİT ÇEKİLEN", "BANKADAN NAKİT (KASA)"):
        from finans_ui import BankadanCekilenDialog

        dialog = BankadanCekilenDialog(parent, belge_no=belge_no)
    elif "BANKA VİRMAN" in tur_u:
        from finans_ui import BankalarArasiVirmanDialog

        dialog = BankalarArasiVirmanDialog(parent, belge_no=belge_no)
    elif tur_u == "ALINAN HAVALE":
        from finans_ui import HavaleFisDialog

        dialog = HavaleFisDialog(parent, tur="ahv", belge_no=belge_no)
    elif tur_u == "GÖNDERİLEN HAVALE":
        from finans_ui import HavaleFisDialog

        dialog = HavaleFisDialog(parent, tur="ghv", belge_no=belge_no)
    else:
        try:
            from database.finans_service import FinansService

            fis = FinansService.banka_islem_fis_getir(belge_no)
        except ValueError:
            fis = None
        if fis:
            kod = fis.get("tur")
            if kod == "kby":
                from finans_ui import KasadanBankayaYatirDialog

                dialog = KasadanBankayaYatirDialog(parent, belge_no=belge_no)
            elif kod == "bnc":
                from finans_ui import BankadanCekilenDialog

                dialog = BankadanCekilenDialog(parent, belge_no=belge_no)
            elif kod == "bvr":
                from finans_ui import BankalarArasiVirmanDialog

                dialog = BankalarArasiVirmanDialog(parent, belge_no=belge_no)
            elif kod == "kvr":
                from finans_ui import KasalarArasiVirmanDialog

                dialog = KasalarArasiVirmanDialog(parent, belge_no=belge_no)
            elif kod in ("ahv", "ghv"):
                from finans_ui import HavaleFisDialog

                dialog = HavaleFisDialog(parent, tur=kod, belge_no=belge_no)
    if dialog is not None:
        if dialog.winfo_exists():
            parent.wait_window(dialog)
        return True

    return False


def belge_id_ile_ac(parent, *, belge_id: int | None, belge_turu: str | None = None,
                    kaynak: str | None = None) -> bool:
    """Kayıt kimliğiyle satış/iade evrakını düzenleme ekranında aç (numaraya güvenmez)."""
    if not belge_id:
        return False
    tur = (belge_turu or "").strip().casefold()
    kay = (kaynak or "").strip().casefold()
    if tur in {"satis", "satış", "satis_faturasi", "satış faturası"} or kay in {
        "satış faturası",
        "satis faturasi",
    }:
        from app import CariDialog, SatisFaturasiDialog
        from database.satis_faturasi_service import SatisFaturasiService

        fatura = SatisFaturasiService.getir(int(belge_id))
        if not fatura:
            raise ValueError("Satış faturası bulunamadı.")
        if getattr(fatura, "is_deleted", False):
            raise ValueError("Silinmiş fatura açılamaz.")
        dialog = SatisFaturasiDialog(
            parent,
            fatura=fatura,
            cari_ac=lambda cari: CariDialog(parent, cari),
        )
        try:
            dialog.lift()
            dialog.focus_force()
        except tk.TclError:
            pass
        parent.wait_window(dialog)
        return True
    if tur in {"iade", "satis_iade", "satış iadesi", "satis iadesi"} or kay in {
        "satış iadesi",
        "satis iadesi",
    }:
        from app import SatisIadeFaturasiDialog
        from database.satis_iade_faturasi_service import SatisIadeFaturasiService

        iade = SatisIadeFaturasiService.getir(int(belge_id))
        if not iade:
            raise ValueError("Satış iade faturası bulunamadı.")
        if getattr(iade, "is_deleted", False):
            raise ValueError("Silinmiş iade faturası açılamaz.")
        dialog = SatisIadeFaturasiDialog(parent, iade=iade)
        try:
            dialog.lift()
            dialog.focus_force()
        except tk.TclError:
            pass
        parent.wait_window(dialog)
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

    if tur == "Satış" or belge_no.startswith(("SRAY", "SF-", "RAY-")):
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

    # Hizmet alış/satış (HAG/HSG/…) — etiket veya önek
    tur_cf = (tur or "").casefold()
    if (
        belge_no.upper().startswith(("HAG", "HSG", "HAI", "HSI"))
        or "hizmet" in tur_cf
    ):
        from database.hizmet_faturasi_service import HizmetFaturasiService
        from database.models.hizmet_faturasi import HizmetFaturasi
        from hizmet_fatura_ui import HizmetFaturaDialog

        fatura_id = _id_bul(HizmetFaturasi, "fatura_no", belge_no)
        if not fatura_id:
            return False
        fatura = HizmetFaturasiService.getir(fatura_id)
        if not fatura:
            raise ValueError("Hizmet faturası bulunamadı.")
        dialog = HizmetFaturaDialog(
            parent,
            hizmet_turu=fatura.fatura_turu,
            fatura=fatura,
        )
        parent.wait_window(dialog)
        return True

    return False
