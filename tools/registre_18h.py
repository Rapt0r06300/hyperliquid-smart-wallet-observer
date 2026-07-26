"""REGISTRE EXHAUSTIF DES ESSAIS 18 h (Flo 26/07). Trois journaux append-only :
  ledger/trials_preregistered.jsonl  — l'essai est enregistré AVANT son résultat (trial_id immuable) ;
  ledger/trials_results.jsonl        — le résultat, lié au trial_id (un résultat SANS préreg est refusé) ;
  ledger/trials_superseded.jsonl     — un essai corrigé reçoit un NOUVEAU trial_id + lien `supersedes`.
Un retry TECHNIQUE garde le même trial_id. TOUS les essais (KILL/erreur compris) alimentent la correction de
multiplicité (DSR/PBO). 0 réseau, 0 ordre.
"""
from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path

CHAMPS = ("trial_id", "family", "variant", "parameter_hash", "source_hash", "data_partition", "data_cutoff",
          "coins", "regime", "direction", "entry_rule", "exit_rule", "horizons", "latency_model", "fill_model",
          "cost_model", "size_model", "random_seed", "created_before_result", "status", "reason")


def _p(rundir: Path, nom: str) -> Path:
    p = Path(rundir) / "ledger" / nom
    p.parent.mkdir(parents=True, exist_ok=True)
    return p


def trial_id(family: str, variant: str, parameter_hash: str) -> str:
    return "t-" + hashlib.sha256(("%s|%s|%s" % (family, variant, parameter_hash)).encode()).hexdigest()[:16]


def parameter_hash(params: dict) -> str:
    return hashlib.sha256(json.dumps(params, sort_keys=True, ensure_ascii=False).encode()).hexdigest()[:16]


def preenregistrer(rundir: Path, essai: dict) -> dict:
    """Écrit un préreg (created_before_result=True, status=PREREGISTERED). trial_id dérivé si absent.
    IDEMPOTENT (P7) : un trial_id déjà préenregistré n'est PAS réécrit (le préreg initial fait foi)."""
    ligne = {c: essai.get(c) for c in CHAMPS}
    if not ligne["parameter_hash"] and isinstance(essai.get("params"), dict):
        ligne["parameter_hash"] = parameter_hash(essai["params"])
    if not ligne["trial_id"]:
        ligne["trial_id"] = trial_id(ligne["family"] or "?", ligne["variant"] or "?", ligne["parameter_hash"] or "?")
    if ligne["trial_id"] in _prereg_ids(rundir):        # déjà préenregistré -> ne pas dupliquer
        return ligne
    ligne["created_before_result"] = True
    ligne["status"] = "PREREGISTERED"
    ligne["preregistration_ts"] = int(time.time() * 1000)
    with _p(rundir, "trials_preregistered.jsonl").open("a", encoding="utf-8") as f:
        f.write(json.dumps(ligne, ensure_ascii=False) + "\n")
    return ligne


def _prereg_ids(rundir: Path) -> set:
    ids = set()
    p = _p(rundir, "trials_preregistered.jsonl")
    if p.exists():
        for l in p.read_text(encoding="utf-8").splitlines():
            try:
                ids.add(json.loads(l).get("trial_id"))
            except ValueError:
                continue
    return ids


def _ids_resultats(rundir: Path) -> set:
    ids = set()
    p = _p(rundir, "trials_results.jsonl")
    if p.exists():
        for l in p.read_text(encoding="utf-8").splitlines():
            try:
                ids.add(json.loads(l).get("trial_id"))
            except ValueError:
                continue
    return ids


def enregistrer_resultat(rundir: Path, trial_id_: str, resultat: dict) -> dict:
    """Résultat TERMINAL lié à un trial_id DÉJÀ préenregistré (sinon REFUSÉ). UN SEUL résultat terminal par
    trial_id (P7) : un 2e est un RETRY technique -> journal séparé (ne compte pas comme nouvel essai)."""
    if trial_id_ not in _prereg_ids(rundir):
        raise ValueError("RESULTAT_SANS_PREREGISTRATION: %s" % trial_id_)
    ligne = {"trial_id": trial_id_, "ts_ms": int(time.time() * 1000), **resultat}
    if trial_id_ in _ids_resultats(rundir):             # déjà un résultat terminal -> retry, pas un nouvel essai
        with _p(rundir, "trials_retries.jsonl").open("a", encoding="utf-8") as f:
            f.write(json.dumps(ligne, ensure_ascii=False) + "\n")
        return {**ligne, "_retry": True}
    with _p(rundir, "trials_results.jsonl").open("a", encoding="utf-8") as f:
        f.write(json.dumps(ligne, ensure_ascii=False) + "\n")
    return ligne


def superseder(rundir: Path, ancien_trial_id: str, nouveau: dict) -> dict:
    """Essai corrigé : NOUVEAU trial_id + lien supersedes (l'ancien n'est jamais effacé)."""
    nouveau = dict(nouveau)
    nouveau["supersedes"] = ancien_trial_id
    nv = preenregistrer(rundir, nouveau)
    with _p(rundir, "trials_superseded.jsonl").open("a", encoding="utf-8") as f:
        f.write(json.dumps({"ancien": ancien_trial_id, "nouveau": nv["trial_id"],
                            "ts_ms": int(time.time() * 1000)}, ensure_ascii=False) + "\n")
    return nv


def sharpes_tous_resultats(rundir: Path) -> list[float]:
    """Sharpe de TOUS les résultats terminaux (KILL/erreur compris) — la distribution que DSR/PBO doivent
    dégonfler (correction de multiplicité)."""
    out = []
    p = _p(rundir, "trials_results.jsonl")
    if p.exists():
        for l in p.read_text(encoding="utf-8").splitlines():
            try:
                s = json.loads(l).get("sharpe")
            except ValueError:
                continue
            if isinstance(s, (int, float)):
                out.append(float(s))
    return out


def compter(rundir: Path) -> dict:
    def _n(nom):
        p = _p(rundir, nom)
        return sum(1 for _ in p.read_text(encoding="utf-8").splitlines()) if p.exists() else 0
    return {"preregistres": _n("trials_preregistered.jsonl"), "resultats": _n("trials_results.jsonl"),
            "superseded": _n("trials_superseded.jsonl")}


__all__ = ["trial_id", "parameter_hash", "preenregistrer", "enregistrer_resultat", "superseder",
           "sharpes_tous_resultats", "compter", "CHAMPS"]
