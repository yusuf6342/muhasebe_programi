"""Kaynak→hedef kimlik eşlemesi — devam, tekillik, mükerrer engeli.

Hazırlık: bellekte/diskte eşleme; gerçek hedefe yazmaz.
"""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from tools.dnm_d2.donem_sabitleri import CALISMA_KOK, KAYNAK_FIRMA_NO

KOK = Path(__file__).resolve().parents[2]
ESLEME_YOL = KOK / CALISMA_KOK / "esleme" / "KAYNAK_HEDEF_KIMLIK.json"


@dataclass
class KimlikKayit:
    aile: str  # stok|cari|belge|finans|lot|banka|kasa
    kaynak_id: str
    hedef_id: str | None = None
    kaynak_surum: str | None = None
    acilis_anahtari: str | None = None
    icerik_ozet: str | None = None
    durum: str = "BEKLIYOR"  # BEKLIYOR|ESLENDI|ATLANDI|HATA
    son_guncelleme: str = field(
        default_factory=lambda: datetime.now().astimezone().isoformat(timespec="seconds")
    )


class KimlikDefteri:
    """Kalıcı anahtar: firma + aile + kaynak_id (+ hedef dönem)."""

    def __init__(self, yol: Path | None = None) -> None:
        self.yol = yol or ESLEME_YOL
        self.kayitlar: dict[str, KimlikKayit] = {}
        self._yukle()

    @staticmethod
    def anahtar(aile: str, kaynak_id: str) -> str:
        return f"{KAYNAK_FIRMA_NO}|{aile}|{kaynak_id}"

    def _yukle(self) -> None:
        if not self.yol.is_file():
            return
        ham = json.loads(self.yol.read_text(encoding="utf-8"))
        for k, v in (ham.get("kayitlar") or {}).items():
            self.kayitlar[k] = KimlikKayit(**v)

    def kaydet(self) -> Path:
        self.yol.parent.mkdir(parents=True, exist_ok=True)
        veri = {
            "format": "d2-kimlik-esleme-v1",
            "zaman": datetime.now().astimezone().isoformat(timespec="seconds"),
            "firma": KAYNAK_FIRMA_NO,
            "adet": len(self.kayitlar),
            "kayitlar": {k: asdict(v) for k, v in self.kayitlar.items()},
            "mali_yazim": False,
        }
        self.yol.write_text(json.dumps(veri, ensure_ascii=False, indent=2), encoding="utf-8")
        return self.yol

    def kaydet_esleme(
        self,
        aile: str,
        kaynak_id: str,
        *,
        hedef_id: str | None = None,
        durum: str = "ESLENDI",
        acilis_anahtari: str | None = None,
        icerik_ozet: str | None = None,
        kaynak_surum: str | None = None,
        uzerine_yaz: bool = False,
    ) -> KimlikKayit:
        key = self.anahtar(aile, kaynak_id)
        eski = self.kayitlar.get(key)
        if eski and eski.hedef_id and hedef_id and eski.hedef_id != hedef_id and not uzerine_yaz:
            raise ValueError(
                f"Mükerrer eşleme engellendi: {key} mevcut hedef={eski.hedef_id} yeni={hedef_id}"
            )
        if eski and eski.durum == "ESLENDI" and not uzerine_yaz and hedef_id == eski.hedef_id:
            return eski  # tekrarlı çalışma: yeni etki yok
        kayit = KimlikKayit(
            aile=aile,
            kaynak_id=str(kaynak_id),
            hedef_id=hedef_id,
            kaynak_surum=kaynak_surum,
            acilis_anahtari=acilis_anahtari,
            icerik_ozet=icerik_ozet,
            durum=durum,
        )
        self.kayitlar[key] = kayit
        return kayit

    def resume_adaylari(self, aile: str | None = None) -> list[KimlikKayit]:
        out = []
        for k in self.kayitlar.values():
            if aile and k.aile != aile:
                continue
            if k.durum in {"BEKLIYOR", "HATA"}:
                out.append(k)
        return out


def smoke_mukerrer() -> dict[str, Any]:
    """İzole: aynı kaynak iki kez → tek kayıt."""
    import tempfile

    with tempfile.TemporaryDirectory() as td:
        yol = Path(td) / "kimlik.json"
        d = KimlikDefteri(yol)
        d.kaydet_esleme("stok", "8", hedef_id="H1")
        d.kaydet_esleme("stok", "8", hedef_id="H1")  # no-op
        try:
            d.kaydet_esleme("stok", "8", hedef_id="H2")
            ok_conflict = False
        except ValueError:
            ok_conflict = True
        d.kaydet()
        d2 = KimlikDefteri(yol)
        return {
            "tekil_adet": len(d2.kayitlar),
            "mukerrer_engel": ok_conflict,
            "resume_bos": len(d2.resume_adaylari()) == 0,
            "ok": len(d2.kayitlar) == 1 and ok_conflict,
        }
