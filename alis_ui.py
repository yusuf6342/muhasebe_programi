"""Satın alma belge diyalogları (satış UI kalıplarının alış karşılığı)."""
from __future__ import annotations

import tkinter as tk
from datetime import date, datetime, timedelta
from decimal import Decimal
from tkinter import filedialog, messagebox, simpledialog, ttk
from birim_hatasi_ui import birim_hatasi_goster

import logging

from database.alis_faturasi_service import (
    ODEME_SEKILLERI,
    AlisFaturasiService,
    MukerrerTedarikciFaturaHatasi,
    alis_evrak_durumu,
    onay_hatalari,
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
from ui_takvim import saat_dogrula, saat_varsayilan, takvim_entry_bagla
from database.turkce_normalize import turkce_normalize
import fatura_tema as ftema
from cari_kart_tema import (
    ACIK_BG as T_ACIK_BG,
    BEYAZ as T_BEYAZ,
    CIZGI as T_CIZGI,
    IKINCIL as T_IKINCIL,
    LACIVERT as T_LACIVERT,
    SARI as T_SARI,
    font as t_font,
    stil_uygula as t_stil_uygula,
    tk_buton as t_buton,
)

BIRIM_SECENEKLERI = ("Adet", "Kg", "Metre", "Koli", "Paket", "Torba", "Boy", "Top")
ALIS_BELGE_BASLIGI = "ALIŞ FATURASI"
ALIS_TABLO_STILI = "AlisSatir.Treeview"
# Geriye uyumluluk; gerçek değer form_pady() ile açılışta alınır (~1,5 mm / 2 kenar)
ALIS_UST_PADY = 3
SEVKIYAT_YONTEMLERI = ("", "Kara", "Hava", "Deniz", "Demiryolu", "Kurye", "Kendi Aracımız", "Tedarikçi Aracı")
_LOG = logging.getLogger("alis_ui")


def para_goster(tutar):
    return f"{float(tutar):,.2f} TL".replace(",", "X").replace(".", ",").replace("X", ".")


def tarih_goster(tarih):
    return tarih.strftime("%d.%m.%Y")


def satin_alma_satir_ozellikleri(dialog) -> dict:
    """Satın alma evraklarında ortak: fiyat hücresine sağ tık geçmiş alışlar + kısa yeni ürün."""
    from alis_fiyat_gecmisi_ui import satirdan_fiyat_gecmisi

    tablo = dialog.satir_tablosu
    try:
        kolonlar = tuple(tablo["columns"])
    except tk.TclError:
        kolonlar = ()
    return {
        "fiyat_gecmisi": lambda i: satirdan_fiyat_gecmisi(dialog, dialog.satirlar, i, tablo),
        "fiyat_kolonu": "fiyat" if "fiyat" in kolonlar else None,
        "kisa_urun": True,
    }


def _tema_hazirla(pencere) -> None:
    """Lacivert/sarı tema: ttk stilleri + pencere arka planı."""
    try:
        t_stil_uygula(root=pencere)
    except Exception:  # noqa: BLE001
        pass
    try:
        pencere.configure(bg=T_ACIK_BG)
    except tk.TclError:
        pass


def _tema_baslik(pencere, baslik: str, alt_metin: str = "") -> dict:
    """Lacivert başlık şeridi + sarı çizgi; sağda sarı vurgulu tutar etiketi."""
    cubuk = tk.Frame(pencere, bg=T_LACIVERT)
    cubuk.pack(side="top", fill="x")
    sol = tk.Frame(cubuk, bg=T_LACIVERT)
    sol.pack(side="left", padx=(14, 8), pady=8)
    tk.Label(sol, text=baslik, bg=T_LACIVERT, fg=T_BEYAZ, font=t_font(16, "bold", pencere)).pack(anchor="w")
    alt = tk.Label(sol, text=alt_metin, bg=T_LACIVERT, fg=T_SARI, font=t_font(10, "bold", pencere))
    alt.pack(anchor="w")
    sag = tk.Label(cubuk, text="", bg=T_LACIVERT, fg=T_SARI, font=t_font(15, "bold", pencere))
    sag.pack(side="right", padx=16)
    tk.Frame(pencere, bg=T_SARI, height=3).pack(side="top", fill="x")
    return {"cubuk": cubuk, "alt": alt, "sag": sag}


def _tema_panel(parent, baslik: str) -> tuple[tk.Frame, tk.Frame]:
    """Başlıklı beyaz kart; (dış, iç) döner. İç çerçeveye grid ile alan eklenir."""
    dis = tk.Frame(parent, bg=T_BEYAZ, highlightthickness=1, highlightbackground=T_CIZGI)
    tk.Label(
        dis, text=baslik, bg=T_LACIVERT, fg=T_BEYAZ, font=t_font(10, "bold", parent),
        anchor="w", padx=10, pady=4,
    ).pack(fill="x")
    tk.Frame(dis, bg=T_SARI, height=2).pack(fill="x")
    ic = tk.Frame(dis, bg=T_BEYAZ)
    ic.pack(fill="both", expand=True, padx=10, pady=8)
    return dis, ic


def _tema_etiket(parent, metin: str) -> tk.Label:
    return tk.Label(parent, text=metin, bg=T_BEYAZ, fg=T_IKINCIL, font=t_font(9, root=parent), anchor="w")


def _tarih_opsiyonel(metin: str, alan: str):
    """Boş → None; dolu → gg.aa.yyyy date (hatalıysa ValueError)."""
    metin = (metin or "").strip()
    if not metin:
        return None
    try:
        return datetime.strptime(metin, "%d.%m.%Y").date()
    except ValueError as hata:
        raise ValueError(f"{alan} gg.aa.yyyy biçiminde olmalıdır.") from hata


def _depo_secenekleri() -> list[str]:
    """Depo adları (boş seçenek = firma varsayılan deposu)."""
    try:
        from database.stok_rapor_service import depo_adlari

        return [""] + list(depo_adlari())
    except Exception:  # noqa: BLE001
        return [""]


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
    # True: "isk" hücresi 3 kademeli (10+5+2) iskonto girişi yapar (alış siparişi)
    _uclu_iskonto = False

    def _alis_girisi_kur(self):
        from satir_ici_urun_giris import (
            HucreAlani, SatirHucreDuzenleyici, SatirIciUrunGirisi, iskonto_metni, sayi_metni,
        )

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
            **satin_alma_satir_ozellikleri(self),
        )
        self._hucre = SatirHucreDuzenleyici(
            self,
            self.satir_tablosu,
            [
                HucreAlani("miktar", deger=lambda i: sayi_metni(self.satirlar[i].get("miktar") or 0)),
                HucreAlani("birim", "secim", secenekler=self._alis_birimleri),
                HucreAlani("fiyat", deger=lambda i: sayi_metni(self.satirlar[i].get(self._fiyat_alani) or 0)),
                (
                    HucreAlani("isk", "iskonto3", deger=lambda i: iskonto_metni(self.satirlar[i]))
                    if self._uclu_iskonto
                    else HucreAlani("isk", deger=lambda i: sayi_metni(self.satirlar[i].get("iskonto_orani") or 0))
                ),
                HucreAlani("kdv", "secim", secenekler=lambda _i: ("0", "1", "10", "20"), serbest=True,
                           deger=lambda i: sayi_metni(self.satirlar[i].get("kdv_orani") or 0)),
            ],
            uygula=self.alis_hucre_uygula,
            satir_sayisi=lambda: len(self.satirlar),
            bitince=self._satir_ici_giris.odakla,
        )
        self.satir_tablosu.bind("<Delete>", lambda _e: self.satir_sil())
        self._satir_ici_giris.tabloya_ekle()
        from fiyat_kaynagi_ui import fiyat_notu_bagla

        fiyat_notu_bagla(self, self.satir_tablosu, lambda: self.satirlar)
        self.after_idle(lambda: setattr(self, "_ilk_ozet", self._belge_ozeti()))
        from evrak_baslik_gezinme import baslik_gezinme_kur

        baslik_gezinme_kur(self, getattr(self, "_baslik_kaplari", None), son_hedef=self._satir_ici_giris.odakla)

    def _alis_yenile(self):
        raise NotImplementedError

    def _satir_toplu_yenile(self):
        self._alis_yenile()

    _liste_komutu = ""
    _belge_adi = "Belge"

    def _belge_ozeti(self):
        try:
            ted = self.tedarikci.get()
        except (AttributeError, tk.TclError):
            ted = ""
        return repr([sorted((k, str(v)) for k, v in s.items()) for s in self.satirlar]), ted

    def _kayitli_belge(self):
        return None

    def listeye_git(self):
        """İlgili listeye geçer; değişiklik varsa Kaydet / Kaydetmeden / Vazgeç sorulur."""
        from satin_alma_ui import belgeden_listeye_git

        app = self._root()
        liste_fn = getattr(app, self._liste_komutu, None)
        if not callable(liste_fn):
            return
        if self.satirlar and getattr(self, "_ilk_ozet", None) != self._belge_ozeti():
            cevap = messagebox.askyesnocancel(
                "Listeye Git",
                f"{self._belge_adi} kaydedilmemiş değişiklik içeriyor.\n\n"
                "Evet: Kaydet ve listeye git\nHayır: Kaydetmeden listeye git\nİptal: Belgede kal",
                parent=self,
            )
            if cevap is None:
                return
            if cevap:
                self.kaydet()
                try:
                    if self.winfo_exists():
                        return
                except tk.TclError:
                    pass
        belge = self._kayitli_belge()
        try:
            if self.winfo_exists():
                self.destroy()
        except tk.TclError:
            pass
        belgeden_listeye_git(app, liste_fn, getattr(belge, "id", None))

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
            from birim_secim_ui import evrak_birim_secenekleri

            return evrak_birim_secenekleri(s.get("urun_kodu") or "") or list(BIRIM_SECENEKLERI)
        except Exception:
            return list(BIRIM_SECENEKLERI)

    def _alis_satiri(self, degerler) -> dict:
        from fiyat_kaynagi_ui import alis_fiyati_coz, sonucu_satira_yaz
        from satir_ici_urun_giris import ondalik

        kod = (degerler[0] if degerler else "") or ""
        if not kod:
            raise ValueError("Ürün kodu boş.")
        birim = (degerler[2] if len(degerler) > 2 else "") or "Adet"
        kdv_metin = degerler[6] if len(degerler) > 6 else None
        try:
            kdv = ondalik(kdv_metin, Decimal("20")) if kdv_metin not in (None, "") else Decimal("20")
        except ValueError:
            kdv = Decimal("20")
        sonuc = alis_fiyati_coz(self, kod, birim, kdv)
        veri = {
            "urun_kodu": kod, "urun_adi": (degerler[1] if len(degerler) > 1 else "") or "",
            "aciklama": "", "miktar": Decimal("1"), "birim": birim,
            self._fiyat_alani: sonuc.fiyat if sonuc.fiyat is not None else Decimal("0"),
            "iskonto_orani": Decimal("0"), "iskonto_orani_2": Decimal("0"), "iskonto_orani_3": Decimal("0"),
            "kdv_orani": kdv,
        }
        return sonucu_satira_yaz(veri, sonuc)

    def _alis_fiyati_yenile(self, idx: int) -> None:
        from fiyat_kaynagi_ui import alis_fiyati_coz, fiyat_notu_goster, sonucu_satira_yaz, yenileme_onayi

        if not (0 <= idx < len(self.satirlar)):
            return
        s = self.satirlar[idx]
        if self._alis_bagli(s):
            messagebox.showinfo("Fiyatı Yenile", "Bağlı belgeden gelen satırın fiyatı korunur.", parent=self)
            return
        if not yenileme_onayi(self, s):
            return
        sonuc = alis_fiyati_coz(self, s.get("urun_kodu") or "", s.get("birim") or "", s.get("kdv_orani"))
        yeni = dict(s)
        if sonuc.fiyat is not None:
            yeni[self._fiyat_alani] = sonuc.fiyat
        sonucu_satira_yaz(yeni, sonuc)
        self.satirlar[idx] = yeni
        self._alis_yenile()
        fiyat_notu_goster(self, self.satir_tablosu, yeni)

    def _alis_urun_ekle(self, degerler, konum):
        from satir_ici_urun_giris import birlesecek_satir, giris_bileseni, toplu_ekleme_mi

        veri = self._alis_satiri(degerler)
        giris = giris_bileseni(self)
        if giris is not None and giris.son_islem == "barkod" and konum is None:
            adaylar = [s if not self._alis_bagli(s) else {**s, "siparis_satiri_id": -1} for s in self.satirlar]
            idx = birlesecek_satir(
                adaylar, veri, fiyat_alani=self._fiyat_alani,
                ek_alanlar=("iskonto_orani", "iskonto_orani_2", "iskonto_orani_3"),
            )
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
            from fiyat_kaynagi_ui import fiyat_notu_goster

            fiyat_notu_goster(self, self.satir_tablosu, veri)
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
            from birim_secim_ui import kart_birimini_hazirla

            if not kart_birimini_hazirla(self, s.get("urun_kodu") or "", birim):
                return
            from fiyat_kaynagi_ui import alis_fiyati_coz, birim_degisiminde_yeniden_fiyat, sonucu_satira_yaz

            karar = birim_degisiminde_yeniden_fiyat(self, s)
            if karar is None:
                return
            yeni["birim"] = birim
            if karar:
                sonuc = alis_fiyati_coz(self, s.get("urun_kodu") or "", birim, s.get("kdv_orani"))
                yeni[self._fiyat_alani] = sonuc.fiyat if sonuc.fiyat is not None else Decimal("0")
                sonucu_satira_yaz(yeni, sonuc)
        elif kolon == "fiyat":
            from fiyat_kaynagi_ui import elle_isaretle

            yeni[self._fiyat_alani] = decimal(metin or 0, "Birim alış", Decimal("0"))
            if yeni[self._fiyat_alani] != decimal(s.get(self._fiyat_alani) or 0, "Birim alış", Decimal("0")):
                elle_isaretle(yeni)
        elif kolon == "isk" and self._uclu_iskonto:
            from satir_ici_urun_giris import iskonto_metni_coz

            i1, i2, i3 = iskonto_metni_coz(metin)
            yeni["iskonto_orani"], yeni["iskonto_orani_2"], yeni["iskonto_orani_3"] = i1, i2, i3
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
            if self._fiyat_alani:
                ogeler.insert(2, ("Fiyatı Yenile", lambda: self._alis_fiyati_yenile(idx)))
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
    _uclu_iskonto = True
    _liste_komutu = "alis_siparisleri_goster"
    _belge_adi = "Alış siparişi"

    def _kayitli_belge(self):
        return self.result or self.siparis

    def __init__(self, parent, siparis=None, cari=None, hazir_satirlar=None):
        super().__init__(parent)
        self.siparis = siparis
        self.result = None
        self.mevcut_borc = Decimal("0")
        self.title("ALIŞ SİPARİŞİ")
        self.geometry("1180x720")
        self.minsize(980, 580)
        self.grab_set()
        from ui_pencere import pencere_os_krom_ac

        pencere_os_krom_ac(self)
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

        _tema_hazirla(self)
        baslik = _tema_baslik(self, "SATIN ALMA SİPARİŞİ", "Alış siparişi")
        self._baslik_tutar = baslik["sag"]
        self._baslik_alt = baslik["alt"]

        # Alt kısım (butonlar + toplam şeridi) önce pack edilir; böylece pencere küçülünce de görünür kalır.
        alt = tk.Frame(self, bg=T_ACIK_BG, padx=10, pady=8)
        alt.pack(side="bottom", fill="x")
        t_buton(alt, "Listeye Git", self.listeye_git, rol="ikincil").pack(side="left")
        t_buton(alt, "Kapat", self.destroy, rol="ikincil").pack(side="right")
        t_buton(alt, "Kaydet", self.kaydet, rol="vurgu").pack(side="right", padx=8)

        toplam_seridi = tk.Frame(self, bg=T_LACIVERT, padx=14, pady=6)
        toplam_seridi.pack(side="bottom", fill="x")
        self._brut_lbl = tk.Label(
            toplam_seridi, text="Brüt: 0,00", bg=T_LACIVERT, fg=T_BEYAZ, font=t_font(9, root=self),
        )
        self._brut_lbl.pack(side="left", padx=(0, 12))
        self._iskonto_toplam_lbl = tk.Label(
            toplam_seridi, text="İskonto: 0,00", bg=T_LACIVERT, fg=T_BEYAZ, font=t_font(9, root=self),
        )
        self._iskonto_toplam_lbl.pack(side="left", padx=(0, 12))
        self._ara_lbl = tk.Label(
            toplam_seridi, text="Ara: 0,00", bg=T_LACIVERT, fg=T_BEYAZ, font=t_font(9, root=self),
        )
        self._ara_lbl.pack(side="left", padx=(0, 12))
        self._kdv_lbl = tk.Label(
            toplam_seridi, text="KDV: 0,00", bg=T_LACIVERT, fg=T_BEYAZ, font=t_font(9, root=self),
        )
        self._kdv_lbl.pack(side="left", padx=(0, 16))
        tk.Label(
            toplam_seridi, text="SİPARİŞ TOPLAMI", bg=T_LACIVERT, fg=T_BEYAZ, font=t_font(10, "bold", self),
        ).pack(side="left")
        self._tutar_lbl = tk.Label(
            toplam_seridi, text="0,00 TL", bg=T_LACIVERT, fg=T_SARI, font=t_font(18, "bold", self),
        )
        self._tutar_lbl.pack(side="left", padx=(12, 24))
        self._odeme_lbl = tk.Label(
            toplam_seridi, text="Ödeme / Avans: 0,00 TL", bg=T_LACIVERT, fg=T_BEYAZ, font=t_font(10, root=self),
        )
        self._odeme_lbl.pack(side="right")

        ust = tk.Frame(self, bg=T_ACIK_BG)
        ust.pack(fill="x", padx=10, pady=(8, 4))
        self._genel_olustur(ust)

        aciklama_fr = tk.Frame(self, bg=T_ACIK_BG, padx=10)
        aciklama_fr.pack(fill="x")
        tk.Label(aciklama_fr, text="Açıklama", bg=T_ACIK_BG, fg=T_LACIVERT, font=t_font(10, "bold", self)).pack(side="left")
        self.girdiler["aciklama"] = ttk.Entry(aciklama_fr)
        self.girdiler["aciklama"].pack(side="left", fill="x", expand=True, padx=8)
        self._baslik_kaplari = [ust, aciklama_fr]

        self._sekmeler = ttk.Notebook(self)
        self._sekmeler.pack(fill="both", expand=True, padx=10, pady=4)
        orta = ttk.Frame(self._sekmeler, padding=8)
        self._sekmeler.add(orta, text="Ürün Satırları")
        try:
            import siparis_tema as stema

            stema.stil_uygula(root=self)
            stil_adi = "SiparisSatir.Treeview"
        except Exception:
            stil_adi = "Treeview"
            ttk.Style(self).configure(
                "Treeview",
                rowheight=ftema.tablo_satir_rowheight(self),
            )
        self.satir_tablosu = ttk.Treeview(
            orta, columns=("kod", "ad", "miktar", "birim", "fiyat", "isk", "kdv", "tutar"),
            show="headings", height=10, style=stil_adi,
        )
        for kolon, baslik_metni, w in (
            ("kod", "Kod", 100), ("ad", "Ad", 220), ("miktar", "Miktar", 80),
            ("birim", "Birim", 70), ("fiyat", "Alış Fiyatı", 100), ("isk", "İskonto (10+5+2)", 130),
            ("kdv", "KDV%", 60), ("tutar", "Satır Tutarı", 110),
        ):
            self.satir_tablosu.heading(kolon, text=baslik_metni)
            self.satir_tablosu.column(kolon, width=w)
        self.satir_tablosu.pack(fill="both", expand=True)
        try:
            from treeview_excel_cizgi import excel_cizgi_bagla

            self.after_idle(
                lambda: excel_cizgi_bagla(
                    self, self.satir_tablosu, style_name=stil_adi, bag_adi="alis_siparis"
                )
            )
        except Exception:
            pass
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

        odeme_cerceve = ttk.Frame(self._sekmeler, padding=8)
        self._sekmeler.add(odeme_cerceve, text="Ödemeler / Avans")
        self.odeme_tablosu = ttk.Treeview(
            odeme_cerceve, columns=("tarih", "tutar", "sekil", "hesap"), show="headings", height=6,
        )
        for kolon, baslik_metni in (("tarih", "Tarih"), ("tutar", "Tutar"), ("sekil", "Şekil"), ("hesap", "Hesap")):
            self.odeme_tablosu.heading(kolon, text=baslik_metni)
            self.odeme_tablosu.column(kolon, width=120)
        self.odeme_tablosu.pack(fill="both", expand=True)
        odeme_btn = ttk.Frame(odeme_cerceve)
        odeme_btn.pack(fill="x", pady=4)
        ttk.Button(odeme_btn, text="Ödeme Ekle", command=self.odeme_ekle).pack(side="left")
        ttk.Button(odeme_btn, text="Ödeme Sil", command=self.odeme_sil).pack(side="left", padx=6)

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
            birim_hatasi_goster(self, hata) or messagebox.showerror("Talepten Aktar", str(hata), parent=self)
            return
        self.talep_satirlarini_ekle(hazir["satirlar"])

    def _genel_olustur(self, parent):
        """Üst kısım: 3 kısa panel (~41/29/30) — Tedarikçi ve Cari | Sipariş Bilgileri | Teslimat ve Organizasyon."""
        parent.columnconfigure(0, weight=41, uniform="alis_siparis_ust")
        parent.columnconfigure(1, weight=29, uniform="alis_siparis_ust")
        parent.columnconfigure(2, weight=30, uniform="alis_siparis_ust")
        parent.rowconfigure(0, weight=1)

        def _grid_panel(sutun, baslik):
            dis, ic = _tema_panel(parent, baslik)
            dis.grid(row=0, column=sutun, sticky="nsew", padx=(0 if sutun == 0 else 6, 0))
            ic.columnconfigure(0, weight=1, uniform=f"alis_siparis_ic{sutun}")
            ic.columnconfigure(1, weight=1, uniform=f"alis_siparis_ic{sutun}")
            return ic

        # 1) Tedarikçi ve Cari Hesap
        ic1 = _grid_panel(0, "Tedarikçi ve Cari Hesap")
        _tema_etiket(ic1, "Tedarikçi Adı (en az 2 harf yazın)").grid(row=0, column=0, columnspan=2, sticky="w")
        self.tedarikci_combo = ttk.Combobox(
            ic1, textvariable=self.tedarikci, values=list(self.tedarikci_map), state="normal",
        )
        self.tedarikci_combo.grid(row=1, column=0, columnspan=2, sticky="ew", pady=(0, 4))
        self.tedarikci_combo.bind("<<ComboboxSelected>>", self._tedarikci_kart_uygula)
        self.tedarikci_combo.bind("<KeyRelease>", self._tedarikci_arama_filtrele)
        _tema_etiket(ic1, "Kod").grid(row=2, column=0, columnspan=2, sticky="w")
        self.girdiler["tedarikci_kodu"] = ttk.Entry(ic1, state="readonly")
        self.girdiler["tedarikci_kodu"].grid(row=3, column=0, columnspan=2, sticky="ew", pady=(0, 4))
        _tema_etiket(ic1, "Mevcut Bakiye").grid(row=4, column=0, sticky="w")
        _tema_etiket(ic1, "Valör (gün)").grid(row=4, column=1, sticky="w", padx=(6, 0))
        self.girdiler["mevcut_bakiye"] = ttk.Entry(ic1, state="readonly")
        self.girdiler["mevcut_bakiye"].insert(0, "—")
        self.girdiler["mevcut_bakiye"].grid(row=5, column=0, sticky="ew", pady=(0, 4))
        self.girdiler["valor_gun"] = ttk.Entry(ic1)
        self.girdiler["valor_gun"].grid(row=5, column=1, sticky="ew", padx=(6, 0), pady=(0, 4))
        if self.siparis is not None and self.siparis.valor_gun is not None:
            self.girdiler["valor_gun"].insert(0, str(int(self.siparis.valor_gun)))
        _tema_etiket(ic1, "Sipariş dahil tahmini bakiye").grid(row=6, column=0, columnspan=2, sticky="w")
        self.girdiler["yeni_bakiye"] = ttk.Entry(ic1, state="readonly")
        self.girdiler["yeni_bakiye"].insert(0, "—")
        self.girdiler["yeni_bakiye"].grid(row=7, column=0, columnspan=2, sticky="ew")

        # 2) Sipariş Bilgileri
        ic2 = _grid_panel(1, "Sipariş Bilgileri")
        _tema_etiket(ic2, "Sipariş No").grid(row=0, column=0, columnspan=2, sticky="w")
        self.girdiler["siparis_no"] = ttk.Entry(ic2)
        siparis_no = self.siparis.siparis_no if self.siparis else AlisSiparisiService.siparis_no()
        self.girdiler["siparis_no"].insert(0, siparis_no)
        self.girdiler["siparis_no"].grid(row=1, column=0, columnspan=2, sticky="ew", pady=(0, 4))
        if self.siparis:
            self.girdiler["siparis_no"].configure(state="readonly")
        _tema_etiket(ic2, "Sipariş Tarihi").grid(row=2, column=0, columnspan=2, sticky="w")
        self.girdiler["siparis_tarihi"] = ttk.Entry(ic2)
        siparis_tarihi = (
            tarih_goster(self.siparis.siparis_tarihi)
            if self.siparis
            else date.today().strftime("%d.%m.%Y")
        )
        self.girdiler["siparis_tarihi"].insert(0, siparis_tarihi)
        self.girdiler["siparis_tarihi"].grid(row=3, column=0, columnspan=2, sticky="ew", pady=(0, 4))
        self.girdiler["siparis_tarihi"].bind("<FocusOut>", self._termin_tarih_uygula)
        _tema_etiket(ic2, "Durum").grid(row=4, column=0, columnspan=2, sticky="w")
        durum_satiri = tk.Frame(ic2, bg=T_BEYAZ)
        durum_satiri.grid(row=5, column=0, columnspan=2, sticky="ew")
        self.durum = ttk.Combobox(
            durum_satiri,
            values=("TASLAK", "AÇIK", "KISMİ İRSALİYELİ", "İRSALİYELİ", "KISMİ FATURALI", "FATURALI", "İPTAL"),
            state="readonly",
            width=18,
        )
        self.durum.pack(side="left", fill="x", expand=True)
        self.durum.set(self.siparis.durum if self.siparis else "AÇIK")
        t_buton(durum_satiri, "Tanımla", self._durum_tanimla, rol="ikincil").pack(side="left", padx=(6, 0))

        # 3) Teslimat ve Organizasyon
        ic3 = _grid_panel(2, "Teslimat ve Organizasyon")
        _tema_etiket(ic3, "Termin Günü").grid(row=0, column=0, sticky="w")
        _tema_etiket(ic3, "Beklenen Teslim Tarihi").grid(row=0, column=1, sticky="w", padx=(6, 0))
        self.girdiler["termin_gun"] = ttk.Entry(ic3)
        self.girdiler["termin_gun"].grid(row=1, column=0, sticky="ew", pady=(0, 4))
        self.girdiler["termin_gun"].bind("<KeyRelease>", self._termin_tarih_uygula)
        if self.siparis and self.siparis.siparis_tarihi and self.siparis.termin_tarihi:
            termin_gun = (self.siparis.termin_tarihi - self.siparis.siparis_tarihi).days
            self.girdiler["termin_gun"].insert(0, str(termin_gun))
        else:
            self.girdiler["termin_gun"].insert(0, "0")
        self.girdiler["termin_tarihi"] = ttk.Entry(ic3)
        termin_tarihi = (
            tarih_goster(self.siparis.termin_tarihi)
            if self.siparis
            else date.today().strftime("%d.%m.%Y")
        )
        self.girdiler["termin_tarihi"].insert(0, termin_tarihi)
        self.girdiler["termin_tarihi"].grid(row=1, column=1, sticky="ew", padx=(6, 0), pady=(0, 4))
        _tema_etiket(ic3, "Şube").grid(row=2, column=0, columnspan=2, sticky="w")
        from sube_ui import sube_secim_hazirla

        self.sube, self._sube_map = sube_secim_hazirla(
            ic3, getattr(self.siparis, "sube_id", None) if self.siparis else None
        )
        self.sube.grid(row=3, column=0, columnspan=2, sticky="ew", pady=(0, 4))
        _tema_etiket(ic3, "Teslim Alınacak Depo").grid(row=4, column=0, columnspan=2, sticky="w")
        self.teslim_depo = ttk.Combobox(ic3, values=_depo_secenekleri(), state="readonly")
        self.teslim_depo.grid(row=5, column=0, columnspan=2, sticky="ew")
        self.teslim_depo.set((getattr(self.siparis, "teslim_depo", None) or "") if self.siparis else "")

    def _durum_tanimla(self):
        messagebox.showinfo(
            "Durum Tanımla",
            "Sipariş durum kataloğu şimdilik sabit durum değerleriyle yönetilir "
            "(TASLAK, AÇIK, KISMİ İRSALİYELİ, İRSALİYELİ, KISMİ FATURALI, FATURALI, İPTAL).\n\n"
            "İrsaliye / fatura işlendikçe durum otomatik güncellenir; özel durum tanımları ileride eklenecek.",
            parent=self,
        )

    def _valor_yaz(self, gun) -> None:
        widget = self.girdiler.get("valor_gun")
        if widget is None:
            return
        widget.delete(0, "end")
        if gun not in (None, ""):
            widget.insert(0, str(int(gun)))

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

    def _tedarikci_kart_uygula(self, _event=None, valor_yaz: bool = True):
        secili = self.tedarikci_map.get(self.tedarikci.get())
        if valor_yaz:
            # Valör varsayılanı: carinin alış vade günü (siparişte elle değiştirilebilir)
            self._valor_yaz(getattr(secili, "alis_vade_gunu", None) if secili else None)
        for alan, deger in (
            ("tedarikci_kodu", secili.cari_kodu if secili else ""),
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
        """Sipariş genel toplamı (KDV dahil); satır tutarlarının toplamı."""
        return sum((self._satir_tutari(s) for s in self.satirlar), Decimal("0"))

    def _satir_tutari(self, s: dict) -> Decimal:
        """Satır tutarı (KDV dahil): ardışık 3 iskonto — iskonto_hesap_service.satir_iskonto_hesapla."""
        try:
            from database.iskonto_hesap_service import satir_iskonto_hesapla

            h = satir_iskonto_hesapla(
                miktar=s.get("miktar") or 0,
                brut_birim_fiyat=s.get("birim_alis_fiyati") or 0,
                iskonto1=s.get("iskonto_orani") or 0,
                iskonto2=s.get("iskonto_orani_2") or 0,
                iskonto3=s.get("iskonto_orani_3") or 0,
                kdv_orani=s.get("kdv_orani") or 0,
            )
            return h["iskonto_sonrasi_satir"] + h["kdv_tutari"]
        except (ImportError, ValueError):
            miktar = decimal(s.get("miktar") or 0, "Miktar", Decimal("0"))
            fiyat = decimal(s.get("birim_alis_fiyati") or 0, "Fiyat", Decimal("0"))
            isk = decimal(s.get("iskonto_orani") or 0, "İskonto", Decimal("0"))
            kdv_o = decimal(s.get("kdv_orani") or 0, "KDV", Decimal("0"))
            net = miktar * fiyat * (Decimal("1") - isk / Decimal("100"))
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
        brut = Decimal("0")
        iskonto = Decimal("0")
        ara = Decimal("0")
        kdv = Decimal("0")
        try:
            from database.iskonto_hesap_service import satir_iskonto_hesapla

            for s in self.satirlar:
                h = satir_iskonto_hesapla(
                    miktar=s.get("miktar") or 0,
                    brut_birim_fiyat=s.get("birim_alis_fiyati") or 0,
                    iskonto1=s.get("iskonto_orani") or 0,
                    iskonto2=s.get("iskonto_orani_2") or 0,
                    iskonto3=s.get("iskonto_orani_3") or 0,
                    kdv_orani=s.get("kdv_orani") or 0,
                )
                brut += h.get("brut_satir", Decimal("0"))
                iskonto += h.get("iskonto_tutari", Decimal("0"))
                ara += h.get("iskonto_sonrasi_satir", Decimal("0"))
                kdv += h.get("kdv_tutari", Decimal("0"))
        except (ImportError, ValueError, KeyError):
            pass
        if hasattr(self, "satir_ozet"):
            self.satir_ozet.configure(
                text=f"Sipariş tutarı: {para_goster(siparis_tutari)} | Ödeme: {para_goster(odeme)}"
            )
        for ad, metin in (
            ("_brut_lbl", f"Brüt: {para_goster(brut)}"),
            ("_iskonto_toplam_lbl", f"İskonto: {para_goster(iskonto)}"),
            ("_ara_lbl", f"Ara: {para_goster(ara)}"),
            ("_kdv_lbl", f"KDV: {para_goster(kdv)}"),
            ("_tutar_lbl", para_goster(siparis_tutari)),
            ("_baslik_tutar", f"Sipariş Tutarı: {para_goster(siparis_tutari)}"),
            ("_odeme_lbl", f"Ödeme / Avans: {para_goster(odeme)}"),
        ):
            widget = getattr(self, ad, None)
            if widget is not None:
                widget.configure(text=metin)
        tedarikci = self.tedarikci_map.get(self.tedarikci.get())
        if not tedarikci:
            self._readonly_yaz("yeni_bakiye", "—")
            return
        # Yeni bakiye = mevcut bakiye + bu sipariş tutarı (− ödeme/avans)
        yeni = self.mevcut_borc + siparis_tutari - odeme
        self._readonly_yaz("yeni_bakiye", para_goster(yeni))

    @staticmethod
    def _iskonto_gosterim(s: dict) -> str:
        """isk1/isk2/isk3 → «%10 + %5 + %2»; iskonto yoksa «0»."""
        try:
            from database.iskonto_hesap_service import iskonto_goster_metin

            return iskonto_goster_metin(
                s.get("iskonto_orani") or 0, s.get("iskonto_orani_2") or 0, s.get("iskonto_orani_3") or 0,
                bos_goster="0",
            )
        except (ImportError, ValueError):
            return str(s.get("iskonto_orani", 0))

    def _satir_listesini_yenile(self):
        for item in self.satir_tablosu.get_children():
            self.satir_tablosu.delete(item)
        for sira, s in enumerate(self.satirlar):
            self.satir_tablosu.insert("", "end", iid=str(sira), values=(
                s["urun_kodu"], s["urun_adi"], s["miktar"], s["birim"],
                para_goster(s["birim_alis_fiyati"]), self._iskonto_gosterim(s), s.get("kdv_orani", 20),
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
        self._tedarikci_kart_uygula(valor_yaz=False)
        # Valör: siparişte kayıtlı değer; yoksa carinin alış vade günü
        self._valor_yaz(s.valor_gun if s.valor_gun is not None else getattr(s.cari, "alis_vade_gunu", None))
        if hasattr(self, "teslim_depo"):
            self.teslim_depo.set(s.teslim_depo or "")
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
        valor_metin = self.girdiler["valor_gun"].get().strip()
        try:
            valor_gun = int(valor_metin) if valor_metin else None
            if valor_gun is not None and valor_gun < 0:
                raise ValueError
        except ValueError:
            messagebox.showwarning("Valör", "Valör gün sayısı 0 veya pozitif tam sayı olmalıdır.", parent=self)
            return
        try:
            veriler = {
                "valor_gun": valor_gun,
                "teslim_depo": self.teslim_depo.get().strip(),
                "durum": self.durum.get(),
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
            birim_hatasi_goster(self, hata) or messagebox.showerror("Kayıt", str(hata), parent=self)
            return
        self.result = True
        self.destroy()


class AlisIrsaliyesiDialog(_AlisSatirGirisi, tk.Toplevel):
    _fiyat_alani = "birim_fiyat"
    _liste_komutu = "alis_irsaliyeleri_goster"
    _belge_adi = "Alış irsaliyesi"

    def _kayitli_belge(self):
        return self.result or self.irsaliye

    def __init__(self, parent, irsaliye=None, siparis=None, cari=None):
        super().__init__(parent)
        self.irsaliye = irsaliye
        self.result = None
        self.title("SATIN ALMA İRSALİYESİ")
        self.geometry("1280x820")
        self.minsize(1000, 620)
        self.grab_set()
        from ui_pencere import pencere_os_krom_ac

        pencere_os_krom_ac(self)
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
        self.mevcut_borc = Decimal("0")
        self.sevk = {}

        _tema_hazirla(self)
        baslik = _tema_baslik(self, "SATIN ALMA İRSALİYESİ", irsaliye.irsaliye_no if irsaliye else "Yeni irsaliye")
        self._baslik_tutar = baslik["sag"]

        # Alt kısım önce pack edilir (pencere küçülünce de görünür kalsın)
        alt = tk.Frame(self, bg=T_ACIK_BG, padx=10, pady=8)
        alt.pack(side="bottom", fill="x")
        t_buton(alt, "Listeye Git", self.listeye_git, rol="ikincil").pack(side="left")
        t_buton(alt, "Kapat", self.destroy, rol="ikincil").pack(side="right")
        t_buton(alt, "Kaydet", self.kaydet, rol="vurgu").pack(side="right", padx=8)

        toplam_seridi = tk.Frame(self, bg=T_LACIVERT, padx=14, pady=6)
        toplam_seridi.pack(side="bottom", fill="x")
        tk.Label(
            toplam_seridi, text="İRSALİYE TUTARI", bg=T_LACIVERT, fg=T_BEYAZ, font=t_font(10, "bold", self),
        ).pack(side="left")
        self._tutar_lbl = tk.Label(
            toplam_seridi, text="0,00 TL", bg=T_LACIVERT, fg=T_SARI, font=t_font(16, "bold", self),
        )
        self._tutar_lbl.pack(side="left", padx=12)

        ust = tk.Frame(self, bg=T_ACIK_BG)
        ust.pack(fill="x", padx=10, pady=(8, 4))
        ust.columnconfigure(0, weight=48, uniform="alis_irs_ust")
        ust.columnconfigure(1, weight=52, uniform="alis_irs_ust")
        ust.rowconfigure(0, weight=1)

        # ── SOL: irsaliye / tedarikçi / depo / sipariş ──
        sol_dis, sol = _tema_panel(ust, "İrsaliye ve Tedarikçi")
        sol_dis.grid(row=0, column=0, sticky="nsew", padx=(0, 6))
        sol.columnconfigure(0, weight=1, uniform="alis_irs_sol")
        sol.columnconfigure(1, weight=1, uniform="alis_irs_sol")

        _tema_etiket(sol, "İç İrsaliye No").grid(row=0, column=0, sticky="w")
        _tema_etiket(sol, "Tarih").grid(row=0, column=1, sticky="w", padx=(6, 0))
        self.irsaliye_no_giris = ttk.Entry(sol)
        self.irsaliye_no_giris.insert(
            0, irsaliye.irsaliye_no if irsaliye else f"{AlisIrsaliyesiService.irsaliye_no()} (otomatik)",
        )
        self.irsaliye_no_giris.configure(state="readonly")
        self.irsaliye_no_giris.grid(row=1, column=0, sticky="ew", pady=(0, 4))
        self.tarih = ttk.Entry(sol)
        self.tarih.insert(0, date.today().strftime("%d.%m.%Y"))
        self.tarih.grid(row=1, column=1, sticky="ew", padx=(6, 0), pady=(0, 4))

        _tema_etiket(sol, "Tedarikçi (en az 2 harf yazın)").grid(row=2, column=0, columnspan=2, sticky="w")
        self.tedarikci_combo = ttk.Combobox(sol, textvariable=self.tedarikci, values=list(self.tedarikci_map))
        self.tedarikci_combo.grid(row=3, column=0, columnspan=2, sticky="ew", pady=(0, 4))
        self.tedarikci_combo.bind("<<ComboboxSelected>>", self._tedarikci_secildi)
        self.tedarikci_combo.bind("<KeyRelease>", self._tedarikci_arama_filtrele)

        _tema_etiket(sol, "Bakiye").grid(row=4, column=0, sticky="w")
        _tema_etiket(sol, "Giriş Deposu").grid(row=4, column=1, sticky="w", padx=(6, 0))
        self.bakiye_giris = ttk.Entry(sol, state="readonly")
        self.bakiye_giris.grid(row=5, column=0, sticky="ew", pady=(0, 4))
        self.giris_depo = ttk.Combobox(sol, values=_depo_secenekleri(), state="readonly")
        self.giris_depo.grid(row=5, column=1, sticky="ew", padx=(6, 0), pady=(0, 4))

        _tema_etiket(sol, "Bağlı Alış Siparişi").grid(row=6, column=0, columnspan=2, sticky="w")
        siparis_satiri = tk.Frame(sol, bg=T_BEYAZ)
        siparis_satiri.grid(row=7, column=0, columnspan=2, sticky="ew", pady=(0, 4))
        self.siparis_combo = ttk.Combobox(
            siparis_satiri, textvariable=self.siparis_secimi, values=list(self.siparis_map),
        )
        self.siparis_combo.pack(side="left", fill="x", expand=True)
        t_buton(siparis_satiri, "Siparişten Doldur", self.siparisten_doldur, rol="ara").pack(side="left", padx=(6, 0))

        _tema_etiket(sol, "Tedarikçi İrsaliye No").grid(row=8, column=0, sticky="w")
        _tema_etiket(sol, "Tedarikçi İrsaliye Tarihi").grid(row=8, column=1, sticky="w", padx=(6, 0))
        self.harici_no = ttk.Entry(sol)
        self.harici_no.grid(row=9, column=0, sticky="ew", pady=(0, 4))
        self.harici_tarih = ttk.Entry(sol)
        self.harici_tarih.grid(row=9, column=1, sticky="ew", padx=(6, 0), pady=(0, 4))

        _tema_etiket(sol, "Açıklama").grid(row=10, column=0, sticky="w")
        _tema_etiket(sol, "Şube").grid(row=10, column=1, sticky="w", padx=(6, 0))
        self.aciklama = ttk.Entry(sol)
        self.aciklama.grid(row=11, column=0, sticky="ew")
        from sube_ui import sube_secim_hazirla

        self.sube, self._sube_map = sube_secim_hazirla(
            sol, getattr(irsaliye, "sube_id", None) if irsaliye else getattr(siparis, "sube_id", None)
        )
        self.sube.grid(row=11, column=1, sticky="ew", padx=(6, 0))

        # ── SAĞ: Teslim Alma / Sevkiyat (12 alan) ──
        sag_dis, sag = _tema_panel(ust, "Teslim Alma / Sevkiyat")
        sag_dis.grid(row=0, column=1, sticky="nsew", padx=(6, 0))
        for kol in range(3):
            sag.columnconfigure(kol, weight=1, uniform="alis_irs_sag")

        def _sevk_alani(satir, kolon, etiket, alan, *, span=1, secenekler=None):
            _tema_etiket(sag, etiket).grid(
                row=satir, column=kolon, columnspan=span, sticky="w", padx=(0 if kolon == 0 else 6, 0),
            )
            if secenekler is not None:
                w = ttk.Combobox(sag, values=secenekler)
            else:
                w = ttk.Entry(sag)
            w.grid(
                row=satir + 1, column=kolon, columnspan=span, sticky="ew",
                padx=(0 if kolon == 0 else 6, 0), pady=(0, 4),
            )
            self.sevk[alan] = w
            return w

        _sevk_alani(0, 0, "Teslim Alma Adresi", "teslim_adresi", span=3)
        _sevk_alani(2, 0, "İl", "teslim_il")
        _sevk_alani(2, 1, "İlçe", "teslim_ilce")
        _sevk_alani(2, 2, "Planlanan Teslim Tarihi", "planlanan_teslim")
        _sevk_alani(4, 0, "Teslim Alacak Kişi", "teslim_kisi")
        _sevk_alani(4, 1, "Telefon", "teslim_telefon")
        _sevk_alani(4, 2, "Sevkiyat Yöntemi", "sevkiyat_yontemi", secenekler=SEVKIYAT_YONTEMLERI)
        _sevk_alani(6, 0, "Nakliyeci", "nakliyeci")
        _sevk_alani(6, 1, "Plaka", "arac_plaka")
        _sevk_alani(6, 2, "Şoför", "sofor_adi")
        _sevk_alani(8, 0, "Şoför Telefonu", "sofor_telefon")
        _sevk_alani(8, 1, "Takip No", "takip_no")
        tk.Label(
            sag, text="Sevkiyat bilgileri alış faturasında «Sevkiyat ve Teslimat Bilgileri» ile görüntülenir.",
            bg=T_BEYAZ, fg=T_IKINCIL, font=t_font(8, root=self), anchor="w", wraplength=420, justify="left",
        ).grid(row=10, column=0, columnspan=3, sticky="w", pady=(4, 0))
        self._baslik_kaplari = [sol, sag]

        orta = ttk.LabelFrame(self, text="Ürün Satırları", padding=8)
        orta.pack(fill="both", expand=True, padx=10, pady=(4, 0))
        self.satir_tablosu = ttk.Treeview(
            orta, columns=("kod", "ad", "miktar", "birim", "fiyat", "isk", "kdv", "tutar"),
            show="headings", height=8,
        )
        for kolon, baslik_metni, w in (
            ("kod", "Kod", 100), ("ad", "Ad", 240), ("miktar", "Miktar", 80),
            ("birim", "Birim", 70), ("fiyat", "Fiyat", 100), ("isk", "İsk%", 60),
            ("kdv", "KDV%", 60), ("tutar", "Tutar", 110),
        ):
            self.satir_tablosu.heading(kolon, text=baslik_metni)
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
                self._tedarikci_secildi()

    def _satir_tutari(self, s: dict) -> Decimal:
        """Satır tutarı (KDV dahil). İrsaliye satırında tek iskonto saklanır (iskonto_orani)."""
        try:
            from database.iskonto_hesap_service import satir_iskonto_hesapla

            h = satir_iskonto_hesapla(
                miktar=s.get("miktar") or 0,
                brut_birim_fiyat=s.get("birim_fiyat") or 0,
                iskonto1=s.get("iskonto_orani") or 0,
                kdv_orani=s.get("kdv_orani") or 0,
            )
            return h["iskonto_sonrasi_satir"] + h["kdv_tutari"]
        except (ImportError, ValueError):
            return Decimal("0")

    def _yenile(self):
        for item in self.satir_tablosu.get_children():
            self.satir_tablosu.delete(item)
        toplam = Decimal("0")
        for sira, s in enumerate(self.satirlar):
            tutar = self._satir_tutari(s)
            toplam += tutar
            self.satir_tablosu.insert("", "end", iid=str(sira), values=(
                s["urun_kodu"], s["urun_adi"], s["miktar"], s["birim"], para_goster(s["birim_fiyat"]),
                s.get("iskonto_orani", 0), s.get("kdv_orani", 20), para_goster(tutar),
            ))
        self._satir_ici_giris.tabloya_ekle()
        for ad, metin in (("_tutar_lbl", para_goster(toplam)), ("_baslik_tutar", f"İrsaliye Tutarı: {para_goster(toplam)}")):
            widget = getattr(self, ad, None)
            if widget is not None:
                widget.configure(text=metin)

    def _tedarikci_secildi(self, _event=None):
        tedarikci = self.tedarikci_map.get(self.tedarikci.get())
        metin = "—"
        if tedarikci is not None:
            try:
                metin = para_goster(AlisIrsaliyesiService.mevcut_bakiye(tedarikci.id))
            except Exception:  # noqa: BLE001
                _LOG.exception("Tedarikçi bakiyesi okunamadı")
        self.bakiye_giris.configure(state="normal")
        self.bakiye_giris.delete(0, "end")
        self.bakiye_giris.insert(0, metin)
        self.bakiye_giris.configure(state="readonly")

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

    def _sevk_oku(self) -> dict:
        """Teslim alma / sevkiyat alanlarını servis sözlüğüne çevirir (boş → None, tarihler date)."""
        veri = {}
        for alan, widget in self.sevk.items():
            metin = widget.get().strip()
            if alan == "planlanan_teslim":
                veri[alan] = _tarih_opsiyonel(metin, "Planlanan teslim tarihi")
            else:
                veri[alan] = metin or None
        return veri

    def _sevk_yaz(self, kaynak) -> None:
        for alan, widget in self.sevk.items():
            deger = getattr(kaynak, alan, None)
            widget.delete(0, "end")
            if deger is None:
                continue
            widget.insert(0, tarih_goster(deger) if hasattr(deger, "strftime") else str(deger))

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
            self._tedarikci_secildi()
        if getattr(siparis, "teslim_depo", None) and not self.giris_depo.get():
            self.giris_depo.set(siparis.teslim_depo)
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
        self._tedarikci_secildi()
        self.tarih.delete(0, "end")
        self.tarih.insert(0, tarih_goster(i.irsaliye_tarihi))
        self.aciklama.insert(0, i.aciklama or "")
        self.giris_depo.set(getattr(i, "giris_depo", None) or "")
        self.harici_no.delete(0, "end")
        self.harici_no.insert(0, getattr(i, "harici_irsaliye_no", None) or "")
        self.harici_tarih.delete(0, "end")
        if getattr(i, "harici_irsaliye_tarihi", None):
            self.harici_tarih.insert(0, tarih_goster(i.harici_irsaliye_tarihi))
        self._sevk_yaz(i)
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
            veriler = {
                "irsaliye_tarihi": datetime.strptime(self.tarih.get(), "%d.%m.%Y").date(),
                "cari_id": tedarikci.id,
                "sube_id": self._sube_map.get(self.sube.get()),
                "siparis_id": siparis_id,
                "aciklama": self.aciklama.get().strip() or None,
                "ayrintili_notlar": None,
                "giris_depo": self.giris_depo.get().strip() or None,
                "harici_irsaliye_no": self.harici_no.get().strip() or None,
                "harici_irsaliye_tarihi": _tarih_opsiyonel(self.harici_tarih.get(), "Tedarikçi irsaliye tarihi"),
                "row_version": int(getattr(self.irsaliye, "row_version", 1) or 1)
                if self.irsaliye
                else None,
            }
            veriler.update(self._sevk_oku())
            AlisIrsaliyesiService.kaydet(
                veriler,
                self.satirlar,
                self.irsaliye.id if self.irsaliye else None,
            )
        except ValueError as hata:
            birim_hatasi_goster(self, hata) or messagebox.showerror("Kayıt", str(hata), parent=self)
            return
        self.result = True
        self.destroy()


SEVKIYAT_ALAN_ETIKETLERI = (
    ("teslim_adresi", "Teslim Alma Adresi"),
    ("teslim_il", "İl"),
    ("teslim_ilce", "İlçe"),
    ("planlanan_teslim", "Planlanan Teslim Tarihi"),
    ("teslim_kisi", "Teslim Alacak Kişi"),
    ("teslim_telefon", "Telefon"),
    ("sevkiyat_yontemi", "Sevkiyat Yöntemi"),
    ("nakliyeci", "Nakliyeci"),
    ("arac_plaka", "Plaka"),
    ("sofor_adi", "Şoför"),
    ("sofor_telefon", "Şoför Telefonu"),
    ("takip_no", "Takip No"),
)


class SevkiyatBilgiDialog(tk.Toplevel):
    """Alış faturası için sevkiyat/teslimat bilgileri.

    Bağlı irsaliye varsa alanlar irsaliyeden gelir ve salt okunurdur; yoksa elle girilebilir.
    «Uygula» yalnızca sözlüğü (result) döndürür; stok/hareket üretmez.
    """

    def __init__(self, parent, irsaliye=None, mevcut: dict | None = None):
        super().__init__(parent)
        self.result: dict | None = None
        self._salt_okunur = irsaliye is not None
        self.title("Sevkiyat ve Teslimat Bilgileri")
        self.transient(parent)
        self.resizable(False, False)
        try:
            self.configure(bg=T_ACIK_BG)
        except tk.TclError:
            pass
        self.grab_set()

        kaynak = {}
        if irsaliye is not None:
            kaynak = {a: getattr(irsaliye, a, None) for a, _e in SEVKIYAT_ALAN_ETIKETLERI}
        elif mevcut:
            kaynak = dict(mevcut)

        baslik = "Bağlı irsaliyeden (salt okunur)" if irsaliye is not None else "Elle giriş (bağlı irsaliye yok)"
        tk.Label(
            self, text=baslik, bg=T_LACIVERT, fg=T_SARI, font=t_font(11, "bold", self), anchor="w", padx=12, pady=8,
        ).pack(fill="x")
        govde = tk.Frame(self, bg=T_BEYAZ, padx=14, pady=10)
        govde.pack(fill="both", expand=True)
        govde.columnconfigure(1, weight=1)
        self.alanlar = {}
        for sira, (alan, etiket) in enumerate(SEVKIYAT_ALAN_ETIKETLERI):
            _tema_etiket(govde, etiket).grid(row=sira, column=0, sticky="w", pady=3, padx=(0, 10))
            w = ttk.Entry(govde, width=46)
            deger = kaynak.get(alan)
            if deger is not None:
                w.insert(0, tarih_goster(deger) if hasattr(deger, "strftime") else str(deger))
            if self._salt_okunur:
                w.configure(state="readonly")
            w.grid(row=sira, column=1, sticky="ew", pady=3)
            self.alanlar[alan] = w
        alt = tk.Frame(self, bg=T_ACIK_BG, padx=12, pady=8)
        alt.pack(fill="x")
        t_buton(alt, "Vazgeç", self.destroy, rol="ikincil").pack(side="right")
        t_buton(alt, "Uygula", self._uygula, rol="vurgu").pack(side="right", padx=8)
        try:
            from ui_pencere import popup_ortala

            popup_ortala(self, parent, genislik=560, yukseklik=520)
        except Exception:  # noqa: BLE001
            pass

    def _uygula(self):
        veri = {}
        try:
            for alan, w in self.alanlar.items():
                metin = w.get().strip()
                veri[alan] = _tarih_opsiyonel(metin, "Planlanan teslim tarihi") if alan == "planlanan_teslim" else (metin or None)
        except ValueError as hata:
            messagebox.showwarning("Sevkiyat", str(hata), parent=self)
            return
        self.result = veri
        self.destroy()


class AlisFaturasiDialog(tk.Toplevel):
    """Satış faturası kartına denk, satın alma (alış) faturası kartı."""

    _print_belge_turu = ALIS_BELGE_BASLIGI
    _print_belge_no_etiketi = "Kayıt No"
    _print_ters_renk = True
    _hizli_stok_kaynak = "Alış Faturası – Hızlı Stok Oluşturma"

    def __init__(self, parent, fatura=None, siparis=None, irsaliye=None, cari=None, cari_ac=None):
        super().__init__(parent)
        self.fatura = fatura
        self.kaynak_siparis = siparis
        self.kaynak_irsaliye = irsaliye
        self.cari_ac = cari_ac
        self.result = None
        # «Sevkiyat ve Teslimat Bilgileri» taslağı (henüz faturaya kalıcı yazılmaz)
        self._sevkiyat_kopya: dict | None = None
        self._fatura_form_kirli = False
        self._fatura_yukleniyor = True
        self.title("Alış Fatura Kartı")
        from ui_pencere import belge_penceresini_hazirla, pencere_os_krom_ac

        # maximize=False: widget'lar zoomed pencerede kurulursa her pack pahalı layout tetikler
        belge_penceresini_hazirla(
            self,
            min_genislik=900,
            min_yukseklik=520,
            varsayilan_genislik=1200,
            varsayilan_yukseklik=720,
            maximize=False,
        )
        self.grab_set()
        # transient/grab sonrası Windows —/□ düğmeleri: kromu yeniden aç
        pencere_os_krom_ac(self)
        self.after_idle(lambda: pencere_os_krom_ac(self) if self.winfo_exists() else None)
        self.satirlar = []
        self.odemeler = []
        self.mevcut_borc = Decimal("0")

        # İlk boyamada tüm tedarikçi listesini bekletme — açık belge/cari hemen, kalanı idle
        self.tedarikci_map: dict = {}
        for belge in (fatura, siparis, irsaliye):
            if belge and getattr(belge, "cari", None) is not None:
                _tedarikci_ekle(self.tedarikci_map, belge.cari)
        if cari is not None:
            _tedarikci_ekle(self.tedarikci_map, cari)
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
        self.bind("<Escape>", self._alis_escape)
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
        from evrak_baslik_gezinme import baslik_gezinme_kur

        baslik_gezinme_kur(
            self, [self._fatura_ust_panel, self._doviz_cerceve], son_hedef=self._satir_ici_giris.odakla
        )
        # Ödemeler / Notlar sticky alt banda taşınır (_alis_sticky_footer_kur)
        self._alis_scroll_alt = None

        if fatura:
            self._faturayi_doldur()
        elif irsaliye:
            self._irsaliyeyi_doldur(irsaliye)
        elif siparis:
            self._siparis_yukle(siparis)
        elif cari:
            self._tedarikci_sec(cari)
            if self.tedarikci.get():
                self._bakiye_guncelle()
        self.vade_tarih_degisti()
        self._toplamlari_guncelle()
        self._alis_sticky_footer_kur()
        self._doviz_gorunumu_guncelle()
        self._toolbar_guncelle()
        ftema.renkleri_tersle(self, haric=[self._alis_toolbar["rozet"]])
        self._fatura_yukleniyor = False
        self._fatura_form_kirli = False
        # İlk kullanılabilir çerçeveden sonra doldur (update/idle ölçümünü şişirmesin)
        self.after(80, self._tedarikci_haritasini_doldur)
        # Büyütmeyi kurulumdan sonraya bırak — açılış layout maliyetini düşürür
        try:
            self.after_idle(lambda: self.state("zoomed") if self.winfo_exists() else None)
        except tk.TclError:
            pass

    def _alis_kayit_no_ata(self) -> None:
        """Yeni belgede kayıt no'yu ilk boyamadan sonra üretir."""
        if not self.winfo_exists() or self.fatura is not None:
            return
        e = self.girdiler.get("fatura_no")
        if e is None:
            return
        try:
            no = AlisFaturasiService.fatura_no()
            e.configure(state="normal")
            e.delete(0, "end")
            e.insert(0, no)
            e.configure(state="readonly")
            tb = getattr(self, "_alis_toolbar", None)
            if tb and tb.get("fatura_no"):
                tb["fatura_no"].configure(text=no)
        except Exception:
            _LOG.exception("Alış fatura no atanamadı")

    def _tedarikci_haritasini_doldur(self) -> None:
        """Aktif tedarikçileri ilk boyamadan sonra haritaya ekler (açılış hızı)."""
        if not self.winfo_exists():
            return
        try:
            for c in AlisFaturasiService.aktif_tedarikcileri():
                _tedarikci_ekle(self.tedarikci_map, c)
        except Exception:
            _LOG.exception("Tedarikçi haritası doldurulamadı")

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
        """Üst butonlar + orta kaydırma + açık zeminli Notlar/Ödemeler + Net Toplam."""
        from ui_pencere import sticky_footer_layout, calisma_alani

        footer = getattr(self, "_alis_toplam_cerceve", None)
        if footer is None:
            return
        try:
            footer.grid_forget()
        except tk.TclError:
            try:
                footer.pack_forget()
            except tk.TclError:
                pass
        alt = tk.Frame(self, bg=ftema.ACIK_BG)
        footer.pack(in_=alt, fill="x", padx=6, pady=(2, 4))
        sticky_footer_layout(
            self,
            ust=getattr(self, "_alis_ust_butonlar", None),
            orta=getattr(self, "_kaydirma_alani", None),
            alt=alt,
        )
        try:
            _, _, _, ah = calisma_alani(self)
            if hasattr(self, "satir_tablosu"):
                self.satir_tablosu.configure(height=12 if ah < 800 else 16)
            if hasattr(self, "odeme_tablosu"):
                self.odeme_tablosu.configure(height=3 if ah < 800 else 4)
            if hasattr(self, "ayrintili_notlar"):
                self.ayrintili_notlar.configure(height=3 if ah < 800 else 4)
        except Exception:
            pass
        try:
            from ui_pencere import pencere_os_krom_ac

            pencere_os_krom_ac(self)
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
        if self._alis_kilitli():
            return False
        if getattr(self, "_fatura_form_kirli", False):
            return True
        if self.fatura is None:
            return bool(self.satirlar) or bool((self.tedarikci.get() or "").strip())
        return False

    def _kaydet_kapatmadan(self) -> bool:
        """Liste geçişi için kaydet; destroy yok."""
        if self._kilit_uyar():
            return False
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
            # Mal girişi tamam — lot barkod + etiket penceresi (hata girişi geri almaz)
            try:
                from database.lot_barkod_service import LotBarkodService
                from lot_etiket_ui import lot_etiket_sonrasi_ac

                is_ozeti = LotBarkodService.alis_faturasi_sonrasi(self.fatura)
                if is_ozeti:
                    self.after(80, lambda o=is_ozeti: lot_etiket_sonrasi_ac(self, o))
            except Exception:
                pass
            return True
        except MukerrerTedarikciFaturaHatasi as hata:
            self._mukerrer_kaydi_goster(
                hata.fatura_id, hata.fatura_no, self.girdiler["tedarikci_fatura_no"].get().strip()
            )
            return False
        except ValueError as hata:
            birim_hatasi_goster(self, hata) or messagebox.showerror("Fatura kaydedilemedi", str(hata), parent=self)
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

    def _alis_escape(self, _event=None):
        """Önce açık takvimi kapat; fatura Esc ile kapanmasın."""
        try:
            from ui_takvim import _acik_takvim

            if _acik_takvim is not None and _acik_takvim.winfo_exists():
                _acik_takvim.destroy()
                return "break"
        except (tk.TclError, ImportError):
            pass
        self.kapat_istegi()
        return "break"

    def _girdi(self, parent, satir, baslik, alan, deger="", sutun=0, genislik=35, readonly=False):
        py = getattr(self, "_alis_form_pady", ALIS_UST_PADY)
        ttk.Label(parent, text=baslik, style="AlisUst.TLabel").grid(
            row=satir, column=sutun, padx=(0, 6), pady=py, sticky="w"
        )
        widget = ttk.Entry(parent, width=genislik, style="FaturaUst.TEntry")
        widget.grid(row=satir, column=sutun + 1, padx=(0, 8), pady=py, sticky="ew")
        widget.insert(0, deger)
        if readonly:
            widget.configure(state="readonly")
        self.girdiler[alan] = widget
        return widget

    def _alis_stilleri_kur(self):
        stil = ttk.Style(self)
        stil.configure("AlisUst.TLabel", font=ftema.font(9, root=self), foreground="#334155")
        stil.configure("AlisUst.TLabelframe", padding=(6, 2))
        stil.configure(
            "AlisUst.TLabelframe.Label", font=ftema.font(9, "bold", self), foreground=ftema.LACIVERT
        )
        try:
            stil.configure(
                "FaturaUst.TLabel",
                font=ftema.font(9, root=self),
                foreground=ftema.IKINCIL,
            )
            stil.configure("FaturaUst.TLabelframe", padding=(6, 2))
        except tk.TclError:
            pass
        kaynak = "FaturaSatir.Treeview"
        ayar = {}
        for secenek in ("rowheight", "font", "borderwidth", "relief", "fieldbackground", "background", "foreground"):
            deger = stil.lookup(kaynak, secenek)
            if deger not in ("", None):
                ayar[secenek] = deger
        # Metrik satır yüksekliği — FaturaSatir ile aynı (ızgara/yazı çakışmasın)
        ayar["rowheight"] = ftema.tablo_satir_rowheight(self)
        ayar["borderwidth"] = 0
        ayar["relief"] = "flat"
        stil.configure(ALIS_TABLO_STILI, **ayar)
        stil.configure(
            f"{ALIS_TABLO_STILI}.Heading",
            font=ftema.font(9, "bold", self),
            background=ftema.SARI,
            foreground=ftema.LACIVERT,
            relief="flat",
            borderwidth=0,
            padding=(4, ftema.scale_height(ftema.TABLO_BASLIK_PAD_TABAN)),
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
        self._fatura_toolbar = refs  # arac_cubugu_sigdir_kur
        self._alis_ust_butonlar = refs["cubuk"]
        sag = refs["sag"]
        bp = refs.get("sag_dis") or sag
        ftema.fatura_buton_olcu_sifirla()
        ftema.fatura_buton_olculeri(self, grup="dis")
        ftema.fatura_buton_olculeri(self, grup="panel")

        def _pack(btn):
            btn.pack(side="left", padx=2, in_=sag)

        liste_btn = ftema.oval_buton(
            bp, "Fatura Listesi (F3)", self._fatura_listesini_ac, rol="yardimci", grup="dis"
        )
        _pack(liste_btn)
        self._tooltip_bagla(liste_btn, "Alış Fatura Listesini Aç")
        self.kaydet_btn = ftema.oval_buton(bp, "Kaydet (F1)", self.kaydet, rol="kaydet", grup="dis")
        _pack(self.kaydet_btn)
        self.onayla_btn = ftema.oval_buton(bp, "Onayla", self.onayla, rol="onayla", grup="dis")
        _pack(self.onayla_btn)
        self._tooltip_bagla(
            self.onayla_btn,
            "Faturayı doğrular, kaydedilmemiş değişiklikleri kaydeder ve onaylar.\n"
            "Onaylı faturada içerik değiştirilemez.",
        )
        self.onay_kaldir_btn = ftema.oval_buton(
            bp, "Onayı Kaldır", self.onay_kaldir, rol="yardimci", grup="dis"
        )
        # Onayı Kaldır yalnız onaylı belgede pack edilir (_toolbar_guncelle)
        onizleme_btn = ftema.oval_buton(bp, "Önizleme", self._alis_onizleme_ac, rol="yardimci", grup="dis")
        _pack(onizleme_btn)
        pdf_btn = ftema.oval_buton(bp, "PDF", self._alis_pdf_kaydet, rol="yardimci", grup="dis")
        _pack(pdf_btn)
        masraf_btn = ftema.oval_buton(bp, "Masraflar", self._masraf_dagitimlari, rol="yardimci", grup="dis")
        _pack(masraf_btn)
        self._tooltip_bagla(masraf_btn, "Bağlı Masraflar — bu faturaya bağlı masraf dağıtımları")
        iade_btn = ftema.oval_buton(bp, "İadeler", self._bagli_iadeler, rol="yardimci", grup="dis")
        _pack(iade_btn)
        self._tooltip_bagla(iade_btn, "Bağlı İadeler — bu faturaya bağlı alış iade faturaları")
        sevk_btn = ftema.oval_buton(
            bp, "Sevkiyat", self._sevkiyat_bilgileri_ac, rol="yardimci", grup="dis"
        )
        _pack(sevk_btn)
        self._tooltip_bagla(sevk_btn, "Sevkiyat ve Teslimat Bilgileri")
        aktar_btn = ftema.oval_buton(
            bp, "Dosyadan Aktar", self._fatura_dosyadan_aktar, rol="yardimci", grup="dis"
        )
        _pack(aktar_btn)
        self.iptal_btn = ftema.oval_buton(bp, "İptal Et", self.faturayi_iptal_et, rol="sil", grup="dis")
        _pack(self.iptal_btn)
        listeye_btn = ftema.oval_buton(bp, "Listeye Git", self.fatura_listeye_git, rol="yardimci", grup="dis")
        _pack(listeye_btn)
        kapat_btn = ftema.oval_buton(bp, "Kapat (Esc)", self.kapat_istegi, rol="yardimci", grup="dis")
        kapat_btn.pack(side="right", padx=(6, 0))
        try:
            from fatura_yerlesim import arac_cubugu_sigdir_kur

            arac_cubugu_sigdir_kur(self)
        except Exception:
            pass

    def _sevkiyat_kaynak_irsaliye(self):
        """Faturanın bağlı olduğu irsaliye (yeni faturada kaynak, kayıtlıda irsaliye_id)."""
        irsaliye = self.kaynak_irsaliye
        if irsaliye is None and self.fatura is not None and getattr(self.fatura, "irsaliye_id", None):
            try:
                irsaliye = AlisIrsaliyesiService.getir(int(self.fatura.irsaliye_id))
            except Exception:  # noqa: BLE001
                _LOG.exception("Bağlı irsaliye okunamadı")
                irsaliye = None
        return irsaliye

    def _sevkiyat_bilgileri_ac(self):
        irsaliye = self._sevkiyat_kaynak_irsaliye()
        dlg = SevkiyatBilgiDialog(self, irsaliye=irsaliye, mevcut=self._sevkiyat_kopya)
        self.wait_window(dlg)
        if dlg.result is not None:
            self._sevkiyat_kopya = dlg.result
            self._fatura_form_kirli = True

    def _fatura_dosyadan_aktar(self):
        from fatura_dosyadan_aktar_ui import fatura_dosyadan_aktar_calistir

        try:
            kart_dolu = bool(self.satir_tablosu.get_children())
        except Exception:
            kart_dolu = bool(getattr(self, "fatura", None))
        fatura_dosyadan_aktar_calistir(self, yon="ALIS", kart_dolu=kart_dolu)

    def _pencere_basligi(self) -> str:
        no = getattr(self.fatura, "fatura_no", "") if self.fatura else ""
        return (f"{ALIS_BELGE_BASLIGI} — {no}" if no else f"{ALIS_BELGE_BASLIGI} — Yeni") + self._muhasebe_eki()

    def _muhasebe_eki(self) -> str:
        f = self.fatura
        anahtar = (getattr(f, "id", None), getattr(f, "durum", None), getattr(f, "row_version", None))
        if getattr(self, "_muhasebe_eki_anahtari", None) != anahtar:
            from database.muhasebelestirme_service import MuhasebelestirmeService

            self._muhasebe_eki_anahtari = anahtar
            self._muhasebe_eki_metni = MuhasebelestirmeService.baslik_eki("alis_faturasi", anahtar[0])
        return self._muhasebe_eki_metni or ""

    def _toolbar_guncelle(self):
        refs = getattr(self, "_alis_toolbar", None)
        self.title(self._pencere_basligi())
        if not refs:
            return
        try:
            refs["fatura_no"].configure(text=getattr(self.fatura, "fatura_no", "") or "Yeni")
            tedarikci = self.tedarikci_map.get(self.tedarikci.get()) if hasattr(self, "tedarikci") else None
            refs["musteri"].configure(text=(f"Tedarikçi: {tedarikci.unvan}" if tedarikci else "")[:60])
            if self.fatura is not None and getattr(self.fatura, "id", None):
                rozet = alis_evrak_durumu(self.fatura.durum, getattr(self.fatura, "onaylandi", False))
            else:
                rozet = "YENİ"
            ftema.rozet_guncelle(refs["rozet"], rozet)
        except tk.TclError:
            return
        iptal = bool(self.fatura and self.fatura.durum == "İPTAL")
        onayli = self._alis_onayli()
        for dugme, kapali in (
            (getattr(self, "kaydet_btn", None), iptal or onayli),
            (getattr(self, "iptal_btn", None), iptal),
            (getattr(self, "onayla_btn", None), iptal or onayli),
        ):
            if dugme is not None:
                dugme.configure(state="disabled" if kapali else "normal")
        kaldir = getattr(self, "onay_kaldir_btn", None)
        if kaldir is not None:
            try:
                if onayli and not iptal:
                    if not kaldir.winfo_manager():
                        hedef = getattr(self, "_alis_toolbar", {}).get("sag") or self.onayla_btn.master
                        kaldir.pack(side="left", padx=2, in_=hedef, after=self.onayla_btn)
                elif kaldir.winfo_manager():
                    kaldir.pack_forget()
            except tk.TclError:
                pass
        self._kilit_uygula()

    def _form_degisti(self, _event=None):
        if not getattr(self, "_fatura_yukleniyor", False):
            self._fatura_form_kirli = True

    def _form_tus_degisti(self, event):
        if self._alis_kilitli():
            return
        if event.char and event.char.isprintable() or event.keysym in ("BackSpace", "Delete"):
            self._form_degisti()

    # ─── onay ve kilit
    def _alis_onayli(self) -> bool:
        return bool(self.fatura is not None and getattr(self.fatura, "onaylandi", False))

    def _alis_kilitli(self) -> bool:
        """Onaylı veya iptal faturada içerik değiştirilemez."""
        f = getattr(self, "fatura", None)
        return bool(f is not None and (getattr(f, "onaylandi", False) or (f.durum or "") == "İPTAL"))

    def _kilit_uyar(self) -> bool:
        """Kilitliyse kullanıcıyı uyarır ve True döner."""
        if not self._alis_kilitli():
            return False
        if self._alis_onayli():
            metin = "Onaylı faturada değişiklik yapılamaz.\nDeğişiklik için önce «Onayı Kaldır» kullanın."
        else:
            metin = "İptal edilmiş fatura değiştirilemez."
        messagebox.showinfo("Fatura kilitli", metin, parent=self)
        return True

    # Kilitte açık kalan (yalnızca bakma / gezinme) düğmeler
    _KILITTE_ACIK = frozenset({
        "Cari Kartına Geç", "Cari Kart", "Alış Evrakları", "Döviz / Kur", "Kolon Ayarları",
    })

    def _alis_ust_yukseklik_esitle(self):
        """Dört üst paneli ortak (en küçük gerekli) yüksekliğe getirir."""
        paneller = [
            p
            for p in (
                getattr(self, "_alis_ust_tedarikci", None),
                getattr(self, "_alis_ust_fatura", None),
                getattr(self, "_alis_ust_depo", None),
                getattr(self, "_alis_ust_borc", None),
            )
            if p is not None
        ]
        if not paneller:
            return
        try:
            self.update_idletasks()
            hedef = max(int(p.winfo_reqheight()) for p in paneller)
            # Borç paneli referans (içerik tam); diğerleri buna uzar/kısar
            borc = getattr(self, "_alis_ust_borc", None)
            if borc is not None:
                borc.update_idletasks()
                hedef = max(hedef, int(borc.winfo_reqheight()))
            for panel in paneller:
                panel.update_idletasks()
                gen = max(120, int(panel.winfo_width()) or int(panel.winfo_reqwidth()))
                try:
                    panel.grid_propagate(False)
                    panel.configure(width=gen, height=hedef)
                except tk.TclError:
                    pass
            self._alis_ust_yukseklik_px = hedef
            # H: Kayıt No gerçek yüksekliği
            kn = self.girdiler.get("fatura_no")
            if kn is not None:
                try:
                    self._alis_h_ref = int(kn.winfo_height()) or self._alis_h_ref
                except tk.TclError:
                    pass
        except tk.TclError:
            pass

    def _kilit_hedefleri(self):
        kokler = [w for w in (getattr(self, "icerik", None),) if w is not None]
        yigin = list(kokler)
        while yigin:
            w = yigin.pop()
            try:
                yigin.extend(w.winfo_children())
            except tk.TclError:
                continue
            if isinstance(w, (ttk.Treeview, ttk.Scrollbar, ttk.Label, tk.Label)):
                continue
            if isinstance(w, (ttk.Button, tk.Button)):
                try:
                    if str(w.cget("text")) in self._KILITTE_ACIK:
                        continue
                except tk.TclError:
                    continue
            if isinstance(w, (ttk.Entry, ttk.Combobox, ttk.Button, tk.Button, tk.Text, ttk.Checkbutton, ttk.Radiobutton)):
                yield w

    def _kilit_uygula(self, zorla: bool | None = None) -> None:
        """Onay/iptal durumuna göre form alanlarını kilitler veya eski durumuna döndürür."""
        if not hasattr(self, "icerik") or not hasattr(self, "satir_tablosu"):
            return
        kilitli = self._alis_kilitli() if zorla is None else zorla
        eski = getattr(self, "_kilit_eski_durum", None)
        if kilitli and eski is None:
            eski = {}
            for w in self._kilit_hedefleri():
                if getattr(self, "_satir_ici_giris", None) is not None and w is self._satir_ici_giris.entry:
                    continue
                try:
                    eski[w] = str(w.cget("state"))
                    w.configure(state="disabled")
                except tk.TclError:
                    continue
            self._kilit_eski_durum = eski
        elif not kilitli and eski is not None:
            for w, durum in eski.items():
                try:
                    if w.winfo_exists():
                        w.configure(state=durum)
                except tk.TclError:
                    pass
            self._kilit_eski_durum = None
        alt = getattr(self, "_alt_kaydet_btn", None)
        if alt is not None:
            try:
                alt.configure(state="disabled" if kilitli else "normal")
            except tk.TclError:
                pass
        try:
            if kilitli and getattr(self, "_hucre", None) is not None:
                self._hucre.kapat()
            if getattr(self, "_satir_ici_giris", None) is not None:
                self._satir_ici_giris.tabloya_ekle()
        except Exception:
            pass
        etiket = getattr(self, "_onay_bilgi_lbl", None)
        if etiket is not None:
            try:
                if self._alis_onayli():
                    zaman = getattr(self.fatura, "onay_tarihi", None)
                    ek = f" · {zaman:%d.%m.%Y %H:%M}" if zaman else ""
                    etiket.configure(text=f"ONAYLI{ek} — içerik kilitli", foreground=ftema.BASARI)
                elif self.fatura is not None and getattr(self.fatura, "id", None) and not kilitli:
                    etiket.configure(text="Onaysız — kaydedildi, onay bekliyor", foreground="#B45309")
                elif kilitli:
                    etiket.configure(text="İPTAL — içerik kilitli", foreground=ftema.IKINCIL)
                else:
                    etiket.configure(text="Yeni — kaydedilmedi", foreground=ftema.IKINCIL)
            except tk.TclError:
                pass

    def onay_dogrula(self) -> list[str]:
        """Ekrandaki (kaydedilmemiş olabilir) bilgilerle onay kontrolü."""
        try:
            fatura_tarihi = datetime.strptime(self.girdiler["fatura_tarihi"].get(), "%d.%m.%Y").date()
        except ValueError:
            fatura_tarihi = None
        try:
            vade_tarihi = datetime.strptime(self.girdiler["vade_tarihi"].get(), "%d.%m.%Y").date()
        except ValueError:
            vade_tarihi = None
        pb, kur = "TRY", 1
        if hasattr(self, "_doviz_para_birimi"):
            pb = (self._doviz_para_birimi.get() or "TRY").upper()
            try:
                kur = self._doviz_kur.get()
            except (AttributeError, tk.TclError):
                kur = 0
        satirlar = [
            {**s, "birim_fiyat": s.get("birim_fiyat", s.get("birim_alis_fiyati", 0))}
            for s in self.satirlar
        ]
        return onay_hatalari(
            cari=self.tedarikci_map.get(self.tedarikci.get()),
            satirlar=satirlar,
            fatura_tarihi=fatura_tarihi,
            vade_tarihi=vade_tarihi,
            depo=self.depo.get(),
            para_birimi=pb,
            kur=kur,
        )

    def onayla(self, _event=None):
        """Doğrula → gerekirse kaydet → onayla. Kayıt başarısızsa onay yapılmaz."""
        if getattr(self, "_onay_isleniyor", False):
            return False
        if self._alis_onayli():
            messagebox.showinfo("Onay", "Bu fatura zaten onaylı.", parent=self)
            return False
        if self.fatura is not None and (self.fatura.durum or "") == "İPTAL":
            messagebox.showwarning("Onay", "İptal edilmiş fatura onaylanamaz.", parent=self)
            return False
        self._onay_isleniyor = True
        btn = getattr(self, "onayla_btn", None)
        if btn is not None:
            btn.configure(state="disabled")
        try:
            try:
                self._alis_editorleri_uygula()
            except ValueError as hata:
                messagebox.showwarning("Fatura onaylanamadı", str(hata), parent=self)
                return False
            hatalar = self.onay_dogrula()
            if hatalar:
                messagebox.showwarning(
                    "Fatura onaylanamadı",
                    "Onay için şu alanları düzeltin:\n\n• " + "\n• ".join(hatalar),
                    parent=self,
                )
                return False
            if self.fatura is None or not getattr(self.fatura, "id", None) or self._fatura_kirli_mi():
                if not self._kaydet_kapatmadan():
                    return False
            try:
                self.fatura = AlisFaturasiService.onayla(
                    self.fatura.id, row_version=getattr(self.fatura, "row_version", None)
                )
            except Exception as hata:  # AccessError dahil
                messagebox.showerror("Fatura onaylanamadı", str(hata), parent=self)
                return False
            self._faturayi_doldur()
            self.result = self.fatura
            return True
        finally:
            self._onay_isleniyor = False
            self._toolbar_guncelle()

    def onay_kaldir(self, _event=None):
        if not self._alis_onayli():
            return False
        if not messagebox.askyesno(
            "Onayı Kaldır",
            "Faturanın onayı kaldırılsın mı?\n\nOnay kaldırılınca fatura yeniden düzenlenebilir; "
            "stok ve cari hareketleri bir sonraki kayıtta güncellenir.",
            parent=self,
        ):
            return False
        try:
            self.fatura = AlisFaturasiService.onay_kaldir(self.fatura.id)
        except Exception as hata:
            messagebox.showerror("Onay kaldırılamadı", str(hata), parent=self)
            return False
        self._faturayi_doldur()
        return True

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

    def fatura_listeye_git(self):
        """Alış Faturaları listesine geçer ve bu faturayı listede seçer."""
        from satin_alma_ui import belgeden_listeye_git

        app = self._root()
        liste_fn = getattr(app, "alis_faturalari_goster", None)
        self.kapat_istegi()
        try:
            if self.winfo_exists():
                return
        except tk.TclError:
            pass
        if callable(liste_fn):
            belge = getattr(self, "result", None) or getattr(self, "fatura", None)
            belgeden_listeye_git(app, liste_fn, getattr(belge, "id", None))

    def _ust_paneller_olustur(self):
        """Üst dört panel: Tedarikçi | Fatura | Depo | Borç — eşit genişlik/yükseklik, 1,5 mm aralık."""
        py = ftema.form_pady()
        self._alis_form_pady = py
        self._alis_satir_h = ftema.form_satir_dis_yukseklik()
        self._alis_satir_yuvasi = self._alis_satir_h + 2 * py
        gap = 6

        ust = tk.Frame(self.icerik, bg=ftema.ACIK_BG)
        ust.pack(fill="x", pady=(0, 4))
        self._fatura_ust_panel = ust
        for _c in range(4):
            ust.columnconfigure(_c, weight=1, minsize=160, uniform="alis_ust")
        ust.rowconfigure(0, weight=0)

        def _satir_yuva(panel, n):
            for _r in range(n):
                panel.rowconfigure(_r, weight=0, minsize=self._alis_satir_yuvasi)

        # ========== 1 — Tedarikçi ve Cari (sol) ==========
        p_ted = ttk.LabelFrame(ust, text="Tedarikçi ve Cari", style="AlisUst.TLabelframe")
        p_ted.grid(row=0, column=0, sticky="nsew", padx=(0, gap))
        self._alis_ust_tedarikci = p_ted
        p_ted.columnconfigure(1, weight=1)
        _satir_yuva(p_ted, 6)

        ttk.Label(p_ted, text="Tedarikçi", style="AlisUst.TLabel").grid(
            row=0, column=0, padx=(0, 6), pady=py, sticky="w"
        )
        self.tedarikci = tk.StringVar()
        self._tedarikci_metin = tk.StringVar()
        self.tedarikci_ad = ttk.Entry(
            p_ted, textvariable=self._tedarikci_metin, width=22, style="FaturaUst.TEntry"
        )
        self.tedarikci_ad.grid(row=0, column=1, padx=0, pady=py, sticky="ew")
        self.tedarikci_combo = self.tedarikci_ad
        self.tedarikci_ara_btn = ttk.Button(
            p_ted, text="Ara", width=4, command=self._tedarikci_listeden_sec, style="FaturaUst.TButton"
        )
        self.tedarikci_ara_btn.grid(row=0, column=2, padx=(4, 0), pady=py)
        self.yeni_tedarikci_btn = ttk.Button(
            p_ted, text="Yeni Tedarikçi", command=self.yeni_tedarikci_ekle, style="FaturaUst.TButton"
        )
        self.yeni_tedarikci_btn.grid(row=0, column=3, padx=(4, 0), pady=py)
        self._tooltip_bagla(
            self.tedarikci_ad,
            "Adın bir bölümünü yazın — sonuçlar altta listelenir (↑↓, Enter, Esc).\n"
            "F10 veya sağ tık: tam tedarikçi listesi",
        )
        for olay in ("<F10>", "<Button-3>"):
            self.tedarikci_ad.bind(olay, self._tedarikci_listeden_sec)
        from cari_arama_alani import CariAramaAlani

        self._tedarikci_arama = CariAramaAlani(
            self,
            self.tedarikci_ad,
            cari_turu="Tedarikçi",
            on_secim=self._tedarikci_aramadan_sec,
            on_temizle=self._tedarikci_secimi_temizle,
            secili_ad=self._secili_tedarikci_adi,
            on_yeni=self.yeni_tedarikci_ekle,
            kayit_adi="Tedarikçi",
        )
        ttk.Label(p_ted, text="Tedarikçi Kodu", style="AlisUst.TLabel").grid(
            row=1, column=0, padx=(0, 6), pady=py, sticky="w"
        )
        self._tedarikci_kod = ttk.Entry(p_ted, width=18, style="FaturaUst.TEntry")
        self._tedarikci_kod.insert(0, "— seçilmedi")
        self._tedarikci_kod.configure(state="readonly")
        self._tedarikci_kod.grid(row=1, column=1, columnspan=3, padx=0, pady=py, sticky="ew")
        self._tedarikci_kod_lbl = self._tedarikci_kod  # geriye uyumluluk
        self.tedarikci.trace_add("write", lambda *_a: self._tedarikci_gorunumu_esitle())
        ttk.Label(p_ted, text="Sipariş No", style="AlisUst.TLabel").grid(
            row=2, column=0, padx=(0, 6), pady=py, sticky="w"
        )
        self.siparis_no = ttk.Entry(p_ted, width=18, style="FaturaUst.TEntry")
        self.siparis_no.grid(row=2, column=1, columnspan=3, padx=0, pady=py, sticky="ew")
        ttk.Label(p_ted, text="İrsaliye No", style="AlisUst.TLabel").grid(
            row=3, column=0, padx=(0, 6), pady=py, sticky="w"
        )
        self.irsaliye_no = ttk.Entry(p_ted, width=18, style="FaturaUst.TEntry")
        self.irsaliye_no.grid(row=3, column=1, columnspan=3, padx=0, pady=py, sticky="ew")
        ttk.Label(p_ted, text="Şube", style="AlisUst.TLabel").grid(
            row=4, column=0, padx=(0, 6), pady=py, sticky="w"
        )
        from sube_ui import sube_secim_hazirla

        kaynak_sube_id = (
            getattr(self.fatura, "sube_id", None)
            or getattr(self.kaynak_irsaliye, "sube_id", None)
            or getattr(self.kaynak_siparis, "sube_id", None)
        )
        self.sube, self._sube_map = sube_secim_hazirla(p_ted, kaynak_sube_id)
        self.sube.configure(style="FaturaUst.TCombobox")
        self.sube.grid(row=4, column=1, columnspan=3, padx=0, pady=py, sticky="ew")
        dugmeler = tk.Frame(p_ted, bg=ftema.ACIK_BG)
        dugmeler.grid(row=5, column=0, columnspan=4, sticky="w", pady=py)
        ftema.oval_buton(
            dugmeler, "Cari Kart", self.cariye_git, rol="kaydet", grup="panel"
        ).pack(side="left")
        ftema.oval_buton(
            dugmeler, "Alış Evrakları", self._tedarikci_evraklari, rol="yardimci", grup="panel"
        ).pack(side="left", padx=(6, 0))
        self.girdiler["siparis_no"] = self.siparis_no
        self.girdiler["irsaliye_no"] = self.irsaliye_no
        if self.kaynak_siparis:
            self.siparis_no.insert(0, self.kaynak_siparis.siparis_no)
        if self.kaynak_irsaliye:
            self.irsaliye_no.insert(0, self.kaynak_irsaliye.irsaliye_no)
            if self.kaynak_irsaliye.siparis:
                self.siparis_no.delete(0, "end")
                self.siparis_no.insert(0, self.kaynak_irsaliye.siparis.siparis_no)

        # ========== 2 — Fatura Bilgileri ==========
        p_fat = ttk.LabelFrame(ust, text="Fatura Bilgileri", style="AlisUst.TLabelframe")
        p_fat.grid(row=0, column=1, sticky="nsew", padx=(0, gap))
        self._alis_ust_fatura = p_fat
        p_fat.columnconfigure(1, weight=1)
        p_fat.columnconfigure(3, weight=1)
        _satir_yuva(p_fat, 5)

        # Yeni belgede numara idle'da alınır — açılışta DB max sorgusu UI kurulumunu bloklamasın
        fatura_no = self.fatura.fatura_no if self.fatura else "…"
        self._girdi(p_fat, 0, "Kayıt No", "fatura_no", fatura_no, genislik=14, readonly=True)
        if self.fatura is None:
            self.after_idle(self._alis_kayit_no_ata)
        self._girdi(
            p_fat,
            1,
            "Tedarikçi Fat. No",
            "tedarikci_fatura_no",
            (getattr(self.fatura, "tedarikci_fatura_no", None) or "") if self.fatura else "",
            genislik=14,
        )
        self.girdiler["tedarikci_fatura_no"].bind("<FocusOut>", self._mukerrer_uyar, add="+")

        # Satır 2: Fatura Tarihi | İşlem Saati — Takvim düğmesi yok; tıkla → takvim
        ttk.Label(p_fat, text="Fatura Tarihi", style="AlisUst.TLabel").grid(
            row=2, column=0, padx=(0, 6), pady=py, sticky="w"
        )
        e_ft = ttk.Entry(p_fat, width=12, style="FaturaUst.TEntry")
        e_ft.insert(
            0,
            tarih_goster(self.fatura.fatura_tarihi)
            if self.fatura
            else date.today().strftime("%d.%m.%Y"),
        )
        takvim_entry_bagla(e_ft, on_select=self.vade_gun_degisti)
        e_ft.grid(row=2, column=1, padx=(0, 8), pady=py, sticky="ew")
        self.girdiler["fatura_tarihi"] = e_ft
        ttk.Label(p_fat, text="İşlem Saati", style="AlisUst.TLabel").grid(
            row=2, column=2, padx=(0, 6), pady=py, sticky="w"
        )
        saat_deger = saat_varsayilan(
            self.fatura.islem_saati
            if self.fatura and self.fatura.islem_saati
            else (self.fatura.olusturma_tarihi.strftime("%H:%M") if self.fatura else None)
        )
        e_saat = ttk.Entry(p_fat, width=7, style="FaturaUst.TEntry")
        e_saat.insert(0, saat_deger)
        e_saat.grid(row=2, column=3, padx=0, pady=py, sticky="ew")
        self.girdiler["islem_saati"] = e_saat

        # Satır 3: Vade Tarihi | Vade Günü
        ttk.Label(p_fat, text="Vade Tarihi", style="AlisUst.TLabel").grid(
            row=3, column=0, padx=(0, 6), pady=py, sticky="w"
        )
        e_vt = ttk.Entry(p_fat, width=12, style="FaturaUst.TEntry")
        e_vt.insert(
            0,
            tarih_goster(self.fatura.vade_tarihi)
            if self.fatura
            else date.today().strftime("%d.%m.%Y"),
        )
        takvim_entry_bagla(e_vt, on_select=self.vade_tarih_degisti)
        e_vt.grid(row=3, column=1, padx=(0, 8), pady=py, sticky="ew")
        self.girdiler["vade_tarihi"] = e_vt
        ttk.Label(p_fat, text="Vade Günü", style="AlisUst.TLabel").grid(
            row=3, column=2, padx=(0, 6), pady=py, sticky="w"
        )
        e_vg = ttk.Entry(p_fat, width=7, style="FaturaUst.TEntry")
        e_vg.insert(0, str(self.fatura.vade_gunu if self.fatura else 0))
        e_vg.grid(row=3, column=3, padx=0, pady=py, sticky="ew")
        self.girdiler["vade_gunu"] = e_vg
        e_ft.bind("<FocusOut>", self.vade_gun_degisti)
        e_vt.bind("<FocusOut>", self.vade_tarih_degisti)
        e_vg.bind("<KeyRelease>", self.vade_gun_degisti)

        # Satır 4: Durum | Onay
        ttk.Label(p_fat, text="Durum", style="AlisUst.TLabel").grid(
            row=4, column=0, padx=(0, 6), pady=py, sticky="w"
        )
        self.durum = ttk.Combobox(
            p_fat,
            values=("AÇIK", "KAPALI", "İPTAL"),
            state="readonly",
            width=10,
            style="FaturaUst.TCombobox",
        )
        self.durum.grid(row=4, column=1, padx=(0, 8), pady=py, sticky="ew")
        self.durum.set(self.fatura.durum if self.fatura else "AÇIK")
        self.durum.configure(state="disabled")
        ttk.Label(p_fat, text="Onay", style="AlisUst.TLabel").grid(
            row=4, column=2, padx=(0, 6), pady=py, sticky="w"
        )
        self._onay_bilgi_lbl = ttk.Label(p_fat, text="", style="AlisUst.TLabel")
        self._onay_bilgi_lbl.grid(row=4, column=3, padx=0, pady=py, sticky="w")

        # H referansı: Kayıt No kutusu
        try:
            self.update_idletasks()
            self._alis_h_ref = max(
                self._alis_satir_h, int(self.girdiler["fatura_no"].winfo_reqheight())
            )
        except tk.TclError:
            self._alis_h_ref = self._alis_satir_h

        # ========== 3 — Depo, Belge ve Döviz (+ Açıklama) ==========
        p_depo = ttk.LabelFrame(ust, text="Depo, Belge ve Döviz", style="AlisUst.TLabelframe")
        p_depo.grid(row=0, column=2, sticky="nsew", padx=(0, gap))
        self._alis_ust_depo = p_depo
        p_depo.columnconfigure(1, weight=1)
        _satir_yuva(p_depo, 5)

        ttk.Label(p_depo, text="Giriş Deposu", style="AlisUst.TLabel").grid(
            row=0, column=0, padx=(0, 6), pady=py, sticky="w"
        )
        depo_satir = ttk.Frame(p_depo)
        depo_satir.grid(row=0, column=1, columnspan=2, sticky="ew", pady=py)
        depolar = tuple(d.ad for d in StokService.depolar()) or ("ANA DEPO",)
        self.depo = ttk.Combobox(
            depo_satir, values=depolar, state="readonly", width=14, style="FaturaUst.TCombobox"
        )
        self.depo.pack(side="left", fill="x", expand=True)
        if self.fatura and self.fatura.depo in depolar:
            self.depo.set(self.fatura.depo)
        else:
            self.depo.set(depolar[0])
        ttk.Button(depo_satir, text="Yeni", width=5, command=self.depo_ekle, style="FaturaUst.TButton").pack(
            side="left", padx=(4, 0)
        )
        self.girdiler["depo"] = self.depo

        ttk.Label(p_depo, text="Doküman", style="AlisUst.TLabel").grid(
            row=1, column=0, padx=(0, 6), pady=py, sticky="w"
        )
        dok_satir = ttk.Frame(p_depo)
        dok_satir.grid(row=1, column=1, columnspan=2, sticky="ew", pady=py)
        self.dokuman = ttk.Entry(dok_satir, width=14, style="FaturaUst.TEntry")
        self.dokuman.pack(side="left", fill="x", expand=True)
        ttk.Button(dok_satir, text="Seç", width=4, command=self.dokuman_sec, style="FaturaUst.TButton").pack(
            side="left", padx=(4, 0)
        )
        self.girdiler["dokuman"] = self.dokuman

        ttk.Label(p_depo, text="Para Birimi", style="AlisUst.TLabel").grid(
            row=2, column=0, padx=(0, 6), pady=py, sticky="w"
        )
        dov_satir = ttk.Frame(p_depo)
        dov_satir.grid(row=2, column=1, columnspan=2, sticky="ew", pady=py)
        self._doviz_ozet_lbl = ttk.Label(dov_satir, text="TRY", style="AlisUst.TLabel")
        self._doviz_ozet_lbl.pack(side="left")
        self._doviz_ac_btn = ttk.Button(
            dov_satir, text="Döviz / Kur", command=self._doviz_alani_ac_kapat, style="FaturaUst.TButton"
        )
        self._doviz_ac_btn.pack(side="left", padx=(8, 0))

        ttk.Label(p_depo, text="Açıklama", style="AlisUst.TLabel").grid(
            row=3, column=0, padx=(0, 6), pady=py, sticky="w"
        )
        self.girdiler["aciklama"] = ttk.Entry(p_depo, width=22, style="FaturaUst.TEntry")
        self.girdiler["aciklama"].grid(row=3, column=1, columnspan=2, padx=0, pady=py, sticky="ew")

        ttk.Label(
            p_depo,
            text="Stok girişi ve lot bu depoya yazılır.",
            style="AlisUst.TLabel",
            foreground=ftema.IKINCIL,
        ).grid(row=4, column=0, columnspan=3, sticky="w", pady=py)

        # ========== 4 — Borç / Alacak Özeti ==========
        p_borc = ttk.LabelFrame(ust, text="Borç / Alacak Özeti", style="AlisUst.TLabelframe")
        p_borc.grid(row=0, column=3, sticky="nsew")
        self._alis_ust_borc = p_borc
        from cari_borc_alacak_ozet import EvrakCariOzetPaneli

        self._cari_borc_alacak = EvrakCariOzetPaneli(
            p_borc,
            bg=ftema.BEYAZ,
            font_fn=lambda boy, kalin: ftema.font(boy, kalin, self),
            tedarikci_modu=True,
            kompakt=True,
        )
        gizli = tk.Frame(p_borc)
        self.girdiler["mevcut_bakiye"] = ttk.Entry(gizli)
        self.girdiler["tahmini_bakiye"] = ttk.Entry(gizli)

        self.after(80, self._alis_ust_yukseklik_esitle)

    def _tedarikci_degisti(self):
        self._form_degisti()
        self._bakiye_guncelle()
        self._toolbar_guncelle()

    def _tedarikci_listeden_sec(self, _event=None):
        """F10 / sağ tık / Ara: tam tedarikçi listesi (yazılan metinle filtreli açılır)."""
        if self._alis_kilitli() or str(self.tedarikci_ad.cget("state")) == "disabled":
            return "break"
        arama = getattr(self, "_tedarikci_arama", None)
        if arama is not None:
            arama.kapat()
        from app import MusteriSecimDialog

        metin = (self._tedarikci_metin.get() or "").strip()
        if metin == self._secili_tedarikci_adi():
            metin = ""
        try:
            tedarikciler = list(AlisFaturasiService.aktif_tedarikcileri())
        except Exception:
            tedarikciler = []
        for c in tedarikciler:
            _tedarikci_ekle(self.tedarikci_map, c)
        tedarikciler = list(dict.fromkeys(self.tedarikci_map.values()))
        try:
            dialog = MusteriSecimDialog(
                self, musteriler=tedarikciler, baslik="Tedarikçi Seçimi", kayit_adi="tedarikçi",
                ara=metin,
            )
        except Exception as hata:  # noqa: BLE001
            from uygulama_log import hata_yaz

            hata_yaz("Alış faturası — tedarikçi listesi", hata)
            messagebox.showerror("Tedarikçi", f"Tedarikçi listesi açılamadı:\n{hata}", parent=self)
            return "break"
        self._tedarikci_liste_pencere = dialog
        self.wait_window(dialog)
        self._tedarikci_liste_pencere = None
        try:
            self.grab_set()
            self.tedarikci_ad.focus_set()
        except tk.TclError:
            pass
        cari = getattr(dialog, "result", None)
        if cari is not None:
            self._tedarikci_sec(cari)
            self._tedarikci_degisti()
        return "break"

    # ─── tedarikçi seçimi (kart kimliğine bağlı)
    def _secili_tedarikci(self):
        return self.tedarikci_map.get(self.tedarikci.get())

    def _secili_tedarikci_adi(self) -> str:
        cari = self._secili_tedarikci()
        return (cari.unvan or "").strip() if cari is not None else ""

    def _tedarikci_gorunumu_esitle(self) -> None:
        cari = self._secili_tedarikci()
        kod_w = getattr(self, "_tedarikci_kod", None) or getattr(self, "_tedarikci_kod_lbl", None)
        try:
            if cari is not None:
                if (self._tedarikci_metin.get() or "").strip() != (cari.unvan or "").strip():
                    self._tedarikci_metin.set(cari.unvan or "")
                kod = cari.cari_kodu or ""
            else:
                metin = (self._tedarikci_metin.get() or "").strip()
                kod = "— geçerli kart seçin" if metin else "— seçilmedi"
            if kod_w is None:
                return
            if isinstance(kod_w, (ttk.Entry, tk.Entry)):
                once = str(kod_w.cget("state") or "readonly")
                kod_w.configure(state="normal")
                kod_w.delete(0, "end")
                kod_w.insert(0, kod)
                kod_w.configure(state="readonly" if once != "disabled" else "disabled")
            else:
                kod_w.configure(
                    text=kod,
                    foreground=ftema.LACIVERT if cari is not None else "#B45309",
                )
        except (tk.TclError, AttributeError):
            pass

    def _tedarikci_aramadan_sec(self, cari) -> None:
        self._tedarikci_sec(cari)
        self._tedarikci_degisti()

    def _tedarikci_secimi_temizle(self) -> None:
        """Ad elle değiştirildi: eski kart kimliği bağlı kalmasın."""
        if not self.tedarikci.get():
            return
        self.tedarikci.set("")
        self._tedarikci_degisti()

    def yeni_tedarikci_ekle(self):
        """Mevcut tedarikçi cari kartını açar; kaydedilirse faturada seçer. İptalde değişiklik yok."""
        if self._kilit_uyar():
            return None
        from database.access import yetki_var

        if not yetki_var("cari_duzenleme", "yeni_kayit"):
            messagebox.showwarning("Yetki", "Cari kart oluşturma yetkiniz yok.", parent=self)
            return None
        arama = getattr(self, "_tedarikci_arama", None)
        if arama is not None:
            arama.kapat()
        ad = (self._tedarikci_metin.get() or "").strip()
        if ad == self._secili_tedarikci_adi():
            ad = ""
        try:
            from cari_kart_ui import CariDialog

            dialog = CariDialog(self, cari_turu="Tedarikçi")
        except Exception as hata:  # noqa: BLE001
            from uygulama_log import hata_yaz

            hata_yaz("Alış faturası — Yeni Tedarikçi", hata)
            messagebox.showerror("Yeni Tedarikçi", f"Tedarikçi kartı açılamadı:\n{hata}", parent=self)
            return None
        self._yeni_tedarikci_pencere = dialog
        if ad and "unvan" in getattr(dialog, "degerler", {}):
            try:
                w = dialog.degerler["unvan"]
                w.delete(0, "end")
                w.insert(0, ad)
            except (tk.TclError, AttributeError):
                pass
        self.wait_window(dialog)
        self._yeni_tedarikci_pencere = None
        try:
            self.grab_set()
            self.lift()
        except tk.TclError:
            pass
        yeni = getattr(dialog, "result", None)
        if yeni is None or not getattr(yeni, "id", None):
            return None
        tur = (getattr(yeni, "cari_turu", "") or "").casefold()
        if not tur.startswith("tedarik"):
            messagebox.showwarning("Yeni Tedarikçi", "Kaydedilen kart bir tedarikçi kartı değil.", parent=self)
            return None
        if not getattr(yeni, "aktif", True):
            messagebox.showwarning("Yeni Tedarikçi", "Kaydedilen tedarikçi kartı pasif; seçilmedi.", parent=self)
            return None
        self._tedarikci_sec(yeni)
        self._tedarikci_degisti()
        return yeni

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
            "F6 yeni stok · Enter/Tab alanlar arasında ilerler · sağ tık: satır işlemleri",
            foreground="#627D98",
        ).pack(side="left")
        ttk.Button(butonlar, text="Kolon Ayarları", command=self._alis_kolon_ayarlari_ac).pack(side="right", padx=4)
        self.yeni_stok_btn = ttk.Button(
            butonlar, text="Yeni Stok Oluştur (F6)", command=self.yeni_stok_olustur
        )
        self.yeni_stok_btn.pack(side="right", padx=4)
        self._alis_irsaliye_getir_btn = ttk.Button(
            butonlar, text="İrsaliyeden Getir (Alt+I)", command=self._alis_irsaliyeden_getir
        )
        self._alis_irsaliye_getir_btn.pack(side="right", padx=4)
        self._alis_siparis_getir_btn = ttk.Button(
            butonlar, text="Siparişten Getir (Alt+S)", command=self._alis_siparisten_getir
        )
        self._alis_siparis_getir_btn.pack(side="right", padx=4)
        ttk.Button(butonlar, text="Çoklu İskonto", command=self._alis_iskonto_ac).pack(side="right", padx=4)
        ttk.Button(butonlar, text="Araya Satır Ekle", command=self._alis_araya_ekle).pack(side="right", padx=4)
        ttk.Button(butonlar, text="Satırı Sil (Del)", command=self.satir_sil).pack(side="right", padx=4)
        self.bind("<Alt-s>", self._alis_siparisten_getir)
        self.bind("<Alt-S>", self._alis_siparisten_getir)
        self.bind("<Alt-i>", self._alis_irsaliyeden_getir)
        self.bind("<Alt-I>", self._alis_irsaliyeden_getir)

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
        try:
            from treeview_excel_cizgi import excel_cizgi_bagla

            self.after_idle(
                lambda: excel_cizgi_bagla(
                    self,
                    self.satir_tablosu,
                    style_name=ALIS_TABLO_STILI,
                    bag_adi="alis_fatura",
                )
            )
        except Exception:
            pass
        self._alis_fatura_girisi_kur()

        # Açık zemin sticky alt özet (satış düzeni) — Toplevel çocuğu olmalı
        self._alis_alt_ozet_kur()

    def _alis_alt_ozet_kur(self):
        """Satıştaki gibi açık zemin: solda Notlar/Ödemeler, sağda hizalı toplamlar + Net."""
        dis = tk.Frame(self, bg=ftema.ACIK_BG, padx=4, pady=2)
        self._alis_toplam_cerceve = dis
        self._alis_satir_brut = Decimal("0")
        self._alis_net_toplam = Decimal("0")
        self._fatura_persisted = bool(
            getattr(self, "fatura", None) and getattr(self.fatura, "id", None)
        )

        kart = tk.Frame(dis, bg=ftema.BEYAZ, highlightthickness=1, highlightbackground=ftema.CIZGI)
        kart.pack(fill="x", expand=True, padx=2, pady=2)
        kart.columnconfigure(0, weight=3)
        kart.columnconfigure(1, weight=2)

        sol = tk.Frame(kart, bg=ftema.BEYAZ)
        sol.grid(row=0, column=0, sticky="nsew", padx=(6, 4), pady=4)
        try:
            stil = ttk.Style(self)
            stil.configure(
                "AlisDetay.TNotebook",
                background=ftema.BEYAZ,
                borderwidth=0,
                tabmargins=(0, 0, 0, 0),
            )
            stil.configure(
                "AlisDetay.TNotebook.Tab",
                padding=(10, 2),
                font=ftema.font(9, "bold", root=self),
            )
        except tk.TclError:
            pass
        nb = ttk.Notebook(sol, style="AlisDetay.TNotebook")
        nb.pack(fill="both", expand=True)
        not_fr = ttk.Frame(nb, padding=4)
        odeme_fr = ttk.Frame(nb, padding=4)
        nb.add(not_fr, text="Ayrıntılı Notlar")
        nb.add(odeme_fr, text="Ödemeler")
        if "aciklama" not in self.girdiler:
            self.girdiler["aciklama"] = ttk.Entry(not_fr)
        self.ayrintili_notlar = tk.Text(not_fr, height=4, width=40, relief="flat", bd=0)
        self.ayrintili_notlar.pack(fill="both", expand=True)
        kolonlar = ("tarih", "tutar", "sekil", "hesap", "aciklama")
        self.odeme_tablosu = ttk.Treeview(odeme_fr, columns=kolonlar, show="headings", height=4)
        for kolon, baslik in zip(kolonlar, ("Tarih", "Tutar", "Ödeme Şekli", "Hesap", "Açıklama")):
            self.odeme_tablosu.heading(kolon, text=baslik)
            self.odeme_tablosu.column(kolon, width=100)
        self.odeme_tablosu.pack(fill="both", expand=True)
        odeme_alt = ttk.Frame(odeme_fr)
        odeme_alt.pack(fill="x", pady=(4, 0))
        ttk.Button(odeme_alt, text="Ödeme Ekle", command=self.odeme_ekle).pack(side="left")
        ttk.Button(odeme_alt, text="Ödeme Düzenle", command=self.odeme_duzenle).pack(side="left", padx=6)
        ttk.Button(odeme_alt, text="Ödeme Kaldır", command=self.odeme_kaldir).pack(side="left")
        self.odeme_ozet = ttk.Label(odeme_fr, text="Ödenen: 0,00 TL | Kalan: 0,00 TL")
        self.odeme_ozet.pack(anchor="w", pady=(2, 0))

        sag = tk.Frame(kart, bg=ftema.BEYAZ)
        sag.grid(row=0, column=1, sticky="ne", padx=(4, 8), pady=4)
        self._alis_ozet_lbls: dict[str, tk.Label] = {}
        kucuk = ftema.font(9, root=self)
        kalin = ftema.font(9, "bold", root=self)
        ozet_satirlar = (
            (0, 0, "ara", "Ara Toplam"),
            (1, 0, "iskonto", "İskonto"),
            (2, 0, "brut", "Brüt Toplam"),
            (0, 1, "matrah", "KDV Matrahı"),
            (1, 1, "kdv", "KDV"),
            (2, 1, "doviz", "Döviz Karşılığı"),
        )
        for satir, grup, anahtar, baslik in ozet_satirlar:
            k = grup * 3
            tk.Label(
                sag, text=baslik, bg=ftema.BEYAZ, fg=ftema.IKINCIL, font=kucuk, anchor="e"
            ).grid(row=satir, column=k, sticky="e", padx=(12 if grup else 0, 6), pady=0)
            deger = tk.Label(
                sag,
                text="—" if anahtar == "doviz" else "0,00 TL",
                bg=ftema.BEYAZ,
                fg=ftema.METIN,
                font=kalin,
                anchor="e",
                width=14,
            )
            deger.grid(row=satir, column=k + 1, sticky="e", pady=0)
            self._alis_ozet_lbls[anahtar] = deger
        tk.Frame(sag, bg=ftema.CIZGI, height=1).grid(
            row=3, column=0, columnspan=6, sticky="ew", pady=(4, 2)
        )
        tk.Label(
            sag,
            text="Net Toplam",
            bg=ftema.BEYAZ,
            fg=ftema.LACIVERT,
            font=ftema.font(11, "bold", root=self),
            anchor="e",
        ).grid(row=4, column=0, columnspan=4, sticky="e", padx=(0, 8))
        self._alis_net_lbl = tk.Label(
            sag,
            text="0,00 TL",
            bg=ftema.BEYAZ,
            fg=ftema.LACIVERT,
            font=ftema.font(13, "bold", root=self),
            anchor="e",
            width=14,
        )
        self._alis_net_lbl.grid(row=4, column=4, columnspan=2, sticky="e")
        self._alis_brut_lbl = self._alis_ozet_lbls["brut"]
        # Geriye uyumluluk
        self.satir_ozet = tk.Label(sag, text="", bg=ftema.BEYAZ, fg=ftema.IKINCIL, font=kucuk)

        dugme = tk.Frame(dis, bg=ftema.ACIK_BG)
        dugme.pack(fill="x", padx=4, pady=(0, 2))
        ftema.oval_buton(dugme, "Kapat (Esc)", self.kapat_istegi, rol="yardimci", grup="dis").pack(
            side="right", padx=(8, 0)
        )
        self._alt_kaydet_btn = ftema.oval_buton(
            dugme, "Kaydet (F1)", self.kaydet, rol="kaydet", grup="dis"
        )
        self._alt_kaydet_btn.pack(side="right", padx=(8, 0))

    def _odeme_olustur(self, parent):
        """Eski çağrılar için yedek — sticky alt özet kurulmuşsa no-op."""
        if getattr(self, "odeme_tablosu", None) is not None:
            return
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
        """Eski çağrılar için yedek — sticky alt özet kurulmuşsa no-op."""
        if getattr(self, "ayrintili_notlar", None) is not None:
            return
        cerceve = ttk.LabelFrame(parent, text="AYRINTILI NOTLAR", padding=8)
        cerceve.grid(row=0, column=1, sticky="nsew", padx=(8, 0))
        if "aciklama" not in self.girdiler:
            self.girdiler["aciklama"] = ttk.Entry(cerceve)
        self.ayrintili_notlar = tk.Text(cerceve, height=5, width=45)
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
        if anahtar:
            self.tedarikci.set(anahtar)
            self._tedarikci_gorunumu_esitle()

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
            kilitli=self._alis_kilitli,
            yeni_stok_eklendi=self._yeni_stok_faturaya_ekle,
            **satin_alma_satir_ozellikleri(self),
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
                HucreAlani("iskonto", "iskonto3", deger=lambda i: iskonto_metni(self.satirlar[i])),
                HucreAlani("kdv", "secim", secenekler=lambda _i: ("0", "1", "10", "20"), serbest=True,
                           deger=lambda i: sayi_metni(self.satirlar[i].get("kdv_orani") or 0)),
                HucreAlani("lot", "metin", deger=lambda i: self.satirlar[i].get("lot_no") or ""),
            ],
            uygula=self.alis_fatura_hucre_uygula,
            satir_sayisi=lambda: len(self.satirlar),
            bitince=self._satir_ici_giris.odakla,
            kilitli=self._alis_kilitli,
        )
        self.satir_tablosu.bind("<Delete>", lambda _e: self.satir_sil())
        self.bind("<F6>", self.yeni_stok_olustur)
        self._satir_ici_giris.tabloya_ekle()
        from fiyat_kaynagi_ui import fiyat_notu_bagla

        fiyat_notu_bagla(self, self.satir_tablosu, lambda: self.satirlar)

    def yeni_stok_olustur(self, _event=None):
        """Stokta olmayan ürün için hızlı stok kartı; kaydedilirse faturaya eklenir."""
        if self._kilit_uyar():
            return "break"
        giris = getattr(self, "_satir_ici_giris", None)
        if giris is None:
            return "break"
        try:
            giris.yeni_stok_karti()
        except Exception as hata:  # noqa: BLE001
            from uygulama_log import hata_yaz

            hata_yaz("Alış faturası — Yeni Stok Oluştur", hata)
            messagebox.showerror("Yeni Stok", f"Stok kartı penceresi açılamadı:\n{hata}", parent=self)
        return "break"

    def _yeni_stok_faturaya_ekle(self, stok) -> None:
        """Hızlı stok kartı kaydedildi ama satır eklenmediyse karttaki ürünü satıra alır."""
        giris = getattr(self, "_satir_ici_giris", None)
        if giris is None or stok is None or self._alis_kilitli():
            return
        giris.stoktan_ekle(stok)

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
        kod = (s.get("urun_kodu") or "").strip()
        try:
            from birim_secim_ui import evrak_birim_secenekleri
            from fatura_satir_birim_service import _stok_yukle, stok_aktif_birimleri

            # Faturada yalnız stok kartının birimleri; kartsız satırda genel birim listesi
            if kod and _stok_yukle(kod) is not None:
                return stok_aktif_birimleri(kod)
            return evrak_birim_secenekleri(kod) or list(BIRIM_SECENEKLERI)
        except Exception:
            return list(BIRIM_SECENEKLERI)

    def _alis_fatura_satiri(self, degerler) -> dict:
        from fiyat_kaynagi_ui import alis_fiyati_coz, sonucu_satira_yaz

        kod = ((degerler[0] if degerler else "") or "").strip()
        if not kod:
            raise ValueError("Ürün kodu boş.")
        birim = (degerler[2] if len(degerler) > 2 else "") or "Adet"
        stok = next((s for s in StokService.stoklari_ara(kod) if s.stok_kodu == kod), None)
        kdv_metin = satir_kdv_metin(stok_kdv=getattr(stok, "kdv_orani", None) if stok else None)
        # Fiyat belge para biriminde gelir; doviz_satir_kaydet_oncesi başlık kuruyla TL'ye çevirir
        sonuc = alis_fiyati_coz(self, kod, birim, decimal(kdv_metin or 0, "KDV", Decimal("0")))
        fiyat = sonuc.fiyat if sonuc.fiyat is not None else Decimal("0")
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
            "kdv_orani": kdv_metin,
            "lot_no": lot,
            "lot_girisi": lot,
        }
        sonucu_satira_yaz(veri, sonuc)
        return doviz_satir_kaydet_oncesi(self, veri)

    def _alis_fatura_fiyati_yenile(self, idx: int) -> None:
        from fiyat_kaynagi_ui import alis_fiyati_coz, fiyat_notu_goster, sonucu_satira_yaz, yenileme_onayi

        if self._kilit_uyar() or not (0 <= idx < len(self.satirlar)):
            return
        s = self.satirlar[idx]
        if self._alis_fatura_bagli(s):
            messagebox.showinfo(
                "Fiyatı Yenile", "Sipariş / irsaliyeden gelen satırın anlaşılan fiyatı korunur.", parent=self
            )
            return
        if not yenileme_onayi(self, s):
            return
        sonuc = alis_fiyati_coz(self, s.get("urun_kodu") or "", s.get("birim") or "", decimal(
            s.get("kdv_orani") or 0, "KDV", Decimal("0")))
        yeni = dict(s)
        if sonuc.fiyat is not None:
            yeni["birim_fiyat"] = yeni["birim_alis_fiyati"] = f"{sonuc.fiyat:f}"
            yeni.pop("birim_fiyat_doviz", None)
            yeni = doviz_satir_kaydet_oncesi(self, yeni)
        sonucu_satira_yaz(yeni, sonuc)
        self.satirlar[idx] = yeni
        self._alis_fatura_yenile()
        fiyat_notu_goster(self, self.satir_tablosu, yeni)

    def _alis_fatura_urun_ekle(self, degerler, konum):
        from satir_ici_urun_giris import birlesecek_satir, giris_bileseni

        if self._alis_kilitli():
            raise ValueError("Onaylı veya iptal faturaya satır eklenemez.")
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
        from fiyat_kaynagi_ui import fiyat_notu_goster

        fiyat_notu_goster(self, self.satir_tablosu, veri)
        return idx

    def _alis_fatura_urun_degistir(self, idx: int, degerler) -> bool:
        if not (0 <= idx < len(self.satirlar)) or self._kilit_uyar():
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
        from satir_ici_urun_giris import iskonto_metni_coz

        if not (0 <= idx < len(self.satirlar)):
            return
        if self._alis_kilitli():
            raise ValueError("Onaylı veya iptal faturada satır değiştirilemez.")
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
            from birim_secim_ui import kart_birimini_hazirla

            if not kart_birimini_hazirla(self, s.get("urun_kodu") or "", birim):
                return
            from fiyat_kaynagi_ui import alis_fiyati_coz, birim_degisiminde_yeniden_fiyat, sonucu_satira_yaz

            karar = birim_degisiminde_yeniden_fiyat(self, s)
            if karar is None:
                return
            yeni["birim"] = birim
            if karar:
                sonuc = alis_fiyati_coz(self, s.get("urun_kodu") or "", birim, decimal(
                    s.get("kdv_orani") or 0, "KDV", Decimal("0")))
                fiyat = sonuc.fiyat if sonuc.fiyat is not None else Decimal("0")
                yeni["birim_fiyat"] = yeni["birim_alis_fiyati"] = f"{fiyat:f}"
                yeni.pop("birim_fiyat_doviz", None)
                yeni = doviz_satir_kaydet_oncesi(self, yeni)
                sonucu_satira_yaz(yeni, sonuc)
        elif kolon == "fiyat":
            from fiyat_kaynagi_ui import elle_isaretle

            fiyat = decimal(metin or 0, "Birim alış", Decimal("0"))
            eski_metin = s.get("birim_fiyat_doviz") if self._alis_doviz_aktif() else s.get("birim_fiyat")
            yeni["birim_fiyat"] = yeni["birim_alis_fiyati"] = f"{fiyat:f}"
            yeni = doviz_satir_kaydet_oncesi(self, yeni)
            if fiyat != decimal(eski_metin or 0, "Birim alış", Decimal("0")):
                elle_isaretle(yeni)
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
            ogeler.insert(2, ("Fiyatı Yenile", lambda: self._alis_fatura_fiyati_yenile(idx)))
        return ogeler

    def _alis_araya_ekle(self):
        if self._kilit_uyar():
            return
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
        if self._kilit_uyar():
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
        if self._kilit_uyar():
            return "break"
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
        if self._kilit_uyar():
            return
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

        if self._kilit_uyar():
            return "break"
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
            self._cari_borc_alacak_yenile()
            self._toplamlari_guncelle(Decimal("0"))
            return
        ozet = AlisFaturasiService.bakiye_ozeti(
            tedarikci.id, Decimal("0"), None, self.fatura.fatura_no if self.fatura else None
        )
        self._cari_ozet = ozet
        self.mevcut_borc = ozet["bakiye"]
        self._readonly_yaz("mevcut_bakiye", para_goster(self.mevcut_borc))
        self._cari_borc_alacak_yenile()
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
        matrah = toplam["ara_toplam"] - toplam["iskonto"]
        self._alis_satir_brut = toplam["ara_toplam"]
        self._alis_net_toplam = satir_genel
        ozet_lbls = getattr(self, "_alis_ozet_lbls", None) or {}
        degerler = {
            "ara": toplam["ara_toplam"],
            "iskonto": toplam["iskonto"],
            "brut": toplam["ara_toplam"],  # alışta satır brütü (iskonto öncesi)
            "matrah": matrah,
            "kdv": toplam["kdv"],
        }
        for anahtar, tutar in degerler.items():
            lbl = ozet_lbls.get(anahtar)
            if lbl is not None:
                try:
                    lbl.configure(text=para_goster(tutar))
                except tk.TclError:
                    pass
        doviz_lbl = ozet_lbls.get("doviz")
        if doviz_lbl is not None:
            try:
                pb = "TRY"
                if hasattr(self, "_doviz_para_birimi"):
                    pb = (self._doviz_para_birimi.get() or "TRY").upper()
                if pb != "TRY":
                    kur = Decimal("1")
                    if hasattr(self, "_doviz_kur"):
                        try:
                            kur = decimal(self._doviz_kur.get() or 1, "Kur")
                        except Exception:
                            kur = Decimal("1")
                    if kur > 0:
                        doviz_lbl.configure(text=f"{para_goster(satir_genel / kur)} {pb}")
                    else:
                        doviz_lbl.configure(text="—")
                else:
                    doviz_lbl.configure(text="—")
            except tk.TclError:
                pass
        if hasattr(self, "satir_ozet"):
            try:
                self.satir_ozet.configure(text="")
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
        if "tahmini_bakiye" not in getattr(self, "girdiler", {}):
            return
        ozet = getattr(self, "_cari_ozet", None) or {}
        mevcut = decimal(ozet.get("bakiye") or 0, "Bakiye")
        odeme = sum((decimal(o["tutar"], "Ödeme") for o in getattr(self, "odemeler", [])), Decimal("0"))
        try:
            self._readonly_yaz("tahmini_bakiye", para_goster(mevcut + fatura_toplami - odeme))
        except (tk.TclError, KeyError):
            pass

    def _cari_borc_alacak_yenile(self, *, hemen: bool = False):
        """Üst paneldeki Borç / Alacak özetini seçili tedarikçi için yeniler (cari kart değerleri)."""
        panel = getattr(self, "_cari_borc_alacak", None)
        if panel is None:
            return
        tedarikci = self.tedarikci_map.get(self.tedarikci.get())
        panel.yenile(getattr(tedarikci, "id", None), hemen=hemen)

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

    def _alis_kilitli_mi(self) -> bool:
        return bool(self._alis_kilitli()) if hasattr(self, "_alis_kilitli") else False

    def _secili_tedarikci(self):
        return self.tedarikci_map.get(self.tedarikci.get()) if hasattr(self, "tedarikci") else None

    def _alis_siparisten_getir(self, _event=None):
        if self._alis_kilitli_mi():
            messagebox.showinfo(
                "Siparişten Getir",
                "Onaylı faturada sipariş aktarmak için önce Onayı Kaldır yapın.",
                parent=self,
            )
            return "break"
        tedarikci = self._secili_tedarikci()
        if not tedarikci:
            messagebox.showinfo(
                "Siparişten Getir",
                "Önce tedarikçi seçin; ardından bekleyen alış siparişleri listelenecek.",
                parent=self,
            )
            return "break"
        from fatura_siparis_secim_ui import fatura_icin_siparis_sec

        siparis_id = fatura_icin_siparis_sec(self, tedarikci, yon="alis")
        if not siparis_id:
            return "break"
        siparis = AlisSiparisiService.getir(int(siparis_id))
        if not siparis:
            messagebox.showerror("Sipariş", "Sipariş bulunamadı.", parent=self)
            return "break"
        if int(getattr(siparis, "cari_id", 0) or 0) != int(tedarikci.id):
            messagebox.showerror("Sipariş", "Seçilen sipariş bu tedarikçiye ait değil.", parent=self)
            return "break"
        self.kaynak_irsaliye = None
        self._siparis_yukle(siparis, ekle=True)
        return "break"

    def _alis_irsaliyeden_getir(self, _event=None):
        if self._alis_kilitli_mi():
            messagebox.showinfo(
                "İrsaliyeden Getir",
                "Onaylı faturada irsaliye aktarmak için önce Onayı Kaldır yapın.",
                parent=self,
            )
            return "break"
        tedarikci = self._secili_tedarikci()
        if not tedarikci:
            messagebox.showinfo(
                "İrsaliyeden Getir",
                "Önce tedarikçi seçin; ardından faturalanacak alış irsaliyeleri listelenecek.",
                parent=self,
            )
            return "break"
        from fatura_irsaliye_secim_ui import fatura_icin_irsaliye_sec

        irsaliye_id = fatura_icin_irsaliye_sec(self, tedarikci, yon="alis")
        if not irsaliye_id:
            return "break"
        irsaliye = AlisIrsaliyesiService.getir(int(irsaliye_id))
        if not irsaliye:
            messagebox.showerror("İrsaliye", "İrsaliye bulunamadı.", parent=self)
            return "break"
        if int(getattr(irsaliye, "cari_id", 0) or 0) != int(tedarikci.id):
            messagebox.showerror("İrsaliye", "Seçilen irsaliye bu tedarikçiye ait değil.", parent=self)
            return "break"
        if self.satirlar:
            if not messagebox.askyesno(
                "İrsaliyeden Getir",
                f"{irsaliye.irsaliye_no} irsaliyesinin kalan satırları faturaya eklensin mi?\n"
                "Mevcut satırlar korunur; aynı irsaliye satırları mükerrer eklenmez.",
                parent=self,
            ):
                return "break"
        self._irsaliyeyi_doldur(irsaliye, ekle=True)
        return "break"

    def _siparis_yukle(self, siparis, *, ekle: bool = False):
        self.kaynak_siparis = siparis
        self._tedarikci_sec(siparis.cari)
        self.siparis_no.delete(0, "end")
        self.siparis_no.insert(0, siparis.siparis_no)
        mevcut_siparis = {
            int(s["siparis_satiri_id"])
            for s in self.satirlar
            if s.get("siparis_satiri_id")
        }
        if not ekle:
            self.satirlar.clear()
            mevcut_siparis.clear()
        eklendi = 0
        for satir in siparis.satirlar:
            acik = satir.miktar - satir.faturalanan_miktar
            if acik <= 0:
                continue
            if int(satir.id) in mevcut_siparis:
                continue
            # Aynı teslimat irsaliye satırı olarak zaten varsa atla
            if any(
                int(s.get("siparis_satiri_id") or 0) == int(satir.id)
                for s in self.satirlar
            ):
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
            eklendi += 1
        if eklendi == 0 and not ekle:
            messagebox.showinfo("Fatura", "Bu siparişte faturalanacak açık miktar kalmadı.", parent=self)
        elif eklendi == 0 and ekle:
            messagebox.showinfo(
                "Siparişten Getir",
                "Aktarılacak yeni satır yok (açık miktar kalmadı veya zaten faturada).",
                parent=self,
            )
        self._bakiye_guncelle()
        self._satir_listesini_yenile()

    def _irsaliyeyi_doldur(self, irsaliye, *, ekle: bool = False):
        self.kaynak_irsaliye = irsaliye
        self._tedarikci_sec(irsaliye.cari)
        self.irsaliye_no.delete(0, "end")
        self.irsaliye_no.insert(0, irsaliye.irsaliye_no)
        if irsaliye.siparis:
            self.kaynak_siparis = irsaliye.siparis
            self.siparis_no.delete(0, "end")
            self.siparis_no.insert(0, irsaliye.siparis.siparis_no)
        mevcut_irs = {
            int(s["irsaliye_satiri_id"])
            for s in self.satirlar
            if s.get("irsaliye_satiri_id")
        }
        mevcut_sip = {
            int(s["siparis_satiri_id"])
            for s in self.satirlar
            if s.get("siparis_satiri_id")
        }
        if not ekle:
            self.satirlar.clear()
            mevcut_irs.clear()
            mevcut_sip.clear()
        eklendi = 0
        for satir in irsaliye.satirlar:
            kalan = satir.miktar - satir.faturalanan_miktar
            if kalan <= 0:
                continue
            if int(satir.id) in mevcut_irs:
                continue
            # Bağlı sipariş satırı zaten faturadaysa aynı teslimatı ikinci kez ekleme
            sip_sid = getattr(satir, "siparis_satiri_id", None)
            if sip_sid and int(sip_sid) in mevcut_sip:
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
            eklendi += 1
            if sip_sid:
                mevcut_sip.add(int(sip_sid))
        if eklendi == 0 and ekle:
            messagebox.showinfo(
                "İrsaliyeden Getir",
                "Aktarılacak yeni satır yok (kalan yok veya zaten faturada).",
                parent=self,
            )
        self._bakiye_guncelle()
        self._satir_listesini_yenile()

    def _faturayi_doldur(self):
        self._fatura_yukleniyor = True
        # Kilitli alanlara değer yazılabilsin; sonunda _toolbar_guncelle yeniden kilitler
        self._kilit_uygula(zorla=False)
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

    def _bagli_iadeler(self):
        if not self.fatura:
            messagebox.showinfo("Bağlı İadeler", "Önce faturayı kaydedin.", parent=self)
            return None
        from alis_iade_ui import BagliIadelerDialog

        pencere = BagliIadelerDialog(self, int(self.fatura.id), fatura_no=self.fatura.fatura_no or "")
        try:
            self.wait_window(pencere)
        finally:
            try:
                if self.winfo_exists():
                    self.grab_set()
            except tk.TclError:
                pass
        return pencere

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


# Alış iade faturası ekranı ayrı modülde (taslak → onay, kaynak kontrolü); eski ad korunur.
from alis_iade_ui import AlisIadeFaturasiPenceresi as AlisIadeFaturasiDialog  # noqa: E402,F401
