"""Dosya yükleme, hash, saklama ve yön belirleme."""

from __future__ import annotations

import logging
import traceback
from datetime import datetime
from decimal import Decimal
from pathlib import Path

from sqlalchemy import select

from database.database import get_session
from database.session_manager import oturum
from fatura_belge_aktarim.json_codec import dumps_accounting
from fatura_belge_aktarim.models import InvoiceImportAudit, InvoiceImportDraft, InvoiceImportFile, InvoiceImportLine
from fatura_belge_aktarim.normalize import (
    ALLOWED_EXT,
    MAX_BYTES,
    normalize_vkn,
    safe_filename,
    sha256_bytes,
)
from fatura_belge_aktarim.pdf_extractor import extract_image_invoice, extract_pdf_invoice
from fatura_belge_aktarim.ubl_extractor import ExtractedInvoice, extract_from_zip_or_xml

_LOG = logging.getLogger("fatura_belge_aktarim.document")

KULLANICI_DONUSUM_HATASI = (
    "Fatura taslağı oluşturulurken veri dönüştürme hatası meydana geldi.\n"
    "Belge kaydedilmedi. Ayrıntılar sistem günlüğüne kaydedildi."
)


def _storage_root() -> Path:
    base = Path(oturum.db_path).resolve().parent if oturum.db_path else Path("data")
    root = base / "invoice_imports"
    root.mkdir(parents=True, exist_ok=True)
    return root


def _firma_vkn() -> str:
    vkn = normalize_vkn(getattr(oturum, "firma_vergi_no", None) or "")
    if vkn:
        return vkn
    try:
        from database.database import get_system_session
        from database.system.models import Company

        if not oturum.company_id:
            return ""
        with get_system_session() as session:
            firma = session.get(Company, oturum.company_id)
            return normalize_vkn(getattr(firma, "vergi_no", None) if firma else None)
    except Exception:
        return ""


def determine_direction(extracted: ExtractedInvoice, menu_yon: str) -> tuple[str, list[str]]:
    """menu_yon: ALIS | SATIS. Dönüş: (yon, uyarilar)."""
    uyarilar: list[str] = []
    bizim = _firma_vkn()
    satici = normalize_vkn((extracted.satici or {}).get("vkn"))
    alici = normalize_vkn((extracted.alici or {}).get("vkn"))
    yon = menu_yon.upper()

    if bizim:
        if alici and alici == bizim:
            yon = "ALIS"
        elif satici and satici == bizim:
            yon = "SATIS"
        elif satici and alici and bizim not in {satici, alici}:
            uyarilar.append(
                "Belgedeki alıcı/satıcı bilgileri seçili firmayla eşleşmiyor (yanlış firma uyarısı)."
            )
    if yon != menu_yon.upper():
        uyarilar.append(
            f"Belge taraflarına göre yön {yon}; menü {menu_yon.upper()} seçili. "
            "Doğru menüye yönlendirin veya yönü onaylayın."
        )
    if not satici and not alici:
        uyarilar.append("Taraf bilgisi okunamadı; alış/satış yönünü kullanıcı seçmeli.")
    return yon, uyarilar


def _log_donusum_hatasi(
    *,
    dosya_adi: str,
    draft_id: int | None,
    fonksiyon: str,
    exc: BaseException,
) -> None:
    _LOG.error(
        "Fatura JSON dönüştürme hatası | zaman=%s kullanici=%s firma=%s dosya=%s "
        "draft_id=%s servis=%s tip=%s\n%s",
        datetime.now().isoformat(timespec="seconds"),
        oturum.kullanici_adi,
        oturum.firma_unvan or oturum.firma_kodu or oturum.company_id,
        dosya_adi,
        draft_id,
        fonksiyon,
        type(exc).__name__,
        traceback.format_exc(),
    )


class InvoiceDocumentService:
    @staticmethod
    def yukleme(dosya_yolu: str | Path, *, menu_yon: str = "ALIS") -> InvoiceImportDraft:
        yol = Path(dosya_yolu)
        if not yol.is_file():
            raise ValueError("Dosya bulunamadı.")
        ext = yol.suffix.lower()
        if ext not in ALLOWED_EXT:
            raise ValueError(
                f"Desteklenmeyen dosya türü: {ext}. "
                f"İzin verilenler: {', '.join(sorted(ALLOWED_EXT))}"
            )
        data = yol.read_bytes()
        if len(data) > MAX_BYTES:
            raise ValueError(f"Dosya boyutu limiti aşıldı (max {MAX_BYTES // (1024*1024)} MB).")
        if len(data) == 0:
            raise ValueError("Dosya boş.")

        digest = sha256_bytes(data)
        with get_session() as session:
            eski = session.scalar(
                select(InvoiceImportFile).where(InvoiceImportFile.sha256 == digest)
            )
            if eski:
                draft_eski = session.get(InvoiceImportDraft, eski.draft_id)
                if draft_eski and draft_eski.durum not in {"iptal_edildi"}:
                    raise ValueError(
                        f"Bu belge daha önce yüklenmiş (taslak #{eski.draft_id}, durum: {draft_eski.durum}). "
                        "Mevcut taslağı açın veya mevcut faturaya bağlayın."
                    )

        safe = safe_filename(yol.name)
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        rel = f"{stamp}_{digest[:10]}_{safe}"
        hedef = _storage_root() / rel
        hedef.write_bytes(data)
        try:
            hedef.chmod(0o444)
        except Exception:
            pass

        try:
            return InvoiceDocumentService._taslak_kaydet(
                data=data,
                ext=ext,
                hedef=hedef,
                rel=rel,
                safe=safe,
                digest=digest,
                menu_yon=menu_yon,
                dosya_adi=safe,
            )
        except Exception as exc:
            InvoiceDocumentService._dosya_temizle(hedef)
            if "serializable" in str(exc).lower() or (
                isinstance(exc, TypeError) and "Decimal" in str(exc)
            ):
                _log_donusum_hatasi(
                    dosya_adi=safe,
                    draft_id=None,
                    fonksiyon="InvoiceDocumentService.yukleme",
                    exc=exc,
                )
                raise ValueError(KULLANICI_DONUSUM_HATASI) from exc
            if isinstance(exc, ValueError):
                raise
            _log_donusum_hatasi(
                dosya_adi=safe,
                draft_id=None,
                fonksiyon="InvoiceDocumentService.yukleme",
                exc=exc,
            )
            raise

    @staticmethod
    def _dosya_temizle(hedef: Path) -> None:
        try:
            if hedef.is_file():
                try:
                    hedef.chmod(0o666)
                except Exception:
                    pass
                hedef.unlink(missing_ok=True)
        except Exception as exc:  # noqa: BLE001
            _LOG.warning("Geçici fatura dosyası silinemedi: %s (%s)", hedef, exc)

    @staticmethod
    def _taslak_kaydet(
        *,
        data: bytes,
        ext: str,
        hedef: Path,
        rel: str,
        safe: str,
        digest: str,
        menu_yon: str,
        dosya_adi: str,
    ) -> InvoiceImportDraft:
        extracted, kaynak, diag = InvoiceDocumentService._extract(data, ext, hedef)
        yon, yon_uyari = determine_direction(extracted, menu_yon)
        uyarilar = list(extracted.uyarılar) + yon_uyari
        _LOG.info(
            "Taslak çıkarma diag winning=%s satir=%s methods=%s",
            diag.get("winning_method"),
            diag.get("line_count"),
            diag.get("methods_tried"),
        )

        if extracted.ettn:
            with get_session() as session:
                ayni = session.scalar(
                    select(InvoiceImportDraft).where(
                        InvoiceImportDraft.ettn == extracted.ettn,
                        InvoiceImportDraft.is_deleted.is_(False),
                        InvoiceImportDraft.durum.notin_(["iptal_edildi"]),
                    )
                )
                if ayni:
                    uyarilar.append(
                        f"Aynı ETTN ile taslak/fatura mevcut (#{ayni.id}). Mükerrer kontrolü gerekli."
                    )

        extracted_payload = {
            "satici": extracted.satici,
            "alici": extracted.alici,
            "toplamlar": extracted.toplamlar or {},
            "satirlar": extracted.satirlar,
            "para_birimi": extracted.para_birimi,
            "kur": extracted.kur,
            "guven": extracted.guven,
            "diag": {
                k: diag.get(k)
                for k in ("winning_method", "line_count", "methods_tried", "ocr_used", "page_count")
            },
        }

        kullanici = oturum.kullanici_adi
        with get_session() as session:
            try:
                draft = InvoiceImportDraft(
                    yon=yon,
                    durum="kontrol_bekliyor"
                    if extracted.satirlar or extracted.belge_no
                    else "eslestirme_bekliyor",
                    kaynak_turu=kaynak,
                    belge_no=extracted.belge_no,
                    ettn=extracted.ettn,
                    belge_tarihi=extracted.belge_tarihi,
                    senaryo=extracted.senaryo,
                    fatura_tipi=extracted.fatura_tipi,
                    para_birimi=extracted.para_birimi or "TRY",
                    kur=extracted.kur,
                    genel_toplam=(extracted.toplamlar or {}).get("genel_toplam")
                    or (extracted.toplamlar or {}).get("odenecek"),
                    genel_guven=extracted.guven,
                    satici_unvan=(extracted.satici or {}).get("unvan"),
                    satici_vkn=(extracted.satici or {}).get("vkn"),
                    alici_unvan=(extracted.alici or {}).get("unvan"),
                    alici_vkn=(extracted.alici or {}).get("vkn"),
                    extracted_json=dumps_accounting(extracted_payload),
                    uyari_json=dumps_accounting(uyarilar),
                    created_by=kullanici,
                )
                session.add(draft)
                session.flush()
                session.add(
                    InvoiceImportFile(
                        draft_id=draft.id,
                        safe_name=safe,
                        mime=_mime(ext),
                        size=len(data),
                        sha256=digest,
                        storage_relpath=rel,
                        sayfa_sayisi=diag.get("page_count"),
                    )
                )
                for s in extracted.satirlar:
                    session.add(
                        InvoiceImportLine(
                            draft_id=draft.id,
                            sira=int(s.get("sira") or 1),
                            aciklama=s.get("aciklama"),
                            satici_urun_kodu=s.get("satici_urun_kodu"),
                            alici_urun_kodu=s.get("alici_urun_kodu"),
                            barkod=s.get("barkod"),
                            miktar=s.get("miktar"),
                            birim=s.get("birim"),
                            birim_fiyat=s.get("birim_fiyat"),
                            iskonto_orani=s.get("iskonto_orani"),
                            kdv_orani=s.get("kdv_orani"),
                            satir_toplam=s.get("satir_toplam"),
                            match_status="bekliyor",
                            guven=s.get("guven"),
                            raw_json=dumps_accounting(s),
                        )
                    )
                session.add(
                    InvoiceImportAudit(
                        draft_id=draft.id,
                        kullanici=kullanici,
                        aksiyon="yukleme",
                        sonraki_json=dumps_accounting(
                            {
                                "belge_no": draft.belge_no,
                                "ettn": draft.ettn,
                                "yon": yon,
                                "dosya": dosya_adi,
                                "satir_sayisi": len(extracted.satirlar),
                                "winning_method": diag.get("winning_method"),
                            }
                        ),
                    )
                )
                session.flush()
                session.refresh(draft)
                return draft
            except Exception:
                session.rollback()
                raise

    @staticmethod
    def _extract(
        data: bytes, ext: str, yol: Path, *, force_method: str | None = None
    ) -> tuple[ExtractedInvoice, str, dict]:
        if ext in {".xml", ".zip"}:
            inv = extract_from_zip_or_xml(data, yol.name)
            return inv, "ubl_xml", {"winning_method": "ubl_xml", "line_count": len(inv.satirlar)}
        if ext == ".pdf":
            return extract_pdf_invoice(data, force_method=force_method)
        if ext in {".jpg", ".jpeg", ".png", ".webp"}:
            data_img = data
            inv, kaynak, diag = extract_image_invoice(data_img, yol=yol)
            return inv, kaynak, diag
        raise ValueError("Desteklenmeyen tür.")

    @staticmethod
    def dosya_yolu(draft_id: int) -> Path | None:
        with get_session() as session:
            f = session.scalar(
                select(InvoiceImportFile).where(InvoiceImportFile.draft_id == draft_id)
            )
            if not f:
                return None
            return _storage_root() / f.storage_relpath

    @staticmethod
    def okuma_ayrintilari(draft_id: int) -> dict:
        with get_session() as session:
            draft = session.get(InvoiceImportDraft, draft_id)
            if not draft:
                raise ValueError("Taslak bulunamadı.")
            satir_sayisi = len(
                list(
                    session.scalars(
                        select(InvoiceImportLine).where(InvoiceImportLine.draft_id == draft_id)
                    )
                )
            )
            return {
                "draft_id": draft_id,
                "kaynak_turu": draft.kaynak_turu,
                "belge_no": draft.belge_no,
                "satir_sayisi": satir_sayisi,
                "genel_guven": draft.genel_guven,
                "uyarilar": draft.uyari_json,
                "extracted_json": (draft.extracted_json or "")[:4000],
            }

    @staticmethod
    def satirlarini_yeniden_oku(
        draft_id: int,
        *,
        force_method: str | None = None,
        manuel_koru: bool = True,
        xml_bytes: bytes | None = None,
    ) -> dict:
        """Mevcut belgeden satırları yeniden çıkar; mükerrer satır bırakmaz."""
        yol = InvoiceDocumentService.dosya_yolu(draft_id)
        if xml_bytes is not None:
            extracted = extract_from_zip_or_xml(xml_bytes, "yeniden.xml")
            kaynak = "ubl_xml"
            diag = {"winning_method": "ubl_xml", "line_count": len(extracted.satirlar)}
        else:
            if not yol or not yol.is_file():
                raise ValueError("Taslağa bağlı belge dosyası bulunamadı.")
            data = yol.read_bytes()
            ext = yol.suffix.lower()
            extracted, kaynak, diag = InvoiceDocumentService._extract(
                data, ext, yol, force_method=force_method
            )

        kullanici = oturum.kullanici_adi
        with get_session() as session:
            draft = session.get(InvoiceImportDraft, draft_id)
            if not draft or draft.is_deleted:
                raise ValueError("Taslak bulunamadı.")
            if draft.durum == "fatura_olusturuldu":
                raise ValueError("Kesinleşmiş taslak yeniden okunamaz.")

            eski = list(
                session.scalars(select(InvoiceImportLine).where(InvoiceImportLine.draft_id == draft_id))
            )
            manuel = [s for s in eski if (s.raw_json or "").find('"source_method": "manual"') >= 0 or (s.raw_json or "").find('"kaynak": "manual"') >= 0]
            if not manuel_koru:
                for s in eski:
                    session.delete(s)
                manuel = []
            else:
                for s in eski:
                    if s not in manuel:
                        session.delete(s)
            session.flush()

            # Başlık alanlarını güncelle (boş olanları doldur)
            if extracted.belge_no:
                draft.belge_no = extracted.belge_no
            if extracted.belge_tarihi:
                draft.belge_tarihi = extracted.belge_tarihi
            if extracted.ettn:
                draft.ettn = extracted.ettn
            if extracted.satici:
                draft.satici_unvan = extracted.satici.get("unvan") or draft.satici_unvan
                draft.satici_vkn = extracted.satici.get("vkn") or draft.satici_vkn
            if extracted.alici:
                draft.alici_unvan = extracted.alici.get("unvan") or draft.alici_unvan
                draft.alici_vkn = extracted.alici.get("vkn") or draft.alici_vkn
            if extracted.toplamlar:
                draft.genel_toplam = (
                    extracted.toplamlar.get("genel_toplam")
                    or extracted.toplamlar.get("odenecek")
                    or draft.genel_toplam
                )
            draft.kaynak_turu = kaynak
            draft.genel_guven = extracted.guven
            draft.extracted_json = dumps_accounting(
                {
                    "satici": extracted.satici,
                    "alici": extracted.alici,
                    "toplamlar": extracted.toplamlar or {},
                    "satirlar": extracted.satirlar,
                    "diag": diag,
                }
            )
            draft.uyari_json = dumps_accounting(list(extracted.uyarılar))
            draft.updated_at = datetime.now()

            base_sira = len(manuel)
            for i, s in enumerate(extracted.satirlar, start=1):
                session.add(
                    InvoiceImportLine(
                        draft_id=draft_id,
                        sira=base_sira + i,
                        aciklama=s.get("aciklama"),
                        satici_urun_kodu=s.get("satici_urun_kodu"),
                        alici_urun_kodu=s.get("alici_urun_kodu"),
                        barkod=s.get("barkod"),
                        miktar=s.get("miktar"),
                        birim=s.get("birim"),
                        birim_fiyat=s.get("birim_fiyat"),
                        iskonto_orani=s.get("iskonto_orani"),
                        kdv_orani=s.get("kdv_orani"),
                        satir_toplam=s.get("satir_toplam"),
                        match_status="bekliyor",
                        guven=s.get("guven"),
                        raw_json=dumps_accounting(s),
                    )
                )
            # Manuel satır sıralarını koru (1..n)
            for i, s in enumerate(manuel, start=1):
                s.sira = i

            session.add(
                InvoiceImportAudit(
                    draft_id=draft_id,
                    kullanici=kullanici,
                    aksiyon="yeniden_oku",
                    sonraki_json=dumps_accounting(
                        {
                            "force_method": force_method,
                            "kaynak": kaynak,
                            "satir": len(extracted.satirlar),
                            "manuel_koru": manuel_koru,
                            "diag": {k: diag.get(k) for k in ("winning_method", "line_count", "methods_tried", "ocr_used")},
                        }
                    ),
                )
            )
            session.flush()

        return {
            "draft_id": draft_id,
            "satir_sayisi": len(extracted.satirlar) + (len(manuel) if manuel_koru else 0),
            "kaynak": kaynak,
            "diag": diag,
        }


def _mime(ext: str) -> str:
    return {
        ".xml": "application/xml",
        ".pdf": "application/pdf",
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".png": "image/png",
        ".webp": "image/webp",
        ".zip": "application/zip",
    }.get(ext, "application/octet-stream")
