"""Intentions des leaders : quelle part de leurs exécutions était VISIBLE à l'avance, et que valait-elle ?

Copier un fill, c'est arriver après : le prix a déjà bougé, et il faut payer l'écart et les frais
taker pour rattraper. Or Hyperliquid publie les ordres en attente de chaque compte (famille
``leader_orders`` du coffre). Si un leader pose ses entrées et ses sorties à l'avance, un copieur
peut les lire AVANT leur exécution et poser un ordre jumeau au même prix : même instant, même prix,
frais maker au lieu de frais taker.

Ce module mesure, sans rien supposer :

1. l'ANTICIPABILITÉ — la part du notionnel exécuté par un leader dont l'ordre était visible au
   moins ``min_lead_ms`` avant l'exécution, et de combien de temps ;
2. une BORNE HAUTE de la valeur d'un ordre jumeau — le prix, 1 h et 4 h après l'exécution, comparé
   au prix limite du leader, net d'une entrée maker et d'une sortie taker. Borne haute, car elle
   suppose que l'ordre jumeau est exécuté chaque fois que celui du leader l'est (il passe après
   lui dans la file : en réalité il est exécuté moins souvent, et plutôt quand le prix traverse) ;
3. un REJEU PRUDENT de l'ordre jumeau (``twin_order_replay``) — posé après le délai de réaction, au
   prix du leader, il n'est réputé exécuté que si le prix TRAVERSE ce niveau (une clôture strictement
   au-delà) : il passe derrière le leader dans la file, donc une simple touche ne le sert pas. Il
   reste en place jusqu'à ce que la disparition de l'ordre du leader ait pu être observée, délai
   d'annulation compris — c'est pendant ce temps qu'il se fait exécuter à contre-courant. Les
   non-exécutions sont comptées : un ordre jumeau jamais servi ne rapporte rien et ne coûte rien.

Garde-fous : seuls comptent les fills survenus pendant que le carnet d'ordres du leader était suivi ;
un carnet résumé (teneur de marché, des centaines de cotations) n'apporte aucun ordre détaillé et le
leader est écarté, compté à part ; un ordre doit avoir été revu peu avant son exécution (sinon la
vue était interrompue et rien ne prouve qu'il existait encore).

Résultat EXPLORATOIRE : une précondition d'information, jamais une preuve de rentabilité.
"""
from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import asdict, dataclass
from typing import Any

import numpy as np
import pandas as pd

from hl_observer.backtesting.copy_vault_event_study import EventStudyConfig, intervalle_blocs, serie_par_jour
from hl_observer.fees.hyperliquid_fees import MAKER_PERP_BPS, TAKER_PERP_BPS

DAY_MS = 86_400_000
HOUR_MS = 3_600_000
SCHEMA_VERSION = "hypersmart.copy_vault_order_intent.v1"
H_ORDER_INTENT = "copy_vault_leader_order_intent"


@dataclass(frozen=True, slots=True)
class OrderIntentConfig:
    """Paramètres déclarés AVANT la mesure."""

    min_lead_ms: int = 60_000            # ordre vu au moins 60 s avant son exécution : anticipable
    max_gap_ms: int = 900_000            # et revu dans les 15 min qui précèdent (vue non interrompue)
    horizons_h: tuple[int, ...] = (1, 4)
    reaction_ms: int = 60_000            # délai entre l'observation d'un ordre et la pose du jumeau
    cancel_delay_ms: int = 300_000       # délai pour constater la disparition de l'ordre et annuler le jumeau
    anticipable_share_required: float = 0.30
    min_days: int = 5
    min_fills: int = 200
    min_leaders: int = 5
    maker_fee_bps: float = MAKER_PERP_BPS
    taker_fee_bps: float = TAKER_PERP_BPS
    bootstrap_samples: int = 2_000
    confidence: float = 0.95
    seed: int = 20_261_111

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def order_lifetimes(snapshots: Iterable[Mapping[str, Any]]) -> tuple[pd.DataFrame, dict[str, dict[str, Any]]]:
    """Vie observée de chaque ordre : ``(table des ordres, suivi par leader)``.

    Table : une ligne par ``(vault, dex, oid)`` avec premier et dernier instant où l'ordre a été VU.
    Suivi : par leader, fenêtre couverte et nombre de carnets détaillés ou résumés."""
    ordres: dict[tuple[str, str, int], dict[str, Any]] = {}
    suivi: dict[str, dict[str, Any]] = {}
    for snap in snapshots:
        vault, ts = str(snap.get("vault") or "").lower(), snap.get("ts_ms")
        if not vault or type(ts) is not int or ts <= 0 or not isinstance(snap.get("orders"), list):
            continue
        etat = suivi.setdefault(vault, {"debut_ms": ts, "fin_ms": ts, "carnets": 0, "carnets_resumes": 0})
        etat["debut_ms"], etat["fin_ms"] = min(etat["debut_ms"], ts), max(etat["fin_ms"], ts)
        etat["carnets"] += 1
        if snap.get("tronque"):
            etat["carnets_resumes"] += 1
            continue
        dex = str(snap.get("dex") or "")
        for ordre in snap["orders"]:
            cle = (vault, dex, ordre["oid"])
            vie = ordres.get(cle)
            if vie is None:
                ordres[cle] = {"vault": vault, "dex": dex, "oid": ordre["oid"], "coin": ordre["coin"],
                               "side": ordre["side"], "px": float(ordre["px"]), "genre": ordre.get("genre") or "",
                               "premier_ms": ts, "dernier_ms": ts, "vues": 1}
            else:
                vie["premier_ms"], vie["dernier_ms"] = min(vie["premier_ms"], ts), max(vie["dernier_ms"], ts)
                vie["vues"] += 1
                if ts >= vie["dernier_ms"]:
                    vie["px"] = float(ordre["px"])          # un ordre modifié garde son identité : dernier prix vu
    colonnes = ["vault", "dex", "oid", "coin", "side", "px", "genre", "premier_ms", "dernier_ms", "vues"]
    return pd.DataFrame(list(ordres.values()), columns=colonnes), suivi


def match_fills(fills: pd.DataFrame, vies: pd.DataFrame, suivi: Mapping[str, Mapping[str, Any]],
                config: OrderIntentConfig | None = None) -> pd.DataFrame:
    """Fills survenus pendant le suivi du carnet de leur leader, rapprochés de l'ordre qui les a produits.

    Colonnes ajoutées : ``avance_ms`` (exécution − première vue de l'ordre ; ``NaN`` si jamais vu),
    ``anticipable``, ``px_ordre``, ``genre``."""
    config = config or OrderIntentConfig()
    if not len(fills):
        return fills.assign(avance_ms=[], anticipable=[], px_ordre=[], genre=[])
    debut = fills["vault"].map(lambda v: (suivi.get(v) or {}).get("debut_ms", np.nan)).to_numpy(dtype=float)
    fin = fills["vault"].map(lambda v: (suivi.get(v) or {}).get("fin_ms", np.nan)).to_numpy(dtype=float)
    detaille = fills["vault"].map(
        lambda v: bool(suivi.get(v)) and suivi[v]["carnets"] > suivi[v]["carnets_resumes"]).to_numpy(dtype=bool)
    temps = fills["time"].to_numpy(dtype=float)
    couverts = fills.loc[detaille & (temps >= debut) & (temps <= fin)].copy()
    if not len(couverts):
        return couverts.assign(avance_ms=[], anticipable=[], px_ordre=[], genre=[])
    # un oid est unique sur la plateforme : pas besoin du dex pour rapprocher
    cles = vies.drop_duplicates(["vault", "oid"])[["vault", "oid", "px", "genre", "premier_ms", "dernier_ms"]]
    joint = couverts.merge(cles, how="left", on=["vault", "oid"], suffixes=("", "_ordre"))
    joint["avance_ms"] = joint["time"] - joint["premier_ms"]
    revu = (joint["time"] - joint["dernier_ms"]) <= config.max_gap_ms
    joint["anticipable"] = (joint["avance_ms"] >= config.min_lead_ms) & revu
    joint["px_ordre"] = joint["px_ordre"] if "px_ordre" in joint.columns else joint["px"]
    joint["genre"] = joint["genre"].fillna("")
    return joint.drop(columns=["premier_ms", "dernier_ms"])


def twin_order_replay(vies: pd.DataFrame, panel: Any, half_spread_bps: Mapping[str, float],
                      config: OrderIntentConfig | None = None, *, genres: tuple[str, ...] = ("ENTREE_LIMITE",),
                      ) -> dict[str, Any]:
    """Rejeu prudent d'un ordre jumeau pour chaque ordre d'entrée observé.

    ``vies`` : sortie de ``order_lifetimes``. ``panel`` : prix de clôture réguliers (``ts`` croissant).
    Exécution : première clôture STRICTEMENT au-delà du prix limite pendant que le jumeau est en place
    (de ``première vue + réaction`` à ``dernière vue + délai d'annulation``). Entrée au prix limite
    (frais maker), sortie au prix du marché ``horizon`` plus tard (frais taker + demi-écart)."""
    config = config or OrderIntentConfig()
    base = {"ordres_d_entree": 0, "jumeaux_executes": 0, "taux_d_execution": None, "sans_prix": 0}
    entrees = vies[vies["genre"].isin(genres)] if len(vies) else vies
    if not len(entrees) or panel is None or len(panel.ts) < 2:
        return base
    ts = np.asarray(panel.ts, dtype=np.int64)
    lignes: list[dict[str, Any]] = []
    sans_prix = 0
    for ordre in entrees.itertuples():
        colonne = panel.column(ordre.coin)
        if colonne is None:
            sans_prix += 1
            continue
        pose, retire = int(ordre.premier_ms) + config.reaction_ms, int(ordre.dernier_ms) + config.cancel_delay_ms
        debut, fin = int(np.searchsorted(ts, pose, side="right")), int(np.searchsorted(ts, retire, side="right"))
        if fin <= debut:
            continue                                          # l'ordre a disparu avant que le jumeau soit posé
        cloture = np.asarray(panel.px[debut:fin, colonne], dtype=float)
        signe = 1.0 if ordre.side == "B" else -1.0
        with np.errstate(invalid="ignore"):
            traverse = np.flatnonzero(signe * (cloture - float(ordre.px)) < 0)      # achat : clôture SOUS le prix limite
        if not traverse.size:
            continue                                          # jamais traversé : jumeau non exécuté, retiré
        instant = int(ts[debut + int(traverse[0])])
        lignes.append({"unit": ordre.vault, "coin": ordre.coin, "signe": signe, "px": float(ordre.px),
                       "execution_ms": instant, "jour": instant // DAY_MS, "colonne": colonne})
    sortie: dict[str, Any] = {**base, "ordres_d_entree": int(len(entrees)), "sans_prix": sans_prix,
                              "jumeaux_executes": len(lignes),
                              "taux_d_execution": len(lignes) / max(1, len(entrees) - sans_prix)}
    if not lignes:
        return sortie
    table = pd.DataFrame(lignes)
    demi_ecart = table["coin"].map(lambda c: half_spread_bps.get(c, np.nan)).to_numpy(dtype=float)
    cout = config.maker_fee_bps + config.taker_fee_bps + demi_ecart
    niveau = 1.0 - (1.0 - config.confidence) / max(1, len(config.horizons_h))
    reglages = EventStudyConfig(bootstrap_samples=config.bootstrap_samples, seed=config.seed)
    instants, colonnes = table["execution_ms"].to_numpy(dtype=np.int64), table["colonne"].to_numpy(dtype=np.int64)
    for horizon in config.horizons_h:
        brut = table["signe"].to_numpy() * (panel.at(instants + horizon * HOUR_MS, colonnes) / table["px"].to_numpy() - 1.0) * 1e4
        for nom, valeurs in (("brut", brut), ("net", brut - cout)):
            serie = serie_par_jour(table.assign(_v=valeurs), "_v").to_numpy(dtype=float)
            sortie[f"{nom}_{horizon}h"] = {
                "jours": int(serie.size), "moyenne_bps": float(serie.mean()) if serie.size else None,
                "intervalle_bps": intervalle_blocs(serie, bloc=1, niveau=niveau, config=reglages),
                "jumeaux_mesures": int(np.isfinite(valeurs).sum())}
    sortie["leaders"] = int(table["unit"].nunique())
    return sortie


def _part(notionnel: pd.Series, masque: pd.Series) -> float | None:
    total = float(notionnel.sum())
    return float(notionnel[masque].sum() / total) if total > 0 else None


def run_order_intent_study(
    snapshots: Iterable[Mapping[str, Any]], fills: pd.DataFrame, config: OrderIntentConfig | None = None, *,
    panel: Any | None = None, half_spread_bps: Mapping[str, float] | None = None,
) -> dict[str, Any]:
    """Étude complète. ``fills`` : fills OBSERVÉS (``vault, coin, time, oid, signe, crossed, is_open, notional``).
    ``panel`` (facultatif) : prix pour la borne haute de valeur d'un ordre jumeau."""
    config = config or OrderIntentConfig()
    vies, suivi = order_lifetimes(snapshots)
    base = {"schema_version": SCHEMA_VERSION, "mechanism": "copy_vault_order_intent_v1", "config": config.as_dict(),
            "paper_read_only": True, "real_execution": False, "economically_proven": False,
            "caveats": [
                "La valeur d'un ordre jumeau est une BORNE HAUTE : elle suppose une exécution à chaque fois que "
                "l'ordre du leader est exécuté, alors que le jumeau passe après lui dans la file.",
                "Un carnet résumé (teneur de marché) n'apporte aucun ordre détaillé : ces leaders sont écartés.",
                "Tier LOCAL, exploratoire : une précondition d'information, jamais une preuve de rentabilité.",
            ]}
    if not suivi:
        return {**base, "inputs": {"carnets": 0, "leaders_suivis": 0},
                "verdicts": [{"hypothesis": H_ORDER_INTENT, "status": "UNMEASURABLE", "economically_proven": False,
                              "reason": "aucun carnet d'ordres de leader au coffre"}]}
    table = match_fills(fills, vies, suivi, config)
    resumes = sorted(v for v, etat in suivi.items() if etat["carnets"] == etat["carnets_resumes"])
    jours = sorted({int(t) // DAY_MS for t in table["time"]}) if len(table) else []
    entrees = {"carnets": int(sum(etat["carnets"] for etat in suivi.values())), "leaders_suivis": len(suivi),
               "leaders_au_carnet_resume": len(resumes), "ordres_distincts": int(len(vies)),
               "fills_pendant_le_suivi": int(len(table)), "jours": len(jours),
               "leaders_avec_fills": int(table["vault"].nunique()) if len(table) else 0}
    mesures: dict[str, Any] = {}
    if len(table):
        vus = table["avance_ms"].notna()
        passifs = table["crossed"] == 0.0
        mesures = {
            "part_notionnel_ordre_vu": _part(table["notional"], vus),
            "part_notionnel_anticipable": _part(table["notional"], table["anticipable"]),
            "part_notionnel_passif_anticipable": _part(table.loc[passifs, "notional"], table.loc[passifs, "anticipable"]),
            "part_notionnel_agressif_anticipable": _part(table.loc[~passifs, "notional"], table.loc[~passifs, "anticipable"]),
            "avance_mediane_s": float(table.loc[table["anticipable"], "avance_ms"].median() / 1000.0)
            if table["anticipable"].any() else None,
            "par_genre": {genre: {"fills": int(len(groupe)), "notionnel_usd": float(groupe["notional"].sum())}
                          for genre, groupe in table.loc[table["anticipable"]].groupby("genre")},
            "par_leader": sorted(
                ({"vault": vault, "fills": int(len(g)), "notionnel_usd": float(g["notional"].sum()),
                  "part_anticipable": _part(g["notional"], g["anticipable"])} for vault, g in table.groupby("vault")),
                key=lambda ligne: -ligne["notionnel_usd"])[:40],
        }
    valeur: dict[str, Any] = {}
    if panel is not None and len(table) and table["anticipable"].any():
        valeur = _valeur_ordre_jumeau(table.loc[table["anticipable"] & (table["is_open"].astype(bool))], panel,
                                      half_spread_bps or {}, config)
    rejeu = twin_order_replay(vies, panel, half_spread_bps or {}, config) if panel is not None else {}
    part = mesures.get("part_notionnel_anticipable")
    verdict = {"hypothesis": H_ORDER_INTENT, "economically_proven": False}
    if (entrees["jours"] < config.min_days or entrees["fills_pendant_le_suivi"] < config.min_fills
            or entrees["leaders_avec_fills"] < config.min_leaders or part is None):
        verdict.update(status="MORE_DATA",
                       reason=f"{entrees['jours']} jour(s), {entrees['fills_pendant_le_suivi']} fill(s), "
                              f"{entrees['leaders_avec_fills']} leader(s) pendant le suivi des carnets ; il en faut au "
                              f"moins {config.min_days}, {config.min_fills} et {config.min_leaders}")
    elif part >= config.anticipable_share_required:
        verdict.update(status="PROMISING",
                       reason=f"{part * 100:.0f} % du notionnel exécuté était visible au moins {config.min_lead_ms // 1000} s "
                              "à l'avance : la simulation d'ordres jumeaux (file d'attente, non-exécution) est justifiée")
    else:
        verdict.update(status="REJECTED",
                       reason=f"seulement {part * 100:.0f} % du notionnel exécuté était visible à l'avance : les ordres en "
                              "attente n'annoncent pas les exécutions de ces leaders")
    return {**base, "inputs": entrees, "anticipability": mesures, "twin_order_upper_bound": valeur,
            "twin_order_replay": rejeu, "verdicts": [verdict]}


def _valeur_ordre_jumeau(table: pd.DataFrame, panel: Any, half_spread_bps: Mapping[str, float],
                         config: OrderIntentConfig) -> dict[str, Any]:
    colonne = table["coin"].map(lambda c: -1 if panel.column(c) is None else panel.column(c)).to_numpy()
    connu = colonne >= 0
    travail = table.loc[connu].copy()
    if not len(travail):
        return {}
    colonne = colonne[connu].astype(np.int64)
    signe = travail["signe"].to_numpy(dtype=float)
    temps = travail["time"].to_numpy(dtype=np.int64)
    prix_ordre = travail["px_ordre"].to_numpy(dtype=float)
    demi_ecart = travail["coin"].map(lambda c: half_spread_bps.get(c, np.nan)).to_numpy(dtype=float)
    cout = config.maker_fee_bps + config.taker_fee_bps + demi_ecart       # entrée passive, sortie agressive
    travail["jour"] = temps // DAY_MS
    travail["unit"] = travail["vault"]
    niveau = 1.0 - (1.0 - config.confidence) / max(1, len(config.horizons_h))
    reglages = EventStudyConfig(bootstrap_samples=config.bootstrap_samples, seed=config.seed)
    sortie: dict[str, Any] = {"fills_d_entree_anticipables": int(len(travail))}
    for horizon in config.horizons_h:
        brut = signe * (panel.at(temps + horizon * HOUR_MS, colonne) / prix_ordre - 1.0) * 1e4
        for nom, valeurs in (("brut", brut), ("net", brut - cout)):
            serie = serie_par_jour(travail.assign(_v=valeurs), "_v").to_numpy(dtype=float)
            sortie[f"{nom}_{horizon}h"] = {
                "jours": int(serie.size), "moyenne_bps": float(serie.mean()) if serie.size else None,
                "intervalle_bps": intervalle_blocs(serie, bloc=1, niveau=niveau, config=reglages)}
    return sortie


__all__ = ["H_ORDER_INTENT", "OrderIntentConfig", "SCHEMA_VERSION", "match_fills", "order_lifetimes",
           "run_order_intent_study", "twin_order_replay"]
