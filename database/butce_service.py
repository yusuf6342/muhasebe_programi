"""Bütçe planı servisi — oluşturma, satır kaydı, eşit aylık dağıtım, gerçekleşen adaptörleri.

Ön Muhasebe ve Genel Muhasebe ayrı kaynaklardır; asla toplanmaz.
Nakit bütçesinde iç virman firma nakdini artırmaz.
Plan açmak / kaydetmek fatura, fiş veya stok hareketi üretmez.
"""

from __future__ import annotations

import re
from calendar import monthrange
from datetime import date, datetime
from decimal import Decimal, InvalidOperation, ROUND_DOWN, ROUND_HALF_UP
from pathlib import Path
from typing import Any

from sqlalchemy import select

import database.database as _db
from database.database import Base, get_session
from database.models.butce import (
    DURUM_ARSIV,
    DURUM_GECISLER,
    DURUM_KILITLI,
    DURUM_ONAYLI,
    DURUM_TASLAK,
    DURUMLAR,
    OLCU_BILANCO,
    OLCU_GIDER,
    OLCU_NAKIT,
    OLCU_SATIS,
    OLCU_TURLERI,
    SENARYO_TEMEL,
    SENARYOLAR,
    ButceBilancoHedef,
    ButceEslesme,
    ButcePlan,
    ButceSatir,
)

_Q = Decimal("0.01")
_SIFIR = Decimal("0.00")
_KOD_RE = re.compile(r"^BTC-(\d{4})-(\d{4})$")

AY_ADLARI = (
    "Ocak",
    "Şubat",
    "Mart",
    "Nisan",
    "Mayıs",
    "Haziran",
    "Temmuz",
    "Ağustos",
    "Eylül",
    "Ekim",
    "Kasım",
    "Aralık",
)

GIRIS_DAGITIM = "DAGITIM"
GIRIS_MANUEL = "MANUEL"
GIRIS_EXCEL = "EXCEL"

# Taslak / iptal — gerçekleşmeye dahil edilmez
_SATIS_HARIC_DURUM = frozenset({"TASLAK", "İPTAL", "IPTAL", "IPTAL EDİLDİ"})
_GIDER_HARIC_DURUM = frozenset({"TASLAK", "İPTAL", "IPTAL", "IPTAL EDİLDİ"})

KAYNAK_ON_MUHASEBE = "ON_MUHASEBE"
KAYNAK_GENEL_MUHASEBE = "GENEL_MUHASEBE"
KAYNAK_YAN_YANA = "YAN_YANA"
KAYNAK_ETIKET = "Ön Muhasebe"
KAYNAK_ETIKET_GM = "Genel Muhasebe"
KAYNAK_ETIKET_YY = "Yan Yana Karşılaştırma"

# Firma içi kasa/banka aktarımları — gerçek dış nakit giriş/çıkış sayılmaz
_IC_VIRMAN_TURLERI = frozenset(
    {
        "VIRMAN GİRİŞ",
        "VIRMAN ÇIKIŞ",
        "BANKA VİRMAN GİRİŞ",
        "BANKA VİRMAN ÇIKIŞ",
        "KASADAN BANKAYA YATAN",
        "KASADAN BANKAYA (KASA)",
        "BANKADAN NAKİT (KASA)",
        "BANKADAN NAKİT ÇEKİLEN",
        "POS → KMH AKTARIM (KMH)",
        "POS → KMH AKTARIM (POS)",
        "POS VALÖR AKTARIM (HEDEF)",
        "POS VALÖR AKTARIM (POS)",
    }
)

# Kullanılabilir nakit: kasa + mevduat/KMH (POS alacağı, KK borcu, kredi borcu hariç)
_NAKIT_ALT_TURLER = frozenset({"MEVDUAT", "KMH", ""})

_EXCEL_BASLIKLAR = ("kategori", "olcu_turu", "para_birimi", "ay", "tutar")
_OLCU_EXCEL_MAP = {
    "SATIS": OLCU_SATIS,
    "SATIŞ": OLCU_SATIS,
    "ALIS": "ALIS",
    "ALIŞ": "ALIS",
    "GIDER": OLCU_GIDER,
    "GİDER": OLCU_GIDER,
    "KARLILIK": "KARLILIK",
    "KÂRLILIK": "KARLILIK",
    "NAKIT": OLCU_NAKIT,
    "NAKİT": OLCU_NAKIT,
}


def _q2(v) -> Decimal:
    return Decimal(str(v or 0)).quantize(_Q, rounding=ROUND_HALF_UP)


def _firma_id(firma_id: int | None = None) -> int:
    if firma_id is not None:
        return int(firma_id)
    try:
        from database.session_manager import oturum

        return int(oturum.company_id or 0)
    except Exception:  # noqa: BLE001
        return 0


def _kullanici() -> str | None:
    try:
        from database.session_manager import oturum

        return oturum.ad_soyad or oturum.kullanici_adi or None
    except Exception:  # noqa: BLE001
        return None


def dagit_yillik_esit(yillik: Decimal | int | float | str, ay_sayisi: int = 12) -> list[Decimal]:
    """Yıllık tutarı aylara eşit böler; kuruş artığını son aya yazar. Toplam = yıllık."""
    if ay_sayisi < 1:
        raise ValueError("ay_sayisi en az 1 olmalıdır.")
    hedef = _q2(yillik)
    if ay_sayisi == 1:
        return [hedef]
    birim = (hedef / Decimal(ay_sayisi)).quantize(_Q, rounding=ROUND_DOWN)
    aylar = [birim] * (ay_sayisi - 1)
    son = (hedef - birim * (ay_sayisi - 1)).quantize(_Q, rounding=ROUND_HALF_UP)
    aylar.append(son)
    return aylar


def parse_tr_tutar(metin: str | None, *, bos_izinli: bool = False) -> Decimal | None:
    """Türkçe / düz sayı biçimi: 1250000 ve 1.250.000,00 aynı tutar.

    Boş metin → None (eksik ay). Geçersiz biçim ValueError.
    """
    s = (metin or "").strip().replace("TL", "").replace("tl", "").replace("\u00a0", " ")
    s = s.replace(" ", "")
    if not s:
        if bos_izinli:
            return None
        raise ValueError("Tutar boş olamaz.")
    # Yalnızca rakam, nokta, virgül, eksi
    if not re.fullmatch(r"-?[0-9.,]+", s):
        raise ValueError(f"Geçersiz tutar biçimi: «{metin}»")
    if "," in s and "." in s:
        # 1.250.000,00 → binlik nokta, ondalık virgül
        s = s.replace(".", "").replace(",", ".")
    elif "," in s:
        # 1250000,50 veya 1,5
        s = s.replace(",", ".")
    # yalnız nokta: 1250000.50 (ondalık) veya 1.250.000 (binlik)
    elif s.count(".") > 1:
        s = s.replace(".", "")
    elif s.count(".") == 1:
        sol, sag = s.split(".")
        if len(sag) == 3 and sag.isdigit() and sol.replace("-", "").isdigit():
            # 1.250 gibi üç haneli grup → binlik
            s = sol + sag
    try:
        return _q2(Decimal(s))
    except (InvalidOperation, ValueError) as hata:
        raise ValueError(f"Geçersiz tutar: «{metin}»") from hata


def ay_adi(ay: int) -> str:
    if 1 <= int(ay) <= 12:
        return AY_ADLARI[int(ay) - 1]
    return str(ay)


class ButceService:
    _schema_hazir = False

    @classmethod
    def ensure_schema(cls, eng=None) -> None:
        """create_all(checkfirst) — mevcut veriyi silmez.

        ``from database.database import engine`` ile alınan sabit referans
        firma_db_ac sonrası bayat kalır; her zaman aktif motoru kullan.
        """
        bag = eng if eng is not None else _db.engine
        if bag is None:
            return
        import database.models.butce  # noqa: F401

        Base.metadata.create_all(
            bind=bag,
            tables=[
                ButcePlan.__table__,
                ButceSatir.__table__,
                ButceEslesme.__table__,
                ButceBilancoHedef.__table__,
            ],
        )
        # Eski DB: yeni kolonlar (IF NOT EXISTS benzeri try)
        from sqlalchemy import text

        alterler = (
            'ALTER TABLE butce_planlari ADD COLUMN senaryo VARCHAR(20) DEFAULT "TEMEL"',
            "ALTER TABLE butce_planlari ADD COLUMN kaynak_plan_id INTEGER",
            "ALTER TABLE butce_planlari ADD COLUMN proje_kodu VARCHAR(40)",
            "ALTER TABLE butce_planlari ADD COLUMN onay_tarihi DATETIME",
            "ALTER TABLE butce_planlari ADD COLUMN onaylayan VARCHAR(120)",
            "ALTER TABLE butce_satirlari ADD COLUMN kaynak_giris VARCHAR(20)",
        )
        try:
            with bag.begin() as conn:
                for sql in alterler:
                    try:
                        conn.execute(text(sql))
                    except Exception:
                        pass
        except Exception:
            pass
        cls._schema_hazir = True

    @classmethod
    def _sonraki_kod(cls, session, firma_id: int, mali_yil: int) -> str:
        """BTC-YYYY-#### — firma+yıl içinde çakışmasız (max+1)."""
        onek = f"BTC-{int(mali_yil)}-"
        max_n = 0
        for kod in session.scalars(
            select(ButcePlan.kod).where(
                ButcePlan.firma_id == firma_id,
                ButcePlan.kod.like(f"{onek}%"),
            )
        ).all():
            m = _KOD_RE.match((kod or "").strip())
            if m and int(m.group(1)) == int(mali_yil):
                max_n = max(max_n, int(m.group(2)))
        return f"{onek}{max_n + 1:04d}"

    @classmethod
    def plan_olustur(
        cls,
        ad: str,
        mali_yil: int,
        *,
        para_birimi: str = "TRY",
        firma_id: int | None = None,
        aciklama: str | None = None,
        durum: str = DURUM_TASLAK,
    ) -> dict[str, Any]:
        cls.ensure_schema()
        ad = (ad or "").strip()
        if not ad:
            raise ValueError("Bütçe adı zorunludur.")
        if durum not in DURUMLAR:
            raise ValueError(f"Geçersiz durum: {durum}")
        fid = _firma_id(firma_id)
        with get_session() as session:
            kod = cls._sonraki_kod(session, fid, int(mali_yil))
            # Eşzamanlı çakışmaya karşı kısa yeniden deneme
            for _ in range(5):
                var = session.scalar(
                    select(ButcePlan.id).where(
                        ButcePlan.firma_id == fid,
                        ButcePlan.kod == kod,
                    )
                )
                if var is None:
                    break
                kod = cls._sonraki_kod(session, fid, int(mali_yil))
            plan = ButcePlan(
                kod=kod,
                ad=ad,
                mali_yil=int(mali_yil),
                durum=durum,
                para_birimi=(para_birimi or "TRY").upper()[:3],
                firma_id=fid,
                surum=1,
                aciklama=(aciklama or None),
                olusturma=datetime.now(),
                olusturan=_kullanici(),
            )
            session.add(plan)
            session.flush()
            return cls._plan_dict(plan)

    @classmethod
    def planlari_listele(
        cls,
        *,
        firma_id: int | None = None,
        mali_yil: int | None = None,
    ) -> list[dict[str, Any]]:
        cls.ensure_schema()
        fid = _firma_id(firma_id)
        with get_session() as session:
            q = select(ButcePlan).where(ButcePlan.firma_id == fid)
            if mali_yil is not None:
                q = q.where(ButcePlan.mali_yil == int(mali_yil))
            q = q.order_by(ButcePlan.mali_yil.desc(), ButcePlan.kod.desc())
            return [cls._plan_dict(p) for p in session.scalars(q).all()]

    @classmethod
    def plan_getir(cls, plan_id: int, *, firma_id: int | None = None) -> dict[str, Any] | None:
        cls.ensure_schema()
        fid = _firma_id(firma_id)
        with get_session() as session:
            plan = session.get(ButcePlan, int(plan_id))
            if plan is None or int(plan.firma_id) != fid:
                return None
            d = cls._plan_dict(plan)
            d["satirlar"] = [
                cls._satir_dict(s)
                for s in session.scalars(
                    select(ButceSatir)
                    .where(ButceSatir.plan_id == plan.id)
                    .order_by(ButceSatir.olcu_turu, ButceSatir.kategori, ButceSatir.ay)
                ).all()
            ]
            return d

    @classmethod
    def plan_duzenlenebilir(
        cls, plan_id: int, *, firma_id: int | None = None
    ) -> tuple[bool, str]:
        """(izin, neden). Kilitli / arşiv / başka firma → False."""
        plan = cls.plan_getir(plan_id, firma_id=firma_id)
        if plan is None:
            return False, "Bütçe planı bulunamadı veya başka firmaya aittir."
        if plan["durum"] == DURUM_KILITLI:
            return False, "Plan kilitli; tutar düzenlenemez. Önce kilidi kaldırın veya revizyon açın."
        if plan["durum"] == DURUM_ARSIV:
            return False, "Arşivlenmiş plan düzenlenemez."
        return True, ""

    @classmethod
    def satirlar_kaydet(
        cls,
        plan_id: int,
        satirlar: list[dict[str, Any]],
        *,
        firma_id: int | None = None,
        olcu_turu: str | None = None,
        kategori: str | None = None,
        beklenen_surum: int | None = None,
    ) -> list[dict[str, Any]]:
        """Satırları kaydet / güncelle. Aynı (olcu, kategori, ay) yeniden yazılır (idempotent).

        ``olcu_turu`` / ``kategori`` verilirse o kapsam dışındaki satırlar silinmez;
        verilen listedeki anahtarlar upsert edilir. Listede olmayan aynı kapsamdaki aylar
        silinmez (kısmi kayıt güvenli). Tam kapsama için tüm 12 ayı gönderin.
        ``beklenen_surum`` verilirse eşzamanlı yazmada çakışma bildirilir (sessiz ezme yok).
        """
        cls.ensure_schema()
        fid = _firma_id(firma_id)
        izin, neden = cls.plan_duzenlenebilir(plan_id, firma_id=fid)
        if not izin:
            raise ValueError(neden)
        degisen: list[dict[str, Any]] = []
        with get_session() as session:
            plan = session.get(ButcePlan, int(plan_id))
            if plan is None or int(plan.firma_id) != fid:
                raise ValueError("Bütçe planı bulunamadı.")
            if plan.durum in (DURUM_KILITLI, DURUM_ARSIV):
                raise ValueError(f"«{plan.durum}» durumda plan satırları değiştirilemez.")
            if beklenen_surum is not None and int(plan.surum or 1) != int(beklenen_surum):
                raise ValueError(
                    "Bu bütçe planı başka bir oturumda değiştirilmiş. "
                    "Listeyi yenileyip güncel sürümü açın (sessizce üzerine yazılmaz)."
                )
            kaydedilen: list[ButceSatir] = []
            for raw in satirlar:
                olcu = (raw.get("olcu_turu") or olcu_turu or "").strip().upper()
                if olcu not in OLCU_TURLERI:
                    raise ValueError(f"Geçersiz ölçü türü: {olcu}")
                kat = (raw.get("kategori") or kategori or "GENEL").strip() or "GENEL"
                ay = int(raw["ay"])
                if ay < 1 or ay > 12:
                    raise ValueError(f"Ay 1–12 olmalı: {ay}")
                tutar = _q2(raw.get("tutar"))
                if olcu != OLCU_NAKIT and tutar < _SIFIR:
                    raise ValueError(
                        f"{ay_adi(ay)}: «{olcu}» ölçüsünde negatif plan tutarı kabul edilmez."
                    )
                aciklama = raw.get("aciklama")
                kaynak_giris = (raw.get("kaynak_giris") or "").strip().upper() or None
                mevcut = session.scalar(
                    select(ButceSatir).where(
                        ButceSatir.plan_id == plan.id,
                        ButceSatir.olcu_turu == olcu,
                        ButceSatir.kategori == kat,
                        ButceSatir.ay == ay,
                    )
                )
                eski_tutar = None
                if mevcut is None:
                    mevcut = ButceSatir(
                        plan_id=plan.id,
                        olcu_turu=olcu,
                        kategori=kat,
                        ay=ay,
                        tutar=tutar,
                        aciklama=aciklama,
                        kaynak_giris=kaynak_giris,
                    )
                    session.add(mevcut)
                    degisen.append(
                        {
                            "ay": ay,
                            "olcu": olcu,
                            "kategori": kat,
                            "eski": None,
                            "yeni": str(tutar),
                        }
                    )
                else:
                    eski_tutar = _q2(mevcut.tutar)
                    if eski_tutar != tutar or (
                        kaynak_giris and getattr(mevcut, "kaynak_giris", None) != kaynak_giris
                    ):
                        degisen.append(
                            {
                                "ay": ay,
                                "olcu": olcu,
                                "kategori": kat,
                                "eski": str(eski_tutar),
                                "yeni": str(tutar),
                            }
                        )
                    mevcut.tutar = tutar
                    if aciklama is not None:
                        mevcut.aciklama = aciklama
                    if kaynak_giris is not None:
                        mevcut.kaynak_giris = kaynak_giris
                kaydedilen.append(mevcut)
            plan.guncelleme = datetime.now()
            plan.guncelleyen = _kullanici()
            if degisen:
                plan.surum = int(plan.surum or 1) + 1
            session.flush()
            sonuc = [cls._satir_dict(s) for s in kaydedilen]
        if degisen:
            try:
                from database.user_audit import audit_document

                audit_document(
                    "BUTCE_SATIR_GUNCELLE",
                    modul="butce",
                    kayit_id=str(plan_id),
                    belge_no=None,
                    eski={"satirlar": [{"ay": d["ay"], "tutar": d["eski"]} for d in degisen]},
                    yeni={"satirlar": [{"ay": d["ay"], "tutar": d["yeni"]} for d in degisen]},
                    aciklama=f"{len(degisen)} aylık plan tutarı güncellendi",
                )
            except Exception:
                pass
        return sonuc

    @classmethod
    def yillik_dagit_ve_kaydet(
        cls,
        plan_id: int,
        yillik_tutar: Decimal | int | float | str,
        *,
        olcu_turu: str = OLCU_SATIS,
        kategori: str = "GENEL",
        firma_id: int | None = None,
        aciklama: str | None = None,
    ) -> list[dict[str, Any]]:
        """Yıllık tutarı 12 aya eşit dağıtıp kaydeder (son aya kuruş)."""
        olcu = (olcu_turu or OLCU_SATIS).strip().upper()
        if olcu not in OLCU_TURLERI:
            raise ValueError(f"Geçersiz ölçü türü: {olcu}")
        aylik = dagit_yillik_esit(_q2(yillik_tutar), 12)
        satirlar = [
            {
                "olcu_turu": olcu,
                "kategori": kategori or "GENEL",
                "ay": i + 1,
                "tutar": aylik[i],
                "aciklama": aciklama,
                "kaynak_giris": GIRIS_DAGITIM,
            }
            for i in range(12)
        ]
        return cls.satirlar_kaydet(plan_id, satirlar, firma_id=firma_id)

    @classmethod
    def plan_satirlari(
        cls,
        plan_id: int,
        *,
        olcu_turu: str | None = None,
        kategori: str | None = None,
        firma_id: int | None = None,
    ) -> list[dict[str, Any]]:
        cls.ensure_schema()
        fid = _firma_id(firma_id)
        with get_session() as session:
            plan = session.get(ButcePlan, int(plan_id))
            if plan is None or int(plan.firma_id) != fid:
                return []
            q = select(ButceSatir).where(ButceSatir.plan_id == plan.id)
            if olcu_turu:
                q = q.where(ButceSatir.olcu_turu == olcu_turu.strip().upper())
            if kategori:
                q = q.where(ButceSatir.kategori == kategori)
            q = q.order_by(ButceSatir.olcu_turu, ButceSatir.kategori, ButceSatir.ay)
            return [cls._satir_dict(s) for s in session.scalars(q).all()]

    @classmethod
    def gerceklesen_on_muhasebe(
        cls,
        mali_yil: int,
        *,
        olcu_turu: str = OLCU_SATIS,
        firma_id: int | None = None,
    ) -> dict[str, Any]:
        """Ön muhasebe gerçekleşmesi — yalnız bu kaynak; genel muhasebe eklenmez.

        Eksik aylar için sıfır uydurulmaz: ``aylar`` yalnızca belge bulunan ayları içerir.
        ``bos_aylar`` listesinde veri olmayan aylar yer alır (başarı sayılmaz).
        """
        _ = _firma_id(firma_id)  # firma izolasyonu ileride çok-firma DB için
        olcu = (olcu_turu or OLCU_SATIS).strip().upper()
        yil = int(mali_yil)
        bas = date(yil, 1, 1)
        bit = date(yil, 12, 31)

        if olcu == OLCU_SATIS:
            aylar, belge_sayisi = cls._satis_aylik_net(bas, bit)
        elif olcu == OLCU_GIDER:
            aylar, belge_sayisi = cls._gider_aylik_net(bas, bit)
        else:
            # TODO: ALIS / KARLILIK / NAKIT ön muhasebe adaptörleri
            return {
                "kaynak": KAYNAK_ON_MUHASEBE,
                "kaynak_etiket": KAYNAK_ETIKET,
                "olcu_turu": olcu,
                "mali_yil": yil,
                "aylar": {},
                "bos_aylar": list(range(1, 13)),
                "belge_sayisi": 0,
                "toplam": _SIFIR,
                "durum": "DESTEKLENMIYOR",
                "mesaj": f"{olcu} için ön muhasebe gerçekleşmesi henüz bağlanmadı (TODO).",
            }

        bos = [a for a in range(1, 13) if a not in aylar]
        toplam = sum(aylar.values(), _SIFIR)
        return {
            "kaynak": KAYNAK_ON_MUHASEBE,
            "kaynak_etiket": KAYNAK_ETIKET,
            "olcu_turu": olcu,
            "mali_yil": yil,
            "aylar": {a: _q2(t) for a, t in aylar.items()},
            "bos_aylar": bos,
            "belge_sayisi": belge_sayisi,
            "toplam": _q2(toplam),
            "durum": "OK" if belge_sayisi > 0 else "VERI_YOK",
            "mesaj": (
                None
                if belge_sayisi > 0
                else "Seçilen yılda geçerli ön muhasebe belgesi yok; sıfır uydurulmadı."
            ),
        }

    @classmethod
    def gerceklesen_genel_muhasebe(
        cls,
        mali_yil: int,
        *,
        olcu_turu: str = OLCU_SATIS,
        firma_id: int | None = None,
    ) -> dict[str, Any]:
        """Genel muhasebe gerçekleşmesi — yalnız bu kaynak; ön muhasebe ile toplanmaz.

        Eksik paket / tablo için sıfır uydurulmaz: ``durum=PAKET_YOK`` ve boş ``aylar``.
        Gelir: ilgili hesaplarda alacak − borç; gider: borç − alacak.
        Açılış fişi ve taslak/iptal (ters kayıtsız) hariç tutulur.
        """
        fid = _firma_id(firma_id)
        olcu = (olcu_turu or OLCU_SATIS).strip().upper()
        yil = int(mali_yil)
        bas = date(yil, 1, 1)
        bit = date(yil, 12, 31)

        with get_session() as session:
            if not _tablo_var(session, "muhasebe_fisleri") or not _tablo_var(
                session, "muhasebe_fis_satirlari"
            ):
                return {
                    "kaynak": KAYNAK_GENEL_MUHASEBE,
                    "kaynak_etiket": KAYNAK_ETIKET_GM,
                    "olcu_turu": olcu,
                    "mali_yil": yil,
                    "aylar": {},
                    "bos_aylar": list(range(1, 13)),
                    "belge_sayisi": 0,
                    "toplam": None,
                    "durum": "PAKET_YOK",
                    "mesaj": (
                        "Genel muhasebe fiş tabloları yok veya paket kapalı; "
                        "sıfır gerçekleşme uydurulmadı."
                    ),
                    "firma_id": fid,
                }

        if olcu == OLCU_SATIS:
            aylar, belge_sayisi = cls._gm_aylik(bas, bit, olcu="SATIS", firma_id=fid)
        elif olcu == OLCU_GIDER:
            aylar, belge_sayisi = cls._gm_aylik(bas, bit, olcu="GIDER", firma_id=fid)
        else:
            return {
                "kaynak": KAYNAK_GENEL_MUHASEBE,
                "kaynak_etiket": KAYNAK_ETIKET_GM,
                "olcu_turu": olcu,
                "mali_yil": yil,
                "aylar": {},
                "bos_aylar": list(range(1, 13)),
                "belge_sayisi": 0,
                "toplam": None,
                "durum": "DESTEKLENMIYOR",
                "mesaj": f"{olcu} için genel muhasebe gerçekleşmesi henüz bağlanmadı.",
                "firma_id": fid,
            }

        bos = [a for a in range(1, 13) if a not in aylar]
        toplam = sum(aylar.values(), _SIFIR) if aylar else None
        return {
            "kaynak": KAYNAK_GENEL_MUHASEBE,
            "kaynak_etiket": KAYNAK_ETIKET_GM,
            "olcu_turu": olcu,
            "mali_yil": yil,
            "aylar": {a: _q2(t) for a, t in aylar.items()},
            "bos_aylar": bos,
            "belge_sayisi": belge_sayisi,
            "toplam": _q2(toplam) if toplam is not None else None,
            "durum": "OK" if belge_sayisi > 0 else "VERI_YOK",
            "mesaj": (
                None
                if belge_sayisi > 0
                else "Seçilen yılda geçerli genel muhasebe fişi yok; sıfır uydurulmadı."
            ),
            "firma_id": fid,
        }

    @classmethod
    def karsilastirma(
        cls,
        plan_id: int,
        *,
        olcu_turu: str = OLCU_SATIS,
        kategori: str = "GENEL",
        firma_id: int | None = None,
        kaynak: str = KAYNAK_ON_MUHASEBE,
    ) -> dict[str, Any]:
        """Bütçe vs seçili kaynak(lar). Ön + Genel asla toplanmaz.

        ``kaynak``: ON_MUHASEBE | GENEL_MUHASEBE | YAN_YANA
        Yan yana: Bütçe | Ön | Genel | sapmalar | kaynak farkı (GM − Ön).
        """
        plan = cls.plan_getir(plan_id, firma_id=firma_id)
        if plan is None:
            raise ValueError("Bütçe planı bulunamadı.")
        olcu = (olcu_turu or OLCU_SATIS).strip().upper()
        kaynak_kod = (kaynak or KAYNAK_ON_MUHASEBE).strip().upper()
        if kaynak_kod not in {KAYNAK_ON_MUHASEBE, KAYNAK_GENEL_MUHASEBE, KAYNAK_YAN_YANA}:
            raise ValueError(f"Geçersiz gerçekleşme kaynağı: {kaynak}")

        satirlar = [
            s
            for s in (plan.get("satirlar") or [])
            if s["olcu_turu"] == olcu and s["kategori"] == (kategori or "GENEL")
        ]
        butce_ay = {int(s["ay"]): _q2(s["tutar"]) for s in satirlar}

        on = None
        gm = None
        if kaynak_kod in {KAYNAK_ON_MUHASEBE, KAYNAK_YAN_YANA}:
            on = cls.gerceklesen_on_muhasebe(
                plan["mali_yil"], olcu_turu=olcu, firma_id=firma_id
            )
        if kaynak_kod in {KAYNAK_GENEL_MUHASEBE, KAYNAK_YAN_YANA}:
            gm = cls.gerceklesen_genel_muhasebe(
                plan["mali_yil"], olcu_turu=olcu, firma_id=firma_id
            )

        on_ay = (on or {}).get("aylar") or {}
        gm_ay = (gm or {}).get("aylar") or {}
        satir_ozet = []
        for ay in range(1, 13):
            b = butce_ay.get(ay)
            o = on_ay.get(ay) if on is not None else None
            g = gm_ay.get(ay) if gm is not None else None
            fark_on = (_q2(o) - _q2(b)) if (b is not None and o is not None) else None
            fark_gm = (_q2(g) - _q2(b)) if (b is not None and g is not None) else None
            kaynak_farki = (
                (_q2(g) - _q2(o)) if (o is not None and g is not None) else None
            )
            satir_ozet.append(
                {
                    "ay": ay,
                    "butce": b,
                    "on_muhasebe": o,
                    "genel_muhasebe": g,
                    "fark": fark_on if kaynak_kod == KAYNAK_ON_MUHASEBE else (
                        fark_gm if kaynak_kod == KAYNAK_GENEL_MUHASEBE else fark_on
                    ),
                    "fark_on": fark_on,
                    "fark_gm": fark_gm,
                    "kaynak_farki": kaynak_farki,  # GM − Ön; toplanmaz
                    "kaynak_etiket": {
                        KAYNAK_ON_MUHASEBE: KAYNAK_ETIKET,
                        KAYNAK_GENEL_MUHASEBE: KAYNAK_ETIKET_GM,
                        KAYNAK_YAN_YANA: KAYNAK_ETIKET_YY,
                    }[kaynak_kod],
                }
            )

        etiket = {
            KAYNAK_ON_MUHASEBE: KAYNAK_ETIKET,
            KAYNAK_GENEL_MUHASEBE: KAYNAK_ETIKET_GM,
            KAYNAK_YAN_YANA: KAYNAK_ETIKET_YY,
        }[kaynak_kod]

        return {
            "plan": plan,
            "olcu_turu": olcu,
            "kategori": kategori or "GENEL",
            "kaynak": kaynak_kod,
            "kaynak_etiket": etiket,
            "on_muhasebe": on,
            "genel_muhasebe": gm,
            "satirlar": satir_ozet,
            "butce_toplam": _q2(sum(butce_ay.values(), _SIFIR)) if butce_ay else None,
            "on_muhasebe_toplam": (on or {}).get("toplam") if on else None,
            "genel_muhasebe_toplam": (gm or {}).get("toplam") if gm else None,
            "kaynak_farki_toplam": (
                _q2((gm or {}).get("toplam") or 0) - _q2((on or {}).get("toplam") or 0)
                if (
                    kaynak_kod == KAYNAK_YAN_YANA
                    and on
                    and gm
                    and on.get("toplam") is not None
                    and gm.get("toplam") is not None
                )
                else None
            ),
            "gerceklesen_meta": {
                "on": {
                    "durum": (on or {}).get("durum"),
                    "belge_sayisi": (on or {}).get("belge_sayisi"),
                    "bos_aylar": (on or {}).get("bos_aylar"),
                    "mesaj": (on or {}).get("mesaj"),
                }
                if on
                else None,
                "gm": {
                    "durum": (gm or {}).get("durum"),
                    "belge_sayisi": (gm or {}).get("belge_sayisi"),
                    "bos_aylar": (gm or {}).get("bos_aylar"),
                    "mesaj": (gm or {}).get("mesaj"),
                }
                if gm
                else None,
                # Geriye uyumluluk (eski UI)
                "durum": (on or gm or {}).get("durum"),
                "belge_sayisi": (on or gm or {}).get("belge_sayisi"),
                "bos_aylar": (on or gm or {}).get("bos_aylar"),
                "mesaj": (on or gm or {}).get("mesaj"),
            },
        }

    # ------------------------------------------------------------------ nakit

    @staticmethod
    def ic_virman_mi(hareket_turu: str | None) -> bool:
        """Firma içi kasa/banka aktarımı mı? (dış nakit sayılmaz)"""
        tur = (hareket_turu or "").strip().upper()
        if tur in {t.upper() for t in _IC_VIRMAN_TURLERI}:
            return True
        # Normalizasyon: İ→I
        tur_n = tur.replace("İ", "I")
        for v in _IC_VIRMAN_TURLERI:
            if tur_n == v.upper().replace("İ", "I"):
                return True
        if "VIRMAN" in tur_n or "VİRMAN" in tur:
            if "MASRAF" in tur_n:
                return False  # banka masrafı gerçek çıkış
            return True
        return False

    @staticmethod
    def nakit_donem_hesapla(
        baslangic_bakiye: Decimal | int | float | str,
        gercek_giris: Decimal | int | float | str,
        gercek_cikis: Decimal | int | float | str,
        *,
        ic_virman_giris: Decimal | int | float | str = 0,
        ic_virman_cikis: Decimal | int | float | str = 0,
        planlanan_giris: Decimal | int | float | str | None = None,
        planlanan_cikis: Decimal | int | float | str | None = None,
    ) -> dict[str, Any]:
        """Dönem sonu nakit = başlangıç + gerçek giriş − gerçek çıkış.

        İç virman tutarları ayrı izlenir; firma nakdine eklenmez/çıkarılmaz.
        """
        bas = _q2(baslangic_bakiye)
        gir = _q2(gercek_giris)
        cik = _q2(gercek_cikis)
        iv_g = _q2(ic_virman_giris)
        iv_c = _q2(ic_virman_cikis)
        donem_sonu = _q2(bas + gir - cik)
        return {
            "baslangic_kullanilabilir": bas,
            "gercek_giris": gir,
            "gercek_cikis": cik,
            "donem_sonu": donem_sonu,
            "ic_virman_giris": iv_g,
            "ic_virman_cikis": iv_c,
            "ic_virman_net": _q2(iv_g - iv_c),  # bilgilendirme; firma nakdini değiştirmez
            "planlanan_giris": _q2(planlanan_giris) if planlanan_giris is not None else None,
            "planlanan_cikis": _q2(planlanan_cikis) if planlanan_cikis is not None else None,
            "finansman_acigi": (
                _q2(donem_sonu)
                if donem_sonu >= 0
                else _q2(donem_sonu)  # negatif = açık
            ),
        }

    @classmethod
    def nakit_butcesi(
        cls,
        mali_yil: int,
        *,
        ay: int | None = None,
        plan_id: int | None = None,
        firma_id: int | None = None,
        baslangic_override: Decimal | int | float | str | None = None,
    ) -> dict[str, Any]:
        """Kasa/banka kullanılabilir nakit bütçesi (ön muhasebe finans hareketleri).

        - Başlangıç: dönem başı kullanılabilir kasa+mevduat/KMH bakiyesi
        - Gerçek giriş/çıkış: dış hareketler (iç virman hariç)
        - Dönem sonu = başlangıç + giriş − çıkış
        - Plan satırları (ölçü NAKIT) varsa planlanan kolonlara yazılır
        """
        yil = int(mali_yil)
        if ay is not None and (int(ay) < 1 or int(ay) > 12):
            raise ValueError("Ay 1–12 olmalı.")
        fid = _firma_id(firma_id)

        if ay is None:
            donem_bas, donem_bit = date(yil, 1, 1), date(yil, 12, 31)
            ay_etiket = f"{yil} (yıllık)"
        else:
            donem_bas, donem_bit = ay_araligi(yil, int(ay))
            ay_etiket = f"{yil}-{int(ay):02d}"

        if baslangic_override is not None:
            baslangic = _q2(baslangic_override)
            bakiye_kaynak = "OVERRIDE"
        else:
            baslangic, bakiye_kaynak = cls._nakit_baslangic_bakiye(donem_bas)

        hareket = cls._nakit_hareket_ozet(donem_bas, donem_bit)
        plan_gir = plan_cik = None
        if plan_id is not None:
            plan_gir, plan_cik = cls._nakit_plan_tutarlari(
                int(plan_id), ay=ay, firma_id=fid
            )

        ozet = cls.nakit_donem_hesapla(
            baslangic,
            hareket["gercek_giris"],
            hareket["gercek_cikis"],
            ic_virman_giris=hareket["ic_virman_giris"],
            ic_virman_cikis=hareket["ic_virman_cikis"],
            planlanan_giris=plan_gir,
            planlanan_cikis=plan_cik,
        )
        # KK taksit vade planı — gerçek çıkış değil; bilgi kolonu
        kk_aylik = cls.kk_taksit_nakit_aylik(yil, firma_id=fid)
        if ay is not None:
            kk_plan = _q2(kk_aylik.get(int(ay), _SIFIR))
        else:
            kk_plan = _q2(sum(kk_aylik.values(), _SIFIR))
        return {
            **ozet,
            "mali_yil": yil,
            "ay": ay,
            "donem_etiket": ay_etiket,
            "donem_bas": donem_bas.isoformat(),
            "donem_bit": donem_bit.isoformat(),
            "bakiye_kaynak": bakiye_kaynak,
            "firma_id": fid,
            "kaynak_etiket": KAYNAK_ETIKET,
            "hareket_sayisi": hareket["hareket_sayisi"],
            "ic_virman_sayisi": hareket["ic_virman_sayisi"],
            "durum": hareket["durum"],
            "mesaj": hareket["mesaj"],
            "kk_taksit_plan": kk_plan,
            "kk_taksit_aylik": {a: _q2(t) for a, t in kk_aylik.items()},
            "aylik": (
                None
                if ay is not None
                else cls._nakit_aylik_seri(yil, baslangic, plan_id=plan_id, firma_id=fid)
            ),
        }

    @classmethod
    def _nakit_aylik_seri(
        cls,
        mali_yil: int,
        yil_basi_bakiye: Decimal,
        *,
        plan_id: int | None = None,
        firma_id: int | None = None,
    ) -> list[dict[str, Any]]:
        """Her ayın son bakiyesini bir sonraki ayın başına taşır (başlangıç tekrarı yok)."""
        tasinan = _q2(yil_basi_bakiye)
        kk_aylik = cls.kk_taksit_nakit_aylik(mali_yil, firma_id=firma_id)
        seri = []
        for a in range(1, 13):
            bas, bit = ay_araligi(mali_yil, a)
            har = cls._nakit_hareket_ozet(bas, bit)
            plan_gir = plan_cik = None
            if plan_id is not None:
                plan_gir, plan_cik = cls._nakit_plan_tutarlari(
                    int(plan_id), ay=a, firma_id=firma_id
                )
            o = cls.nakit_donem_hesapla(
                tasinan,
                har["gercek_giris"],
                har["gercek_cikis"],
                ic_virman_giris=har["ic_virman_giris"],
                ic_virman_cikis=har["ic_virman_cikis"],
                planlanan_giris=plan_gir,
                planlanan_cikis=plan_cik,
            )
            o["ay"] = a
            o["kk_taksit_plan"] = _q2(kk_aylik.get(a, _SIFIR))
            seri.append(o)
            tasinan = o["donem_sonu"]
        return seri

    @classmethod
    def _nakit_plan_tutarlari(
        cls, plan_id: int, *, ay: int | None, firma_id: int | None
    ) -> tuple[Decimal | None, Decimal | None]:
        satirlar = cls.plan_satirlari(
            plan_id, olcu_turu=OLCU_NAKIT, firma_id=firma_id
        )
        if not satirlar:
            return None, None
        giris = _SIFIR
        cikis = _SIFIR
        var = False
        for s in satirlar:
            if ay is not None and int(s["ay"]) != int(ay):
                continue
            var = True
            kat = (s.get("kategori") or "GENEL").upper()
            t = _q2(s["tutar"])
            if "CIKIS" in kat or "ÇIKIŞ" in kat or "ODEME" in kat or "ÖDEME" in kat:
                cikis += t
            else:
                giris += t
        if not var:
            return None, None
        return _q2(giris), _q2(cikis)

    @classmethod
    def _nakit_baslangic_bakiye(cls, kesim: date) -> tuple[Decimal, str]:
        """Kesim tarihinden önce kullanılabilir kasa/banka bakiyesi (TL kayıt karşılığı)."""
        try:
            from database.finans_service import FinansService
            from database.models.finans import FinansHesabi
        except Exception:  # noqa: BLE001
            return _SIFIR, "SERVIS_YOK"

        toplam = _SIFIR
        hesap_sayisi = 0
        with get_session() as session:
            if not _tablo_var(session, "finans_hesaplari"):
                return _SIFIR, "TABLO_YOK"
            hesaplar = session.scalars(
                select(FinansHesabi).where(FinansHesabi.aktif.is_(True))
            ).all()
            for h in hesaplar:
                if not cls._nakit_hesabi_mi(h):
                    continue
                hesap_sayisi += 1
                bak = _q2(getattr(h, "acilis_bakiyesi", 0) or 0)
                # TRY dışı: kayıt TL karşılığı tercih
                pb = (getattr(h, "para_birimi", None) or "TRY").upper()
                if pb != "TRY":
                    acilis_tl = getattr(h, "acilis_tl_karsiligi", None)
                    if acilis_tl is not None:
                        bak = _q2(acilis_tl)
                    else:
                        kur = getattr(h, "acilis_kuru", None)
                        bak = _q2(_q2(bak) * _q2(kur or 0))
                for har in getattr(h, "hareketler", None) or []:
                    t = getattr(har, "tarih", None)
                    if t is None:
                        continue
                    if isinstance(t, str):
                        t = date.fromisoformat(t[:10])
                    if t >= kesim:
                        continue
                    isaret = FinansService.hareket_isareti(har.hareket_turu)
                    tl = getattr(har, "tl_karsiligi", None)
                    if tl is None:
                        tutar = _q2(har.tutar)
                        hpb = (getattr(har, "para_birimi", None) or pb).upper()
                        if hpb == "TRY":
                            tl = tutar
                        else:
                            kur = getattr(har, "kur", None)
                            tl = _q2(tutar * _q2(kur or 0))
                    bak += _q2(tl) * isaret
                toplam += bak
        if hesap_sayisi == 0:
            return _SIFIR, "HESAP_YOK"
        return _q2(toplam), "FINANS"

    @classmethod
    def _nakit_hesabi_mi(cls, hesap) -> bool:
        tur = (getattr(hesap, "hesap_turu", None) or "").upper()
        alt = (getattr(hesap, "alt_hesap_turu", None) or "").upper()
        if tur == "KASA":
            return True
        if tur == "BANKA":
            if alt in {"KREDI_KARTI", "KREDILER", "POS"}:
                return False
            return alt in _NAKIT_ALT_TURLER or alt in {"MEVDUAT", "KMH"}
        return False

    @classmethod
    def _nakit_hareket_ozet(cls, bas: date, bit: date) -> dict[str, Any]:
        try:
            from database.finans_service import FinansService
            from database.models.finans import FinansHareketi, FinansHesabi
        except Exception:  # noqa: BLE001
            return {
                "gercek_giris": _SIFIR,
                "gercek_cikis": _SIFIR,
                "ic_virman_giris": _SIFIR,
                "ic_virman_cikis": _SIFIR,
                "hareket_sayisi": 0,
                "ic_virman_sayisi": 0,
                "durum": "SERVIS_YOK",
                "mesaj": "Finans servisi yüklenemedi.",
            }

        gir = cik = iv_g = iv_c = _SIFIR
        sayac = iv_sayac = 0
        with get_session() as session:
            if not _tablo_var(session, "finans_hareketleri"):
                return {
                    "gercek_giris": _SIFIR,
                    "gercek_cikis": _SIFIR,
                    "ic_virman_giris": _SIFIR,
                    "ic_virman_cikis": _SIFIR,
                    "hareket_sayisi": 0,
                    "ic_virman_sayisi": 0,
                    "durum": "TABLO_YOK",
                    "mesaj": "finans_hareketleri tablosu yok; sıfır uydurulmadı (hareket yok).",
                }
            q = (
                select(FinansHareketi)
                .join(FinansHesabi, FinansHesabi.id == FinansHareketi.hesap_id)
                .where(
                    FinansHareketi.tarih >= bas,
                    FinansHareketi.tarih <= bit,
                    FinansHesabi.aktif.is_(True),
                )
            )
            for har in session.scalars(q).all():
                hesap = har.hesap
                if hesap is None or not cls._nakit_hesabi_mi(hesap):
                    continue
                isaret = FinansService.hareket_isareti(har.hareket_turu)
                tl = getattr(har, "tl_karsiligi", None)
                if tl is None:
                    tutar = _q2(har.tutar)
                    pb = (getattr(har, "para_birimi", None) or "TRY").upper()
                    if pb == "TRY":
                        tl = tutar
                    else:
                        kur = getattr(har, "kur", None)
                        tl = _q2(tutar * _q2(kur or 0))
                tut = _q2(tl)
                if cls.ic_virman_mi(har.hareket_turu):
                    iv_sayac += 1
                    if isaret >= 0:
                        iv_g += tut
                    else:
                        iv_c += tut
                    continue
                sayac += 1
                if isaret >= 0:
                    gir += tut
                else:
                    cik += tut

        return {
            "gercek_giris": _q2(gir),
            "gercek_cikis": _q2(cik),
            "ic_virman_giris": _q2(iv_g),
            "ic_virman_cikis": _q2(iv_c),
            "hareket_sayisi": sayac,
            "ic_virman_sayisi": iv_sayac,
            "durum": "OK" if (sayac + iv_sayac) > 0 else "VERI_YOK",
            "mesaj": (
                None
                if (sayac + iv_sayac) > 0
                else "Dönemde kasa/banka hareketi yok; başlangıç bakiyesi korunur."
            ),
        }

    # ------------------------------------------------------------------ Excel

    @classmethod
    def excel_sablon_olustur(cls, dosya_yolu: str | Path) -> Path:
        """Şablon: kategori, olcu_turu, para_birimi, ay, tutar (+ örnek satır)."""
        from openpyxl import Workbook

        yol = Path(dosya_yolu)
        wb = Workbook()
        ws = wb.active
        ws.title = "ButceSatirlari"
        ws.append(list(_EXCEL_BASLIKLAR))
        ws.append(["GENEL", "SATIS", "TRY", 1, 1000])
        ws.append(["GENEL", "SATIS", "TRY", 2, 1000])
        notlar = wb.create_sheet("Notlar")
        notlar.append(["Zorunlu kolonlar: kategori, olcu_turu, para_birimi, ay, tutar"])
        notlar.append(["olcu_turu: SATIS | ALIS | GIDER | KARLILIK | NAKIT"])
        notlar.append(["ay: 1–12"])
        notlar.append(["Hata varsa hiçbir satır aktarılmaz."])
        notlar.append(["Tekrar aktarımda cakisma=guncelle veya atla."])
        wb.save(yol)
        return yol

    @classmethod
    def excel_onizle(
        cls,
        dosya_yolu: str | Path,
        *,
        plan_id: int | None = None,
        firma_id: int | None = None,
        beklenen_pb: str | None = None,
    ) -> dict[str, Any]:
        """Önizleme + doğrulama. Hatalı satırlar işaretlenir; aktarım yapılmaz."""
        from openpyxl import load_workbook

        yol = Path(dosya_yolu)
        if not yol.is_file():
            raise FileNotFoundError(f"Excel bulunamadı: {yol}")

        pb_beklenen = (beklenen_pb or "TRY").upper()
        if plan_id is not None:
            plan = cls.plan_getir(plan_id, firma_id=firma_id)
            if plan is None:
                raise ValueError("Bütçe planı bulunamadı.")
            pb_beklenen = (plan.get("para_birimi") or "TRY").upper()

        wb = load_workbook(yol, read_only=True, data_only=True)
        ws = wb.active
        rows = list(ws.iter_rows(values_only=True))
        wb.close()
        if not rows:
            return {
                "satirlar": [],
                "hatalar": [{"satir": 0, "mesaj": "Dosya boş."}],
                "uyarilar": [],
                "gecerli": False,
            }

        baslik = [str(c or "").strip().lower() for c in rows[0]]
        eksik = [c for c in _EXCEL_BASLIKLAR if c not in baslik]
        if eksik:
            return {
                "satirlar": [],
                "hatalar": [
                    {
                        "satir": 1,
                        "mesaj": f"Eksik kolonlar: {', '.join(eksik)}",
                    }
                ],
                "uyarilar": [],
                "gecerli": False,
            }
        idx = {c: baslik.index(c) for c in _EXCEL_BASLIKLAR}
        aciklama_i = baslik.index("aciklama") if "aciklama" in baslik else None

        satirlar: list[dict[str, Any]] = []
        hatalar: list[dict[str, Any]] = []
        uyarilar: list[dict[str, Any]] = []
        anahtarlar: set[tuple] = set()

        for rno, row in enumerate(rows[1:], start=2):
            if row is None or all(c is None or str(c).strip() == "" for c in row):
                continue
            try:
                kategori = str(row[idx["kategori"]] or "").strip() or "GENEL"
                olcu_raw = str(row[idx["olcu_turu"]] or "").strip().upper()
                olcu = _OLCU_EXCEL_MAP.get(olcu_raw, olcu_raw)
                pb = str(row[idx["para_birimi"]] or "").strip().upper()
                ay_raw = row[idx["ay"]]
                tutar_raw = row[idx["tutar"]]
                aciklama = (
                    str(row[aciklama_i]).strip()
                    if aciklama_i is not None and row[aciklama_i] is not None
                    else None
                )
            except Exception as hata:  # noqa: BLE001
                hatalar.append({"satir": rno, "mesaj": f"Okuma hatası: {hata}"})
                continue

            satir_hata = []
            if olcu not in OLCU_TURLERI:
                satir_hata.append(f"Geçersiz ölçü türü: {olcu_raw}")
            if pb != pb_beklenen:
                satir_hata.append(
                    f"Para birimi plan ile uyuşmuyor ({pb} ≠ {pb_beklenen})"
                )
            try:
                ay = int(ay_raw)
                if ay < 1 or ay > 12:
                    satir_hata.append(f"Ay 1–12 olmalı: {ay}")
            except Exception:
                satir_hata.append(f"Geçersiz ay: {ay_raw}")
                ay = 0
            try:
                tutar = _q2(str(tutar_raw).replace(",", "."))
            except Exception:
                satir_hata.append(f"Geçersiz tutar: {tutar_raw}")
                tutar = _SIFIR

            anahtar = (olcu, kategori, ay)
            if ay and anahtar in anahtarlar:
                satir_hata.append(
                    f"Dosyada yinelenen satır: {olcu}/{kategori}/ay={ay}"
                )
            if ay:
                anahtarlar.add(anahtar)

            kayit = {
                "satir_no": rno,
                "kategori": kategori,
                "olcu_turu": olcu,
                "para_birimi": pb,
                "ay": ay,
                "tutar": tutar,
                "aciklama": aciklama,
                "hatalar": satir_hata,
                "mevcut_tutar": None,
                "cakisma_durum": "yeni",
            }
            satirlar.append(kayit)
            for m in satir_hata:
                hatalar.append({"satir": rno, "mesaj": m})

        # Plan varsa çakışma önizlemesi (güncelle / atla seçimine göre UI gösterir)
        if plan_id is not None and satirlar:
            plan = cls.plan_getir(plan_id, firma_id=firma_id)
            mevcut_map: dict[tuple, Any] = {}
            if plan:
                for s in plan.get("satirlar") or []:
                    mevcut_map[
                        (s["olcu_turu"], s["kategori"], int(s["ay"]))
                    ] = _q2(s.get("tutar"))
            for kayit in satirlar:
                anahtar = (kayit["olcu_turu"], kayit["kategori"], int(kayit["ay"] or 0))
                if anahtar in mevcut_map:
                    kayit["mevcut_tutar"] = mevcut_map[anahtar]
                    kayit["cakisma_durum"] = "guncellenecek"
                else:
                    kayit["cakisma_durum"] = "yeni"

        return {
            "satirlar": satirlar,
            "hatalar": hatalar,
            "uyarilar": uyarilar,
            "gecerli": len(hatalar) == 0 and len(satirlar) > 0,
            "para_birimi": pb_beklenen,
            "satir_sayisi": len(satirlar),
            "yeni_sayisi": sum(1 for s in satirlar if s.get("cakisma_durum") == "yeni"),
            "cakisma_sayisi": sum(
                1 for s in satirlar if s.get("cakisma_durum") == "guncellenecek"
            ),
        }

    @classmethod
    def excel_aktar(
        cls,
        plan_id: int,
        dosya_yolu: str | Path,
        *,
        firma_id: int | None = None,
        cakisma: str = "guncelle",
    ) -> dict[str, Any]:
        """Doğrulanmış Excel satırlarını aktarır. Hata varsa yarım aktarım yok.

        ``cakisma``: guncelle (mevcut satırı güncelle) | atla (mevcutu bırak).
        """
        mod = (cakisma or "guncelle").strip().lower()
        if mod not in {"guncelle", "atla"}:
            raise ValueError("cakisma 'guncelle' veya 'atla' olmalı.")

        onizleme = cls.excel_onizle(dosya_yolu, plan_id=plan_id, firma_id=firma_id)
        if not onizleme["gecerli"]:
            raise ValueError(
                "Excel doğrulama hatalı; aktarım yapılmadı. "
                + "; ".join(
                    f"S{h['satir']}: {h['mesaj']}" for h in onizleme["hatalar"][:8]
                )
            )

        fid = _firma_id(firma_id)
        guncellenen = 0
        atlanan = 0
        eklenen = 0
        with get_session() as session:
            plan = session.get(ButcePlan, int(plan_id))
            if plan is None or int(plan.firma_id) != fid:
                raise ValueError("Bütçe planı bulunamadı.")
            for raw in onizleme["satirlar"]:
                olcu = raw["olcu_turu"]
                kat = raw["kategori"]
                ay = int(raw["ay"])
                mevcut = session.scalar(
                    select(ButceSatir).where(
                        ButceSatir.plan_id == plan.id,
                        ButceSatir.olcu_turu == olcu,
                        ButceSatir.kategori == kat,
                        ButceSatir.ay == ay,
                    )
                )
                if mevcut is None:
                    session.add(
                        ButceSatir(
                            plan_id=plan.id,
                            olcu_turu=olcu,
                            kategori=kat,
                            ay=ay,
                            tutar=_q2(raw["tutar"]),
                            aciklama=raw.get("aciklama"),
                        )
                    )
                    eklenen += 1
                elif mod == "atla":
                    atlanan += 1
                else:
                    mevcut.tutar = _q2(raw["tutar"])
                    if raw.get("aciklama") is not None:
                        mevcut.aciklama = raw["aciklama"]
                    guncellenen += 1
            plan.guncelleme = datetime.now()
            plan.guncelleyen = _kullanici()
            session.flush()

        return {
            "plan_id": int(plan_id),
            "eklenen": eklenen,
            "guncellenen": guncellenen,
            "atlanan": atlanan,
            "cakisma": mod,
            "satir_sayisi": onizleme["satir_sayisi"],
        }

    @classmethod
    def plan_meta_guncelle(
        cls,
        plan_id: int,
        *,
        ad: str | None = None,
        proje_kodu: str | None = None,
        senaryo: str | None = None,
        firma_id: int | None = None,
    ) -> dict[str, Any]:
        """Ad / proje / senaryo — kilitli planda reddedilir."""
        cls.ensure_schema()
        fid = _firma_id(firma_id)
        with get_session() as session:
            plan = session.get(ButcePlan, int(plan_id))
            if plan is None or int(plan.firma_id) != fid:
                raise ValueError("Bütçe planı bulunamadı.")
            if plan.durum == DURUM_KILITLI:
                raise ValueError("Kilitli planda meta değiştirilemez.")
            if ad is not None:
                ad2 = ad.strip()
                if not ad2:
                    raise ValueError("Ad boş olamaz.")
                plan.ad = ad2
            if proje_kodu is not None:
                plan.proje_kodu = (proje_kodu.strip() or None)
            if senaryo is not None:
                sen = senaryo.strip().upper()
                if sen not in SENARYOLAR:
                    raise ValueError(f"Geçersiz senaryo: {sen}")
                plan.senaryo = sen
            plan.guncelleme = datetime.now()
            plan.guncelleyen = _kullanici()
            session.flush()
            return cls._plan_dict(plan)

    @classmethod
    def yil_sonu_tahmini(
        cls,
        plan_id: int,
        *,
        olcu_turu: str = OLCU_SATIS,
        firma_id: int | None = None,
        bugun: date | None = None,
    ) -> dict[str, Any]:
        """Kapanmış aylar gerçek + devam eden ay (gerçek) + gelecek aylar bütçe.

        Onaylı bütçeyi değiştirmez. Devam eden ayda gerçekleşeni iki kez eklemez.
        """
        plan = cls.plan_getir(plan_id, firma_id=firma_id)
        if plan is None:
            raise ValueError("Plan bulunamadı.")
        yil = int(plan["mali_yil"])
        bugun = bugun or date.today()
        kars = cls.karsilastirma(
            plan_id, olcu_turu=olcu_turu, firma_id=firma_id, kaynak=KAYNAK_ON_MUHASEBE
        )
        aylar = []
        toplam = _SIFIR
        for s in kars.get("satirlar") or []:
            ay = int(s["ay"])
            butce = s.get("butce")
            ger = s.get("on_muhasebe")
            if yil < bugun.year or (yil == bugun.year and ay < bugun.month):
                # Kapanmış ay: gerçek (yoksa bütçe)
                deger = _q2(ger) if ger is not None else (_q2(butce) if butce is not None else _SIFIR)
                kaynak = "GERCEK" if ger is not None else "BUTCE_YEDEK"
            elif yil == bugun.year and ay == bugun.month:
                # Devam eden: yalnız bugüne kadar gerçekleşen (üstüne bütçe eklenmez)
                deger = _q2(ger) if ger is not None else _SIFIR
                kaynak = "DEVAM_GERCEK"
            else:
                deger = _q2(butce) if butce is not None else _SIFIR
                kaynak = "BUTCE"
            toplam = _q2(toplam + deger)
            aylar.append({"ay": ay, "tutar": deger, "kaynak": kaynak, "butce": butce, "gercek": ger})
        return {
            "plan_id": int(plan_id),
            "mali_yil": yil,
            "olcu_turu": olcu_turu,
            "kesim": bugun.isoformat(),
            "aylar": aylar,
            "yil_sonu_tahmini": toplam,
            "senaryo": plan.get("senaryo"),
            "surum": plan.get("surum"),
        }

    @classmethod
    def plan_durum_degistir(
        cls,
        plan_id: int,
        yeni_durum: str,
        *,
        firma_id: int | None = None,
        gerekce: str | None = None,
    ) -> dict[str, Any]:
        """Onay / kilit / arşiv — geçiş tablosuna uygun."""
        cls.ensure_schema()
        fid = _firma_id(firma_id)
        hedef = (yeni_durum or "").strip().upper()
        if hedef not in DURUMLAR:
            raise ValueError(f"Geçersiz durum: {hedef}")
        with get_session() as session:
            plan = session.get(ButcePlan, int(plan_id))
            if plan is None or int(plan.firma_id) != fid:
                raise ValueError("Bütçe planı bulunamadı.")
            if plan.durum == DURUM_KILITLI and hedef not in DURUM_GECISLER.get(DURUM_KILITLI, ()):
                raise ValueError("Kilitli planda değişiklik için yetkili arşiv geçişi gerekir.")
            izin = DURUM_GECISLER.get(plan.durum, ())
            if hedef not in izin and hedef != plan.durum:
                raise ValueError(f"{plan.durum} → {hedef} geçişine izin yok.")
            plan.durum = hedef
            plan.guncelleme = datetime.now()
            plan.guncelleyen = _kullanici()
            if hedef == DURUM_ONAYLI:
                plan.onay_tarihi = datetime.now()
                plan.onaylayan = _kullanici()
            if gerekce:
                notu = (plan.aciklama or "") + f"\n[Durum {hedef}] {gerekce}"
                plan.aciklama = notu.strip()
            session.flush()
            return cls._plan_dict(plan)

    @classmethod
    def plan_senaryo_kopyala(
        cls,
        plan_id: int,
        senaryo: str,
        *,
        firma_id: int | None = None,
        ad_ek: str | None = None,
    ) -> dict[str, Any]:
        """Temel/İyimser/Temkinli senaryo kopyası — satırlar çoğaltılır, kaynak bağlanır."""
        cls.ensure_schema()
        sen = (senaryo or SENARYO_TEMEL).strip().upper()
        if sen not in SENARYOLAR:
            raise ValueError(f"Geçersiz senaryo: {sen}")
        kaynak = cls.plan_getir(plan_id, firma_id=firma_id)
        if kaynak is None:
            raise ValueError("Kaynak plan bulunamadı.")
        ek = (ad_ek or sen).strip()
        yeni = cls.plan_olustur(
            ad=f"{kaynak['ad']} ({ek})",
            mali_yil=int(kaynak["mali_yil"]),
            para_birimi=kaynak.get("para_birimi") or "TRY",
            firma_id=firma_id,
            aciklama=f"Senaryo kopyası ← {kaynak['kod']}",
            durum=DURUM_TASLAK,
        )
        with get_session() as session:
            plan = session.get(ButcePlan, int(yeni["id"]))
            plan.senaryo = sen
            plan.kaynak_plan_id = int(kaynak["id"])
            plan.proje_kodu = getattr(
                session.get(ButcePlan, int(kaynak["id"])), "proje_kodu", None
            )
            session.flush()
        if kaynak.get("satirlar"):
            cls.satirlar_kaydet(int(yeni["id"]), kaynak["satirlar"], firma_id=firma_id)
        return cls.plan_getir(int(yeni["id"]), firma_id=firma_id) or yeni

    @classmethod
    def plan_revizyon_olustur(
        cls, plan_id: int, *, firma_id: int | None = None, gerekce: str = ""
    ) -> dict[str, Any]:
        """Onaylı plandan yeni sürüm (TASLAK); eski onaylı korunur."""
        kaynak = cls.plan_getir(plan_id, firma_id=firma_id)
        if kaynak is None:
            raise ValueError("Plan bulunamadı.")
        kopya = cls.plan_senaryo_kopyala(
            plan_id,
            kaynak.get("senaryo") or SENARYO_TEMEL,
            firma_id=firma_id,
            ad_ek=f"Rev.{int(kaynak.get('surum') or 1) + 1}",
        )
        with get_session() as session:
            plan = session.get(ButcePlan, int(kopya["id"]))
            plan.surum = int(kaynak.get("surum") or 1) + 1
            plan.kaynak_plan_id = int(kaynak["id"])
            plan.aciklama = (
                f"Revizyon ← {kaynak['kod']} s{kaynak.get('surum')}. {gerekce}"
            ).strip()
            session.flush()
        return cls.plan_getir(int(kopya["id"]), firma_id=firma_id) or kopya

    @classmethod
    def bilanco_hedef_kaydet(
        cls,
        plan_id: int,
        hedefler: list[dict[str, Any]],
        *,
        firma_id: int | None = None,
    ) -> list[dict[str, Any]]:
        """Dönem sonu bilanço hedefleri (hareket toplamı değil)."""
        cls.ensure_schema()
        fid = _firma_id(firma_id)
        with get_session() as session:
            plan = session.get(ButcePlan, int(plan_id))
            if plan is None or int(plan.firma_id) != fid:
                raise ValueError("Plan bulunamadı.")
            if plan.durum in (DURUM_KILITLI,):
                raise ValueError("Kilitli planda bilanço hedefi değiştirilemez.")
            for h in hedefler:
                grup = (h.get("hesap_grubu") or "").strip().upper()
                if not grup:
                    continue
                ay = int(h.get("ay") or 12)
                if ay < 1 or ay > 12:
                    raise ValueError("Ay 1–12 olmalı.")
                mevcut = session.scalar(
                    select(ButceBilancoHedef).where(
                        ButceBilancoHedef.plan_id == plan.id,
                        ButceBilancoHedef.hesap_grubu == grup,
                        ButceBilancoHedef.ay == ay,
                    )
                )
                if mevcut is None:
                    mevcut = ButceBilancoHedef(plan_id=plan.id, hesap_grubu=grup, ay=ay)
                    session.add(mevcut)
                mevcut.hedef_tutar = _q2(h.get("hedef_tutar") or 0)
                mevcut.aciklama = (h.get("aciklama") or None)
            session.flush()
            return [
                {
                    "id": int(x.id),
                    "hesap_grubu": x.hesap_grubu,
                    "ay": int(x.ay),
                    "hedef_tutar": _q2(x.hedef_tutar),
                    "aciklama": x.aciklama,
                }
                for x in session.scalars(
                    select(ButceBilancoHedef)
                    .where(ButceBilancoHedef.plan_id == plan.id)
                    .order_by(ButceBilancoHedef.hesap_grubu, ButceBilancoHedef.ay)
                ).all()
            ]

    @classmethod
    def bilanco_hedefleri(cls, plan_id: int, *, firma_id: int | None = None) -> list[dict]:
        cls.ensure_schema()
        fid = _firma_id(firma_id)
        with get_session() as session:
            plan = session.get(ButcePlan, int(plan_id))
            if plan is None or int(plan.firma_id) != fid:
                return []
            return [
                {
                    "id": int(x.id),
                    "hesap_grubu": x.hesap_grubu,
                    "ay": int(x.ay),
                    "hedef_tutar": _q2(x.hedef_tutar),
                    "aciklama": x.aciklama or "",
                }
                for x in session.scalars(
                    select(ButceBilancoHedef)
                    .where(ButceBilancoHedef.plan_id == plan.id)
                    .order_by(ButceBilancoHedef.hesap_grubu, ButceBilancoHedef.ay)
                ).all()
            ]

    @staticmethod
    def asim_uyari_hesapla(
        butce: Decimal | int | float | str | None,
        gerceklesen: Decimal | int | float | str | None,
        *,
        olcu_turu: str = OLCU_GIDER,
        esikler: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Kullanım oranı ve uyarı seviyesi. Satış aşımı olumsuz sayılmaz."""
        e = esikler or {
            "bilgi_yuzde": 80,
            "uyari_yuzde": 100,
            "asim_yuzde": 100,
        }
        b = _q2(butce) if butce is not None else None
        g = _q2(gerceklesen) if gerceklesen is not None else None
        if b is None or b == 0:
            if g is not None and g != 0:
                return {
                    "oran": None,
                    "seviye": "BUTCESIZ",
                    "mesaj": "Bütçesiz harcama / gerçekleşme",
                }
            return {"oran": None, "seviye": "YOK", "mesaj": "Bütçe veya gerçekleşme yok"}
        oran = (_q2(g or 0) / b * Decimal("100")).quantize(_Q)
        olcu = (olcu_turu or "").upper()
        if olcu == OLCU_SATIS:
            # Satış hedef aşımı olumsuz uyarı değil
            seviye = "BILGI" if oran >= _q2(e.get("bilgi_yuzde", 80)) else "NORMAL"
            return {"oran": oran, "seviye": seviye, "mesaj": f"Satış gerçekleşme %{oran}"}
        if oran >= _q2(e.get("asim_yuzde", 100)) and oran > 100:
            seviye = "ASIM"
        elif oran >= _q2(e.get("uyari_yuzde", 100)):
            seviye = "UYARI"
        elif oran >= _q2(e.get("bilgi_yuzde", 80)):
            seviye = "BILGI"
        else:
            seviye = "NORMAL"
        return {"oran": oran, "seviye": seviye, "mesaj": f"Kullanım %{oran} ({seviye})"}

    @classmethod
    def kk_taksit_nakit_aylik(
        cls, mali_yil: int, *, firma_id: int | None = None
    ) -> dict[int, Decimal]:
        """Firma KK taksit vade aylarına göre planlanan nakit çıkış (ödenmemiş).

        Gerçek çıkış yalnızca ödeme tarihinde; burada vade planı bilgisidir.
        """
        yil = int(mali_yil)
        aylar: dict[int, Decimal] = {a: _SIFIR for a in range(1, 13)}
        try:
            from database.models.finans import KrediKartiEkstreTaksit  # type: ignore
        except Exception:
            try:
                from sqlalchemy import text

                with get_session() as session:
                    if not _tablo_var(session, "kredi_karti_ekstre_taksitleri") and not _tablo_var(
                        session, "kk_ekstre_taksitleri"
                    ):
                        return aylar
            except Exception:
                return aylar
            return aylar
        # Esnek: mevcut KK taksit tablosu adları
        with get_session() as session:
            for tablo in ("kredi_karti_taksitleri", "kk_ekstre_taksitleri", "kredi_karti_ekstre_taksit"):
                if not _tablo_var(session, tablo):
                    continue
                cols = _sutunlar(session, tablo)
                if "vade_tarihi" not in cols and "vade" not in cols:
                    continue
                vade_col = "vade_tarihi" if "vade_tarihi" in cols else "vade"
                tutar_col = "tutar" if "tutar" in cols else ("kalan" if "kalan" in cols else None)
                if not tutar_col:
                    continue
                from sqlalchemy import text

                sql = text(
                    f"SELECT {vade_col} AS vade, {tutar_col} AS tutar FROM {tablo} "
                    f"WHERE {vade_col} IS NOT NULL AND strftime('%Y', {vade_col}) = :yil"
                )
                try:
                    for row in session.execute(sql, {"yil": str(yil)}).mappings():
                        v = row["vade"]
                        if hasattr(v, "month"):
                            aylar[int(v.month)] = _q2(aylar[int(v.month)] + _q2(row["tutar"]))
                except Exception:
                    continue
                break
        return aylar

    @classmethod
    def pdf_rapor_yaz(
        cls,
        plan_id: int,
        yol: str | Path,
        *,
        olcu_turu: str = OLCU_SATIS,
        firma_id: int | None = None,
    ) -> Path:
        """Basit PDF: plan kodu + aylık bütçe/gerçekleşme (reportlab yoksa minimal PDF)."""
        plan = cls.plan_getir(plan_id, firma_id=firma_id)
        if plan is None:
            raise ValueError("Plan bulunamadı.")
        kars = cls.karsilastirma(plan_id, olcu_turu=olcu_turu, firma_id=firma_id)
        hedef = Path(yol)
        hedef.parent.mkdir(parents=True, exist_ok=True)
        satirlar_txt = [
            f"Butce Raporu — {plan['kod']} {plan['ad']}",
            (
                f"Yil {plan['mali_yil']} | Durum {plan['durum']} | Surum {plan.get('surum')} | "
                f"Senaryo {plan.get('senaryo') or 'TEMEL'} | Olcu {olcu_turu}"
            ),
            "Ay  Butce          Gerceklesen    Fark",
        ]
        for s in kars.get("satirlar") or []:
            ger = s.get("on_muhasebe")
            fark = s.get("fark_on")
            satirlar_txt.append(
                f"{s['ay']:02d}  {s.get('butce') or '-':>12}  {ger or '-':>12}  {fark or '-':>12}"
            )
        try:
            from reportlab.lib.pagesizes import A4
            from reportlab.pdfgen import canvas

            c = canvas.Canvas(str(hedef), pagesize=A4)
            _w, h = A4
            y = h - 40
            for i, line in enumerate(satirlar_txt):
                c.setFont("Helvetica-Bold" if i == 0 else "Helvetica", 12 if i == 0 else 9)
                c.drawString(40, y, line[:110])
                y -= 14 if i else 18
                if y < 50:
                    c.showPage()
                    y = h - 40
            c.save()
        except Exception:
            # Minimal tek sayfa PDF (Latin-1 güvenli satırlar)
            def _esc(t: str) -> str:
                return (
                    t.replace("\\", "\\\\")
                    .replace("(", "\\(")
                    .replace(")", "\\)")
                    .encode("latin-1", "replace")
                    .decode("latin-1")
                )

            y = 800
            icerik = ["BT", "/F1 10 Tf"]
            for line in satirlar_txt:
                icerik.append(f"40 {y} Td ({_esc(line[:90])}) Tj")
                icerik.append("0 -14 Td")
                y -= 14
            icerik.append("ET")
            stream = "\n".join(icerik).encode("latin-1", "replace")
            objs = []
            objs.append(b"1 0 obj<< /Type /Catalog /Pages 2 0 R >>endobj\n")
            objs.append(b"2 0 obj<< /Type /Pages /Kids [3 0 R] /Count 1 >>endobj\n")
            objs.append(
                b"3 0 obj<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] "
                b"/Contents 4 0 R /Resources<< /Font<< /F1 5 0 R >> >> >>endobj\n"
            )
            objs.append(
                f"4 0 obj<< /Length {len(stream)} >>stream\n".encode("latin-1")
                + stream
                + b"\nendstream\nendobj\n"
            )
            objs.append(b"5 0 obj<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>endobj\n")
            out = bytearray(b"%PDF-1.4\n")
            offsets = [0]
            for o in objs:
                offsets.append(len(out))
                out.extend(o)
            xref = len(out)
            out.extend(f"xref\n0 {len(objs) + 1}\n".encode())
            out.extend(b"0000000000 65535 f \n")
            for off in offsets[1:]:
                out.extend(f"{off:010d} 00000 n \n".encode())
            out.extend(
                f"trailer<< /Size {len(objs) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode()
            )
            hedef.write_bytes(out)
        return hedef

    # ------------------------------------------------------------------ yardımcılar

    @staticmethod
    def _plan_dict(p: ButcePlan) -> dict[str, Any]:
        return {
            "id": int(p.id),
            "kod": p.kod,
            "ad": p.ad,
            "mali_yil": int(p.mali_yil),
            "durum": p.durum,
            "para_birimi": p.para_birimi,
            "firma_id": int(p.firma_id),
            "surum": int(p.surum),
            "senaryo": getattr(p, "senaryo", None) or SENARYO_TEMEL,
            "kaynak_plan_id": getattr(p, "kaynak_plan_id", None),
            "proje_kodu": getattr(p, "proje_kodu", None),
            "aciklama": p.aciklama,
            "onay_tarihi": (
                p.onay_tarihi.isoformat(sep=" ", timespec="seconds")
                if getattr(p, "onay_tarihi", None)
                else None
            ),
            "onaylayan": getattr(p, "onaylayan", None),
            "olusturma": p.olusturma.isoformat(sep=" ", timespec="seconds") if p.olusturma else None,
            "olusturan": p.olusturan,
        }

    @staticmethod
    def _satir_dict(s: ButceSatir) -> dict[str, Any]:
        return {
            "id": int(s.id),
            "plan_id": int(s.plan_id),
            "olcu_turu": s.olcu_turu,
            "kategori": s.kategori,
            "ay": int(s.ay),
            "ay_adi": ay_adi(int(s.ay)),
            "kaynak_giris": getattr(s, "kaynak_giris", None),
            "tutar": _q2(s.tutar),
            "aciklama": s.aciklama,
        }

    @classmethod
    def _satis_aylik_net(cls, bas: date, bit: date) -> tuple[dict[int, Decimal], int]:
        """Satış faturaları KDV hariç net (tl_matrah); taslak/iptal hariç.

        Ham SQL — ORM ilişki ağı zorunlu değil; yalnız okuma, belge üretmez.
        """
        from sqlalchemy import text

        aylar: dict[int, Decimal] = {}
        sayac = 0
        with get_session() as session:
            if not _tablo_var(session, "satis_faturalari"):
                return {}, 0
            # is_deleted / cancelled_at kolonları eski DB'de yoksa yok say
            sutunlar = _sutunlar(session, "satis_faturalari")
            silinen = "AND IFNULL(is_deleted, 0) = 0" if "is_deleted" in sutunlar else ""
            iptal_kolon = "AND cancelled_at IS NULL" if "cancelled_at" in sutunlar else ""
            sql = text(
                f"""
                SELECT fatura_tarihi, tl_matrah, durum
                FROM satis_faturalari
                WHERE fatura_tarihi >= :bas AND fatura_tarihi <= :bit
                {silinen}
                {iptal_kolon}
                """
            )
            for fatura_tarihi, tl_matrah, durum_raw in session.execute(
                sql, {"bas": bas.isoformat(), "bit": bit.isoformat()}
            ):
                durum = (durum_raw or "").strip().upper()
                durum_n = durum.replace("İ", "I")
                if durum in _SATIS_HARIC_DURUM or durum_n in {"TASLAK", "IPTAL", "IPTAL EDILDI"}:
                    continue
                if isinstance(fatura_tarihi, str):
                    ay = int(fatura_tarihi[5:7])
                else:
                    ay = int(fatura_tarihi.month)
                aylar[ay] = aylar.get(ay, _SIFIR) + _q2(tl_matrah)
                sayac += 1
        return aylar, sayac

    @classmethod
    def _gider_aylik_net(cls, bas: date, bit: date) -> tuple[dict[int, Decimal], int]:
        """Hizmet gider faturaları (tl_matrah) + gider fişleri (tutar); iptal hariç."""
        aylar: dict[int, Decimal] = {}
        sayac = 0
        with get_session() as session:
            # Hizmet alış (gider) faturaları
            try:
                from database.models.hizmet_faturasi import HizmetFaturasi

                if _tablo_var(session, "hizmet_faturalari"):
                    for f in session.scalars(
                        select(HizmetFaturasi).where(
                            HizmetFaturasi.fatura_turu == "GIDER",
                            HizmetFaturasi.fatura_tarihi >= bas,
                            HizmetFaturasi.fatura_tarihi <= bit,
                        )
                    ).all():
                        durum = (getattr(f, "durum", "") or "").strip().upper().replace("İ", "I")
                        if durum in {"TASLAK", "IPTAL", "IPTAL EDILDI"}:
                            continue
                        ay = int(f.fatura_tarihi.month)
                        aylar[ay] = aylar.get(ay, _SIFIR) + _q2(getattr(f, "tl_matrah", 0))
                        sayac += 1
            except Exception:  # noqa: BLE001
                pass
            # Gider fişleri
            try:
                from database.models.finans import GiderFisi

                if _tablo_var(session, "gider_fisleri"):
                    for g in session.scalars(
                        select(GiderFisi).where(
                            GiderFisi.tarih >= bas,
                            GiderFisi.tarih <= bit,
                        )
                    ).all():
                        durum = (getattr(g, "durum", "") or "").strip().upper().replace("İ", "I")
                        if durum in {"IPTAL", "TASLAK"}:
                            continue
                        ay = int(g.tarih.month)
                        aylar[ay] = aylar.get(ay, _SIFIR) + _q2(getattr(g, "tutar", 0))
                        sayac += 1
            except Exception:  # noqa: BLE001
                pass
        return aylar, sayac

    @classmethod
    def _gm_aylik(
        cls,
        bas: date,
        bit: date,
        *,
        olcu: str,
        firma_id: int = 0,
    ) -> tuple[dict[int, Decimal], int]:
        """Genel muhasebe fiş satırlarından aylık net (ham SQL; belge üretmez).

        SATIS: 60x / 64x / 67x → alacak − borç
        GIDER: 62–63, 65–66, 68 ve 7xx → borç − alacak
        Yansıma/kapanış için güvenilir tür yoksa metin tahminiyle sessiz filtre yok;
        yalnız Açılış Fişi ve taslak/iptal (ters kayıtsız) elenir.
        """
        from sqlalchemy import text

        aylar: dict[int, Decimal] = {}
        fis_idler: set[int] = set()
        with get_session() as session:
            sutunlar = _sutunlar(session, "muhasebe_fisleri")
            firma_filtre = ""
            params: dict[str, Any] = {
                "bas": bas.isoformat(),
                "bit": bit.isoformat(),
            }
            if "firma_id" in sutunlar and firma_id:
                firma_filtre = "AND f.firma_id = :firma_id"
                params["firma_id"] = int(firma_id)

            # defterde kalan: Kesinleşmiş veya (İptal + ters_fis_id)
            ters_kolon = "ters_fis_id" in sutunlar
            if ters_kolon:
                durum_filtre = (
                    "(f.durum = 'Kesinleşmiş' OR "
                    "(f.durum = 'İptal' AND f.ters_fis_id IS NOT NULL))"
                )
            else:
                durum_filtre = "f.durum = 'Kesinleşmiş'"

            sql = text(
                f"""
                SELECT f.id, f.fis_tarihi, s.hesap_kodu, s.borc, s.alacak, f.fis_turu
                FROM muhasebe_fis_satirlari s
                JOIN muhasebe_fisleri f ON f.id = s.fis_id
                WHERE f.fis_tarihi >= :bas AND f.fis_tarihi <= :bit
                  AND {durum_filtre}
                  AND IFNULL(f.fis_turu, '') != 'Açılış Fişi'
                  {firma_filtre}
                """
            )
            for fis_id, fis_tarihi, hesap_kodu, borc, alacak, _fis_turu in session.execute(
                sql, params
            ):
                kod = (hesap_kodu or "").strip()
                net = cls._gm_satir_net(kod, borc, alacak, olcu=olcu)
                if net is None:
                    continue
                if isinstance(fis_tarihi, str):
                    ay = int(fis_tarihi[5:7])
                else:
                    ay = int(fis_tarihi.month)
                aylar[ay] = aylar.get(ay, _SIFIR) + net
                fis_idler.add(int(fis_id))
        return aylar, len(fis_idler)

    @staticmethod
    def _gm_satir_net(
        hesap_kodu: str, borc, alacak, *, olcu: str
    ) -> Decimal | None:
        kod = (hesap_kodu or "").strip()
        if not kod:
            return None
        b = _q2(borc)
        a = _q2(alacak)
        if olcu == "SATIS":
            # Gelir: 60x satış, 64 diğer faaliyet, 67 olağandışı gelir
            if kod.startswith("60") or kod.startswith("64") or kod.startswith("67"):
                return _q2(a - b)
            return None
        if olcu == "GIDER":
            if kod.startswith("7"):
                return _q2(b - a)
            if any(kod.startswith(p) for p in ("62", "63", "65", "66", "68")):
                return _q2(b - a)
            return None
        return None


def _tablo_var(session, ad: str) -> bool:
    try:
        bind = session.get_bind()
        from sqlalchemy import inspect as sa_inspect

        return sa_inspect(bind).has_table(ad)
    except Exception:  # noqa: BLE001
        return False


def _sutunlar(session, tablo: str) -> set[str]:
    try:
        bind = session.get_bind()
        from sqlalchemy import inspect as sa_inspect

        return {c["name"] for c in sa_inspect(bind).get_columns(tablo)}
    except Exception:  # noqa: BLE001
        return set()


def ay_araligi(yil: int, ay: int) -> tuple[date, date]:
    son = monthrange(yil, ay)[1]
    return date(yil, ay, 1), date(yil, ay, son)


def _butce_ayar_yolu(firma_id: int) -> Path:
    import os

    taban = Path(os.environ.get("LOCALAPPDATA") or Path.home()) / "MuhasebeProgrami" / "ayarlar"
    taban.mkdir(parents=True, exist_ok=True)
    return taban / f"butce_esikler_f{int(firma_id)}.json"


class ButceAyarService:
    """Aşım eşikleri (firma) + kategori/hesap eşleştirme kayıtları."""

    VARSAYILAN_ESIK = {
        "bilgi_yuzde": 80,
        "uyari_yuzde": 100,
        "asim_yuzde": 100,
    }

    @staticmethod
    def esikler_oku(firma_id: int = 0) -> dict[str, Any]:
        import json

        yol = _butce_ayar_yolu(firma_id)
        if not yol.is_file():
            return dict(ButceAyarService.VARSAYILAN_ESIK)
        try:
            veri = json.loads(yol.read_text(encoding="utf-8"))
            out = dict(ButceAyarService.VARSAYILAN_ESIK)
            for k in out:
                if k in veri:
                    out[k] = int(veri[k])
            return out
        except Exception:  # noqa: BLE001
            return dict(ButceAyarService.VARSAYILAN_ESIK)

    @staticmethod
    def esikler_kaydet(firma_id: int, bilgi: int, uyari: int, asim: int) -> dict[str, Any]:
        import json

        if not (0 <= bilgi <= 500 and 0 <= uyari <= 500 and 0 <= asim <= 500):
            raise ValueError("Eşik yüzdeleri 0–500 arasında olmalı.")
        veri = {"bilgi_yuzde": int(bilgi), "uyari_yuzde": int(uyari), "asim_yuzde": int(asim)}
        yol = _butce_ayar_yolu(firma_id)
        yol.write_text(json.dumps(veri, ensure_ascii=False, indent=2), encoding="utf-8")
        return veri

    @staticmethod
    def eslesme_listele(firma_id: int = 0, olcu_turu: str | None = None) -> list[dict[str, Any]]:
        with get_session() as session:
            q = select(ButceEslesme).where(ButceEslesme.firma_id == int(firma_id))
            if olcu_turu:
                q = q.where(ButceEslesme.olcu_turu == olcu_turu.strip().upper())
            q = q.order_by(ButceEslesme.olcu_turu, ButceEslesme.kategori)
            return [
                {
                    "id": e.id,
                    "firma_id": e.firma_id,
                    "olcu_turu": e.olcu_turu,
                    "kategori": e.kategori,
                    "kaynak": e.kaynak,
                    "kaynak_kod": e.kaynak_kod or "",
                    "aktif": bool(e.aktif),
                    "aciklama": e.aciklama or "",
                }
                for e in session.scalars(q).all()
            ]

    @staticmethod
    def eslesme_kaydet(
        *,
        firma_id: int = 0,
        olcu_turu: str,
        kategori: str,
        kaynak: str = KAYNAK_ON_MUHASEBE,
        kaynak_kod: str | None = None,
        aciklama: str | None = None,
        eslesme_id: int | None = None,
    ) -> int:
        olcu = (olcu_turu or "").strip().upper()
        kat = (kategori or "").strip() or "GENEL"
        kay = (kaynak or KAYNAK_ON_MUHASEBE).strip().upper()
        if olcu not in OLCU_TURLERI and olcu not in ("ALIS", "KARLILIK", "BILANCO"):
            raise ValueError(f"Geçersiz ölçü: {olcu}")
        if kay not in (KAYNAK_ON_MUHASEBE, KAYNAK_GENEL_MUHASEBE):
            raise ValueError("Kaynak ON_MUHASEBE veya GENEL_MUHASEBE olmalı.")
        with get_session() as session:
            if eslesme_id:
                e = session.get(ButceEslesme, int(eslesme_id))
                if not e or e.firma_id != int(firma_id):
                    raise ValueError("Eşleştirme bulunamadı.")
            else:
                e = ButceEslesme(firma_id=int(firma_id))
                session.add(e)
            e.olcu_turu = olcu
            e.kategori = kat
            e.kaynak = kay
            e.kaynak_kod = (kaynak_kod or "").strip() or None
            e.aciklama = (aciklama or "").strip() or None
            e.aktif = 1
            session.flush()
            return int(e.id)

    @staticmethod
    def eslesme_pasiflestir(eslesme_id: int, firma_id: int = 0) -> None:
        with get_session() as session:
            e = session.get(ButceEslesme, int(eslesme_id))
            if not e or e.firma_id != int(firma_id):
                raise ValueError("Eşleştirme bulunamadı.")
            e.aktif = 0
