"""QUI EST ENCORE MORT ? — l'audit de câblage, en une commande.

🔴 Flo : « en gros rien n'est vraiment branché sur la simulation ? »
    **Il avait raison : 22 modules livrés, 3 branchés.**

Cet outil répond à la question **par AST**, pas par une impression :
pour chaque module, **qui l'importe dans `src/` (le runtime)** — et pas seulement dans un test.

    ***Un module qui existe n'est pas un module qui garde.***
    ***Un test n'est pas un branchement.***

Aucun ordre réel.
"""
from __future__ import annotations

import ast
import sys
from collections import defaultdict
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
SRC = RACINE / "src"

# Ce qui DOIT être dans la porte (garde-fous), et ce qui est légitimement un OUTIL de recherche.
GARDES = {
    "hl_observer.fees.hyperliquid_fees": "#543 — la source unique des frais",
    "hl_observer.risk.side_lock": "#566 — 19/21 SHORT",
    "hl_observer.market.flow_toxicity": "#521 — le VPIN",
    "hl_observer.market.execution_constraints": "#576 — l'ordre est-il possible ?",
    "hl_observer.risk.session_gate": "#292b — les 11 gates V19",
    "hl_observer.freshness.horloges": "#318 — la fraîcheur n'est plus une tautologie",
}
OUTILS = {
    "hl_observer.backtesting.lead_lag": "#549 — mesure (0/66)",
    "hl_observer.market.hlp_vault": "#544 — benchmark",
    "hl_observer.market.hip3_markets": "#517 — mesure",
    "hl_observer.market.oracle_lag": "#556 — mesure",
    "hl_observer.backtesting.liquidation_cascade": "#530 — mesure",
    "hl_observer.collection.archive_s3": "#462 — collecte (payant : REFUSE)",
    "hl_observer.funding.funding_cross_venue": "#542 — mesure",
    "hl_observer.funding.snapshot_capture": "#531 — mesure",
    "hl_observer.runtime.replay_shadow": "#302 — outil de vérité",
    "hl_observer.runtime.session_and_bus": "#286 — outil de vérité",
    "hl_observer.realtime.ws_resilience": "#314 — à brancher au collecteur",
    "hl_observer.realtime.raw_spool": "#501 — à brancher au collecteur",
    "hl_observer.backtesting.honest_metrics": "#571 — rapport",
    "hl_observer.backtesting.intrabar": "#572 — backtest",
    "hl_observer.backtesting.backtest_live_parity": "#583 — backtest",
    "hl_observer.testing.lookahead_detector": "#562 — outil",
    "hl_observer.arbitrage.triangular_measure": "#296 — mesure",
    "hl_observer.collection.funding_backfill": "#606 — collecte",
}

# Le chemin d'ENTREE : si un garde y est, il garde vraiment.
PORTE = "src/hl_observer/decision_engine/noyau_unique.py"


def importateurs() -> dict[str, set[str]]:
    out: dict[str, set[str]] = defaultdict(set)
    for f in SRC.rglob("*.py"):
        try:
            a = ast.parse(f.read_text(encoding="utf-8", errors="replace"))
        except SyntaxError:
            continue
        rel = str(f.relative_to(RACINE)).replace("\\", "/")
        for n in ast.walk(a):
            if isinstance(n, ast.ImportFrom) and n.module:
                out[n.module].add(rel)
            elif isinstance(n, ast.Import):
                for al in n.names:
                    out[al.name].add(rel)
    return out


def main() -> int:
    imp = importateurs()
    print("=" * 96)
    print("  QUI EST BRANCHE SUR LA SIMULATION ? (AST — pas une impression)")
    print("  *Un module qui existe n'est pas un module qui garde. Un test n'est pas un branchement.*")
    print("=" * 96)

    print("\n  🔒 LES GARDE-FOUS — ils doivent etre DANS LA PORTE (`noyau_unique.decider`)\n")
    manquants = []
    for m, why in GARDES.items():
        src = imp.get(m, set())
        dans_la_porte = PORTE in src
        etat = "✅ DANS LA PORTE" if dans_la_porte else ("⚠️  runtime (%d)" % len(src) if src
                                                         else "🔴 MORT")
        if not src:
            manquants.append(m)
        print("    %-18s %-46s %s" % (etat, m.replace("hl_observer.", ""), why))

    print("\n  🔬 LES OUTILS DE MESURE — hors runtime, et **c'est LEGITIME**\n")
    for m, why in OUTILS.items():
        src = {s for s in imp.get(m, set()) if s.startswith("src/")}
        print("    %-18s %-46s %s"
              % ("(outil)" if not src else "runtime(%d)" % len(src),
                 m.replace("hl_observer.", ""), why))

    print("\n" + "-" * 96)
    if manquants:
        print("  🔴 **%d GARDE-FOU(S) MORT(S)** : %s" % (len(manquants), ", ".join(manquants)))
        print("     *Brancher ou enterrer. Le nombre ne remonte pas.*")
        return 1
    print("  ✅ Tous les garde-fous sont importes par le runtime.")
    print("     ⚠️ Les OUTILS restent hors runtime -- **et je le dis au lieu de le maquiller.**")
    print("-" * 96)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
