"""[LAB α] AUDIT des câblages : pour chaque brique du chemin canonique unique (feed_adapter → MegaCablage →
Copy-Vault + Cross-Venue + Lead-Lag → netting/routing → risk gates → PaperLedger), affiche un statut honnête :
  CÂBLÉ ET UTILISÉ · CÂBLÉ MAIS SANS DONNÉE · PRÉSENT MAIS NON CÂBLÉ · BLOQUÉ · ERREUR.
On importe réellement chaque module (import KO → ERREUR/PRÉSENT NON CÂBLÉ) et on croise avec la disponibilité
réelle des données (pas de statut « utilisé » sans donnée). Pur/lecture seule ; 0 réseau, 0 ordre réel.
"""
from __future__ import annotations

import importlib
from typing import Any

CABLE_UTILISE = "CABLE ET UTILISE"
CABLE_SANS_DONNEE = "CABLE MAIS SANS DONNEE"
PRESENT_NON_CABLE = "PRESENT MAIS NON CABLE"
BLOQUE = "BLOQUE"
ERREUR = "ERREUR"

# (nom, module, symbole attendu, dépend-de-données ?)
_BRIQUES = (
    ("feed_adapter", "hl_observer.mega_cablage.feed_adapter", "evenements_depuis_bundles", "evenements"),
    ("MegaCablage", "hl_observer.mega_cablage.pipeline", "MegaCablage", "spine"),
    ("Copy-Vault", "hl_observer.mega_cablage.copy_stage", "intent_copie", "evenements"),
    ("Cross-Venue", "hl_observer.mega_cablage.cross_venue_paper_stage", "executer_paire_cross_venue", "hedge"),
    ("Lead-Lag", "hl_observer.mega_cablage.lead_lag_stage", "score_lead_lag", "lead_lag"),
    ("netting/routing", "hl_observer.mega_cablage.netting_routing_stage", "netter_et_router", "evenements"),
    ("risk gates", "hl_observer.mega_cablage.risk_stage", "filtrer_risque", "evenements"),
    ("PaperLedger", "hl_observer.simulation.paper_ledger", "PaperLedger", "spine"),
)


def _import_ok(module: str, symbole: str) -> tuple[bool, str | None]:
    try:
        mod = importlib.import_module(module)
    except Exception as exc:                        # noqa: BLE001 (import KO = brique bloquée honnêtement)
        return False, "%s: %s" % (type(exc).__name__, exc)
    if not hasattr(mod, symbole):
        return False, "SYMBOLE_ABSENT:%s" % symbole
    return True, None


def auditer(*, a_des_evenements: bool, a_des_carnets_hedge: bool = False,
            a_lead_lag: bool = False) -> dict[str, Any]:
    """Statut par brique en croisant import réel + disponibilité des données. Retourne {bricks, resume}."""
    dispo = {"evenements": a_des_evenements, "hedge": a_des_carnets_hedge,
             "lead_lag": a_lead_lag, "spine": True}
    bricks: list[dict[str, Any]] = []
    for nom, module, symbole, dep in _BRIQUES:
        ok, err = _import_ok(module, symbole)
        if not ok:
            statut = ERREUR if err and err.startswith(("ImportError", "ModuleNotFound")) else BLOQUE
            bricks.append({"brique": nom, "statut": statut, "detail": err})
            continue
        statut = CABLE_UTILISE if dispo.get(dep, False) else CABLE_SANS_DONNEE
        bricks.append({"brique": nom, "statut": statut})
    resume = {s: sum(1 for b in bricks if b["statut"] == s)
              for s in (CABLE_UTILISE, CABLE_SANS_DONNEE, PRESENT_NON_CABLE, BLOQUE, ERREUR)}
    return {"bricks": bricks, "resume": resume}


__all__ = ["auditer", "CABLE_UTILISE", "CABLE_SANS_DONNEE", "PRESENT_NON_CABLE", "BLOQUE", "ERREUR"]
