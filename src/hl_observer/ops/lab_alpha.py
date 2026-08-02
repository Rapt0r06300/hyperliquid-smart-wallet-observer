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
from hl_observer.strategies.lead_lag_paper import signaux_depuis_events, rejouer_lead_lag
from hl_observer.ops.lab_inventaire import inventorier, bundles_depuis_fichier, LabFormatBloque
from hl_observer.ops.lab_flux import fusionner_causalement, charger_borne


def _venue_du_fichier(chemin) -> str:
    """item 9 : déduit la VENUE d'un artefact depuis son chemin (pour l'étiquetage cross-venue).
    Cross-Venue et Lead-Lag ont besoin de savoir de quelle venue vient chaque tick après la fusion."""
    bas = str(chemin).lower()
    for venue in ("binance", "hyperliquid", "dydx", "bybit", "okx", "coinbase"):
        if venue in bas:
            return venue
    from pathlib import Path as _P
    return _P(chemin).stem
from hl_observer.ops.lab_audit import auditer
from hl_observer.ops import lab_recherche as R
from hl_observer.ops.lab_eta import MoteurETA, format_hms
from hl_observer.ops.lab_dashboard import rendre_tableau, Journal
from hl_observer.ops.lab_rapport import ecrire_rapport
from hl_observer.ops.rafraichisseur import RafraichisseurPeriodique

DOSSIER_RAPPORTS = "runtime/reports/backtest_replay"


class AnalyseVerrouilleeError(RuntimeError):
    """item 13 : une autre analyse écrit déjà dans le même dossier de sortie (rapport/shard/checkpoint)."""


def acquerir_verrou_analyse(sortie: str | Path, *, pid_vivant=None) -> Path:
    """item 5/13 : verrou d'analyse RÉELLEMENT ATOMIQUE via os.open(O_CREAT|O_EXCL) — pas un exists()
    suivi d'un write_text() (fenêtre TOCTOU). Deux lancements ne peuvent pas écrire le même rapport/shard/
    checkpoint. Un verrou dont le PID est mort (crash) est repris atomiquement (os.replace) ; un verrou
    dont le PID est VIVANT bloque (AnalyseVerrouilleeError)."""
    import json
    import os as _os
    from hl_observer.ops.preuve_de_vie import _pid_vivant_reel
    vivant = pid_vivant or _pid_vivant_reel
    verrou = Path(sortie) / ".analyse.lock"
    verrou.parent.mkdir(parents=True, exist_ok=True)
    charge = json.dumps({"pid": _os.getpid()})
    try:
        fd = _os.open(str(verrou), _os.O_CREAT | _os.O_EXCL | _os.O_WRONLY, 0o644)   # création ATOMIQUE
        with _os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(charge)
        return verrou
    except FileExistsError:
        pass
    # le verrou existe déjà : détenteur vivant → bloqué ; mort (crash) → reprise ATOMIQUE (temp+replace).
    try:
        pid = int(json.loads(verrou.read_text(encoding="utf-8")).get("pid", -1))
    except Exception:  # noqa: BLE001
        pid = -1
    if pid > 0 and vivant(pid):
        raise AnalyseVerrouilleeError("analyse deja en cours (pid %d) dans %s" % (pid, sortie))
    tmp = verrou.with_name(".analyse.%d.tmp" % _os.getpid())
    tmp.write_text(charge, encoding="utf-8")
    _os.replace(tmp, verrou)
    return verrou


def _events_valides(events: list[dict[str, Any]]) -> int:
    return sum(1 for e in events
               if isinstance(e.get("px"), (int, float)) and (e.get("px") or 0) > 0 and e.get("signe"))


def _lire_catalogue_session(session_dir: Path) -> dict[str, Any]:
    """Lit DATA_CATALOG.json d'une session. Absent/illisible → dict vide (aucune analyse fabriquée)."""
    import json
    p = Path(session_dir) / "DATA_CATALOG.json"
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _inventaire_session(session_dir: Path, catalogue: dict[str, Any]) -> dict[str, Any]:
    """Inventaire SCOPÉ (item 2) : UNIQUEMENT les artefacts CATALOGUÉS et présents de la session. Aucun
    scan global de la racine (pas de mélange sessions/archives/logs/données actives)."""
    fichiers: list[dict[str, Any]] = []
    total = 0
    for s in (catalogue.get("sources") or {}).values():
        rel = s.get("chemin") or ""
        if not rel:
            continue
        p = Path(session_dir) / rel
        if not p.is_file():
            continue
        taille = p.stat().st_size
        total += taille
        fichiers.append({"chemin": str(p), "rel": rel, "octets": taille, "lisible": True})
    return {"fichiers": fichiers, "total_fichiers": len(fichiers), "lisibles": len(fichiers),
            "bloques": 0, "total_octets": total, "scope": "SESSION"}


def _sha_git(racine: Path) -> str | None:
    try:
        from hl_observer.runtime.protections import manifeste_execution
        return manifeste_execution(racine).get("git_head")
    except Exception:  # noqa: BLE001
        return None


def _ecrire_manifeste_run(sortie: Path, *, run_id: Any, data_hash: str, git_head: Any,
                          n_fichiers: int) -> None:
    """Manifeste de run (item 4) : run_id + hash des données + SHA git → traçabilité + anti-réutilisation."""
    import json
    try:
        (Path(sortie) / "manifeste_run.json").write_text(
            json.dumps({"run_id": run_id, "data_hash": data_hash, "git_head": git_head,
                        "n_fichiers": n_fichiers, "real_execution": False}, ensure_ascii=False, indent=2),
            encoding="utf-8")
    except OSError:
        pass


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
               imprimer: bool = False, max_events: int = 0, min_episodes: int = 30,
               max_fichiers: int = 20_000, max_ram_events: int = 0,
               session_dir: str | Path | None = None) -> dict[str, Any]:
    """Exécute tout le laboratoire et écrit le rapport. Retourne un résumé (chemins, verdict, compteurs, table).

    `session_dir` (item 2) : si fourni, on n'analyse QUE les artefacts CATALOGUÉS de CETTE session COMPLETE
    (aucun inventaire global de la racine). Les rapports/shards/checkpoints sont alors NAMESPACÉS par run_id
    (item 4) → jamais de réutilisation d'un shard d'une autre session."""
    temps = temps_fn or time.monotonic
    t0 = temps()
    racine = Path(racine)
    # item 2/4 : mode SESSION -> scope + namespacing par run_id (+ SHA git au manifeste).
    session_meta = None
    if session_dir:
        session_dir = Path(session_dir)
        cat = _lire_catalogue_session(session_dir)
        session_meta = {"run_id": cat.get("run_id") or session_dir.name, "git_head": cat.get("git_head"),
                        "statut": cat.get("statut"), "catalogue": cat}
    if sortie_dir:
        sortie = Path(sortie_dir)
    elif session_meta:
        sortie = racine / DOSSIER_RAPPORTS / session_meta["run_id"]      # namespacé par run_id
    else:
        sortie = racine / DOSSIER_RAPPORTS
    sortie.mkdir(parents=True, exist_ok=True)
    # item 13 : verrou d'analyse — deux ANALYSER ne peuvent pas ecrire le meme rapport/shard/checkpoint.
    _verrou_analyse = acquerir_verrou_analyse(sortie)
    journal = Journal(journal_path or sortie / "journal_lab.log")
    checkpoint_path = checkpoint_path or sortie / "checkpoint_recherche.jsonl"
    # Honnêteté dure : run réel → aucune equity leader fictive.
    reel = not str(source).upper().startswith("SYNTH")
    leader_equity_defaut = None if reel else 100000.0

    espace = R.ESPACE_DEFAUT
    n_grille = 1
    for v in espace.values():
        n_grille *= len(v)
    # Item 11 : plus de plafond arbitraire de configs (l'ancien 48/32). budget <= 0 => MAXIMAL = grille
    # entiere (ici 24) : le double-clic explore tout l'espace par defaut, sans cap code en dur.
    budget = n_grille if int(budget) <= 0 else int(budget)
    total_etapes = 4 + min(n_grille, budget)
    eta = MoteurETA(total_etapes=total_etapes, min_echantillons=3)
    etat: dict[str, Any] = {"titre": source, "total_etapes": total_etapes, "source": source,
                            "cfg_prevues": min(n_grille, budget), "erreurs": 0, "manquantes": 0,
                            "workers": 1, "en_cours": "démarrage", "derniere": "-", "prochaine": "inventaire"}

    # item 10 : chaque étape a son PROPRE timestamp de début. La durée d'une étape = temps depuis le début
    # de CETTE étape — jamais le cumul `temps() - t0` (qui gonflait toutes les durées et faussait l'ETA).
    _t_etape = [t0]

    def _fin_etape(**kw: Any) -> None:
        maintenant = temps()
        eta.terminer_etape(maintenant - _t_etape[0], **kw)
        _t_etape[0] = maintenant

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

    # 1) INVENTAIRE (item 2 : scopé à la session en mode session, jamais un scan global de la racine)
    etat.update({"en_cours": "inventaire des sources", "prochaine": "lecture"})
    _jrn("inventaire: debut")
    if session_meta is not None:
        inv = _inventaire_session(session_dir, session_meta["catalogue"])
        _jrn("inventaire SCOPE session %s : %d artefacts catalogues" % (session_meta["run_id"],
                                                                        inv["total_fichiers"]))
    else:
        inv = inventorier(racine, max_fichiers=max_fichiers)
    etat.update({"octets_total": inv["total_octets"], "derniere": "inventaire (%d fichiers)" % inv["total_fichiers"]})
    _fin_etape(octets=0)
    _jrn("inventaire: %d fichiers, %d lisibles, %d bloques" % (inv["total_fichiers"], inv["lisibles"], inv["bloques"]))
    _rafraichir(horodatage or "T")

    # item 15 : rafraîchissement PÉRIODIQUE (1 s) même pendant une phase BLOQUANTE (lecture d'un gros
    # fichier, recherche/replay). Uniquement en mode interactif (imprimer) → tests déterministes intacts.
    from contextlib import nullcontext

    def _refr_ctx():
        return (RafraichisseurPeriodique(lambda: _rafraichir(horodatage or "T"), intervalle_s=1.0)
                if imprimer else nullcontext())

    # 2) LECTURE -> events, EN STREAMING À MÉMOIRE BORNÉE (item 5) : plus de plafond arbitraire 200k.
    # On déverse tous les événements dans un shard sur DISQUE (RAM bornée, checkpoint/reprise), puis on
    # charge une FENÊTRE bornée pour le replay (budget mémoire EXPLICITE, jamais un nombre magique).
    etat.update({"en_cours": "lecture des donnees (streaming)", "prochaine": "audit"})
    octets_lus = sum(int(f["octets"]) for f in inv["fichiers"] if f["lisible"])
    bloques = int(inv.get("bloques", 0))
    fichiers_lisibles = [f["chemin"] for f in inv["fichiers"] if f["lisible"]]
    # item 4/5 : NAMESPACE shard+checkpoint par run_id (dossier) + HASH des données + SHA git. Un shard
    # d'une autre session (autre hash) ne peut JAMAIS être réutilisé — le nom du fichier change.
    import hashlib
    empreinte_donnees = hashlib.sha256(
        "|".join("%s:%d" % (Path(c).name, Path(c).stat().st_size if Path(c).is_file() else -1)
                 for c in sorted(fichiers_lisibles)).encode("utf-8")).hexdigest()[:12]
    sha_git = (session_meta or {}).get("git_head") or _sha_git(racine)
    ns = "%s.%s" % (empreinte_donnees, (sha_git or "nogit")[:8])
    _ecrire_manifeste_run(sortie, run_id=(session_meta or {}).get("run_id"), data_hash=empreinte_donnees,
                          git_head=sha_git, n_fichiers=len(fichiers_lisibles))
    shard = sortie / ("events_shard.%s.jsonl" % ns)
    with _refr_ctx():
        # item 9 : FUSION CAUSALE (tri-fusion externe) et non une concaténation naïve fichier-par-fichier.
        # Le shard global est ordonné exchange_ts→recv_ts→sequence→source ; une FENÊTRE bornée en est
        # alors un échantillon temporel REPRÉSENTATIF de TOUTES les venues (item 8), pas « tout le
        # fichier 1 puis le fichier 2 ». Indispensable au Lead-Lag Binance→Hyperliquid et au Cross-Venue.
        info_shard = fusionner_causalement(
            fichiers_lisibles, shard, source_de=_venue_du_fichier,
            checkpoint_path=sortie / ("events_shard.%s.checkpoint.json" % ns))
    etat["events_shardes"] = info_shard["n"]
    etat["fusion_causale"] = {k: info_shard.get(k) for k in ("dedupes", "hors_ordre", "gaps", "sources")}
    # item 8 : la fenêtre RAM borne le replay ; c'est un échantillon causalement contigu (pas biaisé venue).
    plafond = [v for v in (max_ram_events, max_events) if v and v > 0]
    events = charger_borne(shard, max_ram=(min(plafond) if plafond else 0))
    valides = _events_valides(events)
    etat.update({"octets_lus": octets_lus, "events_lus": len(events), "events_valides": valides,
                 "events_rejetes": len(events) - valides, "derniere": "lecture (%d events)" % len(events)})
    _fin_etape(octets=octets_lus, evenements=len(events))
    _jrn("lecture: %d events (%d valides), %d fichiers bloques" % (len(events), valides, bloques))
    _rafraichir(horodatage or "T")

    # 3) AUDIT CABLAGE (croise import reel + disponibilite donnees)
    paires_ll = _paires_lead_lag(events)
    ll = score_lead_lag(paires_ll, min_echantillons=20)
    a_hedge = any(isinstance(e.get("cross_venue"), dict) for e in events)
    audit = auditer(a_des_evenements=valides > 0, a_des_carnets_hedge=a_hedge,
                    a_lead_lag=(ll.get("score") != "UNMEASURABLE"))
    audit["lead_lag"] = ll
    # item 13 : Lead-Lag comme VRAIE stratégie paper (signal causal -> entrée -> sortie gelée -> fill ->
    # coûts -> ledger -> PnL IS/OOS/FORWARD). Consommée ici (chemin ANALYSER), résultat au rapport.
    sigs_ll = signaux_depuis_events(events)
    ll_paper = (rejouer_lead_lag(sigs_ll, config={"fee_bps": 2.5}, min_episodes=min_episodes)
                if sigs_ll else {"verdict": "UNMEASURABLE", "segments": {}, "placebo_net": None})
    audit["lead_lag_paper"] = {"verdict": ll_paper["verdict"], "segments": ll_paper.get("segments", {}),
                               "placebo_net": ll_paper.get("placebo_net")}
    etat.update({"en_cours": "audit cablage", "prochaine": "recherche",
                 "derniere": "audit (%d bricks utilisees)" % audit["resume"].get("CABLE ET UTILISE", 0)})
    _fin_etape()
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
        _fin_etape()
        _rafraichir(horodatage or "T")

    with _refr_ctx():
        rech = R.rechercher(events, espace=espace, leader_equity_defaut=leader_equity_defaut, budget=budget,
                            checkpoint_path=checkpoint_path, min_episodes=min_episodes, source=source,
                            on_eval=_on_eval)
    fills = sum(c.get("segments", {}).get("IS", {}).get("fills", 0) or 0 for c in rech["candidats"])
    etat.update({"cfg_testees": rech["evalues"], "fills": fills, "replays": rech["evalues"]})
    _jrn("recherche: %d evaluees, %d cache, verdict %s" % (rech["evalues"], rech["caches"], rech["verdict_global"]))

    # 5) RAPPORT
    etat.update({"en_cours": "ecriture du rapport", "prochaine": "fin"})
    _fin_etape()
    periode = _periode(events)
    chemins = ecrire_rapport(sortie, horodatage=horodatage or "T", inventaire=inv, audit=audit, recherche=rech,
                             eta_final=format_hms(temps() - t0), source=source, periode=periode,
                             checkpoints=[str(checkpoint_path)])
    _jrn("rapport: %s (verdict %s)" % (chemins["latest"], chemins["verdict"]))
    _rafraichir(horodatage or "T")

    try:
        _verrou_analyse.unlink()                 # item 13 : libère le verrou d'analyse en fin de run
    except OSError:
        pass
    return {"rapport": chemins, "verdict": chemins["verdict"], "inventaire": inv, "audit": audit,
            "recherche": rech, "events": len(events), "events_valides": valides, "periode": periode,
            "duree_s": round(temps() - t0, 3), "tableau": etat.get("_tableau", ""),
            "journal": str(journal.chemin), "lead_lag": ll,
            "lead_lag_paper": audit.get("lead_lag_paper")}


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
    ap.add_argument("--session-dir", default=None,
                    help="item 2 : analyser EXCLUSIVEMENT les artefacts catalogues de CETTE session COMPLETE.")
    ap.add_argument("--max-ram-events", type=int, default=0,
                    help="item 7 : fenetre RAM bornee pour le replay (0 = tout le shard, jamais un plafond magique).")
    ap.add_argument("--no-dry-run", action="store_true", help="INTERDIT (paper only) : provoque un refus.")
    args = ap.parse_args(argv)
    if args.no_dry_run:
        print("lab refuse: paper/dry-run only. Aucune execution reelle possible.")
        return 2
    from datetime import datetime, timezone
    horo = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    # item 21 : taxonomie NETTE. Erreur TECHNIQUE (exception, verrou) -> code NON NUL. Sinon le run a
    # produit un rapport valide (verdict economique POSITIF/NEGATIF/NON_MESURABLE) -> code 0, verdict au
    # rapport. Un edge negatif (KILL) ou des donnees insuffisantes (UNMEASURABLE) ne sont PAS des echecs
    # techniques : ce sont des resultats honnetes.
    try:
        res = lancer_lab(racine=args.root, sortie_dir=args.out, budget=args.budget, source=args.source,
                         horodatage=horo, imprimer=True, session_dir=args.session_dir,
                         max_ram_events=args.max_ram_events)
    except AnalyseVerrouilleeError as e:
        print("[LAB][ERREUR] %s" % e, flush=True)
        return 8                                 # verrou d'analyse : une autre analyse ecrit deja ici
    except Exception as e:                        # noqa: BLE001 — erreur technique -> code non nul
        print("[LAB][ERREUR TECHNIQUE] %s: %s" % (type(e).__name__, e), flush=True)
        return 1
    print(res["tableau"])
    print("\nVERDICT: %s\nRAPPORT: %s\nJOURNAL: %s\nDUREE: %ss" % (
        res["verdict"], res["rapport"]["latest"], res["journal"], res["duree_s"]))
    return 0                                       # rapport valide produit (issue economique dans le rapport)


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = ["lancer_lab", "main", "DOSSIER_RAPPORTS", "AnalyseVerrouilleeError", "acquerir_verrou_analyse"]
