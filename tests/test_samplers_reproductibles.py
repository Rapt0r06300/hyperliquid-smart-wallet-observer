"""AUD-091 — REPRODUCTIBILITÉ des samplers/pruners ADAPTATIFS (Optuna).

Le bug audité : dans `tools/outils_recherche.py`, les samplers Optuna ADAPTATIFS (TPE/CMA-ES/NSGA-II)
et les pruners (SuccessiveHalving/Hyperband, dont le sampler de base) étaient construits SANS `seed=` :
deux optimisations « identiques » proposaient donc des points DIFFÉRENTS (non reproductible). En parallèle,
`recherche_continue.py` dérivait sa graine de scheduler via `abs(hash(code_sha))` — salé par PYTHONHASHSEED,
donc instable ENTRE processus. Les tirages purs (grid/random/QMC-Halton) étaient déjà seedés.

Ce que ces tests verrouillent :
  1. MÊME graine  -> suggestions IDENTIQUES (samplers ET pruners adaptatifs) ;
  2. graines DIFFÉRENTES -> suggestions DIFFÉRENTES ;
  3. PLOMBERIE : `lancer_registre()` PROPAGE la graine à chaque outil (prouvé sans Optuna) ;
  4. la graine de `recherche_continue` est dérivée par HASHLIB, donc STABLE entre processus
     (indépendante de PYTHONHASHSEED), contrairement à `hash()`.
"""
from __future__ import annotations

import hashlib
import os
import subprocess
import sys
from pathlib import Path

import pytest

RACINE = Path(__file__).resolve().parents[1]
for _sous in ("tools", "src"):
    _p = str(RACINE / _sous)
    if _p not in sys.path:
        sys.path.insert(0, _p)

import outils_recherche as OUT  # noqa: E402

ESPACE = {"direction": [1, -1], "horizon_ms": [250, 1000, 5000], "th": {"min": 0.0, "max": 1.0}}
ADAPTATIFS = ("tpe", "cma_es", "nsga2", "successive_halving", "hyperband")
SAMPLERS = ("tpe", "cma_es", "nsga2")


@pytest.fixture(autouse=True)
def _objectif_deterministe_et_optuna_silencieux(monkeypatch):
    """L'objectif devient une fonction DÉTERMINISTE des paramètres (aucune dépendance externe) : la seule
    source d'aléa restante est le sampler -> toute divergence de suggestion vient de la graine, pas du bruit."""
    monkeypatch.setattr(OUT, "objectif_multicritere", lambda m: float(m.get("net_median_bps", 0.0)))
    try:
        import optuna
        optuna.logging.set_verbosity(optuna.logging.WARNING)
    except Exception:  # noqa: BLE001 — Optuna absent : les tests concernés se SKIP proprement
        pass


def _metrique(params: dict) -> dict:
    net = float(params.get("horizon_ms", 0)) * (1.0 if params.get("direction", 1) >= 0 else -1.0)
    net += float(params.get("th", 0.0)) * 10.0
    return {"net_median_bps": net, "pf": 1.2, "n": 64}


def _suggestions(outil: str, seed: int, *, n_trials: int = 6) -> list[dict]:
    """Capture la SÉQUENCE exacte de paramètres proposés (storage_dir=None -> étude en mémoire, toujours
    fraîche : pas de reprise SQLite qui masquerait la (non-)reproductibilité)."""
    vues: list[dict] = []

    def evaluer(params, budget: float = 1.0):
        vues.append({k: params[k] for k in sorted(params)})
        return _metrique(params)

    OUT.optimiser(evaluer, ESPACE, outil=outil, n_trials=n_trials, storage_dir=None, seed=seed)
    return vues


@pytest.mark.parametrize("outil", ADAPTATIFS)
def test_meme_graine_suggestions_identiques(outil):
    pytest.importorskip("optuna")
    if outil == "cma_es":
        pytest.importorskip("cmaes")
    a = _suggestions(outil, seed=42)
    b = _suggestions(outil, seed=42)
    assert a, "%s: aucune suggestion capturée (outil non lancé ?)" % outil
    assert a == b, "%s: suggestions DIVERGENTES à graine égale -> sampler non seedé" % outil


@pytest.mark.parametrize("outil", SAMPLERS)
def test_graines_differentes_suggestions_differentes(outil):
    pytest.importorskip("optuna")
    if outil == "cma_es":
        pytest.importorskip("cmaes")
    a = _suggestions(outil, seed=1)
    b = _suggestions(outil, seed=2)
    assert a and b
    assert a != b, "%s: MÊMES suggestions pour des graines différentes (graine ignorée ?)" % outil


def test_lancer_registre_propage_la_graine_a_chaque_outil(monkeypatch):
    """PLOMBERIE (sans Optuna) : `lancer_registre(seed=...)` doit transmettre la graine à CHAQUE `optimiser`."""
    captes: list[tuple[str, int]] = []

    def faux_optimiser(evaluer, espace, *, outil="random", n_trials=24, storage_dir=None, seed=0):
        captes.append((outil, seed))
        return {"outil": outil, "disponible": True, "lance": True, "trials_termines": 0}

    monkeypatch.setattr(OUT, "optimiser", faux_optimiser)
    OUT.lancer_registre(lambda p, budget=1.0: {"net_median_bps": 1.0}, ESPACE, n_trials=1, seed=123)
    assert captes, "aucun outil lancé"
    assert {o for o, _s in captes} == set(OUT.OUTILS), "tous les outils du registre doivent être lancés"
    assert all(s == 123 for _o, s in captes), "graine non propagée: %r" % captes


def test_seed_recherche_continue_derive_par_hashlib_est_stable():
    """La graine du scheduler continu est dérivée d'une CHAÎNE via SHA-256 (déterministe), pas via hash()."""
    import recherche_continue as RC
    attendu = int(hashlib.sha256(b"code_sha_ABC").hexdigest(), 16) % 997
    assert RC._seed_deterministe("code_sha_ABC") == attendu
    assert RC._seed_deterministe("zzz") == RC._seed_deterministe("zzz")   # déterministe intra-process
    assert 0 <= RC._seed_deterministe("n'importe quoi") < 997


def test_seed_recherche_continue_independant_du_PYTHONHASHSEED():
    """Preuve de STABILITÉ ENTRE PROCESSUS : deux interpréteurs avec des PYTHONHASHSEED différents dérivent
    la MÊME graine (ce que `abs(hash(...))` ne garantissait pas)."""
    import recherche_continue  # noqa: F401 — assure l'importabilité locale avant le sous-processus
    code = "sha-XYZ-123"
    attendu = str(int(hashlib.sha256(code.encode()).hexdigest(), 16) % 997)

    def _val(hashseed: str) -> str:
        env = dict(os.environ)
        env["PYTHONHASHSEED"] = hashseed
        env["PYTHONPATH"] = os.pathsep.join(
            [str(RACINE / "tools"), str(RACINE / "src"), str(RACINE)])
        out = subprocess.run(
            [sys.executable, "-c",
             "import recherche_continue as RC; print(RC._seed_deterministe(%r))" % code],
            capture_output=True, text=True, env=env, cwd=str(RACINE), timeout=90)
        assert out.returncode == 0, out.stderr
        return out.stdout.strip()

    assert _val("0") == _val("987654") == attendu
