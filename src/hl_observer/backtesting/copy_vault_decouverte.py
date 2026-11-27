"""Moteur de decouverte CopyVault (27/11/2026) : generer, juger, memoriser, et mesurer sa propre capacite a decouvrir.

POURQUOI. Le labo testait une poignee d'hypotheses ecrites a la main (22 familles, aucune retenue). Ce module les
GENERE depuis une grammaire de mecanismes, les juge avec les outils deja en place (DSR de ``research.deflated_sharpe``,
PBO par CSCV de ``robustesse_selection``), retient ce qu'il apprend d'une campagne a l'autre, et mesure sur des mondes
a VERITE CONNUE si une nouvelle version de sa methode decouvre mieux sans fabriquer de faux gagnants. Deterministe,
sans LLM, sans reseau, PAPER : rien ici ne passe d'ordre ni ne modifie le moteur.

L'UNITE : la DECISION d'un leader (fills du meme vault, coin, sens et type d'action a moins de 5 min), jamais la ligne.
Le leader est un CAPTEUR (sa decision annonce-t-elle le prix ?), pas un modele a recopier : on teste SUIVRE et CONTRER.

LES TROIS POPULATIONS (biais de selection retrospective, mesure le 27/11) : les 38 vaults suivis ont ete choisis entre
le 9 et le 24/11/2026 sur leurs resultats. Une decision prise AVANT ce choix est flattee pour « suivre ». Donc :
  * EXPLORATION : decisions entierement denouees avant la coupure (1re entree dans la liste suivie) -- biaisees, ne
    servent qu'a CHOISIR quoi geler ;
  * VALIDATION : decisions apres coupure + embargo d'un horizon maximal, d'un leader DEJA suivi -- lecture precoce ;
  * SUIVI (forward) : decisions posterieures au GEL d'un candidat -- la seule preuve recevable (module champion).

LA GRAMMAIRE (une dimension = un mecanisme, documente dans ``DIMENSIONS``) : direction (suivre / contrer) x horizon
x conjonction d'au plus deux predicats de dimensions distinctes. Toutes les cellules evaluees comptent dans le N du DSR,
avec les essais anterieurs du registre. Les croisements de profondeur 2 sont tires par la memoire scientifique
(echantillonnage de Thompson sur les predicats qui ont deja aide), jamais par le resultat de la campagne en cours.

GARDE-FOUS FIXES (``GARDE_FOUS``) : aucune variante de methode ne peut les affaiblir (DSR >= 0,95, PBO <= 0,5, au moins
20 jours d'exploration et 3 leaders, 30 jours de suivi avant toute promotion). Une campagne ne rend JAMAIS mieux que
MORE_DATA : seul le suivi apres gel peut promouvoir. Le banc a verite connue vit dans ``copy_vault_decouverte_banc``.

JUGE v2 (``JUGE_VERSION``), ECRIT APRES AVOIR VU LE REEL DU 27/11 -- declare comme tel, puis GELE :
  * variance des Sharpe des essais COMPARABLES (meme direction, meme horizon ; plancher 1/(T-1)) : la v1 melangeait
    « suivre » et « contrer », ce qui gonflait mecaniquement la barre. Ce changement ASSOUPLIT le DSR ;
  * PBO calcule par (direction, horizon) pour la meme raison -- ce changement-ci DURCIT (la v1 flattait le PBO) ;
  * chevauchements retires (une position tenue par leader, coin et sens, comme ``copy_vault_event_study``) ;
  * SELECTION sur toutes les decisions denouees avant la campagne (exploration + validation) : la boucle n'est plus
    figee sur la coupure du 9/11 ; garde supplementaire : la part post-entree ne doit pas etre negative ;
  * aucune cellule REFUTEE sans demi-ecarts MESURES pour au moins 90 % de ses decisions.
JUGE v3 (27/11, apres la 1re campagne a ecarts mesures -- declare) : palier SURVEILLANCE. Le banc recale montre que
la porte DSR >= 0,95 ne gele rien en dessous d'environ 160 bps par decision : le suivi, seule preuve, ne demarrait
jamais. Plan classique en deux temps : REPERAGE des ``max_surveillance`` meilleures cellules SAINES au rang du DSR
(moyenne > 0, >= 20 jours, >= 3 leaders, bat la copie naive, part post-entree non negative, PBO du groupe <= seuil),
puis CONFIRMATION sur des jours NOUVEAUX avec les MEMES regles de promotion (30 jours, IC95 > 0, Benjamini-Hochberg
sur tous les challengers actifs, mieux que le champion). Aucun garde-fou de promotion n'est touche.
Toute modification ulterieure du juge change ``JUGE_VERSION`` et se declare ici.
"""
from __future__ import annotations

import bisect
import hashlib
import heapq
import itertools
import json
import math
from collections import Counter, deque
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import asdict, dataclass
from typing import Any

import numpy as np
import pandas as pd

from hl_observer.backtesting.copy_vault_event_study import _sans_chevauchement
from hl_observer.backtesting.copy_vault_protocol import PAPER_EQUITY_USD
from hl_observer.backtesting.robustesse_selection import pbo_cscv
from hl_observer.fees.hyperliquid_fees import TAKER_PERP_BPS
from hl_observer.research.deflated_sharpe import deflated_sharpe

SCHEMA = "hypersmart.copy_vault_decouverte.v1"
HYPOTHESE = "copy_vault_discovery_engine"
FAMILLE = "copy_vault_decouverte"
EVIDENCE_TIER = "LOCAL_REST_BACKFILL_EPISODES_EXPLORATORY"
JUGE_VERSION = "2026-11-27.v3"
HEURE_MS, JOUR_MS = 3_600_000, 86_400_000
ACTIONS = ("OPEN", "ADD", "REDUCE", "CLOSE")
DIRECTIONS = ("suivre", "contrer")

#: Seuils que NI la recherche de methode NI une campagne ne peuvent affaiblir.
GARDE_FOUS: dict[str, float] = {"dsr_min": 0.95, "pbo_max": 0.5, "explo_min_jours": 20, "min_unites": 3,
                                "forward_min_jours": 30, "q_fdr": 0.10}

#: Une dimension = un mecanisme (pourquoi elle pourrait porter de l'information), pas une case de plus a essayer.
DIMENSIONS: dict[str, tuple[tuple[str, ...], str]] = {
    "action": (ACTIONS, "ouvrir, renforcer, alleger, solder : seule une ouverture annonce une conviction neuve"),
    "taille": (("grosse", "normale"), "ordre grand pour CE leader (centile causal >= 80 %) : Kyle, l'informe charge"),
    "consensus": (("seul", "accompagne"), "un autre leader a pris le meme sens sur le coin dans les 4 h : agregation"),
    "opposition": (("non", "oui"), "un autre leader a pris le sens inverse dans les 4 h : desaccord, bruit"),
    "tendance": (("avec", "contre"), "la decision suit ou remonte le mouvement du coin sur 24 h : momentum / contrarien"),
    "volatilite": (("calme", "agite"), "mouvement absolu du coin sur 24 h au-dessus de la mediane d'EXPLORATION"),
    "funding": (("recoit", "paie"), "le sens de la decision encaisse ou paie le funding : portage sans info, foule"),
    "historique": (("gagnant", "perdant"), "net passe DENOUE de ce leader, ramene vers zero : persistance du talent"),
    "session": (("asie", "europe", "us"), "heure UTC de la decision : liquidite et participants differents"),
}


@dataclass(frozen=True)
class DecouverteConfig:
    """Parametres declares AVANT la mesure (couts, causalite, populations, statistiques)."""

    horizons_h: tuple[int, ...] = (4, 12, 24)
    gap_ms: int = 300_000
    min_decision_usd: float = 1_000.0
    reaction_ms: int = 60_000
    retard_observation_ms: int = 60_000          # backfill : instant d'observation SUPPOSE (fill + 60 s)
    taker_bps: float = TAKER_PERP_BPS
    demi_ecart_defaut_bps: float = 8.0           # coin sans ecart mesure : valeur PRUDENTE declaree, jamais zero
    glissement_bps: float = 1.0
    couverture_funding_min: float = 0.9
    fenetre_consensus_ms: int = 4 * HEURE_MS
    historique_min: int = 10
    historique_a_priori: float = 20.0
    taille_min_historique: int = 20
    embargo_ms: int = JOUR_MS
    blocs_pbo: int = 8
    bloc_bootstrap_jours: int = 2
    tirages: int = 2000
    graine: int = 20_261_127
    max_geles: int = 5
    max_surveillance: int = 5
    capital_usd: float = PAPER_EQUITY_USD

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class Methode:
    """Comment la campagne cherche et choisit. Versionnee ; amelioree seulement sur banc a verite connue."""

    version: int = 1
    profondeur: int = 2
    predicats_croises: int = 6
    dsr_seuil: float = 0.95
    pbo_max: float = 0.5
    explo_min_jours: int = 20
    exiger_bat_naif: bool = True

    def respecte_les_garde_fous(self) -> bool:
        return (self.dsr_seuil >= GARDE_FOUS["dsr_min"] and self.pbo_max <= GARDE_FOUS["pbo_max"]
                and self.explo_min_jours >= GARDE_FOUS["explo_min_jours"] and self.exiger_bat_naif
                and self.profondeur in (1, 2) and self.predicats_croises >= 2)

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


# =========================================================================== decisions

COLONNES_DECISIONS = ["unit", "coin", "signe", "action", "t0", "notional", "n_fills", "entree_suivi"]


def decisions_depuis_episodes(episodes: Iterable[Mapping[str, Any]], *, entree_suivi_ms: Mapping[str, int],
                              config: DecouverteConfig | None = None) -> tuple[pd.DataFrame, dict[str, int]]:
    """Episodes (une ligne par fill) -> decisions. Un fill vu deux fois (meme ``fill_id``) ne compte qu'une fois.

    ``entree_suivi_ms`` : vault (minuscules) -> instant ou il est entre dans la liste suivie (-1 si jamais)."""
    config = config or DecouverteConfig()
    rejets: Counter[str] = Counter()
    vus: set[Any] = set()
    lignes = []
    for r in episodes:
        cle = r.get("fill_id") or r.get("stable_event_id") or (r.get("hash"), r.get("tid"))
        if cle in vus:
            rejets["doublon"] += 1
            continue
        vus.add(cle)
        action, ts, vault, coin = r.get("action"), r.get("ts_ms"), r.get("vault"), r.get("coin")
        signe = r.get("fill_sign", r.get("signe"))
        if action not in ACTIONS or type(ts) is not int or ts <= 0 or signe not in (1, -1) or not vault or not coin:
            rejets["illisible"] += 1
            continue
        try:
            usd = abs(float(r.get("taille_usd")))
        except (TypeError, ValueError):
            rejets["illisible"] += 1
            continue
        if not math.isfinite(usd) or usd <= 0:
            rejets["illisible"] += 1
            continue
        lignes.append((str(vault).lower(), str(coin), int(signe), action, ts, usd))
    if not lignes:
        return pd.DataFrame(columns=COLONNES_DECISIONS), dict(rejets)
    df = pd.DataFrame(lignes, columns=["unit", "coin", "signe", "action", "t", "usd"])
    df = df.sort_values(["unit", "coin", "signe", "action", "t"], kind="stable", ignore_index=True)
    cles = df[["unit", "coin", "signe", "action"]]
    change = (cles != cles.shift()).any(axis=1).to_numpy()
    t = df["t"].to_numpy(dtype=np.int64)
    ecart = np.diff(t, prepend=t[0])
    nouveau = change | (ecart > config.gap_ms)
    nouveau[0] = True
    ident = np.cumsum(nouveau) - 1
    premier = np.flatnonzero(nouveau)
    dec = pd.DataFrame({
        "unit": df["unit"].to_numpy()[premier], "coin": df["coin"].to_numpy()[premier],
        "signe": df["signe"].to_numpy()[premier].astype(int), "action": df["action"].to_numpy()[premier],
        "t0": t[premier], "notional": np.bincount(ident, weights=df["usd"].to_numpy()),
        "n_fills": np.bincount(ident),
    })
    petites = dec["notional"] < config.min_decision_usd
    rejets["decision_sous_le_seuil"] = int(petites.sum())
    dec = dec.loc[~petites].copy()
    dec["entree_suivi"] = dec["unit"].map(lambda v: int(entree_suivi_ms.get(v, -1))).astype(np.int64)
    return dec.sort_values(["t0", "unit", "coin"], kind="stable", ignore_index=True), dict(rejets)


# =========================================================================== enrichissement causal

def _funding_cumule(funding: Mapping[tuple[str, int], float], coins: Iterable[str]) -> dict[str, tuple[int, np.ndarray, np.ndarray]]:
    """Par coin : (premiere heure, somme cumulee des taux, nombre cumule d'heures connues) -> somme sur une plage en O(1)."""
    par_coin: dict[str, dict[int, float]] = {}
    voulus = set(coins)
    for (coin, heure), taux in funding.items():
        if coin in voulus:
            par_coin.setdefault(coin, {})[int(heure)] = float(taux)
    sortie = {}
    for coin, heures in par_coin.items():
        h0, h1 = min(heures), max(heures)
        valeurs = np.zeros(h1 - h0 + 1)
        connues = np.zeros(h1 - h0 + 1)
        for h, f in heures.items():
            valeurs[h - h0], connues[h - h0] = f, 1.0
        sortie[coin] = (h0, np.concatenate([[0.0], np.cumsum(valeurs)]), np.concatenate([[0.0], np.cumsum(connues)]))
    return sortie


def _somme_funding(cumul, coin: str, debut_h: np.ndarray, fin_h: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Somme des taux des heures [debut_h, fin_h] et part des heures connues."""
    if coin not in cumul:
        return np.full(debut_h.shape, np.nan), np.zeros(debut_h.shape)
    h0, cs, cn = cumul[coin]
    n = cs.size - 1
    a = np.clip(debut_h - h0, 0, n)
    b = np.clip(fin_h - h0 + 1, 0, n)
    somme = cs[b] - cs[a]
    connues = cn[b] - cn[a]
    total = (fin_h - debut_h + 1).astype(float)
    return somme, np.where(total > 0, connues / total, 0.0)


def enrichir(dec: pd.DataFrame, panel: Any, *, bar_ms: int, funding: Mapping[tuple[str, int], float],
             demi_ecarts: Mapping[str, float], config: DecouverteConfig | None = None) -> tuple[pd.DataFrame, dict[str, int]]:
    """Prix d'entree et de sortie, couts, funding porte, et les predicats -- tous lus AVANT l'entree.

    Entree au premier prix PUBLIE apres ``t0 + retard d'observation + reaction`` (cloture de bougie, jamais avant sa
    fin). Cout = 2 x (frais taker + demi-ecart + glissement). Funding porte = taux des heures tenues, signe du sens."""
    config = config or DecouverteConfig()
    rejets: Counter[str] = Counter()
    out = dec.copy()
    if not len(out):
        return out, {}
    colonne = out["coin"].map(lambda c: -1 if panel.column(c) is None else panel.column(c)).to_numpy()
    rejets["coin_sans_prix"] = int((colonne < 0).sum())
    out = out.loc[colonne >= 0].reset_index(drop=True)
    colonne = colonne[colonne >= 0].astype(np.int64)
    if not len(out):
        return out, dict(rejets)
    t0 = out["t0"].to_numpy(dtype=np.int64)
    signe = out["signe"].to_numpy(dtype=float)
    entree = -(-(t0 + config.retard_observation_ms + config.reaction_ms) // bar_ms) * bar_ms
    p0 = panel.at(entree, colonne)
    p_avant = panel.at(entree - 24 * HEURE_MS, colonne)
    out["entree"] = entree
    out["jour"] = entree // JOUR_MS
    with np.errstate(invalid="ignore", divide="ignore"):
        mouvement = (p0 / p_avant - 1.0) * 1e4
    out["mouvement_24h_bps"] = mouvement
    out["tendance"] = np.where(np.isnan(mouvement), "inconnue", np.where(signe * mouvement > 0, "avec", "contre"))
    demi = out["coin"].map(lambda c: demi_ecarts.get(c)).astype(float).to_numpy()
    out["ecart_mesure"] = np.isfinite(demi)
    demi = np.where(np.isfinite(demi), demi, config.demi_ecart_defaut_bps)
    cout = 2.0 * (config.taker_bps + demi + config.glissement_bps)
    out["cout_bps"] = cout
    cumul = _funding_cumule(funding, out["coin"].unique())
    heure_entree = entree // HEURE_MS
    coins = out["coin"].to_numpy()
    taux_avant = np.full(len(out), np.nan)
    for coin in np.unique(coins):
        m = coins == coin
        s, part = _somme_funding(cumul, coin, heure_entree[m] - 1, heure_entree[m] - 1)
        taux_avant[m] = np.where(part > 0, s, np.nan)
    out["funding"] = np.where(np.isnan(taux_avant) | (taux_avant == 0), "inconnu",
                              np.where(signe * taux_avant < 0, "recoit", "paie"))
    heure_utc = (t0 // HEURE_MS) % 24
    out["session"] = np.where(heure_utc < 8, "asie", np.where(heure_utc < 14, "europe", "us"))
    for h in config.horizons_h:
        p1 = panel.at(entree + h * HEURE_MS, colonne)
        with np.errstate(invalid="ignore", divide="ignore"):
            brut = signe * (p1 / p0 - 1.0) * 1e4
        porte = np.full(len(out), np.nan)
        for coin in np.unique(coins):
            m = coins == coin
            s, part = _somme_funding(cumul, coin, heure_entree[m] + 1, heure_entree[m] + h)
            porte[m] = np.where(part >= config.couverture_funding_min, s / np.maximum(part, 1e-9), np.nan)
        funding_bps = signe * porte * 1e4                        # ce que PAIE un copieur qui suit (long, taux > 0)
        out[f"brut_{h}h"] = brut
        out[f"net_suivre_{h}h"] = brut - cout - funding_bps
        out[f"net_contrer_{h}h"] = -brut - cout + funding_bps
        rejets[f"net_inconnu_{h}h"] = int(np.isnan(out[f"net_suivre_{h}h"].to_numpy()).sum())
    # une seule position par (leader, coin, sens) : une decision prise pendant qu'une copie est tenue est ignoree
    groupe = pd.factorize(pd.MultiIndex.from_frame(out[["unit", "coin", "signe"]]))[0]
    for h in config.horizons_h:
        net = out[f"net_suivre_{h}h"].to_numpy(dtype=float)
        mesurable = np.isfinite(net)
        garde = np.zeros(len(out), dtype=bool)
        idx = np.flatnonzero(mesurable)
        garde[idx] = _sans_chevauchement(entree[idx], groupe[idx], h * HEURE_MS)
        retire = mesurable & ~garde
        rejets[f"chevauchement_{h}h"] = int(retire.sum())
        for d in DIRECTIONS:
            col = out[f"net_{d}_{h}h"].to_numpy(dtype=float).copy()
            col[retire] = np.nan
            out[f"net_{d}_{h}h"] = col
    _predicats_causaux(out, config)
    return out, dict(rejets)


def _predicats_causaux(out: pd.DataFrame, config: DecouverteConfig) -> None:
    """Taille, consensus, opposition, historique : chacun ne lit que des decisions ANTERIEURES (en place)."""
    n = len(out)
    t0 = out["t0"].to_numpy(dtype=np.int64)
    unit = out["unit"].to_numpy()
    coin = out["coin"].to_numpy()
    signe = out["signe"].to_numpy(dtype=np.int64)
    notional = out["notional"].to_numpy(dtype=float)
    ordre = np.lexsort((np.arange(n), t0))
    # taille : centile parmi les decisions PRECEDENTES du meme leader
    taille = np.full(n, "inconnue", dtype=object)
    vues: dict[str, list[float]] = {}
    for i in ordre:
        prec = vues.setdefault(unit[i], [])
        if len(prec) >= config.taille_min_historique:
            taille[i] = "grosse" if bisect.bisect_left(prec, notional[i]) / len(prec) >= 0.8 else "normale"
        bisect.insort(prec, notional[i])
    out["taille"] = taille
    # consensus / opposition : autres leaders, meme coin, dans [t0 - fenetre, t0) -- strictement avant
    consensus = np.full(n, "seul", dtype=object)
    opposition = np.full(n, "non", dtype=object)
    for c in np.unique(coin):
        idx = np.flatnonzero(coin == c)
        idx = idx[np.lexsort((idx, t0[idx]))]
        fenetre: deque[int] = deque()
        compte = {1: Counter(), -1: Counter()}
        k = 0
        while k < idx.size:
            groupe = [idx[k]]
            while k + len(groupe) < idx.size and t0[idx[k + len(groupe)]] == t0[idx[k]]:
                groupe.append(idx[k + len(groupe)])
            debut = t0[idx[k]] - config.fenetre_consensus_ms
            while fenetre and t0[fenetre[0]] < debut:
                j = fenetre.popleft()
                compte[signe[j]][unit[j]] -= 1
                if compte[signe[j]][unit[j]] <= 0:
                    del compte[signe[j]][unit[j]]
            for i in groupe:
                memes = len(compte[signe[i]]) - (1 if unit[i] in compte[signe[i]] else 0)
                contraires = len(compte[-signe[i]]) - (1 if unit[i] in compte[-signe[i]] else 0)
                consensus[i] = "accompagne" if memes > 0 else "seul"
                opposition[i] = "oui" if contraires > 0 else "non"
            for i in groupe:
                fenetre.append(i)
                compte[signe[i]][unit[i]] += 1
            k += len(groupe)
    out["consensus"] = consensus
    out["opposition"] = opposition
    # historique : net (suivre) des decisions DENOUEES du meme leader avant cette entree, par horizon
    entree = out["entree"].to_numpy(dtype=np.int64)
    for h in config.horizons_h:
        net = out[f"net_suivre_{h}h"].to_numpy(dtype=float)
        hist = np.full(n, "inconnu", dtype=object)
        ordre_e = np.lexsort((np.arange(n), entree))
        attente: dict[str, list[tuple[int, float]]] = {}
        resolu: dict[str, list[float]] = {}
        for i in ordre_e:
            tas = attente.setdefault(unit[i], [])
            acc = resolu.setdefault(unit[i], [0.0, 0.0])
            while tas and tas[0][0] <= entree[i]:
                _, v = heapq.heappop(tas)
                acc[0] += v
                acc[1] += 1.0
            if acc[1] >= config.historique_min:
                hist[i] = "gagnant" if acc[0] / (acc[1] + config.historique_a_priori) > 0 else "perdant"
            if math.isfinite(net[i]):
                heapq.heappush(tas, (int(entree[i] + h * HEURE_MS), float(net[i])))
        out[f"historique_{h}h"] = hist


def attribuer_populations(out: pd.DataFrame, *, coupure_ms: int | None, config: DecouverteConfig | None = None) -> pd.DataFrame:
    """EXPLORATION (denouee avant la coupure), VALIDATION (apres coupure + embargo, leader deja suivi), sinon EXCLUE.

    ``coupure_ms`` par defaut : la premiere entree d'un vault dans la liste suivie. Aucun leader date : tout est
    EXPLORATION ou EXCLU -- aucune validation n'est fabriquee. La volatilite est coupee a la mediane d'EXPLORATION."""
    config = config or DecouverteConfig()
    out = out.copy()
    suivi = out["entree_suivi"].to_numpy(dtype=np.int64) if len(out) else np.array([], dtype=np.int64)
    if coupure_ms is None:
        dates = suivi[suivi > 0]
        coupure_ms = int(dates.min()) if dates.size else None
    hmax = max(config.horizons_h) * HEURE_MS
    t0 = out["t0"].to_numpy(dtype=np.int64) if len(out) else np.array([], dtype=np.int64)
    entree = out["entree"].to_numpy(dtype=np.int64) if len(out) else np.array([], dtype=np.int64)
    if coupure_ms is None:
        pop = np.full(len(out), "exploration", dtype=object)
    else:
        pop = np.full(len(out), "exclue", dtype=object)
        pop[entree + hmax <= coupure_ms] = "exploration"
        pop[(t0 >= coupure_ms + config.embargo_ms) & (suivi > 0) & (t0 >= suivi)] = "validation"
    out["population"] = pop
    mouvement = np.abs(out["mouvement_24h_bps"].to_numpy(dtype=float)) if len(out) else np.array([])
    ref = mouvement[(pop == "exploration") & np.isfinite(mouvement)]
    seuil = float(np.median(ref)) if ref.size else float("nan")
    out["volatilite"] = np.where(~np.isfinite(mouvement) | (not math.isfinite(seuil)), "inconnue",
                                 np.where(mouvement > seuil, "agite", "calme"))
    out.attrs["coupure_ms"] = coupure_ms
    out.attrs["seuil_volatilite_bps"] = seuil
    return out


# =========================================================================== grammaire

def id_cellule(cellule: Mapping[str, Any]) -> str:
    cle = {"direction": cellule["direction"], "horizon_h": int(cellule["horizon_h"]),
           "predicats": sorted([list(p) for p in cellule["predicats"]])}
    return hashlib.sha256(json.dumps(cle, sort_keys=True).encode()).hexdigest()[:16]


def _cellule(direction: str, horizon: int, predicats: Sequence[tuple[str, str]]) -> dict[str, Any]:
    c = {"direction": direction, "horizon_h": int(horizon), "predicats": tuple(sorted(predicats))}
    c["id"] = id_cellule(c)
    return c


def predicats_disponibles() -> list[tuple[str, str]]:
    return [(dim, val) for dim, (valeurs, _) in DIMENSIONS.items() for val in valeurs]


def choisir_croisements(memoire: Mapping[str, Any] | None, direction: str, nombre: int, graine: int) -> list[tuple[str, str]]:
    """Predicats a croiser : Thompson sur Beta(1 + aides, 1 + echecs) de la memoire (uniforme sans memoire)."""
    rng = np.random.default_rng(graine)
    memo = (memoire or {}).get("predicats", {})
    tirages = []
    for dim, val in predicats_disponibles():
        m = memo.get(f"{direction}|{dim}={val}", {})
        tirages.append((float(rng.beta(1.0 + m.get("aide", 0), 1.0 + m.get("echec", 0))), dim, val))
    tirages.sort(key=lambda x: (-x[0], x[1], x[2]))
    return [(dim, val) for _, dim, val in tirages[:nombre]]


def generer_cellules(methode: Methode, config: DecouverteConfig, *, memoire: Mapping[str, Any] | None = None,
                     graine: int = 0) -> list[dict[str, Any]]:
    """Toutes les cellules d'une campagne, AVANT toute mesure (a pre-enregistrer telles quelles)."""
    cellules: dict[str, dict[str, Any]] = {}
    for direction in DIRECTIONS:
        croises = choisir_croisements(memoire, direction, methode.predicats_croises, graine) if methode.profondeur >= 2 else []
        for h in config.horizons_h:
            for c in [_cellule(direction, h, ())] + [_cellule(direction, h, (p,)) for p in predicats_disponibles()]:
                cellules[c["id"]] = c
            for a, b in itertools.combinations(croises, 2):
                if a[0] != b[0]:
                    c = _cellule(direction, h, (a, b))
                    cellules[c["id"]] = c
    return sorted(cellules.values(), key=lambda c: (c["direction"], c["horizon_h"], len(c["predicats"]), c["id"]))


def masque_cellule(table: pd.DataFrame, cellule: Mapping[str, Any], cache: dict | None = None) -> np.ndarray:
    m = np.ones(len(table), dtype=bool)
    for dim, val in cellule["predicats"]:
        colonne = f"historique_{int(cellule['horizon_h'])}h" if dim == "historique" else dim
        cle = (colonne, val)
        if cache is not None and cle in cache:
            m &= cache[cle]
            continue
        p = table[colonne].to_numpy() == val
        if cache is not None:
            cache[cle] = p
        m &= p
    return m


# =========================================================================== statistiques

def serie_journaliere(valeurs: np.ndarray, jour: np.ndarray, unite: np.ndarray, masque: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Moyenne par (jour, leader), puis par jour : un leader hyperactif ne pese pas plus qu'un autre."""
    m = masque & np.isfinite(valeurs)
    if not m.any():
        return np.array([], dtype=np.int64), np.array([])
    j, u, v = jour[m].astype(np.int64), unite[m].astype(np.int64), valeurs[m]
    base = int(unite.max()) + 1 if unite.size else 1
    cles, inv = np.unique(j * base + u, return_inverse=True)
    moy = np.bincount(inv, weights=v) / np.bincount(inv)
    jours, inv2 = np.unique(cles // base, return_inverse=True)
    return jours, np.bincount(inv2, weights=moy) / np.bincount(inv2)


def moyennes_bootstrap(x: np.ndarray, *, bloc: int, tirages: int, graine: int) -> np.ndarray:
    n = x.size
    rng = np.random.default_rng(graine)
    b = max(1, min(int(bloc), n))
    nb = -(-n // b)
    departs = rng.integers(0, n, size=(int(tirages), nb))
    index = (departs[:, :, None] + np.arange(b)[None, None, :]) % n
    return x[index.reshape(int(tirages), -1)[:, :n]].mean(axis=1)


def resumer(x: np.ndarray, config: DecouverteConfig, *, avec_bootstrap: bool = True) -> dict[str, Any]:
    n = int(x.size)
    if n == 0:
        return {"n_jours": 0}
    moyenne = float(x.mean())
    ecart = float(x.std(ddof=1)) if n > 1 else float("nan")
    sortie = {"n_jours": n, "moyenne_bps": moyenne, "ecart_bps": ecart,
              "sharpe_jour": moyenne / ecart if n > 1 and ecart > 0 else float("nan")}
    if n > 3 and ecart > 0:
        z = (x - moyenne) / x.std(ddof=0)
        sortie["asymetrie"], sortie["kurtosis"] = float((z ** 3).mean()), float((z ** 4).mean())
    else:
        sortie["asymetrie"], sortie["kurtosis"] = 0.0, 3.0
    if avec_bootstrap and n >= 4:
        boot = moyennes_bootstrap(x, bloc=config.bloc_bootstrap_jours, tirages=config.tirages, graine=config.graine)
        sortie["ic95"] = [float(np.quantile(boot, 0.025)), float(np.quantile(boot, 0.975))]
        sortie["p_un_cote"] = float((boot <= 0).mean())
    return sortie


def benjamini_hochberg(p: Mapping[str, float], q: float) -> set[str]:
    """Ids retenus au taux de fausses decouvertes ``q`` (Benjamini-Hochberg, une seule fois pour toute la famille)."""
    tries = sorted(p.items(), key=lambda kv: (kv[1], kv[0]))
    m, retenus = len(tries), 0
    for k, (_, pv) in enumerate(tries, 1):
        if pv <= q * k / m:
            retenus = k
    return {i for i, _ in tries[:retenus]}


# =========================================================================== campagne

def _part_couts_mesures(table: pd.DataFrame, masque: np.ndarray) -> float:
    if "ecart_mesure" not in table.columns or not masque.any():
        return 0.0
    return float(table["ecart_mesure"].to_numpy(dtype=bool)[masque].mean())


def juger_campagne(table: pd.DataFrame, cellules: Sequence[Mapping[str, Any]], methode: Methode,
                   config: DecouverteConfig | None = None, *, essais_anterieurs: int = 0,
                   sharpes_anterieurs: Sequence[float] = (), rapide: bool = False) -> dict[str, Any]:
    """Evalue chaque cellule pre-enregistree ; gele au plus ``max_geles`` candidats ; ne prouve jamais rien.

    SELECTION = toutes les decisions denouees avant la campagne (exploration + validation). ``rapide`` (banc) :
    ni bootstrap ni lectures separees -- seule la selection compte."""
    config = config or DecouverteConfig()
    if not methode.respecte_les_garde_fous():
        raise ValueError("methode refusee : elle affaiblit un garde-fou")
    n = len(table)
    pop = table["population"].to_numpy() if n else np.array([])
    explo, valid = pop == "exploration", pop == "validation"
    sel = explo | valid
    jour = table["jour"].to_numpy(dtype=np.int64) if n else np.array([], dtype=np.int64)
    unite = pd.factorize(table["unit"])[0] if n else np.array([], dtype=np.int64)
    cache: dict = {}
    valeurs = ({f"{d}_{h}": table[f"net_{d}_{h}h"].to_numpy(dtype=float) for d in DIRECTIONS for h in config.horizons_h}
               if n else {})
    jours_sel = np.unique(jour[sel]) if sel.any() else np.array([], dtype=np.int64)
    blocs = np.array_split(jours_sel, config.blocs_pbo) if jours_sel.size >= config.blocs_pbo else []
    resultats: list[dict[str, Any]] = []
    matrices: dict[tuple[str, int], list[list[float]]] = {}
    for c in cellules:
        m = masque_cellule(table, c, cache) if n else np.zeros(0, dtype=bool)
        v = valeurs.get(f"{c['direction']}_{c['horizon_h']}", np.zeros(0))
        connu = np.isfinite(v) if v.size else np.zeros(0, dtype=bool)
        js, xs = serie_journaliere(v, jour, unite, m & sel)
        r = {"id": c["id"], "direction": c["direction"], "horizon_h": c["horizon_h"],
             "predicats": [list(p) for p in c["predicats"]], "selection": resumer(xs, config, avec_bootstrap=not rapide),
             "n_decisions_selection": int((m & sel & connu).sum()),
             "n_unites_selection": int(np.unique(unite[m & sel & connu]).size)}
        if not rapide:
            r["exploration"] = resumer(serie_journaliere(v, jour, unite, m & explo)[1], config)
            r["validation"] = resumer(serie_journaliere(v, jour, unite, m & valid)[1], config)
            r["part_couts_mesures"] = _part_couts_mesures(table, m & sel & connu)
        if blocs:
            par_jour = dict(zip(js.tolist(), xs.tolist()))
            ligne = [float(np.mean([par_jour[d] for d in b if d in par_jour])) if any(d in par_jour for d in b)
                     else float("nan") for b in blocs]
            if all(math.isfinite(x) for x in ligne):
                matrices.setdefault((c["direction"], int(c["horizon_h"])), []).append(ligne)
        resultats.append(r)
    # DSR : N = TOUS les essais ; variance = essais COMPARABLES (meme direction, meme horizon), plancher 1/(T-1)
    n_essais = int(essais_anterieurs) + len(cellules)
    par_groupe: dict[tuple[str, int], list[float]] = {}
    for r in resultats:
        s = r["selection"].get("sharpe_jour", float("nan"))
        if math.isfinite(s):
            par_groupe.setdefault((r["direction"], int(r["horizon_h"])), []).append(float(s))
    var_groupe = {g: float(np.var(v, ddof=1)) if len(v) >= 2 else 0.0 for g, v in par_groupe.items()}
    anterieurs = [float(s) for s in sharpes_anterieurs if isinstance(s, (int, float)) and math.isfinite(s)]
    var_anterieurs = float(np.var(anterieurs, ddof=1)) if len(anterieurs) >= 2 else 0.0
    for r in resultats:
        e, d = r["selection"], None
        if e.get("n_jours", 0) >= 2 and math.isfinite(e.get("sharpe_jour", float("nan"))):
            var_sr = max(var_groupe.get((r["direction"], int(r["horizon_h"])), 0.0), 1.0 / (e["n_jours"] - 1.0))
            if var_anterieurs > var_sr:
                var_sr = min(var_anterieurs, 4.0 * var_sr)          # l'histoire ne peut que durcir, sans exploser
            d = deflated_sharpe(e["sharpe_jour"], n_trials=n_essais, var_sr_trials=var_sr, n_obs=e["n_jours"],
                                skew=e["asymetrie"], kurt=e["kurtosis"])
            r["var_sr_utilisee"] = var_sr
            r["sr_max_attendu"] = d["sr_max_attendu"] if d else None
        r["dsr"] = d["dsr"] if d else None
    # PBO par (direction, horizon) : melanger « suivre » et « contrer » flatte la CSCV par construction
    pbo_groupes = {f"{g[0]}_{g[1]}h": (pbo_cscv(rows) if len(rows) >= 2 else
                                       {"pbo": None, "verdict": "INSUFFISANT (< 2 cellules completes)"})
                   for g, rows in sorted(matrices.items())}

    def porte_pbo(r: Mapping[str, Any]) -> bool:
        p = pbo_groupes.get(f"{r['direction']}_{r['horizon_h']}h", {}).get("pbo")
        return p is not None and p <= methode.pbo_max

    naif = {(r["direction"], r["horizon_h"]): r for r in resultats if not r["predicats"]}
    candidats = []
    for r in resultats:
        e, ref = r["selection"], naif.get((r["direction"], r["horizon_h"]))
        bat_naif = (not r["predicats"]) or (ref is not None and e.get("moyenne_bps", -math.inf)
                                            > ref["selection"].get("moyenne_bps", math.inf))
        v = r.get("validation", {})
        post_entree_ok = v.get("n_jours", 0) < 10 or v.get("moyenne_bps", 0.0) >= 0.0
        if (porte_pbo(r) and r["dsr"] is not None and r["dsr"] >= methode.dsr_seuil
                and e.get("n_jours", 0) >= methode.explo_min_jours
                and r["n_unites_selection"] >= GARDE_FOUS["min_unites"]
                and e.get("moyenne_bps", -1.0) > 0 and (bat_naif or not methode.exiger_bat_naif) and post_entree_ok):
            candidats.append(r)
    candidats.sort(key=lambda r: (-r["dsr"], -r["selection"]["moyenne_bps"], r["id"]))
    geles = {r["id"] for r in candidats[: config.max_geles]}
    # palier SURVEILLANCE : les meilleures cellules SAINES au rang du DSR, hors gels ; la preuve viendra du suivi
    saines = []
    for r in resultats:
        e, ref = r["selection"], naif.get((r["direction"], r["horizon_h"]))
        v = r.get("validation", {})
        if (r["id"] not in geles and r["predicats"] and porte_pbo(r) and r["dsr"] is not None
                and e.get("n_jours", 0) >= methode.explo_min_jours and r["n_unites_selection"] >= GARDE_FOUS["min_unites"]
                and e.get("moyenne_bps", -1.0) > 0 and ref is not None
                and e["moyenne_bps"] > ref["selection"].get("moyenne_bps", math.inf)
                and (v.get("n_jours", 0) < 10 or v.get("moyenne_bps", 0.0) >= 0.0)):
            saines.append(r)
    saines.sort(key=lambda r: (-r["dsr"], -r["selection"]["moyenne_bps"], r["id"]))
    surveillance = {r["id"] for r in saines[: config.max_surveillance]}
    retenus_bh: set[str] = set()
    if not rapide:
        p = {r["id"]: r["validation"]["p_un_cote"] for r in candidats if "p_un_cote" in r.get("validation", {})}
        retenus_bh = benjamini_hochberg(p, GARDE_FOUS["q_fdr"]) if p else set()
    for r in resultats:
        e, v = r.get("exploration", {}), r.get("validation", {})
        couts_ok = r.get("part_couts_mesures", 0.0) >= 0.9         # jamais refuter sur des couts supposes
        refute_explo = (couts_ok and r["direction"] == "suivre" and e.get("n_jours", 0) >= GARDE_FOUS["explo_min_jours"]
                        and e.get("ic95", [0, 0])[1] < 0)          # biais pro-« suivre » ET quand meme negatif
        refute_valid = couts_ok and v.get("n_jours", 0) >= GARDE_FOUS["forward_min_jours"] and v.get("ic95", [0, 0])[1] < 0
        r["statut"] = ("CANDIDAT_GELE" if r["id"] in geles else "REFUTEE" if (refute_explo or refute_valid)
                       else "SURVEILLANCE" if r["id"] in surveillance else "MORE_DATA")
        r["validation_bh_retenue"] = r["id"] in retenus_bh
    pires = [x["pbo"] for x in pbo_groupes.values() if x.get("pbo") is not None]
    return {"schema": SCHEMA, "juge_version": JUGE_VERSION, "methode": methode.as_dict(), "n_cellules": len(cellules),
            "n_essais_dsr": n_essais, "variance_sharpes_par_groupe": {f"{g[0]}_{g[1]}h": v for g, v in sorted(var_groupe.items())},
            "variance_sharpes_anterieurs": var_anterieurs, "pbo_par_groupe": pbo_groupes,
            "pbo": {"pbo": max(pires) if pires else None, "lecture": "le PIRE des groupes (direction, horizon)"},
            "geles": [r for r in resultats if r["id"] in geles],
            "surveillance": [r for r in resultats if r["statut"] == "SURVEILLANCE"], "resultats": resultats,
            "jours_selection": int(jours_sel.size),
            "jours_exploration": int(np.unique(jour[explo]).size) if explo.any() else 0,
            "jours_validation": int(np.unique(jour[valid]).size) if valid.any() else 0}


def verdict_campagne(rapport: Mapping[str, Any]) -> dict[str, Any]:
    """Une campagne ne rend jamais mieux que MORE_DATA : seul le suivi apres gel peut promouvoir."""
    n_geles = len(rapport["geles"])
    n_surv = len(rapport.get("surveillance", []))
    refutees = sum(1 for r in rapport["resultats"] if r["statut"] == "REFUTEE")
    pbo = {k: v.get("pbo") for k, v in rapport.get("pbo_par_groupe", {}).items()}
    if n_geles:
        raison = (f"{n_geles} candidat(s) gele(s) sur {rapport['n_cellules']} cellules (DSR >= seuil avec N = "
                  f"{rapport['n_essais_dsr']} essais, PBO par groupe {pbo}) ; preuve attendue : "
                  f"{int(GARDE_FOUS['forward_min_jours'])} jours de SUIVI apres le gel")
    else:
        raison = (f"aucun candidat sur {rapport['n_cellules']} cellules (N = {rapport['n_essais_dsr']} essais, PBO par "
                  f"groupe {pbo}) ; {refutees} refutee(s) sur couts mesures ; {n_surv} cellule(s) mise(s) en "
                  f"SURVEILLANCE (reperage : la preuve viendra de {int(GARDE_FOUS['forward_min_jours'])} jours de suivi)")
    return {"hypothesis": HYPOTHESE, "status": "MORE_DATA", "reason": raison}


def primaire(rapport: Mapping[str, Any]) -> dict[str, Any]:
    """Mesure resumee pour le planificateur : le meilleur gele (sinon le meilleur DSR), lu sur sa part POST-ENTREE."""
    pool = rapport["geles"] or sorted(rapport["resultats"], key=lambda r: -(r["dsr"] or 0.0))[:1]
    if not pool:
        return {}
    r = pool[0]
    v = r.get("validation", {})
    return {"cellule": r["id"], "direction": r["direction"], "horizon_h": r["horizon_h"], "predicats": r["predicats"],
            "dsr_selection": r["dsr"], "moyenne_selection_bps": r["selection"].get("moyenne_bps"),
            "effet_bps_par_decision": v.get("moyenne_bps"), "intervalle_bps_par_decision": v.get("ic95"),
            "jours": v.get("n_jours", 0), "jours_requis": int(GARDE_FOUS["forward_min_jours"]),
            "gele": bool(rapport["geles"]), "juge_version": rapport.get("juge_version")}


# =========================================================================== memoire scientifique

def mettre_a_jour_memoire(memoire: Mapping[str, Any] | None, rapport: Mapping[str, Any], *, campagne: str,
                          cle_donnees: str | None = None) -> dict[str, Any]:
    """Chaque predicat retient s'il a AIDE (bat la copie sans filtre, meme direction et horizon) ; angles morts notes.

    Memes donnees que la campagne precedente (``cle_donnees`` identique) : aucun compte n'est rajoute -- la meme
    preuve relue n'est pas une preuve de plus."""
    memo = json.loads(json.dumps(memoire or {"predicats": {}, "cellules": {}, "campagnes": []}))
    if cle_donnees is not None and memo.get("derniere_cle_donnees") == cle_donnees:
        return memo
    naif = {(r["direction"], r["horizon_h"]): r for r in rapport["resultats"] if not r["predicats"]}
    angles_morts = []
    for r in rapport["resultats"]:
        e = r["selection"]
        memo["cellules"].setdefault(r["id"], []).append(
            {"campagne": campagne, "selection": e.get("moyenne_bps"), "valid": r.get("validation", {}).get("moyenne_bps"),
             "dsr": r["dsr"], "statut": r["statut"]})
        if len(r["predicats"]) != 1:
            continue
        dim, val = r["predicats"][0]
        ref = naif.get((r["direction"], r["horizon_h"]))
        if e.get("n_jours", 0) < 10 or ref is None or "moyenne_bps" not in ref["selection"]:
            angles_morts.append(f"{r['direction']}|{dim}={val}|{r['horizon_h']}h ({e.get('n_jours', 0)} j)")
            continue
        cle = f"{r['direction']}|{dim}={val}"
        p = memo["predicats"].setdefault(cle, {"aide": 0, "echec": 0})
        p["aide" if e["moyenne_bps"] > ref["selection"]["moyenne_bps"] else "echec"] += 1
    memo["campagnes"].append({"campagne": campagne, "n_cellules": rapport["n_cellules"],
                              "n_geles": len(rapport["geles"]), "pbo": rapport["pbo"].get("pbo"),
                              "juge_version": rapport.get("juge_version"), "cle_donnees": cle_donnees})
    memo["angles_morts"] = sorted(set(angles_morts))
    memo["derniere_cle_donnees"] = cle_donnees
    return memo


__all__ = ["ACTIONS", "DIMENSIONS", "DIRECTIONS", "DecouverteConfig", "EVIDENCE_TIER", "FAMILLE", "GARDE_FOUS",
           "HYPOTHESE", "JUGE_VERSION", "Methode", "SCHEMA", "attribuer_populations", "benjamini_hochberg",
           "decisions_depuis_episodes", "enrichir", "generer_cellules", "id_cellule", "juger_campagne", "masque_cellule",
           "mettre_a_jour_memoire", "primaire", "resumer", "serie_journaliere", "verdict_campagne"]
