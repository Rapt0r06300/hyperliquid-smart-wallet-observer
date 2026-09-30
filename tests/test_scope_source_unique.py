"""P0 — UNE SEULE vérité de scope.

`strategies.active_scope` est l'autorité UNIQUE. Aucun autre module (dont `ops.paper_canonique`) ne
doit redéclarer une allowlist qui diverge. Ce test ÉCHOUE si deux manifests de scope divergent, et
prouve qu'une famille SHADOW (twap_metaorder) ou DISABLED (carry) ne peut pas émettre d'intent
économique via le moteur canonique.
"""

import sys
from pathlib import Path

import pytest

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE / "src"))

from hl_observer.strategies import active_scope as AS  # noqa: E402
from hl_observer.ops import paper_canonique as PC  # noqa: E402


def test_paper_canonique_ne_diverge_pas_de_lautorite():
    # Le manifeste de paper_canonique EST celui de l'autorité — sinon ce test échoue.
    assert set(PC.STRATEGIES_ACTIVES) == set(AS.active_strategy_families())


def test_une_famille_shadow_ne_peut_pas_emettre_un_intent():
    assert AS.strategy_scope_status("twap_metaorder") is AS.StrategyScopeStatus.SHADOW
    with pytest.raises(PC.ScopeViolation):
        PC.PaperIntent(strategy="twap_metaorder", coin="BTC", side=1,
                       notional_usd=50.0, signal_observable_at_ms=1)


def test_le_carry_disabled_ne_peut_pas_emettre_un_intent():
    assert AS.strategy_scope_status("funding_carry") is AS.StrategyScopeStatus.DISABLED
    with pytest.raises(PC.ScopeViolation):
        PC.PaperIntent(strategy="carry", coin="BTC", side=1, notional_usd=50.0, signal_observable_at_ms=1)


def test_chaque_famille_active_peut_emettre_un_intent():
    familles = AS.active_strategy_families()
    assert familles  # non vide
    for fam in familles:
        i = PC.PaperIntent(strategy=fam, coin="BTC", side=1, notional_usd=50.0, signal_observable_at_ms=1)
        assert i.as_dict()["strategy"] == fam and i.as_dict()["real_execution"] is False


def test_aucune_seconde_allowlist_codee_en_dur_dans_paper_canonique():
    # Garde-fou anti-régression : paper_canonique doit DÉRIVER le scope, pas re-hardcoder un tuple concurrent.
    src = (RACINE / "src" / "hl_observer" / "ops" / "paper_canonique.py").read_text(encoding="utf-8")
    assert "active_strategy_families" in src, "paper_canonique doit dériver le scope de l'autorité"
    assert '("cross_venue_dislocation", "lead_lag"' not in src, "liste de scope concurrente détectée"
