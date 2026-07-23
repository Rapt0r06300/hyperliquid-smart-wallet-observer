"""Carry HYPE en PAPER — décision de Flo (2026-07-14) : « les 3 », dont l'exploitation du carry.

CE QUE CE MODULE FAIT (v1, honnête) :
  * lit les entrées MESURÉES depuis `runtime/data/carry_spot_inputs.json` (base spot-perp,
    liquidité spot, marge/levier/pire hausse pour le verrou T2b) — écrites par l'outil de
    mesure (T2/T2b), PAS devinées ;
  * lit le funding depuis le même fichier (même règle : mesuré ou absent) ;
  * appelle `evaluer_carry_neutre` (deny-by-default + verrou liquidation T2b/#588) ;
  * JOURNALISE chaque décision — ACCEPT ou REFUS motivé — dans
    `runtime/data/carry_hype_paper_decisions.jsonl`, estampillée session_id.

CE QU'IL NE FAIT PAS (v1) : il n'ouvre PAS encore de position paper. La décision est
matérialisée et auditable d'abord ; l'ouverture ledger est l'étape 2, nommée. Un module qui
déciderait ET exécuterait ET tiendrait le ledger dans la même passe serait invérifiable.

PIÈGE D'UNITÉ (leçon du 13/07 : « 38 % APR qui étaient l'intervalle de funding ») : ce module
ne CONVERTIT jamais un taux. `funding_bps_h` doit arriver DÉJÀ en bps/heure depuis l'outil de
mesure. Des entrées trop vieilles (> max_age_s) valent ABSENTES → refus INPUTS_PERIMES.

Read-only / paper-only : AUCUN ordre réel, aucune clé, aucune signature. Un signal n'est
jamais un ordre ; un paper trade n'est jamais un ordre.
"""
from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any

from hl_observer.funding.delta_neutral_carry import evaluer_carry_neutre
from hl_observer.runtime.session_identity import session_courante
from hl_observer.ops.echec_silencieux import noter as _noter_echec

ENV_ENABLED = "HYPERSMART_CARRY_HYPE_PAPER"
ENV_ETAPE2 = "HYPERSMART_CARRY_ETAPE2"   # opt-in : ouvrir REELLEMENT la position paper (etape 2)
MAX_SLOTS_CARRY = 12   # plafond de positions carry : on OUVRE tous les viables (plus d'ouvertures =
#                      # plus de funding + plus de donnees replay). Rotation garde les meilleurs nets.
INPUTS_RELPATH = Path("runtime") / "data" / "carry_spot_inputs.json"
SHORTLIST_RELPATH = Path("runtime") / "data" / "carry_spot_shortlist.json"   # TOUS les viables (parallele)
JOURNAL_RELPATH = Path("runtime") / "data" / "carry_hype_paper_decisions.jsonl"

MOTIF_INPUTS_ABSENTS = "INPUTS_SPOT_ABSENTS_NO_TRADE"
MOTIF_INPUTS_PERIMES = "INPUTS_SPOT_PERIMES_NO_TRADE"
MAX_AGE_S_DEFAUT = 900.0


ENV_CAPITAL = "HYPERSMART_SIMULATION_INITIAL_EQUITY_USDT"


def _capital_depuis_env() -> float | None:
    """Le capital de simulation déclaré, ou None. On ne DEVINE jamais un capital : inventer un
    capital, ce serait inventer une taille de position, donc un PnL."""
    brut = os.environ.get(ENV_CAPITAL, "").strip()
    try:
        v = float(brut)
    except (TypeError, ValueError):
        return None
    return v if v > 0 else None


def _capital_disponible(root: str | Path) -> float | None:
    """Le capital RÉEL de la simulation, ou None si on ne peut pas le lire.

    🔴 CORRIGÉ LE 19/07 — MA MARGE DYNAMIQUE ÉTAIT INERTE. Je l'avais branchée sur
    `simulation.paper_ledger.equity_courante(...)` : **cette fonction n'existe pas**. L'import
    levait une ImportError, on retombait sur la variable d'env — que le lanceur ne pose nulle
    part — donc `None`, donc la marge par défaut de 50 $. Le notional est resté à 75 $ toute la
    journée pendant que je croyais l'avoir agrandi.

    C'est exactement la maladie du projet, commise par moi, et attrapée seulement parce que j'ai
    relu un notional au lieu de croire mon propre commit : **un module branché sur une fonction
    fantôme est un module mort**. Le `except Exception` autour de l'import rendait la panne
    silencieuse — la 106ᵉ occurrence du problème qu'on a passé la journée à traquer.

    On lit maintenant l'équity là où elle est VRAIMENT écrite (l'état UI du moteur), avec deux
    replis explicites et aucune invention : env déclarée, sinon None (marge par défaut).
    """
    # 1) l'état moteur, écrit par le runtime lui-même
    # 🔴 20/07 — DEUXIÈME clé fantôme au même endroit (constat : `capital live = None` pendant
    # que le fichier existait) : les clés testées (`equity_usdt`...) n'existent PAS dans ce
    # fichier. Le vrai schéma : `simulation_equity_history[-1].current_equity_usdt` (équity
    # vivante) puis `simulation_starting_equity_usdt` (départ). Lu au VRAI schéma, vérifié sur
    # le fichier réel — plus jamais une clé supposée.
    try:
        etat = json.loads((Path(root) / "runtime" / "data" / "ui_simulation_state.json")
                          .read_text(encoding="utf-8-sig"))
        if isinstance(etat, dict):
            for cle in ("equity_usdt", "current_equity_usdt", "equity"):
                v = etat.get(cle)
                if isinstance(v, (int, float)) and float(v) > 0:
                    return float(v)
            hist = etat.get("simulation_equity_history")
            if isinstance(hist, list) and hist and isinstance(hist[-1], dict):
                v = hist[-1].get("current_equity_usdt")
                if isinstance(v, (int, float)) and float(v) > 0:
                    return float(v)
            v = etat.get("simulation_starting_equity_usdt")
            if isinstance(v, (int, float)) and float(v) > 0:
                return float(v)
    except (OSError, ValueError, TypeError) as exc:
        # cliquet 105->0 : on avale, mais on COMPTE (une panne muette n'a jamais de piste)
        _noter_echec("hl_observer/funding/carry_paper_runtime.py:capital_etat", exc)
    # 2) le capital déclaré en environnement
    return _capital_depuis_env()


def enabled() -> bool:
    return os.environ.get(ENV_ENABLED, "0").strip() == "1"


def etape2_active() -> bool:
    """Ouvrir REELLEMENT les positions paper (etape 2). Opt-in : off par defaut."""
    return os.environ.get(ENV_ETAPE2, "0").strip() == "1"


def charger_inputs(root: str | Path = ".", *, now_ms: int | None = None,
                   max_age_s: float = MAX_AGE_S_DEFAUT) -> tuple[dict[str, Any] | None, str]:
    """(inputs, motif_de_refus_si_None). Une donnée trop vieille est une donnée ABSENTE."""
    path = Path(root) / INPUTS_RELPATH
    try:
        data = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError):
        return None, MOTIF_INPUTS_ABSENTS
    if not isinstance(data, dict):
        return None, MOTIF_INPUTS_ABSENTS
    ts = data.get("ts_ms")
    now = float(now_ms or time.time() * 1000)
    if not isinstance(ts, (int, float)) or ts <= 0 or (now - float(ts)) > max_age_s * 1000.0:
        return None, MOTIF_INPUTS_PERIMES
    return data, ""


def evaluer_inputs(inputs: dict[str, Any]) -> dict[str, Any]:
    """inputs MESURES -> decision dict (verdict.as_dict()). AUCUNE conversion d'unite (piege 38%)."""
    def _g(key: str) -> float | None:
        v = inputs.get(key)
        return float(v) if isinstance(v, (int, float)) else None
    verdict = evaluer_carry_neutre(
        coin=str(inputs.get("coin") or "HYPE"),
        funding_bps_h=_g("funding_bps_h"), base_bps=_g("base_bps"),
        liquidite_spot_usd=_g("liquidite_spot_usd"), maker=bool(inputs.get("maker", True)),
        levier_max=_g("levier_max"), marge_ratio=_g("marge_ratio"),
        pire_hausse_observee=_g("pire_hausse_observee"))
    return verdict.as_dict()


def charger_shortlist(root: str | Path = ".", *, now_ms: int | None = None,
                      max_age_s: float = MAX_AGE_S_DEFAUT) -> list[dict[str, Any]]:
    """La liste des carrys viables, chacun frais (< max_age). Un vieux/absent -> [] (deny-by-default)."""
    try:
        data = json.loads((Path(root) / SHORTLIST_RELPATH).read_text(encoding="utf-8-sig"))
    except (OSError, ValueError):
        return []
    if not isinstance(data, list):
        return []
    now = float(now_ms or time.time() * 1000)
    out: list[dict[str, Any]] = []
    for e in data:
        if not isinstance(e, dict):
            continue
        ts = e.get("ts_ms")
        if isinstance(ts, (int, float)) and ts > 0 and (now - float(ts)) <= max_age_s * 1000.0:
            out.append(e)
    return out


def _journal_path(root: str | Path) -> Path:
    return Path(root) / JOURNAL_RELPATH


def evaluer_et_journaliser(root: str | Path = ".", *, now_ms: int | None = None,
                           max_age_s: float = MAX_AGE_S_DEFAUT) -> dict[str, Any]:
    """Une évaluation = une ligne de journal. Jamais d'exception vers l'appelant."""
    now = int(now_ms or time.time() * 1000)
    inputs, motif = charger_inputs(root, now_ms=now, max_age_s=max_age_s)
    if inputs is None:
        decision: dict[str, Any] = {
            "coin": "HYPE", "viable": False, "motif": motif,
            "note": "les entrees (base, liquidite spot, funding, marge) doivent etre MESUREES; "
                    "on ne les invente pas. Outil: tools/diagnostic_spot_hyperliquid.py + MESURER-588.cmd",
            "real_execution": False,
        }
        inputs_age_s = None
    else:
        decision = evaluer_inputs(inputs)
        inputs_age_s = round((now - float(inputs["ts_ms"])) / 1000.0, 1)

    # ETAPE 2 (opt-in) : ouvrir/tenir/fermer REELLEMENT les positions paper -- MULTI-COINS via la
    # shortlist (repli sur le meilleur seul). Ne casse JAMAIS la decision/journal (erreur capturee).
    # PAPER only : aucun ordre, aucune signature.
    # FIREHOSE (#1) : chaque décision carry (ACCEPT ou REFUS) devient un candidat replay, dans le
    # MÊME flux que lit le docteur replay -> on rejoue MÊME sans ouverture réelle. Best-effort.
    try:
        from hl_observer.ops.decision_firehose import (
            enregistrer_decision as _fh, enregistrer_marks as _mk)
        _fh(str(root), decision, strategie="carry", ts_s=now / 1000.0,
            mid=(inputs or {}).get("perp_px") if inputs else None)
        # 🔴 MARKS — CONSTAT 18/07 : marks.jsonl contenait 0 ligne pour 1610 candidats, donc le
        # replay A/B ne mesurait RIEN (prefilter jette tout sans marks = cause du « 1 sur 1M »).
        # L'écrivain d'origine (v26_exit_pipeline) n'est pas atteint par la boucle -> on écrit les
        # marks ICI, depuis le runtime qui TOURNE, avec le prix perp réel de chaque coin suivi.
        _mids: dict[str, float] = {}
        _liste = charger_shortlist(root, now_ms=now, max_age_s=max_age_s) or ([inputs] if inputs else [])
        for _inp in _liste:
            _c = str((_inp or {}).get("coin") or "").upper()
            _p = (_inp or {}).get("perp_px")
            if _c and isinstance(_p, (int, float)) and float(_p) > 0:
                _mids[_c] = float(_p)
        if _mids:
            _mk(str(root), _mids, ts_s=now / 1000.0)
    except Exception:  # noqa: BLE001 — un firehose qui échoue ne casse jamais la décision
        _noter_echec("hl_observer/funding/carry_paper_runtime.py:166")

    # SUPERVISEUR (19/07) : les 4 collecteurs sont morts ensemble a 15:27 -> inputs perimes en
    # 15 min -> INPUTS_SPOT_PERIMES_NO_TRADE en boucle -> bot affame. L'alarme existait
    # (VERIFIER-TOUT section 5) mais personne ne la regardait pendant que le bot tournait.
    # Ce moteur-ci SURVIT (prouve : il journalisait encore a 15:55) -> c'est donc LUI qui
    # constate le silence d'un collecteur et le relance. Best-effort, cooldown 10 min,
    # journalise dans runtime/data/superviseur_collecteurs.json. Ne casse JAMAIS la decision.
    try:
        from hl_observer.ops.superviseur_collecteurs import verifier_et_relancer
        verifier_et_relancer(root)
    except Exception:  # noqa: BLE001 — un superviseur qui tue le moteur serait pire que la panne
        _noter_echec("hl_observer/funding/carry_paper_runtime.py:superviseur")

    # ── ARBITRAGE DE DISLOCATION paper v1 (21/07) — portes dures pre-declarees (35 bps
    # d'ouverture = couts 22 + marge 13 : edge positif a l'entree PAR CONSTRUCTION). Ecrit
    # dans LE MEME ledger -> PnL unifie. Jamais bloquant pour le carry.
    if os.environ.get("HYPERSMART_ARB_DISLOCATION_PAPER", "0").strip() == "1":
        try:
            from hl_observer.funding.arb_dislocation_paper import tick as _arb_tick
            from hl_observer.runtime.session_identity import session_courante as _sid
            _arb_tick(root, session_id=_sid(root))
        except Exception:  # noqa: BLE001 — compte, jamais silencieux, jamais bloquant
            _noter_echec("hl_observer/funding/carry_paper_runtime.py:arb_dislocation")

    # ── CARRY CROSS-VENUE paper (23/07) — delta-neutre : SHORT perp HL (encaisse le funding le
    # plus haut) / LONG perp Binance. Encaisse le premium `hl_bps_h − bin_bps_h` tant qu'il tient,
    # coûts RÉELS du carnet déduits. Même ledger -> PnL unifié. Jamais bloquant pour le carry.
    if os.environ.get("HYPERSMART_CROSS_VENUE_CARRY_PAPER", "0").strip() == "1":
        try:
            from hl_observer.funding.cross_venue_carry_paper import tick as _cv_tick
            from hl_observer.runtime.session_identity import session_courante as _sid2
            _cv_tick(root, session_id=_sid2(root))
        except Exception:  # noqa: BLE001 — compte, jamais silencieux, jamais bloquant
            _noter_echec("hl_observer/funding/carry_paper_runtime.py:cross_venue_carry")

    etape2 = None
    if etape2_active():
        try:
            from hl_observer.funding.carry_positions_store import tick_multi_sur_disque, etat_carry
            liste = charger_shortlist(root, now_ms=now, max_age_s=max_age_s)
            if not liste and inputs is not None:
                liste = [inputs]
            mesures: dict[str, dict[str, Any]] = {}
            for inp in liste:
                dec = evaluer_inputs(inp)
                if dec.get("viable"):
                    mesures[str(dec.get("coin") or "").upper()] = {
                        "decision": dec, "inputs": inp, "funding": dec.get("funding_bps_h"),
                        "prix": inp.get("perp_px"), "base": dec.get("base_bps")}
            # CAPITAL RÉEL -> marge dynamique. 92 % du capital dormait (75 $ de notional sur
            # 1 000 $ d'equity = 2,25 centimes/jour, invisible au dashboard). Grossir la MARGE à
            # levier constant n'ajoute AUCUN risque de liquidation (la distance dépend du levier).
            # Capital illisible -> None -> marge par défaut : on n'invente jamais un capital.
            capital = _capital_disponible(root)
            evts = tick_multi_sur_disque(root, mesures, now_ms=now, max_slots=MAX_SLOTS_CARRY,
                                         capital_usd=capital)
            etat = etat_carry(root)
            etape2 = {"evts": evts, "n_mesures": len(mesures),
                      "positions_ouvertes": etat["positions_ouvertes"],
                      "coins_ouverts": etat["coins_ouverts"],
                      "realise_total_usdt": etat["realized_net_pnl_usdc"]}
        except Exception as exc:  # noqa: BLE001
            etape2 = {"erreur": "etape2_indisponible", "detail": str(exc)}

    ligne = {
        "ts_ms": now,
        "session_id": session_courante(root),
        "inputs_age_s": inputs_age_s,
        "decision": decision,
        "etape2": etape2,
        "paper_only": True,
        "real_execution": False,
    }
    try:
        path = _journal_path(root)
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(ligne, ensure_ascii=False) + "\n")
    except OSError:
        _noter_echec("hl_observer/funding/carry_paper_runtime.py:217")
    return ligne


def main(argv: list[str] | None = None) -> int:
    import argparse
    p = argparse.ArgumentParser(description="Carry HYPE paper: evaluer et journaliser (read-only)")
    p.add_argument("--root", default=".")
    p.add_argument("--once", action="store_true")
    args = p.parse_args(argv)
    ligne = evaluer_et_journaliser(args.root)
    print(json.dumps(ligne, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
