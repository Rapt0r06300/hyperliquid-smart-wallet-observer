"""Persistance de la compétence des vaults : la condition nécessaire d'une copie lente.

QUESTION. Copier un vault lentement (répliquer son portefeuille à faible fréquence) n'a de sens
que si un vault qui a bien performé CONTINUE de bien performer une fois qu'on l'a choisi. Si le
classement passé ne prédit pas le rendement suivant, aucune règle de sélection de leaders ne peut
gagner, quels que soient l'exécution et les coûts. Ce module mesure donc, sur les courbes
valeur / PnL publiées par Hyperliquid (famille ``vault_portfolio`` du coffre), si cette
persistance existe, et ce qu'il en resterait après le coût d'une réplication.

MÉTHODE (marche avant, point dans le temps).
* Rendement d'une période = ΔPnL / capital moyen (méthode de Dietz simple) : un dépôt ou un
  retrait n'est jamais compté comme un gain ou une perte.
* À chaque date, chaque vault est noté UNIQUEMENT sur ses ``formation`` périodes passées, puis
  comparé à son rendement de la période suivante. Aucune donnée postérieure n'entre dans la note.
* Mesures : corrélation de rang note → rendement suivant (IC), excès du meilleur quantile sur
  « copier tout le monde », placebo par permutation des notes, intervalles par bootstrap sur les
  dates, correction de multiplicité sur le nombre de configurations essayées.
* Coût : rotation du leader (volume traité / capital) × coût par unité de notionnel. C'est une
  BORNE HAUTE du coût d'un copieur qui reproduirait chaque transaction. Rotation inconnue =
  coût inconnu (jamais zéro).

LIMITES DÉCLARÉES. Les courbes ne couvrent que les vaults suivis aujourd'hui (survivants) : le
niveau de rendement est biaisé vers le haut, le classement relatif l'est moins. Le rendement
total d'un vault inclut son trading intrajournalier, non réplicable lentement : une persistance
mesurée ici est NÉCESSAIRE, pas suffisante. Résultat EXPLORATOIRE (tier LOCAL), jamais une preuve.
"""
from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass
from typing import Any

import numpy as np
from scipy.stats import rankdata

# v2 (2026-11-11) : la note bayésienne v1 dégénérait (toutes les notes égales) dès que la variance
# entre vaults passait sous le bruit moyen — 57 dates sur 86 dans l'analyse primaire réelle. Le
# « meilleur quantile » était alors les premiers vaults du tableau (ordre des adresses) et l'IC de
# la date disparaissait sans trace. v2 : estimateur à effets aléatoires pondéré par la précision,
# égalités départagées en espérance, vaults inactifs hors univers, dates dégénérées comptées.
SCHEMA_VERSION = "hypersmart.copy_vault_persistence.v2"
SEUIL_ACTIVITE = 1e-12        # écart-type des rendements en deçà duquel un vault n'a rien fait
H_PERSISTENCE = "copy_vault_leader_skill_persistence"
EVIDENCE_TIER = "LOCAL_RETROSPECTIVE_PORTFOLIO_CURVES"
DAY_MS = 86_400_000
SCORES = ("moyenne_bayes", "moyenne", "sharpe")


@dataclass(frozen=True, slots=True)
class PersistenceConfig:
    """Paramètres déclarés AVANT la mesure. La première valeur de chaque grille est l'analyse primaire."""

    period_days: tuple[int, ...] = (7, 1, 30)
    formation_periods: tuple[int, ...] = (8, 4, 12)
    scores: tuple[str, ...] = SCORES
    min_capital_usd: float = 10_000.0      # capital moyen minimal pour qu'un rendement ait un sens
    min_vaults_per_date: int = 10
    min_dates: int = 12
    top_fraction: float = 0.2
    stale_fraction: float = 0.25           # âge maximal d'un point, en fraction de la période
    cost_bps_per_notional: float = 6.0     # frais taker 4,5 bps + demi-écart 1,5 bps
    slow_turnover_per_day: float = 0.5     # « leader lent » : moins de 0,5 fois son capital traité par jour
    bootstrap_samples: int = 2_000
    permutation_samples: int = 2_000
    confidence: float = 0.95
    negligible_ic: float = 0.05
    dates_for_rejection: int = 40
    capital_usd: float = 350.0
    seed: int = 20_261_111

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


# --------------------------------------------------------------------------- rotation du leader

_JOURS_FENETRE = {"month": 30.0, "week": 7.0, "day": 1.0}     # ordre de préférence : la plus longue d'abord


def turnover_per_day(
    lignes: Sequence[Mapping[str, Any]],
    curves: Mapping[str, Sequence[tuple[int, float | None, float | None]]],
) -> dict[str, float | None]:
    """Rotation quotidienne de chaque vault : volume traité par jour / capital moyen de la fenêtre.

    Prend la tranche la plus récente de la fenêtre la plus longue disponible (mois, sinon semaine,
    sinon jour). Volume ou capital absent -> ``None`` : une rotation inconnue n'est jamais nulle.
    """
    retenu: dict[str, tuple[tuple[int, int], str, float, int]] = {}
    preference = list(_JOURS_FENETRE)
    for ligne in lignes:
        vault = str(ligne.get("vault") or "").strip().lower()
        fenetre, volume, observation = ligne.get("fenetre"), ligne.get("vlm_fenetre_usd"), ligne.get("observed_at_ms")
        if not vault or fenetre not in _JOURS_FENETRE or volume is None or not isinstance(observation, int):
            continue
        cle = (-preference.index(fenetre), observation)
        if vault not in retenu or cle > retenu[vault][0]:
            retenu[vault] = (cle, str(fenetre), float(volume), observation)
    sortie: dict[str, float | None] = {}
    for vault, curve in curves.items():
        if vault not in retenu:
            sortie[vault] = None
            continue
        _, fenetre, volume, observation = retenu[vault]
        jours = _JOURS_FENETRE[fenetre]
        debut = observation - int(jours * DAY_MS)
        capitaux = [v for ts, v, _ in curve if debut <= ts <= observation and v is not None and v > 0]
        sortie[vault] = (volume / jours) / float(np.mean(capitaux)) if capitaux else None
    return sortie


# --------------------------------------------------------------------------- rendements

def _valeur_a(ts: np.ndarray, valeurs: np.ndarray, borne: int, stale_ms: int) -> float:
    """Dernière valeur CONNUE à ``borne`` (jamais postérieure), si elle n'est pas trop ancienne."""
    connus = np.flatnonzero(~np.isnan(valeurs) & (ts <= borne))
    if connus.size == 0:
        return float("nan")
    index = connus[-1]
    return float(valeurs[index]) if borne - int(ts[index]) <= stale_ms else float("nan")


def period_returns(
    curve: Sequence[tuple[int, float | None, float | None]], *, period_days: int,
    config: PersistenceConfig | None = None,
) -> dict[int, dict[str, float]]:
    """Rendements par période calendaire UTC (grille commune à tous les vaults).

    Renvoie ``{indice_de_période: {"ret", "capital", "valeur_debut"}}``. Une période dont une
    borne n'a pas de point assez récent est ABSENTE (inconnue), jamais prolongée ni interpolée.
    """
    config = config or PersistenceConfig()
    if not curve:
        return {}
    period_ms = int(period_days) * DAY_MS
    stale_ms = int(period_ms * config.stale_fraction)
    ts = np.array([int(point[0]) for point in curve], dtype=np.int64)
    ordre = np.argsort(ts, kind="stable")
    ts = ts[ordre]
    valeur = np.array([np.nan if curve[i][1] is None else float(curve[i][1]) for i in ordre], dtype=float)
    pnl = np.array([np.nan if curve[i][2] is None else float(curve[i][2]) for i in ordre], dtype=float)
    # première borne de grille à partir du premier point (incluse s'il tombe exactement dessus)
    premier, dernier = -(-int(ts[0]) // period_ms), int(ts[-1]) // period_ms
    bornes: dict[int, tuple[float, float]] = {}
    for k in range(premier, dernier + 1):
        borne = k * period_ms
        bornes[k] = (_valeur_a(ts, valeur, borne, stale_ms), _valeur_a(ts, pnl, borne, stale_ms))
    sortie: dict[int, dict[str, float]] = {}
    for k in range(premier, dernier):
        (v0, p0), (v1, p1) = bornes[k], bornes[k + 1]
        if any(np.isnan(x) for x in (v0, p0, v1, p1)):
            continue
        gain = p1 - p0
        flux = v1 - v0 - gain                       # dépôts nets des retraits sur la période
        capital = v0 + 0.5 * flux                   # Dietz simple : capital moyen engagé
        if capital < config.min_capital_usd or v0 <= 0:
            continue
        sortie[k] = {"ret": gain / capital, "capital": capital, "valeur_debut": v0, "flux_ratio": flux / capital}
    return sortie


def return_matrix(
    curves: Mapping[str, Sequence[tuple[int, float | None, float | None]]], *, period_days: int,
    config: PersistenceConfig | None = None,
) -> tuple[list[str], np.ndarray, np.ndarray]:
    """Matrice vaults × périodes (``NaN`` = inconnu) et indices des périodes."""
    config = config or PersistenceConfig()
    par_vault = {vault: period_returns(curve, period_days=period_days, config=config)
                 for vault, curve in sorted(curves.items())}
    periodes = sorted({k for rendements in par_vault.values() for k in rendements})
    vaults = [vault for vault, rendements in par_vault.items() if rendements]
    if not periodes or not vaults:
        return [], np.empty((0, 0)), np.array([], dtype=np.int64)
    colonne = {k: j for j, k in enumerate(periodes)}
    matrice = np.full((len(vaults), len(periodes)), np.nan)
    for i, vault in enumerate(vaults):
        for k, cellule in par_vault[vault].items():
            matrice[i, colonne[k]] = cellule["ret"]
    return vaults, matrice, np.array(periodes, dtype=np.int64)


# --------------------------------------------------------------------------- notes (passé seulement)

def score_formation(fenetre: np.ndarray, score: str) -> np.ndarray:
    """Note de chaque vault sur sa fenêtre de formation (lignes = vaults, colonnes = périodes passées).

    Un vault sans aucune variation sur toute la fenêtre (inactif) n'a rien à copier : il n'est pas
    noté (``NaN``), quelle que soit la note. La règle n'utilise que le passé.
    """
    if score not in SCORES:
        raise ValueError(f"score inconnu : {score}")
    moyenne = fenetre.mean(axis=1)
    ecart = fenetre.std(axis=1, ddof=1) if fenetre.shape[1] > 1 else np.full(fenetre.shape[0], np.nan)
    actif = ecart > SEUIL_ACTIVITE
    if score == "moyenne":
        return np.where(actif, moyenne, np.nan)
    if score == "sharpe":
        return np.where(actif, moyenne / np.where(actif, ecart, 1.0), np.nan)
    return _moyenne_bayes(moyenne, ecart ** 2 / fenetre.shape[1], actif)


def _moyenne_bayes(moyenne: np.ndarray, bruit: np.ndarray, actif: np.ndarray) -> np.ndarray:
    """Bayes empirique à effets aléatoires (DerSimonian–Laird) : chaque moyenne est ramenée vers le
    centre de l'univers d'autant plus fortement que son estimation est bruitée.

    La dispersion vraie entre vaults est estimée avec des poids de précision : quelques vaults très
    volatils ne peuvent plus l'annuler à eux seuls. Si elle reste indétectable, la note est la
    LIMITE de la formule quand cette dispersion tend vers zéro (écart au centre pondéré par la
    précision) : le classement reste défini, jamais une égalité générale.
    """
    notes = np.full(moyenne.shape, np.nan)
    if int(actif.sum()) < 2:
        return notes
    m, b = moyenne[actif], bruit[actif]
    w = 1.0 / b
    centre_fixe = float((w * m).sum() / w.sum())
    q = float((w * (m - centre_fixe) ** 2).sum())
    denominateur = float(w.sum() - (w ** 2).sum() / w.sum())
    dispersion = max(0.0, (q - (m.size - 1)) / denominateur) if denominateur > 0 else 0.0
    if dispersion > 0:
        w_etoile = 1.0 / (b + dispersion)
        centre = float((w_etoile * m).sum() / w_etoile.sum())
        poids = dispersion / (dispersion + b)
    else:
        centre, poids = centre_fixe, b.min() / b
    notes[actif] = centre + poids * (m - centre)
    return notes


def _poids_quantile(notes: np.ndarray, taille: int) -> np.ndarray:
    """Poids de sélection du meilleur quantile (somme = ``taille``). Des notes égales au seuil se
    partagent les places restantes : c'est l'espérance d'un départage au hasard. L'ordre du tableau
    (l'ordre des adresses) ne décide jamais de qui est retenu."""
    seuil = np.sort(notes)[-taille]
    dessus, egal = notes > seuil, notes == seuil
    poids = dessus.astype(float)
    poids[egal] = (taille - int(dessus.sum())) / int(egal.sum())
    return poids


def _spearman(a: np.ndarray, b: np.ndarray) -> float:
    ra, rb = rankdata(a), rankdata(b)
    sa, sb = ra.std(), rb.std()
    if sa == 0 or sb == 0:
        return float("nan")
    return float(((ra - ra.mean()) * (rb - rb.mean())).mean() / (sa * sb))


def evaluer_notes(
    matrice: np.ndarray, notes_par_date: Mapping[int, np.ndarray], *, config: PersistenceConfig | None = None,
    cout_par_periode: np.ndarray | None = None,
) -> list[dict[str, Any]]:
    """Une ligne par date notée : IC, quantile de tête, univers. ``notes_par_date[t]`` = note de
    chaque vault AVANT la période ``t`` (``NaN`` = non noté) ; le rendement réalisé est ``matrice[:, t]``.

    Fonction commune à toutes les règles de sélection (performance passée, modèle...) : elles sont
    ainsi jugées par exactement la même mesure, les mêmes quantiles et les mêmes coûts.
    """
    config = config or PersistenceConfig()
    lignes: list[dict[str, Any]] = []
    for t in sorted(notes_par_date):
        notes = notes_par_date[t]
        suivants = matrice[:, t]
        selectionnables = ~np.isnan(notes)
        mesurables = selectionnables & ~np.isnan(suivants)
        if int(mesurables.sum()) < config.min_vaults_per_date:
            continue
        n, r = notes[mesurables], suivants[mesurables]
        taille = max(1, int(round(config.top_fraction * n.size)))
        tete, queue = _poids_quantile(n, taille), _poids_quantile(-n, taille)
        ligne: dict[str, Any] = {
            "t": t, "n": int(n.size), "ic": _spearman(n, r),
            "tete": float((tete * r).sum() / taille), "univers": float(r.mean()),
            "queue": float((queue * r).sum() / taille),
            "note_degeneree": bool(np.ptp(n) == 0),          # la note ne départage personne à cette date
            # vaults notés dont le rendement suivant est introuvable (arrêt, trou de données) :
            # une attrition élevée signale un biais de survie possible sur la période.
            "attrition": float(1.0 - mesurables.sum() / max(1, selectionnables.sum())),
            "_notes": n, "_rendements": r, "_taille": taille,
        }
        if cout_par_periode is not None:
            couts = cout_par_periode[mesurables]
            retenus = tete > 0
            ligne["tete_nette"] = (
                float((tete[retenus] * (r[retenus] - couts[retenus])).sum() / taille)
                if not np.isnan(couts[retenus]).any() else None
            )
            connus = ~np.isnan(couts)
            ligne["univers_net"] = float((r[connus] - couts[connus]).mean()) if connus.any() else None
        lignes.append(ligne)
    return lignes


def walk_forward(
    matrice: np.ndarray, *, formation: int, score: str, config: PersistenceConfig | None = None,
    cout_par_periode: np.ndarray | None = None,
) -> list[dict[str, Any]]:
    """Sélection sur la performance passée : note = périodes ``[t-formation, t)``, jamais au-delà."""
    config = config or PersistenceConfig()
    notes_par_date: dict[int, np.ndarray] = {}
    for t in range(formation, matrice.shape[1]):
        passe = matrice[:, t - formation:t]
        notables = ~np.isnan(passe).any(axis=1)
        if int(notables.sum()) < config.min_vaults_per_date:
            continue
        notes = np.full(matrice.shape[0], np.nan)
        notes[notables] = score_formation(passe[notables], score)
        notes_par_date[t] = notes
    return evaluer_notes(matrice, notes_par_date, config=config, cout_par_periode=cout_par_periode)


# --------------------------------------------------------------------------- agrégation

def _intervalle(valeurs: np.ndarray, *, niveau: float, config: PersistenceConfig, rng: np.random.Generator,
                ) -> tuple[float, float]:
    if valeurs.size < 2:
        return float("nan"), float("nan")
    tirages = rng.integers(0, valeurs.size, size=(config.bootstrap_samples, valeurs.size))
    moyennes = valeurs[tirages].mean(axis=1)
    alpha = (1.0 - niveau) / 2.0
    return float(np.quantile(moyennes, alpha)), float(np.quantile(moyennes, 1.0 - alpha))


def summarize(lignes: list[dict[str, Any]], *, period_days: int, niveau: float,
              config: PersistenceConfig | None = None) -> dict[str, Any]:
    """Synthèse d'une configuration : moyennes, intervalles (bootstrap sur les dates), placebo."""
    config = config or PersistenceConfig()
    rng = np.random.default_rng(config.seed)
    if not lignes:
        return {"dates": 0}
    ic = np.array([ligne["ic"] for ligne in lignes], dtype=float)
    ic_indefinis = int(np.isnan(ic).sum())
    ic = ic[~np.isnan(ic)]
    exces = np.array([ligne["tete"] - ligne["univers"] for ligne in lignes], dtype=float)
    ecart = np.array([ligne["tete"] - ligne["queue"] for ligne in lignes], dtype=float)
    univers = np.array([ligne["univers"] for ligne in lignes], dtype=float)
    tete = np.array([ligne["tete"] for ligne in lignes], dtype=float)
    # Placebo : les notes sont permutées entre vaults à chaque date. Toute structure (taille des
    # quantiles, dates, dispersion) est conservée ; seule l'information de la note est détruite.
    placebo = np.zeros(config.permutation_samples)
    for ligne in lignes:
        r, taille = ligne["_rendements"], ligne["_taille"]
        tirages = np.argsort(rng.random((config.permutation_samples, r.size)), axis=1)[:, :taille]
        placebo += r[tirages].mean(axis=1) - r.mean()
    placebo /= len(lignes)
    p_placebo = float((1 + np.sum(placebo >= exces.mean())) / (1 + placebo.size))
    bps_jour = 1e4 / period_days
    sortie: dict[str, Any] = {
        "dates": len(lignes),
        # dates où l'IC n'existe pas (notes ou rendements tous égaux) : comptées, jamais passées sous silence
        "dates_ic_indefini": ic_indefinis,
        "dates_note_degeneree": int(sum(1 for ligne in lignes if ligne.get("note_degeneree"))),
        "vaults_median_par_date": float(np.median([ligne["n"] for ligne in lignes])),
        "attrition_moyenne": float(np.mean([ligne["attrition"] for ligne in lignes])),
        "ic_moyen": float(ic.mean()) if ic.size else None,
        "ic_intervalle": _intervalle(ic, niveau=niveau, config=config, rng=rng) if ic.size else None,
        "ic_autocorrelation_1": (
            float(np.corrcoef(ic[:-1], ic[1:])[0, 1]) if ic.size > 3 and ic[:-1].std() > 0 and ic[1:].std() > 0
            else None),
        "part_dates_ic_positif": float((ic > 0).mean()) if ic.size else None,
        "exces_tete_bps_jour": float(exces.mean() * bps_jour),
        "exces_tete_intervalle_bps_jour": tuple(
            x * bps_jour for x in _intervalle(exces, niveau=niveau, config=config, rng=rng)),
        "ecart_tete_queue_bps_jour": float(ecart.mean() * bps_jour),
        "tete_bps_jour": float(tete.mean() * bps_jour),
        "univers_bps_jour": float(univers.mean() * bps_jour),
        "p_placebo_exces_tete": p_placebo,
        "niveau_intervalle": niveau,
    }
    nets = [ligne.get("tete_nette") for ligne in lignes]
    if nets and all(valeur is not None for valeur in nets):
        net = np.array(nets, dtype=float)
        sortie["tete_nette_bps_jour"] = float(net.mean() * bps_jour)
        sortie["tete_nette_intervalle_bps_jour"] = tuple(
            x * bps_jour for x in _intervalle(net, niveau=niveau, config=config, rng=rng))
        sortie["tete_nette_usd_jour_sur_capital"] = float(net.mean() / period_days * config.capital_usd)
    else:
        sortie["tete_nette_bps_jour"] = None      # rotation inconnue pour au moins un vault retenu
    return sortie


def verdict_persistance(primaire: Mapping[str, Any], config: PersistenceConfig | None = None) -> dict[str, Any]:
    """Verdict de l'analyse primaire, règles fixées avant la mesure."""
    config = config or PersistenceConfig()
    base = {"hypothesis": H_PERSISTENCE, "evidence_tier": EVIDENCE_TIER, "economically_proven": False}
    dates = int(primaire.get("dates") or 0)
    if dates < config.min_dates or primaire.get("ic_intervalle") is None:
        return {**base, "status": "MORE_DATA",
                "reason": f"{dates} dates mesurables ; il en faut au moins {config.min_dates}"}
    ic_bas, ic_haut = primaire["ic_intervalle"]
    ex_bas, ex_haut = primaire["exces_tete_intervalle_bps_jour"]
    if ic_bas > 0 and ex_bas > 0:
        net = primaire.get("tete_nette_intervalle_bps_jour")
        if net is not None and net[0] > 0:
            return {**base, "status": "PROMISING",
                    "reason": "le classement passé prédit le rendement suivant et l'excès résiste à la borne "
                              "haute du coût de réplication ; à confirmer hors survivants et sur portefeuilles observés"}
        return {**base, "status": "MORE_DATA",
                "reason": "persistance mesurée avant coûts, mais le net de réplication n'est pas établi "
                          "(rotation inconnue ou excès absorbé par le coût) : mesurer la part d'inventaire réplicable"}
    if ic_haut <= 0 or ex_haut <= 0:
        return {**base, "status": "REJECTED",
                "reason": "aucune persistance : le classement passé ne prédit pas (ou prédit à l'envers) le rendement suivant"}
    if dates >= config.dates_for_rejection and ic_haut < config.negligible_ic:
        return {**base, "status": "REJECTED",
                "reason": f"persistance négligeable (IC < {config.negligible_ic}) malgré {dates} dates"}
    return {**base, "status": "MORE_DATA",
            "reason": "intervalle à cheval sur zéro : l'échantillon ne tranche pas"}


def _limite_univers(total: int, fermes: int | None) -> str:
    if not fermes:
        return "Univers = vaults suivis aujourd'hui (survivants) : le niveau des rendements est biaisé vers le haut."
    return (f"Univers élargi : {total} vaults dont {fermes} fermés (biais de survie réduit, pas supprimé : les "
            "vaults restés sous les seuils de taille du balayage n'y figurent pas).")


def run_persistence_study(
    curves: Mapping[str, Sequence[tuple[int, float | None, float | None]]],
    *, turnover_per_day: Mapping[str, float | None] | None = None,
    config: PersistenceConfig | None = None, extra_configurations: int = 0,
    closed_vaults: int | None = None,
) -> dict[str, Any]:
    """Étude complète : toutes les configurations, correction de multiplicité, segment « leaders lents ».

    ``closed_vaults`` : nombre de vaults FERMÉS présents dans les courbes (None = inconnu). La limite
    déclarée sur l'univers en dépend : elle ne doit pas annoncer un biais de survie déjà corrigé.

    ``extra_configurations`` : règles évaluées ailleurs sur les mêmes données (modèle de sélection) ;
    elles élargissent les intervalles de TOUTES les configurations, celles-ci comprises."""
    config = config or PersistenceConfig()
    turnover_per_day = turnover_per_day or {}
    grille = [(p, f, s) for p in config.period_days for f in config.formation_periods for s in config.scores]
    # Bonferroni : l'intervalle de chaque configuration est élargi par le nombre de configurations.
    niveau = 1.0 - (1.0 - config.confidence) / (len(grille) + max(0, int(extra_configurations)))
    configurations: list[dict[str, Any]] = []
    primaire: dict[str, Any] = {"dates": 0}
    segment_lent: dict[str, Any] = {"dates": 0}
    entrees: dict[str, Any] = {"vaults_avec_courbe": len(curves)}
    for period in config.period_days:
        vaults, matrice, periodes = return_matrix(curves, period_days=period, config=config)
        entrees[f"periodes_{period}j"] = int(periodes.size)
        entrees[f"vaults_mesurables_{period}j"] = len(vaults)
        if not vaults:
            continue
        rotation = np.array([np.nan if turnover_per_day.get(v) is None else float(turnover_per_day[v])
                             for v in vaults])
        cout = rotation * period * config.cost_bps_per_notional / 1e4
        for formation in config.formation_periods:
            for score in config.scores:
                lignes = walk_forward(matrice, formation=formation, score=score, config=config,
                                      cout_par_periode=cout)
                resume = summarize(lignes, period_days=period, niveau=niveau, config=config)
                est_primaire = (period, formation, score) == grille[0]
                configurations.append({"period_days": period, "formation_periods": formation,
                                       "score": score, "primaire": est_primaire, **resume})
                if est_primaire:
                    primaire = resume
                    lents = ~np.isnan(rotation) & (rotation < config.slow_turnover_per_day)
                    if int(lents.sum()) >= config.min_vaults_per_date:
                        segment_lent = summarize(
                            walk_forward(matrice[lents], formation=formation, score=score, config=config,
                                         cout_par_periode=cout[lents]),
                            period_days=period, niveau=niveau, config=config)
                        segment_lent["vaults"] = int(lents.sum())
    rotations = [float(v) for v in turnover_per_day.values() if v is not None]
    entrees["vaults_rotation_connue"] = len(rotations)
    entrees["rotation_mediane_par_jour"] = float(np.median(rotations)) if rotations else None
    return {
        "schema_version": SCHEMA_VERSION,
        "config": config.as_dict(),
        "inputs": entrees,
        "hypotheses_tested": len(grille) + max(0, int(extra_configurations)),
        "confidence_after_multiplicity": niveau,
        "primary": primaire,
        "slow_leaders_segment": segment_lent,
        "configurations": configurations,
        "verdicts": [verdict_persistance(primaire, config)],
        "baselines": {
            "ne_pas_trader_bps_jour": 0.0,
            "copier_tous_les_vaults_bps_jour": primaire.get("univers_bps_jour"),
            "copier_les_meilleurs_passes_bps_jour": primaire.get("tete_bps_jour"),
            "placebo_selection_aleatoire_p": primaire.get("p_placebo_exces_tete"),
        },
        "caveats": [
            _limite_univers(len(curves), closed_vaults),
            "Rendement total du vault (trading intrajournalier compris) : borne haute de ce qu'une réplication lente capte.",
            "Coût = rotation observée du leader × coût par notionnel : borne haute pour un copieur lent ; "
            "la rotation est mesurée à l'observation, pas période par période.",
            "Historique relu après coup (tier LOCAL) : exploratoire, jamais une preuve économique.",
            "Un vault sans aucune variation de PnL sur la fenêtre de formation est hors univers à cette date "
            "(rien à copier) ; « copier tout le monde » désigne donc les vaults actifs.",
        ],
        "paper_read_only": True,
        "real_execution": False,
        "economically_proven": False,
    }


__all__ = [
    "DAY_MS", "EVIDENCE_TIER", "H_PERSISTENCE", "PersistenceConfig", "SCHEMA_VERSION", "SCORES",
    "evaluer_notes", "period_returns", "return_matrix", "run_persistence_study", "score_formation", "summarize",
    "turnover_per_day", "verdict_persistance", "walk_forward",
]
