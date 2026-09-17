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
    InvoiceImportLine,
)
from fatura_belge_aktarim.normalize import tarih_tr


def _q2(v: Decimal) -> Decimal:
    return v.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


class InvoiceDraftService:
    @staticmethod
    def listele(*, yon: str | None = None, durum: str | None = None, limit: int = 100) -> list[InvoiceImportDraft]:
        with get_session() as session:
            q = select(InvoiceImportDraft).where(InvoiceImportDraft.is_deleted.is_(False))
            if yon:
                q = q.where(InvoiceImportDraft.yon == yon.upper())
            if durum:
                q = q.where(InvoiceImportDraft.durum == durum)
            q = q.order_by(InvoiceImportDraft.id.desc()).limit(limit)
            return list(session.scalars(q))

    @staticmethod
    def getir(draft_id: int) -> dict[str, Any]:
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
            for line in satirlar:
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
            if d.cari_id and all(s.match_status == "eslesti" for s in satirlar):
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
    def satir_stok_ata(line_id: int, stok_id: int, stok_kodu: str, *, carpan: Decimal = Decimal("1")) -> None:
        with get_session() as session:
            line = session.get(InvoiceImportLine, line_id)
            if not line:
                raise ValueError("Satır bulunamadı.")
            line.stok_id = int(stok_id)
            line.stok_kodu = stok_kodu
            line.birim_carpan = carpan
            line.match_status = "eslesti"
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
            if not (jc.get("vergi_numarasi") or jc.get("tc_kimlik")):
                hatalar.append("Yeni cari taslağında vergi/T.C. no zorunlu.")

        if not satirlar:
            hatalar.append(
                "Fatura satırı yok. Satırlar okunmadan veya manuel eklenmeden kesin fatura oluşturulamaz."
            )
            if draft.genel_toplam:
                hatalar.append(
                    "Genel toplam okunmuş olsa da satır bulunamadığı için okuma başarılı sayılmaz."
                )

        for s in satirlar:
            if s.match_status not in {"eslesti", "hizmet", "gider", "haric"}:
                hatalar.append(f"Satır {s.sira}: stok/hizmet eşleşmesi tamamlanmadı.")
            if s.match_status == "haric":
                continue
            if s.miktar is None or s.miktar <= 0:
                hatalar.append(f"Satır {s.sira}: miktar geçersiz.")
            fiyat_ok = s.birim_fiyat is not None and s.birim_fiyat >= 0
            toplam_ok = s.satir_toplam is not None and s.satir_toplam >= 0
            if not fiyat_ok and not toplam_ok:
                hatalar.append(f"Satır {s.sira}: birim fiyat ve satır toplamı birlikte boş.")

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
            for s in aktif_satirlar:
                carpan = s.birim_carpan or Decimal("1")
                miktar = (s.miktar or Decimal("0")) * carpan
                satir_verileri.append(
                    {
                        "urun_kodu": s.stok_kodu,
                        "urun_adi": s.aciklama or s.stok_kodu,
                        "miktar": miktar,
                        "birim": "Adet",
                        "birim_fiyat": s.birim_fiyat or Decimal("0"),
                        "iskonto_orani": s.iskonto_orani or Decimal("0"),
                        "kdv_orani": s.kdv_orani or Decimal("20"),
                        "barkod": s.barkod,
                    }
                )

            if draft.yon == "ALIS":
                fatura = AlisFaturasiService.kaydet(
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
                d.updated_at = datetime.now()
                session.add(
                    InvoiceImportAudit(
                        draft_id=draft_id,
                        kullanici=oturum.kullanici_adi,
                        aksiyon="kesin_kayit",
                        sonraki_json=dumps_accounting(
                            {"fatura_id": fatura_id, "tur": tur},
                        ),
                    )
                )
                session.flush()

            return {"fatura_id": fatura_id, "tur": tur, "belge_no": draft.belge_no}
        except Exception:
            with get_session() as session:
                d = session.get(InvoiceImportDraft, draft_id)
                if d:
                    d.durum = "hatali"
                    d.hata_mesaji = "Kesin kayıt başarısız; yarım kayıt bırakılmadı (rollback)."
                    session.flush()
            raise
