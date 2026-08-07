"""[Bloc 5-7/37/56 / AUD-071,221,222] Orchestrateur UNIQUE hyperlab_master.

run(mode) : quick / full / deep / maximum / resume. UN SEUL chemin economique (AUD-071) : toutes les
familles passent par le moteur paper unique et l'enveloppe 1000 USD. Pipeline REEL :
ingest (data_plane -> Bronze/Silver/Gold/catalogue) -> familles -> moteur paper -> ledger/equity ->
rapport. `deep`/`maximum` ajoutent la validation statistique. `resume` reprend depuis un etat.
Carry reste DISABLED_BY_SCOPE (hors familles). 0 reseau, 0 ordre reel.
"""
from __future__ import annotations

from typing import Mapping, Optional

from . import data_plane
from . import report as _report
from . import validation as _val
from .moteur_paper_unique import MoteurPaper
from .strategies import CopyVault, CrossVenue, LeadLag

MODES = {
    "quick":   {"familles": ("copy_vault",), "validation": False, "notionnel": 100.0},
    "full":    {"familles": ("copy_vault", "lead_lag", "cross_venue"), "validation": False, "notionnel": 100.0},
    "deep":    {"familles": ("copy_vault", "lead_lag", "cross_venue"), "validation": True, "notionnel": 100.0},
    "maximum": {"familles": ("copy_vault", "lead_lag", "cross_venue"), "validation": True, "notionnel": 150.0},
}
ETAPES = ("ingest", "strategies", "execution", "validation", "report")


def run(mode: str, *, root: str, conn, fixtures: Mapping, etat: Optional[Mapping] = None,
        blocages=(), prochaine_action: str = "collecte live (REQUIRES_NETWORK)") -> dict:
    if mode == "resume":
        assert etat is not None, "resume exige un etat"
        cfg = dict(etat["cfg"])
        faites = set(etat.get("faites", []))
    else:
        assert mode in MODES, "mode inconnu: %s" % mode
        cfg = dict(MODES[mode], mode=mode)
        faites = set()

    ts = fixtures.get("ts", 1000.0)
    venue = fixtures.get("venue", "bybit")
    symbole = fixtures.get("symbole", "BTCUSDT")
    moteur = MoteurPaper(1000.0)

    if "ingest" not in faites:
        data_plane.ingerer(root, conn, venue, fixtures["records"], ts=ts)
        faites.add("ingest")

    intents = []
    fam = set(cfg["familles"])
    if "copy_vault" in fam and fixtures.get("copy_action"):
        intents += CopyVault().generer_intents(fixtures["copy_action"], notionnel_usd=cfg["notionnel"], ts=ts)
    if "lead_lag" in fam and fixtures.get("leadlag"):
        p, c = fixtures["leadlag"]
        intents += LeadLag().generer_intents(p, c, venue=venue, symbole=symbole,
                                              notionnel_usd=cfg["notionnel"], ts=ts)
    if "cross_venue" in fam and fixtures.get("crossvenue"):
        a, b = fixtures["crossvenue"]
        intents += CrossVenue().generer_intents(a["mid"], b["mid"], venue_a=a["venue"], venue_b=b["venue"],
                                                symbole=symbole, notionnel_usd=cfg["notionnel"], ts=ts)
    faites.add("strategies")
    resultats = [moteur.soumettre(i) for i in intents]
    faites.add("execution")

    val = None
    if cfg["validation"] and fixtures.get("perf_is") is not None:
        val = {"pbo": _val.pbo(fixtures["perf_is"], fixtures["perf_oos"]),
               "dsr": _val.deflated_sharpe(fixtures.get("sr", 1.0), fixtures.get("n_trials", 20),
                                           fixtures.get("T", 250))}
    faites.add("validation")

    rap = _report.rapport_simple(moteur, blocages=list(blocages), prochaine_action=prochaine_action,
                                 equity_series=fixtures.get("equity_series"))
    faites.add("report")

    return {"mode": cfg["mode"], "intents": len(intents), "fills": len(moteur.fills),
            "refus": sum(1 for r in resultats if not r["accepte"]),
            "validation": val, "rapport": rap,
            "etat": {"cfg": cfg, "faites": sorted(faites)}}
