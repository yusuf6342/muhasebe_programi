"""Evo anlık görüntüsünden aktarım planı: alan eşleştirme, bakiye hesabı ve satır bazında bulgular.

Veritabanına dokunmaz. Önizleme, aktarım ve mutabakat aynı planı kullanır; böylece önizlemede
gösterilen ile yazılan aynıdır.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

from entegrasyon.cari_acilis_import import parse_evobulut_bakiye
from entegrasyon.cari_import import map_evobulut_api_satir as cari_map
from entegrasyon.stok_import import map_evobulut_api_satir as stok_map

SIFIR = Decimal("0")
KURUS = Decimal("0.01")

# Evo MUSTIP → yerel cari türü. Evo türü ayrıca müşteri grubunda korunur.
CARI_TUR_HARITASI = {
    "müşteri": "Müşteri",
    "perakende müşteriler": "Müşteri",
    "tedarikçi": "Tedarikçi",
    "hizmet satıcılar": "Tedarikçi",
    "personel": "Personel",
}


def tr_kucuk(metin: str) -> str:
    return (metin or "").strip().replace("İ", "i").replace("I", "ı").lower()

DOVIZ_SEMBOL = {"TL": "TRY", "₺": "TRY", "$": "USD", "€": "EUR", "£": "GBP"}

# Evo cari listesinde olup Cin Muhasebe cari kartında karşılığı olmayan / bu aktarımda yazılmayan alanlar
CARI_KARSILIKSIZ = {
    "R.a_isk_oran": "Cari iskonto oranı (cari kartta alan yok)",
    "personel": "Sorumlu personel",
    "R.a_per_id": "Sorumlu personel kimliği",
    "FS.a_adi": "Firma faaliyet sektörü",
    "R.a_firma_faaliyet_tur": "Firma faaliyet türü kodu",
    "R.a_kimdir": "Yetkili kişi (serbest metin)",
    "R.a_hitap": "Hitap",
    "H.a_adi": "Hitap adı",
    "R.a_ver_tar": "Vergi levhası tarihi",
    "R.a_baba": "Baba adı",
    "R.a_dogtar": "Doğum tarihi",
    "ULKE.a_adi": "Ülke",
}
STOK_KARSILIKSIZ = {
    "a_dip_fiyat": "Dip (taban) fiyat",
    "a_envfiy": "Envanter fiyatı",
    "a_en": "En", "a_boy": "Boy", "a_cap": "Çap", "a_yuk": "Yükseklik",
    "a_url_web": "Web adresi", "a_url_img": "Resim adresi", "a_url_dok": "Doküman adresi",
    "muafiyet_kodu": "KDV muafiyet kodu",
}


def d(v: Any) -> Decimal:
    s = str(v if v is not None else "").strip().replace(" ", "")
    if not s:
        return SIFIR
    try:
        return Decimal(s.replace(",", "."))
    except (InvalidOperation, ValueError):
        return SIFIR


def _tarih(s: str | None) -> datetime:
    s = (s or "").strip()
    for f in ("%d.%m.%Y %H:%M:%S", "%d.%m.%Y"):
        try:
            return datetime.strptime(s[:19] if len(s) > 10 else s, f)
        except ValueError:
            continue
    return datetime.min


def maskele(metin: str) -> str:
    """Kart numarası gibi uzun rakam dizilerinin yalnız son 4 hanesi görünsün."""
    def _m(eslesme: re.Match) -> str:
        rakam = re.sub(r"\D", "", eslesme.group(0))
        return f"****{rakam[-4:]}"

    return re.sub(r"\d[\d ]{9,}\d", _m, metin or "")


@dataclass
class Bulgu:
    alan: str  # cari | stok | kasa | banka | genel
    evo_id: str
    ad: str
    seviye: str  # hata | uyari | bilgi
    mesaj: str


@dataclass
class Plan:
    kaynak_dosya: str
    kaynak_sha256: str
    cekilme_zamani: str
    devir_tarihi: date
    cariler: list[dict] = field(default_factory=list)
    stoklar: list[dict] = field(default_factory=list)
    finans: list[dict] = field(default_factory=list)
    bulgular: list[Bulgu] = field(default_factory=list)
    karsiliksiz_alanlar: list[dict] = field(default_factory=list)
    kaynak_verilmedi: list[dict] = field(default_factory=list)
    bakiye_dosyasi: str = ""
    bakiye_sha256: str = ""

    def bulgu(self, alan, evo_id, ad, seviye, mesaj):
        self.bulgular.append(Bulgu(alan, str(evo_id), maskele(str(ad))[:80], seviye, mesaj))


def anlik_oku(yol: str | Path) -> tuple[dict, str]:
    ham = Path(yol).read_bytes()
    return json.loads(ham.decode("utf-8")), hashlib.sha256(ham).hexdigest()


# ---------------------------------------------------------------- cari

def _cari_plani(plan: Plan, cariler: list[dict]) -> None:
    for s in cariler:
        evo_id = str(s.get("R.a_id") or "").strip()
        evo_tur = (s.get("MUSTIP.a_adi") or "").strip()
        tur = CARI_TUR_HARITASI.get(tr_kucuk(evo_tur), "Müşteri")
        veriler = cari_map(s, varsayilan_tur=tur)
        veriler["cari_turu"] = tur
        veriler.pop("cari_kodu", None)  # kod Cin tarafından üretilir; Evo kodu müşteri notunda korunur
        grup = evo_tur or "Türü belirtilmemiş"
        veriler["musteri_grubu"] = f"Evo: {grup}"[:100]
        notlar = [veriler.get("ozel_notlar") or ""]
        evo_kod = (s.get("R.a_kod") or "").strip()
        notlar.append(f"Evo cari id {evo_id}" + (f", Evo kod {evo_kod}" if evo_kod else ""))
        veriler["ozel_notlar"] = " | ".join(n for n in notlar if n)[:1000]
        vade_s = d(s.get("R.a_vguns"))
        vade_a = d(s.get("R.a_vguna"))
        if vade_s > 0:
            veriler["satis_vade_gunu"] = int(vade_s)
        if vade_a > 0:
            veriler["alis_vade_gunu"] = int(vade_a)
        if (s.get("R.a_vergidairesi") or "").strip() and not veriler.get("vergi_dairesi"):
            veriler["vergi_dairesi"] = s["R.a_vergidairesi"].strip()[:100]

        ham_vkn = re.sub(r"\D", "", s.get("R.a_verginosu") or "")
        if ham_vkn and not (veriler.get("vergi_numarasi") or veriler.get("tc_kimlik")):
            plan.bulgu("cari", evo_id, veriler.get("unvan"), "uyari",
                       f"Vergi/TC no geçersiz uzunlukta ({len(ham_vkn)} hane), aktarılmadı")
        if tr_kucuk(evo_tur) not in CARI_TUR_HARITASI:
            plan.bulgu("cari", evo_id, veriler.get("unvan"), "bilgi",
                       f"Evo türü '{evo_tur or 'boş'}' Cin'de yok; Müşteri olarak açıldı, grup alanında korunuyor")

        bakiye = parse_evobulut_bakiye(s)
        metin = s.get("text") or ""
        if bakiye is None and not re.search(r"Bakiye\s*:\s*0*[.,]?0*\s*\(", metin):
            plan.bulgu("cari", evo_id, veriler.get("unvan"), "hata", "Bakiye metni çözülemedi; açılış yazılmadı")
        tutar, yon = (bakiye if bakiye else (SIFIR, ""))
        plan.cariler.append({
            "evo_id": evo_id,
            "evo_tur": evo_tur,
            "tur": tur,
            "veriler": veriler,
            "tutar": tutar,
            "yon": yon,
            "aktif": True,
        })
        for alan, aciklama in CARI_KARSILIKSIZ.items():
            deger = str(s.get(alan) or "").strip()
            if deger and deger not in {"0", "Türkiye"}:
                plan.karsiliksiz_alanlar.append(
                    {"alan": "cari", "evo_id": evo_id, "kaynak_alan": alan, "aciklama": aciklama, "deger": maskele(deger)[:60]}
                )
    adlar = Counter(c["veriler"].get("unvan", "").casefold() for c in plan.cariler)
    for c in plan.cariler:
        if adlar[c["veriler"].get("unvan", "").casefold()] > 1:
            plan.bulgu("cari", c["evo_id"], c["veriler"].get("unvan"), "uyari",
                       "Aynı unvanlı başka Evo carisi var; ayrı kart olarak aktarılır (Evo kimliğiyle eşleşir)")


# ---------------------------------------------------------------- stok

def _stok_plani(plan: Plan, stoklar: list[dict]) -> None:
    sayac = Counter((s.get("a_kod") or "").strip() for s in stoklar)
    gorulen: set[str] = set()
    for s in sorted(stoklar, key=lambda x: int(x.get("a_id") or 0)):
        evo_id = str(s.get("a_id") or "").strip()
        veriler = stok_map(s)
        ad = veriler.get("stok_adi") or ""
        kod = (veriler.get("stok_kodu") or "").strip()
        if not kod:
            kod = f"EVO-{evo_id}"
            plan.bulgu("stok", evo_id, ad, "uyari", f"Evo'da stok kodu boş; '{kod}' kodu verildi")
        elif sayac[kod] > 1:
            if kod in gorulen:
                yeni = f"{kod}-E{evo_id}"[:50]
                plan.bulgu("stok", evo_id, ad, "uyari",
                           f"Mükerrer stok kodu {kod}: ilk kart bu kodla, bu kart '{yeni}' koduyla açıldı")
                kod = yeni
            else:
                plan.bulgu("stok", evo_id, ad, "uyari", f"Mükerrer stok kodu {kod}: bu kart kodu korudu")
            veriler["barkod"] = None
        gorulen.add((veriler.get("stok_kodu") or "").strip())
        veriler["stok_kodu"] = kod
        kdv = d(s.get("a_kdv_sat"))
        if kdv not in {Decimal(x) for x in ("0", "1", "8", "10", "18", "20")}:
            plan.bulgu("stok", evo_id, ad, "hata", f"Geçersiz KDV oranı {s.get('a_kdv_sat')}; KDV boş bırakıldı")
            veriler.pop("kdv_orani", None)

        doviz = DOVIZ_SEMBOL.get((s.get("doviz_al_sembol") or "TL").strip(), None)
        if doviz is None:
            plan.bulgu("stok", evo_id, ad, "hata", f"Tanınmayan alış para birimi {s.get('doviz_al_sembol')!r}")
            doviz = "?"
        if DOVIZ_SEMBOL.get((s.get("doviz_sat_sembol") or "TL").strip()) not in {"TRY"}:
            plan.bulgu("stok", evo_id, ad, "uyari", f"Satış fiyatı dövizli ({s.get('doviz_sat_sembol')})")
        birim = (s.get("ana_birim_adi") or "").strip()
        if not birim:
            plan.bulgu("stok", evo_id, ad, "uyari", "Evo'da ana birim boş; 'Adet' kullanıldı")

        kalan = d(s.get("a_kalan")).quantize(Decimal("0.000001")) + SIFIR
        alis = d(s.get("a_fiyat_al"))
        if kalan < 0:
            plan.bulgu("stok", evo_id, ad, "hata", f"Evo miktarı negatif ({kalan}); açılış stoku yazılmadı")
        elif kalan > 0 and alis <= 0:
            plan.bulgu("stok", evo_id, ad, "uyari", "Miktar var ama Evo son alış fiyatı 0; devir maliyeti 0")
        plan.stoklar.append({
            "evo_id": evo_id,
            "veriler": veriler,
            "kalan": kalan,
            "alis_fiyati": alis,
            "alis_doviz": doviz,
            "satis_fiyati": d(s.get("a_fiyat_sat")),
            "satis_doviz": DOVIZ_SEMBOL.get((s.get("doviz_sat_sembol") or "TL").strip(), "?"),
            "kdv": kdv,
            "aktif": veriler.get("aktif", True),
        })
        for alan, aciklama in STOK_KARSILIKSIZ.items():
            deger = str(s.get(alan) or "").strip()
            if deger and deger not in {"0", "TL"}:
                plan.karsiliksiz_alanlar.append(
                    {"alan": "stok", "evo_id": evo_id, "kaynak_alan": alan, "aciklama": aciklama, "deger": deger[:60]}
                )


# ---------------------------------------------------------------- kasa / banka

def finans_sinifi(ad: str, posmu: bool) -> str:
    on = (ad or "").strip()[:3].strip()
    if on.startswith("00") or (posmu and not on.startswith(("02", "03"))):
        return "POS_BAGLI"
    if on.startswith("01"):
        return "MEVDUAT"
    if on.startswith("02"):
        return "KREDI_KARTI"
    if on.startswith("03"):
        return "KREDILER"
    return "KARSILIKSIZ"


def _dogrudan_bakiye(plan: Plan, tur: str, evo_id: str, ad: str, hareket_net: Decimal,
                     dogrudan: dict | None) -> tuple[Decimal, str]:
    """Evo'nun kendi bakiye toplamı esastır; hareket toplamı yalnız kontrol amaçlıdır."""
    from entegrasyon.evo_devir.guncel_bakiye import bakiye

    kayit = (dogrudan or {}).get((tur, evo_id))
    deger = bakiye(kayit) if kayit else None
    if deger is None:
        plan.bulgu(tur, evo_id, ad, "uyari", "Evo doğrudan bakiyesi alınamadı; hareket toplamı kullanıldı")
        return hareket_net, "hareket_toplami"
    dv = d(deger).quantize(KURUS) + SIFIR
    if not kayit.get("filtre_dogru"):
        plan.bulgu(tur, evo_id, ad, "hata", "Evo bakiye raporu hesap filtresi tutmadı")
    if dv != hareket_net:
        plan.bulgu(tur, evo_id, ad, "uyari",
                   f"Evo doğrudan bakiye {dv} ile hareket toplamı {hareket_net} farklı (fark {dv - hareket_net})")
    return dv, "evo_dogrudan_bakiye"


def _finans_plani(plan: Plan, kasalar, bankalar, kasa_h, banka_h, dogrudan: dict | None = None) -> None:
    devir = datetime.combine(plan.devir_tarihi, datetime.max.time())

    def grupla(hareketler, alan):
        g = defaultdict(list)
        for h in hareketler:
            g[str(h.get(alan) or "").strip()].append(h)
        return g

    kg = grupla(kasa_h, "G.a_kasa_id")
    for k in kasalar:
        kid = str(k.get("id"))
        ad_k = (k.get("text") or "").strip()
        tum = kg.get(kid, [])
        sonra = [h for h in tum if _tarih(h.get("G.a_tarih")) > devir]
        hs = [h for h in tum if _tarih(h.get("G.a_tarih")) <= devir]
        hareket_net = sum((d(h.get("G.a_giren")) - d(h.get("G.a_cikan")) for h in hs), SIFIR).quantize(KURUS)
        net, kaynak = _dogrudan_bakiye(plan, "kasa", kid, ad_k, hareket_net, dogrudan)
        doviz = DOVIZ_SEMBOL.get((k.get("doviz_kodu") or "TL").strip(), "?")
        kayit = {
            "evo_tur": "kasa", "evo_id": kid, "ad": ad_k, "sinif": "KASA",
            "doviz": doviz, "hareket_sayisi": len(hs), "net": net, "hedefler": {"KASA": net},
            "bakiye_kaynagi": kaynak, "hareket_toplami": hareket_net,
            "ilk_hareket": min((_tarih(h.get("G.a_tarih")) for h in hs), default=None),
        }
        plan.finans.append(kayit)
        if net < 0:
            plan.bulgu("kasa", kid, kayit["ad"], "hata",
                       f"Evo kasa bakiyesi eksi ({net}); kasada eksi bakiye olmaz, Evo'da eksik/yanlış kayıt var. "
                       "Tutar Evo'daki haliyle aktarıldı, düzeltme uydurulmadı")
        if sonra:
            plan.bulgu("kasa", kid, kayit["ad"], "uyari", f"Devir tarihinden sonra {len(sonra)} hareket var; bakiyeye katılmadı")

    bg = grupla(banka_h, "G.a_banka_id")
    for b in bankalar:
        bid = str(b.get("id"))
        ad = (b.get("text") or "").strip()
        posmu = str(b.get("a_posmu") or "0").strip() == "1"
        sinif = finans_sinifi(ad, posmu)
        hs = [h for h in bg.get(bid, []) if _tarih(h.get("G.a_tarih")) <= devir]
        hareket_net = sum((d(h.get("G.a_giren")) - d(h.get("G.a_cikan")) for h in hs), SIFIR).quantize(KURUS)
        net, kaynak = _dogrudan_bakiye(plan, "banka", bid, maskele(ad), hareket_net, dogrudan)
        doviz = DOVIZ_SEMBOL.get((b.get("DOV_Kodu") or "TL").strip(), "?")
        hedefler: dict[str, Decimal] = {}
        notlar: list[str] = []
        pos_bekleyen = SIFIR
        if sinif == "POS_BAGLI":
            bekleyen = [
                h for h in hs
                if str(h.get("G.a_pos_bloke") or "0").strip() not in {"", "0"} and _tarih(h.get("G.a_vtarih")) > devir
            ]
            pos_bekleyen = sum((d(h.get("G.a_giren")) for h in bekleyen), SIFIR).quantize(KURUS)
            mevduat = net - pos_bekleyen
            hedefler = {"KMH" if mevduat < 0 else "MEVDUAT": mevduat, "POS": pos_bekleyen}
            if pos_bekleyen:
                notlar.append(f"{len(bekleyen)} blokeli POS tahsilatının valörü devirden sonra: POS alacağı {pos_bekleyen}"
                              " (Evo bakiye raporu blokeli tutarı ayırmadığı için hareket satırlarından hesaplandı)")
            if mevduat < 0:
                notlar.append("POS alacağı düşülünce mevduat eksi; tutar KMH alt hesabına yazılır")
                plan.bulgu("banka", bid, ad, "uyari", f"POS bağlı hesapta mevduat eksi ({mevduat}); KMH alt hesabına yazıldı")
        elif sinif == "MEVDUAT":
            if net < 0:
                hedefler = {"KMH": net}
                notlar.append("Eksi bakiye KMH (ek hesap) kullanımı olarak KMH alt hesabına yazılır")
            else:
                hedefler = {"MEVDUAT": net}
        elif sinif == "KREDI_KARTI":
            borc = -net
            hedefler = {"KREDI_KARTI": borc}
            if borc < 0:
                plan.bulgu("banka", bid, ad, "uyari", f"Kredi kartında alacak bakiyesi ({-borc}); fazla ödeme olabilir")
            gelecek = [h for h in bg.get(bid, []) if _tarih(h.get("G.a_vtarih")) > devir]
            if gelecek:
                notlar.append(f"{len(gelecek)} işlemin ödeme/valör tarihi devirden sonra; taksit planı Cin'e ayrıca girilmeli")
        elif sinif == "KREDILER":
            borc = -net
            hedefler = {"KREDILER": borc}
            if borc < 0:
                plan.bulgu("banka", bid, ad, "uyari", f"Kredi hesabında alacak bakiyesi ({-borc})")
            notlar.append("Kalan anapara/faiz ayrımı ve ödeme planı kaynakta yok; bakiye KREDİLER alt hesabına borç olarak yazılır")
        else:
            notlar.append("Cin Muhasebe'de karşılığı yok (menkul kıymet vb.); aktarılmadı")
            plan.bulgu("banka", bid, ad, "uyari", f"Karşılığı olmayan hesap türü; bakiye {net} aktarılmadı")
        plan.finans.append({
            "evo_tur": "banka", "evo_id": bid, "ad": ad, "ad_maskeli": maskele(ad), "sinif": sinif,
            "posmu": posmu, "doviz": doviz, "evo_kod": maskele((b.get("a_kod") or "").strip()),
            "kart_son4": re.sub(r"\D", "", b.get("a_kod") or "")[-4:] if sinif == "KREDI_KARTI" else "",
            "pos_valor_gun": int(d(b.get("a_posgun")) or 1),
            "hareket_sayisi": len(hs), "net": net, "pos_bekleyen": pos_bekleyen,
            "bakiye_kaynagi": kaynak, "hareket_toplami": hareket_net,
            "hedefler": hedefler, "notlar": notlar,
        })


# ---------------------------------------------------------------- plan

KAYNAKTA_YOK = "Kaynakta yok"
HENUZ_ALINAMADI = "Henüz alınamadı"
TAMAMLANDI = "Aktarımı tamamlandı"

# (kalem, durum, neden, Cin'de aktarılacağı yer, çift etki kuralı)
KAYNAK_VERILMEDI = [
    ("Kredi ödeme planları (taksit, anapara/faiz ayrımı)", KAYNAKTA_YOK,
     "Evo'da kredi modülü yok; yalnız kredi hesabının kalan bakiyesi var (aktarıldı)",
     "Banka kredisi + taksitler, ilgili Evo kredi banka kartına bağlı (detay_aktarim, Kredi_Odeme_Plani)",
     "Kredi ve taksitler hareketsiz yazılır (kullandırım hareketi/fişi yok); hesabın kalan anapara toplamı "
     "aktarılan KREDİLER bakiyesine eşit değilse o hesabın planı yazılmaz. Sonraki taksit ödemesi KREDİLER'i "
     "anapara kadar bir kez azaltır"),
    ("KMH limitleri", KAYNAKTA_YOK, "Evo banka kartında limit alanı yok",
     "Banka kartı KMH limiti (detay_aktarim, KMH_Limit)", "Limit bilgisidir; bakiye/hareket yazılmaz"),
    ("Kredi kartı limiti, hesap kesim / son ödeme günü", KAYNAKTA_YOK, "Evo'da kredi kartı modülü yok",
     "Kredi kartı tanımı (detay_aktarim, Kredi_Karti)", "Tanım bilgisidir; hareket yazılmaz"),
    ("Kredi kartı ekstre borcu ve gelecek taksitler", KAYNAKTA_YOK, "Evo'da kredi kartı modülü yok",
     "Yalnız kontrol: ekstre + gelecek taksit = aktarılan KK borcu (kayıt yazılmaz)",
     "Ekstre ve taksitler aktarılan KREDİ KARTI borcunun parçasıdır; KK çekimi/ödeme evrakı olarak girilmemeli"),
    ("POS komisyon oranları", KAYNAKTA_YOK, "Evo banka kartında yalnız valör günü var",
     "Banka kartı POS taksit komisyonları (detay_aktarim, POS_Komisyon)", "Oran bilgisidir; hareket yazılmaz"),
    ("Çek ve senetler (alınan/verilen)", HENUZ_ALINAMADI,
     "Evo API'de çek/senet servisi yok; Evo ekranında kayıt tutulup tutulmadığı doğrulanmadı",
     "Çek/Senet portföyü, ilgili cariye bağlı (detay_aktarim, Cek_Senet)",
     "Evrak cari hareketi ve muhasebe fişi olmadan yazılır (tutar cari açılışında var); sonraki tahsil/ödeme "
     "yalnız kasa/banka hareketi yazar"),
    ("Müşteri/tedarikçi avans ve depozitoları (ayrı)", KAYNAKTA_YOK, "Evo cari bakiyesi tek tutar; avans ayrımı yok",
     "Cari açılış anlamı (avans işareti) / GM açılış", "Toplam cari bakiyesi değişmez; yalnız sınıflandırma"),
    ("Vergi, SGK, personel ve diğer borç/alacaklar", KAYNAKTA_YOK, "Evo'da karşılığı yok",
     "GM açılış fişi (muhasebe_fisleri)", "Kasa/banka/cari/stok satırları devir tutarlarıyla aynı olmalı; ayrıca hareket yazılmaz"),
    ("Sabit kıymetler ve birikmiş amortisman", KAYNAKTA_YOK, "Evo'da karşılığı yok", "GM açılış fişi", "-"),
    ("Sermaye ve geçmiş dönem sonuçları (GM açılış)", KAYNAKTA_YOK, "Evo'da genel muhasebe yok",
     "GM açılış fişi", "Açılış fişi alt defter (kasa/banka/cari/stok) bakiyelerini değiştirmez"),
    ("Depo bazında stok miktarı", HENUZ_ALINAMADI,
     "Evo stok listesi yalnız toplam kalan veriyor; tümü ANA DEPO'ya yazıldı",
     "Depolar arası transfer", "Yeni stok girişi değil, ANA DEPO'dan transfer olmalı"),
    ("FIFO maliyet katmanları", KAYNAKTA_YOK,
     "Evo'da yok; devir maliyeti = Evo son alış fiyatı (başlangıç devir katmanı)", "-", "-"),
    ("Stok ana/tali/alt grup, diğer birimler ve katsayılar, ek barkodlar", HENUZ_ALINAMADI,
     "Evo stok listesinde yok (yalnız rapor grubu ve ana birim)", "Stok kartı", "Mali etkisi yok"),
    ("Cari risk limiti, adres satırı, pasif durumu", HENUZ_ALINAMADI, "Evo cari listesinde bu alanlar yok",
     "Cari kart", "Mali etkisi yok"),
    ("Pasif stok/cari kartlar", HENUZ_ALINAMADI, "Evo listesi yalnız aktif kartları döndürdü",
     "Cari/stok kartı (pasif)", "Bakiyeli pasif kart varsa açılışı ayrıca aktarılmalı; aktif kart açılışlarıyla çakışmamalı"),
    ("Bekleyen sipariş, faturalanmamış irsaliye, ödeme sözleri", HENUZ_ALINAMADI,
     "Bu aktarımın kapsamı dışında bırakıldı", "İlgili evraklar", "Finansal etki yaratmadan, bekleyen olarak"),
]

AKTARILANLAR = [
    ("Cari bakiyeleri (müşteri, tedarikçi, personel)", "Cari açılış hareketi EVB-ACL-{evo id}"),
    ("Stok kartları, miktar ve devir maliyeti", "Başlangıç devir katmanı lot EVB-SG-{evo id}, ANA DEPO"),
    ("Kasa bakiyeleri", "Kasa kartının açılış bakiyesi (ayrıca hareket yazılmaz)"),
    ("Banka MEVDUAT / KMH / POS bakiyeleri", "Finans açılış hareketi EVB-FA-B{evo id}-{alt hesap}"),
    ("Kredi kartı borç bakiyeleri", "KREDİ KARTI alt hesabı açılışı + kart tanımı (son 4 hane)"),
    ("Kredi kalan borç bakiyeleri", "KREDİLER alt hesabı açılışı"),
]


def bakiye_oku(yol: str | Path | None) -> tuple[dict | None, str]:
    if not yol:
        return None, ""
    ham = Path(yol).read_bytes()
    g = json.loads(ham.decode("utf-8"))
    sozluk = {("kasa", k["id"]): k for k in g.get("kasalar", [])}
    sozluk |= {("banka", b["id"]): b for b in g.get("bankalar", [])}
    return sozluk, hashlib.sha256(ham).hexdigest()


def plan_olustur(anlik_yolu: str | Path, devir_tarihi: date, bakiye_yolu: str | Path | None = None) -> Plan:
    g, sha = anlik_oku(anlik_yolu)
    dogrudan, bakiye_sha = bakiye_oku(bakiye_yolu)
    plan = Plan(
        kaynak_dosya=str(Path(anlik_yolu).resolve()),
        kaynak_sha256=sha,
        cekilme_zamani=g.get("cekilme_zamani", ""),
        devir_tarihi=devir_tarihi,
    )
    cekilme = (g.get("cekilme_zamani") or "")[:10]
    if cekilme and cekilme != devir_tarihi.isoformat():
        plan.bulgu("genel", "-", "Anlık görüntü", "hata",
                   f"Kaynak {cekilme} tarihinde çekildi, devir tarihi {devir_tarihi}; Evo bakiyeleri çekilme anına aittir")
    _cari_plani(plan, g.get("cariler") or [])
    _stok_plani(plan, g.get("stoklar") or [])
    _finans_plani(plan, g.get("kasalar") or [], g.get("bankalar") or [],
                  g.get("kasa_hareketleri") or [], g.get("banka_hareketleri") or [], dogrudan)
    plan.bakiye_dosyasi = str(Path(bakiye_yolu).resolve()) if bakiye_yolu else ""
    plan.bakiye_sha256 = bakiye_sha
    plan.kaynak_verilmedi = [{"kalem": k, "durum": du, "neden": n, "cin_hedef": h, "cift_etki": c}
                             for k, du, n, h, c in KAYNAK_VERILMEDI]
    return plan


def ozet(plan: Plan) -> dict:
    cari_b = sum((c["tutar"] for c in plan.cariler if c["yon"] == "B"), SIFIR)
    cari_a = sum((c["tutar"] for c in plan.cariler if c["yon"] == "A"), SIFIR)
    tur_yon = Counter((c["tur"], c["yon"] or "0") for c in plan.cariler)
    stok_poz = [s for s in plan.stoklar if s["kalan"] > 0]
    finans_sinif = defaultdict(lambda: SIFIR)
    for f in plan.finans:
        for hedef, tutar in f["hedefler"].items():
            finans_sinif[hedef] += tutar
    return {
        "cari_sayisi": len(plan.cariler),
        "cari_tur": dict(Counter(c["tur"] for c in plan.cariler)),
        "cari_tur_yon": {f"{t}/{y}": n for (t, y), n in sorted(tur_yon.items())},
        "cari_borclu_toplam": cari_b,
        "cari_alacakli_toplam": cari_a,
        "stok_sayisi": len(plan.stoklar),
        "stok_miktarli": len(stok_poz),
        "stok_sifir": sum(1 for s in plan.stoklar if s["kalan"] == 0),
        "stok_negatif": sum(1 for s in plan.stoklar if s["kalan"] < 0),
        "stok_miktar_toplam": sum((s["kalan"] for s in stok_poz), SIFIR),
        "stok_maliyet_tl_haric_doviz": sum(
            (s["kalan"] * s["alis_fiyati"] for s in stok_poz if s["alis_doviz"] == "TRY"), SIFIR
        ).quantize(KURUS),
        "stok_dovizli_maliyetli": sum(1 for s in stok_poz if s["alis_doviz"] not in {"TRY"}),
        "finans_hesap": len(plan.finans),
        "finans_hedef_toplam": {k: v.quantize(KURUS) for k, v in finans_sinif.items()},
        "bulgu": dict(Counter(b.seviye for b in plan.bulgular)),
    }
