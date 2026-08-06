"""[Bloc 36/53/54 / AUD-368,369,113] Parite live/replay (MEME adaptateur) + replay rapide puis exact +
reconciliation des 5 vues.

- rejouer(normalizer, raw_msgs) : applique le MEME normalizer offline qu'en live -> lignes canoniques.
- parite_live_replay(live, replay) : egalite STRICTE (sinon on liste les differences).
- fast_screen(lignes) vs exact_replay(lignes) : le rapide ne doit jamais contredire l'exact.
- reconcilier_5_vues(moteur, ledger, store, api, ui) : 5 vues d'equity doivent concorder (AUD-113).
deterministe, 0 reseau."""
from __future__ import annotations

from typing import Callable, Mapping, Sequence


def rejouer(normalizer: Callable, raw_msgs: Sequence) -> list:
    """Meme normalizer qu'en live -> garantit la parite par construction (un seul adaptateur)."""
    return [normalizer(m) for m in raw_msgs]


def parite_live_replay(live: Sequence, replay: Sequence) -> dict:
    """Egalite stricte ligne a ligne. Retourne parite + indices divergents."""
    if len(live) != len(replay):
        return {"parite": False, "raison": "longueurs", "n_live": len(live), "n_replay": len(replay)}
    diffs = [i for i, (a, b) in enumerate(zip(live, replay)) if a != b]
    return {"parite": not diffs, "diffs": diffs[:10], "n": len(live)}


def fast_screen(lignes: Sequence[Mapping]) -> dict:
    """Agregats rapides (bornes) : compte + somme notionnelle approx (prix*taille)."""
    n = 0
    notion = 0.0
    for r in lignes:
        n += 1
        px, sz = r.get("prix"), r.get("taille")
        if px is not None and sz is not None:
            notion += float(px) * float(sz)
    return {"n": n, "notionnel": notion}


def exact_replay(lignes: Sequence[Mapping]) -> dict:
    """Recompute complet, par symbole."""
    par_sym: dict = {}
    notion = 0.0
    for r in lignes:
        px, sz = r.get("prix"), r.get("taille")
        v = (float(px) * float(sz)) if (px is not None and sz is not None) else 0.0
        notion += v
        par_sym[r.get("symbole")] = par_sym.get(r.get("symbole"), 0.0) + v
    return {"n": len(lignes), "notionnel": notion, "par_symbole": par_sym}


def coherence_fast_exact(fast: Mapping, exact: Mapping, *, tol: float = 1e-6) -> dict:
    """Le fast screen ne doit pas contredire l'exact sur les invariants (compte, notionnel total)."""
    ok = (fast["n"] == exact["n"]) and abs(fast["notionnel"] - exact["notionnel"]) <= tol
    return {"coherent": ok, "delta_notionnel": fast["notionnel"] - exact["notionnel"]}


def reconcilier_5_vues(moteur: float, ledger: float, store: float, api: float, ui: float,
                       *, tol: float = 1e-6) -> dict:
    """Les 5 vues d'equity (moteur/ledger/store/api/ui) doivent concorder (AUD-113). Ecart -> signale."""
    vues = {"moteur": moteur, "ledger": ledger, "store": store, "api": api, "ui": ui}
    ref = moteur
    ecarts = {k: (v - ref) for k, v in vues.items() if abs(v - ref) > tol}
    return {"coherent": not ecarts, "ecarts": ecarts, "vues": vues}
