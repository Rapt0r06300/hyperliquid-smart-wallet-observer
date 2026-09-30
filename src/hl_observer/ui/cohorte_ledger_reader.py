"""AUD-125 — le dashboard lit AUSSI les ledgers de COHORTES (meme source, pas divergente).

Les cohortes exploratoires ecrivent des ledgers separes (exploratory_paper_ledger.jsonl,
discovery_probe_ledger.jsonl, raw_probe_ledger.jsonl) qu'aucun module UI ne lisait -> source
divergente non affichee. Ce lecteur les agrege pour le dashboard, a cote du ledger principal, afin
que l'UI presente la MEME comptabilite que les moteurs de cohorte. Read-only, aucun reseau.
"""
from __future__ import annotations

import json
from pathlib import Path

LEDGERS_COHORTES = {
    "ALPHA": "exploratory_paper_ledger.jsonl",
    "DISCOVERY_PROBE": "discovery_probe_ledger.jsonl",
    "RAW_PROBE": "raw_probe_ledger.jsonl",
}


def _lire_jsonl(p: Path) -> list:
    if not p.is_file():
        return []
    out = []
    for ligne in p.read_text(encoding="utf-8").splitlines():
        ligne = ligne.strip()
        if not ligne:
            continue
        try:
            out.append(json.loads(ligne))
        except json.JSONDecodeError:
            continue
    return out


def lire_ledgers_cohortes(dossier: str | Path) -> dict:
    """Agrege les ledgers de cohortes pour le dashboard. Rend {cohorte: {present, n, fichier, events}}
    plus `_cohortes_disponibles` (celles reellement presentes sur disque)."""
    d = Path(dossier)
    res: dict = {}
    for cohorte, nom in LEDGERS_COHORTES.items():
        p = d / nom
        events = _lire_jsonl(p)
        res[cohorte] = {"present": p.is_file(), "n": len(events), "fichier": nom, "events": events}
    res["_cohortes_disponibles"] = sorted(c for c in LEDGERS_COHORTES if res[c]["present"])
    return res


__all__ = ["lire_ledgers_cohortes", "LEDGERS_COHORTES"]
