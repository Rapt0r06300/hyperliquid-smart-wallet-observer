"""Dashboard v2 — le compteur POSITIONS suit la vérité canonique active.

Carry reste historiquement surfacé dans le dashboard pour compatibilité/diagnostic, mais il est hors
périmètre du runtime officiel et forcé OFF par le lanceur. Le compteur principal ne doit donc plus
additionner artificiellement copy + carry lorsqu'une ancienne vue carry existe encore.
"""
from __future__ import annotations

import hl_observer.ui.dashboard_v2 as d


def _html() -> str:
    for attr in ("PAGE", "HTML", "PAGE_HTML", "INDEX_HTML", "_PAGE"):
        v = getattr(d, attr, None)
        if isinstance(v, str) and "HYPERSMART" in v:
            return v
    return "\n".join(v for v in vars(d).values() if isinstance(v, str))


def test_le_compteur_positions_reste_ancre_sur_la_verite_canonique_active():
    html = _html()
    assert "syncTop" in html, "la fonction d'unification syncTop doit exister"
    assert "_copyPos" in html, "le compte canonique des positions paper doit être stocké"
    assert "cp+cy" not in html and "cp + cy" not in html, (
        "Carry est hors scope du runtime officiel : il ne doit pas gonfler le compteur principal"
    )
    # Les éléments legacy carry peuvent rester visibles comme diagnostic sans devenir source de vérité.
    assert "_carryPos" in html and 'id="carry-sub"' in html
    assert 'id="pos-bd"' in html, "le détail du compteur doit rester affiché"
