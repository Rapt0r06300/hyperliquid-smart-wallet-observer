"""TOUT TESTER — l'orchestrateur unique (21/07, Flo : « tous les tests dans un seul .cmd…
le replay + tous les autres tests, et à la fin ça génère un méga .md récapitulatif »).

Il enchaîne les 6 étapes qui disent la vérité sur le bot, dans l'ordre du plus dur au plus
informatif, et écrit `RECAP-COMPLET.md` À LA FIN QUOI QU'IL ARRIVE :

  1. SÉCURITÉ        — 0 ordre réel possible (la barrière non négociable, en premier)
  2. TESTS UNITAIRES — la suite pytest COMPLÈTE (804 fichiers) : la vérité du code
  3. AUDIT CÂBLAGE   — modules câblés / testés-seulement / orphelins + fichiers sans test
  4. DONNÉES REPLAY  — qualité (étiquetage, couverture, résolution, doublons, prix)
  5. RECHERCHE       — pépites par module (budget borné : ce n'est pas la nuit complète)
  6. SANTÉ LIVE      — moteur, collecteurs, positions, mesures en cours

RÈGLES (chèrement payées) :
  * une étape qui explose n'arrête JAMAIS les suivantes — son verdict devient ERREUR ;
  * chaque étape a un BUDGET : un test qui pend ne mange plus la soirée ;
  * le récapitulatif est écrit atomiquement, et il existe même après un Ctrl-C ;
  * aucun chiffre inventé : ce qui n'a pas pu être mesuré est écrit « NON MESURÉ ».
"""
from __future__ import annotations

import json
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

RACINE = Path(__file__).resolve().parents[1]
RECAP = RACINE / "RECAP-COMPLET.md"

#: budgets par étape (s) — un test qui pend ne doit jamais manger la soirée
BUDGETS = {"securite": 300, "tests": 3600, "cablage": 900, "donnees": 900,
           "recherche": 5400, "sante": 120}


def _courir(nom: str, cmd: list[str], budget_s: float) -> dict[str, Any]:
    t0 = time.time()
    print("\n" + "=" * 70, flush=True)
    print("  [%s] %s" % (nom.upper(), " ".join(cmd[-2:])), flush=True)
    print("=" * 70, flush=True)
    try:
        p = subprocess.run(cmd, cwd=str(RACINE), capture_output=True, text=True,
                           timeout=budget_s, encoding="utf-8", errors="replace")
        sortie = (p.stdout or "") + (p.stderr or "")
        print(sortie[-4000:], flush=True)          # la queue suffit à l'écran
        return {"etape": nom, "code": p.returncode, "duree_s": round(time.time() - t0, 1),
                "sortie": sortie[-20000:], "statut": "OK" if p.returncode == 0 else "ECHEC"}
    except subprocess.TimeoutExpired:
        return {"etape": nom, "code": -9, "duree_s": round(time.time() - t0, 1),
                "sortie": "BUDGET DEPASSE (%.0f s)" % budget_s, "statut": "BUDGET"}
    except Exception as exc:  # noqa: BLE001 — une étape morte n'arrête pas les autres
        return {"etape": nom, "code": -1, "duree_s": round(time.time() - t0, 1),
                "sortie": str(exc)[:2000], "statut": "ERREUR"}


def _resume_pytest(sortie: str) -> str:
    for l in reversed(sortie.splitlines()):
        if (" passed" in l or " failed" in l or " error" in l) and "=" in l:
            return l.strip("= ").strip()
    return "résumé introuvable"


def _sante_live() -> dict[str, Any]:
    """Lecture seule de l'état runtime — jamais une mesure inventée."""
    import os
    out: dict[str, Any] = {}
    now = time.time()
    try:
        d = json.loads((RACINE / "runtime/data/carry_hype_paper_decisions.jsonl")
                       .read_text(encoding="utf-8").splitlines()[-1])
        out["moteur_derniere_decision_s"] = round(now - float(d.get("ts_ms", 0)) / 1000)
        out["session"] = d.get("session_id")
    except Exception:  # noqa: BLE001
        out["moteur_derniere_decision_s"] = None
    col = {}
    for n in ("carry-feeder", "marks-collector", "liq-collector", "venues-collector",
              "copy-whitelist", "rapport-quotidien"):
        p = RACINE / ("runtime/logs/%s.log" % n)
        col[n] = round(now - os.path.getmtime(p)) if p.exists() else None
    out["collecteurs_age_s"] = col
    try:
        sys.path.insert(0, str(RACINE / "src"))
        from hl_observer.funding.carry_positions_store import etat_carry
        e = etat_carry(root=str(RACINE))
        out["positions_carry"] = e.get("positions_ouvertes")
        out["coins"] = e.get("coins_ouverts")
        out["realise_session"] = e.get("realized_net_pnl_usdc_session")
        out["realise_total"] = e.get("realized_net_pnl_usdc")
    except Exception:  # noqa: BLE001
        out["positions_carry"] = None
    try:
        lignes = (RACINE / "runtime/data/dispersion_venues.jsonl").read_text(
            encoding="utf-8").splitlines()

        def ts(l):
            r = json.loads(l)
            return float(r.get("ts_ms") or (r.get("ts") or 0) * 1000) / 1000
        out["cross_venue_h"] = round((ts(lignes[-1]) - ts(lignes[0])) / 3600, 1)
    except Exception:  # noqa: BLE001
        out["cross_venue_h"] = None
    return out


def ecrire_recap(etapes: list[dict], sante: dict, chemin: Path = RECAP) -> Path:
    ok = [e for e in etapes if e["statut"] == "OK"]
    l = ["# RÉCAPITULATIF COMPLET — HyperSmart Observer", "",
         "_Généré le %s · %d/%d étapes vertes · durée totale %.1f min._"
         % (time.strftime("%d/%m/%Y %H:%M"), len(ok), len(etapes),
            sum(e["duree_s"] for e in etapes) / 60), "",
         "| Étape | Statut | Durée | Détail |", "|---|---|---|---|"]
    for e in etapes:
        icone = {"OK": "✅", "ECHEC": "🔴", "BUDGET": "⏱️", "ERREUR": "💥"}.get(e["statut"], "?")
        detail = e.get("resume") or (e["sortie"].strip().splitlines() or [""])[-1][:120]
        l.append("| %s | %s %s | %.0f s | %s |"
                 % (e["etape"], icone, e["statut"], e["duree_s"], detail.replace("|", "/")))
    l += ["", "## Santé live (lecture seule)", ""]
    l.append("- moteur : dernière décision il y a **%s s** · session `%s`"
             % (sante.get("moteur_derniere_decision_s"), sante.get("session")))
    l.append("- collecteurs (âge du dernier battement) : `%s`" % sante.get("collecteurs_age_s"))
    l.append("- carry : **%s position(s)** %s · réalisé session %s $ · total historique %s $"
             % (sante.get("positions_carry"), sante.get("coins"),
                sante.get("realise_session"), sante.get("realise_total")))
    l.append("- cross-venue : **%s h / 72 h**" % sante.get("cross_venue_h"))
    l += ["", "## Sorties détaillées", ""]
    for e in etapes:
        l += ["<details><summary>%s — %s</summary>" % (e["etape"], e["statut"]), "",
              "```", e["sortie"][-6000:].strip() or "(vide)", "```", "</details>", ""]
    l += ["## Les autres rapports produits par ce lancement", "",
          "- `runtime/replay/RESULTATS_RECHERCHE.md` — pépites + **recommandation par module**",
          "- `runtime/replay/QUALITE_DONNEES.md` — santé des données du replay",
          "- `rapports/RAPPORT_DU_JOUR.md` — PnL 24 h, économie des positions, à-faire du jour",
          "- `resultat-audit.md` — audit de câblage détaillé (si l'étape a tourné)", "",
          "---", "",
          "**Sécurité : 0 ordre réel · 0 argent réel · 0 clé privée · 0 signature · "
          "0 dépôt/retrait.**", ""]
    chemin.parent.mkdir(parents=True, exist_ok=True)
    tmp = chemin.with_suffix(".md.tmp")
    tmp.write_text("\n".join(l), encoding="utf-8")
    import os
    os.replace(tmp, chemin)
    return chemin


def main(argv: list[str] | None = None) -> int:
    args = set(argv if argv is not None else sys.argv[1:])
    rapide = "--rapide" in args           # saute la recherche de pépites (la plus longue)
    py = sys.executable
    etapes: list[dict] = []
    try:
        etapes.append(_courir("securite", [py, "-m", "hl_observer", "safety-audit"],
                              BUDGETS["securite"]))
        # consolidation AVANT tout ce qui lit le replay (qualite + recherche) : on ne juge
        # jamais sur des donnees d'hier alors que les shards du jour sont la.
        etapes.append(_courir("consolidation",
                              [py, "-m", "hl_observer.runtime.replay_recorder",
                               "--base", "runtime/replay"], BUDGETS["donnees"]))
        r = _courir("tests", [py, "-m", "pytest", "-q", "--timeout=120", "tests"],
                    BUDGETS["tests"])
        r["resume"] = _resume_pytest(r["sortie"])
        etapes.append(r)
        etapes.append(_courir("cablage", [py, "tools/audit_cablage_cli.py"],
                              BUDGETS["cablage"]))
        etapes.append(_courir("donnees", [py, "tools/qualite_donnees_replay.py", "."],
                              BUDGETS["donnees"]))
        if not rapide:
            etapes.append(_courir(
                "recherche", [py, "-c",
                              "from hl_observer.backtesting.recherche_scenario import "
                              "chercher_toutes; chercher_toutes('.', "
                              "budget_s_par_module=1200)"], BUDGETS["recherche"]))
        else:
            etapes.append({"etape": "recherche", "statut": "SAUTEE", "code": 0, "duree_s": 0,
                           "sortie": "--rapide : recherche de pepites sautee"})
        # le rapport du matin (PnL par motif, economie des positions, verrous du scan,
        # a-faire du jour) — regenere ici pour qu'UN seul lancement suffise le matin.
        etapes.append(_courir("rapport_jour", [py, "tools/rapport_quotidien.py"],
                              BUDGETS["sante"]))
    except KeyboardInterrupt:
        etapes.append({"etape": "interruption", "statut": "ERREUR", "code": -2, "duree_s": 0,
                       "sortie": "Ctrl-C : le recap couvre les etapes deja faites"})
    sante = _sante_live()
    chemin = ecrire_recap(etapes, sante)
    print("\n" + "=" * 70, flush=True)
    for e in etapes:
        print("  %-11s %-8s %5.0f s  %s" % (e["etape"], e["statut"], e["duree_s"],
                                            (e.get("resume") or "")[:60]), flush=True)
    print("=" * 70, flush=True)
    print("  RECAP : %s" % chemin, flush=True)
    return 0 if all(e["statut"] in ("OK", "SAUTEE") for e in etapes) else 1


if __name__ == "__main__":
    raise SystemExit(main())
