"""Fail-closed tests for funding settlements lacking exact point-in-time valuation."""
from __future__ import annotations

import sys
from decimal import Decimal
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))

from hl_observer.backtesting.copy_vault_causal_selection import cluster_metaorders  # noqa: E402
from hl_observer.backtesting.copy_vault_executable import execute_metaorder  # noqa: E402

HEURE_MS = 3_600_000


def _entry(event_id: str, ts_ms: int, *, direction: int = 1) -> dict:
    """Mêmes champs que la fixture de `test_copy_vault_executable.py` : `dir`, `taille_usd`
    et `move_frac` sont requis par `cluster_metaorders`, sans quoi aucun cluster ne sort."""
    return {
        "event_id": event_id, "ts_ms": ts_ms, "coin": "BTC", "direction": direction,
        "action": "ADD", "dir": "Open Long" if direction > 0 else "Open Short",
        "vault": "0xA", "taille_usd": 100.0, "move_frac": 0.01,
    }


def _book(ts_ms: int, bid: float, ask: float, *, line: int = 1) -> dict:
    capacite = 1_000_000.0
    return {
        "coin": "BTC", "ts_ms": ts_ms, "bid": bid, "ask": ask,
        "capacity_usd": capacite,
        "bids5": [[bid, capacite / bid]], "asks5": [[ask, capacite / ask]],
        "source_line": line, "causal_observation": False,
    }


#: L'entrée se fait au signal + délai de copie (60 s) ; la sortie à l'entrée + horizon.
DELAI_COPIE_MS = 60_000
HORIZON_MS = 300_000


def _episode(*, enjambe: bool, direction: int = 1) -> tuple[dict, list[dict]]:
    """Un épisode dont la frontière horaire tombe STRICTEMENT à l'intérieur (ou dehors).

    `enjambe=True`  : signal 3 400 000 → entrée 3 460 000, sortie 3 760 000.
                      La frontière de 3 600 000 est strictement entre les deux.
    `enjambe=False` : signal 3 700 000 → entrée 3 760 000, sortie 4 060 000.
                      Aucune frontière (la suivante est à 7 200 000).
    """
    signal = 3_400_000 if enjambe else 3_700_000
    entree = signal + DELAI_COPIE_MS
    sortie = entree + HORIZON_MS
    metaordre = cluster_metaorders([_entry("f1", signal, direction=direction)])[0][0]
    livres = [
        _book(signal - 10_000, 99.0, 101.0, line=1),
        _book(entree, 100.0, 102.0, line=2),
        _book(sortie, 109.0, 111.0, line=3),
    ]
    return metaordre, livres


def _taux(valeur: str = "0.0001") -> dict[str, list[tuple[int, Decimal]]]:
    """Un règlement à CHAQUE frontière horaire, du début à 3 heures."""
    return {"BTC": [(h * HEURE_MS, Decimal(valeur)) for h in range(0, 4)]}


def test_sans_frontiere_franchie_rien_ne_change() -> None:
    metaordre, livres = _episode(enjambe=False)
    trade, raison = execute_metaorder(metaordre, livres, horizon_ms=300_000)
    assert trade is not None, raison
    assert raison == "LIQUIDATABLE_NET"


def test_SANS_taux_fournis_la_porte_refuse_comme_avant() -> None:
    """Le comportement par défaut ne bouge pas d'un iota."""
    metaordre, livres = _episode(enjambe=True)
    trade, raison = execute_metaorder(metaordre, livres, horizon_ms=300_000)
    assert trade is None
    assert raison == "FUNDING_BOUNDARY_UNPRICED"


def test_AVEC_taux_sans_valeur_exacte_le_reglement_reste_bloque() -> None:
    metaordre, livres = _episode(enjambe=True)
    trade, raison = execute_metaorder(
        metaordre, livres, horizon_ms=300_000,
        taux_funding=_taux(), couverture_funding_ms=(0, 4 * HEURE_MS),
    )
    assert trade is None
    assert raison == "FUNDING_SETTLEMENT_VALUATION_UNAVAILABLE"


def test_taux_positif_ne_permet_pas_de_faire_passser_un_long_sans_oracle() -> None:
    metaordre, livres = _episode(enjambe=True, direction=1)
    trade, reason = execute_metaorder(
        metaordre, livres, horizon_ms=300_000,
        taux_funding=_taux("0.0001"), couverture_funding_ms=(0, 4 * HEURE_MS),
    )
    assert trade is None
    assert reason == "FUNDING_SETTLEMENT_VALUATION_UNAVAILABLE"


def test_l_equation_de_conservation_du_net_reste_INTACTE() -> None:
    """Le funding ne doit JAMAIS entrer dans `net_pnl_usd` : la réconciliation en dépend."""
    metaordre, livres = _episode(enjambe=False)
    trade, _ = execute_metaorder(metaordre, livres, horizon_ms=300_000)
    assert trade is not None
    # Le net reste la pure economie d'execution, reconciliee : gross - spread - fees -
    # slippage - latency. Il ne contient pas le portage.
    recompose = (trade["gross_pnl_usd"] - trade["spread_cost_usd"] - trade["fees_usd"]
                 - trade["slippage_cost_usd"] - trade["latency_cost_usd"])
    assert abs(trade["net_pnl_usd"] - recompose) < 1e-8
    assert trade["net_after_carry_usd"] == trade["net_pnl_usd"]
    assert trade["carry_status"] == "MEASURED_ZERO_NO_SETTLEMENT_CROSSED"


def test_des_taux_qui_NE_COUVRENT_PAS_l_episode_sont_REFUSES() -> None:
    """Fail-closed : ne pas savoir ce qui a été payé n'autorise pas à supposer zéro."""
    metaordre, livres = _episode(enjambe=True)
    trade, raison = execute_metaorder(
        metaordre, livres, horizon_ms=300_000,
        taux_funding=_taux(), couverture_funding_ms=(2 * HEURE_MS, 4 * HEURE_MS),
    )
    assert trade is None
    assert raison == "FUNDING_BOUNDARY_RATE_UNOBSERVED", raison


def test_un_coin_SANS_taux_est_REFUSE_et_non_suppose_gratuit() -> None:
    metaordre, livres = _episode(enjambe=True)
    trade, raison = execute_metaorder(
        metaordre, livres, horizon_ms=300_000,
        taux_funding={"ETH": [(0, Decimal("0.0001"))]},
        couverture_funding_ms=(0, 4 * HEURE_MS),
    )
    assert trade is None
    assert raison == "FUNDING_BOUNDARY_RATE_UNOBSERVED", raison


def _episode_frontiere_sur(instant: str) -> tuple[dict, list[dict]]:
    """Un épisode dont la frontière horaire tombe EXACTEMENT sur l'entrée ou la sortie.

    entrée = signal + 60 s, sortie = entrée + 300 s. On choisit donc le signal pour que l'un
    des deux coïncide avec 3 600 000 ms.
    """
    signal = (HEURE_MS - DELAI_COPIE_MS if instant == "entree"
              else HEURE_MS - DELAI_COPIE_MS - HORIZON_MS)
    entree = signal + DELAI_COPIE_MS
    sortie = entree + HORIZON_MS
    attendu = entree if instant == "entree" else sortie
    assert attendu % HEURE_MS == 0, "la fixture doit poser la frontiere PILE sur l'instant visé"
    metaordre = cluster_metaorders([_entry("f1", signal)])[0][0]
    livres = [
        _book(signal - 10_000, 99.0, 101.0, line=1),
        _book(entree, 100.0, 102.0, line=2),
        _book(sortie, 109.0, 111.0, line=3),
    ]
    return metaordre, livres


def test_une_frontiere_PILE_SUR_L_ENTREE_reste_refusee_MEME_avec_les_taux() -> None:
    """L'ordre fill/funding est inconnu : aucun taux ne lève cette ambiguïté.

    ⚠️ Cette garde manquait : l'injection « la frontiere AMBIGUE devient chiffrable » laissait
    les sept premiers tests VERTS, parce qu'aucun n'exerçait ce cas. Sixième zone aveugle de la
    session, trouvée par injection comme les autres.
    """
    metaordre, livres = _episode_frontiere_sur("entree")
    trade, raison = execute_metaorder(
        metaordre, livres, horizon_ms=HORIZON_MS,
        taux_funding=_taux(), couverture_funding_ms=(0, 4 * HEURE_MS),
    )
    assert trade is None
    assert raison == "FUNDING_BOUNDARY_UNPRICED", raison


def test_une_frontiere_PILE_SUR_LA_SORTIE_reste_refusee_MEME_avec_les_taux() -> None:
    metaordre, livres = _episode_frontiere_sur("sortie")
    trade, raison = execute_metaorder(
        metaordre, livres, horizon_ms=HORIZON_MS,
        taux_funding=_taux(), couverture_funding_ms=(0, 4 * HEURE_MS),
    )
    assert trade is None
    assert raison == "FUNDING_BOUNDARY_UNPRICED", raison
