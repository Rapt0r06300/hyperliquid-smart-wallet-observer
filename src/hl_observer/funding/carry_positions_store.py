"""Persistance sur disque de l'ETAPE 2 du carry (positions ouvertes + ledger PnL realise).

Le core `carry_position_lifecycle` est PUR (sans I/O). Ici on ajoute la couche disque pour que les
positions survivent entre les polls du bot :
  * `runtime/data/carry_paper_positions.json`  -> les positions OUVERTES (dict coin->pos), avec le `mode` ;
  * `runtime/data/carry_paper_ledger.jsonl`    -> append-only : chaque OPEN / CLOSE (PnL realise).

Regle dure : un fichier d'etat = UN seul mode. Si le mode demande != le mode du fichier, on repart
VIDE (jamais de melange LIVE/BACKTEST/REPLAY/TEST_FIXTURE). PAPER only : aucun ordre, aucune signature.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from hl_observer.funding.carry_anti_churn import (
    SORTIE_ABSENCE_PROLONGEE, churn_excessif, doit_fermer_pour_absence, filtrer_sortie,
)
from hl_observer.funding.carry_marge_dynamique import marge_par_position
from hl_observer.funding.carry_position_lifecycle import (
    MODE_LIVE, MODES_VALIDES, GestionnaireCarry, pnl_realise,
)

SORTIE_HORS_SHORTLIST = "COIN_PLUS_DANS_SHORTLIST"   # conservé : d'anciennes lignes de ledger le portent
SORTIE_ROTATION = "ROTATION_HORS_TOP_SLOTS"   # A7 : plafond de slots -> on garde les meilleurs nets

POSITIONS_RELPATH = Path("runtime") / "data" / "carry_paper_positions.json"
LEDGER_RELPATH = Path("runtime") / "data" / "carry_paper_ledger.jsonl"


def _positions_path(root: str | Path) -> Path:
    return Path(root) / POSITIONS_RELPATH


def _ledger_path(root: str | Path) -> Path:
    return Path(root) / LEDGER_RELPATH


def charger_gestionnaire(root: str | Path = ".", *, mode: str = MODE_LIVE) -> GestionnaireCarry:
    """Reconstruit le gestionnaire depuis le disque. Mode different sur le fichier -> on repart VIDE
    (on ne melange jamais deux modes de PnL)."""
    if mode not in MODES_VALIDES:
        raise ValueError("mode inconnu: %r" % (mode,))
    try:
        data = json.loads(_positions_path(root).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        data = None
    ouvertes: dict[str, dict[str, Any]] = {}
    if isinstance(data, dict) and data.get("mode") == mode and isinstance(data.get("ouvertes"), dict):
        for coin, pos in data["ouvertes"].items():
            if isinstance(pos, dict) and pos.get("mode") == mode:
                ouvertes[str(coin).upper()] = pos
    return GestionnaireCarry(mode=mode, ouvertes=ouvertes)


def sauver_gestionnaire(root: str | Path, g: GestionnaireCarry) -> None:
    p = _positions_path(root)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps({"mode": g.mode, "ouvertes": g.ouvertes}, ensure_ascii=False, indent=2),
                 encoding="utf-8")


def _append_ledger(root: str | Path, row: dict[str, Any]) -> None:
    p = _ledger_path(root)
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(row, ensure_ascii=False) + "\n")


def tick_sur_disque(root: str | Path, decision: dict[str, Any], inputs: dict[str, Any], *,
                    now_ms: int, funding_bps_h_courant: float | None = None,
                    hausse_depuis_entree: float = 0.0, mode: str = MODE_LIVE) -> dict[str, Any]:
    """Une passe persistee : charge, tick (accrue/sort/ouvre), sauve, append OPEN/CLOSE au ledger."""
    g = charger_gestionnaire(root, mode=mode)
    evt = g.tick(decision, inputs, now_ms=now_ms, funding_bps_h_courant=funding_bps_h_courant,
                 hausse_depuis_entree=hausse_depuis_entree)
    sauver_gestionnaire(root, g)
    for r in g.journal.rows():                       # journal frais a chaque charge -> uniquement CE tick
        _append_ledger(root, {**r, "ts_ms": int(now_ms), "mode": mode})
    return evt


def tick_multi_sur_disque(root: str | Path, mesures: dict[str, dict[str, Any]], *,
                          now_ms: int, mode: str = MODE_LIVE,
                          max_slots: int | None = None,
                          capital_usd: float | None = None) -> list[dict[str, Any]]:
    """Une passe MULTI-COINS persistee. `mesures` = {coin: {"decision","inputs","funding"}}.
    Ouvre/tient une position par coin mesuré ; FERME tout coin ouvert qui n'est PLUS mesuré ce
    poll (deny-by-default : on ne tient jamais une position sur une donnée disparue). Un coin =
    une position. A7 : `max_slots` plafonne le nombre de positions -> on garde les meilleurs nets
    (rotation vers le meilleur carry ; l'hysteresis de carry_rotation evite le churn marginal)."""
    g = charger_gestionnaire(root, mode=mode)
    evts: list[dict[str, Any]] = []
    # MARGE DYNAMIQUE — 92 % du capital dormait pendant que le PnL « ne bougeait pas » (75 $ de
    # notional sur 1 000 $ d'equity => 2,25 centimes/jour, invisible). On répartit le capital
    # DÉPLOYABLE entre les positions visées. La distance à la liquidation dépend du LEVIER, pas
    # de la taille : grossir la marge à levier constant n'ajoute AUCUN risque de liquidation.
    # `capital_usd` absent -> marge par défaut (on n'invente jamais un capital).
    n_visees = min(len(mesures) or 1, int(max_slots) if max_slots else (len(mesures) or 1))
    marge = marge_par_position(capital_usd=capital_usd, n_positions_visees=n_visees)
    for coin, m in mesures.items():
        evts.append(g.tick(m["decision"], m["inputs"], now_ms=now_ms,
                           funding_bps_h_courant=m.get("funding"), prix_courant=m.get("prix"),
                           base_bps_courant=m.get("base"), marge_usd=marge))
    # 🔴 A1 — LE BUG QUI MANGEAIT TOUT LE PnL (mesuré le 19/07 : 29 fermetures sur 31 ici).
    # L'ancienne version fermait DES QU'un coin manquait d'une passe, au nom du deny-by-default.
    # C'etait une MAUVAISE application de la regle : deny-by-default veut dire « ne pas OUVRIR
    # sans donnee », pas « FERMER quand la donnee cligne ». Le feeder saute une passe -> on
    # fermait (11 bps) puis on rouvrait (12,5 bps) : 17,6 centimes, soit ~188 HEURES de funding,
    # detruites parce qu'un fichier n'avait pas ete ecrit a temps.
    # Desormais : une absence est TOLEREE quelques passes ET quelques minutes. Elle fige la
    # decision, elle ne declenche plus d'aller-retour.
    for coin in list(g.ouvertes):
        pos = g.ouvertes[coin]
        if coin in mesures:
            pos.pop("absences_consecutives", None)         # la donnee est revenue : on oublie
            pos.pop("premiere_absence_ts_ms", None)
            continue
        n_abs = int(pos.get("absences_consecutives") or 0) + 1
        premiere = pos.get("premiere_absence_ts_ms")
        if not isinstance(premiere, (int, float)) or float(premiere) <= 0:
            premiere = int(now_ms)
        pos["absences_consecutives"] = n_abs
        pos["premiere_absence_ts_ms"] = int(premiere)
        minutes = (int(now_ms) - int(premiere)) / 60_000.0
        if not doit_fermer_pour_absence(absences_consecutives=n_abs,
                                        minutes_depuis_1re_absence=minutes):
            evts.append({"coin": coin, "mode": mode, "ouvert": False, "ferme": None,
                         "attente_donnee": {"passes": n_abs, "minutes": round(minutes, 1)},
                         "funding_add_usdt": 0.0})
            continue                                       # on GARDE : l'absence n'est pas une sortie
        # 🔴 NUIT DU 19-20/07 : PURR ferme 3x (-0,49 $) par CETTE porte alors que le marche
        # etait bien MESURE -- c'est le feeder qui ratait ses bougies ('pire-hausse non
        # mesurable'), donc PURR sortait de la shortlist, donc 'absent'. Refuser d'OUVRIR sans
        # bougies est juste ; fermer une position DEJA OUVERTE (risque mesure a l'entree, prix
        # suivi par les marks) pour un rate de fetch est le churn qui revient par la fenetre.
        # Distinction desormais :
        #   * mesures VIDES (vrai blackout, feeder mort)   -> fermer (deny-by-default, inchange) ;
        #   * d'autres coins MESURES (donnee vivante, CE coin non viable ce tick) -> la sortie
        #     redevient un 'hors shortlist' NON URGENT : gate par l'amortissement (A3, meme
        #     regle que COIN_PLUS_DANS_SHORTLIST). Funding d'entree en proxy pour l'amorti.
        if mesures:
            motif_apres_gate = filtrer_sortie(
                SORTIE_HORS_SHORTLIST, pos, now_ms=int(now_ms),
                funding_bps_h=float(pos.get("funding_bps_h_entree") or 0.0))
            if motif_apres_gate is None:
                evts.append({"coin": coin, "mode": mode, "ouvert": False, "ferme": None,
                             "attente_donnee": {"passes": n_abs, "minutes": round(minutes, 1),
                                                "non_amorti": True},
                             "funding_add_usdt": 0.0})
                continue                                   # non amorti : fermer acterait la perte
        # absence PROLONGEE : la donnee a vraiment disparu -> la, on ferme.
        # base courante inconnue -> conservateur : base d'entree (aucun premium capture)
        realized = pnl_realise(pos, base_bps_courant=float(pos.get("base_bps_entree") or 0.0))
        g.journal.record(kind="CLOSE", coin=coin, side="CARRY", notional_usdt=pos["notional_usdt"],
                         realized_net_pnl_usdc=realized, reason=SORTIE_ABSENCE_PROLONGEE,
                         now_ms=int(now_ms))
        g.ouvertes.pop(coin, None)
        evts.append({"coin": coin, "mode": mode, "ouvert": False, "ferme": SORTIE_ABSENCE_PROLONGEE,
                     "pnl_realise_usdt": realized, "funding_add_usdt": 0.0,
                     "absence": {"passes": n_abs, "minutes": round(minutes, 1)}})
    if max_slots is not None and len(g.ouvertes) > int(max_slots):   # A7 : rotation vers les meilleurs nets
        par_net = sorted(g.ouvertes.items(),
                         key=lambda kv: float(kv[1].get("gain_net_24h_bps") or 0.0))   # pire net d'abord
        for coin, pos in par_net[: len(g.ouvertes) - int(max_slots)]:
            realized = pnl_realise(pos, base_bps_courant=float(pos.get("base_bps_entree") or 0.0))
            g.journal.record(kind="CLOSE", coin=coin, side="CARRY", notional_usdt=pos["notional_usdt"],
                             realized_net_pnl_usdc=realized, reason=SORTIE_ROTATION, now_ms=int(now_ms))
            g.ouvertes.pop(coin, None)
            evts.append({"coin": coin, "mode": mode, "ouvert": False, "ferme": SORTIE_ROTATION,
                         "pnl_realise_usdt": realized, "funding_add_usdt": 0.0})
    sauver_gestionnaire(root, g)
    for r in g.journal.rows():
        _append_ledger(root, {**r, "ts_ms": int(now_ms), "mode": mode})
    return evts


def diagnostic_churn(root: str | Path = ".", *, now_ms: int | None = None,
                     fenetre_h: float = 24.0) -> dict[str, Any]:
    """A5 — COMBIEN D'ALLERS-RETOURS par coin sur la fenêtre, et lesquels sont anormaux ?

    Le 19/07, le bot a fait 32 ouvertures et 31 fermetures du MÊME coin en 22,3 h. Personne ne
    l'a vu pendant une journée entière : le dashboard n'affichait qu'un PnL qui « ne bougeait
    pas ». Ce diagnostic existe pour que ce symptôme soit LISIBLE, pas déductible.

    Lecture seule sur le ledger append-only (la source de vérité), aucun effet de bord.
    """
    import time as _t
    fin = int(now_ms or _t.time() * 1000)
    debut = fin - int(float(fenetre_h) * 3.6e6)
    par_coin: dict[str, dict[str, Any]] = {}
    try:
        lignes = _ledger_path(root).read_text(encoding="utf-8").splitlines()
    except OSError:
        lignes = []
    for l in lignes:
        try:
            r = json.loads(l)
        except ValueError:
            continue
        if not isinstance(r, dict):
            continue
        ts = r.get("ts_ms")
        if not isinstance(ts, (int, float)) or int(ts) < debut:
            continue
        coin = str(r.get("coin") or "").upper()
        if not coin:
            continue
        e = par_coin.setdefault(coin, {"opens": 0, "closes": 0, "motifs": {}})
        if str(r.get("kind")) == "OPEN":
            e["opens"] += 1
        elif str(r.get("kind")) == "CLOSE":
            e["closes"] += 1
            motif = str(r.get("reason") or "?")
            e["motifs"][motif] = e["motifs"].get(motif, 0) + 1
    suspects = [c for c, e in par_coin.items()
                if churn_excessif(allers_retours_24h=min(e["opens"], e["closes"]))]
    return {"fenetre_h": float(fenetre_h), "par_coin": par_coin, "coins_en_churn": sorted(suspects),
            "churn_detecte": bool(suspects)}


def resume_depuis_ledger(root: str | Path = ".", *, mode: str = MODE_LIVE) -> dict[str, Any]:
    """Le PnL realise TOTAL, lu depuis le ledger append-only (source de verite, pas un compteur)."""
    realized, opens, closes = 0.0, 0, 0
    try:
        lignes = _ledger_path(root).read_text(encoding="utf-8").splitlines()
    except OSError:
        lignes = []
    for l in lignes:
        try:
            r = json.loads(l)
        except ValueError:
            continue
        if r.get("mode") != mode:
            continue
        if r.get("kind") == "OPEN":
            opens += 1
        elif r.get("kind") == "CLOSE":
            closes += 1
            realized += float(r.get("realized_net_pnl_usdc") or 0.0)
    return {"mode": mode, "opens": opens, "closes": closes,
            "realized_net_pnl_usdc": round(realized, 6)}


def etat_carry(root: str | Path = ".", *, mode: str = MODE_LIVE) -> dict[str, Any]:
    """Vue complete pour le dashboard/metrics : PnL realise CUMULE (du ledger) + positions
    ouvertes + funding deja accru (non encore realise). Source de verite = les fichiers, jamais
    un compteur en memoire."""
    r = resume_depuis_ledger(root, mode=mode)
    g = charger_gestionnaire(root, mode=mode)
    r["positions_ouvertes"] = len(g.ouvertes)
    r["coins_ouverts"] = sorted(g.ouvertes)
    r["funding_accru_ouvert_usdt"] = round(
        sum(float(p.get("funding_accrued_usdt") or 0.0) for p in g.ouvertes.values()), 6)
    return r


__all__ = ["POSITIONS_RELPATH", "LEDGER_RELPATH", "SORTIE_HORS_SHORTLIST", "SORTIE_ROTATION",
           "charger_gestionnaire", "sauver_gestionnaire", "tick_sur_disque", "tick_multi_sur_disque",
           "resume_depuis_ledger", "etat_carry"]
