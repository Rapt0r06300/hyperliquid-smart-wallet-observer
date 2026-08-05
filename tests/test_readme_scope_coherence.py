"""AUD-016 — Le README ne doit JAMAIS contredire l'autorité de scope.

`strategies.active_scope` est l'UNIQUE vérité du scope économique (V2). Le README public
présentait au contraire Carry (famille DISABLED) comme le moteur « en production paper / actif »,
et Copy (famille ACTIVE) comme « verrouillé » — l'inverse exact du scope. Ce faux-vert au niveau
documentaire est précisément AUD-016. Ce test échoue si le README réintroduit cette contradiction.
0 réseau.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE / "src"))

from hl_observer.strategies.active_scope import active_strategy_families  # noqa: E402

README = (RACINE / "README.md").read_text(encoding="utf-8")

# Étiquettes humaines attendues pour chaque famille ACTIVE de l'autorité.
_LABELS_ACTIFS = {
    "copy_vault": ("copy",),
    "lead_lag": ("lead-lag", "lead lag"),
    "cross_venue_dislocation": ("cross-venue", "dislocation"),
}


def test_autorite_scope_est_bien_les_trois_familles():
    # Verrou : si l'autorité change, ce test le force à rester cohérent avec le README.
    assert active_strategy_families() == frozenset(_LABELS_ACTIFS)


def test_readme_ne_presente_pas_carry_comme_moteur_actif():
    bas = README.lower()
    assert "en production paper (carry)" not in bas, (
        "README: 'en production paper (Carry)' contredit active_scope (funding_carry DISABLED)."
    )
    # Aucune ligne de tableau 'Carry ... | actif' : Carry est DISABLED_BY_SCOPE.
    for ligne in README.splitlines():
        l = ligne.lower()
        if re.match(r"^\|\s*\*\*carry", l):
            assert "actif" not in l, f"README: Carry (DISABLED) marqué actif -> {ligne!r}"


def test_readme_declare_carry_disabled_by_scope():
    assert "DISABLED_BY_SCOPE" in README, (
        "README doit déclarer Carry hors scope (DISABLED_BY_SCOPE) pour s'aligner sur l'autorité."
    )


def test_readme_mentionne_chaque_famille_active():
    bas = README.lower()
    for famille, labels in _LABELS_ACTIFS.items():
        assert any(lbl in bas for lbl in labels), (
            f"README ne mentionne aucune étiquette de la famille active {famille}: {labels}"
        )
