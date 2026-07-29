"""DÉMARRAGE ÉTALÉ + BUDGET DE RECONNEXIONS (IDEA-7, IDEA-8).

IDEA-7 — staggered startup : démarrer tous les collecteurs/abonnements dans la même milliseconde crée un
burst (thundering herd) qui déclenche les rate limits Hyperliquid (10 connexions/IP, 30 nouvelles
connexions/minute, 2000 messages/minute). On échelonne donc les démarrages avec un décalage déterministe
+ un jitter stable par nom (reproductible : le même nom donne toujours le même décalage).

IDEA-8 — reconnexion intelligente : exponential backoff + jitter (déjà présents dans
`realtime/ws_resilience.delai_reconnexion_ms` et `collection/backoff`), auxquels ce module ajoute ce qui
manquait : la GRACE PERIOD (une connexion qui a tenu longtemps repart au premier échelon) et le BUDGET de
reconnexions par fenêtre glissante (au-delà : on refuse de reconnecter et on le dit, plutôt que de marteler
la source et de se faire bannir).

0 réseau (calcul pur), 0 ordre, paper-only.
"""
from __future__ import annotations

import hashlib

ECART_DEFAUT_MS = 750.0            # décalage nominal entre deux démarrages
JITTER_FRAC = 0.25                 # ±25 % de jitter déterministe par nom
BUDGET_DEFAUT = 20                 # reconnexions max par fenêtre
FENETRE_BUDGET_MS = 60_000.0       # fenêtre glissante du budget (1 min, aligné sur la limite HL)
GRACE_PERIOD_MS = 120_000.0        # connexion stable > 2 min -> l'escalade du backoff est remise à zéro


def _jitter_stable(nom: str) -> float:
    """Jitter déterministe dans [-1, +1] dérivé du nom : reproductible d'un run à l'autre (donc testable),
    mais différent d'un collecteur à l'autre (donc désynchronisant)."""
    h = hashlib.sha256(str(nom).encode("utf-8")).hexdigest()
    return (int(h[:8], 16) / 0xFFFFFFFF) * 2.0 - 1.0


def plan_demarrage(noms, *, ecart_ms: float = ECART_DEFAUT_MS, jitter_frac: float = JITTER_FRAC) -> list:
    """IDEA-7 — rend [(nom, delai_ms)] : délais croissants et désynchronisés. Le premier part immédiatement
    (delai 0) pour ne pas retarder inutilement le run ; les suivants sont étalés."""
    plan = []
    for i, nom in enumerate(noms or []):
        base = float(ecart_ms) * i
        delai = max(0.0, base * (1.0 + float(jitter_frac) * _jitter_stable(nom))) if i else 0.0
        plan.append((nom, round(delai, 1)))
    return plan


class BudgetReconnexions:
    """IDEA-8 — budget de reconnexions par fenêtre glissante + grace period.

    `autoriser(nom, maintenant_ms, connecte_depuis_ms)` rend un verdict explicite :
      • autorise=False si le budget de la fenêtre est épuisé (motif BUDGET_EPUISE) — on ne martèle pas ;
      • `essai` repart à 0 si la connexion a tenu plus que la grace period (elle était saine) ;
      • `delai_ms` = backoff exponentiel plafonné + jitter déterministe."""

    def __init__(self, *, budget: int = BUDGET_DEFAUT, fenetre_ms: float = FENETRE_BUDGET_MS,
                 grace_ms: float = GRACE_PERIOD_MS, base_ms: float = 500.0, max_ms: float = 30_000.0):
        self.budget = int(budget)
        self.fenetre_ms = float(fenetre_ms)
        self.grace_ms = float(grace_ms)
        self.base_ms = float(base_ms)
        self.max_ms = float(max_ms)
        self._hist: dict = {}                # nom -> [timestamps ms]
        self._essais: dict = {}              # nom -> compteur d'échecs consécutifs

    def _purger(self, nom: str, maintenant_ms: float):
        h = self._hist.setdefault(nom, [])
        limite = float(maintenant_ms) - self.fenetre_ms
        self._hist[nom] = [t for t in h if t >= limite]
        return self._hist[nom]

    def autoriser(self, nom: str, *, maintenant_ms: float, connecte_depuis_ms: float | None = None) -> dict:
        h = self._purger(nom, maintenant_ms)
        if connecte_depuis_ms is not None and float(connecte_depuis_ms) >= self.grace_ms:
            self._essais[nom] = 0                       # la connexion était stable : on ne pénalise pas
        if len(h) >= self.budget:
            plus_ancien = min(h) if h else float(maintenant_ms)
            return {"autorise": False, "motif": "BUDGET_EPUISE",
                    "restant": 0, "reessai_possible_dans_ms": round(self.fenetre_ms - (float(maintenant_ms) - plus_ancien), 1)}
        essai = int(self._essais.get(nom, 0))
        delai = min(self.max_ms, self.base_ms * (2 ** essai))
        delai = max(0.0, delai * (1.0 + JITTER_FRAC * _jitter_stable("%s#%d" % (nom, essai))))
        return {"autorise": True, "motif": "OK", "essai": essai, "delai_ms": round(delai, 1),
                "restant": self.budget - len(h)}

    def enregistrer(self, nom: str, *, maintenant_ms: float, succes: bool) -> dict:
        """Consomme une unité de budget. Un succès remet l'escalade à zéro, un échec l'incrémente."""
        self._purger(nom, maintenant_ms)
        self._hist.setdefault(nom, []).append(float(maintenant_ms))
        self._essais[nom] = 0 if succes else int(self._essais.get(nom, 0)) + 1
        return {"nom": nom, "essais_consecutifs": self._essais[nom],
                "utilises_dans_fenetre": len(self._hist[nom]), "budget": self.budget}


__all__ = ["plan_demarrage", "BudgetReconnexions", "ECART_DEFAUT_MS", "JITTER_FRAC",
           "BUDGET_DEFAUT", "FENETRE_BUDGET_MS", "GRACE_PERIOD_MS"]
