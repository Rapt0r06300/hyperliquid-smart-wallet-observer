"""MOTEUR INLINE DEUX-COHORTES (rectif Flo 23/07) — le WS userFills ouvre dans le MÊME flux.

Chaque fill reçu appelle `traiter_fill` : dédup (isSnapshot/hash), agrégation des OPEN/ADD EN DOLLARS
sur quelques secondes (plus de ΔNAV 2 % obligatoire), puis DÈS que le cumulé est significatif →
admission → L2 <1 s → VWAP/coûts complets → edge net positif → OUVERTURE paper INLINE, en mesurant la
LATENCE fill leader → décision. Les REDUCE/CLOSE du leader sortent la position inline.

DEUX cohortes ISOLÉES (stores/budgets/ledgers séparés — les PnL ne se mélangent jamais) :
  • ALPHA  : SOL/ADA (table GELÉE stricte, risque KILL appliqué), notional normal, budget $300, max 3 ;
  • DISCOVERY_PROBE : 2 CORE + 6 CHALLENGERS, table LARGE, tout petits notionals ($10-20), max 4, pertes
    très plafonnées — pour OBSERVER vite les autres coins liquides sans polluer le PnL ALPHA.

Auto-KILL : toute cohorte dont l'expectancy LIVE devient négative se met en pause (KILL). Aucun signal
synthétique, aucun trade forcé, aucune exécution réelle.
"""
from __future__ import annotations

import json
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from hl_observer.experimental import moteur_paper as MP
from hl_observer.experimental.signaux import (_l2_pour_coin, _snapshots_bbo, _carnet_l2_frais, _allmids,
                                              _vaults_retenus, _filer_coins_au_carnet)

FENETRE_AGG_MS = 5_000.0          # on agrège les OPEN/ADD d'un (vault,coin) sur 5 s
NOTIONAL_MIN_USD = 8.0
SLIPPAGE_BASE_BPS = 1.0
SLIPPAGE_IMPACT_COEF = 8.0
LATENCE_COUT_BPS = 1.0
AGE_MAX_OPEN_MS = 5_000.0         # PLAFOND DE SÉCURITÉ (pas une cible) : un fill de CATCH-UP plus vieux ne doit JAMAIS ouvrir
SEUIL_ABS_MIN_USD = 150.0         # plancher EXÉCUTABLE anti-dust : jamais copier un OPEN cumulé sous ça
FRAC_TVL_SIGNIF = 0.002           # significatif RELATIF au vault : cumulé >= 0.2 % de son TVL = vraie conviction
PLAFOND_RAW_USD = 2_000.0         # PLAFOND du seuil relatif : un TRÈS gros vault ne doit pas être bloqué (clamp haut)
COINS_ACTIFS_RELPATH = Path("runtime") / "data" / "raw_coins_actifs.json"


@dataclass(frozen=True)
class Cohorte:
    nom: str
    prefixe: str                  # préfixe des fichiers (ledger/positions/status)
    budget_usd: float
    max_positions: int
    notional_usd: float
    stop_bps_defaut: float
    seuil_open_usd: float         # cumulé $ d'OPEN/ADD du leader qui déclenche une copie
    tables: tuple                 # tables prélim à essayer (ordre de priorité)
    edge_requis: bool = True       # ALPHA/PROBE : edge mesuré requis. RAW_PROBE : non (on MESURE)
    depth_min_usd: float = 0.0    # RAW_PROBE : profondeur mini pour juger un coin « liquide »
    marque: str = ""              # étiquette de statut des positions (ex. NON_VALIDEE pour RAW)


ALPHA = Cohorte("ALPHA_PAPER", "exploratory_paper", 300.0, 3, 60.0, 20.0, 2000.0,
                ("copy_prelim_gele_v1.json", "copy_prelim_edge.json"))
PROBE = Cohorte("DISCOVERY_PROBE", "discovery_probe", 100.0, 4, 15.0, 30.0, 500.0,
                ("copy_prelim_probe.json",))
# RAW_PROBE : ouvre sur TOUT OPEN/ADD candidat liquide (SANS edge requis) pour MESURER la paire vault+coin.
# Mini 5 $, MAX 2, budget minuscule (perte totale plafonnée), positions marquées NON_VALIDEE.
RAW_PROBE = Cohorte("RAW_PROBE", "raw_probe", 20.0, 2, 10.0, 40.0, 200.0, (),
                    edge_requis=False, depth_min_usd=100.0, marque="NON_VALIDEE")
COHORTES = {"ALPHA": ALPHA, "PROBE": PROBE, "RAW_PROBE": RAW_PROBE}


def _p(coh: Cohorte, root: Path, quoi: str) -> Path:
    return root / "runtime" / "data" / ("%s_%s" % (coh.prefixe, quoi))


def _cle(coh: Cohorte, vault: str, coin: str) -> str:
    """Clé d'une position : PAR PAIRE vault+coin pour RAW_PROBE (on mesure chaque paire), par coin sinon."""
    return ("%s|%s" % (vault, coin)) if not coh.edge_requis else coin


def charger_store(coh: Cohorte, root: Path) -> dict:
    try:
        return json.loads(_p(coh, root, "positions.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {"cash": coh.budget_usd, "ouvertes": {}, "realise_total_usd": 0.0}


def _sauver(coh: Cohorte, root: Path, store: dict) -> None:
    if not _ecriture_permise(root):
        raise PermissionError("ecriture RUNTIME_ROOT non autorisee (hors collecteur) — isolation TEST/RUNTIME")
    p = _p(coh, root, "positions.json")
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(store, ensure_ascii=False), encoding="utf-8")
    tmp.replace(p)


def _ledger(coh: Cohorte, root: Path, evt: dict) -> None:
    if not _ecriture_permise(root):
        raise PermissionError("ecriture RUNTIME_ROOT non autorisee (hors collecteur) — isolation TEST/RUNTIME")
    p = _p(coh, root, "ledger.jsonl")
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("a", encoding="utf-8") as f:
        f.write(json.dumps({**evt, "cohorte": coh.nom, "real_execution": False}, ensure_ascii=False) + "\n")


def charger_table(coh: Cohorte, root: Path) -> dict[str, dict]:
    t: dict[str, dict] = {}
    for rel in coh.tables:
        try:
            d = json.loads((root / "runtime" / "data" / rel).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        t = {str(k).upper(): v for k, v in (d.get("table") or d).items() if isinstance(v, dict)}
        if t:
            break
    if coh is PROBE and t:
        # ANTI-DOUBLE-COMPTAGE : PROBE ne trade JAMAIS un coin déjà géré par ALPHA (ex. ADA/SOL).
        # ALPHA a la priorité ; PROBE se réserve les AUTRES coins liquides.
        coins_alpha = set(charger_table(ALPHA, root))
        t = {c: v for c, v in t.items() if c not in coins_alpha}
    return t


def _mark(coin: str, root: Path, now_ms: float, lecteur_l2) -> float | None:
    l2 = _l2_pour_coin(coin, lecteur_l2=lecteur_l2, bbo=_snapshots_bbo(root),
                       carnet=_carnet_l2_frais(root, now_ms=now_ms), now_ms=now_ms)
    if l2:
        return (l2["hl_bid"] + l2["hl_ask"]) / 2.0
    return _allmids(root, now_ms=now_ms).get(coin)


SOURCE_LIVE = "LIVE_WS"           # étiquette d'audit dans le journal (PAS le gate — cf. token hors-payload)
MARQUEUR_RUNTIME = Path("runtime") / "data" / ".runtime_marker"   # présent dans le VRAI runtime, absent des tmp de test
_RUNTIME_AUTORISE: str | None = None   # token en mémoire ; seul le collecteur (via autoriser_runtime) l'arme


def autoriser_runtime(token: str) -> None:
    """Le COLLECTEUR appelle ceci APRÈS avoir pris le mutex : arme l'écriture sous le RUNTIME_ROOT marqué.
    Un pytest ne l'appelle jamais → il ne peut pas écrire dans le vrai runtime (cf. _ecriture_permise)."""
    global _RUNTIME_AUTORISE
    _RUNTIME_AUTORISE = token


def _est_runtime_marque(root: Path) -> bool:
    return (Path(root) / MARQUEUR_RUNTIME).exists()


def _ecriture_permise(root: Path) -> bool:
    """Écrire sous un RUNTIME_ROOT MARQUÉ exige l'autorisation du collecteur. Les racines de test (tmp,
    sans marqueur) sont toujours permises. => aucun pytest ne peut écrire dans le vrai runtime."""
    return (not _est_runtime_marque(root)) or (_RUNTIME_AUTORISE is not None)


def etat_initial(coh: Cohorte, root: Path, *, run_id: str | None = None, token: str | None = None) -> dict:
    import secrets
    import uuid
    return {"store": charger_store(coh, root), "agg": {}, "vus": set(),
            "run_id": run_id or ("run-" + uuid.uuid4().hex[:12]),
            "token": token or secrets.token_hex(16)}      # provenance HORS PAYLOAD (en mémoire)


def _expectancy(coh: Cohorte, root: Path) -> dict:
    try:
        closes = [json.loads(l) for l in _p(coh, root, "ledger.jsonl").read_text(encoding="utf-8", errors="ignore").splitlines() if l.strip()]
    except OSError:
        return {"n_trades": 0}
    closes = [c for c in closes if c.get("evt") == "CLOSE"]
    if not closes:
        return {"n_trades": 0}
    pnls = [float(c.get("realized_usd") or 0.0) for c in closes]
    lat = [float(c["latence_ms"]) for c in closes if c.get("latence_ms") is not None]
    n = len(pnls)
    return {"n_trades": n, "winrate_pct": round(sum(1 for p in pnls if p > 0) / n * 100, 1),
            "expectancy_usd_par_trade": round(sum(pnls) / n, 4),
            "latence_moyenne_ms": round(sum(lat) / len(lat)) if lat else None}


def cohorte_active(coh: Cohorte, root: Path) -> bool:
    """AUTO-KILL : une cohorte dont l'expectancy LIVE est négative (sur assez de trades) se met en pause."""
    ex = _expectancy(coh, root)
    return not (ex.get("n_trades", 0) >= 10 and ex.get("expectancy_usd_par_trade", 0.0) < 0)


def _tvl_vault(vault: str, root: Path) -> float:
    """TVL (capital) du vault depuis vaults_scores.json — sert au déclencheur RELATIF (0 si inconnu)."""
    try:
        d = json.loads((root / "runtime" / "data" / "vaults_scores.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return 0.0
    for c in (d.get("classement") or []):
        if c.get("vault") == vault:
            return float((c.get("facteurs") or {}).get("tvl_usd") or 0.0)
    return 0.0


def _params_trigger(root: Path) -> dict:
    """Params du déclencheur RAW — variante VERSIONNÉE (défauts = v1). Externalisés pour NE PAS re-tuner la
    cohorte en dur : versionner runtime/data/raw_trigger.json {variante, floor_usd, frac_tvl, plafond_usd}."""
    d = {"variante": "v1", "floor_usd": SEUIL_ABS_MIN_USD, "frac_tvl": FRAC_TVL_SIGNIF, "plafond_usd": PLAFOND_RAW_USD}
    try:
        j = json.loads((root / "runtime" / "data" / "raw_trigger.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return d
    for k in ("variante", "floor_usd", "frac_tvl", "plafond_usd"):
        if k in j:
            d[k] = j[k]
    return d


def _declencheur_significatif(coh: Cohorte, vault: str, notional_agg: float, root: Path) -> tuple[bool, float]:
    """Le cumulé same-side est-il SIGNIFICATIF ? Seuil = clamp(frac × TVL, [floor, PLAFOND]) — petit vault
    gouverné par le floor, GROS vault PLAFONNÉ (jamais bloqué). TVL inconnu -> repli coh.seuil_open_usd.
    Params VERSIONNÉS (raw_trigger.json, défaut v1). Rend (significatif, seuil_retenu)."""
    tvl = _tvl_vault(vault, root)
    if tvl <= 0:
        return notional_agg >= coh.seuil_open_usd, coh.seuil_open_usd
    p = _params_trigger(root)
    seuil = min(max(float(p["floor_usd"]), float(p["frac_tvl"]) * tvl), float(p["plafond_usd"]))
    return notional_agg >= seuil, seuil


def _maj_coins_actifs(root: Path, coin: str, *, ajouter: bool, now_ms: float) -> None:
    """Abonnement BBO/L2 DYNAMIQUE du coin pendant la vie de la position : à l'ouverture on inscrit le coin
    (les collecteurs carnet/bbo l'abonnent -> flux frais pour le marquage/VWAP/MFE/MAE) ; à la clôture on le
    retire. `raw_coins_actifs.json` = registre de cycle de vie. Best-effort, ne casse jamais le tick."""
    if not _ecriture_permise(root):
        return
    if ajouter:
        try:
            _filer_coins_au_carnet(root, [coin], now_ms=now_ms)      # prompt d'abonnement (mécanisme carnet existant)
        except Exception:  # noqa: BLE001
            pass
    p = root / COINS_ACTIFS_RELPATH
    try:
        cur = set(json.loads(p.read_text(encoding="utf-8")).get("coins") or []) if p.exists() else set()
    except (OSError, ValueError):
        cur = set()
    cur.add(coin) if ajouter else cur.discard(coin)
    try:
        p.parent.mkdir(parents=True, exist_ok=True)
        tmp = p.with_suffix(".json.tmp")
        tmp.write_text(json.dumps({"maj_ms": int(now_ms), "coins": sorted(cur)}, ensure_ascii=False), encoding="utf-8")
        tmp.replace(p)
    except OSError:
        pass


def _ouvrir(coh: Cohorte, store: dict, root: Path, *, cle, coin, sens, notional, prix, cfg, cout_ar,
            spread, slippage, fhl, vault, now_ms, fill_ts, lat_mono, run_id="", src_l2="", marque="") -> dict:
    eb = cfg.get("edge_brut_bps")
    edge_net = (float(eb) - cout_ar) if eb is not None else None    # RAW : pas d'edge (NON_VALIDEE)
    pos = {"coin": coin, "paire": cle, "moteur": "copy_" + coh.nom, "sens": sens, "type_pnl": "directional",
           "notional_usd": round(notional, 2), "prix_entree": prix, "ts_ouverture_ms": now_ms,
           "cout_entree_bps": round(cout_ar / 2.0, 4), "edge_estime_bps": round(edge_net, 4) if edge_net is not None else None,
           "spread_bps": round(spread, 4), "frais_bps": fhl, "slippage_bps": round(slippage, 4),
           "hold_h": float(cfg.get("horizon_ms") or 0.0) / 3_600_000.0,
           "meta": {"vault": vault, "coin": coin, "stop_bps": cfg.get("stop_bps"),
                    "take_profit_bps": cfg.get("take_profit_bps"), "latence_ws_open_ms": lat_mono.get("ws_open_ms"),
                    "latences_mono": lat_mono, "fill_leader_ts_ms": int(fill_ts), "run_id": run_id,
                    "source": SOURCE_LIVE, "src_l2": src_l2, "statut": marque or "VALIDEE"}}
    store["ouvertes"][cle] = pos
    store["cash"] = round(store["cash"] - notional, 6)
    _ledger(coh, root, {"evt": "OPEN", "ts_ms": now_ms, "paire": cle, "coin": coin, "sens": sens,
                        "notional_usd": pos["notional_usd"], "prix_entree": prix, "edge_net_bps": pos["edge_estime_bps"],
                        "latences_mono": lat_mono, "vault": vault, "run_id": run_id, "source": SOURCE_LIVE,
                        "src_l2": src_l2, "statut": marque or "VALIDEE",
                        "motif": ("RAW mesure (sans edge)" if not coh.edge_requis else "copy OPEN/ADD + L2<1s + edge net>0")})
    _sauver(coh, root, store)
    if not coh.edge_requis:                                          # RAW : abonne le coin en BBO/L2 pour la vie de la position
        _maj_coins_actifs(root, coin, ajouter=True, now_ms=now_ms)
    return pos


def _sortir(coh: Cohorte, pos: dict, store: dict, root: Path, *, prix_sortie, cout_sortie_bps, raison,
            now_ms, mae_bps=None, mfe_bps=None) -> dict:
    realized = round(MP.pnl_courant_usd(pos, mark=prix_sortie, now_ms=now_ms) - cout_sortie_bps / 1e4 * pos["notional_usd"], 6)
    store["ouvertes"].pop(pos.get("paire", pos["coin"]), None)       # clé = paire (RAW = vault|coin), pas coin
    store["cash"] = round(store["cash"] + pos["notional_usd"] + realized, 6)
    store["realise_total_usd"] = round(store.get("realise_total_usd", 0.0) + realized, 6)
    _ledger(coh, root, {"evt": "CLOSE", "ts_ms": now_ms, "coin": pos["coin"], "sens": pos["sens"],
                        "notional_usd": pos["notional_usd"], "prix_entree": pos["prix_entree"], "prix_sortie": prix_sortie,
                        "realized_usd": realized, "raison": raison, "mae_bps": mae_bps, "mfe_bps": mfe_bps,
                        "latence_ms": pos.get("meta", {}).get("latence_fill_copie_ms"),
                        "run_id": pos.get("meta", {}).get("run_id"), "source": SOURCE_LIVE,
                        "vault": pos.get("meta", {}).get("vault")})
    _sauver(coh, root, store)
    if not coh.edge_requis and not any(p.get("coin") == pos["coin"] for p in store["ouvertes"].values()):
        _maj_coins_actifs(root, pos["coin"], ajouter=False, now_ms=now_ms)   # désabonne si plus aucune position sur ce coin
    return {"coin": pos["coin"], "realized_usd": realized, "raison": raison}


def _reduire(coh: Cohorte, pos: dict, store: dict, root: Path, *, fraction: float, prix: float,
             cout_sortie_bps: float, now_ms: float) -> dict:
    """REDUCE : réduit la copie de `fraction` (0<f<1) proportionnellement au leader — réalise le PnL sur
    la part fermée, garde le reste ouvert."""
    frac = max(0.0, min(1.0, fraction))
    part = round(pos["notional_usd"] * frac, 2)
    realized = round(MP.pnl_courant_usd(pos, mark=prix, now_ms=now_ms) * frac - cout_sortie_bps / 1e4 * part, 6)
    pos["notional_usd"] = round(pos["notional_usd"] - part, 2)
    store["cash"] = round(store["cash"] + part + realized, 6)
    store["realise_total_usd"] = round(store.get("realise_total_usd", 0.0) + realized, 6)
    _ledger(coh, root, {"evt": "REDUCE", "ts_ms": now_ms, "coin": pos["coin"], "fraction": round(frac, 3),
                        "part_notional_usd": part, "realized_usd": realized, "prix_sortie": prix,
                        "run_id": pos.get("meta", {}).get("run_id"), "source": SOURCE_LIVE,
                        "vault": pos.get("meta", {}).get("vault")})
    _sauver(coh, root, store)
    return {"coin": pos["coin"], "realized_usd": realized, "raison": "LEADER_A_REDUIT", "fraction": round(frac, 3)}


def traiter_fill(coh: Cohorte, etat: dict, fill: dict, root: Path, *, now_ms: float | None = None,
                 lecteur_l2=None, table: dict | None = None, token: str | None = None,
                 t_ws_mono: float | None = None) -> dict | None:
    """INLINE : traite UN fill leader. Dédup (hash/isSnapshot) ; REDUCE/CLOSE → sortie ; OPEN/ADD agrégés
    en $ → admission → L2<1s → coûts → edge net>0 → OUVERTURE. Rend {ouverture|fermeture|refus, latence_ms}."""
    now = float(now_ms if now_ms is not None else time.time() * 1000)
    # PROVENANCE HORS PAYLOAD : le token doit correspondre au token EN MÉMOIRE de la cohorte (créé par le
    # collecteur). Un fill fabriqué ne peut PAS le connaître → refusé. Le champ source du payload n'est
    # plus le gate (contournable) ; il ne sert qu'à l'audit du journal.
    if token is None or token != etat.get("token"):
        return {"refus": "PROVENANCE_NON_AUTORISEE", "coin": fill.get("coin")}
    if fill.get("isSnapshot"):
        return None                                               # snapshot initial : on ne trade pas dessus
    h = fill.get("hash")
    if h:
        if h in etat["vus"]:
            return None                                           # dédup
        etat["vus"].add(h)
    store = etat["store"]
    coin = str(fill.get("coin") or "").upper()
    vault = fill.get("vault")
    sens = int(fill.get("signe") or 0)
    dir_bas = str(fill.get("dir") or "").lower()
    if not coin or sens == 0:
        return None
    table = table if table is not None else charger_table(coh, root)
    # LEADER REDUCE / CLOSE / FLIP -> on suit proportionnellement (via startPosition du fill)
    if "close" in dir_bas:
        pos = store["ouvertes"].get(_cle(coh, vault, coin))
        if not (pos and pos.get("meta", {}).get("vault") == vault):
            return None
        mark = _mark(coin, root, now, lecteur_l2) or pos["prix_entree"]
        cout = float(pos.get("spread_bps") or 0.0) / 2.0 + float(pos.get("frais_bps") or 0.0) + float(pos.get("slippage_bps") or 0.0)
        start = fill.get("start_position")
        sz = abs(float(fill.get("sz") or 0.0))
        if start is None or abs(start) < 1e-9:                     # info absente -> fermeture prudente complète
            return {"fermeture": _sortir(coh, pos, store, root, prix_sortie=mark, cout_sortie_bps=cout,
                                         raison="LEADER_A_CLOS", now_ms=now)}
        pos_after = start + sens * sz
        if abs(pos_after) < 1e-9:                                  # CLOSE : le leader ferme entièrement -> on ferme tout
            return {"fermeture": _sortir(coh, pos, store, root, prix_sortie=mark, cout_sortie_bps=cout,
                                         raison="LEADER_A_CLOS", now_ms=now)}
        if (start > 0) != (pos_after > 0):                        # FLIP : fermer puis REPASSER l'admission (résidu = nouvel OPEN)
            ferm = _sortir(coh, pos, store, root, prix_sortie=mark, cout_sortie_bps=cout, raison="LEADER_A_FLIP", now_ms=now)
            etat["agg"][(vault, coin)] = {"sens": 1 if pos_after > 0 else -1, "notional": abs(pos_after) * float(fill.get("px") or 0.0),
                                          "t0": now, "fill_ts": int(fill.get("ts_ms") or now)}
            return {"fermeture": ferm, "flip": True}
        fraction = min(1.0, sz / abs(start))                      # REDUCE : réduire la copie de la même fraction
        if fraction >= 0.999:
            return {"fermeture": _sortir(coh, pos, store, root, prix_sortie=mark, cout_sortie_bps=cout,
                                         raison="LEADER_A_CLOS", now_ms=now)}
        return {"reduction": _reduire(coh, pos, store, root, fraction=fraction, prix=mark, cout_sortie_bps=cout, now_ms=now)}
    if "open" not in dir_bas:
        return None
    # GATE D'ÂGE STRICT : un fill de CATCH-UP vieux de plusieurs secondes ne doit JAMAIS ouvrir (on n'agit
    # que sur du FRAIS ; le skew d'horloge HL rend l'âge parfois négatif -> seul un âge franchement positif
    # trahit un rejeu tardif). Les REDUCE/CLOSE (traités plus haut) restent suivis quel que soit l'âge.
    age_ms = now - float(fill.get("ts_ms") or now)
    if age_ms > AGE_MAX_OPEN_MS:
        return {"refus": "FILL_TROP_VIEUX_OPEN", "coin": coin, "age_ms": round(age_ms)}
    # OPEN/ADD : agrégation EN DOLLARS sur quelques secondes (gros OPEN OU plusieurs fills même sens)
    key = (vault, coin)
    ag = etat["agg"].get(key)
    notional_fill = abs(float(fill.get("sz") or 0.0)) * float(fill.get("px") or 0.0)
    if ag and ag["sens"] == sens and (now - ag["t0"]) <= FENETRE_AGG_MS:
        ag["notional"] += notional_fill
    else:
        ag = {"sens": sens, "notional": notional_fill, "t0": now, "fill_ts": int(fill.get("ts_ms") or now)}
        etat["agg"][key] = ag
    # DÉCLENCHEUR SIGNIFICATIF RELATIF AU VAULT (remplace le seuil fixe unique) : cumulé >= max(plancher
    # exécutable, frac × TVL). Petit vault -> plancher ; gros vault -> conviction proportionnelle.
    signif, _seuil = _declencheur_significatif(coh, vault, ag["notional"], root)
    if not signif:
        return None                                               # pas encore un OPEN/ADD significatif pour CE vault
    etat["agg"].pop(key, None)
    t_dec = time.monotonic()                                     # HORLOGE MONOTONE LOCALE : décision
    cle = _cle(coh, vault, coin)
    if not cohorte_active(coh, root):                             # AUTO-KILL : cohorte en pause (expectancy live < 0)
        return {"refus": "COHORTE_EN_PAUSE_AUTO_KILL", "coin": coin}
    # deny-by-default : le vault doit être suivi par la cohorte
    if vault not in _vaults_cohorte(coh, root):
        return {"refus": "VAULT_NON_SUIVI", "coin": coin}
    # EDGE : requis pour ALPHA/PROBE (table par paire coin) ; PAS pour RAW_PROBE (on OUVRE pour MESURER)
    if coh.edge_requis:
        cfg = table.get(coin)
        if not cfg:
            return {"refus": "EDGE_PRELIM_ABSENT", "coin": coin}
    else:
        cfg = {"horizon_ms": 3_600_000.0, "stop_bps": coh.stop_bps_defaut, "take_profit_bps": None, "edge_brut_bps": None}
    if cle in store["ouvertes"]:
        return {"refus": "DEJA_OUVERT", "coin": coin}
    if len(store["ouvertes"]) >= coh.max_positions:
        return {"refus": "LIMITE_POSITIONS", "coin": coin}
    min_notional = 3.0 if not coh.edge_requis else NOTIONAL_MIN_USD
    if store["cash"] < min_notional:
        return {"refus": "BUDGET_EPUISE", "coin": coin}
    l2 = _l2_pour_coin(coin, lecteur_l2=lecteur_l2, bbo=_snapshots_bbo(root),
                       carnet=_carnet_l2_frais(root, now_ms=now), now_ms=now)
    t_l2 = time.monotonic()                                      # MONOTONE : L2 obtenu
    if not l2:
        return {"refus": "L2_INDISPONIBLE_1S", "coin": coin}
    from hl_observer.experimental.carry_deux_jambes import frais_venues
    fhl = frais_venues(root)[0]
    hl_bid, hl_ask = l2["hl_bid"], l2["hl_ask"]
    mid = (hl_bid + hl_ask) / 2.0
    ref = _allmids(root, now_ms=now).get(coin)                    # garde-fou : prix L2 plausible vs allMids
    if ref and ref > 0 and abs(mid - ref) / ref > 0.10:           # >10 % d'écart = L2 aberrant/injecté -> refus
        return {"refus": "L2_ABERRANT", "coin": coin, "mid": round(mid, 6), "ref": round(ref, 6)}
    spread = (hl_ask - hl_bid) / mid * 1e4
    depth = float(l2.get("depth_usd") or 0.0)
    if not coh.edge_requis and depth < coh.depth_min_usd:         # RAW : coin doit être LIQUIDE
        return {"refus": "COIN_TROP_ILLIQUIDE_RAW", "coin": coin, "depth_usd": round(depth, 1)}
    cible_notional = coh.notional_usd
    if coh is PROBE:                                              # un CANDIDAT PROMU trade en MINI (5-10 $)
        from hl_observer.experimental.promotion_candidats import charger_promus
        pr = charger_promus(root).get(vault)
        if pr:
            cible_notional = float(pr.get("notional_usd") or coh.notional_usd)
    notional = min(cible_notional, min(depth, store["cash"]))
    if notional < min_notional:
        return {"refus": "LIQUIDITE_INSUFFISANTE", "coin": coin}
    slippage = SLIPPAGE_BASE_BPS + SLIPPAGE_IMPACT_COEF * (notional / depth if depth else 1.0)
    cout_ar = 2.0 * fhl + spread + 2.0 * slippage + LATENCE_COUT_BPS
    if coh.edge_requis and float(cfg.get("edge_brut_bps") or 0.0) - cout_ar <= 0:
        return {"refus": "EDGE_NEGATIF_APRES_COUTS", "coin": coin}
    prix = hl_ask if sens > 0 else hl_bid
    t_open = time.monotonic()
    t0 = t_ws_mono if t_ws_mono is not None else t_dec
    lat_mono = {"ws_decision_ms": round((t_dec - t0) * 1000, 1), "decision_l2_ms": round((t_l2 - t_dec) * 1000, 1),
                "l2_open_ms": round((t_open - t_l2) * 1000, 1), "ws_open_ms": round((t_open - t0) * 1000, 1),
                "age_event_ms": round(now - float(fill.get("ts_ms") or now))}   # HL ts = âge/skew (peut être négatif)
    pos = _ouvrir(coh, store, root, cle=cle, coin=coin, sens=sens, notional=notional, prix=prix, cfg=cfg,
                  cout_ar=cout_ar, spread=spread, slippage=slippage, fhl=fhl, vault=vault, now_ms=now,
                  fill_ts=ag["fill_ts"], lat_mono=lat_mono, run_id=etat.get("run_id", ""), src_l2=l2.get("src", ""),
                  marque=coh.marque)
    return {"ouverture": pos, "latence_ws_open_ms": lat_mono["ws_open_ms"], "paire": cle}


def _vaults_cohorte(coh: Cohorte, root: Path) -> set[str]:
    """Vaults TRADABLES par la cohorte (deny-by-default). ALPHA = retenus stricts ; PROBE = CORE +
    CHALLENGERS sûrs + CANDIDATS PROMUS ; RAW_PROBE = TOUS les abonnés (CORE + candidats) — on MESURE."""
    from hl_observer.experimental.exploratoire import tiers
    if coh is ALPHA:
        return _vaults_retenus(root)
    core, chal = tiers(root)
    if coh is RAW_PROBE:
        # tous les abonnés (retenus + candidats scorés) — RAW ouvre pour mesurer la paire, pas pour valider
        try:
            d = json.loads((root / "runtime" / "data" / "vaults_scores.json").read_text(encoding="utf-8"))
            tous = {c["vault"] for c in (d.get("classement") or [])[:8]}
        except (OSError, ValueError):
            tous = set()
        return core | chal | tous
    from hl_observer.experimental.promotion_candidats import charger_promus
    return core | chal | set(charger_promus(root))


def gerer_exits(coh: Cohorte, root: Path, *, now_ms: float | None = None, lecteur_l2=None) -> list[dict]:
    """Sorties par PRIX/TEMPS (stop calibré / take-profit / horizon) — complète les sorties leader inline.
    MAE/MFE suivis en continu."""
    now = float(now_ms if now_ms is not None else time.time() * 1000)
    store = charger_store(coh, root)
    fermetures = []
    for pos in list(store["ouvertes"].values()):
        mark = _mark(pos["coin"], root, now, lecteur_l2)
        if mark is None or not pos.get("prix_entree"):
            continue
        exc = pos["sens"] * (mark - pos["prix_entree"]) / pos["prix_entree"] * 1e4
        pos["mae_bps"] = round(min(pos.get("mae_bps", 0.0), exc), 3)
        pos["mfe_bps"] = round(max(pos.get("mfe_bps", 0.0), exc), 3)
        meta = pos.get("meta", {})
        stop = float(meta.get("stop_bps") or coh.stop_bps_defaut)
        tp = meta.get("take_profit_bps")
        cout = float(pos.get("spread_bps") or 0.0) / 2.0 + float(pos.get("frais_bps") or 0.0) + float(pos.get("slippage_bps") or 0.0)
        raison = None
        if exc <= -stop:
            raison = "STOP_PERTE"
        elif tp and exc >= float(tp):
            raison = "TAKE_PROFIT"
        elif (now - float(pos.get("ts_ouverture_ms") or now)) >= float(pos.get("hold_h") or 1.0) * 3_600_000.0:
            raison = "HORIZON_ATTEINT"
        if raison:
            fermetures.append(_sortir(coh, pos, store, root, prix_sortie=mark, cout_sortie_bps=cout,
                                      raison=raison, now_ms=now, mae_bps=pos.get("mae_bps"), mfe_bps=pos.get("mfe_bps")))
    _sauver(coh, root, store)
    return fermetures


def statut(coh: Cohorte, root: Path, *, now_ms: float | None = None, lecteur_l2=None) -> dict:
    now = float(now_ms if now_ms is not None else time.time() * 1000)
    store = charger_store(coh, root)
    non_realise = 0.0
    for pos in store["ouvertes"].values():
        mark = _mark(pos["coin"], root, now, lecteur_l2)
        if mark is not None:
            non_realise += MP.pnl_courant_usd(pos, mark=mark, now_ms=now)
    equity = round(store["cash"] + sum(p["notional_usd"] for p in store["ouvertes"].values()) + non_realise, 4)
    st = {"cohorte": coh.nom, "real_execution": False, "ts_ms": int(now), "active": cohorte_active(coh, root),
          "budget_usd": coh.budget_usd, "cash": store["cash"], "positions_ouvertes": len(store["ouvertes"]),
          "realise_total_usd": store.get("realise_total_usd", 0.0), "non_realise_usd": round(non_realise, 4),
          "equity_usd": equity, "roi_cumulatif_pct": round((equity - coh.budget_usd) / coh.budget_usd * 100, 3),
          "expectancy": _expectancy(coh, root),
          "positions": [{"coin": p["coin"], "sens": p["sens"], "notional_usd": p["notional_usd"],
                         "prix_entree": p["prix_entree"], "vault": p.get("meta", {}).get("vault"),
                         "edge_net_bps": p["edge_estime_bps"], "mae_bps": p.get("mae_bps"), "mfe_bps": p.get("mfe_bps"),
                         "latence_fill_copie_ms": p.get("meta", {}).get("latence_fill_copie_ms")}
                        for p in store["ouvertes"].values()]}
    p = _p(coh, root, "status.json")
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(st, ensure_ascii=False, indent=1), encoding="utf-8")
    return st


__all__ = ["Cohorte", "ALPHA", "PROBE", "COHORTES", "traiter_fill", "gerer_exits", "statut",
           "charger_store", "charger_table", "etat_initial", "cohorte_active", "FENETRE_AGG_MS"]
