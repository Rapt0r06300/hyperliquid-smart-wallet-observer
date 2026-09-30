"""#517 / H-112 — LE MARKET MAKING SUR LES MARCHÉS HIP-3. **La seule réouverture légitime.**

═══════════════════════════════════════════════════════════════════════════════════════════════
POURQUOI CETTE PISTE A LE DROIT D'EXISTER (et pas les 14 autres du cluster MM)
═══════════════════════════════════════════════════════════════════════════════════════════════

T1b a fermé le market making : **0/29 coins viables, à 100 % de remplissage** -- la borne la plus
généreuse possible. Et ma zone morte `MODELE_DE_FILE_ET_DE_FILL` enterre par **DOMINATION** tout
ce qui prétend améliorer le *modèle de file*.

**MAIS elle prévoit EXPLICITEMENT sa réouverture :**

    « une mesure montrant que le RISQUE D'INVENTAIRE (mouvement du prix pendant la détention)
      est INFÉRIEUR au spread capturé sur au moins un marché »

***#517 affirme exactement cela pour les marchés HIP-3 : 20 bps de DEMI-spread.***
Je dois donc **MESURER**, pas refuser. C'est ma propre règle.

Et un second fait, vérifié sur la doc :

    « When growth mode is activated for an HIP-3 perp, protocol fees ... are reduced by **90%**. »
    -> maker **0,15 bps** au lieu de 1,5. **Un facteur 10.**

═══════════════════════════════════════════════════════════════════════════════════════════════
🚩 ET VOICI POURQUOI JE M'ATTENDS QUAND MÊME À UN ÉCHEC — dit AVANT la mesure
═══════════════════════════════════════════════════════════════════════════════════════════════

*Annoncer mon attente d'avance m'empêche de me raconter une histoire après coup.*

  1. **T1b n'est PAS mort sur les frais. Il est mort sur l'INVENTAIRE.** Le prix bouge **5 à 30×
     plus** que le spread capturé pendant qu'on porte la position. **Diviser les frais par 10 ne
     touche PAS ce terme.** Ça franchit la porte B (coûts), pas la porte C (inventaire).
     *Et c'est la porte C qui tue.*
  2. **Un spread large n'est pas un cadeau : c'est le PRIX DU RISQUE.** Un marché HIP-3 neuf est
     **illiquide** et **volatil**. 20 bps de demi-spread devraient venir avec une volatilité
     *supérieure*, pas inférieure. **L'inventaire devrait être PIRE, pas meilleur.**
  3. 🔴 **Sur HIP-3, l'ORACLE EST FIXÉ PAR LE DÉPLOYEUR** (doc HIP-3 : *« Market operation,
     including setting oracle prices »*). Ce n'est **pas** la médiane robuste des CEX. Un risque
     que le marché principal n'a pas.
  4. **Le déployeur peut MULTIPLIER les frais** (`deployerFeeScale` 0-300 % → jusqu'à ×2).
     Le growth mode et la part du déployeur se **composent**.
  5. **La profondeur.** On size 500 $. Sur un carnet HIP-3 mince, c'est peut-être une fraction
     énorme du livre -- et alors le « spread » affiché ne nous est pas accessible.

**Si la mesure dit VIABLE, je regarderai QUI survit avant d'annoncer quoi que ce soit.**
*(La règle qui a sauvé le faux 38 % APR et le faux CASHCAT +34,94 bps.)*

═══════════════════════════════════════════════════════════════════════════════════════════════

Nom des coins HIP-3 : **`{dex}:{coin}`** (doc : for-developers/api/asset-ids).
Ils passent donc par le **même `l2Book`** que les autres. Aucun code d'exécution.

PUR : ce module PARSE et CLASSE. Aucun appel réseau. Aucun ordre réel.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable, Mapping

SEPARATEUR_HIP3 = ":"

MOTIF_PAS_HIP3 = "COIN_DU_MARCHE_PRINCIPAL_PAS_HIP3"
MOTIF_DEX_INCONNU = "DEX_ABSENT_DE_perpDexs_ECARTE"


@dataclass(frozen=True, slots=True)
class DexHip3:
    index: int
    nom: str
    deployeur: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return {"index": self.index, "nom": self.nom, "deployeur": self.deployeur}


@dataclass(frozen=True, slots=True)
class MarcheHip3:
    dex: str
    coin: str
    sz_decimals: int
    max_leverage: int | None = None

    @property
    def nom_complet(self) -> str:
        """`{dex}:{coin}` -- c'est ce que `l2Book` attend."""
        return "%s%s%s" % (self.dex, SEPARATEUR_HIP3, self.coin)

    def as_dict(self) -> dict[str, Any]:
        return {"dex": self.dex, "coin": self.coin, "nom_complet": self.nom_complet,
                "sz_decimals": self.sz_decimals, "max_leverage": self.max_leverage}


def est_hip3(nom: str) -> bool:
    """Un coin HIP-3 se reconnait a son `{dex}:{coin}`. **Le marche principal n'a pas de `:`.**"""
    n = str(nom or "")
    return SEPARATEUR_HIP3 in n and not n.startswith(SEPARATEUR_HIP3) \
        and not n.endswith(SEPARATEUR_HIP3)


def parser_perp_dexs(payload: Any) -> list[DexHip3]:
    """Reponse de `perpDexs` -> [DexHip3].

    DENY-BY-DEFAULT : une entree illisible est **ECARTEE**, jamais devinee.
    ⚠️ L'index 0 est le marche PRINCIPAL (`null` dans la reponse) : il n'est PAS un dex HIP-3.
    """
    out: list[DexHip3] = []
    if not isinstance(payload, list):
        return out
    for i, e in enumerate(payload):
        if e is None:
            continue                       # index 0 = marche principal, PAS HIP-3
        if not isinstance(e, Mapping):
            continue
        nom = str(e.get("name") or "").strip()
        if not nom:
            continue
        d = e.get("deployer")
        out.append(DexHip3(index=i, nom=nom,
                           deployeur=str(d) if d else None))
    return out


def parser_meta_dex(dex: str, payload: Any) -> list[MarcheHip3]:
    """Reponse de `meta` (avec `dex`) -> [MarcheHip3]. Format : {"universe": [{...}, ...]}."""
    out: list[MarcheHip3] = []
    if not isinstance(payload, Mapping):
        return out
    univers = payload.get("universe")
    if not isinstance(univers, list):
        return out
    for a in univers:
        if not isinstance(a, Mapping):
            continue
        nom = str(a.get("name") or "").strip()
        if not nom:
            continue
        # Le `name` du meta d'un dex est le coin NU (sans prefixe) ; on rebatit `{dex}:{coin}`.
        coin = nom.split(SEPARATEUR_HIP3)[-1]
        # 🔴 BUG TROUVE PAR UN TEST ROUGE (2026-07-13) : j'avais ecrit `a.get("szDecimals", 0)`.
        # **Un defaut a 0 n'est PAS deny-by-default** : un marche sans szDecimals passait
        # silencieusement avec szDecimals=0 -> toute taille < 1 unite serait ECRASEE A ZERO.
        # *Un defaut silencieux est un mensonge qui attend son heure.*
        brut = a.get("szDecimals")
        if brut is None:
            continue                       # sans szDecimals on ne peut RIEN arrondir -> ECARTE
        try:
            szd = int(brut)
        except (TypeError, ValueError):
            continue
        if szd < 0:
            continue
        lev = a.get("maxLeverage")
        try:
            lev_i = int(lev) if lev is not None else None
        except (TypeError, ValueError):
            lev_i = None
        out.append(MarcheHip3(dex=dex, coin=coin, sz_decimals=szd, max_leverage=lev_i))
    return out


def resume(dexs: Iterable[DexHip3], marches: Iterable[MarcheHip3]) -> dict[str, Any]:
    ds, ms = list(dexs), list(marches)
    return {
        "n_dexs": len(ds),
        "n_marches": len(ms),
        "dexs": [d.as_dict() for d in ds],
        "attente_declaree_AVANT_la_mesure": (
            "🚩 Je m'attends a un ECHEC. T1b n'est pas mort sur les FRAIS, il est mort sur "
            "l'INVENTAIRE : le prix bouge 5 a 30x plus que le spread capture. Diviser les frais "
            "par 10 franchit la porte des COUTS, pas celle de l'INVENTAIRE -- et c'est celle-la "
            "qui tue. De plus, un spread large sur un marche NEUF et ILLIQUIDE devrait venir avec "
            "une volatilite SUPERIEURE. **Si la mesure dit VIABLE, je regarderai QUI survit "
            "avant d'annoncer quoi que ce soit.**"
        ),
        "risques_specifiques_HIP3": [
            "l'ORACLE est fixe par le DEPLOYEUR (doc HIP-3), pas par une mediane de CEX",
            "le deployeur peut MULTIPLIER les frais (deployerFeeScale 0-300 % -> jusqu'a x2)",
            "carnet mince : 500 $ de notionnel peut etre une fraction enorme du livre",
        ],
        "real_execution": False,
    }


__all__ = [
    "MOTIF_DEX_INCONNU", "MOTIF_PAS_HIP3", "SEPARATEUR_HIP3",
    "DexHip3", "MarcheHip3", "est_hip3", "parser_meta_dex", "parser_perp_dexs", "resume",
]
