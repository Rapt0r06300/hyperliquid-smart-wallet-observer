"""Étude d'événements : les décisions AGRESSIVES des leaders gardent-elles une valeur après observation ?

CONSTAT DE DÉPART (corpus certifié, 4,8 M de fills observés). Deux tiers des fills des leaders sont
passifs (ordres en attente) : ils gagnent l'écart puis le reperdent en sélection adverse, soit à
peu près zéro avant frais. Les copier revient à payer des frais pour du bruit d'inventaire. Les
fills AGRESSIFS (le leader paie l'écart pour entrer tout de suite) sont l'inverse : le prix
continue dans leur sens. La question est de savoir ce qu'il en reste pour un copieur, c'est-à-dire
APRÈS le délai d'observation, à un horizon assez long pour amortir un aller-retour de frais.

HYPOTHÈSE (falsifiable). Suivre seulement les ouvertures agressives d'un leader, entrer au premier
prix publié après l'observation, tenir un horizon fixe : le rendement net de frais et d'écart est
positif, et il dépasse ce que la même position aurait rapporté 7 et 14 jours plus tôt (témoins :
même coin, même sens — ils retirent la tendance du coin et le biais directionnel du leader).

GARDE-FOUS.
* Une DÉCISION, pas un fill : les fills d'un même leader, coin, sens et type, rapprochés dans le
  temps, forment un seul événement ; les clones d'un même opérateur comptent pour un seul leader.
* Pas de chevauchement : tant qu'une position issue d'un événement est tenue, les événements
  suivants du même leader sur le même coin et le même sens sont ignorés.
* Entrée au premier prix publié APRÈS ``observation + réaction`` (jamais avant) ; coût = deux fois
  (frais taker + demi-écart mesuré). Écart inconnu : net inconnu, jamais supposé nul.
* Deux populations, jamais mélangées. OBSERVÉE EN DIRECT : le premier fill de la décision a été vu
  par nos collecteurs dans les 5 minutes — l'instant d'observation est réel et le leader était déjà
  suivi. RECONSTRUITE : fill récupéré après coup (backfill, ou relevé tardif après un arrêt des
  collecteurs) — l'instant d'observation est SUPPOSÉ, et le leader a pu être choisi plus tard sur
  ses résultats passés, ce qui flatte ses anciennes décisions. Le verdict ne lit que la première.
* Une moyenne par (jour, leader) puis par jour : un leader hyperactif ne compte pas mille fois ;
  intervalles par bootstrap de blocs de jours, élargis par le nombre de cellules essayées.

Résultat EXPLORATOIRE : au mieux PROMISING, à confirmer par le moteur PAPER sur des jours nouveaux.
"""
from __future__ import annotations

import hashlib
from collections.abc import Mapping
from dataclasses import asdict, dataclass
from typing import Any

import numpy as np
import pandas as pd

from hl_observer.backtesting.copy_vault_protocol import PAPER_EQUITY_USD
from hl_observer.fees.hyperliquid_fees import MIN_ORDER_VALUE_USD, TAKER_PERP_BPS

DAY_MS = 86_400_000
HOUR_MS = 3_600_000
SCHEMA_VERSION = "hypersmart.copy_vault_event_study.v2"
H_AGGRESSIVE_OPEN = "copy_vault_aggressive_open_drift"
H_SELECTED_LEADERS = "copy_vault_aggressive_open_selected_leaders"
SEGMENTS = ("TAKER_OPEN", "MAKER_OPEN", "TAKER_CLOSE")
PERIODES = ("OBSERVEE_EN_DIRECT", "RECONSTRUITE")
#: au-delà de ce délai entre le fill et son observation, la décision n'a pas été vue « en direct »
MAX_DELAI_OBSERVATION_DIRECTE_MS = 300_000
_IDENTITE_FILL = ("vault", "coin", "time", "tid", "oid", "px", "sz", "signe")


@dataclass(frozen=True, slots=True)
class EventStudyConfig:
    """Paramètres déclarés AVANT la mesure. La première valeur de chaque grille est l'analyse primaire."""

    horizons_h: tuple[int, ...] = (4, 1, 24)
    segments: tuple[str, ...] = SEGMENTS
    cluster_gap_ms: int = 300_000          # fills rapprochés de moins de 5 min = une seule décision
    min_event_usd: float = 1_000.0         # en dessous, ce n'est pas une décision du leader
    reaction_ms: int = 60_000
    control_offsets_days: tuple[int, ...] = (7, 14)
    taker_fee_bps: float = TAKER_PERP_BPS
    min_days: int = 30
    min_events: int = 200
    min_units: int = 10
    bootstrap_samples: int = 2_000
    confidence: float = 0.95
    seed: int = 20_261_111
    capital_usd: float = PAPER_EQUITY_USD
    slots: int = 5                         # 350 USD en 5 lignes de 70 USD, sans levier
    # Sélection en marche avant : un leader n'est suivi qu'après ``selection_min_history`` décisions
    # DÉNOUÉES, et seulement si leur net moyen, ramené vers zéro comme s'il avait déjà fait
    # ``selection_prior_events`` décisions nulles, est positif.
    selection_min_history: int = 20
    selection_prior_events: float = 20.0
    min_order_usd: float = MIN_ORDER_VALUE_USD

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


# --------------------------------------------------------------------------- réunion des fills

def assembler_fills(observes: pd.DataFrame, reconstruits: pd.DataFrame, *, assumed_lag_ms: int) -> pd.DataFrame:
    """Réunit les fills OBSERVÉS par nos collecteurs et les fills RECONSTRUITS (backfill), déjà préparés.

    Colonne ``post`` : vrai si le fill a été observé en direct (délai réel d'au plus 5 minutes).
    Pour tous les autres — backfill, ou fill relevé longtemps après (collecteurs arrêtés) — l'instant
    d'observation est remplacé par ``fill + assumed_lag_ms`` : une HYPOTHÈSE, déclarée comme telle.
    Un fill présent des deux côtés est gardé une fois, dans sa version observée en direct."""
    observes = observes.copy()
    observes["post"] = (observes["obs"] - observes["time"]) <= MAX_DELAI_OBSERVATION_DIRECTE_MS
    reconstruits = reconstruits.copy()
    reconstruits["post"] = False
    reunis = pd.concat([observes, reconstruits], ignore_index=True)
    if not len(reunis):
        return reunis
    reunis = reunis.sort_values("post", ascending=False, kind="stable").drop_duplicates(list(_IDENTITE_FILL), keep="first")
    suppose = ~reunis["post"].to_numpy(dtype=bool)
    reunis.loc[suppose, "obs"] = reunis.loc[suppose, "time"] + int(assumed_lag_ms)
    return reunis.sort_values(["vault", "coin", "time", "tid"], kind="stable").reset_index(drop=True)


# --------------------------------------------------------------------------- événements

def build_events(fills: pd.DataFrame, units: Mapping[str, str], config: EventStudyConfig | None = None) -> pd.DataFrame:
    """Regroupe les fills en décisions. Colonnes attendues : ``vault, coin, time, obs, signe, crossed,
    is_open, notional`` et, si connue, ``post`` (le fill a été observé en direct, voir ``assembler_fills``)."""
    config = config or EventStudyConfig()
    colonnes = ["unit", "coin", "signe", "segment", "t0", "obs", "notional", "n_fills", "post"]
    if not len(fills):
        return pd.DataFrame(columns=colonnes)
    crossed, ouverture = fills["crossed"].to_numpy(), fills["is_open"].to_numpy().astype(bool)
    segment = np.select(
        [(crossed == 1.0) & ouverture, (crossed == 0.0) & ouverture, (crossed == 1.0) & ~ouverture],
        [0, 1, 2], default=-1)
    garde = segment >= 0
    if not garde.any():
        return pd.DataFrame(columns=colonnes)
    unit = fills["vault"].map(units).fillna(fills["vault"]).astype(str).to_numpy()[garde]
    coin = fills["coin"].astype(str).to_numpy()[garde]
    temps = fills["time"].to_numpy().astype(np.int64)[garde]
    obs = fills["obs"].to_numpy().astype(np.int64)[garde]
    signe = fills["signe"].to_numpy().astype(np.int8)[garde]
    notionnel = fills["notional"].to_numpy().astype(float)[garde]
    post = (fills["post"].to_numpy().astype(bool)[garde] if "post" in fills.columns
            else np.zeros(int(garde.sum()), dtype=bool))
    segment = segment[garde]
    code_unit, noms_unit = pd.factorize(unit)
    code_coin, noms_coin = pd.factorize(coin)
    ordre = np.lexsort((temps, segment, signe, code_coin, code_unit))
    cu, cc, sg, se, t = code_unit[ordre], code_coin[ordre], signe[ordre], segment[ordre], temps[ordre]
    nouveau = np.ones(t.size, dtype=bool)
    nouveau[1:] = ((cu[1:] != cu[:-1]) | (cc[1:] != cc[:-1]) | (sg[1:] != sg[:-1]) | (se[1:] != se[:-1])
                   | (t[1:] - t[:-1] > config.cluster_gap_ms))
    identifiant = np.cumsum(nouveau) - 1
    premier = np.flatnonzero(nouveau)
    n = int(identifiant[-1]) + 1
    evenements = pd.DataFrame({
        "unit": noms_unit[cu[premier]], "coin": noms_coin[cc[premier]], "signe": sg[premier].astype(int),
        "segment": np.array(SEGMENTS)[se[premier]], "t0": t[premier],
        # la décision est observable dès que son premier fill l'est
        "obs": obs[ordre][premier],
        "notional": np.bincount(identifiant, weights=notionnel[ordre], minlength=n),
        "n_fills": np.bincount(identifiant, minlength=n),
        "post": post[ordre][premier],
    })
    return evenements[evenements["notional"] >= config.min_event_usd].reset_index(drop=True)


def _sans_chevauchement(entree: np.ndarray, groupe: np.ndarray, duree_ms: int) -> np.ndarray:
    """Masque des événements gardés : dans un même groupe, pas d'entrée tant que la précédente est tenue."""
    garde = np.zeros(entree.size, dtype=bool)
    ordre = np.lexsort((entree, groupe))
    dernier_groupe, libre_a = -1, 0
    for i in ordre:
        if groupe[i] != dernier_groupe:
            dernier_groupe, libre_a = groupe[i], 0
        if entree[i] >= libre_a:
            garde[i] = True
            libre_a = entree[i] + duree_ms
    return garde


def event_returns(events: pd.DataFrame, panel: Any, half_spread_bps: Mapping[str, float], *,
                  horizon_h: int, bar_ms: int, config: EventStudyConfig | None = None,
                  ) -> tuple[pd.DataFrame, dict[str, int]]:
    """Rendement de chaque décision copiée : entrée au premier prix publié après l'observation."""
    config = config or EventStudyConfig()
    rejets: dict[str, int] = {}
    if not len(events):
        return events.assign(entree=[], brut_bps=[], net_bps=[], temoin_bps=[], timing_bps=[], jour=[]), rejets
    colonne = events["coin"].map(lambda c: -1 if panel.column(c) is None else panel.column(c)).to_numpy()
    connu = colonne >= 0
    rejets["coin_sans_prix"] = int((~connu).sum())
    table = events.loc[connu].copy()
    colonne = colonne[connu].astype(np.int64)
    duree = int(horizon_h) * HOUR_MS
    entree = -(-(table["obs"].to_numpy().astype(np.int64) + config.reaction_ms) // bar_ms) * bar_ms
    signe = table["signe"].to_numpy().astype(float)
    p0, p1 = panel.at(entree, colonne), panel.at(entree + duree, colonne)
    table["entree"] = entree
    table["brut_bps"] = signe * (p1 / p0 - 1.0) * 1e4
    demi_ecart = table["coin"].map(lambda c: half_spread_bps.get(c, np.nan)).to_numpy().astype(float)
    table["cout_bps"] = 2.0 * (config.taker_fee_bps + demi_ecart)
    table["net_bps"] = table["brut_bps"] - table["cout_bps"]
    temoins = []
    for jours in config.control_offsets_days:
        recul = entree - int(jours) * DAY_MS
        temoins.append(signe * (panel.at(recul + duree, colonne) / panel.at(recul, colonne) - 1.0) * 1e4)
    empile = np.vstack(temoins) if temoins else np.full((1, len(table)), np.nan)
    with np.errstate(invalid="ignore"):
        connus = (~np.isnan(empile)).sum(axis=0)
        table["temoin_bps"] = np.where(connus > 0, np.nansum(empile, axis=0) / np.maximum(connus, 1), np.nan)
    table["timing_bps"] = table["brut_bps"] - table["temoin_bps"]
    table["jour"] = entree // DAY_MS
    mesurable = ~np.isnan(table["brut_bps"].to_numpy())
    rejets["prix_inconnu_a_l_entree_ou_a_la_sortie"] = int((~mesurable).sum())
    table = table.loc[mesurable]
    groupe = pd.factorize(pd.MultiIndex.from_frame(table[["unit", "coin", "signe", "segment"]]))[0]
    garde = _sans_chevauchement(table["entree"].to_numpy(), groupe, duree)
    rejets["position_deja_tenue"] = int((~garde).sum())
    return table.loc[garde].reset_index(drop=True), rejets


# --------------------------------------------------------------------------- synthèse

def serie_par_jour(table: pd.DataFrame, colonne: str) -> pd.Series:
    """Moyenne par (jour, leader), puis par jour : chaque leader pèse autant, chaque jour compte une fois."""
    valide = table.dropna(subset=[colonne])
    if not len(valide):
        return pd.Series(dtype=float)
    return valide.groupby(["jour", "unit"])[colonne].mean().groupby("jour").mean().sort_index()


def intervalle_blocs(valeurs: np.ndarray, *, bloc: int, niveau: float, config: EventStudyConfig) -> tuple[float, float] | None:
    """Bootstrap de blocs circulaires de jours (un horizon de 24 h lie deux jours voisins)."""
    n = valeurs.size
    if n < 4:
        return None
    rng = np.random.default_rng(config.seed)
    blocs = -(-n // bloc)
    departs = rng.integers(0, n, size=(config.bootstrap_samples, blocs))
    index = (departs[:, :, None] + np.arange(bloc)[None, None, :]) % n
    moyennes = valeurs[index.reshape(config.bootstrap_samples, -1)[:, :n]].mean(axis=1)
    alpha = (1.0 - niveau) / 2.0
    return float(np.quantile(moyennes, alpha)), float(np.quantile(moyennes, 1.0 - alpha))


def summarize_events(table: pd.DataFrame, *, horizon_h: int, niveau: float,
                     config: EventStudyConfig | None = None) -> dict[str, Any]:
    config = config or EventStudyConfig()
    sortie: dict[str, Any] = {"evenements": int(len(table)), "leaders": int(table["unit"].nunique()) if len(table) else 0,
                              "coins": int(table["coin"].nunique()) if len(table) else 0}
    bloc = max(1, -(-int(horizon_h) // 24) + (1 if horizon_h >= 24 else 0))
    for nom, colonne in (("brut", "brut_bps"), ("net", "net_bps"), ("timing", "timing_bps"), ("temoin", "temoin_bps")):
        serie = serie_par_jour(table, colonne) if len(table) else pd.Series(dtype=float)
        valeurs = serie.to_numpy(dtype=float)
        sortie[nom] = {
            "jours": int(valeurs.size),
            "moyenne_bps": float(valeurs.mean()) if valeurs.size else None,
            "intervalle_bps": intervalle_blocs(valeurs, bloc=bloc, niveau=niveau, config=config),
            "part_jours_positifs": float((valeurs > 0).mean()) if valeurs.size else None,
            "mediane_par_evenement_bps": float(table[colonne].median()) if len(table) and table[colonne].notna().any() else None,
            "evenements_mesures": int(table[colonne].notna().sum()) if len(table) else 0,
        }
    sortie["jours"] = sortie["net"]["jours"]
    sortie["cout_moyen_bps"] = float(table["cout_bps"].mean()) if len(table) and table["cout_bps"].notna().any() else None
    sortie["niveau_intervalle"] = niveau
    return sortie


def _rang_stable(table: pd.DataFrame) -> np.ndarray:
    """Ordre de départage reproductible et indépendant de l'ordre des lignes (jamais l'ordre du tableau)."""
    cles = (table["unit"].astype(str) + "|" + table["coin"].astype(str) + "|" + table["entree"].astype(str)
            + "|" + table["signe"].astype(str))
    return np.array([int(hashlib.sha256(c.encode()).hexdigest()[:12], 16) for c in cles], dtype=np.int64)


def simulate_capital(table: pd.DataFrame, *, horizon_h: int, config: EventStudyConfig | None = None) -> dict[str, Any]:
    """Ce qu'un compte PAPER de 350 USD aurait fait : ``slots`` lignes égales, sans levier, ordre minimal
    respecté, une ligne par décision tant qu'une place est libre, coût connu obligatoire."""
    config = config or EventStudyConfig()
    taille = config.capital_usd / max(1, config.slots)
    base = {"capital_usd": config.capital_usd, "lignes": config.slots, "taille_ligne_usd": taille}
    if taille < config.min_order_usd:
        return {**base, "status": "UNMEASURABLE", "reason": "ligne inférieure à l'ordre minimal de la plateforme"}
    if not len(table):
        return {**base, "status": "UNMEASURABLE", "reason": "aucune décision mesurable"}
    travail = table.assign(_rang=_rang_stable(table)).sort_values(["entree", "_rang"], kind="stable")
    duree = int(horizon_h) * HOUR_MS
    libres_a: list[int] = [0] * config.slots
    par_jour: dict[int, float] = {}
    pris = sans_place = cout_inconnu = 0
    for entree, net in zip(travail["entree"].to_numpy(), travail["net_bps"].to_numpy(), strict=True):
        if np.isnan(net):
            cout_inconnu += 1
            continue
        place = next((i for i, t in enumerate(libres_a) if t <= entree), None)
        if place is None:
            sans_place += 1
            continue
        libres_a[place] = int(entree) + duree
        jour = (int(entree) + duree) // DAY_MS
        par_jour[jour] = par_jour.get(jour, 0.0) + taille * float(net) / 1e4
        pris += 1
    if not par_jour:
        return {**base, "status": "UNMEASURABLE", "reason": "aucune décision à coût connu"}
    jours = np.arange(min(par_jour), max(par_jour) + 1)
    quotidien = np.array([par_jour.get(int(j), 0.0) for j in jours])
    cumul = np.cumsum(quotidien)
    # Le parcours ci-dessus ne retient que les décisions tombées sur une place libre : sur peu de trades,
    # son résultat est surtout du hasard. L'espérance, elle, applique au débit du compte (trades par jour)
    # le net moyen de TOUTES les décisions mesurées : c'est le chiffre à lire.
    net_moyen = float(np.nanmean(travail["net_bps"].to_numpy(dtype=float)))
    debit = pris / float(jours.size)
    return {**base, "status": "OK", "trades": pris, "refus_sans_place": sans_place, "refus_cout_inconnu": cout_inconnu,
            "trades_par_jour": debit, "net_moyen_toutes_decisions_bps": net_moyen,
            "esperance_usd_par_jour": debit * taille * net_moyen / 1e4,
            "jours_calendaires": int(jours.size), "net_usd_par_jour": float(quotidien.mean()),
            "net_total_usd": float(cumul[-1]), "pire_jour_usd": float(quotidien.min()),
            "repli_max_usd": float((np.maximum.accumulate(np.maximum(cumul, 0.0)) - cumul).max()),
            "part_jours_positifs": float((quotidien > 0).mean())}


def walk_forward_selection(table: pd.DataFrame, *, horizon_h: int, niveau: float,
                           config: EventStudyConfig | None = None) -> dict[str, Any]:
    """Ne copier que les leaders dont les décisions PASSÉES ont rapporté après coûts.

    À l'instant d'une décision, la note de son leader ne lit que ses décisions déjà DÉNOUÉES (entrée
    + horizon antérieurs à cet instant) : aucune issue future n'y entre. La moyenne est ramenée vers
    zéro (peu d'historique = peu de crédit). Trois populations sont comparées sur les mêmes jours :
    les décisions RETENUES, les décisions ÉLIGIBLES (leader assez connu, sélection ou non — la
    référence) et les ÉCARTÉES. Si la sélection a un pouvoir, retenues > éligibles > écartées."""
    config = config or EventStudyConfig()
    vide = {"retenus": summarize_events(table.iloc[:0], horizon_h=horizon_h, niveau=niveau, config=config),
            "eligibles": summarize_events(table.iloc[:0], horizon_h=horizon_h, niveau=niveau, config=config),
            "ecartes": summarize_events(table.iloc[:0], horizon_h=horizon_h, niveau=niveau, config=config),
            "ecart_retenus_moins_eligibles": {"jours": 0, "moyenne_bps": None, "intervalle_bps": None},
            "capital_350": {"status": "UNMEASURABLE", "reason": "aucune décision retenue"}}
    if not len(table):
        return vide
    duree = int(horizon_h) * HOUR_MS
    travail = table.sort_values(["unit", "entree"], kind="stable").reset_index(drop=True)
    net = travail["net_bps"].to_numpy(dtype=float)
    entree = travail["entree"].to_numpy(dtype=np.int64)
    code_unit = pd.factorize(travail["unit"])[0]
    note = np.full(len(travail), np.nan)
    passe = np.zeros(len(travail), dtype=np.int64)
    for code in np.unique(code_unit):
        index = np.flatnonzero(code_unit == code)
        instants, valeurs = entree[index], net[index]
        connu = ~np.isnan(valeurs)
        sorties = instants[connu] + duree                       # triées : l'horizon est le même pour toutes
        cumul = np.concatenate([[0.0], np.cumsum(valeurs[connu])])
        deja = np.searchsorted(sorties, instants, side="right")   # décisions à coût connu ET dénouées avant celle-ci
        passe[index] = deja
        moyenne = np.divide(cumul[deja], deja, out=np.full(deja.shape, np.nan), where=deja > 0)
        note[index] = moyenne * deja / (deja + config.selection_prior_events)
    eligible = passe >= config.selection_min_history
    retenu = eligible & (note > 0)
    sortie = {
        "retenus": summarize_events(travail.loc[retenu], horizon_h=horizon_h, niveau=niveau, config=config),
        "eligibles": summarize_events(travail.loc[eligible], horizon_h=horizon_h, niveau=niveau, config=config),
        "ecartes": summarize_events(travail.loc[eligible & ~retenu], horizon_h=horizon_h, niveau=niveau, config=config),
        "capital_350": simulate_capital(travail.loc[retenu], horizon_h=horizon_h, config=config),
    }
    # écart apparié par jour : même marché, mêmes journées, seule la sélection diffère
    a, b = serie_par_jour(travail.loc[retenu], "net_bps"), serie_par_jour(travail.loc[eligible], "net_bps")
    communs = a.index.intersection(b.index)
    ecart = (a.loc[communs] - b.loc[communs]).to_numpy(dtype=float)
    bloc = max(1, -(-int(horizon_h) // 24) + (1 if horizon_h >= 24 else 0))
    sortie["ecart_retenus_moins_eligibles"] = {
        "jours": int(ecart.size), "moyenne_bps": float(ecart.mean()) if ecart.size else None,
        "intervalle_bps": intervalle_blocs(ecart, bloc=bloc, niveau=niveau, config=config)}
    return sortie


def verdict_selection(selection: Mapping[str, Any], config: EventStudyConfig | None = None) -> dict[str, Any]:
    """Verdict de la sélection en marche avant sur les décisions observées en direct (mêmes règles)."""
    config = config or EventStudyConfig()
    base = {"hypothesis": H_SELECTED_LEADERS, "economically_proven": False}
    retenus = selection.get("retenus") or {}
    net, ecart = retenus.get("net") or {}, selection.get("ecart_retenus_moins_eligibles") or {}
    jours, evenements, leaders = int(net.get("jours") or 0), int(retenus.get("evenements") or 0), int(retenus.get("leaders") or 0)
    if jours < config.min_days or evenements < config.min_events or leaders < config.min_units:
        return {**base, "status": "MORE_DATA",
                "reason": f"{jours} jour(s), {evenements} décision(s) retenue(s), {leaders} leader(s) observés en "
                          f"direct ; il en faut au moins {config.min_days}, {config.min_events} et {config.min_units}"}
    if net.get("intervalle_bps") is not None and net["intervalle_bps"][1] <= 0:
        return {**base, "status": "REJECTED",
                "reason": "même en ne suivant que les leaders au passé gagnant, le net reste négatif"}
    if (net.get("intervalle_bps") is not None and net["intervalle_bps"][0] > 0
            and ecart.get("intervalle_bps") is not None and ecart["intervalle_bps"][0] > 0):
        return {**base, "status": "PROMISING",
                "reason": "les leaders retenus sur leur passé gagnent après coûts ET font mieux que les éligibles ; "
                          "à confirmer par le moteur PAPER sur des jours nouveaux"}
    return {**base, "status": "MORE_DATA", "reason": "intervalle à cheval sur zéro : l'échantillon ne tranche pas"}


def verdict_ouvertures(primaire: Mapping[str, Any], config: EventStudyConfig | None = None) -> dict[str, Any]:
    """Verdict de l'analyse primaire (décisions observées en direct). Règles fixées avant la mesure.

    L'échantillon minimal passe AVANT tout : quelques jours ne sont qu'un seul régime de marché, et un
    intervalle étroit sur quatre jours ne dit rien du cinquième. Ni promotion ni rejet en dessous."""
    config = config or EventStudyConfig()
    base = {"hypothesis": H_AGGRESSIVE_OPEN, "economically_proven": False}
    net, timing = primaire.get("net") or {}, primaire.get("timing") or {}
    jours, evenements, leaders = int(net.get("jours") or 0), int(primaire.get("evenements") or 0), int(primaire.get("leaders") or 0)
    if jours < config.min_days or evenements < config.min_events or leaders < config.min_units:
        return {**base, "status": "MORE_DATA",
                "reason": f"{jours} jour(s), {evenements} décision(s), {leaders} leader(s) observés en direct ; "
                          f"il en faut au moins {config.min_days}, {config.min_events} et {config.min_units}"}
    if net.get("intervalle_bps") is not None and net["intervalle_bps"][1] <= 0:
        return {**base, "status": "REJECTED",
                "reason": "net négatif après frais et écart sur toute la plage de confiance"}
    if (net.get("intervalle_bps") is not None and net["intervalle_bps"][0] > 0
            and timing.get("intervalle_bps") is not None and timing["intervalle_bps"][0] > 0):
        return {**base, "status": "PROMISING",
                "reason": "net positif après coûts ET supérieur aux témoins ; à confirmer par le moteur PAPER "
                          "sur des jours nouveaux"}
    return {**base, "status": "MORE_DATA", "reason": "intervalle à cheval sur zéro : l'échantillon ne tranche pas"}


def run_event_study(fills: pd.DataFrame, units: Mapping[str, str], panels: Mapping[str, tuple[Any, int]],
                    half_spread_bps: Mapping[str, float], config: EventStudyConfig | None = None) -> dict[str, Any]:
    """Étude complète. ``panels`` : ``{nom: (panel de prix, durée d'une bougie en ms)}`` ; le PREMIER est primaire."""
    config = config or EventStudyConfig()
    evenements = build_events(fills, units, config)
    # toutes les cellules, plus la règle de sélection jugée sur chaque prix et chaque population
    cellules_totales = (len(config.segments) * len(config.horizons_h) + 1) * max(1, len(panels)) * len(PERIODES)
    niveau = 1.0 - (1.0 - config.confidence) / cellules_totales
    cellules: list[dict[str, Any]] = []
    selections: list[dict[str, Any]] = []
    selection_primaire: dict[str, Any] = {}
    primaire: dict[str, Any] = {}
    capital: dict[str, Any] = {"status": "UNMEASURABLE", "reason": "aucune décision"}
    rejets_totaux: dict[str, int] = {}
    for rang_panel, (nom_panel, (panel, bar_ms)) in enumerate(panels.items()):
        for horizon in config.horizons_h:
            table, rejets = event_returns(evenements, panel, half_spread_bps, horizon_h=horizon, bar_ms=bar_ms,
                                          config=config)
            if rang_panel == 0 and horizon == config.horizons_h[0]:
                rejets_totaux = rejets
            for segment in config.segments:
                for periode in PERIODES:
                    masque = (table["segment"] == segment) & (table["post"] == (periode == PERIODES[0]))
                    resume = summarize_events(table.loc[masque], horizon_h=horizon, niveau=niveau, config=config)
                    est_primaire = (rang_panel == 0 and horizon == config.horizons_h[0]
                                    and segment == config.segments[0] and periode == PERIODES[0])
                    cellules.append({"prix": nom_panel, "horizon_h": horizon, "segment": segment, "periode": periode,
                                     "primaire": est_primaire, **resume})
                    if est_primaire:
                        primaire = resume
                        capital = simulate_capital(table.loc[masque], horizon_h=horizon, config=config)
                    if segment == config.segments[0] and horizon == config.horizons_h[0]:
                        choix = walk_forward_selection(table.loc[masque], horizon_h=horizon, niveau=niveau, config=config)
                        selections.append({"prix": nom_panel, "periode": periode, "primaire": est_primaire, **choix})
                        if est_primaire:
                            selection_primaire = choix
    return {
        "schema_version": SCHEMA_VERSION, "mechanism": "copy_vault_aggressive_open_event_study_v1",
        "config": config.as_dict(),
        "inputs": {"fills": int(len(fills)), "decisions": int(len(evenements)),
                   "decisions_par_segment": {s: int((evenements["segment"] == s).sum()) for s in config.segments},
                   "decisions_observees_en_direct": int(evenements["post"].sum()) if len(evenements) else 0,
                   "prix": list(panels), "coins_avec_ecart": len(half_spread_bps), "rejets_primaire": rejets_totaux},
        "hypotheses_tested": cellules_totales, "confidence_after_multiplicity": niveau,
        "primary": primaire, "capital_350": capital, "cells": cellules,
        "selection": {"regle": {"historique_minimal": config.selection_min_history,
                                "decisions_nulles_a_priori": config.selection_prior_events,
                                "segment": config.segments[0], "horizon_h": config.horizons_h[0]},
                      "primaire": selection_primaire, "cellules": selections},
        "verdicts": [verdict_ouvertures(primaire, config), verdict_selection(selection_primaire, config)],
        "caveats": [
            "Prix = clôtures de bougies récupérées après coup ; l'entrée attend la première clôture publiée après "
            "l'observation, ce qui retarde la copie (jusqu'à une bougie) sans jamais l'avancer.",
            "Demi-écarts mesurés sur la période récente et appliqués à tout l'historique ; funding non compté.",
            "Décisions reconstruites (backfill, relevés tardifs) : instant d'observation SUPPOSÉ et leaders choisis "
            "après coup sur leurs résultats, donc flatteuses ; elles sont rapportées mais ne comptent pas pour le verdict.",
            "Le parcours du compte de 350 USD ne retient que les décisions tombées sur une place libre ; sur peu de "
            "trades il est surtout du hasard : lire l'espérance au débit du compte.",
            "Tier LOCAL, exploratoire : aucune rentabilité n'est prouvée par une étude d'événements.",
        ],
        "paper_read_only": True, "real_execution": False, "economically_proven": False,
    }


__all__ = ["DAY_MS", "EventStudyConfig", "H_AGGRESSIVE_OPEN", "H_SELECTED_LEADERS",
           "MAX_DELAI_OBSERVATION_DIRECTE_MS", "PERIODES", "SCHEMA_VERSION", "SEGMENTS", "assembler_fills",
           "verdict_selection", "walk_forward_selection", "build_events", "event_returns", "intervalle_blocs", "run_event_study", "serie_par_jour",
           "simulate_capital", "summarize_events", "verdict_ouvertures"]
