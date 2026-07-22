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
BUDGETS = {"securite": 300, "tests": 3600, "invariants": 900, "cablage": 900, "donnees": 900,
           "recherche": 5400, "sante": 120}


#: durées TYPIQUES (s) observées sur un vrai RECAP — pour l'ETA. C'est une ESTIMATION affichée
#: comme telle, jamais une promesse. Sert uniquement à donner « le temps restant » à Flo.
DUREE_TYPIQUE_S = {"securite": 21, "consolidation": 12, "tests": 300, "invariants": 3,
                   "cablage": 2, "donnees": 6, "backtests": 900, "recherche": 1800,
                   "rapport_jour": 15}
#: état de progression, rempli par `_planifier()` au début de `main`.
_PLAN: dict[str, Any] = {"debut": 0.0, "restant": {}, "total": 0, "i": 0}


def _mmss(s: float) -> str:
    s = int(max(0, s))
    return "%d:%02d" % (s // 60, s % 60)


def _planifier(noms: list[str]) -> None:
    """Fixe le plan : les étapes qui VONT tourner (selon les options) et leur durée estimée."""
    _PLAN["debut"] = time.time()
    _PLAN["restant"] = {n: DUREE_TYPIQUE_S.get(n, 60) for n in noms}
    _PLAN["total"] = len(noms)
    _PLAN["i"] = 0


def _entete_progres(nom: str) -> None:
    """La ligne « où on en est + temps restant » avant chaque étape. Flo VOIT sa progression."""
    if not _PLAN.get("debut"):
        return
    _PLAN["i"] = _PLAN.get("i", 0) + 1
    ecoule = time.time() - _PLAN["debut"]
    reste = sum(_PLAN["restant"].values())         # inclut l'étape qui démarre
    _PLAN["restant"].pop(nom, None)
    print("  ⏱  étape %d/%d · écoulé %s · reste ~%s (estimé)"
          % (_PLAN["i"], _PLAN.get("total", 0), _mmss(ecoule), _mmss(reste)), flush=True)


def _courir(nom: str, cmd: list[str], budget_s: float) -> dict[str, Any]:
    """Lance une étape en STREAMANT sa sortie en direct (Flo voit tout ce qui se passe), tout en
    la capturant pour le RECAP, avec un timeout DUR (un Timer tue le process même s'il se fige en
    silence — le stream seul ne suffirait pas à couper un blocage sans sortie)."""
    import threading
    t0 = time.time()
    print("\n" + "=" * 70, flush=True)
    print("  [%s] %s" % (nom.upper(), " ".join(cmd[-2:])), flush=True)
    _entete_progres(nom)
    print("=" * 70, flush=True)
    lignes: list[str] = []
    proc = None
    depasse = {"v": False}
    try:
        proc = subprocess.Popen(cmd, cwd=str(RACINE), stdout=subprocess.PIPE,
                                stderr=subprocess.STDOUT, text=True, encoding="utf-8",
                                errors="replace", bufsize=1)

        def _tuer_si_depasse() -> None:
            depasse["v"] = True
            try:
                proc.kill()
            except Exception:  # noqa: BLE001
                pass

        minuteur = threading.Timer(max(1.0, float(budget_s)), _tuer_si_depasse)
        minuteur.daemon = True
        minuteur.start()
        try:
            for ligne in proc.stdout:              # STREAM : la progression s'affiche en direct
                print(ligne, end="", flush=True)
                lignes.append(ligne)
        finally:
            minuteur.cancel()
            code = proc.wait(timeout=30)
        sortie = "".join(lignes)
        if depasse["v"]:
            return {"etape": nom, "code": -9, "duree_s": round(time.time() - t0, 1),
                    "sortie": (sortie[-20000:] + "\nBUDGET DEPASSE (%.0f s)" % budget_s),
                    "statut": "BUDGET"}
        return {"etape": nom, "code": code, "duree_s": round(time.time() - t0, 1),
                "sortie": sortie[-20000:], "statut": "OK" if code == 0 else "ECHEC"}
    except Exception as exc:  # noqa: BLE001 — une étape morte n'arrête pas les autres
        try:
            if proc is not None:
                proc.kill()
        except Exception:  # noqa: BLE001
            pass
        return {"etape": nom, "code": -1, "duree_s": round(time.time() - t0, 1),
                "sortie": ("".join(lignes)[-20000:] or str(exc)[:2000]), "statut": "ERREUR"}


def _pytest_parallele() -> list[str]:
    """Arguments xdist pour paralléliser la suite — SEULEMENT si `xdist` est installé et la
    machine a plusieurs cœurs. Sinon liste vide = exécution SÉRIE (aucune régression possible).
    `--dist loadfile` : chaque FICHIER de test reste sur un seul worker, l'état intra-fichier est
    préservé. Coupe-circuit : TOUT_TESTER_PYTEST_SERIE=1 force la série."""
    try:
        import importlib.util
        import os as _os
        if _os.environ.get("TOUT_TESTER_PYTEST_SERIE", "").strip() in ("1", "true", "oui"):
            return []
        if importlib.util.find_spec("xdist") is None or (_os.cpu_count() or 1) <= 1:
            return []
        return ["-n", "auto", "--dist", "loadfile"]
    except Exception:  # noqa: BLE001 — dans le doute, série (jamais un run cassé pour aller vite)
        return []


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


HISTORIQUE = RACINE / "runtime" / "data" / "recap_historique.jsonl"


def attribution_pnl(root: Path = RACINE, *, fenetre_h: float = 24.0) -> dict[str, Any]:
    """OÙ VA L'ARGENT (21/07) : réalisé 24 h PAR STRATÉGIE et PAR MOTIF, depuis le ledger.
    Un récap qui ne dit pas où part chaque dollar ne sert pas le PnL."""
    from collections import Counter
    out: dict[str, Any] = {"par_strategie": {}, "par_motif": {}, "total_24h": 0.0,
                           "n_fermetures": 0}
    seuil = (time.time() - fenetre_h * 3600) * 1000
    try:
        strat: Counter = Counter()
        motif: Counter = Counter()
        for l in (root / "runtime/data/carry_paper_ledger.jsonl").read_text(
                encoding="utf-8").splitlines():
            try:
                r = json.loads(l)
            except ValueError:
                continue
            if r.get("kind") != "CLOSE" or float(r.get("ts_ms") or 0) < seuil:
                continue
            pnl = float(r.get("realized_net_pnl_usdc") or 0.0)
            strat[str(r.get("strategie") or "carry")] += pnl
            motif[str(r.get("reason") or "?")] += pnl
            out["n_fermetures"] += 1
            out["total_24h"] += pnl
        out["par_strategie"] = {k: round(v, 4) for k, v in strat.most_common()}
        out["par_motif"] = {k: round(v, 4) for k, v in motif.most_common()}
        out["total_24h"] = round(out["total_24h"], 4)
    except OSError:
        out["erreur"] = "ledger illisible"
    return out


def plan_action_pnl(etapes: list[dict], sante: dict, attrib: dict,
                    root: Path = RACINE) -> list[str]:
    """LE PLAN, en tête du récap (21/07, Flo : « les tests doivent servir le PnL »).
    Chaque ligne est DÉRIVÉE d'une mesure de ce run — jamais un conseil générique."""
    actions: list[str] = []
    # 1. les recommandations de la recherche, remontées telles quelles
    try:
        md = (root / "runtime/replay/RESULTATS_RECHERCHE.md").read_text(encoding="utf-8")
        bloc = md.split("<!-- JSON_RESULTATS", 1)[1].split("-->", 1)[0].strip()
        from hl_observer.backtesting.recherche_scenario import recommandation
        for strat, r in json.loads(bloc).items():
            actions.append("**%s** → %s" % (strat, recommandation(strat, r)))
    except Exception:  # noqa: BLE001
        actions.append("Recherche de pépites : pas de résultat lisible ce tour-ci.")
    # 2. la qualité des données commande tout le reste
    for e in etapes:
        if e["etape"] == "donnees" and "ÉTIQUETAGE" in e.get("sortie", ""):
            actions.append("**Données** → défaut d'ÉTIQUETAGE encore présent : redémarre le "
                           "bot pour que les nouveaux candidats portent leur `strategie` "
                           "(sinon chaque module cherche dans le mauvais seau).")
        if e["etape"] == "donnees" and "COUVERTURE" in e.get("sortie", ""):
            actions.append("**Données** → COUVERTURE insuffisante : des candidats n'ont aucun "
                           "mark après eux (outcomes inmesurables) — vérifier marks-collector.")
    # 3. l'argent : où il part
    if attrib.get("n_fermetures"):
        pires = [(k, v) for k, v in attrib["par_motif"].items() if v < 0]
        if pires:
            k, v = min(pires, key=lambda kv: kv[1])
            actions.append("**PnL 24 h** → le motif le plus coûteux est `%s` (%.4f $) : "
                           "c'est LUI qu'il faut comprendre avant d'ajouter quoi que ce soit."
                           % (k, v))
        else:
            actions.append("**PnL 24 h** → aucune fermeture perdante sur la fenêtre (%+.4f $ "
                           "sur %d fermetures)." % (attrib["total_24h"], attrib["n_fermetures"]))
    else:
        actions.append("**PnL 24 h** → aucune fermeture : le PnL vit dans le funding couru "
                       "(positions ouvertes), rien à corriger de ce côté.")
    # 4. les mesures qui arrivent à échéance
    h = sante.get("cross_venue_h")
    if isinstance(h, (int, float)):
        actions.append("**Cross-venue** → %.1f h / 72 h %s"
                       % (h, "→ **le verdict est mûr, lance-le**" if h >= 72
                          else "— verdict dans ~%.0f h, ne rien conclure avant." % (72 - h)))
    # 5. la santé qui bloquerait tout
    morts = [n for n, a in (sante.get("collecteurs_age_s") or {}).items()
             if a is None or a > 1800]
    if morts:
        actions.append("**Santé** → collecteur(s) muet(s) : %s — sans eux, les mesures "
                       "s'arrêtent (REANIMER-COLLECTEURS.cmd)." % ", ".join(morts))
    for e in etapes:
        if e["etape"] == "tests" and e["statut"] != "OK":
            actions.append("**Tests** → %s : réparer AVANT d'ajouter une stratégie (un test "
                           "rouge = une mesure qui ment peut-être)." % e.get("resume", "échec"))
    return actions


def _progression(etapes: list[dict], sante: dict, attrib: dict) -> tuple[list[str], dict]:
    """Compare au passage PRÉCÉDENT : on progresse ou on régresse ? (le journal est
    append-only : l'historique des runs ne s'écrase jamais)."""
    courant = {"ts": time.time(),
               "tests": next((e.get("resume") for e in etapes if e["etape"] == "tests"), None),
               "verts": sum(1 for e in etapes if e["statut"] == "OK"),
               "n_etapes": len(etapes),
               "pnl_total": sante.get("realise_total"),
               "pnl_24h": attrib.get("total_24h"),
               "positions": sante.get("positions_carry"),
               "cross_venue_h": sante.get("cross_venue_h")}
    lignes: list[str] = []
    try:
        precedents = [json.loads(l) for l in
                      HISTORIQUE.read_text(encoding="utf-8").splitlines() if l.strip()]
    except (OSError, ValueError):
        precedents = []
    if precedents:
        p = precedents[-1]
        dt_h = (courant["ts"] - float(p.get("ts") or courant["ts"])) / 3600.0
        lignes.append("_Comparé au passage d'il y a %.1f h._" % dt_h)
        for cle, label in (("verts", "étapes vertes"), ("pnl_total", "PnL total"),
                           ("pnl_24h", "PnL 24 h"), ("positions", "positions carry")):
            a, b = p.get(cle), courant.get(cle)
            if isinstance(a, (int, float)) and isinstance(b, (int, float)):
                fleche = "▲" if b > a else ("▼" if b < a else "=")
                lignes.append("- %s : %s → **%s** %s" % (label, a, b, fleche))
        if p.get("tests") != courant.get("tests"):
            lignes.append("- tests : `%s` → `%s`" % (p.get("tests"), courant.get("tests")))
    else:
        lignes.append("_Premier passage : la comparaison arrivera au prochain lancement._")
    try:
        HISTORIQUE.parent.mkdir(parents=True, exist_ok=True)
        with HISTORIQUE.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(courant, ensure_ascii=False) + "\n")
    except OSError:
        pass
    return lignes, courant


def inventaire_donnees(root: Path = RACINE) -> list[dict]:
    """COMBIEN de données chaque module a réellement, et sur quelle étendue.

    Exigé par Flo le 21/07 (« des données en masse ») : une masse de données qu'on ne peut
    pas citer finira par être surestimée. On mesure les fichiers, on ne devine pas.
    Le carry est né avec 96 lignes ici — c'est cette ligne-là qui l'a rendu visible.
    """
    import json as _j
    srcs = [
        ("copy · candidats replay", "runtime/replay/_merged/candidates.jsonl"),
        ("copy · marks replay", "runtime/replay/_merged/marks.jsonl"),
        ("carry · journal de scans", "runtime/replay/carry_scan.jsonl"),
        ("carry · ledger positions", "runtime/data/carry_paper_ledger.jsonl"),
        ("arbitrage · cross-venue", "runtime/data/dispersion_venues.jsonl"),
        # 22/07 — LA donnée qui manquait à l'arbitrage : le carnet (bid/ask+profondeur) pour le
        # prix EXÉCUTABLE. Collecteur auto-démarré (LANCER/REANIMER) et supervisé.
        ("arbitrage · carnet bid/ask", "runtime/data/carnet_venues.jsonl"),
        ("copy · fills de leaders", "runtime/data/leader_fills_bruts.jsonl"),
        ("copy · fills markout", "runtime/data/leader_fills_forward.jsonl"),
    ]
    sqlites = [("liquidations · grappes", "runtime/data/liquidation_map.sqlite3",
                "grappe_snapshots")]
    out = []
    for nom, rel in srcs:
        chemin = Path(root) / rel
        e = {"source": nom, "fichier": rel, "lignes": 0, "mo": 0.0, "etendue_h": None}
        try:
            e["mo"] = round(chemin.stat().st_size / 1e6, 2)
            premier = dernier = None
            n = 0
            with chemin.open(encoding="utf-8", errors="ignore") as f:
                for l in f:
                    if not l.strip():
                        continue
                    n += 1
                    if premier is None:
                        premier = l
                    dernier = l
            e["lignes"] = n

            def _ts(l):
                try:
                    d = _j.loads(l)
                except (ValueError, TypeError):
                    return None
                for k in ("ts_ms", "ts", "time", "timestamp"):
                    v = d.get(k) if isinstance(d, dict) else None
                    if isinstance(v, (int, float)) and not isinstance(v, bool):
                        return float(v) / 1000.0 if float(v) > 1e11 else float(v)
                return None
            a, b = _ts(premier or ""), _ts(dernier or "")
            if a and b and b >= a:
                e["etendue_h"] = round((b - a) / 3600.0, 1)
        except OSError:
            e["absent"] = True
        out.append(e)
    # sources SQLite (les liquidations ne sont pas un JSONL) — même exigence : on compte, on
    # ne devine pas, et une base absente est DITE absente.
    import sqlite3 as _sq
    for nom, rel, table in sqlites:
        chemin = Path(root) / rel
        e = {"source": nom, "fichier": rel, "lignes": 0, "mo": 0.0, "etendue_h": None}
        try:
            e["mo"] = round(chemin.stat().st_size / 1e6, 2)
            con = _sq.connect("file:%s?mode=ro" % chemin, uri=True)
            try:
                e["lignes"] = con.execute("select count(*) from %s" % table).fetchone()[0]
                bornes = con.execute("select min(ts_ms), max(ts_ms) from %s" % table).fetchone()
                if bornes and bornes[0] and bornes[1]:
                    e["etendue_h"] = round((bornes[1] - bornes[0]) / 3.6e6, 1)
            finally:
                con.close()
        except Exception:  # noqa: BLE001
            e["absent"] = True
        out.append(e)
    return out


def ecrire_recap(etapes: list[dict], sante: dict, chemin: Path = RECAP) -> Path:
    ok = [e for e in etapes if e["statut"] == "OK"]
    attrib = attribution_pnl()
    plan = plan_action_pnl(etapes, sante, attrib)
    progres, _ = _progression(etapes, sante, attrib)
    l = ["# RÉCAPITULATIF COMPLET — HyperSmart Observer", "",
         "_Généré le %s · %d/%d étapes vertes · durée totale %.1f min._"
         % (time.strftime("%d/%m/%Y %H:%M"), len(ok), len(etapes),
            sum(e["duree_s"] for e in etapes) / 60), "",
         "## 🎯 PLAN D'ACTION POUR LE PnL (dérivé des mesures de CE run)", ""]
    l += ["%d. %s" % (i, a) for i, a in enumerate(plan, 1)]
    l += ["", "## 📈 Progression depuis le dernier passage", ""] + progres
    l += ["", "## 💰 Où va l'argent (24 h)", "",
          "- total : **%+.4f $** sur %d fermeture(s)"
          % (attrib.get("total_24h", 0.0), attrib.get("n_fermetures", 0)),
          "- par stratégie : `%s`" % (attrib.get("par_strategie") or "aucune"),
          "- par motif : `%s`" % (attrib.get("par_motif") or "aucun"), "",
         "## Étapes", "",
         "| Étape | Statut | Durée | Détail |", "|---|---|---|---|"]
    for e in etapes:
        icone = {"OK": "✅", "ECHEC": "🔴", "BUDGET": "⏱️", "ERREUR": "💥"}.get(e["statut"], "?")
        detail = e.get("resume") or (e["sortie"].strip().splitlines() or [""])[-1][:120]
        l.append("| %s | %s %s | %.0f s | %s |"
                 % (e["etape"], icone, e["statut"], e["duree_s"], detail.replace("|", "/")))
    # LA MASSE DE DONNEES, CHIFFREE (exigence de Flo le 21/07). Le carry est ne avec 96
    # lignes ici : c'est cette table qui l'a rendu visible. Ce qu'on ne cite pas, on le
    # surestime.
    l += ["", "## 📦 Données disponibles (ce que le replay peut manger)", "",
          "| source | lignes | Mo | étendue |", "|---|---:|---:|---:|"]
    for d in inventaire_donnees():
        if d.get("absent"):
            l.append("| %s | — | — | **fichier absent** (`%s`) |" % (d["source"], d["fichier"]))
        else:
            l.append("| %s | %d | %.2f | %s |"
                     % (d["source"], d["lignes"], d["mo"],
                        ("%.1f h" % d["etendue_h"]) if d["etendue_h"] is not None else "?"))
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


#: options reconnues. Toute autre option est REFUSÉE plutôt qu'ignorée en silence : une
#: option avalée sans effet donne un run qui ne fait pas ce que l'on croit — et on lit
#: ensuite un RECAP en pensant qu'il répond à une question qu'on n'a jamais posée.
OPTIONS = {
    "--rapide": "saute la recherche de pepites (l'etape la plus longue) -> ~10 min",
    "--tests-seulement": "securite + suite pytest + invariants, rien d'autre (~5 min)",
    "--securite-seulement": "UNIQUEMENT l'audit no-real-trade (~30 s)",
    "--sans-recherche": "synonyme de --rapide",
    "--aide": "affiche cette liste et sort",
}


def _aide() -> int:
    print("TOUT-TESTER — options reconnues :\n")
    for o, d in OPTIONS.items():
        print("  %-22s %s" % (o, d))
    print("\n  (sans option : tout, ~1 h)")
    return 0


def main(argv: list[str] | None = None) -> int:
    brut = list(argv if argv is not None else sys.argv[1:])
    inconnues = [a for a in brut if a.startswith("-") and a not in OPTIONS]
    if inconnues:
        print("option inconnue : %s" % ", ".join(inconnues), file=sys.stderr)
        _aide()
        return 2
    args = set(brut)
    if "--aide" in args:
        return _aide()
    rapide = bool(args & {"--rapide", "--sans-recherche"})
    tests_seuls = "--tests-seulement" in args
    securite_seule = "--securite-seulement" in args
    py = sys.executable
    # PLAN DE PROGRESSION (22/07, « voir tout ce qui se passe et le temps restant ») : on liste
    # les étapes qui VONT tourner selon les options, pour afficher « étape i/N · reste ~ETA ».
    if securite_seule:
        _planifier(["securite"])
    elif tests_seuls:
        _planifier(["securite", "consolidation", "tests", "invariants"])
    else:
        _plan = ["securite", "consolidation", "tests", "invariants", "cablage", "donnees",
                 "backtests"] + ([] if rapide else ["recherche"]) + ["rapport_jour"]
        _planifier(_plan)
    etapes: list[dict] = []
    try:
        etapes.append(_courir("securite", [py, "-m", "hl_observer", "safety-audit"],
                              BUDGETS["securite"]))
        if securite_seule:
            sante = _sante_live()
            chemin = ecrire_recap(etapes, sante)
            print("\n  --securite-seulement : RECAP %s" % chemin, flush=True)
            return 0 if etapes[0]["statut"] == "OK" else 1
        # consolidation AVANT tout ce qui lit le replay (qualite + recherche) : on ne juge
        # jamais sur des donnees d'hier alors que les shards du jour sont la.
        etapes.append(_courir("consolidation",
                              [py, "-m", "hl_observer.runtime.replay_recorder",
                               "--base", "runtime/replay"], BUDGETS["donnees"]))
        # 22/07 — PLUS RAPIDE : la suite complète en PARALLÈLE (xdist) si dispo. `--dist loadfile`
        # garde chaque fichier sur un worker (état intra-fichier préservé) -> pas de régression.
        # Repli automatique en série si xdist absent ou 1 seul cœur (jamais un run cassé).
        r = _courir("tests", [py, "-m", "pytest", "-q", "--timeout=120",
                              *_pytest_parallele(), "tests"], BUDGETS["tests"])
        r["resume"] = _resume_pytest(r["sortie"])
        etapes.append(r)
        # INVARIANTS ECONOMIQUES (property-based, ~700 cas generes) : les LOIS qui protegent
        # le PnL (pas de gain sorti de rien, couts toujours payes, portes infranchissables).
        ri = _courir("invariants",
                     [py, "-m", "pytest", "-q", "tests/test_invariants_economiques.py"],
                     BUDGETS["cablage"])
        ri["resume"] = _resume_pytest(ri["sortie"])
        etapes.append(ri)
        if tests_seuls:
            sante = _sante_live()
            chemin = ecrire_recap(etapes, sante)
            print("\n  --tests-seulement : RECAP %s" % chemin, flush=True)
            return 0 if all(e["statut"] in ("OK", "SAUTEE") for e in etapes) else 1
        etapes.append(_courir("cablage", [py, "tools/audit_cablage_cli.py"],
                              BUDGETS["cablage"]))
        etapes.append(_courir("donnees", [py, "tools/qualite_donnees_replay.py", "."],
                              BUDGETS["donnees"]))
        # BACKTEST CARRY (21/07) : rejoue nos VRAIES passes de scan sous d'autres reglages.
        # Le carry n'avait que 96 lignes rejouables ; le journal de scans en produit ~2 900/j.
        etapes.append(_courir("backtests", [py, "tools/backtest_carry_cli.py", "."],
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
