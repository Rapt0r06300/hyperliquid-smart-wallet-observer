"""Chiffrer le funding au lieu de refuser l'épisode — sans jamais fabriquer de profit.

CE QUE CE CHANTIER CORRIGE (feu vert opérateur du 22/11/2026). La porte d'exécutabilité
refusait TOUT épisode franchissant une frontière de funding :

    first_possible_funding_ms = next_funding_time_ms(entry_ts_ms - 1, interval_hours=1)
    if first_possible_funding_ms <= int(exit_book["ts_ms"]):
        return None, "FUNDING_BOUNDARY_UNPRICED"

231 candidats sur 1 613 mouraient là. Et le refus était JUSTE tant que le moteur ne déduisait
le funding nulle part : desserrer une porte derrière laquelle aucun coût n'est retiré, c'est
sous-estimer les frais, donc **fabriquer du profit**.

Le correctif respecte quatre contraintes, et chacune a son test :

1. **L'équation de conservation reste intacte.** `net = gross - spread - fees - slippage -
   latency` est réconcilié contre `executable_before_fees - fees`. Le funding n'y entre PAS :
   il vit dans `carry_pnl_usd`, et `net_after_carry_usd` est la somme explicite. Mélanger
   casserait la réconciliation et brouillerait la provenance.
2. **Provenance séparée.** Les taux viennent de `REST_FUNDING_HISTORY`, un rattrapage :
   `causal_forward_eligible: False`. Acceptable pour CHIFFRER après coup, jamais pour DÉCIDER.
3. **Défaut inchangé.** Sans taux fournis, la porte refuse exactement comme avant.
4. **Fail-closed.** Frontière ambiguë (à l'entrée ou à la sortie exacte) → refus. Taux
   indisponibles → refus nommé, jamais un passage favorable.
"""
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


def test_AVEC_taux_une_frontiere_INTERIEURE_devient_chiffrable() -> None:
    metaordre, livres = _episode(enjambe=True)
    trade, raison = execute_metaorder(
        metaordre, livres, horizon_ms=300_000,
        taux_funding=_taux(), couverture_funding_ms=(0, 4 * HEURE_MS),
    )
    assert trade is not None, raison
    assert trade["carry_status"] == "MEASURED"
    assert trade["settlement_crossing_count"] == 1


def test_le_SIGNE_est_juste_un_long_PAIE_a_taux_positif() -> None:
    """Le test qui compte le plus : une erreur de signe ferait d'un coût un revenu."""
    metaordre, livres = _episode(enjambe=True, direction=1)
    trade, _ = execute_metaorder(
        metaordre, livres, horizon_ms=300_000,
        taux_funding=_taux("0.0001"), couverture_funding_ms=(0, 4 * HEURE_MS),
    )
    assert trade is not None
    assert trade["carry_pnl_usd"] < 0.0, "a taux positif, un LONG paie le funding"
    assert trade["net_after_carry_usd"] < trade["net_pnl_usd"], "le cout doit REDUIRE le net"


def test_l_equation_de_conservation_du_net_reste_INTACTE() -> None:
    """Le funding ne doit JAMAIS entrer dans `net_pnl_usd` : la réconciliation en dépend."""
    metaordre, livres = _episode(enjambe=True)
    avec, _ = execute_metaorder(
        metaordre, livres, horizon_ms=300_000,
        taux_funding=_taux(), couverture_funding_ms=(0, 4 * HEURE_MS),
    )
    sans_metaordre, sans_livres = _episode(enjambe=False)
    sans, _ = execute_metaorder(sans_metaordre, sans_livres, horizon_ms=300_000)
    assert avec is not None and sans is not None
    # Le net reste la pure economie d'execution, reconciliee : gross - spread - fees -
    # slippage - latency. Il ne contient pas le portage.
    recompose = (avec["gross_pnl_usd"] - avec["spread_cost_usd"] - avec["fees_usd"]
                 - avec["slippage_cost_usd"] - avec["latency_cost_usd"])
    assert abs(avec["net_pnl_usd"] - recompose) < 1e-8
    assert abs(avec["net_after_carry_usd"]
               - (avec["net_pnl_usd"] + avec["carry_pnl_usd"])) < 1e-8


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
