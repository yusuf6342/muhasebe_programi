"""Dönen Sermaye Bilançosu (Özet Tablolar): seçilen tarih sonu, yalnız ön muhasebe kaynakları.

Kapsam gerçek bilançonun 1 ve 3 gruplarına karşılık gelen ön muhasebe varlık / borçlarıdır; muhasebe fişi,
muhasebeleşme durumu veya hesap kodu giriş şartı değildir. Duran varlık, uzun vadeli borç, özkaynak ve
gelir-gider ile denkleştirme yapılmaz:

    Dönen sermaye = işaretli aktif genel toplamı + işaretli pasif genel toplamı

İşaret şirketin bakış açısındadır: alacak / varlık pozitif, borç negatif. Taraf sabittir:
* Kasa, mevduat, vadeli, KMH ve POS her durumda aktifte; hesap kimliği başına ayrı satır, eksi bakiye eksi.
* Kredi ana parası ve kredi kartı her durumda pasifte; olağan borç eksi, gerçek ters bakiye artı.
* Müşteri bakiyeleri aktifte iki ayrı satır (alacaklar + / borçlar −); tedarikçiler pasifte iki ayrı satır
  (borçlar − / alacaklar +); personel borcu pasifte, personel avansı aktifte. İsimler ana özette listelenmez.
* Kredi: yalnız rapor tarihinde ödenmemiş ve vadesi 12 ay içinde olan ana para; faiz ve masraf eklenmez.
* Stok: tarih itibarıyla maliyet değeri; demirbaş kart türü ve işaretli demirbaş grupları (alt grupları dahil)
  hariç.

Kaynak işaretleri (cari listesi formülü, ``giris_ozet_service.cari_bakiyeleri``): müşteride pozitif bakiye
müşterinin borcu, tedarikçi / personelde pozitif bakiye bizim borcumuzdur (belge yönü). Rapor bu kaynak
işaretini tek bir normalleştirmeyle şirket bakışına çevirir.
"""

from __future__ import annotations

import threading
import time
from collections import defaultdict
from datetime import date, datetime
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

from sqlalchemy import event, select
from sqlalchemy.orm import Session, selectinload

from database.database import get_session

SIFIR = Decimal("0")
KURUS = Decimal("0.01")
TOLERANS = Decimal("0.05")

AKTIF, PASIF = "aktif", "pasif"
BASLIK, ALT_BASLIK, KALEM, ALT_TOPLAM, ARA_TOPLAM = "baslik", "alt_baslik", "kalem", "alt_toplam", "ara_toplam"

MUSTERI_TURLERI = ("müşteri", "musteri")
TEDARIKCI_TURLERI = ("tedarikçi", "tedarikci")
PERSONEL_TURLERI = ("personel",)
GIDER_TARAFI_TURLERI = ("banka",)

ALINAN_ELDE = ("PORTFOYDE", "BANKAYA_TAHSILE", "BANKAYA_TEMINATA", "KISMI_TAHSIL", "VADESI_GECTI")
VERILEN_ACIK = ("PORTFOYDE", "TEDARIKCIYE_VERILDI", "KISMI_ODENDI", "VADESI_GECTI")
KISMI_DURUMLAR = ("KISMI_TAHSIL", "KISMI_ODENDI")

KAPALI_KREDI_TAKSITI = ("IPTAL", "YAPILANDIRILDI")
KISA_VADE_AY = 12


def _d(v) -> Decimal:
    if v is None or v == "":
        return SIFIR
    return v if isinstance(v, Decimal) else Decimal(str(v))


def _q2(v) -> Decimal:
    q = _d(v).quantize(KURUS, rounding=ROUND_HALF_UP)
    return q if q != 0 else SIFIR.quantize(KURUS)


def tutar_metni(v, *, arti: bool = False) -> str:
    """1.234,56 / -1.234,56 (eksi işareti açık; -0,00 üretmez)."""
    q = _q2(v)
    metin = f"{abs(q):,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    if q < 0:
        return "-" + metin
    return ("+" + metin) if arti and q > 0 else metin


def _tur(cari_turu: str | None) -> str:
    return (cari_turu or "").strip().casefold()


# ----------------------------------------------------------------------------- kesinleşmiş değişiklik sayacı
_kilit = threading.Lock()
_sayac = 0
_ISARET = "_donen_sermaye_degisti"


@event.listens_for(Session, "after_flush")
def _flush_isaretle(session, _ctx) -> None:
    if session.new or session.dirty or session.deleted:
        session.info[_ISARET] = True


@event.listens_for(Session, "after_commit")
def _commit_say(session) -> None:
    global _sayac
    if session.info.pop(_ISARET, False):
        with _kilit:
            _sayac += 1


@event.listens_for(Session, "after_rollback")
def _geri_al(session) -> None:
    session.info.pop(_ISARET, None)


def degisim_sayaci() -> int:
    """Yalnız başarıyla commit edilmiş yazmalarda artar; geri alınan işlem sayılmaz."""
    return _sayac


# ----------------------------------------------------------------------------- demirbaş grupları
def _demirbas_tablosu(session) -> None:
    from database.models.demirbas_grup import DemirbasStokGrubu

    DemirbasStokGrubu.__table__.create(session.connection(), checkfirst=True)


def demirbas_grup_idleri(session=None) -> set[int]:
    from database.models.demirbas_grup import DemirbasStokGrubu

    def oku(s):
        _demirbas_tablosu(s)
        return {int(g) for g in s.scalars(select(DemirbasStokGrubu.grup_id)).all()}

    if session is not None:
        return oku(session)
    with get_session() as s:
        sonuc = oku(s)
        s.commit()
        return sonuc


def demirbas_gruplarini_kaydet(grup_idleri) -> None:
    """İşaretli demirbaş gruplarını kaydeder (yalnız rapor sınıflaması; stok kayıtları değişmez)."""
    from database.access import yetki_var
    from database.models.demirbas_grup import DemirbasStokGrubu
    from database.models.stok import StokGrubu
    from database.session_manager import oturum

    if not yetki_var("stok_duzenleme"):
        raise PermissionError("Demirbaş grup sınıflamasını değiştirmek için stok düzenleme yetkisi gerekir.")
    yeni = {int(g) for g in grup_idleri}
    with get_session() as s:
        _demirbas_tablosu(s)
        gecerli = {int(g) for g in s.scalars(select(StokGrubu.id)).all()}
        bilinmeyen = yeni - gecerli
        if bilinmeyen:
            raise ValueError(f"Stok grubu bulunamadı: {', '.join(map(str, sorted(bilinmeyen)))}")
        mevcut = {int(r.grup_id): r for r in s.scalars(select(DemirbasStokGrubu)).all()}
        for gid, r in mevcut.items():
            if gid not in yeni:
                s.delete(r)
        kullanici = getattr(oturum, "kullanici_adi", None) or getattr(oturum, "ad_soyad", None)
        for gid in sorted(yeni - set(mevcut)):
            s.add(DemirbasStokGrubu(grup_id=gid, kullanici=kullanici))
        s.commit()


def stok_gruplari() -> list[dict]:
    """Demirbaş seçim penceresi için grup ağacı (id, kod, ad, seviye, parent_id, kart sayısı, işaret)."""
    from database.models.stok import StokGrubu, StokKarti

    with get_session() as s:
        isaretli = demirbas_grup_idleri(s)
        s.commit()
        sayi: dict[int, int] = defaultdict(int)
        for a, t, al in s.execute(select(StokKarti.ana_grup_id, StokKarti.tali_grup_id,
                                         StokKarti.alt_grup_id)).all():
            for g in {a, t, al} - {None}:
                sayi[int(g)] += 1
        return [{"id": int(g.id), "kod": g.kod or "", "ad": g.ad or "", "seviye": int(g.seviye or 1),
                 "parent_id": g.parent_id, "kart": sayi.get(int(g.id), 0), "demirbas": int(g.id) in isaretli}
                for g in s.scalars(select(StokGrubu).order_by(StokGrubu.seviye, StokGrubu.sira_no,
                                                              StokGrubu.ad, StokGrubu.id)).all()]


# ----------------------------------------------------------------------------- satır ve toplam üretimi
def grup(anahtar: str, baslik: str, ara_toplam: str, satirlar: list[dict] | None = None,
         alt_gruplar: list[dict] | None = None) -> dict:
    return {"anahtar": anahtar, "baslik": baslik, "ara_toplam": ara_toplam,
            "satirlar": satirlar or [], "alt_gruplar": alt_gruplar or []}


def satir(etiket: str, tutar, *, ayrinti: list | None = None, not_: str = "") -> dict:
    return {"etiket": etiket, "tutar": _d(tutar), "ayrinti": ayrinti or [], "not": not_}


def _grup_toplami(g: dict) -> Decimal:
    toplam = sum((_d(s["tutar"]) for s in g["satirlar"]), SIFIR)
    for ag in g["alt_gruplar"]:
        toplam += sum((_d(s["tutar"]) for s in ag["satirlar"]), SIFIR)
    return toplam


def _gorunur(satirlar: list[dict]) -> list[dict]:
    return [s for s in satirlar if _q2(s["tutar"]) != 0]


def taraf_satirlari(gruplar: list[dict]) -> tuple[list[dict], Decimal]:
    """Ekran / dışa aktarma satırları ve taraf genel toplamı.

    Genel toplam çakışmayan grup ara toplamlarından üretilir; görünür alt satırlar yeniden eklenmez.
    Sıfır satırlar gizlenir; hiç bakiyeli satırı olmayan grup gizlenir, net sıfır grup 0,00 ara toplamıyla
    görünür.
    """
    out: list[dict] = []
    genel = SIFIR
    for g in gruplar:
        toplam = _grup_toplami(g)
        genel += toplam
        dogrudan = _gorunur(g["satirlar"])
        altlar = [(ag, _gorunur(ag["satirlar"])) for ag in g["alt_gruplar"]]
        if not dogrudan and not any(v for _ag, v in altlar):
            continue
        out.append({"seviye": BASLIK, "etiket": g["baslik"], "tutar": None, "grup": g["anahtar"]})
        for s in dogrudan:
            out.append({"seviye": KALEM, "etiket": s["etiket"], "tutar": _q2(s["tutar"]), "grup": g["anahtar"],
                        "ayrinti": s["ayrinti"], "not": s["not"]})
        for ag, gorunur in altlar:
            if not gorunur:
                continue
            out.append({"seviye": ALT_BASLIK, "etiket": ag["baslik"], "tutar": None, "grup": g["anahtar"]})
            for s in gorunur:
                out.append({"seviye": KALEM, "etiket": s["etiket"], "tutar": _q2(s["tutar"]),
                            "grup": g["anahtar"], "ayrinti": s["ayrinti"], "not": s["not"]})
            out.append({"seviye": ALT_TOPLAM, "etiket": ag["ara_toplam"],
                        "tutar": _q2(sum((_d(s["tutar"]) for s in ag["satirlar"]), SIFIR)), "grup": g["anahtar"]})
        out.append({"seviye": ARA_TOPLAM, "etiket": g["ara_toplam"], "tutar": _q2(toplam), "grup": g["anahtar"]})
    return out, _q2(genel)


def rapor_olustur(aktif_gruplar: list[dict], pasif_gruplar: list[dict]) -> dict:
    aktif, aktif_toplam = taraf_satirlari(aktif_gruplar)
    pasif, pasif_toplam = taraf_satirlari(pasif_gruplar)
    return {"aktif": aktif, "pasif": pasif, "aktif_toplam": aktif_toplam, "pasif_toplam": pasif_toplam,
            "donen_sermaye": _q2(aktif_toplam + pasif_toplam)}


def cari_ozet_satirlari(bakiyeler: list[tuple[str, Decimal]], arti_etiket: str, eksi_etiket: str,
                        *, once_arti: bool = True) -> list[dict]:
    """Şirket işaretli cari bakiyelerinden ayrı + ve − toplam satırları (farklı cariler netleşmez)."""
    arti = [(ad, _q2(t)) for ad, t in bakiyeler if _q2(t) > 0]
    eksi = [(ad, _q2(t)) for ad, t in bakiyeler if _q2(t) < 0]
    s_arti = satir(arti_etiket, sum((t for _a, t in arti), SIFIR), ayrinti=sorted(arti, key=lambda x: -x[1]))
    s_eksi = satir(eksi_etiket, sum((t for _a, t in eksi), SIFIR), ayrinti=sorted(eksi, key=lambda x: x[1]))
    return [s_arti, s_eksi] if once_arti else [s_eksi, s_arti]


# ----------------------------------------------------------------------------- finans hesapları
def hesap_turu(h) -> str:
    """KASA | MEVDUAT | VADELI | KMH | POS | KREDI_KARTI | KREDILER."""
    tur = (h.hesap_turu or "").upper()
    alt = (h.alt_hesap_turu or "").upper()
    if tur == "KASA":
        return "KASA"
    if alt == "POS" or (tur.startswith("KRED") and not alt):
        return "POS"
    if alt in ("KREDI_KARTI", "KREDILER", "KMH"):
        return alt
    if alt.startswith("VADELI"):
        return "VADELI"
    return "MEVDUAT"


BANKA_SIRASI = {"MEVDUAT": 0, "VADELI": 1, "KMH": 2, "POS": 3}


def _finans(b) -> tuple[dict, list[str], list[str]]:
    """Kasa / banka varlık satırları, kredi kartı satırları ve krediler defteri bakiyesi."""
    from database.turkce_normalize import turkce_normalize

    bak = b.finans_bakiyeleri()
    hesaplar = b.hesaplar()
    kasalar, bankalar, kartlar = [], [], []
    krediler_defteri = SIFIR
    notlar: list[str] = []
    supheli, eksi_banka = [], []
    kredi_izi = turkce_normalize("kredi")
    for hid, h in sorted(hesaplar.items(), key=lambda x: ((x[1].banka_karti_id or 0), x[0])):
        tur = hesap_turu(h)
        v = _d(bak.get(hid))
        ad = (h.hesap_adi or f"Hesap #{hid}").strip()
        if tur == "KASA":
            kasalar.append((hid, satir(ad, v)))
            if _q2(v) < 0:
                notlar.append(f"{ad} (hesap #{hid}) eksi bakiyede ({tutar_metni(v)} TL); kasa aktifte eksi "
                              "gösterildi, kayıtların incelenmesi önerilir.")
        elif tur in BANKA_SIRASI:
            bankalar.append((BANKA_SIRASI[tur], h.banka_karti_id or 0, hid, satir(ad, v)))
            if tur in ("MEVDUAT", "VADELI") and _q2(v) < 0:
                if kredi_izi in turkce_normalize(ad).replace(turkce_normalize("Yapı Kredi"), ""):
                    supheli.append(f"#{hid} {ad} ({tutar_metni(v)})")
                else:
                    eksi_banka.append(f"#{hid} {ad} ({tutar_metni(v)})")
        elif tur == "KREDI_KARTI":
            kartlar.append((hid, satir(f"Kredi Kartı — {ad}", -v)))
        elif tur == "KREDILER":
            krediler_defteri += v
    bankalar.sort(key=lambda x: x[:3])
    eksikler = []
    if supheli:
        eksikler.append(f"Hesap türü eşlemesi incelenmeli: adı kredi / kredi kartı olan {len(supheli)} hesap ön "
                        "muhasebede MEVDUAT alt hesabı olarak kayıtlı ve eksi bakiyede. Sabit taraf kuralı gereği "
                        "aktifte eksi gösterildi (dönen sermaye sonucu değişmez; yalnız aktif / pasif dağılımı "
                        "etkilenir). Hesap türü Finans'ta düzeltilirse pasife geçer: " + "; ".join(supheli))
    if eksi_banka:
        notlar.append(f"{len(eksi_banka)} mevduat / vadeli hesap eksi bakiyede; aktifte eksi gösterildi, kayıtların "
                      "incelenmesi önerilir: " + "; ".join(eksi_banka))
    return ({"kasalar": [s for _i, s in kasalar], "bankalar": [x[3] for x in bankalar],
             "kartlar": [s for _i, s in kartlar], "krediler_defteri": _q2(krediler_defteri)}, notlar, eksikler)


# ----------------------------------------------------------------------------- cari
def _cari(b) -> tuple[dict, list[str], list[str]]:
    from database import giris_ozet_service as go

    bakiyeler, notlar = go.cari_bakiyeleri(b)
    musteri, tedarikci, personel_borc, personel_alacak, diger = [], [], [], [], []
    silinmis_adet, silinmis_tutar = 0, SIFIR
    for cid, v in bakiyeler.items():
        v = _q2(v)
        if v == 0:
            continue
        if cid in b.silinmis:
            silinmis_adet += 1
            silinmis_tutar += v
            continue
        kod, unvan, tur = b.cariler.get(int(cid), ("", f"Cari #{cid}", ""))
        ad = f"{unvan} ({kod})" if kod else unvan
        t = _tur(tur)
        if t.startswith(MUSTERI_TURLERI):
            musteri.append((ad, v))
        elif t.startswith(TEDARIKCI_TURLERI):
            tedarikci.append((ad, -v))
        elif t.startswith(PERSONEL_TURLERI):
            (personel_borc if v > 0 else personel_alacak).append((ad, -v))
        elif t.startswith(GIDER_TARAFI_TURLERI):
            diger.append((ad, -v))
        else:
            diger.append((ad, v))
    if silinmis_adet:
        notlar.append(f"Silinmiş {silinmis_adet} cari kartın bakiyesi ({tutar_metni(silinmis_tutar)} TL, kaynak "
                      "işaretiyle) rapora alınmadı.")
    if diger:
        notlar.append(f"Türü müşteri / tedarikçi / personel olmayan {len(diger)} cari, 'Diğer' satırlarında "
                      "gösterildi.")
    return ({"musteri": musteri, "tedarikci": tedarikci, "personel_borc": personel_borc,
             "personel_alacak": personel_alacak, "diger": diger}, notlar, [])


# ----------------------------------------------------------------------------- kredi
def _yil_sonra(d: date) -> date:
    try:
        return d.replace(year=d.year + KISA_VADE_AY // 12)
    except ValueError:
        return d.replace(year=d.year + KISA_VADE_AY // 12, day=28)


def kredi_kalanlari(taksitler: list[dict], odemeler: list[dict], d: date) -> dict[int, Decimal]:
    """Taksit başına D sonu kalan ana para.

    ``taksitler``: id, vade, anapara, durum, odenen_anapara, odeme_tarihi.
    ``odemeler``: taksit_id (None olabilir), tarih, anapara — yalnız geçerli (AKTİF) ödemeler.
    Taksite bağlı ödeme kaydı olmayan eski kayıtlarda taksit üzerindeki ödenen ana para ve ödeme tarihi
    kullanılır. Taksite bağlanmamış ara / erken ödeme ana parası en son vadeden geriye doğru düşülür.
    """
    bagli: dict[int, Decimal] = defaultdict(lambda: SIFIR)
    bagli_var: set[int] = set()
    serbest = SIFIR
    for o in odemeler:
        if o["taksit_id"] is not None:
            bagli_var.add(int(o["taksit_id"]))
        if o["tarih"] > d:
            continue
        if o["taksit_id"] is None:
            serbest += _d(o["anapara"])
        else:
            bagli[int(o["taksit_id"])] += _d(o["anapara"])
    kalan: dict[int, Decimal] = {}
    for t in taksitler:
        tid = int(t["id"])
        if t["durum"] in KAPALI_KREDI_TAKSITI:
            continue
        ana = _d(t["anapara"])
        if tid in bagli_var:
            odenen = bagli[tid]
        else:
            odenen = _d(t.get("odenen_anapara"))
            if odenen == 0 and t["durum"] in ("ODENDI", "ERKEN_KAPATILDI"):
                odenen = ana
            ot = t.get("odeme_tarihi")
            if odenen and ot is not None and ot > d:
                odenen = SIFIR
        kalan[tid] = max(SIFIR, ana - odenen)
    for t in sorted(taksitler, key=lambda x: (x["vade"], x["id"]), reverse=True):
        if serbest <= 0:
            break
        tid = int(t["id"])
        if tid not in kalan:
            continue
        pay = min(serbest, kalan[tid])
        kalan[tid] -= pay
        serbest -= pay
    return kalan


def _kredi(b) -> tuple[dict, list[str], list[str]]:
    from database.models.finans import BankaKredisi, BankaKrediOdeme

    d = b.d
    kisa_sinir = _yil_sonra(d)
    odemeler: dict[int, list[dict]] = defaultdict(list)
    for o in b.s.scalars(select(BankaKrediOdeme).where(BankaKrediOdeme.durum == "AKTIF")).all():
        odemeler[int(o.kredi_id)].append({"taksit_id": o.taksit_id, "tarih": o.odeme_tarihi,
                                          "anapara": _d(o.anapara)})
    bankalar: dict[int, dict] = {}
    notlar, eksikler = [], []
    uzun_toplam = SIFIR
    toplam_kalan = SIFIR
    for k in b.s.scalars(select(BankaKredisi).options(selectinload(BankaKredisi.taksitler),
                                                      selectinload(BankaKredisi.banka_karti))
                         .where(BankaKredisi.kullandirim_tarihi <= d)).all():
        if (k.durum or "").upper() == "IPTAL":
            continue
        kimlik = f"{k.belge_no} (kredi #{k.id})"
        pb = (k.para_birimi or "TRY").upper()
        kur = Decimal("1")
        if pb not in ("TRY", "TL"):
            kur = _d(k.kur)
            if kur <= 0:
                eksikler.append(f"{kimlik}: {pb} kredi için kur kaydı yok; kredi tutarı hesaplanamadı.")
                continue
            notlar.append(f"{kimlik}: {pb} kredi kayıtlı kullandırım kuruyla TL'ye çevrildi.")
        taksitler = [{"id": t.id, "vade": t.vade_tarihi, "anapara": _d(t.anapara), "durum": (t.durum or "").upper(),
                      "odenen_anapara": _d(t.odenen_anapara), "odeme_tarihi": t.odeme_tarihi}
                     for t in (k.taksitler or [])]
        if not taksitler:
            eksikler.append(f"{kimlik}: taksit planı yok; kalan ana para ve vade ayrımı hesaplanamadı. "
                            "Taksit planına ana para tutarları girilmelidir.")
            continue
        plan = sum((t["anapara"] for t in taksitler if t["durum"] not in ("IPTAL",)), SIFIR)
        if plan <= 0 or abs(plan - _d(k.ana_para)) > TOLERANS:
            eksikler.append(f"{kimlik}: taksit planındaki ana para toplamı {tutar_metni(plan)} TL, kredi ana parası "
                            f"{tutar_metni(k.ana_para)} TL. Ana para ayrımı eksik / tutarsız; taksit ana para "
                            "alanları düzeltilmeden bu kredinin tutarı tamamlanmış sayılmaz.")
        kalanlar = kredi_kalanlari(taksitler, odemeler.get(int(k.id), []), d)
        vade = {int(t["id"]): t["vade"] for t in taksitler}
        kisa = sum((v for tid, v in kalanlar.items() if vade[tid] <= kisa_sinir), SIFIR) * kur
        uzun = sum((v for tid, v in kalanlar.items() if vade[tid] > kisa_sinir), SIFIR) * kur
        uzun_toplam += uzun
        toplam_kalan += kisa + uzun
        if _q2(kisa) == 0:
            continue
        bk = k.banka_karti
        anahtar = int(k.banka_karti_id)
        g = bankalar.setdefault(anahtar, {"ad": (bk.banka_adi if bk else "") or f"Banka #{anahtar}",
                                          "tutar": SIFIR, "ayrinti": []})
        g["tutar"] -= kisa
        g["ayrinti"].append((f"{k.kredi_adi} — {k.belge_no}", -_q2(kisa)))
    if _q2(uzun_toplam):
        notlar.append(f"Kredilerin {KISA_VADE_AY} aydan sonra vadesi gelen ana parası ({tutar_metni(uzun_toplam)} TL) "
                      "uzun vadeli (4 grubu) sayıldı ve rapora alınmadı.")
    adlar = defaultdict(int)
    for g in bankalar.values():
        adlar[g["ad"]] += 1
    satirlar = [satir(f"Kredi Ana Para — {g['ad']}" + (f" (banka #{bid})" if adlar[g["ad"]] > 1 else ""),
                      g["tutar"], ayrinti=g["ayrinti"]) for bid, g in sorted(bankalar.items())]
    return {"satirlar": satirlar, "toplam_kalan": _q2(toplam_kalan)}, notlar, eksikler


# ----------------------------------------------------------------------------- çek / senet
def _evrak_durumu(e, d: date, bugun: date) -> tuple[str, Decimal]:
    """Evrakın D sonundaki durumu ve kalan TL tutarı (durum geçmişinden)."""
    hareketler = sorted(e.hareketler or [], key=lambda h: (h.tarih, h.id))
    sonraki = [h for h in hareketler if h.tarih.date() > d]
    if not sonraki or d >= bugun:
        return (e.durum or "").upper(), _d(e.kalan_tutar)
    oncekiler = [h for h in hareketler if h.tarih.date() <= d]
    if oncekiler:
        durum = oncekiler[-1].yeni_durum
    else:
        durum = hareketler[0].yeni_durum if hareketler else e.durum
    kismi = sum((_d(h.tutar) for h in oncekiler if (h.yeni_durum or "").upper() in KISMI_DURUMLAR), SIFIR)
    toplam = _d(e.tl_tutari)
    return (durum or "").upper(), max(SIFIR, toplam - kismi)


def _cek_senet(b) -> tuple[dict, list[str], list[str]]:
    from database.models.cek_senet import CekSenetEvrak

    from sqlalchemy import inspect

    toplam = {"alinan_cek": [], "alinan_senet": [], "firma_cek": [], "firma_senet": []}
    notlar = []
    tanimsiz = 0
    if not inspect(b.s.connection()).has_table(CekSenetEvrak.__tablename__):
        return toplam, ["Çek / senet modülü bu firmada kullanılmamış; çek senet kalemi yok."], []
    for e in b.s.scalars(select(CekSenetEvrak).options(selectinload(CekSenetEvrak.hareketler))
                         .where(CekSenetEvrak.duzenleme_tarihi <= b.d)).all():
        if e.aktif is False:
            continue
        durum, kalan = _evrak_durumu(e, b.d, b.bugun)
        if kalan <= 0:
            continue
        tur, yon = (e.evrak_turu or "").upper(), (e.islem_yonu or "").upper()
        etiket = f"{e.portfoy_no} — vade {e.vade_tarihi:%d.%m.%Y}"
        if yon == "ALINAN" and tur.startswith("MUSTERI") and durum in ALINAN_ELDE:
            toplam["alinan_cek" if tur.endswith("CEKI") else "alinan_senet"].append((etiket, _q2(kalan)))
        elif yon == "VERILEN" and tur.startswith("FIRMA") and durum in VERILEN_ACIK:
            toplam["firma_cek" if tur.endswith("CEKI") else "firma_senet"].append((etiket, -_q2(kalan)))
        elif yon == "ALINAN" and tur.startswith("FIRMA") and durum in ALINAN_ELDE:
            tanimsiz += 1
    if tanimsiz:
        notlar.append(f"Alınan firma çeki / senedi olarak kayıtlı {tanimsiz} açık evrak sınıflandırılamadı; "
                      "rapora alınmadı.")
    return toplam, notlar, []


# ----------------------------------------------------------------------------- stok
def stok_kok_grubu(kart: dict, gruplar: dict[int, dict]) -> tuple[int | None, bool]:
    """Kartın gösterim grubu (en üst ana grup) ve eşleme tutarlılığı."""
    def kok(gid):
        gorulen = set()
        while gid is not None and gid in gruplar and gid not in gorulen:
            gorulen.add(gid)
            p = gruplar[gid].get("parent_id")
            if p is None:
                return gid
            gid = int(p)
        return gid

    kokler = {kok(int(g)) for g in (kart.get("ana_grup_id"), kart.get("tali_grup_id"), kart.get("alt_grup_id"))
              if g is not None}
    if not kokler:
        return None, True
    ana = kart.get("ana_grup_id")
    secilen = kok(int(ana)) if ana is not None else sorted(kokler)[0]
    return secilen, len(kokler) == 1


def demirbas_mi(kart: dict, gruplar: dict[int, dict], isaretli: set[int]) -> bool:
    """Kart türü 'Demirbaş' veya kartın herhangi bir grubu / üst grubu demirbaş olarak işaretli."""
    from database.turkce_normalize import turkce_normalize

    if turkce_normalize((kart.get("kart_turu") or "").strip()) == turkce_normalize("Demirbaş"):
        return True
    for g in (kart.get("ana_grup_id"), kart.get("tali_grup_id"), kart.get("alt_grup_id")):
        gid = int(g) if g is not None else None
        gorulen = set()
        while gid is not None and gid not in gorulen:
            if gid in isaretli:
                return True
            gorulen.add(gid)
            p = gruplar.get(gid, {}).get("parent_id")
            gid = int(p) if p is not None else None
    return False


def _stok(b, yontem: str) -> tuple[dict, list[str], list[str]]:
    from database import stok_rapor_service as sr
    from database.models.stok import StokGrubu, StokKarti
    from database.turkce_normalize import turkce_normalize

    notlar, eksikler = [], []
    if not sr.maliyet_gorunur():
        return {"satirlar": []}, [], ["Stok maliyetlerini görme yetkiniz olmadığından stok değeri hesaplanamadı; "
                                      "aktif toplamı stoksuz gösterilir."]
    try:
        deg = sr.degerleme(tarih=b.d, yontem=yontem)
    except PermissionError as hata:
        return {"satirlar": []}, [], [f"Stok değeri hesaplanamadı: {hata}"]
    gruplar = {int(g.id): {"kod": g.kod or "", "ad": g.ad or "", "parent_id": g.parent_id}
               for g in b.s.scalars(select(StokGrubu)).all()}
    kartlar = {int(k.id): {"ana_grup_id": k.ana_grup_id, "tali_grup_id": k.tali_grup_id,
                           "alt_grup_id": k.alt_grup_id, "kart_turu": k.kart_turu, "kod": k.stok_kodu}
               for k in b.s.scalars(select(StokKarti)).all()}
    isaretli = demirbas_grup_idleri(b.s)
    deger: dict[int | None, Decimal] = defaultdict(lambda: SIFIR)
    adet: dict[int | None, set] = defaultdict(set)
    demirbas_tutar, demirbas_kart = SIFIR, set()
    eksik_maliyet, negatif, eslesmeyen = set(), set(), set()
    for r in deg["satirlar"]:
        sid = int(r["stok_id"])
        kart = kartlar.get(sid)
        if kart is None:
            continue
        tutar = _d(r["toplam_maliyet"])
        if demirbas_mi(kart, gruplar, isaretli):
            demirbas_tutar += tutar
            demirbas_kart.add(sid)
            continue
        if r["durum"].startswith(("Eksik", "Kısmi")):
            eksik_maliyet.add(r["urun_kodu"])
        elif r["durum"] == "Negatif stok":
            negatif.add(r["urun_kodu"])
        kok, tutarli = stok_kok_grubu(kart, gruplar)
        if not tutarli:
            eslesmeyen.add(r["urun_kodu"])
        deger[kok] += tutar
        adet[kok].add(sid)
    ad_say = defaultdict(int)
    for gid in deger:
        if gid is not None:
            ad_say[gruplar.get(gid, {}).get("ad", "")] += 1
    satirlar = []
    for gid in sorted(deger, key=lambda g: (g is None, gruplar.get(g, {}).get("ad", "").casefold() if g else "",
                                            g or 0)):
        if gid is None:
            etiket = "Grupsuz stoklar"
        else:
            gg = gruplar.get(gid, {"ad": f"Grup #{gid}", "kod": ""})
            etiket = gg["ad"] + (f" [{gg['kod'] or gid}]" if ad_say[gg["ad"]] > 1 else "")
        satirlar.append(satir(etiket, deger[gid], ayrinti=[(f"{len(adet[gid])} stok kartı", _q2(deger[gid]))]))
    if demirbas_kart:
        notlar.append(f"Demirbaş olarak sınıflanan {len(demirbas_kart)} kartın stok değeri "
                      f"({tutar_metni(demirbas_tutar)} TL) stok toplamından hariç tutuldu.")
    hedef = turkce_normalize("demirbaş")
    for gid, g in gruplar.items():
        if gid not in isaretli and (hedef in turkce_normalize(g["ad"]) or hedef in turkce_normalize(g["kod"])):
            notlar.append(f"'{g['ad']}' adlı stok grubu (grup #{gid}) demirbaş olarak işaretli değil; ad tahmini "
                          "yapılmadı. Hariç tutulacaksa 'Demirbaş grupları' ile işaretleyin.")
    if eksik_maliyet:
        eksikler.append(f"{len(eksik_maliyet)} stok kartında maliyet eksik / kısmi; bu kartların maliyeti bilinmeyen "
                        "miktarı stok toplamına katılmadı (Stok Raporları → Değerleme'de listelenir).")
    if adet.get(None):
        notlar.append(f"{len(adet[None])} stok kartının stok grubu eşlemesi yok; 'Grupsuz stoklar' satırında "
                      "toplandı. Demirbaş kart türündekiler bu satıra girmez.")
    if negatif:
        notlar.append(f"{len(negatif)} stok kartı rapor tarihinde negatif miktarda; negatif stok değerlenmez.")
    if eslesmeyen:
        eksikler.append(f"{len(eslesmeyen)} stok kartının ana / tali / alt grup eşlemesi farklı üst gruplara "
                        f"işaret ediyor; ana grup esas alındı (ör. {', '.join(sorted(eslesmeyen)[:5])}).")
    if deg.get("notlar"):
        notlar.append(deg["notlar"][0])
    return {"satirlar": satirlar}, notlar, eksikler


# ----------------------------------------------------------------------------- ana hesap
def hesapla(tarih: date | None = None, yontem: str | None = None, *, bugun: date | None = None) -> dict:
    """Seçilen tarih sonu dönen sermaye bilançosu (önbelleksiz; her çağrı güncel kaynaktan okur)."""
    from database import giris_ozet_service as go
    from database import stok_rapor_service as sr

    bas = time.perf_counter()
    bugun = bugun or date.today()
    d = tarih or bugun
    yontem = yontem or sr.FIFO
    sayac = degisim_sayaci()
    notlar: list[str] = []
    eksikler: list[str] = []
    with get_session() as s:
        b = go._Baglam(s, d, bugun, None)

        def topla(sonuc):
            veri, n, e = sonuc
            notlar.extend(n)
            eksikler.extend(e)
            return veri

        fin = topla(_finans(b))
        cari = topla(_cari(b))
        kredi = topla(_kredi(b))
        cek = topla(_cek_senet(b))
        stok = topla(_stok(b, yontem))
    if abs(_d(kredi["toplam_kalan"]) - _d(fin["krediler_defteri"])) > TOLERANS:
        notlar.append(f"Kredi planından bulunan toplam kalan ana para ({tutar_metni(kredi['toplam_kalan'])} TL) "
                      f"Krediler hesabı bakiyesinden ({tutar_metni(fin['krediler_defteri'])} TL) farklı; rapor "
                      "taksit planındaki ana parayı kullandı.")

    aktif_gruplar = [
        grup("kasalar", "KASALAR", "Kasalar ara toplam", fin["kasalar"]),
        grup("banka_varlik", "BANKA LİKİT VARLIKLARI", "Banka varlıkları ara toplam", fin["bankalar"]),
        grup("alinan_cek", "ALINAN ÇEK VE SENETLER", "Alınan çek senet ara toplam", [
            satir("Alınan Müşteri Çekleri", sum((t for _a, t in cek["alinan_cek"]), SIFIR), ayrinti=cek["alinan_cek"]),
            satir("Alınan Müşteri Senetleri", sum((t for _a, t in cek["alinan_senet"]), SIFIR),
                  ayrinti=cek["alinan_senet"])]),
        grup("musteriler", "MÜŞTERİLER", "Müşteriler ara toplam",
             cari_ozet_satirlari(cari["musteri"], "Müşterilerden Alacaklar", "Müşterilere Borçlar")),
        grup("diger_alacak", "DİĞER KISA VADELİ ALACAKLAR", "Diğer alacaklar ara toplam", [
            satir("Personelden Alacaklar (avans)", sum((t for _a, t in cari["personel_alacak"]), SIFIR),
                  ayrinti=cari["personel_alacak"]),
            satir("Diğer Cari Alacaklar", sum((t for _a, t in cari["diger"] if t > 0), SIFIR),
                  ayrinti=[x for x in cari["diger"] if x[1] > 0])]),
        grup("stoklar", "DEMİRBAŞ DIŞI STOKLAR", "Stoklar ara toplam", stok["satirlar"]),
    ]
    pasif_gruplar = [
        grup("banka_borc", "BANKA LİKİT BORÇLARI", "Banka borçları ara toplam", alt_gruplar=[
            grup("kredi", "Kredi Borçları Ana Para", "Kredi ana para toplamı", kredi["satirlar"]),
            grup("kredi_karti", "Kredi Kartı Borçları", "Kredi kartı toplamı", fin["kartlar"])]),
        grup("tedarikciler", "TEDARİKÇİLER", "Tedarikçiler ara toplam",
             cari_ozet_satirlari(cari["tedarikci"], "Tedarikçilerden Alacaklar", "Tedarikçilere Borçlar",
                                 once_arti=False)),
        grup("firma_cek", "FİRMA ÇEK VE SENETLERİ", "Çek senet ara toplam", [
            satir("Firma Çek Borçları", sum((t for _a, t in cek["firma_cek"]), SIFIR), ayrinti=cek["firma_cek"]),
            satir("Firma Senet Borçları", sum((t for _a, t in cek["firma_senet"]), SIFIR),
                  ayrinti=cek["firma_senet"])]),
        grup("personel", "PERSONEL BORÇLARI", "Personel ara toplam", [
            satir("Personele Borçlar", sum((t for _a, t in cari["personel_borc"]), SIFIR),
                  ayrinti=cari["personel_borc"])]),
        grup("diger_borc", "DİĞER KISA VADELİ BORÇLAR", "Diğer borçlar ara toplam", [
            satir("Diğer Cari Borçlar", sum((t for _a, t in cari["diger"] if t < 0), SIFIR),
                  ayrinti=[x for x in cari["diger"] if x[1] < 0])]),
    ]
    sonuc = rapor_olustur(aktif_gruplar, pasif_gruplar)
    notlar.append("Kapsam dışı: KDV / vergi / SGK alacak-borçları ve sipariş avansları için ön muhasebede rapor "
                  "grubu eşlemesi yok; bu kalemler rapora alınmadı (sıfır sayılmadı).")
    notlar.append("Rapor firma genelidir; şube filtresi uygulanmaz. Muhasebe fişleri kaynak değildir; "
                  "muhasebeleştirme tek başına sonucu değiştirmez.")
    sonuc.update(tarih=d, yontem=yontem, notlar=notlar, eksikler=eksikler, sayac=sayac,
                 zaman=datetime.now(), sure_ms=int((time.perf_counter() - bas) * 1000))
    return sonuc


def disa_aktarim_satirlari(sonuc: dict) -> list[list[str]]:
    """Ekranla aynı sıra, ara toplamlar ve genel toplamlar (CSV / yazdırma)."""
    out = [["Dönen Sermaye Bilançosu", f"{sonuc['tarih']:%d.%m.%Y}", "", ""], ["Taraf", "Seviye", "Kalem", "Tutar TL"]]
    for taraf, ad, toplam_ad, toplam in ((AKTIF, "AKTİF", "AKTİF GENEL TOPLAMI", sonuc["aktif_toplam"]),
                                         (PASIF, "PASİF", "PASİF GENEL TOPLAMI", sonuc["pasif_toplam"])):
        for r in sonuc[taraf]:
            out.append([ad, r["seviye"], r["etiket"], "" if r["tutar"] is None else tutar_metni(r["tutar"])])
        out.append([ad, "genel_toplam", toplam_ad, tutar_metni(toplam)])
    out.append(["", "sonuc", "DÖNEN SERMAYE", tutar_metni(sonuc["donen_sermaye"])])
    return out
