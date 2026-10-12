"""Evo devir aktarımı: önizleme, aktarım, geri alma, mutabakat.

Yalnız devir tarihindeki son durum yazılır: kartlar + devir tarihli açılış kayıtları. Geçmiş Evo
hareketleri evrak olarak aktarılmaz. Her çalıştırma bir ``ImportBatch`` (aktarım kimliği) açar;
eklenen her satır tablo/kimlik olarak ``ImportChange``'e yazılır ve geri alma bu listeyi siler.
Aynı Evo kaydı (tür + Evo id) etkin bir aktarımda varsa yeniden yazılmaz.

    python -m entegrasyon.evo_devir.aktarim onizle  --anlik A.json --bakiye B.json --devir 06.10.2026
    python -m entegrasyon.evo_devir.aktarim aktar   --anlik A.json --bakiye B.json --devir 06.10.2026
    python -m entegrasyon.evo_devir.aktarim geri_al --batch EVODEVIR-...
    python -m entegrasyon.evo_devir.aktarim mutabakat --anlik A.json --bakiye B.json --devir 06.10.2026
    python -m entegrasyon.evo_devir.aktarim kart_mutabakat --anlik A.json --bakiye B.json --veri D:\\data
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path

from entegrasyon.evo_devir import oturum as evo_oturum

VARSAYILAN_VERI = r"C:\CinMuhasebeEvoDevir\data"
MODUL = "evo_devir"
DEPO = "ANA DEPO"
TEDARIKCI = "Evo devir (başlangıç devir katmanı)"
ACILIS_GIRIS = "AÇILIŞ"
ACILIS_CIKIS = "AÇILIŞ ÇIKIŞ"
SIFIR = Decimal("0")
KURUS = Decimal("0.01")


def _tarih(metin: str) -> date:
    return datetime.strptime(metin, "%d.%m.%Y").date()


def _json(deger) -> str:
    return json.dumps(deger, ensure_ascii=False, default=str)


# ---------------------------------------------------------------- tablo kimliği farkı

def _tablolar():
    from database.database import Base

    return [t for t in Base.metadata.sorted_tables if "id" in t.c]


def _en_buyuk_idler(session) -> dict[str, int]:
    from sqlalchemy import func, inspect, select

    mevcut = set(inspect(session.connection()).get_table_names())
    return {
        t.name: int(session.execute(select(func.coalesce(func.max(t.c.id), 0))).scalar() or 0)
        for t in _tablolar() if t.name in mevcut
    }


def _yeni_satirlar(session, once: dict[str, int]) -> dict[str, list[int]]:
    from sqlalchemy import select

    sonuc = {}
    for t in _tablolar():
        if t.name not in once or t.name.startswith("import_"):
            continue
        idler = [int(i) for i in session.execute(select(t.c.id).where(t.c.id > once[t.name])).scalars()]
        if idler:
            sonuc[t.name] = idler
    return sonuc


def _satirlari_sil(session, tablo_idleri: dict[str, list[int]]) -> dict[str, int]:
    """Bağımlılık sırasının tersine (önce çocuk tablolar) siler."""
    silinen = {}
    for t in reversed(_tablolar()):
        idler = tablo_idleri.get(t.name)
        if not idler:
            continue
        for i in range(0, len(idler), 500):
            session.execute(t.delete().where(t.c.id.in_(idler[i:i + 500])))
        silinen[t.name] = len(idler)
    return silinen


# ---------------------------------------------------------------- etkin aktarım haritası

def _etkin_harita() -> dict[tuple[str, str], dict]:
    from sqlalchemy import select

    from database.database import get_session
    from excel_aktarim.models import ImportBatch, ImportRow

    harita = {}
    with get_session() as s:
        q = (select(ImportRow, ImportBatch.batch_kodu)
             .join(ImportBatch, ImportBatch.id == ImportRow.batch_id)
             .where(ImportBatch.modul == MODUL, ImportBatch.durum.in_(("basarili", "kismi")),
                    ImportRow.durum == "uygulandi"))
        for row, kod in s.execute(q).all():
            ham = json.loads(row.ham_json or "{}")
            harita[(ham.get("tur"), str(ham.get("evo_id")))] = {
                "hedef_id": row.hedef_id, "batch": kod, "ek": json.loads(row.eslenen_json or "{}")}
    return harita


# ---------------------------------------------------------------- yazıcılar

class Yazici:
    def __init__(self, plan, devir: date):
        self.plan = plan
        self.devir = devir
        self.satirlar: list[dict] = []
        self.harita = _etkin_harita()
        self.kurlar: dict[str, Decimal] = {}

    def kayit(self, tur, evo_id, durum, mesaj="", tablo=None, hedef_id=None, ek=None):
        self.satirlar.append({"tur": tur, "evo_id": str(evo_id), "durum": durum, "mesaj": mesaj,
                              "tablo": tablo, "hedef_id": hedef_id, "ek": ek or {}})

    def zaten(self, tur, evo_id) -> bool:
        onceki = self.harita.get((tur, str(evo_id)))
        if onceki:
            self.kayit(tur, evo_id, "atla", f"Önceki aktarımda yazıldı ({onceki['batch']})", hedef_id=onceki["hedef_id"])
            return True
        return False

    # -- kur
    def kur(self, kod: str) -> Decimal:
        if kod in ("TRY", "TL"):
            return Decimal("1")
        if kod not in self.kurlar:
            from database.doviz_service import DovizService

            try:
                self.kurlar[kod] = DovizService.kur_degeri(self.devir, kod, "forex_selling")
            except ValueError:
                DovizService.tcmb_kurlari_cek(self.devir)
                self.kurlar[kod] = DovizService.kur_degeri(self.devir, kod, "forex_selling")
        return self.kurlar[kod]

    # -- cari
    def cariler(self):
        from database.cari_service import CariService
        from database.models.cari import Cari

        sutunlar = set(Cari.__table__.columns.keys()) - {"id"}
        for c in self.plan.cariler:
            if self.zaten("cari", c["evo_id"]):
                continue
            try:
                veriler = {k: v for k, v in c["veriler"].items() if k in sutunlar}
                veriler["aktif"] = bool(c.get("aktif", True))
                cari = CariService.ekle(veriler)
            except Exception as hata:  # satır hatası: aktarım sürer, rapora yazılır
                self.kayit("cari", c["evo_id"], "hata", f"{type(hata).__name__}: {hata}")
                continue
            ek = {"cari_kodu": cari.cari_kodu}
            if c["tutar"] and c["yon"]:
                try:
                    _, anlam = CariService.acilis_bakiyesi_ekle(
                        cari.id, self.devir, tutar=c["tutar"], yon=c["yon"],
                        belge_no=f"EVB-ACL-{c['evo_id']}",
                        aciklama=f"Evo devir açılışı {self.devir:%d.%m.%Y} (Evo cari id {c['evo_id']})",
                    )
                    ek.update(acilis_tutar=str(c["tutar"]), yon=c["yon"], anlam=anlam.durum)
                except Exception as hata:
                    self.kayit("cari_acilis", c["evo_id"], "hata", f"{type(hata).__name__}: {hata}",
                               ek={"tutar": str(c["tutar"]), "yon": c["yon"], "cari_id": cari.id})
            self.kayit("cari", c["evo_id"], "uygulandi", tablo="cariler", hedef_id=cari.id, ek=ek)

    # -- stok
    def stoklar(self):
        from sqlalchemy import select

        from database.database import get_session
        from database.models.stok import StokFiyati, StokKarti
        from database.stok_service import StokService
        from entegrasyon.stok_import import kaydet_veya_guncelle

        for st in self.plan.stoklar:
            if self.zaten("stok", st["evo_id"]):
                continue
            veriler = dict(st["veriler"])
            veriler["_fiyatlar"] = list(veriler.get("_fiyatlar") or [])
            kod = veriler["stok_kodu"]
            try:
                with get_session() as s:
                    if s.scalar(select(StokKarti.id).where(StokKarti.stok_kodu == kod)):
                        raise ValueError(f"Stok kodu {kod} hedefte zaten var; Evo kartı eşleşmesi belirsiz")
                kaydet_veya_guncelle(veriler)
                ek = {"stok_kodu": kod}
                with get_session() as s:
                    stok = s.scalar(select(StokKarti).where(StokKarti.stok_kodu == kod))
                    if stok is None:
                        raise ValueError("Stok kartı oluşturulamadı (kod/ad boş olabilir)")
                    stok_id = stok.id
                    for f in s.scalars(select(StokFiyati).where(StokFiyati.stok_id == stok_id)):
                        ad = (f.fiyat_adi or "").upper()
                        pb = st["alis_doviz"] if ad == "ALIŞ FİYATI" else st.get("satis_doviz", "TRY")
                        if pb in ("USD", "EUR", "GBP"):
                            f.para_birimi = pb
                            ek[f"fiyat_pb:{f.fiyat_adi}"] = pb
            except Exception as hata:
                self.kayit("stok", st["evo_id"], "hata", f"{type(hata).__name__}: {hata}")
                continue
            try:
                if st["kalan"] > 0:
                    pb = st["alis_doviz"]
                    kur = self.kur(pb) if pb in ("USD", "EUR", "GBP") else Decimal("1")
                    maliyet = (st["alis_fiyati"] * kur).quantize(Decimal("0.0001"))
                    lot = StokService.stok_girisi(kod, DEPO, TEDARIKCI, self.devir, st["kalan"], maliyet,
                                                  f"EVB-SG-{st['evo_id']}")
                    ek.update(miktar=str(st["kalan"]), birim_maliyet_tl=str(maliyet), lot=lot.lot_no,
                              maliyet_kaynagi="Evo son alış fiyatı")
                    if kur != 1:
                        ek.update(doviz=pb, doviz_fiyat=str(st["alis_fiyati"]), kur=str(kur),
                                  kur_kaynagi=f"TCMB döviz satış {self.devir:%d.%m.%Y}")
            except Exception as hata:
                self.kayit("stok_acilis", st["evo_id"], "hata", f"{type(hata).__name__}: {hata}",
                           ek={"miktar": str(st["kalan"]), "stok_id": stok_id})
            self.kayit("stok", st["evo_id"], "uygulandi", tablo="stok_kartlari", hedef_id=stok_id, ek=ek)

    # -- kasa / banka
    def _acilis_hareketi(self, hesap_id: int, tutar: Decimal, belge: str, aciklama: str):
        from database.database import get_session
        from database.models.finans import FinansHareketi

        tutar = Decimal(tutar).quantize(KURUS)
        if tutar == 0:
            return None
        with get_session() as s:
            h = FinansHareketi(hesap_id=hesap_id, tarih=self.devir,
                               hareket_turu=ACILIS_GIRIS if tutar > 0 else ACILIS_CIKIS,
                               belge_no=belge, tutar=abs(tutar), aciklama=aciklama[:500])
            s.add(h)
            s.flush()
            return h.id

    def finans(self):
        from sqlalchemy import select

        from database.database import get_session
        from database.finans_service import FinansService
        from database.models.finans import BankAccountMatchRule, FinansHesabi
        from entegrasyon.evo_devir.eslestirme import maskele

        for f in self.plan.finans:
            tur, evo_id = f["evo_tur"], f["evo_id"]
            if self.zaten(tur, evo_id):
                continue
            try:
                metin = (f"Evo devir açılışı {self.devir:%d.%m.%Y} (Evo {tur} id {evo_id}; "
                         f"kaynak: {'Evo bakiye raporu' if f.get('bakiye_kaynagi') == 'evo_dogrudan_bakiye' else 'hareket toplamı'})")
                if f["sinif"] == "KARSILIKSIZ":
                    self.kayit(tur, evo_id, "atla", "Cin'de karşılığı yok; aktarılmadı (rapora yazıldı)",
                               ek={"bakiye": str(f["net"])})
                    continue
                if tur == "kasa":
                    # Devir bakiyesi kartın açılış bakiyesidir; ayrıca hareket yazılmaz (eksi ise eksi kalır)
                    hesap = FinansService.hesap_kaydet({
                        "hesap_adi": f["ad"], "hesap_turu": "KASA",
                        "acilis_bakiyesi": Decimal(f["net"]).quantize(KURUS),
                        "aciklama": f"Evo kasa id {evo_id}",
                    })
                    self.kayit(tur, evo_id, "uygulandi", tablo="finans_hesaplari", hedef_id=hesap.id,
                               ek={"KASA": str(f["net"]), "acilis_bakiyesi": str(Decimal(f["net"]).quantize(KURUS))})
                    continue
                ad = maskele(f["ad"])[:100]
                kart = FinansService.banka_karti_kaydet({
                    "banka_adi": ad,
                    "hesap_no": "" if f["sinif"] == "KREDI_KARTI" else (f.get("evo_kod") or "")[:50],
                    "pos_valor_gun": f.get("pos_valor_gun") or 1,
                    "aciklama": f"Evo banka id {evo_id}; sınıf {f['sinif']}",
                })
                with get_session() as s:
                    alt = {(h.alt_hesap_turu or "").upper(): h.id for h in
                           s.scalars(select(FinansHesabi).where(FinansHesabi.banka_karti_id == kart.id))}
                ek = {"banka_karti_id": kart.id}
                ana_alt = next(iter(f["hedefler"]), "MEVDUAT")
                for hedef, tutar in f["hedefler"].items():
                    if hedef not in alt:
                        raise ValueError(f"{hedef} alt hesabı oluşmadı")
                    ek[hedef] = str(tutar)
                    ek[f"hareket_{hedef}"] = self._acilis_hareketi(
                        alt[hedef], tutar, f"EVB-FA-B{evo_id}-{hedef}"[:50], metin)
                with get_session() as s:
                    s.add(BankAccountMatchRule(
                        evo_banka_id=str(evo_id), evo_banka_adi=ad[:200], banka_karti_id=kart.id,
                        finans_hesap_id=alt.get(ana_alt), alt_hesap_turu=ana_alt, kaynak="evo_devir", guven=Decimal("1"),
                    ))
                if f["sinif"] == "KREDI_KARTI":
                    kk = FinansService.kredi_karti_kaydet({
                        "kart_adi": ad, "banka_karti_id": kart.id,
                        "son_dort_hane": f.get("kart_son4") if len(f.get("kart_son4") or "") == 4 else "",
                        "bagli_hesap_id": alt.get("KREDI_KARTI"),
                        "aciklama": f"Evo banka id {evo_id}; limit/kesim/son ödeme kaynakta yok",
                    })
                    ek["kredi_karti_id"] = kk.id
                self.kayit(tur, evo_id, "uygulandi", tablo="banka_kartlari", hedef_id=kart.id, ek=ek)
            except Exception as hata:
                self.kayit(tur, evo_id, "hata", f"{type(hata).__name__}: {hata}")


# ---------------------------------------------------------------- komutlar

def _plan(a):
    from entegrasyon.evo_devir.eslestirme import plan_olustur

    return plan_olustur(a.anlik, _tarih(a.devir), a.bakiye)


def onizle(a) -> dict:
    from entegrasyon.evo_devir.eslestirme import ozet

    plan = _plan(a)
    o = ozet(plan)
    o["bulgu_ornek"] = [vars(b) for b in plan.bulgular if b.seviye == "hata"][:40]
    o["finans"] = [{k: f.get(k) for k in ("evo_tur", "evo_id", "ad_maskeli", "sinif", "net", "hareket_toplami",
                                          "bakiye_kaynagi", "hedefler")} for f in plan.finans]
    return o


def aktar(a) -> dict:
    from sqlalchemy import select

    from database.database import get_session
    from excel_aktarim.models import ImportBatch, ImportChange, ImportRow

    t0 = time.time()
    plan = _plan(a)
    devir = _tarih(a.devir)
    kod = f"EVODEVIR-{datetime.now():%Y%m%d%H%M%S}"
    with get_session() as s:
        onceki = s.scalars(select(ImportBatch).where(ImportBatch.modul == MODUL,
                                                     ImportBatch.durum == "basarili")).all()
        ayni = [b.batch_kodu for b in onceki if plan.kaynak_sha256 in (b.notlar or "")]
        batch = ImportBatch(
            batch_kodu=kod, modul=MODUL, import_tipi="evo_devir_son_durum",
            dosya_adi=Path(plan.kaynak_dosya).name, dosya_yolu=plan.kaynak_dosya[:500], durum="taslak",
            kullanici_adi="Evo devir aktarımı", basladi_at=datetime.now(),
            notlar=_json({"kaynak_sha256": plan.kaynak_sha256, "bakiye_dosyasi": plan.bakiye_dosyasi,
                          "bakiye_sha256": plan.bakiye_sha256, "devir_tarihi": devir.isoformat(),
                          "ayni_kaynakla_onceki": ayni}),
        )
        s.add(batch)
        s.flush()
        batch_id = batch.id
        once = _en_buyuk_idler(s)

    y = Yazici(plan, devir)
    try:
        for adim in (y.cariler, y.stoklar, y.finans):
            t = time.time()
            adim()
            print(f"{adim.__name__}: {time.time() - t:.0f} sn", flush=True)
    except BaseException as hata:
        with get_session() as s:
            silinen = _satirlari_sil(s, _yeni_satirlar(s, once))
            b = s.get(ImportBatch, batch_id)
            b.durum, b.bitti_at = "hatali", datetime.now()
            b.hata_ozeti = f"{type(hata).__name__}: {hata}; otomatik geri alındı {silinen}"[:4000]
        raise

    with get_session() as s:
        yeni = _yeni_satirlar(s, once)
        for tablo, idler in yeni.items():
            s.add_all(ImportChange(batch_id=batch_id, hedef_tablo=tablo, hedef_id=i, islem="insert") for i in idler)
        for no, r in enumerate(y.satirlar, start=1):
            s.add(ImportRow(batch_id=batch_id, satir_no=no,
                            ham_json=_json({"tur": r["tur"], "evo_id": r["evo_id"]}),
                            eslenen_json=_json(r["ek"]), durum=r["durum"], mesaj=r["mesaj"][:2000] or None,
                            hedef_tablo=r["tablo"], hedef_id=r["hedef_id"],
                            islem="insert" if r["durum"] == "uygulandi" else "skip"))
        b = s.get(ImportBatch, batch_id)
        b.toplam_satir = len(y.satirlar)
        b.eklenen_satir = b.basarili_satir = sum(r["durum"] == "uygulandi" for r in y.satirlar)
        b.hata_satir = sum(r["durum"] == "hata" for r in y.satirlar)
        b.atlanan_satir = sum(r["durum"] == "atla" for r in y.satirlar)
        b.durum = "kismi" if b.hata_satir else "basarili"
        b.bitti_at = datetime.now()
        sonuc = {"batch": kod, "durum": b.durum, "sure_sn": round(time.time() - t0),
                 "satir": {"uygulandi": b.basarili_satir, "hata": b.hata_satir, "atla": b.atlanan_satir},
                 "eklenen_tablo_satiri": {t: len(i) for t, i in yeni.items()},
                 "kurlar": {k: str(v) for k, v in y.kurlar.items()},
                 "hatalar": [r for r in y.satirlar if r["durum"] == "hata"][:50]}
    return sonuc


def geri_al(a) -> dict:
    from sqlalchemy import select

    from database.database import get_session
    from excel_aktarim.models import ImportBatch, ImportChange, ImportRow

    with get_session() as s:
        b = s.scalar(select(ImportBatch).where(ImportBatch.batch_kodu == a.batch))
        if b is None or b.modul != MODUL:
            raise SystemExit(f"Aktarım bulunamadı: {a.batch}")
        if b.durum not in ("basarili", "kismi"):
            raise SystemExit(f"Aktarım durumu {b.durum}; geri alınamaz")
        degisim = s.scalars(select(ImportChange).where(ImportChange.batch_id == b.id,
                                                       ImportChange.geri_alindi.is_(False))).all()
        tablo_idleri: dict[str, list[int]] = {}
        for ch in degisim:
            tablo_idleri.setdefault(ch.hedef_tablo, []).append(int(ch.hedef_id))
        silinen = _satirlari_sil(s, tablo_idleri)
        for ch in degisim:
            ch.geri_alindi = True
        for r in s.scalars(select(ImportRow).where(ImportRow.batch_id == b.id, ImportRow.durum == "uygulandi")):
            r.durum = "geri_alindi"
        b.durum = "geri_alindi"
        b.notlar = (b.notlar or "") + f"\nGeri alındı: {datetime.now().isoformat(timespec='seconds')}"
    return {"batch": a.batch, "silinen": silinen}


def _finans_mutabakat(s, plan) -> list[dict]:
    """Her Evo kasa/banka hesabı için Cin alt hesap bakiyeleri (KASA, MEVDUAT, POS, KMH, KK, KREDİLER)."""
    from sqlalchemy import select

    from database.finans_service import FinansService
    from database.models.finans import BankaKarti, FinansHesabi

    kartlar = {}
    for k in s.scalars(select(BankaKarti)):
        evo = (k.aciklama or "").split(";")[0].replace("Evo banka id", "").strip()
        kartlar[evo] = k.id
    satirlar = []
    for f in plan.finans:
        satir = {"evo_tur": f["evo_tur"], "evo_id": f["evo_id"], "ad": f.get("ad_maskeli") or f["ad"],
                 "sinif": f["sinif"], "doviz": f["doviz"], "evo_bakiye": str(f["net"]),
                 "kaynak": f.get("bakiye_kaynagi")}
        if f["evo_tur"] == "kasa":
            h = s.scalar(select(FinansHesabi).where(FinansHesabi.aciklama == f"Evo kasa id {f['evo_id']}"))
            satir["cin"] = {"KASA": str(FinansService.bakiye(h))} if h else None
        else:
            kid = kartlar.get(f["evo_id"])
            satir["cin"] = {(h.alt_hesap_turu or ""): str(FinansService.bakiye(h)) for h in s.scalars(
                select(FinansHesabi).where(FinansHesabi.banka_karti_id == kid))
                if FinansService.bakiye(h) != 0} if kid else None
        satir["evo_hedef"] = {k: str(v) for k, v in f["hedefler"].items() if v != 0}
        satir["tutuyor"] = (satir["cin"] or {}) == satir["evo_hedef"] or (
            f["sinif"] == "KARSILIKSIZ" and satir["cin"] is None)
        satirlar.append(satir)
    return satirlar


CIFT_ETKI_TABLOLARI = (
    "banka_kredileri", "banka_kredi_taksitleri", "cek_senet_evraklari", "kredi_karti_ekstreleri",
    "kredi_karti_odemeleri", "kk_cekimleri", "muhasebe_fisleri",
)


def _cift_etki_kontrol(s) -> dict:
    """Devir sonrası aynı borç/alacağın ikinci kez yazılıp yazılmadığı.

    Evo devri yalnız açılış hareketi yazar: cari ``Açılış``, finans ``AÇILIŞ`` / ``AÇILIŞ ÇIKIŞ``.
    Kredi, çek/senet, KK ekstre/çekim veya muhasebe fişi kaydı normal ekranlardan girilirse
    KREDİLER / cari bakiyesine ikinci kez etki eder; burada sayılır ve listelenir. ``detay_aktarim``
    ile hareketsiz bağlanan devir ayrıntıları ayrı sayılır.
    """
    from sqlalchemy import inspect, text

    from entegrasyon.evo_devir.detay_aktarim import DEVIR_ISARETI

    mevcut = set(inspect(s.connection()).get_table_names())
    devir_detay_kosulu = {
        "banka_kredileri": "aciklama LIKE :isaret",
        "banka_kredi_taksitleri": "kredi_id IN (SELECT id FROM banka_kredileri WHERE aciklama LIKE :isaret)",
        "cek_senet_evraklari": "aciklama LIKE :isaret",
    }
    isaret = {"isaret": f"{DEVIR_ISARETI}%"}
    tablolar, devir_detay = {}, {}
    for t in CIFT_ETKI_TABLOLARI:
        if t not in mevcut:
            tablolar[t] = None
            continue
        kosul = devir_detay_kosulu.get(t)
        if kosul:
            devir_detay[t] = s.execute(text(f"SELECT COUNT(*) FROM {t} WHERE {kosul}"), isaret).scalar()
            tablolar[t] = s.execute(text(f"SELECT COUNT(*) FROM {t} WHERE NOT ({kosul})"), isaret).scalar()
        else:
            tablolar[t] = s.execute(text(f"SELECT COUNT(*) FROM {t}")).scalar()
    finans_diger = s.execute(text(
        "SELECT hareket_turu, COUNT(*), COALESCE(SUM(tutar), 0) FROM finans_hareketleri "
        "WHERE hareket_turu NOT IN (:g, :c) GROUP BY hareket_turu"), {"g": ACILIS_GIRIS, "c": ACILIS_CIKIS}).all()
    cari_diger = s.execute(text(
        "SELECT islem_turu, COUNT(*) FROM cari_islemleri WHERE islem_turu <> 'Açılış' GROUP BY islem_turu")).all()
    mukerrer_belge = s.execute(text(
        "SELECT belge_no, COUNT(*) FROM finans_hareketleri WHERE belge_no LIKE 'EVB-%' "
        "GROUP BY belge_no HAVING COUNT(*) > 1")).all() + s.execute(text(
        "SELECT belge_no, COUNT(*) FROM cari_islemleri WHERE belge_no LIKE 'EVB-%' "
        "GROUP BY belge_no HAVING COUNT(*) > 1")).all()
    stok_lot_mukerrer = s.execute(text(
        "SELECT lot_no, COUNT(*) FROM stok_lotlari WHERE lot_no LIKE 'EVB-%' "
        "GROUP BY lot_no HAVING COUNT(*) > 1")).all()
    riskli = {t: n for t, n in tablolar.items() if n}
    return {
        "tablo_sayilari": tablolar,
        "devir_detay_kayitlari": devir_detay,
        "devir_disi_finans_hareketi": [{"tur": r[0], "adet": r[1], "tutar": str(r[2])} for r in finans_diger],
        "devir_disi_cari_islem": [{"tur": r[0], "adet": r[1]} for r in cari_diger],
        "mukerrer_evb_belge": [{"belge_no": r[0], "adet": r[1]} for r in mukerrer_belge],
        "mukerrer_evb_lot": [{"lot_no": r[0], "adet": r[1]} for r in stok_lot_mukerrer],
        "temiz": not (riskli or finans_diger or cari_diger or mukerrer_belge or stok_lot_mukerrer),
    }


def kart_mutabakat(a) -> dict:
    """Her Evo kartını aktarımda eşlendiği Cin kartıyla tek tek karşılaştırır.

    Cari: programın liste bakiyesi (``net_bakiye``) = açılış anlamına göre beklenen işaretli tutar.
    Stok: lot kalan miktarı ve TL birim maliyeti (dövizlide aktarımda kullanılan TCMB kuru).
    Kasa/banka/KK/kredi: alt hesap bakiyeleri.
    """
    from sqlalchemy import select

    from database.cari_acilis_anlam import acilis_anlami
    from database.cari_bakiye_service import net_bakiye
    from database.database import get_session
    from database.models.cari import Cari, CariIslem
    from database.models.stok import StokKarti, StokLotu

    plan = _plan(a)
    harita = _etkin_harita()
    sonuc: dict = {"cari": {}, "stok": {}, "finans": {}}

    with get_session() as s:
        farklar, eksik, tutan = [], [], 0
        toplam_beklenen = toplam_cin = SIFIR
        for c in plan.cariler:
            es = harita.get(("cari", str(c["evo_id"])))
            cari = s.get(Cari, es["hedef_id"]) if es and es["hedef_id"] else None
            if cari is None:
                eksik.append({"evo_id": c["evo_id"], "unvan": c["veriler"].get("unvan")})
                continue
            beklenen = SIFIR
            if c["tutar"] and c["yon"]:
                anlam = acilis_anlami(cari.cari_turu, c["yon"])
                beklenen = Decimal(c["tutar"]).quantize(KURUS) * (1 if anlam.kalem_borc else -1)
            cin = Decimal(str(net_bakiye(cari.id, session=s)["bakiye"])).quantize(KURUS)
            acilis_adet = len(s.scalars(select(CariIslem.id).where(
                CariIslem.cari_id == cari.id, CariIslem.belge_no == f"EVB-ACL-{c['evo_id']}")).all())
            toplam_beklenen += beklenen
            toplam_cin += cin
            if cin == beklenen and acilis_adet == (1 if beklenen else 0):
                tutan += 1
            else:
                farklar.append({"evo_id": c["evo_id"], "cari_kodu": cari.cari_kodu, "tur": cari.cari_turu,
                                "evo": f"{c['tutar']} {c['yon']}", "beklenen": str(beklenen),
                                "cin": str(cin), "acilis_hareketi": acilis_adet})
        sonuc["cari"] = {"evo_kart": len(plan.cariler), "tutan": tutan, "fark": len(farklar),
                         "eslesmeyen": len(eksik), "beklenen_net_toplam": str(toplam_beklenen),
                         "cin_net_toplam": str(toplam_cin), "farklar": farklar[:100], "eslesmeyenler": eksik[:100]}

        farklar, eksik, tutan, yuvarlanan = [], [], 0, []
        toplam_maliyet = SIFIR
        for st in plan.stoklar:
            es = harita.get(("stok", str(st["evo_id"])))
            stok = s.get(StokKarti, es["hedef_id"]) if es and es["hedef_id"] else None
            if stok is None:
                eksik.append({"evo_id": st["evo_id"], "stok_kodu": st["veriler"].get("stok_kodu")})
                continue
            lotlar = s.scalars(select(StokLotu).where(StokLotu.stok_id == stok.id)).all()
            cin_miktar = sum((Decimal(str(l.kalan_miktar or 0)) for l in lotlar), SIFIR)
            cin_maliyet = sum((Decimal(str(l.kalan_miktar or 0)) * Decimal(str(l.birim_maliyet or 0))
                               for l in lotlar), SIFIR).quantize(KURUS)
            kalan = Decimal(st["kalan"])
            # Cin miktarı Numeric(18, 4); Evo 6 ondalık tutabilir
            beklenen_miktar = kalan.quantize(Decimal("0.0001")) if kalan > 0 else SIFIR
            if kalan > 0 and beklenen_miktar != kalan:
                yuvarlanan.append({"stok_kodu": stok.stok_kodu, "evo_kalan": str(kalan),
                                   "cin_miktar": str(cin_miktar)})
            kur = Decimal(es["ek"].get("kur") or "1")
            birim = (Decimal(st["alis_fiyati"]) * kur).quantize(Decimal("0.0001"))
            beklenen_maliyet = (beklenen_miktar * birim).quantize(KURUS)
            toplam_maliyet += cin_maliyet
            if cin_miktar == beklenen_miktar and cin_maliyet == beklenen_maliyet:
                tutan += 1
            else:
                farklar.append({"evo_id": st["evo_id"], "stok_kodu": stok.stok_kodu, "evo_kalan": str(kalan),
                                "cin_miktar": str(cin_miktar), "beklenen_maliyet": str(beklenen_maliyet),
                                "cin_maliyet": str(cin_maliyet), "doviz": st["alis_doviz"]})
        sonuc["stok"] = {"evo_kart": len(plan.stoklar), "tutan": tutan, "fark": len(farklar),
                         "eslesmeyen": len(eksik), "dort_ondaliga_yuvarlanan": yuvarlanan,
                         "negatif_evo_kalan": sum(1 for st in plan.stoklar if st["kalan"] < 0),
                         "cin_maliyet_toplam": str(toplam_maliyet),
                         "farklar": farklar[:100], "eslesmeyenler": eksik[:100]}

        finans = _finans_mutabakat(s, plan)
        sinif_toplam: dict[str, Decimal] = {}
        for f in finans:
            for alt, tutar in (f["cin"] or {}).items():
                sinif_toplam[alt] = sinif_toplam.get(alt, SIFIR) + Decimal(tutar)
        sonuc["finans"] = {"evo_hesap": len(finans), "tutan": sum(1 for f in finans if f["tutuyor"]),
                           "fark": [f for f in finans if not f["tutuyor"]],
                           "cin_alt_hesap_toplam": {k: str(v) for k, v in sinif_toplam.items()},
                           "hesaplar": finans}
        sonuc["cift_etki"] = _cift_etki_kontrol(s)
    return sonuc


def mutabakat(a) -> dict:
    """Evo planı ile Cin firma verisini tür, aktif/pasif ve para birimi bazında karşılaştırır."""
    from sqlalchemy import func, select

    from database.database import get_session
    from database.models.cari import Cari, CariIslem
    from database.models.finans import FinansHareketi
    from database.models.stok import StokFiyati, StokKarti, StokLotu

    plan = _plan(a)
    sonuc: dict = {"cari": {}, "stok": {}, "finans": [], "ciro_kdv": {}}
    with get_session() as s:
        evo_tur = {}
        for c in plan.cariler:
            evo_tur.setdefault(c["tur"], {"adet": 0, "B": SIFIR, "A": SIFIR})
            evo_tur[c["tur"]]["adet"] += 1
            if c["yon"]:
                evo_tur[c["tur"]][c["yon"]] += c["tutar"]
        for tur, e in evo_tur.items():
            adet = s.scalar(select(func.count()).select_from(Cari).where(Cari.cari_turu == tur))
            aktif = s.scalar(select(func.count()).select_from(Cari).where(Cari.cari_turu == tur, Cari.aktif.is_(True)))
            borc, alacak = s.execute(
                select(func.coalesce(func.sum(CariIslem.borc), 0), func.coalesce(func.sum(CariIslem.alacak), 0))
                .join(Cari, Cari.id == CariIslem.cari_id)
                .where(Cari.cari_turu == tur, CariIslem.islem_turu == "Açılış")).one()
            # Tedarikçide program kalem yönü tersine yazar (A → borç sütunu)
            cin_b, cin_a = (Decimal(str(alacak)), Decimal(str(borc))) if tur == "Tedarikçi" else (
                Decimal(str(borc)), Decimal(str(alacak)))
            sonuc["cari"][tur] = {"evo_adet": e["adet"], "cin_adet": adet, "cin_aktif": aktif, "cin_pasif": adet - aktif,
                                  "evo_borclu": str(e["B"]), "cin_borclu": str(cin_b),
                                  "evo_alacakli": str(e["A"]), "cin_alacakli": str(cin_a),
                                  "fark_borclu": str(cin_b - e["B"]), "fark_alacakli": str(cin_a - e["A"])}
        evo_miktar = sum((st["kalan"] for st in plan.stoklar if st["kalan"] > 0), SIFIR)
        cin_miktar = s.scalar(select(func.coalesce(func.sum(StokLotu.kalan_miktar), 0)))
        sonuc["stok"] = {
            "evo_kart": len(plan.stoklar), "cin_kart": s.scalar(select(func.count()).select_from(StokKarti)),
            "cin_aktif": s.scalar(select(func.count()).select_from(StokKarti).where(StokKarti.aktif.is_(True))),
            "evo_miktarli": sum(1 for st in plan.stoklar if st["kalan"] > 0),
            "cin_lotlu": s.scalar(select(func.count(func.distinct(StokLotu.stok_id)))),
            "evo_miktar": str(evo_miktar), "cin_miktar": str(Decimal(str(cin_miktar))),
            "cin_maliyet_tl": str(Decimal(str(s.scalar(select(func.coalesce(
                func.sum(StokLotu.kalan_miktar * StokLotu.birim_maliyet), 0))))).quantize(KURUS)),
            "doviz_fiyat": dict(s.execute(select(StokFiyati.para_birimi, func.count())
                                          .group_by(StokFiyati.para_birimi)).all()),
        }
        sonuc["finans"] = _finans_mutabakat(s, plan)
        from database.models.satis_faturasi import SatisFaturasi
        from database.models.alis_faturasi import AlisFaturasi

        sonuc["ciro_kdv"] = {
            "satis_faturasi": s.scalar(select(func.count()).select_from(SatisFaturasi)),
            "alis_faturasi": s.scalar(select(func.count()).select_from(AlisFaturasi)),
            "finans_hareket_turleri": dict(s.execute(select(FinansHareketi.hareket_turu, func.count())
                                                     .group_by(FinansHareketi.hareket_turu)).all()),
        }
    return sonuc


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    p = argparse.ArgumentParser()
    p.add_argument("komut", choices=("onizle", "aktar", "geri_al", "mutabakat", "kart_mutabakat"))
    p.add_argument("--anlik")
    p.add_argument("--bakiye")
    p.add_argument("--devir", default="06.10.2026")
    p.add_argument("--batch")
    p.add_argument("--veri", default=VARSAYILAN_VERI)
    p.add_argument("--unvan", default=evo_oturum.VARSAYILAN_UNVAN)
    p.add_argument("--rapor", help="Sonucu bu JSON dosyasına da yaz")
    a = p.parse_args()
    if a.komut != "geri_al" and not (a.anlik and a.bakiye):
        p.error("--anlik ve --bakiye gerekli")

    evo_oturum.veri_klasoru_sec(a.veri)
    if a.komut == "onizle":
        sonuc = onizle(a)
    else:
        bilgi = evo_oturum.firma_oturumu_ac(a.unvan)
        print(f"Firma: {bilgi['unvan']} ({bilgi['kod']}) {bilgi['yol']}", flush=True)
        sonuc = {"aktar": aktar, "geri_al": geri_al, "mutabakat": mutabakat,
                 "kart_mutabakat": kart_mutabakat}[a.komut](a)
    metin = json.dumps(sonuc, ensure_ascii=False, indent=1, default=str)
    if a.rapor:
        Path(a.rapor).parent.mkdir(parents=True, exist_ok=True)
        Path(a.rapor).write_text(metin, encoding="utf-8")
    print(metin)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
