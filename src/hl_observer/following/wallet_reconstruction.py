"""Global Wallet Observer — reconstruction du cycle de vie des positions depuis des fills L1 (pur, 0 réseau).

Aujourd'hui la découverte de wallets dépend des **10 slots `userFills`** : on ne voit que ce qu'on a déjà
choisi de regarder. Ce module renverse la contrainte : il reconstruit `OPEN / ADD / REDUCE / CLOSE / FLIP`
(+ marquage `TWAP`) pour **n'importe quel** wallet, à partir d'un flux de fills global — `node_fills_by_block`,
archive S3, ou simplement les fills déjà collectés.

Le champ qui rend la reconstruction honnête est `start_pos` (`startPosition` chez Hyperliquid) : la position
**avant** le fill, telle que l'exchange la voit. On l'utilise comme autorité et on le compare à notre propre
accumulateur. S'ils divergent, c'est qu'il **manque des fills** : l'épisode est marqué `DESYNC` au lieu de
produire un cycle de vie faux avec l'air d'être juste. C'est la différence entre « je ne sais pas » et
« je me trompe sans le savoir ».

Deny-by-default : taille, prix ou horodatage manquant ⇒ `UNMEASURABLE`, compté et nommé, jamais deviné.

0 réseau, 0 ordre réel, 0 clé, 0 signature.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterable, Mapping

SCHEMA_VERSION = "hypersmart.wallet_reconstruction.v1"

ACTIONS = ("OPEN", "ADD", "REDUCE", "CLOSE", "FLIP")
#: Motifs de refus. Un fill refusé n'est jamais silencieusement ignoré : il est compté.
REFUS = ("TAILLE_ABSENTE", "PRIX_ABSENT", "HORODATAGE_ABSENT", "SENS_INCONNU", "WALLET_OU_COIN_ABSENT")

#: Tolérance relative de comparaison entre `start_pos` et notre accumulateur.
TOLERANCE_DESYNC = 1e-6


def _f(valeur: Any) -> float | None:
    if isinstance(valeur, bool) or valeur is None:
        return None
    try:
        v = float(valeur)
    except (TypeError, ValueError):
        return None
    return None if v != v else v


def _sens(fill: Mapping[str, Any]) -> int | None:
    """+1 achat, -1 vente. Hyperliquid : `side` ∈ {B, A} ou `dir` textuel. Rien n'est deviné."""
    side = str(fill.get("side") or "").strip().upper()
    if side in {"B", "BUY", "LONG"}:
        return 1
    if side in {"A", "S", "SELL", "SHORT"}:
        return -1
    direction = str(fill.get("dir") or "").strip().lower()
    if not direction:
        return None
    if "open long" in direction or "close short" in direction or direction.startswith("buy"):
        return 1
    if "open short" in direction or "close long" in direction or direction.startswith("sell"):
        return -1
    return None


def cle_fill(fill: Mapping[str, Any]) -> str:
    """Identité de dédup : `tid` s'il existe, sinon (oid, time, sz). Un hash nul ne sert pas de clé."""
    tid = fill.get("tid")
    if tid not in (None, "", 0, "0"):
        return "tid:%s" % tid
    return "oid:%s|t:%s|sz:%s" % (fill.get("oid"), fill.get("time"), fill.get("sz"))


@dataclass
class EtatPosition:
    """Position courante reconstruite pour un (wallet, coin)."""

    quantite: float = 0.0
    prix_moyen: float | None = None
    ouverte_depuis_ms: int | None = None
    n_fills: int = 0


@dataclass
class Reconstruction:
    """Résultat : épisodes ordonnés, positions finales, refus et désynchronisations comptés."""

    episodes: list[dict[str, Any]] = field(default_factory=list)
    positions: dict[tuple[str, str], EtatPosition] = field(default_factory=dict)
    refus: dict[str, int] = field(default_factory=dict)
    desyncs: list[dict[str, Any]] = field(default_factory=list)
    doublons: int = 0

    def resume(self) -> dict[str, Any]:
        par_action: dict[str, int] = {}
        for e in self.episodes:
            par_action[e["action"]] = par_action.get(e["action"], 0) + 1
        wallets = {w for w, _ in self.positions}
        return {
            "schema_version": SCHEMA_VERSION,
            "n_episodes": len(self.episodes),
            "par_action": par_action,
            "n_twap": sum(1 for e in self.episodes if e.get("twap_id")),
            "n_wallets": len(wallets),
            "n_positions_ouvertes": sum(1 for p in self.positions.values() if abs(p.quantite) > TOLERANCE_DESYNC),
            "refus": dict(self.refus),
            "n_doublons": self.doublons,
            "n_desyncs": len(self.desyncs),
            "fiable": not self.desyncs,
            "note_desync": (None if not self.desyncs else
                            "des fills manquent : le cycle de vie reconstruit n'est pas fiable sur ces (wallet, coin)"),
            "real_execution": False,
        }


def _classer(avant: float, apres: float) -> str:
    """Action déduite du passage `avant -> apres`. Le FLIP est distingué d'un CLOSE suivi d'un OPEN."""
    if abs(avant) <= TOLERANCE_DESYNC:
        return "OPEN"
    if abs(apres) <= TOLERANCE_DESYNC:
        return "CLOSE"
    if (avant > 0) != (apres > 0):
        return "FLIP"
    return "ADD" if abs(apres) > abs(avant) else "REDUCE"


def reconstruire(fills: Iterable[Mapping[str, Any]], *, utiliser_start_pos: bool = True) -> Reconstruction:
    """Reconstruit le cycle de vie par (wallet, coin), en ordre chronologique strict.

    `start_pos` fait autorité quand il est présent : notre accumulateur n'est qu'un contrôle. Une divergence
    signale des fills manquants et marque l'épisode `DESYNC` — elle ne se corrige pas en silence.
    """
    resultat = Reconstruction()
    vus: set[str] = set()

    lisibles: list[tuple[int, Mapping[str, Any]]] = []
    for fill in fills:
        wallet = str(fill.get("user") or fill.get("wallet") or "").strip().lower()
        coin = str(fill.get("coin") or "").strip().upper()
        if not wallet or not coin:
            resultat.refus["WALLET_OU_COIN_ABSENT"] = resultat.refus.get("WALLET_OU_COIN_ABSENT", 0) + 1
            continue
        ts = _f(fill.get("time") or fill.get("ts_ms"))
        if ts is None:
            resultat.refus["HORODATAGE_ABSENT"] = resultat.refus.get("HORODATAGE_ABSENT", 0) + 1
            continue
        lisibles.append((int(ts), fill))
    lisibles.sort(key=lambda p: (p[0], cle_fill(p[1])))

    for ts, fill in lisibles:
        cle = cle_fill(fill)
        if cle in vus:
            resultat.doublons += 1
            continue
        vus.add(cle)

        wallet = str(fill.get("user") or fill.get("wallet") or "").strip().lower()
        coin = str(fill.get("coin") or "").strip().upper()
        taille = _f(fill.get("sz"))
        prix = _f(fill.get("px"))
        sens = _sens(fill)
        if taille is None or taille <= 0:
            resultat.refus["TAILLE_ABSENTE"] = resultat.refus.get("TAILLE_ABSENTE", 0) + 1
            continue
        if prix is None or prix <= 0:
            resultat.refus["PRIX_ABSENT"] = resultat.refus.get("PRIX_ABSENT", 0) + 1
            continue
        if sens is None:
            resultat.refus["SENS_INCONNU"] = resultat.refus.get("SENS_INCONNU", 0) + 1
            continue

        etat = resultat.positions.setdefault((wallet, coin), EtatPosition())
        suivi = etat.quantite
        declare = _f(fill.get("start_pos") if "start_pos" in fill else fill.get("startPosition"))
        desync = None
        if utiliser_start_pos and declare is not None and abs(declare - suivi) > max(
                TOLERANCE_DESYNC, abs(declare) * 1e-6):
            desync = {"wallet": wallet, "coin": coin, "ts_ms": ts,
                      "position_declaree": declare, "position_suivie": round(suivi, 10),
                      "ecart": round(declare - suivi, 10)}
            resultat.desyncs.append(desync)
        avant = declare if (utiliser_start_pos and declare is not None) else suivi

        delta = sens * taille
        apres = avant + delta
        action = _classer(avant, apres)

        # prix moyen : recalculé seulement quand la position grossit dans le même sens
        if action in {"OPEN", "FLIP"}:
            etat.prix_moyen = prix
            etat.ouverte_depuis_ms = ts
        elif action == "ADD" and etat.prix_moyen is not None and abs(apres) > 0:
            etat.prix_moyen = (etat.prix_moyen * abs(avant) + prix * taille) / abs(apres)
        elif action == "CLOSE":
            etat.prix_moyen = None
            etat.ouverte_depuis_ms = None

        etat.quantite = apres
        etat.n_fills += 1

        twap_id = fill.get("twap_id") if "twap_id" in fill else fill.get("twapId")
        resultat.episodes.append({
            "wallet": wallet, "coin": coin, "action": action,
            "sens": sens, "taille": taille, "prix": prix, "ts_ms": ts,
            "position_avant": round(avant, 10), "position_apres": round(apres, 10),
            "prix_moyen_apres": (None if etat.prix_moyen is None else round(etat.prix_moyen, 10)),
            "notional_usd": round(taille * prix, 8),
            "oid": fill.get("oid"), "tid": fill.get("tid"),
            "twap_id": (None if twap_id in (None, "", 0, "0") else twap_id),
            "source_start_pos": bool(declare is not None),
            "desync": desync is not None,
            "real_execution": False,
        })
    return resultat


def episodes_par_wallet(reconstruction: Reconstruction) -> dict[str, list[dict[str, Any]]]:
    """Regroupe par wallet, chronologiquement — la forme attendue par le scoring point-in-time."""
    par_wallet: dict[str, list[dict[str, Any]]] = {}
    for e in reconstruction.episodes:
        par_wallet.setdefault(e["wallet"], []).append(e)
    return par_wallet


__all__ = ["SCHEMA_VERSION", "ACTIONS", "REFUS", "TOLERANCE_DESYNC", "EtatPosition", "Reconstruction",
           "cle_fill", "reconstruire", "episodes_par_wallet"]
