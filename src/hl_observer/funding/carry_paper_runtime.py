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

ENV_ENABLED = "HYPERSMART_CARRY_HYPE_PAPER"
ENV_ETAPE2 = "HYPERSMART_CARRY_ETAPE2"   # opt-in : ouvrir REELLEMENT la position paper (etape 2)
INPUTS_RELPATH = Path("runtime") / "data" / "carry_spot_inputs.json"
SHORTLIST_RELPATH = Path("runtime") / "data" / "carry_spot_shortlist.json"   # TOUS les viables (parallele)
JOURNAL_RELPATH = Path("runtime") / "data" / "carry_hype_paper_decisions.jsonl"

MOTIF_INPUTS_ABSENTS = "INPUTS_SPOT_ABSENTS_NO_TRADE"
MOTIF_INPUTS_PERIMES = "INPUTS_SPOT_PERIMES_NO_TRADE"
MAX_AGE_S_DEFAUT = 900.0


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
                        "prix": inp.get("perp_px")}
            evts = tick_multi_sur_disque(root, mesures, now_ms=now)
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
        pass  # un journal qui echoue ne casse pas la boucle; la decision est retournee quand meme
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
