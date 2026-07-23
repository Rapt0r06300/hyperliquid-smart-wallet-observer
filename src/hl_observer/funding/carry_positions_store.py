"""Persistance sur disque de l'ETAPE 2 du carry (positions ouvertes + ledger PnL realise).

Le core `carry_position_lifecycle` est PUR (sans I/O). Ici on ajoute la couche disque pour que les
positions survivent entre les polls du bot :
  * `runtime/data/carry_paper_positions.json`  -> les positions OUVERTES (dict coin->pos), avec le `mode` ;
  * `runtime/data/carry_paper_ledger.jsonl`    -> append-only : chaque OPEN / CLOSE (PnL realise).

Regle dure : un fichier d'etat = UN seul mode. Si le mode demande != le mode du fichier, on repart
VIDE (jamais de melange LIVE/BACKTEST/REPLAY/TEST_FIXTURE). PAPER only : aucun ordre, aucune signature.
"""
from __future__ import annotations
from hl_observer.ops.echec_silencieux import noter as _noter_echec

import json
import os
from pathlib import Path
from typing import Any

from hl_observer.funding.carry_anti_churn import (
    SORTIE_ABSENCE_PROLONGEE, churn_excessif, doit_fermer_pour_absence, filtrer_sortie,
)
from hl_observer.funding.carry_allocation_nette import allouer_marges, diagnostic
from hl_observer.funding.carry_qualite_cross_venue import facteurs_qualite_carry
from hl_observer.funding.carry_marge_dynamique import marge_par_position
from hl_observer.funding.carry_position_lifecycle import (
    MODE_LIVE, MODES_VALIDES, GestionnaireCarry, pnl_realise,
)

SORTIE_HORS_SHORTLIST = "COIN_PLUS_DANS_SHORTLIST"   # conservé : d'anciennes lignes de ledger le portent
SORTIE_ROTATION = "ROTATION_HORS_TOP_SLOTS"   # A7 : plafond de slots -> on garde les meilleurs nets
SORTIE_MODULE_DESACTIVE = "MODULE_CARRY_DESACTIVE"   # 23/07 : fermeture propre a la mise en SHADOW
#: 🔴 23/07 — STRATEGIES RETIREES (decision Flo). Le carry delta-neutre est retire : sa perte historique
#: (−10,73 $) ne doit PLUS apparaitre dans le LIVRE LIVE (grand chiffre + courbe). Elle reste INTACTE dans
#: le ledger append-only (audit/rapport), simplement EXCLUE des vues live. L'arbitrage (meme ledger) reste.
#: Les vieilles lignes SANS `strategie` datent du carry -> traitees comme "carry" (retirees) elles aussi.
STRATEGIES_RETIREES = frozenset({"carry"})

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
    # PnL par session (20/07) : chaque ligne porte l'identite de SA session -> le dashboard
    # peut repartir a zero au redemarrage sans JAMAIS toucher aux lignes precedentes.
    if "session_id" not in row:
        try:
            from hl_observer.runtime.session_identity import session_courante
            row = {**row, "session_id": session_courante(root)}
        except Exception:  # noqa: BLE001 — une identite illisible ne bloque pas le ledger
            row = {**row, "session_id": ""}
    # 🔴 23/07 — ÉTIQUETAGE À LA SOURCE (casseur de confiance n°1). Ce store n'écrit QUE du carry ;
    # sans ce champ, 60 % des closes du ledger sortaient en `?` -> attribution du PnL PAR MOTEUR
    # fausse et risque de mélange carry/arb/cross-venue dans le même fichier. On tague ici, une fois.
    if not row.get("strategie"):
        row = {**row, "strategie": "carry"}
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


def fermer_tout_et_desactiver(root: str | Path, *, bases_courantes: dict[str, float] | None = None,
                              now_ms: int, mode: str = MODE_LIVE) -> dict[str, Any]:
    """Ferme TOUTES les positions carry ouvertes aux prix EXÉCUTABLES courants (base par coin depuis
    `bases_courantes`, sinon base d'entrée = conservateur, aucun premium inventé), COÛTS COMPLETS via
    `pnl_realise` (frais spot+perp, spread, slippage — le MÊME chemin comptable que les closes normaux,
    donc le ledger reste cohérent), écrit chaque CLOSE au ledger (historique CONSERVÉ) et vide le
    fichier de positions. Idempotent : 0 ouverte -> no-op. Sert à passer le carry historique en
    DISABLED/SHADOW sans laisser de position fantôme (décision Flo 23/07 : ce carry est DOMINÉ par HLP).
    PAPER only : aucun ordre, aucune signature, real_execution=False."""
    g = charger_gestionnaire(root, mode=mode)
    fermees: list[dict[str, Any]] = []
    for coin in list(g.ouvertes):
        pos = g.ouvertes[coin]
        b = (bases_courantes or {}).get(coin)
        base_bps = float(b) if isinstance(b, (int, float)) else float(pos.get("base_bps_entree") or 0.0)
        realized = pnl_realise(pos, base_bps_courant=base_bps)
        g.journal.record(kind="CLOSE", coin=coin, side="CARRY", notional_usdt=pos["notional_usdt"],
                         realized_net_pnl_usdc=realized, reason=SORTIE_MODULE_DESACTIVE, now_ms=int(now_ms))
        g.ouvertes.pop(coin, None)
        fermees.append({"coin": coin, "pnl_realise_usdt": round(float(realized), 4),
                        "base_executable_bps": round(base_bps, 3), "notional_usdt": pos.get("notional_usdt")})
    sauver_gestionnaire(root, g)
    for r in g.journal.rows():
        _append_ledger(root, {**r, "ts_ms": int(now_ms), "mode": mode, "raison_module": "DESACTIVE_SHADOW"})
    return {"n_fermees": len(fermees), "fermees": fermees, "real_execution": False,
            "pnl_realise_total_usdt": round(sum(f["pnl_realise_usdt"] for f in fermees), 4)}


ALLOCATION_RELPATH = Path("runtime") / "data" / "carry_allocation.json"


def _publier_allocation(root: str | Path, nets: dict, marges: dict, *, now_ms: int,
                        mode: str) -> None:
    """Ecrit le diagnostic d'allocation (atomique : tmp + replace). Best-effort : une panne
    d'ecriture ne doit JAMAIS empecher le carry de tourner."""
    try:
        d = diagnostic(nets, marges)
        d.update({"ts_ms": int(now_ms), "mode": mode,
                  "marges_usd": {c: round(float(v), 2) for c, v in (marges or {}).items()},
                  "rendements_bps_j": {c: v for c, v in (nets or {}).items()},
                  "real_execution": False})
        chemin = Path(root) / ALLOCATION_RELPATH
        chemin.parent.mkdir(parents=True, exist_ok=True)
        tmp = chemin.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(d, ensure_ascii=False, indent=1), encoding="utf-8")
        os.replace(tmp, chemin)
    except Exception:  # noqa: BLE001
        _noter_echec("hl_observer/funding/carry_positions_store.py:publier_allocation")


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
    # 🔴 21/07 — ALLOCATION PAR RENDEMENT NET. La marge etait divisee en parts EGALES, puis
    # modulee par un `facteur_taille` bati sur le z-score du funding : correlation mesuree
    # entre ce facteur et le rendement net = -0,596, autrement dit on mettait le PLUS de
    # capital sur les MOINS rentables (BTC, le meilleur, avait 25 $ ; STABLE, parmi les pires,
    # 126 $). On repartit desormais le meme capital ∝ gain_net_24h_bps**3 — un nombre qu'on
    # calculait DEJA et qu'on jetait. Aucun levier ne bouge : aucune distance de liquidation
    # ne bouge. Donnee absente -> marge par defaut (on ne degrade jamais l'existant).
    nets = {coin: (m.get("decision") or {}).get("gain_net_24h_bps") for coin, m in mesures.items()}
    # 🟠 23/07 — TILT QUALITÉ CROSS-VENUE (« gagner de l'argent avec le cross-venue », capturable).
    # On incline le capital du carry vers les coins dont le funding HL est PERSISTAMMENT au-dessus de
    # Binance (premium structurel, plus robuste), BORNÉ ±10 % : jamais décisif seul, jamais un levier
    # ne bouge, un net ≤ 0 reste à ZÉRO. Source absente/illisible -> {} -> allocation INCHANGÉE. Ne
    # peut PAS casser le poll (try/except) : le carry doit tourner même sans cette source.
    try:
        qualite = facteurs_qualite_carry(root)
    except Exception:
        qualite = {}
    marges = allouer_marges(nets, capital_usd=capital_usd, n_positions_visees=n_visees,
                            marge_defaut_usd=marge, qualite_par_coin=qualite)
    _publier_allocation(root, nets, marges, now_ms=now_ms, mode=mode)
    for coin, m in mesures.items():
        marge_coin = marges.get(coin)
        if not isinstance(marge_coin, (int, float)) or marge_coin <= 0:
            # rendement absent ou <= 0 : l'ouverture est de toute facon refusee en amont ;
            # une position DEJA ouverte garde simplement sa marge (aucun renfort, aucune vente).
            marge_coin = float((g.ouvertes.get(coin) or {}).get("marge_usdt") or marge)
        evts.append(g.tick(m["decision"], m["inputs"], now_ms=now_ms,
                           funding_bps_h_courant=m.get("funding"), prix_courant=m.get("prix"),
                           base_bps_courant=m.get("base"), marge_usd=float(marge_coin)))
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


def resume_depuis_ledger(root: str | Path = ".", *, mode: str = MODE_LIVE,
                         session_id: str | None = None,
                         exclure_strategies: frozenset[str] = frozenset()) -> dict[str, Any]:
    """Le PnL realise TOTAL, lu depuis le ledger append-only (source de verite, pas un compteur).

    PnL PAR SESSION (demande de Flo, 20/07) : chaque ligne du ledger porte desormais son
    `session_id`. Si `session_id` est fourni, le resume contient AUSSI le realise de CETTE
    session (`realized_net_pnl_usdc_session`, `closes_session`). Le compteur de session repart
    donc a ZERO a chaque redemarrage — SANS rien supprimer : l'historique complet reste dans
    `realized_net_pnl_usdc` et dans le fichier, ligne par ligne. Les vieilles lignes sans
    etiquette n'appartiennent a AUCUNE session courante (elles datent d'avant).
    """
    realized, opens, closes = 0.0, 0, 0
    realized_sess, closes_sess = 0.0, 0
    renforts, notional_renforce = 0, 0.0
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
        if (r.get("strategie") or "carry") in exclure_strategies:
            continue                                     # stratégie RETIRÉE : hors du livre live
        if r.get("kind") == "OPEN":
            opens += 1
        elif r.get("kind") == "RENFORT":
            # un renfort ne REALISE rien (il ajoute du notional a une position vivante) : il
            # n'entre donc JAMAIS dans le PnL. On le compte pour qu'il soit VISIBLE — une
            # action invisible finit toujours par etre confondue avec un bug.
            renforts += 1
            notional_renforce += float(r.get("notional_usdt") or 0.0)
        elif r.get("kind") == "CLOSE":
            closes += 1
            pnl = float(r.get("realized_net_pnl_usdc") or 0.0)
            realized += pnl
            if session_id and str(r.get("session_id") or "") == session_id:
                closes_sess += 1
                realized_sess += pnl
    out = {"mode": mode, "opens": opens, "closes": closes,
           "renforts": renforts, "notional_renforce_usdt": round(notional_renforce, 4),
           "realized_net_pnl_usdc": round(realized, 6)}
    if session_id is not None:
        out["session_id"] = session_id
        out["closes_session"] = closes_sess
        out["realized_net_pnl_usdc_session"] = round(realized_sess, 6)
    return out


def etat_carry(root: str | Path = ".", *, mode: str = MODE_LIVE) -> dict[str, Any]:
    """Vue complete pour le dashboard/metrics : PnL realise CUMULE (du ledger) + positions
    ouvertes + funding deja accru (non encore realise). Source de verite = les fichiers, jamais
    un compteur en memoire. Contient AUSSI le realise de la SESSION COURANTE
    (`realized_net_pnl_usdc_session`) : c'est LUI que le dashboard affiche en grand — il
    repart a zero a chaque redemarrage, l'historique reste dans `realized_net_pnl_usdc`."""
    try:
        from hl_observer.runtime.session_identity import session_courante
        sid = session_courante(root)
    except Exception:  # noqa: BLE001
        sid = ""
    r = resume_depuis_ledger(root, mode=mode, session_id=sid)
    # 🔴 23/07 — LIVRE LIVE (hors stratégies RETIRÉES). Le carry delta-neutre est retiré (décision Flo) :
    # sa perte historique reste dans `realized_net_pnl_usdc` (audit/ledger, jamais supprimée) mais le
    # GRAND chiffre du dashboard affiche le livre LIVE = ledger MOINS les retirées. L'arbitrage reste.
    r["realized_net_pnl_usdc_live"] = resume_depuis_ledger(
        root, mode=mode, exclure_strategies=STRATEGIES_RETIREES)["realized_net_pnl_usdc"]
    g = charger_gestionnaire(root, mode=mode)
    r["positions_ouvertes"] = len(g.ouvertes)
    r["coins_ouverts"] = sorted(g.ouvertes)
    r["funding_accru_ouvert_usdt"] = round(
        sum(float(p.get("funding_accrued_usdt") or 0.0) for p in g.ouvertes.values()), 6)
    # capital REELLEMENT deploye — la seule mesure qui dit si le renfort sert a quelque chose.
    r["notional_ouvert_usdt"] = round(
        sum(float(p.get("notional_usdt") or 0.0) for p in g.ouvertes.values()), 4)
    r["marge_ouverte_usdt"] = round(
        sum(float(p.get("marge_usdt") or 0.0) for p in g.ouvertes.values()), 4)
    r["positions_renforcees"] = sum(1 for p in g.ouvertes.values()
                                    if int(p.get("renforts") or 0) > 0)
    # 🔴 P0 (21/07) — FUNDING REGLE vs FUNDING ESTIME. `funding_accrued_usdt` est un PRORATA
    # LINEAIRE, alors qu'Hyperliquid regle au SOMMET DE CHAQUE HEURE. Une position ouverte
    # depuis 20 min se voyait crediter 1/3 d'heure de funding : c'est une ESTIMATION, pas un
    # encaissement. Le README l'appelait « l'encaisse, stable » — doublement faux (c'est
    # l'interpolation lineaire d'une fonction en escalier). On decoupe : seul le REGLE entre
    # dans le PnL stable ; l'estimation s'affiche a cote, comme le latent de base.
    # La somme des deux vaut EXACTEMENT l'accru : aucune valeur creee ni detruite.
    try:
        import time as _t
        from hl_observer.paper_trading.funding_settlement import agreger, pnl_stable
        d = agreger(g.ouvertes, now_ms=int(_t.time() * 1000))
        r["net_funding_settled"] = d["net_funding_settled"]
        r["funding_accrual_estimate"] = d["funding_accrual_estimate"]
        r["stable_net_pnl"] = pnl_stable(r.get("realized_net_pnl_usdc") or 0.0,
                                         d["net_funding_settled"])
        if r.get("realized_net_pnl_usdc_session") is not None:
            r["stable_net_pnl_session"] = pnl_stable(r["realized_net_pnl_usdc_session"],
                                                     d["net_funding_settled"])
    except Exception:  # noqa: BLE001 — un decoupage rate ne fait pas disparaitre l'etat
        _noter_echec("hl_observer/funding/carry_positions_store.py:etat_carry_session")
    return r


__all__ = ["POSITIONS_RELPATH", "LEDGER_RELPATH", "SORTIE_HORS_SHORTLIST", "SORTIE_ROTATION",
           "charger_gestionnaire", "sauver_gestionnaire", "tick_sur_disque", "tick_multi_sur_disque",
           "resume_depuis_ledger", "etat_carry"]
