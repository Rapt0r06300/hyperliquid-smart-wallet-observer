"""[LAB α] ORCHESTRATEUR du laboratoire — le point d'entrée unique lancé par ANALYSER_BACKTESTS_REPLAYS.cmd.
Au lancement il enchaîne, sur le CHEMIN CANONIQUE UNIQUE (données → feed_adapter → MegaCablage → Copy-Vault +
Cross-Venue + Lead-Lag → netting/routing → risk → fills paper → PaperLedger → PnL) :

    1) inventaire des sources   2) lecture multi-format → bundles → events (feed_adapter)
    3) audit des câblages       4) recherche IS/OOS/FORWARD + stress + placebo + gate
    5) rapport final (RAPPORT_LATEST.md + JSON + manifeste + hashes)

avec ETA recalculé, tableau de bord dynamique et journal horodaté. HONNÊTETÉ DURE : en run RÉEL, aucune equity
leader fictive (leader_equity_defaut forcé à None) → sans source d'equity leader réelle, la copie est UNMEASURABLE
et n'invente aucun fill. Aucune donnée synthétique n'entre dans le verdict. Paper strict : 0 ordre réel, 0 clé,
0 signature, aucun /exchange.
"""
from __future__ import annotations

import argparse
import time
from pathlib import Path
from typing import Any, Callable

from hl_observer.mega_cablage.feed_adapter import evenements_depuis_bundles
from hl_observer.mega_cablage.lead_lag_stage import score_lead_lag
from hl_observer.ops.lab_inventaire import inventorier, bundles_depuis_fichier, LabFormatBloque
from hl_observer.ops.lab_audit import auditer
from hl_observer.ops import lab_recherche as R
from hl_observer.ops.lab_eta import MoteurETA, format_hms
from hl_observer.ops.lab_dashboard import rendre_tableau, Journal
from hl_observer.ops.lab_rapport import ecrire_rapport

DOSSIER_RAPPORTS = "runtime/reports/backtest_replay"


def _events_valides(events: list[dict[str, Any]]) -> int:
    return sum(1 for e in events
               if isinstance(e.get("px"), (int, float)) and (e.get("px") or 0) > 0 and e.get("signe"))


def _paires_lead_lag(events: list[dict[str, Any]]) -> list[tuple[Any, Any]]:
    """Paires (signe_leader, Δmid_futur) par coin (ordre temporel) pour mesurer le lead-lag réel."""
    par_coin: dict[str, list] = {}
    for e in events:
        mid = e.get("mid", e.get("px"))
        if isinstance(mid, (int, float)) and e.get("signe"):
            par_coin.setdefault(str(e.get("coin")), []).append((e.get("ts_ms") or 0, e.get("signe"), mid))
    paires: list[tuple[Any, Any]] = []
    for _coin, série in par_coin.items():
        série.sort(key=lambda t: t[0])
        for i in range(len(série) - 1):
            paires.append((série[i][1], série[i + 1][2] - série[i][2]))
    return paires


def lancer_lab(*, racine: str | Path, sortie_dir: str | Path | None = None, budget: int = 32,
               source: str = "REEL", horodatage: str = "", temps_fn: Callable[[], float] | None = None,
               journal_path: str | Path | None = None, checkpoint_path: str | Path | None = None,
               imprimer: bool = False, max_events: int = 200_000, min_episodes: int = 30,
               max_fichiers: int = 20_000) -> dict[str, Any]:
    """Exécute tout le laboratoire et écrit le rapport. Retourne un résumé (chemins, verdict, compteurs, table)."""
    temps = temps_fn or time.monotonic
    t0 = temps()
    racine = Path(racine)
    sortie = Path(sortie_dir) if sortie_dir else racine / DOSSIER_RAPPORTS
    sortie.mkdir(parents=True, exist_ok=True)
    journal = Journal(journal_path or sortie / "journal_lab.log")
    checkpoint_path = checkpoint_path or sortie / "checkpoint_recherche.jsonl"
    # Honnêteté dure : run réel → aucune equity leader fictive.
    reel = not str(source).upper().startswith("SYNTH")
    leader_equity_defaut = None if reel else 100000.0

    espace = R.ESPACE_DEFAUT
    n_grille = 1
    for v in espace.values():
        n_grille *= len(v)
    total_etapes = 4 + min(n_grille, budget)
    eta = MoteurETA(total_etapes=total_etapes, min_echantillons=3)
    etat: dict[str, Any] = {"titre": source, "total_etapes": total_etapes, "source": source,
                            "cfg_prevues": min(n_grille, budget), "erreurs": 0, "manquantes": 0,
                            "workers": 1, "en_cours": "démarrage", "derniere": "-", "prochaine": "inventaire"}

    def _rafraichir(hh: str) -> None:
        est = eta.estimer(elapsed_s=temps() - t0)
        etat.update({"heure": hh, "ecoule": format_hms(temps() - t0), "eta": est["texte"],
                     "eta_etape": format_hms(est.get("eta_total_s") or 0) if not est["calibration"] else "CALIB",
                     "fin_estimee": format_hms(est.get("fin_relative_s") or 0) if not est["calibration"] else "-",
                     "confiance": ("+/- %ss" % round(est.get("confiance_s") or 0)) if not est["calibration"] else "-",
                     "etape": eta.etapes_finies})
        tableau = rendre_tableau(etat)
        etat["_tableau"] = tableau
        if imprimer:
            print("\033[2J\033[H" + tableau, flush=True)

    def _jrn(msg: str) -> None:
        journal.ligne(horodatage or "T", msg)

    # 1) INVENTAIRE
    etat.update({"en_cours": "inventaire des sources", "prochaine": "lecture"})
    _jrn("inventaire: debut")
    inv = inventorier(racine, max_fichiers=max_fichiers)
    etat.update({"octets_total": inv["total_octets"], "derniere": "inventaire (%d fichiers)" % inv["total_fichiers"]})
    eta.terminer_etape(temps() - t0, octets=0)
    _jrn("inventaire: %d fichiers, %d lisibles, %d bloques" % (inv["total_fichiers"], inv["lisibles"], inv["bloques"]))
    _rafraichir(horodatage or "T")

    # 2) LECTURE -> bundles -> events (feed_adapter)
    etat.update({"en_cours": "lecture des donnees", "prochaine": "audit"})
    bundles: list[dict[str, Any]] = []
    octets_lus = 0
    bloques = 0
    for f in inv["fichiers"]:
        if not f["lisible"] or len(bundles) >= max_events:
            continue
        etat["fichier"] = f["rel"]
        try:
            bs = bundles_depuis_fichier(f["chemin"], max_lignes=max_events - len(bundles))
            bundles.extend(bs)
            octets_lus += f["octets"]
        except LabFormatBloque:
            bloques += 1
        except Exception:                                     # noqa: BLE001 (lecture défaillante = compte honnête)
            etat["erreurs"] = etat.get("erreurs", 0) + 1
    events = evenements_depuis_bundles(bundles)
    valides = _events_valides(events)
    etat.update({"octets_lus": octets_lus, "events_lus": len(events), "events_valides": valides,
                 "events_rejetes": len(events) - valides, "derniere": "lecture (%d events)" % len(events)})
    eta.terminer_etape(temps() - t0, octets=octets_lus, evenements=len(events))
    _jrn("lecture: %d events (%d valides), %d fichiers bloques" % (len(events), valides, bloques))
    _rafraichir(horodatage or "T")

    # 3) AUDIT CABLAGE (croise import reel + disponibilite donnees)
    paires_ll = _paires_lead_lag(events)
    ll = score_lead_lag(paires_ll, min_echantillons=20)
    a_hedge = any(isinstance(e.get("cross_venue"), dict) for e in events)
    audit = auditer(a_des_evenements=valides > 0, a_des_carnets_hedge=a_hedge,
                    a_lead_lag=(ll.get("score") != "UNMEASURABLE"))
    audit["lead_lag"] = ll
    etat.update({"en_cours": "audit cablage", "prochaine": "recherche",
                 "derniere": "audit (%d bricks utilisees)" % audit["resume"].get("CABLE ET UTILISE", 0)})
    eta.terminer_etape(temps() - t0)
    _jrn("audit: %s" % audit["resume"])
    _rafraichir(horodatage or "T")

    # 4) RECHERCHE (chemin canonique) — donnees REELLES uniquement pour le verdict
    etat.update({"en_cours": "recherche IS/OOS/FORWARD + stress + placebo", "prochaine": "rapport"})
    best = {"is": None, "oos": None, "fwd": None, "adv95": None, "dd": None}

    def _on_eval(info: dict[str, Any]) -> None:
        res = info["res"]
        m = res.get("metriques", {})
        for k, mk in (("is", "net_pnl"), ("oos", "oos_net"), ("fwd", "forward_net"),
                      ("adv95", "adverse_p95_net")):
            v = m.get(mk)
            if isinstance(v, (int, float)) and (best[k] is None or v > best[k]):
                best[k] = v
        etat.update({"cfg_testees": info["evalues"], "cfg_restantes": info["restantes"],
                     "cfg_eliminees": sum(1 for c in [res] if c.get("verdict") in ("KILL", "MORE_DATA")),
                     "best_is": best["is"], "best_oos": best["oos"], "best_fwd": best["fwd"],
                     "best_adv95": best["adv95"], "sous_etape": "config %d" % info["evalues"],
                     "derniere": "eval %s -> %s" % (res.get("config", {}).get("notional_max"), res.get("verdict"))})
        eta.terminer_etape(temps() - t0)
        _rafraichir(horodatage or "T")

    rech = R.rechercher(events, espace=espace, leader_equity_defaut=leader_equity_defaut, budget=budget,
                        checkpoint_path=checkpoint_path, min_episodes=min_episodes, source=source, on_eval=_on_eval)
    fills = sum(c.get("segments", {}).get("IS", {}).get("fills", 0) or 0 for c in rech["candidats"])
    etat.update({"cfg_testees": rech["evalues"], "fills": fills, "replays": rech["evalues"]})
    _jrn("recherche: %d evaluees, %d cache, verdict %s" % (rech["evalues"], rech["caches"], rech["verdict_global"]))

    # 5) RAPPORT
    etat.update({"en_cours": "ecriture du rapport", "prochaine": "fin"})
    eta.terminer_etape(temps() - t0)
    periode = _periode(events)
    chemins = ecrire_rapport(sortie, horodatage=horodatage or "T", inventaire=inv, audit=audit, recherche=rech,
                             eta_final=format_hms(temps() - t0), source=source, periode=periode,
                             checkpoints=[str(checkpoint_path)])
    _jrn("rapport: %s (verdict %s)" % (chemins["latest"], chemins["verdict"]))
    _rafraichir(horodatage or "T")

    return {"rapport": chemins, "verdict": chemins["verdict"], "inventaire": inv, "audit": audit,
            "recherche": rech, "events": len(events), "events_valides": valides, "periode": periode,
            "duree_s": round(temps() - t0, 3), "tableau": etat.get("_tableau", ""),
            "journal": str(journal.chemin), "lead_lag": ll}


def _periode(events: list[dict[str, Any]]) -> dict[str, Any]:
    ts = [e.get("ts_ms") for e in events if isinstance(e.get("ts_ms"), (int, float))]
    if not ts:
        return {"debut_ms": None, "fin_ms": None, "n": len(events)}
    return {"debut_ms": min(ts), "fin_ms": max(ts), "n": len(events)}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        prog="hl_observer.ops.lab_alpha",
        description="Laboratoire de recherche d'alpha / PnL net (paper strict, 0 ordre reel).")
    ap.add_argument("--root", default=".", help="Racine du projet (contient runtime/, logs/, ...).")
    ap.add_argument("--out", default=None, help="Dossier de sortie des rapports.")
    ap.add_argument("--budget", type=int, default=32, help="Budget d'evaluations de configs.")
    ap.add_argument("--source", default="REEL", help="Etiquette de source (REEL / SYNTHETIQUE).")
    ap.add_argument("--no-dry-run", action="store_true", help="INTERDIT (paper only) : provoque un refus.")
    args = ap.parse_args(argv)
    if args.no_dry_run:
        print("lab refuse: paper/dry-run only. Aucune execution reelle possible.")
        return 2
    from datetime import datetime, timezone
    horo = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    res = lancer_lab(racine=args.root, sortie_dir=args.out, budget=args.budget, source=args.source,
                     horodatage=horo, imprimer=True)
    print(res["tableau"])
    print("\nVERDICT: %s\nRAPPORT: %s\nJOURNAL: %s\nDUREE: %ss" % (
        res["verdict"], res["rapport"]["latest"], res["journal"], res["duree_s"]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = ["lancer_lab", "main", "DOSSIER_RAPPORTS"]
