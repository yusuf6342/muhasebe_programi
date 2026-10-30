"""Taslak yönetimi, doğrulama ve kesin kayıt."""

from __future__ import annotations

import json
from datetime import date, datetime, timedelta
from decimal import Decimal, ROUND_HALF_UP
from typing import Any

from sqlalchemy import select

from database.access import yazma_zorunlu
from database.alis_faturasi_service import AlisFaturasiService
from database.cari_service import CariService
from database.database import get_session
from database.satis_faturasi_service import SatisFaturasiService
from database.session_manager import oturum
from fatura_belge_aktarim.json_codec import dumps_accounting, to_decimal
from fatura_belge_aktarim.matching import PartyMatchingService, ProductMatchingService
from fatura_belge_aktarim.models import (
    InvoiceImportAudit,
    InvoiceImportDraft,
    InvoiceImportFile,
    InvoiceImportLine,
    PartyMatchRule,
    ProductMatchRule,
)
from fatura_belge_aktarim.normalize import tarih_tr

MAL_KABUL_DURUMLARI = ("mal_geldi", "mal_bekleniyor", "irsaliyeden")


def _q2(v: Decimal) -> Decimal:
    return v.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


class InvoiceDraftService:
    _schema_hazir = False

    @classmethod
    def ensure_schema(cls, eng=None) -> None:
        """create_all + eski DB için mal_kabul_durumu kolonu."""
        if cls._schema_hazir and eng is None:
            return
        from database.database import Base, engine as default_engine
        from sqlalchemy import text

        bag = eng if eng is not None else default_engine
        if bag is None:
            return
        Base.metadata.create_all(
            bind=bag,
            tables=[
                InvoiceImportDraft.__table__,
                InvoiceImportFile.__table__,
                InvoiceImportLine.__table__,
                InvoiceImportAudit.__table__,
                PartyMatchRule.__table__,
                ProductMatchRule.__table__,
            ],
        )
        alterler = (
            'ALTER TABLE "invoice_import_drafts" ADD COLUMN "mal_kabul_durumu" VARCHAR(40)',
            'ALTER TABLE "invoice_import_drafts" ADD COLUMN "linked_irsaliye_id" INTEGER',
            'ALTER TABLE "invoice_import_lines" ADD COLUMN "teslim_miktar" NUMERIC(18, 4)',
            'ALTER TABLE "invoice_import_lines" ADD COLUMN "irsaliye_satiri_id" INTEGER',
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
        if eng is None:
            cls._schema_hazir = True

    @staticmethod
    def listele(*, yon: str | None = None, durum: str | None = None, limit: int = 100) -> list[InvoiceImportDraft]:
        InvoiceDraftService.ensure_schema()
        with get_session() as session:
            q = select(InvoiceImportDraft).where(InvoiceImportDraft.is_deleted.is_(False))
            if yon:
                q = q.where(InvoiceImportDraft.yon == yon.upper())
            if durum:
                q = q.where(InvoiceImportDraft.durum == durum)
            q = q.order_by(InvoiceImportDraft.id.desc()).limit(limit)
            return list(session.scalars(q))

    @staticmethod
    def mal_kabul_ata(draft_id: int, durum: str) -> None:
        drm = (durum or "").strip().lower()
        if drm not in MAL_KABUL_DURUMLARI:
            raise ValueError(
                "Mal kabul durumu Mal Geldi, Mal Bekleniyor veya İrsaliyeden Alındı olmalı."
            )
        with get_session() as session:
            d = session.get(InvoiceImportDraft, draft_id)
            if not d or d.is_deleted:
                raise ValueError("Taslak bulunamadı.")
            if d.durum == "fatura_olusturuldu":
                raise ValueError("Kesinleşmiş taslakta mal kabul değiştirilemez.")
            d.mal_kabul_durumu = drm
            d.updated_at = datetime.now()
            session.add(
                InvoiceImportAudit(
                    draft_id=draft_id,
                    kullanici=oturum.kullanici_adi,
                    aksiyon="mal_kabul",
                    sonraki_json=dumps_accounting({"mal_kabul_durumu": drm}),
                )
            )
            session.flush()

    @staticmethod
    def satir_teslim_ata(line_id: int, teslim_miktar: Decimal | None) -> None:
        """Kısmi mal kabul: satır teslim miktarı (None = tam belge miktarı)."""
        InvoiceDraftService.ensure_schema()
        with get_session() as session:
            line = session.get(InvoiceImportLine, line_id)
            if not line:
                raise ValueError("Satır bulunamadı.")
            belge = line.miktar or Decimal("0")
            if teslim_miktar is not None:
                t = Decimal(str(teslim_miktar))
                if t < 0:
                    raise ValueError("Teslim miktarı negatif olamaz.")
                if t > belge:
                    raise ValueError(
                        f"Teslim miktarı ({t}) belge miktarını ({belge}) aşamaz."
                    )
                line.teslim_miktar = t
            else:
                line.teslim_miktar = None
            session.flush()

    @staticmethod
    def irsaliye_bagla(draft_id: int, irsaliye_id: int | None) -> dict[str, Any]:
        """ALIS taslağına açık alış irsaliyesi bağla; satırları stok koduyla eşleştir."""
        InvoiceDraftService.ensure_schema()
        data = InvoiceDraftService.getir(draft_id)
        draft: InvoiceImportDraft = data["draft"]
        if draft.yon != "ALIS":
            raise ValueError("İrsaliye bağlantısı yalnız alış taslaklarında.")
        if draft.durum == "fatura_olusturuldu":
            raise ValueError("Kesinleşmiş taslakta irsaliye değiştirilemez.")

        eslesen = 0
        with get_session() as session:
            d = session.get(InvoiceImportDraft, draft_id)
            if not d:
                raise ValueError("Taslak bulunamadı.")
            d.linked_irsaliye_id = int(irsaliye_id) if irsaliye_id else None
            d.updated_at = datetime.now()
            satirlar = list(
                session.scalars(
                    select(InvoiceImportLine).where(InvoiceImportLine.draft_id == draft_id)
                )
            )
            for line in satirlar:
                line.irsaliye_satiri_id = None

            if irsaliye_id:
                from database.models.alis_irsaliyesi import AlisIrsaliyesi, AlisIrsaliyesiSatiri

                irs = session.get(AlisIrsaliyesi, int(irsaliye_id))
                if not irs:
                    raise ValueError("İrsaliye bulunamadı.")
                if draft.cari_id and irs.cari_id and int(irs.cari_id) != int(draft.cari_id):
                    raise ValueError("İrsaliye carisi taslak carisiyle uyuşmuyor.")
                irs_satirlar = list(
                    session.scalars(
                        select(AlisIrsaliyesiSatiri).where(
                            AlisIrsaliyesiSatiri.irsaliye_id == int(irsaliye_id)
                        )
                    )
                )
                # stok_kodu → kalan miktarı olan ilk satır
                havuz: dict[str, list] = {}
                for is_ in irs_satirlar:
                    kod = (is_.urun_kodu or "").strip()
                    if not kod:
                        continue
                    kalan = (is_.miktar or Decimal("0")) - (is_.faturalanan_miktar or Decimal("0"))
                    if kalan <= 0:
                        continue
                    havuz.setdefault(kod, []).append(is_)
                for line in satirlar:
                    if line.match_status == "haric":
                        continue
                    kod = (line.stok_kodu or "").strip()
                    if not kod or kod not in havuz or not havuz[kod]:
                        continue
                    is_ = havuz[kod].pop(0)
                    line.irsaliye_satiri_id = int(is_.id)
                    eslesen += 1

            session.add(
                InvoiceImportAudit(
                    draft_id=draft_id,
                    kullanici=oturum.kullanici_adi,
                    aksiyon="irsaliye_bagla",
                    sonraki_json=dumps_accounting(
                        {"irsaliye_id": irsaliye_id, "eslesen_satir": eslesen}
                    ),
                )
            )
            session.flush()
        return {"irsaliye_id": irsaliye_id, "eslesen_satir": eslesen}

    @staticmethod
    def acik_irsaliyeler_cari(cari_id: int | None) -> list[dict[str, Any]]:
        """Cariye ait faturalanabilir alış irsaliyeleri (önizleme listesi)."""
        from database.alis_faturasi_service import AlisFaturasiService

        out = []
        for irs in AlisFaturasiService.acik_irsaliyeler():
            if cari_id and getattr(irs, "cari_id", None) and int(irs.cari_id) != int(cari_id):
                continue
            kalan_satir = 0
            for s in getattr(irs, "satirlar", None) or []:
                kalan = (s.miktar or Decimal("0")) - (s.faturalanan_miktar or Decimal("0"))
                if kalan > 0:
                    kalan_satir += 1
            if kalan_satir <= 0:
                continue
            out.append(
                {
                    "id": int(irs.id),
                    "irsaliye_no": irs.irsaliye_no,
                    "tarih": str(getattr(irs, "irsaliye_tarihi", "") or ""),
                    "cari_id": getattr(irs, "cari_id", None),
                    "durum": irs.durum,
                    "kalan_satir": kalan_satir,
                }
            )
        return out

    @staticmethod
    def getir(draft_id: int) -> dict[str, Any]:
        InvoiceDraftService.ensure_schema()
        with get_session() as session:
            draft = session.get(InvoiceImportDraft, draft_id)
            if not draft or draft.is_deleted:
                raise ValueError("Taslak bulunamadı.")
            satirlar = list(
                session.scalars(
                    select(InvoiceImportLine)
                    .where(InvoiceImportLine.draft_id == draft_id)
                    .order_by(InvoiceImportLine.sira)
                )
            )
            return {"draft": draft, "satirlar": satirlar}

    @staticmethod
    def otomatik_eslestir(draft_id: int) -> dict[str, Any]:
        data = InvoiceDraftService.getir(draft_id)
        draft: InvoiceImportDraft = data["draft"]
        cari_turu = "Tedarikçi" if draft.yon == "ALIS" else "Müşteri"
        vkn = draft.satici_vkn if draft.yon == "ALIS" else draft.alici_vkn
        unvan = draft.satici_unvan if draft.yon == "ALIS" else draft.alici_unvan
        parti = PartyMatchingService.eslestir(vkn, unvan, cari_turu=cari_turu)

        with get_session() as session:
            d = session.get(InvoiceImportDraft, draft_id)
            if d is None:
                raise ValueError("Taslak bulunamadı.")
            if parti.get("cari_id"):
                d.cari_id = int(parti["cari_id"])
                d.cari_eslesme_modu = "mevcut"
            elif parti.get("modu") == "bulunamadi":
                d.cari_eslesme_modu = "yeni_taslak"
                d.yeni_cari_json = dumps_accounting(
                    {
                        "unvan": unvan,
                        "vergi_numarasi": vkn if vkn and len(vkn) == 10 else None,
                        "tc_kimlik": vkn if vkn and len(vkn) == 11 else None,
                        "cari_turu": cari_turu,
                    }
                )
            d.updated_at = datetime.now()
            satirlar = list(
                session.scalars(select(InvoiceImportLine).where(InvoiceImportLine.draft_id == draft_id))
            )
            _ESLESME_TAMAM = {"eslesti", "yeni_stok", "hizmet", "gider", "haric"}
            for line in satirlar:
                # Kullanıcı eşleştirmesini / yeni kart bağını otomatik ezme
                if line.match_status in _ESLESME_TAMAM:
                    continue
                sonuc = ProductMatchingService.satir_eslestir(line, tedarikci_cari_id=d.cari_id)
                if sonuc.get("status") == "eslesti":
                    line.match_status = "eslesti"
                    line.stok_id = sonuc["stok_id"]
                    line.stok_kodu = sonuc["stok_kodu"]
                    line.birim_carpan = sonuc.get("birim_carpan") or Decimal("1")
                    line.guven = sonuc.get("guven")
                elif sonuc.get("status") == "secim_gerekli":
                    line.match_status = "secim_gerekli"
                    line.guven = sonuc.get("guven")
                else:
                    line.match_status = "bulunamadi"
            if d.cari_id and all(s.match_status in _ESLESME_TAMAM for s in satirlar):
                d.durum = "kontrol_bekliyor"
            else:
                d.durum = "eslestirme_bekliyor"
            session.flush()
        return {"parti": parti, "draft_id": draft_id}

    @staticmethod
    def cari_ata(draft_id: int, cari_id: int) -> None:
        with get_session() as session:
            d = session.get(InvoiceImportDraft, draft_id)
            if not d:
                raise ValueError("Taslak bulunamadı.")
            d.cari_id = int(cari_id)
            d.cari_eslesme_modu = "mevcut"
            d.updated_at = datetime.now()
            session.flush()
        vkn = None
        data = InvoiceDraftService.getir(draft_id)
        draft = data["draft"]
        vkn = draft.satici_vkn if draft.yon == "ALIS" else draft.alici_vkn
        if vkn:
            PartyMatchingService.hafizaya_yaz(vkn, cari_id, draft.satici_unvan or draft.alici_unvan)

    @staticmethod
    def satir_stok_ata(
        line_id: int,
        stok_id: int,
        stok_kodu: str,
        *,
        carpan: Decimal = Decimal("1"),
        match_status: str = "eslesti",
    ) -> None:
        durum = (match_status or "eslesti").strip() or "eslesti"
        if durum not in {"eslesti", "yeni_stok"}:
            durum = "eslesti"
        with get_session() as session:
            line = session.get(InvoiceImportLine, line_id)
            if not line:
                raise ValueError("Satır bulunamadı.")
            line.stok_id = int(stok_id)
            line.stok_kodu = stok_kodu
            line.birim_carpan = carpan
            line.match_status = durum
            line.guven = Decimal("100")
            draft = session.get(InvoiceImportDraft, line.draft_id)
            tedarikci = draft.cari_id if draft else None
            session.flush()
        ProductMatchingService.hafizaya_yaz(
            tedarikci_cari_id=tedarikci,
            satici_urun_kodu=None,
            barkod=None,
            stok_id=stok_id,
            birim_carpan=carpan,
        )
        # satıcı kodunu da yaz
        with get_session() as session:
            line = session.get(InvoiceImportLine, line_id)
            if line and line.satici_urun_kodu:
                ProductMatchingService.hafizaya_yaz(
                    tedarikci_cari_id=tedarikci,
                    satici_urun_kodu=line.satici_urun_kodu,
                    barkod=line.barkod,
                    stok_id=stok_id,
                    birim_carpan=carpan,
                )

    @staticmethod
    def dogrula(draft_id: int) -> dict[str, Any]:
        data = InvoiceDraftService.getir(draft_id)
        draft: InvoiceImportDraft = data["draft"]
        satirlar: list[InvoiceImportLine] = data["satirlar"]
        hatalar: list[str] = []
        uyarilar: list[str] = []

        if not draft.belge_no:
            hatalar.append("Fatura numarası zorunlu.")
        if not draft.belge_tarihi or not tarih_tr(draft.belge_tarihi):
            hatalar.append("Fatura tarihi zorunlu.")
        if draft.yon not in {"ALIS", "SATIS"}:
            hatalar.append("Alış/satış yönü belirsiz.")
        if not draft.cari_id and draft.cari_eslesme_modu != "yeni_taslak":
            hatalar.append("Cari seçilmedi.")
        if draft.cari_eslesme_modu == "yeni_taslak":
            try:
                jc = json.loads(draft.yeni_cari_json or "{}")
            except json.JSONDecodeError:
                jc = {}
            if not (jc.get("unvan") or "").strip():
                hatalar.append("Yeni cari taslağında ünvan zorunlu.")
            # VKN/TCKN zorunlu değil; boş kimlik ile gerçek kart açılabilir.

        if not satirlar:
            hatalar.append(
                "Fatura satırı yok. Satırlar okunmadan veya manuel eklenmeden kesin fatura oluşturulamaz."
            )
            if draft.genel_toplam:
                hatalar.append(
                    "Genel toplam okunmuş olsa da satır bulunamadığı için okuma başarılı sayılmaz."
                )

        for s in satirlar:
            if s.match_status not in {"eslesti", "yeni_stok", "hizmet", "gider", "haric"}:
                hatalar.append(f"Satır {s.sira}: stok/hizmet eşleşmesi tamamlanmadı.")
            if s.match_status == "haric":
                continue
            if s.match_status in {"eslesti", "yeni_stok"} and not s.stok_id:
                hatalar.append(f"Satır {s.sira}: stok eşleşmesi var ama stok kimliği eksik.")
            if s.miktar is None or s.miktar <= 0:
                hatalar.append(f"Satır {s.sira}: miktar geçersiz.")
            fiyat_ok = s.birim_fiyat is not None and s.birim_fiyat >= 0
            toplam_ok = s.satir_toplam is not None and s.satir_toplam >= 0
            if not fiyat_ok and not toplam_ok:
                hatalar.append(f"Satır {s.sira}: birim fiyat ve satır toplamı birlikte boş.")
            # Birim dönüşümü: fatura birimi ile stok bağında çarpan yoksa uyarı
            if s.match_status in {"eslesti", "yeni_stok"} and s.birim_carpan is None:
                uyarilar.append(
                    f"Satır {s.sira}: birim çarpanı boş; 1 kabul edilecek. "
                    "Koli/paket için dönüşümü kontrol edin."
                )

        hesaplanan = Decimal("0")
        for s in satirlar:
            if s.match_status == "haric":
                continue
            if s.miktar is not None and s.birim_fiyat is not None:
                net = s.miktar * s.birim_fiyat
                isk = (s.iskonto_orani or Decimal("0")) / Decimal("100")
                net = net * (Decimal("1") - isk)
                kdv = (s.kdv_orani or Decimal("0")) / Decimal("100")
                hesaplanan += net * (Decimal("1") + kdv)
            elif s.satir_toplam is not None:
                kdv = (s.kdv_orani or Decimal("0")) / Decimal("100")
                hesaplanan += s.satir_toplam * (Decimal("1") + kdv)
        hesaplanan = _q2(hesaplanan)
        belge_toplam = _q2(draft.genel_toplam or Decimal("0"))
        fark = abs(hesaplanan - belge_toplam) if belge_toplam else Decimal("0")
        tolerans = Decimal("0.05")
        if satirlar and belge_toplam and fark > tolerans:
            hatalar.append(
                f"Belgedeki genel toplam ({belge_toplam}) ile hesaplanan ({hesaplanan}) arasında {fark} TL fark var."
            )
        elif satirlar and belge_toplam and fark > 0:
            uyarilar.append(f"Kuruş farkı: {fark} TL (tolerans içinde).")

        # Mükerrer ETTN kesin fatura
        if draft.ettn:
            uyarilar.append(f"ETTN: {draft.ettn}")

        return {
            "ok": not hatalar,
            "hatalar": hatalar,
            "uyarilar": uyarilar,
            "hesaplanan_toplam": hesaplanan,
            "belge_toplam": belge_toplam,
            "fark": fark,
            "satir_sayisi": len(satirlar),
        }

    @staticmethod
    def satir_ekle(draft_id: int, veri: dict[str, Any]) -> int:
        with get_session() as session:
            draft = session.get(InvoiceImportDraft, draft_id)
            if not draft or draft.is_deleted:
                raise ValueError("Taslak bulunamadı.")
            max_sira = session.scalar(
                select(InvoiceImportLine.sira)
                .where(InvoiceImportLine.draft_id == draft_id)
                .order_by(InvoiceImportLine.sira.desc())
                .limit(1)
            ) or 0
            miktar = to_decimal(veri.get("miktar"), "0")
            fiyat = to_decimal(veri.get("birim_fiyat"), "0")
            toplam = veri.get("satir_toplam")
            toplam_d = to_decimal(toplam, "0") if toplam not in (None, "") else miktar * fiyat
            line = InvoiceImportLine(
                draft_id=draft_id,
                sira=max_sira + 1,
                aciklama=(veri.get("aciklama") or "").strip() or None,
                satici_urun_kodu=veri.get("satici_urun_kodu"),
                miktar=miktar,
                birim=veri.get("birim") or "ADET",
                birim_fiyat=fiyat,
                iskonto_orani=to_decimal(veri.get("iskonto_orani"), "0"),
                kdv_orani=to_decimal(veri.get("kdv_orani"), "20"),
                satir_toplam=toplam_d,
                match_status="bekliyor",
                guven=Decimal("100"),
                raw_json=dumps_accounting({**veri, "source_method": "manual", "kaynak": "manual"}),
            )
            session.add(line)
            session.add(
                InvoiceImportAudit(
                    draft_id=draft_id,
                    kullanici=oturum.kullanici_adi,
                    aksiyon="manuel_satir_ekle",
                    sonraki_json=dumps_accounting({"aciklama": line.aciklama, "miktar": miktar}),
                )
            )
            session.flush()
            return int(line.id)

    @staticmethod
    def satir_guncelle(line_id: int, veri: dict[str, Any]) -> None:
        with get_session() as session:
            line = session.get(InvoiceImportLine, line_id)
            if not line:
                raise ValueError("Satır bulunamadı.")
            onceki = {
                "aciklama": line.aciklama,
                "miktar": line.miktar,
                "birim_fiyat": line.birim_fiyat,
                "satir_toplam": line.satir_toplam,
            }
            if "aciklama" in veri:
                line.aciklama = (veri.get("aciklama") or "").strip() or None
            if "miktar" in veri:
                line.miktar = to_decimal(veri.get("miktar"), "0")
            if "birim" in veri:
                line.birim = veri.get("birim") or line.birim
            if "birim_fiyat" in veri:
                line.birim_fiyat = to_decimal(veri.get("birim_fiyat"), "0")
            if "kdv_orani" in veri:
                line.kdv_orani = to_decimal(veri.get("kdv_orani"), "20")
            if "iskonto_orani" in veri:
                line.iskonto_orani = to_decimal(veri.get("iskonto_orani"), "0")
            if "satir_toplam" in veri:
                line.satir_toplam = to_decimal(veri.get("satir_toplam"), "0")
            elif line.miktar is not None and line.birim_fiyat is not None:
                line.satir_toplam = line.miktar * line.birim_fiyat
            session.add(
                InvoiceImportAudit(
                    draft_id=line.draft_id,
                    kullanici=oturum.kullanici_adi,
                    aksiyon="manuel_satir_duzenle",
                    onceki_json=dumps_accounting(onceki),
                    sonraki_json=dumps_accounting(veri),
                )
            )
            session.flush()

    @staticmethod
    def satir_sil(line_id: int) -> None:
        with get_session() as session:
            line = session.get(InvoiceImportLine, line_id)
            if not line:
                raise ValueError("Satır bulunamadı.")
            draft_id = line.draft_id
            session.delete(line)
            session.add(
                InvoiceImportAudit(
                    draft_id=draft_id,
                    kullanici=oturum.kullanici_adi,
                    aksiyon="manuel_satir_sil",
                    onceki_json=dumps_accounting({"line_id": line_id}),
                )
            )
            session.flush()

    @staticmethod
    def taslak_iptal(draft_id: int) -> None:
        with get_session() as session:
            draft = session.get(InvoiceImportDraft, draft_id)
            if not draft:
                raise ValueError("Taslak bulunamadı.")
            if draft.durum == "fatura_olusturuldu":
                raise ValueError("Kesinleşmiş fatura iptal edilemez.")
            draft.durum = "iptal_edildi"
            draft.updated_at = datetime.now()
            session.add(
                InvoiceImportAudit(
                    draft_id=draft_id,
                    kullanici=oturum.kullanici_adi,
                    aksiyon="taslak_iptal",
                )
            )
            session.flush()


class InvoicePostingService:
    @staticmethod
    def kesinlestir(draft_id: int) -> dict[str, Any]:
        yazma_zorunlu("alis_duzenleme", "satis_duzenleme", "yeni_kayit")
        dog = InvoiceDraftService.dogrula(draft_id)
        if not dog["ok"]:
            raise ValueError("Kesin kayıt engellendi:\n- " + "\n- ".join(dog["hatalar"]))

        data = InvoiceDraftService.getir(draft_id)
        draft: InvoiceImportDraft = data["draft"]
        satirlar: list[InvoiceImportLine] = data["satirlar"]

        # Optimistic lock
        with get_session() as session:
            d = session.get(InvoiceImportDraft, draft_id)
            if d is None:
                raise ValueError("Taslak bulunamadı.")
            if d.durum == "fatura_olusturuldu":
                raise ValueError("Bu taslak zaten faturaya dönüştürülmüş.")
            if d.durum == "iptal_edildi":
                raise ValueError("İptal edilmiş taslak kesinleştirilemez.")
            ver = d.version
            d.version = ver + 1
            d.durum = "isleniyor"
            session.flush()

        try:
            cari_id = draft.cari_id
            if not cari_id and draft.cari_eslesme_modu == "yeni_taslak":
                jc = json.loads(draft.yeni_cari_json or "{}")
                cari = CariService.ekle(
                    {
                        "unvan": jc.get("unvan"),
                        "cari_turu": jc.get("cari_turu") or ("Tedarikçi" if draft.yon == "ALIS" else "Müşteri"),
                        "vergi_numarasi": jc.get("vergi_numarasi"),
                        "tc_kimlik": jc.get("tc_kimlik"),
                        "aktif": True,
                    }
                )
                cari_id = cari.id
                if draft.satici_vkn or draft.alici_vkn:
                    PartyMatchingService.hafizaya_yaz(
                        draft.satici_vkn or draft.alici_vkn or "",
                        cari_id,
                        draft.satici_unvan or draft.alici_unvan,
                    )

            tarih = tarih_tr(draft.belge_tarihi) or date.today()
            vade = tarih + timedelta(days=0)
            aktif_satirlar = [s for s in satirlar if s.match_status != "haric"]
            satir_verileri = []
            kismi_teslim = False
            for s in aktif_satirlar:
                carpan = s.birim_carpan or Decimal("1")
                miktar = (s.miktar or Decimal("0")) * carpan
                belge_mik = s.miktar or Decimal("0")
                if s.teslim_miktar is not None and s.teslim_miktar < belge_mik:
                    kismi_teslim = True
                row = {
                    "urun_kodu": s.stok_kodu,
                    "urun_adi": s.aciklama or s.stok_kodu,
                    "miktar": miktar,
                    "birim": "Adet",
                    "birim_fiyat": s.birim_fiyat or Decimal("0"),
                    "iskonto_orani": s.iskonto_orani or Decimal("0"),
                    "kdv_orani": s.kdv_orani or Decimal("20"),
                    "barkod": s.barkod,
                }
                if getattr(s, "irsaliye_satiri_id", None):
                    row["irsaliye_satiri_id"] = int(s.irsaliye_satiri_id)
                satir_verileri.append(row)

            mal_kabul = (getattr(draft, "mal_kabul_durumu", None) or "mal_bekleniyor").strip().lower()
            if mal_kabul not in MAL_KABUL_DURUMLARI:
                mal_kabul = "mal_bekleniyor"
            if mal_kabul == "irsaliyeden" and not getattr(draft, "linked_irsaliye_id", None):
                bagli = any(getattr(s, "irsaliye_satiri_id", None) for s in aktif_satirlar)
                if not bagli:
                    raise ValueError(
                        "İrsaliyeden Alındı seçildi fakat irsaliye bağlanmadı. "
                        "Önce açık irsaliyeyi seçin."
                    )
            # Mal Geldi + tam teslim → stok şimdi. Kısmi teslim / bekleniyor / irsaliye → stok yazma
            # (kısmi: fatura mali kaydı oluşur; kalan fiziksel kabul sonra bağlanır).
            hareket_yaz = (
                draft.yon == "ALIS"
                and mal_kabul == "mal_geldi"
                and not kismi_teslim
            )

            if draft.yon == "ALIS":
                acik = f"e-Fatura aktarım ETTN={draft.ettn or '-'} | mal_kabul={mal_kabul}"
                if kismi_teslim:
                    acik += " | kismi_teslim"
                kayit = {
                    "fatura_no": draft.belge_no,
                    "fatura_tarihi": tarih,
                    "vade_tarihi": vade,
                    "cari_id": cari_id,
                    "depo": "ANA DEPO",
                    "para_birimi": draft.para_birimi or "TRY",
                    "kur": draft.kur or Decimal("1"),
                    "aciklama": acik,
                    "hareket_yaz": hareket_yaz,
                }
                if getattr(draft, "linked_irsaliye_id", None):
                    kayit["irsaliye_id"] = int(draft.linked_irsaliye_id)
                fatura = AlisFaturasiService.kaydet(kayit, satir_verileri)
                fatura_id = fatura.id if hasattr(fatura, "id") else getattr(fatura, "fatura_id", None)
                tur = "ALIS"
            else:
                fatura = SatisFaturasiService.kaydet(
                    {
                        "fatura_no": draft.belge_no,
                        "fatura_tarihi": tarih,
                        "vade_tarihi": vade,
                        "cari_id": cari_id,
                        "depo": "ANA DEPO",
                        "para_birimi": draft.para_birimi or "TRY",
                        "kur": draft.kur or Decimal("1"),
                        "aciklama": f"e-Fatura aktarım ETTN={draft.ettn or '-'}",
                    },
                    satir_verileri,
                )
                fatura_id = fatura.id if hasattr(fatura, "id") else None
                tur = "SATIS"

            with get_session() as session:
                d = session.get(InvoiceImportDraft, draft_id)
                if d is None:
                    raise ValueError("Taslak kayboldu.")
                d.durum = "fatura_olusturuldu"
                d.linked_invoice_id = fatura_id
                d.linked_invoice_tur = tur
                d.cari_id = cari_id
                if draft.yon == "ALIS":
                    d.mal_kabul_durumu = mal_kabul
                d.updated_at = datetime.now()
                session.add(
                    InvoiceImportAudit(
                        draft_id=draft_id,
                        kullanici=oturum.kullanici_adi,
                        aksiyon="kesin_kayit",
                        sonraki_json=dumps_accounting(
                            {
                                "fatura_id": fatura_id,
                                "tur": tur,
                                "mal_kabul_durumu": mal_kabul if draft.yon == "ALIS" else None,
                                "hareket_yaz": hareket_yaz,
                                "kismi_teslim": kismi_teslim,
                                "irsaliye_id": getattr(draft, "linked_irsaliye_id", None),
                            },
                        ),
                    )
                )
                session.flush()

            return {
                "fatura_id": fatura_id,
                "tur": tur,
                "belge_no": draft.belge_no,
                "mal_kabul_durumu": mal_kabul if draft.yon == "ALIS" else None,
                "hareket_yaz": hareket_yaz,
                "kismi_teslim": kismi_teslim,
                "irsaliye_id": getattr(draft, "linked_irsaliye_id", None),
            }
        except Exception:
            with get_session() as session:
                d = session.get(InvoiceImportDraft, draft_id)
                if d:
                    d.durum = "hatali"
                    d.hata_mesaji = "Kesin kayıt başarısız; yarım kayıt bırakılmadı (rollback)."
                    session.flush()
            raise
