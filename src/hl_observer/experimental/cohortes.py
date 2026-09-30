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

from hl_observer.experimental.cohort_paper_bridge import (
    ECONOMIC_SOURCE,
    available_margin_usdt,
    canonical_execution_truth,
)
from hl_observer.experimental.cohort_paper_bridge import (
    apply_entry as _apply_canonical_entry,
)
from hl_observer.experimental.cohort_paper_bridge import (
    apply_exit as _apply_canonical_exit,
)
from hl_observer.experimental.cohort_paper_bridge import (
    build_engine as _build_canonical_engine,
)
from hl_observer.experimental.signaux import (
    _allmids,
    _carnet_l2_frais,
    _filer_coins_au_carnet,
    _l2_pour_coin,
    _snapshots_bbo,
    _vaults_retenus,
)

FENETRE_AGG_MS = 5_000.0          # on agrège les OPEN/ADD d'un (vault,coin) sur 5 s
NOTIONAL_MIN_USD = 8.0
SLIPPAGE_BASE_BPS = 1.0
SLIPPAGE_IMPACT_COEF = 8.0
LATENCE_COUT_BPS = 1.0
AGE_MAX_OPEN_MS = 5_000.0         # PLAFOND DE SÉCURITÉ (pas une cible) : un fill de CATCH-UP plus vieux ne doit JAMAIS ouvrir
SEUIL_ABS_MIN_USD = 150.0         # plancher EXÉCUTABLE anti-dust : jamais copier un OPEN cumulé sous ça
FRAC_TVL_SIGNIF = 0.002           # significatif RELATIF au vault : cumulé >= 0.2 % de son TVL = vraie conviction
PLAFOND_RAW_USD = 2_000.0         # PLAFOND du seuil relatif : un TRÈS gros vault ne doit pas être bloqué (clamp haut)
AGE_MAX_PAPER_FILL_MS = 5_000.0   # ENTRÉE refusée si le délai TOTAL fill_leader->exécution_paper dépasse ça
RAW_BASELINE_MAX_CYCLES = 20      # RAW = baseline MINUSCULE : figée à 20 cycles clôturés (config courante) puis KILL/OBSERVE
COINS_ACTIFS_RELPATH = Path("runtime") / "data" / "raw_coins_actifs.json"
COINS_PREWARM_RELPATH = Path("runtime") / "data" / "raw_coins_prewarm.json"   # coins en agrégation -> abonnement L2 EN PARALLÈLE


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
        store = json.loads(_p(coh, root, "positions.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        store = {"cash": coh.budget_usd, "ouvertes": {}, "realise_total_usd": 0.0}
    store.setdefault("ouvertes", {})
    store.setdefault("realise_total_usd", 0.0)
    store["economic_source"] = ECONOMIC_SOURCE
    store["cash"] = available_margin_usdt(coh, store)
    return store


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
                       carnet=_carnet_l2_frais(root, now_ms=now_ms), now_ms=now_ms, root=root)
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


def etat_initial(coh: Cohorte, root: Path, *, run_id: str | None = None, token: str | None = None,
                 git_commit: str = "", transport_version: str = "") -> dict:
    import secrets
    import uuid
    return {"store": charger_store(coh, root), "agg": {}, "vus": set(), "paper_engine": None,
            "run_id": run_id or ("run-" + uuid.uuid4().hex[:12]), "git_commit": git_commit,
            "transport_version": transport_version,        # transport WS (hors config_hash) : compare latence avant/après
            "token": token or secrets.token_hex(16)}      # provenance HORS PAYLOAD (en mémoire)


def _paper_engine(coh: Cohorte, etat: dict, *, taker_fee_bps: float):
    engine = etat.get("paper_engine")
    if engine is None:
        engine = _build_canonical_engine(
            coh,
            etat["store"],
            taker_fee_bps=taker_fee_bps,
        )
        etat["paper_engine"] = engine
    return engine


def _expectancy(coh: Cohorte, root: Path, *, run_id: str | None = None, trigger_version: str | None = None,
                config_hash: str | None = None) -> dict:
    """Stats des CLOSE, séparées par CONFIG. Clé = config_hash (empreinte des VRAIES valeurs) si fourni, sinon
    trigger_version (étiquette). Validité RUN-AGNOSTIQUE (un cycle traverse un redémarrage). Les cycles d'une
    AUTRE config comptent à part LEGACY_CROSS_RUN — jamais reclassés. `run_id` ignoré (audit). PnL/ROI cumulé
    + alpha placebo moyen inclus."""
    try:
        evs = [json.loads(l) for l in _p(coh, root, "ledger.jsonl").read_text(encoding="utf-8", errors="ignore").splitlines() if l.strip()]
    except OSError:
        return {"n_trades": 0}
    closes = [c for c in evs if c.get("evt") == "CLOSE"]
    n_legacy = 0
    cle = config_hash if config_hash is not None else trigger_version   # config_hash = clé PRÉCISE ; sinon l'étiquette
    champ = "config_hash" if config_hash is not None else "trigger_version"
    if cle is not None:                                        # VALIDITÉ RUN-AGNOSTIQUE (un cycle traverse un redémarrage)
        courant = []
        for c in closes:
            if c.get(champ) == cle:
                courant.append(c)
            else:
                n_legacy += 1                                  # LEGACY_CROSS_RUN : autre config -> à part, JAMAIS reclassé
        closes = courant
    if not closes:
        return {"n_trades": 0, "n_legacy_cross_run": n_legacy}
    pnls = [float(c.get("realized_usd") or 0.0) for c in closes]
    rois = [float(c.get("realized_usd") or 0.0) / (float(c.get("notional_usd") or 0.0) or 1.0) * 100 for c in closes]
    lat = [float(c["latence_ms"]) for c in closes if c.get("latence_ms") is not None]
    alphas = [float(c["alpha_vs_marche_bps"]) for c in closes if c.get("alpha_vs_marche_bps") is not None]
    n = len(pnls)
    return {"n_trades": n, "winrate_pct": round(sum(1 for p in pnls if p > 0) / n * 100, 1),
            "expectancy_usd_par_trade": round(sum(pnls) / n, 4), "pnl_cumule_usd": round(sum(pnls), 4),
            "roi_moyen_par_trade_pct": round(sum(rois) / n, 3),
            "alpha_vs_marche_moyen_bps": round(sum(alphas) / len(alphas), 2) if alphas else None,
            "latence_moyenne_ms": round(sum(lat) / len(lat)) if lat else None, "n_legacy_cross_run": n_legacy}


def cohorte_active(coh: Cohorte, root: Path, *, run_id: str | None = None, trigger_version: str | None = None,
                   config_hash: str | None = None) -> bool:
    """AUTO-KILL : une cohorte dont l'expectancy LIVE (config COURANTE seule, clé config_hash) est négative sur
    assez de trades se met en pause. Une autre config (legacy) ne peut ni sauver ni tuer la config courante."""
    if not coh.edge_requis:        # RAW = baseline de MESURE : gouvernée par le CAP 20 cycles, pas par l'auto-KILL d'expectancy
        return True                # (on VEUT l'échantillon complet jusqu'à 20 ; la perte reste bornée par son budget minuscule)
    ex = _expectancy(coh, root, run_id=run_id, trigger_version=trigger_version, config_hash=config_hash)
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


L2_MODELE = "top5depth+rest_ondemand+ws_prewarm+book_ws_marquage"   # identifiant du MODÈLE L2 (entre dans config_hash)
MODELE_EXECUTION = "exec_v1"       # VERSION du modèle d'exécution paper (entre dans config_hash)
MODELE_FRAIS = "hl_taker_roundtrip_2x+spread+2xslippage+latence"    # hypothèse EXACTE de frais applicable


def _cfg_defaut(coh: Cohorte) -> dict:
    """cfg par défaut d'une cohorte (RAW = exactement le cfg synthétique utilisé à l'ouverture)."""
    return {"horizon_ms": 3_600_000.0, "stop_bps": coh.stop_bps_defaut, "take_profit_bps": None, "edge_brut_bps": None}


def _config_hash(coh: Cohorte, cfg: dict, fhl: float, root: Path) -> str:
    """Empreinte DÉTERMINISTE de la config IMMUABLE à l'OPEN : JSON CANONIQUE (clés triées) puis SHA-256
    (hash COMPLET). Inclut notional, params du déclencheur, âges max, HYPOTHÈSE de frais exacte, stop/TP/
    horizon (du cfg = par coin pour ALPHA/PROBE), TABLES/paire, profondeur/slippage, MODÈLE L2 et VERSION du
    modèle d'exécution. PAS le commit Git (gardé à part). VRAIE clé de séparation (trigger_version = étiquette)."""
    import hashlib
    p = _params_trigger(root)
    payload = {"notional_usd": coh.notional_usd,
               "trigger": {"floor": p["floor_usd"], "frac_tvl": p["frac_tvl"], "plafond": p["plafond_usd"], "variante": p["variante"]},
               "age_max_open_ms": AGE_MAX_OPEN_MS, "age_max_paper_fill_ms": AGE_MAX_PAPER_FILL_MS,
               "frais": {"hl_bps": round(float(fhl), 4), "modele": MODELE_FRAIS},
               "cfg": {"stop_bps": cfg.get("stop_bps"), "take_profit_bps": cfg.get("take_profit_bps"), "horizon_ms": cfg.get("horizon_ms")},
               "tables": list(coh.tables), "depth_min_usd": coh.depth_min_usd, "slippage_base_bps": SLIPPAGE_BASE_BPS,
               "slippage_impact_coef": SLIPPAGE_IMPACT_COEF, "latence_cout_bps": LATENCE_COUT_BPS,
               "modele_l2": L2_MODELE, "modele_execution": MODELE_EXECUTION}
    canon = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return "cfg-" + hashlib.sha256(canon.encode("utf-8")).hexdigest()


def config_hash_courant(coh: Cohorte, root: Path) -> str:
    """config_hash de la config COURANTE d'une cohorte (cfg par défaut + frais courants). Sert au filtre des
    stats et au gate live. Pour RAW, identique au hash estampillé à l'ouverture (même cfg)."""
    root = Path(root)
    try:
        from hl_observer.experimental.carry_deux_jambes import frais_venues
        fhl = frais_venues(root)[0]
    except Exception:  # noqa: BLE001
        fhl = 0.0
    return _config_hash(coh, _cfg_defaut(coh), fhl, root)


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
            import logging as _lg  # panne rendue VISIBLE (interdiction des except:pass muets)
            _lg.getLogger(__name__).debug("exception ignoree volontairement ici", exc_info=True)
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
        import logging as _lg  # panne rendue VISIBLE (interdiction des except:pass muets)
        _lg.getLogger(__name__).debug("exception ignoree volontairement ici", exc_info=True)


def _maj_coins_prewarm(root: Path, coin: str, *, now_ms: float) -> None:
    """PREWARM L2 EN PARALLÈLE : dès qu'un OPEN commence à s'agréger, on inscrit le coin ici pour que
    l'abonnement L2 WS démarre TOUT DE SUITE (course avec le REST). Au moment du déclenchement, le book WS
    est souvent déjà chaud -> admission rapide ; sinon repli REST. Best-effort, TTL géré côté collecteur."""
    if not _ecriture_permise(root):
        return
    p = root / COINS_PREWARM_RELPATH
    try:
        cur = dict(json.loads(p.read_text(encoding="utf-8")).get("coins") or {}) if p.exists() else {}
    except (OSError, ValueError):
        cur = {}
    cur[coin] = int(now_ms)
    cur = {c: t for c, t in cur.items() if now_ms - float(t) <= 15_000}   # purge > 15 s
    try:
        p.parent.mkdir(parents=True, exist_ok=True)
        tmp = p.with_suffix(".json.tmp")
        tmp.write_text(json.dumps({"maj_ms": int(now_ms), "coins": cur}, ensure_ascii=False), encoding="utf-8")
        tmp.replace(p)
    except OSError:
        import logging as _lg  # panne rendue VISIBLE (interdiction des except:pass muets)
        _lg.getLogger(__name__).debug("exception ignoree volontairement ici", exc_info=True)


def _ouvrir_legacy_disabled(coh: Cohorte, store: dict, root: Path, *, cle, coin, sens, notional, prix, cfg, cout_ar,
                            spread, slippage, fhl, vault, now_ms, fill_ts, lat_mono, run_id="", src_l2="", marque="",
                            trigger_version="", placebo=None, config_hash="", git_commit="", transport_version="") -> dict:
    raise RuntimeError("legacy cohort execution is disabled; use PaperEngine")
    import uuid
    eb = cfg.get("edge_brut_bps")
    edge_net = (float(eb) - cout_ar) if eb is not None else None    # RAW : pas d'edge (NON_VALIDEE)
    cycle_id = "cyc-" + uuid.uuid4().hex[:12]                       # IDENTITÉ PERSISTANTE du cycle (survit aux redémarrages)
    from hl_observer.experimental.selecteur_audit import snapshot_selecteur
    sel = snapshot_selecteur(root, vault)                          # SÉLECTEUR figé À L'OPEN (couche SÉPARÉE, hors config_hash)
    pos = {"coin": coin, "paire": cle, "moteur": "copy_" + coh.nom, "sens": sens, "type_pnl": "directional",
           "notional_usd": round(notional, 2), "prix_entree": prix, "ts_ouverture_ms": now_ms,
           "cout_entree_bps": round(cout_ar / 2.0, 4), "edge_estime_bps": round(edge_net, 4) if edge_net is not None else None,
           "spread_bps": round(spread, 4), "frais_bps": fhl, "slippage_bps": round(slippage, 4),
           "hold_h": float(cfg.get("horizon_ms") or 0.0) / 3_600_000.0,
           "meta": {"vault": vault, "coin": coin, "stop_bps": cfg.get("stop_bps"),
                    "take_profit_bps": cfg.get("take_profit_bps"), "latence_ws_open_ms": lat_mono.get("ws_open_ms"),
                    "latences_mono": lat_mono, "fill_leader_ts_ms": int(fill_ts), "run_id": run_id,
                    "source": SOURCE_LIVE, "src_l2": src_l2, "statut": marque or "VALIDEE",
                    "trigger_version": trigger_version, "placebo": placebo, "config_hash": config_hash,
                    "cycle_id": cycle_id, "open_run_id": run_id, "notional_open_usd": round(notional, 2),
                    "git_commit": git_commit, "transport_version": transport_version, "selecteur": sel}}
    store["ouvertes"][cle] = pos
    store["cash"] = round(store["cash"] - notional, 6)
    _ledger(coh, root, {"evt": "OPEN", "ts_ms": now_ms, "paire": cle, "coin": coin, "sens": sens,
                        "notional_usd": pos["notional_usd"], "prix_entree": prix, "edge_net_bps": pos["edge_estime_bps"],
                        "latences_mono": lat_mono, "vault": vault, "run_id": run_id, "source": SOURCE_LIVE,
                        "src_l2": src_l2, "statut": marque or "VALIDEE", "trigger_version": trigger_version,
                        "age_at_paper_fill_ms": lat_mono.get("age_at_paper_fill_ms"),
                        "cycle_id": cycle_id, "open_run_id": run_id, "config_hash": config_hash, "git_commit": git_commit,
                        "transport_version": transport_version, "selecteur": sel,   # SÉLECTEUR figé (hors config_hash)
                        "vault_role_at_open": sel.get("vault_role_at_open"), "roster_hash": sel.get("roster_hash"),
                        "score_model_version": sel.get("score_model_version"), "score_snapshot_ts": sel.get("score_snapshot_ts"),
                        "motif": ("RAW mesure (sans edge)" if not coh.edge_requis else "copy OPEN/ADD + L2<1s + edge net>0")})
    _sauver(coh, root, store)
    if not coh.edge_requis:                                          # RAW : abonne le coin en BBO/L2 pour la vie de la position
        _maj_coins_actifs(root, coin, ajouter=True, now_ms=now_ms)
    return pos


def _legacy_pnl_forbidden(*_args, **_kwargs) -> float:
    """Prevent the disabled cohort path from becoming an economic source again."""

    raise RuntimeError("legacy cohort PnL is disabled; use PaperEngine/PaperLedger")


def _sortir_legacy_disabled(coh: Cohorte, pos: dict, store: dict, root: Path, *, prix_sortie, cout_sortie_bps, raison,
                            now_ms, mae_bps=None, mfe_bps=None, close_run_id=None) -> dict:
    raise RuntimeError("legacy cohort execution is disabled; use PaperEngine")
    realized = round(_legacy_pnl_forbidden(pos, mark=prix_sortie, now_ms=now_ms) - cout_sortie_bps / 1e4 * pos["notional_usd"], 6)
    meta = pos.get("meta", {})
    pl = meta.get("placebo") or {}                                   # PLACEBO même coin/même instant : alpha vs marché
    mc0, mm0 = float(pl.get("mid_coin_open") or 0.0), float(pl.get("mid_marche_open") or 0.0)
    mm1 = float(_allmids(root, now_ms=now_ms).get("BTC") or 0.0)
    ret_coin_bps = round((prix_sortie / mc0 - 1.0) * 1e4, 3) if mc0 > 0 else None        # dérive brute du coin
    ret_marche_bps = round((mm1 / mm0 - 1.0) * 1e4, 3) if (mm0 > 0 and mm1 > 0) else None  # dérive du MARCHÉ (BTC)
    placebo_marche_bps = round(pos["sens"] * ret_marche_bps, 3) if ret_marche_bps is not None else None   # même sens sur le marché
    alpha_vs_marche_bps = (round(pos["sens"] * ret_coin_bps - placebo_marche_bps, 3)     # capture coin MOINS marché = alpha vault
                           if (ret_coin_bps is not None and placebo_marche_bps is not None) else None)
    store["ouvertes"].pop(pos.get("paire", pos["coin"]), None)       # clé = paire (RAW = vault|coin), pas coin
    store["cash"] = round(store["cash"] + pos["notional_usd"] + realized, 6)
    store["realise_total_usd"] = round(store.get("realise_total_usd", 0.0) + realized, 6)
    _ledger(coh, root, {"evt": "CLOSE", "ts_ms": now_ms, "coin": pos["coin"], "sens": pos["sens"],
                        "notional_usd": pos["notional_usd"], "prix_entree": pos["prix_entree"], "prix_sortie": prix_sortie,
                        "realized_usd": realized, "raison": raison, "mae_bps": mae_bps, "mfe_bps": mfe_bps,
                        "latence_ms": meta.get("latence_fill_copie_ms"), "run_id": meta.get("run_id"),
                        "trigger_version": meta.get("trigger_version"), "source": SOURCE_LIVE, "vault": meta.get("vault"),
                        "cycle_id": meta.get("cycle_id"), "open_run_id": meta.get("open_run_id") or meta.get("run_id"),
                        "close_run_id": close_run_id, "notional_open_usd": meta.get("notional_open_usd"),
                        "config_hash": meta.get("config_hash"), "git_commit": meta.get("git_commit"),
                        "transport_version": meta.get("transport_version"),
                        "selecteur": meta.get("selecteur"),                       # SÉLECTEUR figé à l'OPEN, recopié (pas reclassé)
                        "vault_role_at_open": (meta.get("selecteur") or {}).get("vault_role_at_open"),
                        "roster_hash": (meta.get("selecteur") or {}).get("roster_hash"),
                        "score_model_version": (meta.get("selecteur") or {}).get("score_model_version"),
                        "ret_coin_bps": ret_coin_bps, "ret_marche_bps": ret_marche_bps,
                        "placebo_marche_bps": placebo_marche_bps, "alpha_vs_marche_bps": alpha_vs_marche_bps})
    _sauver(coh, root, store)
    if not coh.edge_requis and not any(p.get("coin") == pos["coin"] for p in store["ouvertes"].values()):
        _maj_coins_actifs(root, pos["coin"], ajouter=False, now_ms=now_ms)   # désabonne si plus aucune position sur ce coin
    return {"coin": pos["coin"], "realized_usd": realized, "raison": raison}


def _reduire_legacy_disabled(coh: Cohorte, pos: dict, store: dict, root: Path, *, fraction: float, prix: float,
                             cout_sortie_bps: float, now_ms: float) -> dict:
    raise RuntimeError("legacy cohort execution is disabled; use PaperEngine")
    """REDUCE : réduit la copie de `fraction` (0<f<1) proportionnellement au leader — réalise le PnL sur
    la part fermée, garde le reste ouvert."""
    frac = max(0.0, min(1.0, fraction))
    part = round(pos["notional_usd"] * frac, 2)
    realized = round(_legacy_pnl_forbidden(pos, mark=prix, now_ms=now_ms) * frac - cout_sortie_bps / 1e4 * part, 6)
    pos["notional_usd"] = round(pos["notional_usd"] - part, 2)
    store["cash"] = round(store["cash"] + part + realized, 6)
    store["realise_total_usd"] = round(store.get("realise_total_usd", 0.0) + realized, 6)
    _ledger(coh, root, {"evt": "REDUCE", "ts_ms": now_ms, "coin": pos["coin"], "fraction": round(frac, 3),
                        "part_notional_usd": part, "realized_usd": realized, "prix_sortie": prix,
                        "run_id": pos.get("meta", {}).get("run_id"), "source": SOURCE_LIVE,
                        "vault": pos.get("meta", {}).get("vault")})
    _sauver(coh, root, store)
    return {"coin": pos["coin"], "realized_usd": realized, "raison": "LEADER_A_REDUIT", "fraction": round(frac, 3)}


def _canonical_refusal(
    coh: Cohorte,
    store: dict,
    root: Path,
    *,
    coin: str,
    result,
    now_ms: float,
    run_id: str = "",
) -> dict:
    reasons = tuple(dict.fromkeys(str(reason) for reason in result.reason_codes))
    refusal = {
        "refus": reasons[0] if reasons else "PAPER_ENGINE_REJECTED",
        "raisons": list(reasons),
        "coin": coin,
        "evidence_hash": result.evidence_hash,
        "economic_source": ECONOMIC_SOURCE,
    }
    if result.trade is not None:
        refusal["paper_trade_id"] = result.trade.trade_id
    store["last_no_trade"] = refusal
    store["canonical_ledger_snapshot"] = result.ledger_snapshot
    _ledger(
        coh,
        root,
        {
            "evt": "NO_TRADE",
            "ts_ms": now_ms,
            "coin": coin,
            "run_id": run_id,
            "source": SOURCE_LIVE,
            "economic_source": ECONOMIC_SOURCE,
            "reason_codes": list(reasons),
            "evidence_hash": result.evidence_hash,
            "paper_trade_id": (
                result.trade.trade_id if result.trade is not None else None
            ),
        },
    )
    _sauver(coh, root, store)
    return refusal


def _ouvrir(
    coh: Cohorte,
    store: dict,
    root: Path,
    *,
    cle,
    coin,
    sens,
    notional,
    prix,
    cfg,
    cout_ar,
    spread,
    slippage,
    fhl,
    vault,
    now_ms,
    fill_ts,
    lat_mono,
    engine,
    execution_truth,
    evidence_ref,
    run_id="",
    src_l2="",
    marque="",
    trigger_version="",
    placebo=None,
    config_hash="",
    git_commit="",
    transport_version="",
) -> dict:
    del prix
    import uuid

    from hl_observer.experimental.selecteur_audit import snapshot_selecteur

    edge_brut = cfg.get("edge_brut_bps")
    edge_net = (
        None if edge_brut is None else float(edge_brut) - float(cout_ar)
    )
    selector = snapshot_selecteur(root, vault)
    wallet_score = selector.get("score_at_open")
    signal_score = max(
        0.0,
        min(
            100.0,
            100.0
            * (
                1.0
                - max(0.0, float(now_ms) - float(fill_ts))
                / max(1.0, AGE_MAX_PAPER_FILL_MS)
            ),
        ),
    )
    result = _apply_canonical_entry(
        engine,
        wallet=str(vault),
        coin=str(coin),
        side_sign=int(sens),
        leader_size=max(
            1e-12,
            float(notional) / max(execution_truth.mid_price, 1e-12),
        ),
        observed_at_ms=int(now_ms),
        leader_event_time_ms=int(fill_ts),
        evidence_ref=str(evidence_ref),
        edge_remaining_bps=edge_net,
        wallet_score=(
            None if wallet_score is None else float(wallet_score)
        ),
        signal_score=signal_score,
        estimated_slippage_bps=float(slippage),
        target_notional_usdt=float(notional),
        execution_truth=execution_truth,
        decision_context={
            "cohort": coh.nom,
            "run_id": run_id,
            "config_hash": config_hash,
            "trigger_version": trigger_version,
        },
    )
    if not result.accepted or result.position is None or result.trade is None:
        return _canonical_refusal(
            coh,
            store,
            root,
            coin=str(coin),
            result=result,
            now_ms=now_ms,
            run_id=run_id,
        )

    position = result.position
    trade = result.trade
    cycle_id = "cyc-" + uuid.uuid4().hex[:12]
    projection = {
        "coin": coin,
        "paire": cle,
        "moteur": "copy_" + coh.nom,
        "sens": sens,
        "type_pnl": "directional",
        "notional_usd": round(position.notional_usdt, 8),
        "quantity": round(position.quantity, 12),
        "margin_locked_usd": round(position.margin_locked_usdt, 8),
        "prix_entree": trade.fill_price,
        "ts_ouverture_ms": now_ms,
        "cout_entree_bps": round(trade.fees_and_cost_bps, 8),
        "edge_estime_bps": (
            round(edge_net, 8) if edge_net is not None else None
        ),
        "spread_bps": round(spread, 8),
        "frais_bps": fhl,
        "slippage_bps": round(slippage, 8),
        "hold_h": float(cfg.get("horizon_ms") or 0.0) / 3_600_000.0,
        "meta": {
            "vault": vault,
            "coin": coin,
            "stop_bps": cfg.get("stop_bps"),
            "take_profit_bps": cfg.get("take_profit_bps"),
            "latence_ws_open_ms": lat_mono.get("ws_open_ms"),
            "latences_mono": lat_mono,
            "fill_leader_ts_ms": int(fill_ts),
            "run_id": run_id,
            "source": SOURCE_LIVE,
            "src_l2": src_l2,
            "statut": marque or "VALIDEE",
            "trigger_version": trigger_version,
            "placebo": placebo,
            "config_hash": config_hash,
            "cycle_id": cycle_id,
            "open_run_id": run_id,
            "notional_open_usd": round(position.notional_usdt, 8),
            "git_commit": git_commit,
            "transport_version": transport_version,
            "selecteur": selector,
            "paper_position_id": position.position_id,
            "paper_trade_id": trade.trade_id,
            "source_delta_id": position.source_delta_id,
            "canonical_evidence_hash": result.evidence_hash,
            "execution_snapshot_id": trade.execution_snapshot_id,
            "economic_source": ECONOMIC_SOURCE,
        },
    }
    store["ouvertes"][cle] = projection
    store["cash"] = available_margin_usdt(coh, store)
    store["canonical_ledger_snapshot"] = result.ledger_snapshot
    _ledger(
        coh,
        root,
        {
            "evt": "OPEN",
            "ts_ms": now_ms,
            "paire": cle,
            "coin": coin,
            "sens": sens,
            "notional_usd": projection["notional_usd"],
            "quantity": projection["quantity"],
            "prix_entree": trade.fill_price,
            "edge_net_bps": projection["edge_estime_bps"],
            "latences_mono": lat_mono,
            "vault": vault,
            "run_id": run_id,
            "source": SOURCE_LIVE,
            "src_l2": src_l2,
            "statut": marque or "VALIDEE",
            "trigger_version": trigger_version,
            "age_at_paper_fill_ms": lat_mono.get("age_at_paper_fill_ms"),
            "cycle_id": cycle_id,
            "open_run_id": run_id,
            "config_hash": config_hash,
            "git_commit": git_commit,
            "transport_version": transport_version,
            "selecteur": selector,
            "vault_role_at_open": selector.get("vault_role_at_open"),
            "roster_hash": selector.get("roster_hash"),
            "score_model_version": selector.get("score_model_version"),
            "score_snapshot_ts": selector.get("score_snapshot_ts"),
            "paper_position_id": position.position_id,
            "paper_trade_id": trade.trade_id,
            "source_delta_id": position.source_delta_id,
            "evidence_hash": result.evidence_hash,
            "execution_snapshot_id": trade.execution_snapshot_id,
            "economic_source": ECONOMIC_SOURCE,
            "motif": "canonical PaperEngine OPEN with executable L2",
        },
    )
    _sauver(coh, root, store)
    _maj_coins_actifs(root, coin, ajouter=True, now_ms=now_ms)
    return projection


def _executer_sortie(
    coh: Cohorte,
    pos: dict,
    store: dict,
    root: Path,
    *,
    engine,
    execution_truth,
    fraction: float,
    raison: str,
    now_ms: float,
    evidence_ref: str,
    leader_event_time_ms: float | None = None,
    close_run_id=None,
    mae_bps=None,
    mfe_bps=None,
) -> dict:
    result = _apply_canonical_exit(
        engine,
        position_payload=pos,
        fraction=fraction,
        observed_at_ms=int(now_ms),
        leader_event_time_ms=int(
            leader_event_time_ms
            if leader_event_time_ms is not None
            else now_ms
        ),
        evidence_ref=str(evidence_ref),
        execution_truth=execution_truth,
        reason=raison,
        decision_context={
            "cohort": coh.nom,
            "close_run_id": close_run_id,
        },
    )
    if not result.accepted or result.trade is None:
        return _canonical_refusal(
            coh,
            store,
            root,
            coin=str(pos.get("coin") or ""),
            result=result,
            now_ms=now_ms,
            run_id=str(close_run_id or ""),
        )

    trade = result.trade
    meta = dict(pos.get("meta") or {})
    key = str(pos.get("paire") or pos.get("coin"))
    notional_before = float(pos.get("notional_usd") or 0.0)
    closed_fraction = min(
        1.0,
        trade.quantity / max(float(pos.get("quantity") or 0.0), 1e-12),
    )
    if result.position is None:
        store["ouvertes"].pop(key, None)
    else:
        pos["quantity"] = round(result.position.quantity, 12)
        pos["notional_usd"] = round(result.position.notional_usdt, 8)
        pos["margin_locked_usd"] = round(
            result.position.margin_locked_usdt,
            8,
        )
        store["ouvertes"][key] = pos
    store["realise_total_usd"] = round(
        float(store.get("realise_total_usd") or 0.0)
        + float(trade.realized_pnl_usdt),
        8,
    )
    store["cash"] = available_margin_usdt(coh, store)
    store["canonical_ledger_snapshot"] = result.ledger_snapshot

    placebo = meta.get("placebo") or {}
    coin_open = float(placebo.get("mid_coin_open") or 0.0)
    market_open = float(placebo.get("mid_marche_open") or 0.0)
    market_now = float(_allmids(root, now_ms=now_ms).get("BTC") or 0.0)
    exit_price = float(trade.fill_price or 0.0)
    ret_coin_bps = (
        round((exit_price / coin_open - 1.0) * 1e4, 3)
        if coin_open > 0 and exit_price > 0
        else None
    )
    ret_market_bps = (
        round((market_now / market_open - 1.0) * 1e4, 3)
        if market_open > 0 and market_now > 0
        else None
    )
    placebo_market_bps = (
        round(int(pos.get("sens") or 0) * ret_market_bps, 3)
        if ret_market_bps is not None
        else None
    )
    alpha_bps = (
        round(
            int(pos.get("sens") or 0) * ret_coin_bps
            - placebo_market_bps,
            3,
        )
        if ret_coin_bps is not None and placebo_market_bps is not None
        else None
    )
    event_name = "CLOSE" if result.position is None else "REDUCE"
    _ledger(
        coh,
        root,
        {
            "evt": event_name,
            "ts_ms": now_ms,
            "coin": pos["coin"],
            "sens": pos["sens"],
            "notional_usd": notional_before,
            "closed_fraction": round(closed_fraction, 8),
            "part_notional_usd": round(trade.notional_usdt, 8),
            "prix_entree": pos["prix_entree"],
            "prix_sortie": trade.fill_price,
            "realized_usd": trade.realized_pnl_usdt,
            "raison": raison,
            "mae_bps": mae_bps,
            "mfe_bps": mfe_bps,
            "run_id": meta.get("run_id"),
            "trigger_version": meta.get("trigger_version"),
            "source": SOURCE_LIVE,
            "vault": meta.get("vault"),
            "cycle_id": meta.get("cycle_id"),
            "open_run_id": meta.get("open_run_id") or meta.get("run_id"),
            "close_run_id": close_run_id,
            "config_hash": meta.get("config_hash"),
            "git_commit": meta.get("git_commit"),
            "transport_version": meta.get("transport_version"),
            "selecteur": meta.get("selecteur"),
            "ret_coin_bps": ret_coin_bps,
            "ret_marche_bps": ret_market_bps,
            "placebo_marche_bps": placebo_market_bps,
            "alpha_vs_marche_bps": alpha_bps,
            "paper_position_id": meta.get("paper_position_id"),
            "paper_trade_id": trade.trade_id,
            "source_delta_id": trade.source_delta_id,
            "evidence_hash": result.evidence_hash,
            "execution_snapshot_id": trade.execution_snapshot_id,
            "economic_source": ECONOMIC_SOURCE,
        },
    )
    _sauver(coh, root, store)
    if not any(
        opened.get("coin") == pos["coin"]
        for opened in store["ouvertes"].values()
    ):
        _maj_coins_actifs(root, pos["coin"], ajouter=False, now_ms=now_ms)
    return {
        "coin": pos["coin"],
        "realized_usd": trade.realized_pnl_usdt,
        "raison": raison,
        "fraction": round(closed_fraction, 8),
        "paper_trade_id": trade.trade_id,
        "evidence_hash": result.evidence_hash,
        "economic_source": ECONOMIC_SOURCE,
    }


def _sortir(
    coh: Cohorte,
    pos: dict,
    store: dict,
    root: Path,
    *,
    engine,
    execution_truth,
    raison,
    now_ms,
    evidence_ref,
    leader_event_time_ms=None,
    mae_bps=None,
    mfe_bps=None,
    close_run_id=None,
) -> dict:
    return _executer_sortie(
        coh,
        pos,
        store,
        root,
        engine=engine,
        execution_truth=execution_truth,
        fraction=1.0,
        raison=raison,
        now_ms=now_ms,
        evidence_ref=evidence_ref,
        leader_event_time_ms=leader_event_time_ms,
        mae_bps=mae_bps,
        mfe_bps=mfe_bps,
        close_run_id=close_run_id,
    )


def _reduire(
    coh: Cohorte,
    pos: dict,
    store: dict,
    root: Path,
    *,
    engine,
    execution_truth,
    fraction: float,
    now_ms: float,
    evidence_ref: str,
    leader_event_time_ms: float | None = None,
    close_run_id=None,
) -> dict:
    return _executer_sortie(
        coh,
        pos,
        store,
        root,
        engine=engine,
        execution_truth=execution_truth,
        fraction=fraction,
        raison="LEADER_A_REDUIT",
        now_ms=now_ms,
        evidence_ref=evidence_ref,
        leader_event_time_ms=leader_event_time_ms,
        close_run_id=close_run_id,
    )


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
        l2 = _l2_pour_coin(
            coin,
            lecteur_l2=lecteur_l2,
            bbo=_snapshots_bbo(root),
            carnet=_carnet_l2_frais(root, now_ms=now),
            now_ms=now,
            root=root,
        )
        execution_truth = canonical_execution_truth(
            coin,
            l2,
            now_ms=int(now),
        )
        if execution_truth is None:
            return {
                "refus": "NO_LIVE_EXECUTABLE_BOOK",
                "coin": coin,
                "action": "CLOSE",
            }
        from hl_observer.experimental.carry_deux_jambes import frais_venues

        engine = _paper_engine(
            coh,
            etat,
            taker_fee_bps=frais_venues(root)[0],
        )
        evidence_ref = str(
            fill.get("hash")
            or fill.get("tid")
            or fill.get("oid")
            or fill.get("ts_ms")
            or f"{vault}:{coin}:{int(now)}"
        )
        leader_event_time_ms = float(fill.get("ts_ms") or now)
        start = fill.get("start_position")
        sz = abs(float(fill.get("sz") or 0.0))
        if start is None or abs(start) < 1e-9:                     # info absente -> fermeture prudente complète
            outcome = _sortir(
                coh, pos, store, root, engine=engine,
                execution_truth=execution_truth, raison="LEADER_A_CLOS",
                now_ms=now, evidence_ref=evidence_ref,
                leader_event_time_ms=leader_event_time_ms,
                close_run_id=etat.get("run_id"),
            )
            return outcome if outcome.get("refus") else {"fermeture": outcome}
        pos_after = start + sens * sz
        if abs(pos_after) < 1e-9:                                  # CLOSE : le leader ferme entièrement -> on ferme tout
            outcome = _sortir(
                coh, pos, store, root, engine=engine,
                execution_truth=execution_truth, raison="LEADER_A_CLOS",
                now_ms=now, evidence_ref=evidence_ref,
                leader_event_time_ms=leader_event_time_ms,
                close_run_id=etat.get("run_id"),
            )
            return outcome if outcome.get("refus") else {"fermeture": outcome}
        if (start > 0) != (pos_after > 0):                        # FLIP : fermer puis REPASSER l'admission (résidu = nouvel OPEN)
            ferm = _sortir(
                coh, pos, store, root, engine=engine,
                execution_truth=execution_truth, raison="LEADER_A_FLIP",
                now_ms=now, evidence_ref=evidence_ref,
                leader_event_time_ms=leader_event_time_ms,
                close_run_id=etat.get("run_id"),
            )
            if ferm.get("refus"):
                return ferm
            etat["agg"][(vault, coin)] = {"sens": 1 if pos_after > 0 else -1, "notional": abs(pos_after) * float(fill.get("px") or 0.0),
                                          "t0": now, "fill_ts": int(fill.get("ts_ms") or now)}
            return {"fermeture": ferm, "flip": True}
        fraction = min(1.0, sz / abs(start))                      # REDUCE : réduire la copie de la même fraction
        if fraction >= 0.999:
            outcome = _sortir(
                coh, pos, store, root, engine=engine,
                execution_truth=execution_truth, raison="LEADER_A_CLOS",
                now_ms=now, evidence_ref=evidence_ref,
                leader_event_time_ms=leader_event_time_ms,
                close_run_id=etat.get("run_id"),
            )
            return outcome if outcome.get("refus") else {"fermeture": outcome}
        outcome = _reduire(
            coh, pos, store, root, engine=engine,
            execution_truth=execution_truth, fraction=fraction,
            now_ms=now, evidence_ref=evidence_ref,
            leader_event_time_ms=leader_event_time_ms,
            close_run_id=etat.get("run_id"),
        )
        return outcome if outcome.get("refus") else {"reduction": outcome}
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
        if not coh.edge_requis:
            _maj_coins_prewarm(root, coin, now_ms=now)             # RAW : lance l'abonnement L2 WS EN PARALLÈLE
    # DÉCLENCHEUR SIGNIFICATIF RELATIF AU VAULT (remplace le seuil fixe unique) : cumulé >= max(plancher
    # exécutable, frac × TVL). Petit vault -> plancher ; gros vault -> conviction proportionnelle.
    signif, _seuil = _declencheur_significatif(coh, vault, ag["notional"], root)
    if not signif:
        return None                                               # pas encore un OPEN/ADD significatif pour CE vault
    etat["agg"].pop(key, None)
    t_dec = time.monotonic()                                     # HORLOGE MONOTONE LOCALE : décision
    cle = _cle(coh, vault, coin)
    _trig = _params_trigger(root).get("variante", "v1")          # étiquette éditable (indicative)
    _chash_gate = config_hash_courant(coh, root)                 # clé de config pour le gate (RAW = identique au stamp)
    if not cohorte_active(coh, root, trigger_version=_trig, config_hash=_chash_gate):   # AUTO-KILL : config COURANTE seule
        return {"refus": "COHORTE_EN_PAUSE_AUTO_KILL", "coin": coin}
    if not coh.edge_requis:                                       # RAW = baseline minuscule : FIGÉE à N cycles clôturés
        n_clot = _expectancy(coh, root, config_hash=_chash_gate).get("n_trades", 0)   # cycles config COURANTE (run-agnostique)
        if n_clot >= RAW_BASELINE_MAX_CYCLES:                     # jamais promue ; ne perd pas indéfiniment -> on FIGE pour décision
            return {"refus": "RAW_BASELINE_FIGEE_%d" % RAW_BASELINE_MAX_CYCLES, "coin": coin, "cycles_clotures": n_clot}
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
                       carnet=_carnet_l2_frais(root, now_ms=now), now_ms=now, root=root)
    t_l2 = time.monotonic()                                      # MONOTONE : L2 obtenu
    if not l2:
        return {"refus": "L2_INDISPONIBLE_1S", "coin": coin}
    execution_truth = canonical_execution_truth(
        coin,
        l2,
        now_ms=int(now),
    )
    if execution_truth is None:
        return {"refus": "NO_LIVE_EXECUTABLE_BOOK", "coin": coin}
    from hl_observer.experimental.carry_deux_jambes import frais_venues
    fhl = frais_venues(root)[0]
    hl_bid, hl_ask = l2["hl_bid"], l2["hl_ask"]
    mid = (hl_bid + hl_ask) / 2.0
    ref = _allmids(root, now_ms=now).get(coin)                    # garde-fou : prix L2 plausible vs allMids
    if ref and ref > 0 and abs(mid - ref) / ref > 0.10:           # >10 % d'écart = L2 aberrant/injecté -> refus
        return {"refus": "L2_ABERRANT", "coin": coin, "mid": round(mid, 6), "ref": round(ref, 6)}
    spread = (hl_ask - hl_bid) / mid * 1e4
    depth = execution_truth.visible_notional(
        "BUY" if sens > 0 else "SELL"
    )
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
    # ÂGE RÉEL À L'EXÉCUTION PAPER = fill leader -> réception -> décision -> acquisition L2 -> open (PAS juste
    # l'âge à la décision : les 2 1ers trades faisaient ~1,7 s, pas 317/769 ms). ENTRÉE refusée si trop tardive.
    age_paper = round(now - float(fill.get("ts_ms") or now) + (t_open - t_dec) * 1000)
    if age_paper > AGE_MAX_PAPER_FILL_MS:
        return {"refus": "ENTREE_TROP_TARDIVE", "coin": coin, "age_at_paper_fill_ms": age_paper}
    lat_mono = {"ws_decision_ms": round((t_dec - t0) * 1000, 1), "decision_l2_ms": round((t_l2 - t_dec) * 1000, 1),
                "l2_open_ms": round((t_open - t_l2) * 1000, 1), "ws_open_ms": round((t_open - t0) * 1000, 1),
                "age_event_ms": round(now - float(fill.get("ts_ms") or now)),   # HL ts à la décision (skew possible)
                "age_at_paper_fill_ms": age_paper}                              # DÉLAI TOTAL à l'exécution paper
    _chash = _config_hash(coh, cfg, fhl, root)                   # STAMP : cfg RÉEL (stop/TP/horizon par coin) + frais réels
    placebo = {"mid_coin_open": round(mid, 8), "mid_marche_open": _allmids(root, now_ms=now).get("BTC"), "ts_open": now}
    engine = _paper_engine(coh, etat, taker_fee_bps=fhl)
    evidence_ref = str(
        fill.get("hash")
        or fill.get("tid")
        or fill.get("oid")
        or fill.get("ts_ms")
        or f"{vault}:{coin}:{int(now)}"
    )
    pos = _ouvrir(
        coh,
        store,
        root,
        cle=cle,
        coin=coin,
        sens=sens,
        notional=notional,
        prix=prix,
        cfg=cfg,
        cout_ar=cout_ar,
        spread=spread,
        slippage=slippage,
        fhl=fhl,
        vault=vault,
        now_ms=now,
        fill_ts=ag["fill_ts"],
        lat_mono=lat_mono,
        engine=engine,
        execution_truth=execution_truth,
        evidence_ref=evidence_ref,
        run_id=etat.get("run_id", ""),
        src_l2=str(l2.get("src") or execution_truth.source),
        marque=coh.marque,
        trigger_version=_trig,
        placebo=placebo,
        config_hash=_chash,
        git_commit=etat.get("git_commit", ""),
        transport_version=etat.get("transport_version", ""),
    )
    if pos.get("refus"):
        return pos
    return {"ouverture": pos, "latence_ws_open_ms": lat_mono["ws_open_ms"], "paire": cle,
            "age_at_paper_fill_ms": age_paper}


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


def gerer_exits(coh: Cohorte, root: Path, *, now_ms: float | None = None, lecteur_l2=None, close_run_id=None) -> list[dict]:
    """Sorties par PRIX/TEMPS (stop calibré / take-profit / horizon) — complète les sorties leader inline.
    MAE/MFE suivis en continu."""
    now = float(now_ms if now_ms is not None else time.time() * 1000)
    store = charger_store(coh, root)
    from hl_observer.experimental.carry_deux_jambes import frais_venues

    etat = {"store": store, "paper_engine": None}
    engine = _paper_engine(
        coh,
        etat,
        taker_fee_bps=frais_venues(root)[0],
    )
    fermetures = []
    for pos in list(store["ouvertes"].values()):
        l2 = _l2_pour_coin(
            pos["coin"],
            lecteur_l2=lecteur_l2,
            bbo=_snapshots_bbo(root),
            carnet=_carnet_l2_frais(root, now_ms=now),
            now_ms=now,
            root=root,
        )
        execution_truth = canonical_execution_truth(
            pos["coin"],
            l2,
            now_ms=int(now),
        )
        if execution_truth is None or not pos.get("prix_entree"):
            continue
        mark = execution_truth.mid_price
        exc = pos["sens"] * (mark - pos["prix_entree"]) / pos["prix_entree"] * 1e4
        pos["mae_bps"] = round(min(pos.get("mae_bps", 0.0), exc), 3)
        pos["mfe_bps"] = round(max(pos.get("mfe_bps", 0.0), exc), 3)
        meta = pos.get("meta", {})
        stop = float(meta.get("stop_bps") or coh.stop_bps_defaut)
        tp = meta.get("take_profit_bps")
        raison = None
        if exc <= -stop:
            raison = "STOP_PERTE"
        elif tp and exc >= float(tp):
            raison = "TAKE_PROFIT"
        elif (now - float(pos.get("ts_ouverture_ms") or now)) >= float(pos.get("hold_h") or 1.0) * 3_600_000.0:
            raison = "HORIZON_ATTEINT"
        if raison:
            outcome = _sortir(
                coh,
                pos,
                store,
                root,
                engine=engine,
                execution_truth=execution_truth,
                raison=raison,
                now_ms=now,
                evidence_ref=(
                    f"exit:{pos.get('meta', {}).get('paper_position_id')}:"
                    f"{raison}:{int(now)}"
                ),
                leader_event_time_ms=now,
                mae_bps=pos.get("mae_bps"),
                mfe_bps=pos.get("mfe_bps"),
                close_run_id=close_run_id,
            )
            fermetures.append(outcome)
    _sauver(coh, root, store)
    return fermetures


def statut(coh: Cohorte, root: Path, *, now_ms: float | None = None, lecteur_l2=None,
           run_id: str | None = None, trigger_version: str | None = None, config_hash: str | None = None) -> dict:
    now = float(now_ms if now_ms is not None else time.time() * 1000)
    store = charger_store(coh, root)
    from hl_observer.experimental.carry_deux_jambes import frais_venues

    engine = _build_canonical_engine(
        coh,
        store,
        taker_fee_bps=frais_venues(root)[0],
    )
    marks: dict[str, float] = {}
    for pos in store["ouvertes"].values():
        l2 = _l2_pour_coin(
            pos["coin"],
            lecteur_l2=lecteur_l2,
            bbo=_snapshots_bbo(root),
            carnet=_carnet_l2_frais(root, now_ms=now),
            now_ms=now,
            root=root,
        )
        execution_truth = canonical_execution_truth(
            pos["coin"],
            l2,
            now_ms=int(now),
        )
        if execution_truth is not None:
            marks[pos["coin"]] = (
                execution_truth.best_bid
                if int(pos.get("sens") or 0) > 0
                else execution_truth.best_ask
            )
    equity, non_realise, drawdown = engine.mark_to_market(marks)
    ledger_snapshot = engine.ledger.snapshot()
    store["canonical_ledger_snapshot"] = ledger_snapshot
    st = {"cohorte": coh.nom, "real_execution": False, "ts_ms": int(now),
          "active": cohorte_active(coh, root, run_id=run_id, trigger_version=trigger_version, config_hash=config_hash),
          "config": {"run_id": run_id, "trigger_version": trigger_version, "config_hash": config_hash},
          "budget_usd": coh.budget_usd, "cash": store["cash"], "positions_ouvertes": len(store["ouvertes"]),
          "realise_total_usd": store.get("realise_total_usd", 0.0), "non_realise_usd": round(non_realise, 4),
          "equity_usd": round(equity, 4), "drawdown_usd": round(drawdown, 4),
          "roi_cumulatif_pct": round((equity - coh.budget_usd) / coh.budget_usd * 100, 3),
          "economic_source": ECONOMIC_SOURCE, "mark_source": "EXECUTABLE_L2_ONLY",
          "canonical_ledger_snapshot": ledger_snapshot,
          "expectancy": _expectancy(coh, root, run_id=run_id, trigger_version=trigger_version, config_hash=config_hash),
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
