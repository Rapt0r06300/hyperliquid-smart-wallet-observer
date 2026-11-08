#!/usr/bin/env python3
"""Suivi ADAPTATIF des leaders : curés (vettés) + traders ACTIFS découverts par l'explorer.

Problème observé : on suit 71 leaders mais la plupart sont inactifs à l'instant t, donc
les fills viennent d'un seul trader. L'explorer, lui, découvre en continu les traders
réellement actifs. Cet outil fusionne, à chaque lancement, la liste suivie :

    suivis = base curée (toujours gardée) + top traders ACTIFS (classement explorer), plafonné

Le débit REST est capé par l'AIMD anti-429 du poll (suivre plus de leaders ne crée pas plus
de 429 : chaque leader est simplement interrogé un peu moins souvent). Résultat : des fills
de BEAUCOUP plus de traders, donc plus de diversité et de jours scoreables pour le labo.
Non destructif : la base curée est sauvegardée une fois, l'ancienne liste est sauvegardée.
PAPER / lecture seule vis-à-vis du réseau.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]

LEADERS = Path("config") / "copy_vault_leaders.json"
CURES = Path("config") / "copy_vault_leaders_cures.json"     # base vettée permanente
CLASSEMENT = Path("config") / "leaders_actifs_classement.json"  # écrit par l'explorer
CAP_DEFAUT = 120


def _valide(v) -> str | None:
    s = str(v or "").strip().lower()
    return s if s.startswith("0x") and len(s) >= 10 else None


def construire_suivis(cures: list[str], actifs: list[str], *, cap: int = CAP_DEFAUT) -> list[str]:
    """Base curée (gardée, en tête) + traders actifs non déjà curés, plafonné à `cap`."""
    out: list[str] = []
    vus: set[str] = set()
    for src in (cures, actifs):          # curés d'abord (vettés), puis actifs
        for v in src:
            vv = _valide(v)
            if vv and vv not in vus:
                vus.add(vv)
                out.append(vv)
                if len(out) >= cap:
                    return out
    return out


def _charger_vaults(path: Path) -> list[str]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    v = data.get("vaults") if isinstance(data, dict) else data
    return [x for x in (v or []) if _valide(x)]


def _charger_actifs(path: Path) -> list[str]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    actifs = data.get("actifs") if isinstance(data, dict) else data
    out = []
    for item in actifs or []:
        v = item.get("vault") if isinstance(item, dict) else item
        if _valide(v):
            out.append(str(v).strip().lower())
    return out


def fusionner(root: Path, *, cap: int = CAP_DEFAUT) -> dict:
    leaders_path = root / LEADERS
    cures_path = root / CURES
    # 1) snapshot de la base curée (une seule fois) depuis la liste actuelle.
    if not cures_path.exists() and leaders_path.exists():
        cures_path.parent.mkdir(parents=True, exist_ok=True)
        cures_path.write_text(json.dumps(
            {"vaults": _charger_vaults(leaders_path), "note": "base curee vettee (figee)"},
            ensure_ascii=False, indent=2), encoding="utf-8")
    cures = _charger_vaults(cures_path) or _charger_vaults(leaders_path)
    actifs = _charger_actifs(root / CLASSEMENT)
    if not actifs:
        return {"statut": "pas_de_classement", "cures": len(cures), "actifs_ajoutes": 0,
                "total": len(cures)}
    suivis = construire_suivis(cures, actifs, cap=cap)
    ajoutes = [v for v in suivis if v not in set(cures)]
    # 2) sauvegarde de l'ancienne liste puis écriture.
    if leaders_path.exists():
        bak = leaders_path.with_suffix(".json.avant-fusion.bak")
        bak.write_text(leaders_path.read_text(encoding="utf-8", errors="replace"), encoding="utf-8")
    leaders_path.parent.mkdir(parents=True, exist_ok=True)
    leaders_path.write_text(json.dumps(
        {"vaults": suivis, "source": "fusion curés+actifs (fusionner_leaders_actifs)",
         "n_cures": len(cures), "n_actifs_ajoutes": len(ajoutes), "cap": cap},
        ensure_ascii=False, indent=2), encoding="utf-8")
    return {"statut": "OK", "cures": len(cures), "actifs_ajoutes": len(ajoutes), "total": len(suivis)}


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Fusionne leaders curés + actifs découverts (suivi adaptatif).")
    p.add_argument("--root", default=str(RACINE))
    p.add_argument("--cap", type=int, default=CAP_DEFAUT)
    args = p.parse_args(argv)
    rap = fusionner(Path(args.root), cap=max(1, args.cap))
    if rap["statut"] == "OK":
        print(f"[leaders] suivi adaptatif : {rap['cures']} cures + {rap['actifs_ajoutes']} actifs "
              f"= {rap['total']} leaders suivis.", flush=True)
    else:
        print(f"[leaders] {rap['statut']} : {rap['cures']} cures conserves (pas d'ajout). "
              f"L'explorer doit tourner un cycle pour produire le classement.", flush=True)
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
