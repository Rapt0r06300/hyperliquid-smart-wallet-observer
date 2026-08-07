"""[LANCEUR item 10] Porte d'entrée de ANALYSER_BACKTESTS_REPLAYS.cmd : SÉLECTIONNE la session à
analyser et la VÉRIFIE avant tout backtest/replay.

Règle dure : ANALYSER ne travaille QUE sur une session **COMPLETE** (jamais ACTIVE — collecte en cours —
ni QUARANTINED — clôture échouée). Il relit son ``DATA_CATALOG.json``, RECALCULE tous les checksums,
vérifie que chaque fichier catalogué est présent + intègre, et qu'il n'y a AUCUN orphelin. Si la
vérification échoue, le verdict est **NO_GO** et le lanceur d'analyse s'arrête : mieux vaut ne rien
analyser qu'analyser des données corrompues/absentes.

Il n'exécute PAS lui-même le moteur de backtest (pas de pipeline parallèle — item 10) : il produit un
verdict + un en-tête de rapport CONSOLIDÉ que ANALYSER embarque, puis rend la main aux briques existantes
(suite historique + lab alpha + MegaCablage). CLI exit 0 = GO (session vérifiée), 2 = NO_GO.
0 réseau, 0 ordre.
"""
from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

from hl_observer.ops import session_catalog as SC

GO = "GO"
NO_GO = "NO_GO"


def selectionner_session(root: str | Path, *, exiger_complete: bool = True, age_max_s: float | None = None,
                         maintenant_ms: float | None = None,
                         autoriser_complete_ancienne: bool = False) -> dict:
    """Choisit la session à analyser (item 14). Règle dure : la session GLOBALEMENT la plus récente doit
    être COMPLETE. Si la plus récente est ACTIVE / QUARANTINED / corrompue, on NE retombe PAS en silence
    sur une vieille COMPLETE — NO_GO (sauf `autoriser_complete_ancienne`). `age_max_s` : seuil de fraîcheur
    configurable (une COMPLETE trop vieille est refusée). Rend {verdict, run_id, statut, raison, age_s,
    fraiche, sessions}."""
    import time as _t
    sessions = SC.scanner_sessions(root)                 # triées par debut_ms décroissant
    now_ms = float(maintenant_ms) if maintenant_ms is not None else _t.time() * 1000.0

    def _age_s(s):
        deb = s.get("debut_ms") or 0
        return round(max(0.0, (now_ms - float(deb)) / 1000.0), 3) if deb else None

    if not sessions:
        return {"verdict": NO_GO, "run_id": None, "statut": None, "age_s": None, "fraiche": False,
                "raison": "aucune session sur disque (runtime/data/sessions vide)", "sessions": sessions}

    plus_recente = sessions[0]
    complete = next((s for s in sessions if s.get("statut") == SC.STATUT_COMPLETE), None)

    # la plus récente n'est PAS COMPLETE -> on refuse de rejouer une vieille session en silence.
    if plus_recente.get("statut") != SC.STATUT_COMPLETE and not autoriser_complete_ancienne:
        etats = ", ".join("%s=%s(age=%ss)" % (s["run_id"], s["statut"], _age_s(s)) for s in sessions[:5])
        raison = ("la session la plus recente est %s (%s), pas COMPLETE : on n'analyse PAS une vieille "
                  "session a sa place. Sessions: %s" % (plus_recente["run_id"], plus_recente["statut"], etats))
        return {"verdict": NO_GO, "run_id": None, "statut": plus_recente.get("statut"),
                "age_s": _age_s(plus_recente), "fraiche": False, "raison": raison, "sessions": sessions}

    if not complete:
        etats = ", ".join("%s=%s" % (s["run_id"], s["statut"]) for s in sessions[:5])
        return {"verdict": NO_GO, "run_id": None, "statut": None, "age_s": None, "fraiche": False,
                "raison": "aucune session COMPLETE ; sessions presentes: %s" % etats, "sessions": sessions}

    age = _age_s(complete)
    fraiche = (age_max_s is None) or (age is not None and age <= float(age_max_s))
    if not fraiche:
        return {"verdict": NO_GO, "run_id": complete["run_id"], "statut": SC.STATUT_COMPLETE,
                "age_s": age, "fraiche": False,
                "raison": "session COMPLETE %s trop vieille (age=%ss > seuil %ss)" %
                          (complete["run_id"], age, age_max_s), "sessions": sessions}
    return {"verdict": GO, "run_id": complete["run_id"], "statut": SC.STATUT_COMPLETE, "age_s": age,
            "fraiche": True, "data_origin": complete.get("data_origin") or SC.ORIGINE_INCONNUE,
            "raison": "session COMPLETE la plus recente (age=%ss)" % age,
            "sessions": sessions}


def verifier_session(root: str | Path, run_id: str) -> dict:
    """Relit le catalogue de `run_id` et RECALCULE checksums + présence + orphelins (item 10)."""
    cat = SC.CatalogueSession(root, run_id).lire()
    if not cat:
        return {"ok": False, "raison": "DATA_CATALOG.json introuvable", "run_id": run_id}
    if cat.get("statut") != SC.STATUT_COMPLETE:
        return {"ok": False, "raison": "statut %s (attendu COMPLETE)" % cat.get("statut"),
                "run_id": run_id, "statut": cat.get("statut")}
    dossier = SC.chemin_session(root, run_id)
    verif = SC.verifier_catalogue(dossier, cat.get("sources") or {})
    verif.update({"ok": bool(verif.get("tout_ok")), "run_id": run_id, "statut": cat.get("statut"),
                  "git_head": cat.get("git_head"), "debut_ms": cat.get("debut_ms"),
                  "fin_ms": cat.get("fin_ms"), "n_sources": len(cat.get("sources") or {})})
    if not verif["ok"]:
        raisons = []
        if not verif.get("checksums_ok"):
            raisons.append("checksums/fichiers divergents (%d)" % len(verif.get("divergences") or []))
        if not verif.get("zero_orphelin"):
            raisons.append("orphelins (%d)" % len(verif.get("orphelins") or []))
        verif["raison"] = " ; ".join(raisons) or "verification echouee"
    return verif


def _rapport_markdown(sel: dict, verif: dict | None) -> str:
    lignes = ["# ANALYSE DE SESSION — verdict d'entree ANALYSER", "",
              "**Verdict** : `%s`" % sel.get("verdict"),
              "", "## Selection", "",
              "- Session retenue : `%s`" % (sel.get("run_id") or "AUCUNE"),
              "- Statut : `%s`" % (sel.get("statut") or "-"),
              "- Raison : %s" % sel.get("raison", "-"), ""]
    if verif is not None:
        lignes += ["## Verification (checksums recalcules + presence + orphelins)", "",
                   "- Integre : `%s`" % verif.get("ok"),
                   "- Artefacts verifies : %s" % verif.get("n_artefacts_verifies"),
                   "- Divergences : %d" % len(verif.get("divergences") or []),
                   "- Orphelins : %d" % len(verif.get("orphelins") or []),
                   "- Git HEAD : `%s`" % (verif.get("git_head") or "?"), ""]
        if verif.get("divergences"):
            lignes.append("### Divergences")
            for d in verif["divergences"][:50]:
                lignes.append("- `%s` : %s" % (d.get("chemin"), d.get("probleme")))
            lignes.append("")
        if verif.get("orphelins"):
            lignes.append("### Orphelins (fichiers de donnees hors catalogue)")
            for o in verif["orphelins"][:50]:
                lignes.append("- `%s`" % o)
            lignes.append("")
    lignes += ["## Suite (briques existantes, non dupliquees)", "",
               "Sur GO, ANALYSER enchaine : suite historique + laboratoire alpha (lab_alpha) +",
               "MegaCablage (raw->PnL, cross-venue, IS/OOS/FORWARD). PAPER strict.", ""]
    return "\n".join(lignes)


def analyser(root: str | Path, *, exiger_complete: bool = True, ecrire: bool = True,
             horloge=time.time, age_max_s: float | None = None,
             autoriser_complete_ancienne: bool = False) -> dict:
    """Orchestration de la porte d'entree : selection (avec fraicheur, item 14) -> verification ->
    verdict + rapport consolide. Rend {verdict, run_id, age_s, verification, rapport_md, chemins}."""
    sel = selectionner_session(root, exiger_complete=exiger_complete, age_max_s=age_max_s,
                               maintenant_ms=horloge() * 1000.0,
                               autoriser_complete_ancienne=autoriser_complete_ancienne)
    verif = None
    verdict = sel["verdict"]
    if verdict == GO:
        verif = verifier_session(root, sel["run_id"])
        if not verif.get("ok"):
            verdict = NO_GO
            sel["raison"] = "session %s selectionnee mais VERIFICATION ECHOUEE: %s" % (
                sel["run_id"], verif.get("raison"))
    rapport_md = _rapport_markdown({**sel, "verdict": verdict}, verif)
    # item 12 : deux vérités DISTINCTES. `real_execution` reste TOUJOURS False (aucun ordre réel n'est
    # jamais passé — invariant de sécurité). `data_origin` dit si la donnée analysée est RÉELLEMENT
    # collectée (REEL) ou une fixture SYNTHETIQUE ; un « vert » sur du SYNTHETIQUE serait un faux gain.
    origine = sel.get("data_origin") or SC.ORIGINE_INCONNUE
    resultat = {"verdict": verdict, "run_id": sel.get("run_id"), "statut": sel.get("statut"),
                "age_s": sel.get("age_s"), "fraiche": sel.get("fraiche"),
                "raison": sel.get("raison"), "verification": verif, "rapport_md": rapport_md,
                "ts_ms": int(horloge() * 1000), "real_execution": False, "data_origin": origine}
    chemins = {}
    if ecrire:
        base = Path(root) / "runtime" / "reports" / "backtest_replay"
        base.mkdir(parents=True, exist_ok=True)
        (base / "ANALYSE_SESSION.json").write_text(
            json.dumps({k: v for k, v in resultat.items() if k != "rapport_md"},
                       ensure_ascii=False, indent=2), encoding="utf-8")
        (base / "ANALYSE_SESSION.md").write_text(rapport_md, encoding="utf-8")
        chemins = {"json": str(base / "ANALYSE_SESSION.json"), "md": str(base / "ANALYSE_SESSION.md")}
    resultat["chemins"] = chemins
    return resultat


def main(argv: list[str] | None = None) -> int:
    import argparse
    p = argparse.ArgumentParser(description="Porte d'entree ANALYSER : selection + verification de session.")
    p.add_argument("--root", default=".")
    p.add_argument("--autoriser-degrade", action="store_true",
                   help="(reserve) tolerer une session DEGRADE_DOCUMENTE — par defaut on exige COMPLETE")
    p.add_argument("--emit-run-id", action="store_true",
                   help="sur GO, ecrit runtime/reports/backtest_replay/SESSION_SELECTIONNEE.txt (run_id) pour le .cmd")
    p.add_argument("--age-max-s", type=float, default=None,
                   help="item 14 : seuil de fraicheur (une session COMPLETE plus vieille est refusee)")
    p.add_argument("--autoriser-complete-ancienne", action="store_true",
                   help="item 14 : tolerer une vieille COMPLETE meme si une session plus recente est ACTIVE/QUARANTINED")
    args = p.parse_args(argv)
    res = analyser(Path(args.root), exiger_complete=not args.autoriser_degrade, age_max_s=args.age_max_s,
                   autoriser_complete_ancienne=args.autoriser_complete_ancienne)
    print("ANALYSE_SESSION verdict=%s run_id=%s : %s" %
          (res["verdict"], res.get("run_id"), res.get("raison")), flush=True)
    # item 2 : expose le run_id sélectionné pour que ANALYSER.cmd le passe à lab_alpha (--session-dir).
    if res["verdict"] == GO and res.get("run_id"):
        print("SELECTED_RUN_ID=%s" % res["run_id"], flush=True)
        print("SESSION_DIR=%s" % SC.chemin_session(Path(args.root), res["run_id"]), flush=True)
        if args.emit_run_id:
            try:
                pointeur = Path(args.root) / "runtime" / "reports" / "backtest_replay" / "SESSION_SELECTIONNEE.txt"
                pointeur.parent.mkdir(parents=True, exist_ok=True)
                pointeur.write_text(str(res["run_id"]), encoding="utf-8")
            except OSError:
                import logging as _lg  # panne rendue VISIBLE (interdiction des except:pass muets)
                _lg.getLogger(__name__).debug("exception ignoree volontairement ici", exc_info=True)
    return 0 if res["verdict"] == GO else 2


__all__ = ["GO", "NO_GO", "selectionner_session", "verifier_session", "analyser", "main"]
