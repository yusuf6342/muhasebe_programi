"""Evo devir kasa bakiyesi düzeltmesi: yalnız kasa kartları, devir tarihindeki Evo bakiyesiyle.

Kaynak: ``guncel_bakiye`` çıktısı (Evo'nun kendi hesapladığı, ``son_tarih`` = devir tarihli kasa
bakiyesi). Geçmiş Evo kasa hareketleri okunmaz/aktarılmaz.

Her Evo kasası, devir aktarımında eşlendiği Cin kasa kartına (``ImportRow`` tür "kasa") bağlanır;
para birimi eşleşmezse o kasa yazılmaz. Düzeltme:

* Evo devir bakiyesi kartın açılış bakiyesine yazılır (üzerine eklenmez; eksi ise eksi kalır).
* Aktarımla gelen kasa hareketleri (``EVB-`` belgeli veya bir aktarımın eklediği) silinir; aynı
  bakiye bir de hareket olarak sayılmaz. Silinen satır geri alma için saklanır.
* Cin'de girilen diğer kasa hareketlerine dokunulmaz: güncel bakiye = devir bakiyesi + bunlar.

Kart zaten doğruysa hiçbir şey yazılmaz; tekrar çalıştırmak bakiyeyi ikinci kez eklemez.

    python -m entegrasyon.evo_devir.kasa_devir_duzelt kontrol --bakiye B.json
    python -m entegrasyon.evo_devir.kasa_devir_duzelt duzelt  --bakiye B.json
    python -m entegrasyon.evo_devir.kasa_devir_duzelt geri_al --batch EVOKASA-...
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path

from entegrasyon.evo_devir import oturum as evo_oturum
from entegrasyon.evo_devir.detay_aktarim import VARSAYILAN_VERI, _program_acik_mi

MODUL = "evo_devir_kasa"
KULLANICI = "Evo devir kasa düzeltmesi"
CIN_PARA_BIRIMI = "TRY"
EVO_DOVIZ = {"TL": "TRY", "TRY": "TRY", "USD": "USD", "EUR": "EUR", "GBP": "GBP"}
KURUS = Decimal("0.01")
SIFIR = Decimal("0")


def _gun(metin: str) -> date:
    return datetime.strptime(metin, "%d.%m.%Y").date()


def _json(deger) -> str:
    return json.dumps(deger, ensure_ascii=False, default=str)


def evo_kasalari(yol: Path, devir: date) -> list[dict]:
    from entegrasyon.evo_devir.guncel_bakiye import bakiye

    g = json.loads(Path(yol).read_text(encoding="utf-8"))
    if (g.get("son_tarih") or "").strip() != f"{devir:%d.%m.%Y}":
        raise SystemExit(f"Bakiye dosyası {g.get('son_tarih')} tarihli; devir tarihi {devir:%d.%m.%Y}")
    sonuc = []
    for k in g.get("kasalar") or []:
        deger = bakiye(k)
        sonuc.append({
            "evo_id": str(k["id"]), "ad": k.get("ad"), "evo_doviz": (k.get("doviz") or "TL").strip().upper(),
            "bakiye": Decimal(deger).quantize(KURUS) + SIFIR if deger is not None else None,
            "filtre_dogru": bool(k.get("filtre_dogru")),
        })
    return sonuc


def _aktarim_hareketleri(s, hesap_id: int) -> list:
    """Kasadaki aktarım katmanı hareketleri: ``EVB-`` belgeli veya bir aktarım batch'inin eklediği."""
    from sqlalchemy import or_, select

    from database.models.finans import FinansHareketi
    from excel_aktarim.models import ImportChange

    eklenen = select(ImportChange.hedef_id).where(ImportChange.hedef_tablo == "finans_hareketleri",
                                                  ImportChange.islem == "insert",
                                                  ImportChange.geri_alindi.is_(False))
    return list(s.scalars(select(FinansHareketi).where(
        FinansHareketi.hesap_id == hesap_id,
        or_(FinansHareketi.belge_no.like("EVB-%"), FinansHareketi.id.in_(eklenen)),
    ).order_by(FinansHareketi.id)))


def _satir_json(nesne) -> dict:
    return {c.name: getattr(nesne, c.key) for c in nesne.__table__.columns}


def _etki(hareketler) -> Decimal:
    from database.finans_service import FinansService

    return sum((Decimal(str(h.tutar or 0)) * FinansService.hareket_isareti(h.hareket_turu) for h in hareketler),
               SIFIR).quantize(KURUS)


def durum(s, kasalar: list[dict]) -> list[dict]:
    """Her Evo kasası için eşleşme, Cin devir bakiyesi ve yapılacak düzeltme (yazmaz)."""
    from sqlalchemy import select

    from database.finans_service import FinansService
    from database.models.finans import FinansHesabi
    from entegrasyon.evo_devir.aktarim import _etkin_harita

    harita = _etkin_harita()
    satirlar, eslenen = [], set()
    for k in kasalar:
        satir = {"evo_id": k["evo_id"], "evo_ad": k["ad"], "evo_doviz": k["evo_doviz"],
                 "evo_devir_bakiyesi": k["bakiye"], "sorun": None}
        es = harita.get(("kasa", k["evo_id"]))
        hesap = s.get(FinansHesabi, int(es["hedef_id"])) if es and es.get("hedef_id") else None
        if hesap is None:
            satir["sorun"] = "Cin kasa kartı eşleşmesi yok"
        elif (hesap.hesap_turu or "").upper() != "KASA":
            satir["sorun"] = f"Eşlenen kart kasa değil ({hesap.hesap_turu})"
        elif EVO_DOVIZ.get(k["evo_doviz"]) != CIN_PARA_BIRIMI:
            satir["sorun"] = f"Para birimi eşleşmiyor: Evo {k['evo_doviz']}, Cin kasa {CIN_PARA_BIRIMI}"
        elif k["bakiye"] is None or not k["filtre_dogru"]:
            satir["sorun"] = "Evo devir bakiyesi okunamadı"
        if hesap is not None:
            eslenen.add(hesap.id)
            aktarim = _aktarim_hareketleri(s, hesap.id)
            aktarim_idleri = {h.id for h in aktarim}
            sonra = [h for h in hesap.hareketler if h.id not in aktarim_idleri]
            acilis = Decimal(str(hesap.acilis_bakiyesi or 0)).quantize(KURUS)
            cin_devir = (acilis + _etki(aktarim)).quantize(KURUS)
            satir.update({
                "cin_hesap_id": hesap.id, "cin_hesap_adi": hesap.hesap_adi, "cin_para_birimi": CIN_PARA_BIRIMI,
                "cin_acilis_bakiyesi": acilis, "aktarim_hareketi": [
                    {"id": h.id, "belge_no": h.belge_no, "tur": h.hareket_turu, "tutar": str(h.tutar)} for h in aktarim],
                "cin_devir_bakiyesi": cin_devir,
                "devir_sonrasi_hareket": len(sonra), "devir_sonrasi_toplam": _etki(sonra),
                "guncel_bakiye": Decimal(str(FinansService.bakiye(hesap))).quantize(KURUS),
            })
            if not satir["sorun"]:
                satir["fark"] = (cin_devir - k["bakiye"]).quantize(KURUS)
                satir["duzeltme_gerekli"] = bool(aktarim) or acilis != k["bakiye"]
        satirlar.append(satir)
    for hesap in s.scalars(select(FinansHesabi).where(FinansHesabi.hesap_turu == "KASA")):
        if hesap.id not in eslenen:
            satirlar.append({"evo_id": None, "cin_hesap_id": hesap.id, "cin_hesap_adi": hesap.hesap_adi,
                             "sorun": "Evo karşılığı yok; dokunulmadı",
                             "guncel_bakiye": Decimal(str(FinansService.bakiye(hesap))).quantize(KURUS)})
    return satirlar


def _ozet(satirlar: list[dict]) -> list[dict]:
    """Ekrana: kasa, Evo devir bakiyesi, Cin düzeltilmiş devir bakiyesi, fark."""
    return [{"kasa": r.get("cin_hesap_adi") or r.get("evo_ad"), "evo_id": r.get("evo_id"),
             "para_birimi": f"Evo {r.get('evo_doviz', '-')} / Cin {r.get('cin_para_birimi', '-')}",
             "evo_devir_bakiyesi": r.get("evo_devir_bakiyesi"), "cin_devir_bakiyesi": r.get("cin_devir_bakiyesi"),
             "fark": r.get("fark"), "devir_sonrasi_toplam": r.get("devir_sonrasi_toplam"),
             "guncel_bakiye": r.get("guncel_bakiye"), "sorun": r.get("sorun")} for r in satirlar]


def yedekle(veri: Path, firma_db: Path) -> Path:
    hedef = veri / "yedekler" / f"kasa_devir_duzelt_{datetime.now():%Y%m%d_%H%M%S}"
    hedef.mkdir(parents=True, exist_ok=False)
    for kaynak in (firma_db, veri / "system.db"):
        if not kaynak.is_file():
            continue
        src, dst = sqlite3.connect(str(kaynak)), sqlite3.connect(str(hedef / kaynak.name))
        try:
            src.backup(dst)
        finally:
            dst.close()
            src.close()
    return hedef


def kontrol(a) -> dict:
    from database.database import get_session

    kasalar = evo_kasalari(Path(a.bakiye), _gun(a.devir))
    with get_session() as s:
        satirlar = durum(s, kasalar)
    return {"bakiye_dosyasi": a.bakiye, "devir": a.devir, "kasalar": _ozet(satirlar), "ayrinti": satirlar,
            "duzeltme_gerekli": [r["cin_hesap_adi"] for r in satirlar if r.get("duzeltme_gerekli")]}


def duzelt(a) -> dict:
    from database.database import get_session
    from database.models.finans import FinansHesabi, FinansHareketi
    from excel_aktarim.models import ImportBatch, ImportChange, ImportRow

    acik = _program_acik_mi()
    if acik:
        raise SystemExit(f"Önce Evo Devir Deneme programını kapatın: {acik}")
    devir = _gun(a.devir)
    kasalar = evo_kasalari(Path(a.bakiye), devir)
    with get_session() as s:
        plan = durum(s, kasalar)
    yapilacak = [r for r in plan if r.get("duzeltme_gerekli")]
    if not yapilacak:
        sonuc = kontrol(a)
        sonuc["yazildi"] = False
        sonuc["mesaj"] = "Kasa devir bakiyeleri zaten Evo ile aynı; hiçbir kayıt yazılmadı"
        return sonuc

    yedek = yedekle(Path(a.veri), Path(a.firma_db))
    kod = f"EVOKASA-{datetime.now():%Y%m%d%H%M%S}"
    with get_session() as s:
        batch = ImportBatch(batch_kodu=kod, modul=MODUL, import_tipi="evo_devir_kasa_bakiye",
                            dosya_adi=Path(a.bakiye).name, dosya_yolu=str(a.bakiye)[:500], durum="taslak",
                            kullanici_adi=KULLANICI, basladi_at=datetime.now(),
                            notlar=_json({"devir_tarihi": devir.isoformat(), "yedek": str(yedek)}))
        s.add(batch)
        s.flush()
        for no, r in enumerate(yapilacak, start=1):
            hesap = s.get(FinansHesabi, r["cin_hesap_id"])
            for har in _aktarim_hareketleri(s, hesap.id):
                s.add(ImportChange(batch_id=batch.id, satir_no=no, hedef_tablo="finans_hareketleri",
                                   hedef_id=har.id, islem="delete", onceki_json=_json(_satir_json(har)),
                                   tutar=har.tutar))
                hesap.hareketler.remove(har)
                s.delete(har)
            onceki = Decimal(str(hesap.acilis_bakiyesi or 0))
            hesap.acilis_bakiyesi = r["evo_devir_bakiyesi"]
            s.add(ImportChange(batch_id=batch.id, satir_no=no, hedef_tablo="finans_hesaplari", hedef_id=hesap.id,
                               islem="update", onceki_json=_json({"acilis_bakiyesi": str(onceki)}),
                               sonraki_json=_json({"acilis_bakiyesi": str(r["evo_devir_bakiyesi"])}),
                               tutar=r["evo_devir_bakiyesi"]))
            s.add(ImportRow(batch_id=batch.id, satir_no=no,
                            ham_json=_json({"tur": "kasa", "evo_id": r["evo_id"],
                                            "evo_devir_bakiyesi": str(r["evo_devir_bakiyesi"])}),
                            eslenen_json=_json({"onceki_cin_devir_bakiyesi": str(r["cin_devir_bakiyesi"]),
                                                "silinen_aktarim_hareketi": r["aktarim_hareketi"]}),
                            durum="uygulandi", hedef_tablo="finans_hesaplari", hedef_id=hesap.id, islem="update"))
        s.flush()
        b = s.get(ImportBatch, batch.id)
        b.toplam_satir = b.basarili_satir = len(yapilacak)
        b.durum, b.bitti_at = "basarili", datetime.now()
    sonuc = kontrol(a)
    sonuc.update({"yazildi": True, "batch": kod, "yedek": str(yedek),
                  "once": _ozet(plan)})
    return sonuc


def geri_al(a) -> dict:
    from sqlalchemy import select

    from database.database import Base, get_session
    from excel_aktarim.models import ImportBatch, ImportChange, ImportRow

    tablolar = {t.name: t for t in Base.metadata.sorted_tables}
    with get_session() as s:
        b = s.scalar(select(ImportBatch).where(ImportBatch.batch_kodu == a.batch))
        if b is None or b.modul != MODUL:
            raise SystemExit(f"Kasa düzeltmesi bulunamadı: {a.batch}")
        if b.durum != "basarili":
            raise SystemExit(f"Düzeltme durumu {b.durum}; geri alınamaz")
        degisim = s.scalars(select(ImportChange).where(ImportChange.batch_id == b.id,
                                                       ImportChange.geri_alindi.is_(False))).all()
        donen = {"update": 0, "delete": 0}
        for ch in degisim:
            t = tablolar[ch.hedef_tablo]
            onceki = json.loads(ch.onceki_json or "{}")
            if ch.islem == "update":
                onceki = {k: Decimal(v) for k, v in onceki.items()}
                s.execute(t.update().where(t.c.id == ch.hedef_id).values(**onceki))
            elif ch.islem == "delete" and s.execute(select(t.c.id).where(t.c.id == ch.hedef_id)).first() is None:
                onceki["tarih"] = date.fromisoformat(onceki["tarih"])
                onceki["tutar"] = Decimal(onceki["tutar"])
                s.execute(t.insert().values(**onceki))
            donen[ch.islem] = donen.get(ch.islem, 0) + 1
            ch.geri_alindi = True
        for r in s.scalars(select(ImportRow).where(ImportRow.batch_id == b.id, ImportRow.durum == "uygulandi")):
            r.durum = "geri_alindi"
        b.durum = "geri_alindi"
        b.notlar = (b.notlar or "") + f"\nGeri alındı: {datetime.now().isoformat(timespec='seconds')}"
    return {"batch": a.batch, "geri_donen": donen}


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    p = argparse.ArgumentParser()
    p.add_argument("komut", choices=("kontrol", "duzelt", "geri_al"))
    p.add_argument("--bakiye", help="guncel_bakiye çıktısı (son_tarih = devir tarihi)")
    p.add_argument("--devir", default="06.10.2026")
    p.add_argument("--batch")
    p.add_argument("--veri", default=VARSAYILAN_VERI)
    p.add_argument("--unvan", default=evo_oturum.VARSAYILAN_UNVAN)
    p.add_argument("--rapor", help="Sonucu bu JSON dosyasına da yaz")
    a = p.parse_args()
    if a.komut != "geri_al" and not a.bakiye:
        p.error("--bakiye gerekli")
    if a.komut == "geri_al" and not a.batch:
        p.error("--batch gerekli")

    evo_oturum.veri_klasoru_sec(a.veri)
    bilgi = evo_oturum.firma_oturumu_ac(a.unvan)
    a.firma_db = bilgi["yol"]
    print(f"Firma: {bilgi['unvan']} ({bilgi['kod']}) {bilgi['yol']}", flush=True)
    sonuc = {"kontrol": kontrol, "duzelt": duzelt, "geri_al": geri_al}[a.komut](a)
    metin = json.dumps(sonuc, ensure_ascii=False, indent=1, default=str)
    if a.rapor:
        Path(a.rapor).parent.mkdir(parents=True, exist_ok=True)
        Path(a.rapor).write_text(metin, encoding="utf-8")
    print(metin)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
