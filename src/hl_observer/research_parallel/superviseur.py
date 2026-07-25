"""SUPERVISEUR du laboratoire — orchestre les plugins du registre avec ISOLATION DE CRASH.

Propriété centrale (mandat Flo) : une panne ou surcharge du labo NE DOIT JAMAIS ralentir ni arrêter le
moteur principal. Deux niveaux :
  1. process séparé (lancé par UNE ligne réversible de l'autopilot) -> le main est un autre process ;
  2. try/except PAR plugin -> un plugin qui lève est journalisé (CRASH_ISOLE) et N'ARRÊTE ni les autres
     plugins ni le superviseur. Le labo dégrade, il ne tombe pas.

Rollback réversible SANS toucher le lanceur : un fichier `runtime/research_lab/DISABLED` fait sortir le
superviseur proprement au démarrage (kill-switch mou), en plus du retrait de la ligne d'autopilot.
"""
from __future__ import annotations

import json
import time
import traceback
from pathlib import Path

from hl_observer.research_parallel import isolation as ISO
from hl_observer.research_parallel import registre as REG

DISABLED_REL = ISO.LAB_REL / "DISABLED"        # kill-switch mou (rollback sans toucher le lanceur)


def est_desactive(root: Path) -> bool:
    return (Path(root) / DISABLED_REL).exists()


def _journal_erreur(root: Path, plugin: str, exc: BaseException) -> None:
    base = ISO.lab_root(root) / "logs"
    base.mkdir(parents=True, exist_ok=True)
    try:
        with (base / "erreurs.jsonl").open("a", encoding="utf-8") as f:
            f.write(json.dumps({"ts_ms": int(time.time() * 1000), "plugin": plugin,
                                "erreur": str(exc)[:300], "trace": traceback.format_exc()[-800:]},
                               ensure_ascii=False) + "\n")
    except OSError:
        pass


_ORDRE_CAT = {"data": 0, "router": 1, "signal": 2}     # data collecté AVANT que les signaux le lisent


def tick_tous(root: Path, ident: dict, contexte: dict, *, plugins=None) -> dict:
    """Un tick : chaque plugin est appelé DANS UN try/except. Un crash est isolé + journalisé ; les autres
    continuent. Rend {plugin_id: {statut, n|erreur}}. N'échoue jamais globalement. Ordre par catégorie :
    data (collecte) -> router (régime) -> signal (émission), pour que les signaux lisent une data fraîche."""
    plugins = plugins if plugins is not None else REG.lister()
    plugins = sorted(plugins, key=lambda p: _ORDRE_CAT.get(p.categorie, 3))
    resultats = {}
    ok = 0
    for p in plugins:
        try:
            lignes = p.tick(contexte) or []
            n = ISO.ajouter_ledger(root, p.id, lignes, ident)
            resultats[p.id] = {"statut": "OK", "n": n}
            ok += 1
        except Exception as e:                      # noqa: BLE001 — isolation VOLONTAIRE et totale
            _journal_erreur(root, p.id, e)
            resultats[p.id] = {"statut": "CRASH_ISOLE", "erreur": str(e)[:200]}
    ISO.battre_coeur(root, ident, extra={"plugins": len(plugins), "ok": ok,
                                         "crash_isoles": len(plugins) - ok})
    return resultats


def demarrer(root: Path, *, plugins=None, params: dict | None = None) -> dict:
    """Initialise le labo : refuse de démarrer si DISABLED (rollback mou). Rend l'identité (ou {desactive})."""
    if est_desactive(root):
        return {"desactive": True, "motif": "DISABLED présent — labo volontairement à l'arrêt"}
    ISO.preparer(root)
    plugins = plugins if plugins is not None else REG.lister()
    if REG.total_variantes() > REG.MAX_VARIANTES_TOTAL:
        raise ValueError("plafond de variantes dépassé — refus de démarrer")
    return ISO.nouvelle_identite(root, [p.id for p in plugins], params)


def boucle(root: Path, *, poll_s: float = 60.0, contexte_fn=None, plugins=None, max_ticks: int | None = None):
    """Boucle du superviseur. `contexte_fn(root)->dict` fabrique le contexte (données read-only) à chaque
    tick. S'arrête proprement si DISABLED apparaît. Une exception de tick_tous ne peut pas remonter (déjà
    isolée), mais la construction du contexte est aussi protégée."""
    ident = demarrer(root, plugins=plugins)
    if ident.get("desactive"):
        return ident
    n = 0
    while True:
        if est_desactive(root):
            ISO.battre_coeur(root, ident, extra={"arret": "DISABLED"})
            return {"arret_propre": True, "ticks": n}
        try:
            contexte = contexte_fn(root) if contexte_fn else {}
        except Exception as e:      # noqa: BLE001 — même la fabrique de contexte ne tue pas le labo
            _journal_erreur(root, "_contexte", e)
            contexte = {}
        tick_tous(root, ident, contexte, plugins=plugins)
        n += 1
        if max_ticks is not None and n >= max_ticks:
            return {"arret_propre": True, "ticks": n}
        time.sleep(poll_s)


__all__ = ["est_desactive", "tick_tous", "demarrer", "boucle", "DISABLED_REL"]
