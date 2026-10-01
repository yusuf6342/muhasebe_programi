"""Satın alma belge diyalogları (satış UI kalıplarının alış karşılığı)."""
from __future__ import annotations

import tkinter as tk
from datetime import date, datetime, timedelta
from decimal import Decimal
from tkinter import filedialog, messagebox, simpledialog, ttk

from database.alis_faturasi_service import (
    ODEME_SEKILLERI,
    AlisFaturasiService,
    MukerrerTedarikciFaturaHatasi,
)
from database.alis_iade_faturasi_service import AlisIadeFaturasiService
from database.alis_irsaliyesi_service import AlisIrsaliyesiService
from database.alis_siparisi_service import AlisSiparisiService
from database.fatura_kdv_service import kdv_oran_metni, satir_kdv_metin
from database.satis_siparisi_service import decimal
from database.stok_service import StokService
from doviz_fatura_panel import (
    doviz_ozet_guncelle,
    doviz_paneli_kur,
    doviz_satir_kaydet_oncesi,
    doviz_verilerini_doldur,
    doviz_verilerini_topla,
)
from product_provider import search_prices, search_products
from ui_takvim import saat_dogrula, saat_varsayilan, tarih_alani
from database.turkce_normalize import turkce_normalize
import fatura_tema as ftema

BIRIM_SECENEKLERI = ("Adet", "Kg", "Metre", "Koli", "Paket", "Torba", "Boy", "Top")
ALIS_BELGE_BASLIGI = "ALIŞ FATURASI"
ALIS_TABLO_STILI = "AlisSatir.Treeview"
ALIS_UST_PADY = 3


def para_goster(tutar):
    return f"{float(tutar):,.2f} TL".replace(",", "X").replace(".", ",").replace("X", ".")


def tarih_goster(tarih):
    return tarih.strftime("%d.%m.%Y")


def _tedarikci_ekle(tedarikci_map: dict, cari) -> str | None:
    """Pasif/eksik tedarikçiyi haritaya ekler; combobox anahtarını döner."""
    if not cari:
        return None
    anahtar = f"{cari.cari_kodu} - {cari.unvan}"
    if anahtar not in tedarikci_map:
        tedarikci_map[anahtar] = cari
    return anahtar


class _AlisSatirGirisi:
    """Alış sipariş / irsaliye: son satırda ürün girişi ve hücre düzenleme (alış fiyatıyla)."""

    _fiyat_alani = "birim_alis_fiyati"

    def _alis_girisi_kur(self):
        from satir_ici_urun_giris import HucreAlani, SatirHucreDuzenleyici, SatirIciUrunGirisi, sayi_metni

        self._satir_ici_giris = SatirIciUrunGirisi(
            self,
            self.satir_tablosu,
            urun_ekle=self._alis_urun_ekle,
            kolonlar={"kod": "kod", "ad": "ad"},
            urun_degistir=self._alis_urun_degistir,
            miktara_git=lambda idx: self._hucre.duzenle(idx, "miktar"),
            fiyat_turu="alis",
            alis_fiyati=lambda kod: StokService.son_alis_fiyati(kod, None),
            satir_menusu=self._alis_satir_menusu,
        )
        self._hucre = SatirHucreDuzenleyici(
            self,
            self.satir_tablosu,
            [
                HucreAlani("miktar", deger=lambda i: sayi_metni(self.satirlar[i].get("miktar") or 0)),
                HucreAlani("birim", "secim", secenekler=self._alis_birimleri),
                HucreAlani("fiyat", deger=lambda i: sayi_metni(self.satirlar[i].get(self._fiyat_alani) or 0)),
                HucreAlani("isk", deger=lambda i: sayi_metni(self.satirlar[i].get("iskonto_orani") or 0)),
                HucreAlani("kdv", "secim", secenekler=lambda _i: ("0", "1", "10", "20"), serbest=True,
                           deger=lambda i: sayi_metni(self.satirlar[i].get("kdv_orani") or 0)),
            ],
            uygula=self.alis_hucre_uygula,
            satir_sayisi=lambda: len(self.satirlar),
            bitince=self._satir_ici_giris.odakla,
        )
        self.satir_tablosu.bind("<Delete>", lambda _e: self.satir_sil())
        self._satir_ici_giris.tabloya_ekle()

    def _alis_yenile(self):
        raise NotImplementedError

    def _satir_toplu_yenile(self):
        self._alis_yenile()

    @staticmethod
    def _alis_bagli(s: dict) -> bool:
        if s.get("siparis_satiri_id") or s.get("kaynak_fatura_satiri_id") or s.get("talep_paylari"):
            return True
        return any(
            decimal(s.get(k) or 0, "Miktar", Decimal("0")) > 0
            for k in ("irsaliyelenen_miktar", "faturalanan_miktar")
        )

    def _alis_birimleri(self, idx: int) -> list[str]:
        s = self.satirlar[idx]
        if self._alis_bagli(s):
            return [s.get("birim") or "Adet"]
        try:
            from fatura_satir_birim_service import stok_aktif_birimleri

            return stok_aktif_birimleri(s.get("urun_kodu") or "") or list(BIRIM_SECENEKLERI)
        except Exception:
            return list(BIRIM_SECENEKLERI)

    def _alis_satiri(self, degerler) -> dict:
        from satir_ici_urun_giris import alis_birim_fiyati, ondalik

        kod = (degerler[0] if degerler else "") or ""
        if not kod:
            raise ValueError("Ürün kodu boş.")
        birim = (degerler[2] if len(degerler) > 2 else "") or "Adet"
        kdv_metin = degerler[6] if len(degerler) > 6 else None
        try:
            kdv = ondalik(kdv_metin, Decimal("20")) if kdv_metin not in (None, "") else Decimal("20")
        except ValueError:
            kdv = Decimal("20")
        return {
            "urun_kodu": kod, "urun_adi": (degerler[1] if len(degerler) > 1 else "") or "",
            "aciklama": "", "miktar": Decimal("1"), "birim": birim,
            self._fiyat_alani: alis_birim_fiyati(kod, birim),
            "iskonto_orani": Decimal("0"), "kdv_orani": kdv,
        }

    def _alis_urun_ekle(self, degerler, konum):
        from satir_ici_urun_giris import birlesecek_satir, giris_bileseni, toplu_ekleme_mi

        veri = self._alis_satiri(degerler)
        giris = giris_bileseni(self)
        if giris is not None and giris.son_islem == "barkod" and konum is None:
            adaylar = [s if not self._alis_bagli(s) else {**s, "siparis_satiri_id": -1} for s in self.satirlar]
            idx = birlesecek_satir(adaylar, veri, fiyat_alani=self._fiyat_alani, ek_alanlar=("iskonto_orani",))
            if idx is not None:
                s = self.satirlar[idx]
                s["miktar"] = decimal(s.get("miktar") or 0, "Miktar", Decimal("0")) + Decimal("1")
                if not toplu_ekleme_mi(self):
                    self._alis_yenile()
                return idx
        if konum is not None and 0 <= konum <= len(self.satirlar):
            self.satirlar.insert(konum, veri)
            idx = konum
        else:
            self.satirlar.append(veri)
            idx = len(self.satirlar) - 1
        if not toplu_ekleme_mi(self):
            self._alis_yenile()
        return idx

    def _alis_urun_degistir(self, idx: int, degerler) -> bool:
        if not (0 <= idx < len(self.satirlar)):
            return False
        eski = self.satirlar[idx]
        if self._alis_bagli(eski):
            messagebox.showwarning(
                "Bağlı satır", "Bağlı belgeden gelen / işlem görmüş satırın ürünü değiştirilemez.", parent=self
            )
            return False
        try:
            veri = self._alis_satiri(degerler)
        except ValueError as hata:
            messagebox.showwarning("Ürün", str(hata), parent=self)
            return False
        veri["miktar"] = eski.get("miktar") or Decimal("1")
        veri["aciklama"] = eski.get("aciklama") or ""
        self.satirlar[idx] = veri
        self._alis_yenile()
        return True

    def alis_hucre_uygula(self, idx: int, kolon: str, metin: str) -> None:
        from satir_ici_urun_giris import alis_birim_fiyati

        if not (0 <= idx < len(self.satirlar)):
            return
        s = self.satirlar[idx]
        yeni = dict(s)
        if kolon == "miktar":
            miktar = decimal(metin or 0, "Miktar")
            if miktar <= 0:
                raise ValueError("Miktar sıfırdan büyük olmalıdır.")
            islenen = max(
                decimal(s.get("irsaliyelenen_miktar") or 0, "M", Decimal("0")),
                decimal(s.get("faturalanan_miktar") or 0, "M", Decimal("0")),
            )
            if miktar < islenen:
                raise ValueError(f"Miktar işlem görmüş miktarın ({islenen:f}) altına indirilemez.")
            yeni["miktar"] = miktar
        elif kolon == "birim":
            birim = (metin or "").strip()
            if not birim:
                raise ValueError("Birim zorunludur.")
            if birim.casefold() == (s.get("birim") or "").casefold():
                return
            if self._alis_bagli(s):
                raise ValueError("Bağlı satırın birimi değiştirilemez.")
            yeni["birim"] = birim
            yeni[self._fiyat_alani] = alis_birim_fiyati(s.get("urun_kodu") or "", birim)
        elif kolon == "fiyat":
            yeni[self._fiyat_alani] = decimal(metin or 0, "Birim alış", Decimal("0"))
        elif kolon == "isk":
            isk = decimal((metin or "0").replace("%", ""), "İskonto", Decimal("0"))
            if isk > 100:
                raise ValueError("İskonto %100'den büyük olamaz.")
            yeni["iskonto_orani"] = isk
        elif kolon == "kdv":
            yeni["kdv_orani"] = decimal((metin or "0").replace("%", ""), "KDV", Decimal("0"))
        else:
            return
        self.satirlar[idx] = yeni
        self._alis_yenile()

    def _alis_secili(self) -> int | None:
        from satir_ici_urun_giris import satir_indeksi

        secim = self.satir_tablosu.selection()
        return satir_indeksi(self.satir_tablosu, secim[0]) if secim else None

    def _alis_satir_menusu(self, idx: int) -> list:
        ogeler = [
            ("Satırı Düzenle (F2)", lambda: self._hucre.ilk_alana(idx)),
            ("Araya Satır Ekle", lambda: self._satir_ici_giris.araya_ekle(idx)),
            ("Satırı Sil (Del)", self.satir_sil),
        ]
        if 0 <= idx < len(self.satirlar) and not self._alis_bagli(self.satirlar[idx]):
            ogeler.insert(1, ("Ürünü Değiştir…", lambda: self._satir_ici_giris.urun_degistir_baslat(idx)))
        return ogeler

    def satir_duzenle(self):
        idx = self._alis_secili()
        if idx is not None:
            self._hucre.ilk_alana(idx)

    def satir_sil(self):
        from satir_ici_urun_giris import satir_editorlerini_kapat, satir_silme_sonrasi_temizle

        idx = self._alis_secili()
        if idx is None:
            return "break"
        satir_editorlerini_kapat(self)
        if messagebox.askyesno("Sil", "Satır silinsin mi?", parent=self):
            self.satirlar.pop(idx)
            self._alis_yenile()
            satir_silme_sonrasi_temizle(self, self.satir_tablosu)
        return "break"

    def _alis_bekleyenleri_uygula(self) -> bool:
        if not self._hucre.bekleyeni_uygula():
            return False
        self._satir_ici_giris.bekleyeni_uygula()
        return True


class AlisSiparisOdemeDialog(tk.Toplevel):
    def __init__(self, parent, odeme=None):
        super().__init__(parent)
        self.result = None
        self.title("Ödeme")
        self.geometry("420x260")
        self.transient(parent)
        self.grab_set()
        try:
            from ui_pencere import popup_ortala

            popup_ortala(self, parent, genislik=420, yukseklik=260)
        except Exception:
            pass
        self.girdiler = {}
        frame = ttk.Frame(self, padding=12)
        frame.pack(fill="both", expand=True)
        for sira, (etiket, alan) in enumerate((
            ("Ödeme Tarihi", "odeme_tarihi"), ("Tutar", "tutar"),
            ("Ödeme Şekli", "odeme_sekli"), ("Hesap", "hesap"), ("Açıklama", "aciklama"),
        )):
            ttk.Label(frame, text=etiket).grid(row=sira, column=0, sticky="w", pady=4)
            if alan == "odeme_sekli":
                w = ttk.Combobox(frame, values=ODEME_SEKILLERI, state="readonly", width=28)
                w.set((odeme or {}).get(alan) or ODEME_SEKILLERI[0])
            else:
                w = ttk.Entry(frame, width=30)
                if odeme and odeme.get(alan) is not None:
                    deger = odeme[alan]
                    w.insert(0, deger.strftime("%d.%m.%Y") if hasattr(deger, "strftime") else str(deger))
                elif alan == "odeme_tarihi":
                    w.insert(0, date.today().strftime("%d.%m.%Y"))
            w.grid(row=sira, column=1, padx=6, pady=4)
            self.girdiler[alan] = w
        alt = ttk.Frame(frame)
        alt.grid(row=6, column=0, columnspan=2, sticky="e", pady=10)
        ttk.Button(alt, text="İptal", command=self.destroy).pack(side="right")
        ttk.Button(alt, text="Tamam", command=self.tamam).pack(side="right", padx=8)

    def tamam(self):
        try:
            veri = {a: w.get().strip() for a, w in self.girdiler.items()}
            veri["odeme_tarihi"] = datetime.strptime(veri["odeme_tarihi"], "%d.%m.%Y").date()
            veri["tutar"] = decimal(veri["tutar"], "Tutar", Decimal("0.01"))
            self.result = veri
            self.destroy()
        except ValueError as hata:
            messagebox.showerror("Ödeme", str(hata), parent=self)


class AlisSiparisiDialog(_AlisSatirGirisi, tk.Toplevel):
    def __init__(self, parent, siparis=None, cari=None, hazir_satirlar=None):
        super().__init__(parent)
        self.siparis = siparis
        self.result = None
        self.mevcut_borc = Decimal("0")
        self.title("SATIN ALMA SİPARİŞİ")
        self.geometry("1180x720")
        self.minsize(980, 580)
        self.transient(parent)
        self.grab_set()
        self.satirlar = []
        self.odemeler = []
        self.girdiler = {}
        tedarikciler = AlisSiparisiService.aktif_tedarikcileri()
        if siparis and siparis.cari and siparis.cari not in tedarikciler:
            tedarikciler.append(siparis.cari)
        if cari and cari not in tedarikciler:
            tedarikciler.append(cari)
        self.tedarikci_map = {f"{c.cari_kodu} - {c.unvan}": c for c in tedarikciler}
        self.tedarikci = tk.StringVar()

        ust = ttk.LabelFrame(self, text="Sipariş Bilgileri", padding=6)
        ust.pack(fill="x", padx=10, pady=(8, 4))
        self._genel_olustur(ust)

        aciklama_fr = ttk.Frame(self, padding=(10, 0))
        aciklama_fr.pack(fill="x")
        ttk.Label(aciklama_fr, text="Açıklama").pack(side="left")
        self.girdiler["aciklama"] = ttk.Entry(aciklama_fr)
        self.girdiler["aciklama"].pack(side="left", fill="x", expand=True, padx=8)

        orta = ttk.LabelFrame(self, text="Satırlar", padding=8)
        orta.pack(fill="both", expand=True, padx=10, pady=4)
        self.satir_tablosu = ttk.Treeview(
            orta, columns=("kod", "ad", "miktar", "birim", "fiyat", "isk", "kdv", "tutar"),
            show="headings", height=10,
        )
        for kolon, baslik, w in (
            ("kod", "Kod", 100), ("ad", "Ad", 200), ("miktar", "Miktar", 80),
            ("birim", "Birim", 70), ("fiyat", "Alış Fiyatı", 100), ("isk", "İsk%", 60),
            ("kdv", "KDV%", 60), ("tutar", "Satır Tutarı", 110),
        ):
            self.satir_tablosu.heading(kolon, text=baslik)
            self.satir_tablosu.column(kolon, width=w)
        self.satir_tablosu.pack(fill="both", expand=True)
        self._alis_girisi_kur()
        satir_btn = ttk.Frame(orta)
        satir_btn.pack(fill="x", pady=4)
        ttk.Label(
            satir_btn, text="Son satıra ürün kodu/adı yazın veya barkod okutun · F10 stok listesi",
            foreground="#627D98",
        ).pack(side="left")
        ttk.Button(satir_btn, text="Satır Sil (Del)", command=self.satir_sil).pack(side="left", padx=6)
        ttk.Button(satir_btn, text="Talepten Aktar", command=self.talepten_aktar).pack(side="left", padx=6)
        ttk.Button(satir_btn, text="Bağlı Talepler", command=self.bagli_talepler).pack(side="left")
        self.satir_ozet = ttk.Label(satir_btn, text="Sipariş tutarı: 0,00 TL")
        self.satir_ozet.pack(side="right")

        odeme_cerceve = ttk.LabelFrame(self, text="Ödemeler / Avans", padding=8)
        odeme_cerceve.pack(fill="x", padx=10, pady=4)
        self.odeme_tablosu = ttk.Treeview(
            odeme_cerceve, columns=("tarih", "tutar", "sekil", "hesap"), show="headings", height=4,
        )
        for kolon, baslik in (("tarih", "Tarih"), ("tutar", "Tutar"), ("sekil", "Şekil"), ("hesap", "Hesap")):
            self.odeme_tablosu.heading(kolon, text=baslik)
            self.odeme_tablosu.column(kolon, width=120)
        self.odeme_tablosu.pack(fill="x")
        odeme_btn = ttk.Frame(odeme_cerceve)
        odeme_btn.pack(fill="x", pady=4)
        ttk.Button(odeme_btn, text="Ödeme Ekle", command=self.odeme_ekle).pack(side="left")
        ttk.Button(odeme_btn, text="Ödeme Sil", command=self.odeme_sil).pack(side="left", padx=6)

        alt = ttk.Frame(self, padding=10)
        alt.pack(fill="x")
        ttk.Button(alt, text="Kapat", command=self.destroy).pack(side="right")
        ttk.Button(alt, text="Kaydet", command=self.kaydet).pack(side="right", padx=8)

        if siparis:
            self._doldur()
        elif cari:
            anahtar = _tedarikci_ekle(self.tedarikci_map, cari)
            self.tedarikci_combo["values"] = list(self.tedarikci_map)
            if anahtar:
                self.tedarikci.set(anahtar)
                self._tedarikci_kart_uygula()
        else:
            self._bakiye_guncelle()
        if hazir_satirlar:
            self.talep_satirlarini_ekle(hazir_satirlar)

    def talep_satirlarini_ekle(self, satirlar: list[dict]) -> None:
        """Talep servisinden hazırlanan satırlar; aynı ürün/birimdeki talep satırıyla birleşir."""
        for yeni in satirlar:
            hedef = next(
                (s for s in self.satirlar
                 if s.get("talep_paylari") and s["urun_kodu"] == yeni["urun_kodu"]
                 and (s.get("birim") or "").casefold() == (yeni.get("birim") or "").casefold()
                 and not any(decimal(s.get(k) or 0, "M", Decimal("0")) > 0
                             for k in ("irsaliyelenen_miktar", "faturalanan_miktar"))),
                None,
            )
            if hedef is None:
                self.satirlar.append(dict(yeni, talep_paylari=list(yeni.get("talep_paylari") or [])))
                continue
            hedef["miktar"] = decimal(hedef["miktar"], "Miktar", Decimal("0")) + decimal(yeni["miktar"], "Miktar")
            hedef["talep_paylari"] = list(hedef["talep_paylari"]) + list(yeni.get("talep_paylari") or [])
        self._satir_listesini_yenile()

    def bagli_talepler(self):
        from satin_alma_talep_ui import SiparisTalepleriDialog

        if not self.siparis:
            messagebox.showinfo("Bağlı Talepler", "Sipariş henüz kaydedilmedi.", parent=self)
            return None
        return SiparisTalepleriDialog(self, self.siparis.id, self.siparis.siparis_no)

    def talepten_aktar(self):
        from database.satin_alma_talep_service import SatinAlmaTalepService
        from satin_alma_talep_ui import TalepAktarDialog

        if not self._alis_bekleyenleri_uygula():
            return
        dlg = TalepAktarDialog(self)
        self.wait_window(dlg)
        if not dlg.result:
            return
        mevcut: dict[int, Decimal] = {}
        for s in self.satirlar:
            for p in s.get("talep_paylari") or []:
                mevcut[int(p["talep_satiri_id"])] = mevcut.get(int(p["talep_satiri_id"]), Decimal("0")) + Decimal(
                    str(p["miktar"]))
        if self.siparis:
            onceki = SatinAlmaTalepService.siparis_paylari(self.siparis.id)
            for paylar in onceki.values():
                for p in paylar:
                    mevcut[int(p["talep_satiri_id"])] = mevcut.get(int(p["talep_satiri_id"]), Decimal("0")) - p["miktar"]
        cakisan = [sid for sid in dlg.result if mevcut.get(sid, Decimal("0")) > 0]
        if cakisan:
            messagebox.showwarning(
                "Talepten Aktar", "Seçilen talep satırlarının bir kısmı bu siparişe zaten eklenmiş (henüz kaydedilmemiş).",
                parent=self,
            )
            return
        try:
            hazir = SatinAlmaTalepService.siparis_satirlari_hazirla(dlg.result)
        except (ValueError, PermissionError) as hata:
            messagebox.showerror("Talepten Aktar", str(hata), parent=self)
            return
        self.talep_satirlarini_ekle(hazir["satirlar"])

    def _genel_olustur(self, parent):
        """Üst kısım: 4 eşit bölme — Sipariş | Vade | Tedarikçi | Bakiyeler."""
        for i in range(4):
            parent.columnconfigure(i, weight=1, uniform="alis_siparis_ust")
        parent.rowconfigure(0, weight=1)

        def _kart(column, baslik, arka_plan):
            cerceve = tk.Frame(parent, bg=arka_plan, bd=1, relief="solid", padx=10, pady=10)
            cerceve.grid(row=0, column=column, sticky="nsew", padx=6, pady=4)
            tk.Label(
                cerceve, text=baslik, bg=arka_plan, fg="#1F2937", font=("Segoe UI", 10, "bold")
            ).pack(anchor="w", pady=(0, 8))
            return cerceve

        siparis_karti = _kart(0, "Sipariş", "#FFF7CC")
        ttk.Label(siparis_karti, text="Sipariş No").pack(anchor="w")
        self.girdiler["siparis_no"] = ttk.Entry(siparis_karti, width=28)
        siparis_no = self.siparis.siparis_no if self.siparis else AlisSiparisiService.siparis_no()
        self.girdiler["siparis_no"].insert(0, siparis_no)
        self.girdiler["siparis_no"].pack(fill="x", pady=(0, 6))
        if self.siparis:
            self.girdiler["siparis_no"].configure(state="readonly")
        ttk.Label(siparis_karti, text="Sipariş Tarihi").pack(anchor="w")
        self.girdiler["siparis_tarihi"] = ttk.Entry(siparis_karti, width=28)
        siparis_tarihi = (
            tarih_goster(self.siparis.siparis_tarihi)
            if self.siparis
            else date.today().strftime("%d.%m.%Y")
        )
        self.girdiler["siparis_tarihi"].insert(0, siparis_tarihi)
        self.girdiler["siparis_tarihi"].pack(fill="x")
        self.girdiler["siparis_tarihi"].bind("<FocusOut>", self._termin_tarih_uygula)

        vade_karti = _kart(1, "Vade", "#FFFFFF")
        ttk.Label(vade_karti, text="Termin Günü").pack(anchor="w")
        self.girdiler["termin_gun"] = ttk.Entry(vade_karti, width=20)
        self.girdiler["termin_gun"].pack(fill="x", pady=(0, 6))
        self.girdiler["termin_gun"].bind("<KeyRelease>", self._termin_tarih_uygula)
        if self.siparis and self.siparis.siparis_tarihi and self.siparis.termin_tarihi:
            termin_gun = (self.siparis.termin_tarihi - self.siparis.siparis_tarihi).days
            self.girdiler["termin_gun"].insert(0, str(termin_gun))
        else:
            self.girdiler["termin_gun"].insert(0, "0")
        ttk.Label(vade_karti, text="Termin Tarihi").pack(anchor="w")
        self.girdiler["termin_tarihi"] = ttk.Entry(vade_karti, width=20)
        termin_tarihi = (
            tarih_goster(self.siparis.termin_tarihi)
            if self.siparis
            else date.today().strftime("%d.%m.%Y")
        )
        self.girdiler["termin_tarihi"].insert(0, termin_tarihi)
        self.girdiler["termin_tarihi"].pack(fill="x")

        tedarikci_karti = _kart(2, "Tedarikçi", "#FFF7CC")
        ttk.Label(tedarikci_karti, text="Tedarikçi Kodu").pack(anchor="w")
        self.girdiler["tedarikci_kodu"] = ttk.Entry(tedarikci_karti, width=28, state="readonly")
        self.girdiler["tedarikci_kodu"].pack(fill="x", pady=(0, 6))
        ttk.Label(tedarikci_karti, text="Tedarikçi Adı").pack(anchor="w")
        self.girdiler["tedarikci_adi"] = ttk.Entry(tedarikci_karti, width=28, state="readonly")
        self.girdiler["tedarikci_adi"].pack(fill="x", pady=(0, 6))
        ttk.Label(tedarikci_karti, text="Seç / Ara").pack(anchor="w")
        self.tedarikci_combo = ttk.Combobox(
            tedarikci_karti, textvariable=self.tedarikci, values=list(self.tedarikci_map),
            state="normal", width=28,
        )
        self.tedarikci_combo.pack(fill="x")
        self.tedarikci_combo.bind("<<ComboboxSelected>>", self._tedarikci_kart_uygula)
        self.tedarikci_combo.bind("<KeyRelease>", self._tedarikci_arama_filtrele)

        bakiye_karti = _kart(3, "Bakiyeler", "#F4F7FF")
        ttk.Label(bakiye_karti, text="Bakiye").pack(anchor="w")
        self.girdiler["mevcut_bakiye"] = ttk.Entry(bakiye_karti, width=25, state="readonly")
        self.girdiler["mevcut_bakiye"].insert(0, "—")
        self.girdiler["mevcut_bakiye"].pack(fill="x", pady=(0, 6))
        ttk.Label(bakiye_karti, text="Yeni Bakiye").pack(anchor="w")
        self.girdiler["yeni_bakiye"] = ttk.Entry(bakiye_karti, width=25, state="readonly")
        self.girdiler["yeni_bakiye"].insert(0, "—")
        self.girdiler["yeni_bakiye"].pack(fill="x", pady=(0, 6))
        ttk.Label(
            bakiye_karti,
            text="Yeni = bakiye + sipariş tutarı",
            font=("Segoe UI", 8),
        ).pack(anchor="w")
        ttk.Label(bakiye_karti, text="Sipariş Durumu").pack(anchor="w", pady=(8, 0))
        self.durum = ttk.Combobox(
            bakiye_karti,
            values=("AÇIK", "KISMİ İRSALİYELİ", "İRSALİYELİ", "KISMİ FATURALI", "FATURALI", "İPTAL"),
            state="readonly",
            width=25,
        )
        self.durum.pack(fill="x")
        self.durum.set(self.siparis.durum if self.siparis else "AÇIK")
        ttk.Label(bakiye_karti, text="Şube").pack(anchor="w", pady=(8, 0))
        from sube_ui import sube_secim_hazirla

        self.sube, self._sube_map = sube_secim_hazirla(
            bakiye_karti, getattr(self.siparis, "sube_id", None) if self.siparis else None
        )
        self.sube.pack(fill="x")

    def _termin_tarih_uygula(self, _event=None):
        try:
            gun = self.girdiler["termin_gun"].get().strip()
            if not gun:
                return
            termin_gun = int(gun)
            tarih_metin = self.girdiler["siparis_tarihi"].get().strip()
            siparis_tarihi = (
                datetime.strptime(tarih_metin, "%d.%m.%Y").date() if tarih_metin else date.today()
            )
            yeni_tarih = siparis_tarihi + timedelta(days=termin_gun)
            self.girdiler["termin_tarihi"].delete(0, "end")
            self.girdiler["termin_tarihi"].insert(0, tarih_goster(yeni_tarih))
        except (KeyError, TypeError, ValueError):
            pass

    def _tedarikci_kart_uygula(self, _event=None):
        secili = self.tedarikci_map.get(self.tedarikci.get())
        for alan, deger in (
            ("tedarikci_kodu", secili.cari_kodu if secili else ""),
            ("tedarikci_adi", secili.unvan if secili else ""),
        ):
            widget = self.girdiler.get(alan)
            if widget is None:
                continue
            widget.configure(state="normal")
            widget.delete(0, "end")
            widget.insert(0, deger)
            widget.configure(state="readonly")
        self._bakiye_guncelle()

    def _tedarikci_arama_filtrele(self, _event=None):
        sorgu = turkce_normalize(self.tedarikci.get().strip())
        if len(sorgu) < 2:
            self.tedarikci_combo.configure(values=())
            return
        eslesenler = [
            etiket
            for etiket, cari in self.tedarikci_map.items()
            if sorgu in turkce_normalize(cari.unvan or "") or sorgu in turkce_normalize(cari.cari_kodu or "")
        ]
        self.tedarikci_combo.configure(values=eslesenler)
        if eslesenler:
            try:
                self.tedarikci_combo.tk.call("ttk::combobox::Post", self.tedarikci_combo._w)
            except tk.TclError:
                pass

    def _readonly_yaz(self, alan, deger):
        widget = self.girdiler.get(alan)
        if widget is None:
            return
        widget.configure(state="normal")
        widget.delete(0, "end")
        widget.insert(0, deger)
        widget.configure(state="readonly")

    def _siparis_tutari(self) -> Decimal:
        ara = Decimal("0")
        iskonto = Decimal("0")
        kdv = Decimal("0")
        for s in self.satirlar:
            miktar = decimal(s.get("miktar") or 0, "Miktar", Decimal("0"))
            fiyat = decimal(s.get("birim_alis_fiyati") or 0, "Fiyat", Decimal("0"))
            isk = decimal(s.get("iskonto_orani") or 0, "İskonto", Decimal("0"))
            kdv_o = decimal(s.get("kdv_orani") or 0, "KDV", Decimal("0"))
            brut = miktar * fiyat
            indirim = brut * isk / Decimal("100")
            net = brut - indirim
            ara += brut
            iskonto += indirim
            kdv += net * kdv_o / Decimal("100")
        return (ara - iskonto) + kdv

    def _satir_tutari(self, s: dict) -> Decimal:
        miktar = decimal(s.get("miktar") or 0, "Miktar", Decimal("0"))
        fiyat = decimal(s.get("birim_alis_fiyati") or 0, "Fiyat", Decimal("0"))
        isk = decimal(s.get("iskonto_orani") or 0, "İskonto", Decimal("0"))
        kdv_o = decimal(s.get("kdv_orani") or 0, "KDV", Decimal("0"))
        brut = miktar * fiyat
        net = brut - (brut * isk / Decimal("100"))
        return net + (net * kdv_o / Decimal("100"))

    def _bakiye_guncelle(self):
        from database.cari_service import CariService

        tedarikci = self.tedarikci_map.get(self.tedarikci.get())
        if not tedarikci:
            self.mevcut_borc = Decimal("0")
            self._readonly_yaz("mevcut_bakiye", "—")
            self._readonly_yaz("yeni_bakiye", "—")
            self._toplamlari_guncelle()
            return
        ozet = next(
            (o for o in CariService.listele(hizli=True) if o["cari"].id == tedarikci.id),
            None,
        )
        self.mevcut_borc = ozet["bakiye"] if ozet else Decimal("0")
        self._readonly_yaz("mevcut_bakiye", para_goster(self.mevcut_borc))
        self._toplamlari_guncelle()

    def _toplamlari_guncelle(self):
        siparis_tutari = self._siparis_tutari()
        odeme = sum(
            (decimal(o.get("tutar") or 0, "Ödeme", Decimal("0")) for o in self.odemeler),
            Decimal("0"),
        )
        if hasattr(self, "satir_ozet"):
            self.satir_ozet.configure(
                text=f"Sipariş tutarı: {para_goster(siparis_tutari)} | Ödeme: {para_goster(odeme)}"
            )
        tedarikci = self.tedarikci_map.get(self.tedarikci.get())
        if not tedarikci:
            self._readonly_yaz("yeni_bakiye", "—")
            return
        # Yeni bakiye = mevcut bakiye + bu sipariş tutarı (− ödeme/avans)
        yeni = self.mevcut_borc + siparis_tutari - odeme
        self._readonly_yaz("yeni_bakiye", para_goster(yeni))

    def _satir_listesini_yenile(self):
        for item in self.satir_tablosu.get_children():
            self.satir_tablosu.delete(item)
        for sira, s in enumerate(self.satirlar):
            self.satir_tablosu.insert("", "end", iid=str(sira), values=(
                s["urun_kodu"], s["urun_adi"], s["miktar"], s["birim"],
                para_goster(s["birim_alis_fiyati"]), s.get("iskonto_orani", 0), s.get("kdv_orani", 20),
                para_goster(self._satir_tutari(s)),
            ))
        self._satir_ici_giris.tabloya_ekle()
        self._toplamlari_guncelle()

    def _alis_yenile(self):
        self._satir_listesini_yenile()

    def _odeme_listesini_yenile(self):
        for item in self.odeme_tablosu.get_children():
            self.odeme_tablosu.delete(item)
        for sira, o in enumerate(self.odemeler):
            self.odeme_tablosu.insert("", "end", iid=str(sira), values=(
                tarih_goster(o["odeme_tarihi"]), para_goster(o["tutar"]),
                o["odeme_sekli"], o.get("hesap") or "",
            ))
        self._toplamlari_guncelle()

    def odeme_ekle(self):
        dialog = AlisSiparisOdemeDialog(self)
        self.wait_window(dialog)
        if dialog.result:
            self.odemeler.append(dialog.result)
            self._odeme_listesini_yenile()

    def odeme_sil(self):
        secim = self.odeme_tablosu.selection()
        if secim:
            self.odemeler.pop(int(secim[0]))
            self._odeme_listesini_yenile()

    def _doldur(self):
        s = self.siparis
        anahtar = _tedarikci_ekle(self.tedarikci_map, s.cari)
        self.tedarikci_combo["values"] = list(self.tedarikci_map)
        if anahtar:
            self.tedarikci.set(anahtar)
        self.girdiler["siparis_tarihi"].configure(state="normal")
        self.girdiler["siparis_tarihi"].delete(0, "end")
        self.girdiler["siparis_tarihi"].insert(0, tarih_goster(s.siparis_tarihi))
        self.girdiler["termin_tarihi"].delete(0, "end")
        self.girdiler["termin_tarihi"].insert(0, tarih_goster(s.termin_tarihi))
        self.girdiler["aciklama"].delete(0, "end")
        self.girdiler["aciklama"].insert(0, s.aciklama or "")
        if hasattr(self, "durum"):
            self.durum.set(s.durum or "AÇIK")
        self.satirlar.clear()
        self.odemeler.clear()
        from database.satin_alma_talep_service import SatinAlmaTalepService

        talep_paylari = SatinAlmaTalepService.siparis_paylari(s.id)
        for satir in s.satirlar:
            self.satirlar.append({
                "talep_paylari": talep_paylari.get(int(satir.id), []),
                "urun_kodu": satir.urun_kodu, "urun_adi": satir.urun_adi,
                "aciklama": satir.aciklama or "", "miktar": satir.miktar, "birim": satir.birim,
                "birim_alis_fiyati": satir.birim_alis_fiyati,
                "iskonto_orani": satir.iskonto_orani,
                "iskonto_orani_2": getattr(satir, "iskonto_orani_2", 0) or 0,
                "iskonto_orani_3": getattr(satir, "iskonto_orani_3", 0) or 0,
                "kdv_orani": satir.kdv_orani,
                "irsaliyelenen_miktar": satir.irsaliyelenen_miktar,
                "faturalanan_miktar": satir.faturalanan_miktar,
            })
        for odeme in s.odemeler:
            self.odemeler.append({
                "odeme_tarihi": odeme.odeme_tarihi, "tutar": odeme.tutar,
                "odeme_sekli": odeme.odeme_sekli, "hesap": odeme.hesap or "",
                "aciklama": odeme.aciklama or "",
            })
        self._tedarikci_kart_uygula()
        self._satir_listesini_yenile()
        self._odeme_listesini_yenile()

    def kaydet(self):
        tedarikci = self.tedarikci_map.get(self.tedarikci.get())
        if not tedarikci:
            messagebox.showwarning("Eksik", "Tedarikçi seçin.", parent=self)
            return
        if not self._alis_bekleyenleri_uygula():
            return
        if not self.satirlar:
            messagebox.showwarning("Eksik", "En az bir satır ekleyin.", parent=self)
            return
        try:
            veriler = {
                "siparis_no": self.girdiler["siparis_no"].get().strip(),
                "siparis_tarihi": datetime.strptime(self.girdiler["siparis_tarihi"].get(), "%d.%m.%Y").date(),
                "termin_tarihi": datetime.strptime(self.girdiler["termin_tarihi"].get(), "%d.%m.%Y").date(),
                "cari_id": tedarikci.id,
                "sube_id": self._sube_map.get(self.sube.get()),
                "aciklama": self.girdiler["aciklama"].get().strip() or None,
                "row_version": int(getattr(self.siparis, "row_version", 1) or 1) if self.siparis else None,
            }
            AlisSiparisiService.kaydet(
                veriler, self.satirlar, self.odemeler,
                self.siparis.id if self.siparis else None,
            )
        except ValueError as hata:
            messagebox.showerror("Kayıt", str(hata), parent=self)
            return
        self.result = True
        self.destroy()


class AlisIrsaliyesiDialog(_AlisSatirGirisi, tk.Toplevel):
    _fiyat_alani = "birim_fiyat"

    def __init__(self, parent, irsaliye=None, siparis=None, cari=None):
        super().__init__(parent)
        self.irsaliye = irsaliye
        self.result = None
        self.title("SATIN ALMA İRSALİYESİ")
        self.geometry("1000x620")
        self.transient(parent)
        self.grab_set()
        self.satirlar = []
        tedarikciler = list(AlisIrsaliyesiService.aktif_tedarikcileri())
        for belge in (irsaliye, siparis):
            if belge and belge.cari and belge.cari not in tedarikciler:
                tedarikciler.append(belge.cari)
        if cari and cari not in tedarikciler:
            tedarikciler.append(cari)
        self.tedarikci_map = {f"{c.cari_kodu} - {c.unvan}": c for c in tedarikciler}
        acik_siparisler = list(AlisIrsaliyesiService.acik_siparisler())
        if siparis and siparis.siparis_no not in {s.siparis_no for s in acik_siparisler}:
            acik_siparisler.append(siparis)
        if irsaliye and irsaliye.siparis and irsaliye.siparis.siparis_no not in {s.siparis_no for s in acik_siparisler}:
            acik_siparisler.append(irsaliye.siparis)
        self.siparis_map = {s.siparis_no: s for s in acik_siparisler}
        self.tedarikci = tk.StringVar()
        self.siparis_secimi = tk.StringVar()
        ust = ttk.LabelFrame(self, text="İrsaliye", padding=10)
        ust.pack(fill="x", padx=10, pady=8)
        ttk.Label(ust, text="Tedarikçi").grid(row=0, column=0, sticky="w")
        self.tedarikci_combo = ttk.Combobox(ust, textvariable=self.tedarikci, values=list(self.tedarikci_map), width=40)
        self.tedarikci_combo.grid(row=0, column=1, sticky="w", padx=6)
        ttk.Label(ust, text="Sipariş").grid(row=1, column=0, sticky="w")
        self.siparis_combo = ttk.Combobox(
            ust, textvariable=self.siparis_secimi, values=list(self.siparis_map), width=40,
        )
        self.siparis_combo.grid(row=1, column=1, sticky="w", padx=6)
        ttk.Button(ust, text="Siparişten Doldur", command=self.siparisten_doldur).grid(row=1, column=2, padx=6)
        self.tarih = ttk.Entry(ust, width=18)
        self.tarih.insert(0, date.today().strftime("%d.%m.%Y"))
        ttk.Label(ust, text="Tarih").grid(row=2, column=0, sticky="w")
        self.tarih.grid(row=2, column=1, sticky="w", padx=6)
        self.aciklama = ttk.Entry(ust, width=42)
        ttk.Label(ust, text="Açıklama").grid(row=3, column=0, sticky="w")
        self.aciklama.grid(row=3, column=1, sticky="w", padx=6)
        ttk.Label(ust, text="Şube").grid(row=4, column=0, sticky="w")
        from sube_ui import sube_secim_hazirla

        self.sube, self._sube_map = sube_secim_hazirla(
            ust, getattr(irsaliye, "sube_id", None) if irsaliye else getattr(siparis, "sube_id", None)
        )
        self.sube.grid(row=4, column=1, sticky="w", padx=6)

        orta = ttk.LabelFrame(self, text="Satırlar", padding=8)
        orta.pack(fill="both", expand=True, padx=10)
        self.satir_tablosu = ttk.Treeview(
            orta, columns=("kod", "ad", "miktar", "birim", "fiyat"), show="headings",
        )
        for kolon, baslik, w in (
            ("kod", "Kod", 100), ("ad", "Ad", 220), ("miktar", "Miktar", 80),
            ("birim", "Birim", 70), ("fiyat", "Fiyat", 100),
        ):
            self.satir_tablosu.heading(kolon, text=baslik)
            self.satir_tablosu.column(kolon, width=w)
        self.satir_tablosu.pack(fill="both", expand=True)
        self._alis_girisi_kur()
        btn = ttk.Frame(orta)
        btn.pack(fill="x", pady=4)
        ttk.Label(
            btn, text="Son satıra ürün kodu/adı yazın veya barkod okutun · F10 stok listesi",
            foreground="#627D98",
        ).pack(side="left")
        ttk.Button(btn, text="Satır Sil (Del)", command=self.satir_sil).pack(side="left", padx=6)

        alt = ttk.Frame(self, padding=10)
        alt.pack(fill="x")
        ttk.Button(alt, text="Kapat", command=self.destroy).pack(side="right")
        ttk.Button(alt, text="Kaydet", command=self.kaydet).pack(side="right", padx=8)

        if irsaliye:
            self._doldur()
        elif siparis:
            self.siparis_secimi.set(siparis.siparis_no)
            self.siparisten_doldur()
        elif cari:
            anahtar = _tedarikci_ekle(self.tedarikci_map, cari)
            self.tedarikci_combo["values"] = list(self.tedarikci_map)
            if anahtar:
                self.tedarikci.set(anahtar)

    def _yenile(self):
        for item in self.satir_tablosu.get_children():
            self.satir_tablosu.delete(item)
        for sira, s in enumerate(self.satirlar):
            self.satir_tablosu.insert("", "end", iid=str(sira), values=(
                s["urun_kodu"], s["urun_adi"], s["miktar"], s["birim"], para_goster(s["birim_fiyat"]),
            ))
        self._satir_ici_giris.tabloya_ekle()

    def _alis_yenile(self):
        self._yenile()

    def _siparis_coz(self):
        no = self.siparis_secimi.get().strip()
        if not no:
            return None
        siparis = self.siparis_map.get(no)
        if siparis:
            return siparis
        siparis = next(
            (s for s in AlisIrsaliyesiService.acik_siparisler() if s.siparis_no == no),
            None,
        )
        if siparis:
            self.siparis_map[siparis.siparis_no] = siparis
            self.siparis_combo["values"] = list(self.siparis_map)
        return siparis

    def siparisten_doldur(self):
        siparis = self._siparis_coz()
        if not siparis:
            return
        anahtar = _tedarikci_ekle(self.tedarikci_map, siparis.cari)
        self.tedarikci_combo["values"] = list(self.tedarikci_map)
        if anahtar:
            self.tedarikci.set(anahtar)
        self.satirlar.clear()
        for satir in siparis.satirlar:
            acik = satir.miktar - satir.irsaliyelenen_miktar
            if acik > 0:
                self.satirlar.append({
                    "siparis_satiri_id": satir.id,
                    "urun_kodu": satir.urun_kodu, "urun_adi": satir.urun_adi,
                    "aciklama": satir.aciklama or "", "miktar": acik, "birim": satir.birim,
                    "birim_fiyat": satir.birim_alis_fiyati,
                    "iskonto_orani": satir.iskonto_orani, "iskonto_orani_2": getattr(satir, "iskonto_orani_2", 0) or 0, "iskonto_orani_3": getattr(satir, "iskonto_orani_3", 0) or 0, "kdv_orani": satir.kdv_orani,
                })
        self._yenile()

    def _doldur(self):
        i = self.irsaliye
        anahtar = _tedarikci_ekle(self.tedarikci_map, i.cari)
        self.tedarikci_combo["values"] = list(self.tedarikci_map)
        if anahtar:
            self.tedarikci.set(anahtar)
        self.tarih.delete(0, "end")
        self.tarih.insert(0, tarih_goster(i.irsaliye_tarihi))
        self.aciklama.insert(0, i.aciklama or "")
        if i.siparis:
            self.siparis_map[i.siparis.siparis_no] = i.siparis
            self.siparis_combo["values"] = list(self.siparis_map)
            self.siparis_secimi.set(i.siparis.siparis_no)
        for satir in i.satirlar:
            self.satirlar.append({
                "siparis_satiri_id": satir.siparis_satiri_id,
                "urun_kodu": satir.urun_kodu, "urun_adi": satir.urun_adi,
                "aciklama": satir.aciklama or "", "miktar": satir.miktar, "birim": satir.birim,
                "birim_fiyat": satir.birim_fiyat, "iskonto_orani": satir.iskonto_orani,
                "iskonto_orani_2": getattr(satir, "iskonto_orani_2", 0) or 0,
                "iskonto_orani_3": getattr(satir, "iskonto_orani_3", 0) or 0,
                "kdv_orani": satir.kdv_orani,
            })
        self._yenile()

    def kaydet(self):
        tedarikci = self.tedarikci_map.get(self.tedarikci.get())
        if not tedarikci:
            messagebox.showwarning("Eksik", "Tedarikçi seçin.", parent=self)
            return
        if not self._alis_bekleyenleri_uygula():
            return
        siparis = self._siparis_coz()
        siparis_id = siparis.id if siparis else (self.irsaliye.siparis_id if self.irsaliye else None)
        try:
            AlisIrsaliyesiService.kaydet(
                {
                    "irsaliye_tarihi": datetime.strptime(self.tarih.get(), "%d.%m.%Y").date(),
                    "cari_id": tedarikci.id,
                    "sube_id": self._sube_map.get(self.sube.get()),
                    "siparis_id": siparis_id,
                    "aciklama": self.aciklama.get().strip() or None,
                    "ayrintili_notlar": None,
                    "row_version": int(getattr(self.irsaliye, "row_version", 1) or 1)
                    if self.irsaliye
                    else None,
                },
                self.satirlar,
                self.irsaliye.id if self.irsaliye else None,
            )
        except ValueError as hata:
            messagebox.showerror("Kayıt", str(hata), parent=self)
            return
        self.result = True
        self.destroy()


class AlisFaturasiDialog(tk.Toplevel):
    """Satış faturası kartına denk, satın alma (alış) faturası kartı."""

    _print_belge_turu = ALIS_BELGE_BASLIGI
    _print_belge_no_etiketi = "Kayıt No"
    _print_ters_renk = True

    def __init__(self, parent, fatura=None, siparis=None, irsaliye=None, cari=None, cari_ac=None):
        super().__init__(parent)
        self.fatura = fatura
        self.kaynak_siparis = siparis
        self.kaynak_irsaliye = irsaliye
        self.cari_ac = cari_ac
        self.result = None
        self._fatura_form_kirli = False
        self._fatura_yukleniyor = True
        self.title("Alış Fatura Kartı")
        from ui_pencere import belge_penceresini_hazirla

        belge_penceresini_hazirla(
            self,
            min_genislik=900,
            min_yukseklik=520,
            varsayilan_genislik=1200,
            varsayilan_yukseklik=720,
            maximize=True,
        )
        self.transient(parent)
        self.grab_set()
        self.satirlar = []
        self.odemeler = []
        self.mevcut_borc = Decimal("0")

        tedarikciler = list(AlisFaturasiService.aktif_tedarikcileri())
        for belge in (fatura, siparis, irsaliye):
            if belge and belge.cari and belge.cari not in tedarikciler:
                tedarikciler.append(belge.cari)
        if cari and cari not in tedarikciler:
            tedarikciler.append(cari)
        self.tedarikci_map = {f"{c.cari_kodu} - {c.unvan}": c for c in tedarikciler}
        self.girdiler = {}
        self._cari_ozet = {"bakiye": Decimal("0"), "ortalama_vade": None}

        try:
            ftema.stil_uygula(root=self)
        except Exception:
            pass
        try:
            self.configure(bg=ftema.ACIK_BG)
        except tk.TclError:
            pass
        self._alis_stilleri_kur()
        self._alis_toolbar_kur()
        self.bind("<F1>", self._f1_kaydet)
        self.bind("<F3>", self._f3_fatura_listesi)
        self.bind_all("<F1>", self._f1_kaydet)
        self.bind("<Escape>", lambda _e: self.kapat_istegi())
        self.protocol("WM_DELETE_WINDOW", self.kapat_istegi)
        self.bind("<KeyRelease>", self._form_tus_degisti, add="+")
        self.bind("<<ComboboxSelected>>", self._form_degisti, add="+")
        from kapatma_detay_ui import OdemeKapatmaBilgisi

        self._odeme_kapatma_bilgisi = OdemeKapatmaBilgisi(
            self,
            fatura_turu="ALIS",
            fatura_id_getir=lambda: getattr(self.fatura, "id", None) if self.fatura else None,
        )
        self._odeme_kapatma_bilgisi.pack(side="bottom", fill="x", padx=10, pady=(0, 4))
        self._odeme_kapatma_bilgisi.yenile()

        kaydirma_alani = ttk.Frame(self, padding=(6, 4))
        kaydirma_alani.pack(fill="both", expand=True)
        self._kaydirma_alani = kaydirma_alani
        self.canvas = tk.Canvas(kaydirma_alani, highlightthickness=0, bg=ftema.ACIK_BG)
        dikey_kaydirma = ttk.Scrollbar(kaydirma_alani, orient="vertical", command=self.canvas.yview)
        self.canvas.configure(yscrollcommand=dikey_kaydirma.set)
        dikey_kaydirma.pack(side="right", fill="y")
        self.canvas.pack(side="left", fill="both", expand=True)
        self.icerik = ttk.Frame(self.canvas, padding=6)
        pencere = self.canvas.create_window((0, 0), window=self.icerik, anchor="nw")
        self.icerik.bind("<Configure>", lambda _e: self.canvas.configure(scrollregion=self.canvas.bbox("all")))
        self.canvas.bind("<Configure>", lambda e: self.canvas.itemconfigure(pencere, width=e.width))
        self.canvas.bind_all("<MouseWheel>", self._fare_tekerlegi)

        self._ust_paneller_olustur()
        self._doviz_cerceve = ttk.LabelFrame(
            self.icerik, text="Döviz / Kur", padding=6, style="AlisUst.TLabelframe"
        )
        self._doviz_fiyat_alani = "birim_fiyat"
        doviz_paneli_kur(self, self._doviz_cerceve)
        satir_sayfasi = ttk.LabelFrame(
            self.icerik, text="ÜRÜN SATIRLARI", padding=8, style="AlisUst.TLabelframe"
        )
        satir_sayfasi.pack(fill="both", expand=True, pady=4)
        self._satir_sayfasi = satir_sayfasi
        self._satir_olustur(satir_sayfasi)
        alt = ttk.Frame(self.icerik)
        alt.pack(fill="x", pady=4)
        alt.columnconfigure(0, weight=1)
        alt.columnconfigure(1, weight=1)
        self._odeme_olustur(alt)
        self._notlar_olustur(alt)

        if fatura:
            self._faturayi_doldur()
        elif irsaliye:
            self._irsaliyeyi_doldur(irsaliye)
        elif siparis:
            self._siparis_yukle(siparis)
        elif cari:
            anahtar = _tedarikci_ekle(self.tedarikci_map, cari)
            self.tedarikci_combo["values"] = list(self.tedarikci_map)
            if anahtar:
                self.tedarikci.set(anahtar)
                self._bakiye_guncelle()
        self.vade_tarih_degisti()
        self._toplamlari_guncelle()
        self._alis_sticky_footer_kur()
        self._doviz_gorunumu_guncelle()
        self._toolbar_guncelle()
        ftema.renkleri_tersle(self, haric=[self._alis_toolbar["rozet"]])
        self._fatura_yukleniyor = False
        self._fatura_form_kirli = False

    def _tooltip_bagla(self, widget, metin: str):
        tip = {"win": None}

        def _goster(_e=None):
            if tip["win"] is not None:
                return
            try:
                x = widget.winfo_rootx() + 8
                y = widget.winfo_rooty() + widget.winfo_height() + 4
            except tk.TclError:
                return
            win = tk.Toplevel(widget)
            win.wm_overrideredirect(True)
            win.wm_geometry(f"+{x}+{y}")
            tk.Label(
                win,
                text=metin,
                bg="#fff8dc",
                fg="#1a1a1a",
                relief="solid",
                bd=1,
                padx=6,
                pady=3,
                font=("Segoe UI", 9),
            ).pack()
            tip["win"] = win

        def _gizle(_e=None):
            win = tip["win"]
            tip["win"] = None
            if win is not None:
                try:
                    win.destroy()
                except tk.TclError:
                    pass

        widget.bind("<Enter>", _goster)
        widget.bind("<Leave>", _gizle)

    def _alis_sticky_footer_kur(self):
        """Üst butonlar + orta kaydırma + alt Brüt/Net sabit."""
        from ui_pencere import sticky_footer_layout, calisma_alani

        footer = getattr(self, "_alis_toplam_cerceve", None)
        if footer is None:
            return
        # Satır grid'inden çıkar, alt banda taşı
        try:
            footer.grid_forget()
        except tk.TclError:
            try:
                footer.pack_forget()
            except tk.TclError:
                pass
        alt = tk.Frame(self, bg=ftema.ACIK_BG)
        footer.pack(in_=alt, fill="x", padx=6, pady=(2, 4))
        footer.lift(alt)
        sticky_footer_layout(
            self,
            ust=getattr(self, "_alis_ust_butonlar", None),
            orta=getattr(self, "_kaydirma_alani", None),
            alt=alt,
        )
        try:
            _, _, _, ah = calisma_alani(self)
            if hasattr(self, "satir_tablosu"):
                self.satir_tablosu.configure(height=10 if ah < 800 else 14)
            if hasattr(self, "odeme_tablosu"):
                self.odeme_tablosu.configure(height=3 if ah < 800 else 5)
            if hasattr(self, "ayrintili_notlar"):
                self.ayrintili_notlar.configure(height=3 if ah < 800 else 5)
        except Exception:
            pass

    def _fare_tekerlegi(self, event):
        self.canvas.yview_scroll(-int(event.delta / 120), "units")

    def _f1_kaydet(self, _event=None):
        """F1 = Kaydet (alan odaktayken de)."""
        try:
            if not self.winfo_exists():
                return
            odak = self.focus_get()
            if odak is None:
                return
            # Bu diyaloğun parçası değilse yok say
            w = odak
            while w is not None:
                if w == self:
                    self.kaydet()
                    return "break"
                w = w.master if hasattr(w, "master") else None
        except tk.TclError:
            return
        return "break"

    def _f3_fatura_listesi(self, _event=None):
        self._fatura_listesini_ac()
        return "break"

    def _fatura_listesini_ac(self):
        from fatura_liste_pencere import DOC_ALIS, fatura_listesi_ac

        fatura_listesi_ac(self, document_type=DOC_ALIS)

    def _alis_onizleme_ac(self):
        """Geçici PDF önizleme — kalıcı kayıt yok."""
        try:
            if hasattr(self, "_toplamlari_guncelle"):
                self._toplamlari_guncelle()
            from invoice_print.service import InvoicePrintService

            InvoicePrintService.open_pdf_preview(kart=self)
        except ValueError as hata:
            messagebox.showerror("Ön İzleme", str(hata), parent=self)
        except Exception as hata:
            messagebox.showerror(
                "Ön İzleme",
                f"PDF önizleme oluşturulamadı:\n{hata}",
                parent=self,
            )

    def _alis_pdf_kaydet(self):
        """Kalıcı PDF kaydı (kullanıcı klasör seçer)."""
        from pathlib import Path
        from tkinter import filedialog

        from invoice_print.pdf_service import render_invoice_to_pdf, safe_pdf_filename
        from invoice_print.service import InvoicePrintService
        from invoice_print.settings import load_print_settings, save_print_settings

        try:
            if hasattr(self, "_toplamlari_guncelle"):
                self._toplamlari_guncelle()
            vm = InvoicePrintService.build_from_kart(self)
        except ValueError as exc:
            messagebox.showerror("PDF", str(exc), parent=self)
            return
        ayar = load_print_settings()
        baslangic = ayar.get("son_pdf_klasoru") or str(Path.home() / "Documents")
        yol = filedialog.asksaveasfilename(
            parent=self,
            title="PDF Kaydet",
            initialdir=baslangic,
            initialfile=safe_pdf_filename(vm),
            defaultextension=".pdf",
            filetypes=[("PDF", "*.pdf")],
        )
        if not yol:
            return
        try:
            render_invoice_to_pdf(vm, Path(yol))
            ayar["son_pdf_klasoru"] = str(Path(yol).parent)
            save_print_settings(ayar)
            messagebox.showinfo("PDF", f"PDF kaydedildi:\n{yol}", parent=self)
        except ValueError as exc:
            messagebox.showerror("PDF", str(exc), parent=self)

    def _fatura_kirli_mi(self) -> bool:
        if getattr(self, "_fatura_form_kirli", False):
            return True
        if self.fatura is None:
            return bool(self.satirlar) or bool((self.tedarikci.get() or "").strip())
        return False

    def _kaydet_kapatmadan(self) -> bool:
        """Liste geçişi için kaydet; destroy yok."""
        try:
            self._alis_editorleri_uygula()
            tedarikci = self.tedarikci_map.get(self.tedarikci.get())
            if not tedarikci:
                raise ValueError("Aktif bir tedarikçi seçin.")
            if not self.satirlar:
                raise ValueError("En az bir fatura satırı ekleyin.")
            satirlar_hesap = [
                {
                    **dict(s),
                    "birim_fiyat": s.get("birim_alis_fiyati", s.get("birim_fiyat", 0)),
                }
                for s in self.satirlar
            ]
            satir_genel = AlisFaturasiService.toplam(satirlar_hesap)["genel_toplam"]
            self._alis_satir_brut = satir_genel
            self._alis_net_toplam = satir_genel
            fatura_tarihi = datetime.strptime(self.girdiler["fatura_tarihi"].get(), "%d.%m.%Y").date()
            vade_tarihi = datetime.strptime(self.girdiler["vade_tarihi"].get(), "%d.%m.%Y").date()
            islem_saati = saat_dogrula(self.girdiler["islem_saati"].get())
            satirlar = []
            for satir in self.satirlar:
                veri = dict(satir)
                if not veri.get("lot_no"):
                    veri["lot_no"] = StokService.otomatik_lot_no(tedarikci.unvan, fatura_tarihi)
                veri["birim_fiyat"] = veri.get("birim_fiyat", veri.get("birim_alis_fiyati", 0))
                if veri.get("birim_fiyat_doviz") in (None, "", 0, "0"):
                    pb = getattr(self, "_doviz_para_birimi", None)
                    if pb and (pb.get() or "TRY").upper() != "TRY":
                        veri["birim_fiyat_doviz"] = veri["birim_fiyat"]
                satirlar.append(veri)
            odeme_tutari = sum((decimal(o["tutar"], "Ödeme") for o in self.odemeler), Decimal("0"))
            ilk_odeme = self.odemeler[0] if self.odemeler else {}
            siparis_id = self.kaynak_siparis.id if self.kaynak_siparis else (
                self.fatura.siparis_id if self.fatura else None
            )
            irsaliye_id = self.kaynak_irsaliye.id if self.kaynak_irsaliye else (
                self.fatura.irsaliye_id if self.fatura else None
            )
            if not siparis_id and self.kaynak_irsaliye and self.kaynak_irsaliye.siparis_id:
                siparis_id = self.kaynak_irsaliye.siparis_id
            yazilan_siparis = self.siparis_no.get().strip()
            yazilan_irsaliye = self.irsaliye_no.get().strip()
            if yazilan_siparis and not siparis_id:
                eslesen = next(
                    (s for s in AlisFaturasiService.acik_siparisler() if s.siparis_no == yazilan_siparis),
                    None,
                )
                if not eslesen:
                    raise ValueError("Yazılan sipariş numarası bulunamadı.")
                if eslesen.cari_id != tedarikci.id:
                    raise ValueError("Sipariş numarası seçilen tedarikçiye ait değil.")
                siparis_id = eslesen.id
            if yazilan_irsaliye and not irsaliye_id:
                eslesen = next(
                    (i for i in AlisFaturasiService.acik_irsaliyeler() if i.irsaliye_no == yazilan_irsaliye),
                    None,
                )
                if not eslesen:
                    raise ValueError("Yazılan irsaliye numarası bulunamadı.")
                if eslesen.cari_id != tedarikci.id:
                    raise ValueError("İrsaliye numarası seçilen tedarikçiye ait değil.")
                irsaliye_id = eslesen.id
            notlar = self.ayrintili_notlar.get("1.0", "end").strip()
            aciklama = self.girdiler["aciklama"].get().strip()
            if notlar:
                aciklama = f"{aciklama}\n{notlar}".strip() if aciklama else notlar
            veriler = {
                "fatura_no": self.girdiler["fatura_no"].get().strip(),
                "fatura_tarihi": fatura_tarihi,
                "islem_saati": islem_saati,
                "vade_tarihi": vade_tarihi,
                "cari_id": tedarikci.id,
                "sube_id": self._sube_map.get(self.sube.get()),
                "tedarikci_fatura_no": self.girdiler["tedarikci_fatura_no"].get().strip() or None,
                "siparis_id": siparis_id,
                "irsaliye_id": irsaliye_id,
                "depo": self.depo.get(),
                "odeme_tutari": odeme_tutari,
                "odeme_sekli": ilk_odeme.get("odeme_sekli"),
                "odeme_hesabi": ilk_odeme.get("hesap"),
                "aciklama": aciklama or None,
                "dokuman_yolu": self.dokuman.get().strip() or None,
                "row_version": int(getattr(self.fatura, "row_version", 1) or 1)
                if self.fatura
                else None,
                "tl_brut_toplam": getattr(self, "_alis_satir_brut", Decimal("0")),
                "tl_genel_toplam": getattr(self, "_alis_net_toplam", Decimal("0")),
                "genel_islem_turu": None,
                "genel_islem_orani": Decimal("0"),
                "genel_islem_tutari": Decimal("0"),
            }
            if hasattr(self, "_doviz_para_birimi"):
                veriler.update(doviz_verilerini_topla(self))
            self.result = AlisFaturasiService.kaydet(
                veriler,
                satirlar,
                self.fatura.id if self.fatura else None,
            )
            self.fatura = AlisFaturasiService.getir(self.result.id) or self.result
            self.kaynak_siparis = None
            self.kaynak_irsaliye = None
            self._fatura_persisted = True
            self._faturayi_doldur()
            self._toolbar_guncelle()
            return True
        except MukerrerTedarikciFaturaHatasi as hata:
            self._mukerrer_kaydi_goster(
                hata.fatura_id, hata.fatura_no, self.girdiler["tedarikci_fatura_no"].get().strip()
            )
            return False
        except ValueError as hata:
            messagebox.showerror("Fatura kaydedilemedi", str(hata), parent=self)
            return False

    def bagli_listeden_fatura_ac(self, fatura_id: int, *, document_type: str):
        from fatura_liste_pencere import DOC_ALIS
        from database.alis_faturasi_service import AlisFaturasiService

        if document_type != DOC_ALIS:
            raise ValueError("Alış faturası ekranına yalnız alış faturası açılabilir.")
        if self.fatura is not None and getattr(self.fatura, "id", None) == fatura_id:
            return
        if self._fatura_kirli_mi():
            dlg = tk.Toplevel(self)
            dlg.title("Kaydedilmemiş değişiklikler")
            dlg.transient(self)
            dlg.grab_set()
            ttk.Label(
                dlg,
                text="Açık faturada kaydedilmemiş değişiklikler var.\nNe yapmak istersiniz?",
                padding=12,
            ).pack()
            sonuc = {"secim": None}

            def _sec(s):
                sonuc["secim"] = s
                dlg.destroy()

            alt = ttk.Frame(dlg, padding=8)
            alt.pack(fill="x")
            ttk.Button(alt, text="Kaydet ve Aç", command=lambda: _sec("kaydet")).pack(
                side="left", padx=4
            )
            ttk.Button(alt, text="Değişiklikleri At ve Aç", command=lambda: _sec("at")).pack(
                side="left", padx=4
            )
            ttk.Button(alt, text="Vazgeç", command=lambda: _sec("vazgec")).pack(
                side="left", padx=4
            )
            dlg.wait_window()
            if sonuc["secim"] in (None, "vazgec"):
                return
            if sonuc["secim"] == "kaydet":
                if not self._kaydet_kapatmadan():
                    return
        fatura = AlisFaturasiService.getir(fatura_id)
        if not fatura:
            raise ValueError("Fatura bulunamadı.")
        self.fatura = fatura
        self._fatura_form_kirli = False
        self._faturayi_doldur()

    def destroy(self):
        try:
            self.unbind_all("<F1>")
        except tk.TclError:
            pass
        super().destroy()

    def _girdi(self, parent, satir, baslik, alan, deger="", sutun=0, genislik=35, readonly=False):
        ttk.Label(parent, text=baslik, style="AlisUst.TLabel").grid(
            row=satir, column=sutun, padx=(0, 6), pady=ALIS_UST_PADY, sticky="w"
        )
        widget = ttk.Entry(parent, width=genislik, style="FaturaUst.TEntry")
        widget.grid(row=satir, column=sutun + 1, padx=(0, 8), pady=ALIS_UST_PADY, sticky="ew")
        widget.insert(0, deger)
        if readonly:
            widget.configure(state="readonly")
        self.girdiler[alan] = widget
        return widget

    def _alis_stilleri_kur(self):
        stil = ttk.Style(self)
        stil.configure("AlisUst.TLabel", font=ftema.font(9, root=self), foreground="#334155")
        stil.configure("AlisUst.TLabelframe", padding=(10, 8))
        stil.configure(
            "AlisUst.TLabelframe.Label", font=ftema.font(9, "bold", self), foreground=ftema.LACIVERT
        )
        kaynak = "FaturaSatir.Treeview"
        ayar = {}
        for secenek in ("rowheight", "font", "borderwidth", "relief", "fieldbackground", "background", "foreground"):
            deger = stil.lookup(kaynak, secenek)
            if deger not in ("", None):
                ayar[secenek] = deger
        stil.configure(ALIS_TABLO_STILI, **ayar)
        stil.configure(
            f"{ALIS_TABLO_STILI}.Heading",
            font=ftema.font(10, "bold", self),
            background=ftema.SARI,
            foreground=ftema.LACIVERT,
            relief="solid",
            borderwidth=1,
        )
        stil.map(
            f"{ALIS_TABLO_STILI}.Heading",
            background=[("active", ftema.LACIVERT), ("pressed", ftema.LACIVERT)],
            foreground=[("active", ftema.SARI), ("pressed", ftema.SARI)],
        )
        stil.map(
            ALIS_TABLO_STILI,
            background=[("selected", ftema.SECIM)],
            foreground=[("selected", ftema.LACIVERT)],
        )

    def _alis_toolbar_kur(self):
        refs = ftema.ust_toolbar(
            self,
            baslik=ALIS_BELGE_BASLIGI,
            fatura_no=getattr(self.fatura, "fatura_no", "") or "Yeni",
            musteri_kisa="",
            durum=getattr(self.fatura, "durum", None) or "YENİ",
        )
        self._alis_toolbar = refs
        self._alis_ust_butonlar = refs["cubuk"]
        sag = refs["sag"]
        liste_btn = ftema.tk_buton(sag, "Fatura Listesi (F3)", self._fatura_listesini_ac, rol="ikincil")
        liste_btn.pack(side="left", padx=3)
        self._tooltip_bagla(liste_btn, "Alış Fatura Listesini Aç")
        self.kaydet_btn = ftema.tk_buton(sag, "Kaydet (F1)", self.kaydet, rol="vurgu")
        self.kaydet_btn.pack(side="left", padx=3)
        ftema.tk_buton(sag, "Önizleme", self._alis_onizleme_ac, rol="ikincil").pack(side="left", padx=3)
        ftema.tk_buton(sag, "PDF", self._alis_pdf_kaydet, rol="ikincil").pack(side="left", padx=3)
        ftema.tk_buton(sag, "Masraf Dağıtımları", self._masraf_dagitimlari, rol="ikincil").pack(
            side="left", padx=3
        )
        self.iptal_btn = ftema.tk_buton(sag, "İptal Et", self.faturayi_iptal_et, rol="tehlike")
        self.iptal_btn.pack(side="left", padx=3)
        ftema.tk_buton(sag, "Kapat (Esc)", self.kapat_istegi, rol="ikincil").pack(side="left", padx=(10, 3))

    def _pencere_basligi(self) -> str:
        no = getattr(self.fatura, "fatura_no", "") if self.fatura else ""
        return f"{ALIS_BELGE_BASLIGI} — {no}" if no else f"{ALIS_BELGE_BASLIGI} — Yeni"

    def _toolbar_guncelle(self):
        refs = getattr(self, "_alis_toolbar", None)
        self.title(self._pencere_basligi())
        if not refs:
            return
        try:
            refs["fatura_no"].configure(text=getattr(self.fatura, "fatura_no", "") or "Yeni")
            tedarikci = self.tedarikci_map.get(self.tedarikci.get()) if hasattr(self, "tedarikci") else None
            refs["musteri"].configure(text=(f"Tedarikçi: {tedarikci.unvan}" if tedarikci else "")[:60])
            ftema.rozet_guncelle(refs["rozet"], getattr(self.fatura, "durum", None) or "YENİ")
        except tk.TclError:
            return
        iptal = bool(self.fatura and self.fatura.durum == "İPTAL")
        for dugme in (getattr(self, "kaydet_btn", None), getattr(self, "iptal_btn", None)):
            if dugme is not None:
                dugme.configure(state="disabled" if iptal else "normal")

    def _form_degisti(self, _event=None):
        if not getattr(self, "_fatura_yukleniyor", False):
            self._fatura_form_kirli = True

    def _form_tus_degisti(self, event):
        if event.char and event.char.isprintable() or event.keysym in ("BackSpace", "Delete"):
            self._form_degisti()

    def kapat_istegi(self):
        """Kaydedilmemiş değişiklik varsa sorar; kayıt başarısızsa pencere açık kalır."""
        if self._fatura_kirli_mi():
            cevap = messagebox.askyesnocancel(
                "Kaydedilmemiş değişiklikler",
                "Alış faturasında kaydedilmemiş değişiklikler var.\nKaydetmek ister misiniz?",
                parent=self,
            )
            if cevap is None:
                return
            if cevap and not self._kaydet_kapatmadan():
                return
        self.destroy()

    def _ust_paneller_olustur(self):
        ust = tk.Frame(self.icerik, bg=ftema.ACIK_BG)
        ust.pack(fill="x", pady=(0, 6))
        self._fatura_ust_panel = ust
        for sutun, agirlik in enumerate((25, 28, 25, 22)):
            ust.columnconfigure(sutun, weight=agirlik, uniform="alis_ust")

        # 1 — Fatura Bilgileri
        p1 = ttk.LabelFrame(ust, text="Fatura Bilgileri", style="AlisUst.TLabelframe")
        p1.grid(row=0, column=0, sticky="nsew", padx=(0, 6))
        fatura_no = self.fatura.fatura_no if self.fatura else AlisFaturasiService.fatura_no()
        self._girdi(p1, 0, "Kayıt No", "fatura_no", fatura_no, genislik=14, readonly=True)
        self._girdi(
            p1, 1, "Tedarikçi Fat. No", "tedarikci_fatura_no",
            (getattr(self.fatura, "tedarikci_fatura_no", None) or "") if self.fatura else "", genislik=14,
        )
        self.girdiler["tedarikci_fatura_no"].bind("<FocusOut>", self._mukerrer_uyar, add="+")
        tarih_alani(
            p1, 2, "Fatura Tarihi", "fatura_tarihi",
            tarih_goster(self.fatura.fatura_tarihi) if self.fatura else date.today().strftime("%d.%m.%Y"),
            self.girdiler,
            on_select=self.vade_gun_degisti,
            genislik=10,
        )
        saat_deger = saat_varsayilan(
            self.fatura.islem_saati if self.fatura and self.fatura.islem_saati
            else (self.fatura.olusturma_tarihi.strftime("%H:%M") if self.fatura else None)
        )
        self._girdi(p1, 3, "İşlem Saati", "islem_saati", saat_deger, genislik=8)
        tarih_alani(
            p1, 4, "Vade Tarihi", "vade_tarihi",
            tarih_goster(self.fatura.vade_tarihi) if self.fatura else date.today().strftime("%d.%m.%Y"),
            self.girdiler,
            on_select=self.vade_tarih_degisti,
            genislik=10,
        )
        self._girdi(p1, 5, "Vade Günü", "vade_gunu", str(self.fatura.vade_gunu if self.fatura else 0), genislik=8)
        self.girdiler["fatura_tarihi"].bind("<FocusOut>", self.vade_gun_degisti)
        self.girdiler["vade_tarihi"].bind("<FocusOut>", self.vade_tarih_degisti)
        self.girdiler["vade_gunu"].bind("<KeyRelease>", self.vade_gun_degisti)
        ttk.Label(p1, text="Durum", style="AlisUst.TLabel").grid(
            row=6, column=0, padx=(0, 6), pady=ALIS_UST_PADY, sticky="w"
        )
        self.durum = ttk.Combobox(
            p1, values=("AÇIK", "KAPALI", "İPTAL"), state="readonly", width=12, style="FaturaUst.TCombobox"
        )
        self.durum.grid(row=6, column=1, padx=(0, 8), pady=ALIS_UST_PADY, sticky="w")
        self.durum.set(self.fatura.durum if self.fatura else "AÇIK")
        self.durum.configure(state="disabled")
        p1.columnconfigure(1, weight=1)

        # 2 — Tedarikçi ve Cari
        p2 = ttk.LabelFrame(ust, text="Tedarikçi ve Cari", style="AlisUst.TLabelframe")
        p2.grid(row=0, column=1, sticky="nsew", padx=(0, 6))
        ttk.Label(p2, text="Tedarikçi", style="AlisUst.TLabel").grid(
            row=0, column=0, padx=(0, 6), pady=ALIS_UST_PADY, sticky="w"
        )
        self.tedarikci = tk.StringVar()
        self.tedarikci_combo = ttk.Combobox(
            p2, textvariable=self.tedarikci, values=list(self.tedarikci_map), state="readonly", width=30,
            style="FaturaUst.TCombobox",
        )
        self.tedarikci_combo.grid(row=0, column=1, columnspan=3, padx=0, pady=ALIS_UST_PADY, sticky="ew")
        self.tedarikci_combo.bind("<<ComboboxSelected>>", lambda _e: self._tedarikci_degisti())
        self._tooltip_bagla(self.tedarikci_combo, "F10 veya sağ tık: tedarikçi listesinden seç")
        for olay in ("<F10>", "<Button-3>"):
            self.tedarikci_combo.bind(olay, self._tedarikci_listeden_sec)
        ttk.Label(p2, text="Sipariş No", style="AlisUst.TLabel").grid(
            row=1, column=0, padx=(0, 6), pady=ALIS_UST_PADY, sticky="w"
        )
        self.siparis_no = ttk.Entry(p2, width=18, style="FaturaUst.TEntry")
        self.siparis_no.grid(row=1, column=1, columnspan=3, padx=0, pady=ALIS_UST_PADY, sticky="ew")
        ttk.Label(p2, text="İrsaliye No", style="AlisUst.TLabel").grid(
            row=2, column=0, padx=(0, 6), pady=ALIS_UST_PADY, sticky="w"
        )
        self.irsaliye_no = ttk.Entry(p2, width=18, style="FaturaUst.TEntry")
        self.irsaliye_no.grid(row=2, column=1, columnspan=3, padx=0, pady=ALIS_UST_PADY, sticky="ew")
        ttk.Label(p2, text="Şube", style="AlisUst.TLabel").grid(
            row=3, column=0, padx=(0, 6), pady=ALIS_UST_PADY, sticky="w"
        )
        from sube_ui import sube_secim_hazirla

        kaynak_sube_id = (
            getattr(self.fatura, "sube_id", None)
            or getattr(self.kaynak_irsaliye, "sube_id", None)
            or getattr(self.kaynak_siparis, "sube_id", None)
        )
        self.sube, self._sube_map = sube_secim_hazirla(p2, kaynak_sube_id)
        self.sube.grid(row=3, column=1, columnspan=3, padx=0, pady=ALIS_UST_PADY, sticky="ew")
        dugmeler = tk.Frame(p2)
        dugmeler.grid(row=4, column=0, columnspan=4, sticky="w", pady=(6, 0))
        ftema.tk_buton(dugmeler, "Cari Kartına Geç", self.cariye_git, rol="kaydet").pack(side="left")
        ftema.tk_buton(dugmeler, "Alış Evrakları", self._tedarikci_evraklari, rol="ikincil").pack(
            side="left", padx=6
        )
        p2.columnconfigure(1, weight=1)
        self.girdiler["siparis_no"] = self.siparis_no
        self.girdiler["irsaliye_no"] = self.irsaliye_no
        if self.kaynak_siparis:
            self.siparis_no.insert(0, self.kaynak_siparis.siparis_no)
        if self.kaynak_irsaliye:
            self.irsaliye_no.insert(0, self.kaynak_irsaliye.irsaliye_no)
            if self.kaynak_irsaliye.siparis:
                self.siparis_no.delete(0, "end")
                self.siparis_no.insert(0, self.kaynak_irsaliye.siparis.siparis_no)

        # 3 — Depo, Belge ve Döviz
        p3 = ttk.LabelFrame(ust, text="Depo, Belge ve Döviz", style="AlisUst.TLabelframe")
        p3.grid(row=0, column=2, sticky="nsew", padx=(0, 6))
        ttk.Label(p3, text="Giriş Deposu", style="AlisUst.TLabel").grid(
            row=0, column=0, padx=(0, 6), pady=ALIS_UST_PADY, sticky="w"
        )
        depolar = tuple(d.ad for d in StokService.depolar()) or ("ANA DEPO",)
        self.depo = ttk.Combobox(p3, values=depolar, state="readonly", width=18, style="FaturaUst.TCombobox")
        self.depo.grid(row=0, column=1, padx=0, pady=ALIS_UST_PADY, sticky="ew")
        if self.fatura and self.fatura.depo in depolar:
            self.depo.set(self.fatura.depo)
        else:
            self.depo.set(depolar[0])
        ttk.Button(p3, text="Yeni Depo", command=self.depo_ekle, style="FaturaUst.TButton").grid(
            row=0, column=2, padx=(4, 0), pady=ALIS_UST_PADY
        )
        self.girdiler["depo"] = self.depo
        ttk.Label(p3, text="Doküman", style="AlisUst.TLabel").grid(
            row=1, column=0, padx=(0, 6), pady=ALIS_UST_PADY, sticky="w"
        )
        self.dokuman = ttk.Entry(p3, width=18, style="FaturaUst.TEntry")
        self.dokuman.grid(row=1, column=1, padx=0, pady=ALIS_UST_PADY, sticky="ew")
        ttk.Button(p3, text="Seç", command=self.dokuman_sec, style="FaturaUst.TButton").grid(
            row=1, column=2, padx=(4, 0), pady=ALIS_UST_PADY
        )
        self.girdiler["dokuman"] = self.dokuman
        ttk.Label(p3, text="Para Birimi", style="AlisUst.TLabel").grid(
            row=2, column=0, padx=(0, 6), pady=ALIS_UST_PADY, sticky="w"
        )
        self._doviz_ozet_lbl = ttk.Label(p3, text="TRY", style="AlisUst.TLabel")
        self._doviz_ozet_lbl.grid(row=2, column=1, padx=0, pady=ALIS_UST_PADY, sticky="w")
        self._doviz_ac_btn = ttk.Button(
            p3, text="Döviz / Kur", command=self._doviz_alani_ac_kapat, style="FaturaUst.TButton"
        )
        self._doviz_ac_btn.grid(row=2, column=2, padx=(4, 0), pady=ALIS_UST_PADY)
        ttk.Label(
            p3, text="Stok girişi ve lot bu depoya yazılır.", style="AlisUst.TLabel", foreground=ftema.IKINCIL
        ).grid(row=3, column=0, columnspan=3, sticky="w", pady=(6, 0))
        p3.columnconfigure(1, weight=1)

        # 4 — Cari Özet
        p4 = ttk.LabelFrame(ust, text="Cari Özet", style="AlisUst.TLabelframe")
        p4.grid(row=0, column=3, sticky="nsew")
        self._cari_ozet_etiketleri = {}
        for sira, (anahtar, baslik) in enumerate((
            ("mevcut", "Mevcut Borcumuz"),
            ("fatura", "Bu Fatura"),
            ("yeni", "Yeni Borcumuz"),
            ("vade", "Ağırlıklı Ort. Vade"),
        )):
            ttk.Label(p4, text=baslik, style="AlisUst.TLabel").grid(
                row=sira, column=0, sticky="w", padx=(0, 8), pady=ALIS_UST_PADY
            )
            etiket = tk.Label(
                p4, text="—", font=ftema.font(10, "bold", self), fg=ftema.LACIVERT, anchor="e",
                bg=ftema.BEYAZ,
            )
            etiket.grid(row=sira, column=1, sticky="e", pady=ALIS_UST_PADY)
            self._cari_ozet_etiketleri[anahtar] = etiket
        p4.columnconfigure(1, weight=1)
        # Geriye dönük: servis/testler bu iki girdiyi okur
        gizli = tk.Frame(p4)
        self.girdiler["mevcut_bakiye"] = ttk.Entry(gizli)
        self.girdiler["tahmini_bakiye"] = ttk.Entry(gizli)
        self.yeni_bakiye_etiket = self._cari_ozet_etiketleri["yeni"]
        self.ortalama_vade_etiket = self._cari_ozet_etiketleri["vade"]

    def _tedarikci_degisti(self):
        self._form_degisti()
        self._bakiye_guncelle()
        self._toolbar_guncelle()

    def _tedarikci_listeden_sec(self, _event=None):
        if str(self.tedarikci_combo.cget("state")) == "disabled":
            return "break"
        from app import MusteriSecimDialog

        tedarikciler = list(dict.fromkeys(self.tedarikci_map.values()))
        dialog = MusteriSecimDialog(
            self, musteriler=tedarikciler, baslik="Tedarikçi Seçimi", kayit_adi="tedarikçi"
        )
        self.wait_window(dialog)
        cari = getattr(dialog, "result", None)
        if cari is not None:
            self._tedarikci_sec(cari)
            self._tedarikci_degisti()
        return "break"

    def _tedarikci_evraklari(self):
        tedarikci = self.tedarikci_map.get(self.tedarikci.get())
        if not tedarikci:
            messagebox.showinfo("Tedarikçi", "Önce tedarikçi seçin.", parent=self)
            return
        from tedarikci_evrak_ui import TedarikciEvraklariDialog

        self.wait_window(TedarikciEvraklariDialog(self, tedarikci))

    def _mukerrer_uyar(self, _event=None):
        tedarikci = self.tedarikci_map.get(self.tedarikci.get())
        no = self.girdiler["tedarikci_fatura_no"].get().strip()
        if not tedarikci or not no:
            return
        try:
            mevcut = AlisFaturasiService.mukerrer_kontrol(
                tedarikci.id, no, getattr(self.fatura, "id", None) if self.fatura else None
            )
        except Exception:
            return
        if mevcut:
            self._mukerrer_kaydi_goster(mevcut[0], mevcut[1], no)

    def _mukerrer_kaydi_goster(self, fatura_id: int, kayit_no: str, ted_no: str):
        if messagebox.askyesno(
            "Mükerrer tedarikçi faturası",
            f"Bu tedarikçinin '{ted_no}' numaralı faturası zaten kayıtlı (kayıt no: {kayit_no}).\n"
            "Mevcut kaydı açmak ister misiniz?",
            parent=self,
        ):
            fatura = AlisFaturasiService.getir(fatura_id)
            if fatura:
                self.wait_window(AlisFaturasiDialog(self, fatura=fatura, cari_ac=self.cari_ac))

    def _doviz_alani_ac_kapat(self):
        cerceve = self._doviz_cerceve
        if cerceve.winfo_manager():
            cerceve.pack_forget()
        else:
            cerceve.pack(fill="x", pady=(0, 6), after=self._fatura_ust_panel)

    def _doviz_gorunumu_guncelle(self):
        pb = (self._doviz_para_birimi.get() if hasattr(self, "_doviz_para_birimi") else "TRY") or "TRY"
        self._doviz_ozet_lbl.configure(text=pb.upper())
        if pb.upper() != "TRY" and not self._doviz_cerceve.winfo_manager():
            self._doviz_alani_ac_kapat()

    def _satir_olustur(self, parent):
        butonlar = ttk.Frame(parent)
        butonlar.grid(row=0, column=0, columnspan=2, sticky="ew", pady=(0, 6))
        ttk.Label(
            butonlar,
            text="Son satıra barkod okutun, ürün kodu veya adı yazın · F10 stok listesi · "
            "Enter/Tab alanlar arasında ilerler · sağ tık: satır işlemleri",
            foreground="#627D98",
        ).pack(side="left")
        ttk.Button(butonlar, text="Kolon Ayarları", command=self._alis_kolon_ayarlari_ac).pack(side="right", padx=4)
        ttk.Button(butonlar, text="Çoklu İskonto", command=self._alis_iskonto_ac).pack(side="right", padx=4)
        ttk.Button(butonlar, text="Araya Satır Ekle", command=self._alis_araya_ekle).pack(side="right", padx=4)
        ttk.Button(butonlar, text="Satırı Sil (Del)", command=self.satir_sil).pack(side="right", padx=4)

        kolonlar = (
            "barkod", "kod", "ad", "aciklama", "miktar", "birim", "fiyat", "iskonto", "kdv",
            "net_birim", "lot", "lot_girisi", "toplam", "siparis_miktar", "irsaliye_miktar", "fatura_miktar",
        )
        self.satir_tablosu = ttk.Treeview(
            parent, columns=kolonlar, show="headings", height=10, style=ALIS_TABLO_STILI
        )
        basliklar = {
            "barkod": "Barkod", "kod": "Ürün Kodu", "ad": "Ürün Adı", "aciklama": "Açıklama",
            "miktar": "Miktar", "birim": "Birim", "fiyat": "Alış Fiyatı", "iskonto": "İskonto",
            "kdv": "KDV", "net_birim": "Net Birim Fiyat", "lot": "Lot No", "lot_girisi": "Lot Girişi",
            "toplam": "Net Tutar",
            "siparis_miktar": "Sipariş Miktarı", "irsaliye_miktar": "İrsaliye Miktarı",
            "fatura_miktar": "Fatura Miktarı",
        }
        for kolon in kolonlar:
            self.satir_tablosu.heading(kolon, text=basliklar[kolon])
            w = 110 if kolon in ("net_birim", "toplam", "ad") else 100
            if kolon == "ad":
                w = 220
            if kolon == "iskonto":
                w = 160
            if kolon == "kdv":
                w = 70
            self.satir_tablosu.column(
                kolon,
                width=w,
                minwidth=40 if kolon == "iskonto" else 20,
                anchor="e" if kolon in ("net_birim", "toplam", "fiyat") else "w",
            )
        # Firma/kullanıcı kolon tercihleri (displaycolumns; values kesilmez)
        try:
            from fatura_satir_kolon_prefs import (
                EKRAN_ALIS,
                ayarlari_yukle,
                resize_bagla,
                tabloya_uygula,
            )

            self._alis_kolon_ayarlari = ayarlari_yukle(EKRAN_ALIS)
            self._alis_kolon_ayarlari = tabloya_uygula(
                self.satir_tablosu, EKRAN_ALIS, self._alis_kolon_ayarlari
            )

            def _alis_set_ayar(a):
                self._alis_kolon_ayarlari = a

            resize_bagla(
                self.satir_tablosu,
                EKRAN_ALIS,
                ayar_getter=lambda: getattr(self, "_alis_kolon_ayarlari", {}),
                ayar_setter=_alis_set_ayar,
                parent=self,
            )
        except Exception:
            self._alis_kolon_ayarlari = None
        dikey = ttk.Scrollbar(parent, orient="vertical", command=self.satir_tablosu.yview)
        yatay = ttk.Scrollbar(parent, orient="horizontal", command=self.satir_tablosu.xview)
        self.satir_tablosu.configure(yscrollcommand=dikey.set, xscrollcommand=yatay.set)
        self.satir_tablosu.grid(row=1, column=0, sticky="nsew")
        dikey.grid(row=1, column=1, sticky="ns")
        yatay.grid(row=2, column=0, sticky="ew")
        parent.rowconfigure(1, weight=1)
        parent.columnconfigure(0, weight=1)
        self._alis_fatura_girisi_kur()

        # Sabit alt banda pack(in_=...) edilebilmesi için Toplevel'in çocuğu olmalı;
        # kaydırma içindeki bir çerçevenin çocuğu dışarı taşınamaz (TclError).
        toplamlar = tk.Frame(self, bg=ftema.LACIVERT, padx=10, pady=6)
        self._alis_toplam_cerceve = toplamlar
        self._alis_satir_brut = Decimal("0")
        self._alis_net_toplam = Decimal("0")
        self._fatura_persisted = bool(
            getattr(self, "fatura", None) and getattr(self.fatura, "id", None)
        )
        sol = tk.Frame(toplamlar, bg=ftema.LACIVERT)
        sol.pack(side="left", fill="x", expand=True)
        self.satir_ozet = tk.Label(
            sol,
            text="Ara Toplam: 0,00 TL | İskonto: 0,00 TL | KDV: 0,00 TL | Genel: 0,00 TL",
            bg=ftema.LACIVERT,
            fg=ftema.BEYAZ,
            font=ftema.font(10, root=self),
            anchor="w",
            justify="left",
            wraplength=900,
        )
        self.satir_ozet.pack(anchor="w", fill="x")
        brut_satir = tk.Frame(sol, bg=ftema.LACIVERT)
        brut_satir.pack(anchor="w", pady=(2, 0))
        tk.Label(
            brut_satir, text="Brüt:", bg=ftema.LACIVERT, fg=ftema.BEYAZ, font=ftema.font(10, root=self)
        ).pack(side="left")
        self._alis_brut_lbl = tk.Label(
            brut_satir,
            text="0,00 TL",
            bg=ftema.LACIVERT,
            fg=ftema.BEYAZ,
            font=ftema.font(10, "bold", root=self),
            anchor="w",
        )
        self._alis_brut_lbl.pack(side="left", padx=(4, 0))

        sag = tk.Frame(toplamlar, bg=ftema.LACIVERT)
        sag.pack(side="right")
        ftema.tk_buton(sag, "Kapat (Esc)", self.kapat_istegi, rol="ikincil").pack(
            side="right", padx=(8, 0)
        )
        ftema.tk_buton(sag, "Kaydet (F1)", self.kaydet, rol="vurgu").pack(side="right", padx=(8, 0))
        genel = tk.Frame(sag, bg=ftema.LACIVERT)
        genel.pack(side="right", padx=(0, 12))
        tk.Label(
            genel, text="GENEL TOPLAM", bg=ftema.LACIVERT, fg=ftema.SARI, font=ftema.font(9, "bold", root=self)
        ).pack(anchor="e")
        self._alis_net_lbl = tk.Label(
            genel,
            text="0,00 TL",
            bg=ftema.LACIVERT,
            fg=ftema.SARI,
            font=ftema.font(18, "bold", root=self),
            anchor="e",
        )
        self._alis_net_lbl.pack(anchor="e")

    def _odeme_olustur(self, parent):
        cerceve = ttk.LabelFrame(parent, text="ÖDEMELER", padding=8)
        cerceve.grid(row=0, column=0, sticky="nsew")
        kolonlar = ("tarih", "tutar", "sekil", "hesap", "aciklama")
        self.odeme_tablosu = ttk.Treeview(cerceve, columns=kolonlar, show="headings", height=6)
        for kolon, baslik in zip(kolonlar, ("Tarih", "Tutar", "Ödeme Şekli", "Hesap", "Açıklama")):
            self.odeme_tablosu.heading(kolon, text=baslik)
            self.odeme_tablosu.column(kolon, width=140)
        self.odeme_tablosu.pack(fill="both", expand=True)
        alt = ttk.Frame(cerceve)
        alt.pack(fill="x", pady=8)
        ttk.Button(alt, text="Ödeme Ekle", command=self.odeme_ekle).pack(side="left")
        ttk.Button(alt, text="Ödeme Düzenle", command=self.odeme_duzenle).pack(side="left", padx=8)
        ttk.Button(alt, text="Ödeme Kaldır", command=self.odeme_kaldir).pack(side="left")
        self.odeme_ozet = ttk.Label(cerceve, text="Ödenen: 0,00 TL | Kalan: 0,00 TL")
        self.odeme_ozet.pack(anchor="w")

    def _notlar_olustur(self, parent):
        cerceve = ttk.LabelFrame(parent, text="AÇIKLAMA / NOTLAR", padding=8)
        cerceve.grid(row=0, column=1, sticky="nsew", padx=(8, 0))
        ttk.Label(cerceve, text="Genel Açıklama").pack(anchor="w")
        self.girdiler["aciklama"] = ttk.Entry(cerceve)
        self.girdiler["aciklama"].pack(fill="x", pady=(2, 8))
        ttk.Label(cerceve, text="Ayrıntılı Notlar").pack(anchor="w")
        self.ayrintili_notlar = tk.Text(cerceve, height=6, width=45)
        self.ayrintili_notlar.pack(fill="both", expand=True, pady=(2, 0))

    def _readonly_yaz(self, alan, deger):
        w = self.girdiler[alan]
        w.configure(state="normal")
        w.delete(0, "end")
        w.insert(0, deger)
        w.configure(state="readonly")

    def _entry_yaz(self, alan, deger):
        self.girdiler[alan].delete(0, "end")
        self.girdiler[alan].insert(0, deger)

    def _tedarikci_sec(self, cari):
        anahtar = _tedarikci_ekle(self.tedarikci_map, cari)
        self.tedarikci_combo["values"] = list(self.tedarikci_map)
        if anahtar:
            self.tedarikci.set(anahtar)

    def depo_ekle(self):
        ad = simpledialog.askstring("Yeni Depo", "Depo adı:", parent=self)
        if not ad:
            return
        try:
            depo = StokService.depo_ekle(ad)
        except ValueError as hata:
            messagebox.showerror("Depo eklenemedi", str(hata), parent=self)
            return
        self.depo["values"] = tuple(d.ad for d in StokService.depolar())
        self.depo.set(depo.ad)

    def vade_gun_degisti(self, _event=None):
        try:
            fatura_tarihi = datetime.strptime(self.girdiler["fatura_tarihi"].get(), "%d.%m.%Y").date()
            vade_tarihi = fatura_tarihi + timedelta(days=int(self.girdiler["vade_gunu"].get() or 0))
        except (ValueError, TypeError):
            return
        self._entry_yaz("vade_tarihi", tarih_goster(vade_tarihi))
        self._toplamlari_guncelle()

    def vade_tarih_degisti(self, _event=None):
        try:
            fatura_tarihi = datetime.strptime(self.girdiler["fatura_tarihi"].get(), "%d.%m.%Y").date()
            vade_tarihi = datetime.strptime(self.girdiler["vade_tarihi"].get(), "%d.%m.%Y").date()
        except ValueError:
            return
        self.girdiler["vade_gunu"].delete(0, "end")
        self.girdiler["vade_gunu"].insert(0, str((vade_tarihi - fatura_tarihi).days))
        self._toplamlari_guncelle()

    def dokuman_sec(self):
        yol = filedialog.askopenfilename(parent=self, title="Faturaya doküman ekle")
        if yol:
            self.dokuman.delete(0, "end")
            self.dokuman.insert(0, yol)

    def cariye_git(self):
        cari = self.tedarikci_map.get(self.tedarikci.get())
        if not cari:
            messagebox.showinfo("Cari", "Önce tedarikçi seçin.", parent=self)
            return
        if self.cari_ac:
            self.cari_ac(cari)
        else:
            messagebox.showinfo("Cari", "Cari kartı bu ekrandan açılamıyor.", parent=self)

    def _onerilen_lot(self):
        tedarikci = self.tedarikci_map.get(self.tedarikci.get())
        adi = tedarikci.unvan if tedarikci else ""
        try:
            tarih = datetime.strptime(self.girdiler["fatura_tarihi"].get(), "%d.%m.%Y").date()
        except ValueError:
            tarih = date.today()
        return StokService.otomatik_lot_no(adi, tarih)

    # ─── satır içi ürün girişi
    def _alis_fatura_girisi_kur(self):
        from satir_ici_urun_giris import HucreAlani, SatirHucreDuzenleyici, SatirIciUrunGirisi, iskonto_metni, sayi_metni

        self._satir_ici_giris = SatirIciUrunGirisi(
            self,
            self.satir_tablosu,
            urun_ekle=self._alis_fatura_urun_ekle,
            kolonlar={"barkod": "barkod", "kod": "kod", "ad": "ad"},
            urun_degistir=self._alis_fatura_urun_degistir,
            miktara_git=lambda idx: self._hucre.duzenle(idx, "miktar"),
            fiyat_turu="alis",
            alis_fiyati=lambda kod: StokService.son_alis_fiyati(kod, None),
            satir_menusu=self._alis_fatura_satir_menusu,
            ilk_rol="barkod",
        )

        def _fiyat_degeri(i):
            s = self.satirlar[i]
            if self._alis_doviz_aktif() and s.get("birim_fiyat_doviz") not in (None, ""):
                return sayi_metni(s["birim_fiyat_doviz"])
            return sayi_metni(s.get("birim_fiyat", s.get("birim_alis_fiyati", 0)) or 0)

        self._hucre = SatirHucreDuzenleyici(
            self,
            self.satir_tablosu,
            [
                HucreAlani("aciklama", "metin", deger=lambda i: self.satirlar[i].get("aciklama") or ""),
                HucreAlani("miktar", deger=lambda i: sayi_metni(self.satirlar[i].get("miktar") or 0)),
                HucreAlani("birim", "secim", secenekler=self._alis_fatura_birimleri),
                HucreAlani("fiyat", deger=_fiyat_degeri),
                HucreAlani("iskonto", "metin", deger=lambda i: iskonto_metni(self.satirlar[i])),
                HucreAlani("kdv", "secim", secenekler=lambda _i: ("0", "1", "10", "20"), serbest=True,
                           deger=lambda i: sayi_metni(self.satirlar[i].get("kdv_orani") or 0)),
                HucreAlani("lot", "metin", deger=lambda i: self.satirlar[i].get("lot_no") or ""),
            ],
            uygula=self.alis_fatura_hucre_uygula,
            satir_sayisi=lambda: len(self.satirlar),
            bitince=self._satir_ici_giris.odakla,
        )
        self.satir_tablosu.bind("<Delete>", lambda _e: self.satir_sil())
        self._satir_ici_giris.tabloya_ekle()

    def _alis_editorleri_uygula(self) -> None:
        """Kayıt öncesi açık hücreyi yazar; yarım kalan arama metni satır olmaz."""
        if not self._hucre.bekleyeni_uygula():
            raise ValueError("Düzenlenen hücredeki değer geçersiz; düzeltin veya Esc ile vazgeçin.")
        self._satir_ici_giris.bekleyeni_uygula()

    def _alis_doviz_aktif(self) -> bool:
        pb = getattr(self, "_doviz_para_birimi", None)
        try:
            return bool(pb) and (pb.get() or "TRY").upper() != "TRY"
        except (tk.TclError, AttributeError):
            return False

    def _satir_toplu_yenile(self):
        self._satir_listesini_yenile()
        if hasattr(self, "_doviz_para_birimi"):
            doviz_ozet_guncelle(self)

    def _alis_fatura_yenile(self):
        from satir_ici_urun_giris import toplu_ekleme_mi

        if not toplu_ekleme_mi(self):
            self._satir_toplu_yenile()

    @staticmethod
    def _alis_fatura_bagli(s: dict) -> bool:
        return bool(s.get("siparis_satiri_id") or s.get("irsaliye_satiri_id"))

    def _alis_fatura_birimleri(self, idx: int) -> list[str]:
        s = self.satirlar[idx]
        if self._alis_fatura_bagli(s):
            return [s.get("birim") or "Adet"]
        try:
            from fatura_satir_birim_service import stok_aktif_birimleri

            return stok_aktif_birimleri(s.get("urun_kodu") or "") or list(BIRIM_SECENEKLERI)
        except Exception:
            return list(BIRIM_SECENEKLERI)

    def _alis_fatura_satiri(self, degerler) -> dict:
        from satir_ici_urun_giris import alis_birim_fiyati

        kod = ((degerler[0] if degerler else "") or "").strip()
        if not kod:
            raise ValueError("Ürün kodu boş.")
        birim = (degerler[2] if len(degerler) > 2 else "") or "Adet"
        stok = next((s for s in StokService.stoklari_ara(kod) if s.stok_kodu == kod), None)
        fiyat = alis_birim_fiyati(kod, birim)
        lot = self._onerilen_lot()
        veri = {
            "barkod": (getattr(stok, "barkod", None) or "") if stok else "",
            "urun_kodu": kod,
            "urun_adi": (degerler[1] if len(degerler) > 1 else "") or "",
            "aciklama": "",
            "miktar": "1",
            "birim": birim,
            "birim_fiyat": f"{fiyat:f}",
            "birim_alis_fiyati": f"{fiyat:f}",
            "iskonto_orani": "0", "iskonto_orani_2": "0", "iskonto_orani_3": "0",
            "kdv_orani": satir_kdv_metin(stok_kdv=getattr(stok, "kdv_orani", None) if stok else None),
            "lot_no": lot,
            "lot_girisi": lot,
        }
        return doviz_satir_kaydet_oncesi(self, veri)

    def _alis_fatura_urun_ekle(self, degerler, konum):
        from satir_ici_urun_giris import birlesecek_satir, giris_bileseni

        veri = self._alis_fatura_satiri(degerler)
        giris = giris_bileseni(self)
        if giris is not None and giris.son_islem == "barkod" and konum is None:
            idx = birlesecek_satir(
                self.satirlar, veri, fiyat_alani="birim_fiyat",
                ek_alanlar=("iskonto_orani", "iskonto_orani_2", "iskonto_orani_3"),
            )
            if idx is not None:
                s = self.satirlar[idx]
                s["miktar"] = str(decimal(s.get("miktar") or 0, "Miktar", Decimal("0")) + 1)
                self._alis_fatura_yenile()
                return idx
        if konum is not None and 0 <= konum <= len(self.satirlar):
            self.satirlar.insert(konum, veri)
            idx = konum
        else:
            self.satirlar.append(veri)
            idx = len(self.satirlar) - 1
        self._alis_fatura_yenile()
        return idx

    def _alis_fatura_urun_degistir(self, idx: int, degerler) -> bool:
        if not (0 <= idx < len(self.satirlar)):
            return False
        eski = self.satirlar[idx]
        if self._alis_fatura_bagli(eski):
            messagebox.showwarning(
                "Bağlı satır", "Sipariş / irsaliyeden gelen satırın ürünü değiştirilemez.", parent=self
            )
            return False
        try:
            veri = self._alis_fatura_satiri(degerler)
        except ValueError as hata:
            messagebox.showwarning("Ürün", str(hata), parent=self)
            return False
        veri["miktar"] = eski.get("miktar") or "1"
        veri["aciklama"] = eski.get("aciklama") or ""
        veri["lot_no"] = eski.get("lot_no") or veri["lot_no"]
        veri["lot_girisi"] = veri["lot_no"]
        self.satirlar[idx] = veri
        self._alis_fatura_yenile()
        return True

    def alis_fatura_hucre_uygula(self, idx: int, kolon: str, metin: str) -> None:
        from satir_ici_urun_giris import alis_birim_fiyati, iskonto_metni_coz

        if not (0 <= idx < len(self.satirlar)):
            return
        s = self.satirlar[idx]
        yeni = dict(s)
        if kolon == "aciklama":
            yeni["aciklama"] = metin
        elif kolon == "miktar":
            miktar = decimal(metin or 0, "Miktar")
            if miktar <= 0:
                raise ValueError("Miktar sıfırdan büyük olmalıdır.")
            yeni["miktar"] = f"{miktar:f}"
        elif kolon == "birim":
            birim = (metin or "").strip()
            if not birim:
                raise ValueError("Birim zorunludur.")
            if birim.casefold() == (s.get("birim") or "").casefold():
                return
            if self._alis_fatura_bagli(s):
                raise ValueError("Sipariş / irsaliyeden gelen satırın birimi değiştirilemez.")
            yeni["birim"] = birim
            fiyat = alis_birim_fiyati(s.get("urun_kodu") or "", birim)
            yeni["birim_fiyat"] = yeni["birim_alis_fiyati"] = f"{fiyat:f}"
            yeni = doviz_satir_kaydet_oncesi(self, yeni)
        elif kolon == "fiyat":
            fiyat = decimal(metin or 0, "Birim alış", Decimal("0"))
            yeni["birim_fiyat"] = yeni["birim_alis_fiyati"] = f"{fiyat:f}"
            yeni = doviz_satir_kaydet_oncesi(self, yeni)
        elif kolon == "iskonto":
            i1, i2, i3 = iskonto_metni_coz(metin)
            yeni["iskonto_orani"], yeni["iskonto_orani_2"], yeni["iskonto_orani_3"] = f"{i1:f}", f"{i2:f}", f"{i3:f}"
        elif kolon == "kdv":
            kdv = decimal((metin or "0").replace("%", ""), "KDV", Decimal("0"))
            yeni["kdv_orani"] = f"{kdv:f}"
        elif kolon == "lot":
            yeni["lot_no"] = yeni["lot_girisi"] = metin or self._onerilen_lot()
        else:
            return
        self.satirlar[idx] = yeni
        self._alis_fatura_yenile()

    def _alis_secili_index(self) -> int | None:
        from satir_ici_urun_giris import satir_indeksi

        secim = self.satir_tablosu.selection() if hasattr(self, "satir_tablosu") else ()
        return satir_indeksi(self.satir_tablosu, secim[0]) if secim else None

    def _alis_fatura_satir_menusu(self, idx: int) -> list:
        ogeler = [
            ("Satırı Düzenle (F2)", lambda: self._hucre.ilk_alana(idx)),
            ("Alış Fiyatı Seç…", lambda: self.satir_fiyat_secimi_ac(idx=idx)),
            ("Çoklu İskonto Düzenle", lambda: self._alis_iskonto_ac(idx=idx)),
            ("İskontoları Temizle", lambda: self._alis_iskonto_temizle(idx)),
            ("Araya Satır Ekle", lambda: self._satir_ici_giris.araya_ekle(idx)),
            ("Satırı Sil (Del)", self.satir_sil),
        ]
        if 0 <= idx < len(self.satirlar) and not self._alis_fatura_bagli(self.satirlar[idx]):
            ogeler.insert(1, ("Ürünü Değiştir…", lambda: self._satir_ici_giris.urun_degistir_baslat(idx)))
        return ogeler

    def _alis_araya_ekle(self):
        idx = self._alis_secili_index()
        if idx is None:
            self._satir_ici_giris.odakla()
        else:
            self._satir_ici_giris.araya_ekle(idx)

    def satir_sil(self):
        from satir_ici_urun_giris import satir_editorlerini_kapat, satir_silme_sonrasi_temizle

        idx = self._alis_secili_index()
        if idx is None:
            return "break"
        satir_editorlerini_kapat(self)
        if messagebox.askyesno("Sil", "Satır silinsin mi?", parent=self):
            self.satirlar.pop(idx)
            self._alis_fatura_yenile()
            satir_silme_sonrasi_temizle(self, self.satir_tablosu)
        return "break"

    def stok_listesi_ac(self):
        self._satir_ici_giris.stok_listesi_ac("")

    def satir_fiyat_secimi_ac(self, _event=None, idx: int | None = None):
        """Seçili satır için stok kartındaki ALIŞ fiyatlarını listeler."""
        if idx is None:
            idx = self._alis_secili_index()
        if idx is None or not (0 <= idx < len(self.satirlar)):
            messagebox.showinfo("Alış Fiyatı", "Önce ürün satırı seçin.", parent=self)
            return "break"
        from app import PriceSelectionDialog

        def _secildi(fiyat):
            self.alis_fatura_hucre_uygula(idx, "fiyat", f"{Decimal(str(fiyat.tutar)):f}")

        dialog = PriceSelectionDialog(self, self.satirlar[idx]["urun_kodu"], on_select=_secildi, fiyat_turu="alis")
        self.wait_window(dialog)
        return "break"

    def _alis_iskonto_temizle(self, idx: int | None = None):
        if idx is None:
            idx = self._alis_secili_index()
        if idx is None or not (0 <= idx < len(self.satirlar)):
            return
        self.satirlar[idx].update({"iskonto_orani": "0", "iskonto_orani_2": "0", "iskonto_orani_3": "0"})
        self._alis_fatura_yenile()

    def _alis_kolon_ayarlari_ac(self):
        from fatura_satir_kolon_prefs import (
            EKRAN_ALIS,
            FaturaSatirKolonAyarDialog,
            ayarlari_yukle,
            tabloya_uygula,
        )

        mevcut = getattr(self, "_alis_kolon_ayarlari", None) or ayarlari_yukle(EKRAN_ALIS)

        def _uygula(ayar):
            self._alis_kolon_ayarlari = tabloya_uygula(self.satir_tablosu, EKRAN_ALIS, ayar)
            self._satir_ici_giris.tabloya_ekle()

        FaturaSatirKolonAyarDialog(
            self,
            EKRAN_ALIS,
            mevcut,
            on_uygula=_uygula,
            baslik="Alış Faturası — Kolon Ayarları",
        )

    def _alis_iskonto_ac(self, _event=None, idx: int | None = None):
        from fatura_iskonto_ui import satir_iskontolari_ac

        if idx is None:
            idx = self._alis_secili_index()
        if idx is None or not (0 <= idx < len(self.satirlar)):
            messagebox.showinfo("Çoklu İskonto", "Önce ürün satırı seçin.", parent=self)
            return "break"

        def _uygula(oranlar):
            if 0 <= idx < len(self.satirlar):
                self.satirlar[idx].update(oranlar)
                self._alis_fatura_yenile()

        satir_iskontolari_ac(
            self,
            belge_turu="Alış",
            satir=dict(self.satirlar[idx]),
            fiyat_alani="birim_fiyat",
            on_uygula=_uygula,
            satir_kimlik=idx,
        )
        return "break"

    def _satir_listesini_yenile(self):
        from database.iskonto_hesap_service import iskonto_goster_metin, satir_iskonto_hesapla

        for item in self.satir_tablosu.get_children():
            self.satir_tablosu.delete(item)
        for sira, veri in enumerate(self.satirlar):
            miktar = decimal(veri.get("miktar", 0), "Miktar")
            fiyat = decimal(veri.get("birim_fiyat", veri.get("birim_alis_fiyati", 0)), "Fiyat")
            h = satir_iskonto_hesapla(
                miktar=miktar,
                brut_birim_fiyat=fiyat,
                iskonto1=veri.get("iskonto_orani", 0),
                iskonto2=veri.get("iskonto_orani_2", 0),
                iskonto3=veri.get("iskonto_orani_3", 0),
                kdv_orani=veri.get("kdv_orani", 0),
            )
            lot = veri.get("lot_no") or ""
            lot_girisi = veri.get("lot_girisi") or lot
            isk_metin = iskonto_goster_metin(
                veri.get("iskonto_orani", 0),
                veri.get("iskonto_orani_2", 0),
                veri.get("iskonto_orani_3", 0),
                bos_goster="",
            )
            self.satir_tablosu.insert("", "end", iid=str(sira), values=(
                veri.get("barkod", ""),
                veri["urun_kodu"],
                veri["urun_adi"],
                veri.get("aciklama", ""),
                miktar,
                veri.get("birim", "Adet"),
                para_goster(fiyat),
                isk_metin,
                kdv_oran_metni(veri.get("kdv_orani", 0)),
                para_goster(h["net_birim_fiyat"]),
                lot,
                lot_girisi,
                para_goster(h["net_tutar"]),
                veri.get("siparis_miktar", 0),
                veri.get("irsaliye_miktar", 0),
                miktar,
            ))
        giris = getattr(self, "_satir_ici_giris", None)
        if giris is not None:
            giris.tabloya_ekle()
        self._toplamlari_guncelle()

    def _bakiye_guncelle(self):
        tedarikci = self.tedarikci_map.get(self.tedarikci.get())
        if not tedarikci:
            self.mevcut_borc = Decimal("0")
            self._cari_ozet = {"bakiye": Decimal("0"), "ortalama_vade": None}
            self._readonly_yaz("mevcut_bakiye", "0,00 TL")
            self._toplamlari_guncelle(Decimal("0"))
            return
        ozet = AlisFaturasiService.bakiye_ozeti(
            tedarikci.id, Decimal("0"), None, self.fatura.fatura_no if self.fatura else None
        )
        self._cari_ozet = ozet
        self.mevcut_borc = ozet["bakiye"]
        self._readonly_yaz("mevcut_bakiye", para_goster(self.mevcut_borc))
        self._toplamlari_guncelle(self.mevcut_borc)

    def _alis_odeme_ozet_yenile(self):
        odeme = sum((decimal(o["tutar"], "Ödeme") for o in self.odemeler), Decimal("0"))
        net = getattr(self, "_alis_net_toplam", Decimal("0"))
        kalan = net - odeme
        if hasattr(self, "odeme_ozet"):
            self.odeme_ozet.configure(
                text=f"Ödenen: {para_goster(odeme)} | Kalan: {para_goster(kalan)}"
            )

    def _toplamlari_guncelle(self, borc=None):
        """Satırlardan doğal alış fatura toplamlarını yeniden hesapla."""
        if not getattr(self, "_fatura_yukleniyor", False):
            self._fatura_form_kirli = True
        satirlar_hesap = []
        for veri in self.satirlar:
            satirlar_hesap.append({
                "miktar": veri.get("miktar", 0),
                "birim_fiyat": veri.get("birim_fiyat", veri.get("birim_alis_fiyati", 0)),
                "iskonto_orani": veri.get("iskonto_orani", 0),
                "iskonto_orani_2": veri.get("iskonto_orani_2", 0),
                "iskonto_orani_3": veri.get("iskonto_orani_3", 0),
                "kdv_orani": veri.get("kdv_orani", 0),
            })
        toplam = AlisFaturasiService.toplam(satirlar_hesap)
        satir_genel = toplam["genel_toplam"]
        self._alis_satir_brut = satir_genel
        self._alis_net_toplam = satir_genel
        if hasattr(self, "satir_ozet"):
            self.satir_ozet.configure(
                text=(
                    f"Ara Toplam: {para_goster(toplam['ara_toplam'])} | "
                    f"İskonto: {para_goster(toplam['iskonto'])} | "
                    f"KDV: {para_goster(toplam['kdv'])} | "
                    f"Genel: {para_goster(satir_genel)}"
                )
            )
        if getattr(self, "_alis_brut_lbl", None) is not None:
            try:
                self._alis_brut_lbl.configure(text=para_goster(satir_genel))
            except tk.TclError:
                pass
        if getattr(self, "_alis_net_lbl", None) is not None:
            try:
                self._alis_net_lbl.configure(text=para_goster(satir_genel))
            except tk.TclError:
                pass
        try:
            self._alis_odeme_ozet_yenile()
        except Exception:
            pass
        self._cari_ozet_yenile(satir_genel)

    def _cari_ozet_yenile(self, fatura_toplami: Decimal):
        etiketler = getattr(self, "_cari_ozet_etiketleri", None)
        if not etiketler:
            return
        ozet = getattr(self, "_cari_ozet", None) or {}
        mevcut = decimal(ozet.get("bakiye") or 0, "Bakiye")
        odeme = sum((decimal(o["tutar"], "Ödeme") for o in getattr(self, "odemeler", [])), Decimal("0"))
        kalan = fatura_toplami - odeme
        yeni = mevcut + kalan
        vade_metni = "—"
        try:
            vade = datetime.strptime(self.girdiler["vade_tarihi"].get(), "%d.%m.%Y").date()
        except (ValueError, KeyError, tk.TclError):
            vade = None
        ort = ozet.get("ortalama_vade")
        agirlik = Decimal("0")
        pay = Decimal("0")
        if ort and mevcut > 0:
            agirlik += mevcut
            pay += Decimal(ort.toordinal()) * mevcut
        if vade and kalan > 0:
            agirlik += kalan
            pay += Decimal(vade.toordinal()) * kalan
        if agirlik > 0:
            vade_metni = tarih_goster(date.fromordinal(int(pay / agirlik)))
        try:
            etiketler["mevcut"].configure(text=para_goster(mevcut))
            etiketler["fatura"].configure(text=para_goster(fatura_toplami))
            etiketler["yeni"].configure(text=para_goster(yeni))
            etiketler["vade"].configure(text=vade_metni)
            self._readonly_yaz("tahmini_bakiye", para_goster(yeni))
        except (tk.TclError, KeyError):
            pass

    def odeme_ekle(self):
        dialog = AlisSiparisOdemeDialog(self)
        self.wait_window(dialog)
        if dialog.result:
            self.odemeler.append(dialog.result)
            self._odeme_listesini_yenile()

    def odeme_duzenle(self):
        secim = self.odeme_tablosu.selection()
        if not secim:
            return
        idx = int(secim[0])
        dialog = AlisSiparisOdemeDialog(self, self.odemeler[idx])
        self.wait_window(dialog)
        if dialog.result:
            self.odemeler[idx] = dialog.result
            self._odeme_listesini_yenile()

    def odeme_kaldir(self):
        secim = self.odeme_tablosu.selection()
        if secim:
            self.odemeler.pop(int(secim[0]))
            self._odeme_listesini_yenile()

    def _odeme_listesini_yenile(self):
        for item in self.odeme_tablosu.get_children():
            self.odeme_tablosu.delete(item)
        for sira, o in enumerate(self.odemeler):
            self.odeme_tablosu.insert("", "end", iid=str(sira), values=(
                o["odeme_tarihi"].strftime("%d.%m.%Y"),
                para_goster(decimal(o["tutar"], "Tutar")),
                o["odeme_sekli"],
                o.get("hesap", ""),
                o.get("aciklama", ""),
            ))
        self._toplamlari_guncelle()

    def _siparis_yukle(self, siparis):
        self.kaynak_siparis = siparis
        self._tedarikci_sec(siparis.cari)
        self.siparis_no.delete(0, "end")
        self.siparis_no.insert(0, siparis.siparis_no)
        self.satirlar.clear()
        for satir in siparis.satirlar:
            acik = satir.miktar - satir.faturalanan_miktar
            if acik <= 0:
                continue
            self.satirlar.append({
                "siparis_satiri_id": satir.id,
                "urun_kodu": satir.urun_kodu,
                "urun_adi": satir.urun_adi,
                "barkod": "",
                "aciklama": satir.aciklama or "",
                "miktar": acik,
                "birim": satir.birim,
                "birim_fiyat": satir.birim_alis_fiyati,
                "birim_alis_fiyati": satir.birim_alis_fiyati,
                "iskonto_orani": satir.iskonto_orani,
                "iskonto_orani_2": getattr(satir, "iskonto_orani_2", 0) or 0,
                "iskonto_orani_3": getattr(satir, "iskonto_orani_3", 0) or 0,
                "kdv_orani": satir.kdv_orani,
                "lot_no": "",
                "lot_girisi": "",
                "siparis_miktar": satir.miktar,
                "irsaliye_miktar": satir.irsaliyelenen_miktar,
                "faturalanan_miktar": satir.faturalanan_miktar,
            })
        if not self.satirlar:
            messagebox.showinfo("Fatura", "Bu siparişte faturalanacak açık miktar kalmadı.", parent=self)
        self._bakiye_guncelle()
        self._satir_listesini_yenile()

    def _irsaliyeyi_doldur(self, irsaliye):
        self.kaynak_irsaliye = irsaliye
        self._tedarikci_sec(irsaliye.cari)
        self.irsaliye_no.delete(0, "end")
        self.irsaliye_no.insert(0, irsaliye.irsaliye_no)
        if irsaliye.siparis:
            self.kaynak_siparis = irsaliye.siparis
            self.siparis_no.delete(0, "end")
            self.siparis_no.insert(0, irsaliye.siparis.siparis_no)
        self.satirlar.clear()
        for satir in irsaliye.satirlar:
            kalan = satir.miktar - satir.faturalanan_miktar
            if kalan <= 0:
                continue
            self.satirlar.append({
                "irsaliye_satiri_id": satir.id,
                "siparis_satiri_id": satir.siparis_satiri_id,
                "urun_kodu": satir.urun_kodu,
                "urun_adi": satir.urun_adi,
                "barkod": "",
                "aciklama": satir.aciklama or "",
                "miktar": kalan,
                "birim": satir.birim,
                "birim_fiyat": satir.birim_fiyat,
                "iskonto_orani": satir.iskonto_orani,
                "iskonto_orani_2": getattr(satir, "iskonto_orani_2", 0) or 0,
                "iskonto_orani_3": getattr(satir, "iskonto_orani_3", 0) or 0,
                "kdv_orani": satir.kdv_orani,
                "lot_no": "",
                "lot_girisi": "",
                "siparis_miktar": 0,
                "irsaliye_miktar": kalan,
                "faturalanan_miktar": 0,
            })
        self._bakiye_guncelle()
        self._satir_listesini_yenile()

    def _faturayi_doldur(self):
        self._fatura_yukleniyor = True
        bilgi = getattr(self, "_odeme_kapatma_bilgisi", None)
        if bilgi is not None:
            try:
                bilgi.yenile()
            except Exception:
                pass
        try:
            fatura = self.fatura
            self._tedarikci_sec(fatura.cari)
            self._readonly_yaz("fatura_no", fatura.fatura_no or "")
            self._entry_yaz("tedarikci_fatura_no", getattr(fatura, "tedarikci_fatura_no", None) or "")
            self._entry_yaz("fatura_tarihi", tarih_goster(fatura.fatura_tarihi))
            self._entry_yaz(
                "islem_saati",
                saat_varsayilan(fatura.islem_saati or fatura.olusturma_tarihi.strftime("%H:%M")),
            )
            self._entry_yaz("vade_tarihi", tarih_goster(fatura.vade_tarihi))
            self.girdiler["vade_gunu"].delete(0, "end")
            self.girdiler["vade_gunu"].insert(0, str(fatura.vade_gunu or 0))
            self.durum.configure(state="readonly")
            self.durum.set(fatura.durum)
            self.durum.configure(state="disabled")
            self._entry_yaz("aciklama", fatura.aciklama or "")
            self.siparis_no.delete(0, "end")
            self.siparis_no.insert(0, fatura.siparis.siparis_no if fatura.siparis else "")
            self.irsaliye_no.delete(0, "end")
            self.irsaliye_no.insert(0, fatura.irsaliye.irsaliye_no if fatura.irsaliye else "")
            if fatura.depo:
                self.depo.set(fatura.depo)
            self.dokuman.delete(0, "end")
            self.dokuman.insert(0, fatura.dokuman_yolu or "")
            self.satirlar.clear()
            fatura_pb = (getattr(fatura, "para_birimi", None) or "TRY").upper()
            for satir in fatura.satirlar:
                bf = satir.birim_fiyat
                bf_doviz = getattr(satir, "birim_fiyat_doviz", None) or 0
                if fatura_pb != "TRY" and bf_doviz:
                    bf = bf_doviz
                self.satirlar.append({
                    "siparis_satiri_id": satir.siparis_satiri_id,
                    "irsaliye_satiri_id": satir.irsaliye_satiri_id,
                    "urun_kodu": satir.urun_kodu,
                    "urun_adi": satir.urun_adi,
                    "barkod": satir.barkod or "",
                    "aciklama": satir.aciklama or "",
                    "miktar": satir.miktar,
                    "birim": satir.birim,
                    "birim_fiyat": bf,
                    "birim_alis_fiyati": bf,
                    "birim_fiyat_doviz": bf_doviz or None,
                    "iskonto_orani": satir.iskonto_orani,
                    "iskonto_orani_2": getattr(satir, "iskonto_orani_2", 0) or 0,
                    "iskonto_orani_3": getattr(satir, "iskonto_orani_3", 0) or 0,
                    "kdv_orani": satir.kdv_orani,
                    "lot_no": satir.lot_no or "",
                    "lot_girisi": satir.lot_girisi or satir.lot_no or "",
                    "siparis_miktar": satir.miktar if satir.siparis_satiri_id else 0,
                    "irsaliye_miktar": satir.miktar if satir.irsaliye_satiri_id else 0,
                    "faturalanan_miktar": satir.miktar,
                })
            self.odemeler.clear()
            if fatura.odeme_tutari:
                self.odemeler.append({
                    "odeme_tarihi": fatura.fatura_tarihi,
                    "tutar": fatura.odeme_tutari,
                    "odeme_sekli": fatura.odeme_sekli or ODEME_SEKILLERI[0],
                    "hesap": fatura.odeme_hesabi or "",
                    "aciklama": "Fatura ödemesi",
                })
            self._bakiye_guncelle()
            self._satir_listesini_yenile()
            self._odeme_listesini_yenile()
            # Legacy override yok; toplam satırlardan
            self._toplamlari_guncelle()
            if hasattr(self, "_alis_toolbar"):
                self._toolbar_guncelle()
                self._doviz_gorunumu_guncelle()
        finally:
            self._fatura_yukleniyor = False
            self._fatura_form_kirli = False

    def kaydet(self):
        """Kaydeder; pencere açık kalır ve kayıt yeniden yüklenir."""
        return self._kaydet_kapatmadan()

    def _masraf_dagitimlari(self):
        if not self.fatura:
            messagebox.showinfo("Masraf Dağıtımı", "Önce faturayı kaydedin.", parent=self)
            return
        from masraf_dagitim_ui import bagli_dagitimlar_goster

        bagli_dagitimlar_goster(self, alis_fatura_id=int(self.fatura.id))

    def faturayi_iptal_et(self):
        if not self.fatura:
            self.destroy()
            return
        if messagebox.askyesno("Faturayı iptal et", "Bu fatura iptal edilsin mi?", parent=self):
            try:
                AlisFaturasiService.iptal_et(self.fatura.id)
            except ValueError as hata:
                messagebox.showerror("İşlem yapılamadı", str(hata), parent=self)
                return
            self.result = True
            self.destroy()


class _ListeSecDialog(tk.Toplevel):
    def __init__(self, parent, baslik, etiketler):
        super().__init__(parent)
        self.result = None
        self.title(baslik)
        self.geometry("480x320")
        self.transient(parent)
        self.grab_set()
        self.liste = tk.Listbox(self)
        self.liste.pack(fill="both", expand=True, padx=10, pady=10)
        for e in etiketler:
            self.liste.insert("end", e)
        ttk.Button(self, text="Seç", command=self.sec).pack(pady=8)

    def sec(self):
        secim = self.liste.curselection()
        if secim:
            self.result = secim[0]
            self.destroy()


class AlisIadeFaturasiDialog(_AlisSatirGirisi, tk.Toplevel):
    _fiyat_alani = "birim_fiyat"

    def __init__(self, parent, iade=None, kaynak_fatura=None):
        super().__init__(parent)
        self.iade = iade
        self.result = None
        self.title("SATIN ALMA İADE FATURASI")
        self.geometry("980x640")
        self.transient(parent)
        self.grab_set()
        self.satirlar = []
        self.kaynak = kaynak_fatura
        from database.alis_faturasi_service import ODEME_SEKILLERI as FAT_ODEME
        tedarikciler = list(AlisIadeFaturasiService.aktif_tedarikcileri())
        for belge in (iade, kaynak_fatura):
            if belge and belge.cari and belge.cari not in tedarikciler:
                tedarikciler.append(belge.cari)
        self.tedarikci_map = {f"{c.cari_kodu} - {c.unvan}": c for c in tedarikciler}
        self.depolar = [d.ad for d in StokService.depolar()] or ["ANA DEPO"]
        self.tedarikci = tk.StringVar()
        self.depo = tk.StringVar(value=self.depolar[0])
        ust = ttk.Frame(self, padding=10)
        ust.pack(fill="x")
        ttk.Label(ust, text="Tedarikçi").grid(row=0, column=0, sticky="w")
        self.tedarikci_combo = ttk.Combobox(ust, textvariable=self.tedarikci, values=list(self.tedarikci_map), width=40)
        self.tedarikci_combo.grid(row=0, column=1, padx=6, sticky="w")
        ttk.Label(ust, text="Depo").grid(row=0, column=2, sticky="w", padx=(12, 0))
        ttk.Combobox(ust, textvariable=self.depo, values=self.depolar, width=18).grid(row=0, column=3, padx=6)
        self.tarih = ttk.Entry(ust, width=16)
        self.tarih.insert(0, date.today().strftime("%d.%m.%Y"))
        ttk.Label(ust, text="İade Tarihi").grid(row=1, column=0, sticky="w")
        self.tarih.grid(row=1, column=1, sticky="w", padx=6)
        self.aciklama = ttk.Entry(ust, width=42)
        ttk.Label(ust, text="Açıklama").grid(row=2, column=0, sticky="w")
        self.aciklama.grid(row=2, column=1, sticky="w", padx=6)
        ttk.Label(ust, text="Kaynak Fatura").grid(row=3, column=0, sticky="w")
        self.kaynak_lbl = ttk.Label(ust, text=kaynak_fatura.fatura_no if kaynak_fatura else "-")
        self.kaynak_lbl.grid(row=3, column=1, sticky="w", padx=6)
        ttk.Button(ust, text="Kaynak Fatura Seç", command=self.kaynak_sec).grid(row=3, column=2, padx=6)
        ttk.Label(ust, text="Şube").grid(row=3, column=3, sticky="w", padx=(12, 0))
        from sube_ui import sube_secim_hazirla

        kaynak_sube_id = getattr(iade, "sube_id", None) if iade else getattr(kaynak_fatura, "sube_id", None)
        self.sube, self._sube_map = sube_secim_hazirla(ust, kaynak_sube_id)
        self.sube.grid(row=3, column=4, padx=6, sticky="w")
        ttk.Label(ust, text="İade Ödeme").grid(row=4, column=0, sticky="w")
        self.iade_odeme_tutari = ttk.Entry(ust, width=16)
        self.iade_odeme_tutari.insert(0, "0")
        self.iade_odeme_tutari.grid(row=4, column=1, sticky="w", padx=6)
        ttk.Label(ust, text="Ödeme Şekli").grid(row=5, column=0, sticky="w")
        self.iade_odeme_sekli = ttk.Combobox(ust, values=FAT_ODEME, width=40)
        self.iade_odeme_sekli.set(FAT_ODEME[0])
        self.iade_odeme_sekli.grid(row=5, column=1, sticky="w", padx=6)
        ttk.Label(ust, text="Ödeme Hesabı").grid(row=6, column=0, sticky="w")
        self.iade_odeme_hesabi = ttk.Entry(ust, width=42)
        self.iade_odeme_hesabi.grid(row=6, column=1, sticky="w", padx=6)

        self.girdiler = {"iade_tarihi": self.tarih}
        doviz_cerceve = ttk.LabelFrame(self, text="DÖVİZ / KUR", padding=6)
        doviz_cerceve.pack(fill="x", padx=10, pady=4)
        self._doviz_fiyat_alani = "birim_fiyat"
        doviz_paneli_kur(self, doviz_cerceve)
        if iade:
            doviz_verilerini_doldur(self, iade)
        elif kaynak_fatura:
            doviz_verilerini_doldur(self, kaynak_fatura)

        orta = ttk.LabelFrame(self, text="İade Satırları", padding=8)
        orta.pack(fill="both", expand=True, padx=10)
        self.satir_tablosu = ttk.Treeview(
            orta, columns=("kod", "ad", "miktar", "birim", "fiyat"), show="headings",
        )
        for kolon, baslik, w in (
            ("kod", "Kod", 100), ("ad", "Ad", 220), ("miktar", "Miktar", 80), ("birim", "Birim", 70),
            ("fiyat", "Fiyat", 100),
        ):
            self.satir_tablosu.heading(kolon, text=baslik)
            self.satir_tablosu.column(kolon, width=w)
        self.satir_tablosu.pack(fill="both", expand=True)
        self._alis_girisi_kur()
        satir_btn = ttk.Frame(orta)
        satir_btn.pack(fill="x", pady=4)
        ttk.Label(
            satir_btn,
            text="Kaynak faturadan gelen satırlarda yalnızca miktar/fiyat değişir · "
            "son satıra ürün kodu/adı yazın · F10 stok listesi",
            foreground="#627D98",
        ).pack(side="left")
        ttk.Button(satir_btn, text="Satır Sil (Del)", command=self.satir_sil).pack(side="left", padx=6)

        alt = ttk.Frame(self, padding=10)
        alt.pack(fill="x")
        ttk.Button(alt, text="Kapat", command=self.destroy).pack(side="right")
        ttk.Button(alt, text="Kaydet", command=self.kaydet).pack(side="right", padx=8)

        if kaynak_fatura:
            self._kaynaktan_doldur(kaynak_fatura)
        elif iade:
            self._doldur()

    def kaynak_sec(self):
        faturalar = [k["fatura"] for k in AlisFaturasiService.listele() if k["fatura"].durum != "İPTAL"]
        if not faturalar:
            messagebox.showinfo("Fatura", "Alış faturası yok.", parent=self)
            return
        sec = _ListeSecDialog(self, "Kaynak fatura", [f"{f.fatura_no} - {f.cari.unvan}" for f in faturalar])
        self.wait_window(sec)
        if sec.result is not None:
            self._kaynaktan_doldur(faturalar[sec.result])

    def _tedarikci_sec(self, cari):
        anahtar = _tedarikci_ekle(self.tedarikci_map, cari)
        self.tedarikci_combo["values"] = list(self.tedarikci_map)
        if anahtar:
            self.tedarikci.set(anahtar)

    def _satirlari_yenile(self):
        for item in self.satir_tablosu.get_children():
            self.satir_tablosu.delete(item)
        for sira, s in enumerate(self.satirlar):
            self.satir_tablosu.insert("", "end", iid=str(sira), values=(
                s["urun_kodu"], s["urun_adi"], s["miktar"], s.get("birim") or "Adet", para_goster(s["birim_fiyat"]),
            ))
        self._satir_ici_giris.tabloya_ekle()

    def _alis_yenile(self):
        self._satirlari_yenile()

    def _kaynaktan_doldur(self, fatura):
        self.kaynak = fatura
        self.kaynak_lbl.configure(text=fatura.fatura_no)
        self._tedarikci_sec(fatura.cari)
        if fatura.depo:
            self.depo.set(fatura.depo)
        self.satirlar = []
        for satir in fatura.satirlar:
            self.satirlar.append({
                "kaynak_fatura_satiri_id": satir.id,
                "urun_kodu": satir.urun_kodu, "urun_adi": satir.urun_adi,
                "miktar": satir.miktar, "birim": satir.birim, "birim_fiyat": satir.birim_fiyat,
                "iskonto_orani": satir.iskonto_orani, "iskonto_orani_2": getattr(satir, "iskonto_orani_2", 0) or 0, "iskonto_orani_3": getattr(satir, "iskonto_orani_3", 0) or 0, "kdv_orani": satir.kdv_orani,
            })
        self._satirlari_yenile()

    def _doldur(self):
        i = self.iade
        self._tedarikci_sec(i.cari)
        self.tarih.delete(0, "end")
        self.tarih.insert(0, tarih_goster(i.iade_tarihi))
        self.aciklama.insert(0, i.aciklama or "")
        self.depo.set(i.depo or self.depolar[0])
        self.iade_odeme_tutari.delete(0, "end")
        self.iade_odeme_tutari.insert(0, str(i.iade_odeme_tutari or 0))
        if i.iade_odeme_sekli:
            self.iade_odeme_sekli.set(i.iade_odeme_sekli)
        self.iade_odeme_hesabi.insert(0, i.iade_odeme_hesabi or "")
        if i.kaynak_fatura:
            self.kaynak = i.kaynak_fatura
            self.kaynak_lbl.configure(text=i.kaynak_fatura.fatura_no)
        for satir in i.satirlar:
            self.satirlar.append({
                "kaynak_fatura_satiri_id": satir.kaynak_fatura_satiri_id,
                "urun_kodu": satir.urun_kodu, "urun_adi": satir.urun_adi,
                "miktar": satir.miktar, "birim": satir.birim, "birim_fiyat": satir.birim_fiyat,
                "iskonto_orani": satir.iskonto_orani, "iskonto_orani_2": getattr(satir, "iskonto_orani_2", 0) or 0, "iskonto_orani_3": getattr(satir, "iskonto_orani_3", 0) or 0, "kdv_orani": satir.kdv_orani,
            })
        self._satirlari_yenile()

    def kaydet(self):
        if not self._alis_bekleyenleri_uygula():
            return
        tedarikci = self.tedarikci_map.get(self.tedarikci.get())
        if not tedarikci or not self.satirlar:
            messagebox.showwarning("Eksik", "Tedarikçi ve satırlar gerekli.", parent=self)
            return
        try:
            veriler = {
                "iade_tarihi": datetime.strptime(self.tarih.get(), "%d.%m.%Y").date(),
                "cari_id": tedarikci.id,
                "sube_id": self._sube_map.get(self.sube.get()),
                "kaynak_fatura_id": self.kaynak.id if self.kaynak else None,
                "depo": self.depo.get() or "ANA DEPO",
                "aciklama": self.aciklama.get().strip() or None,
                "iade_odeme_tutari": self.iade_odeme_tutari.get(),
                "iade_odeme_sekli": self.iade_odeme_sekli.get() or None,
                "iade_odeme_hesabi": self.iade_odeme_hesabi.get().strip() or None,
            }
            if hasattr(self, "_doviz_para_birimi"):
                veriler.update(doviz_verilerini_topla(self))
            AlisIadeFaturasiService.kaydet(
                veriler,
                self.satirlar,
                self.iade.id if self.iade else None,
            )
        except ValueError as hata:
            messagebox.showerror("Kayıt", str(hata), parent=self)
            return
        self.result = True
        self.destroy()
