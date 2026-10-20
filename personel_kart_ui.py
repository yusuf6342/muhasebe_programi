"""Personel kartı — fotoğraf + sekmeler."""

from __future__ import annotations

import io
import tkinter as tk
from datetime import date
from tkinter import filedialog, messagebox, ttk

from ana_panel_tema import ACIK_BG, BEYAZ, CIZGI, LACIVERT, SARI, FONT_UI, FONT_UI_BOLD, METIN
from database.models.personel import CALISMA_DURUMLARI, KIMLIK_TURLERI, UCRET_TURLERI
from database.personel_belge_service import PersonelBelgeService
from database.personel_finans_service import PersonelFinansService
from database.personel_foto_service import DOSYA_FILTRESI, PersonelFotoService, goruntu_hazirla
from database.personel_puantaj_service import PersonelIzinService
from database.personel_service import PersonelService
from database.personel_sgk_service import PersonelSgkService


class PersonelKartDialog(tk.Toplevel):
    def __init__(self, app, personel_id: int | None = None):
        super().__init__(app)
        self.app = app
        self.personel_id = personel_id
        self.title("Personel Kartı")
        self.geometry("980x700")
        self.minsize(900, 620)
        self.configure(bg=ACIK_BG)
        self.transient(app)
        self._foto_pil = None
        self._foto_tk = None
        self._foto_bekleyen = None
        self._kur()
        if personel_id:
            self.yukle(personel_id)
        else:
            try:
                self.kod_var.set(PersonelService.sonraki_kod())
            except Exception:
                self.kod_var.set("P0001")
            self.giris_var.set(date.today().isoformat())

    def _kur(self):
        # Üst araç çubuğu
        bar = tk.Frame(self, bg=LACIVERT)
        bar.pack(fill="x")
        for metin, cmd in (
            ("Kaydet", self.kaydet),
            ("Vazgeç", self.destroy),
            ("Personel Bul", self.bul),
            ("Yeni Kart", self.yeni),
        ):
            tk.Button(
                bar, text=metin, command=cmd, bg=SARI, fg=LACIVERT,
                font=FONT_UI_BOLD, relief="flat", padx=12, pady=6, cursor="hand2",
            ).pack(side="left", padx=4, pady=6)

        # Üst kimlik + foto
        ust = tk.Frame(self, bg=BEYAZ, highlightbackground=CIZGI, highlightthickness=1)
        ust.pack(fill="x", padx=10, pady=8)
        ust.columnconfigure(1, weight=1)

        foto_cer = tk.Frame(ust, bg=BEYAZ)
        foto_cer.grid(row=0, column=0, rowspan=4, padx=10, pady=10, sticky="n")
        # ~3x4 oran: 120x160
        self.foto_tuval = tk.Canvas(
            foto_cer, width=120, height=160, bg="#F1F4F9",
            highlightthickness=1, highlightbackground=CIZGI,
        )
        self.foto_tuval.pack()
        self._foto_yer_tutucu()
        fb = tk.Frame(foto_cer, bg=BEYAZ)
        fb.pack(fill="x", pady=(4, 0))
        tk.Button(fb, text="Ekle", command=self.foto_ekle, relief="flat", bg=LACIVERT, fg=BEYAZ).pack(
            side="left", expand=True, fill="x", padx=1
        )
        tk.Button(fb, text="Kaldır", command=self.foto_kaldir, relief="flat", bg=LACIVERT, fg=BEYAZ).pack(
            side="left", expand=True, fill="x", padx=1
        )

        form = tk.Frame(ust, bg=BEYAZ)
        form.grid(row=0, column=1, sticky="nwe", padx=8, pady=10)
        self.kod_var = tk.StringVar()
        self.ad_var = tk.StringVar()
        self.soyad_var = tk.StringVar()
        self.gorev_var = tk.StringVar()
        self.sube_var = tk.StringVar()
        self.durum_var = tk.StringVar(value="AKTIF")
        self.kimlik_tur_var = tk.StringVar(value="TCKN")
        self.kimlik_var = tk.StringVar()
        self.dogum_var = tk.StringVar()
        self.tel_var = tk.StringVar()
        self.eposta_var = tk.StringVar()
        self.adres_var = tk.StringVar()
        self.bolum_var = tk.StringVar()
        self.isyeri_var = tk.StringVar()
        self.sicil_var = tk.StringVar()
        self.giris_var = tk.StringVar()
        self.cikis_var = tk.StringVar()
        self.meslek_var = tk.StringVar()
        self.ucret_tur_var = tk.StringVar(value="NET")
        self.ucret_var = tk.StringVar()
        self.ucret_bas_var = tk.StringVar(value=date.today().isoformat())
        self.iban_var = tk.StringVar()
        self.donem_id = None

        satirlar = [
            ("Personel kodu", self.kod_var),
            ("Ad", self.ad_var),
            ("Soyad", self.soyad_var),
            ("Görev", self.gorev_var),
            ("Şube", self.sube_var),
        ]
        for i, (etiket, var) in enumerate(satirlar):
            tk.Label(form, text=etiket, bg=BEYAZ, fg=METIN, font=FONT_UI).grid(
                row=i, column=0, sticky="w", pady=2
            )
            ttk.Entry(form, textvariable=var, width=28).grid(row=i, column=1, sticky="w", pady=2)

        tk.Label(form, text="Çalışma durumu", bg=BEYAZ, fg=METIN, font=FONT_UI).grid(
            row=0, column=2, sticky="w", padx=(16, 0)
        )
        ttk.Combobox(
            form, textvariable=self.durum_var,
            values=[k for k, _ in CALISMA_DURUMLARI], width=18, state="readonly",
        ).grid(row=0, column=3, sticky="w")

        # Finans özeti
        self.finans_lbl = tk.Label(
            ust, text="", bg=BEYAZ, fg=LACIVERT, font=FONT_UI, justify="left", anchor="w"
        )
        self.finans_lbl.grid(row=4, column=0, columnspan=2, sticky="we", padx=10, pady=(0, 8))

        # Sekmeler
        nb = ttk.Notebook(self)
        nb.pack(fill="both", expand=True, padx=10, pady=(0, 10))
        self.sekme_genel = tk.Frame(nb, bg=BEYAZ)
        self.sekme_calisma = tk.Frame(nb, bg=BEYAZ)
        self.sekme_ucret = tk.Frame(nb, bg=BEYAZ)
        self.sekme_sgk = tk.Frame(nb, bg=BEYAZ)
        self.sekme_izin = tk.Frame(nb, bg=BEYAZ)
        self.sekme_ozluk = tk.Frame(nb, bg=BEYAZ)
        self.sekme_hesap = tk.Frame(nb, bg=BEYAZ)
        self.sekme_gecmis = tk.Frame(nb, bg=BEYAZ)
        for frame, ad in (
            (self.sekme_genel, "Genel Bilgiler"),
            (self.sekme_calisma, "Çalışma Bilgileri"),
            (self.sekme_ucret, "Ücret ve Banka"),
            (self.sekme_sgk, "SGK Bilgileri"),
            (self.sekme_izin, "Puantaj ve İzin"),
            (self.sekme_ozluk, "Özlük Belgeleri"),
            (self.sekme_hesap, "Hesap Hareketleri"),
            (self.sekme_gecmis, "Geçmiş"),
        ):
            nb.add(frame, text=ad)

        self._alan(self.sekme_genel, [
            ("Kimlik türü", None),
            ("Kimlik no", self.kimlik_var),
            ("Doğum tarihi", self.dogum_var),
            ("Telefon", self.tel_var),
            ("E-posta", self.eposta_var),
            ("Adres", self.adres_var),
        ], ekstra_kimlik=True)

        self._alan(self.sekme_calisma, [
            ("Bölüm", self.bolum_var),
            ("İşyeri kodu", self.isyeri_var),
            ("İşyeri sicil", self.sicil_var),
            ("Giriş tarihi", self.giris_var),
            ("Çıkış tarihi", self.cikis_var),
            ("Meslek kodu", self.meslek_var),
        ])

        self._alan(self.sekme_ucret, [
            ("Ücret türü", None),
            ("Tutar", self.ucret_var),
            ("Geçerlilik başlangıç", self.ucret_bas_var),
            ("IBAN", self.iban_var),
        ], ekstra_ucret=True)

        self.sgk_text = tk.Text(self.sekme_sgk, height=12, wrap="word")
        self.sgk_text.pack(fill="both", expand=True, padx=8, pady=8)
        self.izin_text = tk.Text(self.sekme_izin, height=12, wrap="word")
        self.izin_text.pack(fill="both", expand=True, padx=8, pady=8)
        self.ozluk_tree = ttk.Treeview(
            self.sekme_ozluk, columns=("tur", "durum", "gec"), show="headings", height=12
        )
        for k, b in zip(("tur", "durum", "gec"), ("Belge", "Durum", "Geçerlilik")):
            self.ozluk_tree.heading(k, text=b)
            self.ozluk_tree.column(k, width=180)
        self.ozluk_tree.pack(fill="both", expand=True, padx=8, pady=8)
        oz_bar = tk.Frame(self.sekme_ozluk, bg=BEYAZ)
        oz_bar.pack(fill="x", padx=8, pady=(0, 8))
        tk.Button(
            oz_bar, text="Belge Yükle", command=self.belge_yukle,
            bg=LACIVERT, fg=BEYAZ, relief="flat",
        ).pack(side="left")

        self.hesap_tree = ttk.Treeview(
            self.sekme_hesap, columns=("tur", "tarih", "tutar"), show="headings", height=12
        )
        for k, b in zip(("tur", "tarih", "tutar"), ("Tür", "Tarih", "Tutar")):
            self.hesap_tree.heading(k, text=b)
        self.hesap_tree.pack(fill="both", expand=True, padx=8, pady=8)
        self.gecmis_text = tk.Text(self.sekme_gecmis, height=12, wrap="word")
        self.gecmis_text.pack(fill="both", expand=True, padx=8, pady=8)

    def _alan(self, parent, alanlar, *, ekstra_kimlik=False, ekstra_ucret=False):
        f = tk.Frame(parent, bg=BEYAZ)
        f.pack(anchor="nw", padx=12, pady=12)
        row = 0
        if ekstra_kimlik:
            tk.Label(f, text="Kimlik türü", bg=BEYAZ).grid(row=0, column=0, sticky="w")
            ttk.Combobox(
                f, textvariable=self.kimlik_tur_var,
                values=[k for k, _ in KIMLIK_TURLERI], width=22, state="readonly",
            ).grid(row=0, column=1, sticky="w", pady=2)
            row = 1
        if ekstra_ucret:
            tk.Label(f, text="Ücret türü", bg=BEYAZ).grid(row=0, column=0, sticky="w")
            ttk.Combobox(
                f, textvariable=self.ucret_tur_var,
                values=[k for k, _ in UCRET_TURLERI], width=12, state="readonly",
            ).grid(row=0, column=1, sticky="w", pady=2)
            row = 1
        for etiket, var in alanlar:
            if var is None:
                continue
            tk.Label(f, text=etiket, bg=BEYAZ).grid(row=row, column=0, sticky="w", pady=2)
            ttk.Entry(f, textvariable=var, width=36).grid(row=row, column=1, sticky="w", pady=2)
            row += 1

    def _foto_yer_tutucu(self):
        self.foto_tuval.delete("all")
        self.foto_tuval.create_rectangle(2, 2, 118, 158, outline="#C5CDD8")
        self.foto_tuval.create_text(60, 80, text="Fotoğraf Yok", fill="#7A8699", font=FONT_UI)

    def _foto_ciz(self):
        self.foto_tuval.delete("all")
        if self._foto_pil is None:
            self._foto_yer_tutucu()
            return
        from PIL import Image, ImageTk

        img = self._foto_pil.copy()
        img.thumbnail((116, 156), Image.Resampling.LANCZOS)
        self._foto_tk = ImageTk.PhotoImage(img)
        x = (120 - img.width) // 2
        y = (160 - img.height) // 2
        self.foto_tuval.create_image(x, y, anchor="nw", image=self._foto_tk)

    def foto_ekle(self):
        yol = filedialog.askopenfilename(parent=self, filetypes=DOSYA_FILTRESI)
        if not yol:
            return
        try:
            hazir = goruntu_hazirla(yol)
            from PIL import Image

            with Image.open(io.BytesIO(hazir["veri"])) as im:
                im.load()
                self._foto_pil = im.copy()
            self._foto_ciz()
            if self.personel_id:
                PersonelFotoService.kaydet(self.personel_id, yol, hazir=hazir)
                self._foto_bekleyen = None
            else:
                self._foto_bekleyen = hazir
        except Exception as e:
            messagebox.showerror("Fotoğraf", str(e), parent=self)

    def foto_kaldir(self):
        self._foto_pil = None
        self._foto_bekleyen = ("KALDIR", None) if self.personel_id else None
        self._foto_ciz()
        if self.personel_id:
            try:
                PersonelFotoService.kaldir(self.personel_id)
            except Exception as e:
                messagebox.showerror("Fotoğraf", str(e), parent=self)

    def yeni(self):
        self.personel_id = None
        self.donem_id = None
        for v in (
            self.ad_var, self.soyad_var, self.gorev_var, self.sube_var, self.kimlik_var,
            self.dogum_var, self.tel_var, self.eposta_var, self.adres_var, self.bolum_var,
            self.isyeri_var, self.sicil_var, self.cikis_var, self.meslek_var, self.ucret_var,
            self.iban_var,
        ):
            v.set("")
        self.durum_var.set("AKTIF")
        self.giris_var.set(date.today().isoformat())
        self.ucret_bas_var.set(date.today().isoformat())
        try:
            self.kod_var.set(PersonelService.sonraki_kod())
        except Exception:
            pass
        self._foto_pil = None
        self._foto_bekleyen = None
        self._foto_ciz()
        self.finans_lbl.configure(text="")

    def bul(self):
        from personel_ui import personel_listesi_goster

        # Basit arama
        try:
            liste = PersonelService.listele(limit=200)
        except Exception as e:
            messagebox.showerror("Personel", str(e), parent=self)
            return
        if not liste:
            messagebox.showinfo("Personel", "Kayıt yok.", parent=self)
            return
        secenek = [f"{p['id']}|{p['kod']} — {p['ad_soyad']}" for p in liste]
        from personel_ui import _basit_secim

        s = _basit_secim(self, "Personel bul", secenek)
        if s:
            self.yukle(int(s.split("|", 1)[0]))

    def yukle(self, personel_id: int):
        try:
            k = PersonelService.getir(int(personel_id))
        except Exception as e:
            messagebox.showerror("Personel", str(e), parent=self)
            return
        self.personel_id = k["id"]
        self.kod_var.set(k["kod"])
        self.ad_var.set(k["ad"])
        self.soyad_var.set(k["soyad"])
        self.durum_var.set(k["calisma_durumu"])
        self.kimlik_tur_var.set(k.get("kimlik_turu") or "TCKN")
        self.kimlik_var.set(k.get("kimlik_no") or "")
        self.dogum_var.set(k.get("dogum_tarihi") or "")
        self.tel_var.set(k.get("telefon") or "")
        self.eposta_var.set(k.get("eposta") or "")
        self.adres_var.set(k.get("adres") or "")
        donem = next((d for d in k["donemler"] if d.get("aktif")), k["donemler"][0] if k["donemler"] else None)
        self.donem_id = donem["id"] if donem else None
        if donem:
            self.gorev_var.set(donem.get("gorev") or "")
            self.sube_var.set(donem.get("sube") or "")
            self.bolum_var.set(donem.get("bolum") or "")
            self.isyeri_var.set(donem.get("isyeri_kodu") or "")
            self.sicil_var.set(donem.get("isyeri_sicil") or "")
            self.giris_var.set(donem.get("giris_tarihi") or "")
            self.cikis_var.set(donem.get("cikis_tarihi") or "")
            self.meslek_var.set(donem.get("meslek_kodu") or "")
            uc = (donem.get("ucretler") or [None])[0]
            if uc:
                self.ucret_tur_var.set(uc.get("ucret_turu") or "NET")
                self.ucret_var.set("" if uc.get("tutar") is None else str(uc["tutar"]))
                self.ucret_bas_var.set(uc.get("gecerli_baslangic") or date.today().isoformat())
                self.iban_var.set(uc.get("iban") or "")

        # Foto
        try:
            veri = PersonelFotoService.getir(self.personel_id, kucuk=False)
            if veri:
                from PIL import Image

                with Image.open(io.BytesIO(veri)) as im:
                    im.load()
                    self._foto_pil = im.copy()
            else:
                self._foto_pil = None
            self._foto_ciz()
        except Exception:
            self._foto_pil = None
            self._foto_ciz()

        self._sekmeleri_doldur()

    def _sekmeleri_doldur(self):
        if not self.personel_id:
            return
        # Finans özeti
        try:
            oz = PersonelFinansService.ay_ozeti(self.personel_id)
            if oz.get("finans_gorur"):
                self.finans_lbl.configure(
                    text=(
                        f"Bu ay onaylı net: {oz['onayli_net_hakedis']:,.2f} TL  |  "
                        f"Mahsup avans: {oz['mahsup_edilecek_avans']:,.2f}  |  "
                        f"Ödenen: {oz['yapilan_maas_odemesi']:,.2f}  |  "
                        f"Kalan: {oz['kalan_odeme']:,.2f}"
                    )
                )
            else:
                self.finans_lbl.configure(text="Finans özeti için yetki gerekli.")
        except Exception:
            self.finans_lbl.configure(text="")

        # Özlük
        for i in self.ozluk_tree.get_children():
            self.ozluk_tree.delete(i)
        try:
            for b in PersonelBelgeService.personel_belgeleri(self.personel_id):
                self.ozluk_tree.insert(
                    "", "end",
                    values=(
                        b.get("belge_adi") or b.get("tur_ad"),
                        "Yetki yok" if b.get("erisim_yok") else b.get("durum"),
                        b.get("gecerlilik_tarihi") or "",
                    ),
                )
            for e in PersonelBelgeService.eksik_listesi(self.personel_id):
                self.ozluk_tree.insert(
                    "", "end", values=(f"[Eksik] {e['tur_ad']}", e["durum"], ""),
                )
        except Exception as ex:
            self.ozluk_tree.insert("", "end", values=(str(ex), "", ""))

        # İzin
        self.izin_text.delete("1.0", "end")
        try:
            o = PersonelIzinService.ozet(self.personel_id)
            self.izin_text.insert(
                "end",
                f"Hak: {o['hak_edilen']}  Devir: {o['onceki_devir']}  "
                f"Kullanılan: {o['kullanilan']}  Kalan: {o['kalan']}\n"
                f"Kural: {o.get('kural_surum')} / {o.get('kural_kaynak')}\n\n",
            )
            for iz in o["izinler"]:
                self.izin_text.insert(
                    "end",
                    f"{iz['baslangic']}–{iz['bitis']} {iz['izin_turu']} "
                    f"{iz['durum']} ({iz['gun']} gün)\n",
                )
        except Exception as ex:
            self.izin_text.insert("end", str(ex))

        # SGK
        self.sgk_text.delete("1.0", "end")
        try:
            for s in PersonelSgkService.listele(personel_id=self.personel_id):
                self.sgk_text.insert(
                    "end",
                    f"{s['islem_turu']} durum={s['durum']} son={s.get('son_tarih')} "
                    f"onay={s.get('onay_no') or '—'} | {s.get('uyari')}\n",
                )
            if self.isyeri_var.get() and self.sicil_var.get():
                self.sgk_text.insert(
                    "end",
                    f"\nKart SGK: işyeri={self.isyeri_var.get()} sicil={self.sicil_var.get()} "
                    f"meslek={self.meslek_var.get()}\n",
                )
        except Exception as ex:
            self.sgk_text.insert("end", str(ex))

        # Hesap
        for i in self.hesap_tree.get_children():
            self.hesap_tree.delete(i)
        try:
            for h in PersonelFinansService.hareketler(self.personel_id):
                if h["iptal"]:
                    continue
                self.hesap_tree.insert(
                    "", "end",
                    values=(h["hareket_turu"], h["tarih"], f"{h['tutar']:,.2f}"),
                )
        except Exception:
            pass

        self.gecmis_text.delete("1.0", "end")
        self.gecmis_text.insert(
            "end",
            "Ücret, görev, durum ve belge değişiklikleri servis geçmişinde tutulur. "
            "Yeniden işe girişte yeni çalışma dönemi eklenir; eski ücret taşınmaz.\n",
        )

    def belge_yukle(self):
        if not self.personel_id:
            messagebox.showwarning("Özlük", "Önce kartı kaydedin.", parent=self)
            return
        from personel_ui import ozluk_dosyalari_goster

        messagebox.showinfo(
            "Özlük",
            "Belge yüklemek için PERSONEL → Özlük Dosyaları ekranını kullanın "
            "veya kayıttan sonra o menüye gidin.",
            parent=self,
        )

    def kaydet(self):
        veri = {
            "kod": self.kod_var.get(),
            "ad": self.ad_var.get(),
            "soyad": self.soyad_var.get(),
            "kimlik_turu": self.kimlik_tur_var.get(),
            "kimlik_no": self.kimlik_var.get(),
            "dogum_tarihi": self.dogum_var.get() or None,
            "telefon": self.tel_var.get() or None,
            "eposta": self.eposta_var.get() or None,
            "adres": self.adres_var.get() or None,
            "calisma_durumu": self.durum_var.get(),
            "donem": {
                "id": self.donem_id,
                "giris_tarihi": self.giris_var.get() or date.today().isoformat(),
                "cikis_tarihi": self.cikis_var.get() or None,
                "gorev": self.gorev_var.get() or None,
                "bolum": self.bolum_var.get() or None,
                "sube": self.sube_var.get() or None,
                "isyeri_kodu": self.isyeri_var.get() or None,
                "isyeri_sicil": self.sicil_var.get() or None,
                "meslek_kodu": self.meslek_var.get() or None,
                "aktif": True,
                "ucret": {},
            },
        }
        if self.ucret_var.get().strip():
            veri["donem"]["ucret"] = {
                "ucret_turu": self.ucret_tur_var.get(),
                "tutar": self.ucret_var.get(),
                "gecerli_baslangic": self.ucret_bas_var.get(),
                "iban": self.iban_var.get() or None,
            }
        try:
            kart = PersonelService.kaydet(veri, self.personel_id)
            self.personel_id = kart["id"]
            if kart.get("donemler"):
                aktif = next((d for d in kart["donemler"] if d.get("aktif")), kart["donemler"][0])
                self.donem_id = aktif["id"]
            if self._foto_bekleyen and self._foto_bekleyen != ("KALDIR", None):
                PersonelFotoService.kaydet(self.personel_id, None, hazir=self._foto_bekleyen)
                self._foto_bekleyen = None
            messagebox.showinfo("Personel", "Kart kaydedildi.", parent=self)
            self._sekmeleri_doldur()
        except Exception as e:
            messagebox.showerror("Personel", str(e), parent=self)
