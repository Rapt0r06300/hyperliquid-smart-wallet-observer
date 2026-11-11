"""Registre de couverture des données collectées : du producteur jusqu'au laboratoire.

Une ligne par TYPE de donnée réellement écrit par les collecteurs (relevé sur un run réel et
dans le code des producteurs). Pour chacun : qui l'écrit, où, sous quelle famille le
certificateur le dépose (ou pourquoi il l'écarte), et ce que le laboratoire en fait.

Ce registre est un CONTRAT vérifié par les tests : tout fichier connu du certificateur doit y
figurer, toute famille certifiée doit avoir un usage labo déclaré, et un fichier de collecte
absent d'ici est signalé ``INCONNU`` par le certificateur — plus rien ne disparaît en silence
entre la collecte et le laboratoire.

Usage labo (déclaré honnêtement, vérifiable dans le code cité) :

* ``CONSOMME``   : lu par un calcul du labo (parcours cité) ;
* ``DISPONIBLE`` : certifié et chargeable, pas encore exploité par un calcul économique ;
* ``AUXILIAIRE`` : volontairement secondaire (contexte d'une famille économique désactivée) ;
* ``NON_CERTIFIE`` : écarté par conception (inférence, dérivé, diagnostic...), jamais au coffre.
"""
from __future__ import annotations

from dataclasses import dataclass

CONSOMME = "CONSOMME"
DISPONIBLE = "DISPONIBLE"
AUXILIAIRE = "AUXILIAIRE"
NON_CERTIFIE = "NON_CERTIFIE"

DATA = "runtime/data"
LAB = "runtime/research_lab/data"
HISTORY = "runtime/history"
ETUDE = "tools/etude_copiabilite.py"
LABO_PRINCIPAL = "backtesting/copy_vault_tier_local.py:_charger_tier_local"


@dataclass(frozen=True, slots=True)
class Flux:
    """Un type de donnée collecté et son parcours déclaré."""

    fichier: str            # nom du ruban (ou motif pour le magasin de ticks)
    dossier: str            # où le collecteur l'écrit
    producteur: str         # script qui l'écrit
    contenu: str            # ce que c'est, en clair
    famille: str | None     # famille du coffre ; None = non certifié par conception
    labo: str               # CONSOMME / DISPONIBLE / AUXILIAIRE / NON_CERTIFIE
    usage: str              # parcours du labo qui le lit, ou raison


FLUX: tuple[Flux, ...] = (
    # ------------------------------------------------------------------ fills des leaders
    Flux("vault_fills_poll.jsonl", DATA, "tools/collecter_userfills_poll.py",
         "fills des leaders vus par relevé REST (causal, retard ~100 s)", "fills_forward", CONSOMME,
         f"{ETUDE} (décroissance, épisodes, attribution) ; {LABO_PRINCIPAL}"),
    Flux("vault_fills_live.jsonl", DATA, "tools/collecter_userfills_vaults.py",
         "fills des leaders vus par WebSocket (causal, retard ~0,2 s)", "fills_forward", CONSOMME,
         f"{ETUDE} (segment « observation rapide ») ; {LABO_PRINCIPAL}"),
    Flux("copy_vault_twap_lane.jsonl", DATA, "tools/collecter_contexte_lane.py",
         "tranches TWAP des leaders (lane GitHub)", "fills_forward", CONSOMME, f"{ETUDE} ; {LABO_PRINCIPAL}"),
    Flux("vault_fills.jsonl", DATA, "tools/backfill_vault_fills.py",
         "historique REST des fills (récupéré après coup, non causal)", "fills_backfill", CONSOMME,
         f"{ETUDE} --retrospectif"),
    Flux("vault_episodes.jsonl", DATA, "tools/backfill_vault_fills.py",
         "même historique, découpé par action (reconnu par son contenu)", "fills_backfill", CONSOMME,
         f"{ETUDE} --retrospectif"),
    Flux("node_fills_tape.jsonl", DATA, "tools/ingester_node_fills.py",
         "fills lus sur un nœud Hyperliquid local", "fills_backfill", CONSOMME, f"{ETUDE} --retrospectif"),
    # ------------------------------------------------------------------ positions, NAV, capital
    Flux("vault_snapshots.jsonl", DATA, "tools/collecter_vaults.py",
         "portefeuille complet + NAV de chaque vault suivi (toutes les 5 min)", "snapshot", CONSOMME,
         f"{ETUDE} --positions (réplication lente du portefeuille observé)"),
    Flux("copy_vault_positions_lane.jsonl", DATA, "tools/collecter_contexte_lane.py",
         "positions par coin (clearinghouseState, lane GitHub)", "position", DISPONIBLE,
         f"{LABO_PRINCIPAL} (signal de contexte) ; à fusionner avec les portefeuilles"),
    Flux("vault_ledger.jsonl", DATA, "tools/backfill_vault_fills.py",
         "dépôts et retraits des vaults", "vault_ledger", DISPONIBLE,
         "prochaine étape : rendement NAV du leader net des flux, comparé au copieur"),
    # ------------------------------------------------------------------ prix, spreads, funding
    Flux("hl_allmids_tape.jsonl", DATA, "tools/collecter_allmids.py",
         "mids de tous les coins, dex HIP-3 compris", "allmids", CONSOMME, f"{ETUDE} (prix de référence)"),
    Flux("asset_ctx_tape.jsonl", DATA, "tools/collecter_asset_ctx.py",
         "funding, open interest, mark, oracle par coin", "asset_ctx", CONSOMME,
         f"{ETUDE} (funding de la position répliquée) ; {LABO_PRINCIPAL} (overshoot)"),
    Flux("bbo_tape.jsonl", DATA, "tools/collecter_bbo.py",
         "cotations bid/ask Hyperliquid + transactions Binance", "bbo", CONSOMME,
         f"{ETUDE} (coût de spread) ; {LABO_PRINCIPAL} (cotations adaptées, une par coin et par seconde)"),
    Flux("copy_vault_bbo_tape.jsonl", DATA, "tools/telecharger_l2_lanes_github.py",
         "BBO Hyperliquid des lanes GitHub", "bbo", CONSOMME, f"{ETUDE} ; backtesting/copy_vault_book_loader.py"),
    Flux("copy_vault_bbo_lane.jsonl", DATA, "tools/collecter_l2_lane.py",
         "BBO Hyperliquid (lane L2)", "bbo", CONSOMME, f"{ETUDE} ; backtesting/copy_vault_book_loader.py"),
    Flux("copy_vault_l2_tape.jsonl", DATA, "tools/collecter_userfills_vaults.py",
         "carnets L2 à 5 niveaux des coins tradés par les leaders", "book_l2", CONSOMME,
         f"{ETUDE} (coût de spread) ; {LABO_PRINCIPAL} (carnets causaux)"),
    Flux("copy_vault_candle_lane.jsonl", DATA, "tools/collecter_market_lane.py",
         "bougies 1 min (WebSocket)", "candle", DISPONIBLE, f"{LABO_PRINCIPAL} (signal de contexte)"),
    Flux("candles_5m.jsonl", HISTORY, "tools/backfill_candles_vaults.py",
         "bougies 5 min récupérées après coup (17 jours)", "candle", CONSOMME,
         f"{ETUDE} --positions / --retrospectif (prix)"),
    Flux("copy_vault_trades_lane.jsonl", DATA, "tools/collecter_market_lane.py",
         "transactions publiques Hyperliquid", "trades_marche", DISPONIBLE, f"{LABO_PRINCIPAL} (signal de contexte)"),
    # ------------------------------------------------------------------ microstructure dense
    Flux("micro_bbo.jsonl", LAB, "tools/collecter_lab_microstructure.py",
         "BBO Hyperliquid dense (séquence + somme de contrôle)", "micro_bbo", CONSOMME, f"{ETUDE} (coût de spread)"),
    Flux("micro_l2book.jsonl", LAB, "tools/collecter_lab_microstructure.py",
         "carnets L2 pleine profondeur", "micro_l2", DISPONIBLE, "prochaine étape : capacité réelle d'exécution"),
    Flux("micro_trades.jsonl", LAB, "tools/collecter_lab_microstructure.py",
         "transactions Hyperliquid (flux dense)", "micro_trades", DISPONIBLE, "contexte de flux ; non exploité"),
    # ------------------------------------------------------------------ événements et contexte
    Flux("liquidations_confirmees.jsonl", DATA, "tools/collecter_userfills_vaults.py",
         "liquidations confirmées", "liquidation", DISPONIBLE, f"{LABO_PRINCIPAL} (signal de contexte)"),
    Flux("overshoots_liquidation.jsonl", DATA, "tools/collecter_overshoots.py",
         "écarts oracle/mark mesurés", "overshoot", DISPONIBLE, f"{LABO_PRINCIPAL} (signal de contexte)"),
    Flux("explorer_tx_tape.jsonl", DATA, "tools/collecter_explorer_lane.py",
         "transactions de tous les utilisateurs vues sur l'explorer", "explorer_tx", DISPONIBLE,
         "sert la découverte de leaders côté collecte ; couverture d'univers à mesurer au labo"),
    Flux("carnet_venues.jsonl", DATA, "tools/collecter_carnet.py",
         "haut de carnet Hyperliquid contre Binance", "venue_book", AUXILIAIRE,
         f"{LABO_PRINCIPAL} (contexte ; famille Cross-Venue désactivée)"),
    Flux("dispersion_venues.jsonl", DATA, "tools/collecter_dispersion_venues.py",
         "écart de prix entre venues", "venue_dispersion", AUXILIAIRE,
         f"{LABO_PRINCIPAL} (contexte ; famille Cross-Venue désactivée)"),
    # ------------------------------------------------------------------ écartés par conception
    Flux("explorer_inferred_fills.jsonl", DATA, "tools/explorer_autonome.py",
         "fills DÉDUITS de l'explorer (estimation)", None, NON_CERTIFIE, "INFERENCE"),
    Flux("metaorder_shadow_ledger.jsonl", DATA, "experimental/metaorder_shadow.py",
         "registre de simulation « shadow »", None, NON_CERTIFIE, "DERIVE"),
    Flux("metaorder_l2_tape.jsonl", DATA, "experimental/metaorder_l2_tape.py",
         "jointure fill + carnet autour des métaordres", None, NON_CERTIFIE, "DERIVE"),
    Flux("leader_fills_bruts.jsonl", DATA, "strategies/fusion_runtime.py",
         "journal des votes de leaders du moteur (ni prix ni taille)", None, NON_CERTIFIE, "DERIVE"),
    Flux("fills_journal.jsonl", DATA, "tools/collecter_userfills_vaults.py",
         "journal des fills WebSocket", None, NON_CERTIFIE, "REDONDANT"),
    Flux("lead_lag_event_decisions.jsonl", DATA, "runtime/lead_lag_event_runtime.py",
         "décisions de la famille Lead-Lag", None, NON_CERTIFIE, "HORS_PERIMETRE"),
    Flux("raw_l2_lifecycle.jsonl", DATA, "tools/collecter_userfills_vaults.py",
         "journal technique des abonnements L2", None, NON_CERTIFIE, "DIAGNOSTIC"),
    Flux("userfills_integrity_diagnostics.jsonl", DATA, "tools/collecter_userfills_vaults.py",
         "diagnostics d'intégrité du collecteur", None, NON_CERTIFIE, "DIAGNOSTIC"),
    Flux("userfills_unclassified.jsonl", DATA, "tools/collecter_userfills_vaults.py",
         "trames userFills non classées", None, NON_CERTIFIE, "DIAGNOSTIC"),
    Flux("recap_historique.jsonl", DATA, "tools/tout_tester.py",
         "récapitulatif d'état du projet", None, NON_CERTIFIE, "DIAGNOSTIC"),
    Flux("raw_probe_ledger.jsonl", DATA, "experimental/rapport_raw.py",
         "journal de décisions du moteur PAPER", None, NON_CERTIFIE, "DERIVE"),
    Flux("exploratory_paper_ledger.jsonl", DATA, "experimental/exploratoire.py",
         "journal de décisions du moteur PAPER exploratoire", None, NON_CERTIFIE, "DERIVE"),
    Flux("discovery_probe_ledger.jsonl", DATA, "ui/cohorte_ledger_reader.py",
         "journal de décisions du moteur PAPER (découverte)", None, NON_CERTIFIE, "DERIVE"),
)

#: Magasin de ticks natifs : pas un ruban mais un arbre auto-manifesté, vérifié et référencé en place.
MAGASIN_TICKS = Flux(
    "market_ticks/<source>/<canal>/<instrument>/shards/*.jsonl.gz", "runtime/data",
    "tools/collecter_native_venues.py ; tools/collecter_bbo.py",
    "ticks natifs par venue (Hyperliquid, Binance, Bybit, Bitget, Gate) : BBO, L2, trades, funding",
    "MARKET_TICKS_STORE", DISPONIBLE,
    "vérifié par SHA-256 et référencé (tools/verifier_store_ticks.py) ; le BBO Hyperliquid depuis le "
    "28/10 est exploitable comme prix observé ; les autres venues sont un contexte auxiliaire",
)


#: Équivalent SAFE-cloud de chaque famille du coffre LOCAL (familles du catalogue restauré par
#: AlinaSync). Tuple vide = la donnée n'existe QUE sur ce PC : elle nourrit la recherche
#: exploratoire mais ne peut jamais porter un verdict PROVEN (la preuve exige SAFE).
EQUIVALENT_SAFE: dict[str, tuple[str, ...]] = {
    "fills_forward": ("copy_vault_fills",),
    "fills_backfill": (),
    "snapshot": ("copy_vault_snapshot",),
    "position": ("copy_vault_positions",),
    "vault_ledger": (),
    "allmids": (),
    "asset_ctx": ("activeAssetCtx", "funding", "mark_price", "open_interest"),
    "bbo": ("bbo",),
    "book_l2": ("copy_vault_l2", "l2Book"),
    "candle": (),
    "trades_marche": ("trades",),
    "micro_bbo": ("bbo",),
    "micro_l2": ("l2Book",),
    "micro_trades": ("trades",),
    "liquidation": ("liquidations",),
    "overshoot": (),
    "explorer_tx": (),
    "venue_book": ("cross_venue_capacity_tape",),
    "venue_dispersion": (),
}


def flux_par_fichier() -> dict[str, Flux]:
    return {f.fichier: f for f in FLUX}


def usage_par_famille() -> dict[str, str]:
    """Meilleur usage labo déclaré pour chaque famille certifiée (CONSOMME > DISPONIBLE > AUXILIAIRE)."""
    ordre = {CONSOMME: 0, DISPONIBLE: 1, AUXILIAIRE: 2}
    usage: dict[str, str] = {}
    for flux in FLUX:
        if flux.famille and (flux.famille not in usage or ordre[flux.labo] < ordre[usage[flux.famille]]):
            usage[flux.famille] = flux.labo
    return usage


__all__ = [
    "AUXILIAIRE", "CONSOMME", "DISPONIBLE", "EQUIVALENT_SAFE", "FLUX", "Flux", "MAGASIN_TICKS", "NON_CERTIFIE",
    "flux_par_fichier", "usage_par_famille",
]
