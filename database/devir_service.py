"""Yıllık Devir / Dönem Yönetimi — çekirdek servis.

===========================================================================
AŞAMA 1 — Mevcut yapı haritası (aynı firma DB, dönemden bağımsız kartlar)
===========================================================================
Firma          : system.db → companies; operasyon: companies/company_*.db
Dönem          : donemler (Donem / DonemService) — aynı DB içinde çok dönem
Cari kapatma   : cari_kapatmalar + cari hareket / belge servisleri
Stok maliyet   : stok_hareketleri, stok_lotlari; StokService
Finans planları: finans_hesaplari, pos_valor_kayitlari, kredi/KMH/çek modelleri
Muhasebe       : genel_muhasebe modelleri + muhasebelestirme
Raporlar       : dönem filtresi oturum.donem; açılış cirosuna karışmamalı
Yedek          : CompanyMgmtService.yedek_al + BackupService.dogrula_yedek

Karar: Yeni yıl = yeni Donem kaydı (yeni firma DEĞİL). Devir, kesim bakiyesi /
açık kalem açılışı yazar; kaynak belgeleri silmez veya kopyalamaz.
===========================================================================
"""

from __future__ import annotations

import json
import re
import sqlite3
from datetime import date, datetime
from pathlib import Path
from typing import Any

from sqlalchemy import select

import database.database as _db
from database.database import Base, get_session
from database.models.devir import (
    DURUM_HAZIRLANIYOR,
    DURUM_KONTROL_GEREKLI,
    DURUM_ONIZLEME_HAZIR,
    DURUMLAR,
    MODUL_ACIK_ISLEM,
    MODUL_CARI,
    MODUL_FINANS,
    MODUL_GM,
    MODUL_STOK,
    MODULLER,
    SCHEMA_SURUM,
    TUR_KESIN,
    TUR_LER,
    TUR_ON,
    VARSAYILAN_AYARLAR,
    DevirAyar,
    DevirDenetim,
    DevirEslesme,
    DevirIs,
)
from database.models.donem import Donem
from database.session_manager import oturum

_IS_NO_RE = re.compile(r"^DEV-(\d{4})-(\d{4})$")

DURUM_ETIKET = {
    "HAZIRLANIYOR": "Hazırlanıyor",
    "KONTROL_GEREKLI": "Kontrol Gerekli",
    "ONIZLEME_HAZIR": "Ön İzleme Hazır",
    "DEVREDILIYOR": "Devrediliyor",
    "DURAKLATILDI": "Duraklatıldı",
    "KARSILASTIRILIYOR": "Karşılaştırılıyor",
    "TAMAMLANDI": "Tamamlandı",
    "UYARILAR_VAR": "Uyarılar Var",
    "BASARISIZ": "İşlem Tamamlanamadı",
    "GERI_ALINDI": "Geri Alındı",
}

# Aşama 1 haritası — UI / testlerde okunabilir
MIMARI_HARITA: dict[str, str] = {
    "firma": "database/system + company_database.CompanyDatabase",
    "donem": "database/models/donem.py + database/donem_service.py",
    "cari_kapatma": "database/models/cari.py (cari_kapatmalar)",
    "stok_maliyet": "database/stok_service.py + stok_lotlari / stok_hareketleri",
    "finans": "database/models/finans.py + finans_service",
    "muhasebe": "database/models/genel_muhasebe.py + muhasebelestirme",
    "yedek": "database/system/company_service.yedek_al + servis_sistem/backup_service",
    "devir_sema": f"database/models/devir.py (schema_surum={SCHEMA_SURUM})",
}


def _firma_id(firma_id: int | None = None) -> int:
    if firma_id is not None:
        return int(firma_id)
    cid = oturum.company_id
    if cid is None:
        raise ValueError("Aktif firma yok.")
    return int(cid)


def _kullanici() -> str:
    return (oturum.kullanici_adi or oturum.role_kod or "sistem")[:120]


def _json_dumps(obj: Any) -> str:
    return json.dumps(obj, ensure_ascii=False, default=str)


def _json_loads(raw: str | None, default: Any) -> Any:
    if not raw:
        return default
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return default


class DevirService:
    """Devir işi yaşam döngüsü (Aşama 2+: şema, ayar, iş CRUD, yedek)."""

    _schema_hazir = False

    @classmethod
    def ensure_schema(cls, eng=None) -> None:
        bag = eng if eng is not None else _db.engine
        if bag is None:
            return
        import database.models.devir  # noqa: F401

        Base.metadata.create_all(
            bind=bag,
            tables=[
                DevirAyar.__table__,
                DevirIs.__table__,
                DevirEslesme.__table__,
                DevirDenetim.__table__,
            ],
        )
        cls._schema_hazir = True

    @classmethod
    def mimari_harita(cls) -> dict[str, str]:
        return dict(MIMARI_HARITA)

    # ── Ayarlar ───────────────────────────────────────────────

    @classmethod
    def ayarlari_getir(cls, *, firma_id: int | None = None) -> dict[str, Any]:
        cls.ensure_schema()
        fid = _firma_id(firma_id)
        with get_session() as session:
            kayit = session.get(DevirAyar, fid)
            if kayit is None:
                return {
                    "firma_id": fid,
                    "surum": 1,
                    "ayarlar": dict(VARSAYILAN_AYARLAR),
                }
            ayar = dict(VARSAYILAN_AYARLAR)
            ayar.update(_json_loads(kayit.ayarlar_json, {}))
            return {
                "firma_id": fid,
                "surum": int(kayit.surum or 1),
                "ayarlar": ayar,
                "guncelleme": kayit.guncelleme,
                "guncelleyen": kayit.guncelleyen,
            }

    @classmethod
    def ayarlari_kaydet(
        cls,
        ayarlar: dict[str, Any],
        *,
        firma_id: int | None = None,
    ) -> dict[str, Any]:
        cls.ensure_schema()
        cls._yetki_ayar()
        fid = _firma_id(firma_id)
        birlesik = dict(VARSAYILAN_AYARLAR)
        birlesik.update(ayarlar or {})
        with get_session() as session:
            kayit = session.get(DevirAyar, fid)
            if kayit is None:
                kayit = DevirAyar(firma_id=fid, surum=1, ayarlar_json=_json_dumps(birlesik))
                session.add(kayit)
            else:
                kayit.ayarlar_json = _json_dumps(birlesik)
                kayit.surum = int(kayit.surum or 1) + 1
            kayit.guncelleme = datetime.now()
            kayit.guncelleyen = _kullanici()
            session.flush()
            surum = int(kayit.surum)
        cls._denetim_yaz(
            None,
            fid,
            "AYAR_KAYIT",
            {"surum": surum, "ayarlar": birlesik},
        )
        return cls.ayarlari_getir(firma_id=fid)

    # ── Dönem yardımcıları ────────────────────────────────────

    @classmethod
    def donemleri_listele(cls) -> list[dict[str, Any]]:
        from database.donem_service import DonemService

        return DonemService.listele()

    @classmethod
    def aktif_devir_isi(
        cls,
        kaynak_donem_id: int,
        hedef_donem_id: int,
        *,
        firma_id: int | None = None,
    ) -> dict[str, Any] | None:
        """Aynı kaynak→hedef için tamamlanmamış / tamamlanmış son iş."""
        cls.ensure_schema()
        fid = _firma_id(firma_id)
        with get_session() as session:
            row = session.scalar(
                select(DevirIs)
                .where(
                    DevirIs.firma_id == fid,
                    DevirIs.kaynak_donem_id == int(kaynak_donem_id),
                    DevirIs.hedef_donem_id == int(hedef_donem_id),
                    DevirIs.durum != "GERI_ALINDI",
                )
                .order_by(DevirIs.id.desc())
                .limit(1)
            )
            return cls._is_dict(row) if row else None

    # ── İş CRUD ───────────────────────────────────────────────

    @classmethod
    def is_olustur(
        cls,
        *,
        kaynak_donem_id: int,
        hedef_donem_id: int,
        kesim_tarihi: date,
        acilis_tarihi: date,
        devir_turu: str = TUR_ON,
        kapsam: list[str] | None = None,
        firma_id: int | None = None,
    ) -> dict[str, Any]:
        cls.ensure_schema()
        cls._yetki_devir()
        fid = _firma_id(firma_id)
        if int(kaynak_donem_id) == int(hedef_donem_id):
            raise ValueError("Kaynak ve hedef dönem aynı olamaz.")
        if acilis_tarihi <= kesim_tarihi:
            raise ValueError("Açılış tarihi kesim tarihinden sonra olmalıdır.")
        if devir_turu not in TUR_LER:
            raise ValueError(f"Geçersiz devir türü: {devir_turu}")
        if devir_turu == TUR_KESIN and oturum.role_kod != "YONETICI":
            raise PermissionError("Kesin devir yalnız yönetici tarafından başlatılabilir.")

        mevcut = cls.aktif_devir_isi(kaynak_donem_id, hedef_donem_id, firma_id=fid)
        if mevcut and mevcut["durum"] not in (
            "TAMAMLANDI",
            "UYARILAR_VAR",
            "BASARISIZ",
            "GERI_ALINDI",
        ):
            raise ValueError(
                f"Bu dönem çifti için açık iş var: {mevcut['is_no']} "
                f"({DURUM_ETIKET.get(mevcut['durum'], mevcut['durum'])}). "
                "Yeni iş açmak yerine mevcut işi açın."
            )

        with get_session() as session:
            kaynak = session.get(Donem, int(kaynak_donem_id))
            hedef = session.get(Donem, int(hedef_donem_id))
            if kaynak is None or hedef is None:
                raise ValueError("Kaynak veya hedef dönem bulunamadı.")

        ayar_paket = cls.ayarlari_getir(firma_id=fid)
        kaps = list(kapsam) if kapsam else [MODUL_CARI, MODUL_STOK, MODUL_FINANS, MODUL_ACIK_ISLEM]
        for m in kaps:
            if m not in MODULLER:
                raise ValueError(f"Geçersiz modül: {m}")

        with get_session() as session:
            yil = int(kesim_tarihi.year)
            is_no = cls._sonraki_is_no(session, fid, yil)
            for _ in range(5):
                var = session.scalar(
                    select(DevirIs.id).where(DevirIs.firma_id == fid, DevirIs.is_no == is_no)
                )
                if var is None:
                    break
                is_no = cls._sonraki_is_no(session, fid, yil)
            is_ = DevirIs(
                is_no=is_no,
                firma_id=fid,
                kaynak_donem_id=int(kaynak_donem_id),
                hedef_donem_id=int(hedef_donem_id),
                kesim_tarihi=kesim_tarihi,
                acilis_tarihi=acilis_tarihi,
                devir_turu=devir_turu,
                durum=DURUM_HAZIRLANIYOR,
                kapsam_json=_json_dumps(kaps),
                ayarlar_json=_json_dumps(ayar_paket["ayarlar"]),
                ayarlar_surum=int(ayar_paket["surum"]),
                schema_surum=SCHEMA_SURUM,
                olusturma=datetime.now(),
                olusturan=_kullanici(),
            )
            session.add(is_)
            session.flush()
            is_id = int(is_.id)
            sonuc = cls._is_dict(is_)

        cls._denetim_yaz(
            is_id,
            fid,
            "IS_OLUSTUR",
            {
                "is_no": sonuc["is_no"],
                "kaynak_donem_id": kaynak_donem_id,
                "hedef_donem_id": hedef_donem_id,
                "devir_turu": devir_turu,
                "kapsam": kaps,
            },
        )
        return sonuc

    @classmethod
    def is_getir(cls, is_id: int, *, firma_id: int | None = None) -> dict[str, Any] | None:
        cls.ensure_schema()
        fid = _firma_id(firma_id)
        with get_session() as session:
            is_ = session.get(DevirIs, int(is_id))
            if is_ is None or int(is_.firma_id) != fid:
                return None
            return cls._is_dict(is_)

    @classmethod
    def isleri_listele(cls, *, firma_id: int | None = None, limit: int = 50) -> list[dict]:
        cls.ensure_schema()
        fid = _firma_id(firma_id)
        with get_session() as session:
            rows = session.scalars(
                select(DevirIs)
                .where(DevirIs.firma_id == fid)
                .order_by(DevirIs.id.desc())
                .limit(int(limit))
            ).all()
            return [cls._is_dict(r) for r in rows]

    @classmethod
    def onizlemeyi_gecersiz_kil(cls, is_id: int, *, firma_id: int | None = None) -> None:
        cls.ensure_schema()
        fid = _firma_id(firma_id)
        with get_session() as session:
            is_ = session.get(DevirIs, int(is_id))
            if is_ is None or int(is_.firma_id) != fid:
                raise ValueError("Devir işi bulunamadı.")
            is_.onizleme_gecerli = False
            is_.onizleme_ozet_json = None

    @classmethod
    def durum_guncelle(
        cls,
        is_id: int,
        durum: str,
        *,
        firma_id: int | None = None,
        hata_mesaji: str | None = None,
    ) -> dict[str, Any]:
        cls.ensure_schema()
        if durum not in DURUMLAR:
            raise ValueError(f"Geçersiz durum: {durum}")
        fid = _firma_id(firma_id)
        with get_session() as session:
            is_ = session.get(DevirIs, int(is_id))
            if is_ is None or int(is_.firma_id) != fid:
                raise ValueError("Devir işi bulunamadı.")
            eski = is_.durum
            is_.durum = durum
            if hata_mesaji is not None:
                is_.hata_mesaji = hata_mesaji
            if durum == "DEVREDILIYOR" and is_.baslama is None:
                is_.baslama = datetime.now()
            if durum in ("TAMAMLANDI", "UYARILAR_VAR", "BASARISIZ", "GERI_ALINDI"):
                is_.bitis = datetime.now()
            session.flush()
            sonuc = cls._is_dict(is_)
        cls._denetim_yaz(is_id, fid, "DURUM", {"eski": eski, "yeni": durum})
        return sonuc

    # ── Yedek ─────────────────────────────────────────────────

    @classmethod
    def yedek_al_ve_dogrula(
        cls,
        is_id: int,
        hedef_klasor: str | Path | None = None,
        *,
        firma_id: int | None = None,
    ) -> dict[str, Any]:
        """Devir öncesi yedek + dosya/SQLite doğrulama."""
        cls.ensure_schema()
        cls._yetki_devir()
        fid = _firma_id(firma_id)
        is_ = cls.is_getir(is_id, firma_id=fid)
        if is_ is None:
            raise ValueError("Devir işi bulunamadı.")

        import shutil

        from database.servis_sistem.backup_service import BackupService

        klasor = Path(hedef_klasor) if hedef_klasor else BackupService.yedek_klasoru_onerisi()
        klasor = klasor / "devir" / is_["is_no"]
        klasor.mkdir(parents=True, exist_ok=True)

        yol: Path | None = None
        try:
            from database.system.company_service import CompanyMgmtService

            yol = CompanyMgmtService.yedek_al(fid, klasor)
        except Exception:
            # Sistem oturumu yoksa aktif firma DB dosyasını doğrudan kopyala
            kaynak = None
            try:
                from database.database import company_db, firma_db_yolu_coz

                if company_db.acik and company_db._db_path:
                    kaynak = Path(company_db._db_path)
                elif oturum.db_path:
                    kaynak = firma_db_yolu_coz(oturum.db_path) or Path(oturum.db_path)
            except Exception:
                kaynak = None
            if kaynak is None or not Path(kaynak).is_file():
                raise ValueError("Yedek alınamadı: aktif firma DB yolu bulunamadı.")
            kaynak = Path(kaynak)
            damga = datetime.now().strftime("%Y%m%d_%H%M%S")
            yol = klasor / f"devir_{is_['is_no']}_{damga}.db"
            shutil.copy2(kaynak, yol)
            for ek in ("-wal", "-shm"):
                k = Path(str(kaynak) + ek)
                if k.is_file():
                    shutil.copy2(k, Path(str(yol) + ek))

        BackupService.dogrula_yedek(yol)
        try:
            conn = sqlite3.connect(f"file:{yol}?mode=ro", uri=True)
            try:
                conn.execute("SELECT 1").fetchone()
            finally:
                conn.close()
        except Exception as exc:  # noqa: BLE001
            raise ValueError(f"Yedek SQLite doğrulaması başarısız: {exc}") from exc

        with get_session() as session:
            row = session.get(DevirIs, int(is_id))
            if row is None:
                raise ValueError("Devir işi bulunamadı.")
            row.yedek_yolu = str(yol)
            row.yedek_dogrulandi = True
            session.flush()
            sonuc = cls._is_dict(row)
        cls._denetim_yaz(is_id, fid, "YEDEK", {"yol": str(yol), "boyut": yol.stat().st_size})
        return sonuc

    # ── Aşama 3: kontrol + kesim görüntüsü + ön izleme ─────────

    @classmethod
    def on_kontrol(
        cls,
        is_id: int,
        *,
        firma_id: int | None = None,
    ) -> dict[str, Any]:
        """Devir öncesi yapısal kontroller (yazmaz)."""
        cls.ensure_schema()
        fid = _firma_id(firma_id)
        is_ = cls.is_getir(is_id, firma_id=fid)
        if is_ is None:
            raise ValueError("Devir işi bulunamadı.")

        hatalar: list[dict[str, str]] = []
        uyarilar: list[dict[str, str]] = []

        if is_["kaynak_donem_id"] == is_["hedef_donem_id"]:
            hatalar.append(
                {"kod": "DONEM_AYNI", "mesaj": "Kaynak ve hedef dönem aynı.", "kayit": ""}
            )
        if is_["acilis_tarihi"] <= is_["kesim_tarihi"]:
            hatalar.append(
                {
                    "kod": "TARIH",
                    "mesaj": "Açılış tarihi kesimden sonra olmalıdır.",
                    "kayit": "",
                }
            )
        with get_session() as session:
            kaynak = session.get(Donem, int(is_["kaynak_donem_id"]))
            hedef = session.get(Donem, int(is_["hedef_donem_id"]))
            if kaynak is None:
                hatalar.append({"kod": "KAYNAK_YOK", "mesaj": "Kaynak dönem yok.", "kayit": ""})
            if hedef is None:
                hatalar.append({"kod": "HEDEF_YOK", "mesaj": "Hedef dönem yok.", "kayit": ""})
            if kaynak and hedef:
                if is_["kesim_tarihi"] > kaynak.bitis_tarihi:
                    uyarilar.append(
                        {
                            "kod": "KESIM_DISI",
                            "mesaj": "Kesim tarihi kaynak dönem bitişinden sonra.",
                            "kayit": kaynak.donem_adi,
                        }
                    )
                if is_["acilis_tarihi"] < hedef.baslangic_tarihi:
                    uyarilar.append(
                        {
                            "kod": "ACILIS_ERKEN",
                            "mesaj": "Açılış tarihi hedef dönem başlangıcından önce.",
                            "kayit": hedef.donem_adi,
                        }
                    )

        mevcut = cls.aktif_devir_isi(
            is_["kaynak_donem_id"], is_["hedef_donem_id"], firma_id=fid
        )
        if mevcut and int(mevcut["id"]) != int(is_id) and mevcut["durum"] in (
            "TAMAMLANDI",
            "UYARILAR_VAR",
            "DEVREDILIYOR",
        ):
            uyarilar.append(
                {
                    "kod": "ONCEKI_IS",
                    "mesaj": f"Bu dönem çiftinde başka iş var: {mevcut['is_no']}.",
                    "kayit": mevcut["is_no"],
                }
            )

        if is_["devir_turu"] == TUR_KESIN and oturum.role_kod != "YONETICI":
            hatalar.append(
                {
                    "kod": "YETKI_KESIN",
                    "mesaj": "Kesin devir için yönetici yetkisi gerekli.",
                    "kayit": "",
                }
            )

        if hatalar:
            sonuc_kod = "DUZELTME_GEREKLI"
            durum = DURUM_KONTROL_GEREKLI
        elif uyarilar:
            sonuc_kod = "UYARI_VAR"
            durum = DURUM_KONTROL_GEREKLI
        else:
            sonuc_kod = "HAZIR"
            durum = DURUM_HAZIRLANIYOR

        cls.durum_guncelle(is_id, durum, firma_id=fid)
        return {
            "sonuc": sonuc_kod,
            "hatalar": hatalar,
            "uyarilar": uyarilar,
            "is_id": is_id,
        }

    @classmethod
    def kesim_cari(
        cls,
        kesim_tarihi: date,
        *,
        limit: int = 5000,
    ) -> dict[str, Any]:
        """Kesim tarihi itibarıyla açık cari kalemleri (salt okuma).

        Kesim sonrası kapatmalar geri eklenir; kesim sonrası belgeler dışlanır.
        Vade yeniden hesaplanmaz — belgedeki / hareketteki vade korunur.
        """
        from decimal import Decimal

        from sqlalchemy import func

        from sqlalchemy import text

        from database.acik_kalem_service import _KAYNAK_ONEKLERI, _kurus, para_anahtari
        from database.models.cari import CariKapatma, SatisHareketi

        TOL = Decimal("0.005")
        satirlar: list[dict[str, Any]] = []
        negatif_say = 0
        toplam_poz = Decimal("0")
        toplam_neg = Decimal("0")

        with get_session() as session:
            hareketler = session.scalars(
                select(SatisHareketi).where(SatisHareketi.satis_tarihi <= kesim_tarihi).limit(
                    int(limit) * 3
                )
            ).all()
            # kesim sonrası kapatma tutarları (hedef bazında)
            sonrasi = session.execute(
                select(
                    CariKapatma.hedef_hareket_id,
                    func.coalesce(func.sum(CariKapatma.tutar), 0),
                )
                .where(
                    CariKapatma.iptal.is_(False),
                    CariKapatma.tarih > kesim_tarihi,
                )
                .group_by(CariKapatma.hedef_hareket_id)
            ).all()
            ekle = {int(hid): _kurus(t) for hid, t in sonrasi if hid}

            cari_cache: dict[int, tuple[str | None, str | None]] = {}
            for h in hareketler:
                bn = h.belge_no or ""
                if bn.startswith(_KAYNAK_ONEKLERI) and _kurus(h.satis_tutari) <= 0:
                    continue
                kalan = _kurus(h.kalan_acik_tutar) + ekle.get(int(h.id), Decimal("0"))
                if abs(kalan) <= TOL:
                    continue
                cid = int(h.cari_id)
                if cid not in cari_cache:
                    row = session.execute(
                        text(
                            "SELECT cari_kodu, unvan FROM cari_kartlar WHERE id = :id"
                        ),
                        {"id": cid},
                    ).first()
                    cari_cache[cid] = (row[0], row[1]) if row else (None, None)
                kod, unvan = cari_cache[cid]
                pb = para_anahtari(h)
                vade = getattr(h, "vade_tarihi", None) or h.satis_tarihi
                yon = "BORC" if kalan > 0 else "ALACAK"
                if kalan < 0:
                    negatif_say += 1
                    toplam_neg += kalan
                else:
                    toplam_poz += kalan
                satirlar.append(
                    {
                        "hareket_id": h.id,
                        "cari_id": cid,
                        "cari_kodu": kod,
                        "cari_unvan": unvan,
                        "belge_no": bn,
                        "belge_tarihi": h.satis_tarihi,
                        "vade_tarihi": vade,
                        "para_birimi": pb,
                        "ilk_tutar": _kurus(h.satis_tutari),
                        "kalan": kalan,
                        "yon": yon,
                    }
                )
                if len(satirlar) >= limit:
                    break

        return {
            "kesim_tarihi": kesim_tarihi,
            "kalem_sayisi": len(satirlar),
            "negatif_kalem": negatif_say,
            "toplam_borc_yonu": str(toplam_poz),
            "toplam_alacak_yonu": str(toplam_neg),
            "satirlar": satirlar,
        }

    @classmethod
    def kesim_stok(cls, kesim_tarihi: date) -> dict[str, Any]:
        """Kesim FIFO miktar/değer özeti (salt okuma)."""
        from decimal import Decimal

        from database.stok_service import StokService

        with get_session() as session:
            envanter = StokService.fifo_envanter_degerleri(session, kesim_tarihi)
        miktar_toplam = Decimal("0")
        deger_bilinen = Decimal("0")
        negatif_satir = 0
        sifir_maliyet_miktar = Decimal("0")
        satir_ozet = []
        for (stok_id, depo_id), kayit in envanter.items():
            m = Decimal(str(kayit.get("miktar") or 0))
            d = Decimal(str(kayit.get("deger") or 0))
            if m == 0 and d == 0:
                continue
            miktar_toplam += m
            if m < 0:
                negatif_satir += 1
            if m != 0 and d == 0:
                sifir_maliyet_miktar += abs(m)
            else:
                deger_bilinen += d
            if len(satir_ozet) < 200:
                satir_ozet.append(
                    {
                        "stok_id": stok_id,
                        "depo_id": depo_id,
                        "miktar": str(m),
                        "deger": str(d),
                    }
                )
        return {
            "kesim_tarihi": kesim_tarihi,
            "satir_sayisi": sum(
                1
                for k in envanter.values()
                if Decimal(str(k.get("miktar") or 0)) != 0
                or Decimal(str(k.get("deger") or 0)) != 0
            ),
            "miktar_toplam_ham": str(miktar_toplam),
            "deger_bilinen": str(deger_bilinen),
            "negatif_satir": negatif_satir,
            "sifir_maliyet_miktar": str(sifir_maliyet_miktar),
            "ornek_satirlar": satir_ozet,
            "not": "Farklı birimler toplanmaz; miktar_toplam_ham yalnız sayısal özet.",
        }

    @classmethod
    def kesim_finans(cls, kesim_tarihi: date) -> dict[str, Any]:
        """Kasa/banka/kart kesim bakiyesi + POS bekleyen + açık çek/senet (salt okuma)."""
        from decimal import Decimal
        from collections import defaultdict

        from database.finans_service import FinansService
        from database.models.finans import FinansHesabi, FinansHareketi, PosValorKaydi

        pb_ozet: dict[str, Decimal] = defaultdict(lambda: Decimal("0"))
        satirlar: list[dict[str, Any]] = []
        negatif = 0
        tl_toplam = Decimal("0")

        with get_session() as session:
            hesaplar = session.scalars(select(FinansHesabi).where(FinansHesabi.aktif.is_(True))).all()
            for hesap in hesaplar:
                acilis = Decimal(str(hesap.acilis_bakiyesi or 0))
                acilis_t = getattr(hesap, "acilis_tarihi", None)
                if acilis_t is not None and acilis_t > kesim_tarihi:
                    acilis = Decimal("0")
                bakiye = acilis
                tl = Decimal("0")
                acilis_tl = getattr(hesap, "acilis_tl_karsiligi", None)
                if acilis_t is None or acilis_t <= kesim_tarihi:
                    if acilis_tl is not None:
                        tl = Decimal(str(acilis_tl))
                    elif FinansService.hesap_pb(hesap) == "TRY":
                        tl = acilis
                for h in session.scalars(
                    select(FinansHareketi).where(
                        FinansHareketi.hesap_id == hesap.id,
                        FinansHareketi.tarih <= kesim_tarihi,
                    )
                ).all():
                    isaret = FinansService.hareket_isareti(h.hareket_turu)
                    bakiye += Decimal(str(h.tutar or 0)) * isaret
                    h_tl = getattr(h, "tl_karsiligi", None)
                    if h_tl is not None:
                        tl += Decimal(str(h_tl)) * isaret
                    elif FinansService.hesap_pb(hesap) == "TRY":
                        tl += Decimal(str(h.tutar or 0)) * isaret
                pb = FinansService.hesap_pb(hesap)
                pb_ozet[pb] += bakiye
                tl_toplam += tl
                if bakiye < 0:
                    negatif += 1
                satirlar.append(
                    {
                        "hesap_id": hesap.id,
                        "hesap_adi": hesap.hesap_adi,
                        "hesap_turu": hesap.hesap_turu,
                        "alt_hesap_turu": getattr(hesap, "alt_hesap_turu", None),
                        "para_birimi": pb,
                        "bakiye": str(bakiye),
                        "tl_tasima": str(tl),
                    }
                )

            pos_bekleyen = 0
            pos_net = Decimal("0")
            try:
                for p in session.scalars(
                    select(PosValorKaydi).where(
                        PosValorKaydi.durum == "BEKLIYOR",
                        PosValorKaydi.tahsilat_tarihi <= kesim_tarihi,
                    )
                ).all():
                    pos_bekleyen += 1
                    pos_net += Decimal(str(p.net_tutar or 0))
            except Exception:
                pass

            cek_acik = 0
            cek_tutar = Decimal("0")
            try:
                from database.models.cek_senet import CekSenetEvrak

                kapali = ("TAHSİL EDİLDİ", "ÖDENDİ", "İADE", "KARŞILIKSIZ", "IPTAL", "İPTAL")
                for c in session.scalars(
                    select(CekSenetEvrak).where(
                        CekSenetEvrak.aktif.is_(True),
                        CekSenetEvrak.duzenleme_tarihi <= kesim_tarihi,
                    )
                ).all():
                    if (c.durum or "").upper() in {x.upper() for x in kapali}:
                        continue
                    kalan = Decimal(str(c.kalan_tutar or c.tl_tutari or 0))
                    if kalan == 0:
                        continue
                    cek_acik += 1
                    cek_tutar += kalan
            except Exception:
                pass

        return {
            "kesim_tarihi": kesim_tarihi,
            "hesap_sayisi": len(satirlar),
            "pb_ozet": {k: str(v) for k, v in pb_ozet.items()},
            "tl_tasima_toplam": str(tl_toplam),
            "negatif_hesap": negatif,
            "pos_bekleyen": pos_bekleyen,
            "pos_bekleyen_net": str(pos_net),
            "cek_senet_acik": cek_acik,
            "cek_senet_tutar": str(cek_tutar),
            "satirlar": satirlar,
            "not": "Para birimleri pb_ozet içinde ayrı; tek sayıda toplanmaz.",
        }

    @classmethod
    def kesim_gm(cls, kesim_tarihi: date) -> dict[str, Any]:
        """Genel muhasebe kesim özeti — paket kapalıysa aktif=False."""
        from decimal import Decimal

        from sqlalchemy import func, inspect as sa_inspect

        bag = _db.engine
        if bag is None or not sa_inspect(bag).has_table("muhasebe_fisleri"):
            return {
                "aktif": False,
                "denk": True,
                "mesaj": "Genel muhasebe tablosu yok / paket kapalı; ön muhasebe devri yeterli.",
            }
        try:
            from database.models.genel_muhasebe import MuhasebeFisi, MuhasebeFisiSatiri
        except Exception:
            return {"aktif": False, "denk": True, "mesaj": "GM modelleri yüklenemedi."}

        with get_session() as session:
            fis_say = session.scalar(
                select(func.count()).select_from(MuhasebeFisi).where(
                    MuhasebeFisi.fis_tarihi <= kesim_tarihi
                )
            ) or 0
            if fis_say == 0:
                return {
                    "aktif": False,
                    "denk": True,
                    "fis_sayisi": 0,
                    "mesaj": "Kesime kadar GM fişi yok — açılış fişi üretilmez.",
                }
            borc = session.scalar(
                select(func.coalesce(func.sum(MuhasebeFisiSatiri.borc), 0))
                .select_from(MuhasebeFisiSatiri)
                .join(MuhasebeFisi, MuhasebeFisiSatiri.fis_id == MuhasebeFisi.id)
                .where(MuhasebeFisi.fis_tarihi <= kesim_tarihi)
            )
            alacak = session.scalar(
                select(func.coalesce(func.sum(MuhasebeFisiSatiri.alacak), 0))
                .select_from(MuhasebeFisiSatiri)
                .join(MuhasebeFisi, MuhasebeFisiSatiri.fis_id == MuhasebeFisi.id)
                .where(MuhasebeFisi.fis_tarihi <= kesim_tarihi)
            )
            b = Decimal(str(borc or 0))
            a = Decimal(str(alacak or 0))
            fark = b - a
            return {
                "aktif": True,
                "denk": abs(fark) <= Decimal("0.05"),
                "fis_sayisi": int(fis_say),
                "borc_toplam": str(b),
                "alacak_toplam": str(a),
                "fark": str(fark),
                "mesaj": (
                    "Mizan denk."
                    if abs(fark) <= Decimal("0.05")
                    else "Mizan denk değil — otomatik denkleştirme yapılmaz."
                ),
            }

    @classmethod
    def onizleme_hesapla(
        cls,
        is_id: int,
        *,
        firma_id: int | None = None,
    ) -> dict[str, Any]:
        """Kapsama göre kesim görüntüsü; işe bağlar; veri yazmaz."""
        from decimal import Decimal

        cls.ensure_schema()
        fid = _firma_id(firma_id)
        is_ = cls.is_getir(is_id, firma_id=fid)
        if is_ is None:
            raise ValueError("Devir işi bulunamadı.")

        kesim = is_["kesim_tarihi"]
        if not isinstance(kesim, date):
            kesim = date.fromisoformat(str(kesim)[:10])

        ozet: dict[str, Any] = {
            "hesaplama": datetime.now().isoformat(timespec="seconds"),
            "kesim_tarihi": str(kesim),
            "acilis_tarihi": str(is_["acilis_tarihi"]),
            "kapsam": is_["kapsam"],
            "moduller": {},
        }
        uyari = 0
        if MODUL_CARI in is_["kapsam"]:
            cari = cls.kesim_cari(kesim)
            ozet["moduller"]["CARI"] = {
                "kalem_sayisi": cari["kalem_sayisi"],
                "negatif_kalem": cari["negatif_kalem"],
                "toplam_borc_yonu": cari["toplam_borc_yonu"],
                "toplam_alacak_yonu": cari["toplam_alacak_yonu"],
            }
            uyari += int(cari["negatif_kalem"] or 0)
            # Ayrıntı örnek (ilk 50) — tam listeyi iş JSON'unda şişirmemek için
            ozet["moduller"]["CARI"]["ornek"] = cari["satirlar"][:50]
        if MODUL_STOK in is_["kapsam"]:
            stok = cls.kesim_stok(kesim)
            ozet["moduller"]["STOK"] = {
                k: stok[k]
                for k in (
                    "satir_sayisi",
                    "deger_bilinen",
                    "negatif_satir",
                    "sifir_maliyet_miktar",
                    "not",
                )
            }
            uyari += int(stok["negatif_satir"] or 0)
            try:
                if Decimal(str(stok["sifir_maliyet_miktar"] or 0)) > 0:
                    uyari += 1
            except Exception:
                pass
            ozet["moduller"]["STOK"]["ornek_satirlar"] = stok["ornek_satirlar"][:50]
        if MODUL_FINANS in is_["kapsam"]:
            fin = cls.kesim_finans(kesim)
            ozet["moduller"]["FINANS"] = {
                "hesap_sayisi": fin["hesap_sayisi"],
                "pb_ozet": fin["pb_ozet"],
                "tl_tasima_toplam": fin["tl_tasima_toplam"],
                "negatif_hesap": fin["negatif_hesap"],
                "pos_bekleyen": fin["pos_bekleyen"],
                "cek_senet_acik": fin["cek_senet_acik"],
            }
            uyari += int(fin["negatif_hesap"] or 0)
            ozet["moduller"]["FINANS"]["ornek"] = fin["satirlar"][:40]
        if MODUL_ACIK_ISLEM in is_["kapsam"]:
            ozet["moduller"]["ACIK_ISLEM"] = {
                "durum": "AYNI_DB",
                "mesaj": (
                    "Açık sipariş/irsaliye kimlikleri aynı DB'de yaşar; "
                    "devir ikinci sevkiyat üretmez (eşleştirme Aşama 4+)."
                ),
            }
        if MODUL_GM in is_["kapsam"]:
            gm = cls.kesim_gm(kesim)
            ozet["moduller"][MODUL_GM] = gm
            if gm.get("aktif") and not gm.get("denk"):
                uyari += 1

        with get_session() as session:
            row = session.get(DevirIs, int(is_id))
            if row is None or int(row.firma_id) != fid:
                raise ValueError("Devir işi bulunamadı.")
            row.onizleme_ozet_json = _json_dumps(ozet)
            row.onizleme_gecerli = True
            row.uyari_sayisi = uyari
            row.durum = DURUM_ONIZLEME_HAZIR
            session.flush()
            sonuc_is = cls._is_dict(row)

        cls._denetim_yaz(is_id, fid, "ONIZLEME", {"uyari_sayisi": uyari})
        return {"is": sonuc_is, "ozet": ozet}

    # ── Aşama 4: uygulama (aynı DB — mükerrer belge yok) ───────

    @classmethod
    def uygula(
        cls,
        is_id: int,
        *,
        firma_id: int | None = None,
        yedek_zorunlu: bool = True,
    ) -> dict[str, Any]:
        """Ön izlemeyi işler: eşleştirme + (kesinse) kaynak dönem kilidi.

        Aynı firma DB modelinde açık cari/stok zaten yaşar; ikinci satış/alış
        veya stok hareketi üretilmez. Benzersizlik anahtarıyla tekrar çalıştırma
        güvenlidir.
        """
        from database.models.devir import (
            DURUM_BASARISIZ,
            DURUM_DEVREDILIYOR,
            DURUM_TAMAMLANDI,
            DURUM_UYARILAR_VAR,
            MODUL_CARI,
            MODUL_FINANS,
            MODUL_GM,
            MODUL_STOK,
            TUR_KESIN,
        )
        from database.donem_service import DonemService

        cls.ensure_schema()
        cls._yetki_devir()
        fid = _firma_id(firma_id)
        is_ = cls.is_getir(is_id, firma_id=fid)
        if is_ is None:
            raise ValueError("Devir işi bulunamadı.")
        if not is_.get("onizleme_gecerli"):
            raise ValueError("Geçerli ön izleme yok; önce Ön İzle çalıştırın.")
        if yedek_zorunlu and not is_.get("yedek_dogrulandi"):
            raise ValueError("Uygulama öncesi doğrulanmış yedek gerekli.")
        if is_["durum"] in (DURUM_DEVREDILIYOR,):
            raise ValueError("İş zaten devrediliyor.")
        if is_["durum"] in (DURUM_TAMAMLANDI, DURUM_UYARILAR_VAR):
            return {"is": is_, "yeni_eslesme": 0, "mesaj": "İş zaten tamamlanmış."}

        cls.durum_guncelle(is_id, DURUM_DEVREDILIYOR, firma_id=fid)
        yeni = 0
        try:
            kid = int(is_["kaynak_donem_id"])
            hid = int(is_["hedef_donem_id"])
            kesim = is_["kesim_tarihi"]
            if not isinstance(kesim, date):
                kesim = date.fromisoformat(str(kesim)[:10])

            if MODUL_CARI in is_["kapsam"]:
                cari = cls.kesim_cari(kesim)
                toplam = max(len(cari["satirlar"]), 1)
                for i, sat in enumerate(cari["satirlar"], start=1):
                    anahtar = (
                        f"{fid}:{kid}:{hid}:{is_id}:CARI:{sat['hareket_id']}:{sat['para_birimi']}"
                    )
                    r = cls.eslesme_kaydet(
                        is_id,
                        modul=MODUL_CARI,
                        kaynak_tip="cari_satis_hareketi",
                        kaynak_id=str(sat["hareket_id"]),
                        benzersizlik_anahtar=anahtar,
                        hedef_tip="ayni_kayit",
                        hedef_id=str(sat["hareket_id"]),
                        kaynak_anahtar=sat.get("belge_no"),
                        tutar=sat.get("kalan"),
                        para_birimi=sat.get("para_birimi"),
                        detay={
                            "vade_tarihi": str(sat.get("vade_tarihi") or ""),
                            "yon": sat.get("yon"),
                        },
                        firma_id=fid,
                    )
                    if r.get("yeni"):
                        yeni += 1
                    if i % 200 == 0 or i == toplam:
                        with get_session() as session:
                            row = session.get(DevirIs, int(is_id))
                            if row:
                                row.ilerleme_modul = MODUL_CARI
                                row.ilerleme_islenen = i
                                row.ilerleme_toplam = toplam
                                row.kontrol_noktasi = f"CARI:{i}"

            if MODUL_STOK in is_["kapsam"]:
                from database.stok_service import StokService

                with get_session() as session:
                    envanter = StokService.fifo_envanter_degerleri(session, kesim)
                items = [
                    (sid, did, kay)
                    for (sid, did), kay in envanter.items()
                    if float(kay.get("miktar") or 0) != 0 or float(kay.get("deger") or 0) != 0
                ]
                toplam = max(len(items), 1)
                for i, (sid, did, kay) in enumerate(items, start=1):
                    anahtar = f"{fid}:{kid}:{hid}:{is_id}:STOK:{sid}:{did}"
                    r = cls.eslesme_kaydet(
                        is_id,
                        modul=MODUL_STOK,
                        kaynak_tip="stok_depo",
                        kaynak_id=f"{sid}:{did}",
                        benzersizlik_anahtar=anahtar,
                        hedef_tip="ayni_envanter",
                        hedef_id=f"{sid}:{did}",
                        tutar=kay.get("deger"),
                        miktar=kay.get("miktar"),
                        para_birimi="TRY",
                        firma_id=fid,
                    )
                    if r.get("yeni"):
                        yeni += 1
                    if i % 400 == 0 or i == toplam:
                        with get_session() as session:
                            row = session.get(DevirIs, int(is_id))
                            if row:
                                row.ilerleme_modul = MODUL_STOK
                                row.ilerleme_islenen = i
                                row.ilerleme_toplam = toplam
                                row.kontrol_noktasi = f"STOK:{i}"

            if MODUL_FINANS in is_["kapsam"]:
                fin = cls.kesim_finans(kesim)
                toplam = max(len(fin["satirlar"]), 1)
                for i, sat in enumerate(fin["satirlar"], start=1):
                    anahtar = (
                        f"{fid}:{kid}:{hid}:{is_id}:FINANS:{sat['hesap_id']}:{sat['para_birimi']}"
                    )
                    r = cls.eslesme_kaydet(
                        is_id,
                        modul=MODUL_FINANS,
                        kaynak_tip="finans_hesap",
                        kaynak_id=str(sat["hesap_id"]),
                        benzersizlik_anahtar=anahtar,
                        hedef_tip="ayni_hesap",
                        hedef_id=str(sat["hesap_id"]),
                        kaynak_anahtar=sat.get("hesap_adi"),
                        tutar=sat.get("bakiye"),
                        para_birimi=sat.get("para_birimi"),
                        detay={"tl_tasima": sat.get("tl_tasima"), "tur": sat.get("hesap_turu")},
                        firma_id=fid,
                    )
                    if r.get("yeni"):
                        yeni += 1
                    if i % 100 == 0 or i == toplam:
                        with get_session() as session:
                            row = session.get(DevirIs, int(is_id))
                            if row:
                                row.ilerleme_modul = MODUL_FINANS
                                row.ilerleme_islenen = i
                                row.ilerleme_toplam = toplam
                                row.kontrol_noktasi = f"FINANS:{i}"

            if MODUL_GM in is_["kapsam"]:
                gm = cls.kesim_gm(kesim)
                if gm.get("aktif"):
                    anahtar = f"{fid}:{kid}:{hid}:{is_id}:GM:MIZAN:{kesim}"
                    r = cls.eslesme_kaydet(
                        is_id,
                        modul=MODUL_GM,
                        kaynak_tip="gm_mizan",
                        kaynak_id=str(kesim),
                        benzersizlik_anahtar=anahtar,
                        hedef_tip="rapor",
                        hedef_id="mizan",
                        tutar=gm.get("fark"),
                        para_birimi="TRY",
                        detay=gm,
                        firma_id=fid,
                    )
                    if r.get("yeni"):
                        yeni += 1
                # Aynı-DB: ikinci toplu açılış fişi üretilmez

            if is_["devir_turu"] == TUR_KESIN:
                DonemService.kapat_ac(kid, True)

            uyari = int(is_.get("uyari_sayisi") or 0)
            bitis = DURUM_UYARILAR_VAR if uyari else DURUM_TAMAMLANDI
            sonuc = cls.durum_guncelle(is_id, bitis, firma_id=fid)
            try:
                kars = cls.karsilastirma_raporu(is_id, firma_id=fid)
            except Exception:
                kars = None
            cls._denetim_yaz(
                is_id,
                fid,
                "UYGULA",
                {"yeni_eslesme": yeni, "devir_turu": is_["devir_turu"], "karsilastirma_ok": bool(kars)},
            )
            return {
                "is": sonuc,
                "yeni_eslesme": yeni,
                "karsilastirma": kars,
                "mesaj": (
                    "Aynı-DB devir: cari/stok/finans eşleştirildi; "
                    "ikinci satış, stok veya finans hareketi yazılmadı."
                ),
            }
        except Exception as exc:
            cls.durum_guncelle(
                is_id, DURUM_BASARISIZ, firma_id=fid, hata_mesaji=str(exc)[:500]
            )
            raise

    @classmethod
    def karsilastirma_raporu(
        cls,
        is_id: int,
        *,
        firma_id: int | None = None,
    ) -> dict[str, Any]:
        """Kaynak kesim vs eşleştirme/açılış tutarları — yeni belge üretmez."""
        from decimal import Decimal

        from sqlalchemy import func

        cls.ensure_schema()
        fid = _firma_id(firma_id)
        is_ = cls.is_getir(is_id, firma_id=fid)
        if is_ is None:
            raise ValueError("Devir işi bulunamadı.")
        kesim = is_["kesim_tarihi"]
        if not isinstance(kesim, date):
            kesim = date.fromisoformat(str(kesim)[:10])

        satırlar: list[dict[str, Any]] = []
        TOL = Decimal("0.05")

        def _fark_satir(modul: str, kaynak, hedef, aciklama: str = ""):
            k = Decimal(str(kaynak or 0))
            h = Decimal(str(hedef or 0))
            f = h - k
            satırlar.append(
                {
                    "modul": modul,
                    "kaynak_kapanis": str(k),
                    "hedef_acilis": str(h),
                    "fark": str(f),
                    "ok": abs(f) <= TOL,
                    "aciklama": aciklama,
                }
            )

        with get_session() as session:
            def _eslesme_toplam(modul: str) -> Decimal:
                v = session.scalar(
                    select(func.coalesce(func.sum(DevirEslesme.tutar), 0)).where(
                        DevirEslesme.is_id == int(is_id),
                        DevirEslesme.modul == modul,
                    )
                )
                return Decimal(str(v or 0))

            def _eslesme_adet(modul: str) -> int:
                return int(
                    session.scalar(
                        select(func.count()).select_from(DevirEslesme).where(
                            DevirEslesme.is_id == int(is_id),
                            DevirEslesme.modul == modul,
                        )
                    )
                    or 0
                )

            if MODUL_CARI in is_["kapsam"]:
                cari = cls.kesim_cari(kesim)
                kaynak = Decimal(str(cari["toplam_borc_yonu"])) + Decimal(
                    str(cari["toplam_alacak_yonu"])
                )
                hedef = _eslesme_toplam(MODUL_CARI)
                _fark_satir(
                    MODUL_CARI,
                    kaynak,
                    hedef,
                    f"kalem {cari['kalem_sayisi']} / eşleşme {_eslesme_adet(MODUL_CARI)}",
                )
            if MODUL_STOK in is_["kapsam"]:
                stok = cls.kesim_stok(kesim)
                _fark_satir(
                    MODUL_STOK,
                    stok["deger_bilinen"],
                    _eslesme_toplam(MODUL_STOK),
                    f"satır {stok['satir_sayisi']} / eşleşme {_eslesme_adet(MODUL_STOK)}",
                )
            if MODUL_FINANS in is_["kapsam"]:
                fin = cls.kesim_finans(kesim)
                # PB karışmasın diye eşleşme adedi + TL taşıma
                _fark_satir(
                    MODUL_FINANS,
                    fin["hesap_sayisi"],
                    _eslesme_adet(MODUL_FINANS),
                    f"hesap sayısı; TL taşıma kesim={fin['tl_tasima_toplam']}",
                )

        ok = all(s["ok"] for s in satırlar) if satırlar else True
        rapor = {
            "is_no": is_["is_no"],
            "kesim_tarihi": str(kesim),
            "satirlar": satırlar,
            "ok": ok,
            "mesaj": "Kaynak kapanış ile eşleştirme uyumlu." if ok else "Fark var — ayrıntıya bakın.",
        }
        with get_session() as session:
            row = session.get(DevirIs, int(is_id))
            if row and int(row.firma_id) == fid:
                ozet = _json_loads(row.onizleme_ozet_json, {}) or {}
                ozet["karsilastirma"] = rapor
                row.onizleme_ozet_json = _json_dumps(ozet)
        cls._denetim_yaz(is_id, fid, "KARSILASTIRMA", {"ok": ok})
        return rapor

    @classmethod
    def yedek_geri_yukle_dogrula(
        cls,
        is_id: int,
        *,
        firma_id: int | None = None,
    ) -> dict[str, Any]:
        """İş yedeğini geçici kopyada açar; canlı DB'ye dokunmaz."""
        from database.servis_sistem.backup_service import BackupService

        cls.ensure_schema()
        fid = _firma_id(firma_id)
        is_ = cls.is_getir(is_id, firma_id=fid)
        if is_ is None:
            raise ValueError("Devir işi bulunamadı.")
        yol = is_.get("yedek_yolu")
        if not yol:
            raise ValueError("İşe bağlı yedek yok; önce yedek alın.")
        sonuc = BackupService.geri_yukle_dogrula(yol)
        cls._denetim_yaz(is_id, fid, "YEDEK_GERI_YUKLE_TEST", sonuc)
        return sonuc

    @classmethod
    def on_devir_guncelleme_gerekli_mi(
        cls,
        is_id: int,
        *,
        firma_id: int | None = None,
    ) -> dict[str, Any]:
        """Ön devir sonrası kaynak kesim değişti mi? (sessiz güncelleme yok)."""
        from decimal import Decimal

        cls.ensure_schema()
        fid = _firma_id(firma_id)
        is_ = cls.is_getir(is_id, firma_id=fid)
        if is_ is None:
            raise ValueError("Devir işi bulunamadı.")
        if is_["devir_turu"] != TUR_ON:
            return {"gerekli": False, "neden": "Yalnız ön devirde kaynak değişimi izlenir."}
        ozet = is_.get("onizleme_ozet") or {}
        eski = (ozet.get("moduller") or {}).get("CARI") or {}
        kesim = is_["kesim_tarihi"]
        if not isinstance(kesim, date):
            kesim = date.fromisoformat(str(kesim)[:10])
        yeni = cls.kesim_cari(kesim)
        farklar = []
        for alan in ("kalem_sayisi", "toplam_borc_yonu", "toplam_alacak_yonu"):
            e = str(eski.get(alan) or "")
            n = str(yeni.get(alan) or "")
            if e and e != n:
                farklar.append({"alan": alan, "eski": e, "yeni": n})
        return {
            "gerekli": bool(farklar),
            "farklar": farklar,
            "mesaj": (
                "Güncelleme Gerekli — kaynak kesim değişti; otomatik yazılmaz."
                if farklar
                else "Kaynak kesim ile kayıtlı ön izleme uyumlu."
            ),
        }

    @classmethod
    def geri_al(
        cls,
        is_id: int,
        *,
        firma_id: int | None = None,
        gerekce: str = "",
    ) -> dict[str, Any]:
        """Yalnız bu işin eşleştirmelerini geri alır; kaynak yıl / kullanıcı kayıtları silinmez.

        Aynı-DB modelinde hedefte üretilmiş ikinci belge yoktur; bağımlı mali hareket
        üretilmediği için kör silme riski yoktur. Kesin devirde kaynak kilidi açılmaz
        (ayrı yetkili düzeltme gerekir).
        """
        from database.models.devir import DURUM_GERI_ALINDI
        from sqlalchemy import delete

        cls.ensure_schema()
        cls._yetki_devir()
        fid = _firma_id(firma_id)
        is_ = cls.is_getir(is_id, firma_id=fid)
        if is_ is None:
            raise ValueError("Devir işi bulunamadı.")
        if is_["durum"] == DURUM_GERI_ALINDI:
            return {"is": is_, "silinen_eslesme": 0, "mesaj": "Zaten geri alınmış."}
        if is_["durum"] not in ("TAMAMLANDI", "UYARILAR_VAR", "BASARISIZ"):
            raise ValueError("Yalnız tamamlanmış / başarısız iş geri alınabilir.")

        with get_session() as session:
            silinen = session.execute(
                delete(DevirEslesme).where(
                    DevirEslesme.is_id == int(is_id),
                    DevirEslesme.firma_id == fid,
                )
            ).rowcount
            row = session.get(DevirIs, int(is_id))
            if row:
                row.durum = DURUM_GERI_ALINDI
                row.bitis = datetime.now()
                row.hata_mesaji = (gerekce or "Kullanıcı geri alma")[:500]
            session.flush()
            sonuc = cls._is_dict(row) if row else is_
        cls._denetim_yaz(
            is_id,
            fid,
            "GERI_AL",
            {"silinen_eslesme": int(silinen or 0), "gerekce": gerekce},
        )
        return {
            "is": sonuc,
            "silinen_eslesme": int(silinen or 0),
            "mesaj": "Eşleştirmeler geri alındı; cari/stok/finans hareketleri silinmedi.",
        }

    # ── Eşleştirme (Aşama 2 altyapı) ───────────────────────────

    @classmethod
    def eslesme_kaydet(
        cls,
        is_id: int,
        *,
        modul: str,
        kaynak_tip: str,
        kaynak_id: str,
        benzersizlik_anahtar: str,
        hedef_tip: str | None = None,
        hedef_id: str | None = None,
        kaynak_anahtar: str | None = None,
        tutar: Any = None,
        miktar: Any = None,
        para_birimi: str | None = None,
        detay: dict | None = None,
        firma_id: int | None = None,
    ) -> dict[str, Any]:
        """Idempotent upsert — aynı benzersizlik anahtarı ikinci kez yazılmaz."""
        cls.ensure_schema()
        fid = _firma_id(firma_id)
        with get_session() as session:
            is_ = session.get(DevirIs, int(is_id))
            if is_ is None or int(is_.firma_id) != fid:
                raise ValueError("Devir işi bulunamadı.")
            mevcut = session.scalar(
                select(DevirEslesme).where(
                    DevirEslesme.firma_id == fid,
                    DevirEslesme.benzersizlik_anahtar == benzersizlik_anahtar,
                )
            )
            if mevcut is not None:
                return {
                    "id": mevcut.id,
                    "yeni": False,
                    "hedef_id": mevcut.hedef_id,
                    "benzersizlik_anahtar": mevcut.benzersizlik_anahtar,
                }
            row = DevirEslesme(
                is_id=int(is_id),
                firma_id=fid,
                modul=modul,
                kaynak_tip=kaynak_tip,
                kaynak_id=str(kaynak_id),
                kaynak_anahtar=kaynak_anahtar,
                hedef_tip=hedef_tip,
                hedef_id=str(hedef_id) if hedef_id is not None else None,
                benzersizlik_anahtar=benzersizlik_anahtar,
                tutar=tutar,
                miktar=miktar,
                para_birimi=(para_birimi or None),
                detay_json=_json_dumps(detay) if detay else None,
            )
            session.add(row)
            session.flush()
            return {
                "id": row.id,
                "yeni": True,
                "hedef_id": row.hedef_id,
                "benzersizlik_anahtar": row.benzersizlik_anahtar,
            }

    # ── iç yardımcılar ────────────────────────────────────────

    @classmethod
    def _sonraki_is_no(cls, session, firma_id: int, yil: int) -> str:
        onek = f"DEV-{int(yil)}-"
        max_n = 0
        for kod in session.scalars(
            select(DevirIs.is_no).where(
                DevirIs.firma_id == firma_id,
                DevirIs.is_no.like(f"{onek}%"),
            )
        ).all():
            m = _IS_NO_RE.match((kod or "").strip())
            if m and int(m.group(1)) == int(yil):
                max_n = max(max_n, int(m.group(2)))
        return f"{onek}{max_n + 1:04d}"

    @classmethod
    def _is_dict(cls, is_: DevirIs) -> dict[str, Any]:
        return {
            "id": is_.id,
            "is_no": is_.is_no,
            "firma_id": is_.firma_id,
            "kaynak_donem_id": is_.kaynak_donem_id,
            "hedef_donem_id": is_.hedef_donem_id,
            "kesim_tarihi": is_.kesim_tarihi,
            "acilis_tarihi": is_.acilis_tarihi,
            "devir_turu": is_.devir_turu,
            "durum": is_.durum,
            "durum_etiket": DURUM_ETIKET.get(is_.durum, is_.durum),
            "kapsam": _json_loads(is_.kapsam_json, []),
            "ayarlar": _json_loads(is_.ayarlar_json, {}),
            "ayarlar_surum": is_.ayarlar_surum,
            "schema_surum": is_.schema_surum,
            "onizleme_gecerli": bool(is_.onizleme_gecerli),
            "onizleme_ozet": _json_loads(is_.onizleme_ozet_json, None),
            "yedek_yolu": is_.yedek_yolu,
            "yedek_dogrulandi": bool(is_.yedek_dogrulandi),
            "ilerleme_modul": is_.ilerleme_modul,
            "ilerleme_islenen": is_.ilerleme_islenen,
            "ilerleme_toplam": is_.ilerleme_toplam,
            "kontrol_noktasi": is_.kontrol_noktasi,
            "hata_mesaji": is_.hata_mesaji,
            "uyari_sayisi": is_.uyari_sayisi,
            "hata_sayisi": is_.hata_sayisi,
            "olusturma": is_.olusturma,
            "olusturan": is_.olusturan,
            "baslama": is_.baslama,
            "bitis": is_.bitis,
        }

    @classmethod
    def _denetim_yaz(
        cls,
        is_id: int | None,
        firma_id: int,
        olay: str,
        detay: dict | None = None,
    ) -> None:
        try:
            with get_session() as session:
                session.add(
                    DevirDenetim(
                        is_id=is_id,
                        firma_id=firma_id,
                        olay=olay,
                        detay_json=_json_dumps(detay) if detay else None,
                        olusturma=datetime.now(),
                        kullanici=_kullanici(),
                    )
                )
        except Exception:
            pass

    @classmethod
    def _yetki_devir(cls) -> None:
        if oturum.role_kod == "YONETICI":
            return
        if oturum.has_permission("donem_degistirme") or oturum.has_permission("sistem_ayarlari"):
            return
        raise PermissionError("Yıllık devir yetkiniz yok.")

    @classmethod
    def _yetki_ayar(cls) -> None:
        if oturum.role_kod == "YONETICI":
            return
        if oturum.has_permission("sistem_ayarlari"):
            return
        raise PermissionError("Devir ayarları yetkiniz yok.")
