"""AUD-158 — property-based testing : invariants sur des ENTREES GENEREES (seedees, deterministes).

Sans dependance externe (hypothesis absent), on genere des cas aleatoires SEEDES et on verifie des
PROPRIETES qui doivent tenir pour TOUTE entree, pas juste des exemples choisis a la main.
"""
import random

from hl_observer.execution_core.enveloppe_capital_unique import verifier_enveloppe
from hl_observer.simulation.reconciliation_5_vues import VUES, reconcilier_5_vues


def test_propriete_enveloppe_respecte_ssi_somme_sous_master():
    rng = random.Random(20260805)
    for _ in range(500):
        budgets = {str(i): rng.uniform(0, 400) for i in range(rng.randint(0, 5))}
        r = verifier_enveloppe(budgets, master_usd=1000.0)
        assert r["respecte"] == (round(sum(budgets.values()), 6) <= 1000.0 + 1e-9)


def test_propriete_reconciliation_concorde_ssi_toutes_egales():
    rng = random.Random(42)
    for _ in range(500):
        base = rng.uniform(-1000, 1000)
        vals = {v: base for v in VUES}
        if rng.random() < 0.5:
            vals[rng.choice(VUES)] = base + rng.choice([0.0, 5.0, -5.0])
        r = reconcilier_5_vues(vals)
        toutes_egales = all(abs(vals[v] - base) <= 1e-9 for v in VUES)
        assert r["concordent"] == toutes_egales
