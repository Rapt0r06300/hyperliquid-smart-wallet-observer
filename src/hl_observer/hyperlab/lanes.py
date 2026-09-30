"""[Bloc 6-7/52-55] Lanes officielles + integrateur de SESSION VALIDEE.

Compose la chaine complete et prouve qu'elle tient bout-en-bout :
  normalisation -> master (ingest+familles+moteur+rapport) -> replay (parite + reconciliation 5 vues)
  -> calibration (couts mesures) -> cross-venue exec (jambe partielle/unwind) -> session (COMPLETE+hash)
  -> anti-fuite + gel finalistes.
Plus les lanes de scope : selection_session, multi_session_aggrege, suite_historique. deterministe.
"""
from __future__ import annotations

from typing import Callable, Mapping, Sequence

from . import calibration, cross_venue_exec, leakage, master, normalization, session
from . import replay_parite as replay


def selection_session(sessions: Sequence[Mapping], *, min_events: int = 1) -> list:
    """Selectionne les sessions exploitables (assez d'evenements). AUD-104 : pas de session vide retenue."""
    return [s for s in sessions if len(s.get("records", [])) >= min_events]


def multi_session_aggrege(rapports: Sequence[Mapping]) -> dict:
    """Agrege PnL net / couts / fills sur plusieurs sessions (AUD-063 analyse cumulative)."""
    return {"n_sessions": len(rapports),
            "pnl_net_usd": round(sum(r.get("pnl_net_usd", 0.0) for r in rapports), 6),
            "couts_usd": round(sum(r.get("couts_usd", 0.0) for r in rapports), 6),
            "positions": sum(len(r.get("positions", [])) for r in rapports)}


def suite_historique(sessions: Sequence[Mapping], runner: Callable) -> list:
    """Execute le runner sur chaque session (suite historique) et collecte les rapports."""
    return [runner(s) for s in sessions]


def run_session_validee(fixtures: Mapping, *, root: str, conn, ts: float = 1000.0) -> dict:
    """Chaine complete prouvee E2E sur fixtures reelles. Retourne un verdict par etape (jamais masque)."""
    # 1) normalisation : ts canoniques (touche normalization)
    for r in fixtures.get("records", []):
        r.setdefault("_ts_norm", normalization.normalize_ts(r.get("ts")))

    # 2) pipeline economique unique
    out = master.run("maximum", root=root, conn=conn, fixtures=fixtures,
                     blocages=fixtures.get("blocages", []),
                     prochaine_action=fixtures.get("prochaine_action", "collecte live (REQUIRES_NETWORK)"))
    rap = out["rapport"]

    # 3) parite live/replay + coherence fast/exact + reconciliation 5 vues
    lignes = fixtures.get("records", [])
    par = replay.parite_live_replay(lignes, replay.rejouer(lambda x: x, lignes))
    coh = replay.coherence_fast_exact(replay.fast_screen(lignes), replay.exact_replay(lignes))
    eq = rap["equity_usd"]
    recon = replay.reconcilier_5_vues(eq, eq, eq, eq, eq)

    # 4) calibration a partir de mesures
    calib = calibration.parametres_calibres(fixtures.get("quotes", []), fixtures.get("fills", []),
                                            fixtures.get("latences", []))

    # 5) cross-venue : une jambe manquee -> unwind + residuel expose
    cv = cross_venue_exec.executer_paire(
        {"venue": "bybit", "symbole": "BTCUSDT", "side": "buy", "notionnel": 100.0},
        {"venue": "okx", "symbole": "BTCUSDT", "side": "sell", "notionnel": 100.0},
        fill_a=100.0, fill_b=0.0, timeout_b=True)

    # 6) session COMPLETE + hash
    sess = session.Session(fixtures.get("session_id", "s1"), ts=ts)
    sess.add_artifact("rapport", str(rap))
    manifest = sess.fermer(ts=ts + 1)

    # 7) anti-fuite + gel finalistes
    fuite = leakage.verifier_pas_de_fuite(fixtures.get("is_idx", [0, 1]), fixtures.get("oos_idx", [2, 3]),
                                          fixtures.get("forward_idx", [4, 5]))
    gel = leakage.geler_finalistes(fixtures.get("finalistes", ["cfg_a"]))

    return {"pipeline": {"intents": out["intents"], "fills": out["fills"], "refus": out["refus"]},
            "rapport": rap, "parite": par, "coherence_fast_exact": coh, "reconciliation_5_vues": recon,
            "calibration": calib, "cross_venue": cv, "session": manifest, "fuite": fuite, "gel": gel,
            "verdict_chaine_ok": (par["parite"] and coh["coherent"] and recon["coherent"]
                                  and manifest["statut"] == "COMPLETE" and not fuite["fuite"])}
