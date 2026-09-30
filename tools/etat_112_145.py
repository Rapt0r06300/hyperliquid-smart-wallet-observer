"""ETAT REEL des taches #112 -> #145 (les 8 IMPROVE-* encore en attente).

LA REGLE DE S1-S4 : ne JAMAIS croire un statut ecrit. On prouve par EXECUTION.
Chaque question ci-dessous a une reponse binaire, obtenue en faisant tourner l'audit de
cablage sur le depot -- pas en lisant le code et en s'auto-persuadant.

Aucun ordre reel. Aucun reseau. Lecture seule.
"""
from __future__ import annotations

import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE / "src"))

from hl_observer.audit.cablage import (  # noqa: E402
    auditer_les_modules,
    graphe_des_imports,
    modules_atteignables,
    _points_d_entree,
)

IGNORE = ("__pycache__", "_archive", "DISABLED")


def _collecter(motifs: tuple[str, ...]) -> dict[str, str]:
    out: dict[str, str] = {}
    for motif in motifs:
        for p in RACINE.glob(motif):
            rel = p.relative_to(RACINE).as_posix()
            if any(x in rel for x in IGNORE):
                continue
            try:
                out[rel] = p.read_text(encoding="utf-8", errors="ignore")
            except OSError:
                pass
    return out


def _module(chemin: str) -> str:
    return chemin.removeprefix("src/").removesuffix(".py").replace("/", ".").removesuffix(".__init__")


# ---------------------------------------------------------------- les modules en question
#
# Une tache = un ou plusieurs modules. On demande a l'audit : EXISTE ? JOIGNABLE ? TESTE ?
SUJETS: dict[str, tuple[str, ...]] = {
    "#112 IMPROVE-05 latence bout-en-bout": (
        "hl_observer.runtime.latency_trace",
        "hl_observer.perf.latency_tracker",
        "hl_observer.perf.latency_budget",
        "hl_observer.realtime.latency_report",
        "hl_observer.copy_wallet.copy_latency_profiler",
        "hl_observer.copy_mode.copy_latency_profiler",
        "hl_observer.risk.latency_model",
        "hl_observer.paper.latency_model",
    ),
    "#127 IMPROVE-20 detecteur de regime EN DIRECT": (
        "hl_observer.backtesting.regime_detection",
        "hl_observer.backtesting.regime",
        "hl_observer.regime.regime_detector",
    ),
    "#130 IMPROVE-23 kill-switch": (
        "hl_observer.risk.kill_switch",
        "hl_observer.risk.circuit_breaker",
        "hl_observer.risk.loss_halts",
        "hl_observer.risk.protections_v26",
        "hl_observer.risk.graded_halt",
    ),
    "#143 IMPROVE-36 cascades de liquidations": (
        "hl_observer.backtesting.liquidation_cascade",
        "hl_observer.liquidations.cascade",
        "hl_observer.collection.liquidations_recorder",
    ),
    "#145 IMPROVE-38 basis Hyperliquid vs CEX": (
        "hl_observer.arbitrage.basis",
        "hl_observer.basis.basis_hl_cex",
        "hl_observer.collection.cex_price_recorder",
    ),
}


def main() -> int:
    py = _collecter(("src/**/*.py", "hyper_smart_observer/**/*.py", "tests/**/*.py"))
    lanceurs = _collecter(("*.cmd", "*.ps1", "*.sh", "tools/**/*.cmd", "tools/**/*.ps1"))

    verdict = auditer_les_modules(py, racine="hl_observer", lanceurs=lanceurs)
    entrees = _points_d_entree(py, "hl_observer", lanceurs)
    joignables = modules_atteignables(py, entrees)
    graphe = graphe_des_imports(py)

    existants = {_module(c) for c in py if c.startswith("src/")}
    testes = {
        m
        for m, importeurs in graphe.items()
        if any(i.startswith("tests/") for i in importeurs)
    }

    print("=" * 78)
    print("ETAT REEL DES TACHES #112 -> #145   (prouve par execution, pas par lecture)")
    print("=" * 78)
    print("modules src/ scannes : %d   |  points d'entree : %d  |  joignables : %d"
          % (len(existants), len(entrees), len(joignables & existants)))
    print()

    for titre, mods in SUJETS.items():
        print("-" * 78)
        print(titre)
        trouve = False
        for m in mods:
            if m not in existants:
                continue
            trouve = True
            j = "JOIGNABLE" if m in joignables else "🔴 MORT   "
            t = "teste" if m in testes else "PAS teste"
            n = len(graphe.get(m, ()))
            print("   %-10s %-9s  importe par %2d  %s" % (j, t, n, m))
        if not trouve:
            print("   ⚪ AUCUN MODULE : la capacite n'existe pas du tout.")
        print()

    print("-" * 78)
    print("#121 IMPROVE-14 couverture de tests")
    non_testes = sorted(m for m in (joignables & existants) if m not in testes)
    print("   modules JOIGNABLES et POURTANT sans test : %d" % len(non_testes))
    for m in non_testes[:25]:
        print("      - %s" % m)
    if len(non_testes) > 25:
        print("      ... (+%d)" % (len(non_testes) - 25))
    print()

    print("-" * 78)
    print("#131 IMPROVE-24 dependances")
    try:
        from importlib.metadata import distributions

        paquets = sorted((d.metadata["Name"] or "?").lower() for d in distributions())
    except Exception as exc:  # pragma: no cover
        paquets = []
        print("   (impossible de lister : %s)" % exc)
    print("   paquets installes : %d" % len(paquets))
    # 🚨 LE SEUL CONTROLE QUI COMPTE VRAIMENT : rien qui EXECUTE de vrais ordres.
    interdits = ("dex-exec", "dexec", "hyperliquid-python-sdk", "ccxt", "web3", "eth-account")
    for p in interdits:
        etat = "🚨 PRESENT" if p in paquets else "absent"
        print("   %-24s %s" % (p, etat))
    print()

    print("-" * 78)
    print("#115 IMPROVE-08 (run de collecte long) et #143/#145 (mesures)")
    print("   Ces taches demandent des DONNEES, pas du code. Voir le rapport.")
    print("=" * 78)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
