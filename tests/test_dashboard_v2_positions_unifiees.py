"""Dashboard v2 — le compteur POSITIONS du haut unifie copy + carry (une seule vérité).
Anti-régression : si le câblage syncTop / le total copy+carry disparaît, ce test casse."""
from __future__ import annotations

import hl_observer.ui.dashboard_v2 as d


def _html() -> str:
    for attr in ("PAGE", "HTML", "PAGE_HTML", "INDEX_HTML", "_PAGE"):
        v = getattr(d, attr, None)
        if isinstance(v, str) and "HYPERSMART" in v:
            return v
    # repli : concatener toutes les constantes str du module
    return "\n".join(v for v in vars(d).values() if isinstance(v, str))


def test_le_compteur_positions_additionne_copy_et_carry():
    html = _html()
    assert "syncTop" in html, "la fonction d'unification syncTop doit exister"
    assert "_copyPos" in html and "_carryPos" in html, "les deux comptes doivent être stockés"
    assert "cp+cy" in html or "cp + cy" in html, "le total doit être copy + carry"
    assert 'id="pos-bd"' in html, "le détail (Nc · My) doit être affiché"
    assert 'id="carry-sub"' in html, "le PnL carry doit être surfacé en haut"
