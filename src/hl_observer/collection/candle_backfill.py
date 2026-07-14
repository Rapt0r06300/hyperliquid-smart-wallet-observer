"""🔴 « DATA-LIMITED » ÉTAIT UNE BLESSURE AUTO-INFLIGÉE (2026-07-13).

═══════════════════════════════════════════════════════════════════════════════════════════════
LE CONSTAT
═══════════════════════════════════════════════════════════════════════════════════════════════

Depuis des jours, chaque mesure meurt sur la meme phrase :

    #242 (cointegration)  -> « data-limited » : 18,9 h d'historique.
    la recherche 150 M    -> horizons de 8 h sur ~19 h de donnees : jamais saine.
    la purge (H-05)       -> vide le train, parce que l'echantillon est trop court.
    T1b                   -> 9 543 snapshots de carnet.

Et pendant ce temps, **l'API publique qu'on interroge tous les jours** expose :

    build_candle_snapshot_payload(coin, interval, **start_time**, end_time)
                                                    ^^^^^^^^^^^^

**Elle etait DEJA ecrite** (`rest_info_client.py:136`), **DEJA autorisee** (`READ_ONLY_INFO_TYPES`),
et on ne s'en servait que pour prendre les bougies **RECENTES** pendant le scan live.

    On peut telecharger des **MOIS** d'historique de prix. Gratuitement. Maintenant.

*Ce n'etait pas une donnee manquante. C'etait une capacite presente, un chainon manquant, et
personne qui se plaint.* **La maladie du projet, dans sa version la plus chere : elle nous a fait
declarer « impossible a mesurer » ce qui etait a un appel de distance.**

═══════════════════════════════════════════════════════════════════════════════════════════════
CE QUE CA DEBLOQUE -- ET CE QUE CA NE DEBLOQUE PAS. IL FAUT DIRE LES DEUX.
═══════════════════════════════════════════════════════════════════════════════════════════════

✅ DEBLOQUE (tout ce qui ne depend que du PRIX) :
   * #242 cointegration -- mort « data-limited », il peut revivre ;
   * la recherche de scenarios : des horizons de 8 h deviennent honnetes sur des mois ;
   * le lead-lag BTC->alts (H-144) ; les regimes ; la volatilite.

❌ NE DEBLOQUE **PAS** :
   * le **carnet L2** (spread, profondeur) -- aucune source historique gratuite. T1b reste sur
     ses 9 543 snapshots. **Le verdict du market making ne change pas** (il etait deja mesure a
     la borne la plus GENEREUSE).
   * les **trades avec agresseur** -- donc la selection adverse reste limitee au live.
   * les **liquidations** -- X-11 vient de commencer a collecter `liquidationPx`.

*Annoncer que « le probleme de donnees est resolu » serait faux. Il est resolu POUR LES PRIX.*

═══════════════════════════════════════════════════════════════════════════════════════════════
CE MODULE : PUR. Il construit le PLAN de requetes (pagine) et PARSE les bougies. Il n'envoie
rien -- `tools/backfill_candles.py` s'en charge. C'est ce qui le rend testable.

Hyperliquid borne chaque reponse (~5 000 bougies). En 1 minute, ca fait ~3,5 jours par requete.
On pagine donc, en avancant la fenetre. **Deny-by-default : une bougie mal formee est ECARTEE,
jamais devinee.**

Aucun ordre reel. Lecture publique seule.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable, Mapping, Sequence

# Hyperliquid borne la reponse. On reste EN DESSOUS : une reponse tronquee sans le dire serait
# un trou silencieux dans l'historique -- exactement le genre de bug qu'on traque.
MAX_BOUGIES_PAR_REQUETE = 4_000

MINUTES_PAR_INTERVALLE: dict[str, int] = {
    "1m": 1, "3m": 3, "5m": 5, "15m": 15, "30m": 30,
    "1h": 60, "2h": 120, "4h": 240, "8h": 480, "12h": 720, "1d": 1440,
}

MOTIF_INTERVALLE_INCONNU = "INTERVALLE_INCONNU_REFUS_DE_DEVINER"


class IntervalleInconnu(ValueError):
    """On ne devine pas la duree d'un intervalle qu'on ne connait pas : on refuse."""


@dataclass(frozen=True, slots=True)
class Bougie:
    coin: str
    t_ms: int          # debut de la bougie
    open: float
    high: float
    low: float
    close: float
    volume: float

    @property
    def cle(self) -> tuple[str, int]:
        """La cle de DEDUPLICATION. Deux requetes qui se chevauchent ne doivent pas doubler
        l'historique -- un volume double fausserait toute mesure de liquidite."""
        return (self.coin, self.t_ms)

    def as_dict(self) -> dict[str, Any]:
        return {
            "coin": self.coin, "t_ms": self.t_ms,
            "o": self.open, "h": self.high, "l": self.low, "c": self.close,
            "v": self.volume, "real_execution": False,
        }


def minutes_de(intervalle: str) -> int:
    m = MINUTES_PAR_INTERVALLE.get(str(intervalle))
    if m is None:
        raise IntervalleInconnu("%s : %r" % (MOTIF_INTERVALLE_INCONNU, intervalle))
    return m


def plan_de_requetes(
    *, debut_ms: int, fin_ms: int, intervalle: str,
    max_bougies: int = MAX_BOUGIES_PAR_REQUETE,
) -> list[tuple[int, int]]:
    """Decoupe [debut, fin] en fenetres qui tiennent sous la borne de l'API.

    🔴 SANS CE DECOUPAGE, l'API renverrait une reponse TRONQUEE **sans le dire** -- et on aurait
    un trou dans l'historique, silencieux. *Le pire bug est celui qui ne plante pas.*
    """
    if debut_ms >= fin_ms:
        return []
    pas_ms = minutes_de(intervalle) * 60_000 * int(max_bougies)
    out: list[tuple[int, int]] = []
    t = int(debut_ms)
    while t < int(fin_ms):
        fin_fenetre = min(t + pas_ms, int(fin_ms))
        out.append((t, fin_fenetre))
        t = fin_fenetre
    return out


def parser_bougies(coin: str, payload: Any) -> list[Bougie]:
    """La reponse de `candleSnapshot` -> des bougies. DENY-BY-DEFAULT.

    Le format Hyperliquid : [{"t":..,"T":..,"s":"BTC","i":"1m","o":"..","c":"..","h":"..",
                              "l":"..","v":"..","n":..}, ...]

    Une bougie qu'on ne comprend pas est **ECARTEE**, jamais devinee. Un `o=0` invente pourrirait
    tous les rendements en aval -- et personne ne le verrait.
    """
    out: list[Bougie] = []
    if not isinstance(payload, list):
        return out
    for row in payload:
        if not isinstance(row, Mapping):
            continue
        try:
            t = int(row["t"])
            o = float(row["o"]); h = float(row["h"])
            lo = float(row["l"]); c = float(row["c"])
            v = float(row.get("v") or 0.0)
        except (KeyError, TypeError, ValueError):
            continue                                  # on n'invente RIEN
        if not (o > 0 and h > 0 and lo > 0 and c > 0):
            continue                                  # un prix <= 0 n'existe pas
        if h < lo:
            continue                                  # bougie incoherente : on l'ecarte
        out.append(Bougie(coin=str(row.get("s") or coin).upper(),
                          t_ms=t, open=o, high=h, low=lo, close=c, volume=v))
    return out


def dedupliquer(bougies: Iterable[Bougie]) -> list[Bougie]:
    """Les fenetres se chevauchent aux bords. **Un volume double fausserait tout.**"""
    vues: dict[tuple[str, int], Bougie] = {}
    for b in bougies:
        vues[b.cle] = b
    return sorted(vues.values(), key=lambda b: (b.coin, b.t_ms))


@dataclass(frozen=True, slots=True)
class Couverture:
    """Ce que l'historique couvre REELLEMENT. On le DIT, on ne le suppose pas."""

    coin: str
    n_bougies: int
    debut_ms: int
    fin_ms: int
    n_trous: int               # minutes manquantes dans la serie
    intervalle: str

    @property
    def heures(self) -> float:
        return max(0.0, (self.fin_ms - self.debut_ms) / 3_600_000.0)

    def as_dict(self) -> dict[str, Any]:
        return {
            "coin": self.coin, "n_bougies": self.n_bougies,
            "debut_ms": self.debut_ms, "fin_ms": self.fin_ms,
            "heures": round(self.heures, 2), "n_trous": self.n_trous,
            "intervalle": self.intervalle, "real_execution": False,
        }


def couverture(bougies: Sequence[Bougie], *, intervalle: str) -> Couverture | None:
    """🔴 UN HISTORIQUE AVEC DES TROUS N'EST PAS UN HISTORIQUE.

    On COMPTE les bougies manquantes. Un trou silencieux, c'est une periode ou le marche a bouge
    et ou notre backtest croit qu'il ne s'est rien passe.
    """
    bs = sorted((b for b in bougies), key=lambda b: b.t_ms)
    if not bs:
        return None
    pas_ms = minutes_de(intervalle) * 60_000
    attendues = ((bs[-1].t_ms - bs[0].t_ms) // pas_ms) + 1
    return Couverture(
        coin=bs[0].coin, n_bougies=len(bs), debut_ms=bs[0].t_ms, fin_ms=bs[-1].t_ms,
        n_trous=max(0, int(attendues) - len(bs)), intervalle=str(intervalle),
    )


__all__ = [
    "MAX_BOUGIES_PAR_REQUETE", "MINUTES_PAR_INTERVALLE", "MOTIF_INTERVALLE_INCONNU",
    "Bougie", "Couverture", "IntervalleInconnu",
    "couverture", "dedupliquer", "minutes_de", "parser_bougies", "plan_de_requetes",
]
