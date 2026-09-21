"""Satış faturası açılış profili — aşama sürelerini ms cinsinden loglar.

Kullanım:
  .venv\\Scripts\\python.exe tools\\fatura_acilis_profil.py
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


class _Timer:
    def __init__(self):
        self.phases: list[tuple[str, float]] = []
        self._t0 = time.perf_counter()
        self._last = self._t0

    def mark(self, name: str):
        now = time.perf_counter()
        self.phases.append((name, (now - self._last) * 1000))
        self._last = now

    def total_ms(self) -> float:
        return (time.perf_counter() - self._t0) * 1000

    def report(self) -> str:
        lines = [f"{n}: {ms:.1f} ms" for n, ms in self.phases]
        lines.append(f"TOPLAM: {self.total_ms():.1f} ms")
        return "\n".join(lines)


def main():
    timer = _Timer()
    import tkinter as tk

    timer.mark("import_tkinter")

    # Firma/oturum — main.py benzeri
    from database.database import company_db, get_session
    from database.session_manager import oturum

    timer.mark("import_database_session")

    # Aktif şirket bağla (varsa)
    try:
        from database.system.bootstrap import ensure_system_ready

        ensure_system_ready()
        timer.mark("system_bootstrap")
    except Exception as exc:
        timer.mark(f"system_bootstrap_skip:{exc}")

    # company_db yolu
    try:
        # oturum zaten set edilmiş olabilir; değilse son kullanılan firmayı dene
        if not getattr(oturum, "company_id", None):
            print("UYARI: oturum.company_id yok — DB sorguları başarısız olabilir")
    except Exception:
        pass
    timer.mark("oturum_kontrol")

    import app as app_mod

    timer.mark("import_app")

    from app import SatisFaturasiDialog
    from database.cari_service import CariService
    from database.satis_siparisi_service import SatisSiparisiService
    from database.satis_personeli import aktif_satis_personelleri
    from database.stok_service import StokService
    from app import fatura_kolon_ayarlari_yukle

    timer.mark("import_services")

    # Ayrı ayrı DB ölçümü
    t = time.perf_counter()
    try:
        m = SatisSiparisiService.aktif_musterileri()
        print(f"  [db] aktif_musterileri: {(time.perf_counter()-t)*1000:.1f} ms (n={len(m)})")
    except Exception as e:
        print(f"  [db] aktif_musterileri ERR: {e}")
    timer.mark("probe_aktif_musterileri")

    t = time.perf_counter()
    try:
        b = list(CariService.listele(hizli=True))
        print(f"  [db] cari_listele_hizli: {(time.perf_counter()-t)*1000:.1f} ms (n={len(b)})")
    except Exception as e:
        print(f"  [db] cari_listele_hizli ERR: {e}")
    timer.mark("probe_cari_listele")

    t = time.perf_counter()
    try:
        p = aktif_satis_personelleri()
        print(f"  [db] satis_personeli: {(time.perf_counter()-t)*1000:.1f} ms (n={len(p)})")
    except Exception as e:
        print(f"  [db] satis_personeli ERR: {e}")
    timer.mark("probe_satis_personeli")

    t = time.perf_counter()
    try:
        s = StokService.stoklari_ara("")
        print(f"  [db] stoklari_ara(''): {(time.perf_counter()-t)*1000:.1f} ms (n={len(s)})")
    except Exception as e:
        print(f"  [db] stoklari_ara ERR: {e}")
    timer.mark("probe_stok_bos")

    t = time.perf_counter()
    fatura_kolon_ayarlari_yukle()
    print(f"  [fs] kolon_ayarlari: {(time.perf_counter()-t)*1000:.1f} ms")
    timer.mark("probe_kolon")

    # Instrument dialog methods
    orig_init_sip = app_mod.SatisSiparisiDialog.__init__
    orig_init_fat = SatisFaturasiDialog.__init__
    marks = []

    def timed_sip(self, parent, siparis=None, cari=None):
        marks.append(("siparis_dialog_start", time.perf_counter()))
        # Patch musteri load
        from database import satis_siparisi_service as sss

        real = sss.SatisSiparisiService.aktif_musterileri

        def wrapped():
            t0 = time.perf_counter()
            r = real()
            marks.append((f"aktif_musterileri_n={len(r)}", time.perf_counter() - t0))
            return r

        sss.SatisSiparisiService.aktif_musterileri = staticmethod(wrapped)
        try:
            orig_init_sip(self, parent, siparis=siparis, cari=cari)
        finally:
            sss.SatisSiparisiService.aktif_musterileri = real
        marks.append(("siparis_dialog_end", time.perf_counter()))

    def timed_fat(self, parent, fatura=None, cari=None, siparis=None, irsaliye=None, cari_ac=None):
        marks.clear()
        t_start = time.perf_counter()
        marks.append(("fatura_start", t_start))

        # Wrap key methods
        wraps = {}
        for name in (
            "_ek_fatura_bilgileri",
            "_fatura_onay_cubugu_olustur",
            "_fatura_satir_baglantilari",
            "_fatura_gorunumu_sikistir",
            "_fatura_alt_ozet_kur",
            "_fatura_satir_etkilesim_kur",
            "_fatura_musteri_listesini_bakiyeli_kur",
            "_toplamlari_guncelle",
            "_fatura_kilit_uygula",
            "_fatura_dogrulama_guncelle",
            "_metinleri_faturaya_cevir",
        ):
            if hasattr(SatisFaturasiDialog, name):
                orig = getattr(SatisFaturasiDialog, name)

                def make(n, o):
                    def w(slf, *a, **k):
                        t0 = time.perf_counter()
                        r = o(slf, *a, **k)
                        marks.append((n, time.perf_counter() - t0))
                        return r

                    return w

                wraps[name] = orig
                setattr(SatisFaturasiDialog, name, make(name, orig))

        # Also wrap CariService.listele
        from database import cari_service as cs

        real_listele = cs.CariService.listele

        def listele_w(*a, **k):
            t0 = time.perf_counter()
            r = real_listele(*a, **k)
            marks.append((f"CariService.listele(hizli={k.get('hizli')})", time.perf_counter() - t0))
            return r

        cs.CariService.listele = staticmethod(listele_w)

        app_mod.SatisSiparisiDialog.__init__ = timed_sip
        try:
            orig_init_fat(
                self, parent, fatura=fatura, cari=cari, siparis=siparis, irsaliye=irsaliye, cari_ac=cari_ac
            )
        finally:
            app_mod.SatisSiparisiDialog.__init__ = orig_init_sip
            for n, o in wraps.items():
                setattr(SatisFaturasiDialog, n, o)
            cs.CariService.listele = real_listele
        marks.append(("fatura_end_total", time.perf_counter() - t_start))

    SatisFaturasiDialog.__init__ = timed_fat

    root = tk.Tk()
    root.withdraw()
    timer.mark("tk_root")

    print("\n=== DIALOG AÇILIŞI ===")
    t_vis = time.perf_counter()
    dlg = SatisFaturasiDialog(root)
    dlg.update_idletasks()
    visible_ms = (time.perf_counter() - t_vis) * 1000
    print(f"Pencere görünür (update_idletasks): {visible_ms:.1f} ms")

    for item in marks:
        if isinstance(item[1], float) and item[0] not in ("fatura_start", "siparis_dialog_start", "siparis_dialog_end"):
            if item[0] == "fatura_end_total":
                print(f"  {item[0]}: {item[1]*1000:.1f} ms")
            elif item[1] < 100:  # likely delta seconds
                print(f"  {item[0]}: {item[1]*1000:.1f} ms")
            else:
                print(f"  {item[0]}: {item[1]}")

    try:
        dlg.destroy()
    except Exception:
        pass
    root.destroy()

    print("\n=== ÖN HAZIRLIK ===")
    print(timer.report())


if __name__ == "__main__":
    main()
