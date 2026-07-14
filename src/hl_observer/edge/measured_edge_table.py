"""Q1 -- L'EDGE BRUT VIENT D'UNE TABLE MESUREE. JAMAIS D'UNE FORMULE.

Le probleme, en une ligne de code (`opportunities/fresh_opportunity.py:342`) :

    return 14.0 + score_component + consensus_component + notional_component + tight_component

Huit constantes magiques (14, 0.55, 30, 9, 28, 25000, 16, 10). Zero mesure. Ce nombre est
l'`edge brut` de TOUTE la chaine de decision : `edge_net = edge_brut - couts`. Si le brut est
invente, le net est invente, et le refus « edge insuffisant » ne refuse rien de reel.

Le meme mensonge existe une 2e fois (`copy_wallet/wallet_mirror_runtime.py:144`) :

    expected_edge = 24.0 + score * 24.0 + copyability * 18.0

Ce module le remplace par la SEULE source honnete : **ce que le prix a REELLEMENT fait**, apres
un signal du meme type, mesure sur des donnees passees.

  edge brut mesure = markout realise = sens * (mid(T+H) - mid(T)) / mid(T) * 10000

Trois disciplines, non negociables :

1. **BORNE BASSE, pas moyenne.** On prend `moyenne - z x erreur_standard` (IC 95 % par defaut).
   Une moyenne de +5 bps sur 3 observations n'est pas un edge, c'est du bruit. La borne basse
   l'ecrase toute seule ; on n'a pas besoin d'y penser.

2. **PAS DE DONNEE -> PAS DE TRADE.** Un bucket sans assez d'echantillons ne rend PAS une valeur
   par defaut, ne rend PAS une moyenne globale, ne rend PAS zero. Il rend `None`, et l'appelant
   doit refuser. C'est le `INSUFFICIENT_DATA` de CLAUDE.md.

3. **ANTI-LOOKAHEAD.** La table porte `construite_jusqu_a_ms`. Un signal ANTERIEUR a cette date
   a ete VU par la table : l'interroger, c'est lire son propre futur. Refus dur.

Ce module est PUR (aucune I/O, aucun reseau). Lecture seule. Aucun ordre, aucune cle,
aucune signature.
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass, field
from typing import Iterable, Sequence

# ------------------------------------------------------------------ raisons (jamais muettes)

EDGE_MESURE_OK = "EDGE_MESURE"
EDGE_BUCKET_VIDE = "EDGE_NON_MESURE_POUR_CE_BUCKET"
EDGE_TABLE_ABSENTE = "EDGE_TABLE_ABSENTE"
EDGE_TABLE_LOOKAHEAD = "EDGE_TABLE_LOOKAHEAD"
EDGE_FEATURES_INCOMPLETES = "EDGE_FEATURES_INCOMPLETES"

# Le sens du trade. Un sens indechiffrable n'est pas un LONG par defaut : c'est un refus.
_LONG = {"LONG", "BUY", "B", "L", "1", "+1", "BID", "OPEN_LONG"}
_SHORT = {"SHORT", "SELL", "S", "-1", "ASK", "OPEN_SHORT"}


def sens_du_trade(direction: object) -> int:
    """+1 LONG, -1 SHORT, 0 = indechiffrable (et 0 veut dire REFUS, pas 'neutre')."""
    d = str(direction or "").strip().upper()
    if d in _LONG:
        return 1
    if d in _SHORT:
        return -1
    return 0


def markout_bps(*, mid_entree: float, mid_futur: float, direction: object) -> float | None:
    """Le seul edge brut honnete : ce que le prix a FAIT, dans le sens du trade.

    Rend None si la mesure est impossible (prix absent/nul, sens indechiffrable). None n'est
    PAS zero : zero serait une affirmation ('le prix n'a pas bouge'), None est un aveu
    ('je ne sais pas'). Confondre les deux, c'est fabriquer de la donnee.
    """
    s = sens_du_trade(direction)
    if s == 0:
        return None
    try:
        e = float(mid_entree)
        f = float(mid_futur)
    except (TypeError, ValueError):
        return None
    if not (e > 0.0) or not (f > 0.0):
        return None
    return s * (f - e) / e * 10_000.0


# ------------------------------------------------------------------ les BUCKETS
#
# Un bucket doit etre assez FIN pour que « l'edge » veuille dire quelque chose, et assez LARGE
# pour qu'il y ait des echantillons dedans. On expose donc DEUX niveaux, explicitement, et le
# resultat dit TOUJOURS lequel a servi. Pas de cascade silencieuse vers un chiffre plus vague.


def _bande(valeur: float | None, bornes: Sequence[float]) -> str:
    if valeur is None:
        return "NA"
    v = float(valeur)
    for i, b in enumerate(bornes):
        if v < b:
            return "b%d" % i
    return "b%d" % len(bornes)


BORNES_AGE_MS: tuple[float, ...] = (1_000.0, 3_000.0, 10_000.0, 30_000.0)
BORNES_SCORE: tuple[float, ...] = (55.0, 65.0, 75.0, 85.0)
BORNES_CONSENSUS: tuple[float, ...] = (2.0, 3.0, 5.0)

# 🔴 Combien de marches DISTINCTS faut-il pour avoir le droit de generaliser ?
# Une cellule LARGE (`STRAT|*|...`) sert un coin qu'on n'a jamais mesure. Si elle n'a ete
# nourrie que par un seul marche, elle ne generalise rien : elle deguise BTC en HMSTR.
# Cinq marches n'est pas un chiffre magique, c'est un minimum defendable -- en dessous, la
# dispersion inter-marches n'est meme pas estimable.
MIN_COINS_POUR_LARGE = 5


@dataclass(frozen=True, slots=True)
class Features:
    """Ce que la DECISION connait au moment ou elle decide. Rien de plus."""

    strategie: str
    coin: str
    direction: str
    signal_age_ms: float | None = None
    leader_score: float | None = None
    consensus_wallets: float | None = None

    def cles(self) -> tuple[str, str]:
        """(cle fine, cle large). La fine porte le coin ; la large ne le porte pas.

        Pourquoi la large existe : 232 marches x 5 bandes d'age = trop de buckets vides. Pourquoi
        elle ne descend PAS plus bas : sans l'age du signal, « l'edge » ne veut plus rien dire
        (la fraicheur est le seul levier qu'on ait mesure -- 09/07).
        """
        strat = (self.strategie or "?").strip().upper()
        coin = (self.coin or "?").strip().upper()
        age = _bande(self.signal_age_ms, BORNES_AGE_MS)
        score = _bande(self.leader_score, BORNES_SCORE)
        cons = _bande(self.consensus_wallets, BORNES_CONSENSUS)
        fine = "|".join((strat, coin, "age" + age, "sc" + score, "cw" + cons))
        large = "|".join((strat, "*", "age" + age, "sc" + score, "cw" + cons))
        return fine, large


@dataclass(frozen=True, slots=True)
class Cellule:
    cle: str
    n: int
    moyenne_bps: float
    ecart_type_bps: float
    borne_basse_bps: float

    def as_dict(self) -> dict[str, object]:
        return {
            "cle": self.cle,
            "n": self.n,
            "moyenne_bps": round(self.moyenne_bps, 6),
            "ecart_type_bps": round(self.ecart_type_bps, 6),
            "borne_basse_bps": round(self.borne_basse_bps, 6),
        }


@dataclass(frozen=True, slots=True)
class ResultatEdge:
    """Ce que la decision recoit. `edge_brut_bps is None` => REFUS. Jamais de valeur par defaut."""

    mesure: bool
    edge_brut_bps: float | None
    raison: str
    niveau: str = ""          # "fin" | "large" | ""
    n: int = 0
    moyenne_bps: float | None = None
    cle: str = ""

    def as_dict(self) -> dict[str, object]:
        return {
            "mesure": self.mesure,
            "edge_brut_bps": self.edge_brut_bps,
            "raison": self.raison,
            "niveau": self.niveau,
            "n": self.n,
            "moyenne_bps": self.moyenne_bps,
            "cle": self.cle,
            "source": "TABLE_MESUREE",
        }


@dataclass(frozen=True, slots=True)
class TableEdgeMesuree:
    horizon_ms: int
    construite_jusqu_a_ms: int
    min_echantillons: int
    z: float
    cellules: dict[str, Cellule] = field(default_factory=dict)
    source: str = "REPLAY"        # LIVE | BACKTEST | REPLAY | TEST_FIXTURE (CLAUDE.md)
    n_observations: int = 0

    # -------------------------------------------------------------- l'interrogation

    def chercher(self, features: Features, *, signal_ms: int | float | None = None) -> ResultatEdge:
        """L'unique porte d'entree. Rend `edge_brut_bps=None` des qu'on ne SAIT pas."""
        if not self.cellules:
            return ResultatEdge(False, None, EDGE_TABLE_ABSENTE)

        # --- ANTI-LOOKAHEAD. Le signal doit etre APRES la fin des donnees d'entrainement.
        # Sinon la table a vu le futur de ce signal, et son « edge » est une prophetie
        # auto-realisatrice. C'est le bug n°1 des backtests -- ici il est impossible.
        if signal_ms is not None and self.construite_jusqu_a_ms > 0:
            if float(signal_ms) <= float(self.construite_jusqu_a_ms):
                return ResultatEdge(False, None, EDGE_TABLE_LOOKAHEAD)

        if sens_du_trade(features.direction) == 0:
            return ResultatEdge(False, None, EDGE_FEATURES_INCOMPLETES)

        fine, large = features.cles()
        for niveau, cle in (("fin", fine), ("large", large)):
            c = self.cellules.get(cle)
            if c is not None and c.n >= self.min_echantillons:
                return ResultatEdge(
                    mesure=True,
                    edge_brut_bps=c.borne_basse_bps,   # BORNE BASSE, pas moyenne.
                    raison=EDGE_MESURE_OK,
                    niveau=niveau,
                    n=c.n,
                    moyenne_bps=c.moyenne_bps,
                    cle=cle,
                )
        return ResultatEdge(False, None, EDGE_BUCKET_VIDE, cle=fine)

    # -------------------------------------------------------------- persistance

    def as_dict(self) -> dict[str, object]:
        return {
            "horizon_ms": self.horizon_ms,
            "construite_jusqu_a_ms": self.construite_jusqu_a_ms,
            "min_echantillons": self.min_echantillons,
            "z": self.z,
            "source": self.source,
            "n_observations": self.n_observations,
            "cellules": [c.as_dict() for c in sorted(self.cellules.values(), key=lambda x: x.cle)],
        }

    def vers_json(self) -> str:
        return json.dumps(self.as_dict(), indent=2, ensure_ascii=False)

    @staticmethod
    def depuis_dict(d: dict[str, object]) -> "TableEdgeMesuree":
        cells: dict[str, Cellule] = {}
        for raw in (d.get("cellules") or []):  # type: ignore[union-attr]
            if not isinstance(raw, dict):
                continue
            c = Cellule(
                cle=str(raw.get("cle") or ""),
                n=int(raw.get("n") or 0),
                moyenne_bps=float(raw.get("moyenne_bps") or 0.0),
                ecart_type_bps=float(raw.get("ecart_type_bps") or 0.0),
                borne_basse_bps=float(raw.get("borne_basse_bps") or 0.0),
            )
            if c.cle:
                cells[c.cle] = c
        return TableEdgeMesuree(
            horizon_ms=int(d.get("horizon_ms") or 0),
            construite_jusqu_a_ms=int(d.get("construite_jusqu_a_ms") or 0),
            min_echantillons=int(d.get("min_echantillons") or 30),
            z=float(d.get("z") or 1.96),
            cellules=cells,
            source=str(d.get("source") or "REPLAY"),
            n_observations=int(d.get("n_observations") or 0),
        )

    @staticmethod
    def depuis_json(texte: str) -> "TableEdgeMesuree":
        return TableEdgeMesuree.depuis_dict(json.loads(texte))


# ------------------------------------------------------------------ la CONSTRUCTION


@dataclass(frozen=True, slots=True)
class Observation:
    """Un signal PASSE, et ce que le prix a fait APRES. Rien d'autre."""

    features: Features
    markout_bps: float
    signal_ms: float


def construire(
    observations: Iterable[Observation],
    *,
    horizon_ms: int,
    min_echantillons: int = 30,
    z: float = 1.96,
    source: str = "REPLAY",
    min_coins_pour_large: int = MIN_COINS_POUR_LARGE,
) -> TableEdgeMesuree:
    """Agrege les markouts REALISES par bucket. Aucune formule, aucune constante inventee.

    `construite_jusqu_a_ms` = le signal le PLUS RECENT vu. Toute interrogation portant sur un
    signal anterieur ou egal sera refusee (lookahead).

    🔴 `min_coins_pour_large` (13/07, trouve par G2) : une cellule LARGE (`STRAT|*|...`) est une
    GENERALISATION -- elle affirme « ce que fait le prix apres ce type de signal, quel que soit
    le marche ». Si elle n'a ete nourrie que par UN SEUL coin, ce n'est pas une generalisation :
    c'est un coin qui porte un masque. Et un marche JAMAIS MESURE en heriterait l'edge.

    C'est la maladie de P2-2 (couts constants d'un coin a l'autre), qui revenait par la porte de
    l'EDGE. Une cellule large nourrie par moins de N coins distincts n'est PAS emise -- et
    l'interrogation retombe alors sur EDGE_BUCKET_VIDE, c'est-a-dire un REFUS. Deny-by-default.
    """
    somme: dict[str, float] = {}
    somme_carres: dict[str, float] = {}
    compte: dict[str, int] = {}
    coins_par_cle: dict[str, set[str]] = {}
    cles_larges: set[str] = set()
    jusqu_a = 0.0
    total = 0

    for obs in observations:
        m = float(obs.markout_bps)
        if not math.isfinite(m):
            continue
        total += 1
        jusqu_a = max(jusqu_a, float(obs.signal_ms or 0.0))
        fine, large = obs.features.cles()
        coin = (obs.features.coin or "?").strip().upper()
        cles_larges.add(large)
        for cle in (fine, large):     # une observation nourrit SES DEUX niveaux
            somme[cle] = somme.get(cle, 0.0) + m
            somme_carres[cle] = somme_carres.get(cle, 0.0) + m * m
            compte[cle] = compte.get(cle, 0) + 1
            coins_par_cle.setdefault(cle, set()).add(coin)

    cellules: dict[str, Cellule] = {}
    for cle, n in compte.items():
        if n <= 0:
            continue
        if cle in cles_larges and len(coins_par_cle.get(cle, ())) < max(1, int(min_coins_pour_large)):
            # Pas assez de marches distincts pour generaliser. On n'emet PAS la cellule : un
            # marche inconnu ne doit jamais heriter de l'edge d'un autre.
            continue
        moy = somme[cle] / n
        if n >= 2:
            var = max(0.0, (somme_carres[cle] - n * moy * moy) / (n - 1))
            ecart = math.sqrt(var)
            se = ecart / math.sqrt(n)
        else:
            ecart = 0.0
            se = float("inf")          # n=1 : l'erreur standard est INFINIE. On ne bluffe pas.
        borne = moy - z * se if math.isfinite(se) else float("-inf")
        cellules[cle] = Cellule(
            cle=cle,
            n=n,
            moyenne_bps=moy,
            ecart_type_bps=ecart,
            borne_basse_bps=borne,
        )

    return TableEdgeMesuree(
        horizon_ms=int(horizon_ms),
        construite_jusqu_a_ms=int(jusqu_a),
        min_echantillons=int(min_echantillons),
        z=float(z),
        cellules=cellules,
        source=str(source),
        n_observations=total,
    )


# ------------------------------------------------------------------ LA PURGE DES ALPHAS FANTOMES
#
# 🚩 LECON APPRISE EN ECRIVANT LES TESTS (2026-07-13).
#
# J'avais ecrit un test qui exigeait « aucune cellule a edge positif ». Il a ECHOUE : la table
# d'entrainement trouve 3 buckets a edge net positif (dont BTC, signal < 1 s, score eleve :
# n=56, moyenne +23,1 bps). Mon test etait faux -- mais la table, elle, est DANGEREUSE.
#
# Car la validation hors-echantillon disait deja la verite : sur les signaux de TEST que la
# table aurait acceptes, le prix fait **-2,69 bps**. Ces 3 buckets sont des ALPHAS FANTOMES :
# ils existent dans les donnees d'entrainement, et nulle part ailleurs.
#
# Un bucket qui trouve de l'edge sur ses PROPRES donnees ne prouve rien. C'est meme la
# definition du sur-ajustement. La seule question qui compte :
#
#     « Ce bucket tient-il sur des donnees qu'il n'a JAMAIS vues ? »
#
# `valider_hors_echantillon` ne garde que les cellules qui repondent OUI -- et remplace leurs
# statistiques d'entrainement par celles du TEST. On ne livre jamais une esperance mesuree sur
# les donnees qui ont servi a la construire.


def valider_hors_echantillon(
    table_train: TableEdgeMesuree,
    observations_test: Iterable[Observation],
    *,
    min_echantillons_test: int | None = None,
) -> TableEdgeMesuree:
    """Ne garde QUE les cellules qui survivent a des donnees jamais vues.

    Chaque cellule survivante porte les statistiques du TEST (n, moyenne, borne basse), pas
    celles du train. Une esperance mesuree sur ses propres donnees d'entrainement est un
    mensonge poli ; celle-ci est une mesure.

    Une cellule absente du test, ou trop peu peuplee, est SUPPRIMEE. Pas degradee, pas gardee
    « au benefice du doute » : supprimee. Le doute ne beneficie a personne ici.
    """
    min_test = int(min_echantillons_test or table_train.min_echantillons)

    somme: dict[str, float] = {}
    somme_carres: dict[str, float] = {}
    compte: dict[str, int] = {}
    jusqu_a = float(table_train.construite_jusqu_a_ms)
    total = 0

    for obs in observations_test:
        m = float(obs.markout_bps)
        if not math.isfinite(m):
            continue
        total += 1
        jusqu_a = max(jusqu_a, float(obs.signal_ms or 0.0))
        for cle in obs.features.cles():
            if cle not in table_train.cellules:
                continue                       # cellule inconnue du train : rien a valider
            somme[cle] = somme.get(cle, 0.0) + m
            somme_carres[cle] = somme_carres.get(cle, 0.0) + m * m
            compte[cle] = compte.get(cle, 0) + 1

    survivantes: dict[str, Cellule] = {}
    for cle, n in compte.items():
        if n < min_test:
            continue                           # pas assez de donnees FRAICHES pour confirmer
        moy = somme[cle] / n
        if n >= 2:
            var = max(0.0, (somme_carres[cle] - n * moy * moy) / (n - 1))
            ecart = math.sqrt(var)
            se = ecart / math.sqrt(n)
        else:
            ecart, se = 0.0, float("inf")
        borne = moy - table_train.z * se if math.isfinite(se) else float("-inf")
        survivantes[cle] = Cellule(
            cle=cle, n=n, moyenne_bps=moy, ecart_type_bps=ecart, borne_basse_bps=borne,
        )

    return TableEdgeMesuree(
        horizon_ms=table_train.horizon_ms,
        construite_jusqu_a_ms=int(jusqu_a),
        min_echantillons=min_test,
        z=table_train.z,
        cellules=survivantes,
        source=table_train.source,
        n_observations=total,
    )


__all__ = [
    "BORNES_AGE_MS",
    "BORNES_CONSENSUS",
    "BORNES_SCORE",
    "Cellule",
    "EDGE_BUCKET_VIDE",
    "EDGE_FEATURES_INCOMPLETES",
    "EDGE_MESURE_OK",
    "EDGE_TABLE_ABSENTE",
    "EDGE_TABLE_LOOKAHEAD",
    "Features",
    "Observation",
    "ResultatEdge",
    "TableEdgeMesuree",
    "construire",
    "markout_bps",
    "sens_du_trade",
    "valider_hors_echantillon",
]
