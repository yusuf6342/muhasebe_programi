"""Kredi kartı ekstre detay ve ödeme pencereleri — Aylara Göre Ödeme Durumu."""

from __future__ import annotations

from datetime import date
from decimal import Decimal
import tkinter as tk
from tkinter import messagebox, ttk


def _para(tutar) -> str:
    return (
        f"{Decimal(str(tutar or 0)):,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
        + " TL"
    )


def _tarih(d) -> str:
    if isinstance(d, date):
        return d.strftime("%d.%m.%Y")
    return str(d or "")


DURUM_ETIKET = {
    "KESILMEMIS": "Kesilmedi", "KESILMIS": "Kesildi", "KISMI": "Kısmen ödendi", "ODENDI": "Ödendi",
    "GECIKMIS": "Gecikmiş", "FAZLA": "Fazla ödendi", "EKSIK_BILGI": "Eksik bilgi (son ödeme günü tanımsız)",
}
KAYNAK_ETIKET = {"EKSTRE": "Ekstre ödemesi", "KASADAN_BANKAYA": "Kasadan yatırma", "VIRMAN": "Banka virmanı"}


def tutar_coz(metin) -> Decimal:
    """'20.000,50' / '20000,50' / '20000.50' → Decimal; geçersiz veya sıfır/eksi ise ValueError."""
    s = str(metin or "").strip().replace(" ", "").replace("TL", "")
    if "," in s:
        s = s.replace(".", "").replace(",", ".")
    try:
        d = Decimal(s)
    except Exception as exc:  # noqa: BLE001
        raise ValueError("Tutar geçerli bir sayı olmalıdır.") from exc
    if not d.is_finite() or d <= 0:
        raise ValueError("Tutar sıfırdan büyük olmalıdır.")
    return d.quantize(Decimal("0.01"))


def _odeme_hesaplari() -> list[tuple[int, str]]:
    """Ekstre ödemesinin çıkabileceği kasa ve vadesiz / KMH banka hesapları."""
    from database.finans_service import FinansService

    sonuc = []
    for h in FinansService.hesaplar():
        tur, alt = (h.hesap_turu or "").upper(), (h.alt_hesap_turu or "").upper()
        if tur == "KASA" or (tur == "BANKA" and alt in ("MEVDUAT", "KMH")):
            sonuc.append((int(h.id), h.hesap_adi))
    return sonuc


def _varsayilan_hesap(kredi_karti_id, hesaplar: list[tuple[int, str]]) -> int | None:
    """Kartın bankasındaki vadesiz hesap (servisin önceki varsayılanı)."""
    if not kredi_karti_id or not hesaplar:
        return None
    from database.database import get_session
    from database.models.finans import FinansHesabi, KrediKartiTanimi

    with get_session() as s:
        kart = s.get(KrediKartiTanimi, int(kredi_karti_id))
        if kart is None:
            return None
        for i, (hid, _ad) in enumerate(hesaplar):
            h = s.get(FinansHesabi, hid)
            if h and h.banka_karti_id == kart.banka_karti_id and (h.alt_hesap_turu or "").upper() == "MEVDUAT":
                return i
    return None


class EkstreSecici(ttk.Frame):
    """Kasa / banka → kredi kartı hesabı: ödenecek ekstre seçimi (ödeme ekstre ödemesi olarak yazılır)."""

    def __init__(self, parent):
        super().__init__(parent)
        self._ekstreler: list[dict] = []
        ttk.Label(self, text="Ödenecek ekstre *").pack(side="left")
        self.cb = ttk.Combobox(self, state="readonly", width=62)
        self.cb.pack(side="left", padx=6)
        self.bilgi = ttk.Label(self, foreground="#8a5a00")
        self.bilgi.pack(side="left")

    def doldur(self, kart_hesap_id: int) -> None:
        from database.database import get_session
        from database.kredi_karti_ekstre_service import KrediKartiEkstreService as E
        from database.models.finans import FinansHesabi, KrediKartiTanimi
        from sqlalchemy import select

        self._ekstreler = []
        with get_session() as s:
            fh = s.get(FinansHesabi, int(kart_hesap_id))
            kart_ids = [int(k.id) for k in s.scalars(select(KrediKartiTanimi).where(
                KrediKartiTanimi.banka_karti_id == fh.banka_karti_id,
                KrediKartiTanimi.aktif.is_(True))).all()] if fh else []
        for kid in kart_ids:
            self._ekstreler += E.acik_ekstreler(kid)
        self.cb.configure(values=[
            f"{e['kart_adi']} · kesim {_tarih(e['kesim_tarihi'])} · son ödeme "
            f"{_tarih(e['son_odeme_tarihi']) or 'tanımsız'} · kalan {_para(e['kalan'])}" for e in self._ekstreler])
        self.cb.set("")
        if self._ekstreler:
            self.cb.current(0)
        self.bilgi.configure(text="" if self._ekstreler else "Ödenecek ekstre yok.")

    def secili_ekstre_id(self) -> int | None:
        i = self.cb.current()
        return int(self._ekstreler[i]["ekstre_id"]) if 0 <= i < len(self._ekstreler) else None


class KkEkstreDetayDialog(tk.Toplevel):
    """Ekstre ana satır detayı + ödeme butonları."""

    def __init__(self, parent, satir: dict, *, yenile_cb=None):
        super().__init__(parent)
        self.satir = satir
        self.yenile_cb = yenile_cb
        self.title("Kredi Kartı Ekstre Detayı")
        self.geometry("1000x660")
        self.transient(parent)
        try:
            self.grab_set()
        except tk.TclError:
            pass

        from database.kredi_karti_ekstre_service import KrediKartiEkstreService

        try:
            if satir.get("ekstre_id"):
                self.detay = KrediKartiEkstreService.ekstre_detay(int(satir["ekstre_id"]))
            else:
                self.detay = KrediKartiEkstreService.ekstre_detay(
                    source_id=str(satir.get("source_id") or "")
                )
        except Exception as exc:
            messagebox.showerror("Ekstre", str(exc), parent=self)
            self.destroy()
            return

        ust = ttk.Frame(self)
        ust.pack(fill="x", padx=10, pady=8)
        ttk.Label(
            ust,
            text=self.detay.get("aciklama") or "Ekstre",
            font=("Segoe UI", 11, "bold"),
        ).pack(anchor="w")
        self.lbl_donem = ttk.Label(ust)
        self.lbl_donem.pack(anchor="w")
        self.lbl_ekstre = ttk.Label(ust, font=("Segoe UI", 9, "bold"))
        self.lbl_ekstre.pack(anchor="w", pady=(4, 0))
        self.lbl_kart = ttk.Label(ust, font=("Segoe UI", 9, "bold"), foreground="#1a2b4a")
        self.lbl_kart.pack(anchor="w", pady=(2, 0))
        self.lbl_uyari = ttk.Label(ust, foreground="#8a5a00", wraplength=960)
        self.lbl_uyari.pack(anchor="w")

        btn = ttk.Frame(self)
        btn.pack(fill="x", padx=10, pady=4)
        ttk.Button(btn, text="Ödeme Yap", command=self._odeme).pack(side="left", padx=2)
        ttk.Button(btn, text="Kısmi Ödeme", command=self._kismi).pack(side="left", padx=2)
        ttk.Button(btn, text="Tamamını Öde", command=self._tamami).pack(side="left", padx=2)
        ttk.Button(btn, text="Yenile", command=self._yenile_detay).pack(side="left", padx=2)
        ttk.Button(btn, text="Kapat", command=self.destroy).pack(side="right", padx=2)

        cols = ("tarih", "aciklama", "tur", "taksit", "borc", "alacak", "etki", "belge", "kaynak")
        self.tv = ttk.Treeview(self, columns=cols, show="headings", height=10)
        basliklar = (
            ("tarih", "İşlem tarihi", 90),
            ("aciklama", "Açıklama", 200),
            ("tur", "Tür", 90),
            ("taksit", "Taksit", 90),
            ("borc", "Borç", 90),
            ("alacak", "Alacak", 90),
            ("etki", "Etki", 90),
            ("belge", "Evrak", 110),
            ("kaynak", "Kaynak gider", 200),
        )
        for k, b, w in basliklar:
            self.tv.heading(k, text=b)
            self.tv.column(k, width=w, anchor="w" if k in ("aciklama", "kaynak") else "center")
        self.tv.pack(fill="both", expand=True, padx=10, pady=6)
        self._detay_filtre: dict = {}
        self._detay_ham: list = []
        from liste_filtre_ui import treeview_filtre_bagla

        self._detay_filtre_bag = treeview_filtre_bagla(
            self.tv,
            {k: b for k, b, _w in basliklar},
            get_filtre_dict=lambda: self._detay_filtre,
            set_filtre_dict=None,
            yenile_cb=self._detay_filtre_yenile,
            deger_listesi_cb=lambda: self._detay_ham,
            parent=self,
            kolonlar=cols,
        )

        odeme_ust = ttk.Frame(self)
        odeme_ust.pack(fill="x", padx=10)
        ttk.Label(odeme_ust, text="Bu ekstreye yapılan ödemeler", font=("Segoe UI", 9, "bold")).pack(side="left")
        self.btn_iptal = ttk.Button(odeme_ust, text="Ödemeyi İptal Et", command=self._odeme_iptal)
        self.btn_iptal.pack(side="right")
        from database.access import yetki_var

        if not yetki_var("finans_duzenleme"):
            self.btn_iptal.configure(state="disabled")
        ocols = ("tarih", "belge", "tutar", "hesap", "kaynak", "durum")
        self.tv_odeme = ttk.Treeview(self, columns=ocols, show="headings", height=4)
        odeme_baslik = (("tarih", "Tarih", 90), ("belge", "Belge", 120), ("tutar", "Tutar", 110),
                        ("hesap", "Dekont / açıklama", 260), ("kaynak", "Giriş", 110), ("durum", "Durum", 260))
        for k, b, w in odeme_baslik:
            self.tv_odeme.heading(k, text=b)
            self.tv_odeme.column(k, width=w, anchor="w" if k in ("hesap", "durum") else "center")
        self.tv_odeme.pack(fill="x", padx=10, pady=(2, 8))
        self._odeme_filtre: dict = {}
        self._odeme_ham: list = []
        self._odeme_filtre_bag = treeview_filtre_bagla(
            self.tv_odeme,
            {k: b for k, b, _w in odeme_baslik},
            get_filtre_dict=lambda: self._odeme_filtre,
            set_filtre_dict=None,
            yenile_cb=self._odeme_filtre_yenile,
            deger_listesi_cb=lambda: self._odeme_ham,
            parent=self,
            kolonlar=ocols,
        )
        self._doldur()

    def _ust_bilgi(self):
        d = self.detay
        son = _tarih(d.get("son_odeme_tarihi")) or "tanımsız"
        self.lbl_donem.configure(text=(
            f"Son ödeme: {son}  ·  Kesim: {_tarih(d.get('kesim_tarihi'))}  ·  "
            f"Dönem: {_tarih(d.get('donem_baslangic'))}–{_tarih(d.get('donem_bitis'))}"))
        self.lbl_ekstre.configure(text=(
            f"Ekstre toplamı: {_para(d.get('tl_tutar'))}  ·  Ödenen: {_para(d.get('odenen'))}  ·  "
            f"{DURUM_ETIKET.get(d.get('ekstre_durum'), d.get('ekstre_durum') or d.get('durum') or '')}"))
        oz = d.get("kart_ozeti") or {}
        if oz.get("limit_tanimli"):
            limit_metin = (f"Kullanılan limit: {_para(oz.get('kullanilan'))}  ·  "
                           f"Kullanılabilir limit: {_para(oz.get('kullanilabilir'))} "
                           f"(limit {_para(oz.get('limit'))})")
        else:
            limit_metin = f"Kullanılan limit: {_para(oz.get('kullanilan'))}  ·  Limit tanımsız"
        self.lbl_kart.configure(text=(
            f"Toplam kart borcu: {_para(oz.get('toplam_borc'))}  ·  Bu ekstrede kalan: {_para(d.get('kalan'))}  ·  "
            + limit_metin))
        uyarilar = []
        if not d.get("son_odeme_tarihi"):
            uyarilar.append("Kartın son ödeme günü tanımsız: ekstre 'Eksik bilgi' durumundadır, gecikme "
                            "belirlenemez. Kart tanımına son ödeme gününü girin.")
        if oz.get("belirsiz"):
            uyarilar.append(f"Dönemi belirsiz kart borcu {_para(oz.get('belirsiz'))} (kesim günü tanımsız) toplam "
                            "borçta ve limitte sayılır.")
        if oz.get("limit_tanimli") and oz.get("kullanilabilir") is not None and oz["kullanilabilir"] < 0:
            uyarilar.append("Kart limiti aşılmış.")
        self.lbl_uyari.configure(text="\n".join(uyarilar))

    def _detay_filtre_yenile(self):
        from liste_filtre_ui import satir_kolon_filtre_uygun

        cols = ("tarih", "aciklama", "tur", "taksit", "borc", "alacak", "etki", "belge", "kaynak")
        for i in self.tv.get_children():
            self.tv.delete(i)
        for item in self._detay_ham:
            if satir_kolon_filtre_uygun(item["values"], cols, self._detay_filtre):
                self.tv.insert("", "end", values=item["values"])
        self._detay_filtre_bag["guncelle_basliklar"]()

    def _odeme_filtre_yenile(self):
        from liste_filtre_ui import satir_kolon_filtre_uygun

        ocols = ("tarih", "belge", "tutar", "hesap", "kaynak", "durum")
        for i in self.tv_odeme.get_children():
            self.tv_odeme.delete(i)
        for item in self._odeme_ham:
            if satir_kolon_filtre_uygun(item["values"], ocols, self._odeme_filtre):
                self.tv_odeme.insert("", "end", iid=item["iid"], values=item["values"])
        self._odeme_filtre_bag["guncelle_basliklar"]()

    def _doldur(self):
        self._ust_bilgi()
        self._odeme_filtre.clear()
        self._odeme_ham.clear()
        for o in self.detay.get("odemeler") or []:
            durum = "Geçerli"
            if o.get("iptal"):
                durum = (f"İptal {_tarih(o.get('iptal_tarihi'))} — {o.get('iptal_nedeni') or ''}"
                         + (f" ({o['iptal_kullanici']})" if o.get("iptal_kullanici") else ""))
            values = (
                _tarih(o.get("tarih")), o.get("belge_no") or "", _para(o.get("tutar")),
                " · ".join(x for x in (o.get("dekont_no"), o.get("aciklama")) if x),
                KAYNAK_ETIKET.get(o.get("kaynak"), o.get("kaynak") or ""), durum,
            )
            self._odeme_ham.append({"iid": o["belge_no"], "values": values})
        self._odeme_filtre_yenile()
        self._detay_filtre.clear()
        self._detay_ham.clear()
        for s in self.detay.get("detay_satirlari") or []:
            values = (
                _tarih(s.get("islem_tarihi")),
                s.get("aciklama") or "",
                s.get("islem_turu") or "",
                s.get("tek_cekim_taksit") or "",
                _para(s.get("borc")),
                _para(s.get("alacak")),
                _para(s.get("etki")),
                s.get("kaynak_evrak") or "",
                s.get("kaynak_gider") or "",
            )
            self._detay_ham.append({"values": values})
        self._detay_filtre_yenile()

    def _yenile_detay(self):
        from database.kredi_karti_ekstre_service import KrediKartiEkstreService

        try:
            self.detay = KrediKartiEkstreService.ekstre_detay(int(self.detay["ekstre_id"]))
            self._doldur()
            if self.yenile_cb:
                self.yenile_cb()
        except Exception as exc:
            messagebox.showerror("Ekstre", str(exc), parent=self)

    def _odeme_iptal(self):
        from tkinter import simpledialog

        from database.kredi_karti_ekstre_service import KrediKartiEkstreService

        secim = self.tv_odeme.selection()
        if not secim:
            messagebox.showinfo("Ödeme iptali", "İptal edilecek ödemeyi listeden seçin.", parent=self)
            return
        odeme = next((o for o in self.detay.get("odemeler") or [] if o["belge_no"] == secim[0]), None)
        if odeme is None or odeme.get("iptal"):
            messagebox.showinfo("Ödeme iptali", "Seçilen ödeme zaten iptal edilmiş.", parent=self)
            return
        neden = simpledialog.askstring(
            "Ödeme iptali",
            f"{odeme['belge_no']} — {_para(odeme['tutar'])}\nÖdeme silinmez; bugün tarihli ters kayıt yazılır "
            "(ödeme hesabına iade, kart borcu geri gelir).\n\nİptal nedeni:", parent=self)
        if neden is None:
            return
        if not neden.strip():
            messagebox.showerror("Ödeme iptali", "İptal nedeni yazın.", parent=self)
            return
        try:
            KrediKartiEkstreService.odeme_iptal(odeme["belge_no"], neden.strip())
        except Exception as exc:
            messagebox.showerror("Ödeme iptali", str(exc), parent=self)
            return
        self._sonra_yenile()

    def _odeme(self):
        KkEkstreOdemeDialog(
            self, self.detay, tamami=False, yenile_cb=self._sonra_yenile
        )

    def _kismi(self):
        self._odeme()

    def _tamami(self):
        KkEkstreOdemeDialog(
            self, self.detay, tamami=True, yenile_cb=self._sonra_yenile
        )

    def _sonra_yenile(self):
        self._yenile_detay()


class KkEkstreOdemeDialog(tk.Toplevel):
    """Ekstre ödeme — Ekstrenin Tamamı / Asgari / Diğer Tutar."""

    def __init__(self, parent, detay: dict, *, tamami: bool = False, yenile_cb=None):
        super().__init__(parent)
        import uuid

        self.detay = detay
        self.tamami = tamami
        self.yenile_cb = yenile_cb
        self.istek_anahtari = uuid.uuid4().hex
        self.title("Ekstre Ödeme")
        self.geometry("520x520")
        self.transient(parent)
        try:
            self.grab_set()
        except tk.TclError:
            pass

        self._kalan = Decimal(str(detay.get("kalan") or 0))
        oz = detay.get("kart_ozeti") or {}
        self._toplam_borc = Decimal(str(oz.get("toplam_borc") or detay.get("toplam_borc") or 0))
        asgari_ham = detay.get("asgari_tutar")
        asgari_odenen = Decimal(str(detay.get("asgari_odenen") or 0))
        if asgari_ham is None and oz.get("asgari_tutar") is not None:
            asgari_ham = oz.get("asgari_tutar")
        self._asgari_biliniyor = asgari_ham is not None and str(asgari_ham).strip() != ""
        self._asgari_kalan = Decimal("0")
        if self._asgari_biliniyor:
            self._asgari_kalan = max(
                Decimal(str(asgari_ham)) - asgari_odenen, Decimal("0")
            ).quantize(Decimal("0.01"))

        ttk.Label(self, text=detay.get("aciklama") or "", wraplength=480, font=("Segoe UI", 10, "bold")).pack(
            anchor="w", padx=12, pady=(10, 4)
        )
        ttk.Label(self, text=f"Bu ekstrede kalan: {_para(self._kalan)}", font=("Segoe UI", 10, "bold")).pack(
            anchor="w", padx=12
        )
        ttk.Label(self, text=f"Toplam kart borcu: {_para(self._toplam_borc)}", font=("Segoe UI", 10, "bold")).pack(
            anchor="w", padx=12
        )
        if self._asgari_biliniyor:
            ttk.Label(
                self,
                text=f"Asgari kalan: {_para(self._asgari_kalan)}",
                font=("Segoe UI", 10, "bold"),
            ).pack(anchor="w", padx=12)
        else:
            ttk.Label(
                self,
                text="Asgari tutar bilinmiyor — Asgari seçeneği pasif (ekstre aktarımı veya manuel giriş gerekir).",
                foreground="#a40",
                wraplength=480,
                font=("Segoe UI", 9, "bold"),
            ).pack(anchor="w", padx=12, pady=(2, 0))

        secenek = ttk.LabelFrame(self, text="Ödeme seçeneği", padding=8)
        secenek.pack(fill="x", padx=12, pady=(8, 4))
        self._sekil = tk.StringVar(value="TAMAMI" if tamami else "DIGER")
        ttk.Radiobutton(
            secenek,
            text="Ekstrenin Tamamı",
            variable=self._sekil,
            value="TAMAMI",
            command=self._sekil_degisti,
        ).pack(anchor="w")
        asgari_rb = ttk.Radiobutton(
            secenek,
            text="Asgari Tutar",
            variable=self._sekil,
            value="ASGARI",
            command=self._sekil_degisti,
        )
        asgari_rb.pack(anchor="w")
        if not self._asgari_biliniyor or self._asgari_kalan <= 0:
            asgari_rb.state(["disabled"])
        ttk.Radiobutton(
            secenek,
            text="Diğer Tutar",
            variable=self._sekil,
            value="DIGER",
            command=self._sekil_degisti,
        ).pack(anchor="w")

        self._onizleme = ttk.Label(self, text="", wraplength=480, font=("Segoe UI", 9, "bold"))
        self._onizleme.pack(anchor="w", padx=12, pady=(4, 0))

        frm = ttk.Frame(self)
        frm.pack(fill="x", padx=12, pady=8)
        ttk.Label(frm, text="Ödeme tarihi", font=("Segoe UI", 10, "bold")).grid(
            row=0, column=0, sticky="w", pady=3
        )
        self.tarih = ttk.Entry(frm, width=14, font=("Segoe UI", 10, "bold"))
        self.tarih.insert(0, date.today().strftime("%d.%m.%Y"))
        self.tarih.grid(row=0, column=1, sticky="w", pady=3)

        ttk.Label(frm, text="Ödenecek tutar", font=("Segoe UI", 10, "bold")).grid(
            row=1, column=0, sticky="w", pady=3
        )
        self.tutar = ttk.Entry(frm, width=14, font=("Segoe UI", 10, "bold"))
        self.tutar.grid(row=1, column=1, sticky="w", pady=3)
        self.tutar.bind("<KeyRelease>", lambda _e: self._onizleme_guncelle())

        ttk.Label(frm, text="Ödeme hesabı", font=("Segoe UI", 10, "bold")).grid(
            row=2, column=0, sticky="w", pady=3
        )
        self._hesaplar = _odeme_hesaplari()
        self.hesap = ttk.Combobox(frm, values=[h[1] for h in self._hesaplar], state="readonly", width=34)
        self.hesap.grid(row=2, column=1, sticky="w", pady=3)
        varsayilan = _varsayilan_hesap(detay.get("kredi_karti_id"), self._hesaplar)
        if varsayilan is not None:
            self.hesap.current(varsayilan)

        ttk.Label(frm, text="Dekont no", font=("Segoe UI", 10, "bold")).grid(
            row=3, column=0, sticky="w", pady=3
        )
        self.dekont = ttk.Entry(frm, width=20, font=("Segoe UI", 10, "bold"))
        self.dekont.grid(row=3, column=1, sticky="w", pady=3)

        ttk.Label(frm, text="Açıklama", font=("Segoe UI", 10, "bold")).grid(
            row=4, column=0, sticky="w", pady=3
        )
        self.aciklama = ttk.Entry(frm, width=32, font=("Segoe UI", 10, "bold"))
        self.aciklama.grid(row=4, column=1, sticky="w", pady=3)

        btns = ttk.Frame(self)
        btns.pack(fill="x", padx=12, pady=12)
        ttk.Button(btns, text="Vazgeç", command=self.destroy).pack(side="right", padx=4)
        kaydet = ttk.Button(btns, text="Öde ve Kaydet", command=self._kaydet)
        kaydet.pack(side="right", padx=4)
        from database.access import yetki_var

        if not yetki_var("finans_duzenleme"):
            kaydet.configure(state="disabled")
            ttk.Label(self, text="Ödeme kaydetme yetkiniz yok.", foreground="#b03a2e").pack(
                anchor="w", padx=12
            )

        self._sekil_degisti()

    def _sekil_degisti(self):
        sekil = self._sekil.get()
        self.tutar.configure(state="normal")
        self.tutar.delete(0, "end")
        if sekil == "TAMAMI":
            self.tutar.insert(0, f"{self._kalan:.2f}".replace(".", ","))
            self.tutar.configure(state="readonly")
            self.tamami = True
        elif sekil == "ASGARI":
            self.tutar.insert(0, f"{self._asgari_kalan:.2f}".replace(".", ","))
            self.tutar.configure(state="readonly")
            self.tamami = False
        else:
            self.tutar.insert(0, f"{self._kalan:.2f}".replace(".", ","))
            self.tamami = False
        self._onizleme_guncelle()

    def _onizleme_guncelle(self):
        try:
            tutar = tutar_coz(self.tutar.get())
        except Exception:
            self._onizleme.configure(text="")
            return
        ekstre_sonra = max(self._kalan - tutar, Decimal("0"))
        asgari_sonra = None
        if self._asgari_biliniyor:
            asgari_sonra = max(self._asgari_kalan - tutar, Decimal("0"))
        borc_sonra = max(self._toplam_borc - tutar, Decimal("0"))
        uyari = ""
        if self._asgari_biliniyor and tutar < self._asgari_kalan and tutar > 0:
            uyari = " · Asgari ödeme altında"
        elif tutar > self._kalan:
            uyari = " · Ekstre kalanını aşıyor (fazla dağıtılmamış sayılabilir)"
        metin = (
            f"Ödeme sonrası — ekstre kalan: {_para(ekstre_sonra)}"
            + (f" · asgari kalan: {_para(asgari_sonra)}" if asgari_sonra is not None else "")
            + f" · net kart borcu: {_para(borc_sonra)}{uyari}"
        )
        self._onizleme.configure(text=metin)

    def _kaydet(self):
        from database.kredi_karti_ekstre_service import KrediKartiEkstreService

        try:
            t_raw = self.tarih.get().strip()
            gun, ay, yil = t_raw.replace("/", ".").split(".")
            tarih = date(int(yil), int(ay), int(gun))
        except Exception:
            messagebox.showerror("Tarih", "Tarih GG.AA.YYYY formatında olmalıdır.", parent=self)
            return
        try:
            tutar = tutar_coz(self.tutar.get())
        except ValueError as exc:
            messagebox.showerror("Tutar", str(exc), parent=self)
            return
        secili = self.hesap.current()
        if secili < 0:
            messagebox.showerror("Ödeme hesabı", "Ödemenin yapılacağı kasa veya banka hesabını seçin.", parent=self)
            return
        try:
            sonuc = KrediKartiEkstreService.odeme_yap(
                ekstre_id=int(self.detay["ekstre_id"]),
                tutar=tutar,
                finans_hesap_id=self._hesaplar[secili][0],
                tarih=tarih,
                dekont_no=self.dekont.get(),
                aciklama=self.aciklama.get(),
                tamami=self.tamami,
                istek_anahtari=self.istek_anahtari,
            )
            messagebox.showinfo(
                "Ödeme",
                ("Bu ödeme zaten kaydedilmişti: " if sonuc.get("mevcut") else "Ödeme kaydedildi: ")
                + f"{sonuc['belge_no']}\nTutar: {_para(sonuc['tutar'])}",
                parent=self,
            )
            if self.yenile_cb:
                self.yenile_cb()
            self.destroy()
        except Exception as exc:
            messagebox.showerror("Ödeme", str(exc), parent=self)
