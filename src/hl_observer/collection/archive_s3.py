"""#462 / H-57 — L'ARCHIVE S3 OFFICIELLE. **J'AI AFFIRMÉ SANS VÉRIFIER, ET J'AVAIS TORT.**

═══════════════════════════════════════════════════════════════════════════════════════════════
🔴 CE QUE J'AI DIT TROIS FOIS, ET QUI ÉTAIT FAUX
═══════════════════════════════════════════════════════════════════════════════════════════════

    « Le carnet L2 et les trades n'ont aucune source historique gratuite. C'est le mur. »

**FAUX.** Doc officielle (hyperliquid-docs/historical-data), publiée depuis 2023 :

    s3://hyperliquid-archive/market_data/[date]/[hour]/l2Book/[coin].lz4   <- LE CARNET L2
    s3://hyperliquid-archive/asset_ctxs/[date].csv.lz4                     <- contextes d'actifs
    s3://hl-mainnet-node-data/node_fills_by_block                          <- LES FILLS, PAR BLOC
    s3://hl-mainnet-node-data/node_trades                                  <- LES TRADES
    s3://hl-mainnet-node-data/misc_events_by_block                         <- transferts + funding

***C'est la TROISIEME fois aujourd'hui.*** `candleSnapshot(startTime)` le matin. `fundingHistory`
le soir. Et maintenant ça. La maladie du projet -- *une capacite presente, un chainon manquant,
personne qui se plaint* -- sauf que le chainon manquant, ici, **c'etait moi qui affirmais sans
verifier**.

═══════════════════════════════════════════════════════════════════════════════════════════════
⚠️ CE QUE LA DOC DIT ELLE-MEME, ET QU'IL FAUT REPETER
═══════════════════════════════════════════════════════════════════════════════════════════════

  1. **« the requester of the data must pay for transfer costs »** -> **REQUESTER-PAYS**.
     Ce n'est pas gratuit : il faut des identifiants AWS et ca coute de l'egress.
     🔒 **AUCUN identifiant n'est ecrit dans un fichier de ce projet.** Ils viennent de
     l'environnement, et le module REFUSE de tourner sans (deny-by-default).
  2. **« There is no guarantee of timely updates and data may be missing. »**
     -> On **COMPTE les trous**. Une couverture trouee est annoncee trouee.
  3. **Uploade « approximately once a month »** -> ce n'est PAS du temps reel. C'est de l'HISTOIRE.
  4. **Pas de bougies ni de spot sur S3** -- mais ca, on l'a deja par l'API (208 jours).

═══════════════════════════════════════════════════════════════════════════════════════════════
⚖️ CE QUE CA REOUVRE — ET CE QUE CA NE REOUVRE **PAS**
═══════════════════════════════════════════════════════════════════════════════════════════════

**CE QUE CA NE REOUVRE PAS : le market making (T1b).**
T1b a mesure a **100 % de remplissage** -- la borne la plus genereuse possible -- et a trouve que
**le prix bouge 5 a 30x plus que le spread capture** pendant qu'on porte l'inventaire. Ce ratio
est une propriete du marche, pas un artefact d'echantillon. Plus de donnees le mesureront **mieux**,
elles ne le feront pas **changer de signe**. *Le spread reste le prix du risque.*
🚩 Annoncer « l'archive S3 ressuscite le MM » serait exactement la faute que je viens de faire
avec les 38 % d'APR : confondre « j'ai une nouvelle donnee » et « j'ai un nouvel edge ».

**CE QUE CA REOUVRE VRAIMENT (entrees JAMAIS mesurees) :**
  * `node_trades` / `node_fills_by_block` -> **les trades avec le cote AGRESSEUR**. C'est
    l'entree du **PIN / VPIN** (#463) et d'une vraie mesure de selection adverse historique.
    Jusqu'ici on n'avait ca qu'en live.
  * `misc_events_by_block` -> **les transferts**. C'est **X-01** (le signal pre-execution des
    depots) **nativement, en historique**, sans scraper Arbitrum.
  * `l2Book` historique -> la **carte des liquidations** (X-11) et la profondeur reelle au
    moment des chocs.

PUR : ce module construit des CHEMINS et compte des TROUS. Aucun telechargement ici.
Aucun ordre reel. Aucune cle privee. Aucune signature.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Iterable

BUCKET_MARCHE = "hyperliquid-archive"
BUCKET_NOEUD = "hl-mainnet-node-data"

# Les jeux de donnees, tels que la doc officielle les nomme. On n'en invente aucun.
JEUX_MARCHE = ("l2Book",)                 # seul type confirme par la doc sous market_data/
JEUX_NOEUD = ("node_fills_by_block", "node_fills", "node_trades",
              "explorer_blocks", "replica_cmds", "misc_events_by_block")

# 🔒 La doc : « the requester of the data must pay for transfer costs ».
VARIABLES_AWS = ("AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY")

MOTIF_SANS_IDENTIFIANTS = "AUCUN_IDENTIFIANT_AWS_REQUESTER_PAYS_IMPOSSIBLE"
MOTIF_JEU_INCONNU = "JEU_DE_DONNEES_ABSENT_DE_LA_DOC_OFFICIELLE"


class IdentifiantsAbsents(RuntimeError):
    """L'archive est en requester-pays. Sans identifiants, on ne devine rien : on REFUSE."""


class JeuDeDonneesInconnu(ValueError):
    """On ne fabrique pas un chemin S3 « de memoire ». Deny-by-default sur le nom du jeu."""


@dataclass(frozen=True, slots=True)
class CleS3:
    bucket: str
    cle: str

    @property
    def uri(self) -> str:
        return "s3://%s/%s" % (self.bucket, self.cle)

    def as_dict(self) -> dict[str, Any]:
        return {"bucket": self.bucket, "cle": self.cle, "uri": self.uri}


def identifiants_presents(env: dict[str, str] | None = None) -> bool:
    e = os.environ if env is None else env
    return all(str(e.get(v) or "").strip() for v in VARIABLES_AWS)


def exiger_identifiants(env: dict[str, str] | None = None) -> None:
    """DENY-BY-DEFAULT. L'archive coute de l'egress : sans identifiants, on ne tente RIEN.

    🔒 Les identifiants viennent de l'ENVIRONNEMENT. Aucun secret n'est ecrit dans un fichier
    de ce projet, jamais. Un test l'interdit.
    """
    if not identifiants_presents(env):
        raise IdentifiantsAbsents(
            "%s : l'archive Hyperliquid est en **requester-pays** (doc officielle). "
            "Definir %s dans l'environnement -- JAMAIS dans un fichier."
            % (MOTIF_SANS_IDENTIFIANTS, " et ".join(VARIABLES_AWS))
        )


def _jour(d: datetime) -> str:
    return d.strftime("%Y%m%d")


def cle_l2_book(coin: str, jour: datetime, heure: int) -> CleS3:
    """s3://hyperliquid-archive/market_data/[date]/[hour]/l2Book/[coin].lz4

    Exemple EXACT de la doc : market_data/20230916/9/l2Book/SOL.lz4
    Noter l'heure **SANS zero de tete** (9, pas 09) -- c'est ce que la doc montre.
    """
    if not 0 <= int(heure) <= 23:
        raise ValueError("heure hors [0..23] : %r" % heure)
    c = str(coin or "").strip().upper()
    if not c:
        raise ValueError("coin vide")
    return CleS3(BUCKET_MARCHE,
                 "market_data/%s/%d/l2Book/%s.lz4" % (_jour(jour), int(heure), c))


def cle_asset_ctxs(jour: datetime) -> CleS3:
    """s3://hyperliquid-archive/asset_ctxs/[date].csv.lz4"""
    return CleS3(BUCKET_MARCHE, "asset_ctxs/%s.csv.lz4" % _jour(jour))


def prefixe_noeud(jeu: str) -> CleS3:
    """Les jeux du bucket de noeud. **Aucun nom inventé** : ils viennent de la doc."""
    j = str(jeu or "").strip()
    if j not in JEUX_NOEUD:
        raise JeuDeDonneesInconnu(
            "%s : %r. Jeux documentes : %s" % (MOTIF_JEU_INCONNU, jeu, ", ".join(JEUX_NOEUD))
        )
    return CleS3(BUCKET_NOEUD, j)


def plan_l2_book(
    coin: str,
    *,
    debut: datetime,
    fin: datetime,
) -> list[CleS3]:
    """Une cle par HEURE, de `debut` a `fin` (exclue). Bornes en UTC, jamais dans le futur."""
    if debut.tzinfo is None or fin.tzinfo is None:
        raise ValueError("les bornes doivent etre en UTC explicite (tzinfo requis)")
    if debut >= fin:
        return []
    maintenant = datetime.now(timezone.utc)
    if fin > maintenant:
        fin = maintenant
    cles: list[CleS3] = []
    t = debut.replace(minute=0, second=0, microsecond=0)
    while t < fin:
        cles.append(cle_l2_book(coin, t, t.hour))
        t += timedelta(hours=1)
    return cles


@dataclass(frozen=True, slots=True)
class CouvertureArchive:
    coin: str
    n_attendues: int
    n_obtenues: int
    n_manquantes: int

    @property
    def taux(self) -> float:
        return (self.n_obtenues / self.n_attendues) if self.n_attendues else 0.0

    def as_dict(self) -> dict[str, Any]:
        return {"coin": self.coin, "n_attendues": self.n_attendues,
                "n_obtenues": self.n_obtenues, "n_manquantes": self.n_manquantes,
                "taux": round(self.taux, 4)}


def couverture(coin: str, attendues: Iterable[CleS3],
               obtenues: Iterable[str]) -> CouvertureArchive:
    """La doc PREVIENT : « data may be missing ». On COMPTE, on ne suppose pas.

    Une couverture trouee doit etre annoncee trouee. Une mesure sur des donnees trouees qui se
    croit complete, c'est le prochain faux edge.
    """
    att = [k.cle for k in attendues]
    obt = set(obtenues)
    presentes = sum(1 for c in att if c in obt)
    return CouvertureArchive(coin=str(coin).upper(), n_attendues=len(att),
                             n_obtenues=presentes, n_manquantes=len(att) - presentes)


__all__ = [
    "BUCKET_MARCHE", "BUCKET_NOEUD", "JEUX_MARCHE", "JEUX_NOEUD", "VARIABLES_AWS",
    "MOTIF_JEU_INCONNU", "MOTIF_SANS_IDENTIFIANTS",
    "CleS3", "CouvertureArchive", "IdentifiantsAbsents", "JeuDeDonneesInconnu",
    "cle_asset_ctxs", "cle_l2_book", "couverture", "exiger_identifiants",
    "identifiants_presents", "plan_l2_book", "prefixe_noeud",
]
