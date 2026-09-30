"""#362 / X-01 — LE SIGNAL **PRÉ-EXÉCUTION** : les dépôts Arbitrum → Hyperliquid.

═══════════════════════════════════════════════════════════════════════════════════════════════
POURQUOI CETTE PISTE EST **LA SEULE** QUI ECHAPPE A LA ZONE MORTE
═══════════════════════════════════════════════════════════════════════════════════════════════

`COPY_TRADING_NO_EDGE` est mesuree sur **le fill PUBLIC d'un leader** : -7,97 bps hors
echantillon, **meme a cout ZERO**, sur 24 133 signaux. Et Q1→Q3 en a trouve la cause : le leader
est **CONTRARIEN** -- le prix court CONTRE lui de -7,75 bps **AVANT** son execution, puis plus
rien. *Quand on voit son fill, tout est deja joue.*

Sa condition de reouverture, ecrite dans le registre :

    « un mecanisme STRUCTURELLEMENT different (ex. acces au flux d'ordres AVANT execution,
      pas apres) »

**Un depot PRECEDE le trade.** On ne peut pas trader ce qu'on n'a pas depose. C'est le seul
signal du projet qui arrive **avant** que le prix ait bouge.

    depot on-chain  ->  [minutes ?]  ->  premier fill  ->  [le prix a deja bouge]
        ^^^^^^^^^                            ^^^^^^^^^
        ICI, on est en avance            LA, il est trop tard (mesure : -7,97 bps)

═══════════════════════════════════════════════════════════════════════════════════════════════
🔴 CE QUE JE REFUSE DE FAIRE : INVENTER L'ADRESSE DU PONT
═══════════════════════════════════════════════════════════════════════════════════════════════

Le contrat de pont Hyperliquid sur Arbitrum a une adresse precise. **Je ne l'ai pas verifiee.**

Ecrire ici une adresse « de memoire » serait exactement la faute que ce projet interdit : **une
donnee fabriquee, presentee comme reelle** -- et cette fois elle ferait lire les depots du MAUVAIS
contrat, produisant un signal parfaitement faux, parfaitement silencieux.

**DENY-BY-DEFAULT : sans adresse fournie ET verifiee, ce module REFUSE de collecter.**
L'adresse se fournit par `HYPERSMART_HL_BRIDGE_ARBITRUM` (env) ou en argument, apres verification
sur la doc officielle. *Une adresse non verifiee est pire qu'aucune adresse.*

═══════════════════════════════════════════════════════════════════════════════════════════════
CE MODULE : parsing PUR des logs `Transfer` ERC-20 vers le pont. Aucun appel reseau ici -- on
recoit les logs, on les lit. C'est ce qui le rend testable, et c'est ce qui l'empeche de mentir.

⚠️ ETAT HONNETE : **l'instrument est ecrit, la MESURE ne l'est pas.** Elle exige :
  1. l'adresse du pont, VERIFIEE ;
  2. un run de collecte (on n'a aucun historique de depots) ;
  3. le markout : entre le depot et le 1er fill du deposant, le prix bouge-t-il ? De combien ?
*Sans ces trois, on n'a rien -- et je ne promets rien.*

Aucun ordre reel. Lecture on-chain seule. Aucune cle, aucune signature, aucun depot EMIS.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable, Mapping, Sequence

# Signature de l'evenement ERC-20 `Transfer(address,address,uint256)` -- constante universelle,
# pas une adresse : on peut la citer sans risque de se tromper de contrat.
TOPIC_TRANSFER = "0xddf252ad1be2c89b69c2b068fc378daa952ba7f163c4a11628f55a4df523b3ef"

MOTIF_PAS_D_ADRESSE = "ADRESSE_DU_PONT_NON_FOURNIE_OU_NON_VERIFIEE_REFUS_DE_COLLECTER"
MOTIF_ADRESSE_INVALIDE = "ADRESSE_MAL_FORMEE_REFUS_DE_COLLECTER"

# Un depot minuscule n'annonce pas un trade : c'est un test, ou de la poussiere.
MIN_DEPOT_USD = 10_000.0


class AdresseDuPontNonVerifiee(ValueError):
    """On refuse de lire un contrat dont on n'a pas verifie l'adresse.

    *Lire les depots du MAUVAIS contrat produirait un signal parfaitement faux -- et parfaitement
    silencieux.* C'est le pire type de bug que ce projet connaisse.
    """


def valider_adresse_du_pont(adresse: str | None) -> str:
    """DENY-BY-DEFAULT. Aucune valeur par defaut, aucune adresse « de memoire »."""
    a = (adresse or "").strip().lower()
    if not a:
        raise AdresseDuPontNonVerifiee(
            "%s : fournis l'adresse du pont Hyperliquid sur Arbitrum, **apres l'avoir verifiee "
            "sur la doc officielle**. Je ne l'invente pas." % MOTIF_PAS_D_ADRESSE
        )
    if not (a.startswith("0x") and len(a) == 42):
        raise AdresseDuPontNonVerifiee(
            "%s : %r n'est pas une adresse Ethereum (0x + 40 hex)." % (MOTIF_ADRESSE_INVALIDE, a)
        )
    try:
        int(a[2:], 16)
    except ValueError as exc:
        raise AdresseDuPontNonVerifiee("%s : %r" % (MOTIF_ADRESSE_INVALIDE, a)) from exc
    return a


@dataclass(frozen=True, slots=True)
class Depot:
    """Un depot vers le pont. **Il PRECEDE le trade.** C'est tout l'interet."""

    tx_hash: str
    bloc: int
    deposant: str
    montant_usd: float

    def as_dict(self) -> dict[str, Any]:
        return {
            "tx_hash": self.tx_hash, "bloc": self.bloc,
            "deposant": self.deposant, "montant_usd": round(self.montant_usd, 2),
            "real_execution": False,
        }


def _adresse_depuis_topic(topic: str) -> str:
    """Un topic fait 32 octets ; une adresse, 20. Elle est a DROITE, zero-paddee a gauche."""
    t = (topic or "").lower().removeprefix("0x")
    return "0x" + t[-40:] if len(t) >= 40 else ""


def parser_logs(
    logs: Sequence[Mapping[str, Any]],
    *,
    adresse_du_pont: str,
    decimales: int = 6,          # USDC = 6 decimales
    min_usd: float = MIN_DEPOT_USD,
) -> list[Depot]:
    """Lit des logs `Transfer` ERC-20 et garde ceux **dont la destination EST le pont**.

    ⚠️ `adresse_du_pont` est OBLIGATOIRE et VALIDE en amont. Sans elle, on ne lit rien.

    DENY-BY-DEFAULT : tout log mal forme est **ecarte**, jamais devine. Un log qu'on ne comprend
    pas ne devient pas un depot de 0 $.
    """
    pont = valider_adresse_du_pont(adresse_du_pont)
    out: list[Depot] = []
    for lg in logs:
        if not isinstance(lg, Mapping):
            continue
        topics = lg.get("topics")
        if not isinstance(topics, (list, tuple)) or len(topics) < 3:
            continue
        if str(topics[0]).lower() != TOPIC_TRANSFER:
            continue
        vers = _adresse_depuis_topic(str(topics[2]))
        if vers != pont:
            continue                                   # ce n'est pas un depot vers le pont
        depuis = _adresse_depuis_topic(str(topics[1]))
        if not depuis:
            continue
        try:
            brut = int(str(lg.get("data") or "0x0"), 16)
            bloc = int(str(lg.get("blockNumber") or "0x0"), 16)
        except ValueError:
            continue                                   # on n'invente pas un montant
        montant = brut / (10 ** int(decimales))
        if montant < float(min_usd):
            continue                                   # poussiere : ca n'annonce aucun trade
        out.append(Depot(
            tx_hash=str(lg.get("transactionHash") or ""),
            bloc=bloc, deposant=depuis, montant_usd=montant,
        ))
    return out


def requete_logs(adresse_du_pont: str, *, du_bloc: int, au_bloc: int) -> dict[str, Any]:
    """La requete JSON-RPC `eth_getLogs`. **Ce module ne l'envoie PAS** -- il la construit.

    Separer la CONSTRUCTION de l'ENVOI, c'est ce qui rend la requete testable... et ce qui
    garantit qu'aucun appel reseau ne part d'un module de parsing.
    """
    pont = valider_adresse_du_pont(adresse_du_pont)
    return {
        "jsonrpc": "2.0", "id": 1, "method": "eth_getLogs",
        "params": [{
            "fromBlock": hex(int(du_bloc)),
            "toBlock": hex(int(au_bloc)),
            "topics": [TOPIC_TRANSFER, None, "0x" + "0" * 24 + pont[2:]],
        }],
    }


def etat_de_la_piste(depots: Iterable[Depot]) -> dict[str, Any]:
    """L'etat HONNETE. Cette piste n'est **pas** mesuree, et il faut le dire."""
    ds = list(depots)
    return {
        "n_depots": len(ds),
        "notionnel_total_usd": round(sum(d.montant_usd for d in ds), 2),
        "mesure_faite": False,
        "mesure_qui_trancherait": (
            "markout du prix entre le DEPOT et le 1er fill du deposant, sur >= 200 depots. "
            "Si > couts -> c'est le premier signal du projet qui arrive AVANT le prix. "
            "Sinon, la derniere porte du copy-trading se ferme aussi."
        ),
        "bloquant": (
            "1) l'adresse du pont, VERIFIEE (je refuse de l'inventer) ; "
            "2) un run de collecte : on n'a AUCUN historique de depots."
        ),
        "real_execution": False,
    }


__all__ = [
    "MIN_DEPOT_USD", "MOTIF_ADRESSE_INVALIDE", "MOTIF_PAS_D_ADRESSE", "TOPIC_TRANSFER",
    "AdresseDuPontNonVerifiee", "Depot",
    "etat_de_la_piste", "parser_logs", "requete_logs", "valider_adresse_du_pont",
]
