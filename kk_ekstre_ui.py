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
KAYNAK_ETIKET = {
    "EKSTRE": "Ekstre ödemesi",
    "KASADAN_BANKAYA": "Kasadan yatırma",
    "VIRMAN": "Banka virmanı",
    "BANKAMATIK": "Bankamatikten nakit",
}


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


def _odeme_hesaplari(*, yontem: str = "BANKA") -> list[tuple[int, str, int | None, str]]:
    """(hesap_id, etiket, banka_karti_id, banka_adi) — düz Python değerleri.

    BANKA → yalnız MEVDUAT/KMH/VADELI; BANKAMATIK → yalnız KASA.
    ``banka_karti`` ilişkisi oturum açıkken eager yüklenir; UI oturum kapandıktan
    sonra ORM lazy-load yapmaz (DetachedInstanceError önlenir).
    """
    from sqlalchemy import select
    from sqlalchemy.orm import selectinload

    from database.database import get_session
    from database.hesap_siralama import hesaplari_sirala
    from database.models.finans import FinansHesabi

    yontem = (yontem or "BANKA").upper()
    ham: list[dict] = []
    with get_session() as session:
        hesaplar = list(
            session.scalars(
                select(FinansHesabi)
                .where(FinansHesabi.aktif.is_(True))
                .options(selectinload(FinansHesabi.banka_karti))
                .order_by(FinansHesabi.id)
            ).all()
        )
        for h in hesaplar:
            tur = (h.hesap_turu or "").upper()
            alt = (h.alt_hesap_turu or "").upper()
            banka_id = int(h.banka_karti_id) if h.banka_karti_id else None
            banka_adi = ""
            bk = h.banka_karti  # session açık — selectinload
            if bk is not None:
                banka_adi = (getattr(bk, "banka_adi", None) or getattr(bk, "kart_adi", None) or "") or ""
            if not banka_adi and tur == "BANKA":
                banka_adi = (h.hesap_adi or "").split(" ")[0]
            hesap_adi = h.hesap_adi or ""
            if yontem == "BANKAMATIK":
                if tur == "KASA":
                    ham.append(
                        {
                            "id": int(h.id),
                            "hesap_adi": hesap_adi,
                            "alt_hesap_turu": "KASA",
                            "hesap_turu": "KASA",
                            "banka_id": None,
                            "banka_adi": "Kasa",
                            "etiket": hesap_adi,
                        }
                    )
            else:
                if tur == "BANKA" and alt in ("MEVDUAT", "KMH", "VADELI"):
                    etiket = f"{banka_adi} · {hesap_adi}" if banka_adi else hesap_adi
                    ham.append(
                        {
                            "id": int(h.id),
                            "hesap_adi": hesap_adi,
                            "alt_hesap_turu": alt,
                            "hesap_turu": tur,
                            "banka_id": banka_id,
                            "banka_adi": banka_adi or "",
                            "etiket": etiket,
                        }
                    )
    return [
        (int(r["id"]), r["etiket"], r["banka_id"], r["banka_adi"])
        for r in hesaplari_sirala(ham)
    ]


def _varsayilan_hesap(kredi_karti_id, hesaplar: list) -> int | None:
    """Kartın bankasındaki vadesiz hesap (zorunlu varsayılan değil; yardımcı seçim)."""
    if not kredi_karti_id or not hesaplar:
        return None
    from database.database import get_session
    from database.models.finans import FinansHesabi, KrediKartiTanimi

    with get_session() as s:
        kart = s.get(KrediKartiTanimi, int(kredi_karti_id))
        if kart is None:
            return None
        for i, row in enumerate(hesaplar):
            hid = row[0]
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
            from ui_pencere import pencere_os_krom_ac

            pencere_os_krom_ac(self)
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
        ttk.Button(btn, text="PDF Kaydet", command=self._pdf_kaydet).pack(side="left", padx=2)
        ttk.Button(btn, text="Excel Kaydet", command=self._excel_kaydet).pack(side="left", padx=2)
        ttk.Button(btn, text="Yenile", command=self._yenile_detay).pack(side="left", padx=2)
        ttk.Button(btn, text="Kapat", command=self.destroy).pack(side="right", padx=2)

        cols = ("tarih", "aciklama", "tur", "taksit", "borc", "alacak", "belge", "kaynak")
        self.tv = ttk.Treeview(self, columns=cols, show="headings", height=10)
        basliklar = (
            ("tarih", "İşlem tarihi", 90),
            ("aciklama", "Açıklama", 200),
            ("tur", "Tür", 90),
            ("taksit", "Taksit", 90),
            ("borc", "Borç", 90),
            ("alacak", "Alacak", 90),
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

        cols = ("tarih", "aciklama", "tur", "taksit", "borc", "alacak", "belge", "kaynak")
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

    def _pdf_kaydet(self):
        from tkinter import filedialog
        from database.kk_ekstre_rapor_service import pdf_kaydet, rapor_verisi

        try:
            kid = int(self.detay.get("kredi_karti_id") or 0)
            if not kid:
                from database.database import get_session
                from database.models.finans import KrediKartiEkstre

                with get_session() as s:
                    e = s.get(KrediKartiEkstre, int(self.detay["ekstre_id"]))
                    kid = int(e.kredi_karti_id) if e else 0
            rapor = rapor_verisi(kid, ekstre_id=int(self.detay["ekstre_id"]))
            yol = filedialog.asksaveasfilename(
                parent=self,
                defaultextension=".pdf",
                initialfile=f"{rapor['dosya_kok']}.pdf",
                filetypes=[("PDF", "*.pdf")],
            )
            if not yol:
                return
            pdf_kaydet(rapor, yol)
            messagebox.showinfo("PDF", f"Kaydedildi:\n{yol}", parent=self)
        except Exception as exc:
            messagebox.showerror("PDF", str(exc), parent=self)

    def _excel_kaydet(self):
        from tkinter import filedialog
        from database.kk_ekstre_rapor_service import excel_kaydet, rapor_verisi

        try:
            kid = int(self.detay.get("kredi_karti_id") or 0)
            if not kid:
                from database.database import get_session
                from database.models.finans import KrediKartiEkstre

                with get_session() as s:
                    e = s.get(KrediKartiEkstre, int(self.detay["ekstre_id"]))
                    kid = int(e.kredi_karti_id) if e else 0
            rapor = rapor_verisi(kid, ekstre_id=int(self.detay["ekstre_id"]))
            yol = filedialog.asksaveasfilename(
                parent=self,
                defaultextension=".xlsx",
                initialfile=f"{rapor['dosya_kok']}.xlsx",
                filetypes=[("Excel", "*.xlsx")],
            )
            if not yol:
                return
            excel_kaydet(rapor, yol)
            messagebox.showinfo("Excel", f"Kaydedildi:\n{yol}", parent=self)
        except Exception as exc:
            messagebox.showerror("Excel", str(exc), parent=self)

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
    """Kredi Kartı Ekstre Ödeme Evrakı — Banka hesabı / Bankamatik nakit, serbest tutar (V6)."""

    def __init__(self, parent, detay: dict, *, tamami: bool = False, yenile_cb=None):
        super().__init__(parent)
        import uuid

        self.detay = detay
        self.tamami = False  # V6: tutar her zaman serbest; yardımcılar yalnız doldurur
        self.yenile_cb = yenile_cb
        self.istek_anahtari = uuid.uuid4().hex
        self.title("Kredi Kartı Ekstre Ödeme Evrakı")
        self.geometry("580x640")
        self.transient(parent)
        try:
            self.grab_set()
            from ui_pencere import pencere_os_krom_ac

            pencere_os_krom_ac(self)
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

        ttk.Label(
            self,
            text=detay.get("aciklama") or detay.get("kart_adi") or "Ekstre ödemesi",
            wraplength=540,
            font=("Segoe UI", 10, "bold"),
        ).pack(anchor="w", padx=12, pady=(10, 4))
        ttk.Label(self, text=f"Bu ekstrede kalan: {_para(self._kalan)}", font=("Segoe UI", 10, "bold")).pack(
            anchor="w", padx=12
        )
        ttk.Label(self, text=f"Toplam kart borcu: {_para(self._toplam_borc)}", font=("Segoe UI", 10, "bold")).pack(
            anchor="w", padx=12
        )
        if self._asgari_biliniyor:
            ttk.Label(
                self,
                text=f"Asgari kalan (bilgi): {_para(self._asgari_kalan)}",
                font=("Segoe UI", 10, "bold"),
            ).pack(anchor="w", padx=12)
        else:
            ttk.Label(
                self,
                text="Asgari tutar bilinmiyor (bilgi amaçlı). Ödeme tutarı serbest girilir.",
                foreground="#a40",
                wraplength=540,
                font=("Segoe UI", 9, "bold"),
            ).pack(anchor="w", padx=12, pady=(2, 0))

        yontem_fr = ttk.LabelFrame(self, text="Ödeme yöntemi", padding=8)
        yontem_fr.pack(fill="x", padx=12, pady=(8, 4))
        self._yontem = tk.StringVar(value="BANKA")
        ttk.Radiobutton(
            yontem_fr,
            text="Banka Hesabından Ödeme",
            variable=self._yontem,
            value="BANKA",
            command=self._yontem_degisti,
        ).pack(anchor="w")
        ttk.Radiobutton(
            yontem_fr,
            text="Bankamatikten Nakit Yatırma",
            variable=self._yontem,
            value="BANKAMATIK",
            command=self._yontem_degisti,
        ).pack(anchor="w")

        yardim = ttk.LabelFrame(self, text="Tutar yardımcısı (serbest değiştirilebilir)", padding=8)
        yardim.pack(fill="x", padx=12, pady=(4, 4))
        self._sekil = tk.StringVar(value="TAMAMI" if tamami else "DIGER")
        ttk.Radiobutton(
            yardim, text="Ekstre kalanını getir", variable=self._sekil, value="TAMAMI",
            command=self._sekil_degisti,
        ).pack(anchor="w")
        asgari_rb = ttk.Radiobutton(
            yardim, text="Asgari kalanı getir", variable=self._sekil, value="ASGARI",
            command=self._sekil_degisti,
        )
        asgari_rb.pack(anchor="w")
        if not self._asgari_biliniyor or self._asgari_kalan <= 0:
            asgari_rb.state(["disabled"])
        ttk.Radiobutton(
            yardim, text="Elle tutar", variable=self._sekil, value="DIGER",
            command=self._sekil_degisti,
        ).pack(anchor="w")

        self._onizleme = ttk.Label(self, text="", wraplength=540, font=("Segoe UI", 9, "bold"))
        self._onizleme.pack(anchor="w", padx=12, pady=(4, 0))

        frm = ttk.Frame(self)
        frm.pack(fill="x", padx=12, pady=8)
        ttk.Label(frm, text="Ödeme tarihi", font=("Segoe UI", 10, "bold")).grid(
            row=0, column=0, sticky="w", pady=3
        )
        self.tarih = ttk.Entry(frm, width=14, font=("Segoe UI", 10, "bold"))
        self.tarih.insert(0, date.today().strftime("%d.%m.%Y"))
        self.tarih.grid(row=0, column=1, sticky="w", pady=3)

        ttk.Label(frm, text="Ödeme tutarı (serbest)", font=("Segoe UI", 10, "bold")).grid(
            row=1, column=0, sticky="w", pady=3
        )
        self.tutar = ttk.Entry(frm, width=14, font=("Segoe UI", 10, "bold"))
        self.tutar.grid(row=1, column=1, sticky="w", pady=3)
        self.tutar.bind("<KeyRelease>", lambda _e: self._onizleme_guncelle())

        self._kaynak_etiket = ttk.Label(frm, text="Ödemenin çıkacağı hesap", font=("Segoe UI", 10, "bold"))
        self._kaynak_etiket.grid(row=2, column=0, sticky="w", pady=3)
        self.hesap = ttk.Combobox(frm, state="readonly", width=40)
        self.hesap.grid(row=2, column=1, sticky="w", pady=3)

        ttk.Label(frm, text="ATM bankası (isteğe bağlı)", font=("Segoe UI", 10, "bold")).grid(
            row=3, column=0, sticky="w", pady=3
        )
        self.atm_bankasi = ttk.Entry(frm, width=28, font=("Segoe UI", 10, "bold"))
        self.atm_bankasi.grid(row=3, column=1, sticky="w", pady=3)

        ttk.Label(frm, text="Dekont / ATM ref.", font=("Segoe UI", 10, "bold")).grid(
            row=4, column=0, sticky="w", pady=3
        )
        self.dekont = ttk.Entry(frm, width=28, font=("Segoe UI", 10, "bold"))
        self.dekont.grid(row=4, column=1, sticky="w", pady=3)

        ttk.Label(frm, text="Açıklama", font=("Segoe UI", 10, "bold")).grid(
            row=5, column=0, sticky="w", pady=3
        )
        self.aciklama = ttk.Entry(frm, width=40, font=("Segoe UI", 10, "bold"))
        self.aciklama.grid(row=5, column=1, sticky="w", pady=3)

        btns = ttk.Frame(self)
        btns.pack(fill="x", padx=12, pady=12)
        ttk.Button(btns, text="Vazgeç", command=self.destroy).pack(side="right", padx=4)
        kaydet = ttk.Button(btns, text="Muhasebeleştir / Kaydet", command=self._kaydet)
        kaydet.pack(side="right", padx=4)
        from database.access import yetki_var

        if not yetki_var("finans_duzenleme"):
            kaydet.configure(state="disabled")
            ttk.Label(self, text="Ödeme kaydetme yetkiniz yok.", foreground="#b03a2e").pack(
                anchor="w", padx=12
            )

        self._hesaplar: list = []
        self._yontem_degisti()
        self._sekil_degisti()

    def _yontem_degisti(self):
        yontem = self._yontem.get()
        self._hesaplar = _odeme_hesaplari(yontem=yontem)
        self.hesap.configure(values=[h[1] for h in self._hesaplar])
        self.hesap.set("")
        if yontem == "BANKAMATIK":
            self._kaynak_etiket.configure(text="Çıkış kasası / nakit kaynağı")
            if self._hesaplar:
                self.hesap.current(0)
        else:
            self._kaynak_etiket.configure(text="Ödemenin çıkacağı banka hesabı")
            varsayilan = _varsayilan_hesap(self.detay.get("kredi_karti_id"), self._hesaplar)
            if varsayilan is not None:
                self.hesap.current(varsayilan)
            elif self._hesaplar:
                self.hesap.current(0)
        self._onizleme_guncelle()

    def _sekil_degisti(self):
        """Yardımcı tutar doldurur; alan her zaman yazılabilir kalır (V6 serbest tutar)."""
        sekil = self._sekil.get()
        self.tutar.configure(state="normal")
        self.tutar.delete(0, "end")
        if sekil == "TAMAMI":
            self.tutar.insert(0, f"{self._kalan:.2f}".replace(".", ","))
        elif sekil == "ASGARI":
            self.tutar.insert(0, f"{self._asgari_kalan:.2f}".replace(".", ","))
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
        fazla = max(tutar - self._kalan, Decimal("0"))
        asgari_sonra = None
        if self._asgari_biliniyor:
            asgari_sonra = max(self._asgari_kalan - tutar, Decimal("0"))
        borc_sonra = max(self._toplam_borc - tutar, Decimal("0"))
        uyari = ""
        if self._asgari_biliniyor and tutar < self._asgari_kalan and tutar > 0:
            uyari = " · Asgari altında (kayıt engellenmez)"
        elif fazla > 0:
            uyari = f" · Fazla ödeme / kart alacağı: {_para(fazla)}"
        yontem = "ATM nakit" if self._yontem.get() == "BANKAMATIK" else "Banka hesabı"
        metin = (
            f"{yontem} · Ödeme sonrası — ekstre kalan: {_para(ekstre_sonra)}"
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
        if secili < 0 or not self._hesaplar:
            messagebox.showerror(
                "Kaynak",
                "Ödemenin çıkacağı hesabı / kasayı seçin.",
                parent=self,
            )
            return
        yontem = self._yontem.get()
        try:
            sonuc = KrediKartiEkstreService.odeme_yap(
                ekstre_id=int(self.detay["ekstre_id"]),
                tutar=tutar,
                finans_hesap_id=self._hesaplar[secili][0],
                tarih=tarih,
                dekont_no=self.dekont.get(),
                aciklama=self.aciklama.get(),
                tamami=False,
                istek_anahtari=self.istek_anahtari,
                odeme_yontemi=yontem,
                kaynak="BANKAMATIK" if yontem == "BANKAMATIK" else "EKSTRE",
                atm_bankasi=self.atm_bankasi.get() if yontem == "BANKAMATIK" else None,
                atm_referans=self.dekont.get() if yontem == "BANKAMATIK" else None,
            )
            fazla = sonuc.get("fazla_odeme") or Decimal("0")
            ekstra = f"\nFazla / kart alacağı: {_para(fazla)}" if Decimal(str(fazla)) > 0 else ""
            messagebox.showinfo(
                "Ödeme",
                ("Bu ödeme zaten kaydedilmişti: " if sonuc.get("mevcut") else "Ödeme muhasebeleştirildi: ")
                + f"{sonuc['belge_no']}\nTutar: {_para(sonuc['tutar'])}"
                + f"\nYöntem: {sonuc.get('odeme_yontemi') or yontem}{ekstra}",
                parent=self,
            )
            if self.yenile_cb:
                self.yenile_cb()
            self.destroy()
        except Exception as exc:
            messagebox.showerror("Ödeme", str(exc), parent=self)


class KkDonemBorcuRaporDialog(tk.Toplevel):
    """Ekstre / Dönem Borcu Raporu — ekstre dönemi veya iki tarih arası; salt okunur."""

    MOD_EKSTRE = "ekstre"
    MOD_TARIH = "tarih_araligi"

    def __init__(self, parent, kredi_karti_id: int, *, yenile_cb=None):
        super().__init__(parent)
        self.kredi_karti_id = int(kredi_karti_id)
        self.yenile_cb = yenile_cb
        self.title("Ekstre / Dönem Borcu Raporu")
        self.geometry("1280x820")
        self.minsize(1100, 700)
        self.resizable(True, True)
        self.transient(parent)
        try:
            self.grab_set()
            from ui_pencere import pencere_os_krom_ac
            pencere_os_krom_ac(self)
        except tk.TclError:
            pass

        from database.kredi_karti_ekstre_service import KrediKartiEkstreService
        from database.kk_ekstre_rapor_service import rapor_verisi

        self._svc = KrediKartiEkstreService
        self._rapor_verisi = rapor_verisi
        self._donemler = self._svc.ekstreleri_hesapla(
            kredi_karti_id=self.kredi_karti_id, odenenleri_dahil=True
        )
        # Son kesilen + kesilmemiş ayırt
        bugun = date.today()
        self._idx = 0
        for i, d in enumerate(self._donemler):
            if d.get("kesim_tarihi") and d["kesim_tarihi"] <= bugun:
                self._idx = i
        if not self._donemler:
            # Kesim günü yoksa bile özet göster
            self._donemler = [{"kesim_tarihi": None, "ekstre_id": None, "kesin": False}]

        self._rapor = None
        self._har_belge: dict[str, str] = {}
        self._odeme_belge: dict[str, str] = {}
        self.var_mod = tk.StringVar(value=self.MOD_EKSTRE)

        # --- Başlık / özet
        ust = ttk.Frame(self, padding=8)
        ust.pack(fill="x")
        self.lbl_baslik = ttk.Label(ust, font=("Segoe UI", 11, "bold"))
        self.lbl_baslik.pack(anchor="w")
        self.lbl_donem = ttk.Label(ust)
        self.lbl_donem.pack(anchor="w", pady=(2, 0))

        ozet = ttk.LabelFrame(ust, text="Özet", padding=6)
        ozet.pack(fill="x", pady=(6, 0))
        self._ozet_lbl: dict[str, ttk.Label] = {}
        alanlar = (
            ("kesim_tutari", "Kesim tutarı"),
            ("onceki_devir", "Önceki dönemden devir"),
            ("odenen", "Ödenen"),
            ("kalan", "Kalan"),
            ("kullanilan_limit", "Kullanılan limit"),
            ("hesap_bakiyesi", "Hesap bakiyesi"),
            ("gelecek_kalan", "Gelecek dönem kalan"),
        )
        for i, (anahtar, baslik) in enumerate(alanlar):
            kutu = ttk.Frame(ozet)
            kutu.grid(row=0, column=i, padx=10, sticky="w")
            ttk.Label(kutu, text=baslik, foreground="#555555").pack(anchor="w")
            lbl = ttk.Label(kutu, text="—", font=("Segoe UI", 10, "bold"))
            lbl.pack(anchor="w")
            self._ozet_lbl[anahtar] = lbl
        self.lbl_kapsam = ttk.Label(ust, foreground="#1a2b4a", wraplength=1200, justify="left")
        self.lbl_kapsam.pack(anchor="w", pady=(6, 0))
        self.bind("<Configure>", self._kapsam_wrap, add="+")

        # --- Mod / tarih / navigasyon
        mod_f = ttk.Frame(self, padding=(8, 2))
        mod_f.pack(fill="x")
        ttk.Radiobutton(
            mod_f, text="Ekstre dönemi", value=self.MOD_EKSTRE,
            variable=self.var_mod, command=self._mod_degisti,
        ).pack(side="left", padx=(0, 8))
        ttk.Radiobutton(
            mod_f, text="İki tarih arası", value=self.MOD_TARIH,
            variable=self.var_mod, command=self._mod_degisti,
        ).pack(side="left", padx=(0, 8))
        ttk.Label(mod_f, text="Başlangıç:").pack(side="left", padx=(12, 2))
        self.ent_bas = ttk.Entry(mod_f, width=11)
        self.ent_bas.pack(side="left")
        ttk.Label(mod_f, text="Bitiş:").pack(side="left", padx=(8, 2))
        self.ent_bit = ttk.Entry(mod_f, width=11)
        self.ent_bit.pack(side="left")
        try:
            from ui_takvim import takvim_butonu

            takvim_butonu(mod_f, self.ent_bas)
            takvim_butonu(mod_f, self.ent_bit)
        except Exception:
            pass
        self.btn_uygula = ttk.Button(mod_f, text="Uygula", command=self._uygula)
        self.btn_uygula.pack(side="left", padx=(8, 2))
        self.btn_temizle = ttk.Button(mod_f, text="Temizle", command=self._temizle)
        self.btn_temizle.pack(side="left", padx=2)

        nav = ttk.Frame(self, padding=(8, 2))
        nav.pack(fill="x")
        self.btn_onceki = ttk.Button(nav, text="◀ Önceki dönem", command=self._onceki)
        self.btn_onceki.pack(side="left", padx=2)
        self.btn_sonraki = ttk.Button(nav, text="Sonraki dönem ▶", command=self._sonraki)
        self.btn_sonraki.pack(side="left", padx=2)
        ttk.Button(nav, text="PDF", command=self._pdf).pack(side="left", padx=8)
        ttk.Button(nav, text="Excel", command=self._excel).pack(side="left", padx=2)
        ttk.Button(nav, text="Yenile", command=self._yenile).pack(side="left", padx=8)
        ttk.Button(nav, text="Kapat", command=self.destroy).pack(side="right", padx=2)

        # --- Tablolar
        orta = ttk.Panedwindow(self, orient="vertical")
        orta.pack(fill="both", expand=True, padx=8, pady=6)

        har_f = ttk.LabelFrame(orta, text="Dönem kalemleri — çift tık belge", padding=4)
        self.tv = self._tablo_olustur(
            har_f,
            (
                ("kaynak_tarihi", "Kaynak tarihi", 95, "center"),
                ("yansima", "Yansıma", 95, "center"),
                ("vade", "Vade", 95, "center"),
                ("belge", "Belge", 130, "w"),
                ("aciklama", "Açıklama", 260, "w"),
                ("taksit", "Taksit", 65, "center"),
                ("ekstre_kesim", "Ekstre kesim", 95, "center"),
                ("son_odeme", "Son ödeme", 95, "center"),
                ("borc", "Borç", 100, "e"),
                ("odeme", "Ödeme / iade", 100, "e"),
                ("bakiye", "Bakiye", 105, "e"),
            ),
            height=11,
        )
        self.tv.bind("<Double-1>", lambda _e: self._belge_ac(self.tv, self._har_belge))
        orta.add(har_f, weight=4)

        odeme_f = ttk.LabelFrame(orta, text="Ödemeler / mahsup — çift tık belge", padding=4)
        self.tv_odeme = self._tablo_olustur(
            odeme_f,
            (
                ("tarih", "Tarih", 95, "center"),
                ("belge", "Belge", 130, "w"),
                ("tutar", "Tutar", 105, "e"),
                ("mahsup", "Mahsup", 105, "e"),
                ("ekstre_kesim", "Ekstre kesim", 100, "center"),
                ("kaynak", "Kaynak", 130, "w"),
                ("aciklama", "Açıklama", 360, "w"),
            ),
            height=5,
        )
        self.tv_odeme.bind(
            "<Double-1>", lambda _e: self._belge_ac(self.tv_odeme, self._odeme_belge)
        )
        orta.add(odeme_f, weight=2)

        dag_f = ttk.LabelFrame(orta, text="Dönemlere göre borç dağılımı", padding=4)
        self.tv_dag = self._tablo_olustur(
            dag_f,
            (
                ("kesim", "Kesim", 95, "center"),
                ("bas", "Dönem başı", 95, "center"),
                ("bitis", "Dönem sonu", 95, "center"),
                ("son", "Son ödeme", 95, "center"),
                ("adet", "Adet", 60, "center"),
                ("kesim_tutari", "Kesim tutarı", 115, "e"),
                ("odenen", "Ödenen", 110, "e"),
                ("kalan", "Kalan", 110, "e"),
                ("durum", "Durum", 150, "w"),
            ),
            height=6,
        )
        orta.add(dag_f, weight=3)

        self._mod_ui_guncelle()
        self._yenile()

    # ------------------------------------------------------------------ yardımcılar
    @staticmethod
    def _tablo_olustur(parent, kolonlar, *, height: int) -> ttk.Treeview:
        cerceve = ttk.Frame(parent)
        cerceve.pack(fill="both", expand=True)
        tv = ttk.Treeview(
            cerceve,
            columns=tuple(k for k, _b, _w, _a in kolonlar),
            show="headings",
            height=height,
        )
        for k, b, w, a in kolonlar:
            tv.heading(k, text=b)
            tv.column(k, width=w, anchor=a, stretch=True)
        yscroll = ttk.Scrollbar(cerceve, orient="vertical", command=tv.yview)
        xscroll = ttk.Scrollbar(cerceve, orient="horizontal", command=tv.xview)
        tv.configure(yscrollcommand=yscroll.set, xscrollcommand=xscroll.set)
        tv.grid(row=0, column=0, sticky="nsew")
        yscroll.grid(row=0, column=1, sticky="ns")
        xscroll.grid(row=1, column=0, sticky="ew")
        cerceve.rowconfigure(0, weight=1)
        cerceve.columnconfigure(0, weight=1)
        return tv

    def _kapsam_wrap(self, event=None):
        try:
            if event is not None and event.widget is not self:
                return
            self.lbl_kapsam.configure(wraplength=max(400, self.winfo_width() - 40))
        except tk.TclError:
            pass

    def _mod(self) -> str:
        return self.var_mod.get() or self.MOD_EKSTRE

    def _mod_ui_guncelle(self) -> None:
        tarih_modu = self._mod() == self.MOD_TARIH
        tarih_durum = "normal" if tarih_modu else "disabled"
        nav_durum = "disabled" if tarih_modu else "normal"
        for w in (self.ent_bas, self.ent_bit, self.btn_uygula, self.btn_temizle):
            w.configure(state=tarih_durum)
        for w in (self.btn_onceki, self.btn_sonraki):
            w.configure(state=nav_durum)

    def _mod_degisti(self) -> None:
        self._mod_ui_guncelle()
        if self._mod() == self.MOD_EKSTRE:
            self._yenile()
        elif (self.ent_bas.get() or "").strip() and (self.ent_bit.get() or "").strip():
            self._yenile()
        else:
            self._tablolari_temizle()
            self.lbl_kapsam.configure(
                text="İki tarih arası: başlangıç ve bitiş tarihini (GG.AA.YYYY) girip «Uygula» düğmesine basın."
            )

    def _uygula(self) -> None:
        if self._mod() != self.MOD_TARIH:
            self.var_mod.set(self.MOD_TARIH)
            self._mod_ui_guncelle()
        self._yenile()

    def _temizle(self) -> None:
        self.ent_bas.delete(0, "end")
        self.ent_bit.delete(0, "end")
        self.var_mod.set(self.MOD_EKSTRE)
        self._mod_ui_guncelle()
        self._yenile()

    def _tarih_oku(self, entry: ttk.Entry, alan: str) -> date | None:
        from datetime import datetime

        ham = (entry.get() or "").strip()
        if not ham:
            return None
        try:
            return datetime.strptime(ham, "%d.%m.%Y").date()
        except ValueError as exc:
            raise ValueError(f"{alan} tarihi GG.AA.YYYY biçiminde olmalıdır.") from exc

    def _tablolari_temizle(self) -> None:
        for t in (self.tv, self.tv_odeme, self.tv_dag):
            for i in t.get_children():
                t.delete(i)
        self._har_belge.clear()
        self._odeme_belge.clear()

    def _belge_ac(self, tablo: ttk.Treeview, harita: dict[str, str]) -> None:
        sec = tablo.selection()
        if not sec:
            return
        belge = (harita.get(sec[0]) or "").strip()
        if not belge:
            return
        try:
            from belge_onizleme_ui import finans_belge_ac

            if not finans_belge_ac(self, "FİNANS", belge):
                messagebox.showinfo("Belge", f"Belge açılamadı: {belge}", parent=self)
        except Exception:
            pass

    # ------------------------------------------------------------------ dönem gezinme
    def _secili_donem(self) -> dict:
        if not self._donemler:
            return {}
        self._idx = max(0, min(self._idx, len(self._donemler) - 1))
        return self._donemler[self._idx]

    def _onceki(self):
        if self._mod() != self.MOD_EKSTRE:
            return
        self._idx = max(0, self._idx - 1)
        self._yenile()

    def _sonraki(self):
        if self._mod() != self.MOD_EKSTRE:
            return
        self._idx = min(len(self._donemler) - 1, self._idx + 1)
        self._yenile()

    # ------------------------------------------------------------------ rapor
    def _yenile(self):
        self._tablolari_temizle()
        mod = self._mod()
        try:
            if mod == self.MOD_TARIH:
                bas = self._tarih_oku(self.ent_bas, "Başlangıç")
                bit = self._tarih_oku(self.ent_bit, "Bitiş")
                r = self._rapor_verisi(
                    self.kredi_karti_id,
                    mod=self.MOD_TARIH,
                    baslangic=bas,
                    bitis=bit,
                    kesim_tarihi=None,
                    ekstre_id=None,
                )
            else:
                d = self._secili_donem()
                r = self._rapor_verisi(
                    self.kredi_karti_id,
                    mod=self.MOD_EKSTRE,
                    baslangic=None,
                    bitis=None,
                    kesim_tarihi=d.get("kesim_tarihi"),
                    ekstre_id=d.get("ekstre_id"),
                )
        except ValueError as exc:
            messagebox.showwarning("Rapor", str(exc), parent=self)
            return
        except Exception as exc:
            messagebox.showerror("Rapor", str(exc), parent=self)
            return
        self._rapor = r
        self._baslik_ozet_doldur(r)
        self._hareketleri_doldur(r)
        self._odemeleri_doldur(r)
        self._dagilimi_doldur(r)

    def _baslik_ozet_doldur(self, r: dict) -> None:
        if r.get("mod") == self.MOD_TARIH:
            tur = "İki tarih arası hareket raporu"
        else:
            tur = "Kesilmiş ekstre" if r.get("kesin") else "Henüz kesilmemiş / hesaplanan dönem"
        self.lbl_baslik.configure(
            text=f"{r.get('banka_adi')} / {r.get('kart_adi')} / {r.get('maskeli_no')}  ·  {tur}"
        )
        self.lbl_donem.configure(
            text=(
                f"Dönem: {_tarih(r.get('donem_baslangic'))} – {_tarih(r.get('donem_bitis'))}  ·  "
                f"Kesim: {_tarih(r.get('kesim_tarihi')) or '—'}  ·  "
                f"Son ödeme: {_tarih(r.get('son_odeme_tarihi')) or 'tanımsız'}  ·  "
                f"Rapor: {_tarih(r.get('rapor_tarihi'))}"
            )
        )
        hb = r.get("hesap_bakiyesi")
        degerler = {
            "kesim_tutari": _para(r.get("kesim_tutari")),
            "onceki_devir": _para(r.get("onceki_devir")),
            "odenen": _para(r.get("donem_odenen")),
            "kalan": _para(r.get("kalan_odenecek")),
            "kullanilan_limit": _para(r.get("kullanilan_limit")),
            "hesap_bakiyesi": _para(hb) if hb is not None else "—",
            "gelecek_kalan": _para(r.get("gelecek_taksit_toplami")),
        }
        for k, v in degerler.items():
            self._ozet_lbl[k].configure(text=v)
        self.lbl_kapsam.configure(text=r.get("kapsam") or "")

    def _hareketleri_doldur(self, r: dict) -> None:
        for n, h in enumerate(r.get("hareketler") or []):
            bakiye = h.get("bakiye") if h.get("bakiye") is not None else h.get("kalan")
            iid = f"h{n}"
            self._har_belge[iid] = h.get("belge") or ""
            self.tv.insert(
                "",
                "end",
                iid=iid,
                values=(
                    _tarih(h.get("kaynak_tarihi")),
                    _tarih(h.get("yansima_tarihi") or h.get("tarih")),
                    _tarih(h.get("vade_tarihi")),
                    h.get("belge") or "",
                    (h.get("aciklama") or "")[:120],
                    h.get("taksit_no") or "",
                    _tarih(h.get("ekstre_kesim_tarihi")),
                    _tarih(h.get("son_odeme_tarihi")),
                    _para(h.get("borc")),
                    _para(h.get("odeme")),
                    _para(bakiye),
                ),
            )

    def _odemeleri_doldur(self, r: dict) -> None:
        satirlar = list(r.get("odemeler") or []) + list(r.get("onceki_odeme_mahsuplari") or [])
        for n, o in enumerate(satirlar):
            iid = f"o{n}"
            self._odeme_belge[iid] = o.get("belge_no") or ""
            self.tv_odeme.insert(
                "",
                "end",
                iid=iid,
                values=(
                    _tarih(o.get("tarih")),
                    o.get("belge_no") or "",
                    _para(o.get("tutar")),
                    _para(o.get("mahsup")),
                    _tarih(o.get("ekstre_kesim_tarihi")),
                    KAYNAK_ETIKET.get(o.get("kaynak"), o.get("kaynak") or ""),
                    " · ".join(x for x in (o.get("dekont_no"), o.get("aciklama")) if x),
                ),
            )

    def _dagilimi_doldur(self, r: dict) -> None:
        for g in r.get("donem_dagilimi") or r.get("gelecek_donemler") or []:
            kesim_tutari = g.get("kesim_tutari")
            if kesim_tutari is None:
                kesim_tutari = g.get("planli_borc")
            kalan = g.get("kalan")
            if kalan is None:
                kalan = g.get("planli_borc")
            self.tv_dag.insert(
                "",
                "end",
                values=(
                    _tarih(g.get("kesim_tarihi")) or "—",
                    _tarih(g.get("donem_baslangic")) or "—",
                    _tarih(g.get("donem_bitis")) or "—",
                    _tarih(g.get("son_odeme_tarihi")) or "—",
                    g.get("taksit_sayisi") or 0,
                    _para(kesim_tutari),
                    _para(g.get("odenen")),
                    _para(kalan),
                    g.get("durum") or g.get("etiket") or "",
                ),
            )

    # ------------------------------------------------------------------ çıktı
    def _pdf(self):
        if not self._rapor:
            return
        from tkinter import filedialog
        from database.kk_ekstre_rapor_service import pdf_kaydet
        yol = filedialog.asksaveasfilename(
            parent=self, defaultextension=".pdf",
            initialfile=f"{self._rapor.get('dosya_kok')}.pdf",
            filetypes=[("PDF", "*.pdf")],
        )
        if not yol:
            return
        try:
            pdf_kaydet(self._rapor, yol)
            messagebox.showinfo("PDF", f"Kaydedildi:\n{yol}", parent=self)
        except Exception as exc:
            messagebox.showerror("PDF", str(exc), parent=self)

    def _excel(self):
        if not self._rapor:
            return
        from tkinter import filedialog
        from database.kk_ekstre_rapor_service import excel_kaydet
        yol = filedialog.asksaveasfilename(
            parent=self, defaultextension=".xlsx",
            initialfile=f"{self._rapor.get('dosya_kok')}.xlsx",
            filetypes=[("Excel", "*.xlsx")],
        )
        if not yol:
            return
        try:
            excel_kaydet(self._rapor, yol)
            messagebox.showinfo("Excel", f"Kaydedildi:\n{yol}", parent=self)
        except Exception as exc:
            messagebox.showerror("Excel", str(exc), parent=self)
