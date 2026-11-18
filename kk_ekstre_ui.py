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
    """Ekstre / Dönem Borcu Raporu — seçili kart; kesin ve gelecek dönemler ayrı."""

    def __init__(self, parent, kredi_karti_id: int, *, yenile_cb=None):
        super().__init__(parent)
        self.kredi_karti_id = int(kredi_karti_id)
        self.yenile_cb = yenile_cb
        self.title("Ekstre / Dönem Borcu Raporu")
        self.geometry("1100x720")
        self.minsize(960, 600)
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
            # Kesim günü yoksa bile ozet göster
            self._donemler = [{"kesim_tarihi": None, "ekstre_id": None, "kesin": False}]

        ust = ttk.Frame(self, padding=8)
        ust.pack(fill="x")
        self.lbl_baslik = ttk.Label(ust, font=("Segoe UI", 11, "bold"))
        self.lbl_baslik.pack(anchor="w")
        self.lbl_ozet = ttk.Label(ust, wraplength=1040)
        self.lbl_ozet.pack(anchor="w", pady=(4, 0))
        self.lbl_ayrim = ttk.Label(ust, foreground="#1a2b4a", font=("Segoe UI", 9, "bold"))
        self.lbl_ayrim.pack(anchor="w", pady=(2, 0))

        nav = ttk.Frame(self, padding=(8, 0))
        nav.pack(fill="x")
        ttk.Button(nav, text="◀ Önceki dönem", command=self._onceki).pack(side="left", padx=2)
        ttk.Button(nav, text="Sonraki dönem ▶", command=self._sonraki).pack(side="left", padx=2)
        ttk.Button(nav, text="PDF", command=self._pdf).pack(side="left", padx=8)
        ttk.Button(nav, text="Excel", command=self._excel).pack(side="left", padx=2)
        ttk.Button(nav, text="Yenile", command=self._yenile).pack(side="left", padx=8)
        ttk.Button(nav, text="Kapat", command=self.destroy).pack(side="right", padx=2)

        orta = ttk.Panedwindow(self, orient="vertical")
        orta.pack(fill="both", expand=True, padx=8, pady=6)

        har_f = ttk.LabelFrame(orta, text="Dönem kalemleri", padding=4)
        cols = ("tarih", "belge", "aciklama", "taksit", "borc", "odeme", "kalan")
        self.tv = ttk.Treeview(har_f, columns=cols, show="headings", height=12)
        for k, b, w in (
            ("tarih", "İşlem / yansıma", 100),
            ("belge", "Belge", 120),
            ("aciklama", "Açıklama", 220),
            ("taksit", "Taksit", 80),
            ("borc", "Borç", 90),
            ("odeme", "Ödeme", 90),
            ("kalan", "Etki", 90),
        ):
            self.tv.heading(k, text=b)
            self.tv.column(k, width=w, anchor="w")
        self.tv.pack(fill="both", expand=True)
        orta.add(har_f, weight=3)

        gel_f = ttk.LabelFrame(orta, text="Gelecek dönem planlı borçları (ödeme/gider üretmez)", padding=4)
        gcols = ("donem", "bas", "kesim", "son", "adet", "tutar", "tur")
        self.tv_gel = ttk.Treeview(gel_f, columns=gcols, show="headings", height=8)
        for k, b, w in (
            ("donem", "Dönem", 70),
            ("bas", "Başlangıç", 90),
            ("kesim", "Hesap kesimi", 100),
            ("son", "Son ödeme", 90),
            ("adet", "Taksit", 60),
            ("tutar", "Planlı borç", 100),
            ("tur", "Tür", 140),
        ):
            self.tv_gel.heading(k, text=b)
            self.tv_gel.column(k, width=w, anchor="w")
        self.tv_gel.pack(fill="both", expand=True)
        orta.add(gel_f, weight=2)

        self._rapor = None
        self._yenile()

    def _secili_donem(self) -> dict:
        if not self._donemler:
            return {}
        self._idx = max(0, min(self._idx, len(self._donemler) - 1))
        return self._donemler[self._idx]

    def _onceki(self):
        self._idx = max(0, self._idx - 1)
        self._yenile()

    def _sonraki(self):
        self._idx = min(len(self._donemler) - 1, self._idx + 1)
        self._yenile()

    def _yenile(self):
        for t in (self.tv, self.tv_gel):
            for i in t.get_children():
                t.delete(i)
        d = self._secili_donem()
        try:
            self._rapor = self._rapor_verisi(
                self.kredi_karti_id,
                ekstre_id=d.get("ekstre_id"),
                kesim_tarihi=d.get("kesim_tarihi"),
            )
        except Exception as exc:
            messagebox.showerror("Rapor", str(exc), parent=self)
            return
        r = self._rapor
        kesin_metin = "Kesilmiş ekstre" if r.get("kesin") else "Henüz kesilmemiş / hesaplanan dönem"
        self.lbl_baslik.configure(
            text=(
                f"{r.get('banka_adi')} / {r.get('kart_adi')} / {r.get('maskeli_no')}  ·  "
                f"{kesin_metin}"
            )
        )
        self.lbl_ozet.configure(
            text=(
                f"Dönem: {_tarih(r.get('donem_baslangic'))} – {_tarih(r.get('donem_bitis'))}  ·  "
                f"Kesim: {_tarih(r.get('kesim_tarihi'))}  ·  Son ödeme: {_tarih(r.get('son_odeme_tarihi')) or 'tanımsız'}  ·  "
                f"Rapor: {_tarih(r.get('rapor_tarihi'))}\n"
                f"Kesim tutarı: {_para(r.get('kesim_tutari'))}  ·  Ödenen: {_para(r.get('donem_odenen'))}  ·  "
                f"Kalan ödenecek: {_para(r.get('kalan_odenecek'))}  ·  "
                f"Toplam kart borcu: {_para(r.get('toplam_kart_borcu'))}  ·  "
                f"Kullanılan limit: {_para(r.get('kullanilan_limit'))}"
            )
        )
        self.lbl_ayrim.configure(
            text=(
                "Kesim tutarı ile kalan ödenecek ayrı izlenir. "
                "Gelecek planlı taksitler bugünkü ödeme/gider toplamına eklenmez."
            )
        )
        for h in r.get("hareketler") or []:
            self.tv.insert(
                "",
                "end",
                values=(
                    _tarih(h.get("tarih") or h.get("plan_vadesi")),
                    h.get("belge") or "",
                    (h.get("aciklama") or "")[:80],
                    h.get("taksit_no") or "",
                    _para(h.get("borc")),
                    _para(h.get("odeme")),
                    _para(h.get("kalan")),
                ),
            )
        for g in r.get("gelecek_donemler") or []:
            self.tv_gel.insert(
                "",
                "end",
                values=(
                    _tarih(g.get("kesim_tarihi"))[:7] if g.get("kesim_tarihi") else "—",
                    _tarih(g.get("donem_baslangic")),
                    _tarih(g.get("kesim_tarihi")),
                    _tarih(g.get("son_odeme_tarihi")) or "—",
                    g.get("taksit_sayisi") or 0,
                    _para(g.get("planli_borc")),
                    g.get("etiket") or "",
                ),
            )

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
