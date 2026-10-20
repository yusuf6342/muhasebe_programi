"""Cari kart — İşletme Yetkilileri paneli ve düzenleme penceresi.

Müşteri ve tedarikçi kartları aynı panel/pencereyi kullanır.
"""

from __future__ import annotations

import tkinter as tk
from datetime import date, datetime
from tkinter import messagebox, ttk
from typing import Any, Callable

from cari_kart_tema import (
    ACIK_BG,
    BEYAZ,
    CIZGI,
    IKINCIL,
    LACIVERT,
    SARI,
    STRIPE,
    UYARI,
    BASARI,
    font,
    tk_buton,
)
from database.cari_yetkili_service import _EMAIL_RE, CariYetkiliService, dogum_gunu_metni
from database.turkce_normalize import turkce_normalize

AY_ADLARI = (
    "Ocak", "Şubat", "Mart", "Nisan", "Mayıs", "Haziran",
    "Temmuz", "Ağustos", "Eylül", "Ekim", "Kasım", "Aralık",
)


def _tarih_goster(d) -> str:
    if not d:
        return ""
    if isinstance(d, date):
        return d.strftime("%d.%m.%Y")
    return str(d)


class TanimSecici(ttk.Combobox):
    """Yazdıkça süzülen tanım seçimi; seçim kayıt kimliğiyle tutulur (``secili_id``).

    Metin bir tanımla birebir eşleşirse (Türkçe/büyük-küçük duyarsız) o tanımın kimliği alınır;
    böylece aynı ad tekrar yazılınca yeni tanım oluşmaz.
    """

    def __init__(self, parent, kaynak: Callable[[], list[dict[str, Any]]], *,
                 on_degisim: Callable[[], None] | None = None, **kw):
        super().__init__(parent, **kw)
        self._kaynak = kaynak
        self._on_degisim = on_degisim
        self._tanimlar: list[dict[str, Any]] = []
        self.secili_id: int | None = None
        self.yenile_kaynak()
        self.bind("<KeyRelease>", self._yazildi, add="+")
        self.bind("<<ComboboxSelected>>", lambda _e: self._eslestir(), add="+")
        self.bind("<FocusOut>", lambda _e: self._eslestir(), add="+")

    def yenile_kaynak(self) -> None:
        try:
            self._tanimlar = list(self._kaynak() or [])
        except Exception:
            self._tanimlar = []
        self._suz("")

    def _suz(self, metin: str) -> None:
        n = turkce_normalize(metin.strip())
        self["values"] = [t["ad"] for t in self._tanimlar if not n or n in turkce_normalize(t["ad"])]

    def _yazildi(self, event) -> None:
        if event.keysym in ("Up", "Down", "Return", "Escape", "Tab"):
            return
        self._suz(self.get())
        self._eslestir()

    def _eslestir(self) -> None:
        n = turkce_normalize(self.get().strip())
        bulunan = next((t for t in self._tanimlar if turkce_normalize(t["ad"]) == n), None) if n else None
        onceki = self.secili_id
        self.secili_id = int(bulunan["id"]) if bulunan else None
        if bulunan and self.get() != bulunan["ad"]:
            self.set(bulunan["ad"])
        if onceki != self.secili_id and callable(self._on_degisim):
            self._on_degisim()

    def ata(self, tanim_id: int | None, ad: str = "") -> None:
        bulunan = next((t for t in self._tanimlar if tanim_id and int(t["id"]) == int(tanim_id)), None)
        self.secili_id = int(bulunan["id"]) if bulunan else None
        self.set(bulunan["ad"] if bulunan else (ad or ""))
        if not bulunan and ad:
            self._eslestir()

    def tanim(self, tanim_id: int | None) -> dict[str, Any] | None:
        return next((t for t in self._tanimlar if tanim_id and int(t["id"]) == int(tanim_id)), None)

    def metin(self) -> str:
        return " ".join(self.get().split())


class YetkiliDialog(tk.Toplevel):
    """Yetkili ekle/düzenle. «Yetkiliyi Kaydet» pencereyi kapatmaz; ikinci kayıt aynı kişiyi günceller."""

    def __init__(
        self,
        parent,
        *,
        cari_id: int | None,
        yetkili: dict[str, Any] | None = None,
        on_kaydet: Callable[[dict[str, Any]], None] | None = None,
        cari_kaydet: Callable[[], int | None] | None = None,
    ):
        super().__init__(parent)
        self.cari_id = int(cari_id) if cari_id else None
        self.yetkili = dict(yetkili or {})
        self._on_kaydet = on_kaydet
        self._cari_kaydet = cari_kaydet
        self._kaydediliyor = False
        self.transient(parent)
        self.configure(bg=ACIK_BG)
        self._baslik_yaz()
        self._pencereyi_yerlestir()
        self._hassas = CariYetkiliService.hassas_izinli()

        alt = tk.Frame(self, bg=ACIK_BG, padx=12, pady=8, highlightthickness=1, highlightbackground=CIZGI)
        alt.pack(side="bottom", fill="x")
        self.kaydet_btn = tk_buton(alt, "Yetkiliyi Kaydet", self._kaydet, rol="kaydet")
        self.kaydet_btn.pack(side="left")
        self._durum_lbl = tk.Label(alt, text="", bg=ACIK_BG, fg=IKINCIL, font=font(9, root=self))
        self._durum_lbl.pack(side="left", padx=10)
        tk_buton(alt, "Kapat", self.destroy, rol="ikincil").pack(side="right")

        govde = tk.Frame(self, bg=ACIK_BG)
        govde.pack(fill="both", expand=True)
        sag = tk.Frame(govde, bg=ACIK_BG, padx=10, pady=10)
        sag.pack(side="right", fill="y")
        from cari_foto_ui import FotoAlani

        self.foto = FotoAlani(sag, sahip_turu="YETKILI", baslik="Yetkili Fotoğrafı", aninda=False,
                              sabit_boyut=(160, 190), bg=ACIK_BG)
        self.foto.pack(anchor="n")
        if self.yetkili.get("id"):
            self.foto.sahip_ata(int(self.yetkili["id"]), cari_id=self.cari_id)

        kaydirma = tk.Frame(govde, bg=ACIK_BG)
        kaydirma.pack(side="left", fill="both", expand=True)
        self._tuval = tk.Canvas(kaydirma, bg=ACIK_BG, highlightthickness=0)
        cubuk = ttk.Scrollbar(kaydirma, orient="vertical", command=self._tuval.yview)
        self._tuval.configure(yscrollcommand=cubuk.set)
        cubuk.pack(side="right", fill="y")
        self._tuval.pack(side="left", fill="both", expand=True)
        form = tk.Frame(self._tuval, bg=ACIK_BG, padx=12, pady=8)
        pencere_id = self._tuval.create_window((0, 0), window=form, anchor="nw")
        form.bind("<Configure>", lambda _e: self._tuval.configure(scrollregion=self._tuval.bbox("all")))
        self._tuval.bind("<Configure>", lambda e: self._tuval.itemconfigure(pencere_id, width=e.width))
        self.bind("<MouseWheel>", self._tekerlek, add="+")
        form.columnconfigure(1, weight=1)

        self._vars: dict[str, tk.Variable] = {}
        self._satir = 0

        self._bolum(form, "Kimlik / Görev")
        self._alan(form, "Ad *", "ad")
        self._alan(form, "Soyad *", "soyad")
        self._alan(form, "Unvan", "unvan")
        self.departman_cb = TanimSecici(form, CariYetkiliService.departmanlar,
                                        on_degisim=self._departman_degisti)
        self._widget_satiri(form, "Departman", self.departman_cb)
        self.gorev_cb = TanimSecici(form, self._gorev_kaynagi)
        self._widget_satiri(form, "Görev", self.gorev_cb)
        self.departman_cb.ata(self.yetkili.get("departman_id"), self.yetkili.get("departman") or "")
        self.gorev_cb.yenile_kaynak()
        self.gorev_cb.ata(self.yetkili.get("gorev_id"), self.yetkili.get("gorev") or "")
        self._alan(form, "Ana yetkili", "ana_yetkili", tip="check")
        self._alan(form, "Aktif", "aktif", tip="check")
        if "aktif" not in self.yetkili:
            self._vars["aktif"].set(True)

        self._bolum(form, "İletişim")
        self._alan(form, "Cep telefonu", "cep_telefonu")
        self._alan(form, "İkinci telefon", "telefon2")
        self._alan(form, "WhatsApp", "whatsapp_telefonu")
        self._alan(form, "İş telefonu", "is_telefonu")
        self._alan(form, "Dahili", "dahili", genislik=12)
        email_e = self._alan(form, "E-posta", "email")
        self._email_uyari = tk.Label(form, text="", bg=ACIK_BG, fg=UYARI, font=font(8, root=self))
        self._email_uyari.grid(row=self._satir, column=1, sticky="w")
        self._satir += 1
        email_e.bind("<FocusOut>", lambda _e: self._email_kontrol(), add="+")

        self.ozel_not: tk.Text | None = None
        if self._hassas:
            self._bolum(form, "Özel bilgiler")
            self._dogum_alani(form)
            self._alan(form, "Doğum günü hatırlat", "dogum_gunu_hatirlat", tip="check")
            if "dogum_gunu_hatirlat" not in self.yetkili:
                self._vars["dogum_gunu_hatirlat"].set(True)
            self._alan(form, "Hitap", "hitap")
            self._alan(form, "Tercih edilen kanal", "iletisim_kanali")
            self.ozel_not = tk.Text(form, height=4, width=40, wrap="word", font=font(9, root=self),
                                    relief="solid", bd=1)
            self.ozel_not.insert("1.0", self.yetkili.get("ozel_notlar") or "")
            self._widget_satiri(form, "Özel not", self.ozel_not)
            tk.Label(form, text="Teklif, fatura ve makbuz çıktılarına eklenmez.", bg=ACIK_BG, fg=IKINCIL,
                     font=font(8, root=self)).grid(row=self._satir, column=1, sticky="w")
            self._satir += 1
            self._alan(form, "Pazarlama izni", "pazarlama_izni", tip="check")
            self._alan(form, "KVKK / iletişim onayı", "kvkk_onayi", tip="check")

        self.bind("<Escape>", lambda _e: self.destroy())
        self.bind("<Control-s>", lambda _e: self._kaydet())
        self.grab_set()
        self.after(50, lambda: self._ilk_odak())

    # --- Yerleşim yardımcıları ---

    def _pencereyi_yerlestir(self):
        """780×640 hedef; küçük iş alanında (ör. %125 ölçek, 1366×768) ekrana sığacak kadar küçülür."""
        try:
            from ui_pencere import calisma_alani

            x, y, aw, ah = calisma_alani(self)
        except Exception:
            x, y, aw, ah = 0, 0, self.winfo_screenwidth(), self.winfo_screenheight()
        gen, yuk = min(780, aw - 20), min(640, ah - 40)
        self.minsize(min(660, gen), min(460, yuk))
        self.geometry(f"{gen}x{yuk}+{x + max(0, (aw - gen) // 2)}+{y + max(0, (ah - yuk) // 2 - 10)}")

    def _baslik_yaz(self):
        if self.yetkili.get("id"):
            self.title(f"Yetkili Düzenle — {self.yetkili.get('ad_soyad') or ''}".rstrip(" —"))
        else:
            self.title("Yeni Yetkili")

    def _ilk_odak(self):
        try:
            for w in self._tuval.winfo_children()[0].grid_slaves(row=1, column=1):
                w.focus_set()
        except (tk.TclError, IndexError):
            pass

    def _tekerlek(self, event):
        try:
            self._tuval.yview_scroll(int(-event.delta / 120), "units")
        except tk.TclError:
            pass

    def _bolum(self, form, metin: str):
        tk.Label(form, text=metin, bg=ACIK_BG, fg=LACIVERT, font=font(11, "bold", self)).grid(
            row=self._satir, column=0, columnspan=2, sticky="w", pady=(8 if self._satir else 0, 4)
        )
        self._satir += 1

    def _widget_satiri(self, form, etiket: str, widget):
        tk.Label(form, text=etiket, bg=ACIK_BG, fg=LACIVERT, font=font(9, root=self)).grid(
            row=self._satir, column=0, sticky="nw", padx=(0, 8), pady=2
        )
        widget.grid(row=self._satir, column=1, sticky="we", pady=2)
        self._satir += 1
        return widget

    def _alan(self, form, etiket: str, alan: str, *, genislik: int = 28, tip: str = "entry"):
        if tip == "check":
            var = tk.BooleanVar(value=bool(self.yetkili.get(alan)))
            w = ttk.Checkbutton(form, variable=var)
            self._vars[alan] = var
            tk.Label(form, text=etiket, bg=ACIK_BG, fg=LACIVERT, font=font(9, root=self)).grid(
                row=self._satir, column=0, sticky="w", padx=(0, 8), pady=2
            )
            w.grid(row=self._satir, column=1, sticky="w", pady=2)
            self._satir += 1
            return w
        var = tk.StringVar(value=str(self.yetkili.get(alan) or ""))
        self._vars[alan] = var
        return self._widget_satiri(form, etiket, ttk.Entry(form, textvariable=var, width=genislik))

    def _dogum_alani(self, form):
        kutu = tk.Frame(form, bg=ACIK_BG)
        self.dogum_gun = ttk.Combobox(kutu, width=4, values=[""] + [str(i) for i in range(1, 32)])
        self.dogum_gun.pack(side="left")
        tk.Label(kutu, text="Ay", bg=ACIK_BG, fg=IKINCIL, font=font(8, root=self)).pack(side="left", padx=(6, 2))
        self.dogum_ay = ttk.Combobox(kutu, width=10, state="readonly", values=("",) + AY_ADLARI)
        self.dogum_ay.pack(side="left")
        tk.Label(kutu, text="Yıl (isteğe bağlı)", bg=ACIK_BG, fg=IKINCIL, font=font(8, root=self)).pack(
            side="left", padx=(6, 2)
        )
        self.dogum_yil = ttk.Entry(kutu, width=6)
        self.dogum_yil.pack(side="left")
        gun = self.yetkili.get("dogum_gun")
        ay = self.yetkili.get("dogum_ay")
        yil = self.yetkili.get("dogum_yili")
        self.dogum_gun.set(str(gun) if gun else "")
        self.dogum_ay.set(AY_ADLARI[int(ay) - 1] if ay and 1 <= int(ay) <= 12 else "")
        if yil:
            self.dogum_yil.insert(0, str(yil))
        self._widget_satiri(form, "Doğum günü", kutu)

    # --- Departman / görev ---

    def _gorev_kaynagi(self) -> list[dict[str, Any]]:
        return CariYetkiliService.gorevler(getattr(self, "departman_cb", None) and self.departman_cb.secili_id)

    def _departman_degisti(self):
        if not hasattr(self, "gorev_cb"):
            return
        onceki_id = self.gorev_cb.secili_id
        onceki_ad = self.gorev_cb.metin()
        self.gorev_cb.yenile_kaynak()
        if onceki_id and self.gorev_cb.tanim(onceki_id) is None:
            self.gorev_cb.ata(None)
            messagebox.showinfo(
                "Görev",
                f"«{onceki_ad}» görevi seçilen departmanla uyumlu değil.\nLütfen görevi yeniden seçin.",
                parent=self,
            )
            self.gorev_cb.focus_set()
        elif onceki_id:
            self.gorev_cb.ata(onceki_id)

    def _tanim_onayi(self, secici: TanimSecici, tur: str) -> bool:
        metin = secici.metin()
        if not metin or secici.secili_id:
            return True
        if messagebox.askyesno(
            tur, f"«{metin}» {tur.lower()} tanımlarında yok.\nYeni {tur.lower()} tanımı olarak eklensin mi?",
            parent=self,
        ):
            return True
        secici.focus_set()
        return False

    # --- Kayıt ---

    def _email_kontrol(self) -> bool:
        deger = (self._vars["email"].get() or "").strip()
        gecerli = not deger or bool(_EMAIL_RE.match(deger))
        self._email_uyari.configure(text="" if gecerli else "E-posta biçimi geçersiz (ör. ad@firma.com).")
        return gecerli

    def form_verisi(self) -> dict[str, Any]:
        veri: dict[str, Any] = {}
        for alan, var in self._vars.items():
            veri[alan] = bool(var.get()) if isinstance(var, tk.BooleanVar) else var.get().strip()
        veri["departman_id"] = self.departman_cb.secili_id
        veri["departman"] = self.departman_cb.metin()
        veri["gorev_id"] = self.gorev_cb.secili_id
        veri["gorev"] = self.gorev_cb.metin()
        if self._hassas:
            ay_metni = self.dogum_ay.get()
            veri["dogum_gun"] = self.dogum_gun.get().strip()
            veri["dogum_ay"] = str(AY_ADLARI.index(ay_metni) + 1) if ay_metni in AY_ADLARI else ""
            veri["dogum_yili"] = self.dogum_yil.get().strip()
            veri["ozel_notlar"] = self.ozel_not.get("1.0", "end").strip() if self.ozel_not else ""
        return veri

    def _kaydet(self):
        if self._kaydediliyor:
            return
        veri = self.form_verisi()
        if not veri.get("ad") or not veri.get("soyad"):
            messagebox.showwarning("Yetkili", "Ad ve soyad zorunludur.", parent=self)
            return
        if not self._email_kontrol():
            return
        if not self._tanim_onayi(self.departman_cb, "Departman") or not self._tanim_onayi(self.gorev_cb, "Görev"):
            return
        if not self.cari_id:
            if self._cari_kaydet is None:
                messagebox.showwarning("Yetkili", "Önce cari kartı kaydediniz.", parent=self)
                return
            if not messagebox.askyesno(
                "Önce cari kartı kaydediniz",
                "Yetkili yalnızca kayıtlı bir cariye bağlanabilir.\nCari kart şimdi kaydedilsin mi?",
                parent=self,
            ):
                return
            self.grab_release()
            try:
                cari_id = self._cari_kaydet()
            finally:
                if self.winfo_exists():
                    self.grab_set()
            if not cari_id:
                return  # Cari kaydı yapılmadı: yetkili formu olduğu gibi kalır
            self.cari_id = int(cari_id)

        self._kaydediliyor = True
        self.kaydet_btn.configure(state="disabled", text="Kaydediliyor…")
        self._durum_lbl.configure(text="")
        self.update_idletasks()
        try:
            if self.yetkili.get("id"):
                sonuc = CariYetkiliService.guncelle(int(self.yetkili["id"]), veri)
            else:
                sonuc = CariYetkiliService.ekle(self.cari_id, veri)
        except Exception as hata:
            messagebox.showerror("Yetkili", str(hata), parent=self)
            return
        finally:
            self._kaydediliyor = False
            if self.winfo_exists():
                self.kaydet_btn.configure(state="normal", text="Yetkiliyi Kaydet")
        self.yetkili = dict(sonuc)
        self._baslik_yaz()
        foto_hatasi = None
        try:
            self.foto.bekleyeni_uygula(int(sonuc["id"]))
            self.foto.cari_id = self.cari_id
        except Exception as hata:
            foto_hatasi = str(hata)
        if self.departman_cb.metin() and not self.departman_cb.secili_id:
            self.departman_cb.yenile_kaynak()
            self.departman_cb.ata(sonuc.get("departman_id"), sonuc.get("departman") or "")
        if self.gorev_cb.metin() and not self.gorev_cb.secili_id:
            self.gorev_cb.yenile_kaynak()
            self.gorev_cb.ata(sonuc.get("gorev_id"), sonuc.get("gorev") or "")
        if callable(self._on_kaydet):
            self._on_kaydet(sonuc)
        self._durum_lbl.configure(text=f"Kaydedildi ✓ {datetime.now():%H:%M}", fg=BASARI)
        if foto_hatasi:
            messagebox.showwarning("Fotoğraf", f"Yetkili kaydedildi; fotoğraf kaydedilemedi:\n{foto_hatasi}",
                                   parent=self)


class YetkiliPanel(tk.Frame):
    """Cari kart içi İşletme Yetkilileri paneli (müşteri ve tedarikçi ortak)."""

    def __init__(self, parent, *, dialog, gomulu: bool = False, **kw):
        kenar = 0 if gomulu else 1
        super().__init__(parent, bg=BEYAZ, highlightthickness=kenar, highlightbackground=CIZGI, **kw)
        self.dialog = dialog
        self._cari_id = int(dialog.cari.id) if dialog.cari and getattr(dialog.cari, "id", None) else None

        if gomulu:
            self._ozet_lbl = tk.Label(
                self, text="", bg=BEYAZ, fg=IKINCIL, font=font(8, root=dialog), anchor="w"
            )
            self._ozet_lbl.pack(fill="x", padx=2, pady=(0, 4))
        else:
            baslik = tk.Frame(self, bg=LACIVERT)
            baslik.pack(fill="x")
            tk.Label(
                baslik,
                text="İşletme Yetkilileri",
                bg=LACIVERT,
                fg=SARI,
                font=font(11, "bold", dialog),
                padx=10,
                pady=6,
            ).pack(side="left")
            self._ozet_lbl = tk.Label(
                baslik, text="", bg=LACIVERT, fg=BEYAZ, font=font(9, root=dialog), padx=8
            )
            self._ozet_lbl.pack(side="right")

        arac = tk.Frame(self, bg=BEYAZ, padx=4 if gomulu else 8, pady=4 if gomulu else 6)
        arac.pack(fill="x")
        self._btn_yeni = tk_buton(
            arac, "Yeni" if gomulu else "Yeni Yetkili", self._yeni, rol="yeni"
        )
        self._btn_yeni.pack(side="left", padx=(0, 3))
        self._btn_duzenle = tk_buton(arac, "Düzenle", self._duzenle, rol="duzenle")
        self._btn_duzenle.pack(side="left", padx=3)
        self._btn_pasif = tk_buton(
            arac, "Pasif" if gomulu else "Pasife Al", self._pasif, rol="ara"
        )
        self._btn_pasif.pack(side="left", padx=3)
        self._btn_sil = tk_buton(arac, "Sil", self._sil, rol="iptal")
        self._btn_sil.pack(side="left", padx=3)

        icerik = tk.Frame(self, bg=BEYAZ)
        icerik.pack(fill="both", expand=True)
        from cari_foto_ui import FotoAlani

        self.foto = FotoAlani(icerik, sahip_turu="YETKILI", baslik="Seçili yetkili", sabit_boyut=(110, 130))
        self.foto.pack(side="right", anchor="n", padx=(4, 4 if gomulu else 8))

        kolonlar = ("ad", "gorev", "telefon", "email", "dogum", "foto", "ana", "durum")
        self.tablo = ttk.Treeview(
            icerik, columns=kolonlar, show="headings", height=8 if gomulu else 5, selectmode="browse"
        )
        for k, b, w in (
            ("ad", "Ad Soyad", 100 if gomulu else 160),
            ("gorev", "Departman / Görev", 110 if gomulu else 160),
            ("telefon", "Tel", 80 if gomulu else 110),
            ("email", "E-posta", 90 if gomulu else 150),
            ("dogum", "Doğum günü", 64 if gomulu else 80),
            ("foto", "Foto", 34),
            ("ana", "Ana", 36 if gomulu else 50),
            ("durum", "Durum", 48 if gomulu else 60),
        ):
            self.tablo.heading(k, text=b)
            self.tablo.column(k, width=w, anchor="w", stretch=k not in ("foto", "ana"))
        self.tablo.tag_configure("cift", background=STRIPE)
        self.tablo.tag_configure("tek", background=BEYAZ)
        self.tablo.pack(side="left", fill="both", expand=True, padx=(4 if gomulu else 8, 0), pady=(0, 6))
        self.tablo.bind("<Double-1>", lambda _e: self._duzenle())
        self.tablo.bind("<Button-3>", self._sag_tik)
        self.tablo.bind("<F2>", lambda _e: self._duzenle())
        self.tablo.bind("<<TreeviewSelect>>", lambda _e: self._secim_degisti())

        self._kayitlar: list[dict[str, Any]] = []
        self._yetki_durumu_ayarla()
        self.yenile()

    def cari_degisti(self):
        """Kart başka cariye yerinde geçti: liste ve fotoğraf o cariye bağlanır."""
        cari = getattr(self.dialog, "cari", None)
        self._cari_id = int(cari.id) if cari is not None and getattr(cari, "id", None) else None
        self._yetki_durumu_ayarla()
        self.yenile()

    def _yetki_durumu_ayarla(self):
        izinli = CariYetkiliService.duzenleme_izinli()
        for b in (self._btn_duzenle, self._btn_pasif, self._btn_sil):
            try:
                b.configure(state="normal" if izinli and self._cari_id else "disabled")
            except tk.TclError:
                pass
        try:
            # Kaydedilmemiş caride de form açılır; kayıtta önce cari kaydı istenir.
            self._btn_yeni.configure(state="normal" if izinli else "disabled")
        except tk.TclError:
            pass

    def yenile(self, secilecek_id: int | None = None):
        for i in self.tablo.get_children():
            self.tablo.delete(i)
        self._kayitlar = []
        if not self._cari_id:
            self._ozet_lbl.configure(text="Cari kaydedilince yetkililer burada listelenir")
            self.foto.sahip_ata(None)
            return
        try:
            self._kayitlar = CariYetkiliService.listele(self._cari_id, pasifler_dahil=True)
        except Exception:
            self._kayitlar = []
        for i, k in enumerate(self._kayitlar):
            gorev = " / ".join(x for x in (k.get("departman"), k.get("gorev")) if x) or k.get("unvan") or ""
            self.tablo.insert(
                "",
                "end",
                iid=str(k["id"]),
                tags=("cift" if i % 2 else "tek",),
                values=(
                    k.get("ad_soyad") or "",
                    gorev,
                    k.get("cep_telefonu") or "",
                    k.get("email") or "",
                    dogum_gunu_metni(k),
                    "●" if k.get("foto_var") else "",
                    "Evet" if k.get("ana_yetkili") else "",
                    "Aktif" if k.get("aktif") else "Pasif",
                ),
            )
        ana = next((k for k in self._kayitlar if k.get("ana_yetkili") and k.get("aktif")), None)
        if ana:
            self._ozet_lbl.configure(
                text=f"Ana: {ana.get('ad_soyad')}  ·  {ana.get('cep_telefonu') or '—'}  ·  {ana.get('email') or '—'}"
            )
        else:
            self._ozet_lbl.configure(text=f"{len([k for k in self._kayitlar if k.get('aktif')])} yetkili")
        if secilecek_id and self.tablo.exists(str(secilecek_id)):
            self.tablo.selection_set(str(secilecek_id))
            self.tablo.see(str(secilecek_id))
        else:
            self._secim_degisti()

    def _secim_degisti(self):
        k = self._secili()
        self.foto.sahip_ata(int(k["id"]) if k else None, cari_id=self._cari_id)

    def _secili(self) -> dict[str, Any] | None:
        sec = self.tablo.selection()
        if not sec:
            return None
        try:
            kid = int(sec[0])
        except (TypeError, ValueError):
            return None
        return next((k for k in self._kayitlar if k["id"] == kid), None)

    def _cari_kaydet(self) -> int | None:
        """Yetkili formundan istenen cari kaydı; başarılıysa yeni cari kimliği."""
        try:
            if not self.dialog.kaydet():
                return None
        except tk.TclError:
            return None
        cari = getattr(self.dialog, "cari", None)
        if cari is None or not getattr(cari, "id", None):
            return None
        self._cari_id = int(cari.id)
        self._yetki_durumu_ayarla()
        return self._cari_id

    def _kaydedildi(self, sonuc: dict[str, Any]):
        self.yenile(secilecek_id=int(sonuc["id"]))

    def _yeni(self):
        YetkiliDialog(self.dialog, cari_id=self._cari_id, on_kaydet=self._kaydedildi,
                      cari_kaydet=self._cari_kaydet)

    def _duzenle(self):
        k = self._secili()
        if not k:
            messagebox.showinfo("Yetkili", "Önce satır seçin.", parent=self.dialog)
            return
        YetkiliDialog(self.dialog, cari_id=self._cari_id, yetkili=k, on_kaydet=self._kaydedildi)

    def _pasif(self):
        k = self._secili()
        if not k:
            return
        if not messagebox.askyesno("Pasife Al", f"{k.get('ad_soyad')} pasife alınsın mı?", parent=self.dialog):
            return
        try:
            CariYetkiliService.pasife_al(int(k["id"]))
            self.yenile(secilecek_id=int(k["id"]))
        except Exception as hata:
            messagebox.showerror("Yetkili", str(hata), parent=self.dialog)

    def _sil(self):
        k = self._secili()
        if not k:
            return
        uyari = f"{k.get('ad_soyad')} silinsin mi?\nKayıt pasife alınıp arşivlenecektir."
        if k.get("ana_yetkili"):
            uyari = "Bu kişi ANA YETKİLİ.\n\n" + uyari
        if not messagebox.askyesno("Sil", uyari, parent=self.dialog):
            return
        try:
            CariYetkiliService.sil(int(k["id"]), fiziksel=False)
            self.yenile()
        except Exception as hata:
            messagebox.showerror("Yetkili", str(hata), parent=self.dialog)

    def _sag_tik(self, event):
        row = self.tablo.identify_row(event.y)
        if row:
            self.tablo.selection_set(row)
        menu = tk.Menu(self, tearoff=0)
        menu.add_command(label="Düzenle", command=self._duzenle)
        menu.add_command(label="Pasife Al", command=self._pasif)
        menu.add_command(label="Sil", command=self._sil)
        try:
            menu.tk_popup(event.x_root, event.y_root)
        finally:
            menu.grab_release()


class DogumGunuBildirimDialog(tk.Toplevel):
    """Ana panel bildirim — yaklaşan yetkili doğum günleri."""

    def __init__(self, parent, *, gun: int = 7, on_cari_ac: Callable[[int, int | None], None] | None = None):
        super().__init__(parent)
        self._on_cari_ac = on_cari_ac
        self.transient(parent)
        self.title("Yaklaşan Doğum Günleri")
        self.geometry("780x480")
        self.configure(bg=ACIK_BG)

        ust = tk.Frame(self, bg=ACIK_BG, padx=10, pady=8)
        ust.pack(fill="x")
        tk.Label(ust, text="Aralık (gün):", bg=ACIK_BG).pack(side="left")
        self._gun = tk.StringVar(value=str(gun))
        ttk.Entry(ust, textvariable=self._gun, width=6).pack(side="left", padx=6)
        tk_buton(ust, "7 gün", lambda: self._gun_ayarla(7), rol="ara").pack(side="left", padx=2)
        tk_buton(ust, "30 gün", lambda: self._gun_ayarla(30), rol="ara").pack(side="left", padx=2)
        tk_buton(ust, "Yenile", self.yenile, rol="ara").pack(side="left", padx=6)

        filtre = tk.Frame(self, bg=ACIK_BG, padx=10, pady=4)
        filtre.pack(fill="x")
        tk.Label(filtre, text="Cari türü:", bg=ACIK_BG).pack(side="left")
        self._cari_turu = tk.StringVar(value="Tümü")
        ttk.Combobox(
            filtre,
            textvariable=self._cari_turu,
            values=("Tümü", "Müşteri", "Tedarikçi"),
            state="readonly",
            width=12,
        ).pack(side="left", padx=6)
        tk.Label(filtre, text="Grup:", bg=ACIK_BG).pack(side="left", padx=(8, 0))
        self._grup = tk.StringVar(value="")
        ttk.Entry(filtre, textvariable=self._grup, width=18).pack(side="left", padx=6)
        self._hatirlat_kapali = tk.BooleanVar(value=False)
        ttk.Checkbutton(
            filtre, text="Hatırlatması kapalıları da göster", variable=self._hatirlat_kapali
        ).pack(side="left", padx=12)

        kolonlar = ("gun", "tarih", "kisi", "cari", "tel", "yas")
        self.tablo = ttk.Treeview(self, columns=kolonlar, show="headings", height=14)
        for k, b, w in (
            ("gun", "Kalan", 60),
            ("tarih", "Doğum günü", 100),
            ("kisi", "Yetkili", 160),
            ("cari", "Cari", 200),
            ("tel", "Telefon", 110),
            ("yas", "Yaş", 50),
        ):
            self.tablo.heading(k, text=b)
            self.tablo.column(k, width=w)
        self.tablo.pack(fill="both", expand=True, padx=10, pady=6)
        self.tablo.bind("<Double-1>", self._ac)

        alt = tk.Frame(self, bg=ACIK_BG, padx=10, pady=8)
        alt.pack(fill="x")
        tk_buton(alt, "Cari Kartı Aç", self._ac, rol="duzenle").pack(side="left")
        tk.Label(
            alt,
            text="Toplu SMS/WhatsApp/e-posta otomatik gönderilmez.",
            bg=ACIK_BG,
            fg=IKINCIL,
            font=font(8, root=self),
        ).pack(side="left", padx=12)
        tk_buton(alt, "Kapat", self.destroy, rol="ikincil").pack(side="right")
        self._kayitlar: list[dict] = []
        self.yenile()

    def _gun_ayarla(self, gun: int):
        self._gun.set(str(gun))
        self.yenile()

    def yenile(self):
        for i in self.tablo.get_children():
            self.tablo.delete(i)
        try:
            gun = int(self._gun.get() or 7)
        except ValueError:
            gun = 7
        tur = self._cari_turu.get()
        if tur == "Tümü":
            tur = None
        grup = (self._grup.get() or "").strip() or None
        try:
            self._kayitlar = CariYetkiliService.dogum_gunleri(
                gun=gun,
                cari_turu=tur,
                musteri_grubu=grup,
                hatirlat_kapali_dahil=bool(self._hatirlat_kapali.get()),
            )
        except Exception as hata:
            messagebox.showerror("Bildirim", str(hata), parent=self)
            self._kayitlar = []
        for i, k in enumerate(self._kayitlar):
            self.tablo.insert(
                "",
                "end",
                iid=str(i),
                values=(
                    k.get("gun_kaldi"),
                    _tarih_goster(k.get("sonraki_dogum")),
                    k.get("ad_soyad"),
                    f"{k.get('cari_kodu')} — {k.get('cari_unvan')}",
                    k.get("cep_telefonu") or "",
                    k.get("yas") if k.get("yas") is not None else "",
                ),
            )

    def _ac(self, _e=None):
        sec = self.tablo.selection()
        if not sec:
            return
        try:
            idx = int(sec[0])
        except (TypeError, ValueError):
            return
        if not (0 <= idx < len(self._kayitlar)):
            return
        k = self._kayitlar[idx]
        if self._on_cari_ac:
            self._on_cari_ac(int(k["cari_id"]), int(k["yetkili_id"]))
        self.destroy()
