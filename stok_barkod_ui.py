"""Stok barkod etiket basımı — üstte barkod, altta ad / birim / satış fiyatı."""

from __future__ import annotations

from decimal import Decimal
from html import escape
from pathlib import Path
import tempfile
import tkinter as tk
from tkinter import messagebox, ttk
import webbrowser

from database.stok_service import StokService

# Code 128B patterns (start B=104, stop=106); her değer 11 bit (son stop 13)
_CODE128 = [
    "11011001100", "11001101100", "11001100110", "10010011000", "10010001100",
    "10001001100", "10011001000", "10011000100", "10001100100", "11001001000",
    "11001000100", "11000100100", "10110011100", "10011011100", "10011001110",
    "10111001100", "10011101100", "10011100110", "11001110010", "11001011100",
    "11001001110", "11011100100", "11001110100", "11101101110", "11101001100",
    "11100101100", "11100100110", "11101100100", "11100110100", "11100110010",
    "11011011000", "11011000110", "11000110110", "10100011000", "10001011000",
    "10001000110", "10110001000", "10001101000", "10001100010", "11010001000",
    "11000101000", "11000100010", "10110111000", "10110001110", "10001101110",
    "10111011000", "10111000110", "10001110110", "11101110110", "11010001110",
    "11000101110", "11011101000", "11011100010", "11011101110", "11101011000",
    "11101000110", "11100010110", "11101101000", "11101100010", "11100011010",
    "11101111010", "11001000010", "11110001010", "10100110000", "10100001100",
    "10010110000", "10010000110", "10000101100", "10000100110", "10110010000",
    "10110000100", "10011010000", "10011000010", "10000110100", "10000110010",
    "11000010010", "11001010000", "11110111010", "11000010100", "10001111010",
    "10100111100", "10010111100", "10010011110", "10111100100", "10011110100",
    "10011110010", "11110100100", "11110010100", "11110010010", "11011011110",
    "11011110110", "11110110110", "10101111000", "10100011110", "10001011110",
    "10111101000", "10111100010", "11110101000", "11110100010", "10111011110",
    "10111101110", "11101011110", "11110101110", "11010000100", "11010010000",
    "11010011100", "1100011101011",
]


def _para(tutar):
    return f"{float(tutar):,.2f} TL".replace(",", "X").replace(".", ",").replace("X", ".")


def code128_svg(metin: str, yukseklik: int = 70, modul: int = 2) -> str:
    """Code 128B barkod SVG üretir."""
    veri = (metin or "").strip()
    if not veri:
        return ""
    # Code 128B: ASCII 32–127
    kodlar = [104]  # Start B
    for ch in veri:
        kod = ord(ch) - 32
        if kod < 0 or kod > 95:
            kod = ord("?") - 32
        kodlar.append(kod)
    toplam = kodlar[0]
    for i, k in enumerate(kodlar[1:], start=1):
        toplam += k * i
    kodlar.append(toplam % 103)
    kodlar.append(106)  # Stop

    bits = "".join(_CODE128[k] for k in kodlar)
    genislik = len(bits) * modul
    dikeyler = []
    x = 0
    for bit in bits:
        if bit == "1":
            dikeyler.append(
                f'<rect x="{x}" y="0" width="{modul}" height="{yukseklik}" fill="#000"/>'
            )
        x += modul
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{genislik}" height="{yukseklik + 18}" '
        f'viewBox="0 0 {genislik} {yukseklik + 18}">'
        f'{"".join(dikeyler)}'
        f'<text x="{genislik / 2}" y="{yukseklik + 14}" text-anchor="middle" '
        f'font-family="Consolas, monospace" font-size="12">{escape(veri)}</text>'
        f"</svg>"
    )


def etiket_fiyati(stok, barkod_kayit=None) -> Decimal:
    """Etikette gösterilecek satış fiyatı."""
    if barkod_kayit is not None:
        bf = Decimal(str(barkod_kayit.fiyat or 0))
        if bf > 0:
            return bf
        fiyat_adi = (barkod_kayit.fiyat_adi or "").strip()
        if fiyat_adi:
            for f in stok.fiyatlar:
                if (f.fiyat_adi or "").strip().upper() == fiyat_adi.upper():
                    return Decimal(str(f.tutar))
    return StokService.satis_fiyati_1(stok.stok_kodu, Decimal("0"))


def etiket_kayitlari(stoklar=None):
    """Yazdırılabilir etiket satırları listesi."""
    kayitlar = []
    for stok in stoklar if stoklar is not None else StokService.stoklari_ara():
        birimler = []
        if stok.barkodlar:
            for b in stok.barkodlar:
                kod = (b.barkod or "").strip()
                if not kod:
                    continue
                birimler.append(
                    {
                        "stok_id": stok.id,
                        "stok_kodu": stok.stok_kodu,
                        "stok_adi": stok.stok_adi,
                        "barkod": kod,
                        "birim": (b.birim or stok.birim or "Adet"),
                        "fiyat": etiket_fiyati(stok, b),
                    }
                )
        ana = (stok.barkod or "").strip()
        if ana and not any(k["barkod"] == ana for k in birimler):
            birimler.insert(
                0,
                {
                    "stok_id": stok.id,
                    "stok_kodu": stok.stok_kodu,
                    "stok_adi": stok.stok_adi,
                    "barkod": ana,
                    "birim": stok.birim or "Adet",
                    "fiyat": etiket_fiyati(stok, None),
                },
            )
        kayitlar.extend(birimler)
    return kayitlar


def etiket_html(etiketler, kopya=1, genislik_mm=58, yukseklik_mm=36) -> str:
    """
    Şablon: üstte barkod, altta stok adı, birim ve satış fiyatı.
    Boyut mm cinsinden (yazıcıdaki etiket kağıdına göre ayarlanır).
    """
    kopya = max(1, int(kopya))
    try:
        genislik_mm = max(20.0, float(genislik_mm))
        yukseklik_mm = max(15.0, float(yukseklik_mm))
    except (TypeError, ValueError):
        genislik_mm, yukseklik_mm = 58.0, 36.0

    # Boyuta göre barkod yüksekliği ve yazı punto
    barkod_h = max(28, min(90, int(yukseklik_mm * 1.6)))
    modul = 2 if genislik_mm >= 45 else 1
    ad_pt = 9 if yukseklik_mm < 28 else (11 if yukseklik_mm < 45 else 13)
    alt_pt = 8 if yukseklik_mm < 28 else 10
    pad = 2 if yukseklik_mm < 28 else 3

    kartlar = []
    for et in etiketler:
        svg = code128_svg(et["barkod"], yukseklik=barkod_h, modul=modul)
        ad = escape(et["stok_adi"] or "")
        birim = escape(et.get("birim") or "Adet")
        fiyat = escape(_para(et.get("fiyat") or 0))
        kod = escape(et.get("stok_kodu") or "")
        for _ in range(kopya):
            kartlar.append(
                f"""
                <div class="etiket">
                  <div class="barkod">{svg}</div>
                  <div class="ad">{ad}</div>
                  <div class="alt">
                    <span class="birim">{birim}</span>
                    <span class="fiyat">{fiyat}</span>
                  </div>
                  <div class="kod">{kod}</div>
                </div>
                """
            )
    govde = "\n".join(kartlar)
    return f"""<!DOCTYPE html>
<html lang="tr">
<head>
<meta charset="utf-8"/>
<title>Stok Barkod Etiketleri ({genislik_mm:g}×{yukseklik_mm:g} mm)</title>
<style>
  @page {{
    size: {genislik_mm}mm {yukseklik_mm}mm;
    margin: 0;
  }}
  * {{ box-sizing: border-box; }}
  body {{
    font-family: "Segoe UI", Arial, sans-serif;
    margin: 0;
    padding: 8px;
    background: #f0f0f0;
  }}
  .toolbar {{
    background: #fff;
    padding: 10px 14px;
    margin-bottom: 12px;
    border: 1px solid #ccc;
    border-radius: 6px;
  }}
  .toolbar button {{
    font-size: 14px;
    padding: 8px 16px;
    cursor: pointer;
  }}
  .sayfa {{
    display: flex;
    flex-wrap: wrap;
    gap: 6px;
    justify-content: flex-start;
  }}
  .etiket {{
    width: {genislik_mm}mm;
    height: {yukseklik_mm}mm;
    background: #fff;
    border: 1px dashed #999;
    padding: {pad}mm;
    text-align: center;
    page-break-after: always;
    page-break-inside: avoid;
    overflow: hidden;
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: flex-start;
  }}
  .barkod {{
    width: 100%;
    flex: 1 1 auto;
    display: flex;
    justify-content: center;
    align-items: center;
    min-height: 0;
  }}
  .barkod svg {{
    max-width: 100%;
    max-height: 100%;
    height: auto;
  }}
  .ad {{
    font-size: {ad_pt}pt;
    font-weight: 700;
    line-height: 1.15;
    margin: 0.5mm 0;
    max-width: 100%;
    word-wrap: break-word;
    flex: 0 0 auto;
  }}
  .alt {{
    display: flex;
    justify-content: space-between;
    width: 100%;
    font-size: {alt_pt}pt;
    gap: 4px;
    flex: 0 0 auto;
  }}
  .birim {{ color: #333; }}
  .fiyat {{ font-weight: 700; }}
  .kod {{
    font-size: 7pt;
    color: #666;
    margin-top: 0.5mm;
    flex: 0 0 auto;
  }}
  @media print {{
    body {{ background: #fff; padding: 0; margin: 0; }}
    .toolbar {{ display: none; }}
    .sayfa {{ gap: 0; }}
    .etiket {{
      border: none;
      margin: 0;
      width: {genislik_mm}mm;
      height: {yukseklik_mm}mm;
    }}
  }}
</style>
</head>
<body>
  <div class="toolbar">
    <strong>Etiket:</strong> {genislik_mm:g} × {yukseklik_mm:g} mm —
    Üst: barkod · Alt: ad, birim, satış fiyatı.
    Yazdırırken kağıt boyutunu da bu ölçüye ayarlayın (veya «Sayfa boyutu: Etiket»).
    &nbsp; <button onclick="window.print()">Yazdır</button>
  </div>
  <div class="sayfa">
    {govde}
  </div>
</body>
</html>
"""


ETIKET_HAZIR_BOYUTLAR = (
    ("30 × 20 mm", 30, 20),
    ("40 × 25 mm", 40, 25),
    ("40 × 30 mm", 40, 30),
    ("50 × 30 mm", 50, 30),
    ("58 × 40 mm", 58, 40),
    ("60 × 40 mm", 60, 40),
    ("70 × 50 mm", 70, 50),
    ("100 × 50 mm", 100, 50),
    ("Özel…", None, None),
)


def _etiket_ayar_yolu() -> Path:
    from database.database import BASE_DIR

    return BASE_DIR / "data" / "etiket_ayarlari.json"


def etiket_ayarlarini_yukle() -> dict:
    yol = _etiket_ayar_yolu()
    varsayilan = {"genislik_mm": 58.0, "yukseklik_mm": 40.0, "kopya": 1}
    if not yol.exists():
        return varsayilan
    try:
        import json

        veri = json.loads(yol.read_text(encoding="utf-8"))
        varsayilan.update({k: veri[k] for k in varsayilan if k in veri})
    except Exception:
        pass
    return varsayilan


def etiket_ayarlarini_kaydet(ayarlar: dict) -> None:
    try:
        import json

        yol = _etiket_ayar_yolu()
        yol.parent.mkdir(parents=True, exist_ok=True)
        yol.write_text(json.dumps(ayarlar, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception:
        pass


class StokBarkodBasimSayfasi:
    """MuhasebeApp içine gömülen barkod basım ekranı."""

    def __init__(self, app):
        self.app = app
        self.secimler = {}  # iid -> etiket dict
        self._kur()

    def _kur(self):
        app = self.app
        app._icerigi_temizle()
        for dugme_anahtari, dugme in app.menu_dugmeleri.items():
            dugme.configure(
                style="SeciliMenu.TButton" if dugme_anahtari == "stoklar" else "Menu.TButton"
            )
        ttk.Label(app.icerik, text="STOK BARKOD BASIMI", style="Baslik.TLabel").pack(anchor="w")
        ttk.Label(
            app.icerik,
            text=(
                "Şablon: üstte barkod, altta stok adı · birim · satış fiyatı. "
                "Etiket boyutunu mm olarak seçin (hazır ölçüler veya özel). "
                "Yazdırırken yazıcıda da aynı kağıt/etiket boyutunu kullanın."
            ),
            wraplength=820,
            justify="left",
        ).pack(anchor="w", pady=(10, 6))

        ayar = etiket_ayarlarini_yukle()

        ust = ttk.Frame(app.icerik)
        ust.pack(fill="x", pady=6)
        ttk.Label(ust, text="Ara:").pack(side="left")
        self.arama = ttk.Entry(ust, width=22)
        self.arama.pack(side="left", padx=6)
        self.arama.bind("<Return>", lambda _e: self.listeyi_yenile())
        ttk.Button(ust, text="Ara", command=self.listeyi_yenile).pack(side="left")

        ttk.Label(ust, text="Boyut:").pack(side="left", padx=(12, 4))
        self.boyut_secim = ttk.Combobox(
            ust,
            values=[b[0] for b in ETIKET_HAZIR_BOYUTLAR],
            state="readonly",
            width=14,
        )
        self.boyut_secim.pack(side="left")
        self.boyut_secim.bind("<<ComboboxSelected>>", self._boyut_secildi)

        ttk.Label(ust, text="En mm").pack(side="left", padx=(10, 2))
        self.genislik_mm = ttk.Spinbox(ust, from_=20, to=200, increment=1, width=6)
        self.genislik_mm.set(str(ayar.get("genislik_mm", 58)))
        self.genislik_mm.pack(side="left")
        ttk.Label(ust, text="Boy mm").pack(side="left", padx=(8, 2))
        self.yukseklik_mm = ttk.Spinbox(ust, from_=15, to=200, increment=1, width=6)
        self.yukseklik_mm.set(str(ayar.get("yukseklik_mm", 40)))
        self.yukseklik_mm.pack(side="left")

        # Kaydedilmiş ölçüye en yakın hazır boyutu seç
        self._boyut_eslestir(
            float(ayar.get("genislik_mm", 58)),
            float(ayar.get("yukseklik_mm", 40)),
        )

        ttk.Label(ust, text="Kopya:").pack(side="left", padx=(12, 4))
        self.kopya = ttk.Spinbox(ust, from_=1, to=99, width=5)
        self.kopya.set(str(ayar.get("kopya", 1)))
        self.kopya.pack(side="left")
        ttk.Button(ust, text="← Stoklar Menüsü", command=lambda: app.sayfa_goster("stoklar")).pack(
            side="right"
        )

        orta = ttk.Frame(app.icerik)
        orta.pack(fill="both", expand=True, pady=6)
        kolonlar = ("sec", "barkod", "kod", "ad", "birim", "fiyat")
        self.tablo = ttk.Treeview(orta, columns=kolonlar, show="headings", selectmode="extended")
        for k, b, w in (
            ("sec", "Seç", 45),
            ("barkod", "Barkod", 140),
            ("kod", "Stok Kodu", 110),
            ("ad", "Stok Adı", 260),
            ("birim", "Birim", 70),
            ("fiyat", "Satış Fiyatı", 110),
        ):
            self.tablo.heading(k, text=b)
            self.tablo.column(k, width=w, anchor="w")
        self.tablo.column("sec", width=45, anchor="center", stretch=False)
        kaydirma = ttk.Scrollbar(orta, orient="vertical", command=self.tablo.yview)
        self.tablo.configure(yscrollcommand=kaydirma.set)
        self.tablo.pack(side="left", fill="both", expand=True)
        kaydirma.pack(side="right", fill="y")
        self.tablo.bind("<Button-1>", self._secim_tikla)
        self.tablo.bind("<Double-1>", lambda _e: self.onizle_secili())

        onizleme = ttk.LabelFrame(app.icerik, text="Etiket şablonu (önizleme)", padding=10)
        onizleme.pack(fill="x", pady=6)
        self.onizleme_cerceve = tk.Canvas(onizleme, height=150, bg="white", highlightthickness=1)
        self.onizleme_cerceve.pack(fill="x")
        self._sablon_ciz(None)

        alt = ttk.Frame(app.icerik)
        alt.pack(fill="x", pady=8)
        ttk.Button(alt, text="Tümünü Seç", command=self.tumunu_sec).pack(side="left")
        ttk.Button(alt, text="Seçimi Temizle", command=self.secimi_temizle).pack(side="left", padx=6)
        ttk.Button(alt, text="Önizleme", command=self.onizle_secili).pack(side="left", padx=6)
        ttk.Button(alt, text="Etiket Yazdır…", command=self.yazdir).pack(side="right")

        self._kayitlar = []
        self.listeyi_yenile()

    def _boyut_eslestir(self, en, boy):
        for ad, w, h in ETIKET_HAZIR_BOYUTLAR:
            if w is not None and abs(w - en) < 0.1 and abs(h - boy) < 0.1:
                self.boyut_secim.set(ad)
                return
        self.boyut_secim.set("Özel…")

    def _boyut_secildi(self, _e=None):
        sec = self.boyut_secim.get()
        for ad, w, h in ETIKET_HAZIR_BOYUTLAR:
            if ad == sec and w is not None:
                self.genislik_mm.delete(0, "end")
                self.genislik_mm.insert(0, str(w))
                self.yukseklik_mm.delete(0, "end")
                self.yukseklik_mm.insert(0, str(h))
                return

    def _boyut_oku(self):
        try:
            en = float(str(self.genislik_mm.get()).replace(",", "."))
            boy = float(str(self.yukseklik_mm.get()).replace(",", "."))
        except ValueError as hata:
            raise ValueError("Etiket en/boy mm sayı olmalıdır.") from hata
        if en < 20 or boy < 15:
            raise ValueError("Etiket eni en az 20 mm, boyu en az 15 mm olmalıdır.")
        return en, boy

    def listeyi_yenile(self):
        arama = self.arama.get().strip()
        stoklar = StokService.stoklari_ara(arama)
        self._kayitlar = etiket_kayitlari(stoklar)
        self.secimler.clear()
        for item in self.tablo.get_children():
            self.tablo.delete(item)
        for i, k in enumerate(self._kayitlar):
            iid = str(i)
            self.tablo.insert(
                "",
                "end",
                iid=iid,
                values=(
                    "☐",
                    k["barkod"],
                    k["stok_kodu"],
                    k["stok_adi"],
                    k["birim"],
                    _para(k["fiyat"]),
                ),
            )

    def _secim_tikla(self, event):
        if self.tablo.identify_region(event.x, event.y) != "cell":
            return
        if self.tablo.identify_column(event.x) != "#1":
            return
        satir = self.tablo.identify_row(event.y)
        if not satir:
            return
        idx = int(satir)
        if idx in self.secimler:
            del self.secimler[idx]
            self.tablo.set(satir, "sec", "☐")
        else:
            self.secimler[idx] = self._kayitlar[idx]
            self.tablo.set(satir, "sec", "☑")
            self._sablon_ciz(self._kayitlar[idx])
        return "break"

    def tumunu_sec(self):
        self.secimler = {i: k for i, k in enumerate(self._kayitlar)}
        for iid in self.tablo.get_children():
            self.tablo.set(iid, "sec", "☑")

    def secimi_temizle(self):
        self.secimler.clear()
        for iid in self.tablo.get_children():
            self.tablo.set(iid, "sec", "☐")
        self._sablon_ciz(None)

    def _secili_liste(self):
        if self.secimler:
            return [self.secimler[i] for i in sorted(self.secimler)]
        # Seçim yoksa treeview seçimi
        sonuc = []
        for iid in self.tablo.selection():
            try:
                sonuc.append(self._kayitlar[int(iid)])
            except (ValueError, IndexError):
                pass
        return sonuc

    def onizle_secili(self):
        liste = self._secili_liste()
        if not liste:
            messagebox.showinfo("Seçim", "Önizlemek için bir barkod seçin.", parent=self.app)
            return
        self._sablon_ciz(liste[0])

    def _sablon_ciz(self, etiket):
        c = self.onizleme_cerceve
        c.delete("all")
        w = max(c.winfo_width(), 520)
        # Kart çerçevesi
        c.create_rectangle(20, 10, 300, 140, outline="#888", dash=(3, 2))
        c.create_text(160, 18, text="ETİKET ŞABLONU", font=("Segoe UI", 8), fill="#888")
        if not etiket:
            c.create_text(160, 75, text="Barkod seçince önizleme burada", fill="#999")
            return
        # Basit barkod çizgileri (görsel önizleme)
        barkod = etiket["barkod"]
        x0 = 40
        for i, ch in enumerate(barkod[:24]):
            kalin = 2 if (ord(ch) + i) % 3 else 1
            c.create_rectangle(x0, 28, x0 + kalin, 78, fill="#000", outline="")
            x0 += kalin + 1
        c.create_text(160, 90, text=barkod, font=("Consolas", 9))
        c.create_text(160, 108, text=etiket["stok_adi"][:40], font=("Segoe UI", 10, "bold"))
        c.create_text(
            160,
            128,
            text=f"{etiket['birim']}    {_para(etiket['fiyat'])}",
            font=("Segoe UI", 9),
        )
        # Sağda açıklama
        c.create_text(
            360,
            50,
            anchor="w",
            justify="left",
            text="Üst: Barkod\nAlt: Stok adı\n      Birim + Satış fiyatı",
            font=("Segoe UI", 10),
        )

    def yazdir(self):
        liste = self._secili_liste()
        if not liste:
            messagebox.showwarning("Seçim", "Yazdırılacak barkod etiketlerini seçin.", parent=self.app)
            return
        try:
            kopya = int(self.kopya.get())
            en, boy = self._boyut_oku()
        except ValueError as hata:
            messagebox.showerror("Boyut", str(hata), parent=self.app)
            return
        etiket_ayarlarini_kaydet({"genislik_mm": en, "yukseklik_mm": boy, "kopya": kopya})
        html = etiket_html(liste, kopya=kopya, genislik_mm=en, yukseklik_mm=boy)
        klasor = Path(tempfile.gettempdir()) / "muhasebe_etiket"
        klasor.mkdir(exist_ok=True)
        dosya = klasor / "barkod_etiketleri.html"
        dosya.write_text(html, encoding="utf-8")
        webbrowser.open(dosya.as_uri())
        messagebox.showinfo(
            "Yazdırma",
            f"{len(liste)} etiket (×{kopya}) — {en:g}×{boy:g} mm\n"
            "Tarayıcıda açıldı. Yazdırırken kağıt/etiket boyutunu aynı mm değere ayarlayın.",
            parent=self.app,
        )


def stok_barkod_basimi_goster(app):
    StokBarkodBasimSayfasi(app)
