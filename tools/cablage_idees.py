"""CÂBLAGE DES 91 IDÉES DANS LE RUN RÉEL (lot WIRING).

Les 16 modules livrés (IDEA-1..91) étaient `PARTIAL_NOT_WIRED` : écrits, testés, mais jamais appelés par le
laboratoire. Ce module est la COUTURE : il expose quelques fonctions de haut niveau que `recherche_continue`
appelle à des points précis du cycle. Tout est **défensif** — si un module manque ou lève, le run continue
et l'incident est journalisé : le câblage ne doit jamais casser une campagne en cours.

Points de câblage :
  • `normaliser_et_dedupliquer` (IDEA-1,2,4,9,10) — à l'ingestion : RAW -> CANONICAL, dédup DURABLE, doublons
    journalisés au lieu d'être jetés en silence ;
  • `verdict_ingestion` (IDEA-79) — panne de scanner ≠ marché calme ;
  • `etat_des_flux` (IDEA-3,6) — statut FEED_* + taux, pour le dashboard ;
  • `controler_verite` (IDEA-11,36,80) — TruthReconciler + ledger corrompu + verrou synthétique, AVANT toute
    promotion ;
  • `manifeste` (IDEA-78) — provenance du run ;
  • `incidents` (IDEA-10,85) — résumé du journal opérationnel + scénarios de stress rejouables.

0 réseau, 0 ordre, paper-only.
"""
from __future__ import annotations

import json
from pathlib import Path


def _journal(rundir):
    try:
        import journal_operationnel as JO
        return JO.JournalOperationnel(Path(rundir) / "operational")
    except Exception:  # noqa: BLE001
        return None


def journaliser_incident(rundir, type_, **kw) -> bool:
    """IDEA-10 — journalise un incident réel. Rend False si le journal est indisponible (jamais une exception
    qui ferait tomber le cycle)."""
    j = _journal(rundir)
    if j is None:
        return False
    try:
        j.enregistrer(type_, **kw)
        return True
    except Exception:  # noqa: BLE001
        return False


def normaliser_et_dedupliquer(rundir, new_events, *, data_origin: str = "REAL") -> dict:
    """IDEA-1/2/4/9/10 — transforme les événements bruts en événements CANONIQUES (3 horloges, provenance,
    snapshot/incrémental, drapeaux qualité), puis retire les DOUBLONS via la dédup DURABLE (qui survit aux
    crashs). Chaque doublon est journalisé (DUPLICATE), jamais effacé en silence.

    Rend {evenements, n_entree, n_canoniques, n_doublons, flags} — `evenements` reste utilisable tel quel par
    le CanonicalStore (mêmes clés coin/exchange_ts/bid/ask)."""
    evs = list(new_events or [])
    out = {"evenements": evs, "n_entree": len(evs), "n_canoniques": 0, "n_doublons": 0,
           "flags": {}, "actif": False}
    try:
        import evenement_canonique as EC
        import dedup_durable as DD
    except Exception:  # noqa: BLE001
        return out
    canoniques, dernier = [], None
    for e in evs:
        try:
            c = EC.normaliser_tick(e, data_origin=data_origin, dernier_recv_ts=dernier)
        except Exception:  # noqa: BLE001
            continue
        dernier = c.get("recv_ts")
        for f in (c.get("data_quality_flags") or []):
            out["flags"][f] = out["flags"].get(f, 0) + 1
        # on conserve les clés d'origine ET les champs canoniques (le CanonicalStore lit coin/exchange_ts/bid/ask)
        canoniques.append({**e, **{k: v for k, v in c.items() if v is not None}})
    try:
        dd = DD.DedupDurable(Path(rundir) / "dedup")
        nouveaux, doublons = dd.filtrer(canoniques, cle="event_id")
    except Exception:  # noqa: BLE001
        nouveaux, doublons = canoniques, []
    for d in doublons[:50]:
        journaliser_incident(rundir, "DUPLICATE", coin=d.get("coin"), detail="event_id deja vu")
    for f, n in out["flags"].items():
        if f in ("GAP", "CARNET_CROISE", "EXCHANGE_TS_DANS_LE_FUTUR"):
            journaliser_incident(rundir, ("WS_GAP" if f == "GAP" else "OUTLIER"),
                                 detail="%s x%d" % (f, n))
    out.update({"evenements": nouveaux, "n_canoniques": len(canoniques),
                "n_doublons": len(doublons), "actif": True})
    return out


def verdict_ingestion(rundir, *, n_nouveaux, erreur=None) -> dict:
    """IDEA-79 — distingue « marché calme » (santé verte) d'une PANNE de collecte (santé rouge, promotion
    interdite). Une panne journalise DATA_MISSING."""
    try:
        import garde_fous_recherche as GF
        v = GF.etat_ingestion(n_nouveaux_evenements=n_nouveaux, erreur_scanner=erreur)
    except Exception:  # noqa: BLE001
        return {"statut": "INCONNU", "sante": "INCONNUE", "promotion_autorisee": True}
    if v.get("sante") == "ROUGE":
        journaliser_incident(rundir, "DATA_MISSING", detail=v.get("motif"))
    return v


def etat_des_flux(snapshot_gate) -> dict:
    """IDEA-3/6 — statut nommé du flux + taux, prêts pour le dashboard. Sans snapshot : statut inconnu."""
    if snapshot_gate is None:
        return {"statut": "INCONNU", "peut_consommer": False, "taux": {}}
    try:
        import etat_flux as EF
        return EF.statut_flux(snapshot_gate)
    except Exception:  # noqa: BLE001
        return {"statut": "INCONNU", "peut_consommer": False, "taux": {}}


def controler_verite(rundir, *, par_candidat=None, verdicts=None) -> dict:
    """IDEA-11/36/80 — contrôle de vérité AVANT toute promotion :
      1. le ledger du portefeuille strict est-il lisible (IDEA-36) ?
      2. la chaîne événement→PnL→dashboard se recoupe-t-elle par candidat (IDEA-11) ?
      3. un verdict de promotion s'appuie-t-il sur des données SYNTHÉTIQUES (IDEA-80) ?
    Rend `promotion_autorisee` : False dès qu'un des trois échoue, avec la raison."""
    res = {"ledger": None, "truth": None, "synthetique": [], "promotion_autorisee": True,
           "raisons": []}
    rundir = Path(rundir)
    try:
        import pnl_verite as PV
        led = PV.scanner_ledger(rundir / "global_portfolio" / "ledger.jsonl")
        res["ledger"] = {k: led[k] for k in ("statut", "n_erreurs", "promotion_autorisee")}
        if not led["promotion_autorisee"]:
            res["promotion_autorisee"] = False
            res["raisons"].append("LEDGER_CORROMPU")
            journaliser_incident(rundir, "LEDGER_MISMATCH",
                                 detail="%d ligne(s) invalide(s)" % led["n_erreurs"])
    except Exception:  # noqa: BLE001
        pass
    if par_candidat:
        try:
            import ledger_verite as LV
            t = LV.TruthReconciler().verifier_tous(par_candidat)
            res["truth"] = {"n_quarantaine": t["n_quarantaine"], "quarantaine": t["quarantaine"]}
            if not t["promotion_globale_autorisee"]:
                res["promotion_autorisee"] = False
                res["raisons"].append("PNL_UNTRUSTED")
                journaliser_incident(rundir, "PNL_UNTRUSTED",
                                     detail="candidats en quarantaine: %s" % ",".join(t["quarantaine"][:5]))
        except Exception:  # noqa: BLE001
            pass
    try:
        import garde_fous_recherche as GF
        for v in (verdicts or []):
            r = GF.verrou_synthetique(v)
            if r["violation"]:
                res["synthetique"].append({"trial_id": v.get("trial_id"),
                                           "verdict_corrige": r["verdict_corrige"]})
        if res["synthetique"]:
            res["promotion_autorisee"] = False
            res["raisons"].append("PROMOTION_SUR_DONNEE_SYNTHETIQUE")
    except Exception:  # noqa: BLE001
        pass
    return res


def manifeste(racine, rundir=None, **kw) -> dict:
    """IDEA-78 — manifeste de campagne (Git HEAD, dirty, Python, config éco…). Écrit dans le run si fourni."""
    try:
        import garde_fous_recherche as GF
        m = GF.manifeste_campagne(Path(racine), **kw)
    except Exception as e:  # noqa: BLE001
        m = {"erreur": str(e)[:160]}
    if rundir:
        try:
            p = Path(rundir) / "manifeste"
            p.mkdir(parents=True, exist_ok=True)
            (p / "campagne.json").write_text(json.dumps(m, ensure_ascii=False, indent=1), encoding="utf-8")
        except OSError:
            pass
    return m


def incidents(rundir) -> dict:
    """IDEA-10/85 — résumé du journal opérationnel + scénarios de stress issus des incidents RÉELS."""
    j = _journal(rundir)
    if j is None:
        return {"n_incidents": 0, "par_type": {}, "scenarios": [], "promotion_interdite": False}
    try:
        r = j.resume()
        return {**r, "scenarios": j.scenarios_pour_replay()}
    except Exception:  # noqa: BLE001
        return {"n_incidents": 0, "par_type": {}, "scenarios": [], "promotion_interdite": False}


__all__ = ["journaliser_incident", "normaliser_et_dedupliquer", "verdict_ingestion", "etat_des_flux",
           "controler_verite", "manifeste", "incidents"]
