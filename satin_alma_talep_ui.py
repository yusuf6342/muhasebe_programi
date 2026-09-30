"""Satın Alma Talebi evrak formu, talep listesi ve talepten siparişe aktarım penceresi."""

from __future__ import annotations

import os
import tkinter as tk
from datetime import date, datetime
from decimal import Decimal
from tkinter import filedialog, messagebox, simpledialog, ttk

from satin_alma_ui import _SatinAlmaSatirGirisi, _liste_ust, _para, _tarih
from satis_tema import (
    ACIK_BG,
    ACIK_SARI,
    BEYAZ,
    IKINCIL,
    KOYU_LACIVERT,
    LACIVERT,
    SARI,
    UYARI,
    font,
    tk_buton,
    treeview_stil,
)


def _tarih_oku(metin: str) -> date | None:
    metin = (metin or "").strip()
    if not metin:
        return None
    for bicim in ("%d.%m.%Y", "%d/%m/%Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(metin, bicim).date()
        except ValueError:
            continue
    raise ValueError(f"Tarih anlaşılamadı: {metin} (gg.aa.yyyy)")


def _sayi(v) -> str:
    from satir_ici_urun_giris import sayi_metni

    return "" if v is None else sayi_metni(v)


def _depolar() -> list[str]:
    try:
        from sqlalchemy import select

        from database.database import get_session
        from database.models.stok import Depo

        with get_session() as s:
            return [d for d in s.scalars(select(Depo.ad).where(Depo.aktif.is_(True)).order_by(Depo.ad)).all()]
    except Exception:  # noqa: BLE001
        return ["ANA DEPO"]


def talep_formu_ac(app, talep_id: int | None = None) -> "SatinAlmaTalepDialog":
    return SatinAlmaTalepDialog(app, talep_id=talep_id)


# ===================================================================== form
class SatinAlmaTalepDialog(_SatinAlmaSatirGirisi, tk.Toplevel):
    _KOLONLAR = (
        ("kod", "Stok Kodu", 90), ("ad", "Ürün Adı", 190), ("aciklama", "Teknik Açıklama", 170),
        ("birim", "Birim", 60), ("miktar", "Miktar", 70), ("stok", "Depo Stok", 75),
        ("bekleyen", "Bekleyen Sip.", 85), ("tedarikci", "Önerilen Tedarikçi", 130), ("ihtiyac", "İhtiyaç", 80),
        ("fiyat", "Tahmini Fiyat", 90), ("pb", "Döviz", 50), ("siparis", "Sipariş", 65),
        ("teslim", "Teslim", 65), ("iptal", "İptal", 55), ("kalan", "Kalan", 65),
    )
    _FIYAT_KOLONLARI = ("fiyat", "pb")

    def __init__(self, parent, talep_id=None):
        super().__init__(parent)
        from database.access import yetki_var
        from database.satin_alma_talep_service import ONCELIKLER, SatinAlmaTalepService
        from database.session_manager import oturum
        from satir_ici_urun_giris import HucreAlani

        self.SatinAlmaTalepService = SatinAlmaTalepService
        self.talep_id = talep_id
        self.row_version: int | None = None
        self._durum = "TASLAK"
        self._gorunen_durum = "TASLAK"
        self._isteyen_id = None
        self._kirli = False
        self._yukleniyor = True
        self._fiyat_gor = yetki_var("alis_talep_fiyat_gorme", "maliyet_gorma")
        self._yetki_duzenle = yetki_var("alis_talep_duzenleme", "alis_duzenleme")
        self._yetki_onay = yetki_var("alis_talep_onay")
        self.title("Satın Alma Talebi")
        self.configure(bg=ACIK_BG)
        self.geometry("1320x780")
        self.transient(parent.winfo_toplevel() if hasattr(parent, "winfo_toplevel") else parent)

        bant = tk.Frame(self, bg=LACIVERT)
        bant.pack(fill="x")
        tk.Label(bant, text="SATIN ALMA TALEBİ", bg=LACIVERT, fg=SARI, font=font(22, "bold", self)).pack(
            side="left", padx=18, pady=10
        )
        self.durum_lbl = tk.Label(bant, text="TASLAK", bg=SARI, fg=KOYU_LACIVERT, font=font(12, "bold", self),
                                  padx=12, pady=4)
        self.durum_lbl.pack(side="right", padx=18)

        ust = tk.Frame(self, bg=ACIK_SARI, highlightthickness=1, highlightbackground=SARI)
        ust.pack(fill="x", padx=10, pady=(8, 4))
        for c in range(8):
            ust.columnconfigure(c, weight=1 if c % 2 else 0)

        def etiket(r, c, metin):
            tk.Label(ust, text=metin, bg=ACIK_SARI, fg=LACIVERT, font=font(10, "bold", self)).grid(
                row=r, column=c, sticky="w", padx=(10, 4), pady=3
            )

        etiket(0, 0, "Talep No")
        self.no = ttk.Entry(ust, width=16)
        self.no.grid(row=0, column=1, sticky="we", pady=3)
        self.no.insert(0, SatinAlmaTalepService.talep_no() if not talep_id else "")
        etiket(0, 2, "Talep Tarihi")
        self.tarih = ttk.Entry(ust, width=12)
        self.tarih.grid(row=0, column=3, sticky="w", pady=3)
        self.tarih.insert(0, date.today().strftime("%d.%m.%Y"))
        etiket(0, 4, "Firma")
        tk.Label(ust, text=oturum.firma_unvan or "", bg=ACIK_SARI, fg=KOYU_LACIVERT, anchor="w").grid(
            row=0, column=5, sticky="we")
        etiket(0, 6, "Talep Eden")
        self.isteyen_lbl = tk.Label(ust, text=oturum.ad_soyad or oturum.kullanici_adi or "", bg=ACIK_SARI,
                                    fg=KOYU_LACIVERT, anchor="w")
        self.isteyen_lbl.grid(row=0, column=7, sticky="we")
        etiket(1, 0, "Departman")
        self.departman = ttk.Entry(ust, width=18)
        self.departman.grid(row=1, column=1, sticky="we", pady=3)
        etiket(1, 2, "Depo")
        self.depo = ttk.Combobox(ust, values=_depolar(), width=16)
        self.depo.set("ANA DEPO")
        self.depo.grid(row=1, column=3, sticky="w", pady=3)
        etiket(1, 4, "Öncelik")
        self.oncelik = ttk.Combobox(ust, values=ONCELIKLER, state="readonly", width=12)
        self.oncelik.set("NORMAL")
        self.oncelik.grid(row=1, column=5, sticky="w", pady=3)
        etiket(1, 6, "İhtiyaç Tarihi")
        self.ihtiyac = ttk.Entry(ust, width=12)
        self.ihtiyac.grid(row=1, column=7, sticky="w", pady=3)
        etiket(2, 0, "Talep Nedeni")
        self.neden = ttk.Entry(ust)
        self.neden.grid(row=2, column=1, columnspan=3, sticky="we", pady=3)
        etiket(2, 4, "Proje / Referans")
        self.proje = ttk.Entry(ust)
        self.proje.grid(row=2, column=5, columnspan=3, sticky="we", pady=3, padx=(0, 10))
        etiket(3, 0, "Açıklama")
        self.aciklama = ttk.Entry(ust)
        self.aciklama.grid(row=3, column=1, columnspan=7, sticky="we", pady=(3, 8), padx=(0, 10))

        satir_fr = tk.LabelFrame(self, text=" Talep Satırları ", bg=ACIK_BG, fg=LACIVERT, font=font(10, "bold", self))
        satir_fr.pack(fill="both", expand=True, padx=10, pady=4)
        arac = tk.Frame(satir_fr, bg=ACIK_BG)
        arac.pack(fill="x", pady=(2, 4))
        self._satir_dugmeleri = [
            tk_buton(arac, "Manuel Satır Ekle", self.manuel_satir_ekle, rol="ara"),
            tk_buton(arac, "Tedarikçi Öner", self.tedarikci_oner, rol="duzenle"),
        ]
        for b in self._satir_dugmeleri:
            b.pack(side="left", padx=(0, 6))
        self.eslestir_btn = tk_buton(arac, "Stok Kartıyla Eşleştir", self.stok_eslestir, rol="duzenle")
        self.eslestir_btn.pack(side="left", padx=(0, 6))
        self.kalan_iptal_btn = tk_buton(arac, "Kalanı İptal Et", self.kalan_iptal, rol="iptal")
        self.kalan_iptal_btn.pack(side="left", padx=(0, 6))
        self.satirlar: list[dict] = []
        alanlar = [
            HucreAlani("miktar", deger=lambda i: _sayi(self.satirlar[i].get("miktar") or 0)),
            HucreAlani("birim", "secim", secenekler=self._satir_birimleri, serbest=False),
            HucreAlani("aciklama", "metin", deger=lambda i: self.satirlar[i].get("aciklama") or ""),
            HucreAlani("ihtiyac", "metin", deger=lambda i: _tarih(self.satirlar[i].get("ihtiyac_tarihi"))),
        ]
        if self._fiyat_gor:
            alanlar.append(HucreAlani("fiyat", deger=lambda i: _sayi(self.satirlar[i].get("tahmini_birim_fiyat"))))
        self._satir_alani_kur(satir_fr, alanlar, depo=lambda: self.depo.get().strip())
        if not self._fiyat_gor:
            self.satir_tablosu.configure(
                displaycolumns=[k for k, _b, _g in self._KOLONLAR if k not in self._FIYAT_KOLONLARI]
            )

        self.mesaj_lbl = tk.Label(self, text="", bg=ACIK_BG, fg=LACIVERT, anchor="w", justify="left")
        self.mesaj_lbl.pack(fill="x", padx=12)
        alt = tk.Frame(self, bg=ACIK_BG)
        alt.pack(fill="x", padx=10, pady=(4, 10))
        self.kaydet_btn = tk_buton(alt, "Kaydet", self._kaydet, rol="kaydet")
        self.gonder_btn = tk_buton(alt, "Onaya Gönder", self.onaya_gonder, rol="ara")
        self.onay_btn = tk_buton(alt, "Onayla", self.onayla, rol="kaydet")
        self.red_btn = tk_buton(alt, "Reddet", self.reddet, rol="iptal")
        self.geri_btn = tk_buton(alt, "Geri Gönder", self.geri_gonder, rol="duzenle")
        self.siparis_btn = tk_buton(alt, "Sipariş Oluştur", self.siparis_olustur, rol="yeni")
        self.teklif_btn = tk_buton(alt, "Teklife Aktar", self.teklife_aktar, rol="duzenle")
        self.iptal_btn = tk_buton(alt, "Talebi İptal Et", self.talep_iptal, rol="iptal")
        for b in (self.kaydet_btn, self.gonder_btn, self.onay_btn, self.red_btn, self.geri_btn, self.siparis_btn,
                  self.teklif_btn, self.iptal_btn):
            b.pack(side="left", padx=(0, 6))
        tk_buton(alt, "Kapat", self.kapat, rol="geri").pack(side="right")
        for metin, islem in (("Word", "word"), ("PDF", "pdf"), ("Yazdır", "yazdir"), ("Önizle", "onizleme")):
            tk_buton(alt, metin, lambda i=islem: self.cikti(i), rol="yazdir").pack(side="right", padx=(6, 0))
        tk_buton(alt, "Geçmiş", self.gecmis_goster, rol="geri").pack(side="right", padx=(6, 0))
        tk_buton(alt, "Ekler", self.ekler_goster, rol="geri").pack(side="right", padx=(6, 0))

        for w in (self.tarih, self.departman, self.ihtiyac, self.neden, self.proje, self.aciklama, self.depo):
            w.bind("<KeyRelease>", self._degisti, add="+")
        for w in (self.depo, self.oncelik):
            w.bind("<<ComboboxSelected>>", self._degisti, add="+")
        self.protocol("WM_DELETE_WINDOW", self.kapat)
        if talep_id:
            self._yukle(int(talep_id))
        self._yukleniyor = False
        self._kirli = False
        self._durum_uygula()
        self._satir_ici_giris.odakla()

    # ---------------------------------------------------------- durum
    def _kilitli(self) -> bool:
        return getattr(self, "_durum", "TASLAK") != "TASLAK" or not getattr(self, "_yetki_duzenle", True)

    def _degisti(self, _e=None):
        if not self._yukleniyor and not self._kilitli():
            self._kirli = True

    def _satirlari_yenile(self) -> None:
        super()._satirlari_yenile()
        if not getattr(self, "_yukleniyor", True):
            self._degisti()

    def _durum_uygula(self):
        kilit = self._kilitli()
        durum = "disabled" if kilit else "normal"
        for w in (self.tarih, self.departman, self.ihtiyac, self.neden, self.proje, self.aciklama):
            w.configure(state=durum)
        self.no.configure(state="readonly")
        self.depo.configure(state="disabled" if kilit else "normal")
        self.oncelik.configure(state="disabled" if kilit else "readonly")
        for b in self._satir_dugmeleri + [self.kaydet_btn]:
            b.configure(state=durum)
        onayli = self._durum in ("ONAYLANDI", "SİPARİŞE AKTARILDI")
        self.gonder_btn.configure(state="normal" if self._durum == "TASLAK" and self._yetki_duzenle else "disabled")
        bekliyor = self._durum == "ONAYA GÖNDERİLDİ" and self._yetki_onay
        self.onay_btn.configure(state="normal" if bekliyor else "disabled")
        self.red_btn.configure(state="normal" if bekliyor else "disabled")
        self.geri_btn.configure(state="normal" if (bekliyor or (onayli and self._yetki_onay)) else "disabled")
        self.siparis_btn.configure(state="normal" if onayli else "disabled")
        self.teklif_btn.configure(state="normal" if onayli else "disabled")
        self.kalan_iptal_btn.configure(state="normal" if onayli else "disabled")
        self.eslestir_btn.configure(state="normal" if self._durum != "İPTAL" and self.talep_id else "disabled")
        self.iptal_btn.configure(
            state="normal" if self.talep_id and self._durum not in ("İPTAL",) and self._yetki_duzenle else "disabled"
        )
        renk = {"İPTAL": UYARI, "REDDEDİLDİ": UYARI}.get(self._gorunen_durum, SARI)
        self.durum_lbl.configure(text=self._gorunen_durum, bg=renk, fg=BEYAZ if renk == UYARI else KOYU_LACIVERT)

    def _mesaj(self, metin: str, hata: bool = False):
        self.mesaj_lbl.configure(text=metin, fg=UYARI if hata else LACIVERT)

    # ---------------------------------------------------------- satırlar
    def _yeni_satir(self, degerler) -> dict:
        from database.stok_service import StokService

        kod = str(degerler[0] if degerler else "").strip()
        if not kod:
            raise ValueError("Stok bulunamadı.")
        bilgi = self._stok_bilgisi(kod)
        try:
            fiyat = Decimal(str(StokService.son_alis_fiyati(kod, Decimal("0")) or 0))
        except Exception:  # noqa: BLE001
            fiyat = Decimal("0")
        return {
            "urun_kodu": kod,
            "urun_adi": str(degerler[1] if len(degerler) > 1 else "").strip() or kod,
            "birim": str(degerler[2] if len(degerler) > 2 else "").strip() or "Adet",
            "miktar": Decimal("1"),
            "aciklama": "",
            "manuel": False,
            "stok": bilgi["stok"],
            "bekleyen": bilgi["bekleyen"],
            "tahmini_birim_fiyat": fiyat if fiyat > 0 else None,
            "para_birimi": "TRY",
            "fiyat_kaynagi": "Son alış fiyatı" if fiyat > 0 else None,
        }

    def _stok_bilgisi(self, kod: str) -> dict:
        try:
            return self.SatinAlmaTalepService.stok_bilgisi(kod, self.depo.get().strip() or None)
        except Exception:  # noqa: BLE001
            return {"stok": None, "bekleyen": None}

    def _satir_degerleri(self, s: dict) -> tuple:
        kod = s.get("urun_kodu") or ""
        if s.get("manuel") and not s.get("stok_id"):
            kod = "MANUEL"
        return (
            kod, s.get("urun_adi") or "", s.get("aciklama") or "", s.get("birim") or "", _sayi(s.get("miktar")),
            _sayi(s.get("stok")), _sayi(s.get("bekleyen")), s.get("tedarikci") or "",
            _tarih(s.get("ihtiyac_tarihi")), _sayi(s.get("tahmini_birim_fiyat")),
            (s.get("para_birimi") or "TRY") if s.get("tahmini_birim_fiyat") is not None else "",
            _sayi(s.get("siparis")), _sayi(s.get("teslim")), _sayi(s.get("iptal")), _sayi(s.get("kalan")),
        )

    def _hucre_ozel(self, yeni: dict, kolon: str, metin: str) -> None:
        from satir_ici_urun_giris import ondalik

        if kolon == "ihtiyac":
            yeni["ihtiyac_tarihi"] = _tarih_oku(metin)
        elif kolon == "fiyat":
            fiyat = ondalik(metin) if metin else None
            if fiyat is not None and fiyat < 0:
                raise ValueError("Tahmini fiyat negatif olamaz.")
            yeni["tahmini_birim_fiyat"] = fiyat
            yeni["fiyat_kaynagi"] = "Elle" if fiyat is not None else None

    def manuel_satir_ekle(self):
        if self._kilitli():
            return
        ad = simpledialog.askstring("Manuel satır", "Ürün / hizmet adı:", parent=self)
        if not ad or not ad.strip():
            return
        birim = simpledialog.askstring("Manuel satır", "Birim:", initialvalue="Adet", parent=self)
        if not birim or not birim.strip():
            return
        miktar = simpledialog.askstring("Manuel satır", "Miktar:", initialvalue="1", parent=self)
        if miktar is None:
            return
        teknik = simpledialog.askstring("Manuel satır", "Teknik açıklama (isteğe bağlı):", parent=self) or ""
        try:
            self.manuel_satir_ekle_degerle(ad, birim, miktar, teknik)
        except ValueError as e:
            messagebox.showwarning("Manuel satır", str(e), parent=self)

    def manuel_satir_ekle_degerle(self, ad: str, birim: str, miktar, teknik: str = "") -> None:
        from satir_ici_urun_giris import ondalik

        mik = ondalik(miktar)
        if mik <= 0:
            raise ValueError("Miktar sıfırdan büyük olmalıdır.")
        self.satirlar.append({
            "urun_kodu": "", "urun_adi": ad.strip(), "birim": birim.strip(), "miktar": mik,
            "aciklama": teknik.strip(), "manuel": True, "stok": None, "bekleyen": None,
            "tahmini_birim_fiyat": None, "para_birimi": "TRY",
        })
        self._satirlari_yenile()

    def tedarikci_oner(self):
        from database.alis_siparisi_service import AlisSiparisiService
        from satin_alma_ui import TedarikciSecDialog

        idx = self._secili_index()
        if idx is None or self._kilitli():
            messagebox.showinfo("Tedarikçi", "Önce bir satır seçin.", parent=self)
            return
        tedarikciler = AlisSiparisiService.aktif_tedarikcileri()
        dlg = TedarikciSecDialog(self, tedarikciler)
        self.wait_window(dlg)
        if dlg.result:
            cari = next((t for t in tedarikciler if int(t.id) == int(dlg.result[0])), None)
            self.satirlar[idx]["onerilen_tedarikci_id"] = int(dlg.result[0])
            self.satirlar[idx]["tedarikci"] = cari.unvan if cari else ""
            self._satirlari_yenile()

    def _satir_menusu(self, idx: int) -> list:
        ogeler = super()._satir_menusu(idx)
        ogeler.append(("Önerilen Tedarikçi…", self.tedarikci_oner))
        return ogeler

    # ------------------------------------------------------------- yükle
    def _yukle(self, talep_id: int):
        d = self.SatinAlmaTalepService.detay(talep_id)
        self._yukleniyor = True
        try:
            self.talep_id = int(d["id"])
            self.row_version = int(d["row_version"] or 1)
            self._durum = d["durum"]
            self._gorunen_durum = d["gorunen_durum"]
            self._isteyen_id = d.get("isteyen_kullanici_id")
            for w in (self.no, self.tarih, self.departman, self.ihtiyac, self.neden, self.proje, self.aciklama):
                w.configure(state="normal")
                w.delete(0, "end")
            self.no.insert(0, d["talep_no"])
            self.tarih.insert(0, _tarih(d["talep_tarihi"]))
            self.departman.insert(0, d.get("departman") or "")
            self.ihtiyac.insert(0, _tarih(d.get("ihtiyac_tarihi")))
            self.neden.insert(0, d.get("talep_nedeni") or "")
            self.proje.insert(0, d.get("proje_ref") or "")
            self.aciklama.insert(0, d.get("aciklama") or "")
            self.depo.configure(state="normal")
            self.depo.set(d.get("depo") or "ANA DEPO")
            self.oncelik.configure(state="readonly")
            self.oncelik.set(d.get("oncelik") or "NORMAL")
            self.isteyen_lbl.configure(text=d.get("isteyen_kullanici") or "")
            onayli = d["durum"] in ("ONAYLANDI", "SİPARİŞE AKTARILDI")
            self.satirlar = [
                {
                    "id": s["id"], "urun_kodu": s["urun_kodu"], "urun_adi": s["urun_adi"], "aciklama": s["aciklama"],
                    "birim": s["birim"], "miktar": s["miktar"], "manuel": s["manuel"], "stok_id": s["stok_id"],
                    "stok": s["mevcut_stok"], "bekleyen": s["bekleyen_siparis"],
                    "onerilen_tedarikci_id": s["onerilen_tedarikci_id"], "tedarikci": s["onerilen_tedarikci"],
                    "ihtiyac_tarihi": s["ihtiyac_tarihi"], "tahmini_birim_fiyat": s["tahmini_birim_fiyat"],
                    "para_birimi": s["para_birimi"], "kur": s["kur"], "fiyat_kaynagi": s["fiyat_kaynagi"],
                    "siparis": s["siparis"] if onayli else None, "teslim": s["teslim"] if onayli else None,
                    "iptal": s["iptal"] if onayli else None, "kalan": s["kalan"] if onayli else None,
                    "eslesmemis": s["eslesmemis"],
                }
                for s in d["satirlar"]
            ]
            self._satirlari_yenile()
            notlar = []
            if d.get("geri_gonderme_nedeni") and d["durum"] == "TASLAK":
                notlar.append(f"Geri gönderme nedeni: {d['geri_gonderme_nedeni']}")
            if d.get("red_nedeni") and d["durum"] == "REDDEDİLDİ":
                notlar.append(f"Red nedeni: {d['red_nedeni']}")
            if d.get("onaylayan") and onayli:
                notlar.append(f"Onaylayan: {d['onaylayan']} ({_tarih(d.get('onay_tarihi'))})")
            if any(s["eslesmemis"] for s in d["satirlar"]):
                notlar.append("Manuel satırlar siparişe aktarılmadan önce stok kartıyla eşleştirilmelidir.")
            self._mesaj("   |   ".join(notlar))
        finally:
            self._yukleniyor = False
        self._kirli = False

    # ---------------------------------------------------------- işlemler
    def _veriler(self) -> dict:
        return {
            "talep_no": self.no.get().strip(),
            "talep_tarihi": _tarih_oku(self.tarih.get()),
            "ihtiyac_tarihi": _tarih_oku(self.ihtiyac.get()),
            "depo": self.depo.get().strip() or "ANA DEPO",
            "departman": self.departman.get().strip(),
            "oncelik": self.oncelik.get(),
            "talep_nedeni": self.neden.get().strip(),
            "proje_ref": self.proje.get().strip(),
            "aciklama": self.aciklama.get().strip(),
        }

    def _kaydet(self) -> bool:
        if self._kilitli():
            return False
        if not self._bekleyenleri_uygula():
            return False
        try:
            veriler = self._veriler()
            yeni_id = self.SatinAlmaTalepService.kaydet(veriler, self.satirlar, self.talep_id, self.row_version)
            uyarilar = self.SatinAlmaTalepService.acik_talep_uyarilari(self.satirlar, yeni_id)
        except (ValueError, PermissionError) as e:
            messagebox.showerror("Kaydedilemedi", str(e), parent=self)
            return False
        self._yukle(yeni_id)
        self._durum_uygula()
        metin = f"{self.no.get()} kaydedildi ({datetime.now():%H:%M})."
        if uyarilar:
            metin += "  Aynı ürün için açık talepler var: " + "; ".join(uyarilar[:4])
        self._mesaj(metin, hata=bool(uyarilar))
        return True

    def _kayitli_olmali(self) -> bool:
        if not self.talep_id:
            if not self._kaydet():
                return False
        elif self._kirli:
            if not messagebox.askyesno("Kaydedilmemiş değişiklik", "Önce değişiklikler kaydedilsin mi?", parent=self):
                return False
            if not self._kaydet():
                return False
        return True

    def _gecis(self, fn, *args, basari: str):
        try:
            fn(self.talep_id, *args)
        except (ValueError, PermissionError) as e:
            messagebox.showerror("Talep", str(e), parent=self)
            return False
        self._yukle(self.talep_id)
        self._durum_uygula()
        self._mesaj(basari)
        return True

    def onaya_gonder(self):
        if not self._kayitli_olmali():
            return False
        return self._gecis(self.SatinAlmaTalepService.onaya_gonder, basari="Talep onaya gönderildi; düzenleme kilitlendi.")

    def onayla(self):
        return self._gecis(self.SatinAlmaTalepService.onayla, basari="Talep onaylandı.")

    def _neden_sor(self, baslik: str) -> str | None:
        neden = simpledialog.askstring(baslik, f"{baslik} nedeni:", parent=self)
        return neden.strip() if neden and neden.strip() else None

    def reddet(self, neden: str | None = None):
        neden = neden or self._neden_sor("Red")
        if neden:
            return self._gecis(self.SatinAlmaTalepService.reddet, neden, basari="Talep reddedildi.")
        return False

    def geri_gonder(self, neden: str | None = None):
        neden = neden or self._neden_sor("Geri gönderme")
        if neden:
            return self._gecis(self.SatinAlmaTalepService.geri_gonder, neden,
                               basari="Talep düzeltme için taslağa geri gönderildi.")
        return False

    def talep_iptal(self):
        if not self.talep_id:
            return
        neden = self._neden_sor("İptal")
        if neden:
            self._gecis(self.SatinAlmaTalepService.iptal_et, neden, basari="Talep iptal edildi.")

    def _secili_satir(self) -> dict | None:
        idx = self._secili_index()
        if idx is None:
            messagebox.showinfo("Seçim", "Önce bir satır seçin.", parent=self)
            return None
        return self.satirlar[idx]

    def kalan_iptal(self):
        s = self._secili_satir()
        if s is None or not s.get("id"):
            return
        miktar = simpledialog.askstring("Kalanı iptal et", f"İptal edilecek miktar (kalan {_sayi(s.get('kalan'))}):",
                                        initialvalue=_sayi(s.get("kalan")), parent=self)
        if not miktar:
            return
        neden = self._neden_sor("Kalan iptal")
        if not neden:
            return
        try:
            self.SatinAlmaTalepService.kalan_iptal(s["id"], miktar, neden)
        except (ValueError, PermissionError) as e:
            messagebox.showerror("Kalan iptal", str(e), parent=self)
            return
        self._yukle(self.talep_id)
        self._durum_uygula()

    def stok_eslestir(self):
        s = self._secili_satir()
        if s is None or not s.get("id"):
            return
        if not s.get("manuel"):
            messagebox.showinfo("Eşleştir", "Bu satır zaten bir stok kartına bağlı.", parent=self)
            return
        kod = simpledialog.askstring("Stok kartıyla eşleştir", f"'{s['urun_adi']}' için stok kodu:", parent=self)
        if not kod:
            return
        try:
            self.SatinAlmaTalepService.manuel_satiri_eslestir(s["id"], kod)
        except (ValueError, PermissionError) as e:
            messagebox.showerror("Eşleştir", str(e), parent=self)
            return
        self._yukle(self.talep_id)
        self._durum_uygula()

    def siparis_olustur(self):
        if not self.talep_id or self._durum not in ("ONAYLANDI", "SİPARİŞE AKTARILDI"):
            return
        dlg = TalepAktarDialog(self, talep_id=self.talep_id)
        self.wait_window(dlg)
        if not dlg.result:
            return
        siparis_ac(self, dlg.result)
        self._yukle(self.talep_id)
        self._durum_uygula()

    def teklife_aktar(self):
        from database.alis_siparisi_service import AlisSiparisiService
        from database.tedarikci_teklif_service import TedarikciTeklifService
        from satin_alma_ui import TedarikciSecDialog

        if not self.talep_id:
            return
        tedarikciler = AlisSiparisiService.aktif_tedarikcileri()
        if not tedarikciler:
            messagebox.showerror("Teklif", "Aktif tedarikçi yok.", parent=self)
            return
        dlg = TedarikciSecDialog(self, tedarikciler)
        self.wait_window(dlg)
        if not dlg.result:
            return
        try:
            tid = TedarikciTeklifService.talepden_olustur(self.talep_id, dlg.result)
        except (ValueError, PermissionError) as e:
            messagebox.showerror("Teklif", str(e), parent=self)
            return
        self._mesaj(f"Tedarikçi teklif taslağı oluşturuldu (id={tid}).")

    def cikti(self, islem: str):
        if not self._kayitli_olmali():
            return None
        from talep_cikti_ui import cikti_al

        return cikti_al(self, self.talep_id, islem)

    def gecmis_goster(self):
        if not self.talep_id:
            messagebox.showinfo("Geçmiş", "Talep henüz kaydedilmedi.", parent=self)
            return
        g = self.SatinAlmaTalepService.detay(self.talep_id)["gecmis"]
        satirlar = [
            f"{x['tarih']:%d.%m.%Y %H:%M}  {x['islem']}  ({x['kullanici'] or '-'})"
            + (f"  {x['eski'] or ''} → {x['yeni']}" if x["yeni"] and x["eski"] != x["yeni"] else "")
            + (f"\n    {x['detay']}" if x["detay"] else "")
            for x in g
        ]
        messagebox.showinfo("İşlem geçmişi", "\n".join(satirlar) or "Kayıt yok.", parent=self)

    def ekler_goster(self):
        if not self._kayitli_olmali():
            return
        EklerDialog(self, self.talep_id)

    def kapat(self):
        if self._kirli and not self._kilitli():
            cevap = messagebox.askyesnocancel("Kaydedilmemiş değişiklik",
                                              "Değişiklikler kaydedilmedi. Kaydedilsin mi?", parent=self)
            if cevap is None:
                return
            if cevap and not self._kaydet():
                return
        self.destroy()


class EklerDialog(tk.Toplevel):
    def __init__(self, parent, talep_id: int):
        super().__init__(parent)
        from database.satin_alma_talep_service import SatinAlmaTalepService

        self.S = SatinAlmaTalepService
        self.talep_id = talep_id
        self.title("Talep ekleri")
        self.geometry("560x320")
        self.transient(parent)
        self.liste = ttk.Treeview(self, columns=("ad", "ekleyen", "tarih"), show="headings")
        treeview_stil(self.liste)
        for k, b, w in (("ad", "Dosya", 280), ("ekleyen", "Ekleyen", 130), ("tarih", "Tarih", 110)):
            self.liste.heading(k, text=b)
            self.liste.column(k, width=w)
        self.liste.pack(fill="both", expand=True, padx=8, pady=8)
        alt = tk.Frame(self)
        alt.pack(fill="x", padx=8, pady=(0, 8))
        tk_buton(alt, "Dosya Ekle", self.ekle, rol="yeni").pack(side="left")
        tk_buton(alt, "Aç", self.ac, rol="duzenle").pack(side="left", padx=6)
        tk_buton(alt, "Kapat", self.destroy, rol="geri").pack(side="right")
        self.liste.bind("<Double-1>", lambda _e: self.ac())
        self.yenile()

    def yenile(self):
        self.liste.delete(*self.liste.get_children())
        for e in self.S.detay(self.talep_id)["ekler"]:
            self.liste.insert("", "end", iid=str(e["id"]), values=(e["dosya_adi"], e["ekleyen"] or "",
                                                                    f"{e['tarih']:%d.%m.%Y %H:%M}"))

    def ekle(self):
        yol = filedialog.askopenfilename(parent=self, title="Talebe eklenecek dosya")
        if not yol:
            return
        try:
            self.S.ek_ekle(self.talep_id, yol)
        except (ValueError, PermissionError, OSError) as e:
            messagebox.showerror("Ek", str(e), parent=self)
            return
        self.yenile()

    def ac(self):
        sec = self.liste.selection()
        if sec:
            os.startfile(str(self.S.ek_yolu(int(sec[0]))))  # noqa: S606


# ======================================================== aktarım penceresi
class TalepAktarDialog(tk.Toplevel):
    """Onaylı talep satırlarından aktarılacak miktarları seçer. result: {talep_satiri_id: Decimal}."""

    def __init__(self, parent, talep_id: int | None = None):
        super().__init__(parent)
        from database.satin_alma_talep_service import SatinAlmaTalepService

        self.result: dict[int, Decimal] | None = None
        self.title("Talepten Siparişe Aktar")
        self.configure(bg=ACIK_BG)
        self.geometry("1180x520")
        self.transient(parent)
        self.talep_id = talep_id
        self.satirlar = [s for s in SatinAlmaTalepService.aktarilabilir_satirlar()
                         if talep_id is None or s["talep_id"] == int(talep_id)]
        self.miktarlar = {s["talep_satiri_id"]: s["kalan"] for s in self.satirlar}
        self.secili = {s["talep_satiri_id"] for s in self.satirlar if not s["eslesmemis"]}
        tk.Label(self, text="İşaretli satırlar seçilen miktarla siparişe eklenir. 'Aktarılacak' hücresine çift "
                            "tıklayarak miktarı değiştirin. Miktar sipariş kaydedilene kadar tüketilmez.",
                 bg=ACIK_BG, fg=IKINCIL, anchor="w").pack(fill="x", padx=10, pady=(8, 4))
        cer = ttk.Frame(self)
        cer.pack(fill="both", expand=True, padx=10)
        kolonlar = (("sec", "Seç", 45), ("talep", "Talep No", 100), ("kod", "Stok Kodu", 90), ("ad", "Ürün", 200),
                    ("aciklama", "Teknik Açıklama", 170), ("birim", "Birim", 60), ("onayli", "Onaylı", 70),
                    ("siparis", "Siparişte", 70), ("kalan", "Kalan", 70), ("aktar", "Aktarılacak", 85),
                    ("ihtiyac", "İhtiyaç", 80), ("oncelik", "Öncelik", 70))
        self.tablo = ttk.Treeview(cer, columns=[k for k, *_ in kolonlar], show="headings")
        treeview_stil(self.tablo)
        for k, b, w in kolonlar:
            self.tablo.heading(k, text=b)
            self.tablo.column(k, width=w, anchor="center" if k in ("sec", "birim") else ("w" if k in (
                "talep", "kod", "ad", "aciklama", "oncelik") else "e"))
        self.tablo.pack(side="left", fill="both", expand=True)
        ttk.Scrollbar(cer, orient="vertical", command=self.tablo.yview).pack(side="right", fill="y")
        self.tablo.bind("<Button-1>", self._tikla)
        self.tablo.bind("<Double-1>", self._miktar_duzenle)
        alt = tk.Frame(self, bg=ACIK_BG)
        alt.pack(fill="x", padx=10, pady=8)
        tk_buton(alt, "Aktar", self.tamam, rol="kaydet").pack(side="right")
        tk_buton(alt, "Vazgeç", self.destroy, rol="geri").pack(side="right", padx=6)
        self._ciz()
        if not self.satirlar:
            tk.Label(alt, text="Aktarılabilir (onaylı ve kalanı olan) talep satırı yok.", bg=ACIK_BG, fg=UYARI).pack(
                side="left")

    def _ciz(self):
        self.tablo.delete(*self.tablo.get_children())
        for i, s in enumerate(self.satirlar):
            sid = s["talep_satiri_id"]
            self.tablo.insert("", "end", iid=str(sid), tags=("tek" if i % 2 == 0 else "cift",), values=(
                "⚠" if s["eslesmemis"] else ("☑" if sid in self.secili else "☐"), s["talep_no"],
                "MANUEL" if s["eslesmemis"] else s["urun_kodu"], s["urun_adi"], s["aciklama"], s["birim"],
                _sayi(s["onayli"]), _sayi(s["siparis"]), _sayi(s["kalan"]), _sayi(self.miktarlar[sid]),
                _tarih(s["ihtiyac_tarihi"]), s["oncelik"],
            ))

    def _tikla(self, event):
        if self.tablo.identify_column(event.x) != "#1":
            return
        iid = self.tablo.identify_row(event.y)
        if iid:
            self.sec_degistir(int(iid))
            return "break"

    def sec_degistir(self, sid: int):
        s = next(x for x in self.satirlar if x["talep_satiri_id"] == sid)
        if s["eslesmemis"]:
            messagebox.showwarning("Manuel satır", "Bu manuel satır önce talep formunda stok kartıyla eşleştirilmeli.",
                                   parent=self)
            return
        self.secili.symmetric_difference_update({sid})
        self._ciz()

    def _miktar_duzenle(self, event):
        iid = self.tablo.identify_row(event.y)
        if not iid or self.tablo.identify_column(event.x) == "#1":
            return
        sid = int(iid)
        metin = simpledialog.askstring("Aktarılacak miktar", "Miktar:", initialvalue=_sayi(self.miktarlar[sid]),
                                       parent=self)
        if metin is None:
            return
        try:
            self.miktar_ayarla(sid, metin)
        except ValueError as e:
            messagebox.showerror("Miktar", str(e), parent=self)

    def miktar_ayarla(self, sid: int, metin) -> None:
        from satir_ici_urun_giris import ondalik

        s = next(x for x in self.satirlar if x["talep_satiri_id"] == sid)
        mik = ondalik(metin)
        if mik <= 0:
            raise ValueError("Miktar sıfırdan büyük olmalıdır.")
        if mik > s["kalan"]:
            raise ValueError(f"Aktarılacak miktar kalanı ({_sayi(s['kalan'])}) aşamaz.")
        self.miktarlar[sid] = mik
        self.secili.add(sid)
        self._ciz()

    def tamam(self):
        if not self.secili:
            messagebox.showwarning("Seçim", "Aktarılacak satır seçin.", parent=self)
            return
        self.result = {sid: self.miktarlar[sid] for sid in sorted(self.secili)}
        self.destroy()


def siparis_ac(parent, miktarlar: dict[int, Decimal]):
    """Seçilen talep miktarlarıyla yeni alış siparişi kartını açar (kayıtla birlikte pay tüketilir)."""
    from alis_ui import AlisSiparisiDialog
    from database.alis_siparisi_service import AlisSiparisiService
    from database.satin_alma_talep_service import SatinAlmaTalepService

    try:
        hazir = SatinAlmaTalepService.siparis_satirlari_hazirla(miktarlar)
    except (ValueError, PermissionError) as e:
        messagebox.showerror("Sipariş Oluştur", str(e), parent=parent)
        return None
    cari = None
    if hazir["onerilen_tedarikci_id"]:
        cari = next((c for c in AlisSiparisiService.aktif_tedarikcileri()
                     if int(c.id) == int(hazir["onerilen_tedarikci_id"])), None)
    dlg = AlisSiparisiDialog(parent, cari=cari, hazir_satirlar=hazir["satirlar"])
    parent.wait_window(dlg)
    return dlg.result


# ===================================================================== liste
def satin_alma_talep_listesi_goster(app) -> None:
    from database.satin_alma_talep_service import DURUMLAR, ONCELIKLER, SatinAlmaTalepService
    from satin_alma_ui import satin_alma_hub_goster

    kok = _liste_ust(app, "SATIN ALMA TALEP LİSTESİ",
                     "Talepleri filtreleyin, açın, onaylayın ve siparişe aktarın",
                     lambda: satin_alma_hub_goster(app))
    f1 = tk.Frame(kok, bg=ACIK_BG)
    f1.pack(fill="x", padx=16, pady=(8, 0))
    f2 = tk.Frame(kok, bg=ACIK_BG)
    f2.pack(fill="x", padx=16, pady=(4, 0))
    alanlar: dict[str, tk.Widget] = {}

    def alan(parent, metin, anahtar, genislik=12, degerler=None, varsayilan=""):
        tk.Label(parent, text=metin, bg=ACIK_BG, fg=LACIVERT, font=font(10, "bold", app)).pack(side="left",
                                                                                               padx=(8, 2))
        if degerler is not None:
            w = ttk.Combobox(parent, values=degerler, state="readonly", width=genislik)
            w.set(varsayilan or degerler[0])
        else:
            w = ttk.Entry(parent, width=genislik)
            w.insert(0, varsayilan)
        w.pack(side="left")
        alanlar[anahtar] = w

    alan(f1, "Başlangıç", "bas", 11, varsayilan=date(date.today().year, 1, 1).strftime("%d.%m.%Y"))
    alan(f1, "Bitiş", "bit", 11, varsayilan=date.today().strftime("%d.%m.%Y"))
    alan(f1, "Talep No", "no", 12)
    alan(f1, "Talep Eden", "isteyen", 16)
    alan(f1, "Departman / Depo", "dd", 16)
    alan(f2, "Durum", "durum", 26, ("Tümü",) + DURUMLAR)
    alan(f2, "Öncelik", "oncelik", 10, ("Tümü",) + ONCELIKLER)
    alan(f2, "Stok", "stok", 16)
    gorunum = tk.StringVar(value="")
    for metin, deger in (("Tümü", ""), ("Onay Bekleyenler", "onay_bekleyen"), ("Geciken İhtiyaçlar", "geciken")):
        tk.Radiobutton(f2, text=metin, variable=gorunum, value=deger, bg=ACIK_BG, fg=LACIVERT,
                       command=lambda: yenile()).pack(side="left", padx=(10, 0))

    cer = ttk.Frame(kok)
    cer.pack(fill="both", expand=True, padx=16, pady=8)
    kolonlar = (("no", "Talep No", 110, "w"), ("tarih", "Tarih", 90, "center"), ("isteyen", "Talep Eden", 150, "w"),
                ("ihtiyac", "İhtiyaç Tarihi", 100, "center"), ("oncelik", "Öncelik", 80, "center"),
                ("durum", "Durum", 200, "w"), ("satir", "Satır", 60, "e"), ("toplam", "Tahmini Toplam", 120, "e"))
    tablo = ttk.Treeview(cer, columns=[k for k, *_ in kolonlar], show="headings", selectmode="browse")
    treeview_stil(tablo)
    for k, b, w, a in kolonlar:
        tablo.heading(k, text=b)
        tablo.column(k, width=w, anchor=a)
    tablo.pack(side="left", fill="both", expand=True)
    ttk.Scrollbar(cer, orient="vertical", command=tablo.yview).pack(side="right", fill="y")
    tablo.tag_configure("gecikmis", foreground=UYARI)

    def yenile():
        try:
            kayitlar = SatinAlmaTalepService.listele(
                alanlar["durum"].get(), baslangic=_tarih_oku(alanlar["bas"].get()),
                bitis=_tarih_oku(alanlar["bit"].get()), no=alanlar["no"].get(), isteyen=alanlar["isteyen"].get(),
                departman_depo=alanlar["dd"].get(), oncelik=alanlar["oncelik"].get(), stok=alanlar["stok"].get(),
                gorunum=gorunum.get() or None,
            )
        except (ValueError, PermissionError) as e:
            messagebox.showerror("Talep listesi", str(e), parent=app)
            return
        tablo.delete(*tablo.get_children())
        for i, r in enumerate(kayitlar):
            etiketler = ["tek" if i % 2 == 0 else "cift"]
            if r["ihtiyac_tarihi"] and r["ihtiyac_tarihi"] < date.today() and r["durum"] not in (
                    "TAMAMLANDI", "İPTAL", "REDDEDİLDİ"):
                etiketler.append("gecikmis")
            tablo.insert("", "end", iid=str(r["id"]), tags=tuple(etiketler), values=(
                r["talep_no"], _tarih(r["talep_tarihi"]), r["isteyen"], _tarih(r["ihtiyac_tarihi"]), r["oncelik"],
                r["durum"], r["satir_adet"], _para(r["tahmini_toplam"]) if r["tahmini_toplam"] is not None else "—",
            ))

    def ac(talep_id=None):
        dlg = SatinAlmaTalepDialog(app, talep_id=talep_id)
        app.wait_window(dlg)
        yenile()

    def secili_ac(_e=None):
        sec = tablo.selection()
        if not sec:
            messagebox.showinfo("Seçim", "Talep seçin.", parent=app)
            return
        ac(int(sec[0]))

    alt = tk.Frame(kok, bg=ACIK_BG)
    alt.pack(fill="x", padx=16, pady=10)
    tk_buton(alt, "Yeni Talep", lambda: ac(None), rol="yeni").pack(side="left")
    tk_buton(alt, "Aç", secili_ac, rol="duzenle").pack(side="left", padx=6)
    tk_buton(alt, "Ürün Bazlı Rapor", lambda: UrunBazliRaporDialog(app), rol="geri").pack(side="left", padx=6)
    tk_buton(alt, "Listele", yenile, rol="ara").pack(side="right")
    tablo.bind("<Double-1>", secili_ac)
    for anahtar, w in alanlar.items():
        if isinstance(w, ttk.Combobox):
            w.bind("<<ComboboxSelected>>", lambda _e: yenile())
        else:
            w.bind("<Return>", lambda _e: yenile())
    yenile()
    if hasattr(app, "nav_sayfa_isaretle"):
        app.nav_sayfa_isaretle(lambda: satin_alma_talep_listesi_goster(app))


class UrunBazliRaporDialog(tk.Toplevel):
    def __init__(self, parent):
        super().__init__(parent)
        from database.satin_alma_talep_service import SatinAlmaTalepService

        self.title("Ürün bazlı talep raporu")
        self.geometry("980x480")
        self.transient(parent)
        kolonlar = (("kod", "Stok Kodu", 100), ("ad", "Ürün", 220), ("birim", "Birim", 60),
                    ("adet", "Talep Sayısı", 90), ("talep", "Talep", 80), ("onayli", "Onaylı", 80),
                    ("siparis", "Sipariş", 80), ("teslim", "Teslim", 80), ("iptal", "İptal", 70), ("kalan", "Kalan", 80))
        t = ttk.Treeview(self, columns=[k for k, *_ in kolonlar], show="headings")
        treeview_stil(t)
        for k, b, w in kolonlar:
            t.heading(k, text=b)
            t.column(k, width=w, anchor="w" if k in ("kod", "ad") else "e")
        t.pack(fill="both", expand=True, padx=8, pady=8)
        for i, r in enumerate(SatinAlmaTalepService.urun_bazli_rapor()):
            t.insert("", "end", tags=("tek" if i % 2 == 0 else "cift",), values=(
                r["urun_kodu"] or "MANUEL", r["urun_adi"], r["birim"], r["talep_sayisi"], _sayi(r["talep"]),
                _sayi(r["onayli"]), _sayi(r["siparis"]), _sayi(r["teslim"]), _sayi(r["iptal"]), _sayi(r["kalan"]),
            ))
