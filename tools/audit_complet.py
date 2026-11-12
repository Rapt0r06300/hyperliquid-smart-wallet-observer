#!/usr/bin/env python3
"""AUDIT COMPLET — un seul rapport : les données collectées, l'exécutabilité, l'économie, et QUOI AMÉLIORER.

Compose les instruments existants pour donner, en une page, l'état sérieux de la recherche et la liste
PRIORISÉE des chantiers vers un PnL positif :

1. DONNÉES  : chaque type collecté est-il récolté, certifié, utilisé ? (``auditer_donnees_collectees``)
2. MESURE   : le labo peut-il mesurer quelque chose, et sinon que collecter ? (``etat_executabilite``)
3. ÉCONOMIE : verdicts et effets mesurés par hypothèse (``copiabilite/PLAN_DE_RECHERCHE.json``).
4. CHANTIERS: la synthèse déduit les priorités (latence, maker, conditionnement, réplication lente).

Lecture seule ; aucun calcul réseau. À lancer après un cycle collecte → Certificateur → labo.
"""
from __future__ import annotations

import argparse
import contextlib
import importlib.util
import json
import sys
from pathlib import Path
from typing import Any

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE))
sys.path.insert(0, str(RACINE / "src"))


def _charger(nom: str):
    spec = importlib.util.spec_from_file_location(nom, RACINE / "tools" / f"{nom}.py")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def _plan_economique(root: Path) -> dict[str, Any]:
    chemin = root / "runtime" / "reports" / "copy_vault_quant_lab" / "copiabilite" / "PLAN_DE_RECHERCHE.json"
    try:
        return json.loads(chemin.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return {}


def synthese(data_audit: list[dict[str, Any]], sonde: dict[str, Any], plan: dict[str, Any]) -> list[str]:
    """Déduit la liste priorisée des chantiers à partir des trois audits."""
    out: list[str] = ["", "═══ QUOI AMÉLIORER (synthèse priorisée) ═══"]
    # 1. mesurabilité
    if sonde and sonde.get("executable") is False:
        cibles = sonde.get("coins_a_collecter") or []
        tete = ", ".join(c.get("coin", "") for c in cibles[:6] if isinstance(c, dict))
        out.append(f"① PRIORITÉ ABSOLUE — rendre le labo MESURABLE : 0 signal exécutable "
                   f"({int(sonde.get('signaux_train') or 0):,} signaux). Collecter des carnets pour : {tete}".replace(",", " "))
    elif sonde and sonde.get("executable"):
        out.append(f"① Le labo est MESURABLE ({int(sonde.get('signaux_executables') or 0):,} signaux exécutables).".replace(",", " "))
    # 2. données gâchées
    gaspilles = [r["famille"] for r in data_audit if str(r.get("etat", "")).startswith("CERTIFIÉ · NON")]
    if gaspilles:
        out.append(f"② DONNÉES GÂCHÉES (certifiées, non utilisées) : {', '.join(gaspilles)} — les brancher au labo.")
    non_collectes = [r["famille"] for r in data_audit
                     if r.get("etat") == "JAMAIS COLLECTÉ" and int(r.get("shards_coffre") or 0) == 0]
    if non_collectes:
        out.append(f"③ FLUX JAMAIS COLLECTÉS : {', '.join(non_collectes)} — vérifier qu'un collecteur les écrit.")
    # 3. économie : où est la perte
    rangs = plan.get("hypotheses") or []
    def _num(v):
        return v if isinstance(v, (int, float)) and not isinstance(v, bool) else None
    negatifs = [h for h in rangs if isinstance(h, dict) and _num(h.get("usd_par_jour")) is not None
                and _num(h["usd_par_jour"]) < 0]
    rejetes = [h for h in rangs if isinstance(h, dict) and str(h.get("status")) == "REJECTED"]
    if negatifs or rejetes:
        out.append(f"④ RECHERCHE NÉGATIVE ({len(rejetes)} rejetées, {len(negatifs)} effets < 0) → chantiers structurels :")
        out.append("   · LATENCE : balayer le délai de copie (tools/chantier_latence.py) — le délai tue l'avantage.")
        out.append("   · MAKER : exécuter aux ordres-limites du leader (gagner le spread au lieu de le payer).")
        out.append("   · CONDITIONNEMENT : ne copier que fill agressif + OFI favorable + leader d'élite + régime.")
        out.append("   · RÉPLICATION LENTE par position (vault_portfolio) : moins sensible au timing.")
    elif rangs:
        out.append("④ Une piste non négative existe — l'approfondir avec plus de données (VALIDATION/OOS/FORWARD).")
    return out


def main(argv: list[str] | None = None) -> int:
    for flux in (sys.stdout, sys.stderr):
        with contextlib.suppress(AttributeError, ValueError):
            flux.reconfigure(encoding="utf-8", errors="replace")
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--root", default=str(RACINE))
    args = p.parse_args(argv)
    root = Path(args.root)

    ad = _charger("auditer_donnees_collectees")
    ee = _charger("etat_executabilite")
    data_audit = ad.auditer(root)
    rapport = ee.dernier_rapport(root)
    sonde = ee.lire_sonde(rapport) if rapport is not None else {}
    plan = _plan_economique(root)

    print("╔" + "═" * 70 + "╗")
    print("║  AUDIT COMPLET — données · mesure · économie · chantiers              ║")
    print("╚" + "═" * 70 + "╝")
    print()
    print("── 1. DONNÉES COLLECTÉES ──")
    for ligne in ad.rendre(data_audit)[-4:]:          # le récapitulatif des écarts
        print(ligne)
    print()
    print("── 2. MESURE (exécutabilité du labo) ──")
    for ligne in ee.rendre(sonde, run_nom=rapport.parent.name if rapport else "")[:6]:
        print(ligne)
    print()
    print("── 3. ÉCONOMIE (verdicts) ──")
    resume = plan.get("resume")
    if isinstance(resume, dict):
        compte = {k: resume.get(k) for k in ("PROVEN", "PROMISING", "MORE_DATA", "UNMEASURABLE", "REJECTED") if k in resume}
        print("   " + " · ".join(f"{k}:{v}" for k, v in compte.items()) if compte else "   " + json.dumps(resume, ensure_ascii=False)[:200])
    else:
        print("   (aucun plan de recherche lisible — lancer l'étude de copiabilité)")
    for ligne in synthese(data_audit, sonde, plan):
        print(ligne)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
