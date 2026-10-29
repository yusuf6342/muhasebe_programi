"""Faiz / masraf ürün tanım ekranı — oranlar, bileşenler, valör/tatil kuralları (DOC2-18/19)."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal, InvalidOperation
import subprocess
import sys
import tkinter as tk
from tkinter import messagebox, ttk
from pathlib import Path


def _d(val) -> Decimal:
    try:
        return Decimal(str(val).replace(",", ".").strip())
    except (InvalidOperation, AttributeError, ValueError):
        raise ValueError("Geçerli bir oran girin (örn. 3,5 → %3,5).")


def faiz_urun_tanim_goster(app, *, urun_turu: str = "KK", urun_id: int | None = None):
    """Ana uygulama içinden açılır; banka/KK menülerinden çağrılabilir."""
    FaizUrunTanimDialog(app, urun_turu=urun_turu, urun_id=urun_id)


class FaizUrunTanimDialog(tk.Toplevel):
    """Ürün oranları (AKDI/GECIKME/NAKIT) + valör/tatil kuralı + görev kurucu."""

    def __init__(self, parent, *, urun_turu: str = "KK", urun_id: int | None = None):
        super().__init__(parent)
        self.title("Faiz ve Masraf Tanımları")
        self.resizable(True, True)
        self.transient(parent)
        try:
            self.grab_set()
        except tk.TclError:
            pass

        self._urun_turu = (urun_turu or "KK").upper()
        self._parent = parent

        frm = ttk.Frame(self, padding=12)
        frm.pack(fill="both", expand=True)

        ttk.Label(frm, text="Faiz ve Masraf Tanımları", font=("", 11, "bold")).grid(
            row=0, column=0, columnspan=4, sticky="w", pady=(0, 8)
        )

        ttk.Label(frm, text="Ürün türü").grid(row=1, column=0, sticky="w")
        self.urun_turu_var = tk.StringVar(value=self._urun_turu)
        ttk.Combobox(
            frm,
            textvariable=self.urun_turu_var,
            values=("KK", "KREDI", "KMH"),
            state="readonly",
            width=12,
        ).grid(row=1, column=1, sticky="w", padx=4)

        ttk.Label(frm, text="Ürün ID").grid(row=1, column=2, sticky="w", padx=(12, 0))
        self.urun_id_var = tk.StringVar(value=str(urun_id or 1))
        ttk.Entry(frm, textvariable=self.urun_id_var, width=10).grid(
            row=1, column=3, sticky="w", padx=4
        )

        # --- Oranlar ---
        oran_fr = ttk.LabelFrame(frm, text="Oranlar (% — örn. 3,5 = %3,5)", padding=8)
        oran_fr.grid(row=2, column=0, columnspan=4, sticky="ew", pady=8)
        self._oran_vars: dict[str, dict[str, tk.StringVar]] = {}
        for i, (kod, etiket) in enumerate(
            (("AKDI", "Akdi faiz"), ("GECIKME", "Gecikme faizi"), ("NAKIT_AVANS", "Nakit avans"))
        ):
            ttk.Label(oran_fr, text=etiket).grid(row=i, column=0, sticky="w", pady=2)
            oran = tk.StringVar()
            donem = tk.StringVar(value="YILLIK")
            esas = tk.StringVar(value="360")
            ttk.Entry(oran_fr, textvariable=oran, width=10).grid(row=i, column=1, padx=4)
            ttk.Combobox(
                oran_fr, textvariable=donem, values=("YILLIK", "AYLIK"), width=8, state="readonly"
            ).grid(row=i, column=2, padx=4)
            ttk.Combobox(
                oran_fr,
                textvariable=esas,
                values=("360", "365", "GERCEK"),
                width=8,
                state="readonly",
            ).grid(row=i, column=3, padx=4)
            self._oran_vars[kod] = {"oran": oran, "donem": donem, "gun_esasi": esas}

        # --- Valör / tatil ---
        kur_fr = ttk.LabelFrame(frm, text="Valör / tatil kuralı (eksikse tahakkuk uydurma yapmaz)", padding=8)
        kur_fr.grid(row=3, column=0, columnspan=4, sticky="ew", pady=8)
        self.tatil_var = tk.StringVar(value="")
        self.min_gun_var = tk.StringVar(value="1")
        self.valor_mod_var = tk.StringVar(value="TAKVIM")
        self.valor_kaydir_var = tk.StringVar(value="0")

        ttk.Label(kur_fr, text="Tatil takvimi kaynağı").grid(row=0, column=0, sticky="w")
        ttk.Combobox(
            kur_fr,
            textvariable=self.tatil_var,
            values=("", "BANKA", "RESMI", "OZEL"),
            width=12,
            state="readonly",
        ).grid(row=0, column=1, sticky="w", padx=4)
        ttk.Label(kur_fr, text="Aynı gün min. faiz günü").grid(row=0, column=2, sticky="w", padx=(12, 0))
        ttk.Entry(kur_fr, textvariable=self.min_gun_var, width=6).grid(row=0, column=3, sticky="w", padx=4)

        ttk.Label(kur_fr, text="Valör modu").grid(row=1, column=0, sticky="w", pady=4)
        ttk.Combobox(
            kur_fr,
            textvariable=self.valor_mod_var,
            values=("TAKVIM", "IS_GUNU", "TATIL_ATLA"),
            width=12,
            state="readonly",
        ).grid(row=1, column=1, sticky="w", padx=4)
        ttk.Label(kur_fr, text="Valör kaydır (gün)").grid(row=1, column=2, sticky="w", padx=(12, 0))
        ttk.Entry(kur_fr, textvariable=self.valor_kaydir_var, width=6).grid(
            row=1, column=3, sticky="w", padx=4
        )

        # --- Bileşenler (bilgi) ---
        bil = ttk.LabelFrame(frm, text="Kart borç bileşenleri (hesap motoru)", padding=8)
        bil.grid(row=4, column=0, columnspan=4, sticky="ew", pady=4)
        ttk.Label(
            bil,
            text="ALISVERIS · NAKIT · ASGARI_EKSIK — ayrı matrah; aynı gün/bileşen mükerrer faiz yok.",
            wraplength=520,
        ).pack(anchor="w")

        btn = ttk.Frame(frm)
        btn.grid(row=5, column=0, columnspan=4, sticky="ew", pady=(12, 0))
        ttk.Button(btn, text="Yükle", command=self._yukle).pack(side="left", padx=2)
        ttk.Button(btn, text="Kaydet", command=self._kaydet).pack(side="left", padx=2)
        ttk.Button(btn, text="Otomatik görevi kur", command=self._gorev_kur).pack(side="left", padx=8)
        ttk.Button(btn, text="Kapat", command=self.destroy).pack(side="right", padx=2)

        self._yukle()
        self.geometry("640x480")

    def _urun(self) -> tuple[str, int]:
        tur = (self.urun_turu_var.get() or "KK").upper()
        try:
            uid = int(str(self.urun_id_var.get()).strip())
        except ValueError as exc:
            raise ValueError("Ürün ID sayı olmalıdır.") from exc
        if uid <= 0:
            raise ValueError("Ürün ID pozitif olmalıdır.")
        return tur, uid

    def _yukle(self):
        from database.gunluk_faiz_service import GunlukFaizService

        try:
            tur, uid = self._urun()
        except ValueError as e:
            messagebox.showwarning("Ürün", str(e), parent=self)
            return
        GunlukFaizService.schema_hazirla()
        for kod, vars_ in self._oran_vars.items():
            oran = GunlukFaizService.aktif_oran(tur, uid, kod)
            if oran is None:
                vars_["oran"].set("")
                vars_["donem"].set("YILLIK")
                vars_["gun_esasi"].set("360")
            else:
                vars_["oran"].set(str(oran.oran_yuzde).replace(".", ","))
                vars_["donem"].set(oran.donem or "YILLIK")
                vars_["gun_esasi"].set(str(oran.gun_esasi or "360"))
        kural = GunlukFaizService.urun_kurali_getir(tur, uid)
        if kural is None:
            self.tatil_var.set("")
            self.min_gun_var.set("1")
            self.valor_mod_var.set("TAKVIM")
            self.valor_kaydir_var.set("0")
        else:
            self.tatil_var.set(kural.tatil_takvim_kaynagi or "")
            self.min_gun_var.set(
                "" if kural.ayni_gun_min_gun is None else str(kural.ayni_gun_min_gun)
            )
            self.valor_mod_var.set(kural.valor_mod or "TAKVIM")
            self.valor_kaydir_var.set(str(kural.valor_kaydir_gun or 0))

    def _kaydet(self):
        from database.gunluk_faiz_service import GunlukFaizService

        try:
            tur, uid = self._urun()
            for kod, vars_ in self._oran_vars.items():
                metin = (vars_["oran"].get() or "").strip()
                if not metin:
                    continue
                oran = _d(metin)
                if oran <= 0:
                    raise ValueError(f"{kod}: oran pozitif olmalıdır.")
                GunlukFaizService.oran_kaydet(
                    urun_turu=tur,
                    urun_id=uid,
                    faiz_turu=kod,
                    oran_yuzde=oran,
                    donem=vars_["donem"].get() or "YILLIK",
                    gun_esasi=vars_["gun_esasi"].get() or "360",
                    baslangic_tarihi=date.today(),
                    kaynak_not=f"UI {datetime.now():%Y-%m-%d %H:%M}",
                )
            min_gun_s = (self.min_gun_var.get() or "").strip()
            min_gun = int(min_gun_s) if min_gun_s else None
            kaydir = int((self.valor_kaydir_var.get() or "0").strip() or 0)
            GunlukFaizService.urun_kurali_kaydet(
                urun_turu=tur,
                urun_id=uid,
                tatil_takvim_kaynagi=(self.tatil_var.get() or None) or None,
                ayni_gun_min_gun=min_gun,
                valor_mod=self.valor_mod_var.get() or None,
                valor_kaydir_gun=kaydir,
            )
        except ValueError as e:
            messagebox.showwarning("Kayıt", str(e), parent=self)
            return
        except Exception as e:
            messagebox.showerror("Kayıt", str(e), parent=self)
            return
        messagebox.showinfo("Kayıt", "Oranlar ve valör/tatil kuralı kaydedildi.", parent=self)

    def _gorev_kur(self):
        """Windows Task Scheduler — scripts/gunluk_faiz_gorev_kur.ps1."""
        root = Path(__file__).resolve().parent
        ps1 = root / "scripts" / "gunluk_faiz_gorev_kur.ps1"
        if not ps1.is_file():
            messagebox.showerror(
                "Görev",
                f"Kurulum betiği bulunamadı:\n{ps1}",
                parent=self,
            )
            return
        try:
            r = subprocess.run(
                [
                    "powershell",
                    "-NoProfile",
                    "-ExecutionPolicy",
                    "Bypass",
                    "-File",
                    str(ps1),
                ],
                capture_output=True,
                text=True,
                cwd=str(root),
                timeout=120,
            )
        except Exception as e:
            messagebox.showerror("Görev", str(e), parent=self)
            return
        out = ((r.stdout or "") + "\n" + (r.stderr or "")).strip()
        if r.returncode != 0:
            messagebox.showerror("Görev", out or f"Çıkış kodu {r.returncode}", parent=self)
            return
        messagebox.showinfo(
            "Görev",
            out or "Günlük faiz görevi kuruldu / güncellendi (tek görev; çoğalmaz).",
            parent=self,
        )


def _cli():
    root = tk.Tk()
    root.withdraw()
    faiz_urun_tanim_goster(root)
    root.mainloop()


if __name__ == "__main__":
    _cli()
    sys.exit(0)
