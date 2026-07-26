"""REGISTRE APPEND-ONLY DES ESSAIS (LOT14 #9, Flo 26/07). Chaque variante testée — GAGNANTE, KILL ou
exploratoire — est enregistrée AVANT/AVEC son résultat, pour que le DSR utilise la distribution de TOUS
les essais pertinents (pas seulement les gagnants conservés = biais de sélection) et que le PBO soit une
vraie CSCV. Append-only : rien n'est réécrit ni supprimé. 0 réseau, 0 ordre.

Champs par essai : family, variant, parameter_hash, data_cutoff, universe, horizon, cost_model_version,
execution_model_version, result, pass_kill, preregistration_ts.
"""
from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path

REGISTRE_RELPATH = Path("runtime") / "data" / "registre_essais.jsonl"
CHAMPS = ("family", "variant", "parameter_hash", "data_cutoff", "universe", "horizon",
          "cost_model_version", "execution_model_version", "result", "pass_kill", "preregistration_ts")


def parameter_hash(params: dict) -> str:
    return hashlib.sha256(json.dumps(params, sort_keys=True, ensure_ascii=False).encode()).hexdigest()[:16]


def enregistrer(root: Path, essai: dict) -> dict:
    """Append un essai (complété des champs manquants). Ne réécrit JAMAIS. Rend la ligne écrite."""
    ligne = {c: essai.get(c) for c in CHAMPS}
    if ligne["preregistration_ts"] is None:
        ligne["preregistration_ts"] = int(time.time() * 1000)
    if ligne["parameter_hash"] is None and isinstance(essai.get("params"), dict):
        ligne["parameter_hash"] = parameter_hash(essai["params"])
    ligne["sharpe"] = essai.get("sharpe")            # pour alimenter le DSR sur TOUS les essais
    p = Path(root) / REGISTRE_RELPATH
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("a", encoding="utf-8") as f:
        f.write(json.dumps(ligne, ensure_ascii=False) + "\n")
    return ligne


def charger(root: Path) -> list[dict]:
    try:
        return [json.loads(l) for l in (Path(root) / REGISTRE_RELPATH).read_text(encoding="utf-8").splitlines() if l.strip()]
    except OSError:
        return []


def sharpes_tous_essais(essais: list[dict], *, family: str | None = None) -> list[float]:
    """Sharpe de TOUS les essais (gagnants ET KILL) — c'est la distribution que le DSR doit dégonfler,
    sinon on ne compte que les survivants (biais)."""
    out = []
    for e in essais:
        if family and e.get("family") != family:
            continue
        s = e.get("sharpe")
        if isinstance(s, (int, float)):
            out.append(float(s))
    return out


__all__ = ["enregistrer", "charger", "parameter_hash", "sharpes_tous_essais", "CHAMPS", "REGISTRE_RELPATH"]
