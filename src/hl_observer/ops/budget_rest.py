r"""Le budget REST commun : chaque collecteur déclare ce qu'il CONSOMME vraiment (amélioration n° 22).

Hyperliquid limite le poids REST à 1 200 par minute et par IP, partagé par tous les collecteurs de la
machine. `rest_budget.json` ne recensait que deux consommateurs (la garde REST↔WS et l'ombre des
métaordres), déclarés par estimation. Les six autres — mids, carnets, vaults, rattrapage des fills,
des bougies et du funding, poll des fills — appelaient sans rien dire : le total affiché (~236/min)
ignorait l'essentiel, et un 429 arrivait sans que personne ne sache qui avait tout pris.

Ici, chaque requête RÉUSSIE est pesée selon la règle publiée (même règle que
`sonde_confirmation_vaults.poids_info`) et cumulée sur une fenêtre glissante d'une minute ; au plus
une écriture par minute et par source, au format déjà lu par `budget_total`. Ne bloque jamais une
requête et ne lève jamais : un budget non écrit n'arrête pas la collecte.
"""
from __future__ import annotations

import json
import os
import sys
import threading
import time
from collections import deque
from pathlib import Path

RACINE = Path(__file__).resolve().parents[3]
FICHIER = Path("runtime") / "data" / "rest_budget.json"
LIMITE_IP_PAR_MIN = 1200
FENETRE_S = 60.0

_LEGERS = {"l2Book", "allMids", "clearinghouseState", "orderStatus", "spotClearinghouseState", "exchangeStatus"}
_PAGINES = {"userFills", "userFillsByTime", "userTwapSliceFills", "userTwapSliceFillsByTime", "twapHistory",
            "recentTrades", "historicalOrders", "fundingHistory", "userFunding", "nonUserFundingUpdates",
            "delegatorHistory", "delegatorRewards", "validatorStats", "userNonFundingLedgerUpdates"}


def poids(type_info: str, n_items: int = 0) -> int:
    """Poids publié d'un appel `info` : 2 léger, 60 `userRole`, 20 sinon ; +1 par 20 éléments rendus
    pour les réponses paginées, +1 par 60 bougies pour `candleSnapshot`."""
    n = max(0, int(n_items or 0))
    base = 2 if type_info in _LEGERS else (60 if type_info == "userRole" else 20)
    if type_info in _PAGINES:
        base += n // 20
    elif type_info == "candleSnapshot":
        base += n // 60
    return base


_VERROU = threading.Lock()
_FENETRES: dict[tuple[str, str], deque] = {}
_DERNIERE_ECRITURE: dict[tuple[str, str], float] = {}


def _source_par_defaut() -> str:
    return Path(sys.argv[0] or "inconnu").stem or "inconnu"


def compter(type_info: str, n_items: int = 0, *, source: str | None = None, root: Path | None = None,
            horloge=time.monotonic, ecrire: bool = True) -> int:
    """Pèse un appel réussi et, au plus une fois par minute, publie le poids de la dernière minute."""
    try:
        racine = str(Path(root) if root is not None else RACINE)
        nom = source or _source_par_defaut()
        cle = (racine, nom)
        maintenant = horloge()
        p = poids(type_info, n_items)
        with _VERROU:
            fen = _FENETRES.setdefault(cle, deque())
            fen.append((maintenant, p))
            while fen and maintenant - fen[0][0] > FENETRE_S:
                fen.popleft()
            total = sum(x[1] for x in fen)
            # Sous pytest, on n'écrit JAMAIS dans le vrai runtime : seulement dans la racine du test.
            sous_test = root is None and bool(os.environ.get("PYTEST_CURRENT_TEST"))
            a_ecrire = (ecrire and not sous_test
                        and maintenant - _DERNIERE_ECRITURE.get(cle, -1e18) >= FENETRE_S)
            if a_ecrire:
                _DERNIERE_ECRITURE[cle] = maintenant
        if a_ecrire:
            publier(Path(racine), nom, total)
        return p
    except Exception:  # noqa: BLE001 - le budget ne doit jamais casser une requête
        return 0


def publier(root: Path, source: str, poids_derniere_minute: int) -> None:
    """Fusionne l'entrée de `source` dans `rest_budget.json` (format de `journaliser_budget`)."""
    chemin = Path(root) / FICHIER
    try:
        cur = json.loads(chemin.read_text(encoding="utf-8"))
        if not isinstance(cur, dict):
            cur = {}
    except (OSError, ValueError):
        cur = {}
    cur[source] = {"poids_par_passe": int(poids_derniere_minute), "intervalle_s": FENETRE_S,
                   "poids_par_min_moyen": float(poids_derniere_minute), "mesure": "REELLE_FENETRE_60S",
                   "ts_ms": int(time.time() * 1000)}
    try:
        chemin.parent.mkdir(parents=True, exist_ok=True)
        tmp = chemin.with_name(f"{chemin.name}.{os.getpid()}.tmp")
        tmp.write_text(json.dumps(cur, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(tmp, chemin)
    except OSError:
        pass
