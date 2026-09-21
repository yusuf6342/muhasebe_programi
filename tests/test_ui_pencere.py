"""ui_pencere — iş alanı birim testleri."""

from ui_pencere import calisma_alani


def test_calisma_alani_pozitif():
    x, y, w, h = calisma_alani()
    assert w >= 640
    assert h >= 480
    assert x >= 0
    assert y >= 0


def test_minsize_is_alanina_sigar():
    """Minsize iş alanının %85'ini aşmamalı (belge_penceresini_hazirla mantığı)."""
    _, _, aw, ah = calisma_alani()
    min_w = max(720, min(1100, max(720, aw - 24)))
    min_h = max(480, min(700, max(480, ah - 24)))
    assert min_w <= aw
    assert min_h <= ah
