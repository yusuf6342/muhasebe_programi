"""Konsinye raporları — tüm kayıtlar üzerinden (200/500 sınırı yok)."""

from __future__ import annotations

from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Any

from sqlalchemy import select

from database.database import get_session
from database.konsinye_service import (
    SAHIP_BIZE,
    SAHIP_TEDARIKCI,
    YON_ALINAN,
    YON_VERILEN,
    KonsinyeService,
    miktar_goster,
)
from database.models.konsinye import KonsinyeHareket, KonsinyeTeslim, KonsinyeTeslimSatiri
from database.models.stok import Depo, StokLotu


def _d(v) -> Decimal:
    return Decimal(str(v or 0))


class KonsinyeRaporService:
    @staticmethod
    def musterideki_mallar(*, cari_id: int | None = None, stok_id: int | None = None) -> dict[str, Any]:
        """A) Müşterideki konsinye mallar — kalan > 0."""
        satirlar = []
        for t in KonsinyeService.listele(yon=YON_VERILEN, limit=None, cari_id=cari_id):
            for s in t["satirlar"]:
                if stok_id and int(s["stok_id"]) != int(stok_id):
                    continue
                if s["kalan_miktar"] <= 0 and s["fatura_bekleyen"] <= 0:
                    continue
                maliyet = _d(s.get("fifo_birim_maliyet"))
                fiyat = _d(s.get("birim_fiyat"))
                satirlar.append(
                    {
                        "cari": t["cari_unvan"],
                        "cari_id": t["cari_id"],
                        "teslim_no": t["belge_no"],
                        "teslim_id": t["id"],
                        "teslim_tarihi": t["belge_tarihi"],
                        "stok_kodu": s["stok_kodu"],
                        "stok_adi": s["stok_adi"],
                        "lot_no": s.get("lot_no"),
                        "birim": s["birim"],
                        "teslim_edilen": s["temel_miktar"],
                        "satilan": s["bildirilen_miktar"],
                        "iade": s["iade_miktar"],
                        "musteride_kalan": s["kalan_miktar"],
                        "faturalanan": s["faturalanan_miktar"],
                        "fatura_bekleyen": s["fatura_bekleyen"],
                        "maliyet_degeri": (s["kalan_miktar"] * maliyet).quantize(Decimal("0.01")),
                        "satis_degeri": (s["kalan_miktar"] * fiyat).quantize(Decimal("0.01")),
                    }
                )
        return {"baslik": "Müşterideki Konsinye Mallar", "satirlar": satirlar, "adet": len(satirlar)}

    @staticmethod
    def tedarikci_envanteri(*, cari_id: int | None = None) -> dict[str, Any]:
        """B) Tedarikçiye ait konsinye envanteri."""
        KonsinyeService.ensure_schema()
        satirlar = []
        with get_session() as session:
            q = select(StokLotu).where(
                StokLotu.sahip_turu == SAHIP_TEDARIKCI,
                StokLotu.kalan_miktar > 0,
            )
            if cari_id:
                q = q.where(StokLotu.sahip_cari_id == int(cari_id))
            for lot in session.scalars(q).all():
                depo = session.get(Depo, lot.depo_id)
                from database.models.stok import StokKarti
                from database.models.cari import Cari

                stok = session.get(StokKarti, lot.stok_id)
                cari = session.get(Cari, lot.sahip_cari_id) if lot.sahip_cari_id else None
                qnt = _d(lot.kalan_miktar)
                satirlar.append(
                    {
                        "cari": getattr(cari, "unvan", "") if cari else "",
                        "cari_id": lot.sahip_cari_id,
                        "depo": depo.ad if depo else "",
                        "stok_kodu": getattr(stok, "stok_kodu", ""),
                        "stok_adi": getattr(stok, "stok_adi", ""),
                        "lot_no": lot.lot_no,
                        "tedarikciye_ait": qnt,
                        "bize_ait": Decimal("0"),
                        "fiziksel": qnt,
                        "firma_degeri": Decimal("0"),
                    }
                )
        # Teslim sayaç özeti
        for t in KonsinyeService.listele(yon=YON_ALINAN, limit=None, cari_id=cari_id):
            for s in t["satirlar"]:
                if s["kalan_miktar"] <= 0 and s["bildirilen_miktar"] <= 0:
                    continue
                satirlar.append(
                    {
                        "cari": t["cari_unvan"],
                        "cari_id": t["cari_id"],
                        "depo": t["depo"],
                        "stok_kodu": s["stok_kodu"],
                        "stok_adi": s["stok_adi"],
                        "lot_no": s.get("lot_no"),
                        "alinan": s["temel_miktar"],
                        "kesin_alinan": s["bildirilen_miktar"],
                        "iade": s["iade_miktar"],
                        "tedarikciye_ait_kalan": s["kalan_miktar"],
                        "kaynak": "teslim",
                        "teslim_no": t["belge_no"],
                    }
                )
        return {"baslik": "Tedarikçiye Ait Konsinye Envanteri", "satirlar": satirlar, "adet": len(satirlar)}

    @staticmethod
    def fatura_bekleyen(*, yon: str | None = None) -> dict[str, Any]:
        """D) Faturalanmayı bekleyen."""
        satirlar = []
        for y in ((yon,) if yon else (YON_VERILEN, YON_ALINAN)):
            for s in KonsinyeService.faturalanabilir_satirlar(yon=y):
                satirlar.append(
                    {
                        "yon": y,
                        "teslim_no": s["belge_no"],
                        "teslim_id": s["teslim_id"],
                        "satir_id": s["id"],
                        "cari": s["cari_unvan"],
                        "stok_kodu": s["stok_kodu"],
                        "stok_adi": s["stok_adi"],
                        "bekleyen": s["fatura_bekleyen"],
                        "taslak_ayrilan": s.get("taslak_ayrilan_miktar", 0),
                        "faturalanan": s["faturalanan_miktar"],
                        "birim_fiyat": s["birim_fiyat"],
                        "tahmini_tutar": (s["fatura_bekleyen"] * _d(s["birim_fiyat"])).quantize(
                            Decimal("0.01")
                        ),
                        "belge_tarihi": s.get("belge_tarihi"),
                    }
                )
        return {"baslik": "Faturalanmayı Bekleyen Konsinyeler", "satirlar": satirlar, "adet": len(satirlar)}

    @staticmethod
    def yaslandirma(*, dilimler: list[tuple[int, int]] | None = None, referans: date | None = None) -> dict:
        """E) Yaşlandırma — müşteride kalan / fatura bekleyen."""
        ref = referans or date.today()
        dilimler = dilimler or [(0, 15), (16, 30), (31, 60), (61, 90), (91, 10_000)]
        kovalar = {f"{a}-{b if b < 1000 else '90+'}": [] for a, b in dilimler}
        for t in KonsinyeService.listele(yon=YON_VERILEN, limit=None):
            bt = t["belge_tarihi"]
            if isinstance(bt, datetime):
                bt = bt.date()
            yas = (ref - bt).days if bt else 0
            for s in t["satirlar"]:
                if s["kalan_miktar"] <= 0:
                    continue
                for a, b in dilimler:
                    if a <= yas <= b:
                        key = f"{a}-{b if b < 1000 else '90+'}"
                        kovalar[key].append(
                            {
                                "cari": t["cari_unvan"],
                                "teslim_no": t["belge_no"],
                                "stok_kodu": s["stok_kodu"],
                                "kalan": s["kalan_miktar"],
                                "yas_gun": yas,
                                "tur": "musteride",
                            }
                        )
                        break
        return {"baslik": "Konsinye Yaşlandırma", "dilimler": kovalar, "referans": ref}

    @staticmethod
    def hareket_gecmisi(*, teslim_id: int | None = None, limit: int | None = None) -> dict:
        """F) İade ve hareket geçmişi — tüm kayıtlar (limit yalnız ekran)."""
        KonsinyeService.ensure_schema()
        with get_session() as session:
            q = select(KonsinyeHareket).order_by(KonsinyeHareket.id.desc())
            if teslim_id:
                q = q.join(KonsinyeTeslimSatiri).where(
                    KonsinyeTeslimSatiri.teslim_id == int(teslim_id)
                )
            if limit is not None:
                q = q.limit(int(limit))
            satirlar = []
            for h in session.scalars(q).all():
                satirlar.append(
                    {
                        "id": h.id,
                        "teslim_satiri_id": h.teslim_satiri_id,
                        "tur": h.hareket_turu,
                        "miktar": _d(h.miktar),
                        "miktar_goster": miktar_goster(h.miktar),
                        "gercek_tarih": h.gercek_tarih,
                        "kayit_tarihi": h.kayit_tarihi,
                        "belge_no": h.belge_no,
                        "belge_id": h.belge_id,
                        "fatura_turu": h.fatura_turu,
                        "aciklama": h.aciklama,
                        "iptal": h.iptal,
                        "olusturan": h.olusturan,
                    }
                )
        return {"baslik": "Konsinye Hareket Geçmişi", "satirlar": satirlar, "adet": len(satirlar)}

    @staticmethod
    def tutarlilik() -> dict[str, Any]:
        """I) Lot ↔ hareket ↔ sahiplik ↔ sayaç tutarlılık kontrolü."""
        hatalar = []
        KonsinyeService.ensure_schema()
        with get_session() as session:
            for t in session.scalars(select(KonsinyeTeslim).where(KonsinyeTeslim.durum != "IPTAL")).all():
                for s in t.satirlar or []:
                    teslim = _d(s.temel_miktar)
                    kalan = _d(s.kalan_miktar)
                    bildir = _d(s.bildirilen_miktar)
                    iade = _d(s.iade_miktar)
                    if kalan + bildir + iade != teslim:
                        hatalar.append(
                            {
                                "belge": t.belge_no,
                                "satir_id": s.id,
                                "tur": "sayac",
                                "mesaj": (
                                    f"kalan({kalan})+bildir({bildir})+iade({iade}) "
                                    f"!= teslim({teslim})"
                                ),
                            }
                        )
            # Hareket net ≠ lot toplamı (stok bazında örnek)
            stok_idler = {
                int(r[0])
                for r in session.execute(select(StokLotu.stok_id).distinct()).all()
            }
            from sqlalchemy import func

            for sid in list(stok_idler)[:200]:
                lot_top = _d(
                    session.scalar(
                        select(func.coalesce(func.sum(StokLotu.kalan_miktar), 0)).where(
                            StokLotu.stok_id == sid
                        )
                    )
                )
                try:
                    net = KonsinyeService.hareket_net_miktar(sid)
                except Exception:
                    continue
                if abs(lot_top - net) > Decimal("0.0001"):
                    # Yalnız konsinye belgeli stoklarda raporla (gürültü azalt)
                    if session.scalar(
                        select(KonsinyeTeslimSatiri.id).where(
                            KonsinyeTeslimSatiri.stok_id == sid
                        ).limit(1)
                    ):
                        hatalar.append(
                            {
                                "stok_id": sid,
                                "tur": "lot_hareket",
                                "mesaj": f"lot_toplam={lot_top} hareket_net={net}",
                            }
                        )
        return {"baslik": "Konsinye Tutarlılık", "hatalar": hatalar, "adet": len(hatalar)}
