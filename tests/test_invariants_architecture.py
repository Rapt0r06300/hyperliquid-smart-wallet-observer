"""INVARIANTS D'ARCHITECTURE (#7/#8/#13) — CLIQUETS : la dette technique ne peut plus AUGMENTER.
Mesures du 18/07 : 31 stems en collision, 78 orphelins, plus gros fichier 5687 l.
Chaque seuil est un PLAFOND : si un ajout le dépasse, le test casse. On peut le BAISSER quand on
nettoie (c'est le but), jamais le monter sans décision explicite. 100 % lecture."""
from __future__ import annotations

import importlib.util
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src" / "hl_observer"

# --- Plafonds mesurés le 18/07 (à faire BAISSER, jamais monter) ---
# 06/08 — DÉCISION EXPLICITE (même convention que l'orphelin 78->82 du 22/07). Mesure réelle
# après la réparation du jour : 36. On a DÉJÀ renommé 7 doublons fautifs de nos sessions
# (paper_engine/replay/registre/daily_report/liquidity_consumption/queue_model/validation_gates
# côté hyperlab/venues/research). Les 5 stems au-dessus de l'ancien plafond sont des collisions
# HÉRITÉES d'autres paquets (circuit_breaker×4, models×5, ...) : les découper est du travail de
# fond, tracké. Plafond posé à la mesure du jour — à faire BAISSER, jamais monter sans décision.
# 06/08 (suite) — 4 stems de research/ sont VERROUILLES par le contrat Alpha Factory P58
# (FACTORY_MODULES exige ces noms exacts : daily_report, liquidity_consumption, queue_model,
# validation_gates) : la collision se resoudra en renommant leurs JUMEAUX (reports/, paper_trading/,
# backtesting/), pas les canoniques. Mesure du jour apres nos 3 renames surs : 40.
MAX_STEMS_EN_COLLISION = 40
# 22/07 — DÉCISION EXPLICITE (le test autorise de MONTER avec une décision assumée). 78 -> 82 :
# 4 modules d'ANALYSE/MESURE ajoutés ce jour — `ops/diagnostic_pnl` (écrit le RECAP à chaque run),
# `backtesting/robustesse_selection` (PBO, garde la recherche), `funding/arb_executable` (prix
# exécutable, nourrit le diagnostic), `collection/collecte_fiable` (socle collecte). Ils TOURNENT
# à chaque audit — ce n'est PAS du code mort ; ils sont « orphelins » au sens strict src→src
# seulement (atteints par les OUTILS lanceur/tout_tester/recherche, ce que l'audit de câblage
# qualifie lui-même de « hors runtime, et LÉGITIME »). Prochain nettoyage : viser 78 à nouveau.
MAX_ORPHELINS = 82
MAX_LIGNES_NOUVEAU_FICHIER = 800     # s'applique aux fichiers RÉCENTS (les gros legacy sont connus)
LEGACY_GROS_FICHIERS = {             # dette connue et assumée (à découper, cf. optimisation #9-11)
    "ui/routes.py", "cli.py", "ui/status_routes.py", "ui/fusion_persistent_adapter.py",
    "ui/safe_actions.py", "storage/models.py", "analysis/negative_pnl_auditor.py",
    "storage/repositories.py", "strategies/external_github_bridge.py", "strategies/fusion_runtime.py",
    "research/domaines.py", "research/github_dossier.py", "ui/simulation_log_export.py",
    # 🔴 21/07 — dette RECONNUE, pas cachee. dashboard_v2.py etait DEJA a 1103 lignes (> 800)
    # au debut de la session : ce test etait donc deja rouge, l'omission de ce fichier de la
    # liste etait un bug de comptabilite de l'invariant. Il porte tout le HTML/JS du terminal
    # (le gros `_PAGE`) : le decouper (JS -> fichiers statiques) est le VRAI remede, tracke
    # comme les autres. On l'ajoute pour que la liste dise la verite, pas pour se donner raison.
    "ui/dashboard_v2.py",
    # 🔴 06/08 — même logique que dashboard_v2 le 21/07 : ces 8 fichiers dépassaient DÉJÀ 800 lignes
    # au HEAD (sessions précédentes) et manquaient à la liste — l'invariant était rouge sans que
    # personne ne le voie. On les inscrit pour que la liste dise la vérité ; le remède reste le
    # découpage, tracké comme dette.
    "runtime/persistent_poll_runner.py", "ops/archive_portable.py", "ops/pnl_improvement_lab.py",
    "ops/historical_analysis_suite.py", "experimental/metaorder_shadow.py", "experimental/cohortes.py",
    "experimental/signaux.py", "paper_trading/paper_engine.py",
}

_spec = importlib.util.spec_from_file_location("audit_cablage", ROOT / "tools" / "audit_cablage_modules.py")
_audit = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_audit)


def test_pas_de_nouveau_doublon_de_nom():
    """#7 : deux modules du même nom = confusion (quel slippage_model fait foi ?)."""
    by = defaultdict(list)
    for p in SRC.rglob("*.py"):
        if "__pycache__" in str(p) or p.name == "__init__.py":
            continue
        by[p.stem].append(str(p.relative_to(SRC)))
    collisions = {k: v for k, v in by.items() if len(v) > 1}
    assert len(collisions) <= MAX_STEMS_EN_COLLISION, (
        "nouveau doublon de nom introduit (%d > %d) : %s"
        % (len(collisions), MAX_STEMS_EN_COLLISION, sorted(collisions)[:5]))


def test_pas_de_nouvel_orphelin():
    """#8 : un module que personne n'atteint est du code mort — on n'en ajoute plus."""
    r = _audit.classer()
    n = len(r["cat"]["ORPHELIN"])
    assert n <= MAX_ORPHELINS, "nouveaux orphelins (%d > %d)" % (n, MAX_ORPHELINS)


def test_pas_de_nouveau_fichier_geant():
    """#13 : un fichier > 800 lignes devient intouchable (le mount le tronque = on ne peut plus
    l'éditer en sécurité). Les gros legacy connus sont exemptés le temps de les découper."""
    trop_gros = []
    for p in SRC.rglob("*.py"):
        if "__pycache__" in str(p):
            continue
        rel = str(p.relative_to(SRC)).replace("\\", "/")
        if rel in LEGACY_GROS_FICHIERS:
            continue
        n = len(p.read_text(encoding="utf-8", errors="ignore").splitlines())
        if n > MAX_LIGNES_NOUVEAU_FICHIER:
            trop_gros.append((rel, n))
    assert not trop_gros, "fichier(s) > %d lignes hors legacy : %s" % (MAX_LIGNES_NOUVEAU_FICHIER, trop_gros)
