"""#45 — « POURQUOI RIEN NE S'OUVRE ? » — agrège les motifs de REFUS du carry depuis son journal.
Au lieu de deviner, on LIT : top des raisons, avec compte et part. Répond en une ligne à la question
la plus fréquente. 100 % lecture, aucun ordre. Journal absent -> réponse honnête « pas de données ».
"""
from __future__ import annotations

import json
from pathlib import Path

JOURNAL_RELPATH = Path("runtime") / "data" / "carry_hype_paper_decisions.jsonl"


def _lignes(root: str | Path, max_lignes: int = 5000) -> list[dict]:
    p = Path(root) / JOURNAL_RELPATH
    try:
        txt = p.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return []
    out: list[dict] = []
    for ligne in txt.splitlines()[-int(max_lignes):]:
        ligne = ligne.strip()
        if not ligne:
            continue
        try:
            o = json.loads(ligne)
            if isinstance(o, dict):
                out.append(o)
        except ValueError:
            continue
    return out


def resumer_refus(root: str | Path = ".", *, max_lignes: int = 5000) -> dict:
    """{n_decisions, n_acceptees, n_refusees, top_motifs:[(motif, n, part)], message}.
    `message` est une phrase prête à afficher : la RAISON n°1 pour laquelle rien ne s'ouvre."""
    lignes = _lignes(root, max_lignes)
    if not lignes:
        return {"n_decisions": 0, "n_acceptees": 0, "n_refusees": 0, "top_motifs": [],
                "message": "pas encore de décision enregistrée (laisse le bot tourner)"}
    motifs: dict[str, int] = {}
    acceptees = 0
    for l in lignes:
        d = l.get("decision") or {}
        if d.get("viable"):
            acceptees += 1
        else:
            m = str(d.get("motif") or "INCONNU")
            motifs[m] = motifs.get(m, 0) + 1
    n = len(lignes)
    refusees = n - acceptees
    top = sorted(motifs.items(), key=lambda kv: -kv[1])[:5]
    top_pct = [(m, c, round(100.0 * c / max(1, refusees), 1)) for m, c in top]
    if refusees == 0:
        msg = "aucun refus : toutes les décisions récentes étaient viables"
    else:
        m1, c1, p1 = top_pct[0]
        msg = "rien ne s'ouvre surtout à cause de : %s (%d refus, %.0f%% des refus)" % (m1, c1, p1)
    return {"n_decisions": n, "n_acceptees": acceptees, "n_refusees": refusees,
            "top_motifs": top_pct, "message": msg, "real_execution": False}


__all__ = ["resumer_refus", "JOURNAL_RELPATH"]
