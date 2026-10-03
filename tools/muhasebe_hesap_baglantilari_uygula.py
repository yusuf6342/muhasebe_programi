"""Muhasebe hesap bağlantıları: kasa varsayılanı ve banka kartı bazında mevduat hesapları (kullanıcı kararıyla).

Kararlar (kullanıcı):
- Kasa firma varsayılanı 100.01.0001 NAKİT TL KASA (100.01.0002 silinmez/birleştirilmez).
- Bankalar tek hesaba bağlanmaz: her gerçek banka hesabı (açıkça ayırt edilen kart) için 102.01 altında ayrı
  alt hesap açılır ve kartın MEVDUAT alt hesabına bağlanır. Belirsiz kartlar (mükerrer olabilecek, ödeme
  kuruluşu, kişi adına, kredi kartı / kredi / hisse olarak açılmış kartlar) bağlanmaz, inceleme listesine yazılır.
- KMH / POS / şirket kartı hesapları seçilmez (kullanıcı kararı).

Şema: ``finans_hesaplari`` iki kolon + ``muhasebe_kur_farki_kayitlari`` / ``muhasebe_finans_ayarlari`` tabloları
``gecis_guvenligi.guvenli_gecis`` ile (doğrulanmış yedek, hata olursa geri yükleme) eklenir. Ardından doğrulanmış
yedek alınır ve veri değişikliği tek transaction'da yapılır. Fiş, fiş satırı, bakiye ve geçmiş belgeler değişmez.

    python tools/muhasebe_hesap_baglantilari_uygula.py            # kuru çalıştırma (TEMP kopyada)
    python tools/muhasebe_hesap_baglantilari_uygula.py --uygula   # gerçek veritabanı
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))

from sqlalchemy import create_engine, func, inspect, select, text  # noqa: E402
from sqlalchemy.orm import Session  # noqa: E402

import ray_hesap_esleme_tamamla as ray  # noqa: E402
from database.models.finans import BankaKarti, FinansHareketi, FinansHesabi  # noqa: E402
from database.models.genel_muhasebe import (  # noqa: E402
    HesapPlani,
    KurFarkiKaydi,
    MuhasebeFinansAyari,
    MuhasebeHesapEsleme,
    MuhasebeIslemGecmisi,
)
from database.muhasebe_entegrasyon import hesap_uygunluk_sorunu  # noqa: E402

CIKTI_KLASORU = ROOT / "inceleme" / "muhasebelestirme"
ISLEM_YAPAN = "muhasebe_hesap_baglantilari (kullanıcı onaylı)"
DEGISEBILIR_TABLOLAR = {"muhasebe_hesap_plani", "muhasebe_hesap_eslemeleri", "muhasebe_islem_gecmisi"}
KASA_HESABI = "100.01.0001"
BANKA_TALI = ("102.01", "BANKALAR VADESİZ TL TALİ HESABI")

# Açıkça ayrı gerçek banka hesabı olan kartlar: (banka kartı id, beklenen ad başlangıcı, açılacak hesap adı)
BANKA_HESAPLARI: tuple[tuple[int, str, str], ...] = (
    (3, "001 AKBANK", "AKBANK AVCILAR VADESİZ TL (001)"),
    (4, "002 ENPARA", "ENPARA ŞİRKET VADESİZ TL (002)"),
    (5, "003 YAPI KREDİ", "YAPI KREDİ BEYLİKDÜZÜ VADESİZ TL (003)"),
    (7, "01 DENİZBANK", "DENİZBANK VADESİZ TL"),
    (9, "01 HALKBANK", "HALKBANK BÜYÜKÇEKMECE VADESİZ TL"),
    (10, "01 KUVEYT", "KUVEYT TÜRK VADESİZ TL"),
    (11, "01 PURLİKİT", "PURLİKİT AKBANK VADESİZ TL"),
    (12, "01 QNB", "QNB BANK VADESİZ TL"),
    (13, "01 VAKIFBANK", "VAKIFBANK BÜYÜKÇEKMECE VADESİZ TL"),
)


def _kart_ozeti(s: Session) -> list[dict]:
    hareket = dict(s.execute(select(FinansHareketi.hesap_id, func.count()).group_by(FinansHareketi.hesap_id)).all())
    sonuc = []
    for k in s.scalars(select(BankaKarti).order_by(BankaKarti.id)):
        altlar = {h.alt_hesap_turu or "": h for h in s.scalars(
            select(FinansHesabi).where(FinansHesabi.banka_karti_id == k.id))}
        sonuc.append({"id": k.id, "banka_adi": k.banka_adi, "sube": k.sube, "hesap_no": k.hesap_no, "iban": k.iban,
                      "aktif": bool(k.aktif),
                      "alt_hesaplar": {a: {"id": h.id, "hareket": int(hareket.get(h.id, 0)),
                                           "muhasebe_hesap_id": getattr(h, "muhasebe_hesap_id", None)}
                                       for a, h in altlar.items()}})
    return sonuc


def planla(s: Session, firma_id: int) -> dict:
    hesaplar = {h.hesap_kodu: h for h in s.scalars(select(HesapPlani).where(HesapPlani.firma_id == firma_id))}
    esleme = s.scalar(select(MuhasebeHesapEsleme).where(MuhasebeHesapEsleme.firma_id == firma_id,
                                                        MuhasebeHesapEsleme.anahtar == "kasa"))
    plan: dict = {"kasa": None, "hesap_ekle": [], "kart_bagla": [], "inceleme": [], "uyari": []}

    kasa = hesaplar.get(KASA_HESABI)
    if kasa is None or hesap_uygunluk_sorunu(s, kasa, firma_id):
        plan["uyari"].append(f"{KASA_HESABI} fişe uygun değil: {hesap_uygunluk_sorunu(s, kasa, firma_id) if kasa else 'yok'}")
    else:
        onceki = s.get(HesapPlani, esleme.hesap_id).hesap_kodu if esleme and esleme.hesap_id else None
        if onceki != KASA_HESABI:
            plan["kasa"] = {"onceki": onceki, "yeni": KASA_HESABI, "ad": kasa.hesap_adi}

    if "102" not in hesaplar:
        raise SystemExit("102 BANKALAR ana hesabı yok; işlem yapılmadı.")
    mevcut_alt = sorted(k for k in hesaplar if k.startswith("102."))
    if mevcut_alt:
        raise SystemExit(f"102 altında hesap var ({mevcut_alt}); planı elle gözden geçirin. İşlem yapılmadı.")
    plan["hesap_ekle"].append({"kod": BANKA_TALI[0], "ad": BANKA_TALI[1], "ust": "102", "tur": hesaplar["102"].hesap_turu})

    kartlar = {k["id"]: k for k in _kart_ozeti(s)}
    secilen = set()
    for i, (kid, onek, ad) in enumerate(BANKA_HESAPLARI, start=1):
        k = kartlar.get(kid)
        if k is None or not " ".join((k["banka_adi"] or "").split()).upper().startswith(onek.upper()):
            raise SystemExit(f"Banka kartı {kid} beklenen kart değil ({k and k['banka_adi']}); işlem yapılmadı.")
        mevduat = k["alt_hesaplar"].get("MEVDUAT")
        if mevduat is None:
            raise SystemExit(f"Banka kartı {kid} için MEVDUAT alt hesabı yok; işlem yapılmadı.")
        kod = f"102.01.{i:04d}"
        plan["hesap_ekle"].append({"kod": kod, "ad": ad[:100], "ust": BANKA_TALI[0], "tur": hesaplar["102"].hesap_turu})
        plan["kart_bagla"].append({"banka_karti_id": kid, "banka_adi": k["banka_adi"], "finans_hesap_id": mevduat["id"],
                                   "hareket": mevduat["hareket"], "hesap": kod, "hesap_adi": ad,
                                   "diger_alt_hareket": {a: v["hareket"] for a, v in k["alt_hesaplar"].items()
                                                         if a != "MEVDUAT" and v["hareket"]}})
        secilen.add(kid)
    for kid, k in kartlar.items():
        if kid not in secilen:
            plan["inceleme"].append({"banka_karti_id": kid, "banka_adi": k["banka_adi"], "hesap_no": k["hesap_no"],
                                     "hareket": {a: v["hareket"] for a, v in k["alt_hesaplar"].items() if v["hareket"]}})
    # Banka kartına bağlı olmayan eski banka hesapları
    for h in s.scalars(select(FinansHesabi).where(FinansHesabi.hesap_turu == "BANKA",
                                                  FinansHesabi.banka_karti_id.is_(None))):
        plan["inceleme"].append({"finans_hesap_id": h.id, "banka_adi": h.hesap_adi, "kartsiz": True,
                                 "hareket": s.scalar(select(func.count()).select_from(FinansHareketi)
                                                     .where(FinansHareketi.hesap_id == h.id))})
    return plan


def uygula(s: Session, firma_id: int, plan: dict) -> dict:
    hesaplar = {h.hesap_kodu: h for h in s.scalars(select(HesapPlani).where(HesapPlani.firma_id == firma_id))}

    def gecmis(kayit_turu, kayit_id, islem, detay):
        s.add(MuhasebeIslemGecmisi(firma_id=firma_id, kayit_turu=kayit_turu, kayit_id=int(kayit_id), islem=islem,
                                   detay=detay, kullanici_id=None, kullanici_adi=ISLEM_YAPAN[:80],
                                   tarih=datetime.now()))

    eklenen = []
    for h in plan["hesap_ekle"]:
        if h["kod"] in hesaplar:
            raise ValueError(f"Bu hesap kodu zaten var: {h['kod']}")
        ust = hesaplar[h["ust"]]
        yeni = HesapPlani(firma_id=firma_id, hesap_kodu=h["kod"], hesap_adi=h["ad"], ust_hesap_id=ust.id,
                          hesap_seviyesi=int(ust.hesap_seviyesi or 1) + 1, hesap_turu=h["tur"], aktif=True,
                          borc_toplam=0, alacak_toplam=0)
        s.add(yeni)
        s.flush()
        hesaplar[h["kod"]] = yeni
        gecmis("hesap", yeni.id, "ekle", f"{h['kod']} {h['ad']} (üst {h['ust']}, sıfır bakiye)")
        eklenen.append(h["kod"])
    s.flush()

    if plan["kasa"]:
        h = hesaplar[KASA_HESABI]
        e = s.scalar(select(MuhasebeHesapEsleme).where(MuhasebeHesapEsleme.firma_id == firma_id,
                                                       MuhasebeHesapEsleme.anahtar == "kasa"))
        e.hesap_id = h.id
        gecmis("esleme", e.id, "bagla", f"kasa: {plan['kasa']['onceki'] or '-'} → {KASA_HESABI}")

    for b in plan["kart_bagla"]:
        h = hesaplar[b["hesap"]]
        sorun = hesap_uygunluk_sorunu(s, h, firma_id)
        if sorun:
            raise ValueError(f"{b['hesap']} fişe uygun değil: {sorun}")
        fh = s.get(FinansHesabi, b["finans_hesap_id"])
        if fh.muhasebe_hesap_id:
            raise ValueError(f"{fh.hesap_adi} kartında zaten muhasebe hesabı var")
        fh.muhasebe_hesap_id = h.id
        gecmis("finans_kart_hesabi", fh.id, "bagla", f"{fh.hesap_adi} [muhasebe_hesap_id]: - → {b['hesap']}")
    s.flush()
    tali = hesaplar[BANKA_TALI[0]]
    if hesap_uygunluk_sorunu(s, tali, firma_id) is None:
        raise ValueError(f"{BANKA_TALI[0]} fişe kapalı olmalıydı")
    return {"eklenen_hesap": eklenen, "kasa": bool(plan["kasa"]), "baglanan_kart": len(plan["kart_bagla"])}


def olcum(baglanti) -> dict:
    o = ray.olcum(baglanti)
    o["belge_durumlari"] = dict(baglanti.execute(text(
        "SELECT durum, COUNT(*) FROM muhasebe_belge_durumlari GROUP BY durum")).all())
    o["finans_kart_hesaplari"] = dict(baglanti.execute(text(
        "SELECT id, muhasebe_hesap_id FROM finans_hesaplari WHERE muhasebe_hesap_id IS NOT NULL")).all())
    return o


def karsilastir(once: dict, sonra: dict, sonuc: dict, plan: dict) -> list[str]:
    sorunlar = []
    for t in sorted(set(once["tablo_sayilari"]) | set(sonra["tablo_sayilari"])):
        a, b = once["tablo_sayilari"].get(t), sonra["tablo_sayilari"].get(t)
        if a != b and t not in DEGISEBILIR_TABLOLAR:
            sorunlar.append(f"{t}: {a} → {b}")
    for k in ("fis", "fis_satiri", "hesap_plani_bakiye", "belge_durumlari"):
        if once[k] != sonra[k]:
            sorunlar.append(f"{k} değişti: {once[k]} → {sonra[k]}")
    for kod, deger in once["hesap_bakiyeleri"].items():
        if sonra["hesap_bakiyeleri"].get(kod) != deger:
            sorunlar.append(f"hesap bakiyesi değişti: {kod}")
    for kod in set(sonra["hesap_bakiyeleri"]) - set(once["hesap_bakiyeleri"]):
        if sonra["hesap_bakiyeleri"][kod] != [0.0, 0.0]:
            sorunlar.append(f"yeni hesap sıfır bakiyeli değil: {kod}")
    if (sonra["tablo_sayilari"]["muhasebe_hesap_plani"] - once["tablo_sayilari"]["muhasebe_hesap_plani"]
            != len(sonuc["eklenen_hesap"])):
        sorunlar.append("hesap planı satır artışı eklenen hesap sayısıyla eşleşmiyor")
    if sonra["tablo_sayilari"]["muhasebe_hesap_eslemeleri"] != once["tablo_sayilari"]["muhasebe_hesap_eslemeleri"]:
        sorunlar.append("eşleştirme satır sayısı değişti")
    if len(sonra["finans_kart_hesaplari"]) - len(once["finans_kart_hesaplari"]) != len(plan["kart_bagla"]):
        sorunlar.append("kart hesabı sayısı beklenenle eşleşmiyor")
    return sorunlar


# ====================================================================== şema
SEMA_KOLONLARI = {"muhasebe_hesap_id": "INTEGER", "muhasebe_komisyon_hesap_id": "INTEGER"}


def sema_eksikleri(db: Path) -> list[str]:
    eng = create_engine(f"sqlite:///{db.as_posix()}")
    try:
        d = inspect(eng)
        tablolar = set(d.get_table_names())
        kolonlar = {k["name"] for k in d.get_columns("finans_hesaplari")}
        eksik = [f"finans_hesaplari.{k}" for k in SEMA_KOLONLARI if k not in kolonlar]
        eksik += [t.__tablename__ for t in (KurFarkiKaydi, MuhasebeFinansAyari) if t.__tablename__ not in tablolar]
        return eksik
    finally:
        eng.dispose()


def sema_uygula(db: Path) -> list[str]:
    eng = create_engine(f"sqlite:///{db.as_posix()}")
    try:
        eksik = sema_eksikleri(db)
        with eng.begin() as c:
            for k, tur in SEMA_KOLONLARI.items():
                if f"finans_hesaplari.{k}" in eksik:
                    c.execute(text(f"ALTER TABLE finans_hesaplari ADD COLUMN {k} {tur}"))
            for t in (KurFarkiKaydi, MuhasebeFinansAyari):
                t.__table__.create(c, checkfirst=True)
        return eksik
    finally:
        eng.dispose()


def calistir(db: Path, *, yaz: bool) -> dict:
    eng = ray.motor(db)
    try:
        with Session(eng, autoflush=False, expire_on_commit=False) as s:
            baglanti = s.connection()
            fid = ray.firma_bul(baglanti, None)
            once = olcum(baglanti)
            plan = planla(s, fid)
            sonuc = uygula(s, fid, plan)
            sonra = olcum(s.connection())
            sorunlar = karsilastir(once, sonra, sonuc, plan)
            if sorunlar or not yaz:
                s.rollback()
            else:
                s.commit()
            return {"firma_id": fid, "plan": plan, "sonuc": sonuc, "once": once, "sonra": sonra,
                    "sorunlar": sorunlar, "yazildi": bool(yaz and not sorunlar)}
    finally:
        eng.dispose()


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--db", type=Path, default=ray.VARSAYILAN_DB)
    p.add_argument("--uygula", action="store_true")
    a = p.parse_args()
    if ray.program_acik_mi():
        raise SystemExit("CinMuhasebe.exe açık; programı kapatıp tekrar çalıştırın. İşlem yapılmadı.")
    rapor: dict = {"zaman": datetime.now().isoformat(timespec="seconds"), "kaynak_db": str(a.db),
                   "mod": "uygula" if a.uygula else "kuru"}
    rapor["butunluk_kaynak"] = ray.butunluk(a.db)
    if rapor["butunluk_kaynak"] != "ok":
        raise SystemExit(f"integrity_check başarısız: {rapor['butunluk_kaynak']}")
    hedef = a.db if a.uygula else ray.kopya_al(a.db)
    if not a.uygula:
        rapor["kopya_db"] = str(hedef)

    eksik = sema_eksikleri(hedef)
    rapor["sema_eksikleri"] = eksik
    if eksik:
        if a.uygula:
            from database.gecis_guvenligi import guvenli_gecis

            _, sema_yedek = guvenli_gecis(hedef, lambda: sema_uygula(hedef), gerekli=True,
                                          etiket="hesap_baglantilari_sema")
            rapor["sema_yedek"] = str(sema_yedek.yol) if sema_yedek else None
        else:
            sema_uygula(hedef)
        rapor["sema_sonrasi_eksik"] = sema_eksikleri(hedef)
        if rapor["sema_sonrasi_eksik"]:
            raise SystemExit(f"Şema tamamlanamadı: {rapor['sema_sonrasi_eksik']}")

    if a.uygula:
        from database.gecis_guvenligi import dogrulanmis_yedek

        yedek = dogrulanmis_yedek(hedef, "hesap_baglantilari_oncesi")
        rapor["yedek"] = {"yol": str(yedek.yol), "tablo": len(yedek.tablo_sayilari),
                          "satir": sum(yedek.tablo_sayilari.values()),
                          "dogrulama": "integrity_check ok, tablo satır sayıları kaynakla eşit"}
        print("Yedek:", yedek.yol)
    rapor["butunluk_once"] = ray.butunluk(hedef)
    if rapor["butunluk_once"] != "ok":
        raise SystemExit(f"integrity_check başarısız: {rapor['butunluk_once']}")
    rapor.update(calistir(hedef, yaz=True))
    rapor["butunluk_sonra"] = ray.butunluk(hedef)

    CIKTI_KLASORU.mkdir(parents=True, exist_ok=True)
    yol = CIKTI_KLASORU / f"muhasebe_hesap_baglantilari_{'uygulama' if a.uygula else 'kuru'}.json"
    yol.write_text(json.dumps(rapor, ensure_ascii=False, indent=1, default=str), encoding="utf-8")

    plan = rapor["plan"]
    print(f"Mod: {rapor['mod']} | hedef: {hedef} | şema eksikleri: {eksik or 'yok'}")
    print(f"Kasa: {plan['kasa']}")
    for h in plan["hesap_ekle"]:
        print(f"  HESAP {h['kod']} {h['ad']}")
    for b in plan["kart_bagla"]:
        print(f"  KART #{b['banka_karti_id']} {b['banka_adi']} MEVDUAT ({b['hareket']} hareket) → {b['hesap']}")
    for i in plan["inceleme"]:
        print(f"  İNCELEME {i}")
    print("Uyarı:", plan["uyari"] or "yok")
    print("Karşılaştırma sorunları:", rapor["sorunlar"] or "yok")
    print("integrity_check:", rapor["butunluk_once"], "→", rapor["butunluk_sonra"])
    print("Yazıldı:", rapor["yazildi"], "| rapor:", yol)
    if rapor["sorunlar"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
