"""TAPE L2/OFI SHADOW synchronisée autour des fills métaordre (rectif Flo 24/07).

Problème corrigé : appliquer le carnet COURANT à des fills HISTORIQUES invalide la courbe de coûts. Ici on
enregistre, autour de CHAQUE fill de vault suivi, un snapshot L2 HORODATÉ :
  • à l'ENTRÉE = réception du fill + notre latence réelle (capture_ts − fill_time) ;
  • à la SORTIE = entrée + horizon (le coût d'exécution de sortie compte aussi).
Plus l'OFI top-5 (variation de pression bid/ask depuis le snapshot précédent du même coin).

Écrit `runtime/data/metaorder_l2_tape.jsonl`. Les prochaines fenêtres OOS utilisent CES carnets synchronisés
(coût entrée+sortie exécutables), jamais le carnet courant. AUCUNE position, RAW intact, lecture seule (l2Book
public). `shadow=true`, `real_execution=false`. 0 ordre, 0 clé, 0 signature.
"""
from __future__ import annotations

import json
import time
from pathlib import Path

TAPE_RELPATH = Path("runtime") / "data" / "metaorder_l2_tape.jsonl"


def cle_fill(coin, hsh, fill_time) -> tuple:
    """Clé d'un fill dans la tape (coin, hash, fill_time) — pour joindre entrée↔sortie et aux signaux offline."""
    return (str(coin).upper() if coin else None, hsh, int(fill_time or 0))


def resume_book(book_brut: dict) -> dict | None:
    """Résumé horodatable d'un l2Book BRUT : bid/ask/mid, spread bps, 5 niveaux (px,sz) de chaque côté
    (conservés pour un VWAP-walk exact plus tard). None si illisible (jamais inventé)."""
    try:
        bids, asks = book_brut["levels"][0], book_brut["levels"][1]
        bid, ask = float(bids[0]["px"]), float(asks[0]["px"])
        if bid <= 0 or ask <= 0:
            return None
        mid = 0.5 * (bid + ask)
        top = lambda cote: [[float(x["px"]), float(x["sz"])] for x in cote[:5]]   # noqa: E731
        return {"bid": bid, "ask": ask, "mid": round(mid, 8), "spread_bps": round((ask - bid) / mid * 1e4, 3),
                "bids5": top(bids), "asks5": top(asks)}
    except (KeyError, IndexError, TypeError, ValueError):
        return None


def ofi_top5(prev5: list | None, cur5: list | None) -> float | None:
    """OFI top-5 = (Δ taille bid) − (Δ taille ask) entre deux snapshots [[px,sz]...]. >0 = pression acheteuse.
    `prev5`/`cur5` = {'bids5','asks5'}. None si un côté manque."""
    try:
        db = sum(s for _, s in cur5["bids5"]) - sum(s for _, s in prev5["bids5"])
        da = sum(s for _, s in cur5["asks5"]) - sum(s for _, s in prev5["asks5"])
        return round(db - da, 4)
    except (KeyError, TypeError, ValueError):
        return None


def ligne_tape(*, phase: str, fill: dict, book_brut: dict, capture_ts: float, prev_resume: dict | None = None,
               entry_ts: float | None = None) -> dict | None:
    """Construit une ligne de tape (phase 'entry' ou 'exit') pour un fill donné. À l'entrée : latence réelle =
    capture_ts − fill_time ; OFI vs le snapshot précédent du coin. À la sortie : délai depuis l'entrée. None si
    le carnet est illisible (on n'écrit RIEN plutôt qu'un carnet inventé)."""
    r = resume_book(book_brut)
    if r is None:
        return None
    coin = str(fill.get("coin") or "").upper()
    ft = int(fill.get("ts_ms") or fill.get("fill_time") or 0)
    ligne = {"phase": phase, "coin": coin, "sens": int(fill.get("signe") or fill.get("sens") or 0),
             "vault": str(fill.get("vault") or "")[:42], "fill_time": ft, "hash": fill.get("hash"),
             "capture_ts": int(capture_ts), "mid": r["mid"], "spread_bps": r["spread_bps"],
             "top5": {"bids": r["bids5"], "asks": r["asks5"]},
             "shadow": True, "real_execution": False}
    if phase == "entry":
        ligne["latence_ms"] = int(capture_ts - ft)
        ligne["ofi_top5"] = ofi_top5(prev_resume, {"bids5": r["bids5"], "asks5": r["asks5"]}) if prev_resume else None
    else:
        ligne["delai_sortie_ms"] = int(capture_ts - (entry_ts or ft))
    return ligne


def fills_a_enregistrer(fills: list, deja: set, *, now_ms: float, age_max_ms: float = 5_000.0) -> list:
    """Fills FRAIS (âge ≤ age_max_ms) pas encore dans `deja` (clé (coin,hash,fill_time)) → à capturer à l'entrée.
    Borne : on ne rejoue jamais l'historique (seulement les fills récents = ~entrée + latence)."""
    out = []
    for f in fills or []:
        ft = int((f or {}).get("ts_ms") or 0)
        k = cle_fill(f.get("coin"), f.get("hash"), ft)
        if ft and (now_ms - ft) <= age_max_ms and k not in deja:
            out.append(f)
    return out


def exits_dus(pending: dict, now_ms: float) -> list:
    """Clés dont l'instant de sortie (pending[cle] = due_ts) est atteint (now ≥ due) → à capturer à la sortie."""
    return [k for k, due in list(pending.items()) if now_ms >= due]


def ecrire_lignes(root, lignes: list) -> None:
    """Append atomique-suffisant des lignes de tape (une par ligne JSON). Jamais de suppression."""
    if not lignes:
        return
    p = Path(root) / TAPE_RELPATH
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("a", encoding="utf-8") as fh:
        for l in lignes:
            fh.write(json.dumps(l, ensure_ascii=False) + "\n")


def charger_tape(root) -> dict:
    """Charge la tape → {cle_fill: {'entry': ligne, 'exit': ligne}} pour joindre aux signaux offline (coût
    synchronisé entrée/sortie). Lecture seule."""
    p = Path(root) / TAPE_RELPATH
    out: dict = {}
    try:
        lignes = p.read_text(encoding="utf-8", errors="ignore").splitlines()
    except OSError:
        return out
    for l in lignes:
        if not l.strip():
            continue
        try:
            d = json.loads(l)
        except ValueError:
            continue
        k = cle_fill(d.get("coin"), d.get("hash"), d.get("fill_time"))
        out.setdefault(k, {})[d.get("phase")] = d
    return out


__all__ = ["TAPE_RELPATH", "cle_fill", "resume_book", "ofi_top5", "ligne_tape", "fills_a_enregistrer",
           "exits_dus", "ecrire_lignes", "charger_tape"]
