"""RUNNER EXPERIMENTAL_PAPER — un tick complet : collecte les signaux des 3 moteurs, ADMET (fraîcheur +
exécutable + edge > 0, jamais prouve_oos), OUVRE, puis GÈRE et SORT les positions ouvertes au bid/ask.

Écrit un statut (`experimental_paper_status.json`) : positions par moteur, 1er signal, refus par motif.
Aucun ordre réel, aucune signature. Rejouable à chaque cycle du lanceur.
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

from hl_observer.experimental import moteur_paper as MP
from hl_observer.experimental.signaux import COLLECTEURS
from hl_observer.alerts.local_alerts import LocalAlerts
from hl_observer.market_data.live_l2_service import LiveL2Service
from hl_observer.signals.all_signals_zero_alert import evaluer_signaux_tous_a_zero

STATUS_RELPATH = MP.STATUS_RELPATH  # versionné (v2) : la v1 reste en quarantaine
LEAD_LAG_EXPERIMENTAL_LANE = "LEAD_LAG_EXP_CALIBRATION"


def _marks_cross_venue(root: Path) -> dict[str, dict]:
    """{coin: {hl_px, d_bps_h, base_bps, cout_ar_bps, ts}} pour marquer/sortir le carry cross-venue."""
    try:
        from hl_observer.funding.cross_venue_carry_judge import charger_series
        from hl_observer.funding.cross_venue_carry_paper import couts_carnet
    except Exception:  # noqa: BLE001
        return {}
    series = charger_series(root)
    couts = couts_carnet(root)
    out: dict[str, dict] = {}
    for c, s in series.items():
        if not s:
            continue
        ts, hl_px, bin_px, hl_f, bin_f = s[-1]
        out[c.upper()] = {
            "hl_px": hl_px,
            "d_bps_h": hl_f - bin_f,
            "base_bps": 1e4 * (hl_px - bin_px) / bin_px if bin_px else 0.0,
            "cout_ar_bps": couts.get(c.upper()),
            "ts": ts,
        }
    return out


def _marks_hl_mid(root: Path, coins: set[str], *, max_lignes: int = 40000) -> dict[str, float]:
    """{coin: mid HL} depuis la tape BBO — pour marquer/sortir les positions directionnelles."""
    p = root / Path("runtime") / "data" / "bbo_tape.jsonl"
    if not p.exists():
        return {}
    out: dict[str, float] = {}
    for l in p.read_text(encoding="utf-8", errors="ignore").splitlines()[-max_lignes:]:
        try:
            d = json.loads(l)
        except ValueError:
            continue
        c = str(d.get("coin") or "").upper()
        if c in coins and d.get("venue") == "HL" and d.get("bid") and d.get("ask"):
            out[c] = (float(d["bid"]) + float(d["ask"])) / 2.0
    return out


def _marks_hl_bidask(root: Path, coins: set[str], *, max_lignes: int = 40000) -> dict[str, dict]:
    """{coin: {bid, ask, ts_ms}} HL depuis la tape BBO — pour FERMER au prix EXÉCUTABLE (LOT14 #4 : long au
    bid, short à l'ask), pas au mid. Garde bid/ask + horodatage exchange pour la fraîcheur."""
    p = root / Path("runtime") / "data" / "bbo_tape.jsonl"
    if not p.exists():
        return {}
    out: dict[str, dict] = {}
    for l in p.read_text(encoding="utf-8", errors="ignore").splitlines()[-max_lignes:]:
        try:
            d = json.loads(l)
        except ValueError:
            continue
        c = str(d.get("coin") or "").upper()
        if c in coins and d.get("venue") == "HL" and d.get("bid") and d.get("ask"):
            out[c] = {
                "bid": float(d["bid"]),
                "ask": float(d["ask"]),
                "ts_ms": d.get("ts_wall_ms") or d.get("ts_ex"),
            }
    return out


BASIS_ADVERSE_BPS = 15.0  # base qui dérive contre nous de > ça -> sortie


def _raison_sortie_carry(pos: dict, m: dict, car: dict | None, *, now_ms: float, age_h: float) -> str | None:
    """Les 6 sorties auto du carry : funding flip, quote périmée, liquidité insuffisante, basis adverse,
    edge net restant disparu, durée max. Renvoie le motif OU None (on garde)."""
    from hl_observer.experimental.carry_deux_jambes import CARNET_AGE_MAX_S

    d_now, d_ent = float(m["d_bps_h"]), float(pos.get("d_bps_h") or 0.0)
    if (d_now >= 0) != (d_ent >= 0):
        return "FUNDING_FLIP"
    if car and (now_ms / 1000.0 - float(car.get("collecte_ts") or 0.0)) > CARNET_AGE_MAX_S:
        return "QUOTE_PERIMEE"
    if car and float(car.get("taille_min_usd") or 0.0) < float(pos.get("notional_usd") or 0.0):
        return "LIQUIDITE_INSUFFISANTE"
    base_ent = float(pos.get("base_entree_bps") or 0.0)
    base_cur = float(m.get("base_bps") if m.get("base_bps") is not None else base_ent)
    if int(pos.get("sens") or 1) * (base_cur - base_ent) < -BASIS_ADVERSE_BPS:
        return "BASIS_ADVERSE"
    if age_h >= float(pos.get("hold_h") or 168.0):  # durée max AVANT edge (sinon reste_h=0 masque)
        return "HOLD_ATTEINT"
    reste_h = max(0.0, float(pos.get("hold_h") or 168.0) - age_h)
    cout_ar = float((pos.get("meta") or {}).get("cout_ar_bps") or 0.0)
    if abs(d_now) * reste_h <= cout_ar:
        return "EDGE_DISPARU"
    return None


def _gap_courant_bps(car: dict, sens: int) -> float:
    """Écart EXÉCUTABLE courant dans le sens d'entrée (bps). Converge vers 0 (ou négatif) quand les
    deux venues se rejoignent -> c'est le signal de déboucle rentable."""
    hl_bid, hl_ask = float(car["hl_bid"]), float(car["hl_ask"])
    bin_bid, bin_ask = float(car["bin_bid"]), float(car["bin_ask"])
    hl_mid, bin_mid = (hl_bid + hl_ask) / 2, (bin_bid + bin_ask) / 2
    if sens >= 0:  # long HL / short BIN
        return (bin_bid - hl_ask) / hl_mid * 1e4 if hl_mid else 0.0
    return (hl_bid - bin_ask) / bin_mid * 1e4 if bin_mid else 0.0


def _raison_sortie_dislocation(pos: dict, car: dict | None, *, now_ms: float) -> tuple[str | None, float]:
    """Sorties dislocation : convergence capturée, écart aggravé (stop), liquidité, quote périmée, durée
    max. Renvoie (motif|None, gap_courant_bps)."""
    from hl_observer.experimental.carry_deux_jambes import CARNET_AGE_MAX_S

    if not car:
        return None, 0.0  # pas de carnet -> on garde (pas de sortie aveugle)
    gap_ent = float((pos.get("meta") or {}).get("gap_entree_bps") or 0.0)
    gap_cur = _gap_courant_bps(car, int(pos.get("sens") or 1))
    age_min = (now_ms - float(pos.get("ts_ouverture_ms") or now_ms)) / 60000.0
    if (now_ms / 1000.0 - float(car.get("collecte_ts") or 0.0)) > CARNET_AGE_MAX_S:
        return "QUOTE_PERIMEE", gap_cur
    if float(car.get("taille_min_usd") or 0.0) < float(pos.get("notional_usd") or 0.0):
        return "LIQUIDITE_INSUFFISANTE", gap_cur
    if gap_cur <= gap_ent * 0.3:  # écart quasi refermé -> on capture
        return "CONVERGENCE_CAPTUREE", gap_cur
    if gap_cur > gap_ent * 1.5:  # écart s'aggrave contre nous -> stop
        return "ECART_AGGRAVE", gap_cur
    if age_min >= float(pos.get("hold_h") or 0.5) * 60.0:  # durée max (court terme)
        return "DUREE_MAX", gap_cur
    return None, gap_cur


SNAPSHOT_FRAICHEUR_MAX_MS = 6 * 3.6e6  # un snapshot de vault > 6 h est trop vieux pour conclure (P3)
BIDASK_FRAICHEUR_MAX_MS = 5_000.0  # un bid/ask HL > 5 s n'est plus « exécutable » (P8)


def _etat_leader(pos: dict, root: Path, *, now_ms: float) -> dict:
    """P1/P2/P3 — état du LEADER depuis le DERNIER snapshot du BON vault. Renvoie un dict :
      action ∈ {REDUCE, ADD, CLOSE, FLIP_LONG_SHORT, FLIP_SHORT_LONG, AUCUN, INVALIDE}, motif,
      entry_szi/current_szi (SIGNÉS), snapshot_ts, snapshot_id.
    Gardes : snapshot_complet_ok (complet + ts + postérieur à l'entrée + frais), déduplication (snapshot
    déjà consommé -> AUCUN), coin absent interprété comme flat SEULEMENT si le snapshot est complet."""
    import hashlib
    import json as _j
    from hl_observer.experimental import execution_paper as EP

    meta = pos.get("meta") or {}
    vault, coin = meta.get("vault"), str(pos.get("coin") or "").upper()
    entry_szi = float(pos.get("entry_leader_szi") or meta.get("szi_apres") or 0.0)
    out = {
        "action": "AUCUN",
        "motif": None,
        "entry_szi": entry_szi,
        "current_szi": entry_szi,
        "snapshot_ts": None,
        "snapshot_id": None,
    }
    if not vault or not coin or abs(entry_szi) <= 0:
        out["motif"] = "PAS_DE_REFERENCE_LEADER"
        return out
    try:
        lignes = (
            (root / "runtime" / "data" / "vault_snapshots.jsonl")
            .read_text(encoding="utf-8", errors="ignore")
            .splitlines()
        )
    except OSError:
        out["motif"] = "PAS_DE_SNAPSHOTS"
        return out
    dernier, brut = None, ""
    for l in reversed(lignes[-8000:]):
        try:
            d = _j.loads(l)
        except ValueError:
            continue
        if d.get("vault") == vault:
            dernier, brut = d, l
            break
    if not dernier:
        out["motif"] = "AUCUN_SNAPSHOT_VAULT"
        return out
    ts = dernier.get("ts_ms")
    snap_id = dernier.get("snapshot_id") or hashlib.sha1(brut.encode("utf-8", "ignore")).hexdigest()[:12]
    out["snapshot_ts"], out["snapshot_id"] = ts, snap_id
    # P3 : un snapshot n'est exploitable que COMPLET (positions présentes + nav>0), horodaté, POSTÉRIEUR à
    # l'entrée et FRAIS. Sinon on NE conclut RIEN (surtout pas un close sur coin « absent »).
    complet = ("positions" in dernier) and (float(dernier.get("nav_usd") or 0.0) > 0)
    ok, motif = EP.snapshot_complet_ok(
        {"complet": complet, "ts_ms": ts},
        coin,
        ts_entree_ms=float(pos.get("ts_ouverture_ms") or 0.0),
        now_ms=now_ms,
        fraicheur_max_ms=SNAPSHOT_FRAICHEUR_MAX_MS,
    )
    if not ok:
        out["motif"] = motif
        return out
    # P1 : déduplication — un snapshot déjà consommé ne redéclenche jamais d'action.
    if pos.get("last_vault_snapshot_id") == snap_id:
        out["motif"] = "SNAPSHOT_DEJA_CONSOMME"
        return out
    cur = 0.0  # coin absent d'un snapshot COMPLET = réellement flat
    for p in dernier.get("positions") or []:
        if str(p.get("coin") or "").upper() == coin:
            cur = float(p.get("szi") or 0.0)
            break
    out["current_szi"] = cur
    last_applied = float(
        pos.get("last_leader_szi_applied") if pos.get("last_leader_szi_applied") is not None else entry_szi
    )
    out["action"] = EP.classifier_changement_leader(
        entry_szi=entry_szi, current_szi=cur, last_applied_szi=last_applied
    )
    return out


def _jambes_sortie_dislocation(pos: dict, car: dict | None) -> list[dict] | None:
    """P7 — construit les DEUX jambes de SORTIE d'une dislocation : entrée = prix exécutés stockés dans
    meta.jambes ; sortie = bid/ask COURANTS des deux venues (on RACHÈTE ce qu'on a vendu, on VEND ce qu'on a
    acheté). Delta-neutre : sens>0 = long HL / short BIN. Rend [jambe_hl, jambe_bin] ou None si illisible."""
    meta = pos.get("meta") or {}
    j = meta.get("jambes") or {}
    if not (j.get("hl") and j.get("bin")) or not car:
        return None
    try:
        hl_bid, hl_ask = float(car["hl_bid"]), float(car["hl_ask"])
        bin_bid, bin_ask = float(car["bin_bid"]), float(car["bin_ask"])
    except (KeyError, TypeError, ValueError):
        return None
    sens = int(pos.get("sens") or 1)
    notional = float(pos.get("notional_usd") or 0.0)
    hl, bn = j["hl"], j["bin"]
    if sens > 0:  # long HL (sortie: vend au hl_bid) / short BIN (rachète au bin_ask)
        hl_leg = {"venue": "HL", "side": 1, "entry_px": float(hl["prix_exec"]), "exit_px": hl_bid}
        bin_leg = {"venue": "BIN", "side": -1, "entry_px": float(bn["prix_exec"]), "exit_px": bin_ask}
    else:  # short HL (rachète au hl_ask) / long BIN (vend au bin_bid)
        hl_leg = {"venue": "HL", "side": -1, "entry_px": float(hl["prix_exec"]), "exit_px": hl_ask}
        bin_leg = {"venue": "BIN", "side": 1, "entry_px": float(bn["prix_exec"]), "exit_px": bin_bid}
    for leg, src in ((hl_leg, hl), (bin_leg, bn)):
        leg["size_usd"] = notional
        leg["fee_bps"] = float(src.get("frais_bps") or 0.0)
        leg["slippage_bps"] = float(src.get("slippage_bps") or 0.0)
    return [hl_leg, bin_leg]


def _gerer_sorties(store: dict, root: Path, *, now_ms: float) -> list[dict]:
    """Sort les positions dont une condition de sortie est atteinte, au prix exécutable courant.
    Les sorties CROSS-VENUE sont GELÉES pendant l'audit (HYPERSMART_EXPERIMENTAL_CROSS_VENUE_GELE=1) :
    on garde la cohorte intacte. Les sorties directionnelles (lead-lag) restent actives."""
    import os

    fermetures: list[dict] = []
    cv = _marks_cross_venue(root)
    from hl_observer.experimental.carry_deux_jambes import carnet_par_coin

    carnet = carnet_par_coin(root)
    gele_cv = os.environ.get("HYPERSMART_EXPERIMENTAL_CROSS_VENUE_GELE", "0") == "1"
    dir_coins = {p["coin"] for p in store["ouvertes"].values() if p.get("type_pnl") == "directional"}
    mids = _marks_hl_mid(root, dir_coins) if dir_coins else {}
    bidask = _marks_hl_bidask(root, dir_coins) if dir_coins else {}  # LOT14 #4 : prix EXÉCUTABLE de sortie
    from hl_observer.experimental import invariants as INV

    for pos in list(store["ouvertes"].values()):
        age_h = (now_ms - float(pos.get("ts_ouverture_ms") or now_ms)) / 3.6e6
        if pos.get("type_pnl") == "dislocation":  # cross-venue COURT TERME : capture/stop rapide
            from hl_observer.experimental import execution_paper as EP

            car = carnet.get(pos["coin"])
            if car:
                pos["ts_derniere_donnee_ms"] = now_ms  # trace de fraîcheur pour la politique data-missing
            gap_ent = float(
                (pos.get("meta") or {}).get("gap_entree_bps") or pos.get("base_entree_bps") or 0.0
            )
            raison, gap_cur = _raison_sortie_dislocation(pos, car, now_ms=now_ms)
            # 🔴 P6 — DONNÉE MANQUANTE : sans carnet frais, on ne GARDE PAS indéfiniment. Grace courte puis
            # DATA_MISSING_TIMEOUT. Le gap courant CONSERVATEUR = gap ENTRÉE (brut NUL) — JAMAIS gap_cur=0 qui
            # simulerait une convergence complète (gain fabriqué). Coûts de stress en plus -> PnL brut <= 0.
            if not raison and not car:
                dm = EP.politique_data_missing(pos, now_ms=now_ms)
                if dm["action"] == "SORTIE":
                    cout_dm = float(pos.get("frais_bps") or 0.0) + float(dm["slippage_stress_bps"])
                    fermetures.append(
                        MP.sortir(
                            pos,
                            store,
                            root,
                            prix_sortie=dm["mark_conservateur"],
                            cout_sortie_bps=cout_dm,
                            base_courant_bps=gap_ent,
                            raison="DATA_MISSING_TIMEOUT",
                            now_ms=now_ms,
                        )
                    )
                    continue
            if raison:
                # 🔴 P7 — fermer comme DEUX JAMBES au bid/ask des DEUX venues (realized = somme EXACTE des
                # jambes), quand le carnet est lisible. Repli convergence de base seulement si carnet illisible.
                jambes = _jambes_sortie_dislocation(pos, car)
                if jambes:
                    fermetures.append(
                        MP.sortir_deux_jambes(pos, store, root, jambes=jambes, raison=raison, now_ms=now_ms)
                    )
                else:
                    fermetures.append(
                        MP.sortir(
                            pos,
                            store,
                            root,
                            prix_sortie=pos.get("prix_entree"),
                            cout_sortie_bps=float(pos.get("spread_bps") or 0.0)
                            + float(pos.get("frais_bps") or 0.0),
                            base_courant_bps=gap_cur,
                            raison=raison,
                            now_ms=now_ms,
                        )
                    )
        elif pos.get("type_pnl") == "funding_carry":  # LEGACY (v1 quarantaine) — plus émis en v2
            if gele_cv:
                continue
            m = cv.get(pos["coin"])
            if not m or m.get("hl_px") is None:
                continue
            raison = _raison_sortie_carry(pos, m, carnet.get(pos["coin"]), now_ms=now_ms, age_h=age_h)
            if raison:
                cout_sortie = (m.get("cout_ar_bps") or 0.0) / 2.0 + 3.3
                fermetures.append(
                    MP.sortir(
                        pos,
                        store,
                        root,
                        prix_sortie=m["hl_px"],
                        cout_sortie_bps=cout_sortie,
                        base_courant_bps=m["base_bps"],
                        raison=raison,
                        now_ms=now_ms,
                    )
                )
        else:  # directionnel (lead_lag / copy_vault)
            from hl_observer.experimental import execution_paper as EP

            et = _etat_leader(pos, root, now_ms=now_ms) if pos["moteur"] == "copy_vault" else None
            action_leader = et["action"] if et else "AUCUN"
            horizon_ms = float((pos.get("meta") or {}).get("horizon_ms") or 1000.0)
            mur_ms = max(horizon_ms, 2000.0) if pos["moteur"] == "lead_lag" else 24 * 3.6e6
            horizon_atteint = (now_ms - float(pos.get("ts_ouverture_ms") or now_ms)) >= mur_ms
            reduce_partiel = action_leader == "REDUCE" and not horizon_atteint
            ferme_complet = horizon_atteint or action_leader in (
                "CLOSE",
                "FLIP_LONG_SHORT",
                "FLIP_SHORT_LONG",
            )
            if not (reduce_partiel or ferme_complet):
                if et and et.get("snapshot_id"):  # ADD / AUCUN : rien à fermer -> on DIGÈRE le snapshot
                    pos["last_vault_snapshot_id"] = et["snapshot_id"]
                    pos["last_leader_szi_applied"] = et["current_szi"]
                continue
            # LOT14 #4/P8 — prix de sortie EXÉCUTABLE et FRAIS (long au bid, short à l'ask), coût SANS double-
            # spread. Un bid/ask périmé (> BIDASK_FRAICHEUR_MAX_MS) n'est PAS exécutable -> repli conservateur.
            ba = bidask.get(pos["coin"])
            frais_ok = bool(ba) and (
                ba.get("ts_ms") is None or (now_ms - float(ba["ts_ms"])) <= BIDASK_FRAICHEUR_MAX_MS
            )
            px_exec = (
                INV.prix_sortie_executable(
                    int(pos.get("sens") or 1), bid=(ba or {}).get("bid"), ask=(ba or {}).get("ask")
                )
                if (ba and frais_ok)
                else None
            )
            if px_exec is not None:
                prix_sortie = px_exec
                cout_sortie = INV.cout_sortie_sans_double_spread(
                    frais_bps=float(pos.get("frais_bps") or 0.0),
                    slippage_bps=float(pos.get("slippage_bps") or 0.0),
                )
            else:  # carnet illisible/périmé -> mid + spread explicite
                prix_sortie = mids.get(pos["coin"]) or pos.get("prix_entree")
                cout_sortie = float(pos.get("spread_bps") or 0.0) + float(pos.get("frais_bps") or 0.0)
            if reduce_partiel:  # P1+P4 : cible depuis le NOTIONNEL INITIAL, idempotent
                rp = EP.reduire_vers_cible(
                    pos,
                    entry_leader_szi=et["entry_szi"],
                    current_leader_szi=et["current_szi"],
                    prix_sortie=float(prix_sortie),
                    cout_sortie_bps=cout_sortie,
                    cout_entree_bps=float(pos.get("cout_entree_bps") or 0.0),
                )
                if rp.get("action") == "REDUCE":
                    pos["ts_derniere_donnee_ms"] = now_ms
                    fermetures.append(
                        MP.reduire(
                            pos,
                            store,
                            root,
                            notional_ferme_usd=rp["notional_ferme_usd"],
                            notional_residuel_usd=rp["notional_residuel_usd"],
                            realized_usd=rp["realized_usd"],
                            prix_sortie=prix_sortie,
                            cout_sortie_bps=cout_sortie,
                            raison="LEADER_A_REDUIT",
                            now_ms=now_ms,
                            entry_cost_allocated_usd=rp["entry_cost_allocated_usd"],
                            exit_cost_usd=rp["exit_cost_usd"],
                            leader_szi_applied=et["current_szi"],
                            snapshot_ts=et["snapshot_ts"],
                            snapshot_id=et["snapshot_id"],
                        )
                    )
                    continue  # position TOUJOURS ouverte (résidu)
                if rp.get("action") == "CLOSE_INTEGRAL":
                    ferme_complet = True
                else:  # AUCUNE (même snapshot / pas de réduction nette)
                    pos["last_vault_snapshot_id"] = et["snapshot_id"]
                    pos["last_leader_szi_applied"] = et["current_szi"]
                    continue
            if ferme_complet:
                raison = "HORIZON_ATTEINT" if horizon_atteint else "LEADER_%s" % action_leader
                fermetures.append(
                    MP.sortir(
                        pos,
                        store,
                        root,
                        prix_sortie=prix_sortie,
                        cout_sortie_bps=cout_sortie,
                        raison=raison,
                        now_ms=now_ms,
                    )
                )
    return fermetures


def tick(
    root: str | Path = ".",
    *,
    now_ms: float | None = None,
    moteurs: tuple[str, ...] | None = None,
    lecteur_l2=None,
) -> dict[str, Any]:
    """Un cycle complet. Renvoie {ouvertures, fermetures, refus, premier_signal, resume}."""
    root = Path(root)
    now = float(now_ms if now_ms is not None else time.time() * 1000)
    store = MP.charger_store(root)
    fermetures = _gerer_sorties(store, root, now_ms=now)  # d'abord les sorties (libère des slots)
    ouvertures: list[dict] = []
    refus: list[dict] = []
    premier_signal: dict | None = None
    candidats: list[MP.Signal] = []
    sizing_outcomes: list[dict] = []
    latences_decision_ms: list[float] = []
    funnel = {k: 0 for k in (
        "events", "fresh", "candidates", "l2", "liquidity", "edge", "consensus",
        "PaperIntent", "PaperFill", "POSITION",
    )}
    l2_reader = lecteur_l2 or LiveL2Service(root).as_legacy_reader()
    for m in moteurs or MP.MOTEURS:
        adaptateur = COLLECTEURS.get(m)
        if not adaptateur:
            continue
        try:
            if m == "copy_vault":
                from hl_observer.experimental.exploratoire import charger_table_prelim

                sigs, refs = adaptateur(
                    root,
                    now_ms=now,
                    lecteur_l2=l2_reader,
                    edge_par_coin=charger_table_prelim(root),
                    experimental_entry_from_add=True,
                )
            elif m == "lead_lag":
                sigs, refs = adaptateur(root, now_ms=now, experimental_calibration=True)
            else:
                sigs, refs = adaptateur(root, now_ms=now)
        except Exception as exc:  # noqa: BLE001 — un moteur qui échoue n'arrête pas les autres
            refus.append({"moteur": m, "motif": "ADAPTATEUR_ERREUR", "detail": str(exc)[:120]})
            continue
        refus.extend(refs)
        funnel["events"] += len(sigs) + len(refs)
        funnel["fresh"] += sum(1 for s in sigs if 0 <= now - float(s.ts_signal_ms) <= MP.AGE_MAX_SIGNAL_MS)
        funnel["candidates"] += len(sigs)
        funnel["l2"] += sum(1 for s in sigs if s.prix_entree > 0 and (s.meta or {}).get("src_prix") is not None)
        funnel["liquidity"] += sum(1 for s in sigs if float((s.meta or {}).get("depth_usd") or s.notional_usd) >= s.notional_usd)
        funnel["edge"] += sum(1 for s in sigs if s.edge_estime_bps > 0)
        funnel["consensus"] += sum(1 for s in sigs if int((s.meta or {}).get("consensus_count") or 1) >= 1)
        candidats.extend(sigs)
        sigs.sort(key=lambda s: -s.edge_estime_bps)  # les meilleurs edges d'abord
        for sig in sigs:
            ok, motif = MP.admettre(sig, store, now_ms=now)
            if not ok:
                refus.append({"moteur": m, "coin": sig.coin, "motif": motif})
                sizing_outcomes.append({"coin": sig.coin, "notional_usd": 0.0, "motif": motif})
                continue
            pos = MP.ouvrir(sig, store, root, now_ms=now)
            funnel["PaperIntent"] += 1
            funnel["PaperFill"] += 1 if pos.get("fill_id") else 0
            funnel["POSITION"] += 1 if pos.get("position_id") else 0
            decision_latency_ms = max(0.0, now - float(sig.ts_signal_ms))
            latences_decision_ms.append(decision_latency_ms)
            sizing_outcomes.append({"coin": sig.coin, "notional_usd": sig.notional_usd})
            info = {
                "moteur": m,
                "coin": sig.coin,
                "sens": sig.sens,
                "prix_entree": sig.prix_entree,
                "cout_entree_bps": round(sig.cout_entree_bps, 3),
                "edge_estime_bps": sig.edge_estime_bps,
                "notional_usd": sig.notional_usd,
                "type_pnl": sig.type_pnl,
                "entry_origin": (sig.meta or {}).get("entry_origin", "ENTRY_FROM_OPEN"),
                "decision_latency_ms": round(decision_latency_ms, 1),
                "intent_id": pos.get("intent_id"),
                "order_id": pos.get("order_id"),
                "fill_id": pos.get("fill_id"),
                "position_id": pos.get("position_id"),
                "real_execution": False,
            }
            ouvertures.append(info)
            if premier_signal is None:
                premier_signal = info
    MP.sauver_store(root, store)
    resume = MP.resume(root)
    # 🔴 MtM COURANT par position -> pour que le dashboard MONTRE le mouvement (funding qui s'accumule,
    # prix qui bougent). Recalcule les marks une fois ; donnée absente -> MtM = coût d'entrée (honnête).
    from hl_observer.experimental.carry_deux_jambes import carnet_par_coin, decomposer

    cv = _marks_cross_venue(root)
    carnet = carnet_par_coin(root)
    dir_coins = {p["coin"] for p in store["ouvertes"].values() if p.get("type_pnl") == "directional"}
    mids = _marks_hl_mid(root, dir_coins) if dir_coins else {}
    bidask = _marks_hl_bidask(root, dir_coins) if dir_coins else {}  # LOT14 #4 : MtM = valeur LIQUIDABLE
    from hl_observer.experimental import invariants as INV

    positions = []
    mtm_total = 0.0
    for p in store["ouvertes"].values():
        car = carnet.get(p["coin"])
        typ = p.get("type_pnl")
        if typ == "dislocation":  # court terme : MtM = convergence de l'écart
            gap_ent = float((p.get("meta") or {}).get("gap_entree_bps") or 0.0)
            gap_cur = _gap_courant_bps(car, int(p.get("sens") or 1)) if car else gap_ent
            mtm = MP.pnl_courant_usd(p, base_courant_bps=gap_cur, now_ms=now)
        else:
            m = cv.get(p["coin"]) or {}
            # LOT14 #4 — marque à la valeur RÉELLEMENT liquidable : un long au BID, un short à l'ASK. Repli mid
            # seulement si le carnet est illisible (jamais un prix plus favorable que ce qu'on obtiendrait).
            ba = bidask.get(p["coin"])
            px_exec = (
                INV.prix_sortie_executable(
                    int(p.get("sens") or 1), bid=(ba or {}).get("bid"), ask=(ba or {}).get("ask")
                )
                if ba
                else None
            )
            mtm = MP.pnl_courant_usd(
                p,
                mark=(px_exec if px_exec is not None else (mids.get(p["coin"]) or m.get("hl_px"))),
                base_courant_bps=m.get("base_bps"),
                now_ms=now,
            )
        mtm_total += mtm
        e = {
            "coin": p["coin"],
            "moteur": p["moteur"],
            "sens": p["sens"],
            "notional_usd": p["notional_usd"],
            "prix_entree": p["prix_entree"],
            "edge_estime_bps": p["edge_estime_bps"],
            "type_pnl": typ,
            "mtm_usd": round(mtm, 6),
            "age_min": round((now - float(p["ts_ouverture_ms"])) / 60000.0, 1),
        }
        if typ == "dislocation":
            e["jambes"] = (p.get("meta") or {}).get("jambes")
            e["hedge_ratio"] = (p.get("meta") or {}).get("hedge_ratio")
            e["liquidite_ok"] = bool(
                car and float(car.get("taille_min_usd") or 0.0) >= float(p["notional_usd"])
            )
            e["decomposition"] = {
                "gap_entree_bps": round(gap_ent, 3),
                "gap_courant_bps": round(gap_cur, 3),
                "convergence_bps": round(gap_ent - gap_cur, 3),
                "funding_settled_usd": 0.0,
                "funding_accru_estime_usd": 0.0,
                "pnl_basis_usd": round((gap_ent - gap_cur) / 1e4 * float(p["notional_usd"]), 6),
                "frais_entree_payes_usd": round(
                    MP._cout_usd(p.get("cout_entree_bps") or 0.0, p["notional_usd"]), 6
                ),
                "pnl_liquidable_maintenant_usd": round(mtm, 6),
            }
        elif typ == "funding_carry":  # legacy quarantaine
            dec = decomposer(p, carnet_courant=car, d_courant=None, base_courant_bps=None, now_ms=now)
            e["decomposition"] = dec
            e["jambes"] = dec.get("jambes") or (p.get("meta") or {}).get("jambes")
            e["hedge_ratio"] = dec.get("hedge_ratio") or (p.get("meta") or {}).get("hedge_ratio")
            e["liquidite_ok"] = dec.get("liquidite_ok")
        positions.append(e)
    from collections import Counter

    motifs = Counter(str(r.get("motif") or "REFUS_SANS_MOTIF") for r in refus)
    refus_par_motif = dict(motifs)
    top_no_trade = [
        {"reason": motif, "count": count}
        for motif, count in motifs.most_common(10)
    ]
    statut_path = root / STATUS_RELPATH
    statut_precedent: dict[str, Any] = {}
    if statut_path.exists():
        try:
            statut_precedent = json.loads(statut_path.read_text(encoding="utf-8"))
        except (OSError, ValueError, TypeError):
            statut_precedent = {}
    metriques_precedentes = statut_precedent.get("metriques_cross_venue") or {}
    metriques_ts_ms = float(statut_precedent.get("metriques_cross_venue_ts_ms") or 0.0)
    try:
        from hl_observer.experimental.signaux import metriques_cross_venue

        if now - metriques_ts_ms >= 30_000 or not metriques_precedentes:
            metriques = metriques_cross_venue(root)
            metriques_ts_ms = now
        else:
            metriques = metriques_precedentes
    except Exception:  # noqa: BLE001 — les métriques ne bloquent jamais le tick
        metriques = metriques_precedentes
    all_zero = evaluer_signaux_tous_a_zero(
        sizing_outcomes,
        alerts=LocalAlerts(enabled=True),
        now_ms=int(now),
    )
    if positions:
        zero_position_reason = None
    elif not candidats:
        zero_position_reason = "AUCUN_CANDIDAT_PRODUIT"
    elif all_zero["tous_a_zero"]:
        zero_position_reason = "TOUS_LES_CANDIDATS_DIMENSIONNES_A_ZERO"
    elif top_no_trade:
        zero_position_reason = "TOUS_REFUSES:%s" % top_no_trade[0]["reason"]
    else:
        zero_position_reason = "AUCUNE_POSITION_APRES_CHAINE_PAPER"

    decision_latency_ms = {
        "last": round(latences_decision_ms[-1], 1) if latences_decision_ms else None,
        "max": round(max(latences_decision_ms), 1) if latences_decision_ms else None,
        "mean": round(sum(latences_decision_ms) / len(latences_decision_ms), 1)
        if latences_decision_ms
        else None,
    }
    statut = {
        "ts": time.time(),
        "now_ms": int(now),
        "ouvertures": ouvertures,
        "fermetures": fermetures,
        "n_refus_ce_tick": len(refus),
        "top_no_trade": top_no_trade,
        "decision_funnel": funnel,
        "all_signals_zero": all_zero,
        "zero_position_reason": zero_position_reason,
        "decision_latency_ms": decision_latency_ms,
        "refus_par_motif_ce_tick": refus_par_motif,  # PAR TICK, pas cumulé
        "premier_signal": premier_signal,
        "resume": resume,
        "positions": positions,
        "mtm_total_usd": round(mtm_total, 6),
        "metriques_cross_venue": metriques,
        "metriques_cross_venue_ts_ms": int(metriques_ts_ms) if metriques_ts_ms else None,
        "lead_lag_lane": LEAD_LAG_EXPERIMENTAL_LANE,
        "lead_lag_lane_semantics": "calibration_only_separate_from_strict_event",
        "real_execution": False,
    }
    p = statut_path
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(statut, ensure_ascii=False, indent=1), encoding="utf-8")
    import os

    os.replace(tmp, p)
    return statut


__all__ = ["LEAD_LAG_EXPERIMENTAL_LANE", "tick", "STATUS_RELPATH"]
