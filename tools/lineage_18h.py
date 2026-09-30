"""LIGNÉE DES DONNÉES 18 h (LOT18H-DATA-COMPLETE P3, Flo 26/07). Chaque PnL doit être remontable :
  source → événement → feature → signal → décision → exécution paper → ledger → PnL → rapport.
Un PnL sans cette lignée complète est marqué NON_AUDITABLE. Écrit data_lineage.jsonl (append-only). 0 réseau.
"""
from __future__ import annotations

import json
from pathlib import Path

MAILLONS = ("source", "evenement", "feature", "signal", "decision", "execution_paper", "ledger", "pnl", "rapport")


def enregistrer(rundir: Path, maillons: dict) -> dict:
    """Ajoute une ligne de lignée. `maillons` = dict avec au moins {source, evenement, signal, decision,
    execution_paper, ledger, pnl}. Marque `auditable` = tous les maillons essentiels présents."""
    rundir = Path(rundir)
    (rundir / "results").mkdir(parents=True, exist_ok=True)
    essentiels = ("source", "evenement", "signal", "decision", "pnl")
    ligne = {m: maillons.get(m) for m in MAILLONS}
    ligne["auditable"] = all(maillons.get(m) is not None for m in essentiels)
    ligne["statut"] = "AUDITABLE" if ligne["auditable"] else "NON_AUDITABLE"
    with (rundir / "results" / "data_lineage.jsonl").open("a", encoding="utf-8") as f:
        f.write(json.dumps(ligne, ensure_ascii=False) + "\n")
    return ligne


def pnl_auditable(rundir: Path, pnl_ref: str) -> bool:
    """Un PnL est auditable seulement s'il existe une lignée complète le référençant."""
    p = Path(rundir) / "results" / "data_lineage.jsonl"
    if not p.exists():
        return False
    for l in p.read_text(encoding="utf-8", errors="ignore").splitlines():
        try:
            d = json.loads(l)
        except ValueError:
            continue
        if d.get("pnl") == pnl_ref and d.get("auditable"):
            return True
    return False


def charger(rundir: Path) -> list[dict]:
    p = Path(rundir) / "results" / "data_lineage.jsonl"
    if not p.exists():
        return []
    return [json.loads(l) for l in p.read_text(encoding="utf-8", errors="ignore").splitlines() if l.strip()]


__all__ = ["enregistrer", "pnl_auditable", "charger", "MAILLONS"]
